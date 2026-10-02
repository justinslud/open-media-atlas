"""One-time, bounded repair/enrichment for catalog works identified by Wikidata QID."""
import hashlib
import json
from urllib.parse import quote

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from catalog.importers.wikidata import WikidataClient, title_from_entity
from catalog.models import (ExternalIdentifier, ImportItem, ImportRun, ImportedWorkState,
    Source, SourceRecord, WorkSource)

IMPORTER_VERSION = "wikidata-title-enrichment-1"


class Command(BaseCommand):
    help = "Enrich existing Wikidata-identified works without overwriting editorial titles."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--after-id", type=int, default=0, help="Resume after this catalog work ID")
        parser.add_argument("--request-limit", type=int, default=500)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        wikidata, _ = Source.objects.get_or_create(title="Wikidata", defaults={
            "kind":"knowledge-base", "url":"https://www.wikidata.org/",
            "notes":"Supplier assertions require OMA review."})
        rows=list(ExternalIdentifier.objects.filter(scheme="wikidata",work_id__gt=options["after_id"])
                  .select_related("work").order_by("work_id")[:options["limit"]])
        run=ImportRun.objects.create(source=wikidata,requested_keys=[r.value for r in rows],
            importer_version=IMPORTER_VERSION,manifest={"after_work_id":options["after_id"],
            "limit":options["limit"],"database":"configured Django default database",
            "sources":["Wikidata entity statements/labels","exact Wikidata Wikipedia sitelink"]})
        self.stdout.write(f"database_vendor={connection.vendor} database_name={connection.settings_dict['NAME']} run_id={run.pk}")
        client=WikidataClient(timeout=options["timeout"],max_requests=options["request_limit"])
        stats={"attempted":len(rows),"updated":0,"preserved":0,"unresolved":0,"conflicted":0,"failures":0}
        try:
            entities=client.entities([r.value for r in rows])
            for identifier in rows:
                qid=identifier.value; work=identifier.work; entity=entities.get(qid,{})
                title,language,basis=title_from_entity(entity)
                status="unchanged"; message=""
                if not title:
                    status="failed"; message="No usable P1476 title or label; kept for later enrichment"
                    stats["unresolved"]+=1; stats["failures"]+=1
                else:
                    imdb=[]
                    for claim in entity.get("claims",{}).get("P345",[]):
                        value=claim.get("mainsnak",{}).get("datavalue",{}).get("value")
                        if isinstance(value,str): imdb.append(value)
                    conflict=ExternalIdentifier.objects.filter(scheme="imdb",value__in=imdb).exclude(work=work).first()
                    if conflict:
                        status="conflicted"; message=f"IMDb ID maps to catalog work {conflict.work_id}; merge requires review"; stats["conflicted"]+=1
                    else:
                        prior=SourceRecord.objects.filter(source=wikidata,external_key=qid).select_related("work_state").first()
                        prior_title=getattr(getattr(prior,"work_state",None),"imported_title",None)
                        machine_title=work.title.upper()==qid.upper() or (prior_title and work.title==prior_title)
                        if machine_title and work.title != title and not options["dry_run"]:
                            work.title=title[:300]; work.save(update_fields=("title","updated_at")); status="updated"; stats["updated"]+=1
                        else:
                            stats["preserved"]+=1
                            message="Editorial/current title preserved" if not machine_title else "Title already current"
                        if not options["dry_run"]:
                            raw=json.dumps(entity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
                            record,_=SourceRecord.objects.update_or_create(source=wikidata,external_key=qid,defaults={
                                "matched_work":work,"payload_hash":hashlib.sha256(raw).hexdigest(),"raw_payload":entity,"retrieved_at":timezone.now()})
                            ImportedWorkState.objects.update_or_create(source_record=record,defaults={
                                "imported_title":title[:300],"imported_date_text":"","imported_year":None})
                            for value in imdb: ExternalIdentifier.objects.get_or_create(work=work,scheme="imdb",value=value)
                            WorkSource.objects.get_or_create(work=work,source=wikidata,defaults={"note":f"Title {basis} ({language}); entity {qid}."})
                            try:
                                self._cite_wikipedia(entity,work,qid,language,client)
                            except Exception as exc:
                                # Wikipedia is supplemental. Keep the exact-ID
                                # Wikidata repair and make the partial fetch visible.
                                stats["failures"]+=1; status="failed"
                                message=f"Wikidata title stored; Wikipedia enrichment failed: {exc}"
                ImportItem.objects.create(run=run,external_key=qid,status=status,work=work,message=(message or f"Title from {basis}; language={language}"))
            run.status=ImportRun.Status.COMPLETED_WITH_ERRORS if stats["failures"] else ImportRun.Status.COMPLETED
        except Exception as exc:
            run.status=ImportRun.Status.FAILED; stats["error"]=str(exc); run.stats=stats; run.finished_at=timezone.now(); run.save()
            raise CommandError(str(exc)) from exc
        stats.update(network_requests=client.requests,last_work_id=rows[-1].work_id if rows else options["after_id"],dry_run=options["dry_run"])
        run.stats=stats; run.finished_at=timezone.now(); run.save(update_fields=("status","stats","finished_at"))
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id":run.pk,**stats},sort_keys=True)))

    def _cite_wikipedia(self, entity, work, qid, title_language, client):
        links=entity.get("sitelinks",{})
        preferred=f"{title_language}wiki"
        key=preferred if preferred in links else next((k for k in sorted(links) if k.endswith("wiki")),None)
        if not key: return
        language=key[:-4]; page=links[key].get("title","")
        if not page: return
        url=f"https://{language}.wikipedia.org/wiki/{quote(page.replace(' ','_'))}"
        api=f"https://{language}.wikipedia.org/w/api.php"
        response=client.get_json(api,{"action":"query","format":"json","formatversion":2,
            "prop":"extracts|info","exintro":1,"explaintext":1,"inprop":"url","titles":page,"maxlag":5})
        article=next(iter(response.get("query",{}).get("pages",[])),{})
        payload={"wikidata_id":qid,"language":language,"page_title":page,"url":url,
            "match":"exact Wikidata sitelink","article":article}
        source,_=Source.objects.get_or_create(title=f"Wikipedia: {page}"[:300],url=url,defaults={
            "kind":"encyclopedia","notes":f"Exact {qid} sitelink; supplemental metadata citation."})
        raw=json.dumps(payload,sort_keys=True).encode()
        SourceRecord.objects.update_or_create(source=source,external_key=f"{language}:{page}",defaults={
            "matched_work":work,"payload_hash":hashlib.sha256(raw).hexdigest(),"raw_payload":payload,"retrieved_at":timezone.now()})
        WorkSource.objects.get_or_create(work=work,source=source,defaults={"note":f"{url} — exact {qid} sitelink; supplemental citation."})
        extract=(article.get("extract") or "").strip()
        if extract and not work.description:
            work.description=extract[:1000]
            work.save(update_fields=("description","updated_at"))

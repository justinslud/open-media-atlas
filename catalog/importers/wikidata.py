"""Small, bounded Wikidata relationship enrichment (never called by web views)."""
import hashlib
import json
import random
import time
from datetime import datetime, timezone as dt_timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import (Agent, Credit, ExternalIdentifier, ImportItem,
    ImportRelationshipProposal, ImportedWorkState, RelationshipType, Source,
    SourceRecord, Version, Work, WorkSource, WorkType)

IMPORTER_VERSION = "wikidata-pilot-1"
ENTITY_API = "https://www.wikidata.org/w/api.php"
QUERY_SERVICE = "https://query.wikidata.org/sparql"
USER_AGENT = "OpenMediaAtlas/1.0 (https://github.com/open-media-atlas/open-media-atlas; wikidata-pilot)"
MAX_RELATED_HARD = 300


class WikidataError(Exception): pass


class WikidataClient:
    def __init__(self, *, timeout=30, max_requests=250, opener=urlopen, sleep=time.sleep):
        self.timeout, self.max_requests, self.opener, self.sleep = timeout, max_requests, opener, sleep
        self.requests = 0

    def get_json(self, url, params, attempts=4):
        if self.requests >= self.max_requests:
            raise WikidataError(f"request limit ({self.max_requests}) reached")
        for attempt in range(attempts):
            self.requests += 1
            request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                    raise WikidataError(f"HTTP {exc.code} from Wikidata") from exc
                retry = exc.headers.get("Retry-After")
                delay = min(30, float(retry)) if retry and retry.isdigit() else min(30, 2 ** attempt + random.random())
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == attempts - 1: raise WikidataError(f"Wikidata request failed: {exc}") from exc
                delay = min(30, 2 ** attempt + random.random())
            self.sleep(delay)

    def discover(self, seeds, limit):
        values = " ".join(f"wd:{qid}" for qid in seeds)
        query = f"""SELECT ?derived ?seed ?statement WHERE {{
          VALUES ?seed {{ {values} }}
          ?derived p:P144 ?statement. ?statement ps:P144 ?seed.
          FILTER NOT EXISTS {{ ?statement wikibase:rank wikibase:DeprecatedRank }}
        }} ORDER BY ?seed ?derived LIMIT {int(limit) + 1}"""
        data = self.get_json(QUERY_SERVICE, {"query": query, "format": "json"})
        return data.get("results", {}).get("bindings", [])

    def entities(self, ids):
        answer = {}
        for offset in range(0, len(ids), 50):
            data = self.get_json(ENTITY_API, {"action": "wbgetentities", "format": "json", "formatversion": 2,
                "ids": "|".join(ids[offset:offset + 50]), "props": "info|labels|aliases|descriptions|claims|sitelinks",
                "languages": "en", "languagefallback": 1, "maxlag": 5})
            answer.update(data.get("entities", {}))
        return answer


TYPE_MAP = {
    "Q7725634": ("literary-work", "Literary work", "text"), "Q571": ("book", "Book", "text"),
    "Q8261": ("novel", "Novel", "text"), "Q25379": ("play", "Play", "stage"),
    "Q11424": ("film", "Film", "screen"), "Q5398426": ("television-series", "Television series", "screen"),
    "Q15416": ("television-program", "Television program", "screen"), "Q7366": ("song", "Song", "audio"),
    "Q482994": ("album", "Album", "audio"), "Q7889": ("video-game", "Video game", "interactive"),
    "Q47461344": ("written-work", "Written work", "text"), "Q17537576": ("creative-work", "Creative work", "other"),
}

def claim_ids(entity, prop):
    values=[]
    for claim in entity.get("claims", {}).get(prop, []):
        value=claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item": values.append(value.get("id"))
    return [v for v in values if v]

def first_claim(entity, prop):
    claims=entity.get("claims", {}).get(prop, [])
    return claims[0].get("mainsnak", {}).get("datavalue", {}).get("value") if claims else None

def date_fields(entity):
    value=first_claim(entity, "P577") or first_claim(entity, "P571")
    if not isinstance(value, dict): return "", None, None
    raw=value.get("time", ""); precision=value.get("precision")
    year=int(raw[1:5]) if len(raw) >= 5 and raw[1:5].isdigit() else None
    text=str(year) if year else raw
    if precision and precision >= 11 and len(raw) >= 11: text=f"{raw[1:5]}-{raw[6:8]}-{raw[9:11]}"
    return text, year, precision

def _source():
    return Source.objects.get_or_create(title="Wikidata", defaults={"kind":"knowledge-base", "url":"https://www.wikidata.org/", "notes":"Supplier assertions require OMA review."})[0]

def stage_entity(entity, source, run, *, supporting_entities=None, existing_only=False):
    qid=entity["id"]
    exact=ExternalIdentifier.objects.filter(scheme="wikidata", value=qid).select_related("work").first()
    olids=[]
    for value in entity.get("claims", {}).get("P648", []):
        candidate=value.get("mainsnak",{}).get("datavalue",{}).get("value")
        if isinstance(candidate,str): olids.append(candidate.removeprefix("/works/"))
    olmatch=ExternalIdentifier.objects.filter(scheme="ol_work", value__in=olids).select_related("work").first()
    if exact and olmatch and exact.work_id != olmatch.work_id:
        return None, "conflicted", "Wikidata and Open Library identifiers point to different works"
    matched=(exact or olmatch).work if (exact or olmatch) else None
    title=entity.get("labels",{}).get("en",{}).get("value", qid)[:300]
    created = not matched
    if created:
        candidates=Work.objects.filter(title__iexact=title)
        if candidates.exists():
            return None, "conflicted", f"title-only candidate(s): {', '.join(str(x.pk) for x in candidates[:5])}; requires review"
        if existing_only: return None, "skipped", "seed is not currently in OMA"
        spec=next((TYPE_MAP[x] for x in claim_ids(entity,"P31") if x in TYPE_MAP), ("creative-work","Creative work","other"))
        work_type,_=WorkType.objects.get_or_create(code=spec[0], defaults={"label":spec[1],"medium":spec[2]})
        date,year,precision=date_fields(entity)
        matched=Work.objects.create(title=title, slug=slugify(f"{title}-{qid}"), work_type=work_type,
            description=entity.get("descriptions",{}).get("en",{}).get("value","")[:1000], first_publication_date_text=date,
            first_publication_year=year, visibility=Work.Visibility.DRAFT, depth="index")
        state_status="created"
    else:
        state_status="unchanged"  # supplier metadata never mutates an existing work in this pilot
        date,year,precision=date_fields(entity)
    raw=json.dumps(entity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    record,_=SourceRecord.objects.update_or_create(source=source,external_key=qid,defaults={"matched_work":matched,
        "payload_hash":hashlib.sha256(raw).hexdigest(),"raw_payload":entity,"retrieved_at":timezone.now()})
    ImportedWorkState.objects.update_or_create(source_record=record,defaults={"imported_title":title,"imported_date_text":date,"imported_year":year})
    ExternalIdentifier.objects.get_or_create(work=matched,scheme="wikidata",value=qid)
    for olid in olids: ExternalIdentifier.objects.get_or_create(work=matched,scheme="ol_work",value=olid)
    WorkSource.objects.get_or_create(work=matched,source=source,defaults={"note":f"Wikidata entity {qid}; staged supplier metadata."})
    supporting_entities=supporting_entities or {}
    languages=claim_ids(entity,"P364")
    if languages and created:
        language_entity=supporting_entities.get(languages[0],{})
        language=language_entity.get("labels",{}).get("en",{}).get("value",languages[0])
        Version.objects.get_or_create(work=matched,label="Original work",defaults={"kind":"original","language":language[:80]})
    if created:
        for prop,role in (("P50","author"),("P57","director")):
            for order,agent_id in enumerate(claim_ids(entity,prop)):
                agent_entity=supporting_entities.get(agent_id,{})
                name=agent_entity.get("labels",{}).get("en",{}).get("value")
                if name:
                    agent,_=Agent.objects.get_or_create(wikidata_id=agent_id,defaults={"name":name[:200],"kind":"person"})
                    Credit.objects.get_or_create(work=matched,agent=agent,role=role,defaults={"billing_order":order,"source":source})
    return matched,state_status,f"staged {qid}; date precision={precision}; aliases retained in source record"

def run_import(run, seeds, *, related_limit=300, client=None, dry_run=False):
    if not 1 <= related_limit <= MAX_RELATED_HARD: raise WikidataError("related limit must be between 1 and 300")
    client=client or WikidataClient(); source=run.source; started=time.monotonic()
    stats={"seeds_attempted":len(seeds),"matched_entities":0,"new_entities":0,"relationships_proposed":0,
           "ambiguous_matches":0,"failures":0,"skipped_statements":0,"network_requests":0,"truncated":False}
    cached={record.external_key:record.raw_payload for record in SourceRecord.objects.filter(source=source,external_key__in=seeds)}
    missing=[qid for qid in seeds if qid not in cached]
    seed_entities={**cached,**(client.entities(missing) if missing else {})}
    bindings=client.discover(seeds,related_limit)
    if len(bindings)>related_limit: stats["truncated"]=True; bindings=bindings[:related_limit]
    related=sorted({row["derived"]["value"].rsplit("/",1)[-1] for row in bindings})
    cached_related={record.external_key:record.raw_payload for record in SourceRecord.objects.filter(source=source,external_key__in=related)}
    missing_related=[qid for qid in related if qid not in cached_related]
    entities={**seed_entities,**cached_related,**(client.entities(missing_related) if missing_related else {})}
    support_ids=sorted({value for entity in entities.values() for prop in ("P50","P57","P364") for value in claim_ids(entity,prop)}-set(entities))
    supporting=client.entities(support_ids) if support_ids else {}
    if dry_run:
        stats.update(network_requests=client.requests,related_entities=len(related),relationships_discovered=len(bindings),elapsed_seconds=round(time.monotonic()-started,2),
                     coverage_limitations="P144 inbound statements only; no recursive traversal; dry run persisted only this ImportRun report and staged no catalog entities")
        return stats
    # Cache complete supplier responses before transforming them so a failed
    # ingestion rerun need only repeat the small discovery query.
    now=timezone.now()
    for qid,entity in entities.items():
        raw=json.dumps(entity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
        SourceRecord.objects.update_or_create(source=source,external_key=qid,defaults={"payload_hash":hashlib.sha256(raw).hexdigest(),
            "raw_payload":entity,"retrieved_at":now})
    works={}
    for qid in seeds+related:
        entity=entities.get(qid)
        if not entity or entity.get("missing"):
            stats["failures"]+=1; ImportItem.objects.update_or_create(run=run,external_key=qid,defaults={"status":"failed","message":"entity missing"}); continue
        work,status,message=stage_entity(entity,source,run,supporting_entities=supporting,existing_only=False)
        if work: works[qid]=work; stats["new_entities" if status=="created" else "matched_entities"]+=1
        if status=="conflicted": stats["ambiguous_matches"]+=1
        ImportItem.objects.update_or_create(run=run,external_key=qid,defaults={"status":status,"work":work,"message":message})
    reltype,_=RelationshipType.objects.update_or_create(code="based-on",defaults={"label":"Based on","inverse_label":"Inspired or adapted works","category":"derivation"})
    retrieved=timezone.now().isoformat()
    for row in bindings:
        derived=row["derived"]["value"].rsplit("/",1)[-1]; seed=row["seed"]["value"].rsplit("/",1)[-1]
        if derived not in works or seed not in works or derived==seed: stats["skipped_statements"]+=1; continue
        statement_uri=row.get("statement",{}).get("value",f"{derived}-P144-{seed}")
        claim=next((c for c in entities[derived].get("claims",{}).get("P144",[]) if c.get("id","").replace("$","-") in statement_uri or claim_ids({"claims":{"x":[c]}},"x")==[seed]),{})
        evidence={"asserted_by":"Wikidata","entity_id":derived,"property_id":"P144","statement_id":claim.get("id") or statement_uri.rsplit("/",1)[-1],
            "rank":claim.get("rank","normal"),"qualifiers":claim.get("qualifiers",{}),"references":claim.get("references",[]),
            "retrieved_at":retrieved,"revision_id":entities[derived].get("lastrevid"),"source_url":f"https://www.wikidata.org/wiki/{derived}"}
        ImportRelationshipProposal.objects.update_or_create(run=run,statement_id=evidence["statement_id"],defaults={"from_work":works[derived],"to_work":works[seed],
            "relationship_type":reltype,"source":source,"evidence":evidence})
        stats["relationships_proposed"]+=1
    stats.update(network_requests=client.requests,related_entities=len(related),elapsed_seconds=round(time.monotonic()-started,2),
        coverage_limitations="Only non-deprecated inbound P144 (based on) statements for the bounded seed set; results may be incomplete or truncated. No license or rights inference.")
    return stats

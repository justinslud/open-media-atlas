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
MAX_RELATED_HARD = 5000  # safety ceiling, not a coverage target
DEFAULT_RELATED_LIMIT = 1000


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
                # Do not filter labels to English: many valid works have no
                # English label, and their original/available title is still useful.
                "maxlag": 5})
            answer.update(data.get("entities", {}))
        return answer


TYPE_MAP = {
    "Q7725634": ("literary-work", "Literary work", "text"), "Q571": ("book", "Book", "text"),
    "Q8261": ("novel", "Novel", "text"), "Q25379": ("play", "Play", "stage"),
    "Q1344": ("opera", "Opera", "stage"), "Q2743": ("musical", "Musical", "stage"),
    "Q15079786": ("ballet", "Ballet", "stage"),
    "Q11424": ("film", "Film", "screen"), "Q5398426": ("television-series", "Television series", "screen"),
    "Q15416": ("television-program", "Television program", "screen"), "Q7366": ("song", "Song", "audio"),
    "Q482994": ("album", "Album", "audio"), "Q7889": ("video-game", "Video game", "interactive"),
    "Q47461344": ("written-work", "Written work", "text"), "Q17537576": ("creative-work", "Creative work", "other"),
    # Clear screen subclasses; do not map broad production/adaptation classes.
    "Q506240": ("film", "Film", "screen"),  # television film
    "Q202866": ("film", "Film", "screen"),  # animated film
    "Q17517379": ("film", "Film", "screen"),  # animated short film
    "Q24869": ("film", "Film", "screen"),  # feature film
    "Q24862": ("film", "Film", "screen"),  # short film
    "Q20650540": ("film", "Film", "screen"),  # anime film
    "Q117467246": ("television-series", "Television series", "screen"),  # animated television series
    "Q1259759": ("television-series", "Television series", "screen"),  # miniseries
    "Q63952888": ("television-series", "Television series", "screen"),  # anime television series
    "Q1261214": ("television-program", "Television program", "screen"),  # television special
    "Q3744532": ("television-program", "Television program", "screen"),  # fiction television program
    "Q21191270": ("television-program", "Television program", "screen"),  # television series episode
    "Q1194583": ("play", "Play", "stage"),  # one-act play
    "Q12799318": ("novel", "Novel", "text"),  # short novel
}
STAGE_TYPE_PRECEDENCE = {"opera": 0, "musical": 1, "ballet": 2, "play": 3}

def claim_ids(entity, prop):
    values=[]
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated": continue
        value=claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item": values.append(value.get("id"))
    return [v for v in values if v]

def first_claim(entity, prop):
    claims=entity.get("claims", {}).get(prop, [])
    return claims[0].get("mainsnak", {}).get("datavalue", {}).get("value") if claims else None

def title_from_entity(entity):
    """Return (title, language, basis), without inventing a translation."""
    titles=[]
    for claim in entity.get("claims",{}).get("P1476",[]):
        value=claim.get("mainsnak",{}).get("datavalue",{}).get("value")
        if isinstance(value,dict) and value.get("text"):
            titles.append((value["text"].strip(),value.get("language","") or "und","P1476"))
    for preferred in ("en","mul"):
        match=next((row for row in titles if row[1]==preferred),None)
        if match: return match
    # P1476 is the work's stated title. Prefer it over a label, which may be a
    # misspelling or a convenience translation.
    if titles: return titles[0]
    labels=entity.get("labels",{})
    for preferred in ("en","mul"):
        value=labels.get(preferred,{}).get("value","").strip()
        if value: return value,preferred,"label"
    # Prefer a language with a Wikipedia article, then deterministic label order.
    for site in sorted(entity.get("sitelinks",{})):
        if site.endswith("wiki"):
            language=site[:-4]
            value=labels.get(language,{}).get("value","").strip()
            if value: return value,language,"label"
    for language,data in sorted(labels.items()):
        value=data.get("value","").strip()
        if value: return value,language,"label"
    return "", "und", "unresolved"

def date_fields(entity):
    from catalog.dates import wikidata_date
    return wikidata_date(entity)[:3]

def _source():
    return Source.objects.get_or_create(title="Wikidata", defaults={"kind":"knowledge-base", "url":"https://www.wikidata.org/", "notes":"Supplier assertions require OMA review."})[0]


def work_type_spec(entity):
    supported = {TYPE_MAP[x] for prop in ("P31", "P7937") for x in claim_ids(entity, prop) if x in TYPE_MAP}
    specific = {spec for spec in supported if spec[0] not in {"book", "literary-work", "written-work", "creative-work"}}
    fallback = next((TYPE_MAP[q] for q in ("Q571", "Q7725634", "Q47461344") if TYPE_MAP[q] in supported), ("creative-work", "Creative work", "other"))
    if len(specific) == 1:
        return next(iter(specific))
    stage_specific = [row for row in specific if row[2] == "stage"]
    return min(stage_specific, key=lambda row: STAGE_TYPE_PRECEDENCE.get(row[0], 99)) if stage_specific else fallback


def stage_entity(entity, source, run, *, supporting_entities=None, existing_only=False, allow_title_collision=False, refresh_existing=False):
    qid=entity["id"]
    exact=ExternalIdentifier.objects.filter(scheme="wikidata", value=qid).select_related("work").first()
    olids=[]
    for value in entity.get("claims", {}).get("P648", []):
        candidate=value.get("mainsnak",{}).get("datavalue",{}).get("value")
        if isinstance(candidate,str): olids.append(candidate.removeprefix("/works/"))
    olmatch=ExternalIdentifier.objects.filter(scheme="ol_work", value__in=olids).select_related("work").first()
    imdbids=[]
    for claim in entity.get("claims",{}).get("P345",[]):
        candidate=claim.get("mainsnak",{}).get("datavalue",{}).get("value")
        if isinstance(candidate,str): imdbids.append(candidate)
    imdbmatch=ExternalIdentifier.objects.filter(scheme="imdb",value__in=imdbids).select_related("work").first()
    matches=[item for item in (exact,olmatch,imdbmatch) if item]
    if len({item.work_id for item in matches}) > 1:
        return None, "conflicted", "Wikidata, Open Library, or IMDb identifiers point to different works; merge requires review"
    matched=matches[0].work if matches else None
    resolved_title,title_language,title_basis=title_from_entity(entity)
    title=(resolved_title or qid)[:300]
    created = not matched
    spec=work_type_spec(entity)
    from catalog.dates import wikidata_date_for_medium
    date,year,precision,kind,evidence=wikidata_date_for_medium(entity,spec[2])
    if created:
        candidates=Work.objects.filter(title__iexact=title)
        if candidates.exists() and not allow_title_collision:
            return None, "conflicted", f"title-only candidate(s): {', '.join(str(x.pk) for x in candidates[:5])}; requires review"
        if existing_only: return None, "skipped", "seed is not currently in OMA"
        work_type,_=WorkType.objects.get_or_create(code=spec[0], defaults={"label":spec[1],"medium":spec[2]})
        matched=Work.objects.create(title=title, slug=slugify(f"{title}-{qid}"), work_type=work_type,
            description=entity.get("descriptions",{}).get("en",{}).get("value","")[:1000], first_publication_date_text=date,
            first_publication_year=year, date_kind=kind, date_evidence=evidence, visibility=Work.Visibility.DRAFT, depth="index")
        state_status="created"
    else:
        state_status="unchanged"  # supplier metadata never mutates an existing work in this pilot
        if refresh_existing and matched.visibility==Work.Visibility.DRAFT and matched.depth=="index":
            fields=[]
            if spec[0] not in {"creative-work", "other"} and matched.work_type.code in {"creative-work", "other"}:
                work_type,_=WorkType.objects.get_or_create(code=spec[0], defaults={"label":spec[1],"medium":spec[2]})
                matched.work_type=work_type; fields.append("work_type")
            current_property=(matched.date_evidence or {}).get("property")
            if date and year and current_property in {"P571", "P580", "P577", None, ""}:
                matched.first_publication_date_text=date; matched.first_publication_year=year
                matched.date_kind=kind; matched.date_evidence=evidence
                fields.extend(("first_publication_date_text", "first_publication_year", "date_kind", "date_evidence"))
            if title_basis=="P1476" and resolved_title and resolved_title != matched.title:
                matched.title=title; fields.append("title")
            if fields:
                matched.save(update_fields=tuple(dict.fromkeys(fields)) + ("updated_at",))
                state_status="updated"
        if state_status=="unchanged":
            date,year,precision=date_fields(entity)
    raw=json.dumps(entity,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    record,_=SourceRecord.objects.update_or_create(source=source,external_key=qid,defaults={"matched_work":matched,
        "payload_hash":hashlib.sha256(raw).hexdigest(),"raw_payload":entity,"retrieved_at":timezone.now()})
    ImportedWorkState.objects.update_or_create(source_record=record,defaults={"imported_title":title,"imported_date_text":date,"imported_year":year})
    from catalog.provenance import imported_fields
    imported_fields(matched, record, title=title, date=date, created=created, type_note="Importer maps stored P31/P7937 classifications to catalog types; conflicting specific classifications keep the generic fallback.")
    ExternalIdentifier.objects.get_or_create(work=matched,scheme="wikidata",value=qid)
    for olid in olids: ExternalIdentifier.objects.get_or_create(work=matched,scheme="ol_work",value=olid)
    for imdbid in imdbids: ExternalIdentifier.objects.get_or_create(work=matched,scheme="imdb",value=imdbid)
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
    return matched,state_status,f"staged {qid}; title={title_basis}:{title_language}; date precision={precision}; aliases retained in source record"

def bindings_from_candidate_claims(entities, seeds):
    """Build P144 bindings from an explicit candidate manifest.

    This is the bridge between a discovery step (SPARQL, Wikipedia pageprops,
    or an editor's candidate list) and the existing staging path. It still
    requires an exact non-deprecated P144 claim; it never infers from titles.
    """
    seed_set=set(seeds); rows=[]
    for qid,entity in entities.items():
        for claim in entity.get("claims",{}).get("P144",[]):
            if claim.get("rank")=="deprecated": continue
            value=claim.get("mainsnak",{}).get("datavalue",{}).get("value")
            if not isinstance(value,dict) or value.get("id") not in seed_set: continue
            statement_id=claim.get("id") or f"{qid}-P144-{value['id']}"
            rows.append({"derived":{"value":f"http://www.wikidata.org/entity/{qid}"},
                         "seed":{"value":f"http://www.wikidata.org/entity/{value['id']}"},
                         "statement":{"value":f"http://www.wikidata.org/entity/statement/{statement_id}"}})
    return rows


def claim_for_statement(entity, statement_uri, seed):
    statement_id=statement_uri.rsplit("/",1)[-1]
    for claim in entity.get("claims",{}).get("P144",[]):
        claim_id=claim.get("id","")
        if claim_id==statement_id or claim_id.replace("$","-")==statement_id:
            return claim
    return next((claim for claim in entity.get("claims",{}).get("P144",[])
                 if claim_ids({"claims":{"x":[claim]}},"x")==[seed]), {})


def run_import(run, seeds, *, related_limit=DEFAULT_RELATED_LIMIT, client=None, dry_run=False, candidate_qids=None):
    if not 1 <= related_limit <= MAX_RELATED_HARD:
        raise WikidataError(f"related limit must be between 1 and {MAX_RELATED_HARD}")
    client=client or WikidataClient(); source=run.source; started=time.monotonic()
    candidate_set=set(candidate_qids or [])
    stats={"seeds_attempted":len(seeds),"matched_entities":0,"new_entities":0,"relationships_proposed":0,
           "relationships_already_proposed":0,"ambiguous_matches":0,"failures":0,"skipped_statements":0,
           "network_requests":0,"truncated":False}
    cached={record.external_key:record.raw_payload for record in SourceRecord.objects.filter(source=source,external_key__in=seeds)}
    missing=[qid for qid in seeds if qid not in cached]
    seed_entities={**cached,**(client.entities(missing) if missing else {})}
    prefetched={}
    if candidate_qids is None:
        bindings=client.discover(seeds,related_limit)
        if len(bindings)>related_limit: stats["truncated"]=True; bindings=bindings[:related_limit]
        related=sorted({row["derived"]["value"].rsplit("/",1)[-1] for row in bindings})
        stats["discovery_mode"]="p144-discovery"
    else:
        candidates=sorted(set(candidate_qids))
        if not candidates: raise WikidataError("candidate list is empty")
        if len(candidates)>related_limit:
            raise WikidataError(f"candidate count {len(candidates)} exceeds related limit {related_limit}")
        cached_candidates={record.external_key:record.raw_payload for record in SourceRecord.objects.filter(source=source,external_key__in=candidates)}
        missing_candidates=[qid for qid in candidates if qid not in cached_candidates]
        candidate_entities={**cached_candidates,**(client.entities(missing_candidates) if missing_candidates else {})}
        prefetched={**candidate_entities}
        bindings=bindings_from_candidate_claims(candidate_entities,seeds)
        related=sorted({row["derived"]["value"].rsplit("/",1)[-1] for row in bindings})
        stats["discovery_mode"]="candidate-manifest"
        stats["candidates_unmatched"]=sorted(set(candidates)-set(related))
        stats["seeds_attempted"]=len(seeds)
        seed_entities={**seed_entities,**{k:v for k,v in candidate_entities.items() if k in seeds}}
    cached_related={record.external_key:record.raw_payload for record in SourceRecord.objects.filter(source=source,external_key__in=related)}
    known_entities={**seed_entities,**cached_related,**prefetched}
    missing_related=[qid for qid in related if qid not in known_entities]
    entities={**known_entities,**(client.entities(missing_related) if missing_related else {})}
    support_ids=sorted({value for entity in entities.values() for prop in ("P50","P57","P364") for value in claim_ids(entity,prop)}-set(entities))
    supporting=client.entities(support_ids) if support_ids else {}
    if dry_run:
        stats.update(network_requests=client.requests,related_entities=len(related),relationships_discovered=len(bindings),elapsed_seconds=round(time.monotonic()-started,2),
                     coverage_limitations="Bounded candidate or P144 inbound statements only; no recursive traversal; dry run persisted only this ImportRun report and staged no catalog entities")
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
        work,status,message=stage_entity(entity,source,run,supporting_entities=supporting,existing_only=False,
            allow_title_collision=qid in candidate_set,refresh_existing=qid in candidate_set)
        if work: works[qid]=work; stats["new_entities" if status=="created" else "matched_entities"]+=1
        if status=="conflicted": stats["ambiguous_matches"]+=1
        ImportItem.objects.update_or_create(run=run,external_key=qid,defaults={"status":status,"work":work,"message":message})
    for qid in stats.get("candidates_unmatched",[]):
        ImportItem.objects.update_or_create(run=run,external_key=qid,defaults={"status":"failed","message":"no non-deprecated P144 claim to a selected seed"})
    reltype,_=RelationshipType.objects.update_or_create(code="based-on",defaults={"label":"Based on","inverse_label":"Works based on this","category":"derivation"})
    retrieved=timezone.now().isoformat()
    for row in bindings:
        derived=row["derived"]["value"].rsplit("/",1)[-1]; seed=row["seed"]["value"].rsplit("/",1)[-1]
        if derived not in works or seed not in works or derived==seed: stats["skipped_statements"]+=1; continue
        statement_uri=row.get("statement",{}).get("value",f"{derived}-P144-{seed}")
        claim=claim_for_statement(entities[derived],statement_uri,seed)
        evidence={"asserted_by":"Wikidata","entity_id":derived,"property_id":"P144","statement_id":claim.get("id") or statement_uri.rsplit("/",1)[-1],
            "rank":claim.get("rank","normal"),"qualifiers":claim.get("qualifiers",{}),"references":claim.get("references",[]),
            "retrieved_at":retrieved,"revision_id":entities[derived].get("lastrevid"),"source_url":f"https://www.wikidata.org/wiki/{derived}"}
        duplicate=ImportRelationshipProposal.objects.filter(statement_id=evidence["statement_id"],from_work=works[derived],
            to_work=works[seed],relationship_type=reltype,
            status__in=(ImportRelationshipProposal.Status.PENDING,ImportRelationshipProposal.Status.APPROVED)).exclude(run=run).exists()
        if duplicate:
            stats["relationships_already_proposed"]+=1
            continue
        ImportRelationshipProposal.objects.update_or_create(run=run,statement_id=evidence["statement_id"],defaults={"from_work":works[derived],"to_work":works[seed],
            "relationship_type":reltype,"source":source,"evidence":evidence})
        stats["relationships_proposed"]+=1
    stats.update(network_requests=client.requests,related_entities=len(related),elapsed_seconds=round(time.monotonic()-started,2),
        coverage_limitations="Only non-deprecated P144 (based on) statements for the bounded seed set or explicit candidate list; results may be incomplete. No license or rights inference.")
    return stats

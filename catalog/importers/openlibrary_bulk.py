"""Bounded, restartable Open Library dump extraction and staged ingestion."""
import gzip
import hashlib
import heapq
import json
import resource
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

from django.db import connection
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import (Agent, Credit, ExternalIdentifier, ImportedWorkState,
    Release, Source, SourceRecord, Version, Work, WorkSource, WorkType)

IMPORTER_VERSION = "ol-bulk-2"
ENGLISH_KEYS = {"/languages/eng", "eng"}

class BulkImportError(Exception): pass

def _sha(value): return hashlib.sha256(value).hexdigest()

def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk)
    return digest.hexdigest()

def _open(path):
    return gzip.open(path, "rb") if str(path).endswith(".gz") else open(path, "rb")

class _HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digests = {"sha1": hashlib.sha1(), "sha256": hashlib.sha256()}
    def read(self, size=-1):
        data = self.stream.read(size)
        for digest in self.digests.values(): digest.update(data)
        return data
    def close(self):
        self.stream.close()

@contextmanager
def open_source(source, checksum=""):
    """Open a local dump or stream a remote gzip dump without materialising it."""
    value = str(source)
    if value.startswith(("https://", "http://")):
        response = urlopen(Request(value, headers={"User-Agent": "OpenMediaAtlas/ol-bulk-2"}), timeout=60)
        hashed = _HashingReader(response)
        stream = gzip.GzipFile(fileobj=hashed) if value.endswith(".gz") else hashed
        try:
            yield stream
        finally:
            stream.close()
            response.close()
        algorithm = "sha1" if len(checksum) == 40 else "sha256"
        if checksum and hashed.digests[algorithm].hexdigest().lower() != checksum.lower():
            raise BulkImportError(f"{algorithm.upper()} checksum mismatch for {value}")
    else:
        with _open(source) as stream:
            yield stream

def _payload(line, expected_type):
    try:
        parts = line.rstrip(b"\r\n").split(b"\t", 4)
        if len(parts) != 5 or parts[0].decode() != expected_type:
            raise ValueError("wrong dump type or column count")
        return json.loads(parts[4]), len(line)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BulkImportError(f"Malformed {expected_type} dump row: {exc}") from exc

def validate_file(path, expected_type):
    if not str(path).startswith(("https://", "http://")):
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0: raise BulkImportError(f"Empty or missing input: {path}")
    with open_source(path) as stream:
        line = stream.readline()
        if not line: raise BulkImportError(f"Empty compressed input: {path}")
        _payload(line, expected_type)

def download(url, destination, checksum=None):
    """Stream a remote dump to a partial file, optionally enforcing sha256."""
    destination = Path(destination); partial = destination.with_suffix(destination.suffix + ".partial")
    digest = hashlib.sha256(); size = 0
    request = Request(url, headers={"User-Agent": "OpenMediaAtlas/ol-bulk-1"})
    with urlopen(request, timeout=60) as response, partial.open("wb") as target:
        expected = response.headers.get("Content-Length")
        while chunk := response.read(1024 * 1024): target.write(chunk); digest.update(chunk); size += len(chunk)
    if not size or (expected and size != int(expected)): partial.unlink(missing_ok=True); raise BulkImportError("Remote download was empty or truncated")
    if checksum and digest.hexdigest().lower() != checksum.lower(): partial.unlink(missing_ok=True); raise BulkImportError("SHA-256 checksum mismatch")
    partial.replace(destination)
    return {"bytes": size, "sha256": digest.hexdigest()}

def _refs(values, prefix):
    result=[]
    for value in values or []:
        key = value.get("key", "") if isinstance(value, dict) else ""
        if key.startswith(prefix): result.append(key.removeprefix(prefix))
    return result

def extract(*, editions, works, authors, output, limit=5000, editions_per_work=2,
            seed="oma-ol-pilot-v1", max_runtime=0, snapshot_date="", urls=None, checksums=None, progress=None):
    """Select by stable hash of work ID; edition dump is intentionally scanned twice."""
    if not 1 <= limit <= 5000: raise BulkImportError("limit must be between 1 and 5000")
    if not 1 <= editions_per_work <= 10: raise BulkImportError("editions_per_work must be between 1 and 10")
    for path, kind in ((editions,"/type/edition"),(works,"/type/work"),(authors,"/type/author")): validate_file(path, kind)
    output=Path(output); output.mkdir(parents=True, exist_ok=True)
    free=shutil.disk_usage(output).free
    input_bytes=sum(Path(p).stat().st_size for p in (editions,works,authors)
                    if not str(p).startswith(("https://", "http://")))
    # Output is small, but extraction must coexist with supplied dumps.
    if free < 100 * 1024 * 1024: raise BulkImportError("Less than 100 MiB temporary storage is available")
    started=time.monotonic(); stats={"bytes_scanned":0,"records_scanned":0,"malformed":0,"eligible_editions":0,"works_selected":0}
    heap=[]; in_heap=set()
    def expired(): return max_runtime and time.monotonic()-started >= max_runtime
    with open_source(editions, (checksums or {}).get("editions", "")) as stream:
        for line in stream:
            stats["bytes_scanned"]+=len(line); stats["records_scanned"]+=1
            try: row,_=_payload(line,"/type/edition")
            except BulkImportError: stats["malformed"]+=1; continue
            langs=set(_refs(row.get("languages"), "/languages/"))
            if "eng" not in langs: continue
            for wid in set(_refs(row.get("works"), "/works/")):
                stats["eligible_editions"]+=1
                if wid in in_heap: continue
                rank=int.from_bytes(hashlib.sha256(f"{seed}:{wid}".encode()).digest(),"big")
                item=(-rank,wid)
                if len(heap)<limit: heapq.heappush(heap,item); in_heap.add(wid)
                elif item>heap[0]:
                    removed=heapq.heapreplace(heap,item); in_heap.discard(removed[1]); in_heap.add(wid)
            if progress and stats["records_scanned"] % 100000 == 0: progress("select_editions", stats)
            if expired(): raise BulkImportError("Maximum runtime reached during non-resumable selection scan")
    selected={wid for _,wid in heap}; stats["works_selected"]=len(selected)
    edition_rows={wid:[] for wid in selected}
    with open_source(editions, (checksums or {}).get("editions", "")) as stream:
        for line in stream:
            stats["bytes_scanned"]+=len(line); stats["records_scanned"]+=1
            try: row,_=_payload(line,"/type/edition")
            except BulkImportError: continue
            if "eng" not in set(_refs(row.get("languages"), "/languages/")): continue
            for wid in set(_refs(row.get("works"), "/works/")) & selected:
                if len(edition_rows[wid])<editions_per_work: edition_rows[wid].append(row)
            if progress and stats["records_scanned"] % 100000 == 0: progress("collect_editions", stats)
            if expired(): raise BulkImportError("Maximum runtime reached during edition collection scan")
    work_rows={}; author_ids=set()
    with open_source(works, (checksums or {}).get("works", "")) as stream:
        for line in stream:
            stats["bytes_scanned"]+=len(line); stats["records_scanned"]+=1
            try: row,_=_payload(line,"/type/work")
            except BulkImportError: continue
            wid=str(row.get("key","")).removeprefix("/works/")
            if wid in selected:
                work_rows[wid]=row
                for entry in row.get("authors") or []:
                    ref=entry.get("author",entry) if isinstance(entry,dict) else {}
                    key=ref.get("key","") if isinstance(ref,dict) else ""
                    if key.startswith("/authors/"): author_ids.add(key.removeprefix("/authors/"))
            if progress and stats["records_scanned"] % 100000 == 0: progress("scan_works", stats)
            if expired(): raise BulkImportError("Maximum runtime reached during works scan")
    author_rows={}
    with open_source(authors, (checksums or {}).get("authors", "")) as stream:
        for line in stream:
            stats["bytes_scanned"]+=len(line); stats["records_scanned"]+=1
            try: row,_=_payload(line,"/type/author")
            except BulkImportError: continue
            aid=str(row.get("key","")).removeprefix("/authors/")
            if aid in author_ids: author_rows[aid]=row
            if progress and stats["records_scanned"] % 100000 == 0: progress("scan_authors", stats)
            if expired(): raise BulkImportError("Maximum runtime reached during authors scan")
    records=output/"records.jsonl"; tmp=output/"records.jsonl.partial"; written=0
    with tmp.open("w",encoding="utf-8") as target:
        for wid in sorted(selected, key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).digest()):
            work=work_rows.get(wid)
            if not work or not (work.get("title") or "").strip(): stats["malformed"]+=1; continue
            aids=[]
            for entry in work.get("authors") or []:
                ref=entry.get("author",entry) if isinstance(entry,dict) else {}; aid=str(ref.get("key","")).removeprefix("/authors/")
                if aid in author_rows: aids.append(aid)
            target.write(json.dumps({"work":work,"editions":edition_rows[wid],"authors":{a:author_rows[a] for a in aids}},sort_keys=True)+"\n"); written+=1
    tmp.replace(records)
    artifact_sha=file_sha256(records); elapsed=time.monotonic()-started
    manifest={"format":"oma-openlibrary-extract-v1","importer_version":IMPORTER_VERSION,"snapshot_date":snapshot_date,
      "sources":urls or {},"checksums":checksums or {},"selection":{"limit":limit,"editions_per_work":editions_per_work,"seed":seed,"method":"lowest SHA-256(seed:work_id) among works referenced by an English-language edition"},
      "artifact":{"path":"records.jsonl","sha256":artifact_sha,"records":written},"stats":stats,"elapsed_seconds":round(elapsed,3),"input_compressed_bytes":input_bytes,"free_bytes_before":free}
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    (output/"extraction-report.json").write_text(json.dumps({**stats,"elapsed_seconds":round(elapsed,3),"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},indent=2)+"\n")
    return manifest

def validate_extract(directory):
    directory=Path(directory); manifest=json.loads((directory/"manifest.json").read_text()); records=directory/manifest["artifact"]["path"]
    if manifest.get("format")!="oma-openlibrary-extract-v1" or manifest.get("importer_version")!=IMPORTER_VERSION: raise BulkImportError("Incompatible extract manifest")
    if not records.is_file() or not records.stat().st_size or file_sha256(records)!=manifest["artifact"]["sha256"]: raise BulkImportError("Extract is empty, truncated, or checksum-mismatched")
    count=0
    with records.open() as stream:
        for line in stream:
            row=json.loads(line); wid=str(row["work"].get("key","")).removeprefix("/works/")
            if not wid or not row["editions"]: raise BulkImportError("Extract record lacks work ID or eligible edition")
            count+=1
    if count!=manifest["artifact"]["records"]: raise BulkImportError("Extract record count mismatch")
    return manifest,records

def db_size():
    if connection.vendor!="postgresql": return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        return cursor.fetchone()[0]

def ingest_record(row, source):
    work_data=row["work"]; wid=str(work_data["key"]).removeprefix("/works/"); title=(work_data.get("title") or "").strip()
    raw=json.dumps(row,sort_keys=True,separators=(",",":")); digest=_sha(raw.encode()); now=timezone.now()
    record=SourceRecord.objects.filter(source=source,external_key=wid).select_related("matched_work").first()
    if record and record.payload_hash==digest: return "unchanged",record.matched_work,"Source payload unchanged"
    identifiers=ExternalIdentifier.objects.filter(scheme="ol_work",value=wid).select_related("work")
    if identifiers.values("work_id").distinct().count()>1: return "conflicted",None,"Open Library ID ambiguously maps to multiple catalog works"
    identifier=identifiers.first()
    if identifier and record and identifier.work_id!=record.matched_work_id: return "conflicted",None,"Open Library ID maps to different catalog records"
    work=(record.matched_work if record else None) or (identifier.work if identifier else None)
    if work and work.visibility==Work.Visibility.PUBLIC:
        return "conflicted",work,"Public record was not mutated; review source changes manually"
    created=work is None
    from catalog.dates import openlibrary_date
    date, year = openlibrary_date(work_data)
    book,_=WorkType.objects.get_or_create(code="book",defaults={"label":"Book","medium":"text"})
    if created:
        work=Work.objects.create(title=title,slug=f"{slugify(title)}-{wid.lower()}",work_type=book,first_publication_date_text=date,first_publication_year=year,date_kind="publication",date_evidence={"date_text":date,"property":"first_publish_date","source_url":f"https://openlibrary.org/works/{wid}"},completion_status="released",visibility=Work.Visibility.DRAFT,depth="index")
    record,_=SourceRecord.objects.update_or_create(source=source,external_key=wid,defaults={"matched_work":work,"payload_hash":digest,"raw_payload":row,"retrieved_at":now})
    state=ImportedWorkState.objects.filter(source_record=record).first(); changed=[]
    if not created:
        preserve_date = (work.date_kind in {"first_publication", "first_release"} or work.depth == "editorial"
            or work.contribution_revisions.filter(field_name="first_publication_date_text").exists()
            or (state is not None and (work.first_publication_date_text not in ("", state.imported_date_text)
                                      or work.first_publication_year not in (None, state.imported_year))))
        for field,value,old in (("title",title,state.imported_title if state else None),("first_publication_date_text",date,state.imported_date_text if state else None),("first_publication_year",year,state.imported_year if state else None)):
            if field.startswith("first_publication") and preserve_date: continue
            current=getattr(work,field)
            if value not in (None,"") and current in (None,"",old) and current!=value: setattr(work,field,value); changed.append(field)
        if "first_publication_date_text" in changed and work.date_kind not in {"first_publication", "first_release"}:
            work.date_kind = "publication"
            work.date_evidence = {"date_text":date,"property":"first_publish_date","source_url":f"https://openlibrary.org/works/{wid}"}
            changed.extend(("date_kind", "date_evidence"))
        if changed: work.save(update_fields=changed+["updated_at"])
    ImportedWorkState.objects.update_or_create(source_record=record,defaults={"imported_title":title,"imported_date_text":date,"imported_year":year})
    from catalog.provenance import imported_fields
    imported_fields(work, record, title=title, date=date, created=created, changed=changed, type_note="Importer assigns Book to Open Library works; this is a process classification.")
    ExternalIdentifier.objects.get_or_create(work=work,scheme="ol_work",value=wid); WorkSource.objects.get_or_create(work=work,source=source,defaults={"note":f"Open Library dump work {wid}; snapshot {now.date()}."})
    author_map=row.get("authors",{})
    for order,entry in enumerate(work_data.get("authors") or []):
        ref=entry.get("author",entry) if isinstance(entry,dict) else {}; aid=str(ref.get("key","")).removeprefix("/authors/"); data=author_map.get(aid,{})
        name=(data.get("name") or "").strip()
        if name:
            # A later supplier spelling must not overwrite an editorial agent name.
            agent,_=Agent.objects.get_or_create(openlibrary_key=aid,defaults={"name":name,"kind":"person"})
            Credit.objects.update_or_create(work=work,agent=agent,role="author",defaults={"billing_order":order,"credited_as":aid,"source":source})
    version,_=Version.objects.get_or_create(work=work,label="English-language editions",defaults={"kind":"unresolved","language":"English"})
    for edition in row.get("editions",[]):
        eid=str(edition.get("key","")).removeprefix("/books/")
        if not eid: continue
        label=f"Open Library edition {eid}"
        Release.objects.get_or_create(openlibrary_key=eid,defaults={"version":version,"edition_name":label,"title":edition.get("title") or title,"format":", ".join(edition.get("physical_format",[]) if isinstance(edition.get("physical_format"),list) else [str(edition.get("physical_format") or "")]).strip(", "),"publication_date_text":str(edition.get("publish_date") or ""),"publisher_statement":"; ".join(edition.get("publishers") or [])[:200],"pages":edition.get("number_of_pages") if isinstance(edition.get("number_of_pages"),int) and edition["number_of_pages"]>0 else None})
    return ("created" if created else "updated"),work,(", ".join(changed) or "Staged source children")

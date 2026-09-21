import hashlib
import json
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import (Agent, Credit, ExternalIdentifier, ImportedWorkState,
    Source, SourceRecord, Work, WorkSource, WorkType)

BASE_URL = "https://openlibrary.org"
USER_AGENT = "OpenMediaAtlas/0.2 (targeted catalog importer)"
WORK_ID = re.compile(r"^OL\d+W$")


class ImportFailure(Exception):
    pass


@dataclass
class ImportResult:
    status: str
    work: Work | None
    message: str = ""


class OpenLibraryImporter:
    def __init__(self, *, retries=3, delay=0.25, opener=urlopen, sleeper=time.sleep):
        self.retries = retries
        self.delay = delay
        self.opener = opener
        self.sleeper = sleeper
        self._last_request_at = None
        self.source, _ = Source.objects.get_or_create(
            title="Open Library",
            defaults={"kind": "dataset", "url": "https://openlibrary.org/", "notes": "Targeted Open Library API metadata."},
        )

    @staticmethod
    def normalize_id(value):
        value = value.strip().removeprefix("/works/").removesuffix(".json")
        if not WORK_ID.fullmatch(value):
            raise ImportFailure(f"Invalid Open Library work ID: {value}")
        return value

    def fetch_json(self, path):
        if self.delay and self._last_request_at is not None:
            remaining = self.delay - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
        request = Request(f"{BASE_URL}{path}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(self.retries + 1):
            try:
                with self.opener(request, timeout=20) as response:
                    payload = json.load(response)
                    self._last_request_at = time.monotonic()
                    return payload
            except HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self.retries:
                    raise ImportFailure(f"HTTP {error.code} for {path}") from error
            except (URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == self.retries:
                    raise ImportFailure(f"Request failed for {path}: {error}") from error
            self.sleeper(self.delay * (2**attempt))
        raise ImportFailure(f"Request failed for {path}")

    def preview(self, external_id):
        external_id = self.normalize_id(external_id)
        payload = self.fetch_json(f"/works/{external_id}.json")
        return {"id": external_id, "title": payload.get("title"), "first_publish_date": payload.get("first_publish_date")}

    @transaction.atomic
    def import_work(self, external_id):
        external_id = self.normalize_id(external_id)
        payload = self.fetch_json(f"/works/{external_id}.json")
        title = (payload.get("title") or "").strip()
        if not title:
            raise ImportFailure("Open Library record has no usable title")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        retrieved_at = timezone.now()
        existing_record = SourceRecord.objects.filter(source=self.source, external_key=external_id).select_related("matched_work").first()
        if existing_record and existing_record.payload_hash == digest:
            existing_record.retrieved_at = retrieved_at
            existing_record.save(update_fields=("retrieved_at",))
            return ImportResult("skipped", existing_record.matched_work, "Source payload unchanged")

        date_text = str(payload.get("first_publish_date") or "").strip()
        year_match = re.search(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", date_text)
        year = int(year_match.group(1)) if year_match else None
        work = existing_record.matched_work if existing_record else None
        created = work is None
        if created:
            book_type, _ = WorkType.objects.get_or_create(code="book", defaults={"label": "Book", "medium": "text"})
            work = Work.objects.create(title=title, slug=f"{slugify(title)}-{external_id.lower()}", work_type=book_type,
                first_publication_date_text=date_text, first_publication_year=year,
                completion_status="released", visibility=Work.Visibility.PUBLIC, depth="index", is_demo=False)

        record, _ = SourceRecord.objects.update_or_create(source=self.source, external_key=external_id, defaults={
            "matched_work": work, "payload_hash": digest, "raw_payload": payload, "retrieved_at": retrieved_at,
        })
        previous = ImportedWorkState.objects.filter(source_record=record).first()
        changed = []
        if not created:
            for field, new_value, old_imported in (
                ("title", title, previous.imported_title if previous else None),
                ("first_publication_date_text", date_text, previous.imported_date_text if previous else None),
                ("first_publication_year", year, previous.imported_year if previous else None),
            ):
                current = getattr(work, field)
                if current in (None, "") or current == old_imported:
                    if current != new_value:
                        setattr(work, field, new_value)
                        changed.append(field)
            if changed:
                work.save(update_fields=changed + ["updated_at"])
        ImportedWorkState.objects.update_or_create(source_record=record, defaults={
            "imported_title": title, "imported_date_text": date_text, "imported_year": year,
        })
        ExternalIdentifier.objects.get_or_create(work=work, scheme="ol_work", value=external_id)
        WorkSource.objects.update_or_create(work=work, source=self.source, defaults={
            "note": f"Open Library work {external_id}; retrieved {retrieved_at.date().isoformat()}."
        })
        self._import_authors(work, payload.get("authors") or [])
        return ImportResult("created" if created else "updated", work, ", ".join(changed) or "Source snapshot updated")

    def _import_authors(self, work, author_refs):
        for order, entry in enumerate(author_refs):
            key = (entry.get("author") or entry).get("key", "") if isinstance(entry, dict) else ""
            author_id = key.removeprefix("/authors/")
            if not author_id:
                continue
            data = self.fetch_json(f"/authors/{author_id}.json")
            name = (data.get("name") or "").strip()
            if not name:
                continue
            agent, _ = Agent.objects.get_or_create(name=name, kind="person")
            Credit.objects.update_or_create(work=work, agent=agent, role="author", defaults={"billing_order": order, "source": self.source})

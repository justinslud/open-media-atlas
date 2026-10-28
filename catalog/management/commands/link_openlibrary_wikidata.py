"""Link local Open Library drafts to Wikidata by exact P648 ID.

This is an identity join only. It never matches by title. Matched entities are
staged through the existing Wikidata staging path so dates/types can refresh
for draft records without mutating public editorial records.
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import IMPORTER_VERSION, WikidataClient, WikidataError, stage_entity
from catalog.models import (
    ExternalIdentifier,
    ImportItem,
    ImportRun,
    Source,
    SourceRecord,
    Work,
)


QUERY_SERVICE = "https://query.wikidata.org/sparql"


class Command(BaseCommand):
    help = "Link Open Library drafts to Wikidata using exact P648 IDs."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", type=int, help="Open Library import run ID")
        parser.add_argument("--extract", type=Path, help="Extract directory; reads records.jsonl")
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        if not options["run_id"] and not options["extract"]:
            raise CommandError("provide --run-id or --extract")

        ol_ids = []
        if options["run_id"]:
            try:
                run = ImportRun.objects.get(pk=options["run_id"])
            except ImportRun.DoesNotExist as exc:
                raise CommandError("import run not found") from exc
            ol_ids = list(run.items.values_list("external_key", flat=True))
        else:
            records = options["extract"] / "records.jsonl"
            if not records.is_file():
                raise CommandError(f"missing {records}")
            with records.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    wid = str(row["work"].get("key", "")).removeprefix("/works/")
                    if wid:
                        ol_ids.append(wid)
        ol_ids = list(dict.fromkeys(ol_ids))[: options["limit"]]
        if not ol_ids:
            raise CommandError("no Open Library IDs found")

        source = Source.objects.get_or_create(
            title="Wikidata",
            defaults={"kind": "knowledge-base", "url": "https://www.wikidata.org/", "notes": "Supplier assertions require OMA review."},
        )[0]
        run = ImportRun.objects.create(
            source=source,
            requested_keys=ol_ids,
            importer_version=IMPORTER_VERSION,
            manifest={"command": "link_openlibrary_wikidata", "ol_count": len(ol_ids)},
        )
        client = WikidataClient(timeout=options["timeout"], max_requests=50)
        started = time.monotonic()
        stats = {"ol_ids": len(ol_ids), "wikidata_matches": 0, "works_linked": 0, "works_refreshed": 0, "failures": 0, "network_requests": 0}

        # Exact P648 join. No title matching. Chunk values to avoid HTTP 414.
        matches = {}
        try:
            for offset in range(0, len(ol_ids), 100):
                chunk = ol_ids[offset:offset + 100]
                values = " ".join(f'"{value}"' for value in chunk)
                query = f"""SELECT ?item ?ol WHERE {{
                  VALUES ?ol {{ {values} }}
                  ?item wdt:P648 ?ol.
                }}"""
                data = client.get_json(
                    QUERY_SERVICE,
                    {"query": query, "format": "json"},
                    attempts=4,
                )
                for binding in data.get("results", {}).get("bindings", []):
                    qid = binding["item"]["value"].rsplit("/", 1)[-1]
                    olid = binding["ol"]["value"]
                    matches[olid] = qid
        except Exception as exc:
            run.status = ImportRun.Status.FAILED
            run.stats = {"error": str(exc)}
            run.finished_at = timezone.now()
            run.save(update_fields=("status", "stats", "finished_at"))
            raise CommandError(f"Wikidata P648 query failed: {exc}") from exc

        stats["wikidata_matches"] = len(matches)
        entities = client.entities(sorted(set(matches.values()))) if matches else {}

        for olid, qid in matches.items():
            identifier = ExternalIdentifier.objects.filter(scheme="ol_work", value=olid).select_related("work").first()
            if not identifier:
                stats["failures"] += 1
                ImportItem.objects.update_or_create(run=run, external_key=olid, defaults={"status": "failed", "message": "no local work for OL ID"})
                continue
            work = identifier.work
            entity = entities.get(qid)
            if not entity or entity.get("missing"):
                stats["failures"] += 1
                ImportItem.objects.update_or_create(run=run, external_key=olid, defaults={"status": "failed", "message": f"Wikidata entity {qid} missing"})
                continue
            if options["dry_run"]:
                stats["works_linked"] += 1
                continue
            staged, status, message = stage_entity(
                entity,
                source,
                run,
                existing_only=True,
                allow_title_collision=False,
                refresh_existing=True,
            )
            if staged:
                stats["works_linked"] += 1
                if status == "updated":
                    stats["works_refreshed"] += 1
                ImportItem.objects.update_or_create(run=run, external_key=olid, defaults={"status": status, "work": staged, "message": message})
            else:
                stats["failures"] += 1
                ImportItem.objects.update_or_create(run=run, external_key=olid, defaults={"status": "failed", "message": message})

        stats["network_requests"] = client.requests
        stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
        run.status = ImportRun.Status.COMPLETED
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id": run.pk, **stats}, sort_keys=True)))
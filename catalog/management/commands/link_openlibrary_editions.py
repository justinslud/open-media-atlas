"""Link Open Library works to Wikidata through edition identifiers.

Work-level P648 matching finds almost nothing for random Open Library records.
An edition record often carries P648 (its Open Library edition ID) and P629
(edition or translation of) pointing at the Wikidata work. This command uses
that chain and still refuses ambiguous or conflicting matches.
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import IMPORTER_VERSION, WikidataClient, stage_entity
from catalog.models import (
    ExternalIdentifier,
    ImportItem,
    ImportRun,
    Source,
    SourceRecord,
    Work,
)

QUERY_SERVICE = "https://query.wikidata.org/sparql"
CHUNK = 80


class Command(BaseCommand):
    help = "Link Open Library works to Wikidata via edition P648/P629 claims."

    def add_arguments(self, parser):
        parser.add_argument("--extract", type=Path, required=True)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--request-limit", type=int, default=100)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        records = options["extract"] / "records.jsonl"
        if not records.is_file():
            raise CommandError(f"missing {records}")

        work_editions = {}
        work_olid = {}
        with records.open() as stream:
            for line in stream:
                row = json.loads(line)
                olid = str(row["work"].get("key", "")).removeprefix("/works/")
                if not olid:
                    continue
                identifiers = ExternalIdentifier.objects.filter(scheme="ol_work", value=olid).select_related("work").first()
                if not identifiers:
                    continue
                if ExternalIdentifier.objects.filter(work=identifiers.work, scheme="wikidata").exists():
                    continue
                editions = [str(edition.get("key", "")).removeprefix("/books/") for edition in row.get("editions") or []]
                editions = [value for value in editions if value.startswith("OL")]
                if not editions:
                    continue
                work_editions[olid] = editions[:5]
                work_olid[olid] = identifiers.work
                if len(work_editions) >= options["limit"]:
                    break

        if not work_editions:
            self.stdout.write("no unlinked works with editions")
            return

        source, _ = Source.objects.get_or_create(
            title="Wikidata",
            defaults={"kind": "knowledge-base", "url": "https://www.wikidata.org/", "notes": "Supplier assertions require OMA review."},
        )
        run = ImportRun.objects.create(
            source=source,
            requested_keys=sorted(work_editions),
            importer_version=IMPORTER_VERSION,
            manifest={"command": "link_openlibrary_editions", "works": len(work_editions)},
        )
        client = WikidataClient(timeout=options["timeout"], max_requests=options["request_limit"])
        started = time.monotonic()

        all_editions = sorted({edition for values in work_editions.values() for edition in values})
        edition_to_work = {
            edition: olid for olid, editions in work_editions.items() for edition in editions
        }
        edition_links = {}
        for offset in range(0, len(all_editions), CHUNK):
            chunk = all_editions[offset:offset + CHUNK]
            values = " ".join(f'"{value}"' for value in chunk)
            query = f"""SELECT ?edition ?olid ?work WHERE {{
              VALUES ?olid {{ {values} }}
              ?edition wdt:P648 ?olid .
              OPTIONAL {{ ?edition wdt:P629 ?work }}
            }}"""
            try:
                data = client.get_json(QUERY_SERVICE, {"query": query, "format": "json"}, attempts=4)
            except Exception as exc:
                run.status = ImportRun.Status.FAILED
                run.stats = {"error": str(exc)}
                run.finished_at = timezone.now()
                run.save(update_fields=("status", "stats", "finished_at"))
                raise CommandError(f"Wikidata edition query failed: {exc}") from exc
            for binding in data.get("results", {}).get("bindings", []):
                edition_qid = binding["edition"]["value"].rsplit("/", 1)[-1]
                edition_olid = binding["olid"]["value"]
                olid = edition_to_work.get(edition_olid)
                if not olid:
                    continue
                target = binding.get("work", {}).get("value", "")
                target_qid = target.rsplit("/", 1)[-1] if target else ""
                edition_links.setdefault(olid, {"editions": set(), "works": set()})
                edition_links[olid]["editions"].add(edition_qid)
                if target_qid:
                    edition_links[olid]["works"].add(target_qid)

        stats = {
            "unlinked_works": len(work_editions),
            "editions_queried": len(all_editions),
            "edition_links_found": len(edition_links),
            "works_linked": 0,
            "works_refreshed": 0,
            "ambiguous": [],
            "no_work_claim": 0,
            "failures": 0,
            "network_requests": 0,
        }

        for olid, work in sorted(work_olid.items()):
            found = edition_links.get(olid)
            if not found:
                continue
            if len(found["works"]) > 1:
                stats["ambiguous"].append({"olid": olid, "work": work.pk, "candidates": sorted(found["works"])})
                ImportItem.objects.update_or_create(
                    run=run, external_key=olid,
                    defaults={"status": "skipped", "work": work, "message": f"ambiguous P629 targets: {sorted(found['works'])}"},
                )
                continue
            if not found["works"]:
                stats["no_work_claim"] += 1
                continue
            qid = next(iter(found["works"]))
            if options["dry_run"]:
                stats["works_linked"] += 1
                ImportItem.objects.update_or_create(
                    run=run, external_key=olid,
                    defaults={"status": "dry-run", "work": work, "message": f"would link {qid} via edition P648/P629"},
                )
                continue
            entity = client.entities([qid]).get(qid)
            if not entity or entity.get("missing"):
                stats["failures"] += 1
                ImportItem.objects.update_or_create(
                    run=run, external_key=olid,
                    defaults={"status": "failed", "work": work, "message": f"Wikidata entity {qid} missing"},
                )
                continue
            raw = json.dumps(entity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            SourceRecord.objects.update_or_create(
                source=source, external_key=qid,
                defaults={"payload_hash": __import__("hashlib").sha256(raw).hexdigest(), "raw_payload": entity,
                          "matched_work": work, "retrieved_at": timezone.now()},
            )
            staged, status, message = stage_entity(
                entity, source, run, existing_only=True,
                allow_title_collision=False, refresh_existing=True,
            )
            if staged:
                stats["works_linked"] += 1
                if status == "updated":
                    stats["works_refreshed"] += 1
                ImportItem.objects.update_or_create(
                    run=run, external_key=olid,
                    defaults={"status": status, "work": staged, "message": f"linked {qid} via edition P648/P629"},
                )
            else:
                stats["failures"] += 1
                ImportItem.objects.update_or_create(
                    run=run, external_key=olid,
                    defaults={"status": "failed", "work": work, "message": message},
                )

        stats["network_requests"] = client.requests
        stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
        run.status = ImportRun.Status.COMPLETED
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))

        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps({"run_id": run.pk, **stats}, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({"run_id": run.pk, **{k: v for k, v in stats.items() if k != "ambiguous"}}, sort_keys=True))
        if stats["ambiguous"]:
            self.stdout.write(f"ambiguous={len(stats['ambiguous'])}")

"""Stage and publish books discovered from Wikidata's Open Library links.

Candidates come from discover_wikidata_books. Each entity goes through the same
stage_entity path used by every other import, so identity, type, date, creator,
and identifier rules stay in one place. Publication is limited to records that
actually have a date and a known title.
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import IMPORTER_VERSION, WikidataClient, stage_entity
from catalog.models import ImportItem, ImportRun, Source, Work


def _claim_ids(entity, prop):
    """Yield item QIDs asserted by a property, ignoring deprecated statements."""
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item" and value.get("id"):
            yield value["id"]


class Command(BaseCommand):
    help = "Stage and optionally publish books from a Wikidata discovery manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--limit", type=int, default=2000)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--request-limit", type=int, default=120)
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--depth", choices=("ambient", "index", "editorial"), default="ambient")
        parser.add_argument("--publish", action="store_true", help="Publish dated records at --depth")
        parser.add_argument("--report", type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        if not 1 <= options["batch_size"] <= 50:
            raise CommandError("--batch-size must be 1..50")
        if not options["manifest"].is_file():
            raise CommandError(f"missing {options['manifest']}")
        manifest = json.loads(options["manifest"].read_text())
        candidates = manifest.get("candidates", [])[: options["limit"]]
        if not candidates:
            self.stdout.write("no candidates")
            return
        if options["dry_run"]:
            self.stdout.write(json.dumps({"dry_run": True, "candidates": len(candidates)}))
            return

        source, _ = Source.objects.get_or_create(
            title="Wikidata",
            defaults={"kind": "knowledge-base", "url": "https://www.wikidata.org/",
                      "notes": "Supplier assertions require OMA review."},
        )
        run = ImportRun.objects.create(
            source=source,
            requested_keys=[row["qid"] for row in candidates],
            importer_version=IMPORTER_VERSION,
            manifest={
                "command": "import_wikidata_books",
                "manifest": str(options["manifest"]),
                "depth": options["depth"],
                "publish": options["publish"],
                "counts": len(candidates),
            },
        )
        client = WikidataClient(timeout=options["timeout"], max_requests=options["request_limit"])
        started = time.monotonic()
        stats = {
            "candidates": len(candidates),
            "created": 0,
            "matched": 0,
            "published": 0,
            "kept_draft": 0,
            "failures": 0,
            "network_requests": 0,
        }
        publish_ids = []

        for offset in range(0, len(candidates), options["batch_size"]):
            batch = candidates[offset:offset + options["batch_size"]]
            try:
                entities = client.entities([row["qid"] for row in batch])
            except Exception as exc:
                stats["failures"] += len(batch)
                for row in batch:
                    ImportItem.objects.update_or_create(
                        run=run, external_key=row["qid"],
                        defaults={"status": "failed", "message": f"entity fetch failed: {exc}"},
                    )
                continue
            # Creator and language labels only exist on their own entities, so a
            # credit cannot be written without fetching them deliberately.
            support_ids = sorted({
                value
                for entity in entities.values()
                for prop in ("P50", "P57", "P86", "P58", "P110", "P162", "P175", "P364")
                for value in _claim_ids(entity, prop)
            } - set(entities))
            supporting = {}
            if support_ids:
                for offset_support in range(0, len(support_ids), 50):
                    supporting.update(client.entities(support_ids[offset_support:offset_support + 50]))
            for row in batch:
                entity = entities.get(row["qid"])
                if not entity or entity.get("missing"):
                    stats["failures"] += 1
                    ImportItem.objects.update_or_create(
                        run=run, external_key=row["qid"],
                        defaults={"status": "failed", "message": "entity missing"},
                    )
                    continue
                work, status, message = stage_entity(
                    entity, source, run,
                    supporting_entities={**entities, **supporting},
                    existing_only=False,
                    allow_title_collision=True,
                    refresh_existing=True,
                )
                if not work:
                    stats["failures"] += 1
                    ImportItem.objects.update_or_create(
                        run=run, external_key=row["qid"],
                        defaults={"status": "failed", "message": message},
                    )
                    continue
                if status == "created":
                    stats["created"] += 1
                else:
                    stats["matched"] += 1
                ImportItem.objects.update_or_create(
                    run=run, external_key=row["qid"],
                    defaults={"status": status, "work": work, "message": message},
                )
                if options["publish"] and work.first_publication_year and work.has_known_title:
                    publish_ids.append(work.pk)

        publish_ids = list(dict.fromkeys(publish_ids))
        if publish_ids:
            published = Work.objects.filter(pk__in=publish_ids).exclude(
                visibility=Work.Visibility.PUBLIC
            ).update(visibility=Work.Visibility.PUBLIC, depth=options["depth"])
            stats["published"] = published
            stats["kept_draft"] = len(publish_ids) - published
        else:
            stats["kept_draft"] = 0

        stats["network_requests"] = client.requests
        stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
        run.status = ImportRun.Status.COMPLETED
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))

        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps({"run_id": run.pk, **stats}, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({"run_id": run.pk, **stats}, sort_keys=True))

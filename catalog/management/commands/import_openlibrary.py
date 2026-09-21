from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.openlibrary import ImportFailure, OpenLibraryImporter
from catalog.models import ImportItem, ImportRun


class Command(BaseCommand):
    help = "Import an explicit, bounded list of Open Library work IDs."

    def add_arguments(self, parser):
        parser.add_argument("work_ids", nargs="*")
        parser.add_argument("--file", type=Path, help="Text file containing one OL work ID per line")
        parser.add_argument("--retry-run", type=int, help="Retry only failed keys from a previous import run")
        parser.add_argument("--limit", type=int, default=25, help="Maximum records to process (1–100; default 25)")
        parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing catalog or run records")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 100:
            raise CommandError("--limit must be between 1 and 100")
        ids = list(options["work_ids"])
        if options["retry_run"]:
            try:
                previous = ImportRun.objects.get(pk=options["retry_run"])
            except ImportRun.DoesNotExist as error:
                raise CommandError("Import run does not exist") from error
            ids.extend(previous.items.filter(status="failed").values_list("external_key", flat=True))
        if options["file"]:
            ids.extend(line.strip() for line in options["file"].read_text().splitlines() if line.strip() and not line.startswith("#"))
        ids = list(dict.fromkeys(ids))[: options["limit"]]
        if not ids:
            raise CommandError("Provide explicit work IDs or --file")
        importer = OpenLibraryImporter()
        if options["dry_run"]:
            for external_id in ids:
                try:
                    item = importer.preview(external_id)
                    self.stdout.write(f"would import {item['id']}: {item['title'] or '[missing title]'}")
                except ImportFailure as error:
                    self.stderr.write(f"failed {external_id}: {error}")
            return

        run = ImportRun.objects.create(source=importer.source, requested_keys=ids)
        stats = {name: 0 for name in ("created", "updated", "skipped", "failed")}
        for external_id in ids:
            try:
                result = importer.import_work(external_id)
            except Exception as error:
                stats["failed"] += 1
                ImportItem.objects.create(run=run, external_key=external_id, status="failed", message=str(error)[:1000])
                self.stderr.write(f"failed {external_id}: {error}")
                continue
            stats[result.status] += 1
            ImportItem.objects.create(run=run, external_key=external_id, status=result.status, work=result.work, message=result.message)
            self.stdout.write(f"{result.status} {external_id}: {result.work.title}")
        run.status = ImportRun.Status.COMPLETED_WITH_ERRORS if stats["failed"] else ImportRun.Status.COMPLETED
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))
        self.stdout.write(self.style.SUCCESS(" ".join(f"{key}={value}" for key, value in stats.items())))

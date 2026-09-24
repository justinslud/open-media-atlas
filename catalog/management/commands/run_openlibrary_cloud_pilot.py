"""Run the bounded Open Library pilot end-to-end in one disposable cloud job."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.openlibrary_bulk import IMPORTER_VERSION, BulkImportError, extract, validate_extract
from catalog.models import ImportRun, Source


ENVIRONMENTS = {
    "snapshot_date": "OPENLIBRARY_SNAPSHOT_DATE",
    "editions": "OPENLIBRARY_EDITIONS_URL",
    "works": "OPENLIBRARY_WORKS_URL",
    "authors": "OPENLIBRARY_AUTHORS_URL",
    "editions_checksum": "OPENLIBRARY_EDITIONS_CHECKSUM",
    "works_checksum": "OPENLIBRARY_WORKS_CHECKSUM",
    "authors_checksum": "OPENLIBRARY_AUTHORS_CHECKSUM",
}


class Command(BaseCommand):
    help = "Stream a pinned Open Library snapshot, validate it, and stage it in one cloud job."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=int(os.getenv("OPENLIBRARY_LIMIT", "5000")))
        parser.add_argument("--editions-per-work", type=int, default=2)
        parser.add_argument("--seed", default="oma-ol-pilot-v1")
        parser.add_argument("--max-runtime", type=int, default=int(os.getenv("OPENLIBRARY_MAX_RUNTIME", "21600")))
        parser.add_argument("--min-free-mib", type=int, default=int(os.getenv("OPENLIBRARY_MIN_FREE_MIB", "512")))
        parser.add_argument("--extract-only", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--resume-run", type=int)

    def handle(self, *args, **options):
        config = {name: os.getenv(env, "").strip() for name, env in ENVIRONMENTS.items()}
        missing = [ENVIRONMENTS[name] for name, value in config.items() if not value]
        if missing:
            raise CommandError("Missing required environment variables: " + ", ".join(missing))
        if any(config["snapshot_date"] not in config[k] for k in ("editions", "works", "authors")):
            raise CommandError("All three pinned URLs must contain OPENLIBRARY_SNAPSHOT_DATE")
        if any(len(config[k]) not in (40, 64) for k in ("editions_checksum", "works_checksum", "authors_checksum")):
            raise CommandError("Each OPENLIBRARY_*_CHECKSUM must be an official 40-character SHA-1 or 64-character SHA-256 digest")
        if options["max_runtime"] < 60:
            raise CommandError("--max-runtime must be at least 60 seconds")

        source, _ = Source.objects.get_or_create(
            title="Open Library",
            defaults={"kind": "dataset", "url": "https://openlibrary.org/developers/dumps", "notes": "Open Library bulk dump metadata; no rights conclusion."},
        )
        parameters = {
            "snapshot_date": config["snapshot_date"], "urls": {k: config[k] for k in ("editions", "works", "authors")},
            "checksums": {k: config[f"{k}_checksum"] for k in ("editions", "works", "authors")},
            "limit": options["limit"], "editions_per_work": options["editions_per_work"], "seed": options["seed"],
            "max_runtime": options["max_runtime"], "min_free_mib": options["min_free_mib"],
        }
        if options["resume_run"]:
            try:
                run = ImportRun.objects.get(pk=options["resume_run"], source=source)
            except ImportRun.DoesNotExist as exc:
                raise CommandError("Resume run not found for Open Library") from exc
            if run.manifest.get("cloud_parameters") != parameters:
                raise CommandError("Resume parameters do not exactly match the original run")
            run.status = ImportRun.Status.RUNNING
            run.finished_at = None
        else:
            run = ImportRun(source=source, importer_version=IMPORTER_VERSION, requested_keys=[])
        run.manifest = {**run.manifest, "cloud_parameters": parameters}
        run.stats = {**run.stats, "phase": "preflight", "report": "Cloud pilot started"}
        run.save()
        started = time.monotonic()

        try:
            with tempfile.TemporaryDirectory(prefix="oma-openlibrary-") as temporary:
                free = shutil.disk_usage(temporary).free
                required = options["min_free_mib"] * 1024 * 1024
                if free < required:
                    raise BulkImportError(f"Temporary disk preflight failed: {free} bytes free; {required} required")

                def progress(phase, stats):
                    run.stats = {**run.stats, "phase": phase, "checkpoint": dict(stats), "temporary_free_bytes": free}
                    run.save(update_fields=("stats",))
                    self.stdout.write(f"run={run.pk} phase={phase} records_scanned={stats['records_scanned']}")

                output = Path(temporary) / "extract"
                manifest = extract(
                    editions=config["editions"], works=config["works"], authors=config["authors"], output=output,
                    limit=options["limit"], editions_per_work=options["editions_per_work"], seed=options["seed"],
                    snapshot_date=config["snapshot_date"], max_runtime=options["max_runtime"],
                    urls=parameters["urls"], checksums=parameters["checksums"], progress=progress,
                )
                manifest["cloud_parameters"] = parameters
                run.manifest = manifest
                run.stats = {**run.stats, "phase": "validated", "extraction": manifest["stats"], "artifact_sha256": manifest["artifact"]["sha256"]}
                run.save(update_fields=("manifest", "stats"))
                validate_extract(output)

                if options["extract_only"] or options["dry_run"]:
                    run.status = ImportRun.Status.COMPLETED
                    run.finished_at = timezone.now()
                    run.stats = {**run.stats, "phase": "extract_only" if options["extract_only"] else "dry_run", "report": "Extracted and validated; ingestion intentionally skipped"}
                    run.save(update_fields=("status", "finished_at", "stats"))
                else:
                    remaining = max(1, options["max_runtime"] - int(time.monotonic() - started))
                    call_command("ingest_openlibrary_extract", output, resume_run=run.pk, max_runtime=remaining)
                    run.refresh_from_db()
                    run.stats = {**run.stats, "total_elapsed_seconds": round(time.monotonic() - started, 3), "report": "Extraction, validation, and staged ingestion finished"}
                    run.save(update_fields=("stats",))
        except Exception as exc:
            run.status = ImportRun.Status.FAILED
            run.finished_at = timezone.now()
            run.stats = {**run.stats, "phase": "failed", "report": str(exc)[:1000]}
            run.save(update_fields=("status", "finished_at", "stats"))
            raise CommandError(f"run={run.pk}: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id": run.pk, "status": run.status, "stats": run.stats}, sort_keys=True)))

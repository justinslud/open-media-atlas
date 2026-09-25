"""Run the bounded Open Library pilot end-to-end in one disposable cloud job."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

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


def resolve_snapshot(config):
    """Resolve OL's `latest` links and fill checksums from official IA metadata."""
    import re

    resolved = {}
    identifiers = set()
    dates = set()
    for kind in ("editions", "works", "authors"):
        url = config[kind]
        with urlopen(Request(url, headers={"User-Agent": "OpenMediaAtlas/ol-bulk-2"}), timeout=60) as response:
            final_url = response.geturl()
        match = re.search(r"/(?:download/|\d+/items/)([^/]+)/(ol_dump_[^/]+\.txt\.gz)$", final_url)
        if not match:
            raise CommandError(f"{kind} URL did not resolve to an official dated Internet Archive dump")
        identifier, filename = match.groups()
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
        if not date_match:
            raise CommandError(f"{kind} dump filename has no snapshot date")
        identifiers.add(identifier)
        dates.add(date_match.group(1))
        metadata_url = f"https://archive.org/metadata/{quote(identifier)}"
        with urlopen(Request(metadata_url, headers={"User-Agent": "OpenMediaAtlas/ol-bulk-2"}), timeout=60) as response:
            metadata = json.load(response)
        file_metadata = next((item for item in metadata.get("files", []) if item.get("name") == filename), None)
        if not file_metadata:
            raise CommandError(f"No official metadata found for {filename}")
        published_checksum = file_metadata.get("sha256") or file_metadata.get("sha1")
        supplied_checksum = config[f"{kind}_checksum"]
        if not supplied_checksum and not published_checksum:
            raise CommandError(f"No SHA-1 or SHA-256 is published for {filename}")
        if supplied_checksum and published_checksum and supplied_checksum.lower() != published_checksum.lower():
            raise CommandError(f"Configured {kind} checksum differs from official metadata")
        resolved[kind] = f"https://archive.org/download/{identifier}/{filename}"
        resolved[f"{kind}_checksum"] = supplied_checksum or published_checksum
    if len(identifiers) != 1 or len(dates) != 1:
        raise CommandError("Editions, works, and authors must resolve to the same dated snapshot")
    snapshot_date = dates.pop()
    if config["snapshot_date"] and config["snapshot_date"] != snapshot_date:
        raise CommandError(f"OPENLIBRARY_SNAPSHOT_DATE must be {snapshot_date} for the resolved files")
    resolved["snapshot_date"] = snapshot_date
    return resolved


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
        missing = [ENVIRONMENTS[name] for name in ("editions", "works", "authors") if not config[name]]
        if missing:
            raise CommandError("Missing required environment variables: " + ", ".join(missing))
        source, _ = Source.objects.get_or_create(
            title="Open Library",
            defaults={"kind": "dataset", "url": "https://openlibrary.org/developers/dumps", "notes": "Open Library bulk dump metadata; no rights conclusion."},
        )
        resume_run = None
        if options["resume_run"]:
            try:
                resume_run = ImportRun.objects.get(pk=options["resume_run"], source=source)
            except ImportRun.DoesNotExist as exc:
                raise CommandError("Resume run not found for Open Library") from exc
            original = resume_run.manifest.get("cloud_parameters", {})
            if original.get("urls") and original.get("checksums"):
                config = {
                    "snapshot_date": original.get("snapshot_date", ""),
                    **original["urls"],
                    **{f"{kind}_checksum": original["checksums"].get(kind, "") for kind in ("editions", "works", "authors")},
                }
        config = resolve_snapshot(config)
        if any(len(config[k]) not in (40, 64) for k in ("editions_checksum", "works_checksum", "authors_checksum")):
            raise CommandError("Each resolved checksum must be a 40-character SHA-1 or 64-character SHA-256 digest")
        if options["max_runtime"] < 60:
            raise CommandError("--max-runtime must be at least 60 seconds")

        parameters = {
            "snapshot_date": config["snapshot_date"], "urls": {k: config[k] for k in ("editions", "works", "authors")},
            "checksums": {k: config[f"{k}_checksum"] for k in ("editions", "works", "authors")},
            "limit": options["limit"], "editions_per_work": options["editions_per_work"], "seed": options["seed"],
            "max_runtime": options["max_runtime"], "min_free_mib": options["min_free_mib"],
        }
        if options["resume_run"]:
            run = resume_run
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

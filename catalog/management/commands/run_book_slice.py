"""Run one complete book slice: discover, import, connect, triage.

The steps already exist as separate commands. This wrapper exists so a slice is
reproducible and cannot be run half-way by accident: every stage is recorded in
one report, and triage approval is opt-in.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run a book slice end to end: discover, import, resolve, triage."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=2500, help="Books to discover and import")
        parser.add_argument("--min-sitelinks", type=int, default=1, help="Discovery sitelink floor")
        parser.add_argument("--scan", type=int, default=0,
                            help="Rows to inspect during discovery (default 3x --limit, max 5000)")
        parser.add_argument("--depth", choices=("ambient", "index"), default="index",
                            help="Depth for published books")
        parser.add_argument("--seed-limit", type=int, default=500)
        parser.add_argument("--seed-min-sitelinks", type=int, default=20)
        parser.add_argument("--relationship-limit", type=int, default=1500)
        parser.add_argument("--approve", action="store_true", help="Approve green triage rows")
        parser.add_argument("--skip-discover", type=Path, help="Reuse an existing candidate manifest")
        parser.add_argument("--workdir", type=Path, default=Path("docs/slices"))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        if not 1 <= options["seed_limit"] <= 500:
            raise CommandError("--seed-limit must be 1..500")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        workdir = options["workdir"] / f"books-{stamp}"
        candidates = options["skip_discover"] or (workdir / "candidates.json")
        seeds = workdir / "seeds.json"
        report_path = workdir / "slice.json"

        steps = [
            ("discover", options["skip_discover"] is None),
            ("import", True),
            ("seeds", True),
            ("resolve", True),
            ("triage", True),
        ]
        if options["dry_run"]:
            self.stdout.write(json.dumps({
                "dry_run": True,
                "workdir": str(workdir),
                "steps": [name for name, enabled in steps if enabled],
                "limits": {key: options[key] for key in ("limit", "seed_limit", "relationship_limit")},
                "approve": options["approve"],
            }, sort_keys=True))
            return

        results = {}
        started = time.monotonic()

        if options["skip_discover"] is None:
            call_command(
                "discover_wikidata_books",
                limit=options["limit"],
                scan=options["scan"] or min(5000, options["limit"] * 3),
                min_sitelinks=options["min_sitelinks"],
                manifest=candidates,
                output=workdir / "discovery.json",
            )
            results["discover"] = json.loads((workdir / "discovery.json").read_text())

        if not json.loads(candidates.read_text()).get("candidates"):
            raise CommandError(
                "discovery found no new candidates; every scanned book is already in the catalog"
            )

        call_command(
            "import_wikidata_books",
            manifest=candidates,
            limit=options["limit"],
            publish=True,
            depth=options["depth"],
            report=workdir / "import.json",
        )
        results["import"] = json.loads((workdir / "import.json").read_text())

        call_command(
            "build_seed_manifest",
            output=seeds,
            depth=options["depth"],
            min_sitelinks=options["seed_min_sitelinks"],
            require_date=True,
            require_creator=True,
            limit=options["seed_limit"],
        )
        results["seeds"] = json.loads(seeds.read_text())["selection"] | {"count": len(json.loads(seeds.read_text())["seeds"])}

        call_command(
            "resolve_wikidata_relationships",
            manifest=seeds,
            seed_limit=options["seed_limit"],
            limit=options["relationship_limit"],
            seed_scope="public",
        )
        call_command(
            "triage_proposals",
            seed_scope="public",
            output=workdir / "triage.json",
            confirm=options["approve"],
        )
        triage = json.loads((workdir / "triage.json").read_text())
        results["triage"] = {
            "candidates": triage["candidate_count"],
            "summary": triage["summary"]["decisions"],
            "applied": triage.get("applied"),
        }

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workdir": str(workdir),
            "depth": options["depth"],
            "approve": options["approve"],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "results": results,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({
            "workdir": str(workdir),
            "elapsed_seconds": report["elapsed_seconds"],
            "import": {key: results["import"].get(key) for key in ("created", "matched", "published")},
            "triage": results["triage"],
        }, sort_keys=True))

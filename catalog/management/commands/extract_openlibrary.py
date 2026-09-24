import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.importers.openlibrary_bulk import BulkImportError, extract

class Command(BaseCommand):
    help = "Create a reusable bounded extract from pinned Open Library dumps."
    def add_arguments(self, p):
        p.add_argument("--editions", type=Path, required=True); p.add_argument("--works", type=Path, required=True); p.add_argument("--authors", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True); p.add_argument("--limit", type=int, default=5000); p.add_argument("--editions-per-work", type=int, default=2)
        p.add_argument("--seed", default="oma-ol-pilot-v1"); p.add_argument("--snapshot-date", required=True); p.add_argument("--max-runtime", type=int, default=0, help="Seconds; 0 disables")
        for kind in ("editions","works","authors"):
            p.add_argument(f"--{kind}-url", required=True); p.add_argument(f"--{kind}-sha256", default="")
    def handle(self,*args,**o):
        try:
            manifest=extract(editions=o["editions"],works=o["works"],authors=o["authors"],output=o["output"],limit=o["limit"],editions_per_work=o["editions_per_work"],seed=o["seed"],snapshot_date=o["snapshot_date"],max_runtime=o["max_runtime"],urls={k:o[f"{k}_url"] for k in ("editions","works","authors")},checksums={k:o[f"{k}_sha256"] for k in ("editions","works","authors")})
        except BulkImportError as exc: raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(json.dumps(manifest["stats"],sort_keys=True)))

import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import IMPORTER_VERSION, WikidataClient, WikidataError, run_import
from catalog.models import ImportRun, Source


class Command(BaseCommand):
    help = "Fetch, validate, and stage a bounded Wikidata P144 relationship batch."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-pilot-seeds.json")
        parser.add_argument("--seed-limit", type=int, default=50)
        parser.add_argument("--related-limit", type=int, default=300)
        parser.add_argument("--request-limit", type=int, default=250)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--max-runtime", type=int, default=1800)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["seed_limit"] <= 50: raise CommandError("--seed-limit must be 1..50")
        if not 1 <= options["related_limit"] <= 300: raise CommandError("--related-limit must be 1..300")
        path=Path(options["manifest"])
        try: manifest=json.loads(path.read_text())
        except (OSError,json.JSONDecodeError) as exc: raise CommandError(f"invalid seed manifest: {exc}") from exc
        chosen=manifest.get("seeds",[])[:options["seed_limit"]]
        seeds=[row["qid"] for row in chosen]
        if len(set(seeds)) != len(seeds) or any(not q[1:].isdigit() for q in seeds if q.startswith("Q")) or any(not q.startswith("Q") for q in seeds):
            raise CommandError("manifest must contain unique Wikidata QIDs")
        source,_=Source.objects.get_or_create(title="Wikidata",defaults={"kind":"knowledge-base","url":"https://www.wikidata.org/","notes":"Supplier assertions require OMA review."})
        run=ImportRun.objects.create(source=source,requested_keys=seeds,importer_version=IMPORTER_VERSION,
            manifest={"seed_manifest":str(path),"seed_manifest_version":manifest.get("version"),"seeds":chosen,
                      "limits":{"seeds":len(seeds),"related":options["related_limit"],"requests":options["request_limit"],"runtime_seconds":options["max_runtime"]},
                      "access":"Wikidata Query Service for bounded inbound P144 discovery; wbgetentities batches of 50 for metadata"})
        self.stdout.write(f"run_id={run.pk} seeds={len(seeds)} related_cap={options['related_limit']} dry_run={options['dry_run']}")
        started=time.monotonic()
        try:
            stats=run_import(run,seeds,related_limit=options["related_limit"],dry_run=options["dry_run"],
                client=WikidataClient(timeout=options["timeout"],max_requests=options["request_limit"]))
            if time.monotonic()-started > options["max_runtime"]: raise WikidataError("runtime limit exceeded")
            run.status=ImportRun.Status.COMPLETED
        except Exception as exc:
            run.status=ImportRun.Status.FAILED; stats={"error":str(exc),"elapsed_seconds":round(time.monotonic()-started,2)}
            run.stats=stats; run.finished_at=timezone.now(); run.save(update_fields=("status","stats","finished_at"))
            raise CommandError(str(exc)) from exc
        run.stats=stats; run.finished_at=timezone.now(); run.save(update_fields=("status","stats","finished_at"))
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id":run.pk,**stats},sort_keys=True)))

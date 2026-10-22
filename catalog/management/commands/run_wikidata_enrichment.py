import json
import re
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import IMPORTER_VERSION, WikidataClient, WikidataError, run_import
from catalog.models import ImportRun, Source

QID = re.compile(r"^Q[1-9]\d*$")


def load_candidates(path, seeds):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"invalid candidate manifest: {exc}") from exc
    rows = data.get("candidates", data) if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise CommandError("candidate manifest must contain a non-empty candidates list")
    normalized = []
    for raw in rows:
        row = {"qid": raw} if isinstance(raw, str) else dict(raw)
        qid = str(row.get("qid", "")).strip()
        if not QID.fullmatch(qid):
            raise CommandError(f"invalid candidate QID: {qid!r}")
        seed_qid = row.get("seed_qid")
        if seed_qid and seed_qid not in seeds:
            raise CommandError(f"candidate {qid} points to seed {seed_qid}, which is not in the selected seed manifest")
        expected_year = row.get("expected_year")
        if expected_year is not None and not isinstance(expected_year, int):
            raise CommandError(f"candidate {qid} expected_year must be an integer")
        normalized.append({
            "qid": qid,
            "seed_qid": seed_qid,
            "label": str(row.get("label", ""))[:200],
            "expected_type": row.get("expected_type"),
            "expected_year": expected_year,
            "evidence": str(row.get("evidence", ""))[:500],
        })
    if len({row["qid"] for row in normalized}) != len(normalized):
        raise CommandError("candidate manifest contains duplicate QIDs")
    return normalized


class Command(BaseCommand):
    help = "Fetch, validate, and stage a bounded Wikidata P144 batch from discovery or an explicit candidate manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-pilot-seeds.json")
        parser.add_argument("--candidates", help="JSON candidate manifest; bypasses WDQS discovery but still requires exact P144 claims.")
        parser.add_argument("--seed-limit", type=int, default=50)
        parser.add_argument("--related-limit", type=int, default=1000)
        parser.add_argument("--request-limit", type=int, default=500)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--max-runtime", type=int, default=1800)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["seed_limit"] <= 200:
            raise CommandError("--seed-limit must be 1..200")
        if not 1 <= options["related_limit"] <= 5000:
            raise CommandError("--related-limit must be 1..5000")
        path = Path(options["manifest"])
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid seed manifest: {exc}") from exc
        chosen = manifest.get("seeds", [])[: options["seed_limit"]]
        seeds = [row["qid"] for row in chosen]
        if len(set(seeds)) != len(seeds) or any(not QID.fullmatch(str(q)) for q in seeds):
            raise CommandError("manifest must contain unique Wikidata QIDs")
        candidate_rows = load_candidates(options["candidates"], seeds) if options["candidates"] else []
        candidate_qids = [row["qid"] for row in candidate_rows]
        if candidate_qids and len(candidate_qids) > options["related_limit"]:
            raise CommandError("candidate count exceeds --related-limit")
        source, _ = Source.objects.get_or_create(
            title="Wikidata",
            defaults={"kind": "knowledge-base", "url": "https://www.wikidata.org/", "notes": "Supplier assertions require OMA review."},
        )
        run = ImportRun.objects.create(
            source=source,
            requested_keys=seeds + candidate_qids,
            importer_version=IMPORTER_VERSION,
            manifest={
                "seed_manifest": str(path),
                "seed_manifest_version": manifest.get("version"),
                "seeds": chosen,
                "candidate_manifest": options["candidates"],
                "candidates": candidate_rows,
                "limits": {
                    "seeds": len(seeds),
                    "related": options["related_limit"],
                    "requests": options["request_limit"],
                    "runtime_seconds": options["max_runtime"],
                },
                "access": "Candidate manifest uses wbgetentities; P144 discovery uses Wikidata Query Service. Both require exact IDs and only stage drafts/proposals.",
            },
        )
        mode = "candidates" if candidate_qids else "discovery"
        self.stdout.write(f"run_id={run.pk} mode={mode} seeds={len(seeds)} candidates={len(candidate_qids)} related_cap={options['related_limit']} dry_run={options['dry_run']}")
        started = time.monotonic()
        try:
            stats = run_import(
                run,
                seeds,
                related_limit=options["related_limit"],
                dry_run=options["dry_run"],
                candidate_qids=candidate_qids or None,
                client=WikidataClient(timeout=options["timeout"], max_requests=options["request_limit"]),
            )
            if time.monotonic() - started > options["max_runtime"]:
                raise WikidataError("runtime limit exceeded")
            if candidate_rows and not options["dry_run"]:
                checks = []
                for row in candidate_rows:
                    item = run.items.filter(external_key=row["qid"]).select_related("work", "work__work_type").first()
                    if not item or not item.work:
                        checks.append({"qid": row["qid"], "status": "exception", "reason": item.message if item else "missing import item"})
                        continue
                    work = item.work
                    exceptions = []
                    if row["expected_type"] and work.work_type.code != row["expected_type"]:
                        exceptions.append(f"type={work.work_type.code}, expected={row['expected_type']}")
                    if row["expected_year"] and work.first_publication_year != row["expected_year"]:
                        exceptions.append(f"year={work.first_publication_year}, expected={row['expected_year']}")
                    checks.append({
                        "qid": row["qid"],
                        "work": work.pk,
                        "title": work.title,
                        "type": work.work_type.code,
                        "year": work.first_publication_year,
                        "status": "exception" if exceptions else "ok",
                        "reason": "; ".join(exceptions),
                    })
                stats["candidate_checks"] = checks
            run.status = ImportRun.Status.COMPLETED
        except Exception as exc:
            run.status = ImportRun.Status.FAILED
            stats = {"error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 2)}
            run.stats = stats
            run.finished_at = timezone.now()
            run.save(update_fields=("status", "stats", "finished_at"))
            raise CommandError(str(exc)) from exc
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id": run.pk, **stats}, sort_keys=True)))

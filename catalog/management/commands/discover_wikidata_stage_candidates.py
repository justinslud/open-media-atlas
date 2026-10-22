"""Discover stage-adaptation candidates from Wikidata P144 and emit a manifest.

This command only discovers and writes a candidate bundle. It never stages
works or creates proposals; feed the output to run_wikidata_enrichment
--candidates after review.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.dates import wikidata_date_for_medium
from catalog.importers.wikidata import (
    QUERY_SERVICE,
    WikidataClient,
    claim_ids,
    title_from_entity,
    work_type_spec,
)
from catalog.models import ExternalIdentifier

STAGE_TYPES = ("Q1344", "Q2743", "Q15079786")  # opera, musical, ballet
STAGE_CODES = {"opera", "musical", "ballet"}
QID_PREFIX = "Q"


def build_candidate_rows(entities, seeds, seed_labels=None, existing_qids=(), include_existing=False):
    seed_labels = seed_labels or {}
    seed_order = {qid: index for index, qid in enumerate(seeds)}
    rows = []
    for qid in sorted(entities):
        entity = entities[qid]
        if not isinstance(entity, dict) or entity.get("missing"):
            continue
        based_on = claim_ids(entity, "P144")
        seed_qid = next((seed for seed in seeds if seed in based_on), None)
        if not seed_qid:
            continue
        spec = work_type_spec(entity)
        if spec[0] not in STAGE_CODES:
            continue
        if qid in existing_qids and not include_existing:
            continue
        title, title_language, title_basis = title_from_entity(entity)
        date, year, precision, kind, evidence = wikidata_date_for_medium(entity, spec[2])
        rows.append({
            "qid": qid,
            "seed_qid": seed_qid,
            "seed_label": seed_labels.get(seed_qid, ""),
            "label": title or qid,
            "title_language": title_language,
            "title_basis": title_basis,
            "expected_type": spec[0],
            "expected_year": year,
            "date": date,
            "date_kind": kind,
            "date_property": evidence.get("property", ""),
            "precision": precision,
            "already_in_catalog": qid in existing_qids,
        })
    rows.sort(key=lambda row: (seed_order.get(row["seed_qid"], 999), row["label"].lower(), row["qid"]))
    return rows


class Command(BaseCommand):
    help = "Discover bounded opera/musical/ballet P144 candidates and write a candidate manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-golden-20.json")
        parser.add_argument("--output", default="data/stage-candidates-discovered.json")
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--request-limit", type=int, default=20)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--include-existing", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 200:
            raise CommandError("--limit must be 1..200")
        path = Path(options["manifest"])
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid seed manifest: {exc}") from exc
        seeds = [row["qid"] for row in manifest.get("seeds", [])]
        labels = {row["qid"]: row.get("label", "") for row in manifest.get("seeds", [])}
        if not seeds or len(set(seeds)) != len(seeds):
            raise CommandError("seed manifest must contain unique QIDs")
        values = " ".join(f"wd:{qid}" for qid in seeds)
        type_values = " ".join(f"wd:{qid}" for qid in STAGE_TYPES)
        query = f"""SELECT DISTINCT ?derived ?seed WHERE {{
          VALUES ?seed {{ {values} }}
          ?derived p:P144 ?statement. ?statement ps:P144 ?seed.
          FILTER NOT EXISTS {{ ?statement wikibase:rank wikibase:DeprecatedRank }}
          VALUES ?type {{ {type_values} }}
          ?derived wdt:P31 ?type.
        }} ORDER BY ?seed ?derived LIMIT {int(options['limit']) * 5 + 1}"""
        client = WikidataClient(timeout=options["timeout"], max_requests=options["request_limit"])
        try:
            data = client.get_json(QUERY_SERVICE, {"query": query, "format": "json"})
        except Exception as exc:
            raise CommandError(f"Wikidata discovery failed: {exc}") from exc
        bindings = data.get("results", {}).get("bindings", [])
        qids = sorted({row["derived"]["value"].rsplit("/", 1)[-1] for row in bindings})
        entities = client.entities(qids) if qids else {}
        existing_qids = set(
            ExternalIdentifier.objects.filter(scheme="wikidata", value__in=qids).values_list("value", flat=True)
        )
        rows = build_candidate_rows(
            entities, seeds, seed_labels=labels, existing_qids=existing_qids,
            include_existing=options["include_existing"],
        )
        truncated = len(bindings) > options["limit"] * 5 or len(rows) > options["limit"]
        rows = rows[: options["limit"]]
        report = {
            "version": "2026-10-22-stage-discovery",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed_manifest": str(path),
            "seed_count": len(seeds),
            "stage_types": list(STAGE_TYPES),
            "query": "non-deprecated inbound P144; P31 in opera/musical/ballet; no recursive traversal",
            "source_policy": "Wikidata CC0 for identity, P144, P31, and date claims. Discovery only; no works or proposals are created.",
            "candidate_count": len(rows),
            "truncated": truncated,
            "candidates": rows,
        }
        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(self.style.SUCCESS(json.dumps({
            "output": str(output),
            "candidate_count": len(rows),
            "truncated": truncated,
            "network_requests": client.requests,
            "candidates": [{k: row[k] for k in ("qid", "seed_qid", "label", "expected_type", "expected_year")} for row in rows],
        }, indent=2, ensure_ascii=False, sort_keys=True)))

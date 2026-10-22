"""Discover bounded P144 adaptation candidates across supported media.

Discovery only writes a candidate manifest. It never stages works or creates
proposals; feed the manifest to run_wikidata_enrichment --candidates and then
triage_proposals.
"""
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.candidate_discovery import build_candidate_rows
from catalog.importers.wikidata import QUERY_SERVICE, TYPE_MAP, WikidataClient
from catalog.models import ExternalIdentifier

SUPPORTED_CODES = (
    "film",
    "television-series",
    "television-program",
    "play",
    "opera",
    "musical",
    "ballet",
    "video-game",
    "album",
    "song",
    "novel",
)

TYPE_QIDS = defaultdict(list)
for qid, (code, _label, _medium) in TYPE_MAP.items():
    if code in SUPPORTED_CODES:
        TYPE_QIDS[code].append(qid)


def parse_types(value):
    if not value or value == "all":
        return set(SUPPORTED_CODES)
    codes = {item.strip() for item in value.split(",") if item.strip()}
    unknown = codes - set(SUPPORTED_CODES)
    if unknown:
        raise CommandError(f"unsupported types: {', '.join(sorted(unknown))}")
    return codes


class Command(BaseCommand):
    help = "Discover bounded P144 candidates across supported media and write a candidate manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-golden-20.json")
        parser.add_argument("--output", default="data/wikidata-candidates-discovered.json")
        parser.add_argument("--types", default="all", help="Comma-separated public type codes, or all.")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--request-limit", type=int, default=30)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--include-existing", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 500:
            raise CommandError("--limit must be 1..500")
        allowed_codes = parse_types(options["types"])
        type_qids = sorted({qid for code in allowed_codes for qid in TYPE_QIDS.get(code, [])})
        if not type_qids:
            raise CommandError("no Wikidata type QIDs for the requested types")
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
        type_values = " ".join(f"wd:{qid}" for qid in type_qids)
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
            entities,
            seeds,
            allowed_codes,
            seed_labels=labels,
            existing_qids=existing_qids,
            include_existing=options["include_existing"],
        )
        truncated = len(bindings) > options["limit"] * 5 or len(rows) > options["limit"]
        rows = rows[: options["limit"]]
        report = {
            "version": "2026-10-22-general-discovery",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed_manifest": str(path),
            "seed_count": len(seeds),
            "types": sorted(allowed_codes),
            "type_qids": type_qids,
            "query": "non-deprecated inbound P144; P31 in supported specific types; no recursive traversal",
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
            "types": sorted(allowed_codes),
            "candidates": [
                {key: row[key] for key in ("qid", "seed_qid", "label", "expected_type", "expected_year")}
                for row in rows
            ],
        }, indent=2, ensure_ascii=False, sort_keys=True)))

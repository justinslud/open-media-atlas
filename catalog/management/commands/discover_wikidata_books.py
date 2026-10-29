"""Discover books that Wikidata already links to Open Library.

Random Open Library scans are almost absent from Wikidata (about 1%). This
command inverts the flow: it asks Wikidata for book items that carry an Open
Library work ID, best-known first, so imported books arrive with creators,
dates, types, and relationship claims already in place.

It only writes a candidate manifest. Staging happens in import_wikidata_books.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.importers.wikidata import WikidataClient
from catalog.models import ExternalIdentifier

QUERY_SERVICE = "https://query.wikidata.org/sparql"

# Book, novel, literary work, written work, short story, novella.
BOOK_TYPES = ("wd:Q571", "wd:Q8261", "wd:Q7725634", "wd:Q47461344", "wd:Q49084", "wd:Q1279564")


class Command(BaseCommand):
    help = "Build a candidate manifest of Wikidata books that carry an Open Library work ID."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=2000)
        parser.add_argument("--scan", type=int, default=0,
                            help="Rows to inspect before filtering known records (default 3x limit)")
        parser.add_argument("--min-sitelinks", type=int, default=0)
        parser.add_argument("--timeout", type=int, default=120)
        parser.add_argument("--include-existing", action="store_true",
                            help="Keep items already present in the catalog")
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--output", type=Path, help="Discovery report path")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        scan = options["scan"] or min(5000, options["limit"] * 3)
        if not options["limit"] <= scan <= 5000:
            raise CommandError("--scan must be between --limit and 5000")
        started = time.monotonic()
        client = WikidataClient(timeout=options["timeout"], max_requests=10)

        values = " ".join(BOOK_TYPES)
        query = f"""SELECT ?item ?olid ?sitelinks WHERE {{
          ?item wdt:P648 ?olid .
          FILTER(STRSTARTS(STR(?olid), "OL") && STRENDS(STR(?olid), "W"))
          VALUES ?type {{ {values} }}
          ?item wdt:P31 ?type .
          ?item wikibase:sitelinks ?sitelinks .
          FILTER(?sitelinks >= {int(options['min_sitelinks'])})
        }} ORDER BY DESC(?sitelinks) LIMIT {int(scan)}"""

        try:
            data = client.get_json(QUERY_SERVICE, {"query": query, "format": "json"}, attempts=3)
        except Exception as exc:
            raise CommandError(f"Wikidata book discovery failed: {exc}") from exc

        rows = []
        for binding in data.get("results", {}).get("bindings", []):
            qid = binding["item"]["value"].rsplit("/", 1)[-1]
            olid = binding["olid"]["value"].removeprefix("/works/")
            rows.append({
                "qid": qid,
                "olid": olid,
                "sitelinks": int(binding.get("sitelinks", {}).get("value", 0) or 0),
            })

        known = {
            value for value in ExternalIdentifier.objects.filter(
                scheme="wikidata", value__in=[row["qid"] for row in rows]
            ).values_list("value", flat=True)
        }
        ol_known = {
            value for value in ExternalIdentifier.objects.filter(
                scheme="ol_work", value__in=[row["olid"] for row in rows]
            ).values_list("value", flat=True)
        }
        if not options["include_existing"]:
            rows = [row for row in rows if row["qid"] not in known and row["olid"] not in ol_known]

        manifest = {
            "version": "2026-10-28-wikidata-books",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Wikidata Query Service",
            "method": "items with P648 Open Library work IDs and a book-like P31, ordered by sitelink count",
            "limits": {"requested": options["limit"], "scanned": scan, "min_sitelinks": options["min_sitelinks"]},
            "counts": {
                "returned": len(rows) + (0 if options["include_existing"] else len(known | ol_known)),
                "scanned": scan,
                "candidates": len(rows),
                "skipped_already_present": 0 if options["include_existing"] else len(known | ol_known),
            },
            "candidates": rows,
        }
        options["manifest"].parent.mkdir(parents=True, exist_ok=True)
        options["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

        report = {
            "manifest": str(options["manifest"]),
            "candidates": len(rows),
            "skipped_already_present": manifest["counts"]["skipped_already_present"],
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "network_requests": client.requests,
        }
        if options["output"]:
            options["output"].parent.mkdir(parents=True, exist_ok=True)
            options["output"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps(report, sort_keys=True))

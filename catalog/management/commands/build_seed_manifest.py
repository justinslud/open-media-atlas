"""Write a seed manifest from catalog state.

Enrichment and relationship commands read a manifest of seed QIDs. Building it
from a query, instead of a hand-written list, keeps seed selection explicit and
repeatable ("the best-known dated books", not "whatever was imported last").
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.models import ExternalIdentifier, Work
from catalog.ranking import sitelink_count


class Command(BaseCommand):
    help = "Build a seed manifest from catalog state."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--depth", choices=("index", "editorial", "ambient"))
        parser.add_argument("--work-type")
        parser.add_argument("--min-sitelinks", type=int, default=0)
        parser.add_argument("--require-date", action="store_true")
        parser.add_argument("--require-creator", action="store_true")
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument(
            "--from", dest="source", choices=("catalog", "unresolved-claims"), default="catalog",
            help="catalog: filter the public catalog; unresolved-claims: works whose cached "
                 "claims never produced a proposal.",
        )

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 500:
            raise CommandError("--limit must be 1..500")
        works = Work.objects.filter(
            visibility=Work.Visibility.PUBLIC, is_demo=False
        ).prefetch_related("source_records", "credits", "identifiers")
        if options["depth"]:
            works = works.filter(depth=options["depth"])
        if options["work_type"]:
            works = works.filter(work_type_id=options["work_type"])
        if options["require_date"]:
            works = works.filter(first_publication_year__isnull=False)
        if options["require_creator"]:
            works = works.filter(credits__isnull=False).distinct()
        if options["source"] == "unresolved-claims":
            from catalog import diagnostics

            index = diagnostics.build_index()
            backlog = set(diagnostics.unresolved_claim_work_ids(index))
            works = works.filter(pk__in=backlog)
            claim_counts = {work_id: len(index["claims"].get(work_id, [])) for work_id in backlog}
        else:
            claim_counts = {}

        rows = []
        for work in works:
            qid = next(
                (item.value for item in work.identifiers.all() if item.scheme == "wikidata"), ""
            )
            if not qid:
                continue
            sitelinks = sitelink_count(work)
            if sitelinks < options["min_sitelinks"]:
                continue
            rows.append({"qid": qid, "label": work.title, "work": work.pk, "sitelinks": sitelinks})

        rows.sort(key=lambda row: (-row["sitelinks"], row["qid"]))
        if options["source"] == "unresolved-claims":
            # Backlog first: the point is to drain claims nobody has resolved yet.
            rows.sort(key=lambda row: (-claim_counts.get(row["work"], 0), -row["sitelinks"], row["qid"]))
        rows = rows[: options["limit"]]
        if not rows:
            raise CommandError("no works matched the selection")

        manifest = {
            "version": "2026-10-28-catalog-seeds",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "selection": {
                "source": options["source"],
                "depth": options["depth"],
                "work_type": options["work_type"],
                "min_sitelinks": options["min_sitelinks"],
                "require_date": options["require_date"],
                "require_creator": options["require_creator"],
                "limit": options["limit"],
            },
            "seeds": rows,
        }
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({"seeds": len(rows), "manifest": str(options["output"])}, sort_keys=True))

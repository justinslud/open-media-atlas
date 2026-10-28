"""Fill missing dates on Open Library drafts from edition publish dates.

The bulk importer reads work-level first_publish_date only. Many works lack
that field even when their editions have explicit publish_date values. This
command uses the local extract's edition rows and writes only to drafts.
"""
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.models import ExternalIdentifier, Work


YEAR = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)")


def first_year(text):
    match = YEAR.search(str(text or ""))
    return int(match.group(1)) if match else None


class Command(BaseCommand):
    help = "Fill draft Open Library dates from local edition publish_date values."

    def add_arguments(self, parser):
        parser.add_argument("--extract", type=Path, required=True)
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")
        records = options["extract"] / "records.jsonl"
        if not records.is_file():
            raise CommandError(f"missing {records}")

        updated = []
        unresolved = []
        with records.open() as stream:
            for line in stream:
                row = json.loads(line)
                work_data = row["work"]
                olid = str(work_data.get("key", "")).removeprefix("/works/")
                if not olid:
                    continue
                identifier = ExternalIdentifier.objects.filter(scheme="ol_work", value=olid).select_related("work").first()
                if not identifier:
                    continue
                work = identifier.work
                if work.visibility != Work.Visibility.DRAFT or work.first_publication_year:
                    continue
                candidates = []
                for edition in row.get("editions") or []:
                    for field in ("publish_date", "copyright_date"):
                        year = first_year(edition.get(field))
                        if year:
                            candidates.append({
                                "text": str(edition.get(field)),
                                "year": year,
                                "field": field,
                                "edition": edition.get("key"),
                            })
                if not candidates:
                    unresolved.append({"work": work.pk, "olid": olid, "title": work.title})
                    continue
                selected = min(candidates, key=lambda item: (item["year"], item["edition"] or ""))
                updated.append({
                    "work": work.pk,
                    "olid": olid,
                    "title": work.title,
                    "date_text": selected["text"],
                    "year": selected["year"],
                    "edition": selected["edition"],
                })
                if options["confirm"]:
                    work.first_publication_date_text = selected["text"][:80]
                    work.first_publication_year = selected["year"]
                    work.date_kind = "publication"
                    work.date_evidence = {
                        "date_text": selected["text"],
                        "property": f"edition:{selected['field']}",
                        "source_url": f"https://openlibrary.org{selected['edition']}",
                        "selection_rule": "earliest edition date with a four-digit year",
                        "candidates": candidates,
                    }
                    work.save(update_fields=(
                        "first_publication_date_text", "first_publication_year",
                        "date_kind", "date_evidence", "updated_at",
                    ))
                if len(updated) >= options["limit"]:
                    break

        self.stdout.write(self.style.SUCCESS(json.dumps({
            "confirm": options["confirm"],
            "updated": len(updated),
            "unresolved": len(unresolved),
            "sample": updated[:5],
            "unresolved_sample": unresolved[:5],
        }, sort_keys=True)))
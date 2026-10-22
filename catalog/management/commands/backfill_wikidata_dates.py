"""Backfill missing work years from cached Wikidata date claims or title years.

Selection is explicit and conservative. It prefers the date property that
matches the work's medium (first performance for stage works, release/start for
screen works, publication for text), uses the earliest assertion when several
differ, and retains every candidate in date_evidence. A trailing parenthetical
year in the title is a last-resort fallback and is marked unverified.
"""
import json
import re

from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.dates import (
    candidates_for,
    choose_date,
    date_kind_for_wikidata_property as date_kind_for,
)
from catalog.models import Work

TITLE_PARENTHETICAL = re.compile(r"\(([^()]*)\)\s*$")
YEAR_IN_TEXT = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)")
YEAR_RANGE = re.compile(r"\d{4}\s*[-–—]\s*\d{4}")


def title_year(title):
    """Return a single four-digit year from the final title parenthetical.

    Ranges and parentheticals with multiple years are deliberately rejected;
    they are too ambiguous to promote without review.
    """
    match = TITLE_PARENTHETICAL.search(title or "")
    if not match:
        return None
    content = match.group(1)
    if YEAR_RANGE.search(content):
        return None
    years = YEAR_IN_TEXT.findall(content)
    return int(years[0]) if len(years) == 1 else None


class Command(BaseCommand):
    help = (
        "Backfill missing work dates from cached Wikidata P577/P1191/P1619/P580/"
        "P2754/P10135/P585/P571 claims, then trailing title years."
    )

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("public", "golden", "all"), default="public")
        parser.add_argument("--ids", help="Comma-separated work IDs to limit the pass.")
        parser.add_argument(
            "--complete-year-only",
            action="store_true",
            help="Only fill display text/evidence for records that already have a year.",
        )
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        works = Work.objects.filter(is_demo=False)
        if options["scope"] == "public":
            works = works.filter(visibility=Work.Visibility.PUBLIC)
        elif options["scope"] == "golden":
            works = works.filter(depth="editorial")
        if options["ids"]:
            ids = [int(item) for item in options["ids"].split(",") if item.strip().isdigit()]
            works = works.filter(pk__in=ids)
        if options["complete_year_only"]:
            works = works.filter(
                first_publication_year__isnull=False, first_publication_date_text=""
            )
        else:
            works = works.filter(first_publication_year__isnull=True)
        report = {
            "updated": [],
            "completed": [],
            "unresolved_count": 0,
            "unresolved": [],
            "confirm": options["confirm"],
            "scope": options["scope"],
            "complete_year_only": options["complete_year_only"],
        }
        for work in works.select_related("work_type").prefetch_related("source_records__source"):
            record = next(
                (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                None,
            )
            payload = record.raw_payload if record and isinstance(record.raw_payload, dict) else {}
            qid = payload.get("id") or (record.external_key if record else "")
            source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""
            medium = work.work_type.medium

            if options["complete_year_only"]:
                evidence = {
                    "date_text": str(work.first_publication_year),
                    "property": "existing_year",
                    "source_url": source_url,
                    "selection_rule": "year already present; display text completed without re-verification",
                    "meaning_unverified": True,
                }
                report["completed"].append(
                    {"work": work.pk, "title": work.title, "year": work.first_publication_year}
                )
                if options["confirm"]:
                    Work.objects.filter(pk=work.pk).update(
                        first_publication_date_text=str(work.first_publication_year),
                        date_evidence=evidence,
                        updated_at=timezone.now(),
                    )
                continue

            chosen = choose_date(payload, medium)
            if not chosen:
                fallback_year = title_year(work.title) if qid else None
                if fallback_year:
                    chosen = {
                        "property": "title",
                        "year": fallback_year,
                        "text": str(fallback_year),
                        "selected": {
                            "statement_id": "",
                            "precision": 9,
                            "rank": "normal",
                            "value": None,
                        },
                        "candidates": [
                            {
                                "text": str(fallback_year),
                                "year": fallback_year,
                                "precision": 9,
                                "rank": "normal",
                                "statement_id": "",
                            }
                        ],
                        "rule": "title parenthetical year; meaning unverified",
                        "meaning_unverified": True,
                    }
            if not chosen:
                report["unresolved_count"] += 1
                if len(report["unresolved"]) < 200:
                    report["unresolved"].append(
                        {"work": work.pk, "title": work.title, "reason": "no usable date claim or title year"}
                    )
                continue
            selected = chosen["selected"]
            kind = date_kind_for(chosen["property"], medium)
            evidence = {
                "date_text": chosen["text"],
                "property": chosen["property"],
                "statement_id": selected["statement_id"],
                "precision": selected["precision"],
                "rank": selected["rank"],
                "value": selected["value"],
                "source_url": source_url,
                "selection_rule": chosen["rule"],
                "candidates": [
                    {
                        "text": row["text"],
                        "year": row["year"],
                        "precision": row["precision"],
                        "rank": row["rank"],
                        "statement_id": row["statement_id"],
                    }
                    for row in chosen["candidates"]
                ],
            }
            if chosen.get("meaning_unverified"):
                evidence["meaning_unverified"] = True
            end_candidates = candidates_for(payload, "P582")
            if end_candidates:
                evidence["end_date_candidates"] = [
                    {
                        "text": row["text"],
                        "year": row["year"],
                        "precision": row["precision"],
                        "rank": row["rank"],
                        "statement_id": row["statement_id"],
                    }
                    for row in end_candidates
                ]
            report["updated"].append(
                {
                    "work": work.pk,
                    "title": work.title,
                    "year": chosen["year"],
                    "text": chosen["text"],
                    "property": chosen["property"],
                    "rule": chosen["rule"],
                    "date_kind": kind,
                    "meaning_unverified": bool(chosen.get("meaning_unverified")),
                }
            )
            if options["confirm"]:
                Work.objects.filter(pk=work.pk).update(
                    first_publication_year=chosen["year"],
                    first_publication_date_text=chosen["text"],
                    date_kind=kind,
                    date_evidence=evidence,
                    updated_at=timezone.now(),
                )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))

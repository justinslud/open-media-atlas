"""Remove supplier quotation marks wrapped around already-imported titles.

Only titles whose cached supplier payload states the same quoted text are
touched, so editor-written titles are never rewritten. Dry run by default.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from catalog.importers.wikidata import strip_wrapping_quotes
from catalog.models import SourceRecord, Work


class Command(BaseCommand):
    help = "Strip wrapping quotation marks from imported titles that came quoted."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        # Supplier quotes appear as ASCII or typographic pairs at either edge.
        quoted = (
            Q(title__startswith='"') | Q(title__endswith='"')
            | Q(title__startswith="\u201c") | Q(title__endswith="\u201d")
            | Q(title__startswith="\u201e") | Q(title__startswith="\u00ab") | Q(title__endswith="\u00bb")
        )
        works = (
            Work.objects.filter(quoted)
            .prefetch_related("source_records")
            .order_by("pk")
        )
        if options["limit"]:
            works = works[: options["limit"]]

        rows, changed = [], []
        for work in works:
            stripped = strip_wrapping_quotes(work.title)
            if stripped == work.title:
                continue
            payloads = [record.raw_payload for record in work.source_records.all() if isinstance(record.raw_payload, dict)]
            supplier_matches = any(
                value == work.title
                for payload in payloads
                for value in self._supplier_titles(payload)
            )
            if not supplier_matches:
                continue
            rows.append({"work": work.pk, "before": work.title, "after": stripped})
            changed.append((work.pk, stripped))

        if options["confirm"] and changed:
            with transaction.atomic():
                for work_id, title in changed:
                    work = Work.objects.select_for_update().get(pk=work_id)
                    work.title = title
                    work.save(update_fields=("title", "updated_at"))

        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps({
                "confirm": options["confirm"],
                "candidates": len(rows),
                "sample": rows[:10],
            }, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({"confirm": options["confirm"], "candidates": len(rows), "sample": rows[:3]}, sort_keys=True, ensure_ascii=False))

    def _supplier_titles(self, payload):
        for claim in payload.get("claims", {}).get("P1476", []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, dict) and value.get("text"):
                yield value["text"].strip()
        for data in payload.get("labels", {}).values():
            if isinstance(data, dict) and data.get("value"):
                yield data["value"].strip()

"""Report public works that fail the shared publication rules.

This is a read-only audit. It writes a JSON report and never edits records, so
the public catalog can be measured before deciding what to fix or demote.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog.models import Work
from catalog.publication import WARNING_LABELS, publication_warnings


class Command(BaseCommand):
    help = "Audit public works against the shared publication rules."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, default=Path("docs/publication-quality-latest.json"))
        parser.add_argument("--limit", type=int, default=0, help="Only inspect this many public works")

    def handle(self, *args, **options):
        works = (
            Work.objects.filter(visibility=Work.Visibility.PUBLIC)
            .select_related("work_type")
            .prefetch_related("credits")
            .order_by("pk")
        )
        if options["limit"]:
            works = works[: options["limit"]]

        rows = []
        counts = Counter()
        for work in works:
            warnings = publication_warnings(work)
            if not warnings:
                continue
            counts.update(warnings)
            rows.append({
                "work": work.pk,
                "title": work.title,
                "type": work.work_type_id,
                "year": work.first_publication_year,
                "depth": work.depth,
                "warnings": warnings,
            })

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "audited": works.count() if isinstance(works, list) else None,
            "flagged": len(rows),
            "summary": {code: counts[code] for code in sorted(counts)},
            "labels": {code: WARNING_LABELS.get(code, code) for code in counts},
            "rows": rows,
        }
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(f"flagged={len(rows)} report={options['output']}")
        for code in sorted(counts):
            self.stdout.write(f"  {code}: {counts[code]}")

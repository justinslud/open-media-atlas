"""Report public works that have no accepted relationship in either direction.

An orphan is not automatically a defect: many works genuinely carry no
relationship claims. The useful question is *why* a record is alone, so this
report separates the same states the diagnostics page shows:

* ``no_claims`` — no supported relationship property in the cached payload
* ``claims_unresolved`` — claims exist but no proposal references them
* ``proposal_pending`` — a proposal exists but is still pending
* ``proposal_rejected`` — proposals exist but none was accepted

Definitions live in :mod:`catalog.diagnostics`, so this report and the staff
diagnostics page cannot disagree. It is read-only.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog import diagnostics
from catalog.models import Work


class Command(BaseCommand):
    help = "Report public works with no accepted relationships, grouped by cause."

    def add_arguments(self, parser):
        parser.add_argument("--depth", choices=("index", "editorial", "ambient"))
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--output", type=Path, default=Path("docs/orphans-latest.json"))

    def handle(self, *args, **options):
        index = diagnostics.build_index()
        works = Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False)
        if options["depth"]:
            works = works.filter(depth=options["depth"])
        works = works.order_by("pk")

        rows = []
        for work in works.only("id", "title", "depth", "work_type_id", "first_publication_year"):
            state = index["states"].get(work.pk, diagnostics.STATE_NO_CLAIMS)
            if state == diagnostics.STATE_CONNECTED:
                continue
            claims = index["claims"].get(work.pk, [])
            rows.append({
                "work": work.pk,
                "title": work.title,
                "depth": work.depth,
                "type": work.work_type_id,
                "year": work.first_publication_year,
                "state": state,
                "claims": len(claims),
                "outcomes": {
                    outcome: sum(1 for claim in claims if claim.outcome == outcome)
                    for outcome in sorted({claim.outcome for claim in claims})
                },
            })
        if options["limit"]:
            rows = rows[: options["limit"]]

        summary = {}
        for row in rows:
            summary[row["state"]] = summary.get(row["state"], 0) + 1
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "depth": options["depth"] or "all",
            "orphans": len(rows),
            "summary": summary,
            "states": diagnostics.STATE_DEFINITIONS,
            "rows": rows,
        }
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(f"orphans={len(rows)} report={options['output']}")
        for state, count in sorted(summary.items(), key=lambda item: -item[1]):
            self.stdout.write(f"  {state}: {count}")

"""Report public works that have no accepted relationship in either direction.

An orphan is not automatically a defect: many works genuinely carry no
relationship claims. The useful question is *why* a record is alone, so this
report separates four states:

* ``no_claims`` — no supported relationship property exists in the cached payload
* ``claims_unresolved`` — claims exist but no proposal was ever created
* ``proposal_pending`` — a proposal exists but is still pending
* ``proposal_rejected`` — every proposal for the work was rejected

It is read-only.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog.models import ImportRelationshipProposal, SourceRecord, Work, WorkRelationship

RELATIONSHIP_PROPERTIES = ("P144", "P155", "P156", "P179", "P629", "P941", "P737", "P4969")


class Command(BaseCommand):
    help = "Report public works with no accepted relationships, grouped by cause."

    def add_arguments(self, parser):
        parser.add_argument("--depth", choices=("index", "editorial", "ambient"))
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--output", type=Path, default=Path("docs/orphans-latest.json"))

    def handle(self, *args, **options):
        works = Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False)
        if options["depth"]:
            works = works.filter(depth=options["depth"])
        works = works.prefetch_related("source_records").order_by("pk")

        connected = set(
            WorkRelationship.objects.filter(review_status="accepted").values_list("from_work_id", flat=True)
        ) | set(
            WorkRelationship.objects.filter(review_status="accepted").values_list("to_work_id", flat=True)
        )
        candidates = [work for work in works if work.pk not in connected]
        if options["limit"]:
            candidates = candidates[: options["limit"]]

        pending = set(
            ImportRelationshipProposal.objects.filter(
                status=ImportRelationshipProposal.Status.PENDING
            ).values_list("from_work_id", flat=True)
        ) | set(
            ImportRelationshipProposal.objects.filter(
                status=ImportRelationshipProposal.Status.PENDING
            ).values_list("to_work_id", flat=True)
        )
        rejected = set(
            ImportRelationshipProposal.objects.filter(
                status=ImportRelationshipProposal.Status.REJECTED
            ).values_list("from_work_id", flat=True)
        ) | set(
            ImportRelationshipProposal.objects.filter(
                status=ImportRelationshipProposal.Status.REJECTED
            ).values_list("to_work_id", flat=True)
        )
        proposed = set(
            ImportRelationshipProposal.objects.values_list("from_work_id", flat=True)
        ) | set(ImportRelationshipProposal.objects.values_list("to_work_id", flat=True))

        counts = Counter()
        rows = []
        for work in candidates:
            state = self._state(work, pending, rejected, proposed)
            counts[state] += 1
            rows.append({
                "work": work.pk,
                "title": work.title,
                "depth": work.depth,
                "type": work.work_type_id,
                "year": work.first_publication_year,
                "state": state,
            })

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "depth": options["depth"] or "all",
            "orphans": len(rows),
            "summary": dict(counts),
            "states": {
                "no_claims": "no supported relationship property in the cached payload",
                "claims_unresolved": "claims exist but no proposal was created",
                "proposal_pending": "a proposal exists but is still pending",
                "proposal_rejected": "every proposal for this work was rejected",
            },
            "rows": rows,
        }
        options["output"].parent.mkdir(parents=True, exist_ok=True)
        options["output"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(f"orphans={len(rows)} report={options['output']}")
        for state, count in counts.most_common():
            self.stdout.write(f"  {state}: {count}")

    def _state(self, work, pending, rejected, proposed):
        if work.pk in pending:
            return "proposal_pending"
        if self._has_claims(work):
            return "claims_unresolved" if work.pk not in proposed else "proposal_rejected"
        return "no_claims" if work.pk not in rejected else "proposal_rejected"

    def _has_claims(self, work):
        for record in work.source_records.all():
            payload = record.raw_payload
            if not isinstance(payload, dict):
                continue
            claims = payload.get("claims", {})
            if isinstance(claims, dict) and any(claims.get(prop) for prop in RELATIONSHIP_PROPERTIES):
                return True
        return False

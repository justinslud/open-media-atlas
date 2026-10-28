"""Reject proposals that cannot pass under the current rules.

Rejection is explicit and report-driven: the command reads a triage report and
only touches rows whose decision and reason codes match the requested filters.
It never approves anything and never edits supplier evidence.
"""
import json
from collections import Counter
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog.models import ImportRelationshipProposal


# Faults that no later pipeline pass can repair: identity or evidence is wrong,
# so the assertion must not stay in the review queue.
DETERMINISTIC_REASONS = (
    "self_link",
    "entity_mismatch",
    "multiple_qids",
    "statement_mismatch",
    "no_qid",
    "deprecated",
    "unsupported_property",
    "unsupported_relationship",
    "demo_work",
    "suppressed_work",
    "already_accepted",
    "edge_exists",
)


class Command(BaseCommand):
    help = "Reject proposals selected from a triage report."

    def add_arguments(self, parser):
        parser.add_argument("--report", type=Path, required=True)
        parser.add_argument("--decisions", default="red")
        parser.add_argument("--reasons", default="", help="Comma-separated reason codes; empty means any")
        parser.add_argument("--deterministic", action="store_true",
                            help=f"Only rows carrying a repair-impossible fault: {', '.join(DETERMINISTIC_REASONS)}")
        parser.add_argument("--reviewer", default="admin")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["report"].is_file():
            raise CommandError(f"missing {options['report']}")
        decisions = {value.strip() for value in options["decisions"].split(",") if value.strip()}
        reasons = {value.strip() for value in options["reasons"].split(",") if value.strip()}
        report = json.loads(options["report"].read_text())

        rows = []
        for row in report.get("rows", []):
            if row.get("decision") not in decisions:
                continue
            if reasons and not reasons & set(row.get("reasons", [])):
                continue
            if options["deterministic"] and not set(DETERMINISTIC_REASONS) & set(row.get("reasons", [])):
                continue
            rows.append(row)
        if options["limit"]:
            rows = rows[: options["limit"]]
        if not rows:
            self.stdout.write("no matching proposals")
            return

        proposals = list(
            ImportRelationshipProposal.objects.filter(
                pk__in=[row["proposal_id"] for row in rows],
                status=ImportRelationshipProposal.Status.PENDING,
            )
        )
        counts = Counter(code for row in rows for code in row.get("reasons", []))
        report_out = {
            "report": str(options["report"]),
            "confirm": options["confirm"],
            "selected": len(rows),
            "pending_matched": len(proposals),
            "reasons": dict(counts),
            "proposal_ids": [proposal.pk for proposal in proposals],
        }

        if options["confirm"] and proposals:
            reviewer = get_user_model().objects.get(username=options["reviewer"])
            with transaction.atomic():
                ImportRelationshipProposal.objects.filter(
                    pk__in=[proposal.pk for proposal in proposals],
                    status=ImportRelationshipProposal.Status.PENDING,
                ).update(
                    status=ImportRelationshipProposal.Status.REJECTED,
                    reviewer=reviewer,
                    reviewed_at=timezone.now(),
                )

        self.stdout.write(
            f"confirm={options['confirm']} selected={len(rows)} "
            f"pending_matched={len(proposals)} rejected={len(proposals) if options['confirm'] else 0}"
        )
        for code, count in counts.most_common():
            self.stdout.write(f"  {code}: {count}")

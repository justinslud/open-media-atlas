"""Repair relationship edges that the resolver stored in the wrong direction.

Older resolver runs wrote the claim target as ``from_work`` and the seed as
``to_work``. For P144/P155/P156/P179/P629/P941/P737 the claim lives on the seed,
so the seed is the subject and belongs in ``from_work``. Evidence is untouched;
only the endpoint order changes.

Detection is explicit: resolver evidence carries a ``relationship_code`` key,
which supplier-discovery evidence never does.
"""
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from catalog.models import ImportRelationshipProposal, WorkRelationship

SWAPPED_PROPERTIES = {"P144", "P155", "P156", "P179", "P629", "P941", "P737"}


def _is_resolver_evidence(evidence):
    return (
        isinstance(evidence, dict)
        and evidence.get("property_id") in SWAPPED_PROPERTIES
        and "relationship_code" in evidence
    )


class Command(BaseCommand):
    help = "Swap endpoints on resolver-created edges that were stored backwards."

    def add_arguments(self, parser):
        parser.add_argument("--report", type=Path)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        proposals = [
            proposal for proposal in ImportRelationshipProposal.objects.select_related("relationship_type")
            if _is_resolver_evidence(proposal.evidence)
        ]
        relationships = [
            relationship for relationship in WorkRelationship.objects.select_related("relationship_type")
            if _is_resolver_evidence(relationship.evidence)
        ]

        proposal_changes, proposal_duplicates = [], 0
        for proposal in proposals:
            if ImportRelationshipProposal.objects.filter(
                from_work_id=proposal.to_work_id,
                to_work_id=proposal.from_work_id,
                relationship_type_id=proposal.relationship_type_id,
                status__in=(
                    ImportRelationshipProposal.Status.PENDING,
                    ImportRelationshipProposal.Status.APPROVED,
                ),
            ).exclude(pk=proposal.pk).exists():
                proposal_duplicates += 1
                continue
            proposal_changes.append(proposal.pk)

        relationship_changes, relationship_duplicates = [], 0
        for relationship in relationships:
            if WorkRelationship.objects.filter(
                from_work_id=relationship.to_work_id,
                to_work_id=relationship.from_work_id,
                relationship_type_id=relationship.relationship_type_id,
            ).exclude(pk=relationship.pk).exists():
                relationship_duplicates += 1
                continue
            relationship_changes.append(relationship.pk)

        counts = Counter(
            proposal.relationship_type.code for proposal in proposals if proposal.pk in set(proposal_changes)
        )

        if options["confirm"]:
            with transaction.atomic():
                for proposal_id in proposal_changes:
                    proposal = ImportRelationshipProposal.objects.select_for_update().get(pk=proposal_id)
                    proposal.from_work_id, proposal.to_work_id = proposal.to_work_id, proposal.from_work_id
                    proposal.save(update_fields=("from_work", "to_work"))
                for relationship_id in relationship_changes:
                    relationship = WorkRelationship.objects.select_for_update().get(pk=relationship_id)
                    relationship.from_work_id, relationship.to_work_id = (
                        relationship.to_work_id, relationship.from_work_id,
                    )
                    relationship.evidence = dict(relationship.evidence, direction_repaired_at=timezone.now().isoformat())
                    relationship.save(update_fields=("from_work", "to_work", "evidence"))

        report = {
            "confirm": options["confirm"],
            "proposals_swapped": len(proposal_changes),
            "proposals_skipped_duplicate": proposal_duplicates,
            "relationships_swapped": len(relationship_changes),
            "relationships_skipped_duplicate": relationship_duplicates,
            "proposal_codes": dict(counts),
        }
        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps(report, sort_keys=True))

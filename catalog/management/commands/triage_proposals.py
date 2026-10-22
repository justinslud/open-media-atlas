"""Triage pending Wikidata relationship proposals in one bounded pass.

The command is deliberately conservative: only fully supported, dated,
specific-type adaptations are approved and published. Everything else stays
pending with a reason code for exception review. It never rejects proposals.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as django_timezone
from django.utils.text import slugify

from catalog.models import (
    ExternalIdentifier,
    ImportRelationshipProposal,
    Work,
    WorkRelationship,
)

GENERIC_TYPES = {"book", "creative-work", "literary-work", "written-work", "unknown"}
MIN_YEAR = 1400
MAX_FUTURE_YEARS = 5

RED_REASONS = {
    "not_based_on": "relationship type is not based-on",
    "not_p144": "evidence is not a P144 claim",
    "deprecated": "P144 statement is deprecated",
    "no_qid": "adaptation has no Wikidata QID",
    "multiple_qids": "adaptation has multiple Wikidata QIDs",
    "entity_mismatch": "P144 entity does not match the adaptation QID",
    "statement_mismatch": "proposal statement ID does not match its evidence",
    "self_link": "work is linked to itself",
    "demo_work": "demo work",
    "suppressed_work": "suppressed work",
    "target_not_seed": "target is not a public editorial seed",
    "no_title": "title is unknown or a bare QID",
    "already_accepted": "an accepted edge already exists",
    "edge_exists": "a non-accepted edge already exists for this pair",
    "year_inversion": "adaptation year precedes the source year",
    "year_out_of_range": "adaptation year is outside the supported range",
}

AMBER_REASONS = {
    "no_year": "adaptation has no year",
    "seed_no_year": "source seed has no year, so order cannot be checked",
    "generic_type": "public type is still generic",
    "title_collision": "adaptation title matches the source title",
    "date_unverified": "date is marked unverified or has unknown meaning",
    "duplicate_pending": "another pending proposal covers the same edge",
    "no_sitelink": "adaptation has no Wikipedia sitelink",
}

WARNING_REASONS = {
    "no_image": "no licensed image; placeholder will remain",
    "eponymous_title": "same title as the source; distinct type and year keep the identity unambiguous",
}


def sitelink_count(work):
    for record in work.source_records.all():
        payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        if str(payload.get("id", "")).startswith("Q"):
            sitelinks = payload.get("sitelinks", {})
            if isinstance(sitelinks, dict):
                return len(sitelinks)
    return 0


def _same_title(work, seed):
    return (
        work.has_known_title
        and seed.has_known_title
        and slugify(work.title) == slugify(seed.title)
    )


def _reason_codes(proposal, qid, qid_count, edge_status, pending_edge_count, today_year, sitelinks):
    work = proposal.from_work
    seed = proposal.to_work
    evidence = proposal.evidence if isinstance(proposal.evidence, dict) else {}
    red, amber = [], []

    if proposal.relationship_type.code != "based-on":
        red.append("not_based_on")
    if evidence.get("property_id") != "P144":
        red.append("not_p144")
    if evidence.get("rank") == "deprecated":
        red.append("deprecated")
    if not qid:
        red.append("no_qid")
    elif qid_count != 1:
        red.append("multiple_qids")
    if qid and evidence.get("entity_id") != qid:
        red.append("entity_mismatch")
    if evidence.get("statement_id") and evidence.get("statement_id") != proposal.statement_id:
        red.append("statement_mismatch")
    if work.pk == seed.pk:
        red.append("self_link")
    if work.is_demo:
        red.append("demo_work")
    if work.visibility == Work.Visibility.SUPPRESSED:
        red.append("suppressed_work")
    if seed.visibility != Work.Visibility.PUBLIC or seed.depth != "editorial":
        red.append("target_not_seed")
    if not work.has_known_title:
        red.append("no_title")
    if edge_status == "accepted":
        red.append("already_accepted")
    elif edge_status:
        red.append("edge_exists")
    if work.first_publication_year and seed.first_publication_year and work.first_publication_year < seed.first_publication_year:
        red.append("year_inversion")
    if work.first_publication_year and not (MIN_YEAR <= work.first_publication_year <= today_year + MAX_FUTURE_YEARS):
        red.append("year_out_of_range")

    if not work.first_publication_year:
        amber.append("no_year")
    if not seed.first_publication_year:
        amber.append("seed_no_year")
    if work.public_type_code in GENERIC_TYPES:
        amber.append("generic_type")
    if _same_title(work, seed) and (
        work.public_type_code == getattr(seed, "public_type_code", None)
        or work.first_publication_year == seed.first_publication_year
        or not work.first_publication_year
        or not seed.first_publication_year
    ):
        amber.append("title_collision")
    date_evidence = work.date_evidence if isinstance(work.date_evidence, dict) else {}
    if work.date_kind == "unknown" or date_evidence.get("meaning_unverified"):
        amber.append("date_unverified")
    if pending_edge_count > 1:
        amber.append("duplicate_pending")
    if not sitelinks:
        amber.append("no_sitelink")
    return red, amber


def evaluate_proposal(
    proposal,
    qid,
    qid_count,
    edge_status,
    pending_edge_count,
    today_year,
    sitelinks,
):
    red, amber = _reason_codes(
        proposal, qid, qid_count, edge_status, pending_edge_count, today_year, sitelinks
    )
    warnings = []
    if not proposal.from_work.image_url:
        warnings.append("no_image")
    if _same_title(proposal.from_work, proposal.to_work) and "title_collision" not in amber:
        warnings.append("eponymous_title")
    if red:
        decision = "red"
    elif amber:
        decision = "amber"
    else:
        decision = "green"
    return decision, red + amber, warnings


def _row(proposal, decision, reasons, warnings, qid, sitelinks):
    work = proposal.from_work
    seed = proposal.to_work
    return {
        "proposal_id": proposal.pk,
        "run_id": proposal.run_id,
        "decision": decision,
        "reasons": reasons,
        "reason_details": [
            RED_REASONS.get(code) or AMBER_REASONS.get(code) or WARNING_REASONS.get(code, code)
            for code in reasons
        ],
        "warnings": warnings,
        "work_id": work.pk,
        "qid": qid,
        "title": work.title,
        "type": work.public_type_code,
        "year": work.first_publication_year,
        "date_text": work.first_publication_date_text,
        "date_kind": work.date_kind,
        "visibility": work.visibility,
        "sitelinks": sitelinks,
        "seed_id": seed.pk,
        "seed": seed.title,
        "seed_year": seed.first_publication_year,
    }


class Command(BaseCommand):
    help = "Triage pending relationship proposals; publish only clean groups."

    def add_arguments(self, parser):
        parser.add_argument("--reviewer", default="admin")
        parser.add_argument("--output", default="docs/proposal-triage-latest.json")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--approve-only", action="store_true", help="Approve green edges but leave endpoints draft.")

    def handle(self, *args, **options):
        reviewer = get_user_model().objects.get(username=options["reviewer"]) if options["confirm"] else None
        if options["limit"] and options["limit"] < 1:
            raise CommandError("--limit must be positive")

        proposals = list(
            ImportRelationshipProposal.objects.filter(status=ImportRelationshipProposal.Status.PENDING)
            .select_related("from_work", "from_work__work_type", "to_work", "relationship_type", "source")
            .prefetch_related("from_work__source_records")
            .order_by("from_work__title", "from_work_id")
        )
        if options["limit"]:
            proposals = proposals[: options["limit"]]
        qids = defaultdict(list)
        for work_id, value in ExternalIdentifier.objects.filter(
            scheme="wikidata", work_id__in=[p.from_work_id for p in proposals]
        ).values_list("work_id", "value"):
            qids[work_id].append(value)
        edge_status = {}
        for from_id, to_id, rel_id, status in WorkRelationship.objects.values_list(
            "from_work_id", "to_work_id", "relationship_type_id", "review_status"
        ):
            edge_status[(from_id, to_id, rel_id)] = status
        pending_counts = Counter((p.from_work_id, p.to_work_id, p.relationship_type_id) for p in proposals)
        today_year = django_timezone.now().year

        rows = []
        for proposal in proposals:
            work_qids = qids.get(proposal.from_work_id, [])
            qid = work_qids[0] if work_qids else ""
            key = (proposal.from_work_id, proposal.to_work_id, proposal.relationship_type_id)
            sitelinks = sitelink_count(proposal.from_work)
            decision, reasons, warnings = evaluate_proposal(
                proposal,
                qid,
                len(work_qids),
                edge_status.get(key, ""),
                pending_counts[key],
                today_year,
                sitelinks,
            )
            rows.append(_row(proposal, decision, reasons, warnings, qid, sitelinks))

        decisions = Counter(row["decision"] for row in rows)
        reason_counts = Counter(code for row in rows for code in row["reasons"])
        warning_counts = Counter(code for row in rows for code in row["warnings"])
        green_types = Counter(row["type"] for row in rows if row["decision"] == "green")
        report = {
            "version": "2026-10-22-proposal-triage",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": not options["confirm"],
            "reviewer": options["reviewer"] if options["confirm"] else None,
            "candidate_count": len(rows),
            "summary": {
                "decisions": dict(decisions),
                "green_types": dict(green_types),
                "reasons": dict(reason_counts),
                "warnings": dict(warning_counts),
            },
            "rules": {
                "green": "exact P144, based-on, dated, specific type, at least one sitelink, public editorial seed, no edge conflict, date order valid",
                "amber": "needs human review: missing year/date confidence, generic type, no sitelink, title collision, or duplicate pending edge",
                "red": "excluded from auto-publish: bad evidence, identity conflict, unsupported type, or existing edge",
                "images": "missing images are warnings, not publication blockers; placeholders remain",
            },
            "rows": rows,
        }

        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

        self.stdout.write(
            f"dry_run={not options['confirm']} candidates={len(rows)} "
            f"green={decisions.get('green', 0)} amber={decisions.get('amber', 0)} red={decisions.get('red', 0)}"
        )
        for code, count in reason_counts.most_common():
            self.stdout.write(f"  {code}: {count}")
        for code, count in warning_counts.most_common():
            self.stdout.write(f"  warning {code}: {count}")
        self.stdout.write(f"report={output}")

        if not options["confirm"]:
            return

        green_rows = [row for row in rows if row["decision"] == "green"]
        published = []
        approved = []
        with transaction.atomic():
            for row in green_rows:
                proposal = ImportRelationshipProposal.objects.select_for_update().get(pk=row["proposal_id"])
                if proposal.status != ImportRelationshipProposal.Status.PENDING:
                    continue
                proposal.approve(reviewer)
                approved.append(proposal.from_work_id)
            if not options["approve_only"]:
                for work in Work.objects.select_for_update().filter(
                    pk__in=set(approved), visibility=Work.Visibility.DRAFT
                ):
                    if work.first_publication_year is None:
                        continue
                    work.visibility = Work.Visibility.PUBLIC
                    work.save(update_fields=("visibility", "updated_at"))
                    published.append(work.pk)
        report["applied"] = {
            "approved_proposals": len(approved),
            "published_works": len(published),
            "published_work_ids": sorted(published),
            "approve_only": options["approve_only"],
        }
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(
            self.style.SUCCESS(
                f"approved {len(approved)} proposals; published {len(published)} works"
            )
        )

"""Split works that a title collision merged two Wikidata items into.

Some staged rows carry two Wikidata IDs. In every observed case the two IDs are
*different works that share a title* — a novel and its play, a film and its
re-release, a short story and the novel it grew into. The merged row produces
fake self-links and makes triage reject otherwise correct edges as
``multiple_qids``.

This command keeps one identity on the existing row and splits the other into
its own draft work, then re-points the proposals and accepted relationships
whose statement belongs to the moved entity.

Safety rules:

* the kept identity defaults to the one the row's date evidence came from;
  anything else must be given explicitly in ``--plan``;
* the moved entity must have a cached payload, or the row is left alone;
* the catalog row's own fields (title, type, date, credits) are never edited;
* every decision is reported, and ``--confirm`` is required to write.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from catalog.importers.wikidata import IMPORTER_VERSION, title_from_entity, work_type_spec
from catalog.models import (
    ExternalIdentifier,
    ImportRelationshipProposal,
    ImportRun,
    Source,
    SourceRecord,
    Work,
    WorkRelationship,
)

# P4969 is asserted on the target, so the seed sits on the to-work side.
DERIVED_ON_TARGET = {"P4969"}


def _qid_from_url(url):
    if not isinstance(url, str):
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.startswith("Q") and tail[1:].isdigit() else None


class Command(BaseCommand):
    help = "Split works that carry more than one Wikidata identity."

    def add_arguments(self, parser):
        parser.add_argument("--plan", type=Path, help="JSON with {\"overrides\": {\"<work id>\": \"<keep qid>\"}}")
        parser.add_argument("--report", type=Path)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        overrides = {}
        if options["plan"]:
            try:
                payload = json.loads(options["plan"].read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"invalid plan file: {exc}") from exc
            overrides = {int(key): value for key, value in (payload.get("overrides") or {}).items()}

        source = Source.objects.get(title="Wikidata")
        merged = (
            ExternalIdentifier.objects.filter(scheme="wikidata")
            .values("work_id")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .order_by("work_id")
        )

        decisions = []
        for row in merged:
            work = Work.objects.select_related("work_type").get(pk=row["work_id"])
            qids = list(
                work.identifiers.filter(scheme="wikidata").values_list("value", flat=True)
            )
            keep = overrides.get(work.pk) or _qid_from_url((work.date_evidence or {}).get("source_url"))
            if keep not in qids:
                decisions.append({
                    "work": work.pk, "title": work.title, "qids": qids,
                    "status": "needs_decision", "keep": keep,
                    "why": "kept identity could not be derived; supply it in --plan",
                })
                continue
            for move in [qid for qid in qids if qid != keep]:
                decisions.append(self._split(work, keep, move, source, options["confirm"]))

        summary = {}
        for decision in decisions:
            summary[decision["status"]] = summary.get(decision["status"], 0) + 1
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "confirm": options["confirm"],
            "merged_works": row_count(decisions),
            "summary": summary,
            "decisions": decisions,
        }
        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({"confirm": options["confirm"], "summary": summary}, sort_keys=True))
        for decision in decisions:
            self.stdout.write(
                f"  {decision['status']:<15} work {decision['work']} keep {decision.get('keep')} "
                f"move {decision.get('move')} {decision['title'][:38]}"
            )

    # -- one split ---------------------------------------------------------

    def _split(self, work, keep, move, source, confirm):
        record = SourceRecord.objects.filter(source=source, external_key=move).first()
        identifier = ExternalIdentifier.objects.filter(work=work, scheme="wikidata", value=move).first()
        base = {
            "work": work.pk, "title": work.title, "keep": keep, "move": move,
        }
        if not record or not isinstance(record.raw_payload, dict):
            return {**base, "status": "skipped_no_payload", "why": "no cached Wikidata payload for the moved item"}
        if not identifier:
            return {**base, "status": "skipped_no_identifier", "why": "the moved QID is not on this work"}

        payload = record.raw_payload
        if not confirm:
            return {**base, "status": "plan", "why": "would split into a new draft work"}

        run = ImportRun.objects.create(
            source=source,
            importer_version=IMPORTER_VERSION,
            stats={"command": "repair_duplicate_identities", "work": work.pk, "keep": keep, "move": move},
        )
        with transaction.atomic():
            identifier.delete()
            new_work = self._create_work(payload, move, source)
            self._link_provenance(new_work, payload, move, source)
            proposals, relationships = self._repoint(work, new_work, move)
            run.finished_at = datetime.now(timezone.utc)
            run.stats = {
                **run.stats,
                "new_work": new_work.pk,
                "proposals_moved": proposals,
                "relationships_moved": relationships,
            }
            run.save(update_fields=("status", "stats", "finished_at"))
        return {
            **base, "status": "split", "new_work": new_work.pk,
            "proposals_moved": proposals, "relationships_moved": relationships,
        }

    def _create_work(self, payload, move, source):
        """Create the new row without the supplier's cross-source matching.

        ``stage_entity`` would happily match the old row again through a shared
        IMDb or Open Library ID, which is exactly how the merge happened. The
        row is created here first, then ``stage_entity`` runs against it so the
        usual provenance, credit, and identifier side effects still happen.
        """
        from django.utils.text import slugify

        from catalog.dates import wikidata_date_for_medium
        from catalog.models import WorkType

        resolved_title, _language, _basis = title_from_entity(payload)
        title = (resolved_title or move)[:300]
        spec = work_type_spec(payload)
        date, year, _precision, kind, evidence = wikidata_date_for_medium(payload, spec[2])
        work_type, _ = WorkType.objects.get_or_create(
            code=spec[0], defaults={"label": spec[1], "medium": spec[2]}
        )
        description = payload.get("descriptions", {}).get("en", {}).get("value", "")
        new_work = Work.objects.create(
            title=title,
            slug=slugify(f"{title}-{move}"),
            work_type=work_type,
            description=description[:1000],
            first_publication_date_text=date,
            first_publication_year=year,
            date_kind=kind,
            date_evidence=evidence,
            visibility=Work.Visibility.DRAFT,
            depth="index",
        )
        ExternalIdentifier.objects.create(work=new_work, scheme="wikidata", value=move)
        return new_work

    def _link_provenance(self, new_work, payload, move, source):
        """Attach the cached payload and the usual supplier provenance to the new row.

        ``stage_entity`` cannot be reused here: the merged row already holds the
        Open Library and IMDb identifiers of *both* items, so its cross-source
        check reports a conflict. Only the Wikidata identity is split; shared
        external identifiers stay with the row that already had them.
        """
        from catalog.provenance import imported_fields
        from catalog.models import ImportedWorkState, WorkSource

        record = SourceRecord.objects.get(source=source, external_key=move)
        record.matched_work = new_work
        record.save(update_fields=("matched_work",))
        title = new_work.title
        date = new_work.first_publication_date_text
        ImportedWorkState.objects.update_or_create(
            source_record=record,
            defaults={
                "imported_title": title,
                "imported_date_text": date,
                "imported_year": new_work.first_publication_year,
            },
        )
        WorkSource.objects.get_or_create(
            work=new_work, source=source,
            defaults={"note": f"Wikidata entity {move}; split from a merged row by repair_duplicate_identities."},
        )
        imported_fields(
            new_work, record, title=title, date=date, created=True,
            type_note="Importer maps stored P31/P7937 classifications to catalog types.",
        )

    def _repoint(self, old, new, moved_qid):
        """Attach claims asserted by, or pointing at, the moved item to its new row."""
        proposals = 0
        for proposal in ImportRelationshipProposal.objects.filter(
            statement_id__startswith=f"{moved_qid}$"
        ):
            changed = self._fix_endpoints(proposal, old, new, moved_qid, subject_only=True)
            if changed:
                proposal.save(update_fields=("from_work", "to_work"))
                proposals += 1
        for proposal in ImportRelationshipProposal.objects.filter(evidence__entity_id=moved_qid):
            changed = self._fix_endpoints(proposal, old, new, moved_qid, subject_only=False)
            if changed:
                proposal.save(update_fields=("from_work", "to_work"))
                proposals += 1
        relationships = 0
        for relationship in WorkRelationship.objects.all():
            evidence = relationship.evidence or {}
            if not (relationship.evidence and evidence.get("statement_id")):
                continue
            moved_statement = str(evidence.get("statement_id", "")).startswith(f"{moved_qid}$")
            moved_target = evidence.get("entity_id") == moved_qid
            changed = self._fix_endpoints(
                relationship, old, new, moved_qid, subject_only=moved_statement,
            ) if (moved_statement or moved_target) else False
            if changed:
                relationship.save(update_fields=("from_work", "to_work"))
                relationships += 1
        return proposals, relationships

    def _fix_endpoints(self, row, old, new, moved_qid, subject_only):
        """Point the moved side at the new work; leave every other endpoint alone."""
        evidence = row.evidence if isinstance(row.evidence, dict) else {}
        property_id = evidence.get("property_id")
        statement_id = str(row.statement_id if hasattr(row, "statement_id") else evidence.get("statement_id", ""))
        subject_is_moved = statement_id.startswith(f"{moved_qid}$")
        target_is_moved = evidence.get("entity_id") == moved_qid
        changed = False
        if subject_is_moved:
            field = "to_work" if property_id in DERIVED_ON_TARGET else "from_work"
            if getattr(row, field + "_id") == old.pk:
                setattr(row, field + "_id", new.pk)
                changed = True
        elif target_is_moved and not subject_only:
            field = "from_work" if property_id in DERIVED_ON_TARGET else "to_work"
            if getattr(row, field + "_id") == old.pk:
                setattr(row, field + "_id", new.pk)
                changed = True
        return changed


def row_count(decisions):
    return len({decision["work"] for decision in decisions})

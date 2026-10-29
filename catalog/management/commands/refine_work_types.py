"""Give generically typed works a specific type when their own claims say so.

Triage refuses to publish a work whose type is a placeholder ("literary work",
"written work", "creative work"). Some of those rows were staged before the
supplier payload carried a form claim, so the type is stale rather than truly
unknown.

This command re-derives the type from the *cached* payload with the same rule
the importer uses (``work_type_spec``: P31 plus P7937, and only when exactly one
specific form survives). A payload that names two conflicting forms keeps its
generic type — ambiguity is not resolved by guessing.

Dry run by default; ``--confirm`` writes.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.importers.wikidata import work_type_spec
from catalog.provenance import record_evidence
from catalog.models import SourceRecord, Work, WorkType
from catalog.publication import GENERIC_TYPE_CODES


class Command(BaseCommand):
    help = "Refine placeholder work types from cached P31/P7937 claims."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("public", "draft", "all"), default="public")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        works = Work.objects.filter(work_type_id__in=GENERIC_TYPE_CODES).order_by("pk")
        if options["scope"] == "public":
            works = works.filter(visibility=Work.Visibility.PUBLIC)
        elif options["scope"] == "draft":
            works = works.filter(visibility=Work.Visibility.DRAFT)
        if options["limit"]:
            works = works[: options["limit"]]

        changes, ambiguous, missing = [], 0, 0
        for work in works.only("id", "title", "work_type_id", "visibility"):
            record = SourceRecord.objects.filter(source__title="Wikidata", matched_work=work).first()
            if not record or not isinstance(record.raw_payload, dict):
                missing += 1
                continue
            code, label, medium = work_type_spec(record.raw_payload)
            if code in GENERIC_TYPE_CODES or code == work.work_type_id:
                ambiguous += 1
                continue
            changes.append({
                "work": work.pk, "title": work.title, "from": work.work_type_id,
                "to": code, "label": label, "medium": medium, "visibility": work.visibility,
            })

        if options["confirm"]:
            for change in changes:
                work = Work.objects.select_related("work_type").get(pk=change["work"])
                work_type, _ = WorkType.objects.get_or_create(
                    code=change["to"], defaults={"label": change["label"], "medium": change["medium"]}
                )
                work.work_type = work_type
                work.save(update_fields=("work_type", "updated_at"))
                record = SourceRecord.objects.filter(source__title="Wikidata", matched_work=work).first()
                record_evidence(
                    work, "work_type", work_type.code,
                    source=record.source if record else None, source_record=record,
                    source_url=f"https://www.wikidata.org/wiki/{record.external_key}" if record else "",
                    origin="imported", retrieved_at=record.retrieved_at if record else None,
                    note="Type refined from the cached P31/P7937 form claims; only an unambiguous specific form is applied.",
                )

        summary = {}
        for change in changes:
            summary[change["to"]] = summary.get(change["to"], 0) + 1
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": options["scope"],
            "confirm": options["confirm"],
            "candidates": len(changes) + ambiguous + missing,
            "refined": len(changes),
            "left_generic_ambiguous": ambiguous,
            "no_cached_payload": missing,
            "by_type": summary,
            "changes": changes,
        }
        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        self.stdout.write(json.dumps({
            "confirm": options["confirm"], "refined": len(changes),
            "still_generic": ambiguous, "no_payload": missing, "by_type": summary,
        }, sort_keys=True))

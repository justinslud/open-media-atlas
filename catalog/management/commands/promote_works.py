"""Promote selected draft works after an explicit, reviewable decision.

Promotion is separate from triage so that "this proposal is clean" and "this
work belongs in the public catalog" stay distinct decisions. The command is
dry-run by default and refuses works that fail the shared publication rules.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import ImportRun, Work
from catalog.publication import WARNING_LABELS, blocking_reasons, publication_warnings


class Command(BaseCommand):
    help = "Promote explicit draft works to public, with shared publication gates."

    def add_arguments(self, parser):
        parser.add_argument("--ids", help="Comma-separated work IDs")
        parser.add_argument("--run-id", type=int, help="Promote the works created by an import run")
        parser.add_argument("--from-triage-report", type=Path, help="Use work_id values from a triage report")
        parser.add_argument("--decisions", default="green", help="Comma-separated triage decisions to take")
        parser.add_argument("--depth", choices=("index", "editorial", "ambient"), default="index")
        parser.add_argument("--require", default="", help="Comma-separated warnings that must block, e.g. no_date,no_creator")
        parser.add_argument("--force", action="store_true", help="Promote even when blocking warnings remain")
        parser.add_argument("--from-depth", choices=("index", "editorial", "ambient"),
                            help="Select works currently at this depth")
        parser.add_argument("--work-type", help="Select works of this work type code")
        parser.add_argument("--min-sitelinks", type=int, help="Select works with at least this many sitelinks")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        ids = self._collect_ids(options)
        if not ids:
            raise CommandError("no works selected; pass --ids, --run-id, or --from-triage-report")
        if options["limit"] and options["limit"] < 1:
            raise CommandError("--limit must be positive")
        require = tuple(code.strip() for code in options["require"].split(",") if code.strip())
        unknown = [code for code in require if code not in WARNING_LABELS]
        if unknown:
            raise CommandError(f"unknown --require codes: {', '.join(unknown)}")

        works = list(Work.objects.filter(pk__in=ids).select_related("work_type").order_by("pk"))
        if options["limit"]:
            works = works[: options["limit"]]

        promoted, blocked, skipped = [], [], []
        for work in works:
            if work.visibility == Work.Visibility.PUBLIC and work.depth == options["depth"]:
                skipped.append({"work": work.pk, "reason": f"already public at depth {work.depth}"})
                continue
            if work.visibility == Work.Visibility.SUPPRESSED:
                skipped.append({"work": work.pk, "reason": "suppressed"})
                continue
            reasons = blocking_reasons(work, require)
            if reasons and not options["force"]:
                blocked.append({"work": work.pk, "title": work.title, "reasons": reasons})
                continue
            promoted.append({
                "work": work.pk,
                "title": work.title,
                "year": work.first_publication_year,
                "warnings": publication_warnings(work),
            })

        report = {
            "confirm": options["confirm"],
            "depth": options["depth"],
            "require": list(require),
            "force": options["force"],
            "selected": len(works),
            "promoted": promoted,
            "blocked": blocked,
            "skipped": skipped,
        }

        if options["confirm"] and promoted:
            with transaction.atomic():
                Work.objects.filter(pk__in=[row["work"] for row in promoted]).update(
                    visibility=Work.Visibility.PUBLIC,
                    depth=options["depth"],
                )

        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

        self.stdout.write(
            f"confirm={options['confirm']} selected={len(works)} "
            f"promoted={len(promoted)} blocked={len(blocked)} skipped={len(skipped)}"
        )
        for code in sorted({code for row in blocked for code in row["reasons"]}):
            self.stdout.write(f"  blocked {code}: {sum(1 for row in blocked if code in row['reasons'])}")

    def _collect_ids(self, options):
        ids = []
        if options["from_depth"] or options["work_type"] or options["min_sitelinks"] is not None:
            ids.extend(self._selected_ids(options))
        if options["ids"]:
            for value in options["ids"].split(","):
                value = value.strip()
                if not value:
                    continue
                if not value.isdigit():
                    raise CommandError(f"not a work ID: {value}")
                ids.append(int(value))
        if options["run_id"]:
            try:
                run = ImportRun.objects.get(pk=options["run_id"])
            except ImportRun.DoesNotExist as exc:
                raise CommandError("import run not found") from exc
            ids.extend(run.items.values_list("work_id", flat=True))
        if options["from_triage_report"]:
            if not options["from_triage_report"].is_file():
                raise CommandError(f"missing {options['from_triage_report']}")
            wanted = {value.strip() for value in options["decisions"].split(",") if value.strip()}
            report = json.loads(options["from_triage_report"].read_text())
            ids.extend(row["work_id"] for row in report.get("rows", []) if row.get("decision") in wanted)
        return list(dict.fromkeys(pk for pk in ids if pk))

    def _selected_ids(self, options):
        """Select works by catalog state, for slices such as "best-known books"."""
        from catalog.ranking import sitelink_count

        works = Work.objects.all()
        if options["from_depth"]:
            works = works.filter(depth=options["from_depth"])
        if options["work_type"]:
            works = works.filter(work_type_id=options["work_type"])
        if options["min_sitelinks"] is not None:
            works = works.prefetch_related("source_records")
            return [work.pk for work in works if sitelink_count(work) >= options["min_sitelinks"]]
        return list(works.values_list("pk", flat=True))

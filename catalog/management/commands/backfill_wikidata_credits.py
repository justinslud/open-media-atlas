"""Add creator credits from cached Wikidata claims for works that have none.

Many staged records were created before their P50/P57 claims were available, or
were matched to an existing work without running the creation-only credit step.
This command reads the cached Wikidata payload, resolves agent labels from cache
or (optionally) Wikidata, and writes ordinary Credit rows. It never invents a
creator and never touches works that already have credits unless asked.
"""
import json
import time

from django.core.management.base import BaseCommand, CommandError

from catalog.importers.wikidata import WikidataClient
from catalog.models import Agent, Credit, SourceRecord, Work


CREATOR_PROPERTIES = (
    ("P50", "author"),
    ("P57", "director"),
    ("P58", "screenwriter"),
    ("P86", "composer"),
    ("P110", "illustrator"),
    ("P162", "producer"),
    ("P175", "performer"),
)
ROLE_BY_PROPERTY = dict(CREATOR_PROPERTIES)


class Command(BaseCommand):
    help = "Backfill Work credits from cached Wikidata P50/P57/... claims."

    def add_arguments(self, parser):
        parser.add_argument("--ids", help="Comma-separated work IDs")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--request-limit", type=int, default=50)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--cache-only", action="store_true", help="Never fetch missing agent labels")
        parser.add_argument("--fill-missing", action="store_true", help="Also top up works that already have credits")
        parser.add_argument("--report", help="Optional JSON report path")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        works = Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False).order_by("pk")
        if options["ids"]:
            try:
                ids = [int(value) for value in options["ids"].split(",") if value.strip()]
            except ValueError as exc:
                raise CommandError("--ids must be comma-separated integers") from exc
            works = works.filter(pk__in=ids)
        if not options["fill_missing"]:
            works = works.filter(credits__isnull=True)
        if options["limit"]:
            works = works[: options["limit"]]

        work_ids = list(works.values_list("pk", flat=True))
        if not work_ids:
            self.stdout.write("no candidate works")
            return

        payloads = {}
        for work_id, key, payload in SourceRecord.objects.filter(
            matched_work_id__in=work_ids, external_key__startswith="Q"
        ).values_list("matched_work_id", "external_key", "raw_payload"):
            if isinstance(payload, dict) and str(payload.get("id", "")).startswith("Q"):
                payloads.setdefault(work_id, payload)

        wanted = set()
        for payload in payloads.values():
            for prop, _role in CREATOR_PROPERTIES:
                for claim in payload.get("claims", {}).get(prop, []):
                    if claim.get("rank") == "deprecated":
                        continue
                    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if isinstance(value, dict) and value.get("entity-type") == "item":
                        wanted.add(value.get("id"))

        labels = self._cached_labels(wanted)
        unresolved_agents = sorted(wanted - set(labels))
        client = WikidataClient(timeout=options["timeout"], max_requests=options["request_limit"])
        fetched = 0
        if unresolved_agents and not options["cache_only"]:
            for offset in range(0, len(unresolved_agents), 50):
                batch = unresolved_agents[offset:offset + 50]
                for qid, entity in client.entities(batch).items():
                    label = (entity.get("labels", {}).get("en", {}) or {}).get("value")
                    if label:
                        labels[qid] = label
                        fetched += 1

        created = []
        no_claim = []
        missing_label = set()
        for work_id in work_ids:
            payload = payloads.get(work_id)
            if not payload:
                no_claim.append(work_id)
                continue
            order = 0
            rows = []
            for prop, role in CREATOR_PROPERTIES:
                for claim in payload.get("claims", {}).get(prop, []):
                    if claim.get("rank") == "deprecated":
                        continue
                    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if not isinstance(value, dict) or value.get("entity-type") != "item":
                        continue
                    qid = value.get("id")
                    label = labels.get(qid)
                    if not label:
                        missing_label.add(qid)
                        continue
                    order += 1
                    rows.append((qid, label, role, order))
            if not rows:
                no_claim.append(work_id)
                continue
            created.append({"work": work_id, "credits": [{"agent": label, "role": role, "qid": qid} for qid, label, role, _ in rows]})
            if options["dry_run"]:
                continue
            for qid, label, role, billing in rows:
                agent, _ = Agent.objects.get_or_create(
                    wikidata_id=qid, defaults={"name": label[:200], "kind": "person"}
                )
                Credit.objects.get_or_create(
                    work_id=work_id, agent=agent, role=role,
                    defaults={"billing_order": billing, "source_id": self._source_id(payload)},
                )

        report = {
            "dry_run": options["dry_run"],
            "cache_only": options["cache_only"],
            "candidate_works": len(work_ids),
            "with_cached_payload": len(payloads),
            "works_filled": len(created),
            "works_without_claims": len(no_claim),
            "agents_resolved_from_cache": len(wanted & set(labels)),
            "agents_fetched": fetched,
            "agents_missing_label": len(missing_label),
            "network_requests": client.requests,
            "sample": created[:5],
        }
        if options["report"]:
            with open(options["report"], "w", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
        self.stdout.write(json.dumps({key: value for key, value in report.items() if key != "sample"}, sort_keys=True))

    def _cached_labels(self, qids):
        labels = {}
        if not qids:
            return labels
        for qid, payload in SourceRecord.objects.filter(
            external_key__in=qids, external_key__startswith="Q"
        ).values_list("external_key", "raw_payload"):
            if isinstance(payload, dict):
                label = (payload.get("labels", {}).get("en", {}) or {}).get("value")
                if label:
                    labels[qid] = label
        return labels

    def _source_id(self, payload):
        from catalog.models import Source

        qid = payload.get("id", "")
        source = Source.objects.filter(title="Wikidata").first()
        return source.pk if source else None

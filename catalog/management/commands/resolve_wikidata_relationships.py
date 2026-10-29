"""Resolve additional Wikidata relationship assertions into inert proposals.

This command does not publish anything. It reads cached Wikidata entities,
stages missing endpoints as drafts, and creates relationship proposals with
exact statement IDs and property-level evidence.

Supported properties:
  P144 -> based-on, optionally refined by a P3831 qualifier
  P155 -> follows
  P156 -> followed-by
  P179 -> part-of-series
  P629 -> edition-of
  P941 -> inspired-by
  P737 -> influenced-by
"""
import hashlib
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from catalog.importers.wikidata import (
    IMPORTER_VERSION,
    WikidataClient,
    WikidataError,
    stage_entity,
)
from catalog.publication import SEED_SCOPES, is_seed
from catalog.models import (
    ExternalIdentifier,
    ImportItem,
    ImportRelationshipProposal,
    ImportRun,
    RelationshipType,
    Source,
    SourceRecord,
    Work,
    WorkRelationship,
)


PROPERTY_MAP = {
    "P144": "based-on",
    "P155": "follows",
    "P156": "followed-by",
    "P179": "part-of-series",
    "P629": "edition-of",
    "P941": "inspired-by",
    "P737": "influenced-by",
    "P4969": "derivative-work",
}

# P4969 is the only property here where the seed is the *source* and the target
# is derived. For P144/P155/P156/P179/P629/P941/P737 the claim lives on the seed,
# so the seed is the subject: the edge must be stored seed -> target to keep the
# catalog convention of "from = derived work".
PROPERTIES_DERIVED_ON_TARGET = {"P4969"}

QUALIFIER_ROLE_MAP = {
    "remake": "remake-of",
    "reboot": "reboot-of",
    "reimagining": "reimagining-of",
    "retelling": "retelling-of",
    "sequel": "sequel-to",
    "prequel": "prequel-to",
    "spin-off": "spin-off-of",
    "spin off": "spin-off-of",
    "parody": "parody-of",
    "pastiche": "pastiche-of",
    "homage": "homage-to",
    "adaptation": "based-on",
}


def claim_value(claim):
    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if isinstance(value, dict) and value.get("entity-type") == "item":
        return value.get("id")
    return None


def qualifier_code(claim, supporting):
    for qualifier in claim.get("qualifiers", {}).get("P3831", []):
        value = qualifier.get("datavalue", {}).get("value")
        if not isinstance(value, dict) or value.get("entity-type") != "item":
            continue
        qid = value.get("id")
        entity = supporting.get(qid, {})
        label = entity.get("labels", {}).get("en", {}).get("value", "").lower()
        for needle, code in QUALIFIER_ROLE_MAP.items():
            if needle in label:
                return code
    return None


class Command(BaseCommand):
    help = "Resolve non-P144 Wikidata relationship assertions into pending proposals."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-pilot-seeds.json")
        parser.add_argument("--seed-limit", type=int, default=30)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--max-runtime", type=int, default=3600)
        parser.add_argument("--timeout", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--seed-scope", choices=SEED_SCOPES, default="editorial",
            help="Only propose edges for seeds in this scope; matches triage_proposals.",
        )

    def handle(self, *args, **options):
        if not 1 <= options["seed_limit"] <= 500:
            raise CommandError("--seed-limit must be 1..500")
        if not 1 <= options["limit"] <= 5000:
            raise CommandError("--limit must be 1..5000")

        path = Path(options["manifest"])
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid seed manifest: {exc}") from exc
        chosen = manifest.get("seeds", [])[: options["seed_limit"]]
        seeds = [row["qid"] for row in chosen]
        if not seeds or len(set(seeds)) != len(seeds):
            raise CommandError("manifest must contain unique QIDs")

        # Keep seed selection and triage on the same rule, so a run cannot create
        # proposals its own triage would reject as target_not_seed.
        seed_works = {
            identifier.value: identifier.work
            for identifier in ExternalIdentifier.objects.filter(
                scheme="wikidata", value__in=seeds
            ).select_related("work")
        }
        in_scope = [qid for qid in seeds if qid in seed_works and is_seed(seed_works[qid], options["seed_scope"])]
        skipped_out_of_scope = [qid for qid in seeds if qid not in in_scope]
        seeds = in_scope
        if not seeds:
            raise CommandError(
                f"no seeds within --seed-scope {options['seed_scope']}; "
                f"{len(skipped_out_of_scope)} manifest seeds were skipped"
            )

        source = Source.objects.get_or_create(
            title="Wikidata",
            defaults={"kind": "knowledge-base", "url": "https://www.wikidata.org/", "notes": "Supplier assertions require OMA review."},
        )[0]
        run = ImportRun.objects.create(
            source=source,
            requested_keys=seeds,
            importer_version=IMPORTER_VERSION,
            manifest={"command": "resolve_wikidata_relationships", "seeds": chosen, "limits": {"relationships": options["limit"]}},
        )
        client = WikidataClient(timeout=options["timeout"], max_requests=500)
        started = time.monotonic()
        stats = {
            "seeds_attempted": len(seeds),
            "seed_scope": options["seed_scope"],
            "seeds_skipped_out_of_scope": len(skipped_out_of_scope),
            "matched_entities": 0,
            "new_entities": 0,
            "relationships_proposed": 0,
            "relationships_already_proposed": 0,
            "failures": 0,
            "skipped_statements": 0,
            "network_requests": 0,
        }
        try:
            cached = {r.external_key: r.raw_payload for r in SourceRecord.objects.filter(source=source, external_key__in=seeds)}
            missing = [qid for qid in seeds if qid not in cached]
            seed_entities = {**cached, **(client.entities(missing) if missing else {})}
            all_ids = set(seeds)
            claims_by_seed = {}
            qualifier_ids = set()
            for seed in seeds:
                entity = seed_entities.get(seed)
                if not entity or entity.get("missing"):
                    stats["failures"] += 1
                    ImportItem.objects.update_or_create(run=run, external_key=seed, defaults={"status": "failed", "message": "seed entity missing"})
                    continue
                claims_by_seed[seed] = []
                for prop, code in PROPERTY_MAP.items():
                    for claim in entity.get("claims", {}).get(prop, []):
                        if claim.get("rank") == "deprecated":
                            continue
                        target = claim_value(claim)
                        if not target or target == seed:
                            stats["skipped_statements"] += 1
                            continue
                        all_ids.add(target)
                        claims_by_seed[seed].append((prop, code, claim, target))
                        for qualifier in claim.get("qualifiers", {}).get("P3831", []):
                            qid = qualifier.get("datavalue", {}).get("value", {}).get("id")
                            if qid:
                                qualifier_ids.add(qid)
            related_ids = sorted(all_ids - set(seed_entities))
            cached_related = {r.external_key: r.raw_payload for r in SourceRecord.objects.filter(source=source, external_key__in=related_ids)}
            missing_related = [qid for qid in related_ids if qid not in cached_related]
            related_entities = {**cached_related, **(client.entities(missing_related) if missing_related else {})}
            entities = {**seed_entities, **related_entities}
            supporting = client.entities(sorted(qualifier_ids)) if qualifier_ids else {}
            entities = {**entities, **supporting}

            now = timezone.now()
            for qid, entity in entities.items():
                if entity.get("missing"):
                    continue
                raw = json.dumps(entity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                SourceRecord.objects.update_or_create(
                    source=source,
                    external_key=qid,
                    defaults={"payload_hash": hashlib.sha256(raw).hexdigest(), "raw_payload": entity, "retrieved_at": now},
                )

            works = {}
            for qid in sorted(all_ids):
                entity = entities.get(qid)
                if not entity or entity.get("missing"):
                    stats["failures"] += 1
                    ImportItem.objects.update_or_create(run=run, external_key=qid, defaults={"status": "failed", "message": "entity missing"})
                    continue
                work, status, message = stage_entity(
                    entity,
                    source,
                    run,
                    supporting_entities=entities,
                    existing_only=False,
                    allow_title_collision=True,
                    refresh_existing=False,
                )
                if work:
                    works[qid] = work
                    if status == "created":
                        stats["new_entities"] += 1
                    else:
                        stats["matched_entities"] += 1
                ImportItem.objects.update_or_create(run=run, external_key=qid, defaults={"status": status, "work": work, "message": message})

            reltype_cache = {}
            for seed in seeds:
                seed_work = works.get(seed)
                if not seed_work:
                    continue
                for prop, code, claim, target in claims_by_seed.get(seed, []):
                    target_work = works.get(target)
                    if not target_work or target_work.pk == seed_work.pk:
                        stats["skipped_statements"] += 1
                        continue
                    if prop == "P144":
                        code = qualifier_code(claim, entities) or code
                    if code not in reltype_cache:
                        reltype_cache[code] = RelationshipType.objects.update_or_create(
                            code=code,
                            defaults={"label": code.replace("-", " ").title(), "inverse_label": code.replace("-", " ").title(), "category": "reference"},
                        )[0]
                    reltype = reltype_cache[code]
                    statement_id = claim.get("id") or f"{target}-{prop}-{seed}"
                    if prop in PROPERTIES_DERIVED_ON_TARGET:
                        from_work, to_work = target_work, seed_work
                    else:
                        from_work, to_work = seed_work, target_work
                    duplicate = ImportRelationshipProposal.objects.filter(
                        statement_id=statement_id,
                        from_work=from_work,
                        to_work=to_work,
                        relationship_type=reltype,
                        status__in=(ImportRelationshipProposal.Status.PENDING, ImportRelationshipProposal.Status.APPROVED),
                    ).exclude(run=run).exists()
                    if duplicate:
                        stats["relationships_already_proposed"] += 1
                        continue
                    evidence = {
                        "asserted_by": "Wikidata",
                        "entity_id": target,
                        "property_id": prop,
                        "statement_id": claim.get("id") or statement_id,
                        "rank": claim.get("rank", "normal"),
                        "qualifiers": claim.get("qualifiers", {}),
                        "references": claim.get("references", []),
                        "retrieved_at": timezone.now().isoformat(),
                        "revision_id": entities.get(target, {}).get("lastrevid"),
                        "source_url": f"https://www.wikidata.org/wiki/{target}",
                        "relationship_code": code,
                    }
                    if prop not in PROPERTIES_DERIVED_ON_TARGET:
                        # Only these properties live on the seed; P4969 lives on
                        # the target, so its evidence must not claim seed subject.
                        evidence["edge_subject"] = "seed"
                    ImportRelationshipProposal.objects.update_or_create(
                        run=run,
                        statement_id=statement_id,
                        defaults={
                            "from_work": from_work,
                            "to_work": to_work,
                            "relationship_type": reltype,
                            "source": source,
                            "evidence": evidence,
                        },
                    )
                    stats["relationships_proposed"] += 1
                    if stats["relationships_proposed"] >= options["limit"]:
                        break
                if stats["relationships_proposed"] >= options["limit"]:
                    break

            stats["network_requests"] = client.requests
            stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
            run.status = ImportRun.Status.COMPLETED
        except Exception as exc:
            run.status = ImportRun.Status.FAILED
            stats = {"error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 2)}
            run.stats = stats
            run.finished_at = timezone.now()
            run.save(update_fields=("status", "stats", "finished_at"))
            raise CommandError(str(exc)) from exc
        run.stats = stats
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "stats", "finished_at"))
        self.stdout.write(self.style.SUCCESS(json.dumps({"run_id": run.pk, **stats}, sort_keys=True)))
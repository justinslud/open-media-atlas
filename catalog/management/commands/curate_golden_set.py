"""Promote a reviewed golden seed set and a bounded number of adaptations."""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import (
    ExternalIdentifier,
    FeaturedWork,
    ImportRelationshipProposal,
    MediaList,
    MediaListEntry,
    Work,
)

TYPE_PRIORITY = {
    "film": 0,
    "television-series": 1,
    "television-program": 2,
    "video-game": 3,
    "play": 4,
    "album": 5,
    "song": 6,
}


def sitelink_count(work):
    for record in work.source_records.all():
        payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        if str(payload.get("id", "")).startswith("Q"):
            sitelinks = payload.get("sitelinks", {})
            if isinstance(sitelinks, dict):
                return len(sitelinks)
    return 0


class Command(BaseCommand):
    help = "Publish the golden seed works and approve a bounded set of adaptation proposals."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-golden-20.json")
        parser.add_argument("--reviewer", required=True)
        parser.add_argument("--adaptations-per-seed", type=int, default=4)
        parser.add_argument("--list-title", default="Golden 20")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not 0 <= options["adaptations_per_seed"] <= 12:
            raise CommandError("--adaptations-per-seed must be 0..12")
        try:
            manifest = json.loads(Path(options["manifest"]).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid manifest: {exc}") from exc
        try:
            reviewer = get_user_model().objects.get(username=options["reviewer"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"reviewer not found: {options['reviewer']}") from exc
        seed_works, missing = [], []
        for seed in manifest.get("seeds", []):
            work = (
                Work.objects.filter(
                    identifiers__scheme="wikidata", identifiers__value=seed["qid"]
                )
                .distinct()
                .first()
            )
            if work:
                seed_works.append((seed, work))
            else:
                missing.append(seed)
        if missing:
            raise CommandError(
                "seed works missing: " + ", ".join(f"{seed['qid']} {seed['label']}" for seed in missing)
            )

        selections = []
        used_adaptations = set()
        for seed, seed_work in seed_works:
            candidates = list(
                ImportRelationshipProposal.objects.filter(
                    to_work=seed_work, status=ImportRelationshipProposal.Status.PENDING
                )
                .select_related("from_work__work_type", "relationship_type")
                .prefetch_related("from_work__source_records")
            )
            unique = {}
            for proposal in candidates:
                unique.setdefault(proposal.from_work_id, proposal)
            ranked = sorted(
                unique.values(),
                key=lambda proposal: (
                    TYPE_PRIORITY.get(proposal.from_work.public_type_code, 9),
                    -sitelink_count(proposal.from_work),
                    proposal.from_work.first_publication_year or 9999,
                    proposal.from_work.title.casefold(),
                ),
            )
            chosen = []
            for proposal in ranked:
                if proposal.from_work_id in used_adaptations:
                    continue
                chosen.append(proposal)
                used_adaptations.add(proposal.from_work_id)
                if len(chosen) >= options["adaptations_per_seed"]:
                    break
            selections.append((seed, seed_work, chosen))

        self.stdout.write(
            f"golden seeds={len(seed_works)} adaptations={sum(len(c) for _, _, c in selections)} "
            f"per_seed={options['adaptations_per_seed']} confirm={options['confirm']}"
        )
        for seed, work, chosen in selections:
            self.stdout.write(f"\n{seed['label']} [{work.pk}] -> {work.title}")
            for proposal in chosen:
                other = proposal.from_work
                self.stdout.write(
                    f"  {other.pk} {other.title[:70]} "
                    f"({other.public_type_code}, {other.first_publication_year or '—'})"
                )
        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("Preview only. Re-run with --confirm to publish."))
            return

        with transaction.atomic():
            for position, (_seed, seed_work, _chosen) in enumerate(selections, 1):
                seed_work.visibility = Work.Visibility.PUBLIC
                seed_work.depth = "editorial"
                seed_work.save(update_fields=("visibility", "depth", "updated_at"))
                FeaturedWork.objects.update_or_create(
                    work=seed_work,
                    defaults={"position": position},
                )
            for seed, seed_work, chosen in selections:
                for proposal in chosen:
                    proposal.approve(reviewer)
                    work = proposal.from_work
                    if work.visibility == Work.Visibility.DRAFT:
                        work.visibility = Work.Visibility.PUBLIC
                        work.save(update_fields=("visibility", "updated_at"))
            public_list, _ = MediaList.objects.get_or_create(
                owner=reviewer,
                title=options["list_title"],
                defaults={
                    "description": "Twenty public-domain source works selected to exercise identity, images, and adaptation evidence.",
                    "visibility": MediaList.Visibility.PUBLIC,
                },
            )
            public_list.visibility = MediaList.Visibility.PUBLIC
            public_list.description = (
                "Twenty public-domain source works selected to exercise identity, images, and adaptation evidence."
            )
            public_list.save(update_fields=("visibility", "description", "updated_at"))
            for position, (_seed, work) in enumerate(seed_works, 1):
                MediaListEntry.objects.update_or_create(
                    media_list=public_list,
                    work=work,
                    defaults={"position": position},
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"published {len(seed_works)} seeds, {sum(len(c) for _, _, c in selections)} adaptations, "
                f"and list '{public_list.title}' [{public_list.pk}]"
            )
        )

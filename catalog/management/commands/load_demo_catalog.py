from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import Agent, Credit, ExternalIdentifier, Release, RelationshipType, Source, Version, Work, WorkRelationship, WorkSource, WorkType


class Command(BaseCommand):
    help = "Idempotently load the fictional Open Media Atlas demonstration catalog."

    @transaction.atomic
    def handle(self, *args, **options):
        types = {}
        for code, label, medium in (("novel", "Novel", "text"), ("film", "Film", "screen")):
            types[code], _ = WorkType.objects.update_or_create(code=code, defaults={"label": label, "medium": medium})

        source_specs = {
            "book": ("Mock catalog record for The Glass Orchard", "book", "Fictional evidence for the novel’s identity."),
            "film78": ("Mock 1978 film credits", "webpage", "Fictional credits naming the source novel."),
            "film25": ("Mock 2025 studio catalog", "webpage", "Fictional studio record naming the source novel."),
        }
        sources = {}
        for key, (title, kind, notes) in source_specs.items():
            sources[key], _ = Source.objects.update_or_create(title=title, defaults={"kind": kind, "notes": notes, "url": ""})

        works = {}
        work_specs = {
            "novel": (1001, "The Glass Orchard", "novel", "1912", 1912, "A precise, fictional catalog demonstration: an orchard keeper returns home to find the glass trees preserving memories that do not belong to her.", "book"),
            "film78": (1002, "The Glass Orchard", "film", "1978", 1978, "A fictional screen adaptation emphasizing the novel’s mystery and rural setting.", "film78"),
            "film25": (1003, "The Glass Orchard", "film", "2025", 2025, "A second fictional adaptation of the source novel. No remake relationship is asserted.", "film25"),
        }
        for key, (pk, title, type_code, date_text, year, description, source_key) in work_specs.items():
            works[key], _ = Work.objects.update_or_create(pk=pk, defaults={
                "title": title, "slug": slugify(f"{title}-{type_code}-{year}"), "work_type": types[type_code],
                "description": description, "first_publication_date_text": date_text, "first_publication_year": year,
                "completion_status": "released", "visibility": Work.Visibility.PUBLIC, "depth": "editorial", "is_demo": True,
            })
            WorkSource.objects.update_or_create(work=works[key], source=sources[source_key], defaults={"note": sources[source_key].notes})
            ExternalIdentifier.objects.update_or_create(work=works[key], scheme="oma_demo", value=f"example-{pk}")

        creators = {}
        for name, kind in (("Mara Vale", "person"), ("Lena Ortiz", "person"), ("Harborlight Pictures", "organization")):
            creators[name], _ = Agent.objects.update_or_create(name=name, defaults={"kind": kind})
        for work, agent, role in ((works["novel"], creators["Mara Vale"], "author"), (works["film78"], creators["Lena Ortiz"], "director"), (works["film25"], creators["Harborlight Pictures"], "production company")):
            Credit.objects.update_or_create(work=work, agent=agent, role=role, defaults={"billing_order": 0})

        original, _ = Version.objects.update_or_create(work=works["novel"], label="Original English text", defaults={"kind": "original", "language": "English", "first_available_date_text": "1912"})
        translation, _ = Version.objects.update_or_create(work=works["novel"], label="Marchand translation", defaults={"kind": "translation", "title": "Le Verger de verre", "language": "French", "contributor_note": "Translated by Julien Marchand", "first_available_date_text": "2002"})
        Release.objects.update_or_create(version=original, title="The Glass Orchard", edition_name="First edition", defaults={"format": "Hardcover", "publication_date_text": "1912", "publisher_statement": "Rowan Press", "pages": 248})
        Release.objects.update_or_create(version=translation, title="Le Verger de verre", edition_name="Marchand translation", defaults={"format": "Paperback", "publication_date_text": "2002", "publisher_statement": "Rowan Press", "pages": 276})
        Release.objects.update_or_create(version=translation, title="Le Verger de verre", edition_name="Digital release", defaults={"format": "Ebook", "publication_date_text": "2016", "publisher_statement": "Rowan Press", "pages": None})
        for key, label, runtime in (("film78", "Theatrical cut", 6000), ("film25", "Theatrical version", None)):
            Version.objects.update_or_create(work=works[key], label=label, defaults={"kind": "original", "runtime_seconds": runtime, "first_available_date_text": work_specs[key][3]})

        adapted, _ = RelationshipType.objects.update_or_create(code="adapted-from", defaults={"label": "Adapted from", "inverse_label": "Adaptations", "category": "derivation"})
        for child_key, source_key in (("film78", "film78"), ("film25", "film25")):
            WorkRelationship.objects.update_or_create(from_work=works[child_key], to_work=works["novel"], relationship_type=adapted, defaults={
                "source": sources[source_key], "scope_note": "The fictional credits identify the novel as the source.",
                "review_status": "accepted", "authorization_status": "unknown",
            })
        self.stdout.write(self.style.SUCCESS("Demonstration catalog loaded (repeat-safe)."))


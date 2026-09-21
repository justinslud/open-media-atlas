from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (Agent, Credit, ExternalIdentifier, FeaturedWork,
    RelationshipType, Source, Work, WorkRelationship, WorkSource, WorkType)


class Command(BaseCommand):
    help = "Idempotently load three manually verified book-to-film relationships."

    @transaction.atomic
    def handle(self, *args, **options):
        required = ("OL872932W", "OL66554W", "OL3140822W")
        book_ids = {item.value: item.work for item in ExternalIdentifier.objects.filter(
            scheme="ol_work", value__in=required).select_related("work")}
        missing = set(required) - set(book_ids)
        if missing:
            raise CommandError("Import the required Open Library works first: " + ", ".join(sorted(missing)))
        film_type, _ = WorkType.objects.get_or_create(code="film", defaults={"label": "Film", "medium": "screen"})
        adapted, _ = RelationshipType.objects.update_or_create(code="adapted-from", defaults={
            "label": "Adapted from", "inverse_label": "Adaptations", "category": "derivation"})
        specs = (
            ("Siddhartha", 1972, "Conrad Rooks", "OL872932W", "https://en.wikipedia.org/wiki/Siddhartha_(1972_film)", "Siddhartha (1972 film) reference"),
            ("Pride & Prejudice", 2005, "Joe Wright", "OL66554W", "https://en.wikipedia.org/wiki/Pride_%26_Prejudice_(2005_film)", "Pride & Prejudice (2005 film) reference"),
            ("To Kill a Mockingbird", 1962, "Robert Mulligan", "OL3140822W", "https://en.wikipedia.org/wiki/To_Kill_a_Mockingbird_(film)", "To Kill a Mockingbird (1962 film) reference"),
        )
        for position, (title, year, director, source_id, url, source_title) in enumerate(specs, 1):
            film, _ = Work.objects.get_or_create(slug=f"{slugify(title)}-film-{year}", defaults={
                "title": title, "work_type": film_type, "first_publication_date_text": str(year),
                "first_publication_year": year, "completion_status": "released",
                "visibility": Work.Visibility.PUBLIC, "depth": "index", "is_demo": False})
            person, _ = Agent.objects.get_or_create(name=director, kind="person")
            Credit.objects.get_or_create(work=film, agent=person, role="director", defaults={"billing_order": 0})
            source, _ = Source.objects.get_or_create(title=source_title, defaults={"kind": "webpage", "url": url,
                "notes": "Manually reviewed public reference identifying the film and source novel."})
            WorkSource.objects.get_or_create(work=film, source=source, defaults={"note": "Film identity and adaptation reference."})
            WorkRelationship.objects.get_or_create(from_work=film, to_work=book_ids[source_id], relationship_type=adapted,
                defaults={"source": source, "scope_note": "The film is identified as an adaptation of this novel.",
                    "review_status": "accepted", "authorization_status": "unknown"})
            FeaturedWork.objects.get_or_create(work=book_ids[source_id], defaults={"position": position})
        self.stdout.write(self.style.SUCCESS("Curated film relationships loaded (repeat-safe)."))

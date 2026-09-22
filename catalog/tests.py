import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .importers.openlibrary import ImportFailure, ImportResult, OpenLibraryImporter
from .models import (Credit, ExternalIdentifier, FeaturedWork, ImportedWorkState,
    ImportItem, ImportRun, Release, Version, Work, WorkRelationship, WorkSource,
    WorkType)


class JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fake_open(payloads):
    responses = iter(payloads)

    def opener(request, timeout=20):
        return JsonResponse(json.dumps(next(responses)).encode())

    return opener
class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_catalog", verbosity=0)

    def test_fixture_is_repeatable(self):
        models = (Work, Version, Release, Credit, WorkRelationship, WorkSource, ExternalIdentifier)
        before = tuple(model.objects.count() for model in models)
        call_command("load_demo_catalog", verbosity=0)
        self.assertEqual(before, tuple(model.objects.count() for model in models))

    def test_health_check(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_production_settings_load_without_optional_email_configuration(self):
        env = os.environ.copy()
        env.update({
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "production-settings-test-key",
            "DATABASE_URL": "postgresql://user:password@db.example.test:5432/oma",
        })
        for name in ("EMAIL_BACKEND", "EMAIL_HOST"):
            env.pop(name, None)

        result = subprocess.run(
            [sys.executable, "-c", "from django.conf import settings; print(settings.EMAIL_HOST)"],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "localhost")

    def test_search_and_media_filter(self):
        response = self.client.get(reverse("discover"), {"q": "Glass", "type": "novel"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["works"].values_list("pk", flat=True)), [1001])
        response = self.client.get(reverse("discover"), {"q": "does not exist"})
        self.assertContains(response, "No works found")

    def test_htmx_search_returns_results_fragment(self):
        response = self.client.get(reverse("discover"), {"type": "film"}, HTTP_HX_REQUEST="true")
        self.assertNotContains(response, "<!doctype html>")
        self.assertContains(response, "<strong>2</strong> works", html=True)

    def test_relationship_direction_and_inverse_label(self):
        film = Work.objects.get(pk=1002)
        novel = Work.objects.get(pk=1001)
        self.assertEqual(film.outgoing_relationships.get().to_work, novel)
        self.assertEqual(novel.incoming_relationships.count(), 2)
        self.assertContains(self.client.get(novel.get_absolute_url()), "Adaptations")
        self.assertContains(self.client.get(film.get_absolute_url()), "Adapted from")

    def test_versions_render_inside_parent(self):
        response = self.client.get(Work.objects.get(pk=1001).get_absolute_url())
        self.assertContains(response, "Marchand translation")
        self.assertContains(response, "Le Verger de verre")

    def test_non_public_records_are_not_discoverable(self):
        draft = Work.objects.create(title="Private draft", slug="private-draft", work_type_id="novel", visibility="draft")
        self.assertNotContains(self.client.get(reverse("discover"), {"q": "Private"}), "Private draft")
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)

    def test_unreviewed_relationship_is_not_public(self):
        relationship = WorkRelationship.objects.first()
        relationship.review_status = "unreviewed"
        relationship.save()
        response = self.client.get(relationship.from_work.get_absolute_url())
        self.assertNotContains(response, relationship.to_work.get_absolute_url())

    def test_homepage_uses_editorial_selection_order_and_notes(self):
        later = Work.objects.get(pk=1003)
        first = Work.objects.get(pk=1001)
        FeaturedWork.objects.create(work=later, position=20, note="A later selection")
        FeaturedWork.objects.create(work=first, position=10, note="Start here")
        response = self.client.get(reverse("home"))
        self.assertContains(response, "EDITOR’S SELECTION")
        self.assertContains(response, "Start here")
        self.assertLess(
            response.content.index(first.get_absolute_url().encode()),
            response.content.index(later.get_absolute_url().encode()),
        )

    def test_homepage_relationships_only_use_public_accepted_records(self):
        relationship = WorkRelationship.objects.first()
        hidden = relationship.from_work
        hidden.visibility = Work.Visibility.DRAFT
        hidden.save()
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, hidden.get_absolute_url())

    def test_detail_does_not_expose_relationship_to_unpublished_work(self):
        relationship = WorkRelationship.objects.first()
        hidden = relationship.to_work
        visible = relationship.from_work
        hidden.visibility = Work.Visibility.DRAFT
        hidden.save()
        response = self.client.get(visible.get_absolute_url())
        self.assertNotContains(response, hidden.get_absolute_url())
        self.assertNotContains(response, 'href="#relationships"')

    def test_detail_jump_links_only_target_populated_sections(self):
        work = Work.objects.create(
            title="Sparse work", slug="sparse-work", work_type_id="novel",
            visibility=Work.Visibility.PUBLIC,
        )
        response = self.client.get(work.get_absolute_url())
        self.assertNotContains(response, 'href="#relationships"')
        self.assertNotContains(response, 'href="#versions"')
        self.assertNotContains(response, 'href="#sources"')


class OpenLibraryImportTests(TestCase):
    def setUp(self):
        self.book_type, _ = WorkType.objects.get_or_create(code="book", defaults={"label": "Book", "medium": "text"})

    def importer(self, title="Imported title", date="1922"):
        return OpenLibraryImporter(delay=0, opener=fake_open([
            {"key": "/works/OL1W", "title": title, "first_publish_date": date,
                "authors": [{"author": {"key": "/authors/OL1A"}}]},
            {"key": "/authors/OL1A", "name": "A Real Author"},
        ]))

    def test_repeat_import_skips_unchanged_source(self):
        first = self.importer().import_work("OL1W")
        second = OpenLibraryImporter(delay=0, opener=fake_open([{
            "key": "/works/OL1W", "title": "Imported title", "first_publish_date": "1922",
            "authors": [{"author": {"key": "/authors/OL1A"}}],
        }])).import_work("OL1W")
        self.assertEqual(first.status, "created")
        self.assertEqual(second.status, "skipped")
        self.assertEqual(Work.objects.filter(is_demo=False).count(), 1)

    def test_reimport_preserves_editorial_override(self):
        work = self.importer().import_work("OL1W").work
        work.title = "Editorial title"
        work.save(update_fields=("title", "updated_at"))
        result = self.importer(title="Changed supplier title", date="1923").import_work("OL1W")
        work.refresh_from_db()
        self.assertEqual(result.status, "updated")
        self.assertEqual(work.title, "Editorial title")
        self.assertEqual(work.first_publication_date_text, "1923")
        self.assertEqual(ImportedWorkState.objects.get().imported_title, "Changed supplier title")

    @patch("catalog.management.commands.import_openlibrary.OpenLibraryImporter")
    def test_command_records_partial_failure(self, importer_class):
        importer = importer_class.return_value
        importer.source = self.importer().source
        imported = Work.objects.create(title="Good", slug="good", work_type=self.book_type, visibility="public")
        importer.import_work.side_effect = [ImportResult("created", imported), ImportFailure("temporary failure")]
        call_command("import_openlibrary", "OL1W", "OL2W", limit=2)
        run = ImportRun.objects.get()
        self.assertEqual(run.status, ImportRun.Status.COMPLETED_WITH_ERRORS)
        self.assertEqual(run.stats, {"created": 1, "updated": 0, "skipped": 0, "failed": 1})
        self.assertEqual(set(ImportItem.objects.values_list("status", flat=True)), {"created", "failed"})

    def test_real_records_hide_demo_records_from_public_catalog(self):
        demo = Work.objects.create(title="Fictional demonstration", slug="fictional-demonstration",
            work_type=self.book_type, visibility=Work.Visibility.PUBLIC, is_demo=True)
        imported = self.importer().import_work("OL1W").work
        response = self.client.get(reverse("discover"))
        self.assertContains(response, imported.title)
        self.assertNotContains(response, demo.get_absolute_url())

    def test_curated_relationships_navigate_in_both_directions(self):
        for external_id, title in (("OL872932W", "Siddhartha"), ("OL66554W", "Pride and Prejudice"),
                                   ("OL3140822W", "To Kill a Mockingbird")):
            work = Work.objects.create(title=title, slug=f"{external_id.lower()}-book", work_type=self.book_type,
                visibility=Work.Visibility.PUBLIC, is_demo=False)
            ExternalIdentifier.objects.create(work=work, scheme="ol_work", value=external_id)
        call_command("load_curated_relationships")
        call_command("load_curated_relationships")
        book = Work.objects.get(identifiers__value="OL872932W")
        film = Work.objects.get(slug="siddhartha-film-1972")
        self.assertContains(self.client.get(book.get_absolute_url()), film.get_absolute_url())
        self.assertContains(self.client.get(film.get_absolute_url()), book.get_absolute_url())
        self.assertEqual(WorkRelationship.objects.filter(from_work=film, to_work=book).count(), 1)

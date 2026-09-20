from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Credit, ExternalIdentifier, Release, Version, Work, WorkRelationship, WorkSource


class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_catalog", verbosity=0)

    def test_fixture_is_repeatable(self):
        models = (Work, Version, Release, Credit, WorkRelationship, WorkSource, ExternalIdentifier)
        before = tuple(model.objects.count() for model in models)
        call_command("load_demo_catalog", verbosity=0)
        self.assertEqual(before, tuple(model.objects.count() for model in models))

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

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmailVerification

from .importers.openlibrary import ImportFailure, ImportResult, OpenLibraryImporter
from .models import (Credit, ExternalIdentifier, FeaturedWork, ImportedWorkState,
    ContributionProposal, ContributionRevision, ImportItem, ImportRun, MediaList, MediaListEntry, RelationshipType, Release, Source, Version, Work, WorkRelationship, WorkSource,
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


class MediaListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user("curator", "curator@example.test", "password123")
        cls.other = get_user_model().objects.create_user("stranger", "stranger@example.test", "password123")
        cls.book = WorkType.objects.create(code="test-book", label="Novel", medium="text")
        cls.film = WorkType.objects.create(code="test-film", label="Film", medium="screen")
        cls.work_a = Work.objects.create(title="Published book", slug="published-book", work_type=cls.book, visibility="public")
        cls.work_b = Work.objects.create(title="Published film", slug="published-film", work_type=cls.film, visibility="public")

    def test_private_list_is_hidden_by_direct_url_and_mutations_are_owner_only(self):
        item = MediaList.objects.create(owner=self.owner, title="Private picks")
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(reverse("list-edit", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("list-add-work", args=[item.pk, self.work_a.pk])).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(item.get_absolute_url()), "Private picks")

    def test_publishing_requires_verified_email_but_private_creation_does_not(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("list-create"), {"title": "Unverified", "description": "", "visibility": "public"})
        self.assertContains(response, "Verify your email address")
        self.assertFalse(MediaList.objects.exists())
        response = self.client.post(reverse("list-create"), {"title": "Private okay", "description": "", "visibility": "private"})
        self.assertEqual(response.status_code, 302)
        EmailVerification.objects.create(user=self.owner, verified_at=timezone.now())
        item = MediaList.objects.get()
        response = self.client.post(reverse("list-edit", args=[item.pk]), {"title": item.title, "description": "", "visibility": "public"})
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.visibility, "public")

    def test_mixed_media_duplicates_ordering_and_deletion(self):
        item = MediaList.objects.create(owner=self.owner, title="Mixed")
        self.client.force_login(self.owner)
        self.client.post(reverse("list-add-work", args=[item.pk, self.work_a.pk]))
        self.client.post(reverse("list-add-work", args=[item.pk, self.work_b.pk]))
        self.client.post(reverse("list-add-work", args=[item.pk, self.work_a.pk]))
        self.assertEqual(item.entries.count(), 2)
        second = item.entries.get(work=self.work_b)
        self.client.post(reverse("list-entry-move", args=[item.pk, second.pk, "up"]))
        self.assertEqual(list(item.entries.values_list("work_id", flat=True)), [self.work_b.pk, self.work_a.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            MediaListEntry.objects.create(media_list=item, work=self.work_a, position=3)
        self.client.post(reverse("list-delete", args=[item.pk]))
        self.assertFalse(MediaList.objects.filter(pk=item.pk).exists())

    def test_unpublished_work_details_hidden_publicly_but_owner_warned(self):
        item = MediaList.objects.create(owner=self.owner, title="Public", visibility="public")
        MediaListEntry.objects.create(media_list=item, work=self.work_a, commentary="My private-ish note", position=1)
        self.work_a.visibility = Work.Visibility.DRAFT
        self.work_a.save()
        response = self.client.get(item.get_absolute_url())
        self.assertNotContains(response, self.work_a.title)
        self.assertNotContains(response, "My private-ish note")
        self.client.force_login(self.owner)
        response = self.client.get(item.get_absolute_url())
        self.assertContains(response, "Unavailable work")
        self.assertNotContains(response, self.work_a.title)

    def test_discovery_only_contains_public_lists_and_search_is_owner_scoped(self):
        MediaList.objects.create(owner=self.owner, title="Private secret")
        public = MediaList.objects.create(owner=self.owner, title="Shared", visibility="public")
        response = self.client.get(reverse("public-lists"))
        self.assertContains(response, "Shared")
        self.assertNotContains(response, "Private secret")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("list-work-search", args=[public.pk]), {"q": "Published"}).status_code, 404)


class ContributionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user("member", "member@example.test", "password123")
        cls.other = get_user_model().objects.create_user("other-member", "other@example.test", "password123")
        cls.reviewer = get_user_model().objects.create_user("reviewer", "reviewer@example.test", "password123", is_staff=True)
        cls.reviewer.user_permissions.add(Permission.objects.get(codename="review_contributionproposal"))
        EmailVerification.objects.create(user=cls.member, verified_at=timezone.now())
        cls.kind = WorkType.objects.create(code="contribution-book", label="Book", medium="text")
        cls.work = Work.objects.create(title="Old title", slug="old-title", description="Old description", work_type=cls.kind, visibility="public")
        cls.target = Work.objects.create(title="Target", slug="target", work_type=cls.kind, visibility="public")
        cls.rel_type = RelationshipType.objects.create(code="inspired-by-test", label="Inspired by", inverse_label="Inspired", category="derivation")

    def correction_data(self, **updates):
        data = {"field_name": "title", "proposed_value": "Better title", "explanation": "The publisher listing uses this title.", "source_url": "https://example.test/source"}
        data.update(updates)
        return data

    def proposal(self, **updates):
        values = dict(kind="correction", submitted_by=self.member, work=self.work, field_name="title",
            value_at_submission=self.work.title, proposed_value="Better title", work_updated_at=self.work.updated_at,
            explanation="Sourced correction", source_url="https://example.test/source")
        values.update(updates)
        return ContributionProposal.objects.create(**values)

    def test_login_verification_validation_and_content_preservation(self):
        url = reverse("suggest-correction", args=[self.work.pk])
        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")
        self.client.force_login(self.other)
        response = self.client.post(url, self.correction_data())
        self.assertContains(response, "Verify your email")
        self.assertContains(response, "Better title")
        self.assertFalse(ContributionProposal.objects.exists())
        self.client.force_login(self.member)
        response = self.client.post(url, self.correction_data(source_url="ftp://unsafe.test/file"))
        self.assertContains(response, "Use an HTTP or HTTPS source URL")
        self.assertFalse(ContributionProposal.objects.exists())
        self.assertRedirects(self.client.post(url, self.correction_data()), reverse("my-contributions"))

    def test_private_contribution_history_is_owner_scoped(self):
        proposal = self.proposal()
        self.client.force_login(self.other)
        response = self.client.get(reverse("my-contributions"))
        self.assertNotContains(response, proposal.explanation)
        self.client.force_login(self.member)
        response = self.client.get(reverse("my-contributions"))
        self.assertContains(response, proposal.explanation)
        self.assertContains(response, "not yet independently reviewed")
        self.assertNotContains(response, self.reviewer.email)

    def test_approval_is_atomic_audited_and_cannot_repeat(self):
        proposal = self.proposal()
        with self.assertRaises(PermissionDenied):
            proposal.review(reviewer=self.member, approve=True)
        proposal.review(reviewer=self.reviewer, approve=True, explanation="Checked against source")
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, "Better title")
        revision = ContributionRevision.objects.get(proposal=proposal)
        self.assertEqual((revision.previous_value, revision.new_value), ("Old title", "Better title"))
        self.assertEqual(revision.contributor, self.member)
        with self.assertRaises(ValidationError):
            proposal.review(reviewer=self.reviewer, approve=True)
        self.assertEqual(ContributionRevision.objects.count(), 1)

    def test_rejection_requires_explanation_and_does_not_change_catalog(self):
        proposal = self.proposal()
        with self.assertRaises(ValidationError):
            proposal.review(reviewer=self.reviewer, approve=False)
        proposal.review(reviewer=self.reviewer, approve=False, explanation="Source does not support this.")
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, "Old title")
        self.assertFalse(ContributionRevision.objects.exists())

    def test_stale_proposal_requires_explicit_reconciliation(self):
        proposal = self.proposal()
        self.work.title = "An intervening edit"
        self.work.save()
        with self.assertRaises(ValidationError):
            proposal.review(reviewer=self.reviewer, approve=True)
        proposal.review(reviewer=self.reviewer, approve=True, explanation="Reconciled manually", reconcile=True)
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, "Better title")

    def test_relationship_direction_duplicates_and_self_links(self):
        self.client.force_login(self.member)
        url = reverse("suggest-relationship", args=[self.work.pk])
        data = {"related_work": self.target.pk, "relationship_type": self.rel_type.pk,
                "explanation": "Documented connection", "source_url": "https://example.test/relationship"}
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse("my-contributions"))
        proposal = ContributionProposal.objects.get(kind="relationship")
        self.assertContains(self.client.get(reverse("my-contributions")), "Old title — Inspired by — Target")
        proposal.review(reviewer=self.reviewer, approve=True)
        relationship = WorkRelationship.objects.get()
        self.assertEqual((relationship.from_work, relationship.to_work), (self.work, self.target))
        response = self.client.post(url, data)
        self.assertContains(response, "already exists")
        invalid = ContributionProposal(kind="relationship", submitted_by=self.member, work=self.work,
            related_work=self.work, relationship_type=self.rel_type, work_updated_at=self.work.updated_at,
            related_work_updated_at=self.work.updated_at, explanation="x", source_url="https://example.test")
        with self.assertRaises(ValidationError): invalid.full_clean()

    def test_approved_imported_field_remains_an_editorial_override(self):
        source = Source.objects.create(title="Importer", url="https://example.test")
        record = source.records.create(external_key="OL999W", matched_work=self.work, payload_hash="a", raw_payload={}, retrieved_at=timezone.now())
        ImportedWorkState.objects.create(source_record=record, imported_title="Old title")
        proposal = self.proposal()
        proposal.review(reviewer=self.reviewer, approve=True)
        # This is the importer's protection contract: accepted supplier state advances,
        # while a current value differing from its previous state is left untouched.
        previous = ImportedWorkState.objects.get(source_record=record)
        if self.work.title == previous.imported_title:
            self.work.title = "Supplier replacement"
        previous.imported_title = "Supplier replacement"
        previous.save()
        self.work.refresh_from_db()
        self.assertEqual(self.work.title, "Better title")

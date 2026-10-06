import json
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import EmailVerification
from .access import link_snapshot
from .forms import AccessProposalForm
from .models import AccessLink, ContributionProposal, Work, WorkType, Version, Release, Source, WorkSource, WorkRelationship, RelationshipType


class AccessTests(TestCase):
    def setUp(self):
        kind = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="Fixture Book", work_type=kind, visibility="public")
        self.user = get_user_model().objects.create_user(username="member")
        EmailVerification.objects.create(user=self.user, verified_at=timezone.now())
        self.reviewer = get_user_model().objects.create_user(username="reviewer")
        self.reviewer.user_permissions.add(Permission.objects.get(codename="review_contributionproposal"))

    def link(self, **values):
        return AccessLink.objects.create(work=self.work, provider="Fixture Provider", url="https://example.org/read", **values)

    def data(self, **values):
        return dict(action="replace", provider="Fixture Provider", url="https://example.org/read", category="full",
                    explanation="PRIVATE explanation", source_url="https://example.org/evidence", **values)

    def proposal(self, target=None, **data):
        form = AccessProposalForm(self.data(**data), work=self.work, target=target)
        self.assertTrue(form.is_valid(), form.errors)
        proposal = ContributionProposal(kind="access", work=self.work, submitted_by=self.user,
            work_updated_at=self.work.updated_at, target_access_link=target, proposed_value=form.payload(),
            explanation="PRIVATE explanation", source_url="https://example.org/evidence")
        proposal.value_at_submission = proposal.current_value
        proposal.full_clean(); proposal.save()
        return proposal

    def test_direct_offers_reference_unknown_and_search_are_separate(self):
        catalog = self.link(category="catalog")
        unknown = self.link(category="unknown")
        search = self.link(category="search")
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "No known access links")
        self.assertContains(response, "Search Fixture Provider")
        self.assertContains(response, "Purpose unknown")
        self.assertContains(response, "Availability is not verified")
        self.link(category="full", restrictions="Account required", region="US")
        self.link(category="excerpt")
        self.link(category="subscription")
        response = self.client.get(self.work.get_absolute_url())
        self.assertNotContains(response, "No known access links")
        self.assertContains(response, "Direct access")
        self.assertContains(response, "Excerpt / sample / trailer")
        self.assertContains(response, "Account required")
        self.assertContains(response, "Region: US")
        self.assertContains(response, "Content / offer not checked")
        self.assertLess(response.content.index(b"Direct access"), response.content.index(b"Reference / catalog and unclassified"))
        self.assertNotContains(response, "PRIVATE explanation")

    def test_legacy_sources_are_preserved_and_not_promoted(self):
        source = Source.objects.create(title="Old catalog", url="https://example.org/catalog")
        WorkSource.objects.create(work=self.work, source=source)
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "No known access links")
        self.assertContains(response, "Old catalog")
        self.assertNotContains(response, "View source or availability")
        self.assertContains(response, "Search Open Library")

    def test_version_release_scope_and_cross_work_rejection(self):
        version = Version.objects.create(work=self.work, label="French translation", kind="translation", language="French")
        release = Release.objects.create(version=version, title="1999 edition")
        self.link(category="borrow", version=version, release=release)
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "French translation — 1999 edition")
        other = Work.objects.create(title="Other", work_type=self.work.work_type)
        wrong = AccessLink(work=other, provider="Other", url="https://example.org", version=version)
        with self.assertRaises(ValidationError): wrong.full_clean()
        form = AccessProposalForm(self.data(version=version.pk), work=other)
        self.assertFalse(form.is_valid())

    def test_no_adaptation_link_inheritance_and_media_labels(self):
        self.link(category="full")
        relation = RelationshipType.objects.create(code="adapted-from", label="Adapted from", inverse_label="Adaptations")
        source = Source.objects.create(title="Adaptation evidence", url="https://example.org/evidence")
        for code, medium, label in (("film", "screen", "Watch"), ("album", "audio", "Listen")):
            kind = WorkType.objects.create(code=code, label=code, medium=medium)
            work = Work.objects.create(title=f"Fixture {code}", work_type=kind, visibility="public")
            if code == "film":
                WorkRelationship.objects.create(from_work=work, to_work=self.work, relationship_type=relation, source=source, review_status="accepted")
            self.assertNotContains(self.client.get(work.get_absolute_url()), "Fixture Provider")
            self.assertContains(self.client.get(work.get_absolute_url()), f'id="access-heading">{label}')
            self.assertContains(self.client.get(work.get_absolute_url()), "No known access links")
        self.work.title = ""; self.work.save()
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), "Search Open Library")

    def test_url_validation_and_safe_rendering(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "https://user:password@example.org/read", "not a url"):
            data = self.data(); data["url"] = url
            self.assertFalse(AccessProposalForm(data, work=self.work).is_valid(), url)
            data = self.data(); data["source_url"] = url
            self.assertFalse(AccessProposalForm(data, work=self.work).is_valid(), url)
        link = self.link(category="full")
        AccessLink.objects.filter(pk=link.pk).update(url="javascript:alert(1)")
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), "javascript:")
        self.link(category="excerpt", scope_note='<script>alert("x")</script>')
        self.assertContains(self.client.get(self.work.get_absolute_url()), "&lt;script&gt;")

    def test_submission_permissions_and_no_automatic_publication(self):
        url = reverse("suggest-access", args=[self.work.pk])
        self.assertEqual(self.client.post(url, self.data()).status_code, 302)
        self.assertEqual(ContributionProposal.objects.count(), 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, self.data()).status_code, 302)
        self.assertFalse(AccessLink.objects.exists())
        proposal = ContributionProposal.objects.get()
        with self.assertRaises(PermissionDenied): proposal.review(reviewer=self.user, approve=True)
        proposal.review(reviewer=self.reviewer, approve=True)
        self.assertTrue(AccessLink.objects.exists())
        self.assertEqual(AccessLink.objects.get().proposals.get(), proposal)
        self.assertEqual(proposal.revision.source_url, "https://example.org/evidence")
        EmailVerification.objects.filter(user=self.user).update(verified_at=None)
        self.assertEqual(self.client.post(url, self.data()).status_code, 200)
        self.assertEqual(ContributionProposal.objects.count(), 1)

    def test_conflicts_removal_and_review_history(self):
        link = self.link(category="full")
        proposal = self.proposal(link)
        link.region = "GB"; link.save()
        with self.assertRaises(ValidationError): proposal.review(reviewer=self.reviewer, approve=True)
        proposal.review(reviewer=self.reviewer, approve=True, reconcile=True)
        self.assertIn('"region": "GB"', proposal.revision.previous_value)
        link.refresh_from_db()
        data = self.data(); data["action"] = "remove"
        form = AccessProposalForm(data, work=self.work, target=link, instance=AccessLink.objects.get(pk=link.pk))
        self.assertTrue(form.is_valid(), form.errors)
        report = ContributionProposal.objects.create(kind="access", work=self.work, submitted_by=self.user,
            work_updated_at=self.work.updated_at, target_access_link=link, proposed_value=form.payload(),
            value_at_submission=link_snapshot(link), explanation="Broken", source_url=link.url)
        report.review(reviewer=self.reviewer, approve=True)
        link.refresh_from_db(); self.assertFalse(link.active)
        self.assertEqual(AccessLink.objects.count(), 1)
        self.assertEqual(link.proposals.count(), 2)
        self.assertContains(self.client.get(self.work.get_absolute_url()), "No known access links")

    def test_clarification_owner_and_resubmission(self):
        proposal = self.proposal()
        proposal.request_clarification(reviewer=self.reviewer, explanation="Which edition?")
        with self.assertRaises(PermissionDenied):
            proposal.resubmit(contributor=self.reviewer, proposed_value=proposal.proposed_value)
        self.client.force_login(self.user)
        response = self.client.post(reverse("resubmit-contribution", args=[proposal.pk]), self.data())
        self.assertEqual(response.status_code, 302)
        replacement = ContributionProposal.objects.get(supersedes=proposal)
        replacement.review(reviewer=self.reviewer, approve=True)
        proposal.refresh_from_db(); self.assertEqual(proposal.status, "superseded")
        self.assertEqual(replacement.revision.explanation, "PRIVATE explanation")

    def test_hidden_work_and_mismatched_target(self):
        link = self.link(category="full")
        other = Work.objects.create(title="Other", work_type=self.work.work_type, visibility="public")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("suggest-access", args=[other.pk]) + f"?link={link.pk}").status_code, 404)
        self.work.visibility = "draft"; self.work.save()
        self.assertEqual(self.client.get(reverse("suggest-access", args=[self.work.pk])).status_code, 404)

    def test_no_domain_or_http_based_access_inference(self):
        from unittest.mock import patch
        source = Source.objects.create(title="Archive reference", url="https://archive.org/details/fixture")
        WorkSource.objects.create(work=self.work, source=source)
        self.assertContains(self.client.get(self.work.get_absolute_url()), "No known access links")
        self.client.force_login(self.user)
        data = self.data(); data["category"] = "unknown"
        with patch("urllib.request.urlopen") as fetch:
            self.client.post(reverse("suggest-access", args=[self.work.pk]), data)
            fetch.assert_not_called()
        proposal = ContributionProposal.objects.get()
        proposal.review(reviewer=self.reviewer, approve=True)
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "No known access links")
        self.assertNotContains(response, "Free access")
        self.assertNotContains(response, "Public domain")

    def test_unsafe_persisted_proposal_cannot_be_approved(self):
        proposal = self.proposal()
        values = json.loads(proposal.proposed_value); values["url"] = "javascript:alert(1)"
        proposal.proposed_value = json.dumps(values); proposal.save()
        with self.assertRaises(ValidationError): proposal.review(reviewer=self.reviewer, approve=True)
        self.assertFalse(AccessLink.objects.exists())
        proposal.refresh_from_db(); self.assertEqual(proposal.status, "pending")

    def test_invalid_target_and_future_check_date(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("suggest-access", args=[self.work.pk]) + "?link=invalid").status_code, 404)
        data = self.data(last_checked="2099-01-01")
        self.assertFalse(AccessProposalForm(data, work=self.work).is_valid())


class AccessPreviewFixtureTests(TestCase):
    fixtures = ["access_preview"]

    def test_representative_pages(self):
        for pk, label in ((1, "Read"), (2, "Watch"), (3, "Listen"), (4, "Read")):
            work = Work.objects.get(pk=pk)
            response = self.client.get(work.get_absolute_url())
            self.assertContains(response, "Demonstration record")
            self.assertContains(response, f'id="access-heading">{label}')
        self.assertContains(self.client.get(Work.objects.get(pk=4).get_absolute_url()), "No known access links")

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import EmailVerification
from .models import (Work, WorkType, Source, SourceRecord, ImportedWorkState, WorkSource,
                     ContributionProposal, RelationshipType, WorkRelationship, FieldEvidence)
from .provenance import work_provenance, record_evidence, safe_url
from .importers.openlibrary import OpenLibraryImporter
from .tests import fake_open


class ProvenanceTests(TestCase):
    def setUp(self):
        self.kind = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="Selected", work_type=self.kind, visibility="public",
                                       first_publication_date_text="1900")
        self.source = Source.objects.create(title="Fixture source", url="https://example.org/work", notes="PRIVATE SOURCE NOTE")
        self.user = get_user_model().objects.create_user(username="contributor", password="pass")
        EmailVerification.objects.create(user=self.user, verified_at=timezone.now())
        self.reviewer = get_user_model().objects.create_user(username="reviewer")
        self.reviewer.user_permissions.add(Permission.objects.get(codename="review_contributionproposal"))

    def snapshot(self, title="Alternative", payload=None):
        record = SourceRecord.objects.create(source=self.source, external_key="OL1W", matched_work=self.work,
            payload_hash="x", raw_payload=payload or {"title": title, "private_note": "PRIVATE PAYLOAD NOTE"}, retrieved_at=timezone.now())
        ImportedWorkState.objects.create(source_record=record, imported_title=title)
        return record

    def proposal(self, field="title", value="Reviewed", relationship=None):
        proposal = ContributionProposal(kind="correction", work=self.work, field_name=field,
            proposed_value=value, target_relationship=relationship, submitted_by=self.user,
            work_updated_at=self.work.updated_at, source_url="https://example.org/correction", explanation="PRIVATE CONTRIBUTOR TEXT")
        proposal.value_at_submission = proposal.current_value
        proposal.full_clean()
        proposal.save()
        return proposal

    def test_direct_source_and_safe_escaping(self):
        record_evidence(self.work, "title", self.work.title, source=self.source,
                        source_url=self.source.url, note='<script>alert("x")</script>')
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, self.source.url)
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(')

    def test_imported_unreviewed_associations(self):
        importer = OpenLibraryImporter(delay=0, opener=fake_open([{"title": "Imported", "first_publish_date": "1901"}]))
        work = importer.import_work("OL2W").work
        data = work_provenance(work)
        self.assertTrue(data["title"]["entries"][0]["state"].startswith("Imported from"))
        self.assertIsNone(data["title"]["entries"][0]["reviewed_at"])
        self.assertIn("process classification", data["work_type"]["entries"][0]["note"])

    def test_general_links_do_not_support_fields(self):
        WorkSource.objects.create(work=self.work, source=self.source)
        response = self.client.get(self.work.get_absolute_url())
        self.assertEqual(response.context["provenance"]["title"]["entries"], [])
        self.assertContains(response, "Source not recorded for this field")

    def test_normalized_type_is_traceable(self):
        self.work.work_type = WorkType.objects.create(code="creative-work", label="Creative work", medium="other")
        self.work.save()
        self.snapshot(title=self.work.title, payload={"id": "Q1", "claims": {"P31": [
            {"mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "Q8261"}}}}]}})
        response = self.client.get(self.work.get_absolute_url())
        self.assertEqual(response.context["provenance"]["work_type"]["value"], "Novel")
        self.assertContains(response, "P31/P7937")
        self.assertContains(response, "https://www.wikidata.org/wiki/Q1")

    def test_genuine_title_conflict_is_recorded(self):
        self.snapshot()
        selected_source = Source.objects.create(title="Selected source", url="https://example.org/selected")
        record_evidence(self.work, "title", self.work.title, source=selected_source, source_url=selected_source.url)
        data = work_provenance(self.work)["title"]
        self.assertTrue(data["conflict"])
        self.assertEqual(data["alternatives"][0]["value"], "Alternative")

    def test_reviewed_correction_preserves_history_and_privacy(self):
        record_evidence(self.work, "title", self.work.title, source=self.source, source_url=self.source.url)
        proposal = self.proposal()
        proposal.review(reviewer=self.reviewer, approve=True, explanation="PRIVATE REVIEW NOTE")
        self.work.refresh_from_db()
        response = self.client.get(self.work.get_absolute_url())
        data = response.context["provenance"]["title"]
        self.assertEqual(data["entries"][0]["state"], "Human-reviewed")
        self.assertEqual(data["history"][-1]["value"], "Selected")
        for private in ("PRIVATE REVIEW NOTE", "PRIVATE CONTRIBUTOR TEXT", "PRIVATE SOURCE NOTE", "contributor", "reviewer"):
            self.assertNotContains(response, private)

    def test_replacement_and_reversion_do_not_reuse_old_evidence(self):
        record_evidence(self.work, "title", "Selected", source=self.source, source_url=self.source.url)
        self.work.title = "Changed"
        self.work.save(update_fields=["title"])
        self.assertEqual(work_provenance(self.work)["title"]["entries"][0]["state"], "Source not recorded for this field")
        self.work.title = "Selected"
        self.work.save()
        self.assertEqual(work_provenance(self.work)["title"]["entries"][0]["state"], "Source not recorded for this field")
        self.assertTrue(FieldEvidence.objects.filter(work=self.work, current=False, source=self.source).exists())

    def test_private_payload_not_serialized(self):
        self.snapshot(title=self.work.title)
        response = self.client.get(self.work.get_absolute_url())
        self.assertNotContains(response, "PRIVATE PAYLOAD NOTE")
        self.assertNotContains(response, "PRIVATE SOURCE NOTE")

    def test_exact_field_correction_prefill_and_pending_submission(self):
        self.client.force_login(self.user)
        url = reverse("suggest-correction", args=[self.work.pk])
        response = self.client.get(url, {"field": "first_publication_date_text"})
        self.assertEqual(response.context["form"].initial["field_name"], "first_publication_date_text")
        self.assertEqual(response.context["current_value"], "1900")
        self.client.post(url, {"field_name": "first_publication_date_text", "proposed_value": "1902",
                               "explanation": "Fixture", "source_url": "https://example.org/date"})
        proposal = ContributionProposal.objects.get()
        self.assertEqual(proposal.value_at_submission, "1900")
        self.assertEqual(proposal.status, "pending")
        self.work.refresh_from_db()
        self.assertEqual(self.work.first_publication_date_text, "1900")

    def relationship(self):
        other = Work.objects.create(title="Other", work_type=self.kind, visibility="public")
        kind, _ = RelationshipType.objects.get_or_create(code="based-on", defaults={"label": "Based on", "inverse_label": "Derivations"})
        return WorkRelationship.objects.create(from_work=self.work, to_work=other, relationship_type=kind,
            source=self.source, review_status="accepted", scope_note="Original note",
            evidence={"authorization_statement": "A fixture statement", "private_note": "PRIVATE RELATIONSHIP NOTE"})

    def test_relationship_and_existing_rights_use_shared_disclosure(self):
        rel = self.relationship()
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "Attributed rights statement")
        self.assertContains(response, f"relationship={rel.pk}")
        self.assertNotContains(response, "PRIVATE RELATIONSHIP NOTE")
        self.assertContains(response, "human review date not recorded")

    def test_relationship_correction_stable_target_and_review(self):
        rel = self.relationship()
        self.client.force_login(self.user)
        url = reverse("suggest-correction", args=[self.work.pk])
        response = self.client.get(url, {"field": "scope_note", "relationship": rel.pk})
        self.assertEqual(response.context["current_value"], "Original note")
        response = self.client.post(url, {"target_relationship": rel.pk, "field_name": "scope_note",
            "proposed_value": "New note", "explanation": "Fixture", "source_url": "https://example.org/new"})
        self.assertEqual(response.status_code, 302)
        proposal = ContributionProposal.objects.get()
        self.assertEqual(proposal.target_relationship_id, rel.pk)
        rel.refresh_from_db()
        self.assertEqual(rel.scope_note, "Original note")
        proposal.review(reviewer=self.reviewer, approve=True)
        rel.refresh_from_db()
        self.assertEqual(rel.scope_note, "New note")
        self.assertEqual(rel.evidence["correction_history"][0]["value"], "Original note")

    def test_relationship_type_change_invalidates_old_evidence(self):
        rel = self.relationship()
        rel.relationship_type = RelationshipType.objects.create(code="remake", label="Remake", inverse_label="Remakes")
        rel.save()
        self.assertTrue(rel.evidence["source_invalidated"])
        self.assertFalse(rel.authorization_statement)
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "Source not recorded for this field")

    def test_relationship_correction_cannot_target_another_work(self):
        rel = self.relationship()
        self.client.force_login(self.user)
        response = self.client.post(reverse("suggest-correction", args=[rel.to_work_id]), {
            "target_relationship": rel.pk, "field_name": "scope_note", "proposed_value": "Bad",
            "explanation": "Fixture", "source_url": "https://example.org"})
        self.assertEqual(response.status_code, 404)

    def test_bounded_queries(self):
        self.snapshot(title=self.work.title)
        self.relationship()
        record_evidence(self.work, "title", self.work.title, source=self.source, source_url=self.source.url)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.work.get_absolute_url())
        for index in range(5):
            rel = self.relationship()
            record_evidence(self.work, "title", self.work.title, source=self.source, source_url=self.source.url)
        with CaptureQueriesContext(connection) as after:
            self.client.get(self.work.get_absolute_url())
        self.assertEqual(len(before), len(after))

    def test_url_schemes_and_credentials_rejected(self):
        for value in ("javascript:alert(1)", "https://user:password@example.org", "file:///etc/passwd"):
            self.assertEqual(safe_url(value), "")

    def test_work_type_correction_is_reviewed(self):
        WorkType.objects.create(code="play", label="Play", medium="text")
        proposal = self.proposal("work_type", "play")
        proposal.review(reviewer=self.reviewer, approve=True)
        self.work.refresh_from_db()
        self.assertEqual(self.work.work_type_id, "play")
        self.assertEqual(work_provenance(self.work)["work_type"]["entries"][0]["state"], "Human-reviewed")

    def test_rights_correction_retains_exact_field_and_history(self):
        rel = self.relationship()
        proposal = self.proposal("authorization_statement", "Corrected fixture statement", rel)
        proposal.review(reviewer=self.reviewer, approve=True)
        rel.refresh_from_db()
        self.assertEqual(rel.authorization_statement, "Corrected fixture statement")
        self.assertEqual(rel.evidence["correction_history"][0]["value"], "A fixture statement")
        response = self.client.get(self.work.get_absolute_url())
        self.assertContains(response, "https://example.org/correction")

    def test_relationship_type_correction_keeps_endpoints(self):
        rel = self.relationship()
        RelationshipType.objects.create(code="remake", label="Remake", inverse_label="Remakes")
        proposal = self.proposal("relationship_type", "remake", rel)
        proposal.review(reviewer=self.reviewer, approve=True)
        rel.refresh_from_db()
        self.assertEqual(rel.relationship_type_id, "remake")
        self.assertEqual(rel.from_work_id, self.work.pk)
        self.assertFalse(rel.authorization_statement)
        self.assertIn("correction_history", rel.evidence)

    def test_resubmission_preserves_relationship_target(self):
        rel = self.relationship()
        proposal = self.proposal("scope_note", "Updated", rel)
        proposal.request_clarification(reviewer=self.reviewer, explanation="Add a source")
        replacement = proposal.resubmit(contributor=self.user, proposed_value="Clarified", explanation="Fixture",
                                        source_url="https://example.org/clarified")
        self.assertEqual(replacement.target_relationship_id, rel.pk)
        self.assertEqual(replacement.field_name, "scope_note")
        self.assertEqual(replacement.value_at_submission, "Original note")

    def test_first_legacy_date_edit_preserves_recorded_support(self):
        self.work.date_evidence = {"date_text": "1900", "source_url": "https://example.org/legacy-date"}
        self.work.save()
        self.work.first_publication_date_text = "1901"
        self.work.save()
        data = work_provenance(self.work)["first_publication_date_text"]
        self.assertEqual(data["entries"][0]["state"], "Source not recorded for this field")
        self.assertEqual(data["history"][0]["url"], "https://example.org/legacy-date")

    def test_correction_flow_cannot_introduce_new_rights_statement(self):
        rel = self.relationship()
        rel.evidence = {}
        rel.save()
        self.client.force_login(self.user)
        url = reverse("suggest-correction", args=[self.work.pk])
        response = self.client.post(url, {"target_relationship": rel.pk, "field_name": "authorization_statement",
            "proposed_value": "New claim", "explanation": "Fixture", "source_url": "https://example.org/new"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ContributionProposal.objects.exists())

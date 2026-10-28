"""Tests for shared publication rules and the commands that use them.

The pipeline must agree on what a seed is, what may be promoted, and what a
publication audit reports. These tests pin those rules and cover the commands
that previously had no coverage.
"""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .management.commands.triage_proposals import evaluate_proposal
from .models import (
    Agent,
    Credit,
    ExternalIdentifier,
    ImportItem,
    ImportRelationshipProposal,
    ImportRun,
    RelationshipType,
    Source,
    Work,
    WorkType,
)
from .publication import blocking_reasons, is_seed, publication_warnings


class PublicationRulesTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")

    def work(self, **kwargs):
        defaults = {
            "title": "A Catalog Work",
            "slug": f"work-{Work.objects.count()}",
            "work_type": self.book,
            "visibility": Work.Visibility.PUBLIC,
            "first_publication_year": 1910,
        }
        defaults.update(kwargs)
        return Work.objects.create(**defaults)

    def test_seed_scope_requires_public_and_respects_depth(self):
        editorial = self.work(depth="editorial")
        indexed = self.work(depth="index")
        draft = self.work(depth="editorial", visibility=Work.Visibility.DRAFT)
        self.assertTrue(is_seed(editorial, "editorial"))
        self.assertFalse(is_seed(indexed, "editorial"))
        self.assertTrue(is_seed(indexed, "public"))
        self.assertFalse(is_seed(draft, "public"))
        self.assertFalse(is_seed(draft, "any"))
        with self.assertRaises(ValueError):
            is_seed(editorial, "unknown")

    def test_publication_warnings_flag_sparse_and_noisy_records(self):
        author = Agent.objects.create(name="Catalog Author", kind="person")
        complete = self.work(title="A Complete Record")
        Credit.objects.create(work=complete, agent=author, role="author")
        self.assertEqual(publication_warnings(complete), [])

        sparse = self.work(title="Q1234", first_publication_year=None,
                           work_type=WorkType.objects.create(code="creative-work", label="Creative work", medium="other"))
        self.assertEqual(
            set(publication_warnings(sparse)),
            {"no_date", "no_creator", "generic_type", "placeholder_title"},
        )
        noisy = self.work(title="Mileage Log Book for Car Taxes / 176 Pages / Fuel and Expenses Tracking / Vehicle Conditions")
        self.assertIn("long_title", publication_warnings(noisy))

    def test_blocking_reasons_include_requested_requirements(self):
        undated = self.work(first_publication_year=None)
        self.assertEqual(blocking_reasons(undated), [])
        self.assertIn("no_date", blocking_reasons(undated, require=("no_date",)))


class PromoteWorksTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")

    def work(self, **kwargs):
        defaults = {
            "title": "Promotable Work",
            "slug": f"work-{Work.objects.count()}",
            "work_type": self.book,
            "visibility": Work.Visibility.DRAFT,
            "first_publication_year": 1950,
        }
        defaults.update(kwargs)
        return Work.objects.create(**defaults)

    def test_dry_run_does_not_change_visibility(self):
        work = self.work()
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "promote.json"
            call_command("promote_works", ids=str(work.pk), report=report)
            work.refresh_from_db()
            self.assertEqual(work.visibility, Work.Visibility.DRAFT)
            self.assertEqual(json.loads(report.read_text())["promoted"][0]["work"], work.pk)

    def test_confirm_promotes_and_sets_requested_depth(self):
        work = self.work()
        call_command("promote_works", ids=str(work.pk), depth="editorial", confirm=True)
        work.refresh_from_db()
        self.assertEqual((work.visibility, work.depth), (Work.Visibility.PUBLIC, "editorial"))

    def test_placeholder_titles_block_unless_forced(self):
        work = self.work(title="Q987654", slug="qid-only")
        call_command("promote_works", ids=str(work.pk), confirm=True)
        work.refresh_from_db()
        self.assertEqual(work.visibility, Work.Visibility.DRAFT)
        call_command("promote_works", ids=str(work.pk), force=True, confirm=True)
        work.refresh_from_db()
        self.assertEqual(work.visibility, Work.Visibility.PUBLIC)

    def test_required_warnings_block_promotion(self):
        work = self.work(first_publication_year=None)
        call_command("promote_works", ids=str(work.pk), require="no_date", confirm=True)
        work.refresh_from_db()
        self.assertEqual(work.visibility, Work.Visibility.DRAFT)


class AuditPublicQualityTests(TestCase):
    def test_report_flags_public_works_without_dates(self):
        book = WorkType.objects.create(code="book", label="Book", medium="text")
        Work.objects.create(title="Dated Work", slug="dated", work_type=book,
                            visibility=Work.Visibility.PUBLIC, first_publication_year=1900)
        Work.objects.create(title="Undated Work", slug="undated", work_type=book,
                            visibility=Work.Visibility.PUBLIC)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "quality.json"
            call_command("audit_public_quality", output=output)
            report = json.loads(output.read_text())
        self.assertEqual(report["flagged"], 2)
        self.assertIn("no_date", report["summary"])
        self.assertEqual({row["title"] for row in report["rows"]}, {"Dated Work", "Undated Work"})


class TriageSeedScopeTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")
        self.reltype = RelationshipType.objects.create(
            code="based-on", label="Based on", inverse_label="Works based on this", category="derivation"
        )
        self.run = ImportRun.objects.create(source=self.source, requested_keys=["Q1"])
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")

    def test_seed_scope_decides_target_not_seed(self):
        seed = Work.objects.create(title="Source Seed", slug="seed", work_type=self.book,
                                   visibility=Work.Visibility.PUBLIC, depth="index",
                                   first_publication_year=1600)
        work = Work.objects.create(title="An Adaptation", slug="adaptation", work_type=self.book,
                                   visibility=Work.Visibility.DRAFT, first_publication_year=1999)
        proposal = ImportRelationshipProposal.objects.create(
            run=self.run, statement_id="Q2$stmt", from_work=work, to_work=seed,
            relationship_type=self.reltype, source=self.source,
            evidence={"property_id": "P144", "entity_id": "Q2", "statement_id": "Q2$stmt", "rank": "normal"},
        )
        editorial = evaluate_proposal(proposal, "Q2", 1, "", 1, 2026, 3, "editorial")
        self.assertIn("target_not_seed", editorial[1])
        public = evaluate_proposal(proposal, "Q2", 1, "", 1, 2026, 3, "public")
        self.assertNotIn("target_not_seed", public[1])


class SeedRelationshipTypesTests(TestCase):
    def test_vocabulary_is_seeded_idempotently(self):
        call_command("seed_relationship_types")
        first = RelationshipType.objects.count()
        call_command("seed_relationship_types")
        self.assertEqual(RelationshipType.objects.count(), first)
        self.assertTrue(RelationshipType.objects.filter(code="based-on").exists())
        self.assertTrue(RelationshipType.objects.filter(code="derivative-work").exists())


class FillOpenLibraryEditionDatesTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="An Undated Book", slug="undated-book", work_type=self.book,
                                        visibility=Work.Visibility.DRAFT)
        ExternalIdentifier.objects.create(work=self.work, scheme="ol_work", value="OL1W")

    def test_edition_date_fills_only_drafts(self):
        with tempfile.TemporaryDirectory() as folder:
            extract = Path(folder)
            (extract / "records.jsonl").write_text(json.dumps({
                "work": {"key": "/works/OL1W"},
                "editions": [
                    {"key": "/books/OL2M", "publish_date": "1999"},
                    {"key": "/books/OL3M", "publish_date": "May 1980"},
                ],
            }) + "\n")
            call_command("fill_openlibrary_edition_dates", extract=extract, confirm=True)
        self.work.refresh_from_db()
        self.assertEqual((self.work.first_publication_year, self.work.date_kind), (1980, "publication"))
        self.assertEqual(self.work.date_evidence["property"], "edition:publish_date")

    def test_public_records_are_left_alone(self):
        self.work.visibility = Work.Visibility.PUBLIC
        self.work.first_publication_year = 1955
        self.work.save()
        with tempfile.TemporaryDirectory() as folder:
            extract = Path(folder)
            (extract / "records.jsonl").write_text(json.dumps({
                "work": {"key": "/works/OL1W"},
                "editions": [{"key": "/books/OL2M", "publish_date": "1999"}],
            }) + "\n")
            call_command("fill_openlibrary_edition_dates", extract=extract, confirm=True)
        self.work.refresh_from_db()
        self.assertEqual(self.work.first_publication_year, 1955)


class FakeWikidataClient:
    """Minimal stand-in for WikidataClient; no network access in tests."""

    bindings = []

    def __init__(self, *args, **kwargs):
        self.requests = 0

    def entities(self, qids):
        self.requests += 1
        return {qid: self.payload(qid) for qid in qids}

    def get_json(self, url, params, attempts=1):
        self.requests += 1
        return {"results": {"bindings": self.bindings}}

    @classmethod
    def binding(cls, qid, olid):
        return {"item": {"value": f"http://www.wikidata.org/entity/{qid}"}, "ol": {"value": olid}}

    def payload(self, qid):
        return {
            "id": qid,
            "labels": {"en": {"value": f"Entity {qid}"}},
            "descriptions": {},
            "sitelinks": {},
            "claims": {"P648": [{"mainsnak": {"datavalue": {"value": "OL1W"}}}]},
            "lastrevid": 1,
        }


class LinkOpenLibraryWikidataTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="Linking Candidate", slug="linking-candidate",
                                        work_type=self.book, visibility=Work.Visibility.DRAFT)
        ExternalIdentifier.objects.create(work=self.work, scheme="ol_work", value="OL1W")
        source = Source.objects.create(title="Open Library", url="https://openlibrary.org/")
        self.run = ImportRun.objects.create(source=source, requested_keys=["OL1W"])
        ImportItem.objects.create(run=self.run, external_key="OL1W", work=self.work)

    def test_exact_p648_match_links_without_creating_works(self):
        from unittest.mock import patch
        from .management.commands import link_openlibrary_wikidata as module

        class Client(FakeWikidataClient):
            bindings = [FakeWikidataClient.binding("Q42", "OL1W")]

        with patch.object(module, "WikidataClient", Client):
            call_command("link_openlibrary_wikidata", run_id=self.run.pk, limit=5)

        self.assertTrue(ExternalIdentifier.objects.filter(work=self.work, scheme="wikidata", value="Q42").exists())
        self.assertEqual(Work.objects.count(), 1)


class ResolveWikidataRelationshipsTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.seed = Work.objects.create(title="Editorial Seed", slug="editorial-seed", work_type=self.book,
                                        visibility=Work.Visibility.PUBLIC, depth="editorial",
                                        first_publication_year=1600)
        ExternalIdentifier.objects.create(work=self.seed, scheme="wikidata", value="Q100")
        self.folder = tempfile.TemporaryDirectory()
        self.manifest = Path(self.folder.name) / "seeds.json"
        self.manifest.write_text(json.dumps({"seeds": [{"qid": "Q100"}]}))

    def tearDown(self):
        self.folder.cleanup()

    def test_editon_claim_becomes_pending_proposal(self):
        from unittest.mock import patch
        from .management.commands import resolve_wikidata_relationships as module

        class Client(FakeWikidataClient):
            def payload(self, qid):
                base = super().payload(qid)
                if qid == "Q100":
                    base["claims"] = {"P629": [{
                        "id": "Q100$edition", "rank": "normal",
                        "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "Q200"}}},
                        "qualifiers": {}, "references": [],
                    }]}
                return base

        with patch.object(module, "WikidataClient", Client):
            call_command("resolve_wikidata_relationships", manifest=self.manifest, seed_limit=1, limit=5)

        proposal = ImportRelationshipProposal.objects.get()
        self.assertEqual(proposal.relationship_type.code, "edition-of")
        self.assertEqual(proposal.to_work_id, self.seed.pk)
        self.assertEqual(proposal.evidence["property_id"], "P629")

    def test_seed_outside_scope_is_skipped(self):
        from django.core.management.base import CommandError
        from unittest.mock import patch
        from .management.commands import resolve_wikidata_relationships as module

        self.seed.depth = "index"
        self.seed.save()
        with patch.object(module, "WikidataClient", FakeWikidataClient):
            with self.assertRaises(CommandError):
                call_command("resolve_wikidata_relationships", manifest=self.manifest, seed_limit=1, limit=5)

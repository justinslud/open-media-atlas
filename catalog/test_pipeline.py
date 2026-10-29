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
    SourceRecord,
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
        # The claim lives on the seed, so the seed is the subject of the edge.
        self.assertEqual(proposal.from_work_id, self.seed.pk)
        self.assertEqual(proposal.to_work_id, Work.objects.get(identifiers__value="Q200").pk)
        self.assertEqual(proposal.evidence["property_id"], "P629")

    def test_derivative_work_claim_is_not_marked_seed_subject(self):
        from unittest.mock import patch
        from .management.commands import resolve_wikidata_relationships as module

        class Client(FakeWikidataClient):
            def payload(self, qid):
                base = super().payload(qid)
                if qid == "Q100":
                    base["claims"] = {"P4969": [{
                        "id": "Q100$derivative", "rank": "normal",
                        "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "Q200"}}},
                        "qualifiers": {}, "references": [],
                    }]}
                return base

        with patch.object(module, "WikidataClient", Client):
            call_command("resolve_wikidata_relationships", manifest=self.manifest, seed_limit=1, limit=5)

        proposal = ImportRelationshipProposal.objects.get()
        self.assertEqual(proposal.relationship_type.code, "derivative-work")
        # P4969 is asserted on the target, so the target is the derived work.
        self.assertEqual(proposal.from_work_id, Work.objects.get(identifiers__value="Q200").pk)
        self.assertEqual(proposal.to_work_id, self.seed.pk)
        self.assertNotIn("edge_subject", proposal.evidence)

    def test_seed_outside_scope_is_skipped(self):
        from django.core.management.base import CommandError
        from unittest.mock import patch
        from .management.commands import resolve_wikidata_relationships as module

        self.seed.depth = "index"
        self.seed.save()
        with patch.object(module, "WikidataClient", FakeWikidataClient):
            with self.assertRaises(CommandError):
                call_command("resolve_wikidata_relationships", manifest=self.manifest, seed_limit=1, limit=5)


class LinkOpenLibraryEditionsTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="Edition Linked Work", slug="edition-linked",
                                        work_type=self.book, visibility=Work.Visibility.DRAFT)
        ExternalIdentifier.objects.create(work=self.work, scheme="ol_work", value="OL1W")
        self.folder = tempfile.TemporaryDirectory()
        self.extract = Path(self.folder.name)
        (self.extract / "records.jsonl").write_text(json.dumps({
            "work": {"key": "/works/OL1W"},
            "editions": [{"key": "/books/OL2M", "publish_date": "2001"}],
        }) + "\n")

    def tearDown(self):
        self.folder.cleanup()

    def test_edition_p629_target_links_the_work(self):
        from unittest.mock import patch
        from .management.commands import link_openlibrary_editions as module

        class Client(FakeWikidataClient):
            def get_json(self, url, params, attempts=1):
                self.requests += 1
                return {"results": {"bindings": [{
                    "edition": {"value": "http://www.wikidata.org/entity/Q10"},
                    "olid": {"value": "OL2M"},
                    "work": {"value": "http://www.wikidata.org/entity/Q42"},
                }]}}

            def payload(self, qid):
                base = super().payload(qid)
                base["claims"] = {"P648": [{"mainsnak": {"datavalue": {"value": "OL1W"}}}]}
                return base

        with patch.object(module, "WikidataClient", Client):
            call_command("link_openlibrary_editions", extract=self.extract)

        self.assertTrue(ExternalIdentifier.objects.filter(work=self.work, scheme="wikidata", value="Q42").exists())

    def test_ambiguous_work_claims_are_not_linked(self):
        from unittest.mock import patch
        from .management.commands import link_openlibrary_editions as module

        class Client(FakeWikidataClient):
            def get_json(self, url, params, attempts=1):
                self.requests += 1
                return {"results": {"bindings": [
                    {"edition": {"value": "http://www.wikidata.org/entity/Q10"},
                     "olid": {"value": "OL2M"}, "work": {"value": "http://www.wikidata.org/entity/Q42"}},
                    {"edition": {"value": "http://www.wikidata.org/entity/Q11"},
                     "olid": {"value": "OL2M"}, "work": {"value": "http://www.wikidata.org/entity/Q43"}},
                ]}}

        with patch.object(module, "WikidataClient", Client):
            call_command("link_openlibrary_editions", extract=self.extract)

        self.assertFalse(ExternalIdentifier.objects.filter(work=self.work, scheme="wikidata").exists())


class BackfillWikidataCreditsTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.work = Work.objects.create(title="Creditless Work", slug="creditless", work_type=self.book,
                                        visibility=Work.Visibility.PUBLIC, first_publication_year=1900)

    def snapshot(self, key, payload, work=None):
        return SourceRecord.objects.create(
            source=self.source, external_key=key, matched_work=work, raw_payload=payload,
            payload_hash=key, retrieved_at=timezone.now(),
        )

    def test_cached_creator_claims_become_credits(self):
        claim = {"rank": "normal", "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "Q535"}}}}
        self.snapshot("Q100", {"id": "Q100", "claims": {"P50": [claim]}}, work=self.work)
        self.snapshot("Q535", {"id": "Q535", "labels": {"en": {"value": "A Cached Author"}}})
        call_command("backfill_wikidata_credits", cache_only=True)

        credit = Credit.objects.get(work=self.work)
        self.assertEqual((credit.agent.name, credit.role), ("A Cached Author", "author"))

    def test_works_with_credits_are_left_alone(self):
        existing = Agent.objects.create(name="Existing Author", kind="person")
        Credit.objects.create(work=self.work, agent=existing, role="author")
        claim = {"rank": "normal", "mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": "Q999"}}}}
        self.snapshot("Q100", {"id": "Q100", "claims": {"P50": [claim]}}, work=self.work)
        self.snapshot("Q999", {"id": "Q999", "labels": {"en": {"value": "Another Author"}}})
        call_command("backfill_wikidata_credits", cache_only=True)

        self.assertEqual(Credit.objects.filter(work=self.work).count(), 1)


class RejectProposalsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(username="admin", password="x")
        self.source = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")
        self.reltype = RelationshipType.objects.create(
            code="based-on", label="Based on", inverse_label="Works based on this", category="derivation"
        )
        self.run = ImportRun.objects.create(source=self.source, requested_keys=["Q1"])
        self.seed = Work.objects.create(title="Seed Work", slug="seed-work", work_type=self.book,
                                        visibility=Work.Visibility.PUBLIC, depth="editorial",
                                        first_publication_year=1600)
        self.work = Work.objects.create(title="Self Linked", slug="self-linked", work_type=self.book,
                                        visibility=Work.Visibility.DRAFT, first_publication_year=1990)

    def proposal(self, statement):
        return ImportRelationshipProposal.objects.create(
            run=self.run, statement_id=statement, from_work=self.work, to_work=self.seed,
            relationship_type=self.reltype, source=self.source, evidence={"property_id": "P144"},
        )

    def test_only_deterministic_faults_are_rejected(self):
        broken = self.proposal("Q2$self")
        repairable = self.proposal("Q2$year")
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "triage.json"
            report.write_text(json.dumps({"rows": [
                {"proposal_id": broken.pk, "decision": "red", "reasons": ["self_link"]},
                {"proposal_id": repairable.pk, "decision": "red", "reasons": ["year_inversion"]},
            ]}))
            call_command("reject_proposals", report=report, deterministic=True, confirm=True)

        broken.refresh_from_db()
        repairable.refresh_from_db()
        self.assertEqual(broken.status, ImportRelationshipProposal.Status.REJECTED)
        self.assertEqual(repairable.status, ImportRelationshipProposal.Status.PENDING)


class WikidataBookDiscoveryTests(TestCase):
    def test_manifest_skips_items_already_in_the_catalog(self):
        from unittest.mock import patch
        from .management.commands import discover_wikidata_books as module

        book = WorkType.objects.create(code="book", label="Book", medium="text")
        existing = Work.objects.create(title="Known Book", slug="known-book", work_type=book,
                                        visibility=Work.Visibility.PUBLIC)
        ExternalIdentifier.objects.create(work=existing, scheme="wikidata", value="Q1")

        class Client(FakeWikidataClient):
            def get_json(self, url, params, attempts=1):
                self.requests += 1
                return {"results": {"bindings": [
                    {"item": {"value": "http://www.wikidata.org/entity/Q1"},
                     "olid": {"value": "OL1W"}, "sitelinks": {"value": "20"}},
                    {"item": {"value": "http://www.wikidata.org/entity/Q2"},
                     "olid": {"value": "OL2W"}, "sitelinks": {"value": "10"}},
                ]}}

        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "books.json"
            with patch.object(module, "WikidataClient", Client):
                call_command("discover_wikidata_books", limit=10, manifest=manifest)
            data = json.loads(manifest.read_text())

        self.assertEqual([row["qid"] for row in data["candidates"]], ["Q2"])
        self.assertEqual(data["counts"]["skipped_already_present"], 1)


class ImportWikidataBooksTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.manifest = Path(self.folder.name) / "books.json"
        self.manifest.write_text(json.dumps({"candidates": [{"qid": "Q500", "olid": "OL500W", "sitelinks": 5}]}))

    def tearDown(self):
        self.folder.cleanup()

    def test_staged_book_publishes_as_ambient_with_a_creator(self):
        from unittest.mock import patch
        from .management.commands import import_wikidata_books as module

        def item(qid):
            return {"mainsnak": {"datavalue": {"value": {"entity-type": "item", "id": qid}}}}

        class Client(FakeWikidataClient):
            def payload(self, qid):
                if qid == "Q500":
                    return {
                        "id": "Q500",
                        "labels": {"en": {"value": "A Discovered Book"}},
                        "descriptions": {},
                        "sitelinks": {},
                        "lastrevid": 1,
                        "claims": {
                            "P31": [item("Q8261")],
                            "P577": [{"mainsnak": {"datavalue": {"value": {"time": "+1901-01-01T00:00:00Z", "precision": 9}}}}],
                            "P648": [{"mainsnak": {"datavalue": {"value": "OL500W"}}}],
                            "P50": [item("Q501")],
                        },
                    }
                return {"id": qid, "labels": {"en": {"value": "Discovered Author"}}, "claims": {}}

        with patch.object(module, "WikidataClient", Client):
            call_command("import_wikidata_books", manifest=self.manifest, publish=True, depth="ambient")

        work = Work.objects.get(identifiers__scheme="wikidata", identifiers__value="Q500")
        self.assertEqual((work.visibility, work.depth), (Work.Visibility.PUBLIC, "ambient"))
        self.assertEqual(work.first_publication_year, 1901)
        self.assertEqual(work.work_type_id, "novel")
        self.assertEqual(work.credits.get().agent.name, "Discovered Author")
        self.assertTrue(ExternalIdentifier.objects.filter(work=work, scheme="ol_work", value="OL500W").exists())

    def test_undated_books_stay_draft(self):
        from unittest.mock import patch
        from .management.commands import import_wikidata_books as module

        class Client(FakeWikidataClient):
            def payload(self, qid):
                return {
                    "id": qid, "labels": {"en": {"value": "Undated Book"}},
                    "descriptions": {}, "sitelinks": {}, "lastrevid": 1,
                    "claims": {"P648": [{"mainsnak": {"datavalue": {"value": "OL500W"}}}]},
                }

        with patch.object(module, "WikidataClient", Client):
            call_command("import_wikidata_books", manifest=self.manifest, publish=True, depth="ambient")

        work = Work.objects.get(identifiers__scheme="wikidata", identifiers__value="Q500")
        self.assertEqual(work.visibility, Work.Visibility.DRAFT)


class TitleAndSeedSelectionTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")

    def work(self, title, **kwargs):
        defaults = {"slug": f"work-{Work.objects.count()}", "work_type": self.book,
                    "visibility": Work.Visibility.PUBLIC, "first_publication_year": 1900}
        defaults.update(kwargs)
        return Work.objects.create(title=title, **defaults)

    def test_strip_wrapping_quotes_removes_only_one_pair(self):
        from .importers.wikidata import strip_wrapping_quotes

        self.assertEqual(strip_wrapping_quotes('"Quoted Title"'), "Quoted Title")
        self.assertEqual(strip_wrapping_quotes("\u201cCurly Title\u201d"), "Curly Title")
        self.assertEqual(strip_wrapping_quotes("Plain Title"), "Plain Title")
        self.assertEqual(strip_wrapping_quotes('"Unbalanced'), '"Unbalanced')
        self.assertEqual(strip_wrapping_quotes('""'), '""')

    def test_clean_quoted_titles_requires_matching_supplier_text(self):
        quoted = self.work('"A Quoted Book"', slug="quoted-book")
        self.snapshot("Q1", {"id": "Q1", "claims": {"P1476": [
            {"mainsnak": {"datavalue": {"value": {"text": '"A Quoted Book"', "language": "en"}}}}
        ]}}, work=quoted)
        editorial = self.work('"Editor Wrote This"', slug="editorial-title")
        self.snapshot("Q2", {"id": "Q2", "claims": {"P1476": [
            {"mainsnak": {"datavalue": {"value": {"text": "Different Title", "language": "en"}}}}
        ]}}, work=editorial)

        call_command("clean_quoted_titles", confirm=True)

        quoted.refresh_from_db()
        editorial.refresh_from_db()
        self.assertEqual(quoted.title, "A Quoted Book")
        self.assertEqual(editorial.title, '"Editor Wrote This"')

    def snapshot(self, key, payload, work):
        return SourceRecord.objects.create(
            source=self.source, external_key=key, matched_work=work, raw_payload=payload,
            payload_hash=key, retrieved_at=timezone.now(),
        )

    def test_build_seed_manifest_selects_by_sitelinks_and_requires_ids(self):
        rich = self.work("Well Known Book", slug="rich")
        ExternalIdentifier.objects.create(work=rich, scheme="wikidata", value="Q100")
        self.snapshot("Q100", {"id": "Q100", "sitelinks": {f"site{i}wiki": {} for i in range(25)}}, work=rich)
        thin = self.work("Obscure Book", slug="thin")
        ExternalIdentifier.objects.create(work=thin, scheme="wikidata", value="Q101")
        self.snapshot("Q101", {"id": "Q101", "sitelinks": {"enwiki": {}}}, work=thin)
        no_qid = self.work("Unlinked Book", slug="unlinked")

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "seeds.json"
            call_command("build_seed_manifest", output=output, min_sitelinks=10, limit=10)
            data = json.loads(output.read_text())

        self.assertEqual([row["qid"] for row in data["seeds"]], ["Q100"])

    def test_promote_works_selects_known_works_by_sitelinks(self):
        known = self.work("Known Ambient Book", slug="known-ambient", depth="ambient")
        self.snapshot("Q200", {"id": "Q200", "sitelinks": {f"site{i}wiki": {} for i in range(30)}}, work=known)
        obscure = self.work("Obscure Ambient Book", slug="obscure-ambient", depth="ambient")
        self.snapshot("Q201", {"id": "Q201", "sitelinks": {"enwiki": {}}}, work=obscure)

        call_command("promote_works", from_depth="ambient", min_sitelinks=10, depth="index", confirm=True)

        known.refresh_from_db()
        obscure.refresh_from_db()
        self.assertEqual((known.visibility, known.depth), (Work.Visibility.PUBLIC, "index"))
        self.assertEqual(obscure.depth, "ambient")


class OrphanReportTests(TestCase):
    def setUp(self):
        self.source = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")
        self.book = WorkType.objects.create(code="book", label="Book", medium="text")

    def work(self, title, **kwargs):
        defaults = {"slug": f"orphan-{Work.objects.count()}", "work_type": self.book,
                    "visibility": Work.Visibility.PUBLIC, "first_publication_year": 1900}
        defaults.update(kwargs)
        return Work.objects.create(title=title, **defaults)

    def test_orphans_are_separated_by_cause(self):
        alone = self.work("No Claims At All", slug="no-claims")
        claimed = self.work("Has Unresolved Claim", slug="unresolved")
        SourceRecord.objects.create(
            source=self.source, external_key="Q1", matched_work=claimed,
            raw_payload={"id": "Q1", "claims": {"P629": [{"mainsnak": {"datavalue": {"value": {"id": "Q9"}}}}]}},
            payload_hash="Q1", retrieved_at=timezone.now(),
        )

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "orphans.json"
            call_command("report_orphans", output=output)
            report = json.loads(output.read_text())

        states = {row["title"]: row["state"] for row in report["rows"]}
        self.assertEqual(states["No Claims At All"], "no_claims")
        self.assertEqual(states["Has Unresolved Claim"], "claims_unresolved")
        self.assertEqual(report["summary"].get("claims_unresolved"), 1)


class BookSliceRunnerTests(TestCase):
    def test_dry_run_lists_steps_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder) / "slices"
            call_command("run_book_slice", dry_run=True, workdir=workdir, limit=50)
            self.assertFalse(workdir.exists())

    def test_scan_must_cover_the_limit(self):
        from django.core.management.base import CommandError

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CommandError):
                call_command("discover_wikidata_books", limit=100, scan=50,
                             manifest=Path(folder) / "m.json")

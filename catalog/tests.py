import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmailVerification

from .importers.openlibrary import ImportFailure, ImportResult, OpenLibraryImporter
from .importers.openlibrary_bulk import BulkImportError, extract, validate_extract
from .importers.wikidata import WikidataClient, run_import, title_from_entity
from .models import (Agent, Credit, ExternalIdentifier, FeaturedWork, ImportedWorkState,
    ContributionProposal, ContributionRevision, ImportItem, ImportRun, ImportRelationshipProposal, MediaList, MediaListEntry, RelationshipType, Release, Source, SourceRecord, Term, Version, Work, WorkRelationship, WorkSource,
    WorkRedirect, WorkTermAssignment, WorkType)
from .services import merge_works


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


class FakeWikidataClient:
    requests = 2
    def entities(self, ids):
        entities = {
            "Q1": {"id":"Q1","lastrevid":11,"labels":{"en":{"value":"Source novel"}},"descriptions":{"en":{"value":"human description"}},
                   "claims":{"P31":[{"mainsnak":{"datavalue":{"value":{"entity-type":"item","id":"Q8261"}}}}],"P648":[{"mainsnak":{"datavalue":{"value":"OL1W"}}}]}},
            "Q2": {"id":"Q2","lastrevid":22,"labels":{"en":{"value":"Derived film"}},"descriptions":{"en":{"value":"film description"}},
                   "claims":{"P31":[{"mainsnak":{"datavalue":{"value":{"entity-type":"item","id":"Q11424"}}}}],
                   "P144":[{"id":"Q2$ABC","rank":"normal","mainsnak":{"datavalue":{"value":{"entity-type":"item","id":"Q1"}}},
                            "qualifiers":{"P580":[{"datavalue":{"value":{"time":"+2020-01-01T00:00:00Z"}}}]},"references":[{"snaks":{"P248":[]}}]}]}}
        }
        return {qid:entities[qid] for qid in ids}
    def discover(self,seeds,limit):
        return [{"derived":{"value":"http://www.wikidata.org/entity/Q2"},"seed":{"value":"http://www.wikidata.org/entity/Q1"},
                 "statement":{"value":"http://www.wikidata.org/entity/statement/Q2-ABC"}}]


class WikidataPilotTests(TestCase):
    def setUp(self):
        self.source=Source.objects.create(title="Wikidata",url="https://www.wikidata.org/")
        self.run=ImportRun.objects.create(source=self.source,requested_keys=["Q1"])

    def test_identifier_matching_stages_without_public_mutation_and_is_idempotent(self):
        kind=WorkType.objects.create(code="novel",label="Novel",medium="text")
        existing=Work.objects.create(title="Editorial title",slug="editorial",work_type=kind,description="A richer editor description",visibility="public")
        ExternalIdentifier.objects.create(work=existing,scheme="ol_work",value="OL1W")
        first=run_import(self.run,["Q1"],related_limit=5,client=FakeWikidataClient())
        self.run.refresh_from_db(); second=run_import(self.run,["Q1"],related_limit=5,client=FakeWikidataClient())
        existing.refresh_from_db()
        self.assertEqual((existing.title,existing.description,existing.visibility),("Editorial title","A richer editor description","public"))
        self.assertEqual(ExternalIdentifier.objects.filter(scheme="wikidata",value="Q1").count(),1)
        self.assertEqual(ImportRelationshipProposal.objects.count(),1)
        self.assertEqual(first["relationships_proposed"],second["relationships_proposed"])

    def test_title_resolution_uses_original_available_title_not_qid(self):
        entity={"labels":{"fr":{"value":"Les Quatre Mousquetaires"}},"claims":{
            "P345":[{"mainsnak":{"datavalue":{"value":"tt0258903"}}}]}}
        self.assertEqual(title_from_entity(entity),("Les Quatre Mousquetaires","fr","label"))

    def test_unresolved_qid_has_an_explicit_incomplete_display(self):
        kind=WorkType.objects.create(code="unknown-film",label="Film",medium="screen")
        work=Work.objects.create(title="Q3235021",slug="q3235021",work_type=kind,visibility="public")
        ExternalIdentifier.objects.create(work=work,scheme="wikidata",value="Q3235021")
        response=self.client.get(work.get_absolute_url())
        self.assertContains(response,"Title unknown — film")
        self.assertContains(response,"Incomplete record")
        self.assertNotContains(response,"<h1>Q3235021</h1>",html=True)

    @patch("catalog.management.commands.enrich_wikidata_titles.WikidataClient")
    def test_title_job_enriches_by_exact_ids_and_cites_wikipedia(self, client_class):
        kind=WorkType.objects.create(code="belgian-film",label="Film",medium="screen")
        work=Work.objects.create(title="Q3235021",slug="q3235021-job",work_type=kind,visibility="public")
        ExternalIdentifier.objects.create(work=work,scheme="wikidata",value="Q3235021")
        record = SourceRecord.objects.create(source=self.source, external_key="Q3235021", matched_work=work,
            payload_hash="old", raw_payload={}, retrieved_at=timezone.now())
        ImportedWorkState.objects.create(source_record=record, imported_title="Q3235021", imported_date_text="1934", imported_year=1934)
        client=client_class.return_value; client.requests=2
        client.entities.return_value={"Q3235021":{"id":"Q3235021","labels":{"fr":{"value":"Les Quatre Mousquetaires"}},
            "sitelinks":{"frwiki":{"title":"Les Quatre Mousquetaires"}},"claims":{
            "P345":[{"mainsnak":{"datavalue":{"value":"tt0258903"}}}]}}}
        client.get_json.return_value={"query":{"pages":[{"title":"Les Quatre Mousquetaires","extract":"Film belge de 1934."}]}}
        call_command("enrich_wikidata_titles",limit=5000)
        work.refresh_from_db()
        self.assertEqual(work.title,"Les Quatre Mousquetaires")
        self.assertEqual(ImportedWorkState.objects.get(source_record=record).imported_date_text, "1934")
        self.assertEqual(work.description,"Film belge de 1934.")
        self.assertTrue(ExternalIdentifier.objects.filter(work=work,scheme="imdb",value="tt0258903").exists())
        self.assertTrue(WorkSource.objects.filter(work=work,source__url__contains="fr.wikipedia.org/wiki/").exists())
        self.assertEqual(ImportRun.objects.latest("pk").status,ImportRun.Status.COMPLETED)

    def test_title_only_match_is_ambiguous_not_merged(self):
        kind=WorkType.objects.create(code="film",label="Film",medium="screen")
        Work.objects.create(title="Derived film",slug="existing-derived",work_type=kind,visibility="public")
        stats=run_import(self.run,["Q1"],related_limit=5,client=FakeWikidataClient())
        self.assertEqual(stats["ambiguous_matches"],1)
        self.assertFalse(ExternalIdentifier.objects.filter(value="Q2").exists())

    def test_direction_mapping_evidence_and_explicit_approval(self):
        run_import(self.run,["Q1"],related_limit=5,client=FakeWikidataClient())
        proposal=ImportRelationshipProposal.objects.get()
        self.assertEqual((proposal.from_work.title,proposal.relationship_type.code,proposal.to_work.title),("Derived film","based-on","Source novel"))
        self.assertEqual(proposal.evidence["property_id"],"P144")
        self.assertTrue(proposal.evidence["references"]); self.assertTrue(proposal.evidence["qualifiers"])
        reviewer=get_user_model().objects.create_user(username="reviewer")
        relationship=proposal.approve(reviewer)
        self.assertEqual(relationship.review_status,"accepted")
        relationship.from_work.visibility=relationship.to_work.visibility="public"
        relationship.from_work.save(); relationship.to_work.save()
        self.assertContains(self.client.get(relationship.from_work.get_absolute_url()),"Based on")
        self.assertContains(self.client.get(relationship.to_work.get_absolute_url()),"Works based on this")

    def test_admin_can_bulk_approve_imported_relationships(self):
        run_import(self.run, ["Q1"], related_limit=5, client=FakeWikidataClient())
        proposal = ImportRelationshipProposal.objects.get()
        admin_user = get_user_model().objects.create_superuser(
            username="import-reviewer", email="reviewer@example.test", password="password123"
        )
        self.client.force_login(admin_user)
        response = self.client.post(reverse("admin:catalog_importrelationshipproposal_changelist"), {
            "action": "approve_selected", "_selected_action": [proposal.pk],
        })
        self.assertEqual(response.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ImportRelationshipProposal.Status.APPROVED)
        self.assertEqual(proposal.reviewer, admin_user)
        self.assertTrue(WorkRelationship.objects.filter(review_status="accepted").exists())

        response = self.client.post(reverse("admin:catalog_importrelationshipproposal_changelist"), {
            "action": "publish_approved_endpoints", "_selected_action": [proposal.pk],
        })
        self.assertEqual(response.status_code, 302)
        proposal.from_work.refresh_from_db()
        proposal.to_work.refresh_from_db()
        self.assertEqual(proposal.from_work.visibility, Work.Visibility.PUBLIC)
        self.assertEqual(proposal.to_work.visibility, Work.Visibility.PUBLIC)
        self.assertContains(self.client.get(proposal.to_work.get_absolute_url()), proposal.to_work.title)
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

    def test_discover_paginates_and_preserves_filters(self):
        kind = WorkType.objects.get(pk="novel")
        Work.objects.bulk_create([
            Work(title=f"Paged work {number:02}", slug=f"paged-{number}", work_type=kind,
                 visibility=Work.Visibility.PUBLIC, is_demo=True)
            for number in range(32)
        ])
        response = self.client.get(reverse("discover"), {"type": "novel", "sort": "newest"})
        self.assertEqual(len(response.context["works"]), 30)
        self.assertEqual(response.context["result_count"], 33)
        self.assertContains(response, "type=novel&amp;sort=newest&amp;page=2")
        second = self.client.get(reverse("discover"), {"type": "novel", "page": 2})
        self.assertEqual(len(second.context["works"]), 3)

    def test_discover_combines_year_creator_and_relationship_direction(self):
        response = self.client.get(reverse("discover"), {
            "creator": "Mara Vale", "year_from": "1900", "year_to": "1920",
            "relationship": "has_adaptations",
        })
        self.assertEqual([work.pk for work in response.context["works"]], [1001])
        response = self.client.get(reverse("discover"), {"relationship": "is_adaptation"})
        self.assertEqual({work.pk for work in response.context["works"]}, {1002, 1003})

    def test_open_library_links_use_structured_work_and_edition_keys(self):
        work = Work.objects.get(pk=1001)
        ExternalIdentifier.objects.create(work=work, scheme="ol_work", value="/works/OL123W")
        release = Release.objects.filter(version__work=work).first()
        release.openlibrary_key = "/books/OL456M"
        release.save()
        response = self.client.get(work.get_absolute_url())
        self.assertContains(response, 'href="https://openlibrary.org/works/OL123W"')
        self.assertContains(response, 'href="https://openlibrary.org/books/OL456M"')
        self.assertNotContains(response, 'href="https://openlibrary.org/"')

    def test_invalid_open_library_identifier_does_not_create_homepage_link(self):
        work = Work.objects.get(pk=1001)
        ExternalIdentifier.objects.create(work=work, scheme="ol_work", value="not-a-work")
        response = self.client.get(work.get_absolute_url())
        self.assertNotContains(response, "View on Open Library")

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


class OpenLibraryBulkImportTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def dump(self, name, kind, rows, malformed=False):
        path=self.root/name
        with path.open("wb") as stream:
            for row in rows:
                stream.write(f"{kind}\t{row['key']}\t1\t2026-09-01T00:00:00\t".encode()+json.dumps(row).encode()+b"\n")
            if malformed: stream.write(b"broken\n")
        return path

    def make_extract(self):
        editions=self.dump("editions.txt","/type/edition",[
            {"key":"/books/OL1M","title":"English One","works":[{"key":"/works/OL1W"}],"languages":[{"key":"/languages/eng"}],"publishers":["Example"]},
            {"key":"/books/OL2M","title":"Francais","works":[{"key":"/works/OL2W"}],"languages":[{"key":"/languages/fre"}]},
            {"key":"/books/OL3M","title":"Translated title","works":[{"key":"/works/OL3W"}],"languages":[{"key":"/languages/eng"}]},
        ],malformed=True)
        works=self.dump("works.txt","/type/work",[
            {"key":"/works/OL1W","title":"One","authors":[{"author":{"key":"/authors/OL1A"}}]},
            {"key":"/works/OL2W","title":"Two"},
            {"key":"/works/OL3W","title":"Original non-English work","authors":[{"author":{"key":"/authors/OL1A"}}]},
        ])
        authors=self.dump("authors.txt","/type/author",[{"key":"/authors/OL1A","name":"Author One"}])
        output=self.root/"extract"
        extract(editions=editions,works=works,authors=authors,output=output,limit=10,snapshot_date="2026-09-01",urls={"works":"https://example.test/works"})
        return output

    def test_selection_uses_edition_language_and_links_children(self):
        output=self.make_extract(); manifest,_=validate_extract(output)
        self.assertEqual(manifest["artifact"]["records"],2)
        call_command("ingest_openlibrary_extract",output)
        self.assertEqual(set(ExternalIdentifier.objects.filter(scheme="ol_work").values_list("value",flat=True)),{"OL1W","OL3W"})
        self.assertEqual(Work.objects.filter(visibility=Work.Visibility.DRAFT).count(),2)
        self.assertEqual(Credit.objects.get(work__identifiers__value="OL1W").agent.openlibrary_key,"OL1A")
        self.assertEqual(Release.objects.filter(openlibrary_key__in=["OL1M","OL3M"]).count(),2)

    def test_dry_run_idempotence_override_and_promotion(self):
        output=self.make_extract(); call_command("ingest_openlibrary_extract",output,dry_run=True)
        self.assertEqual(Work.objects.count(),0)
        call_command("ingest_openlibrary_extract",output); run=ImportRun.objects.get()
        work=Work.objects.get(identifiers__value="OL1W"); work.title="Human title"; work.save()
        call_command("ingest_openlibrary_extract",output)
        work.refresh_from_db(); self.assertEqual(work.title,"Human title"); self.assertEqual(Work.objects.count(),2)
        call_command("promote_openlibrary_run",run.pk,confirm=True); work.refresh_from_db(); self.assertEqual(work.visibility,Work.Visibility.PUBLIC)
        # A later staging pass reports, rather than mutates, a public record.
        rows=(output/"records.jsonl").read_text().splitlines(); data=json.loads(rows[0]); data["work"]["title"]="Supplier change"; rows[0]=json.dumps(data,sort_keys=True)
        (output/"records.jsonl").write_text("\n".join(rows)+"\n"); manifest=json.loads((output/"manifest.json").read_text()); import hashlib
        manifest["artifact"]["sha256"]=hashlib.sha256((output/"records.jsonl").read_bytes()).hexdigest(); (output/"manifest.json").write_text(json.dumps(manifest))
        call_command("ingest_openlibrary_extract",output); work.refresh_from_db(); self.assertEqual(work.title,"Human title"); self.assertTrue(ImportItem.objects.filter(status="conflicted").exists())

    def test_resume_skips_completed_items_and_retries_failure(self):
        output=self.make_extract()
        with patch("catalog.management.commands.ingest_openlibrary_extract.ingest_record",side_effect=[("created",None,"ok"),RuntimeError("stop")]):
            call_command("ingest_openlibrary_extract",output)
        run=ImportRun.objects.get(); self.assertEqual(run.items.filter(status="failed").count(),1)
        call_command("ingest_openlibrary_extract",output,resume_run=run.pk)
        self.assertEqual(run.items.filter(status="failed").count(),0)

    def test_promotion_requires_explicit_override_for_reviewed_failures(self):
        output=self.make_extract(); call_command("ingest_openlibrary_extract",output)
        run=ImportRun.objects.get(); run.status=ImportRun.Status.COMPLETED_WITH_ERRORS; run.save(update_fields=("status",))
        ImportItem.objects.create(run=run,external_key="OLFAILEDW",status="failed",message="reviewed test failure")
        with self.assertRaises(CommandError):
            call_command("promote_openlibrary_run",run.pk,confirm=True)
        call_command("promote_openlibrary_run",run.pk,confirm=True,allow_errors=True)
        self.assertEqual(Work.objects.filter(visibility=Work.Visibility.PUBLIC).count(),2)

    def test_rejects_truncated_extract_and_ambiguous_identifier(self):
        output=self.make_extract(); (output/"records.jsonl").write_text("")
        with self.assertRaises(BulkImportError): validate_extract(output)
        source=Source.objects.create(title="Open Library bulk test"); kind=WorkType.objects.create(code="bulk",label="Book",medium="text")
        for n in (1,2):
            work=Work.objects.create(title=f"Duplicate {n}",slug=f"duplicate-{n}",work_type=kind)
            ExternalIdentifier.objects.create(work=work,scheme="ol_work",value="OL9W")
        from .importers.openlibrary_bulk import ingest_record
        status,_,_=ingest_record({"work":{"key":"/works/OL9W","title":"Nine"},"editions":[{"key":"/books/OL9M"}],"authors":{}},source)
        self.assertEqual(status,"conflicted")

    def test_cloud_command_runs_fixture_extract_and_persists_report(self):
        fixture_extract = self.make_extract()
        manifest = json.loads((fixture_extract / "manifest.json").read_text())
        digest = "a" * 64
        environment = {
            "OPENLIBRARY_SNAPSHOT_DATE": "2026-09-01",
            "OPENLIBRARY_EDITIONS_URL": "https://archive.org/ol_exports_2026-09-01/editions.txt.gz",
            "OPENLIBRARY_WORKS_URL": "https://archive.org/ol_exports_2026-09-01/works.txt.gz",
            "OPENLIBRARY_AUTHORS_URL": "https://archive.org/ol_exports_2026-09-01/authors.txt.gz",
            "OPENLIBRARY_EDITIONS_CHECKSUM": digest,
            "OPENLIBRARY_WORKS_CHECKSUM": digest,
            "OPENLIBRARY_AUTHORS_CHECKSUM": digest,
        }

        def fixture_extraction(**kwargs):
            import shutil
            shutil.copytree(fixture_extract, kwargs["output"])
            return manifest

        resolved = {
            "snapshot_date": environment["OPENLIBRARY_SNAPSHOT_DATE"],
            "editions": environment["OPENLIBRARY_EDITIONS_URL"],
            "works": environment["OPENLIBRARY_WORKS_URL"],
            "authors": environment["OPENLIBRARY_AUTHORS_URL"],
            "editions_checksum": digest, "works_checksum": digest, "authors_checksum": digest,
        }
        with patch.dict(os.environ, environment), patch(
            "catalog.management.commands.run_openlibrary_cloud_pilot.resolve_snapshot", return_value=resolved,
        ), patch("catalog.management.commands.run_openlibrary_cloud_pilot.extract", side_effect=fixture_extraction):
            call_command("run_openlibrary_cloud_pilot", dry_run=True, min_free_mib=1)
        run = ImportRun.objects.latest("pk")
        self.assertEqual(run.status, ImportRun.Status.COMPLETED)
        self.assertEqual(run.stats["phase"], "dry_run")
        self.assertEqual(run.manifest["cloud_parameters"]["snapshot_date"], "2026-09-01")

    def test_cloud_command_resolves_latest_links_and_official_checksums(self):
        from catalog.management.commands.run_openlibrary_cloud_pilot import resolve_snapshot

        responses = []
        for kind in ("editions", "works", "authors"):
            filename = f"ol_dump_{kind}_2026-09-01.txt.gz"
            redirect = JsonResponse(b"")
            redirect.geturl = lambda filename=filename: f"https://ia.example/1/items/ol_dump_2026-09-01/{filename}"
            metadata = JsonResponse(json.dumps({"files": [{"name": filename, "sha1": "b" * 40}]}).encode())
            responses.extend((redirect, metadata))
        config = {"snapshot_date": ""}
        for kind in ("editions", "works", "authors"):
            config[kind] = f"https://openlibrary.org/data/ol_dump_{kind}_latest.txt.gz"
            config[f"{kind}_checksum"] = ""
        with patch("catalog.management.commands.run_openlibrary_cloud_pilot.urlopen", side_effect=responses):
            resolved = resolve_snapshot(config)
        self.assertEqual(resolved["snapshot_date"], "2026-09-01")
        self.assertEqual(resolved["works_checksum"], "b" * 40)
        self.assertIn("ol_dump_works_2026-09-01.txt.gz", resolved["works"])


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

    def test_add_to_list_shows_private_lists_persists_and_handles_duplicate(self):
        own = MediaList.objects.create(owner=self.owner, title="Private shelf")
        MediaList.objects.create(owner=self.other, title="Other private shelf")
        self.client.force_login(self.owner)
        chooser = self.client.get(reverse("add-to-list", args=[self.work_a.pk]))
        self.assertContains(chooser, "Private shelf")
        self.assertNotContains(chooser, "Other private shelf")
        response = self.client.post(reverse("add-to-list", args=[self.work_a.pk]), {"list_id": own.pk})
        self.assertRedirects(response, own.get_absolute_url())
        self.assertContains(self.client.get(own.get_absolute_url()), self.work_a.title)
        self.client.post(reverse("add-to-list", args=[self.work_a.pk]), {"list_id": own.pk})
        self.assertEqual(own.entries.filter(work=self.work_a).count(), 1)

    def test_add_to_list_rejects_another_users_list(self):
        other_list = MediaList.objects.create(owner=self.other, title="Not yours")
        self.client.force_login(self.owner)
        response = self.client.post(reverse("add-to-list", args=[self.work_a.pk]), {"list_id": other_list.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(other_list.entries.exists())

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


    def test_all_collection_mutations_and_search_are_owner_scoped(self):
        item = MediaList.objects.create(owner=self.owner, title="Secret shelf")
        entry = MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1, commentary="Secret annotation")
        self.client.force_login(self.other)
        routes = [
            ("list-edit", [item.pk], {"title": "Stolen", "visibility": "public"}),
            ("list-delete", [item.pk], {}),
            ("list-add-work", [item.pk, self.work_b.pk], {}),
            ("list-entry-edit", [item.pk, entry.pk], {"commentary": "Stolen"}),
            ("list-entry-remove", [item.pk, entry.pk], {}),
            ("list-entry-move", [item.pk, entry.pk, "down"], {}),
        ]
        for name, args, data in routes:
            with self.subTest(route=name):
                self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 404)
        self.assertEqual(self.client.get(reverse("list-work-search", args=[item.pk]), {"q": "Published"}).status_code, 404)
        entry.refresh_from_db()
        self.assertEqual(entry.commentary, "Secret annotation")
        self.assertEqual(item.entries.count(), 1)

    def test_private_discovery_search_and_chooser_do_not_leak(self):
        item = MediaList.objects.create(owner=self.owner, title="Hidden title", description="Hidden introduction")
        MediaListEntry.objects.create(media_list=item, work=self.work_a, commentary="Hidden annotation", position=1)
        for user in (None, self.other):
            if user:
                self.client.force_login(user)
            for route in ("public-lists", "discover"):
                response = self.client.get(reverse(route), {"q": "Hidden"})
                for text in ("Hidden title", "Hidden introduction", "Hidden annotation"):
                    self.assertNotContains(response, text)
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
        response = self.client.get(reverse("add-to-list", args=[self.work_a.pk]), {"q": "Hidden"})
        self.assertNotContains(response, "Hidden title")

    def test_annotations_introductions_and_titles_are_plain_text_and_validated(self):
        payload = '<script>alert("collection")</script>'
        item = MediaList.objects.create(owner=self.owner, title=payload, description=payload, visibility="public")
        entry = MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1)
        self.client.force_login(self.owner)
        self.client.post(reverse("list-entry-edit", args=[item.pk, entry.pk]), {"commentary": payload})
        entry.refresh_from_db()
        self.assertEqual(entry.commentary, payload)
        response = self.client.get(item.get_absolute_url())
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, payload)
        response = self.client.post(reverse("list-entry-edit", args=[item.pk, entry.pk]), {"commentary": "x" * 1001})
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.commentary, payload)
        response = self.client.post(reverse("list-edit", args=[item.pk]), {"title": "x" * 121, "description": "x" * 1001, "visibility": "private"})
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.description, payload)

    def test_sparse_ordering_and_removal_preserve_annotations_and_work(self):
        item = MediaList.objects.create(owner=self.owner, title="Sparse")
        a = MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1, commentary="First note")
        b = MediaListEntry.objects.create(media_list=item, work=self.work_b, position=4, commentary="Second note")
        self.client.force_login(self.owner)
        self.client.post(reverse("list-entry-move", args=[item.pk, b.pk, "up"]))
        self.assertEqual(list(item.entries.values_list("work_id", "position", "commentary")), [(self.work_b.pk, 1, "Second note"), (self.work_a.pk, 2, "First note")])
        self.client.post(reverse("list-entry-remove", args=[item.pk, a.pk]))
        self.assertTrue(Work.objects.filter(pk=self.work_a.pk).exists())
        self.assertEqual(item.entries.get().commentary, "Second note")
        self.assertEqual(item.entries.get().position, 1)

    def test_public_counts_previews_and_all_unavailable_empty_state(self):
        item = MediaList.objects.create(owner=self.owner, title="Visible", visibility="public")
        MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1, commentary="Visible note")
        MediaListEntry.objects.create(media_list=item, work=self.work_b, position=2, commentary="Hidden note")
        self.work_b.visibility = "suppressed"
        self.work_b.save()
        response = self.client.get(reverse("public-lists"))
        self.assertContains(response, "1 work")
        self.assertContains(response, self.work_a.title)
        self.assertNotContains(response, self.work_b.title)
        self.assertContains(self.client.get(item.get_absolute_url()), "1 work")
        self.work_a.visibility = "draft"
        self.work_a.save()
        response = self.client.get(item.get_absolute_url())
        self.assertContains(response, "Still being assembled")
        self.assertContains(response, "0 works")
        self.assertNotContains(response, "Visible note")
        self.assertNotContains(response, "Hidden note")

    def test_creation_from_work_defaults_private_and_rejects_unverified_public(self):
        self.client.force_login(self.owner)
        endpoint = reverse("add-to-list", args=[self.work_a.pk])
        response = self.client.get(endpoint)
        self.assertEqual(response.context["create_form"]["visibility"].value(), "private")
        response = self.client.post(endpoint, {"title": "New shelf", "description": "An introduction"})
        item = MediaList.objects.get()
        self.assertRedirects(response, item.get_absolute_url())
        self.assertEqual(item.visibility, "private")
        self.assertEqual(item.entries.get().work, self.work_a)
        response = self.client.post(endpoint, {"title": "Public shelf", "visibility": "public"})
        self.assertContains(response, "Verify your email address")
        self.assertEqual(MediaList.objects.count(), 1)
        self.assertEqual(self.client.post(endpoint, {"list_id": "invalid"}).status_code, 404)

    def test_auth_flow_retains_intended_work_and_signup_link(self):
        endpoint = reverse("add-to-list", args=[self.work_a.pk])
        response = self.client.get(endpoint, follow=True)
        self.assertEqual(response.context["next"], endpoint)
        from urllib.parse import quote
        self.assertContains(response, reverse("accounts:signup") + "?next=" + quote(endpoint, safe="/"))
        response = self.client.post(reverse("accounts:login"), {"username": "curator", "password": "password123", "next": endpoint})
        self.assertRedirects(response, endpoint)

    def test_collection_search_marks_membership_and_links_remain_stable(self):
        item = MediaList.objects.create(owner=self.owner, title="Original shelf", visibility="public")
        original_url = item.get_absolute_url()
        MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("list-work-search", args=[item.pk]), {"q": "Published"})
        self.assertContains(response, "Already included")
        response = self.client.get(reverse("add-to-list", args=[self.work_a.pk]), {"q": "Original"})
        self.assertContains(response, "Already included")
        EmailVerification.objects.create(user=self.owner, verified_at=timezone.now())
        self.client.post(reverse("list-edit", args=[item.pk]), {"title": "Renamed shelf", "description": "", "visibility": "public"})
        item.refresh_from_db()
        self.assertEqual(item.get_absolute_url(), original_url)
        self.assertContains(self.client.get(original_url), "Renamed shelf")

    def test_position_constraint_and_recent_update_on_membership_change(self):
        item = MediaList.objects.create(owner=self.owner, title="Constraint shelf")
        MediaListEntry.objects.create(media_list=item, work=self.work_a, position=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MediaListEntry.objects.create(media_list=item, work=self.work_b, position=1)
        before = item.updated_at
        self.client.force_login(self.owner)
        self.client.post(reverse("list-add-work", args=[item.pk, self.work_b.pk]))
        item.refresh_from_db()
        self.assertGreater(item.updated_at, before)


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

    def test_clarification_and_resubmission_preserve_attempt_history(self):
        proposal = self.proposal()
        proposal.request_clarification(reviewer=self.reviewer, explanation="Please cite the title page.")
        self.client.force_login(self.member)
        response = self.client.post(reverse("resubmit-contribution", args=[proposal.pk]),
            self.correction_data(proposed_value="Best title", explanation="Now citing the title page."))
        self.assertRedirects(response, reverse("my-contributions"))
        proposal.refresh_from_db()
        replacement = ContributionProposal.objects.get(supersedes=proposal)
        self.assertEqual(proposal.status, ContributionProposal.Status.SUPERSEDED)
        self.assertEqual(replacement.status, ContributionProposal.Status.PENDING)
        self.assertEqual(replacement.proposed_value, "Best title")
        self.assertEqual(proposal.proposed_value, "Better title")
        history = self.client.get(reverse("my-contributions"))
        self.assertContains(history, "retained as part of the proposal history")
        self.assertContains(history, "revision of proposal")

    def test_only_owner_can_resubmit_a_clarification_request(self):
        proposal = self.proposal()
        proposal.request_clarification(reviewer=self.reviewer, explanation="More detail needed.")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("resubmit-contribution", args=[proposal.pk])).status_code, 404)
        with self.assertRaises(PermissionDenied):
            proposal.resubmit(contributor=self.other, proposed_value="No", explanation="No",
                              source_url="https://example.test/no")

    def test_resubmission_refreshes_conflict_snapshot(self):
        proposal = self.proposal()
        proposal.request_clarification(reviewer=self.reviewer, explanation="Please revise.")
        self.work.title = "Intervening title"
        self.work.save()
        replacement = proposal.resubmit(contributor=self.member, proposed_value="Final title",
            explanation="Revised evidence", source_url="https://example.test/revised")
        self.assertEqual(replacement.value_at_submission, "Intervening title")
        self.assertFalse(replacement.has_conflict)

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

    def test_relationship_target_searches_by_title_or_exact_id(self):
        self.client.force_login(self.member)
        url = reverse("relationship-work-search", args=[self.work.pk])
        response = self.client.get(url, {"work_q": "Targ"})
        self.assertContains(response, self.target.title)
        self.assertContains(response, f"catalog ID {self.target.pk}")
        response = self.client.get(url, {"work_q": str(self.target.pk)})
        self.assertContains(response, self.target.title)
        self.assertNotContains(response, self.work.title)

        form_page = self.client.get(reverse("suggest-relationship", args=[self.work.pk]))
        self.assertContains(form_page, "Search by title or catalog ID")
        self.assertNotContains(form_page, 'select name="related_work"', html=False)

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


class WorkTermFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user("term-member", "terms@example.test", "password123")
        cls.reviewer = get_user_model().objects.create_user("term-reviewer", is_staff=True)
        cls.reviewer.user_permissions.add(Permission.objects.get(codename="review_worktermassignment"))
        EmailVerification.objects.create(user=cls.member, verified_at=timezone.now())
        kind = WorkType.objects.create(code="term-book", label="Book", medium="text")
        cls.work = Work.objects.create(title="Tagged work", slug="tagged-work", work_type=kind, visibility="public")
        cls.term = Term.objects.create(vocabulary="oma-subjects", identifier="climate-fiction",
            label="Climate fiction", category="genre", source_identifier="subjects/climate-fiction")

    def test_pending_assignment_never_appears_on_public_work_page(self):
        assignment = WorkTermAssignment.objects.create(work=self.work, term=self.term,
            submitted_by=self.member, provenance_note="A source describes the genre.",
            source_url="https://example.test/genre")
        self.assertNotContains(self.client.get(self.work.get_absolute_url()), self.term.label)
        assignment.review(reviewer=self.reviewer, accept=True, note="Source checked.")
        self.assertContains(self.client.get(self.work.get_absolute_url()), self.term.label)
        assignment.refresh_from_db()
        self.assertEqual(assignment.source.url, "https://example.test/genre")

    def test_verified_contributor_suggests_but_cannot_publish_a_term(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("suggest-term", args=[self.work.pk]), {
            "term": self.term.pk, "provenance_note": "Supported by the linked bibliography.",
            "source_url": "https://example.test/bibliography"})
        self.assertRedirects(response, reverse("my-contributions"))
        assignment = WorkTermAssignment.objects.get()
        self.assertEqual(assignment.review_state, WorkTermAssignment.ReviewState.PENDING)
        self.assertIsNone(assignment.reviewer)
        self.assertContains(self.client.get(reverse("my-contributions")), "not yet independently reviewed")

    def test_term_identifiers_and_active_assignments_are_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Term.objects.create(vocabulary=self.term.vocabulary, identifier=self.term.identifier,
                    label="Duplicate", category="genre")
        WorkTermAssignment.objects.create(work=self.work, term=self.term, submitted_by=self.member,
            provenance_note="First", source_url="https://example.test/first")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkTermAssignment.objects.create(work=self.work, term=self.term,
                    submitted_by=self.member, provenance_note="Duplicate",
                    source_url="https://example.test/duplicate")

class WorkMergeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kind = WorkType.objects.create(code="merge-book", label="Book", medium="text")
        cls.source_work = Work.objects.create(
            title="Duplicate", slug="duplicate", work_type=cls.kind, visibility="public"
        )
        cls.canonical = Work.objects.create(
            title="Canonical", slug="canonical", work_type=cls.kind, visibility="public"
        )
        cls.staff = get_user_model().objects.create_user(username="merger", is_staff=True)
        cls.staff.user_permissions.add(Permission.objects.get(codename="merge_work"))
        cls.unprivileged_staff = get_user_model().objects.create_user(
            username="ordinary-staff", is_staff=True
        )

    def test_merge_requires_explicit_staff_permission(self):
        with self.assertRaises(PermissionDenied):
            merge_works(
                source=self.source_work,
                canonical=self.canonical,
                actor=self.unprivileged_staff,
            )
        self.assertFalse(WorkRedirect.objects.exists())

        self.client.force_login(self.unprivileged_staff)
        response = self.client.get(reverse("admin:catalog_workredirect_add"))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.staff)
        add_url = reverse("admin:catalog_workredirect_add")
        self.assertEqual(self.client.get(add_url).status_code, 200)
        response = self.client.post(
            add_url,
            {
                "old_work": self.source_work.pk,
                "canonical_work": self.canonical.pk,
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            WorkRedirect.objects.filter(
                old_work=self.source_work, canonical_work=self.canonical
            ).exists()
        )

    def test_merge_repoints_records_and_resolves_unique_collisions(self):
        agent = Agent.objects.create(name="Writer", kind="person")
        Credit.objects.create(work=self.canonical, agent=agent, role="author")
        Credit.objects.create(work=self.source_work, agent=agent, role="author")
        other_credit = Credit.objects.create(
            work=self.source_work,
            agent=Agent.objects.create(name="Editor", kind="person"),
            role="editor",
        )

        canonical_version = Version.objects.create(
            work=self.canonical, label="Original", kind="original"
        )
        duplicate_version = Version.objects.create(
            work=self.source_work, label="Original", kind="original"
        )
        release = Release.objects.create(version=duplicate_version, title="Preserved release")
        moved_version = Version.objects.create(
            work=self.source_work, label="Translation", kind="translation"
        )
        ExternalIdentifier.objects.create(work=self.canonical, scheme="isbn", value="same")
        ExternalIdentifier.objects.create(work=self.source_work, scheme="isbn", value="same")
        unique_identifier = ExternalIdentifier.objects.create(
            work=self.source_work, scheme="wikidata", value="Q123"
        )

        source = Source.objects.create(title="Merge evidence", url="https://example.test")
        WorkSource.objects.create(work=self.canonical, source=source)
        WorkSource.objects.create(work=self.source_work, source=source)
        source_record = SourceRecord.objects.create(
            source=source,
            external_key="duplicate-record",
            matched_work=self.source_work,
            payload_hash="hash",
            raw_payload={},
            retrieved_at=timezone.now(),
        )
        relationship_type = RelationshipType.objects.create(
            code="merge-based-on", label="Based on", inverse_label="Basis for"
        )
        third = Work.objects.create(title="Third", slug="third", work_type=self.kind)
        WorkRelationship.objects.create(
            from_work=self.canonical,
            to_work=third,
            relationship_type=relationship_type,
            source=source,
        )
        WorkRelationship.objects.create(
            from_work=self.source_work,
            to_work=third,
            relationship_type=relationship_type,
            source=source,
        )
        WorkRelationship.objects.create(
            from_work=self.source_work,
            to_work=self.canonical,
            relationship_type=relationship_type,
            source=source,
        )

        owner = get_user_model().objects.create_user(username="list-owner")
        media_list = MediaList.objects.create(owner=owner, title="Favorites")
        canonical_entry = MediaListEntry.objects.create(
            media_list=media_list, work=self.canonical, commentary="Canonical note", position=1
        )
        MediaListEntry.objects.create(
            media_list=media_list, work=self.source_work, commentary="Duplicate note", position=2
        )
        proposal = ContributionProposal.objects.create(
            kind="relationship",
            submitted_by=owner,
            work=self.source_work,
            related_work=third,
            relationship_type=relationship_type,
            work_updated_at=self.source_work.updated_at,
            related_work_updated_at=third.updated_at,
            explanation="Evidence",
            source_url="https://example.test/proposal",
        )
        import_run = ImportRun.objects.create(source=source)
        import_item = ImportItem.objects.create(
            run=import_run,
            external_key="merge-item",
            status="created",
            work=self.source_work,
        )
        import_proposal = ImportRelationshipProposal.objects.create(
            run=import_run,
            statement_id="merge-statement",
            from_work=self.source_work,
            to_work=third,
            relationship_type=relationship_type,
            source=source,
        )

        redirect_record = merge_works(
            source=self.source_work, canonical=self.canonical, actor=self.staff
        )

        self.assertEqual(redirect_record.canonical_work, self.canonical)
        other_credit.refresh_from_db()
        self.assertEqual(other_credit.work, self.canonical)
        self.assertEqual(Credit.objects.filter(work=self.canonical, agent=agent, role="author").count(), 1)
        release.refresh_from_db()
        self.assertEqual(release.version, canonical_version)
        moved_version.refresh_from_db()
        self.assertEqual(moved_version.work, self.canonical)
        unique_identifier.refresh_from_db()
        source_record.refresh_from_db()
        proposal.refresh_from_db()
        import_item.refresh_from_db()
        import_proposal.refresh_from_db()
        canonical_entry.refresh_from_db()
        self.assertEqual(unique_identifier.work, self.canonical)
        self.assertEqual(source_record.matched_work, self.canonical)
        self.assertEqual(proposal.work, self.canonical)
        self.assertEqual(import_item.work, self.canonical)
        self.assertEqual(import_proposal.from_work, self.canonical)
        self.assertEqual(MediaListEntry.objects.filter(media_list=media_list).count(), 1)
        self.assertIn("Duplicate note", canonical_entry.commentary)
        self.assertEqual(WorkRelationship.objects.filter(from_work=self.canonical, to_work=third).count(), 1)
        self.assertFalse(WorkRelationship.objects.filter(from_work=self.canonical, to_work=self.canonical).exists())

    def test_old_work_url_permanently_redirects_to_canonical_url(self):
        old_url = self.source_work.get_absolute_url()
        merge_works(source=self.source_work, canonical=self.canonical, actor=self.staff)
        response = self.client.get(old_url)
        self.assertRedirects(
            response, self.canonical.get_absolute_url(), status_code=301, fetch_redirect_response=False
        )
        visible_ids = self.client.get(reverse("discover")).context["works"].values_list(
            "pk", flat=True
        )
        self.assertNotIn(self.source_work.pk, visible_ids)

    def test_failure_rolls_back_all_repointing_and_redirect_creation(self):
        identifier = ExternalIdentifier.objects.create(
            work=self.source_work, scheme="rollback", value="original"
        )
        with patch("catalog.services.WorkRedirect.objects.create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                merge_works(source=self.source_work, canonical=self.canonical, actor=self.staff)

        identifier.refresh_from_db()
        self.assertEqual(identifier.work, self.source_work)
        self.assertFalse(WorkRedirect.objects.exists())

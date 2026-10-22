from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .dates import wikidata_date_for_medium
from .importers.wikidata import run_import, work_type_spec
from .management.commands.backfill_wikipedia_dates import parse_infobox_dates
from .management.commands.discover_wikidata_stage_candidates import build_candidate_rows
from .management.commands.import_performing_arts_dates import idu_productions, spap_performances
from .management.commands.triage_proposals import evaluate_proposal
from .models import (
    AccessLink,
    ExternalIdentifier,
    ImportRelationshipProposal,
    ImportRun,
    Source,
    SourceRecord,
    Work,
    WorkRelationship,
    WorkType,
)


class CurationCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.text = WorkType.objects.create(code="book", label="Book", medium="text")
        cls.stage = WorkType.objects.create(code="play", label="Play", medium="stage")
        cls.screen = WorkType.objects.create(code="film", label="Film", medium="screen")
        cls.wikidata = Source.objects.create(title="Wikidata", url="https://www.wikidata.org/")

    def time_claim(self, value, precision=9, rank="normal", statement_id=""):
        return {
            "rank": rank,
            "id": statement_id,
            "mainsnak": {"datavalue": {"value": {
                "time": value, "precision": precision, "before": 0, "after": 0,
            }}},
        }

    def make_source_record(self, work, qid, claims):
        return SourceRecord.objects.create(
            source=self.wikidata,
            external_key=qid,
            matched_work=work,
            payload_hash=f"hash-{qid}",
            raw_payload={"id": qid, "claims": claims},
            retrieved_at=timezone.now(),
        )

    def test_date_backfill_uses_earliest_assertion_and_retains_candidates(self):
        work = Work.objects.create(
            title="Undated book",
            work_type=self.text,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(
            work,
            "Q100",
            {
                "P577": [
                    {"rank": "normal", "id": "Q100$one", "mainsnak": {"datavalue": {"value": {
                        "time": "+1891-00-00T00:00:00Z", "precision": 9, "before": 0, "after": 0,
                    }}}},
                    {"rank": "normal", "id": "Q100$two", "mainsnak": {"datavalue": {"value": {
                        "time": "+1890-07-01T00:00:00Z", "precision": 11, "before": 0, "after": 0,
                    }}}},
                ],
            },
        )
        call_command("backfill_wikidata_dates", scope="golden", confirm=True, stdout=StringIO())
        work.refresh_from_db()
        self.assertEqual(work.first_publication_year, 1890)
        self.assertEqual(work.first_publication_date_text, "1890")
        self.assertEqual(work.date_kind, "publication")
        self.assertEqual(work.date_evidence["selection_rule"], "earliest assertion; multiple date assertions retained")
        self.assertEqual(len(work.date_evidence["candidates"]), 2)
        self.assertEqual(work.date_label, "Source publication date")

    def test_date_backfill_leaves_works_without_claims_unresolved(self):
        work = Work.objects.create(
            title="Still undated",
            work_type=self.stage,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(work, "Q200", {})
        output = StringIO()
        call_command("backfill_wikidata_dates", scope="golden", confirm=True, stdout=output)
        work.refresh_from_db()
        self.assertIsNone(work.first_publication_year)
        self.assertIn("no usable date claim", output.getvalue())

    def test_first_performance_and_start_time_are_used(self):
        stage = Work.objects.create(
            title="Undated play",
            work_type=self.stage,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(
            stage, "Q201", {"P1191": [self.time_claim("+1602-02-02T00:00:00Z", 11, statement_id="Q201$perf")]}
        )
        screen = Work.objects.create(
            title="Undated series",
            work_type=self.screen,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(
            screen, "Q202", {"P580": [self.time_claim("+1999-00-00T00:00:00Z", 9, statement_id="Q202$start")]}
        )
        call_command("backfill_wikidata_dates", scope="golden", confirm=True, stdout=StringIO())
        stage.refresh_from_db()
        screen.refresh_from_db()
        self.assertEqual((stage.first_publication_year, stage.date_kind), (1602, "first_performance"))
        self.assertEqual(stage.date_label, "First performance date")
        self.assertEqual((screen.first_publication_year, screen.date_kind), (1999, "release"))
        self.assertEqual(screen.date_evidence["property"], "P580")

    def test_title_year_fallback_is_marked_unverified(self):
        work = Work.objects.create(
            title="A New Play (2025)",
            work_type=self.stage,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(work, "Q203", {})
        call_command("backfill_wikidata_dates", scope="golden", confirm=True, stdout=StringIO())
        work.refresh_from_db()
        self.assertEqual((work.first_publication_year, work.first_publication_date_text), (2025, "2025"))
        self.assertTrue(work.date_evidence["meaning_unverified"])
        self.assertEqual(work.date_evidence["property"], "title")
        self.assertEqual(work.date_label, "Date (meaning unverified)")

    def test_end_date_is_not_used_as_a_start_date(self):
        work = Work.objects.create(
            title="Only an end date",
            work_type=self.screen,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(
            work, "Q204", {"P582": [self.time_claim("+2001-00-00T00:00:00Z", 9, statement_id="Q204$end")]}
        )
        call_command("backfill_wikidata_dates", scope="golden", confirm=True, stdout=StringIO())
        work.refresh_from_db()
        self.assertIsNone(work.first_publication_year)

    def test_complete_year_only_fills_display_without_changing_year(self):
        work = Work.objects.create(
            title="Year only",
            work_type=self.stage,
            first_publication_year=2022,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(work, "Q205", {})
        call_command(
            "backfill_wikidata_dates", scope="golden", complete_year_only=True, confirm=True,
            stdout=StringIO(),
        )
        work.refresh_from_db()
        self.assertEqual(work.first_publication_year, 2022)
        self.assertEqual(work.first_publication_date_text, "2022")
        self.assertTrue(work.date_evidence["meaning_unverified"])
        self.assertEqual(work.date_label, "Date (meaning unverified)")

    def test_reading_links_use_exact_ids_and_do_not_duplicate(self):
        work = Work.objects.create(
            title="Golden play",
            work_type=self.stage,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        ExternalIdentifier.objects.create(work=work, scheme="ol_work", value="OL123W")
        self.make_source_record(
            work,
            "Q300",
            {"P2034": [{"mainsnak": {"datavalue": {"value": "9999"}}}]},
        )
        call_command("add_reading_links", scope="golden", confirm=True, stdout=StringIO())
        call_command("add_reading_links", scope="golden", confirm=True, stdout=StringIO())
        links = list(work.access_links.order_by("provider"))
        self.assertEqual(len(links), 2)
        self.assertEqual(
            [(link.provider, link.category, link.url) for link in links],
            [
                ("Open Library", AccessLink.Category.CATALOG, "https://openlibrary.org/works/OL123W"),
                ("Project Gutenberg", AccessLink.Category.FULL, "https://www.gutenberg.org/ebooks/9999"),
            ],
        )

    def test_idu_viewstate_parser_extracts_earliest_production(self):
        import base64
        raw = (
            "\x05\x12Cesta kolem světa\x1f\x06\x05'~/ProductionDetail.aspx?id=2&mode=0"
            "\x1f\x06\x05\x042014\x1f"
            "\x05\x12Cesta kolem světa\x1f\x06\x05'~/ProductionDetail.aspx?id=1&mode=0"
            "\x1f\x06\x05\x041994\x1f"
        )
        html = f'<input type="hidden" id="__VIEWSTATE" value="{base64.b64encode(raw.encode()).decode()}" />'
        rows = idu_productions(html)
        self.assertEqual([row["year"] for row in rows], [2014, 1994])
        self.assertEqual(min(rows, key=lambda row: row["year"])["production_id"], "1")

    def test_spap_performances_uses_season_start(self):
        payload = {
            "results": {"bindings": [{
                "performance": {"value": "http://data.performing-arts.ch/f/1"},
                "season": {"value": "http://data.performing-arts.ch/s/1992-1993"},
                "begin": {"value": "1992-08-01"},
                "label": {"value": "Season 1992/93"},
            }]}
        }
        with patch(
            "catalog.management.commands.import_performing_arts_dates.fetch",
            return_value=__import__("json").dumps(payload),
        ):
            rows = spap_performances("http://data.performing-arts.ch/w/example")
        self.assertEqual(rows[0]["year"], 1992)

    def test_performing_arts_command_marks_production_date(self):
        work = Work.objects.create(
            title="Czech play",
            work_type=self.stage,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        self.make_source_record(
            work,
            "Q400",
            {"P12930": [{"mainsnak": {"datavalue": {"value": "2996"}}}]},
        )
        html = (
            '<input type="hidden" id="__VIEWSTATE" value="'
            + __import__("base64").b64encode(
                "\x05\x12Cesta\x1f\x06\x05'~/ProductionDetail.aspx?id=1&mode=0"
                "\x1f\x06\x05\x041994\x1f".encode()
            ).decode()
            + '" />'
        )
        with patch(
            "catalog.management.commands.import_performing_arts_dates.fetch",
            return_value=html,
        ):
            call_command(
                "import_performing_arts_dates", source="idu", confirm=True,
                stdout=StringIO(),
            )
        work.refresh_from_db()
        self.assertEqual((work.first_publication_year, work.first_publication_date_text), (1994, "1994"))
        self.assertEqual(work.date_kind, "production")
        self.assertEqual(work.date_label, "Production date")
        self.assertEqual(work.date_evidence["license"], "CC BY 4.0")

    def test_wikipedia_infobox_uses_earliest_film_date(self):
        wikitext = """
{{Infobox film
| released = {{Film date|1985|6|7|1985|8|1}}
| director = [[Someone]]
}}
"""
        chosen = parse_infobox_dates(wikitext, "screen")
        self.assertEqual((chosen["year"], chosen["text"]), (1985, "1985"))
        self.assertEqual(chosen["kind"], "release")
        self.assertEqual(chosen["selected"]["field"], "released")

    def test_wikipedia_stage_premiere_is_first_performance(self):
        wikitext = """
{{Infobox play
| premiere = {{Start date|1602|2|2}}
}}
"""
        chosen = parse_infobox_dates(wikitext, "stage")
        self.assertEqual((chosen["year"], chosen["text"]), (1602, "1602-02-02"))
        self.assertEqual(chosen["kind"], "first_performance")

    def test_wikipedia_end_date_is_not_used(self):
        wikitext = """
{{Infobox television
| first_aired = {{Start date|2019|5|1}}
| last_aired = {{End date|2021|9|1}}
}}
"""
        chosen = parse_infobox_dates(wikitext, "screen")
        self.assertEqual((chosen["year"], chosen["kind"]), (2019, "first_release"))

    def test_wikipedia_command_stores_revision_provenance(self):
        work = Work.objects.create(
            title="Wiki dated film",
            work_type=self.screen,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        SourceRecord.objects.create(
            source=self.wikidata,
            external_key="Q500",
            matched_work=work,
            payload_hash="hash-Q500",
            raw_payload={
                "id": "Q500",
                "claims": {},
                "sitelinks": {"enwiki": {"title": "Wiki dated film"}},
            },
            retrieved_at=timezone.now(),
        )
        page = {
            "pageid": 123,
            "title": "Wiki dated film",
            "language": "en",
            "revision_id": 456,
            "revision_timestamp": "2026-01-01T00:00:00Z",
            "wikitext": "{{Infobox film\n| released = {{Film date|1985|6|7}}\n}}",
        }
        with patch(
            "catalog.management.commands.backfill_wikipedia_dates.fetch_page",
            return_value=page,
        ), patch(
            "catalog.management.commands.backfill_wikipedia_dates.time.sleep",
            return_value=None,
        ):
            call_command(
                "backfill_wikipedia_dates", scope="all", confirm=True,
                stdout=StringIO(),
            )
        work.refresh_from_db()
        self.assertEqual(work.first_publication_year, 1985)
        self.assertEqual(work.date_kind, "release")
        self.assertEqual(work.date_label, "Date (meaning unverified)")
        self.assertEqual(work.date_evidence["license"], "CC BY-SA 4.0")
        self.assertIn("oldid=456", work.date_evidence["source_url"])
        record = SourceRecord.objects.get(source__title="Wikipedia", external_key="enwiki:123")
        self.assertEqual(record.raw_payload["revision_id"], 456)
        self.assertEqual(record.matched_work_id, work.pk)

    def test_wikipedia_month_name_premiere_date(self):
        wikitext = """
{{Infobox musical
| premiere_date = December 5, 2012
}}
"""
        chosen = parse_infobox_dates(wikitext, "other")
        self.assertEqual((chosen["year"], chosen["text"]), (2012, "2012-12-05"))
        self.assertEqual(chosen["kind"], "first_performance")

    def test_wikipedia_productions_year_is_production(self):
        wikitext = """
{{Infobox musical
| productions = 2009 [[Tampa]] <br>2011 [[Broadway theatre|Broadway]]
}}
"""
        chosen = parse_infobox_dates(wikitext, "other")
        self.assertEqual((chosen["year"], chosen["kind"]), (2009, "production"))

    def test_wikipedia_release_on_other_medium_is_release(self):
        wikitext = """
{{Infobox film series
| released = 2001
}}
"""
        chosen = parse_infobox_dates(wikitext, "other")
        self.assertEqual((chosen["year"], chosen["kind"]), (2001, "release"))

    def test_wikipedia_german_creation_year_is_inception(self):
        wikitext = """
{{Infobox Drama
| EJahr = 1657
| UA =
}}
"""
        chosen = parse_infobox_dates(wikitext, "text")
        self.assertEqual((chosen["year"], chosen["kind"]), (1657, "inception"))

    def test_stage_date_prefers_first_performance_over_inception(self):
        entity = {
            "id": "Q172324",
            "claims": {
                "P1191": [self.time_claim("+1887-02-05T00:00:00Z", 11, statement_id="Q172324$perf")],
                "P577": [self.time_claim("+1850-00-00T00:00:00Z", 7, statement_id="Q172324$pub")],
                "P571": [self.time_claim("+1884-00-00T00:00:00Z", 9, statement_id="Q172324$start")],
            },
        }
        text, year, precision, kind, evidence = wikidata_date_for_medium(entity, "stage")
        self.assertEqual((text, year, precision, kind), ("1887-02-05", 1887, 11, "first_performance"))
        self.assertEqual(evidence["property"], "P1191")
        self.assertEqual(evidence["candidates"][0]["text"], "1887-02-05")

    def test_candidate_import_stages_stage_work_and_leaves_proposal_pending(self):
        seed = Work.objects.create(
            title="Roméo et Juliette",
            work_type=self.text,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        ExternalIdentifier.objects.create(work=seed, scheme="wikidata", value="Q83186")
        source = Source.objects.get(title="Wikidata")
        run = ImportRun.objects.create(source=source, requested_keys=["Q83186", "Q918714"])
        seed_entity = {
            "id": "Q83186",
            "labels": {"en": {"value": "Romeo and Juliet"}},
            "claims": {},
        }
        candidate_entity = {
            "id": "Q918714",
            "labels": {"en": {"value": "Roméo et Juliette"}},
            "descriptions": {"en": {"value": "opera by Charles Gounod"}},
            "claims": {
                "P31": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q1344", "entity-type": "item"}}}}],
                "P144": [{"rank": "normal", "id": "Q918714$based", "mainsnak": {"datavalue": {"value": {"id": "Q83186", "entity-type": "item"}}}}],
                "P1191": [self.time_claim("+1867-04-27T00:00:00Z", 11, statement_id="Q918714$perf")],
            },
        }

        class FakeClient:
            requests = 0

            def entities(self, ids):
                self.requests += 1
                return {qid: entity for qid, entity in {
                    "Q83186": seed_entity,
                    "Q918714": candidate_entity,
                }.items() if qid in ids}

        stats = run_import(
            run,
            ["Q83186"],
            candidate_qids=["Q918714"],
            client=FakeClient(),
        )
        work = Work.objects.get(identifiers__scheme="wikidata", identifiers__value="Q918714")
        self.assertEqual(Work.objects.filter(title__iexact="Roméo et Juliette").count(), 2)
        self.assertEqual((work.work_type.code, work.first_publication_year), ("opera", 1867))
        self.assertEqual(work.date_kind, "first_performance")
        self.assertEqual(stats["relationships_proposed"], 1)
        proposal = ImportRelationshipProposal.objects.get(run=run)
        self.assertEqual(proposal.status, "pending")
        self.assertFalse(WorkRelationship.objects.filter(from_work=work, to_work=seed).exists())

        rerun = ImportRun.objects.create(source=source, requested_keys=["Q83186", "Q918714"])
        rerun_stats = run_import(rerun, ["Q83186"], candidate_qids=["Q918714"], client=FakeClient())
        self.assertEqual(rerun_stats["relationships_proposed"], 0)
        self.assertEqual(rerun_stats["relationships_already_proposed"], 1)
        self.assertEqual(ImportRelationshipProposal.objects.count(), 1)

    def test_common_screen_subclasses_resolve_to_specific_types(self):
        def entity(qid):
            return {"claims": {"P31": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": qid, "entity-type": "item"}}}}]}}

        self.assertEqual(work_type_spec(entity("Q24869"))[0], "film")
        self.assertEqual(work_type_spec(entity("Q506240"))[0], "film")
        self.assertEqual(work_type_spec(entity("Q1259759"))[0], "television-series")
        self.assertEqual(work_type_spec(entity("Q1261214"))[0], "television-program")
        self.assertEqual(work_type_spec(entity("Q1194583"))[0], "play")

    def test_proposal_triage_green_requires_specific_dated_sourced_edge(self):
        def proposal(**work_overrides):
            work_values = {
                "pk": 10,
                "title": "Example film",
                "first_publication_year": 2000,
                "first_publication_date_text": "2000",
                "date_kind": "release",
                "date_evidence": {},
                "visibility": "draft",
                "is_demo": False,
                "has_known_title": True,
                "public_type_code": "film",
                "image_url": "",
            }
            work_values.update(work_overrides)
            work = SimpleNamespace(**work_values)
            seed = SimpleNamespace(
                pk=20,
                title="Example source",
                first_publication_year=1900,
                visibility="public",
                depth="editorial",
                has_known_title=True,
            )
            return SimpleNamespace(
                pk=1,
                run_id=1,
                from_work=work,
                to_work=seed,
                relationship_type=SimpleNamespace(code="based-on"),
                evidence={
                    "property_id": "P144",
                    "entity_id": "Q10",
                    "rank": "normal",
                    "statement_id": "Q10$statement",
                },
                statement_id="Q10$statement",
            )

        decision, reasons, warnings = evaluate_proposal(proposal(), "Q10", 1, "", 1, 2026, 2)
        self.assertEqual(decision, "green")
        self.assertEqual(reasons, [])
        self.assertEqual(warnings, ["no_image"])

        decision, reasons, _ = evaluate_proposal(
            proposal(first_publication_year=None), "Q10", 1, "", 1, 2026, 2
        )
        self.assertEqual(decision, "amber")
        self.assertIn("no_year", reasons)

        decision, reasons, _ = evaluate_proposal(
            proposal(public_type_code="creative-work"), "Q10", 1, "", 1, 2026, 2
        )
        self.assertEqual(decision, "amber")
        self.assertIn("generic_type", reasons)

        decision, reasons, _ = evaluate_proposal(proposal(), "Q10", 1, "accepted", 1, 2026, 2)
        self.assertEqual(decision, "red")
        self.assertIn("already_accepted", reasons)

    def test_stage_candidate_discovery_requires_p144_and_stage_type(self):
        entities = {
            "Q900": {
                "id": "Q900",
                "labels": {"en": {"value": "Example opera"}},
                "claims": {
                    "P31": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q1344", "entity-type": "item"}}}}],
                    "P144": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q83186", "entity-type": "item"}}}}],
                    "P1191": [self.time_claim("+1900-01-01T00:00:00Z", 11, statement_id="Q900$perf")],
                },
            },
            "Q901": {
                "id": "Q901",
                "labels": {"en": {"value": "Not stage"}},
                "claims": {
                    "P31": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q11424", "entity-type": "item"}}}}],
                    "P144": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q83186", "entity-type": "item"}}}}],
                },
            },
        }
        rows = build_candidate_rows(entities, ["Q83186"], seed_labels={"Q83186": "Romeo and Juliet"})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["qid"], rows[0]["expected_type"], rows[0]["expected_year"]), ("Q900", "opera", 1900))
        self.assertEqual(rows[0]["seed_label"], "Romeo and Juliet")
        self.assertEqual(build_candidate_rows(entities, ["Q83186"], existing_qids={"Q900"}), [])

    def test_exact_candidate_can_refresh_generic_draft_type_and_date(self):
        seed = Work.objects.create(
            title="Romeo and Juliet",
            work_type=self.text,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        ExternalIdentifier.objects.create(work=seed, scheme="wikidata", value="Q83186")
        existing = Work.objects.create(
            title="Roméo et Juliete",
            work_type=WorkType.objects.get(code="creative-work") if WorkType.objects.filter(code="creative-work").exists() else WorkType.objects.create(code="creative-work", label="Creative work", medium="other"),
            first_publication_year=1865,
            first_publication_date_text="1865",
            date_kind="inception",
            date_evidence={"property": "P571"},
            visibility=Work.Visibility.DRAFT,
            depth="index",
        )
        ExternalIdentifier.objects.create(work=existing, scheme="wikidata", value="Q918714")
        source = Source.objects.get(title="Wikidata")
        run = ImportRun.objects.create(source=source, requested_keys=["Q83186", "Q918714"])
        candidate_entity = {
            "id": "Q918714",
            "labels": {"en": {"value": "Roméo et Juliete"}},
            "claims": {
                "P1476": [{"mainsnak": {"datavalue": {"value": {"text": "Roméo et Juliette", "language": "fr"}}}}],
                "P31": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q1344", "entity-type": "item"}}}}],
                "P144": [{"rank": "normal", "id": "Q918714$based", "mainsnak": {"datavalue": {"value": {"id": "Q83186", "entity-type": "item"}}}}],
                "P1191": [self.time_claim("+1867-04-27T00:00:00Z", 11, statement_id="Q918714$perf")],
            },
        }

        seed_entity = {"id": "Q83186", "labels": {"en": {"value": "Romeo and Juliet"}}, "claims": {}}

        class FakeClient:
            requests = 0

            def entities(self, ids):
                self.requests += 1
                return {qid: entity for qid, entity in {"Q83186": seed_entity, "Q918714": candidate_entity}.items() if qid in ids}

        run_import(run, ["Q83186"], candidate_qids=["Q918714"], client=FakeClient())
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Roméo et Juliette")
        self.assertEqual(existing.work_type.code, "opera")
        self.assertEqual((existing.first_publication_year, existing.date_kind), (1867, "first_performance"))
        self.assertEqual(existing.date_evidence["property"], "P1191")

    def test_musical_wins_over_play_when_wikidata_has_both_types(self):
        seed = Work.objects.create(
            title="The Wonderful Wizard of Oz",
            work_type=self.text,
            visibility=Work.Visibility.PUBLIC,
            depth="editorial",
        )
        ExternalIdentifier.objects.create(work=seed, scheme="wikidata", value="Q130295")
        source = Source.objects.get(title="Wikidata")
        run = ImportRun.objects.create(source=source, requested_keys=["Q130295", "Q3990060"])
        candidate_entity = {
            "id": "Q3990060",
            "labels": {"en": {"value": "The Wizard of Oz"}},
            "claims": {
                "P31": [
                    {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q2743", "entity-type": "item"}}}},
                    {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q25379", "entity-type": "item"}}}},
                ],
                "P144": [{"rank": "normal", "id": "Q3990060$based", "mainsnak": {"datavalue": {"value": {"id": "Q130295", "entity-type": "item"}}}}],
                "P577": [self.time_claim("+1902-00-00T00:00:00Z", 9, statement_id="Q3990060$pub")],
            },
        }

        class FakeClient:
            requests = 0

            def entities(self, ids):
                self.requests += 1
                return {"Q3990060": candidate_entity} if "Q3990060" in ids else {}

        run_import(run, ["Q130295"], candidate_qids=["Q3990060"], client=FakeClient())
        work = Work.objects.get(identifiers__scheme="wikidata", identifiers__value="Q3990060")
        self.assertEqual(work.work_type.code, "musical")
        self.assertEqual(work.first_publication_year, 1902)


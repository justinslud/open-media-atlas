import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .dates import wikidata_date
from .importers.openlibrary import OpenLibraryImporter
from .models import (Agent, Credit, FeaturedWork, ImportedWorkState, RelationshipType,
                     Source, SourceRecord, Work, WorkRelationship, WorkType)
from .tests import fake_open


class TrustworthyCatalogTests(TestCase):
    def setUp(self):
        self.book = WorkType.objects.create(code='book', label='Book', medium='text')
        self.novel = WorkType.objects.create(code='novel', label='Novel', medium='text')
        self.film = WorkType.objects.create(code='film', label='Film', medium='screen')
        self.generic = WorkType.objects.create(code='creative-work', label='Creative work', medium='other')
        self.source = Source.objects.create(title='Wikidata', url='https://www.wikidata.org/')

    def work(self, title, kind=None, **kwargs):
        return Work.objects.create(title=title, slug=f'work-{Work.objects.count()}',
                                   work_type=kind or self.book, visibility='public', **kwargs)

    def snapshot(self, work, payload):
        return SourceRecord.objects.create(source=self.source, external_key=f'Q{work.pk}', matched_work=work,
                                           raw_payload=payload, payload_hash='test', retrieved_at=timezone.now())

    def claim(self, year, precision=9, prop='P577', **kwargs):
        return {'id': f'Q1${year}', 'mainsnak': {'datavalue': {'value': {
            'time': f'+{year}-01-01T00:00:00Z', 'precision': precision}}}, **kwargs}

    def test_date_selection_preserves_precision_and_does_not_invent_original(self):
        entity = {'id': 'Q1', 'claims': {'P577': [self.claim(1934)]}}
        text, year, precision, kind, evidence = wikidata_date(entity)
        self.assertEqual((text, year, precision, kind), ('1934', 1934, 9, 'publication'))
        work = self.work('Film', self.film, first_publication_date_text=text,
                         first_publication_year=year, date_kind=kind, date_evidence=evidence)
        response = self.client.get(work.get_absolute_url())
        self.assertContains(response, 'Source publication date')
        self.assertNotContains(response, 'First released')
        self.assertNotContains(response, '1934-01-01')
        entity['claims']['P577'] = [self.claim(1934, precision=10)]
        self.assertEqual(wikidata_date(entity)[0], '1934-01')
        entity['claims']['P577'].append(self.claim(2006))
        self.assertEqual(wikidata_date(entity)[:2], ('', None))
        entity['claims']['P577'][1]['rank'] = 'preferred'
        self.assertEqual(wikidata_date(entity)[0], '2006')
        entity['claims'] = {'P571': [self.claim(1934)]}
        self.assertEqual(wikidata_date(entity)[3], 'inception')

    def test_first_label_requires_matching_evidence_and_source(self):
        work = self.work('Known', first_publication_date_text='1818', date_kind='first_publication')
        self.assertEqual(work.date_label, 'Date (meaning unverified)')
        work.date_evidence = {'date_text': '1818', 'source_url': 'https://example.org/first-edition'}
        work.save()
        self.assertContains(self.client.get(work.get_absolute_url()), 'First published')
        work.first_publication_date_text = '2006'
        self.assertEqual(work.date_label, 'Date (meaning unverified)')

    def test_openlibrary_dates_are_supplier_assertions_and_reviewed_date_survives(self):
        payload = {'title': 'Imported', 'first_publish_date': '1969'}
        importer = OpenLibraryImporter(delay=0, opener=fake_open([payload]))
        work = importer.import_work('OL1W').work
        self.assertEqual(work.date_kind, 'publication')
        self.assertEqual(work.first_publication_date_text, '1969')
        work.date_kind = 'first_publication'
        work.date_evidence = {'date_text': '1969', 'source_url': 'https://example.org/review'}
        work.save()
        payload['first_publish_date'] = '1970'
        OpenLibraryImporter(delay=0, opener=fake_open([payload])).import_work('OL1W')
        work.refresh_from_db()
        self.assertEqual(work.first_publication_date_text, '1969')

    def test_books_include_evidence_backed_novels_with_consistent_labels(self):
        novel = self.work('Specific novel', self.novel)
        generic = self.work('Supplier generic', self.generic)
        self.snapshot(generic, {'id': f'Q{generic.pk}', 'claims': {'P31': [
            {'mainsnak': {'datavalue': {'value': {'entity-type': 'item', 'id': 'Q8261'}}}}]}})
        sparse = self.work('Unclassified', self.generic)
        response = self.client.get(reverse('discover'), {'type': 'book'})
        self.assertEqual({w.pk for w in response.context['works']}, {novel.pk, generic.pk})
        self.assertContains(response, 'Novel')
        self.assertEqual(self.client.get(generic.get_absolute_url()).context['provenance']['work_type']['value'], 'Novel')
        self.assertEqual(generic.work_type_id, 'creative-work')
        unknown = self.client.get(reverse('discover'), {'type': 'unclassified'})
        self.assertEqual([w.pk for w in unknown.context['works']], [sparse.pk])
        self.assertEqual(self.client.get(sparse.get_absolute_url()).status_code, 200)

    def test_missing_title_fallback_is_separate_and_distinguishable(self):
        work = self.work('Q3235021', self.film, first_publication_year=1934)
        person = Agent.objects.create(name='Gaston Schoukens', kind='person')
        Credit.objects.create(work=work, agent=person, role='director')
        old_url = work.get_absolute_url()
        self.assertEqual(work.display_title, 'Title unknown — film, 1934 — Gaston Schoukens')
        self.assertEqual(work.title, 'Q3235021')
        self.assertEqual(work.get_absolute_url(), old_url)
        response = self.client.get(old_url)
        self.assertNotContains(response, 'queued for enrichment')
        self.assertNotContains(response, 'identity standard')
        self.assertContains(response, 'Basic catalog entry. Some details are missing.')
        other = Work.objects.create(title='', work_type=self.film, visibility='public')
        self.assertEqual(self.client.get(other.get_absolute_url()).status_code, 200)
        self.assertIn(f'record {other.pk}', other.display_title)

    def test_query_ranks_titles_aliases_partials_then_creators_and_keeps_adaptations(self):
        partial = self.work('Three Musketeers: a sequel', self.film)
        alias = self.work('The Three Musketeers', self.novel)
        self.snapshot(alias, {'id': f'Q{alias.pk}', 'aliases': {'en': [{'value': 'Three Musketeers'}]}})
        exact = self.work('Three Musketeers', self.film)
        creator_work = self.work('A different title')
        agent = Agent.objects.create(name='Three Musketeers Company', kind='organization')
        Credit.objects.create(work=creator_work, agent=agent, role='creator')
        FeaturedWork.objects.create(work=creator_work)
        response = self.client.get(reverse('discover'), {'q': '  THREE—Musketeers!!  '})
        self.assertEqual([w.pk for w in response.context['works']], [exact.pk, alias.pk, partial.pk, creator_work.pk])
        explicit = self.client.get(reverse('discover'), {'q': 'Three Musketeers', 'sort': 'title'})
        self.assertEqual([w.title for w in explicit.context['works']], sorted(w.title for w in explicit.context['works']))
        self.assertContains(self.client.get(reverse('home')), 'Search works or creators')
        self.assertContains(response, 'Search titles or creators')

    def test_discovery_has_identity_signals_and_sparse_records_remain_reachable(self):
        sparse = self.work('Q100', self.film)
        identified = self.work('Zebra', self.novel)
        author = Agent.objects.create(name='Known Author', kind='person')
        Credit.objects.create(work=identified, agent=author, role='author')
        relation_type = RelationshipType.objects.create(code='based-on', label='Based on', inverse_label='Adaptations')
        for number in range(3):
            other = self.work(f'Connection {number}')
            WorkRelationship.objects.create(from_work=other, to_work=sparse, relationship_type=relation_type,
                                             source=self.source, review_status='accepted')
        works = list(self.client.get(reverse('discover')).context['works'])
        self.assertLess(works.index(identified), works.index(sparse))
        self.assertIn(sparse, works)
        FeaturedWork.objects.create(work=identified)
        self.assertEqual(self.client.get(reverse('discover')).context['works'][0], identified)
        alphabetical = self.client.get(reverse('discover'), {'sort': 'title'})
        self.assertEqual([w.title for w in alphabetical.context['works']], sorted(w.title for w in alphabetical.context['works']))
        response = self.client.get(sparse.get_absolute_url())
        self.assertNotContains(response, 'Authorization status: unknown')
        rel = sparse.incoming_relationships.first()
        rel.evidence = {'authorization_statement': 'Permission disputed by the credited studio'}
        rel.save()
        self.assertContains(self.client.get(sparse.get_absolute_url()), 'Permission disputed')

    def test_correction_dry_run_conflicts_review_protection_and_idempotence(self):
        work = self.work('Bad date', first_publication_date_text='2006', first_publication_year=2006)
        row = {'work_id': work.pk, 'expected_date_text': '2006', 'expected_year': 2006,
               'expected_updated_at': work.updated_at.isoformat(), 'date_text': '1818', 'year': 1818,
               'date_kind': 'first_publication', 'source_url': 'https://example.org/first-edition',
               'basis': 'Reviewed first-edition catalog evidence (test fixture)'}
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'dates.json'
            manifest.write_text(json.dumps([row]))
            output = io.StringIO()
            call_command('correct_catalog_dates', manifest=str(manifest), dry_run=True, stdout=output)
            self.assertIn('would_update', output.getvalue())
            work.refresh_from_db()
            self.assertEqual(work.first_publication_year, 2006)
            work.description = 'Changed after preview'
            work.save()
            output = io.StringIO()
            call_command('correct_catalog_dates', manifest=str(manifest), apply=True, stdout=output)
            self.assertIn('conflict_preserved', output.getvalue())
            row['expected_updated_at'] = work.updated_at.isoformat()
            manifest.write_text(json.dumps([row]))
            call_command('correct_catalog_dates', manifest=str(manifest), apply=True, stdout=io.StringIO())
            output = io.StringIO()
            call_command('correct_catalog_dates', manifest=str(manifest), apply=True, stdout=output)
            self.assertIn('unchanged', output.getvalue())
            row['date_text'] = '1820'
            manifest.write_text(json.dumps([row]))
            output = io.StringIO()
            call_command('correct_catalog_dates', manifest=str(manifest), apply=True, stdout=output)
            self.assertIn('preserved_reviewed', output.getvalue())

    def test_manual_date_pair_is_preserved_and_title_enrichment_keeps_imported_date(self):
        payload = {'title': 'Imported', 'first_publish_date': '1853'}
        work = OpenLibraryImporter(delay=0, opener=fake_open([payload])).import_work('OL2W').work
        work.first_publication_date_text = 'Editorial date'
        work.save()
        payload['first_publish_date'] = '2006'
        OpenLibraryImporter(delay=0, opener=fake_open([payload])).import_work('OL2W')
        work.refresh_from_db()
        self.assertEqual((work.first_publication_date_text, work.first_publication_year), ('Editorial date', 1853))

    def test_alias_search_pagination_and_explicit_sort_survive_shareable_urls(self):
        for number in range(32):
            work = self.work(f'Catalog title {number:02}', self.novel)
            self.snapshot(work, {'id': f'Q{work.pk}', 'aliases': {'en': [{'value': 'Shared alias'}]}})
        params = {'q': 'Shared alias', 'type': 'book', 'sort': 'title', 'page': '2'}
        response = self.client.get(reverse('discover'), params)
        self.assertEqual(response.context['result_count'], 32)
        self.assertEqual([w.title for w in response.context['works']], ['Catalog title 30', 'Catalog title 31'])
        self.assertContains(response, 'q=Shared+alias&amp;type=book&amp;sort=title&amp;page=1')
        self.assertEqual(response.context['selected_sort'], 'title')
        self.assertEqual(self.client.get(reverse('discover'), {'q': 'Catalog titl 30'}).context['result_count'], 1)

    def test_deprecated_and_conflicting_classifications_do_not_guess(self):
        work = self.work('Title alone is not evidence', self.generic)
        def type_claim(qid, rank='normal'):
            return {'rank': rank, 'mainsnak': {'datavalue': {'value': {'entity-type': 'item', 'id': qid}}}}
        self.snapshot(work, {'id': f'Q{work.pk}', 'claims': {'P31': [
            type_claim('Q8261'), type_claim('Q11424')]}})
        self.assertEqual(work.public_type_code, 'creative-work')
        self.assertEqual(self.client.get(reverse('discover'), {'type': 'book'}).context['result_count'], 0)
        record = work.source_records.first()
        record.raw_payload['claims']['P31'][1]['rank'] = 'deprecated'
        record.save()
        self.assertEqual(work.public_type_code, 'novel')

    def test_dumas_supplier_form_and_tight_partial_match_find_novel_without_alias_invention(self):
        # Representative Q140527 evidence: P31 literary work; P7937 novel;
        # no English alias. This is a supplied form, not inference from the title.
        literary = WorkType.objects.create(code='literary-work', label='Literary work', medium='text')
        novel = self.work('The Three Musketeers', literary)
        author = Agent.objects.create(name='Alexandre Dumas', kind='person')
        Credit.objects.create(work=novel, agent=author, role='author')
        def item(qid):
            return {'mainsnak': {'datavalue': {'value': {'entity-type': 'item', 'id': qid}}}}
        self.snapshot(novel, {'id': 'Q140527', 'claims': {
            'P31': [item('Q7725634')], 'P7937': [item('Q8261')]}})
        adaptation = self.work("D'Artagnan and the Three Musketeers", self.film)
        Credit.objects.create(work=adaptation, agent=author, role='test fixture creator')
        FeaturedWork.objects.create(work=adaptation)
        response = self.client.get(reverse('discover'), {'q': 'Three Musketeers'})
        self.assertEqual([w.pk for w in response.context['works']], [novel.pk, adaptation.pk])
        self.assertEqual(novel.public_type_label, 'Novel')
        books = self.client.get(reverse('discover'), {'q': 'Three Musketeers', 'type': 'book'})
        self.assertEqual([w.pk for w in books.context['works']], [novel.pk])
        self.assertEqual(novel.work_type_id, 'literary-work')
        punctuation = self.client.get(reverse('discover'), {'q': 'DArtagnan'})
        self.assertEqual([w.pk for w in punctuation.context['works']], [adaptation.pk])

    def test_wide_result_sets_load_related_rows_without_sqlite_expression_depth_errors(self):
        # SQLite refuses expression trees deeper than 1000. A catalog-wide prefetch
        # of credits__agent used to build one OR term per agent and crash search.
        works = [Work(title=f'Wide result {number:04}', slug=f'wide-{number}',
                      work_type=self.book, visibility='public')
                 for number in range(1100)]
        Work.objects.bulk_create(works, batch_size=200)
        agents = [Agent(name=f'Wide Creator {number:04}', kind='person') for number in range(1100)]
        Agent.objects.bulk_create(agents, batch_size=200)
        stored = list(Work.objects.filter(slug__startswith='wide-').order_by('id'))
        stored_agents = list(Agent.objects.filter(name__startswith='Wide Creator').order_by('id'))
        Credit.objects.bulk_create(
            [Credit(work=work, agent=agent, role='author') for work, agent in zip(stored, stored_agents)],
            batch_size=200,
        )
        response = self.client.get(reverse('discover'), {'q': 'Wide result'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result_count'], 1100)
        creator = self.client.get(reverse('discover'), {'q': 'Wide Creator 0500'})
        self.assertEqual(creator.status_code, 200)
        self.assertEqual([w.pk for w in creator.context['works']], [stored[500].pk])

from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .connections import PAGE_SIZE, direction_label
from .models import RelationshipType, Source, SourceRecord, Work, WorkRelationship, WorkType


class ConnectionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.novel = WorkType.objects.create(code='novel', label='Novel', medium='text')
        cls.film = WorkType.objects.create(code='film', label='Film', medium='screen')
        cls.unknown = WorkType.objects.create(code='unknown', label='Unknown', medium='unknown')
        cls.adapted = RelationshipType.objects.create(code='adapted-from', label='Adapted from', inverse_label='Adaptations')
        cls.inspired = RelationshipType.objects.create(code='inspired-by', label='Inspired by', inverse_label='Inspired', category='influence')
        cls.source = Source.objects.create(title='Synthetic source', url='https://example.test/source')
        cls.work = Work.objects.create(title='Current work', work_type=cls.novel, visibility='public')

    def make_work(self, title, kind=None, **kwargs):
        return Work.objects.create(title=title, work_type=kind or self.film, visibility='public', **kwargs)

    def relate(self, source, target, kind=None, **kwargs):
        return WorkRelationship.objects.create(from_work=source, to_work=target, relationship_type=kind or self.adapted,
            source=self.source, review_status=kwargs.pop('review_status', 'accepted'), **kwargs)

    def get(self, **params):
        return self.client.get(self.work.get_absolute_url(), params)

    def test_direction_grouping_and_no_multihop_inference(self):
        parent = self.make_work('Parent', self.novel)
        child = self.make_work('Child')
        grandchild = self.make_work('Grandchild')
        self.relate(self.work, parent)
        self.relate(child, self.work)
        self.relate(grandchild, child)
        response = self.get()
        rows = response.context['connection_rows']
        self.assertEqual([r['work'].pk for r in rows], [parent.pk, child.pk])
        self.assertEqual([r['group'] for r in rows], ['Source works', 'Adaptations'])
        self.assertEqual([r['relationships'][0]['label'] for r in rows], ['Based on', 'Adapted into'])
        self.assertNotContains(response, 'Grandchild')
        self.assertContains(response, '2 connected works')

    def test_stored_direction_labels_preserve_supported_categories(self):
        child = self.make_work('Child')
        for code, label, inverse, category in [
            ('inspired-by', 'Inspired by', 'Inspired', 'influence'),
            ('remake-of', 'Remake of', 'Remade as', 'derivation'),
            ('sequel-to', 'Sequel to', 'Followed by', 'sequence'),
            ('part-of', 'Part of', 'Contains', 'composition'),
            ('shared-universe', 'Shares universe with', 'Shares universe with', 'association'),
            ('based-on', 'Based on', 'Inspired or adapted works', 'derivation'),
        ]:
            kind, _ = RelationshipType.objects.get_or_create(code=code, defaults=dict(label=label, inverse_label=inverse, category=category))
            edge = self.relate(child, self.work, kind)
            self.assertEqual(direction_label(edge, child.pk), label)
            self.assertEqual(direction_label(edge, self.work.pk), inverse)

    def test_multiple_meanings_and_both_directions_share_one_row(self):
        other = self.make_work('Other')
        self.relate(other, self.work)
        self.relate(other, self.work, self.inspired)
        self.relate(self.work, other, self.inspired)
        response = self.get(connection_relationship='in:adapted-from')
        self.assertEqual(response.context['connection_total'], 1)
        self.assertEqual(response.context['connection_assertions'], 3)
        self.assertEqual(len(response.context['connection_rows']), 1)
        self.assertEqual({r['label'] for r in response.context['connection_rows'][0]['relationships']},
            {'Adapted into', 'Inspired', 'Inspired by'})
        self.assertContains(response, f'href="{other.get_absolute_url()}"', count=1)

    def test_missing_identity_evidence_and_empty_state(self):
        self.assertContains(self.get(), 'No connections recorded yet')
        other = self.make_work('Q1234', self.unknown)
        self.source.url = ''
        self.source.save()
        self.relate(other, self.work, evidence={})
        response = self.get()
        for text in ['Title unknown', 'Unclassified work', 'Date not recorded',
                     'No supporting note or excerpt recorded', 'No evidence source link recorded', 'Origin not recorded']:
            self.assertContains(response, text)
        self.assertEqual(response.context['connection_total'], 1)

    def test_pagination_filters_dates_reset_and_shared_urls(self):
        for index in range(PAGE_SIZE + 4):
            other = self.make_work(f'Connected {index:02}', self.film if index % 2 else self.novel,
                first_publication_year=2000 + index, first_publication_date_text=str(2000 + index))
            self.relate(other, self.work, self.adapted if index % 2 else self.inspired)
        response = self.get(connection_q='connected', connection_sort='title')
        self.assertEqual(len(response.context['connection_rows']), PAGE_SIZE)
        url = response.context['connection_next']
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params['connection_q'], ['connected'])
        self.assertEqual(params['connection_sort'], ['title'])
        second = self.client.get(self.work.get_absolute_url() + url)
        self.assertEqual(len(second.context['connection_rows']), 4)
        first_ids = {r['work'].pk for r in response.context['connection_rows']}
        self.assertFalse(first_ids & {r['work'].pk for r in second.context['connection_rows']})
        filtered = self.get(connection_type='film', connection_relationship='in:adapted-from', connection_sort='-date')
        self.assertEqual(filtered.context['connection_page'].paginator.count, 8)
        self.assertEqual(filtered.context['connection_rows'][0]['work'].first_publication_year, 2015)
        self.assertContains(filtered, 'type Film')
        self.assertContains(filtered, 'Reset view')
        self.assertContains(self.get(connection_q='absent'), 'No connected works match')
        self.assertEqual(self.get(connection_page='invalid').context['connection_page'].number, 1)
        self.assertEqual(self.get(connection_page='999').context['connection_page'].number, 2)
        self.assertEqual(self.get(connection_type='invalid', connection_sort='invalid').context['connection_total'], 16)

    def test_date_null_last_and_title_sort_retains_distinct_work_ids(self):
        for title, year in [('Same', 2001), ('Same', 1999), ('A missing year', None)]:
            self.relate(self.make_work(title, first_publication_year=year), self.work)
        for sort, expected in [('date', [1999, 2001, None]), ('-date', [2001, 1999, None])]:
            rows = self.get(connection_sort=sort).context['connection_rows']
            self.assertEqual([r['work'].first_publication_year for r in rows], expected)
        self.assertEqual(len(self.get().context['connection_rows']), 3)

    def test_timeline_orders_dated_connections_and_counts_undated(self):
        later = self.make_work('Later adaptation', first_publication_year=2010)
        earlier = self.make_work('Earlier adaptation', first_publication_year=1990)
        undated = self.make_work('Undated adaptation')
        self.relate(later, self.work)
        self.relate(earlier, self.work)
        self.relate(earlier, self.work, self.inspired)
        self.relate(undated, self.work)
        response = self.get()
        self.assertEqual(
            [event['work'].pk for event in response.context['timeline_events']],
            [earlier.pk, later.pk],
        )
        self.assertEqual(response.context['timeline_start'], 1990)
        self.assertEqual(response.context['timeline_end'], 2010)
        self.assertEqual(response.context['timeline_undated'], 1)
        self.assertContains(response, 'id="timeline"')
        self.assertContains(response, '1990')
        self.assertContains(response, '2010')
        self.assertContains(response, '1 undated')

    def test_visibility_review_and_unconnected_catalog_are_excluded(self):
        for state in ['draft', 'suppressed']:
            hidden = self.make_work(state)
            hidden.visibility = state
            hidden.save()
            self.relate(hidden, self.work)
        for review in ['unreviewed', 'disputed']:
            self.relate(self.make_work(review), self.work, review_status=review)
        self.make_work('Unconnected')
        response = self.get()
        self.assertEqual(response.context['connection_total'], 0)
        self.assertEqual(response.context['connection_choices'], [])
        self.assertContains(response, 'href="#connections"')

    def test_evidence_distinguishes_import_and_review_without_rights_claims(self):
        other = self.make_work('Imported')
        self.relate(other, self.work, scope_note='A stored supporting note.', evidence={
            'asserted_by': 'Wikidata', 'statement_id': 'Q1$test', 'property_id': 'P144',
            'source_url': 'https://example.test/statement', 'authorization_statement': 'Permission granted',
            'references': [{'snaks': {'P854': [{'datavalue': {'value': 'https://example.test/reference'}}]}}],
        })
        response = self.get()
        for text in ['Imported assertion: Wikidata', 'Review state:</strong> Accepted',
                     'A stored supporting note.', 'https://example.test/reference', 'Q1$test']:
            self.assertContains(response, text)
        self.assertContains(response, 'Permission granted — attributed to Synthetic source')
        self.assertContains(response, 'Suggest a correction')

    def test_type_filter_uses_supplier_evidence_and_date_meaning(self):
        other = self.make_work('Supplier-typed novel', self.unknown,
            first_publication_year=2000, first_publication_date_text='2000', date_kind='inception',
            date_evidence={'date_text': '2000', 'source_url': 'https://example.test/date'})
        SourceRecord.objects.create(source=self.source, external_key='Q100', matched_work=other,
            payload_hash='synthetic', retrieved_at=timezone.now(), raw_payload={
                'id': 'Q100', 'claims': {'P31': [{'mainsnak': {'datavalue': {'value': {'id': 'Q8261'}}}}]}})
        self.relate(other, self.work)
        response = self.get(connection_type='novel')
        self.assertEqual(response.context['connection_page'].paginator.count, 1)
        self.assertContains(response, 'Creation date: 2000')
        self.assertContains(response, 'Novel')

    def test_queries_do_not_grow_per_row_and_only_page_evidence_is_loaded(self):
        self.relate(self.make_work('First'), self.work)
        with CaptureQueriesContext(connection) as small:
            self.get()
        for index in range(20):
            self.relate(self.make_work(f'Item {index:02}'), self.work)
        with CaptureQueriesContext(connection) as large:
            response = self.get()
        self.assertEqual(len(small), len(large))
        self.assertEqual(len(response.context['connection_rows']), PAGE_SIZE)
        evidence_queries = [q['sql'] for q in large if '"catalog_workrelationship"."evidence"' in q['sql']]
        self.assertEqual(len(evidence_queries), 1)
        self.assertIn(' IN ', evidence_queries[0])

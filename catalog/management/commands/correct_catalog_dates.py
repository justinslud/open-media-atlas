"""Explicit, offline, compare-and-set corrections; no catalog-wide selection."""
import json
from pathlib import Path
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Work


class Command(BaseCommand):
    help = 'Preview at most 20 explicitly identified date corrections; writes require --apply.'

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument('--manifest')
        selection.add_argument('--inspect', nargs='+', type=int, metavar='WORK_ID')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if options['apply'] and options['dry_run']:
            raise CommandError('Choose --dry-run or --apply, not both.')
        if options['inspect']:
            if options['apply'] or len(options['inspect']) > 20:
                raise CommandError('--inspect is read-only and accepts at most 20 work IDs.')
            for pk in dict.fromkeys(options['inspect']):
                work = Work.objects.filter(pk=pk).first()
                if work is None:
                    self.stdout.write(json.dumps({'work_id': pk, 'status': 'missing'}))
                    continue
                self.stdout.write(json.dumps({'work_id': pk, 'title': work.title,
                    'expected_date_text': work.first_publication_date_text,
                    'expected_year': work.first_publication_year, 'expected_updated_at': work.updated_at.isoformat(),
                    'date_kind': work.date_kind, 'date_evidence': work.date_evidence,
                    'reviewed_edits': work.contribution_revisions.filter(field_name='first_publication_date_text').exists(),
                    'suppliers': [self.supplier_summary(record) for record in work.source_records.select_related('work_state')]
                }, ensure_ascii=False, sort_keys=True))
            return
        try:
            rows = json.loads(Path(options['manifest']).read_text())
            if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
                raise ValueError('Manifest must contain 1..20 explicit records.')
            ids = [row['work_id'] for row in rows]
            if any(type(pk) is not int for pk in ids) or len(set(ids)) != len(ids):
                raise ValueError('work_id must be a unique integer.')
            for row in rows:
                for field in ('expected_date_text', 'expected_year', 'expected_updated_at',
                              'date_text', 'year', 'date_kind', 'source_url', 'basis'):
                    if field not in row:
                        raise ValueError(f'Missing {field}')
                if not all(isinstance(row[field], str) for field in ('expected_date_text', 'expected_updated_at', 'date_text', 'date_kind', 'source_url', 'basis')):
                    raise ValueError('Text fields and expected_updated_at must be strings.')
                if row['date_kind'] not in dict(Work._meta.get_field('date_kind').choices):
                    raise ValueError('Unsupported date_kind')
                if not isinstance(row['date_text'], str) or len(row['date_text']) > 80:
                    raise ValueError('date_text must be a string of at most 80 characters.')
                if row['year'] is not None and type(row['year']) is not int:
                    raise ValueError('year must be an integer or null.')
                url = urlparse(row['source_url'])
                if url.scheme not in ('https', 'http') or not url.netloc or not row['basis'].strip():
                    raise ValueError('A source URL and explicit evidence basis are required.')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(str(exc)) from exc

        with transaction.atomic():
            for row in rows:
                work = Work.objects.select_for_update().filter(pk=row['work_id']).first()
                report = {'work_id': row['work_id'], 'dry_run': not options['apply']}
                if work is None:
                    report['status'] = 'missing'
                    self.stdout.write(json.dumps(report))
                    continue
                evidence = {'date_text': row['date_text'], 'source_url': row['source_url'],
                            'basis': row['basis'], 'previous_date_text': row['expected_date_text'],
                            'previous_year': row['expected_year'], 'correction': 'explicit manifest'}
                report.update(title=work.title, before={'date_text': work.first_publication_date_text,
                    'year': work.first_publication_year, 'date_kind': work.date_kind,
                    'updated_at': work.updated_at.isoformat()},
                    after={key: row[key] for key in ('date_text', 'year', 'date_kind', 'source_url', 'basis')},
                    suppliers=[self.supplier_summary(record) for record in work.source_records.select_related('work_state')])
                if (work.first_publication_date_text, work.first_publication_year, work.date_kind, work.date_evidence) == (
                        row['date_text'], row['year'], row['date_kind'], evidence):
                    report['status'] = 'unchanged'
                elif work.contribution_revisions.filter(field_name='first_publication_date_text').exists() or work.depth == 'editorial' or work.date_kind in {'first_publication', 'first_release'}:
                    report['status'] = 'preserved_reviewed'
                elif (work.first_publication_date_text, work.first_publication_year, work.updated_at.isoformat()) != (
                        row['expected_date_text'], row['expected_year'], row['expected_updated_at']):
                    report['status'] = 'conflict_preserved'
                else:
                    report['status'] = 'applied' if options['apply'] else 'would_update'
                    if options['apply']:
                        work.first_publication_date_text = row['date_text']
                        work.first_publication_year = row['year']
                        work.date_kind = row['date_kind']
                        work.date_evidence = evidence
                        work.save(update_fields=('first_publication_date_text', 'first_publication_year',
                                                 'date_kind', 'date_evidence', 'updated_at'))
                self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def supplier_summary(record):
        payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        data = payload.get('work', payload)
        return {'record_id': record.pk, 'external_key': record.external_key,
                'imported_date_text': getattr(getattr(record, 'work_state', None), 'imported_date_text', None),
                'first_publish_date': data.get('first_publish_date') if isinstance(data, dict) else None,
                'wikidata_date_claims': {prop: payload.get('claims', {}).get(prop, []) for prop in ('P577', 'P571')},
                'edition_dates': [{'key': row.get('key'), 'publish_date': row.get('publish_date')}
                                  for row in payload.get('editions', []) if isinstance(row, dict)]}

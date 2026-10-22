"""Resumable local download, verified extraction, and bounded draft ingestion.

Run with .venv/bin/python -u scripts/local_openlibrary_pilot.py.
Progress: data/openlibrary-dumps/pilot.log and pilot-status.json.
Rerun the same command after interruption; extraction restarts, downloads resume.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ['DATABASE_URL'] = ''
os.environ['DJANGO_DEBUG'] = 'true'
os.environ['DJANGO_SETTINGS_MODULE'] = 'oma.settings'


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def main():
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from catalog.management.commands.run_openlibrary_cloud_pilot import resolve_snapshot
    from catalog.importers.openlibrary_bulk import extract, validate_extract
    from catalog.models import ImportRun, Source

    assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
    base = ROOT / 'data/openlibrary-dumps'
    base.mkdir(parents=True, exist_ok=True)
    lock = (base / 'pilot.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (base / 'pilot.pid').write_text(str(os.getpid()) + '\n')

    def status(phase, **details):
        value = dict(phase=phase, pid=os.getpid(), at=datetime.now(timezone.utc).isoformat(), **details)
        save(base / 'pilot-status.json', value)
        print(json.dumps(value), flush=True)

    try:
        kinds = ('authors', 'works', 'editions')
        pin = base / 'pilot-snapshot.json'
        if pin.exists():
            config = json.loads(pin.read_text())
        else:
            status('resolving_snapshot')
            config = resolve_snapshot({'snapshot_date': '', **{k: f'https://openlibrary.org/data/ol_dump_{k}_latest.txt.gz' for k in kinds}, **{f'{k}_checksum': '' for k in kinds}})
            identifier = config['works'].split('/')[-2]
            with urlopen(f'https://archive.org/metadata/{identifier}', timeout=60) as response:
                metadata = json.load(response)
            config['sizes'] = {k: int(next(f['size'] for f in metadata['files'] if f['name'] == config[k].split('/')[-1])) for k in kinds}
            save(pin, config)
        folder = base / config['snapshot_date']
        folder.mkdir(exist_ok=True)
        paths = {k: folder / config[k].split('/')[-1] for k in kinds}
        remaining = sum(max(0, config['sizes'][k] - (paths[k].stat().st_size if paths[k].exists() else paths[k].with_suffix('.gz.partial').stat().st_size if paths[k].with_suffix('.gz.partial').exists() else 0)) for k in kinds)
        if shutil.disk_usage(base).free < remaining + 5 * 1024**3:
            raise RuntimeError('Need dump space plus 5 GiB headroom')
        for kind, path in paths.items():
            if not path.exists():
                partial = path.with_suffix('.gz.partial')
                status('downloading', kind=kind, expected_bytes=config['sizes'][kind], total_bytes=sum(config['sizes'].values()))
                subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '8', '--retry-delay', '10', '--connect-timeout', '60', '--speed-limit', '1024', '--speed-time', '120', '--continue-at', '-', '--output', str(partial), config[kind]], check=True)
                candidate = partial
            else:
                candidate = path
            status('verifying', kind=kind)
            expected = config[f'{kind}_checksum']
            with candidate.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256' if len(expected) == 64 else 'sha1').hexdigest()
            if candidate.stat().st_size != config['sizes'][kind] or actual != expected:
                raise RuntimeError(f'{kind} integrity check failed; retained file for inspection')
            if candidate != path:
                candidate.replace(path)
        output = ROOT / 'data/openlibrary-extracts' / (config['snapshot_date'] + '-local-5000')
        if not (output / 'manifest.json').exists():
            status('extracting')
            extract(**paths, output=output, limit=5000, snapshot_date=config['snapshot_date'], urls={k: config[k] for k in kinds}, checksums={k: config[f'{k}_checksum'] for k in kinds}, progress=lambda phase, stats: status('extracting', step=phase, stats=dict(stats)))
        manifest, _ = validate_extract(output)
        call_command('ingest_openlibrary_extract', output, dry_run=True)
        backup = folder / 'before-pilot.sqlite3'
        if not backup.exists():
            with sqlite3.connect(settings.DATABASES['default']['NAME']) as source_db, sqlite3.connect(backup) as target_db:
                source_db.backup(target_db)
        source, _ = Source.objects.get_or_create(title='Open Library', defaults={'kind': 'dataset', 'url': 'https://openlibrary.org/developers/dumps'})
        state = output / 'local-run.json'
        if state.exists():
            run_id = json.loads(state.read_text())['run_id']
        else:
            run = ImportRun.objects.create(source=source, manifest=manifest, importer_version=manifest['importer_version'], requested_keys=[])
            run_id = run.pk
            save(state, {'run_id': run_id})
        status('ingesting_drafts', run_id=run_id)
        call_command('ingest_openlibrary_extract', output, resume_run=run_id)
        run = ImportRun.objects.get(pk=run_id)
        status('finished' if run.status == ImportRun.Status.COMPLETED else 'needs_review', run_id=run_id, run_status=run.status, stats=run.stats)
    except Exception as exc:
        status('failed', error=str(exc))
        raise


if __name__ == '__main__':
    main()

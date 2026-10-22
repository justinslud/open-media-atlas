"""Local-only source snapshots. No Django writes. Resume by repeating the command."""
import argparse
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = 'OpenMediaAtlas-local-catalog/0.1'


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def fetch(url):
    for attempt in range(7):
        try:
            with urlopen(Request(url, headers={'User-Agent': UA}), timeout=60) as r:
                return r.read()
        except HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            delay = e.headers.get('Retry-After', '')
            time.sleep(max(2**attempt, int(delay) if delay.isdigit() else 0))
        except (URLError, TimeoutError):
            if attempt == 6:
                raise
            time.sleep(2**attempt)
    raise RuntimeError('Retry limit reached: ' + url)


def tvmaze(root, status):
    pages = root / 'pages'
    pages.mkdir(exist_ok=True)
    manifest = {'source': 'https://www.tvmaze.com/api', 'license': 'CC BY-SA', 'scope': 'show index only; no episode/cast/image downloads', 'files': []}
    seen = set()
    output = root / 'shows.jsonl.partial'
    with output.open('w') as stream:
        for page in range(10000):
            path = pages / f'{page:05}.json'
            url = f'https://api.tvmaze.com/shows?page={page}'
            if not path.exists():
                time.sleep(1)
                try:
                    raw = fetch(url)
                except HTTPError as e:
                    if e.code == 404 and page > 0:
                        break
                    raise
                rows = json.loads(raw)
                if not isinstance(rows, list):
                    raise ValueError('Expected show list')
                save(path, rows)
            rows = json.loads(path.read_text())
            for row in rows:
                ident = row['id']
                if not isinstance(ident, int) or ident // 250 != page:
                    raise ValueError(f'Unexpected ID on page {page}: {ident}')
                if ident in seen:
                    raise ValueError(f'Duplicate show {ident}')
                seen.add(ident)
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            manifest['files'].append({'page': page, 'url': url, 'records': len(rows), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            status('downloading', pages=page+1, shows=len(seen))
        else:
            raise RuntimeError('Page safety cap reached; not a complete snapshot')
    output.replace(root / 'shows.jsonl')
    manifest.update(records=len(seen), completed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), consistency='Pages fetched over time; not an atomic upstream snapshot')
    save(root / 'manifest.json', manifest)
    status('complete', pages=len(manifest['files']), shows=len(seen), bytes=(root / 'shows.jsonl').stat().st_size)


def imdb(root, status):
    pin = root / 'snapshot.json'
    if pin.exists():
        metadata = json.loads(pin.read_text())
    else:
        metadata = []
        for name in ('name.basics', 'title.akas', 'title.basics', 'title.crew', 'title.episode', 'title.principals', 'title.ratings'):
            url = f'https://datasets.imdbws.com/{name}.tsv.gz'
            with urlopen(Request(url, method='HEAD', headers={'User-Agent': UA}), timeout=60) as r:
                metadata.append({'name': name+'.tsv.gz', 'url': url, 'bytes': int(r.headers['Content-Length']), 'etag': r.headers['ETag'], 'modified': r.headers.get('Last-Modified')})
        save(pin, metadata)
    for entry in metadata:
        path = root / entry['name']
        partial = path.with_suffix('.gz.partial')
        if not path.exists():
            status('downloading', file=entry['name'], expected_bytes=entry['bytes'])
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '5', '--connect-timeout', '60', '--speed-time', '120', '--speed-limit', '1024', '--header', 'If-Match: '+entry['etag'], '--continue-at', '-', '--output', str(partial), entry['url']], check=True)
            candidate = partial
        else:
            candidate = path
        status('validating', file=entry['name'])
        if candidate.stat().st_size != entry['bytes']:
            raise ValueError('Size mismatch: '+entry['name'])
        with gzip.open(candidate, 'rb') as stream:
            header = stream.readline().decode('utf-8').rstrip('\n').split('\t')
            expected_id = 'nconst' if entry['name'].startswith('name.') else 'titleId' if entry['name'].startswith('title.akas') else 'tconst'
            if not header or header[0] != expected_id:
                raise ValueError('Unexpected TSV header')
            while stream.read(1024*1024):
                pass  # Read entire gzip to verify CRC and truncation.
        with candidate.open('rb') as stream:
            entry['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        entry['columns'] = header
        if candidate != path:
            candidate.replace(path)
        save(pin, metadata)
    save(root / 'manifest.json', {'source': 'https://data.imdb.com/non-commercial-datasets/', 'use': 'local research; personal/noncommercial source terms', 'files': metadata})
    status('complete', files=len(metadata), bytes=sum(e['bytes'] for e in metadata))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', choices=['tvmaze', 'imdb'])
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / 'download.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def status(phase, **data):
        value = {'phase': phase, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **data}
        save(args.output / 'status.json', value)
        print(json.dumps(value), flush=True)
    try:
        {'tvmaze': tvmaze, 'imdb': imdb}[args.source](args.output, status)
    except Exception as e:
        status('failed', error=str(e))
        raise

if __name__ == '__main__':
    main()

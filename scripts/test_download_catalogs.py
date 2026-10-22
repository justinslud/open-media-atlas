import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import download_catalogs as d


class DownloadTests(unittest.TestCase):
    def test_tv_resume_uses_cached_pages_and_terminal_404(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'pages').mkdir()
            d.save(root/'pages/00000.json', [{'id': 1, 'name': 'A'}])
            with patch.object(d, 'fetch', side_effect=[b'[{"id":250,"name":"B"}]', HTTPError('u',404,'end',{},None)]) as fetch, patch.object(d.time,'sleep'):
                d.tvmaze(root, lambda *a,**k: None)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(json.loads((root/'manifest.json').read_text())['records'], 2)
            self.assertEqual(len((root/'shows.jsonl').read_text().splitlines()), 2)

    def test_nonterminal_error_does_not_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(d,'fetch',side_effect=HTTPError('u',403,'denied',{},None)), patch.object(d.time,'sleep'):
                with self.assertRaises(HTTPError): d.tvmaze(root, lambda *a,**k:None)
            self.assertFalse((root/'manifest.json').exists())

    def test_rate_limit_retry(self):
        from io import BytesIO
        with patch.object(d,'urlopen',side_effect=[HTTPError('u',429,'slow',{'Retry-After':'3'},None),BytesIO(b'[]')]), patch.object(d.time,'sleep') as sleep:
            self.assertEqual(d.fetch('https://example.com'),b'[]')
            sleep.assert_called_once_with(3)

    def test_imdb_truncated_gzip_never_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            name='title.basics.tsv.gz'
            broken=gzip.compress(b'tconst\tprimaryTitle\ntt1\tTest\n')[:-4]
            (root/(name+'.partial')).write_bytes(broken)
            d.save(root/'snapshot.json',[{'name':name,'bytes':len(broken),'url':'https://example.com','etag':'"pinned"'}])
            with patch.object(d.subprocess,'run') as run:
                with self.assertRaises(EOFError): d.imdb(root,lambda *a,**k:None)
                self.assertIn('If-Match: "pinned"',run.call_args.args[0])
            self.assertFalse((root/name).exists())
            self.assertFalse((root/'manifest.json').exists())

if __name__=='__main__': unittest.main()

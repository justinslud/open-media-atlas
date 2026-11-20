# Local data shortlist — 2026-10-21

Checked the two OMA vault project notes and the repository's September data-source map. The vault's original Gutenberg link is https://github.com/hugovk/gutenberg-metadata (original note line 145; clean note line 544).

## Gutenberg: downloaded, but historical

Saved `~/data/oma/gutenberg/gutenberg-metadata.json` outside Git: 75,131,164 bytes, 68,502 ID-keyed records. JSON parsing passed; SHA-256 and retrieval provenance are in the adjacent `manifest.json`. Pinned repository commit `b8256490234fe44e226a9a2c8fd69b90ca2dfa31`.

Important discovery: repository maintenance is recent, but the JSON's last commit is **2022-07-11**, `9134ddd47e78d7f85cbdff5d6b9d82ec43d2cc1c`. It is a historical sample, not today's complete catalog. Fields include author, title, language, subjects, rights statements, and file URLs. No import or automatic book matching performed.

For fresh data use [Gutenberg's official catalogs](https://www.gutenberg.org/ebooks/offline_catalogs.html): daily XML/RDF metadata; CSV is also described in the catalog section. JSON OPDS2 is currently a testing feed requiring contact, not an established single-file full JSON export. Gutendex is a [Django JSON API implementation](https://github.com/garethbjohnson/gutendex), not itself an official static dump. We can convert the official catalog locally rather than depend on a stale mirror.

Do not map Gutenberg release dates to original publication dates. Gutenberg says print-source dates are not included and ebooks may derive from multiple editions. Keep ebook IDs and supplied rights statements separate from canonical work identity and worldwide rights claims.

## Other candidates

| Source | Easy acquisition | Recommendation |
|---|---|---|
| [TVmaze](https://www.tvmaze.com/api) | Public JSON show index `/shows?page=0`, up to 250 records/page; increment until HTTP 404. Episode/cast endpoints are separate. | Best next small TV sample. New candidate beyond vault list. Attribution + CC BY-SA; retain source URLs and source separation. Back off on 429. |
| [IMDb](https://data.imdb.com/non-commercial-datasets/) | Daily gzip TSV files at https://datasets.imdbws.com/; `title.basics`, `title.episode`, `title.crew`, `name.basics` useful for movie/TV identity, hierarchy and credits. | Convenient local research data. Personal/noncommercial terms; repo plan explicitly deferred unrestricted integration. No download/import launched. |
| [TMDB exports](https://developer.themoviedb.org/docs/daily-id-exports) | Daily movie/TV/person JSONL gzip ID lists without authentication currently; files kept three months. | These are NOT full metadata exports. Detailed records need API access and applicable usage terms. Avoid mistaking an ID list for a catalog. |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Database_download) | Full JSON/RDF dumps and narrower access routes; existing OMA enrichment commands already present. | Strongest fit for cross-media identities and adaptation candidates. Start with bounded relevant records, not the whole knowledge base. |
| [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_Database/Download) | Official database snapshots, selectable component archives; relational/PostgreSQL-oriented. | Good music phase later; more integration work than a small JSON file. Check licenses by component. |
| [MovieLens 100K](https://grouplens.org/datasets/movielens/100k/) | 5 MB ZIP, published checksum; 100,000 ratings over roughly 1,700 movies, released 1998. | Easy recommendation benchmark, not a current film catalog. Keep imported user ratings out of OMA's own community activity. |

Vault also lists Book Genome, Goodreads/UCSD, Goodreads/Kaggle, a Kaggle TV dataset, a [Netflix CSV repository](https://github.com/rohitgillela/NETFLIX-DATASET), Library of Congress, and YouTube Commons. These are leads, not approved sources. Prefer documented primary catalogs for identity; old analysis CSVs can be useful experiments but do not establish current streaming availability. Did not audit all those datasets this pass.

## Next useful experiment

### Follow-up: TVmaze sizing and music direction

Live checks on 2026-10-21: `/updates/shows` returned 90,618 show IDs; highest ID 95,116. Since show-index pages use ID ranges of 250, expect floor(95116/250)+1 = 381 pages, plus one terminal 404 request. First index page contained 240 records and 373,794 decoded bytes. Scaling that page's average gives roughly 141 MB uncompressed show JSON; this is a rough estimate, not a measured full download (early shows may be richer). At one request/second, allow about 6.4 minutes of pacing plus network latency. Docs permit at least 20 requests/10 seconds and explicitly support local caching; use caching, resume and 429 backoff. Episodes and cast are separate: fetching both for every show would add roughly 181,236 requests, about 50 hours at one/second before latency. Start with show index, then enrich selected shows. No TVmaze downloader found under repository scripts/catalog; none launched this pass.

User direction: music belongs in OMA's ambitious cross-media scope, but **hold off MusicBrainz downloads for now**. Suggested entry point is soundtracks, scores, musicals and book/poem adaptations, then covers/samples and wider music relationships. Keep composition/work, particular recording, and album/release distinct. MusicBrainz provides these entity categories and structured relationships; availability of a relationship type does not guarantee complete coverage. IMDb's free seven-table dump has no soundtrack/song-in-film table, despite richer information on its website. Official static IMDb downloads are the intended bulk route, not per-record API scraping.

Finish Open Library pilot; obtain fresh Gutenberg metadata; test how reliably an ebook links to the correct work/edition using IDs and provenance. Then a small TVmaze or bounded Wikidata sample tests series/episode or book/adaptation structure. Downloading more sources alone does not resolve identity matching. No new public ingestion commitments made.

### Authorized downloads — October 21

Implemented `scripts/download_catalogs.py` with `tvmaze` and `imdb` commands. Data lives outside the repo under `~/data/oma/{source}/2026-10-21/`. Both were launched; check each `status.json` and `download.log` for actual completion. Codex sessions: TVmaze 6755, IMDb 83677. These are foreground session jobs, not installed services; keep Codex/WSL running.

Resume from repository:

```
python3 -u scripts/download_catalogs.py tvmaze --output ~/data/oma/tvmaze/2026-10-21
python3 -u scripts/download_catalogs.py imdb --output ~/data/oma/imdb/2026-10-21
```

TVmaze caches each page, requests new pages at one-second intervals plus latency, retries throttling/server/network errors, checks ID ranges/duplicates, and produces combined `shows.jsonl` only after reaching the terminal 404. Fetch is a snapshot across time, not atomic. IMDb pins size/ETag/last-modified before downloading, sends If-Match to prevent resuming across a changed daily file, checks size/gzip CRC/header and records SHA-256. If upstream rotates, a 412 requires a new dated output folder; do not concatenate snapshots. Both commands use exclusive locks. No Django import/publication. Four focused tests passed: cache resume, terminal vs error response, rate-limit retry, truncated gzip rejection.

### More music sources

[Discogs official bulk downloads](https://data.discogs.com/) are the strongest alternative: monthly XML files for releases, master releases, artists and labels, with published checksums. Official directory states CC0 for these dumps. The page was accessible through curl although the browser search tool returned 403. Useful for release variants, tracklists and credits. MusicBrainz remains my preferred initial music foundation for composition/recording relationships; Discogs complements it. No music files downloaded.

[SecondHandSongs](https://secondhandsongs.com/page/API) is a promising targeted source for covers/adaptations. Its [API access](https://secondhandsongs.com/page/API/access) and [terms](https://secondhandsongs.com/page/TermsOfService) require separate consideration; not treating it as an unrestricted free bulk catalog. [ListenBrainz](https://metabrainz.org/datasets) provides listening-history datasets, useful for future discovery/recommendation experiments rather than replacing music identity metadata. AcousticBrainz has historical audio-feature dumps but is discontinued, so it is not the next catalog backbone.

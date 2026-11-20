# Source landscape, terms of use, and acquisition strategy — 2026-11

Planning input for the owner's next source decision. Written 2026-11-04 by
`source-scout`. Complements
[OpenMediaAtlas-Data-Source-Map-v0.1.md](OpenMediaAtlas-Data-Source-Map-v0.1.md)
(2026-09-20), which it corrects where measurement disagrees. It authorises no
ingestion and duplicates no part of the running campaign's slice.

**Verification key.** **VERIFIED** = I fetched the primary page/API on 2026-11-04 and
quote it. **LOCAL** = measured from the repo, `db.sqlite3` (read-only) or campaign
receipts. **INFERRED** = reasoned from evidence I did fetch, but not stated by the
source. **UNVERIFIED** = could not confirm; §6 gives the exact check. No field here
is a licence clearance.

---

## 0. Starting state, re-measured

The brief's numbers were already stale when I read them: the campaign applied its
second slice during this session. Read-only measurement at 2026-11-04T16:35-05:00
(LOCAL):

| Measure | Brief | Measured | Note |
| --- | --- | --- | --- |
| `Source` rows | 6 | 6 | 3 are mock/demo fixtures |
| Import runs / items | 88 / 23,388 | 90 / 23,614 | runs 89–90 added mid-read |
| Source records | 14,075 | 14,075 | Wikidata 8,555, OL 5,500, Wikipedia 20 |
| Proposals | 4,849 / 1,062 pending | 4,849 / 1,062 pending | 3,777 approved, 10 rejected |
| External identifiers | 21,904 | 21,904 | `ol_work` 10,731, `wikidata` 8,384, `imdb` 2,458, `tvmaze` 328 |
| Accepted edges | 4,199 | 4,504 | slice 2 applied 16:27 |
| Wikidata-only works | 3,676 | 3,676 | unchanged, as predicted |
| Public works with no edge | 4,237 | 3,615 | 9,685 works have no edge in total |

Two findings change how the rest of this reads.

**(a) "Accepted edges" overcounts distinct assertions by 16.7%.** 752 ordered pairs
carry *both* `based-on` and `derivative-work` — 1,504 edges over 752 pairs, and no
other duplicate shape exists. Wikidata asserts `P144` and `P4969` for the same two
entities; OMA maps them onto two vocabulary codes, which
`unique_work_relationship` `(from_work, to_work, relationship_type)` permits. So the
graph holds ≈**3,752 distinct assertions**, and "edges per source" should count
ordered pairs, not rows (LOCAL).

**(b) The book work has hit a real ceiling.** The forward `P648` sweep fetched 100 of
3,676 Wikidata-only works: `no_claim` on 3,666, zero links. Gutenberg edition-matching
scanned 56.8M editions for 2 local matches and 0 QIDs (LOCAL,
`ingest-run1-crosswalk-p648.json`, `ingest-run1-report.md`). Any plan that adds
another book corpus "to fix the 3,676" repeats a measured zero.

---

## 1. Source table

Citation keys resolve in §1.5. "Redistribution" means the three separate rights the
Sept map demanded be kept separate: display, local retention, and inclusion in an
open export.

### 1.1 Wikidata — the spine, and the properties that matter

| | |
| --- | --- |
| Role | Seed, identity, cross-media claims, relationship candidates |
| Access | `wbgetentities` (50 IDs/request), Query Service (SPARQL), weekly dumps |
| Licence | **VERIFIED**: "All structured data (i.e. the main, Property, Lexeme, and EntitySchema namespaces) is released into the public domain under Creative Commons Zero"; "Text in other namespaces is copyrighted and available under the Creative Commons Attribution-ShareAlike 4.0 License" [S1] |
| Redistribution | Unrestricted for structured data; CC0 imposes no attribution, so citing Wikidata is provenance practice, not duty. Danger: labels copied from a Wikipedia article, or a Commons image, are not CC0 [S1] |
| Limits | **VERIFIED**: "hard query deadline … 60 seconds"; "One client (user agent + IP) is allowed 60 seconds of processing time each 60 seconds"; "30 error queries per minute"; `429` + `Retry-After` [S3] |
| Cadence | **VERIFIED**: "The dumps are being created on a weekly basis"; JSON recommended, one entity per line [S2]. `latest-all.json.bz2` = **103,565,615,653 bytes** (2026-10-27); `.nt.bz2` = 393,297,902,500 bytes [S4] |
| Coverage | Deep for film/TV/literature, but editor-dependent: `P144` exists for some adaptations and not others, and modelling varies (edition vs work vs series) |
| Verdict | **Usable now** — the only source with no licence friction whatsoever |

Property semantics read live from `wbgetentities` (VERIFIED, [S5]):

| Property | Verified description | OMA consequence |
| --- | --- | --- |
| `P144` | "based on" — "the work(s) or inputs used as the basis for subject item" | Derived → source, one direction. Campaign's main edge producer (1,292 staged proposals, +418 accepted in run 1) |
| `P4969` | "derivative work" — "new work of art … derived from major part of this work" | Asserted on the *source*, so the seed is the `to_work`; `repair_duplicate_identities.py` encodes `DERIVED_ON_TARGET = {"P4969"}`. Mapping both properties is what creates finding (a) |
| `P629` | "version, edition or translation of" | Edition identity, not adaptation. Only 3 staged proposals; mapped to `edition-of` |
| `P2034` | "Project Gutenberg ebook ID" | Read-link identity only; a scan of OL editions for it yielded 2 local matches |
| `P8600` | "TV Maze series ID" | Crosswalk key: 336 entities carried it, 328 linked |
| `P577` | "publication date" — "date or point in time when a work or product was first published or released" | Keep precision; never promote to "original publication", never let `P571` inception pose as publication (rule already implemented in `docs/trustworthy-catalog-discovery.md`) |
| `P648` | "Open Library ID" (work `W`, edition `M`, author `A`) | The book spine; exhausted both directions |
| `P345` `P4947` `P4983` `P724` `P675` `P2969` `P1954` `P434` `P8383` `P10283` | IMDb; TMDB movie; TMDB TV series; Internet Archive; Google Books; Goodreads version; Discogs master; MusicBrainz artist; Goodreads work; OpenAlex | **Already in Wikidata, already CC0** — the cheapest unused identity inventory in the project (§3.1) |

`P1955` is Discogs *label* ID, not release ID. ISFDB identity is also already in
Wikidata (VERIFIED via `list=search`, ns 120): `P1233` author, `P1234` publication,
`P1274` title, `P1235` series/periodical/franchise [S5].

### 1.2 Usable with conditions

**Open Library** [S6][S7][S8] — work/edition/author structure, identifiers,
languages. Access: monthly gzip dumps; API only for spot checks. Licence
**VERIFIED**: "The Internet Archive does not assert any new copyright or other
proprietary rights over any of the material in the Open Library database. There may be
existing rights issues on some contributions and in some jurisdictions" [S7] — no new
rights granted, descriptions and covers explicitly not cleared. No attribution
obligation as a licence term. Cadence **VERIFIED** monthly from the IA search API:
`ol_dump_2026-10-31` (published 2026-11-02) back through `ol_dump_2025-11-30`, one per
month-end [S8]. Scale measured locally: 17.47 GB compressed, 153.78 GB scanned,
170.7M records, 31.07M eligible editions for one 500-work extract in 1,135 s.
Verdict: **usable, conditionally** — work identity only; edition-level rights are
per-record and unresolved.

**Project Gutenberg** [S9][S10] — ebook identity, supplier rights statements,
read-links. Access: official offline catalogs (XML/RDF daily, CSV weekly, MARC,
mirrors), never the website. **VERIFIED**: the site "is intended for human users only.
Any perceived use of automated tools … will result in a temporary or permanent block
of your IP address"; "The catalog data are granted to the public domain" [S9]. Also
**VERIFIED**: "Project Gutenberg metadata does not include the original print source
publication date(s) … we track the Project Gutenberg publication date ('release
date'), but do not include print source information" [S10]. Verdict: **usable but
low-value** — identity and read-links only, never a date source.

**TVmaze** [S11] — TV identity, series/episode structure. Access: public JSON,
`/shows?page=N`, 250/page, terminal 404. **VERIFIED**: "Use of the TVmaze API is
licensed by CC BY-SA. This means the data can freely be used for any purpose, as long
as TVmaze is properly credited as source and your usage complies with the ShareAlike
provision"; "at least 20 calls every 10 seconds per IP"; 429 + backoff; index cached
24 h. Verdict: **usable, conditionally** — ShareAlike is a product decision, not a
footnote, and the licence *version* is unstated (INFERRED 4.0).

**MusicBrainz** [S15][S16] — music identity. Access: PostgreSQL dump restore via
`mbslave`. **VERIFIED**: "Core data … licensed under the CC0"; "Supplementary data …
under the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 license" [S15].
Default 1 req/s API limit is well known but not re-fetched (UNVERIFIED here). Verdict:
**usable with conditions, out of scope for run 1.**

**Discogs** [S17] — release/master identity. **VERIFIED**: "monthly dumps of Discogs
Release, Artist, Label, and Master Release data … made available under the CC0 No
Rights Reserved license." The *API* terms differ and were not fetched (UNVERIFIED).
Verdict: usable with conditions, out of scope.

**Internet Archive** [S19] — reading links, item identity. Access: Item Metadata API
`GET /metadata/{id}` (**VERIFIED** exists [S19]), advanced search, derived dumps.
Items carry heterogeneous rights; the platform clears nothing blanket. `/about/terms.php`
returned 201 bytes → **UNVERIFIED** [S20]. Verdict: usable with conditions; the safe
subset is identity already reachable via `P724`.

**ISFDB** [S18] — SF/fantasy bibliography. Footer states "Creative Commons
Attribution 4.0 International License" (**VERIFIED** from [S18]); whether that covers
the database rather than wiki text is INFERRED. Verdict: usable after a scope check;
identity already reachable via `P1274`.

**Crossref** [S25] — DOI metadata. **VERIFIED**: "No sign-up is required to use the
REST API, and almost none of the metadata is subject to copyright, and you may use it
for any purpose. Some abstracts contained in the metadata may be subject to
copyright." Verdict: usable with conditions; only matters if OMA adds scholarly types.

**Europeana** [S21] — aggregated European heritage objects. Guidelines fetch returned
**403 Cloudflare** → **UNVERIFIED**; the Wikimedia licensing page cites Europeana as a
CC0-metadata example [S1]. Verdict: **needs legal review.**

### 1.3 Not usable, or internal-crosswalk only

| Source | Terms (all VERIFIED quotes) | Consequence |
| --- | --- | --- |
| **TMDB** [S12][S13] | "Our API is free to use for non-commercial purposes as long as you attribute TMDB as the source of the data and/or images"; the API terms "does not permit any commercial use"; you must not use the content "in connection with, or for training, a machine learning or artificial intelligence based Application"; on termination you "must promptly delete or otherwise purge all TMDB Content, including any cached content". Attribution text is prescribed verbatim | Non-commercial, no ML, no durable cache → cannot be a spine, cannot be a permanent cache, cannot feed a model |
| **IMDb** [S14] | "Subsets of IMDb data are available for access to customers for personal and non-commercial use. You can hold local copies of this data, and it is subject to our terms and conditions"; datasets refresh daily from `datasets.imdbws.com` | Non-commercial, no redistribution. The campaign already restricts it correctly (never displayed, never in fixtures or exports); the licensing document itself is UNVERIFIED |
| **Google Books** [S27] | "You may not charge users any fee for the use of your application" without a separate agreement; incorporates Google APIs ToS | No bulk metadata product; per-volume API with display restrictions. Safe artefact is the `P675` value only |
| **BFI** [S22] | "The Site is for your personal and non-commercial use. You may not modify, copy, distribute, transmit, display, revise, perform, …" | No reuse right without a licence; no bulk route observed |
| **AFI Catalog** [S23] | No terms page or API found in a direct read (UNVERIFIED) | "Ask first" |
| **Goodreads** [S24] | `/api` now 302s to a sign-in surface (**VERIFIED** as a status observation); no public API docs reachable unauthenticated. Dec-2020 key discontinuation **UNVERIFIED** | Closed; the circulating Goodreads/UCSD and Kaggle dumps are scrapes of unclear provenance and no lawful substitute |
| **OpenAlex** [S26] | Keyless requests "share one free daily budget ($0.10) with everyone on your network's IP address", free key = $1/day, responses report `cost_usd` (**VERIFIED** live). Dataset licence not on any fetchable page (**UNVERIFIED**) | Free tier too small for bulk, licence unclear, and the record model is scholarly, not creative-work |

### 1.4 Grouping

- **Usable now:** Wikidata.
- **Usable with conditions:** Open Library, TVmaze, Gutenberg (identity only),
  MusicBrainz and Discogs (out of scope this run), Internet Archive (per-item rights),
  Crossref (narrow types), ISFDB (after scope check).
- **Needs legal review:** Europeana, ISFDB scope, Internet Archive, OpenAlex.
- **Not usable:** TMDB, IMDb (except the internal crosswalk already configured),
  Google Books, BFI, AFI, Goodreads.

### 1.5 Citations

[S1] https://www.wikidata.org/wiki/Wikidata:Licensing ·
[S2] https://www.wikidata.org/wiki/Wikidata:Database_download ·
[S3] https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual ·
[S4] https://dumps.wikimedia.org/wikidatawiki/entities/ ·
[S5] `wbgetentities`, https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities ·
[S6] https://openlibrary.org/developers/dumps ·
[S7] https://openlibrary.org/developers/licensing ·
[S8] https://archive.org/details/ol_exports ·
[S9] https://www.gutenberg.org/policy/robot_access ·
[S10] https://www.gutenberg.org/ebooks/offline_catalogs ·
[S11] https://www.tvmaze.com/api ·
[S12] https://www.themoviedb.org/documentation/api/terms-of-use ·
[S13] https://developer.themoviedb.org/docs/faq ·
[S14] https://developer.imdb.com/non-commercial-datasets/ ·
[S15] https://musicbrainz.org/doc/About/Data_License ·
[S16] https://musicbrainz.org/doc/MusicBrainz_Database/Download ·
[S17] https://data.discogs.com/ ·
[S18] https://www.isfdb.org/ ·
[S19] https://archive.org/developers/md-read.html ·
[S20] https://archive.org/about/terms.php ·
[S21] https://www.europeana.eu/en/rights/usage-guidelines-for-metadata ·
[S22] https://www.bfi.org.uk/terms-use ·
[S23] https://aficatalog.afi.com/ ·
[S24] https://www.goodreads.com/api ·
[S25] https://www.crossref.org/documentation/retrieve-metadata/rest-api/ ·
[S26] https://api.openalex.org/works and https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication ·
[S27] https://developers.google.com/books/terms

---

## 2. Honest classification

**Working (code exists, has run, has receipts).** Wikidata ingestion and enrichment
(`importers/wikidata.py`, `run_wikidata_enrichment`, `promote_wikidata_run`): 8,384
QIDs, 4,504 edges, 3,777 approved proposals. Open Library bulk
(`importers/openlibrary_bulk.py`, `run_openlibrary_cloud_pilot`, `extract_openlibrary`,
`ingest_openlibrary_extract`): two complete checksummed extracts, 17.47 GB pinned
snapshot, measured scan rate. Triaging (`triage_proposals.py`) implementing the
green/amber/red rules — `proposal-triage-latest.json` shows 470/926/136 over 1,532
candidates. Guarded apply (`scripts/apply_guard.py` plus the campaign's apply receipts
with matching hashes): backup → integrity → schema hash → pre-state → transaction → recheck →
idempotent rerun, the most trustworthy part of the system. Identity repair
(`repair_duplicate_identities`, `repair_relationship_direction`,
`link_openlibrary_wikidata`). All LOCAL — I read code and receipts, ran nothing.

**Documented but restricted.** TVmaze (docs read and quoted; only the `P8600`
crosswalk has run; the show index was never ingested). Gutenberg (catalog route
documented; a stale 2022 mirror of 68,502 records exists outside Git; the edition scan
yielded 0 QIDs). MusicBrainz and Discogs (terms now verified here; **zero** rows in the
database, no `mbid`/`discogs` identifier scheme). Internet Archive, ISFDB, Crossref,
Europeana (terms partially verified, no code).

**Closed, acquired, historical.** Goodreads (API closed). TMDB (TiVo-owned,
commercial licence, ML prohibited). IMDb (Amazon-owned; datasets non-commercial and
non-redistributable; the website/API path is excluded by its conditions).
AcousticBrainz (discontinued). The 2022 Gutenberg JSON sample (last commit
2022-07-11). The three mock sources and `oma_demo` — fictional fixtures that must
never be counted as coverage; two of them own one accepted edge each, which is why
"edges per source" must exclude them.

**Tested versus read.** Live-tested: `wbgetentities` on the identifier and semantics properties listed in
§1.1 (two batches, 28 IDs); the Wikidata
dump listing; the IA search API for OL dump cadence; the OpenAlex API notice. Pages
read and quoted: Wikidata licensing/dumps/WDQS, OL dumps/licensing, Gutenberg
robot/offline, TVmaze, TMDB terms + FAQ, IMDb datasets, MusicBrainz licence +
download, Discogs, Crossref, Google Books, BFI, ISFDB footer. Failed to fetch:
Europeana (403), Goodreads docs (302), IA terms (201 bytes), OpenAlex licence, AFI
terms. Not performed: any download, any import, any management command, any migration.

---

## 3. Priorities against the Wikidata spine

Ranking rule: expected distinct assertions per unit of cost, where cost includes
licence risk and review labour.

### 3.1 Priority 1 — sweep identifier properties already in Wikidata

Collect every identifier property OMA does not yet store, for the 8,384 QIDs already
cached: `P1274`, `P1954`, `P434`, `P8383`, `P10283`, `P724`, `P675`, plus
`P345`/`P4947`/`P4983` where absent. Today 2,446 works carry an IMDb ID and **every
one already has a Wikidata ID** (LOCAL) — the IMDb column is a derived artefact of the
spine, not independent coverage. Cost: 8,384/50 ≈ **168 `wbgetentities` requests**,
minutes at campaign pacing, no new licence, no dump. This is the only route that
raises expected yield for *every* future source at once, and it is reversible: an
unaccepted identifier is a `SourceRecord` plus an `ImportItem`, nothing more. It also
supplies a denominator the project lacks — how many works have any partner identity
at all.

### 3.2 Priority 2 — finish TVmaze as a bounded, allowlisted slice

The `P8600` crosswalk is done (328 of 336). The remainder is the ~381-page show index
(≈6.4 min at 1 req/s) used to find shows whose Wikidata item lacks `P8600`, matched by
exact IMDb `tconst` only. Ceiling is small and computable: 406 TV works (382 series, 24
programs), 328 already linked → **≲78 works**, minus those with no IMDb ID (LOCAL). Do
**not** fetch episodes or cast: ≈181,236 requests (~50 h) for a node type this run
excludes. Record the CC BY-SA obligation on derived presentation.

### 3.3 Priority 3 — Open Library at edition level, only for works that already have a partner

Identity is exhausted, but OL is the only source with publisher/edition/pagination
structure for the 10,198 works that already carry `ol_work`. Yield is edition rows
(6,578 releases, 7,643 versions), not edges. State plainly in any planning text: the
3,676 Wikidata-only works are **not** a book-import problem; 3,666 have no `P648`, and
title matching is forbidden, so they stay unpartnered by design — the campaign document
already accepts that end state. Cost: ~19 min per 500-work extract measured; a full
refresh of 10,198 works is ~20× that plus the 17.47 GB download. Recommend re-extracting
only works whose `payload_hash` changed, using the `last_modified` field the dumps page
documents [S6].

### 3.4 Priority 4 — ISFDB, after a scope check, starting with identifiers only

`P1274` for SF/fantasy titles; ISFDB is the one source that separates title /
publication / series at the granularity OMA's work–version model needs. Size the
opportunity from the Priority-1 sweep before any download; clear the licence scope
first (footer says CC BY 4.0; database coverage inferred).

### 3.5 Priority 5 — Europeana, legal review only

Metadata reputedly CC0, but per-object rights still gate display, the record model is
object-level, and the guidelines were unfetchable. Future source at best.

### 3.6 What not to acquire

| Tempting | Why not |
| --- | --- |
| Gutenberg full catalog/text | Measured zero (56.8M editions → 2 matches → 0 QIDs) and a date trap [S10]. Keep only `P2034` read-links |
| TMDB | Non-commercial, no ML, purge-on-termination [S12] |
| IMDb beyond the internal crosswalk | Non-commercial, non-redistributable [S14]; the code boundary is already right — keep it |
| Goodreads or scraped Goodreads corpora | Closed API; unclear provenance |
| Music this run | Out of scope, and creators/series are new node types |
| Episode-level TV | ~50 h of requests for an excluded node type |
| Another book corpus | The blocker is upstream claim absence, not corpus shortage |
| AFI / BFI scraping | No reuse grant; BFI forbids copying [S22] |

---

## 4. Reconciliation design

The code is further along than the docs suggest. Order, and where it lives:

1. **Exact identifier** — QID (`importers/wikidata.py`), `ol_work`
   (`link_openlibrary_wikidata.py`, docstring: "This is an identity join only. It
   never matches by title."), `tvmaze`/`imdb` as internal keys.
   `openlibrary_bulk.ingest_record` refuses when an `ol_work` ID "ambiguously maps to
   multiple catalog works".
2. **Structured key** — work+type+year, edition+`P629`, OL edition→work containment.
   `repair_duplicate_identities.py` splits rows carrying two QIDs instead of guessing,
   and derives `DERIVED_ON_TARGET` from the property's assertion side.
3. **Title+creator+year — review only.** The only automated title rule is negative:
   `triage_proposals._same_title` yields amber `title_collision`. The 20 truth-set
   traps are exactly this class (`shared_title_only`, `self_link`,
   `reversed_direction`, `date_order`). There is no fourth step; fuzzy similarity
   appears nowhere and should not until review capacity exists.

**Duplicate detection.** `ExternalIdentifier` is `UniqueConstraint(work, scheme, value)`
— per work, not global, so it will not stop the same QID/OLID landing on two works. I
measured **0** current collisions (LOCAL); the code's conflict checks hold, the schema
does not. A global unique index for definitionally-1:1 schemes is the cheapest
hardening available, but it needs a migration, hence a scoped decision. Edge
duplicates are permitted by design (finding (a)); measure unique ordered pairs in a
view rather than constraining legitimate multi-type pairs. Work duplicates split first,
merge only through the `merge_work` permission.

**Uncertainty classes**, kept orthogonal to publication state: `no_claim` (3,666 on
`P648`), `multi_value` (0 in the TVmaze receipt, 1 in the P648 dry run),
`conflict_owned_elsewhere` (9), `ambiguous_work_identity` (0), import-item `conflicted`
(public record would mutate), and the queue classes amber/red. Two rules to make
explicit: an identifier collision is a review item, never a merge instruction; amber is
**parked, not rejected** — 926 items await a human and bulk approval stays refused.

**Reversible merges.** `WorkRedirect` keeps `old_work` under `PROTECT`, points at
`canonical_work`, records `merged_by`/`merged_at`, forbids self-redirect at constraint
*and* `clean()` level, and is gated by `merge_work`. Undo is a redirect delete plus a
visibility restore because nothing is deleted. But it holds **0 rows** (LOCAL): the
path is unproven for credits, releases, relationships and identifiers.

**Source changes and deprecations.** `SourceRecord.matched_work` is `SET_NULL`, so
records survive a deleted work. Nothing records "the supplier withdrew this" as a
state; a vanished record is only visible by absence from a new dump. Recommend a
`withdrawn_at`/`seen_in_run` marker before the next full OL refresh. Deprecated
statements are excluded rather than copied (`rank == "deprecated"`; 6 skipped per
fetched slice), matching Wikidata semantics.

**Incremental update without churn** — primitives already present and used well:
`payload_hash` short-circuits unchanged records before any Work is touched; `retrieved_at`
is still bumped on unchanged payloads (`importers/openlibrary.py`), preserving "still
valid as of"; `ImportedWorkState` distinguishes "supplier changed it" from "editor
changed it" via the preserve rule (`date_kind` in first_publication/first_release,
`depth == editorial`, contribution revision on the field, divergence from last
accepted values); public works are never mutated (`return "conflicted"`); deterministic
extraction (`lowest SHA-256(seed:work_id)`) with manifest `artifact.sha256` and
committed `ImportItem` rows makes reruns skip finished work, and the cloud pilot refuses
to resume when URLs, checksums, seed or limits changed; `FieldEvidence` (42,349 rows,
`current` flag) plus `provenance.imported_fields` attribute only fields the import
actually wrote. Remaining churn risk: extract selection is stable only per seed string —
a new seed selects different works and looks like a huge import. Pin the seed in the
manifest and compare before alarming.

---

## 5. Method cost/benefit

### 5.1 What the campaign measured

| Method | Evidence | Reading |
| --- | --- | --- |
| Exact identifiers only | +418 `P144`, +9 reverse `P648`, +328 TVmaze, +146 then +161 fetched → 4,504 | The only repeatable non-zero yield |
| Deterministic rules | Amber probe: 1,062 candidates → **0 green**, 926 amber, 136 red | A correct, useful null result |
| Truth set | 60 items, **8 judged** (6 auto, 2 traps), precision 1.0, trap rejection 2/2, coverage 13.3% | Precision not yet established |
| Gutenberg edition route | 56.8M editions → 2 matches → 0 QIDs | Correctly parked dead end |
| Shared-title matching | 20 traps, 2 judged, both rejected; 99 `title_collision` ambers | Correctly refused |

### 5.2 The statistical caveat that should govern the next decision

Precision 1.0 over `precision_n = 6` with zero failures has a 95% Wilson interval of
roughly **[0.61, 1.00]**; even n = 30 with zero failures gives ≈0.89 lower bound. A 99%
gate needs on the order of 300 clean judgments. **The gate cannot be passed at 8 of 60
items**, and scaling ingestion before the owner finishes judging is the largest
methodological risk in the plan — larger than any licence question, because this is the
gate meant to catch everything else.

### 5.3 Where model reasoning may be allowed

1. **Identity or publication decisions — never.** A wrong merge propagates into every
   downstream join and is expensive to unpick (the project has already spent
   `repair_duplicate_identities`, `repair_relationship_direction` and
   `duplicate-identity-repair-20261029.json` on this damage class). The traps are
   near-misses a fluent model would happily confirm: *Macbeth* 1909 vs 1922, *Anna
   Karenina* film vs ballet, *Alice in Wonderland* 1933 vs 1951. Model output touching
   these is a recommendation-with-citation, never an acceptance.
2. **Ordering and explaining the amber queue — yes, offline.** The 926 split by the
   rules' own reasons: *evidence-missing* (`generic_type` 816, `no_sitelink` 342,
   `no_year` 339, `date_unverified` 339, overlapping) where a model can summarise both
   records and draft accept/reject with the statement ID — the cheapest real labour
   saving available; and *contradiction* (`year_inversion` 135, `title_collision` 99,
   `year_out_of_range` 5, `duplicate_pending` 10) where the data disagrees and a model
   must not adjudicate, at most presenting the conflicting dates side by side.
3. **Vocabulary normalisation — yes, with review.** `generic_type` on 816 proposals is a
   classification task over the existing closed 15-row `WorkType` vocabulary. The
   failure is cosmetic and reversible, unlike an identity merge.

### 5.4 Licence limits on model use

TMDB content may not be used "in connection with, or for training, a machine learning
or artificial intelligence based Application" [S12] — an absolute bar, and another
reason TMDB stays out. IMDb datasets are personal/non-commercial [S14]; feeding them to
a hosted model is not obviously permitted, so keep that crosswalk deterministic.
Wikidata is CC0 [S1] and Open Library asserts no new rights [S7]: those two payload sets
are where model-assisted review is clearly permissible — and they are 100% of the
current corpus.

### 5.5 Recommended policy

> Automated acceptance stays limited to exact identifiers plus allowlisted property and
> relation type, with the green rules as they stand. Model reasoning may be used offline
> to summarise and rank the amber queue, to draft a recommendation-with-citation for a
> human reviewer, and to propose vocabulary normalisation for generic types. It must
> never write an accepted relationship, identifier, merge, date or visibility change,
> and never run on TMDB or IMDb payloads. Every model output is an `ImportItem` message
> or a review note, not a `WorkRelationship` row.

---

## 6. Unverified list and exact checks

| # | Unknown | Why it matters | Check |
| --- | --- | --- | --- |
| 1 | Europeana metadata is CC0 | "Review" vs "usable" | Open [S21] in a browser (403 Cloudflare from this VM), or read the `rights` field from the Europeana API, or ask their API support |
| 2 | ISFDB CC BY 4.0 covers the database, not just wiki text | Attribution/SA scope | [S18] wiki `ISFDB:Copyrights` requires login; email the moderators |
| 3 | Goodreads key discontinuation (Dec 2020) | Confirms "closed" vs "undocumented" | Goodreads Help article "Does Goodreads support an API?" (empty to curl) or Goodreads support |
| 4 | Internet Archive platform terms | Governs MDAPI use | Re-fetch [S20] in a browser, then read per-item `rights`/`licenseurl` before display |
| 5 | IMDb "Non-Commercial Licensing" text | The page only summarises it | Follow the link from [S14] |
| 6 | OpenAlex dataset licence | Whether `P10283` may be stored | Browser on the docs site (JS app) or OpenAlex support |
| 7 | MusicBrainz 1 req/s API limit | Only when music enters scope | `musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting` |
| 8 | OL dumps carry `last_modified` per record | Makes monthly refresh incremental | `zcat .../ol_dump_works_2026-09-30.txt.gz \| head -1` and inspect the 5th tab field |
| 9 | AFI Catalog terms | AFI stays "ask first" | No terms link on [S23]; ask AFI |
| 10 | The 8 `qid_unowned` TVmaze entities | Completes the crosswalk | Re-run the crosswalk dry-run, inspect `qid_unowned` |
| 11 | Whether the 10 rejects conceal a false reject | Trust in the reject path | **Checked**: all 10 have 1–2 already-accepted edges between the same endpoints → all are duplicate suppressions, no false rejects found |
| 12 | Truth-set precision at scale | §5.2 | Owner judges the remaining 52 items; re-run `score_truth_set` |

A reader should not conclude from this document that any source is cleared for display
(none is), or that the precision gate has been met (8 of 60 items is a smoke test).

## 7. The decision this asks for

Two coherent postures, and §3.1 is prerequisite to the second:

- **Deepen the spine** (§3.1 sweep + §3.2 bounded TVmaze): cheap, no new licence,
  measurable, and it makes every future source cheaper to adopt. It will not reduce the
  3,615 edge-less public works — those are unpartnered by construction.
- **Broaden sources** (§3.4 ISFDB, §3.5 Europeana): needs a licence decision and a legal
  check first, with unknown yield until the identifier sweep is done.

# OMA decision register

Opened 2026-11-04. Canonical list of open and settled product/architecture decisions for
Open Media Atlas. Replaces the scattered "Decisions for Justin to review" sections in the
v0.1 planning drafts; those drafts remain as historical context and are not rewritten.

**How to use this document**

- One row per decision. Status is A–E (defined below). Only Justin closes **D** items.
- Evidence is cited as `file:line`, a command, or a measured value with a timestamp.
  Values drift while the ingestion campaign is running; every number carries its
  observation time.
- This is a register, not a backlog. Work items go to Beads (`factory-8ab` campaign,
  and project tasks); this file records *what was decided and why*, not who is doing it.
- Proposals are reversible unless marked otherwise. "Irreversible" means it is costly to
  undo after publication (licence grant, identifier contract, merged identities).

**Status legend**

| Status | Meaning | Who decides |
| --- | --- | --- |
| A | Proposed reversible default. Adopt unless someone objects. | Lead proposes, Justin may veto |
| B | Experiment required. Alternatives and measurements are named. | Lead runs, Justin sees results |
| C | Independent critique or audit needed before deciding. | External/independent reviewer |
| D | Justin's decision required: values, major scope, irreversible commitment, spending. | Justin |
| E | Defer or exclude, with reason and a revisit condition. | Lead proposes, Justin may veto |

---

## D — decisions only Justin can make

### DR-01 — Declared domain boundary for "reference-grade" coverage

**Question.** Which media does OMA claim to answer *exceptionally well* at launch, and
which are accepted but explicitly second-class?

**Current position (implicit, not decided).** The product name and README claim
"cross-media"; the model has types for novel, film, play, opera, musical, television
series/program, video game, album, song, ballet, book, literary work. The running ingestion
campaign scopes *books, film, TV and stage* through Wikidata/Open Library/TVmaze and
**excludes music sources and creator/series nodes** (`docs/ingest-campaign-run1.md`).
The launch collection is 50 editorial rows — **47 visible works** once 3 `is_demo` fixtures
excluded by `public_works()` are removed — and their 1,281 one-hop neighbours, of which 666
are films (`docs/planning/oma-strategy-2026-11.md` §3.2).

**Why it is a D.** This is a scope commitment that determines what "the reference" means,
what sources are bought into, and what readers are promised. It is not a routine
implementation detail.

**Recommendation.** Declare the launch domain as **narrative and dramatic works with
verifiable adaptation chains**: novels/books, plays, films, television series, opera,
musical theatre. Video games are in-scope as *works* when they have an adaptation edge
(they already do: 18 in the launch neighbourhood) but not as a coverage target. Music
(albums/songs) is **accepted as a linked type** but out of acquisition scope until the
crosswalk ceiling is reached. Anime/manga, radio, podcasts and comics are **boundary
subjects to link, not absorb** until a source with reliable work-level identity is
adopted.

**Consequence of the recommendation.** Fewer sources, a sharper promise, and a clean
answer to "why isn't X here": X is out of declared scope, not missing. The cost is that
"cross-media" in the README must be qualified.

**Revisit condition.** When ≥60% of declared-domain works have an adaptation edge and a
music source passes the same identity/precision gate (§ source landscape).

### DR-02 — Is agent contribution a first-class write path, and with what authority?

**Question.** May external agents submit catalog data directly (with review), and may any
class of agent submission be auto-accepted?

**Current position.** The v0.1 page map says "Start with a documented read API... write
APIs and agent credentials are later scope" (`docs/planning/OpenMediaAtlas-Page-and-Action-Map-v0.1.md` §8).
The permissions matrix says no action gains power merely by arriving through an API.
The current code has member-authored `ContributionProposal` rows (staff-reviewed), staff
import proposals, and **no agent authentication, no API, no idempotency, no batch
submission** (verified: 0 ContributionProposal rows, no token model, `catalog/urls.py`).

**Why it is a D.** It inverts a stated product decision, defines who is accountable for
the catalog, and creates an abuse surface. It is also the central "Galaxy" premise.

**Recommendation (staged, not a blank cheque).**
0. **Do not build the agent pilot yet.** The independent critique's finding stands: there is
   no account that can authenticate (0 `EmailVerification` rows), no identified partner, and
   the review queue is already the bottleneck. Build the read surface first; re-open writes
   only after E1 (review throughput) and E2 (truth-set expansion) are measured.
1. **Then:** agent *read* access and agent *submission of proposals* through a scoped token,
   with the same review gate as members. No auto-acceptance.
2. **After the truth-set gate is ≥40 judged items at ≥99% precision:** allow auto-accept
   for one narrow class only — *identity crosswalks with an exact external identifier on
   both sides and no conflicting identifier* — attributed to the agent identity.
3. **Never (without a new D):** auto-accept relationships, dates, credits, or rights
   statements from an agent. Those change what readers believe.

**Consequence.** Agents become real contributors without becoming authorities. The
catalog's trust story stays "human-accountable review plus exact identifiers", which is
weaker marketing than "agents maintain it" and stronger as a reference.

**Revisit condition.** After 90 days of the pilot, with measured review load and
false-accept rate. If review load is the bottleneck, the answer is better machine
validation, not weaker review.

### DR-03 — Public data licence and export commitment

**Question.** Under what licence is OMA's *own* catalog released, and what may be
exported in bulk?

**Current position.** No licence file, no export endpoint, no ODbL/CC0 statement. Source
terms differ materially: Wikidata CC0; Open Library dumps with no new proprietary rights
asserted but upstream rights retained; TVmaze CC BY-SA with attribution; IMDb
non-commercial and internal-only; Gutenberg rights statements are per-ebook and
US-centric. `docs/planning/OpenMediaAtlas-Data-Source-Map-v0.1.md` §5 already proposes a
per-source "source-use policy" table; it is not implemented.

**Why it is a D.** A licence grant is effectively irreversible once downstream users rely
on it, and it constrains which sources can ever enter the same export.

**Recommendation.** Adopt **CC0 for OMA-authored factual statements** (identifiers,
relationships, dates, provenance records) and **CC BY-SA 4.0 for the compiled database**
as the share-alike umbrella, with a documented exclusion list for sources that cannot be
redistributed (IMDb; any future TMDB imagery). Do not promise an open export until the
per-source policy table exists and a dry-run export has been reviewed.

**Consequence.** CC BY-SA on the compilation is compatible with TVmaze attribution and
does not claim rights over underlying works or cover images. CC0 on statements keeps the
API usable by downstream software without a copyleft surprise.

**Revisit condition.** Before the first public bulk export; and if any paid offering is
proposed (DR-09).

### DR-04 — Launch definition: canon-first, or coverage-first?

**Question.** Is the public launch "50 works done exceptionally well" or "the whole
imported catalog"?

**Current position.** All 7,452 public works are already public; 6,195 are browsable;
50 are `editorial` depth; 53% carry at least one accepted edge; only 497 have any release;
descriptions are a median of 28 characters. The homepage features 20 works, all from the
editorial slice.

**Why it is a D.** It is a values trade-off between depth and breadth, and it determines
what "launch" means to a reader who lands on a thin record.

**Recommendation.** Launch the *product* on the adaptation canon (50 source works + their
1,281 neighbours), while leaving the longer tail public but explicitly labelled (already
partly implemented via `depth` and "index record"). Do not hide the tail; stop featuring
it. Publish a "what is well-covered" page generated from the same metrics.

**Consequence.** Readers see a coherent, defensible collection; the tail stays honest.
The risk is that the canon looks like an English-language literary curriculum — mitigate
with the non-anglophone spines actually present (Verne, Dumas, Cervantes, Hugo) and the
stage/opera entries. Tolstoy is *not* in the canon (Anna Karenina is `index` depth); do not
claim otherwise.

**Revisit condition.** When ≥70% of the canon's one-hop neighbours have a creator, a date
and a specific type, extend the featured set.

### DR-30 — Content policy for derivative works with adult or sensitive content

**Question.** Is a factual record of an adult film that adapts a canonical work in scope, and
does it inherit any gating?

**Current position.** Work 6121 (*Alice in Pornoland*, 1993) is a public `film` with an
accepted adaptation edge to *Alice's Adventures in Wonderland* (6012). No policy exists;
the record is factual, text-only, and currently unproblematic.

**Why it is a D.** It is a values and audience decision, not an engineering one. Choosing
"exclude" means deciding what a work *is* from its content, which conflicts with the
catalog's factual stance; choosing "include" commits to a moderation policy for images and
excerpts later.

**Recommendation.** Include factual records without content gating; never host explicit
imagery or excerpts; add a single content note only if a surface (image, quote) would carry
it. Publish the rule so it is predictable.

**Revisit condition.** First image ingestion from a source that carries adult covers, or
first complaint.

### DR-05 — Operating model and spending ceiling

**Question.** What is OMA allowed to spend per month, and does any paid offering exist?

**Current position.** Render blueprint: one Starter web service + Basic-256mb Postgres =
**US$13/month** before tax (`README.md`, committed `render.yaml`). No payment taken, no
sponsorship, no grant. Local corpus is 17 GB (`data/`), deliberately outside Git. The
serving database is 382 MB, of which **319.6 MB is cached supplier payload**
(`catalog_sourcerecord`), i.e. 84% of storage is research material, not public data.

**Why it is a D.** Spending and any commercial offering are Justin's call. So is the
tension between "open" and "paid".

**Recommendation.** Keep the ceiling at **≤US$50/month** for hosting/storage through the
launch quarter; no paid tier, no advertising, no data sale. Accept donations/sponsorship
only with a published independence policy (no editorial influence, no exclusive data).
If a paid offering is ever considered, the defensible one is **hosted/private instances
or SLA support for the API**, never access to the public data.

**Consequence.** The project stays cheap and independent; growth is bounded by reviewer
time, not by cash. The archive of raw payloads must stay off the serving path (strategy §9.1), or storage
cost grows with research, not with readers.

**Revisit condition.** If monthly active API consumers exceed ~1,000 or the serving DB
exceeds 2 GB.

---

## C — independent critique or audit required

### DR-06 — Identity and merge durability

**Evidence.** `WorkRedirect` is the documented merge mechanism ("a durable pointer from a
merged work record to its canonical record", `catalog/models.py:127`) and the page map
promises merge redirects and preserved links. **The live catalog contains zero
`WorkRedirect` rows.** Work IDs 1–1000 and 14865–14878 are absent (`sqlite_sequence` max
14,892 vs 13,878 rows); the 1,000 gap is the retired demo fixture set, the trailing 14 are
not explained in any commit message or receipt. `PRAGMA foreign_key_check` is clean and
`quick_check` returns `ok` (2026-11-04 21:33).

**Why C.** I can state the facts but cannot certify that no public link or list entry was
lost, nor that the merge path works under load. This needs an independent reconstruction
from receipts and git history, not a model opinion.

**Ask.** Audit the 14 unexplained deletions, exercise `WorkRedirect` end to end on a
copy, and confirm that a merge preserves `MediaListEntry`, proposals, access links and
incoming relationships.

### DR-07 — Does the adaptation graph mean what the product says it means?

**Evidence.** The launch thesis is "follow the adaptations". The graph is built from
Wikidata `P144` mapped to **two parallel edge types** (`based-on` and `derivative-work`):
752 `(from,to)` pairs carry both (measured when the table held 4,504 rows: 1,504 edges
describing 752 assertions, ~33% of the graph at that moment). The reader-facing consequence is visible: work 6523 (*Les
Trois Mousquetaires*) has 176 raw edges → 93 distinct related works, **all** filed under
"Other direct connections", **none** under "Adaptations"; each row displays "Based On"
*and* "Derivative Work" for the same relationship. `/discover/?relationship=has_adaptations`
returns **0 results** while 3,971 public works have an accepted edge, because the filter
requires `relationship_type.category == "derivation"` and only 2 edges carry that category
(`catalog/views.py:135-142`, `catalog/connections.py:108-110`).

**Why C.** The fix is cheap, but the *interpretation* is not: whether `P144` means
"adaptation", "derivative work", "translation", "sequel" or "any reuse" is a knowledge
question with conflicting source practice. A model should not decide it by voting.

**Two contributing causes, both code, both cheap.** `resolve_wikidata_relationships.py`
creates every relationship type with `category="reference"`, overriding the seeded
`derivation` category — so the broken filter is partly a one-line decision, not only a
knowledge question. And `ImportRelationshipProposal.approve()` (`models.py:631`) hardcodes
the P144 scope note for all properties, so the 2,268 wrong notes are re-created on the next
approval. Separately, ~2,625 edges (≈53%) carry `evidence.entity_id`/`source_url` naming the
*target* while the `statement_id` belongs to the *seed*: the "supporting statement" link
opens a page that does not contain the statement.

**Ask.** Independent review of 50 sampled `based-on`/`derivative-work` assertions against
their Wikidata statements, classifying: true adaptation / same-work translation / sequel
or series / tribute or inspiration / wrong direction / wrong pair. Until then, no page should
say "adaptation" on the strength of the family map.

### DR-08 — Precision gate statistical power

**Evidence.** The truth set is 60 blind items; **8 judged** (13.3% coverage), precision
1.0 over 6 auto-accepted items, trap rejection 2/2
(`run1-score.json`, 2026-11-04). The campaign calls precision 1.0; at n=6, the 95%
confidence interval for 0 false positives is roughly 0–39% false-positive rate. The gate
cannot distinguish an excellent rule from a mediocre one.

**Why C.** The launch and any agent auto-acceptance inherit this number. An independent
statistician/engineer should confirm the sampling design (is the 60-item set
representative of the *production* edge distribution?) before the gate is used to justify
scale.

**Provenance caveat.** The score/report artefacts (`run1-score.json`,
`ingest-run1-report.md`, crosswalk files) and the commands that produce them exist only in
the campaign's isolated workspace (`~/factory/runs/20261104-100518-16895e4b/workspace`), not
in this repository. The gate cannot currently be re-run from `main`; promote the artefacts
and commands before treating the number as a project asset.

**Ask.** Power calculation and sampling review; recommendation on minimum judged n for a
≤1% false-accept claim.

---

## B — experiments required

Each experiment names alternatives, a measurement, and a stopping rule.

### DR-09 — Relationship vocabulary and duplicate claims (revised after critique)

**Alternatives.** (a) Keep both types, dedupe at display with a code-level family map;
(b) add a `claim_family` column and migrate (the first draft's plan); (c) replace the
vocabulary with a small closed set.

**What changed.** The first draft made (b) the first work package and set an acceptance test
of ">1,000 results". The independent critique showed the test is impossible — the measured
ceiling with a correct family filter is **~430** browsable works (528 without endpoint
visibility filtering) — and that (b) would need a migration on a database the campaign is
actively writing (~17 edges/min) for a reader-visible result identical to (a). It also noted
the two causes are code: the resolver forces `category="reference"`, and `approve()`
hardcodes the P144 note.

**Measurement.** Family-filter result count (expect ~430, not >1,000); one label per row on
6523 with 91 adaptation works + 1 sequel + 1 series; duplicate pair count still visible in
diagnostics but absent from public totals; every evidence link opens a page containing the
statement; 50-edge correctness sample before the word "adaptation" is used.

**Stopping rule.** If (a) does not improve the 50-edge sample or the reader test, stop
deduping and fix only display.

**Recommendation.** (a) now — code-only, no migration; (c) only after the 50-edge audit says
what the families mean. Defer (b) indefinitely; the column buys nothing the constant does
not.

### DR-10 — Truth-set expansion to 60 and ongoing sampling

**Alternatives.** Judge all 60 now (≈75 minutes at the observed ~1.25 min/item), or judge
40 now and 20 after the vocabulary fix.

**Measurement.** Judged count, agreement, trap escapes, reviewer minutes per item.

**Stopping rule.** Stop judging when the 95% upper bound on false-accept is <1% for the
class being auto-accepted.

### DR-11 — Agent contribution pilot

**Alternatives.** (a) one partner agent on edition dates for 50 works; (b) three agents on
three task types (dates, translations, identifiers); (c) no pilot, build the API first.

**Measurement.** accepted / rejected / clarification-needed rates; reviewer minutes per
submission; duplicate or conflicting submissions per 100; abuse incidents; share of
submissions that survive a second reviewer.

**Stopping rule.** If reviewer minutes per accepted submission exceed ~3, the contribution
model does not scale regardless of agent quality — redesign the task, not the review.

### DR-12 — Search and discovery benchmark

**Alternatives.** Improve ranking heuristics, add fielded search (creator/year/type),
or keep title search only.

**Measurement.** 12 reference questions with known correct answers; success@5 and
time-to-answer for a human; zero-result rate for plausible queries.

**Starting point.** Today `discover` supports title/alias match, creator substring, year
range, type and a broken relationship filter (`catalog/views.py:116-190`). "Find a 1970s
film adaptation of a Shakespeare play" is not answerable.

### DR-13 — Two-tier storage: serving DB vs research archive

**Alternatives.** (a) keep everything in one SQLite/Postgres; (b) move `SourceRecord.raw_payload`
to compressed files/object storage and keep a manifest in the DB; (c) prune payloads older
than N months.

**Measurement.** Serving DB size after separation (expected ~35–60 MB), backup/restore
time, and the ability to re-run an import without network.

**Why.** 319.6 MB of 382 MB is cached payload. Hosting and backup cost track research
volume, not reader volume — the wrong incentive for a public reference.

### DR-14 — Public conflict disclosure

**Alternatives.** (a) disclose competing date/type claims inline ("sources disagree");
(b) keep only the selected value (current); (c) disclose only after review.

**Measurement.** Reader comprehension (5-person test on 3 records), correction-submission
quality, support questions.

**Evidence.** The data already contains competing claims — 200 works carry an
`assertions`+`disagreements` structure; **no current code reads it and no template shows
it** (`grep -r disagreements` returns only data). Work 6121 has three `P577` values
(1993, 1993-11-01, 1998) and the public page states `SOURCE RELEASE DATE: 1993` with no hint
of the others, while a *title* alternative is disclosed.

---

### DR-33 — Is the identity ceiling real? (Wikidata identifier sweep)

**Alternatives.** (a) Accept "crosswalk is exhausted" and move on; (b) mine the identifier
properties already sitting on cached Wikidata entities; (c) acquire a new corpus.

**Evidence.** The campaign exhausted `P648` and the OL-edition→Gutenberg route, then
concluded the local crosswalk ceiling was reached. But only a few Wikidata identifier
properties have ever been read. For the 8,384 cached QIDs, `P1274`, `P1954`, `P434`,
`P8383`, `P10283`, `P724`, `P675` and missing `P345`/`P4947`/`P4983` are ≈**168
`wbgetentities` calls** under CC0, no dump, no new licence. Also: all 2,446 IMDb IDs sit on
works that already carry a Wikidata ID, so that column is derived, not independent coverage.

**Measurement.** New distinct identifiers per 100 works; crosswalked works before/after;
additional edges reachable from newly linked identifiers.

**Stopping rule.** If the sweep adds <50 distinct identifiers across 8,384 works, the ceiling
is real and further identity work should stop.

**Recommendation.** (b) next slice, before any new corpus.

### DR-34 — Contribution primitives: replace a field, or add a claim?

**Alternatives.** (a) Keep field replacement; (b) add `add_claim` as the primary primitive
with review foregrounding one value; (c) add operation types (`add_version`, `add_release`,
`add_credit`, `add_identifier`, `merge_identity`) on top of the existing proposal table.

**Evidence.** The highest-value missing data is editions, translations, credits and identity
links — none of which `ContributionProposal` can express (it can change title, description,
date text, type, and three relationship fields). Meanwhile competing claims (three `P577`
values on 6121) cannot be *added*, only overwritten. An agent API built on the current
primitives is a typo service.

**Measurement.** Pilot one operation (`add_release` from cached OL payloads) on 20 canon
works: accepted rate, reviewer minutes, duplicate rate, and whether the edition changes the
answer to a reference question.

**Recommendation.** (c) with (b) as the underlying model: operations are additive claims;
review decides foregrounding. Gate the agent API on at least one child-record operation
working end to end.

---

### DR-37 — Separate the research database from the served corpus

**Alternatives.** (a) Keep one database; (b) nightly/build-time export of the public corpus to
a serving DB or static snapshot; (c) serve read-replica of the same DB.

**Evidence.** The ingestion campaign writes the same `db.sqlite3` the app serves: 189 edges
arrived in 11 minutes during this pass (~17/min), and one run has been `running` with zero
items since 2026-10-29. R1–R9 certify a moving object, and P0's original migration would have
raced the writer. 319.6–322.6 MB of the 382 MB database is research payload the app never
needs.

**Measurement.** Served counts stable for a week while the research DB changes; restore time;
serving DB size (ESTIMATE 35–60 MB after separation).

**Recommendation.** (b): a build/export step produces the served corpus (and the public JSONL
snapshot from one artefact), while ingestion writes only the research DB. This is also the
cheapest path to reliable launch certification and to a static fallback if funding stops.

### DR-38 — Every connection list must declare its completeness

**Alternatives.** (a) Say nothing (current); (b) show "N of an unknown total" only when the
source gives a total; (c) a plain, always-visible provenance line: "built from N source
statements, last refreshed <date>; this list may be incomplete".

**Evidence.** The canon was built by capping at the reviewed top four adaptations per source
work (`CURRENT.md:110`) and then bulk-approving 475 amber proposals. No page says so. The
product's promise is "follow a work's adaptations"; a sample presented as complete is the
kind of error a reference cannot make.

**Measurement.** Five-reader comprehension test on three work pages; comparison of stored
edges against the source's own count for three canon works.

**Recommendation.** (c) now, cheaply, on every connection list.

### DR-39 — Statement links must resolve to the statement

**Alternatives.** (a) Fix at write time + backfill old rows; (b) leave the link and label it
"entity" rather than "statement"; (c) hide the link until fixed.

**Evidence.** For non-P144 properties, `evidence.entity_id`/`source_url` name the target
while `statement_id` belongs to the seed: ~2,625 rows (≈53% of edges) link to a page that does
not contain the cited statement. Journey 2 ("verify → source statement") fails for half the
graph, and P2 would build conflict disclosure on top of it.

**Measurement.** Automated check: for every edge, does the linked page/entity match the
`statement_id` prefix? Target 100%.

**Recommendation.** (a), before P2 and before any page says "Adapted from".

### DR-40 — Work-level language, because 14% of the canon neighbourhood cannot state it

**Alternatives.** (a) Leave language only on `Version`; (b) add `Work.language` (BCP-47,
nullable, sourced); (c) derive display language from title script (rejected: inference).

**Evidence.** 181 of 1,283 canon neighbours have non-ASCII (mostly non-English) titles; 46 of
50 canon rows have no version, so `Version.language` cannot reach them. The reader cannot
tell a Swedish *En midsommarnattsdröm* from an English one.

**Recommendation.** (b) after DR-37, with a source and a "language as recorded by
<source>" display rule.

## A — proposed reversible defaults

| ID | Default | Evidence / rationale | Calibration |
| --- | --- | --- | --- |
| DR-15 | Every public record shows: specific type or "Unclassified", a date with its recorded meaning, and at least one creator or an explicit "no creator recorded". | 324 public works have no credit, 115 have no year; the page currently renders absence inconsistently. | Recheck monthly; target ≥90% of the canon neighbourhood. |
| DR-16 | Versions stay embedded unless a version is itself adapted (then it may get a page). No new version pages at launch. | Only 2 works have >1 version; 1 translation exists in the whole catalog; the page map already chose embedded-by-default. | Revisit when translations exceed 500 works. |
| DR-17 | Read API v0 is public, unauthenticated, cursor-paginated, `GET`-only, and versioned `/api/v0/`. Writes arrive only with the agent pilot. | Page map §8 already scopes read API first; no write surface exists today. | Evidence: a broken agent client should fail loudly with a documented error code. |
| DR-18 | Agent tokens are scoped (`read`, `propose:identity`, `propose:relationship`, `propose:date`), rate-limited, revocable, and always attributed in provenance. | Mirrors the permissions matrix's "no power through the API" rule. | Start: 60 reads/min, 30 proposals/hour, 500 items/batch; raise per DR-11 measurements. |
| DR-19 | Rejections must carry a reason code and a note before the importer is run at scale. | `ImportRelationshipProposal` has reviewer + timestamp but **no reason field** (`catalog/models.py:602-640`); `ContributionProposal` has `reviewer_explanation`. All 10 current rejections were independently checked and are duplicate suppressions, not false rejects — but that is recoverable only by hand, and will not survive volume. | Add field + backfill unknown reasons as "not recorded". |
| DR-31 | Stop counting generated placeholder versions as editions. | 7,641 works have exactly one generated version; 5,500 are `kind="unresolved"` labelled like an original. Public/API surfaces must omit or mark them `synthetic: true`, or the catalog claims an edition layer it does not have. | Recheck when real versions exceed 1,000. |
| DR-32 | Rename the AI-contributor concept to `principal`/`operator` before any API ships. | `catalog.Agent` already means *creator* (13,124 rows). Two meanings of "agent" in one codebase and one API is a permanent ambiguity for humans and models alike. | Mechanical rename; no data migration. |
| DR-35 | TVmaze-derived facts carry CC BY-SA attribution and share-alike on the derived presentation. | 328 works carry TVmaze identity; the licence obligation is a product constraint, not a footnote. Attribution present today only as a source row. | Legal check before any bulk export including TVmaze fields. |
| DR-41 | Log search and page-view demand from day one, with no personal data. | The eight reference questions were ranked by supply; no query log exists, so "what to build next" is inferred from tables. Two weeks of `/discover/?q=` logging costs nothing. | Review after 2 weeks; if no signal, stop. |
| DR-20 | `depth` (index / editorial / ambient) is the only public prominence signal; no "quality score". | `ranking.py` deliberately separates richness from publication; keep it. | If a second signal is added, it must be explainable in one sentence on the page. |
| DR-21 | Public pages link out to source statements (Wikidata QID, OL work/edition) on every claim. | Already implemented for title/date evidence; extend to relationships (currently only via the evidence disclosure). | Check 10 random pages. |
| DR-22 | Any new entity type must arrive with (a) a source that supplies identity, (b) a query that needs it, (c) a display rule, and (d) a migration story. No speculative tables. | `schema.dbml` has 37 tables vs ~20 implemented; 30 of 56 relationship types are unused. | Apply to the next 5 proposals; log rejections in this register. |

---

## E — defer or exclude

| ID | Item | Reason | Revisit condition |
| --- | --- | --- | --- |
| DR-23 | Music acquisition (MusicBrainz, Discogs) | Campaign scope excludes it; the identity model for composition vs recording vs release is not built (no song/album nodes beyond 7+7 works); identity work inside Wikidata is unfinished. | Wikidata identifier sweep complete (DR-33) and a bounded music slice passes the identity gate. |
| DR-36 | TMDB as a source (any role) | Free tier is non-commercial, forbids use "for training" an ML/AI application, and requires purging cached content on termination. It cannot be spine, cache, or model input, and so cannot be used by this project's method. | A commercial agreement or a different terms version is reviewed; do not revisit on convenience. |
| DR-24 | Creator and series as first-class graph nodes | Deliberately excluded from run 1. Agents/credits exist as records but there are no creator pages, no inverse credit browsing, no series containers. | When ≥70% of canon neighbours carry a creator (currently 1,085/1,281). |
| DR-25 | Comments, reviews, discussions, recommendations | Deferred by milestone scope; no moderation capacity; they do not serve reference questions. | Only with a funded moderation plan. |
| DR-26 | Streaming availability / "where to watch" claims | Access links exist (32) but availability is not verifiable at scale and creates a freshness liability. Keep links as *access descriptions*, never availability promises. | A source with licensed, refreshed availability data is adopted. |
| DR-27 | Paid licensing or rights transactions | Out of scope; conflates descriptive rights with permissions (strategy §4, item 4). | Never, unless legally advised and separately scoped. |
| DR-28 | Full DBML v0.1 schema (37 tables) | Premature: `catalog_records` supertype, `record_revisions`, `citations`, `rights_claims`, `discussion_threads` have no product demand and no data. | Adopt tables only when a milestone names the query they serve. |
| DR-29 | Image ingestion at scale | Cover rights are not cleared by dataset licence; 22 images currently referenced with per-image licence fields. | A source with explicit per-image reuse terms and an attribution UI. |

---

## Contradictions to resolve (recorded, not silently fixed)

| # | Contradiction | Where | Resolution |
| --- | --- | --- | --- |
| 1 | README says bulk ingestion is "deliberately deferred"; a bulk ingestion campaign is authorised and running. | `README.md` "Milestone scope" vs `docs/ingest-campaign-run1.md` | Documentation fix: README points to the campaign doc and names its scope. Applied in this pass. |
| 2 | Page map: "write APIs and agent credentials are later scope"; current ambition: agents are primary contributors. | `OpenMediaAtlas-Page-and-Action-Map-v0.1.md` §8 vs this brief | DR-02; staged, not reversed. |
| 3 | DBML: 37 tables incl. revisions/citations/rights claims; implementation: ~20 models, 0 revision rows, 0 terms. | `docs/planning/schema.dbml` vs live DB | DR-28; DBML demoted from blueprint to vocabulary. |
| 4 | "Merge keeps incoming links working" (page map acceptance) vs zero `WorkRedirect` rows and 14 unexplained ID gaps. | page map §10 vs live DB | DR-06 audit. |
| 5 | Immersive relationship vocabulary (56 types) vs 2 types carrying 80% of edges and 30 types never used. | `catalog/management/commands/seed_relationship_types.py` vs live DB | DR-09. |
| 6 | "Versions stay embedded by default" is presented as a live policy, but the faithful version model is exercised by exactly one demo work (2 versions, 1 translation). | `AGENTS.md` conventions vs live DB | DR-16; the policy is fine, the data is absent. Advertise the capability only when real translations exist. |
| 7 | "No bulk approval of amber or red" and "ingest never changes visibility/depth" | `CURRENT.md:773-786` records a decided bulk approval of **475 amber** proposals and publication of **351 draft endpoints** by one-off shell | Record it in the register as a past exception with a reason; re-affirm or replace the rule explicitly. |
| 8 | Visibility and vocabulary rules are enforced in code (`public_works()` drops demo rows; resolver forces `category="reference"`) but appear nowhere as decisions | `views.py:46-54`, `resolve_wikidata_relationships.py:250-256` | Add both to the register; a rule enforced by code is still a decision. |
| 9 | Readiness criteria assume a stable catalog | Campaign writes the same `db.sqlite3` the app serves (~17 edges/min during this pass) | DR-37: separate research DB from served corpus, or freeze a snapshot for launch certification. |

---

## Maintenance

- Update a row when its status changes; never delete history — append a dated note.
- Every D item must name the consequence of each option, not just the recommendation.
- Numbers in this register are snapshots. Re-measure before quoting them in public copy.
- The register is the single place where "we decided X" can be checked. Beads tracks the
  work; this tracks the decision.

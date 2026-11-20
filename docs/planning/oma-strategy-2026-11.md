# OMA strategy and product plan — 2026-11

Status: working plan. Supersedes nothing by fiat; it extends the v0.1 planning drafts and
records where it disagrees with them. Companion documents:

| Document | What it holds |
| --- | --- |
| [decision register](../decision-register.md) | A–E decisions, contradictions, revisit conditions |
| [knowledge model](knowledge-model-2026-11.md) | Entity boundaries, claims, provenance, identifiers, migrations |
| [source landscape](source-landscape-2026-11.md) | Terms, access, yield, reconciliation, method policy |
| [agent contribution and API](agent-contribution-and-api-2026-11.md) | Submission protocol, tokens, API v0, critique |
| [worked examples](oma-worked-examples-2026-11.md) | Three real records through discovery → API → correction |
| [independent critique](oma-critique-2026-11.md) | Red-team review and the corrections it forced (§14) |

**Evidence labels.** VERIFIED = read from code/data with a command or `file:line`.
ESTIMATE = arithmetic on verified inputs, assumptions stated. PROPOSAL = design choice.
Snapshot window: **2026-11-04 21:33–21:52 UTC**. The ingestion campaign was writing during the
pass (`db.sqlite3` gained ~189 edges in 11 minutes), so counts are readings, not constants;
where two readings disagree the later one is used and the drift is noted.

---

## 1. What OMA is for

OMA is a reference for **creative works, their relationships, adaptations, versions and
associated context** — not for people, not for availability, not for reviews.

The sentence is already in the README and `AGENTS.md`. What has never been written down is
what it *excludes* and what "reference" commits us to. That is the first gap this plan closes.

### 1.1 The eight questions OMA should answer better than anywhere else

Ranked by how much of the existing data supports them today (support in brackets, measured
in §3).

1. **What is this work, exactly?** Which of the three *Journey to the Center of the Earth*
   films is this, what is its type, its first public date, and who made it?
   *(Strong: identifiers, types, credits, dates exist; disambiguation does not.)*
2. **What is it an adaptation of, and what adapts it?** The complete, direction-correct
   derivation set for a work, with the claim behind each edge.
   *(Strong data, weak vocabulary — see §5.1.)*
3. **What is the same work under another title or edition?** Translations, retitlings,
   serialisations and editions of one work, distinguished from separate works.
   *(Weak: one translation exists; editions are attached to placeholder versions.)*
4. **How are two works connected, and through what evidence?** A path, the predicates on
   each step, and the source statement for each.
   *(Strong at one hop, impossible beyond one hop.)*
5. **When did this work's afterlives happen?** A timeline of derivations with each date's
   recorded meaning (publication / release / performance / creation).
   *(Good — this is the most finished reader feature, `connections.py`.)*
6. **What did this person or organisation make, in which role?**
   *(Partial: 19,603 credits, no creator pages, role vocabulary is 8 raw strings.)*
7. **Give me the record, its provenance and its uncertainty, in a form software can use.**
   *(None: no API, no schema contract, no machine-readable uncertainty.)*
8. **What belongs together?** Series, seasons, anthologies, canons, franchises.
   *(None: three *Game of Thrones* seasons are unparented drafts; an anthology's parts
   exist only in a cached payload.)*

### 1.2 What OMA deliberately does not answer

These are boundaries, not backlog. They belong in public copy so that absence reads as a
decision:

- **Who owns or controls rights.** OMA records *what a source says* about rights and reuse;
  it never infers ownership from credits, availability or a public-domain year.
- **Whether you may reuse something.** Descriptive rights ≠ permission. A work can be
  public domain in one jurisdiction and not another; a scan can carry a separate claim.
- **Where to watch/read it right now.** Access links are described offers with a
  `last_checked` date, never availability promises.
- **Whether it is good.** No ratings, no reviews, no recommendations.
- **Biographies of people.** A creator is an identity plus credits, at most a short sourced
  description.
- **Full text, images or media.** Links and metadata only, unless a source grants reuse.

### 1.3 Adjacent subjects: link, do not absorb

| Adjacent subject | Treatment | Why |
| --- | --- | --- |
| Creators and organisations | Identity + credits now; creator pages next (DR-24) | Already 13,124 agents / 19,603 credits; the join exists, the view does not |
| Publishers, studios, labels | Role on a release or credit, not a first-class page | They matter for editions; low reader demand for pages |
| Series, franchises, canons | Container works or terms — decision open (DR-09, model §6.3) | Four different meanings currently share `part-of-series` |
| Awards, festivals, venues | Out of scope at launch | Requires a new source and a new entity; no reference question depends on it |
| Fan works, covers, remixes | Relationship *types* exist, zero edges; defer | Rights and volume are both hostile |
| Reviews, essays, scholarship | Link out, never host | Copyright; not our domain |
| Availability/streaming | Access descriptions only (DR-26) | Freshness liability |

---

## 2. Where the project actually is

### 2.1 Inventory (VERIFIED, 21:33 UTC)

| Object | Count | Note |
| --- | --- | --- |
| Works | 13,878 | public 7,452: 6,195 index, 1,207 ambient, **50 editorial**; draft 6,426; suppressed 0 |
| Accepted relationships | **4,915** | 4,726 at 21:33, 4,915 at 21:45; every row `accepted`; 0 disputed, 0 unreviewed |
| Relationship types | 56 defined | **9 used**; the top two (`based-on` 1,568, `derivative-work` 2,268 at 16:27) carry ~80% |
| Pending import proposals | 1,062 | 926 amber, 136 red; no rejection reasons stored |
| Credits / agents | 19,603 / 13,124 | 324 public works have no credit |
| Versions / releases | 7,643 / 6,578 | **7,641 works have exactly one version**; 1 translation in the catalog; 497 public works have any release |
| External identifiers | 21,904 | ol_work 10,731, wikidata 8,384, imdb 2,458 (internal only), tvmaze 328 |
| Public works with an accepted edge | 3,971 (53.3%) | of 7,452; 4,358 public→public edges |
| Access links | 32 | 0 reviewed, 0 `last_checked` |
| Contribution proposals | **0** | pipeline built, never used |
| Verified accounts / staff users | **0 / 1** | |
| `WorkRedirect` rows | **0** | merge path never exercised |
| Field evidence | 42,349 | **0** with `origin="reviewed"` |
| Serving DB | 382 MB | **319.6 MB is `SourceRecord.raw_payload`** (84%) |
| Local corpus | 17 GB | `data/`, outside Git |

### 2.2 Behaviour that is actually implemented and observed

These are not claims from the docs; each was exercised in this pass.

1. **Search works but is a Python scan.** `q=hamlet` → 45 hits in 3.7 s / 83 queries;
   `q=the` → 2,433 hits in 3.8 s, over a 6,242-work candidate set. There is no index, no
   full-text field, no fuzzy match (`discovery.py`, `presentation.py:71-88`).
2. **The adaptation filter is broken.** `/discover/?relationship=has_adaptations` returns
   **0 results** and `is_adaptation` returns 0, because the filter tests
   `relationship_type.category == "derivation"` and only 2 edges have that category
   (`views.py:135-142`).
3. **The flagship work page misfiles its adaptations.** Work 6523 (*Les Trois
   Mousquetaires*) has 176 incoming rows describing **92 distinct claims** and 93 public
   related works, rendered **all** under "Other direct connections", none under
   "Adaptations" (`connections.py:108-110`); each row shows both "Based On" and "Derivative
   Work" for the same relationship.
4. **The same claim is stored twice.** 752 `(from,to)` pairs carry both `based-on` and
   `derivative-work`; at 4,504 rows that was 752 duplicate statements out of ~3,752 claims.
   The resolver maps P144 → `based-on` and P4969 → `derivative-work`
   (`resolve_wikidata_relationships.py:45-52`).
5. **Provenance is rich but partly write-only.** `date_evidence` exists on 13,248 works in
   **three incompatible shapes** (7,852 with `candidates`/`selection_rule`; 200 with the
   richer `assertions`/`disagreements`; the rest older). **No code reads
   `disagreements` and no template shows it** — work 6121 has three competing `P577`
   values (1993, 1993-11-01, 1998) but renders one date with no disclosure.
6. **Relationships carry a supplier constant as their "source".** 4,502 of the 4,504 rows
   at the 16:27 snapshot point at the single `Source` row "Wikidata"; 2,268
   `derivative-work` rows carry the scope note
   "Wikidata P144 (based on) assertion" even though they came from P4969. Review **is**
   recorded (3,774 rows carry `evidence.reviewed_at`; their proposals carry `reviewer_id=1`),
   but it lives inside JSON, not as queryable provenance — and no `FieldEvidence` row has
   `origin="reviewed"`.
7. **Versions are a placeholder.** 7,641 works have exactly one; 5,500 are
   `kind="unresolved"`; 1 translation exists; language is 77 raw values mixing names and
   QIDs ("English" 5,791 vs "Q1860" 1,029).
8. **Correction exists for members, unexercised.** `suggest_correction` allows title,
   description, date text, type, and three relationship fields (`models.py:735`). It has
   never carried a proposal. There is no route for credits, versions, identifiers or a
   date *conflict*, and no machine channel at all.

### 2.3 Accepted decisions (from `CURRENT.md`, campaign docs, permissions matrix)

- Wikidata is the seed and spine; Open Library, Gutenberg and TVmaze attach to it.
- Green-only auto-acceptance: exact identifier **plus** an allowlisted relation type.
  Never infer an edge from a shared title. Never bulk-approve amber/red.
- IMDb is an internal crosswalk only — never displayed, redistributed or exported.
- Ingest never changes visibility, depth or rights statements. Enrichment does not publish.
- Any write to the catalog needs a fresh snapshot, reopened integrity check, manifest,
  schema fingerprint, one transaction, and preserved disagreements.
- Versions stay embedded by default; presentation never changes version identity.
- Thin records may be public if they meet the minimum identity/evidence gate.
- No new entity types in run 1: creators and series stay out of the graph.

### 2.4 Contradictions and stale statements

| # | Statement in the repo | Reality | Handling |
| --- | --- | --- | --- |
| 1 | README: bulk ingestion "deliberately deferred" | A scoped ingestion campaign is approved and running | README corrected to point at the campaign doc |
| 2 | Page map: write APIs and agent credentials are "later scope" | Brief makes agents primary contributors | DR-02: staged, explicit |
| 3 | Page map: "a merge keeps incoming links working" | Zero `WorkRedirect` rows; merge path untested | DR-06 audit |
| 4 | `schema.dbml` 37 tables | 30 models implemented; 0 revisions, 0 terms, 0 rights claims | Directory down to a vocabulary (DR-28) |
| 5 | 56 relationship types | 9 used, 30+ never used, two synonyms dominate | DR-09 consolidation |
| 6 | "Versions stay embedded by default" reads as a live capability | Exercised by one demo work | Keep policy; stop implying the data exists |

---

## 3. Coverage: what counts as a useful record or collection

Record count is not coverage. The defensible unit is a record that **answers at least one
reference question without leaving the page**.

### 3.1 The useful-record test (PROPOSAL, adopt as the public gate)

A work is *reference-grade* when all five hold:

1. **Identity** — a human-readable title (never a bare QID), a specific type or an explicit
   "Unclassified", and at least one external identifier.
2. **Dating** — a date with a recorded *meaning* and precision, or an explicit "date
   unknown"; never a date inferred from a title.
3. **Attribution** — at least one creator with a role, or an explicit "no creator recorded".
4. **Connection or declaration** — at least one accepted, direction-correct, typed
   relationship with a retrievable source statement, **or** a visible statement that none
   is known. Silence is not coverage.
5. **Machine form** — a stable ID, a retrievable JSON record, and per-field provenance.

A **useful collection** adds: a source work, its derivation tree to at least two
generations or five direct derivatives, and edition coverage for at least the source work.

Today, 50 works meet (1)–(4) as *editorial* depth; 497 public works meet (5) in principle
(none in practice, because no API exists); **0** collections meet the edition criterion.
That is the honest starting line.

### 3.2 The launch collection: the adaptation canon

The `editorial` depth slice is already a coherent, non-arbitrary collection: **50 editorial
rows, of which 3 are `is_demo` fixtures that `public_works()` excludes**, leaving **47
visible source works** (Shakespeare, the 19th-century novel, Verne, Dumas, Cervantes, Hugo)
with **1,281 one-hop public neighbours** — 666 films, 180 unclassified, 119 TV series, 80
plays, 50 musicals, 44 operas, 18 video games, 13 ballets. *Les Trois Mousquetaires* alone
has 93 public related works (91 adaptation targets + a sequel + a series container), and
the per-work median is 23 neighbours, with five works at ≤2.

What the canon has: 47/47 descriptions, 20 works with an image, 32 access links on 20 works,
dates and creators. What it lacks: **1 of 47 has a release**, 2 have a language, 0 have
accepted terms. So the
canon can support discovery, adaptation exploration, timelines and provenance — and cannot
yet support "compare the editions" or "which translation". The launch plan (§8) is built on
that distinction rather than pretending otherwise.

### 3.3 Coverage targets (ESTIMATE, to be recalibrated after the vocabulary fix)

| Measure | Now | Launch target | Why this number |
| --- | --- | --- | --- |
| Canon works with specific type | 50/50 coded (45/50 if "written work" counts as generic) | 47/47 specific | Type is the cheapest disambiguator |
| Canon neighbours with a creator | 1,085/1,281 (85%) | 95% | Creator is the most-asked follow-up |
| Canon neighbours with a dated, meaning-tagged date | 1,166/1,281 (91%) | 95% | Timeline is the finished feature |
| Public works with an accepted edge | 53.3% | 55% (not a goal) | Edges only count when the vocabulary is honest |
| Distinct claims per duplicate pair | 2 rows | 1 claim, n sources | DR-09 |
| Works with >1 version | 2 | 300 (translations of canon) | Makes "editions" real |

Deliberately **not** a target: total works. The campaign already states that catalog size is
not progress. Growth in unconnected records is a cost, not coverage.

---

## 4. Knowledge model in brief

Full analysis in [knowledge-model-2026-11.md](knowledge-model-2026-11.md). The four
conclusions that change the product plan:

1. **A claim is not a row.** The same real assertion arrives twice (P144/P4969) and the model
   cannot say "one claim, two statements". Equally it cannot say "two sources disagree".
   The minimum fix is a `claim_family` on relationship types (cheap, reversible) followed by
   an `Assertion` table (the real fix). Everything about "N sources", uncertainty and
   public dispute disclosure depends on it.
2. **Version is degenerate.** 7,641 works have exactly one, the label is generated, the only
   translation is demo data. Keep the entity (it is the right shape for translations, cuts
   and performances) but stop treating it as populated; **decision needed**: optional vs
   editorial-only (DR-16, model §9.1).
3. **Identity is `(scheme, value)`, not `(title, year, type)`.** Three different 2008
   *Journey to the Center of the Earth* films are all public, correctly separate. The
   failure mode is the opposite: titles collide, and the page gives no distinguishing fact.
   Add a disambiguation requirement at the public gate.
4. **Rights must stay descriptive.** 37 of 41 image-bearing works assert "Public domain"
   with no jurisdiction, scope or basis; `authorization_status` is `unknown` on every edge.
   A rights layer is
   warranted only as *statements with jurisdiction and component*, never as a determination.

Ranked schema work (all additive, none run until scoped): `claim_family` → `Assertion` +
`review_note` → containment (`WorkComponent`, `is_container`) → identifier consolidation →
language normalisation → `RightsStatement`.

---

## 5. Acquisition and reconciliation

Full landscape with terms and citations in [source-landscape-2026-11.md](source-landscape-2026-11.md).

### 5.1 What the campaign proved (measured, not asserted)

| Strategy | Gate | Result | Decision |
| --- | --- | --- | --- |
| Cached P144 → edge | exact, dated, ordered | **+418 edges** | adopted |
| Reverse P648 (OL→Wikidata) | exact, single, unowned | **+9 crosswalks** | adopted |
| OL edition Gutenberg → P2034 | exact, single | 56.8M editions scanned, **0 new QIDs** | parked |
| Cached P648 → OL | exact, single | 10 values, **0 links** | parked |
| Amber queue triage | existing green rule | **0 of 1,062** green — a *definitional* zero, because the queue is the amber/red residue. The same rule yielded **470 green of 1,532 (30.7%)**, all approved | parked (framing wrong) |

The campaign stopped after two zero-yield slices. One of those zeros (amber triage) is
definitional rather than informative; the honest reading is that **the strategies attempted
have hit their ceiling**, not that identity work is finished (see §5.2, item 2). The stop
rule itself is the most useful thing the campaign produced. Further growth needs a new
allowlisted source, the untried Wikidata identifier sweep, or work on the *quality* of what
exists.

**Artefact provenance.** The receipts for these results (`ingest-run1-report.md`,
`run1-score.json`, `crosswalk-p648-*.json`) and the commands that produce them
(`score_truth_set`, `measure_ingest_coverage`) live in the campaign's isolated workspace
(`~/factory/runs/20261104-100518-16895e4b/workspace`), **not in this repository**. They are
evidence for the campaign, not artefacts a reader or a future agent can re-run from `main`.
Until they are promoted, treat the numbers as campaign-reported and label them so.

### 5.2 Prioritised opportunities

Ranking rule: expected distinct assertions per unit of cost, where cost includes licence
risk and review labour (source landscape §3).

1. **Fix what is already ingested before ingesting more.** 752 duplicate claims, ~2,268 rows
   with the wrong scope note, ~4,700 edges with no recorded reviewer, 1,062 pending
   proposals, 1,041 `conflicted` import items. No new source, no new licence, no network —
   and it improves every later measurement.
2. **Sweep identifier properties already inside Wikidata.** For the 8,384 cached QIDs, collect
   `P1274`, `P1954`, `P434`, `P8383`, `P10283`, `P724`, `P675` and absent
   `P345`/`P4947`/`P4983`: ≈**168 `wbgetentities` calls**, CC0, no dump. This is the only
   route that raises expected yield for *every* future source at once, and it corrects a
   misleading metric — all 2,446 IMDb IDs sit on works that already have a Wikidata ID, so
   the IMDb column is a derived artefact of the spine, not independent coverage.
3. **Open Library at edition level, for works that already have a partner.** The canon has 1
   release across 50 works; 6,575 editions exist elsewhere and the linker exists. Re-extract
   only works whose `payload_hash` changed; a full refresh is ~20× the measured 19 min/500
   works plus a 17.47 GB download. Yield is edition rows, not edges.
4. **Finish TVmaze as a bounded slice.** 328 of 336 linked; the computable ceiling is ≲**78
   works** (406 TV works, 328 linked, minus those without an IMDb `tconst`). Episodes and
   cast would cost ≈181,236 requests (~50 h) for an excluded node type. CC BY-SA is a
   *product* obligation on derived presentation, not a footnote.
5. **ISFDB, identifiers only, after a scope check.** It is the one candidate that separates
   title / publication / series at the granularity the work–version model needs. Size it
   from the Priority-2 sweep; clear the database licence scope first.

**Do not add:** Gutenberg full catalog/text (measured zero: 56.8M editions → 2 matches → 0
QIDs, plus a date trap), TMDB (non-commercial, forbids ML use, purge-on-termination — it can
never be spine, cache or model input), IMDb beyond the internal crosswalk, Goodreads (API
closed, corpus provenance unclear), music or episode-level TV this run, another book corpus,
AFI/BFI scraping (no reuse grant).

**Sharp correction to the campaign's conclusion.** "Crosswalk is near the local ceiling" is
true only for the *strategies attempted* (P648, Gutenberg editions). It is not true of
Wikidata's identifier properties, which have barely been mined. The next slice should test
Priority 2 before concluding that identity work is finished.

### 5.3 Method policy (where a model earns its cost)

- **Deterministic code** for: identifier extraction and comparison, crosswalking, date
  precision, duplicate-pair detection, coverage metrics, API serialisation. These are
  cheap, auditable and already written.
- **Existing identifiers** are the only auto-accept route. No model output enters the
  catalog without a human, at any confidence.
- **Small models** for: title normalisation, role-string clustering (8 raw role strings → a
  closed vocabulary), candidate ranking for a human queue. Reversible, measurable.
- **Large reasoning models** for: reading a *cited* page and proposing a structured claim
  with a quote, and for adjudicating a *specific* conflicting pair with both sources in
  context. Never for bulk classification, never for "is this the same work" without an
  identifier, never for rights conclusions.
- **Never:** model voting on a factual question. The truth set exists precisely to measure
  a rule, not to average opinions.

---

## 6. Contribution: from "members may propose" to agents as contributors

Full protocol in [agent-contribution-and-api-2026-11.md](agent-contribution-and-api-2026-11.md).

### 6.1 The uncomfortable starting facts

- 0 contribution proposals ever; 0 verified accounts; 1 staff user.
- The review surface is a Django admin change form, one item at a time.
- 1,062 pending import proposals ≈ **~35 reviewer-hours** at the observed ~2 min/item.
- 0 of 42,349 field-evidence rows have `origin="reviewed"` — the "human-reviewed" state the
  UI can render has never occurred.
- `Agent` already means *creator* (13,124 rows). Naming a contributor "agent" would be a
  permanent ambiguity: **rename to `principal`/`operator` before any API ships.**

### 6.2 The shape I recommend (feeds DR-02)

Three distinct channels, because they carry different authority:

| Channel | Who | Gate | Precedent |
| --- | --- | --- | --- |
| **Data contribution** (a fact about a work) | member or agent principal | review by a catalog reviewer | `ContributionProposal` |
| **Editorial proposal** (a policy/interpretation change, e.g. "translations should not count as adaptations") | member or agent | discussion + maintainer decision, recorded in the decision register | new, mostly non-code |
| **Platform rule change** (schema, licence, who may approve) | maintainers only | Justin, recorded in the register | governance |

The submission envelope (PROPOSED): batch-first `POST /api/v0/submissions`, `client_ref` +
`idempotency_key`, per-item verdicts (HTTP 207), `method` (`supplier_import | crosswalk |
model_extraction | human_entered`), `evidence.source_url` + `quoted_text` + `retrieved_at`,
optional `expected_updated_at` precondition, `contradicts[]` for conflict groups. Stable
error codes; no `atomic: true`; `confidence` is client-declared and buys nothing until it is
shown to predict review outcomes.

Three properties matter more than the schema:
1. **Idempotency** — a crashed agent run must be replayable without duplicates.
2. **Provenance of method** — "how did this fact arrive" must be answerable for every row,
   which today it is not (0 reviewed origins).
3. **No power through the API** — the permissions matrix holds: an agent token gets exactly
   the authority of the principal behind it, and auto-acceptance (if ever) is one narrow
   identifier class, after DR-08 is resolved.

### 6.3 Quotas and abuse (starting values, PROPOSED)

| Limit | Start | Calibration |
| --- | --- | --- |
| Reads/minute to the API | 60 | Raise until p95 latency on a single worker degrades |
| Submissions/hour/principal | 30 | Set by reviewer throughput (DR-11: if >3 review-minutes per accepted item, lower this) |
| Batch size | 500 items | Larger batches increase replay cost without reducing review |
| Idempotency window | 30 days | Long enough for a retried weekly run |
| Token lifetime | 90 days, revocable | Short enough to limit a leaked credential |
| Auto-acceptance | none | Only after DR-08 shows ≤1% false-accept at n≥40 |

Abuse handling: per-principal rate limits, a `revoked` token state that fails loudly, a
submission audit log that survives proposal deletion, and a rule that a principal cannot
review its own submissions (the permissions matrix already says this for people).

---

## 7. Reader and API experience

Full design in [agent-contribution-and-api-2026-11.md](agent-contribution-and-api-2026-11.md) §4–5.

### 7.1 What the evidence says to build first

- **Traversal is the strong part.** One work's accepted neighbourhood is bounded and cheap
  (12 per page, constant queries). That is already shaped like an API.
- **Search is the weak part.** 3–4 s and 83 queries per request, full-table scan. A local
  SQLite expression-tree failure is documented (`CURRENT.md:946`); there is no production
  receipt, so the claim is "known to fail at this scale", not "caused an outage". **v0 must
  not promise search.** Publish a snapshot + traversal,
  and treat search as a separate, measured project.
- **The public corpus is small** (~420 KB of text; ESTIMATE low-tens-of-MB with credits,
  identifiers and evidence). A nightly JSONL snapshot with a manifest is more valuable to
  agents than a search endpoint, and it is cheap.

Proposed v0 surface: `works/{id}` (+ relationships, versions, access-links, history),
`agents/{id}` (+ works), `lookup?scheme=&value=`, `changes?since=`, `collections/{id}`,
`vocabularies/*`, `contract`, `errors`, `policy`, `snapshot/{date}.jsonl.gz`. No writes until
the pilot. No search. Keyset pagination; `count` only when actually computed.

### 7.2 Uncertainty must be in the payload, not the prose

Machine-readable fields that already exist as concepts but not as API shape: relationship
`review_status`, claim `family`, date `meaning`/`precision`, identifier `scheme`, merge
`status: merged` with `canonical_work_id`, access-link `last_checked`/`restricted`.
An API that returns only the selected value teaches downstream software to treat a guess as
a fact.

### 7.3 Views worth building (and not)

Build, in order: (1) fix the connection grouping/filters (P0, below); (2) creator page with
roles and credits; (3) edition/translation table for a work, once editions exist; (4) a
public conflict disclosure on records with competing claims; (5) a "what is well covered"
page generated from the coverage metrics; (6) export buttons on collections.

Do not build: a global graph explorer (no demand, huge cost, unreadable), a recommendations
dashboard, comparisons of unrelated works, or any chart that does not answer one of §1.1's
questions. A dashboard is not a view.

---

## 8. Launch plan

### 8.1 Proposition

*"Follow any great story across every medium it became — and see who says so."*

The launch collection is the 47-work visible adaptation canon plus its 1,281 neighbours, presented
as one browsable collection with three curated journeys (Dumas, Verne, Shakespeare) and an
explicit statement of coverage and gaps.

### 8.2 Journeys that must work end to end

1. **Discover → follow.** Search or browse → a canon work → "Adaptations" (correctly filed)
   → a film → its source work. No dead ends.
2. **Understand → verify.** Any fact → "Why this value?" → source statement, retrieval date,
   and competing claims where they exist.
3. **Correct → see it land.** A reader reports a wrong date/edge → reviewer decides within
   7 days → the page and the API both show the new value with the reviewer recorded.
4. **Machine → build.** A developer fetches `/api/v0/works/6523` and its relationships,
   reproduces the page's adaptation list, and gets `claim_family` + provenance.
5. **Agent → contribute.** A scoped principal submits 50 identity crosswalks, receives
   per-item verdicts, and follows them to accepted/rejected with reasons.

Journeys 3–5 do not work today. 1–2 partly work; the vocabulary defect breaks 1 in the most
visible place.

### 8.3 Readiness criteria (beyond record counts and page views)

| # | Criterion | Measure |
| --- | --- | --- |
| R1 | Canon pages answer the three core questions with no dead end | Manual audit, 47/47 |
| R2 | Every canon page has a creator, a meaning-tagged date, and a source link | Query: 100% |
| R3 | 12 reference questions ≥90% success | Scripted benchmark, human-checked |
| R4 | API contract published; 8 example queries pass; p95 traversal <300 ms | Scripted |
| R5 | Review SLA ≤7 days for proposals | Admin log over 4 weeks |
| R6 | Restore from snapshot <30 min, verified | Drill on a copy |
| R7 | 0 unexplained deletions; every merge has a redirect | Audit |
| R8 | 5 unaffiliated readers complete journey 1 unassisted | Moderated test |
| R9 | Truth set ≥40 judged, ≤1% false-accept | `score_truth_set` |

### 8.4 Path to readers, contributors and API users

| Audience | Why they come | Why they return | First move |
| --- | --- | --- | --- |
| Wikipedia/Wikidata editors | Cross-source adaptation chains they cannot see in one place | Corrections accepted with attribution; link-backs | Offer a "sources disagree" view and a correction link on every claim |
| Film-adaptation communities (Letterboxd/forum wikis) | "What else adapts this?" with dates | Stable pages, API for their tools | Publish the canon list; ask for gaps |
| Librarians and archives | Edition/translation disambiguation | Exportable, citable records | Consultation on the edition model; one pilot collection |
| Agent/LLM developers | Clean JSON + provenance for adaptation data | Contract stability, snapshot, changes feed | Publish `/contract` and snapshot first |
| Students/teachers | Ready-made adaptation sets | Lesson-friendly collections | 3 curated collections with notes |

The return loop is the correction: a contributor sees their fix live, attributed, and in the
API. Everything else is acquisition.

---

## 9. Sustainability

### 9.1 Cost drivers (ESTIMATE, assumptions explicit)

| Driver | Current | Scaling behaviour | Mitigation |
| --- | --- | --- | --- |
| Hosting | $13/mo (Render Starter + Basic-256mb) | Grows with serving DB, not readers | Serving DB is ~20 MB of relational data; keep payloads out |
| Research archive | 17 GB local + 319.6 MB in DB | ~+17 GB per full dump cycle | Never host the archive; compress payloads; snapshot to object storage |
| Reviewer time | 1 part-time human; 1,062-item backlog (~35 h) | Linear in submissions | Batch triage, better machine validation, narrower auto-accept |
| Engineering | 1 maintainer; 30 models, 43 commands, ~250 tests, 16 MB docs | Superlinear in entity types | Adopt DR-22: new entity type needs a query, a source, a display rule |
| Model/API spend | Campaign: 552k input tokens over 7 turns (subscription, reported cost 0) | Grows with autonomous slices | Bounded slices, cached payloads, no per-request inference |

If a part-time curator were paid 5 h/week at $30/h, **$650/month** would dwarf hosting. That
is the real cost of "reference-grade": review, not servers.

### 9.2 Funding options compared

| Model | Fit | Risk to openness | Realistic early value |
| --- | --- | --- | --- |
| Donations (Open Collective, GitHub Sponsors) | Good; no strings | Low | $0–200/mo until there is an audience |
| Institutional sponsorship (library, university, archive) | Good; aligns with reference use | Medium: sponsor may expect prominence | $500–2,000/mo, needs a sponsorship policy |
| Grants (NEH/Mellon/IMLS, NLnet, Wikimedia community) | Best fit for a knowledge resource | Low–medium: deliverables, reporting | $5k–50k per cycle; 6–12 month lead time |
| Services (hosted instances, curation for an archive, API SLA) | Good; revenue without closing data | Low if scoped | Requires customers and contracts |
| Paid API tier | Poor: charging for CC0/CC BY-SA data is incoherent unless it is SLA/support | High | Only as support, never as access |
| Advertising / data sale | Excluded | Fatal | Never |

**Recommendation.** Grants + donations as the base; sponsorship only with a published
independence policy (no editorial influence, no early access to unreviewed data, disclose
> $1k); services as an option, not a plan. Keep the spending ceiling at ≤$50/month for
hosting through the launch quarter (DR-05).

### 9.3 Remaining useful if funding or contribution slows

The resource must degrade to something still worth having. That means: a nightly public
snapshot + manifest, a documented restore, no dependency on a proprietary service, a
read-only API that can be replaced by the snapshot, and a corpus that fits on a laptop
(the relational data does; the raw dumps do not). A static export of the canon with
provenance is a legitimate end state — it is a better outcome than a half-maintained
database.

---

## 10. Prioritised work

Each package is independently shippable, has a measurable acceptance test, and does not
require a new source or a new entity type.

### P0 — Make the adaptation graph honest, code-only (1 day, revised after critique)

The first version of this package required a `claim_family` column and a data migration on
the live database. The independent critique killed that: the migration would race an active
writer, and its acceptance test (">1,000 results") is impossible — the measured ceiling with
a correct family filter is **~430** browsable works (528 without the endpoint-visibility
filter). The reader-visible gain comes from code, not schema.

Revised scope, all in code, one day, no migration, no catalog write:

1. A module-level family map (`based-on`, `derivative-work`, `adapted-from` → one family) used
   by `discovery.py` and `connections.py` in place of the `category` test.
2. Fix the causes, not the rows: `resolve_wikidata_relationships.py` currently creates every
   type with `category="reference"` (overriding the seeded `derivation`), and
   `ImportRelationshipProposal.approve()` (`models.py:631`) hardcodes the P144 scope note for
   all properties. Correct both at source.
3. Correct `evidence.entity_id`/`source_url` for non-P144 edges: ~2,625 rows (≈53%) point at
   the target entity while the `statement_id` belongs to the seed, so the "supporting
   statement" link opens a page that does not contain the statement. Journey 2 is broken for
   half the graph until this is fixed.
4. Collapse duplicate claims in counts and connection rows (keep both rows, show "N claims"),
   and use a neutral label ("Based on") until the DR-07 audit says "Adapted from" is earned.
5. Add a completeness disclosure on connection lists: the list is a curation sample plus one
   import batch, not the world.
6. Audit 50 sampled edges against their Wikidata statements (DR-07) before any page uses the
   word "adaptation".

Acceptance: `/discover/?relationship=has_adaptations` returns the measured family set
(~430 ± drift); work 6523 shows **91 adaptation works + 1 sequel + 1 series**, one label per
row, no duplicate labels; counts stop double-counting; every rendered evidence link opens a
page containing the cited statement; a visible "not complete" notice; tests for filter,
grouping and statement-entity consistency. No live-DB migration.

### P1 — Creator pages and vocabulary normalisation (1–2 weeks)

Scope: agent page (credits by role, works, identifiers), role vocabulary (8 raw strings →
closed set), language normalisation (77 raw values → BCP-47, raw preserved).
Acceptance: 95% of canon neighbours reachable to a creator page; no raw QID in a language
field; role filter works.

### P2 — Visible uncertainty and review reasons (1 week)

Scope: render competing date/type claims (use the existing `assertions`/`disagreements` data
and extend `dates.py` to produce it for all works); add `review_note` to
`ImportRelationshipProposal` and `ContributionProposal`; backfill "reason not recorded";
surface rejection reasons to submitters.
Acceptance: work 6121 shows all three `P577` claims; 10 historical rejections have a
reason or an explicit "not recorded"; a member can see why their proposal was rejected.

### P3 — Read API v0 + contract + snapshot (2–3 weeks)

Scope: `works/{id}` and sub-resources, `lookup`, `changes` (new append-only log), `contract`,
`errors`, `policy`, nightly JSONL snapshot + manifest; keyset pagination; no search; no
writes.
Acceptance: R4 met; an external script (not ours) reproduces the page's adaptation list and
resolves an OL id; snapshot verified against DB counts.

### P4 — Agent contribution pilot — **PAUSED; do not build yet** (revised after critique)

The independent critique recommends not building this at all in the current state, and the
evidence supports that: there is no account in the database that can authenticate (0
`EmailVerification` rows), no identified partner, no verified principal, and the review
queue is already the bottleneck. Building a submission funnel into a blocked output is the
wrong order of operations.

Re-open only when **all** of the following are true: E1 has measured review throughput; the
email-verification path works for at least one non-staff account; E2 has raised the truth
set to ≥40 judged items; and the 1,062-item backlog is below 200. If those hold, the scope
is: token issuance (`contributor:probationary`), scoped principal, submissions into the
**existing** `ContributionProposal` table, idempotency, per-item verdicts, quota enforcement,
audit log — and the rename to `principal` first.

### P5 — Launch readiness and collection (1 week)

Scope: three curated journeys, coverage page, accessibility/empty-state audit, restore drill,
public statement of scope and gaps.
Acceptance: R1–R9.

### Experiments that can change the plan (run early, cheap)

| # | Experiment | Cost | Decision it settles |
| --- | --- | --- | --- |
| E1 | Review throughput: 20 pending proposals in admin, timed | 1 afternoon | Sets quotas; decides whether a queue UI precedes an API |
| E2 | Truth-set expansion to 40 judged | ~50 min of Justin's time | Whether the precision gate can justify auto-acceptance |
| E3 | 50-edge semantic audit (DR-07) | 2–3 hours | Whether `based-on` means "adaptation" |
| E4 | Search benchmark: 12 questions, p95 latency | 1 day | Whether search is a feature or a project |
| E5 | Merge rehearsal + restore drill on a copy | 1 day | DR-06; whether merge claims are true |
| E6 | Storage split: payloads out of the serving DB | 2 days | Cost model; backup time |

---

## 11. The next substantial work package

**P0, revised: a code-only labelling and honesty fix (one day).** No migration, no catalog
write, no dependency on the campaign's write window.

1. **Family map in code.** A module constant mapping `based-on`, `derivative-work` and
   `adapted-from` to one family; use it in `discovery.py` (replacing the
   `category == "derivation"` test) and `connections.py` (replacing the `adapted-from`
   special case and the priority table). Keep the query parameters unchanged.
2. **Fix the two causes.** `resolve_wikidata_relationships.py` creates every relationship
   type with `category="reference"`, overriding the seeded category; and
   `ImportRelationshipProposal.approve()` (`models.py:631`) hardcodes the P144 scope note for
   all properties. Both are one-line corrections that stop re-creating the defect.
3. **Fix statement links.** For non-P144 edges (~2,625 rows, ≈53%), `evidence.entity_id` and
   `evidence.source_url` name the target entity while `statement_id` belongs to the seed.
   Correct at write time and backfill in a script that preserves the old values in evidence.
4. **Group and label.** One row per related work, one label per claim family, `n claims` when
   a family has more than one assertion, neutral wording ("Based on") until step 6 earns
   "Adapted from".
5. **Completeness notice.** A short, visible line on connection lists: this list is a
   curation sample plus one import batch, not the complete derivation set.
6. **Audit 50 edges (DR-07).** Independent check of whether `based-on` means adaptation,
   translation, sequel or reuse. Only after this may the page use "Adaptations".
7. **Tests and measurement.** Filter returns the measured family set (~430 browsable works,
   not >1,000); 6523 shows 91 adaptation works + 1 sequel + 1 series with one label each;
   public counts stop double-counting; evidence links contain the cited statement. Record
   before/after in `CURRENT.md`, append to DR-09.

Constraints: no network, no db.sqlite3 write, no change to visibility/depth/rights, no new
entity types. This package is safe to run while the campaign is active because it changes
code and display only.

---

## 12. Source of truth

- This plan states the product direction; the **decision register** states what is decided.
- **Beads** (`factory-8ab`, project tasks) tracks work; `CURRENT.md` records what happened.
- The **ingestion campaign doc** is the only authorisation for bulk ingestion.
- If this document and the code disagree, the code plus a fresh query wins; correct the
  document rather than the memory of it.

---

## 13. Limits of this plan, and what would change it

The independent critique this pass produced is in
[agent-contribution-and-api-2026-11.md](agent-contribution-and-api-2026-11.md) §7; it was
written without seeing this synthesis, and it attacks the assumptions this plan inherits.
Its strongest points, which this plan accepts:

1. **The galaxy framing is empirically wrong at current density.** Depending on the reading,
   36–43% of browsable works have zero accepted relationships (2,661 of 6,242 at 21:20; 2,269
   at 21:45 as the campaign added edges), and only 3.7% have five or more. Adding agent-proposed edges
   mostly adds degree-1 links to works nobody reaches, at constant review cost. The plan's
   answer is to stop treating edge count as coverage (§3.3) — but that is a retreat, not a
   refutation.
2. **Review capacity, not tooling, is the binding constraint.** 0 proposals ever, 1 staff
   user, 1,062 pending. Every quota in §6.3 is a guess until E1 measures decisions/hour.
3. **The plan may be polishing an internal metric.** P0 fixes a real reader-visible defect
   (0 adaptation results, all adaptations misfiled), so it survives this criticism — but
   P0's *value* must be proved by R1/R3, not by the duplicate-pair count falling.
4. **The canon is an anglophone literary curriculum.** Shakespeare, the 19th-century novel,
   and translated European classics dominate. Verne/Dumas/Cervantes/Hugo soften this; they
   do not fix it. A launch that cannot show, say, Arabic or Japanese adaptation chains is a
   reference for a slice of world culture, and should say so.
5. **There is no funding path yet, only options.** §9.2 lists models; none is committed.
   The honest position is that the project is unfunded and cheap, and the launch plan does
   not depend on money — only on reviewer time.

What would change the plan, in order of likelihood:

| Signal | Threshold | Change |
| --- | --- | --- |
| E1 review throughput | <15 decisions/hour sustained | Drop the agent pilot; invest in batch triage and auto-validation instead |
| E3 semantic audit | >20% of sampled edges are not adaptations | Stop calling the graph an adaptation graph; rename the product promise |
| DR-33 identifier sweep | <50 new identifiers | Accept the identity ceiling; shift entirely to quality and editions |
| R3 search benchmark | <70% success on reference questions | Search becomes the next milestone, ahead of the API |
| R8 reader test | <3/5 complete journey 1 | The connection page, not the data, is the problem |

**What this plan does not know.** Whether anyone will use OMA is untested. There is no
traffic data, no user research, no waiting list, and no partner. The launch plan is a
hypothesis with acceptance criteria, not a forecast.

---

## 14. Corrections after independent critique

An independent critique ([oma-critique-2026-11.md](oma-critique-2026-11.md)) was run against
this plan and the underlying documents. It found errors, and they are corrected above rather
than defended. The substantive ones:

| Claim in the first draft | Corrected | Where |
| --- | --- | --- |
| P0 acceptance: `has_adaptations` ">1,000" | Measured ceiling ~430 browsable (528 unfiltered); the test was impossible | §10 P0, §11 |
| P0 needs a `claim_family` column + migration | Same reader-visible result from a code constant; the migration would race the campaign writer | §10 P0, §11 |
| "4,504 edges with no recorded reviewer" | False: 3,774 rows carry `evidence.reviewed_at`; review exists but is JSON-only and not queryable provenance | §2.2 item 6 |
| Amber triage "0 of 1,062 green" = zero-yield | Definitional zero; the rule yielded 470/1,532 (30.7%), all approved | §5.1 |
| Canon = 50 works | 47 visible; 3 `is_demo` fixtures are excluded by `public_works()`, so R1 "50/50" was unachievable | §3.2, §8.3 |
| "41 images assert Public domain" | 37 of 41 image-bearing works | §4 item 4 |
| "20 access links" on the canon | 32 links on 20 works | §3.2 |
| "46/50 canon works have a specific type" | 50/50 coded (45/50 if "written work" counts as generic) | §3.3 |
| "Production-wide 500 from search" | A local SQLite expression-tree failure; no production receipt | §7.1 |
| Tolstoy as a non-anglophone mitigation | Anna Karenina is `index` depth, not in the canon | DR-04 |
| 6523 = "93 adaptations, 91 claims" | 91 adaptation works + 1 sequel + 1 series container = 93 public related works; 92 claims | §10 P0, worked examples |
| "~35 reviewer-days" (companion doc) | ~35 reviewer-hours (1,062 × 2 min ≈ 35.4 h) | agent doc editor's note |

**Four things the plan missed, now added as work or decisions:**

- **M1 — research DB vs served corpus.** The campaign writes the same `db.sqlite3` the app
  serves (189 edges in 11 minutes during this pass; one run stuck `running` since 2026-10-29).
  Readiness criteria measure a moving object and P0 nearly raced the writer. → DR-37.
- **M2 — completeness disclosure.** The canon was built by capping at the reviewed top four
  adaptations per source work and then bulk-approving 475 amber proposals. No page says the
  lists are samples. A reference that implies completeness without holding it is misleading.
  → DR-38 and P0 step 5.
- **M3 — statement links.** ~53% of edges link to a Wikidata page that does not contain the
  cited statement, so journey 2 fails for half the graph. → P0 step 3, DR-39.
- **M4 — work-level language.** 181 of 1,283 canon neighbours have non-ASCII titles and
  `language` exists only on `Version`, which 46 of 50 canon rows lack; the reader cannot
  tell a Swedish *Midsummer Night's Dream* from an English one. → DR-40.
- **M5 — no demand data.** The eight questions are ranked by supply. No query log exists.
  → DR-41, free to start.

**What the critique confirmed and this plan keeps:** the refusal set (TMDB, IMDb beyond
internal crosswalk, Goodreads, paid API tier, advertising); no search in API v0; the
useful-record gate; refusing auto-acceptance for relationships/dates/credits/rights; the
CC0-statements + CC BY-SA-compilation licence split; renaming agents to `principal`; and the
statistical warning that a precision of 1.0 over n=6 is not a gate.

**What the critique killed:** the agent-contribution pilot (P4) as currently scoped, and the
"50 works + 1,281 neighbours" framing as a *product* — the collection is a curated sample of
adaptation chains, not a complete reference, and must say so.

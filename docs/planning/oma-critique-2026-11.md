# Independent critique of the 2026-11 OMA plan

Written 2026-11-04 by `critic`, who did not write the plan. Scope: the strategy synthesis,
the decision register, the three supporting research notes, and the repo itself.

Method: read-only SQL against `db.sqlite3` (`file:...?mode=ro`), file reads, `git` state.
I ran no management command, test, migration or import, so runtime claims are inferred from
code or marked **unverified**. Reads span 21:38–21:52 UTC; the campaign was writing
throughout (see §1.3).

Labels: **VERIFIED** (query/`file:line`), **ESTIMATE**, **OPINION**.

---

## 1. Fact-check

### 1.1 What holds

Most of the inventory is accurate to the row and deserves saying plainly: 13,878 works
(7,452 public: 6,195 / 1,207 / 50), 56 types with 9 used, `based-on` 1,568 and
`derivative-work` 2,268 exactly, 752 duplicate pairs exactly, 1,062 pending = 926 amber +
136 red exactly (verified by joining `docs/proposal-triage-latest.json` to the live table:
all 926 and all 136 are pending, all 470 green are approved), 19,603 credits / 13,124
agents, 324 public works without a credit, 115 without a year, 7,641 single-version works,
1 `edition-of` edge, 32 access links with 0 `last_checked`, 42,349 `FieldEvidence` rows with
0 `reviewed`, 0 proposals, 0 verified accounts, 1 staff user, 0 redirects, 41 image-bearing
works, 6 duplicate slugs, 43 command files, 239 tests, 37 DBML tables, 382.3 MB database of
which 322.6 MB (84.4%) is `SourceRecord.raw_payload`. The triage arithmetic, the Wilson
interval in DR-08 and the 35-hour reviewer figure in §6.1 are correct. **VERIFIED**

### 1.2 What is wrong, unsupported, or mislabelled

| # | Plan claim | Measured | Verdict |
|---|---|---|---|
| 1 | "4,504 edges with no reviewer" (strategy §5.2); "all 4,504 accepted edges have no recorded reviewer" (agent §4.7) | 3,777 of 4,915 rows carry `evidence.reviewed_at`; their proposals carry `reviewer_id=1` | **False.** What is true is narrower: no `FieldEvidence` row is `origin="reviewed"`, and no member proposal was ever reviewed |
| 2 | Amber triage "0 of 1,062 green" = a zero-yield null result (§5.1) | The rule produced 470 green of 1,532 candidates, all 470 approved; "0 of 1,062" is definitionally zero because amber/red are by definition not green | **Misleading.** The rule yielded 30.7%, not 0 |
| 3 | P0 acceptance: `has_adaptations` returns ">1,000 works" | 422 works (browsable, public source). Even unfiltered by endpoint visibility the ceiling is 576 | **Impossible.** See §2.3 |
| 4 | "Canon works with specific type 46/50" (§3.3) | 50/50 have a typed code; 45/50 if "literary work" counts as generic | **Unsupported** (no query reproduces 46) |
| 5 | "41 images assert 'Public domain'" (§4.4) | 41 works carry an image; 37 assert "Public domain", 4 carry CC licences | **Overstated** |
| 6 | Canon has "20 access links" (§3.2) | 32 links on 20 works (12 works × 2, 8 works × 1) | **Unit error** (links counted as works) |
| 7 | "The 50-work canon" | 47 visible; 3 are `is_demo=1` "The Glass Orchard" fixtures that `public_works()` (`views.py:46-54`) excludes, so those pages 404 | **Denominator wrong.** R1 "50/50 canon pages answer the three core questions" is unachievable: three pages do not exist |
| 8 | "+418 edges", "56.8M editions → 0 QIDs", "precision 1.0, 8 judged" (§5.1, DR-08) | `ingest-run1-report.md`, `ingest-run1-crosswalk-p648.json`, `run1-score.json` are not in the repo; `score_truth_set` and `measure_ingest_coverage` (§11 step 6, R9) are not commands in `catalog/management/commands/` | **No artefact.** The gate the plan tells us to re-run cannot be run |
| 9 | Snapshot discipline ("21:33 UTC", "counts are readings") | source-landscape reports 4,504 edges at 16:35 local; the strategy reports 4,726 for 21:33 UTC, which is the same minute. They differ by 222 | **One timestamp is wrong.** My read: 4,915 |
| 10 | Backlog "~35 reviewer-days" (agent §2.9, §7.5) vs "~35 reviewer-hours" (strategy §6.1) | 1,062 × 2 min = 35.4 h = 4.4 working days | **8× unit error** in the document whose quota arithmetic depends on it |
| 11 | "Already caused a production 500" (§7.1) | `CURRENT.md:946` documents a *local* SQLite `Expression tree is too large` at 1,000 OR terms; no production receipt exists | **Unsupported.** It proves the scan, not a production failure |
| 12 | DR-04 offers "Tolstoy" as a non-anglophone mitigation | No Tolstoy work is in the 50; Anna Karenina sits at `index` depth | **False** |
| 13 | P0: work 6523 should show "93 adaptations, 91 distinct claims" | 91 adaptation works + 1 sequel (*Vingt ans après*) + 1 series container (*trilogie des mousquetaires*) = 93. Rows: 175 adaptation assertions collapse to 91 works | **Both numbers wrong**; units mixed |
| 14 | §5.1 "0 of 1,062 green … two zero-yield slices stopped expansion" | The graph gained 1,136 edges today; triage approved 470 | **Framing wrong** |

### 1.3 Drift, not error

Edges 4,726 → 4,915 (+189 in ~11 min, ~17/min); import items 23,614 → 23,929; canon
neighbours 1,281 → 1,283; creators 1,085 → 1,087; dated 1,166 (stable); languages 77 → 78;
import runs 90 → 95; `created` items 14,548 → 14,863; payload 319.6 → 322.6 MB. One
"drift" is too large for that rate: browsable zero-degree works are 2,269 (36.3%) now, not
2,661 (42.6%). With 1,136 new edges the campaign cannot attach ~390 isolated works unless
every edge lands on one. The *direction* of §7.5's long-tail argument survives (3.7% have
≥5); the number used as its empirical basis does not. **VERIFIED / ESTIMATE**

---

## 2. The strategy

### 2.1 The eight questions: Q3 fails first, and it fails by construction

**Claim.** "What is the same work under another title or edition?" is answerable.
**Evidence.** 7,643 versions, 1 of kind `translation`, 1 `edition-of` edge, 46 of the 50
canon rows have **no version at all**, and 0 canon works have a translation. The planned
route (Open Library editions) cannot supply translations: the knowledge model records 0
`translated_from` fields in 5,500 OL payloads, and source-landscape §3.3 states identity is
exhausted and OL yield is edition rows. So Q3 is not "weak data" — it has no data route in
the plan. Q8 (containment) is the runner-up: 19 `part-of-series` edges, no container column,
no `WorkComponent`, and containment is ranked third in schema work but absent from P0–P5.
**Consequence.** Two of eight questions are unanswerable at launch, and one of them (Q3) is
the question that distinguishes a reference from a graph viewer. The plan is honest about
ranking it "weak" but not about there being no path.
**Cheapest test.** Pick five canon works; try to answer "which translation/edition is this
reader holding" from the page in under two minutes. If the answer is "impossible three
times out of five", cut Q3 from the launch copy.

### 2.2 The launch thesis is a demo with a bug in it

**Claim.** 50 works + 1,281 neighbours is a product.
**Evidence.** 47 visible works; median 23 neighbours, range 1–93; five works have ≤2 (two
real: 6522 *Journey to the Centre of the Earth* with 2, 6519 *The Adventures of Sherlock
Holmes* with 1); 0 editions; 32 access links, none checked; the only public collection has
20 entries, so "presented as one browsable collection" (§8.1) describes something that does
not exist; search is 3–4 s; and every page's "Adaptations" group is empty until P0 ships.
Membership is also not what §3.2 says: 96 of the 1,283 neighbours are other books (47 novel,
43 literary-work, 5 written-work, 1 book) and 9 are music (6 album, 3 song) — sequels,
collections and cast recordings that DR-01 links-not-absorbs or excludes.
A skeptical reader in five minutes: homepage → *Hamlet* → a list titled "Other direct
connections" where one row shows both "Based On" and "Derivative Work" → no Adaptations
section → search 3 s → a canon work with three competing dates and no disclosure.
**Consequence.** The launch is a graph demo. What converts it into a product is exactly the
three things missing: correct grouping, an explicit completeness statement, and editions.
**Cheapest test.** Five unaffiliated readers, journey 1, no help (this is R8 — run it now,
not in P5, because it can cancel P0's scope).

### 2.3 P0 fixes a metric, not a reader, and its acceptance test cannot pass

**Claim.** "claim_family + dedupe" is the highest-value next work and "ready to run".
**Evidence.** (a) The corrected filter returns **422** works, not >1,000, so whoever
implements P0 must either fail its acceptance test or silently change the definition.
(b) The dedupe half is already available in code: `connections.py:33-44` special-cases
`adapted-from`, `GROUPS` is indexed by a priority derived only from that code, and
`VERSION_LEVEL_CODES` is a Python set — a family map is a 10-line change, no column, no
migration. (c) The column is therefore the only part needing a guarded write to a live DB
that the campaign is actively writing (17 edges/min), which is the riskiest part of P0 and
buys the reader nothing. (d) The 2,268 wrong scope notes come from a hardcoded string in
`ImportRelationshipProposal.approve()` (`models.py:631`) that will re-stamp the wrong note
on the next approval; P0's data migration fixes rows, not the cause. (e) The semantic
question DR-07 marks **C** ("needs independent audit") is exactly what P0 would publish as
fact.
**Consequence.** A week of schema work on a live database to relabel ~10% of public works
(422), leaving the write path that recreates the defect and the interpretation un-audited.
The reader-visible gain of the *code-only* version is identical.
**Cheapest test.** Implement the family map as a module constant and diff page HTML for ten
works. If the diff is the whole of P0's acceptance, the migration is unnecessary.

### 2.4 Agent contribution: circular, and priced off a unit error

**Claim.** Agents are a contributor channel worth a P4 work package.
**Evidence.** 0 verified accounts, 1 staff user, 0 member proposals, 0 `reviewed` evidence
rows, and — decisively — the email gate is vacuous (0 `EmailVerification` rows), so *no
account in this database can submit at all*. The companion document already concludes this
("empirically not a galaxy", §7.5), and the strategy imports its protocol while ignoring its
conclusion. The reasoning is circular in three places: P4 is "gated on DR-11", but DR-11's
measurement needs a probationary principal and a working verification path that P4 was
supposed to create; auto-acceptance is gated on a truth set whose 52 unjudged items need the
same owner attention review needs; quotas derive from a throughput (30 decisions/h) E1 has
not measured, and from a backlog mis-stated by 8× as "35 reviewer-days" when it is 4.4
working days. P4's acceptance also names "one partner agent" — no partner exists anywhere
in the repo.
**Consequence.** P4 buys a submission funnel into a queue whose output is blocked, when 470
of 1,532 items were already resolvable by rule. The scarce input is not submissions; it is
the owner's evenings, and the backlog is a stock of ~35 hours, not a flow.
**Cheapest test.** E1 (20 proposals, stopwatch) plus one SQL pass for `evidence ? 'reviewed_at'`
— both already proposed, both would have caught findings #1 and #10 above.

### 2.5 Money: the hosting number is credible, the review number is doing illegitimate work

**Claim.** "$650/month of curation would dwarf hosting" makes review the real cost.
**Evidence.** $13/mo matches `render.yaml` (Starter + Basic-256MB); $650 = 5 h × $30 × 4.33
is arithmetic-correct. But the review cost is presented as a *rate*, and the data shows a
*stock*: the 1,062 pending items arrived from two import batches, not from users; triage
resolves 31% with no human; no reader-submitted proposal has ever existed. Grants
"$5k–50k per cycle, 6–12 month lead" are **ESTIMATE** with no named programme, no applicant
capacity and a clock incompatible with a seven-week P0–P5.
**Consequence.** If review is a one-time 35-hour stock, the sustainability argument for
automation, for a contribution API and for institutional funding weakens sharply, and
§9.3's own fallback ("a static export of the canon with provenance is a legitimate end
state") becomes the rational plan: generate the site, ship a JSONL snapshot, stop writing.
**Cheapest test.** Count how many of the 1,062 were created by the last two import runs
(one query on `run_id`). If >90%, review is an import artefact, not a service cost.

### 2.6 The register hides decisions that code and the campaign already made

Four are already settled outside the register, and one contradicts an "accepted decision":

1. `resolve_wikidata_relationships.py:250-256` creates every relationship type with
   `category="reference"`, overriding the seeded `derivation` category
   (`seed_relationship_types.py:12,41`). That is why `based-on` and `derivative-work` are
   "reference" today and why the filter returns 0. The vocabulary defect the plan treats as
   an open knowledge question (DR-07 **C**) is partly a one-line code decision.
2. `approve()` hardcodes the P144 scope note for all properties (`models.py:631`), applied
   to 3,777 rows.
3. `public_works()` drops demo rows by existence check (`views.py:46-54`) — a visibility
   rule in code, absent from the register, which is what makes the canon 47 works.
4. `CURRENT.md:773-786` records a decided bulk approval of **475 amber** proposals and the
   publication of **351 draft endpoints** by one-off shell. The campaign doc says "no bulk
   approval of amber or red"; §2.3 lists "ingest never changes visibility" as an accepted
   decision. Both were already broken once, and neither appears in the register's
   contradictions table.

**Consequence.** The register's authority ("the single place where we decided X can be
checked") is weaker than claimed; four load-bearing behaviours are decisions of code, not
of the owner. **Cheapest test.** `grep` for hardcoded vocabulary/visibility constants in
`management/commands/` — 15 minutes, and it produces the missing rows.

---

## 3. What the plan misses (more important than what it includes)

### M1. There is no boundary between the research DB and the served corpus

**Claim.** Readiness criteria can be met.
**Evidence.** The campaign writes to the same `db.sqlite3` the app serves; +189 edges landed
during this review, and knowledge-model §0 records run 85 `running` with zero items since
10-29.
**Consequence.** R1–R9 measure a moving object; a launch certified on Monday is wrong on
Tuesday, and P0's migration can race an active writer. This is the biggest operational
omission.
**Cheapest test.** Snapshot the DB, serve the snapshot, diff served counts daily for a week.

### M2. Nothing tells a reader that an adaptation list is incomplete

**Claim.** §3.1's gate requires declaration of absence; §8.2 promises "see who says so".
**Evidence.** The canon was built by capping at "the reviewed top four adaptations per
source work" (`CURRENT.md:110`) and then bulk-approving 475 amber proposals. No page says
so; P2 discloses competing values, never missing coverage.
**Consequence.** The product's core claim is completeness of derivation sets, and the data
is a curation sample plus a batch import. That is the difference between a reference and a
misleading one.
**Cheapest test.** Compare stored edges for three canon works against their Wikidata P144
count in a browser; if stored < Wikidata, the disclosure is mandatory.

### M3. The statement links are wrong for 53% of edges

**Claim.** Journey 2 ("verify → source statement") works.
**Evidence.** For every property except P144 the resolver stores `entity_id`/`source_url` as
the *target*, while `statement_id` belongs to the *seed*: 2,266 of 2,268 `derivative-work`
rows, plus 185 `followed-by`, 145 `follows`, 19 `part-of-series`, 4+4 influence edges — 2,625
rows — cite a statement that is not on the page the link opens. P0 fixes the note but not
the URL.
**Consequence.** Half the graph's verification path is broken, and P2 would build public
conflict disclosure on top of it.
**Cheapest test.** Open five `derivative-work` rows on a work page and search the linked
Wikidata page for the statement ID.

### M4. Work-level language has nowhere to live, and 14% of the canon neighbourhood needs it

**Claim.** P1's language normalisation improves the reader experience.
**Evidence.** 181 of 1,283 neighbours have non-ASCII (mostly non-English) titles;
`language` exists only on `Version`, and 46/50 canon works have no version.
**Consequence.** P1 normalises a column the canon cannot reach, while the display problem —
a Swedish 1960s production titled *En midsommarnattsdröm* with no language marker — remains.
**Cheapest test.** Filter the canon neighbourhood for non-ASCII titles and try to state each
one's language from the page.

A fifth, smaller miss: there is no demand data at all. Eight questions are ranked by supply;
no query log exists and none is planned, so "what to build next" is inferred from tables.
Logging `/discover/?q=` for two weeks is free.

---

## 4. What survives scrutiny

- **The refusal set is right.** TMDB, IMDb-beyond-crosswalk, Goodreads, paid API tiers and
  advertising are correctly excluded, with quoted terms.
- **"No search in API v0"** is correct for the stated reason (scan-bound), even though the
  "production 500" evidence is wrong.
- **The useful-record test (§3.1)** is a good product gate and should be adopted.
- **Auto-acceptance for relationships, dates, credits and rights is correctly refused**;
  DR-02's staging is the right shape. **"Rename agent → principal"** is right and urgent.
- **The licence split** (CC0 statements, CC BY-SA compilation, exclusion list) is coherent
  and compatible with the TVmaze obligation.
- **DR-08's statistical caveat** is correct and unusually honest.

## 5. The first change, and one thing not to do

**First change.** Re-scope P0 to a code-only labelling fix and gate the word "adaptation" on
the DR-07 audit. Concretely: a module-level family map in `connections.py` and `discovery.py`,
the two hardcoded strings in `resolve_wikidata_relationships.py` and `models.py:631`
corrected at source, `entity_id`/`source_url` fixed for non-P144 rows, a visible "this list
is not complete; N claims came from one import batch" line, and the 50-edge audit run before
any page says "Adapted from". No migration, no live-DB write, one day of work, and it makes
the launch thesis honest instead of merely consistent.

**One thing I would not do.** Do not build P4, the agent-contribution pilot. It has no
verified account that can authenticate, no identified partner, a substrate (the review
queue) that is already the bottleneck, and a quota model derived from an unpublished
measurement and a unit error. The 35 hours of existing backlog should be spent before any
new supply channel is opened.

---

### Appendix — method

All counts are read-only `sqlite3` reads (21:38–21:52 UTC). Adaptation-filter numbers
replicate `discover()`'s predicate on `browsable(public_works())` with public sources.
Triage splits join `docs/proposal-triage-latest.json` to the proposal table by id and
status. Absent artefacts were searched with `find` and `git ls-files`. The
`derivative-work` mismatch compares each `statement_id` prefix with `evidence.entity_id`.

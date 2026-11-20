# Open Media Atlas — knowledge model review, 2026-11

Status: research note, 2026-11-04. Not a migration plan, not a decision record.
Author: model-keeper. Every claim is evidence from the live catalog, an estimate, or an
explicitly labelled proposal. Nothing here was written to the database.

Purpose: decide what the knowledge model should be, given what the live catalog actually
contains. The design artifact (`docs/planning/schema.dbml`, v0.1) and the implementation
(`catalog/models.py`) have diverged in both directions, and the data now shows which parts
of the divergence matter.

## How to read the labels

- **VERIFIED** — a read-only query against `db.sqlite3` on 2026-11-04, or the cited
  repo line. Counts drift: an ingestion campaign is running.
- **ESTIMATE** — arithmetic or judgment from verified facts.
- **PROPOSAL** — a recommendation, not applied or agreed. Schema proposals state cost and
  reversibility.

The exact read-only query pattern is in the appendix. No migration, management command,
import, or test ran against the catalog.

## 0. Live snapshot

Queried 2026-11-04 ~16:30 local. The campaign was active: `ImportRun` 86–90 all started
that day (newest 21:27Z), and run 85 has been `running` since 2026-10-29 with zero items.
**VERIFIED**

| Object | Count | Note |
|---|---|---|
| Work | 13,878 | public 7,452, draft 6,426, suppressed 0 |
| Version | 7,643 | 7,641 works have exactly one |
| Release | 6,578 | 6,575 non-demo |
| Agent | 13,124 | 5,954 OL key, 7,167 Wikidata, 3 neither |
| Credit | 19,603 | |
| ExternalIdentifier | 21,904 | ol_work 10,731, wikidata 8,384, imdb 2,458, tvmaze 328 |
| WorkRelationship | 4,504 | **all** `accepted` |
| RelationshipType | 56 | 9 used, 47 empty |
| ImportRelationshipProposal | 4,849 | 3,777 approved, 1,062 pending, 10 rejected |
| FieldEvidence | 42,349 | 41,622 current, 0 human-reviewed |
| SourceRecord | 14,075 | OL 5,500, Wikidata 8,555, Wikipedia 20 |
| Source | 6 | 4 of 6 are mock |
| WorkSource | 13,878 | one per work, free-text note |
| WorkRedirect | 0 | merge machinery never used |
| Term / WorkTermAssignment | 0 / 0 | vocabulary never populated |
| ContributionProposal / Revision | 0 / 0 | community workflow never used |
| AccessLink | 32 | all active; 0 `last_checked`, 0 `reviewed_at` |

Two corrections to the briefing. The implementation is **30 Django models in 1,015 lines**,
not ~20: 24 catalog models plus six product models (`catalog/models.py:159-226`,
`:973-1015`). **VERIFIED** And accepted relationships were 4,197 when the briefing was
written, 4,504 now (~307 added this session); the ratio that matters is stable —
`derivative-work` 2,268 and `based-on` 1,568 against `adapted-from` 2. **VERIFIED**

## 1. Observed model vs designed model vs what the data needs

| Entity | Implemented | In schema.dbml | Needed | Why it matters |
|---|---|---|---|---|
| Work | Yes `:20-124` | `works` `:121-141` | Yes | Implementation lacks `subtitle`, `sort_title`, `notes`, `creation_method`, `word_count`, `estimated_minutes`. |
| WorkType | Yes `:11-17` | `work_types` `:113-119` | Yes, wrong vocabulary | 15 codes, no `is_container`, no season/episode/story/collection/trailer code. Seasons and collections already exist typed as `creative-work`/`literary-work`. |
| Version | Yes `:251-268` | `versions` `:143-165` | **Contested** | 7,641 works have exactly one version; labels are generated; the only translation is demo. Today it is a required parent for `Release`, not an identity layer. |
| Release | Yes `:271-282` | `releases` + `book_release_details` `:167-200` | Yes | The real bibliographic unit: 6,522 dated, 6,306 with publisher statement, 1,076 versions with >1 release. |
| Credit | Yes `:238-248` | `credits` + `credit_roles` `:267-288` | Yes | Role is free text; targets are works only, so translators and publishers have nowhere to go. |
| Agent | Yes `:228-235` | `agents` `:250-265` | Yes | Identity is split across suppliers (§4). |
| RelationshipType | Yes `:515-522` | `relationship_types` `:227-234` | Yes, but conflated | 47 of 56 unused; `category` does not match semantics (`based-on` and `derivative-work` are category `reference`, while every real derivation code is `derivation` and unused). |
| WorkRelationship | Yes `:525-599` | `work_relationships` `:236-248` | Yes, wrong shape | One source, one review status, one evidence blob, unique on (from,to,type). No `source_version_id`. |
| WorkRedirect | Yes `:127-156` | `catalog_records.redirect_to_id` `:106` | Yes | **0 rows**: no merge has ever been recorded. |
| ImportedWorkState | Yes `:310-316` | Absent | Yes | Last accepted supplier values; without it re-import overwrites editorial edits. 13,875 rows. |
| FieldEvidence | Yes `:947-970` | Absent (`citations` `:433-447` nearest) | Yes | The only field-level provenance; bounded to 3 fields `:968`; 0 reviewed. |
| ImportRun / ImportItem | Yes `:319-347` | `import_runs` `:401-413`; items absent | Yes | Run status can lie: run 85 `running` since 10-29. |
| WorkSource | Yes `:362-368` | Absent | **No** | 13,878 rows whose free-text note restates `ExternalIdentifier` ("Open Library dump work OL3489821W; snapshot 2026-10-21"). Redundant. |
| AccessLink | Yes `:371-418` | `external_links` `:353-366` | Yes | 32 rows; 20 are catalog links, not access. |
| Term / WorkTermAssignment | Yes `:421-512` | `terms`/`record_terms` `:317-336` | Deferred | 0 rows. Harmless placeholders. |
| Relationship evidence | JSON only | `citations` `:433-447` | Yes | Three incompatible JSON shapes, no version marker (§3). |
| catalog_records supertype | **No** | `:99-111` | **No** | Only pays off if citations, revisions, proposals target any kind. None is built. |
| work_components | **No** | `:202-213` | **Yes** | The only way to say "this story is in that collection" or "this episode is in that season". Live data has both (§6.3, §6.4). |
| release_contents | **No** | `:215-225` | Later | Needs components first. |
| languages / record_languages | **No** | `:302-315` | **Yes, now** | `Version.language` is free text with 77 raw values mixing names and QIDs. |
| record_names | **No** | `:290-300` | Yes | Search reads aliases from cached supplier JSON in Python (`docs/trustworthy-catalog-discovery.md:139-142`). |
| rights_statements | **No** | `:449-466` | **Yes** | `Work.image_license` is 120 chars of free text; 37 rows say "Public domain" with no jurisdiction, scope, or basis (§5). |
| record_revisions / change_proposals | Partly (0-row `ContributionRevision`, 3,869 `LibraryEvent`) | `:585-619` | Partly | No generic history; relationship history is JSON on 72 rows. |
| citations | No | `:433-447` | Yes | Split in the implementation into `FieldEvidence` (3 fields) and `Source` (6 supplier rows). |
| media_assets | Partly: 5 columns on `Work` | `:368-385` | Later | 41 works have images; the columns belong on an asset row. |

The implementation is **not** a subset of the DBML: it has four load-bearing things the
DBML lacks (field evidence, imported-input state, import items, durable merge pointers), and
the DBML has three the data has outgrown the alternative for (components, languages,
rights).

**ESTIMATE**: of the 37 DBML tables, 15 are implemented or immediately needed, 14 are
premature, and 8 are designed but unimplemented in a way that already costs work. §8
breaks this down.

## 2. Entity boundaries

Implemented line: **Work** = distinct creation (`schema.dbml:14`); **Version** =
translation/cut/revision/dub/original (`catalog/models.py:254`); **Release** =
publication of a version (`:271-282`); everything else is a relationship (`:525`) or
nothing.

**VERIFIED** facts that decide this section:

- 7,641 works have exactly 1 version; 1 work (demo 1001) has 2; 0 have more. 6,236 works
  have none.
- Kinds: `unresolved` 5,500, `original` 2,142, `translation` 1 (demo).
- Only **6 distinct version labels** exist: `"<Language>-language editions"` ×5,500,
  `"<Language> work"` ×2,139, four one-off demo labels. Labels are generated.
- All 7,643 versions are `page_mode = embedded`; 7,641 have a language; **4** have a date.
- `Version.language` mixes names and QIDs: `"English"` 5,791, `"Q1860"` 1,029, `"Q7737"`
  118, `"Q150"` 110, `"Spanish"` 28 — 77 distinct values for well under 40 languages.
- Zero Open Library payloads contain `translated_from` (0 of 5,500).
- Releases per work: 4,425 works have 1, 2,150 have 2.

So the implemented Version is a **pass-through bucket**. That is not a bug — the DBML
anticipated unresolved versions (`:20-21`) — but the model buys nothing for 5,500 rows and
hides the distinction that matters: a 1970 reprint and a 1970 translation look identical.

### Where the line is wrong

1. **Version is mandatory but not semantic.** Release creation forces a version, so
   importers synthesize one; the "unresolved" placeholder became 72% of the table.
   **PROPOSAL**: make `Release.version` nullable, or add `version_identified`; a null
   version means "attached to the work only". Cost: one nullable FK or boolean, no data
   migration; reversible.
2. **Seasons are untyped, unparented works.** `Game of Thrones, season 2/3/4` (13449,
   13447, 13292) are `creative-work`, draft, with zero relationships, and no series work
   exists. **PROPOSAL**: add `tv_season`, `tv_episode`, `story_collection`, `short_story`,
   `trailer` codes plus `is_container`, and express membership in a component table.
3. **Containment is smuggled into sequence.** The 19 `part-of-series` edges carry four
   meanings (§6.3): book series, fictional canon, franchise typed as a novel, and a TV
   anthology that broadcast a film.
4. **Translation lives in two places and neither works.** The DBML puts it in versions
   (`:15`, `:147`); the vocabulary also has `translation-of` with **0 edges** (`edition-of`
   has 1). Nothing records a translated-from language.
5. **Edition is doing version's job, harmlessly.** 1,076 versions carry 2 releases, which
   matches the DBML's rule (`:164`). `Release.edition_name` (`:274`) is almost never
   populated; `format` (943) and `publisher_statement` (6,306) do the distinguishing, and
   nothing separates "revised edition" from "second printing". Defer.
6. **Performance has no entity.** 394 works carry `date_kind = first_performance` (128
   operas, 84 musicals, 23 ballets), but `Version.kind` has no `performance` and credits
   cannot target a version. **ESTIMATE**: no performance records exist yet — defer, but do
   not add the kind before `credits.target` is extended.

### A decision rule contributors can apply

Answer in order; stop at the first yes.

1. **Would a reader expect its own page, and can it be credited or adapted on its own?**
   → **Work** (film, episode, short story, trailer, game).
2. **Is it a different text/performance of the same creation** — translation, cut, dub,
   restoration, abridgement? → **Version**, one unresolved version allowed per work.
3. **Is it a different issuance of the same version** — publisher, imprint, format, date,
   region, printing? → **Release**.
4. **Does it exist only as a slot in a larger whole** and cannot be adapted alone (chapter,
   track, segment)? → a **component row**; never a Work, never a relationship.
5. **Is it a container with no creation of its own** (series brand, franchise, canon,
   broadcast strand)? → **not a Work**. A container work only if it has real members and
   its own page; otherwise it is a term.

Two guard-rails: never infer a version from a title, publisher, or language string
(language values are unnormalized, so a "language difference" is usually an encoding
difference); never merge on title+year (§6.5).

## 3. Conflict, uncertainty and provenance

### What is stored now

`WorkRelationship` (`:525-599`) has one `source` FK, one `scope_note`, one
`review_status` (`accepted`/`unreviewed`/`disputed`), one `authorization_status`, one
`evidence` JSON, unique on (from, to, type) (`:538`). Public reads filter
`review_status='accepted'` (`catalog/connections.py:93`).

**VERIFIED** on the live table:

- 4,504 of 4,504 are `accepted`; `unreviewed` and `disputed` are unused. No disagreement
  record exists anywhere.
- `authorization_status` is `unknown` for all 4,504.
- `source` is **not a citation**: 4,502 point at the single `Source` row "Wikidata", two at
  mock sources. Six `Source` rows serve 14,075 `SourceRecord` rows and 4,504 claims.
- `evidence` has **four shapes with no version marker**: 3,774 rows of Wikidata statement
  metadata (`asserted_by`, `entity_id`, `property_id`, `statement_id`, `rank`,
  `qualifiers`, `references`, `retrieved_at`, `revision_id`, `reviewed_at`); 725
  cache-derived rows (`property`, `derived_qid`, `source_qid`, `retrieved_via`); 2 empty; 3
  holding only `correction_history`/`source_invalidated`.
- `qualifiers` non-empty on 252 rows; `references` on 1,584. `evidence_history` on 72;
  `correction_history` 3; `direction_repaired_at` 69; `edge_subject` 359.
- `evidence.source_url` resolves to the `from_work` in 4,140 rows, to the `to_work` in
  **359**, neither in 5. The 359 are the direction-repaired rows: the statement was
  asserted on the target and the edge was flipped, and only 359 rows say so.
- All 2,268 `derivative-work` rows carry the scope note `"Wikidata P144 (based on)
  assertion; editor approved."`, inherited from the approval default at `:631`, even
  though those edges came from P4969. 3,777 rows share that identical string.

### The finding that changes the design

**VERIFIED**: 752 work pairs carry two accepted relationships, and in **752 of 752**
cases the pair is `based-on` + `derivative-work`. The 4,504 rows encode about **3,752
distinct claims**: P144 ("derivative → source") and P4969 ("source → derivative") are one
real-world assertion recorded twice under two type codes.

That is the inverse of the conflict problem. The model cannot say "these two rows are one
claim, seconded by two properties", and it cannot say "these two rows disagree". Both are
the same missing idea: a **claim is not a row**.

### Minimum mechanism (PROPOSAL)

One assertion table with a closed predicate vocabulary — not EAV:

```
Assertion
  id
  subject_kind, subject_id        # work | version | release | agent
  predicate_kind                  # relationship | field | classification
  relationship_type_id            # FK when predicate_kind = relationship
  object_work_id / object_value   # exactly one, check-constrained
  source_id, source_record_id     # both exist today
  external_statement_id           # Wikidata statement id, unique per source
  confidence                      # stated | probable | possible | unknown
  review_status                   # accepted | unreviewed | disputed | rejected
  qualifiers                      # JSON, allowlisted keys only
  asserted_at, retrieved_at, reviewed_at, reviewer_id
  supersedes_id, disputed_by_id   # self-FKs; corrections, not deletion
```

Five rules keep it from becoming EAV:

1. `qualifiers` accepts only a documented key set — `source_version`, `scope`
   (chapters/tracks/discs), `date_precision`, `approximate`, `statement_rank`. Anything
   else stays in `evidence` for display and is never queried. `citations.locator` (`:439`)
   already implies this.
2. One row per (subject, source, `external_statement_id`); re-ingesting updates
   `retrieved_at`.
3. Two rows are "the same claim" when subject, object, and **predicate family** agree. Add
   `RelationshipType.claim_family` (or `canonical_code`) so `based-on` and
   `derivative-work` share one family; that column alone removes 752 rows from every count.
4. "Disputed" belongs to an assertion pair, not a work: a doubtful edge can stay
   `disputed` while its well-supported sibling stays `accepted` — what
   `OpenMediaAtlas-Example-Catalog-v0.1.md:259` asks for.
5. Public filter rule, stated so it can be tested: **a connection is public iff one
   assertion in its family is `accepted`; it renders `disputed` iff an accepted assertion
   in the family has a `disputed_by` link; "N sources" = non-rejected assertions in the
   family.** No policy hidden in views.

Uncertainty has four kinds and must not share one field:

| Kind | Live example | Where it belongs |
|---|---|---|
| No evidence | 2 relationships with empty `evidence` | `review_status = unreviewed` |
| Uncertain identity | three 2008 *Journey…* films | identity/dedupe state |
| Uncertain granularity | `based-on` vs `remake-of` on one pair | `confidence` + `claim_family` |
| Disputed truth | none yet — `disputed` unused | `review_status = disputed` + `disputed_by` |

Revision history: do **not** copy the DBML's snapshot table (`:606-619`). The three
targeted ledgers already work: `FieldEvidence` (one current row per field, `:963-970`),
`ContributionRevision` (0 rows), `LibraryEvent` (`:1000-1015`; 3,777 added / 69 corrected /
3 removed). Two gaps remain: relationship history lives in 72 JSON blobs, and nothing
records *why* 10 proposals were rejected — `ImportRelationshipProposal` has no reason column
(`:602-622`); reasons live only in `docs/proposal-triage-*.json`. **PROPOSAL**: add
`review_note` to both models; one additive migration, no backfill.

## 4. Identifiers

### Four mechanisms — VERIFIED

1. `ExternalIdentifier` (`:648-654`): `work` FK, `scheme`, `value`, unique on
   (work, scheme, value). 21,904 rows. Cannot target versions, releases, or agents; no
   source, review status, normalized value, or format validation.
2. `Agent.openlibrary_key`/`wikidata_id` (`:231-232`), both `unique=True, null=True`;
   5,954 and 7,167 populated. Agents are invisible to `ExternalIdentifier`.
3. `Release.openlibrary_key` (`:279`), unique; 6,575 populated — the whole OL edition key
   space lives here only.
4. `SourceRecord.external_key` plus `WorkSource.note`, restating the same keys again.

### Is it coherent?

Coherent in direction (stable internal IDs canonical, external identifiers separate —
`AGENTS.md`), incoherent in mechanics.

- **Collision.** Uniqueness is `(work, scheme, value)`, so one `(scheme, value)` may sit on
  two works; today **0** such rows — an accident of current importers, not a guarantee.
- **Split identity.** 458 works hold more than one identifier of the same scheme (up to
  **5** `ol_work` keys on work 7329; 12 works with >1 IMDb ID). Agents are worse: 116
  name+kind groups hold 121 extra rows and **713 credits** attach to same-named agents.
  `Alexandre Dumas` exists twice (agent 340 `OL18236A`, 1 credit; 5452 `Q38337`, 13
  credits); `Mark Twain` three times (357, 7444 `Q7245`, 11739 `Q6770075`).
- **Merged records.** No work has more than one `wikidata` ID (repaired 2026-10-29,
  `CURRENT.md:1323-1350`), but `WorkRedirect` is **empty**: the repair deleted and
  re-created rather than redirecting, so external links to the old row are dead and no
  history says why. The redirect path (`:127-156`) has never run on real data.
  **ESTIMATE**: the first real merge will be its first test.

### Target arrangement (PROPOSAL)

```
IdentifierScheme   code, label, target_kind, is_globally_unique, format_regex,
                   normalization_rule, validity_note
Identifier         record_kind, record_id, scheme_code, value, normalized_value,
                   source_id, source_record_id, review_status, supersedes_id
                   unique(scheme_code, normalized_value) where is_globally_unique
                   unique(record_kind, record_id, scheme_code, normalized_value)
```

`is_globally_unique = false` for ISBN (reused in practice — `schema.dbml:350` warns),
`true` for `ol_work`, `ol_edition`, `ol_author`, `wikidata`. Uniqueness is enforced on
`normalized_value`; raw `value` is kept.

**Path**: (1) create the scheme registry and backfill 5 rows, no behaviour change; (2) copy
`Agent.openlibrary_key` (5,954), `Agent.wikidata_id` (7,167), `Release.openlibrary_key`
(6,575) into identifiers — **ESTIMATE** 19,696 rows, one data migration, no network;
(3) add `normalized_value` + partial unique indexes with a dry-run collision detector;
(4) flip reads, keep old columns one release. Risk: step 3 surfaces the 116 duplicate agent
names and 713 credits as data errors — the product question it unlocks: **is the 1-credit
Alexandre Dumas the 13-credit one?** Nothing in the catalog can answer that today.

## 5. Descriptive rights vs permission to reuse

### What is recorded — VERIFIED

- `Work.image_url`/`image_source_url`/`image_attribution`/`image_license` (`:32-35`): 41
  works have all four. Licences: `"Public domain"` 37, `CC0` 1, `CC BY-SA 4.0` 1,
  `CC BY 3.0` 1, `CC BY 2.0` 1.
- `AccessLink.restrictions` (`:393`), free text, blank = unknown: 12 of 32 set.
  `last_checked` (`:395`) 0, `reviewed_at` (`:396`) 0.
- `WorkRelationship.authorization_status` (`:533`): all 4,504 `unknown`.
- `Source` has no `license_statement`, although the DBML provides one (`:396`).
- No `rights_statements` table exists; `docs/field-provenance.md:3` says so: "no license or
  public-domain records exist in the implemented catalog schema."

The non-inference rules are already written and partly enforced:
`catalog/models.py:32` ("never assume rights from availability"), `schema.dbml:271` (a
credit is not proof of rights ownership), `models.py:390`,
`docs/work-access.md:11`, `docs/enrichment-policy.md:94-101`.

What the schema fails to separate is four different questions:

| Question | Kind | Belongs in |
|---|---|---|
| What does a source say about rights for component X in jurisdiction Y? | descriptive claim | `rights_statement` with scope, jurisdiction, basis, source |
| May OMA host/reproduce this asset? | permission act | separate reviewer-gated record; never inferred |
| Can a reader watch/borrow this now? | availability | `AccessLink` (already separate, `:371-372`) |
| Was adaptation permission obtained? | authorization | relationship-level statement, default `unknown` (`:533`) |

The dangerous collapse is `image_license = "Public domain"` (37 rows): a legal conclusion
for an unstated jurisdiction about an unstated component, with no basis and no reviewing
source. The work being PD says nothing about the cover scan; a US determination says
nothing about the UK; the original text says nothing about a translation. **PROPOSAL**: a
small rights table requiring three non-empty fields on any public claim —

```
RightsStatement
  record_kind, record_id     # work | version | release
  component_scope            # original_text | translation | cover_image | audio | whole
  rights_status              # public_domain | licensed | copyrighted | disputed | unknown
  jurisdiction               # ISO code or 'unspecified'; never blank, never 'worldwide'
  license_code, license_url, stated_holder_agent_id
  basis                      # NOT NULL: what establishes this
  source_id                  # NOT NULL
  review_status, reviewed_at
```

— plus `media_asset.reuse_basis`/`license_url` for the image itself (`schema.dbml:368-385`).
**Never** add a `can_reuse` boolean. Public pages render "jurisdiction · component · basis",
and "unknown" is legitimate. Cost: one table, 41 rows, one display change; the old column
stays read-only for one release.

## 6. Five unusual cases from the live data

### 6.1 An adaptation hub — work 6523 *Les Trois Mousquetaires*

**VERIFIED**: `novel`, 1844, public, depth `editorial`, `Q140527`, **two** `ol_work` IDs
(`OL15561436W`, `OL36861W`), 1 credit, **0 versions, 0 releases**, 176 incoming edges (91
`based-on`, 84 `derivative-work`, 1 `follows`) and 2 outgoing. All 84 `derivative-work`
sources are also `based-on` sources: 91 distinct claims in 176 rows — a 48% duplicate rate
on the most-connected work in the catalog, which has no bibliographic layer at all.

Decision: keep both identifiers (a genuine merge candidate, not a collision) and fix
redundancy at the vocabulary level with `claim_family` (§3). Do **not** delete rows — they
carry different Wikidata statement IDs and are legitimate provenance. The public count should
be 91, not 176.

### 6.2 Translation/edition with ambiguous dates — works 5949, 3355, 2913

**VERIFIED**: 5949 *A briefe description of the whole worlde*, 1599, one version labelled
`"English-language editions"` (kind `unresolved`), releases 1970 and 1599. 3355: releases
1697 and 1984, work date empty, `date_evidence.date_text = ""`. 2913: releases 1847 and
2022 under one version.

The model cannot tell a facsimile reprint (same version), a modernized edition (new version
of the same work), or a translation (new version, different language): all three look like
"two releases under one unresolved English version", and translation cannot be tagged — the
only `translation` version is demo.

Decision: keep these as releases of one version unless a source says the text was revised
(then a `revised` version with `based_on_version_id`); never infer from the date gap.
Implement `Version.based_on_version_id` and `is_abridged` (DBML `:148`, `:156`), and
normalize language before "different language" can be an assertion. Note also why dates must
never come from releases: the 1599 work date is OL work-level `first_publish_date`
(`docs/trustworthy-catalog-discovery.md:23-40`), still carried in `date_evidence`.

### 6.3 A season with no series — works 13449 / 13447 / 13292

**VERIFIED**: *Game of Thrones, season 2* (13449, `Q302358`), *season 3* (13447,
`Q3009004`), *season 4* (13292, `Q15643670`) are all `creative-work`, draft, **zero
relationships**, no parent; no *Game of Thrones* series work exists, only the novel 7976.
Siblings: 14752 *His Dark Materials, season 1* (`based-on` 8453), 14612 *Person of Interest,
season 2*, 13811 *Shadow and Bone, season 1* (`based-on` 9836 **and** 10027 — a season
covering two books).

The 19 `part-of-series` edges carry four meanings: 6523 → 6957 (book series); 6518 → 7022
*canon of Sherlock Holmes* (a canon, not a series); 8139 *I, Robot.* → 13773 *Robot* (a
franchise typed `novel`); 6238 *The Wizard of Oz* → 10758 *Family Classics* (a TV anthology
that broadcast it).

Decision: a season is a **container work** with a `WorkComponent` row (`season_of` →
series, `episode_of` → season), not a relationship. `part-of-series` keeps meaning
narrative/bibliographic series membership. Franchises and canons are not works; if they must
be browsable, they are terms. Cost: 2 type codes, `is_container`, one table, a review of 19
edges — the only route to a browsable TV slice (`CURRENT.md:354-370`).

### 6.4 An anthology whose parts exist only in a cached payload — work 13151

**VERIFIED**: *A Song for Lya and Other Stories* (13151), `literary-work`, 1976-02,
`OL1955944W` + `Q2956167`, public, **0 versions, 0 relationships**, 1 source record. Its
cached Wikidata payload contains **P527 (has part)** with at least two statements
(`Q8028024`, `Q48773115`). Neither part is a catalog work and nothing records the
containment; `work_components` and `release_contents` do not exist.

Decision: promote P527 into `WorkComponent(container=13151, component=<new draft work>,
role='story')` only after the component exists as its own draft work with its own
identifier. Do **not** auto-create components from every P527 — a P527 may point at a
chapter, section, or volume, none of which are works. The payload is cached; no network.

### 6.5 A false duplicate and an unrecorded merge — 14116 / 14299 / 14303

**VERIFIED**: *Journey to the Center of the Earth* as `film`, 2008, exists three times —
14116 (`tt1156454`, `Q15622394`), 14299 (`tt1231575`, `Q2478003`), 14303 (`tt0373051`,
`Q250770`) — three different films, all public. Same shape for *Montecristo* 2006 as
`television-series`: 7221 (`Q1247823`), 7337 (`Q6022603`), 14661 (`Q6022597`, draft).

Conversely the 2026-10-29 identity repair found all 14 "duplicates" were two different
works sharing a title, and fixed them by splitting (`CURRENT.md:1323-1350`).
`WorkRedirect` is still empty: the catalog has never recorded a merge, only deletions and
re-creations.

Decision: identity is (scheme, value), never (title, year, type). Add a disambiguation
requirement to the public gate — when title+year+type collide, show a distinguishing fact
(creator, country, identifier) before publication. Make the first real merge use
`WorkRedirect`; the two `ol_work` keys on 6523 are the obvious candidate.

### 6.6 The unknown-title case that does not exist

**VERIFIED**: the fallback exists (`has_known_title` `:84-86`, `display_title` `:98-107`,
refusing to render a bare QID) and **0 works match it** — 0 empty titles, 0 QID-shaped, 0
beginning "Title unknown". Keep the mechanism; do not build a workflow on it. The nearest
real case is a scope question: three drafts titled *Sudoku Genius Mind Exercises Volume 1*
(3309, 3859, 5495), with different `ol_work` keys — non-creative utility books inside a
creative-works catalog.

## 7. Minimal migration proposals, ranked

All are additive and reversible by reverting one migration. None runs against
`db.sqlite3` until separately authorized.

**1. `RelationshipType.claim_family`.** One column, a data migration mapping
`derivative-work` and `based-on` to one family, backfill of 56 rows, read-side grouping.
Risk: low (a wrong family mislabels a count). Reversible: drop the column. Unlocks honest
edge counts (3,752 not 4,504) and meaningful "N sources"; also carries the data-only fix for
the 2,268 wrong `scope_note` strings.

**2. `Assertion` table + `review_note` fields.** One table, one allowlisted qualifier
contract, migration of 4,504 `evidence` blobs into rows (script, no network). Risk: medium
— the migration must not fabricate `confidence`; default existing rows to `stated`, leave
the 725 cache-shaped and 2 empty rows as `unknown`. Reversible: keep `evidence` JSON for
two releases. Unlocks competing sources, visible disagreement, per-claim review, and the
public filter rule in §3.

**3. Containment: `WorkType.is_container`, 5 type codes, `WorkComponent`.** One boolean,
five vocabulary rows, one table with a unique constraint on (container, component, role)
and a cycle check. Risk: low mechanically, medium politically — it forces a decision on the
19 `part-of-series` edges. Reversible: drop the table and codes; relationships untouched.
Unlocks three of the five cases in §6.

**4. Identifier consolidation (§4).** Scheme table, identifier table, ~19,696 copied rows,
partial unique indexes, a dry-run detector. Risk: **highest of the six**, because the
detector surfaces the 116 duplicate agent names and 713 credits as data errors. That is the
point, but it needs a review queue before reads flip. Reversible: the copy is additive; old
columns stay one release. Unlocks "is this the same person?" and any future merge tool.

**5. Language normalization.** One lookup (~40 rows), one normalization pass over 77 raw
values to BCP-47, raw strings preserved in payload/evidence, free-text column deprecated.
Risk: low — 77 values are reviewable by eye. Reversible: keep the old column. Unlocks
language filtering, translation detection, and the only route to a real `translation` kind.

**6. Rights separation (§5).** `RightsStatement`, `media_asset.reuse_basis`/`license_url`,
41 rows migrated, a display rule always showing jurisdiction + component. Risk: low volume,
high semantic risk — `"Public domain"` must land as `jurisdiction='unspecified'`,
`review_status='unreviewed'`, never as a verified determination. Reversible: drop the table,
keep the string.

Not proposed: generic `record_revisions` snapshots, a `catalog_records` supertype, full
term/alias infrastructure (0 rows of demand), performance/character entities. One
non-schema fix is cheaper than all six: **stop writing `WorkSource` rows with free-text
external keys** — a one-line importer change.

## 8. Critique of `schema.dbml` v0.1

Keep the header: "a design artifact, NOT a production migration" (`:1-3`), "Kinds and roles
below are suggested seed values, not settled product policy" (`:4`). The eleven
implementation rules (`:34-61`) are better than most production schema docs: 2, 3, 6, 7, 11
are visible in behaviour, while 5 (revision snapshots) and 4 (`source_version`) are not
implemented at all.

Of the 37 tables:

**Justified now — 15.** `work_types`, `works`, `versions`, `releases`,
`book_release_details`, `relationship_types`, `work_relationships`, `agents`, `credits`,
`credit_roles`, `sources`, `import_runs`, `source_records`, `identifiers`,
`external_links`. Four are under-specified:

- `works` (`:121-141`) lacks a disambiguation key and `is_container`; it carries
  `creation_method` and `estimated_minutes`, which no page uses.
- `versions` (`:143-165`) makes translation the paradigm case for a catalog with zero real
  translations. Implement `based_on_version_id` and `is_abridged` first.
- `credits` (`:274-288`) allows version/release targets; the implementation restricts them
  to works (`:239`), so translators and publishers have no home.
- `identifiers` (`:338-351`) has the right fields and a half-measure uniqueness story: it
  warns identifiers are not globally clean (`:350`) then defines only per-record
  uniqueness. Finish it with a scheme registry (§4).

**Designed but unimplemented, already costing work — 8.** `work_components` (`:202-213`),
`release_contents` (`:215-225`), `languages`/`record_languages` (`:302-315`),
`record_names` (`:290-300`), `citations` (`:433-447`), `rights_statements` (`:449-466`),
`media_assets` (`:368-385`), and `sources.license_statement` (`:396`).

**Premature — 14.** `catalog_records` (`:99-111`), `terms`/`record_terms` (`:317-336`),
`rights_claims` (`:468-484`), `project_declarations` (`:486-498`), `users` (`:500-508`),
`lists`/`list_items` (`:510-532`), `user_work_states` (`:534-547`), `saved_searches`
(`:549-558`), `discussion_threads`/`comments` (`:560-583`), `change_proposals` (`:585-604`),
`record_revisions` (`:606-619`).

- `catalog_records` is the biggest bet: a shared anchor for citations, revisions, and
  proposals. Defensible *if* all three are built; none is. Keep the concept for citations,
  not as the identity scheme.
- `record_revisions` snapshots whole aggregates (`:614`). The three targeted ledgers cost
  less and answer the questions the pages ask; adopt snapshots only when "this record at
  revision N" is a product requirement.
- `change_proposals` is a generic patch language (`:603`); the three specific proposal kinds
  (`ContributionProposal` `:656`, `ImportRelationshipProposal` `:602`, `WorkTermAssignment`
  `:446`) are less clever and safer. Do not replace them.
- `terms`/`record_terms` are the right shape with 0 rows after five weeks — evidence the
  vocabulary is not yet a product need, not evidence the tables are wrong.

**Missing from the DBML itself — 9**, each already costing something: a field-level
evidence ledger; imported-input state; import item outcomes and a rejection reason; durable
merge audit (it has only `redirect_to_id`); a claim layer distinct from `citations` (which
attaches to a record, not a claim); `claim_family` on `relationship_types`; per-claim
confidence; a scheme registry for identifiers; and any statement of which fields are
protected from re-import (`OpenMediaAtlas-Example-Catalog-v0.1.md:219`).

One decision the DBML gets right and should not be revisited: versions and releases stay
embedded by default, and presentation (`page_mode`) never changes identity (`:158-160`,
`Schema-Reconciliation-Milestone-1.md:5-7`).

## 9. Open questions for the next session

1. **Should `Version` survive?** 7,641 works have exactly one, the label is generated, and
   the only translation is demo. Either make it optional or make it editorial-only. Every
   other decision (translation, cuts, performance, `source_version`) hangs off the answer.
2. **Is `based-on` the same claim as `derivative-work`?** The data says yes (752/752); the
   source-precedence rule is an editorial decision, not a fact.
3. **May a season be public without its series?** Three seasons are draft with no parent,
   and the public gate (`OpenMediaAtlas-Permissions-Matrix-v0.1.md:60-74`) is silent on
   containers.
4. **What is the first recorded merge?** `WorkRedirect` has never been used; work 6523 is
   the natural test.
5. **Who owns the agent-identity decision?** 116 duplicate names and 713 credits are live;
   the schema cannot fix them, and proposal 4 will surface them.

## Appendix: re-verifying this document

Read-only; never run migrations, management commands, or writes. From the repo root:

```sh
cd open-media-atlas
DJANGO_DEBUG=true .venv/bin/python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oma.settings")
django.setup()
from django.db.models import Count
from catalog import models as m
print(m.Work.objects.count(), m.Work.objects.filter(visibility="public").count())
print(list(m.WorkRelationship.objects.values("relationship_type_id").annotate(n=Count("id")).order_by("-n")))
print(list(m.WorkRelationship.objects.values("review_status").annotate(n=Count("id"))))
PY
```

Counts drift while the campaign runs; re-run them before quoting this document. File:line
references are to `catalog/models.py` (1,015 lines, 30 models),
`docs/planning/schema.dbml` (767 lines, 37 tables), and
`docs/planning/OpenMediaAtlas-Example-Catalog-v0.1.md`.

# OpenMediaAtlas: example catalog and model walkthrough

Draft 0.1 · Companion to `OpenMediaAtlas-v0.1.dbml` and the page-and-action map · 20 September 2026

**All titles, people, organizations, dates, identifiers and evidence below are synthetic fixtures.** They are deliberately fictional so we can test modeling choices without silently inventing facts about real works. Do not publish them as real catalog entries. They are selected records, not a complete production seed or executable import.

## 1. What the identifiers mean

For objects with a shared catalog identity, the numeric ID appears in `catalog_records` and in exactly one typed table. For example, work 1001 has a registry row with `kind = work` and a `works` row with `id = 1001`. IDs here are arbitrary, not encoded category rules.

The fixture assumes registry records are public, at local revision 1, with no redirects, except where a later scenario explicitly changes that. Auxiliary row IDs (citations, terms, sources, list entries) belong only to their respective tables. Initial records would also receive revision snapshots in a runnable seed.

## 2. The small catalog

### Works

| ID | Title | `work_type_code` | Date text | Status | Purpose |
|---|---|---|---|---|---|
| 1001 | The Glass Orchard | novel | 1912 | released | Source novel with translations and adaptations. |
| 1002 | The Glass Orchard | film | 1978 | released | First film adaptation. |
| 1003 | The Glass Orchard | film | 2025 | released | Another adaptation of the novel; remake status unproven. |
| 1004 | Beyond the Orchard | film | 2027 | planned | Announced sequel to 1003; no available release yet. |
| 1005 | Roads After Rain | story_collection | 1930 | released | Collection of independent stories. |
| 1006 | The Last Passenger | short_story | 1928 | released | Story first published before the collection. |
| 1007 | A Window Facing North | short_story | 1929 | released | Another collection member. |
| 1008 | Night Route | short_film | 2024 | released | Combines two source stories. |
| 1009 | Harbor Signals | tv_series | 2018 | cancelled | Cancelled series. |
| 1010 | Harbor Signals: Season One | tv_season | 2018 | completed | Container inside the series. |
| 1011 | The Empty Lighthouse | tv_episode | 2018 | released | One episode in the season. |
| 1012 | Harbor Signals: One More Tide | web_video | 2026 | released | Fan continuation; permission unverified. |
| 1013 | A Window Facing North — Animation | web_video | 2026 | released | Five-minute animation that actually dramatizes a story. |
| 1014 | Night Route — Trailer | trailer | 2024 | released | Promotional work; not counted as another completed film. |
| 1015 | Rivers Beneath the City | nonfiction_book | 2020 | released | Nonfiction with an interactive adaptation. |
| 1016 | Understreet | video_game | 2026 | released | Playable nonfiction; exact format classification is provisional. |
| 1017 | Another Route | web_video | — | in_progress | Creator-declared story adaptation, not finished or released. |

Seed the matching `work_types` codes before these rows. Proposed media: text for the book/story forms, screen for film/TV/video/trailer, interactive for 1016. `is_container = true` for the story collection, series and season. Optional descriptions, word counts, creation methods and rights remain unknown unless supplied by evidence.

### People and organizations (`agents`)

| ID | Name | Kind | Role in the fixture |
|---|---|---|---|
| 2001 | Mara Vale | person | Author of 1001 and 1005–1007. |
| 2002 | Julien Marchand | person | Translator of one version of 1001. |
| 2003 | Rowan Press | organization | Publisher of several releases. |
| 2004 | Lena Ortiz | person | Director of 1002. |
| 2005 | Harborlight Pictures | organization | Production company for 1003. |
| 2006 | Nia Sol | person | Creator of 1008. |
| 2007 | Eli Moss | person | Creator of fan continuation 1012. |
| 2008 | Ada Reed | person | Author of nonfiction work 1015. |
| 2009 | Fieldnote Studio | organization | Developer of 1016. |

These are public identities, not user accounts. One person can have several roles without needing several agent rows.

### Versions

| ID | Work | Kind | Label / localized title | Based on version | Runtime |
|---|---|---|---|---|---|
| 1101 | 1001 | original | Original English text | — | — |
| 1102 | 1001 | translation | Marchand translation / Le Verger de verre | 1101 | — |
| 1103 | 1002 | original | Theatrical cut | — | 6,000 seconds |
| 1104 | 1002 | cut | Director's cut | 1103 | 6,600 seconds |
| 1105 | 1005 | original | Original collection text | — | — |
| 1106 | 1006 | original | Original story text | — | — |
| 1107 | 1007 | original | Original story text | — | — |
| 1108 | 1013 | original | Released animation | — | 300 seconds |
| 1109 | 1015 | original | Original text | — | — |
| 1110 | 1001 | unresolved | Translation/version not identified in imported record | — | — |

Versions are not required for every initial work entry. Do not invent a theatrical cut, language or translation just to fill the diagram. A release needs a version in this draft; 1110 explicitly records that identification is unresolved.

### Releases and book details

| ID | Version | Title | Edition name | Format | Publication date | Pages |
|---|---|---|---|---|---|---|
| 1201 | 1101 | The Glass Orchard | First edition | hardcover | 1912 | 248 |
| 1202 | 1102 | Le Verger de verre | Marchand translation | paperback | 2002 | 276 |
| 1203 | 1102 | Le Verger de verre | Digital release | ebook | 2016 | — |
| 1204 | 1103 | The Glass Orchard | — | theatrical | 1978 | — |
| 1205 | 1104 | The Glass Orchard | Director's cut | bluray | 2008 | — |
| 1206 | 1105 | Roads After Rain | First edition | hardcover | 1930 | 190 |
| 1207 | 1107 | A Window Facing North | Standalone digital release | ebook | 2019 | — |
| 1208 | 1110 | The Glass Orchard | Imported edition; details incomplete | paperback | 1990 | — |

Pages live in `book_release_details`, not `releases`. Do not turn ebook page counts or physical dimensions into invented values. The exact source date string is preserved; a year-only date is not converted into January 1.

### Credits

These are shared catalog records with `kind = credit`; seed matching `credit_roles` first. Each target has a real registry foreign key.

| Credit ID | Target record | Agent | Role | Extra |
|---|---|---|---|---|
| 2101 | 1001 | 2001 | author | — |
| 2102 | 1102 | 2002 | translator | Credited as “J. Marchand.” |
| 2103 | 1202 | 2003 | publisher | — |
| 2104 | 1203 | 2003 | publisher | Same publisher, different release. |
| 2105 | 1002 | 2004 | director | — |
| 2106 | 1003 | 2005 | production_company | Does not establish copyright ownership. |
| 2107 | 1008 | 2006 | director | — |
| 2108 | 1012 | 2007 | director | — |
| 2109 | 1015 | 2008 | author | — |
| 2110 | 1016 | 2009 | developer | — |

Additional author credits for 1005–1007 can be generated in an implementation fixture; their omission here means this is a selected slice rather than a complete bibliography.

## 3. Relationship records

`from_work_id` is the derived/later work; `to_work_id` is its source/prior work. Display arrows may face the other way with different wording.

| Relationship ID | From | Type | To | Exact source version | Review status | Evidence source |
|---|---|---|---|---|---|---|
| 3001 | 1002 | adapted_from | 1001 | — | accepted | 7001 |
| 3002 | 1003 | adapted_from | 1001 | — | accepted | 7002 |
| 3003 | 1004 | sequel_to | 1003 | — | accepted | 7002 |
| 3004 | 1008 | adapted_from | 1006 | 1106 | accepted | 7003 |
| 3005 | 1008 | adapted_from | 1007 | 1107 | accepted | 7003 |
| 3006 | 1012 | continuation_of | 1009 | — | accepted | 7004 |
| 3007 | 1013 | adapted_from | 1007 | 1107 | accepted | 7005 |
| 3008 | 1014 | trailer_for | 1008 | — | accepted | 7003 |
| 3009 | 1016 | adapted_from | 1015 | 1109 | accepted | 7006 |

All authorization statuses are **unknown** in this fixture. Acceptance means the stated relationship has been reviewed; it is not evidence that adaptation permission was obtained. Attach the evidence through `citations`; `work_relationships` does not contain a `source_id` field itself.

### Containment is different

| `container_work_id` | `component_work_id` | Component role | Sequence label | Source |
|---|---|---|---|---|
| 1005 | 1006 | story | 1 | 7007 |
| 1005 | 1007 | story | 2 | 7007 |
| 1009 | 1010 | season | 1 | 7008 |
| 1010 | 1011 | episode | 1 | 7008 |

Specific release contents are more precise:

| `release_id` | `contained_version_id` | Sequence | Location |
|---|---|---|---|
| 1206 | 1106 | 1 | Pages 9–31 |
| 1206 | 1107 | 2 | Pages 33–58 |

A collection is not the author of its stories, and the stories are not adaptations of the collection. A later collection can contain those same story works without duplicating them. Changes in a particular edition's contents belong at release level.

## 4. Classification and language examples

### `terms`

| ID | Vocabulary | Label | Normalized label | Parent |
|---|---|---|---|---|
| 4001 | genre | Speculative fiction | speculative fiction | — |
| 4002 | genre | Science fiction | science fiction | 4001 |
| 4003 | tone | Unsettling | unsettling | — |
| 4004 | subject | Memory | memory | — |
| 4005 | technique | Animation | animation | — |
| 4006 | subject | Urban infrastructure | urban infrastructure | — |

### `record_terms`

| Record | Term | Assignment method | Review status |
|---|---|---|---|
| 1001 | 4002 | editorial | accepted |
| 1001 | 4003 | editorial | accepted |
| 1001 | 4004 | imported | accepted |
| 1013 | 4005 | editorial | accepted |
| 1015 | 4006 | editorial | accepted |
| 1016 | 4006 | editorial | accepted |

These invented classifications are examples of mechanics, not literary claims. Genre/tone tags should not automatically transfer from a book to every adaptation. Parent matching requires an explicit search rule; a foreign key alone does not make a parent filter include descendants. Term synonyms such as “sci-fi” are not modeled yet.

Seed `languages` with `en` (English) and `fr` (French). Assign:

| Record | Language tag | Role |
|---|---|---|
| 1001 | en | original |
| 1101 | en | text |
| 1102 | fr | text |
| 1102 | en | translated_from |

The French version is discoverable through an English-language work page. Do not infer the original language merely from the first edition imported.

## 5. Evidence, rights and import fixtures

### Evidence sources (`sources`)

These are mock source descriptions, with no invented real URLs. In a working fixture they would point to local mock documents. Real production claims require real evidence.

| ID | Kind | Title / purpose |
|---|---|---|
| 7001 | webpage | Mock 1978 film credits naming the source novel. |
| 7002 | webpage | Mock studio catalog and sequel announcement. |
| 7003 | webpage | Mock Night Route credits naming two stories and its official trailer. |
| 7004 | creator_submission | Mock fan-creator statement identifying a continuation. |
| 7005 | webpage | Mock animation credits naming the short story. |
| 7006 | webpage | Mock developer statement explicitly identifying the nonfiction adaptation. |
| 7007 | book | Mock contents page of the 1930 collection. |
| 7008 | webpage | Mock television episode guide. |
| 7009 | dataset | Mock book metadata feed used for repeated imports. |
| 7010 | legal_record | Mock original-text rights assessment, US only. |
| 7011 | book | Mock translation copyright/credits page. |

### Rights statements

| ID | Target | Status | Jurisdiction | Component | Stated holder | Review |
|---|---|---|---|---|---|---|
| 6001 | 1001 | public_domain | US | original_text | — | accepted |
| 6002 | 1102 | copyrighted | unspecified | translation | 2002 | unreviewed |

For 6001, `basis` cites the **fictional assessment**, with citation to source 7010. This is not a real legal conclusion deduced from the made-up date. For 6002, the basis is the mock page from 7011. Unknown ownership details remain unknown; a translator credit alone is insufficient.

No reuse permission has been supplied for the cover, soundtrack, film or fan continuation. Rights statements do not inherit globally from the novel to related records. The public work page may summarize 6001, but must retain “US” and “original text.”

### Import and correction sequence

1. Import run 7101 uses source 7009 and dataset version `fixture-a`. Raw source record 7201 has `external_key = mock-edition-004`, matched to release 1208. Its payload gives only title, paperback format, and year 1990. This is a mock supplier key, not a fake ISBN or OL identifier.
2. Record 7201 retains its raw payload, hash, last run, and match status. Version 1110 remains unresolved. The import does not invent a translator.
3. User 8001 proposes correction 9001 against release 1208 revision 1: change its publication date text to `1991`, attach evidence, explain the correction. It remains pending until review.
4. On acceptance, release 1208 and its registry revision are updated atomically; accepted snapshot 9101 records local revision 2 and the approved child/evidence changes.
5. The original supplier repeats `1990`. The existing source key identifies the same source record. No duplicate public release is created, and the importer must not blindly overwrite `1991`.
6. A genuinely new conflicting source value becomes a review item or proposal. Imported upstream revision and OpenMediaAtlas's local revision counter are separate concepts.

This scenario reveals a missing implementation detail: the schema has provenance and snapshots, but **does not yet explicitly store per-field protection or source precedence**. Decide whether to add a field-state table or implement a documented policy using revision history. Merely storing `source_records` does not make conflict reconciliation work.

## 6. Community fixtures

| Object | Example |
|---|---|
| User 8001 | `orchard_reader`, an ordinary member; not automatically Mara Vale or any represented creator. |
| User 8002 | `film_reviewer`, with reviewer permission supplied by the auth system. |
| List 8101 | “One story, several screens,” owned by 8001, public, containing works 1001, 1002 and 1003 in that order. |
| Saved-work state | User 8001 saves work 1006 and wants an adaptation. A rating may remain null; a private note stays private. |
| Thread 8201 | On relationship record 3002: “Is this also a remake of the 1978 film?” |
| Comment 8301 | User 8001 asks for evidence; user 8002 can reply in the same thread. No new remake relationship is created just because the question exists. |
| Project declaration 8401 | User 8001 declares “Another Route,” source work 1006, resulting work 1017, status `developing`. This is non-exclusive and not proof of permission. |

A wish for adaptation does not reserve the work. A public list does not expose the owner's private notes. A discussion about a relationship can stay attached to that relationship rather than being mistaken for a factual citation.

## 7. Walkthroughs: what the visitor should see

| Case | Expected presentation | Mistake this prevents |
|---|---|---|
| 1001, source novel | One work page; two film adaptation cards; original and French translation expandable below. | Treating paperback, ebook, and translation as three unrelated novels. |
| 1002, first film | Source novel plus theatrical/director cuts; runtime qualified by version. | Claiming one exact runtime applies to every cut. |
| 1003, second film | Source novel and planned sequel. No arrow from 1002 unless remake evidence is accepted. | Assuming shared title means remake. |
| 1006, story | “Appears in Roads After Rain”; Night Route as an adaptation; project declaration labeled in development. | Hiding adaptable stories inside anthology records or counting declarations as completed films. |
| 1008, short film | Two source-story cards with scope notes; trailer in a separate promotional area. | Forcing derivation into a single-parent tree or counting a trailer as another film adaptation. |
| 1009, cancelled series | Cancellation status, season/episode navigation, separately labeled fan continuation. | Treating every continuation as official or assuming fan work is unauthorized. |
| 1013, short animation | Eligible as an adaptation because it dramatizes the story, despite its duration or production quality. | Using professionalism as the definition of a work. |
| 1015, nonfiction book | Explicitly sourced playable adaptation 1016. A video merely sharing facts is not automatically linked as an adaptation. | Conflating shared subject matter with derivation. |
| 1208, incomplete release | Nested under unresolved version 1110 on the novel page, with uncertainty visible. | Inventing translator/cut identity from incomplete metadata. |

Ordinary reviews/commentary and casual mentions are excluded by default in this fixture. Whether a substantial critical work deserves its own catalog entry is an editorial scope decision, not something the relational schema can decide.

## 8. Duplicate and disagreement checks

**Same title, different work:** 1001, 1002 and 1003 share a title but have distinct forms/dates/credits. They must not merge based on title similarity.

**Same translation, different release:** 1202 and 1203 share version 1102. A changed publisher or binding alone should not create a new translation.

**Suspected duplicate work:** if a separately imported record is determined to duplicate 1006, select 1006 as canonical, move/reconcile incoming links and list memberships, retain the old identity as a redirect, and record the merge. If a user already saved both, resolve the duplicate state without discarding private notes or conflicting ratings silently.

**Conflicting sources:** a statement that 1003 is a remake can remain pending or disputed while its well-supported novel-adaptation relationship stays accepted. Disagreement about one link should not erase the whole work.

**Unknown permission:** source-based public-domain evidence, reviewed adaptation relationships, and verified creator identities are different things. None should silently substitute for the others.

## 9. Decisions this fixture exposes

| Decision | Proposed starting point | Schema/workflow consequence |
|---|---|---|
| Every edition must resolve to a known translation? | No; permit explicit unresolved versions. | Needed for incomplete bulk imports; later reconciliation UI required. |
| Child story only exists inside a collection? | No; independent work with containment links. | Already supported. |
| New cuts/translations get public pages? | Embedded by default with stable anchors. | Primarily a routing/UI decision. |
| Multiple source works? | Yes. | Several `work_relationships` rows; no single `parent_work_id`. |
| Reviews/mentions in main adaptation map? | No. | Relationship categories and display rules control this. |
| How to represent the playable nonfiction format? | Reuse `video_game` initially; review whether a distinct form is useful. | A lookup-table row can change without rebuilding the whole schema. |
| Source of a translation is itself another translation? | Link exact `based_on_version_id` when established. | Same-work rule works for this; deeply transformative cases may instead be new works. |
| A physical omnibus contains unrelated works? | A collection work/version represents the aggregate; `release_contents` identifies components. | The aggregate itself still needs a clear identity policy. |
| Cross-medium or multi-step project proposal? | Submit coordinated changes rather than publish half a relationship. | Proposal bundles remain to be designed. |
| Term synonyms and several hierarchical parents? | Curated aliases first; one parent only for the draft. | Alias table is a likely small addition; multi-parent hierarchy only if needed. |
| Who changed a containment link? | Capture membership changes in a defined aggregate revision. | Choose ownership (usually the container record); current file needs this rule made explicit. |
| Creator identity and software/tool credit? | Keep people/organizations clear; defer tool identity design. | The current suggested `ai_tool` role needs a compatible tool entity or a separate technology-credit model. |

## 10. How to use this draft

First, walk through cases 1001, 1006 and 1008: translation/release, anthology/story, and multiple sources. If the data looks reasonable but the page would confuse you, change the presentation before changing the database.

Next, have the coding agent turn a selected subset into deterministic test fixtures using its real auth model, lookup seeds, initial revisions and mock sources. Test the import/correction sequence against the actual implementation. Do not treat these tables as SQL inserts or claim the scenarios are already passing tests.

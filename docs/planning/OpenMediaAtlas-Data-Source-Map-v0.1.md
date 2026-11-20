# OpenMediaAtlas: data-source and reconciliation map

Draft for review · 20 September 2026 · Source policies checked on this date

**Proposed starting point:** Open Library for bibliographic structure, Wikidata for cross-media identities and relationship candidates, then targeted first-party evidence and community contributions. Separate the right to read a source, display imported material, and redistribute it in an open export. This is a planning map, not a license clearance or completed pipeline.

## 1. Sources and ingestion routes

| Source | Use | Retrieval plan | Important limit |
|---|---|---|---|
| Open Library | Works, editions, authors, identifiers, languages, subjects, publication details. | Download works/editions/authors dumps into staging; process in resumable batches; use redirects/deletes for reconciliation. | Work/edition identity is imperfect. Descriptions and cover rights are not automatically cleared by the code license. |
| Wikidata | Cross-source identifiers, people/organizations, dates, media types, candidate based-on and sequence links. | Start with a bounded relevant extract; use suitable bulk access for scale rather than relying on unlimited live queries. | Community data may be incomplete or wrong. A bare relation needs provenance and suitable review. |
| Project Gutenberg | Reading links, ebook IDs, authors/languages, supplier's rights statements. | Use authorized feeds/catalogs and bulk mechanisms; do not scrape the main site at scale. | A statement about US public-domain status does not establish worldwide rights or rights in every edition/image. |
| Publisher/studio/creator pages; actual credits | Exact translator, publisher, release, adaptation credit and project announcement evidence. | Targeted retrieval/manual citation, within access and reuse terms. | Evidence of a fact does not mean permission to copy its prose or images. Promotional claims can be incomplete. |
| Community submissions | Missing works, corrections, precise relationships and evidence. | Structured proposal forms and review. | Contributor identity is not factual proof; retain sources and change history. |
| Direct creator/rights-holder submissions | Claimed representation, project status and explicit licenses. | Private verification workflow with separately publishable statements. | Representation is scoped; does not grant control over every factual field. |
| TMDB, conditional | Film/TV metadata and imagery if its terms fit the chosen business/export model. | Approved API access; scope storage, attribution, redistribution and commercial use before ingestion. | Not an unrestricted open-data feed. Keep its records separable if used. |
| IMDb or other commercial datasets, deferred | Potential later licensed enrichment. | Evaluate a specific agreement before integration. | No ingestion commitment in this draft; do not assume a downloadable dataset is commercially or openly redistributable. |

Open Library explicitly directs bulk users to dumps. Its licensing page says it asserts no new proprietary rights over database material, but notes existing rights can remain. [Bulk data](https://openlibrary.org/data), [licensing](https://openlibrary.org/developers/licensing).

Wikidata's structured data in its main/property/lexeme namespaces is CC0; surrounding text and linked media are not automatically covered by that same permission. [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing).

Gutenberg provides instructions for automated access. Follow the permitted route and limits rather than treating reader-facing pages as a bulk endpoint. [Robot access](https://www.gutenberg.org/policy/robot_access.html).

TMDB describes free noncommercial API access with attribution and directs commercial users to licensing discussions. Its API availability is not permission to release an unrestricted mirror. [TMDB FAQ](https://developer.themoviedb.org/docs/faq).

## 2. Field-by-field map

“Preferred evidence” is a default starting point, not a universal winner. A work's original publication year, a translation date and a release date are different fields, not conflicting votes.

| Field group | Initial source / preferred evidence | Destination | Conflict / publication rule |
|---|---|---|---|
| Book identity, title and edition | OL; bibliographic record/title page to resolve conflicts | Works, versions, releases, identifiers | Exact source IDs first; title-only matches never auto-merge. |
| Film/TV identity | Wikidata; official credits/catalog where needed | Works and identifiers | Keep year, form and credits to disambiguate; duplicates queued. |
| Author/creator/studio identity | OL/Wikidata and official records | Agents, names, identifiers | Names alone are insufficient; preserve unresolved contributors as source text. |
| Credits and credited names | Actual credits/title pages; structured source as candidate | Credits, credit_roles | Preserve credited-as wording; credit does not imply rights ownership. |
| Original date vs release date | Relevant primary record; OL/Wikidata seed | Work/version/release date fields | Preserve uncertain/date-only strings; no invented exact day. |
| Language and translation identity | OL edition language, translator credits/title page | Languages, versions, credits | Map MARC codes explicitly; original language is not inferred from a random edition. |
| Story contents, seasons, episodes | Contents pages/episode guides; structured records | Work_components, release_contents | Separate independent works from headings; release contents can differ. |
| Adaptation/remake/continuation | Explicit credit or reliable attributed statement; Wikidata candidate | Work_relationships and citations | Shared plot/title is insufficient. Unknown authorization remains unknown. |
| Version as exact source | Explicit statement identifying translation/cut | Relationship.source_version_id | Must belong to source work; version remains a version even with a standalone page. |
| Genres, subjects and tone | OL/Wikidata candidates; reviewed editorial/community assignments | Terms, aliases and record_terms | Map to curated vocabulary; no automatic creation of public tags. |
| Descriptions | Original editorial/contributor text; reusable supplied text where permitted | Typed record.description | Do not copy a synopsis just because its page is readable. Model drafts require review and traceable inputs. |
| Covers, posters, portraits | Authorized supplier or contributor with stated reuse basis | Media_assets | Track image rights independently; fallback if missing/unclear. |
| Rights/permissions | Exact license or sourced jurisdiction-specific assessment | Rights_statements and citations | Review scope, territory and component; no global safe-to-adapt boolean. |
| Read/watch/play links | Official provider/catalog/creator | External_links | Record territory, access mode and last check; link does not authorize hosting. |
| Project status and creator declarations | Official announcement or attributed declaration | Works/project_declarations | “Planned” is publishable when evidenced; distinguish declaration from completion. |
| Ratings, saves, wants, lists | OpenMediaAtlas users | Community tables | Do not import another site's community as if it were OpenMediaAtlas's activity. |

## 3. Proposed update cadence

These are operating choices, not promises about source publication schedules.

- Bibliographic baselines: process a new available dump on a planned cycle, initially roughly monthly. Reprocessing unchanged payload hashes is skipped.
- Active projects and recent releases: targeted weekly refresh where a supported source exists; do not poll the entire catalog.
- Watch/read links: recheck important links on a rotating schedule and on user reports; distinguish temporary request failure from removal.
- User corrections and curator decisions: apply upon approval; asynchronous search/cache updates follow.
- Rights statements: revisit when new evidence is reported or known conditions change. Never calculate expiration from a year alone without a reviewed jurisdiction-specific rule.

Pages read accepted local records. They are not rebuilt by an LLM every visit, and viewing a page does not launch unbounded source fetching. Optional enrichment can queue once for a missing record, with deduplication and an observable status.

## 4. Reconciliation policy

1. Preserve supplier, external key, batch/version, retrieval time, raw permitted payload, and hash.
2. Match using existing canonical external-ID mappings plus consistency checks. An identifier collision is a review item, not permission to merge everything sharing it.
3. Normalize into candidate values without discarding original date/language/credit wording.
4. Publish a qualifying new index record only after the minimum gate; quarantine ambiguous identity.
5. For an existing field, compare candidate to its currently accepted value and provenance.
6. Fill genuinely blank eligible factual fields from an approved source. Do not treat “unknown,” “disputed” and blank as interchangeable.
7. Update an unprotected imported field automatically only under its approved source policy and validation rules. Retain an accepted revision.
8. If a field has been human-corrected/protected, queue conflicting input. Human approval is not eternal truth: reviewers can explicitly adopt better evidence and release protection.
9. Merge with a preview of conflicting fields, list memberships, versions, credits and redirects. Preserve old IDs. Do not auto-delete a public record merely because a supplier deleted its copy.
10. Maintain publication and export eligibility separately. Restricted text or imagery does not enter an open bulk dump by accident.

## 5. Proposed data additions beyond DBML v0.1

| Addition | Minimum information | Why |
|---|---|---|
| Accepted field state | Record, field path, accepted revision/value origin, evidence refs, protected flag/reason | Makes reimport precedence inspectable rather than hidden in code. |
| Source-use policy | Source, permitted display/storage/export uses, attribution, terms URL/version, review date | Keeps open exports and possible commercialization manageable. |
| Term aliases and source mappings | Canonical term, alias language/vocabulary; supplier label mapping | Prevents a dump from creating tag sprawl. |
| Version page presentation | Embedded/standalone, decision reason and reviewer | Promotes visibility without changing bibliographic identity. |
| Coordinated proposal batch | Member changes, base revisions and atomicity policy | A new work/creator/relationship can be reviewed coherently. |

Do not build a universal fact engine prematurely. Begin with field-state tracking for the small set of imported fields that will be edited, and document ownership of related child collections such as credits and containment links.

## 6. What the dashboard should make obvious

For each import: source/version, progress, records matched/new/ambiguous/rejected, failed batches, fields proposed/accepted/protected, and last successful run. One click should explain why a record did not publish or why a candidate lost to another value. AI can suggest a match or summarize evidence; source citations and reviewer decisions remain inspectable.

Acceptance examples: repeat the same batch without duplicates; import corrected upstream data without erasing a protected field; distinguish a French edition from a new French work; quarantine a reused identifier; omit restricted material from an open export; keep withdrawn supplier data as an auditable source change rather than silently destroying local history.

---

## Revision note — 2026-11-04

This v0.1 draft is historical context, not current policy. It was not rewritten.

- Current product direction: [oma-strategy-2026-11.md](oma-strategy-2026-11.md).
- Decisions and their status: [../decision-register.md](../decision-register.md).
- Newer evidence: [knowledge-model-2026-11.md](knowledge-model-2026-11.md),
  [source-landscape-2026-11.md](source-landscape-2026-11.md),
  [agent-contribution-and-api-2026-11.md](agent-contribution-and-api-2026-11.md),
  [oma-worked-examples-2026-11.md](oma-worked-examples-2026-11.md).

Where this draft conflicts with the register, the register wins. Two known conflicts worth
naming: this draft sequences a read API before any agent write path (see DR-02, now staged
rather than deferred), and it assumes version/edition data exists (see the strategy §3.2: one
editorial work has an edition).

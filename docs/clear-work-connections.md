# Clear work connections (chunk 2)

Work pages now always have a **Connections** navigation link and a standalone,
server-rendered list. Twelve distinct connected works appear per page; **Next
connected works** browses the remainder. No graph, JavaScript, staging service,
ingestion, or production database is required.

## Representation and public boundaries

`WorkRelationship` records `from_work`, `to_work`, a `RelationshipType`, mandatory
`Source`, optional `scope_note`, `review_status`, and JSON `evidence`. Stable work
IDs remain canonical. Types have a code, category, forward label and inverse
label. Unique `(from_work, to_work, relationship_type)` does not prevent multiple
meanings or assertions in opposite directions between the same works.

Only accepted relationships between public, canonical works are shown, respecting
the existing real-record/demo boundary. No joins infer edges from matching titles,
creators, series, universes, or multi-hop paths. Existing data can represent other
categories through stored relationship types; filters expose only types present
in the current work's accepted neighborhood.

`catalog/connections.py` shares its direction mapping with homepage cards, list
rows, filter choices and evidence details. `adapted-from` reads **Based on** from
the derived work and **Adapted into** from its source. All other codes preserve
stored forward/inverse wording, including Wikidata P144's deliberately broader
**Works based on this** inverse. That assertion alone cannot safely be
reclassified as a verified adaptation, inspiration, or remake.

## Browsing and evidence

Rows group by the connected work ID, retaining every accepted relationship and
its evidence even when a relationship filter matched only one. Identical titles
do not merge different works. The default order groups explicit adaptation source
works first, then adaptations, then other direct connections; a work occupying
several groups appears once in its earliest group. Titles then sort alphabetically
with stable ID tie-breaking. Date sorts use recorded year, with missing years last;
displayed dates still use chunk 1's evidence-aware meaning and precision helpers.

Search (display title or exact record ID), type, directional relationship, sort,
and page use `connection_*` GET parameters. Apply resets the page; pagination
preserves the parameters. Reset clears the view. Native forms and links support
sharing and browser Back without downloading catalog records into the browser.
Counts distinguish distinct connected works from accepted assertions and explain
their public scope. Empty catalogs say **No connections recorded yet**, not that
no connections exist. Missing titles/types/dates do not remove a valid edge.

Expandable native details show exact stored direction, source and reference
links, supporting notes, source notes, acceptance state, known import origin,
statement/property IDs and retrieval time when stored. Missing links, supporting
notes and origin are stated plainly. Wikidata reference URLs (P854) are extracted
from stored reference snaks without inventing citations from other values. Only
HTTP(S) URLs are rendered. Substantive attributed authorization statements from
chunk 1 remain inside details, separate from review; no permission badges or
generic rights text are added.

The current review model records acceptance, not the human reviewer or review
time. A source link does not establish human verification. There is no explicit
inferred-edge field or separate public indirect-edge dataset; none is synthesized.
The existing correction route is linked. Its current form proposes work-field
changes; relationship-specific editing/rejection remains an editorial limitation,
not a new public moderation flow in this change.

## Query behavior and limitations

A metadata projection fetches only the current work's accepted edge neighborhood.
Connected work identities, credits and supplier snapshots are batched to reuse
chunk 1's public type and fallback-title helpers; classification/filtering/sorting
run on that neighborhood, never the entire catalog. Relationship source/evidence
objects are fetched only for the selected page. Query count is constant with row
count. For unusually large neighborhoods, server memory still scales with local
neighbor identities and snapshots; persistent public-type indexing would be a
separate optimization. No schema changes or migration are required.

## Validation and local viewing

Automated tests use Django's isolated SQLite test database with `DATABASE_URL=`.
Focused tests cover direction, no indirect edges, same-pair multiple meanings,
missing identity/evidence, empty and filtered-empty states, accepted/public
boundaries, evidence-backed types, date semantics, stable sorts, URL pagination,
and constant query count/page-bounded evidence loading.

Desktop (1440px) and mobile (390px) Chromium checks cover pagination, browser
Back, search/type filtering, keyboard expansion, sparse and empty pages, absence
of horizontal overflow and JavaScript errors. Screenshots are synthetic fixtures:
[Desktop](screenshots/chunk-2-desktop.png), [Mobile](screenshots/chunk-2-mobile.png).

For a fresh local checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=true
unset DATABASE_URL
python manage.py migrate
python manage.py load_demo_catalog
python manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/works/1001/the-glass-orchard-novel-1912/#connections>.
Use a fresh SQLite checkout for demo viewing so existing real public records do
not intentionally suppress demo records. No hosted preview or production change
is part of this PR.

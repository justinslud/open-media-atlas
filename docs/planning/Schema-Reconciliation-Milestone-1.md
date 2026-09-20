# Milestone 1 schema reconciliation

The draft DBML remains the long-term direction, not a mandate to create unused tables. This milestone implements only works/types, agents and credits, versions/releases, sources, external identifiers, and typed work relationships. Django authentication/admin provide staff foundations without duplicating the DBML's illustrative public-user table.

Two small corrections reconcile later product decisions:

1. `versions.page_mode` records `embedded` (the default) or `standalone`, and `page_mode_reason` records why a reviewer promoted it. This is presentation metadata only: the version keeps its parent work and identity.
2. The existing `catalog_records.visibility` and `depth` fields already separate publication from enrichment. Their notes now explicitly state that a qualifying `index` record may be public; `editorial` depth is not required.

No schema change is needed for controlled vocabulary or rights-holder authority. `terms` already models canonical shared terms; its proposed alias/proposal workflow remains deferred. `rights_claims` already states that claim acceptance neither proves ownership nor permits overwriting factual catalog data. The application intentionally does not implement either workflow in this slice.

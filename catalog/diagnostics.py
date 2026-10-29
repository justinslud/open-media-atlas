"""Read-only diagnostics for the relationship pipeline.

Everything here answers one question: *given a work OMA already imported, where
did its relationship claims go?* The answer is derived from three sources of
truth that must agree:

* the cached supplier payload (``SourceRecord.raw_payload``) — what was claimed;
* ``ImportRelationshipProposal`` — what the resolver turned into a proposal;
* ``WorkRelationship`` — what an editor accepted.

No function here writes to the database. The page, the orphan report, and the
seed selection all call this module so they cannot drift apart.

Claims are keyed by their Wikidata statement ID, which is what the resolver
stores on a proposal. That makes an outcome check exact rather than a guess
based on endpoints and titles.

Performance note: building the index parses every cached Wikidata payload
(~7.5k records, a few seconds). It is memoised per catalog signature, so a
staff page pays that cost only after the catalog changes.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db.models import Max, Q

from .models import (
    ExternalIdentifier,
    ImportRelationshipProposal,
    SourceRecord,
    Work,
    WorkRelationship,
)
from .publication import publication_warnings

WIKIDATA_TITLE = "Wikidata"

# Property -> relationship code. Mirrors the resolver; kept here so the page and
# the resolver read one definition instead of two copies.
PROPERTY_MAP = {
    "P144": "based-on",
    "P155": "follows",
    "P156": "followed-by",
    "P179": "part-of-series",
    "P629": "edition-of",
    "P941": "inspired-by",
    "P737": "influenced-by",
    "P4969": "derivative-work",
}

# P4969 is asserted on the target ("this is a derivative work of me"), so the
# seed is the source side. Every other property is asserted on the seed.
PROPERTIES_DERIVED_ON_TARGET = {"P4969"}

SUPPORTED_PROPERTIES = tuple(PROPERTY_MAP)

STATE_CONNECTED = "connected"
STATE_PROPOSAL_PENDING = "proposal_pending"
STATE_PROPOSAL_REJECTED = "proposal_rejected"
STATE_CLAIMS_UNRESOLVED = "claims_unresolved"
STATE_NO_CLAIMS = "no_claims"

STATE_LABELS = {
    STATE_CONNECTED: "In the accepted graph",
    STATE_PROPOSAL_PENDING: "Proposal pending review",
    STATE_PROPOSAL_REJECTED: "Proposals exist, none accepted",
    STATE_CLAIMS_UNRESOLVED: "Claims exist, never resolved",
    STATE_NO_CLAIMS: "No supported relationship claim",
}

STATE_DEFINITIONS = {
    STATE_CONNECTED: "The work is an endpoint of at least one accepted relationship.",
    STATE_PROPOSAL_PENDING: "At least one supplier claim became a pending proposal; nothing accepted yet.",
    STATE_PROPOSAL_REJECTED: "At least one proposal names the work, but no accepted relationship does. Review rejected it, or the approved edge is missing.",
    STATE_CLAIMS_UNRESOLVED: "The cached payload holds a supported claim, but no proposal references it.",
    STATE_NO_CLAIMS: "The cached payload holds no supported relationship property pointing elsewhere.",
}

STATE_ORDER = (
    STATE_CONNECTED,
    STATE_PROPOSAL_PENDING,
    STATE_PROPOSAL_REJECTED,
    STATE_CLAIMS_UNRESOLVED,
    STATE_NO_CLAIMS,
)

OUTCOME_LABELS = {
    "accepted": "Accepted relationship",
    "proposal_approved": "Proposal approved, edge missing",
    "proposal_pending": "Pending proposal",
    "proposal_rejected": "Proposal rejected",
    "target_missing": "Target entity is not in the catalog",
    "self_link": "Claim points at the work itself",
    "no_proposal": "No proposal for this statement",
}


@dataclass
class Claim:
    statement_id: str
    property_id: str
    code: str
    target_qid: str
    rank: str
    target_work_id: int | None = None
    outcome: str = "no_proposal"
    proposal_id: int | None = None
    relationship_id: int | None = None
    qualifiers: dict = field(default_factory=dict)
    references: int = 0

    @property
    def outcome_label(self):
        return OUTCOME_LABELS.get(self.outcome, self.outcome)


@dataclass
class WorkDiagnosis:
    work: Work
    state: str
    claims: list
    warnings: list
    qids: list

    @property
    def state_label(self):
        return STATE_LABELS.get(self.state, self.state)

    @property
    def unresolved(self):
        return [claim for claim in self.claims if claim.outcome in ("target_missing", "self_link", "no_proposal")]

    @property
    def ambiguous(self):
        return [claim for claim in self.claims if claim.outcome in ("proposal_pending", "proposal_rejected")]

    @property
    def resolved(self):
        return [claim for claim in self.claims if claim.outcome in ("accepted", "proposal_approved")]

    @property
    def duplicate_identity(self):
        """True when a crosswalk merged two or more Wikidata items into one work.

        This is the usual cause of a self-link: the claim points at the work's
        *other* QID, so both endpoints collapse onto one catalog row.
        """
        return len(self.qids) > 1


_CACHE = {}


def _signature():
    """Cheap fingerprint: changes whenever claims, proposals, or edges can change."""
    return (
        SourceRecord.objects.count(),
        _extent(SourceRecord, "id", "retrieved_at"),
        _extent(ImportRelationshipProposal, "id", "reviewed_at"),
        _extent(WorkRelationship, "id"),
    )


def _extent(model, *names):
    row = model.objects.aggregate(**{name: Max(name) for name in names})
    return tuple(row[name] for name in names)


def claim_value(claim):
    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if isinstance(value, dict) and value.get("entity-type") == "item":
        return value.get("id")
    return None


def _raw_claims(payload):
    """Yield (property, statement_id, target_qid, rank) for supported claims."""
    if not isinstance(payload, dict):
        return
    claims = payload.get("claims")
    if not isinstance(claims, dict):
        return
    for prop in SUPPORTED_PROPERTIES:
        for claim in claims.get(prop, []) or []:
            if not isinstance(claim, dict):
                continue
            target = claim_value(claim)
            if not target:
                continue
            yield (
                prop,
                claim.get("id") or f"{target}-{prop}",
                target,
                claim.get("rank", "normal"),
                claim,
            )


def build_index(force=False):
    """Return the cached catalog-wide claim index.

    Shape::

        {
          "signature": (...),
          "claims": {work_id: [Claim, ...]},
          "states": {work_id: state},
          "qid_to_work": {qid: work_id},
          "totals": {...},
          "imported_work_ids": set(),
        }
    """
    signature = _signature()
    if not force and _CACHE.get("signature") == signature:
        return _CACHE

    qid_to_work = dict(
        ExternalIdentifier.objects.filter(scheme="wikidata").values_list("value", "work_id")
    )
    work_qids = defaultdict(list)
    for qid, work_id in qid_to_work.items():
        work_qids[work_id].append(qid)
    claims_by_statement = {
        proposal.statement_id: proposal
        for proposal in ImportRelationshipProposal.objects.only(
            "id", "statement_id", "status", "from_work_id", "to_work_id"
        )
    }
    edges_by_statement = {}
    for relationship in WorkRelationship.objects.only("id", "evidence", "review_status"):
        if relationship.review_status != "accepted":
            continue
        statement_id = (relationship.evidence or {}).get("statement_id")
        if statement_id:
            edges_by_statement[statement_id] = relationship

    claims = defaultdict(list)
    imported_work_ids = set()
    payloads = SourceRecord.objects.filter(
        source__title=WIKIDATA_TITLE, matched_work__isnull=False
    ).only("matched_work_id", "raw_payload")
    for record in payloads.iterator(chunk_size=500):
        work_id = record.matched_work_id
        imported_work_ids.add(work_id)
        for prop, statement_id, target, rank, raw in _raw_claims(record.raw_payload):
            if rank == "deprecated":
                continue
            claim = Claim(
                statement_id=statement_id,
                property_id=prop,
                code=PROPERTY_MAP[prop],
                target_qid=target,
                rank=rank,
                qualifiers=(raw.get("qualifiers") or {}),
                references=len(raw.get("references") or []),
            )
            if target in qid_to_work:
                claim.target_work_id = qid_to_work[target]
            proposal = claims_by_statement.get(statement_id)
            edge = edges_by_statement.get(statement_id)
            if edge is not None:
                claim.outcome, claim.relationship_id, claim.proposal_id = (
                    "accepted", edge.pk, proposal.pk if proposal else None,
                )
            elif proposal is not None:
                claim.proposal_id = proposal.pk
                claim.outcome = {
                    "pending": "proposal_pending",
                    "approved": "proposal_approved",
                    "rejected": "proposal_rejected",
                }.get(proposal.status, "no_proposal")
            elif target == (work_qids[work_id][0] if work_qids[work_id] else None):
                claim.outcome = "self_link"
            elif claim.target_work_id is None:
                claim.outcome = "target_missing"
            else:
                claim.outcome = "no_proposal"
            claims[work_id].append(claim)

    proposal_endpoint_ids = set()
    for from_id, to_id in ImportRelationshipProposal.objects.values_list("from_work_id", "to_work_id"):
        proposal_endpoint_ids.update((from_id, to_id))
    edge_endpoint_ids = set()
    for from_id, to_id in WorkRelationship.objects.filter(review_status="accepted").values_list(
        "from_work_id", "to_work_id"
    ):
        edge_endpoint_ids.update((from_id, to_id))

    states = {}
    all_work_ids = set(Work.objects.values_list("id", flat=True))
    for work_id in all_work_ids:
        if work_id in edge_endpoint_ids:
            states[work_id] = STATE_CONNECTED
        elif any(claim.outcome in ("proposal_pending",) for claim in claims.get(work_id, [])):
            states[work_id] = STATE_PROPOSAL_PENDING
        elif work_id in proposal_endpoint_ids:
            states[work_id] = STATE_PROPOSAL_REJECTED
        elif claims.get(work_id):
            states[work_id] = STATE_CLAIMS_UNRESOLVED
        else:
            states[work_id] = STATE_NO_CLAIMS

    totals = {
        "works": Work.objects.count(),
        "imported_works": len(imported_work_ids),
        "works_with_claims": sum(1 for work_id in claims if claims[work_id]),
        "works_with_proposals": len(proposal_endpoint_ids),
        "works_in_graph": len(edge_endpoint_ids),
        "accepted_relationships": WorkRelationship.objects.filter(review_status="accepted").count(),
        "proposals": ImportRelationshipProposal.objects.count(),
        "proposals_pending": ImportRelationshipProposal.objects.filter(status="pending").count(),
        "claims_total": sum(len(items) for items in claims.values()),
        "source_records": SourceRecord.objects.filter(source__title=WIKIDATA_TITLE).count(),
    }

    _CACHE.clear()
    _CACHE.update({
        "signature": signature,
        "claims": dict(claims),
        "states": states,
        "qid_to_work": qid_to_work,
        "totals": totals,
        "imported_work_ids": imported_work_ids,
    })
    return _CACHE


def funnel(index=None):
    """Four stages, with the drop between them explained in words."""
    index = index or build_index()
    totals = index["totals"]
    stages = [
        {
            "key": "imported",
            "label": "Imported works",
            "count": totals["imported_works"],
            "definition": "Works with at least one cached Wikidata payload. Supplier records stay intact; this is not a publication state.",
        },
        {
            "key": "claims",
            "label": "Works with a usable relationship claim",
            "count": totals["works_with_claims"],
            "definition": "The payload holds a supported property (P144, P155, P156, P179, P629, P941, P737, P4969) at normal rank, pointing at another item.",
        },
        {
            "key": "proposals",
            "label": "Works touched by a proposal",
            "count": totals["works_with_proposals"],
            "definition": "At least one ImportRelationshipProposal names the work as an endpoint, in any status.",
        },
        {
            "key": "accepted",
            "label": "Works in the accepted graph",
            "count": totals["works_in_graph"],
            "definition": "At least one accepted WorkRelationship names the work as an endpoint. Only these appear on public connection views.",
        },
    ]
    previous = None
    for stage in stages:
        stage["drop"] = 0 if previous is None else previous - stage["count"]
        previous = stage["count"]
    return stages


def state_counts(index=None):
    index = index or build_index()
    counts = Counter(index["states"].values())
    return [{"key": state, "label": STATE_LABELS[state], "definition": STATE_DEFINITIONS[state],
             "count": counts.get(state, 0)} for state in STATE_ORDER]


def _matching_ids(index, state=None, query="", type_code="", depth=""):
    ids = index["states"]
    if state:
        ids = {work_id: value for work_id, value in ids.items() if value == state}
    else:
        ids = dict(ids)
    if not (query or type_code or depth):
        return list(ids)

    works = Work.objects.filter(pk__in=ids).select_related("work_type")
    if type_code:
        works = works.filter(work_type__code=type_code)
    if depth:
        works = works.filter(depth=depth)
    if query:
        works = works.filter(
            Q(title__icontains=query) | Q(identifiers__value__icontains=query)
        ).distinct()
    return list(works.values_list("pk", flat=True))


def work_rows(index=None, state="", query="", type_code="", depth="", limit=25, offset=0):
    index = index or build_index()
    ids = _matching_ids(index, state=state or None, query=query, type_code=type_code, depth=depth)
    works = (
        Work.objects.filter(pk__in=ids)
        .select_related("work_type")
        .order_by("title", "id")[offset: offset + limit]
    )
    rows = []
    for work in works:
        claims = index["claims"].get(work.pk, [])
        proposal_ids = sorted({claim.proposal_id for claim in claims if claim.proposal_id})
        relationship_ids = sorted({claim.relationship_id for claim in claims if claim.relationship_id})
        rows.append({
            "work": work,
            "state": index["states"].get(work.pk, STATE_NO_CLAIMS),
            "state_label": STATE_LABELS.get(index["states"].get(work.pk), "Unknown"),
            "claims": claims,
            "claim_count": len(claims),
            "proposals": proposal_ids,
            "relationships": relationship_ids,
            "outcomes": dict(Counter(claim.outcome for claim in claims)),
            "warnings": publication_warnings(work),
        })
    return rows, len(ids)


def diagnose(work, index=None):
    index = index or build_index()
    claims = index["claims"].get(work.pk, [])
    return WorkDiagnosis(
        work=work,
        state=index["states"].get(work.pk, STATE_NO_CLAIMS),
        claims=claims,
        warnings=publication_warnings(work),
        qids=list(
            ExternalIdentifier.objects.filter(work=work, scheme="wikidata").values_list("value", flat=True)
        ),
    )


def sample_cases(index=None):
    """A small, deliberately varied set: resolved, ambiguous, and failed.

    Selection is deterministic so a reviewer can re-open the page and see the
    same rows. One case per category, taken from the richest matching work.
    """
    index = index or build_index()
    wanted = [
        ("accepted", "Successful", "A claim became an accepted relationship."),
        ("proposal_pending", "Ambiguous", "A claim became a pending proposal awaiting review."),
        ("proposal_rejected", "Ambiguous", "A claim became a proposal that review rejected."),
        ("target_missing", "Failed", "A claim points at an entity that was never staged in the catalog."),
        ("no_proposal", "Failed", "Both endpoints exist in the catalog, but no proposal references this statement."),
        ("self_link", "Failed", "One claim points at the work's own other Wikidata item; the claim shown beside it is the real relationship."),
    ]
    cases = []
    used = set()
    for outcome, kind, note in wanted:
        best = None
        for work_id, claims in index["claims"].items():
            if work_id in used:
                continue
            matches = [claim for claim in claims if claim.outcome == outcome]
            if not matches:
                continue
            # Prefer a readable work: a handful of claims, not eighty.
            score = (0 if len(claims) <= 12 else 1, -len({claim.property_id for claim in matches}),
                     abs(len(claims) - 4), -len(matches))
            if best is None or score < best[0]:
                best = (score, work_id)
        if not best:
            continue
        work = Work.objects.select_related("work_type").filter(pk=best[1]).first()
        if not work:
            continue
        used.add(work.pk)
        diagnosis = diagnose(work, index)
        matches = [claim for claim in diagnosis.claims if claim.outcome == outcome]
        if outcome == "self_link":
            # Show the sibling claim on the same property: it is usually the real
            # relationship that the duplicate identity is hiding.
            props = {claim.property_id for claim in matches}
            siblings = [
                claim for claim in diagnosis.claims
                if claim.property_id in props and claim.outcome != "self_link"
            ]
            matches = siblings + matches
        # A self-link is often a duplicate-identity symptom, and it hides the real
        # claim sitting next to it. Show informative claims first.
        ordered = sorted(matches, key=lambda claim: claim.outcome == "self_link")
        highlight, seen_props = [], set()
        for claim in ordered:
            if claim.property_id in seen_props:
                continue
            seen_props.add(claim.property_id)
            highlight.append(claim)
            if len(highlight) == 2:
                break
        cases.append({
            "kind": kind,
            "note": note,
            "work": work,
            "diagnosis": diagnosis,
            "highlight": highlight,
            "hidden": max(len(matches) - len(highlight), 0),
        })
    return cases


def unresolved_claim_work_ids(index=None):
    """Works that carry a claim with no proposal: the resolver's real backlog."""
    index = index or build_index()
    return sorted(
        work_id
        for work_id, claims in index["claims"].items()
        if index["states"].get(work_id) == STATE_CLAIMS_UNRESOLVED
        or any(claim.outcome in ("target_missing", "no_proposal") for claim in claims)
    )


def orphan_states(index=None):
    """State counts restricted to unconnected works, matching report_orphans."""
    index = index or build_index()
    counts = Counter(
        state for work_id, state in index["states"].items() if state != STATE_CONNECTED
    )
    return counts

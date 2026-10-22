"""Shared Wikidata candidate-manifest helpers."""
from catalog.dates import wikidata_date_for_medium
from catalog.importers.wikidata import claim_ids, title_from_entity, work_type_spec


def build_candidate_rows(
    entities,
    seeds,
    allowed_codes,
    seed_labels=None,
    existing_qids=(),
    include_existing=False,
):
    seed_labels = seed_labels or {}
    seed_order = {qid: index for index, qid in enumerate(seeds)}
    rows = []
    for qid in sorted(entities):
        entity = entities[qid]
        if not isinstance(entity, dict) or entity.get("missing"):
            continue
        based_on = claim_ids(entity, "P144")
        seed_qid = next((seed for seed in seeds if seed in based_on), None)
        if not seed_qid:
            continue
        spec = work_type_spec(entity)
        if spec[0] not in allowed_codes:
            continue
        if qid in existing_qids and not include_existing:
            continue
        title, title_language, title_basis = title_from_entity(entity)
        date, year, precision, kind, evidence = wikidata_date_for_medium(entity, spec[2])
        rows.append({
            "qid": qid,
            "seed_qid": seed_qid,
            "seed_label": seed_labels.get(seed_qid, ""),
            "label": title or qid,
            "title_language": title_language,
            "title_basis": title_basis,
            "expected_type": spec[0],
            "expected_year": year,
            "date": date,
            "date_kind": kind,
            "date_property": evidence.get("property", ""),
            "precision": precision,
            "already_in_catalog": qid in existing_qids,
        })
    rows.sort(key=lambda row: (seed_order.get(row["seed_qid"], 999), row["label"].lower(), row["qid"]))
    return rows

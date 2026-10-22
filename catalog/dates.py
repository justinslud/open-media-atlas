"""Date selection retains supplier meaning and precision without claiming primacy."""
import re
from datetime import date


DATE_PROPERTY_ORDER = {
    "text": ("P577", "P580", "P585", "P571", "P1191", "P1619", "P2754", "P10135"),
    "stage": ("P1191", "P1619", "P577", "P580", "P585", "P571", "P2754", "P10135"),
    "screen": ("P577", "P580", "P1619", "P2754", "P10135", "P585", "P571", "P1191"),
    "audio": ("P577", "P580", "P2754", "P10135", "P585", "P571", "P1191", "P1619"),
}
DEFAULT_DATE_PROPERTY_ORDER = ("P577", "P1191", "P1619", "P580", "P2754", "P10135", "P585", "P571")


def parse_wikidata_claim(claim):
    """Parse one non-deprecated Wikidata date claim without inventing precision."""
    if claim.get("rank") == "deprecated":
        return None
    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if not isinstance(value, dict):
        return None
    raw, precision = value.get("time", ""), value.get("precision", 0)
    match = re.fullmatch(r"\+(\d{4})-(\d{2})-(\d{2})T.*", raw)
    if not match or precision not in (9, 10, 11) or value.get("before", 0) or value.get("after", 0):
        return None
    year, month, day = (int(part) for part in match.groups())
    if precision >= 10 and not 1 <= month <= 12:
        return None
    if precision == 11:
        try:
            date(year, month, day)
        except ValueError:
            return None
    text = str(year) if precision == 9 else f"{year}-{month:02d}" if precision == 10 else f"{year}-{month:02d}-{day:02d}"
    return {
        "text": text,
        "year": year,
        "precision": precision,
        "rank": claim.get("rank", "normal"),
        "statement_id": claim.get("id"),
        "value": value,
    }


def wikidata_claim_candidates(entity, prop):
    return [
        parsed
        for claim in entity.get("claims", {}).get(prop, [])
        if (parsed := parse_wikidata_claim(claim))
    ]


# Compatibility aliases used by the date backfill command.
candidates_for = wikidata_claim_candidates


def choose_wikidata_date(entity, medium):
    """Choose a date using the property order appropriate for the medium.

    The earliest assertion is selected when a supplier gives several dates;
    all candidates are retained so the importer does not silently discard
    conflicting evidence.
    """
    order = DATE_PROPERTY_ORDER.get(medium, DEFAULT_DATE_PROPERTY_ORDER)
    for prop in order:
        candidates = wikidata_claim_candidates(entity, prop)
        if not candidates:
            continue
        preferred = [row for row in candidates if row["rank"] == "preferred"]
        selected_pool = preferred or candidates
        earliest = min(selected_pool, key=lambda row: (row["year"], row["precision"], row["text"]))
        distinct_text = {(row["text"], row["precision"]) for row in selected_pool}
        display_text = earliest["text"] if len(distinct_text) == 1 else str(earliest["year"])
        return {
            "property": prop,
            "year": earliest["year"],
            "text": display_text,
            "selected": earliest,
            "candidates": candidates,
            "rule": (
                "single assertion" if len(candidates) == 1
                else "supplier preferred rank, earliest assertion" if preferred and len(preferred) > 1
                else "supplier preferred rank" if preferred
                else "earliest assertion; multiple date assertions retained"
            ),
        }
    return None


choose_date = choose_wikidata_date


def date_kind_for_wikidata_property(prop, medium):
    if prop == "P1191":
        return "first_performance"
    if prop == "P1619":
        return "first_performance" if medium == "stage" else "first_release"
    if prop == "P2754":
        return "production"
    if prop == "P10135":
        return "recording"
    if prop == "P577":
        return "release" if medium in {"screen", "audio"} else "publication"
    if prop == "P580":
        return "release" if medium in {"screen", "audio"} else "inception"
    if prop == "title":
        return "release" if medium in {"screen", "audio"} else "publication" if medium in {"text", "stage"} else "inception"
    return "inception"


def wikidata_date_for_medium(entity, medium):
    """Return (text, year, precision, kind, evidence) for a work medium."""
    chosen = choose_wikidata_date(entity, medium)
    if not chosen:
        return "", None, None, "unknown", {}
    selected = chosen["selected"]
    evidence = {
        "date_text": chosen["text"],
        "property": chosen["property"],
        "statement_id": selected["statement_id"],
        "precision": selected["precision"],
        "rank": selected["rank"],
        "value": selected["value"],
        "source_url": f"https://www.wikidata.org/wiki/{entity.get('id', '')}",
        "selection_rule": chosen["rule"],
        "candidates": [
            {
                "text": row["text"],
                "year": row["year"],
                "precision": row["precision"],
                "rank": row["rank"],
                "statement_id": row["statement_id"],
            }
            for row in chosen["candidates"]
        ],
    }
    if chosen.get("meaning_unverified"):
        evidence["meaning_unverified"] = True
    return chosen["text"], chosen["year"], selected["precision"], date_kind_for_wikidata_property(
        chosen["property"], medium
    ), evidence


def openlibrary_date(payload):
    text = str(payload.get('first_publish_date') or '').strip()
    match = re.search(r'(?<!\d)(\d{4})(?!\d)', text)
    return text, int(match.group(1)) if match else None


def wikidata_date(entity):
    candidates = []
    for prop, kind in (('P577', 'publication'), ('P571', 'inception')):
        for claim in entity.get('claims', {}).get(prop, []):
            if claim.get('rank') == 'deprecated':
                continue
            value = claim.get('mainsnak', {}).get('datavalue', {}).get('value')
            if not isinstance(value, dict):
                continue
            raw, precision = value.get('time', ''), value.get('precision', 0)
            match = re.fullmatch(r'\+(\d{4})-(\d{2})-(\d{2})T.*', raw)
            if not match or precision not in (9, 10, 11) or value.get('before', 0) or value.get('after', 0):
                continue
            year, month, day = match.groups()
            if precision >= 10 and not 1 <= int(month) <= 12:
                continue
            if precision == 11:
                from datetime import date
                try:
                    date(int(year), int(month), int(day))
                except ValueError:
                    continue
            text = year if precision == 9 else f'{year}-{month}' if precision == 10 else f'{year}-{month}-{day}'
            candidates.append((text, int(year), precision, kind, prop, claim))
        if candidates:
            break
    # Prefer supplier rank only if it uniquely resolves the date. Never use min().
    preferred = [row for row in candidates if row[5].get('rank') == 'preferred']
    selected = preferred or candidates
    if len({(row[0], row[3]) for row in selected}) != 1:
        return '', None, None, 'unknown', {}
    text, year, precision, kind, prop, claim = selected[0]
    evidence = {'date_text': text, 'property': prop, 'statement_id': claim.get('id'),
                'precision': precision, 'value': claim.get('mainsnak', {}).get('datavalue', {}).get('value'), 'rank': claim.get('rank', 'normal'),
                'qualifiers': claim.get('qualifiers', {}), 'references': claim.get('references', []),
                'source_url': f"https://www.wikidata.org/wiki/{entity.get('id', '')}"}
    return text, year, precision, kind, evidence

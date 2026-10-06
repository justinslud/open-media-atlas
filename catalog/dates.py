"""Date selection retains supplier meaning and precision without claiming primacy."""
import re


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

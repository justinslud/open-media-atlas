"""Public identity derived from explicit catalog/supplier evidence, never titles."""
import unicodedata

# Existing codes; generic literary/written works are not necessarily books.
TYPE_LABELS = {
    'book': 'Book', 'novel': 'Novel', 'play': 'Play', 'film': 'Film',
    'television-series': 'Television series', 'television-program': 'Television program',
    'song': 'Song', 'album': 'Album', 'video-game': 'Video game',
    'literary-work': 'Written work', 'written-work': 'Written work',
    'creative-work': 'Unclassified work', 'unknown': 'Unclassified work',
}
GENERIC_TYPES = {'unknown', 'book', 'literary-work', 'written-work', 'creative-work'}
BOOK_TYPES = {'book', 'novel'}


def normalize_search(value):
    # Keep words/accents; punctuation, case and whitespace have no ranking weight.
    value = unicodedata.normalize('NFKC', value).casefold()
    # Apostrophes within names/titles do not create a new search word.
    value = value.translate(str.maketrans('', '', "'’ʼ"))
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in value).split())


def public_type_code(work):
    code = work.work_type_id
    if code not in GENERIC_TYPES:
        return code
    from .importers.wikidata import TYPE_MAP, claim_ids
    supported = set()
    for record in work.source_records.all():
        payload = record.raw_payload
        if not isinstance(payload, dict) or not payload.get('id', '').startswith('Q'):
            continue
        for prop in ('P31', 'P7937'):
            supported.update(TYPE_MAP[qid][0] for qid in claim_ids(payload, prop) if qid in TYPE_MAP)
    specific = supported - GENERIC_TYPES
    # Conflicting specific assertions require review, not arbitrary supplier order.
    if len(specific) == 1:
        candidate = specific.pop()
        if code == 'book' and candidate not in BOOK_TYPES:
            return code
        return candidate
    if code in {'unknown', 'literary-work', 'written-work', 'creative-work'} and not specific and 'book' in supported:
        return 'book'
    return code


def aliases(work):
    for record in work.source_records.all():
        payload = record.raw_payload
        if not isinstance(payload, dict):
            continue
        if payload.get('id', '').startswith('Q'):
            for entries in payload.get('aliases', {}).values():
                for entry in entries:
                    if isinstance(entry, dict) and isinstance(entry.get('value'), str):
                        yield entry['value']
        data = payload.get('work', payload)
        if isinstance(data, dict):
            for title in data.get('alternative_titles', []) or []:
                if isinstance(title, str):
                    yield title


def partial_match(value, query):
    words, terms = value.split(), query.split()
    return any(all(word.startswith(term) for word, term in zip(words[offset:], terms))
               for offset in range(len(words) - len(terms) + 1))


def match_score(work, query):
    title = normalize_search(work.title) if work.has_known_title else ''
    names = [normalize_search(value) for value in aliases(work)]
    if query == title:
        return 0, 0
    if query in names:
        return 1, 0
    # Word sequences, not accidental matches inside unrelated words.
    if title and partial_match(title, query):
        return 2, len(title) - len(query)
    matching_aliases = [name for name in names if partial_match(name, query)]
    if matching_aliases:
        return 3, min(len(name) for name in matching_aliases) - len(query)
    creators = [normalize_search(c.agent.name) for c in work.credits.all()]
    matching_creators = [name for name in creators if partial_match(name, query)]
    if matching_creators:
        return 4, min(len(name) for name in matching_creators) - len(query)
    return None

"""Direct public connections, grouped by stable work identity.

Only the current work's accepted neighborhood is considered. Supplier snapshots
are needed to use the same evidence-aware type labels as catalog discovery.
Relationship evidence is fetched only for works on the selected page.
"""
from django.core.paginator import Paginator
from django.db.models import Q

from .models import WorkRelationship
from .presentation import normalize_search
from .ranking import metadata_richness, select_timeline_highlights, work_language

PAGE_SIZE = 12

# Version-level links describe a specific edition or translation, not a new
# work. They stay in the research list, but they are not timeline material.
VERSION_LEVEL_CODES = {"edition-of", "translation-of", "abridgment-of", "modernization-of"}

GROUPS = (
    "Source works",
    "Adaptations",
    "Other direct connections",
    "Edition and translation links",
)


def _year_param(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() and len(value) <= 4 else None


def relationship_label(code, label, inverse_label, forward):
    # P144's broader "based-on" assertion must retain its stored inverse wording;
    # it does not distinguish inspiration from adaptation.
    if code == 'adapted-from':
        return 'Based on' if forward else 'Adapted into'
    return label if forward else inverse_label


def direction_label(relationship, current_id):
    kind = relationship.relationship_type
    return relationship_label(kind.code, kind.label, kind.inverse_label,
                              relationship.from_work_id == current_id)


def evidence_details(relationship):
    from .provenance import relationship_provenance, rights_provenance, safe_url
    relationship.display_label = direction_label(relationship, relationship.current_work_id)
    evidence = relationship.evidence if isinstance(relationship.evidence, dict) else {}
    links = []
    def add(url, label):
        # Render only navigable HTTP sources, never arbitrary supplier schemes.
        if safe_url(url) and url not in [u for u, _ in links]:
            links.append((url, label))
    add(relationship.evidence_url, 'Supporting statement')
    add(relationship.source.url, relationship.source.title)
    # Wikidata references preserve their snak structure; P854 is reference URL.
    references = evidence.get('references', [])
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            snaks = reference.get('snaks', {})
            if not isinstance(snaks, dict) or not isinstance(snaks.get('P854', []), list):
                continue
            for snak in snaks.get('P854', []):
                if isinstance(snak, dict) and isinstance(snak.get('datavalue'), dict):
                    add(snak['datavalue'].get('value'), 'Reference')
    if evidence.get('source_invalidated'):
        links = []
    return {
        'provenance': relationship_provenance(relationship),
        'rights_provenance': rights_provenance(relationship) if relationship.authorization_statement else None,
        'label': direction_label(relationship, relationship.current_work_id),
        'exact': relationship.relationship_type.label,
        'from_work': relationship.from_work,
        'to_work': relationship.to_work,
        'review': relationship.get_review_status_display(),
        'origin': f"Imported assertion: {evidence['asserted_by']}" if evidence.get('asserted_by') else 'Origin not recorded',
        'links': links,
        'source_title': 'Source not recorded for this field' if evidence.get('source_invalidated') else relationship.source.title,
        'source_note': '',
        'authorization_statement': relationship.authorization_statement,
        'note': relationship.scope_note or evidence.get('excerpt') or evidence.get('note') or '',
        'statement_id': evidence.get('statement_id', ''),
        'property_id': evidence.get('property_id', ''),
        'retrieved_at': evidence.get('retrieved_at', ''),
    }


def connections_context(request, work, public):
    edges = WorkRelationship.objects.filter(review_status='accepted').filter(
        Q(from_work=work, to_work__in=public) | Q(to_work=work, from_work__in=public)
    )
    # A small metadata projection avoids loading all evidence for pagination.
    metadata = list(edges.values_list('from_work_id', 'to_work_id', 'relationship_type_id',
                                     'relationship_type__label', 'relationship_type__inverse_label'))
    by_work = {}
    choices = {}
    priorities = {}
    for source, target, code, label, inverse in metadata:
        other = target if source == work.pk else source
        direction = 'out' if source == work.pk else 'in'
        key = f'{direction}:{code}'
        choices[key] = relationship_label(code, label, inverse, direction == 'out')
        by_work.setdefault(other, set()).add(key)
        priority = (0 if direction == 'out' else 1) if code == 'adapted-from' else 2
        if code in VERSION_LEVEL_CODES:
            priority = 3
        priorities[other] = min(priorities.get(other, 3), priority)
    related = list(public.filter(pk__in=by_work).select_related('work_type').prefetch_related(
        'source_records', 'credits__agent', 'versions'
    ))
    types = {w.public_type_code: w.public_type_label for w in related}
    prominence = {w.pk: metadata_richness(w) for w in related}
    work_languages = {w.pk: work_language(w) for w in related}
    languages = {language: language for language in work_languages.values() if language}
    if any(not language for language in work_languages.values()):
        languages['__unknown__'] = 'Language not recorded'
    timeline_events = []
    for item in related:
        if not item.first_publication_year:
            continue
        keys = by_work[item.pk]
        if all(key.split(':', 1)[1] in VERSION_LEVEL_CODES for key in keys):
            continue
        primary = next(
            (key for key in ('in:adapted-from', 'out:adapted-from') if key in keys),
            sorted(keys)[0],
        )
        timeline_events.append({
            'work': item,
            'year': item.first_publication_year,
            'date': item.first_publication_date_text,
            'label': choices[primary],
            'other_relationships': max(len(keys) - 1, 0),
            'type': item.public_type_label,
            'language': work_languages[item.pk],
            'prominence': prominence[item.pk]['score'],
            'signals': prominence[item.pk]['signals'],
        })
    timeline_events.sort(key=lambda event: (
        event['year'], normalize_search(event['work'].display_title), event['work'].pk
    ))
    query = request.GET.get('connection_q', '').strip()[:200]
    relationship = request.GET.get('connection_relationship', '')
    work_type = request.GET.get('connection_type', '')
    language = request.GET.get('connection_language', '')
    year_from = _year_param(request.GET.get('connection_year_from'))
    year_to = _year_param(request.GET.get('connection_year_to'))
    sort = request.GET.get('connection_sort', 'group')
    # Invalid choices are ignored rather than silently producing an empty table.
    relationship = relationship if relationship in choices else ''
    work_type = work_type if work_type in types else ''
    language = language if language in languages else ''
    sort = sort if sort in {'group', 'title', 'date', '-date', 'prominence'} else 'group'
    normalized = normalize_search(query)

    def matches(item):
        item_language = work_languages[item.pk]
        if normalized and normalized not in normalize_search(item.display_title) and query != str(item.pk):
            return False
        if relationship and relationship not in by_work[item.pk]:
            return False
        if work_type and item.public_type_code != work_type:
            return False
        if language == '__unknown__' and item_language:
            return False
        if language and language != '__unknown__' and item_language != language:
            return False
        if year_from is not None and (item.first_publication_year is None or item.first_publication_year < year_from):
            return False
        if year_to is not None and (item.first_publication_year is None or item.first_publication_year > year_to):
            return False
        return True

    filtered = [w for w in related if matches(w)]
    if sort in {'date', '-date'}:
        filtered.sort(key=lambda w: (w.first_publication_year is None,
            (w.first_publication_year or 0) * (-1 if sort == '-date' else 1), normalize_search(w.display_title), w.pk))
    elif sort == 'prominence':
        filtered.sort(key=lambda w: (-prominence[w.pk]['score'], normalize_search(w.display_title), w.pk))
    else:
        filtered.sort(key=lambda w: ((priorities[w.pk] if sort == 'group' else 0), normalize_search(w.display_title), w.pk))
    matching_ids = {w.pk for w in filtered}
    timeline_events = [event for event in timeline_events if event['work'].pk in matching_ids]
    timeline_years = [event['year'] for event in timeline_events]
    timeline_labels = {event['label'] for event in timeline_events}
    timeline_uniform_label = next(iter(timeline_labels)) if len(timeline_labels) == 1 else ''
    timeline_highlights = select_timeline_highlights(timeline_events)
    page = Paginator(filtered, PAGE_SIZE).get_page(request.GET.get('connection_page'))
    page_ids = [w.pk for w in page.object_list]
    page_edges = edges.filter(Q(from_work_id__in=page_ids) | Q(to_work_id__in=page_ids)).select_related(
        'relationship_type', 'source', 'from_work__work_type', 'to_work__work_type'
    ).order_by('relationship_type_id', 'pk')
    rows = {w.pk: {
        'work': w,
        'relationships': [],
        'group': GROUPS[priorities[w.pk]],
        'prominence': prominence[w.pk],
        'language': work_languages[w.pk],
    } for w in page.object_list}
    # Reuse cached identities for evidence wording, avoiding queries on fallback titles.
    identities = {w.pk: w for w in page.object_list}
    identities[work.pk] = work
    for edge in page_edges:
        edge.current_work_id = work.pk
        edge.from_work = identities[edge.from_work_id]
        edge.to_work = identities[edge.to_work_id]
        other = edge.to_work_id if edge.from_work_id == work.pk else edge.from_work_id
        rows[other]['relationships'].append(evidence_details(edge))
    params = request.GET.copy()
    params.pop('connection_page', None)
    def page_url(number):
        next_params = params.copy()
        next_params['connection_page'] = number
        return '?' + next_params.urlencode() + '#connections'
    return {
        'connection_rows': list(rows.values()), 'connection_page': page,
        'connection_total': len(related), 'connection_assertions': len(metadata),
        'connection_choices': sorted(choices.items(), key=lambda item: item[1]),
        'connection_types': sorted(types.items(), key=lambda item: item[1]),
        'connection_languages': sorted(languages.items(), key=lambda item: item[1]),
        'connection_q': query, 'connection_relationship': relationship,
        'connection_type': work_type, 'connection_language': language,
        'connection_year_from': year_from or '', 'connection_year_to': year_to or '',
        'connection_sort': sort,
        'connection_has_filters': bool(
            query or relationship or work_type or language or year_from or year_to or sort != 'group'
        ),
        'connection_matching': len(filtered),
        'connection_previous': page_url(page.previous_page_number()) if page.has_previous() else '',
        'connection_next': page_url(page.next_page_number()) if page.has_next() else '',
        'has_relationships': bool(related),
        'timeline_events': timeline_events,
        'timeline_highlight_events': timeline_highlights,
        'timeline_has_highlights': len(timeline_highlights) < len(timeline_events),
        'timeline_uniform_label': timeline_uniform_label,
        'timeline_show_labels': len(timeline_labels) > 1,
        'timeline_undated': len(filtered) - len(timeline_events),
        'timeline_start': timeline_years[0] if timeline_years else None,
        'timeline_end': timeline_years[-1] if timeline_years else None,
    }

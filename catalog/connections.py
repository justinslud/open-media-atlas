"""Direct public connections, grouped by stable work identity.

Only the current work's accepted neighborhood is considered. Supplier snapshots
are needed to use the same evidence-aware type labels as catalog discovery.
Relationship evidence is fetched only for works on the selected page.
"""
from django.core.paginator import Paginator
from django.db.models import Q

from .models import WorkRelationship
from .presentation import normalize_search

PAGE_SIZE = 12


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
        priorities[other] = min(priorities.get(other, 2), priority)
    related = list(public.filter(pk__in=by_work).select_related('work_type').prefetch_related('source_records', 'credits__agent'))
    types = {w.public_type_code: w.public_type_label for w in related}
    query = request.GET.get('connection_q', '').strip()[:200]
    relationship = request.GET.get('connection_relationship', '')
    work_type = request.GET.get('connection_type', '')
    sort = request.GET.get('connection_sort', 'group')
    # Invalid choices are ignored rather than silently producing an empty table.
    relationship = relationship if relationship in choices else ''
    work_type = work_type if work_type in types else ''
    sort = sort if sort in {'group', 'title', 'date', '-date'} else 'group'
    normalized = normalize_search(query)
    filtered = [w for w in related if
                (not normalized or normalized in normalize_search(w.display_title) or query == str(w.pk)) and
                (not relationship or relationship in by_work[w.pk]) and
                (not work_type or w.public_type_code == work_type)]
    if sort in {'date', '-date'}:
        filtered.sort(key=lambda w: (w.first_publication_year is None,
            (w.first_publication_year or 0) * (-1 if sort == '-date' else 1), normalize_search(w.display_title), w.pk))
    else:
        filtered.sort(key=lambda w: ((priorities[w.pk] if sort == 'group' else 0), normalize_search(w.display_title), w.pk))
    page = Paginator(filtered, PAGE_SIZE).get_page(request.GET.get('connection_page'))
    page_ids = [w.pk for w in page.object_list]
    page_edges = edges.filter(Q(from_work_id__in=page_ids) | Q(to_work_id__in=page_ids)).select_related(
        'relationship_type', 'source', 'from_work__work_type', 'to_work__work_type'
    ).order_by('relationship_type_id', 'pk')
    rows = {w.pk: {'work': w, 'relationships': [], 'group': ('Source works', 'Adaptations', 'Other direct connections')[priorities[w.pk]]} for w in page.object_list}
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
        'connection_q': query, 'connection_relationship': relationship,
        'connection_type': work_type, 'connection_sort': sort,
        'connection_has_filters': bool(query or relationship or work_type or sort != 'group'),
        'connection_previous': page_url(page.previous_page_number()) if page.has_previous() else '',
        'connection_next': page_url(page.next_page_number()) if page.has_next() else '',
        'has_relationships': bool(related),
    }

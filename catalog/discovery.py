"""Modest catalog discovery on Django's existing database and source snapshots."""
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When

from .models import Credit, FeaturedWork
from .presentation import BOOK_TYPES, match_score, normalize_search


def catalog_queryset(public):
    return public.select_related('work_type').prefetch_related('credits__agent', 'source_records').annotate(
        connection_count=Count('outgoing_relationships', filter=Q(
            outgoing_relationships__review_status='accepted', outgoing_relationships__to_work__in=public), distinct=True)
        + Count('incoming_relationships', filter=Q(
            incoming_relationships__review_status='accepted', incoming_relationships__from_work__in=public), distinct=True),
        selected=Exists(FeaturedWork.objects.filter(work_id=OuterRef('pk'))),
        has_creator=Exists(Credit.objects.filter(work_id=OuterRef('pk'))),
    ).annotate(
        known_title=Case(When(Q(title__regex=r'^\s*$') | Q(title__iregex=r'^\s*Q\d+\s*$'), then=Value(0)), default=Value(1), output_field=IntegerField()),
        reviewed_connection=Case(When(connection_count__gt=0, then=Value(1)), default=Value(0), output_field=IntegerField()),
        editorial=Case(When(depth='editorial', then=Value(1)), default=Value(0), output_field=IntegerField()),
    )


DISCOVERY_ORDER = ('-selected', '-known_title', '-has_creator', '-editorial', '-reviewed_connection', 'title', 'id')


def filter_public_type(works, code):
    # The raw supplier type is retained. Membership uses the same evidence-backed
    # presentation as result/detail labels, including already-cached novel claims.
    members = {
        'book': BOOK_TYPES,
        'unclassified': {'creative-work', 'unknown'},
        'written-work': {'literary-work', 'written-work'},
    }.get(code, {code})
    ids = [work.pk for work in works if work.public_type_code in members]
    return works.filter(pk__in=ids)


def search(works, query):
    normalized = normalize_search(query)
    if not normalized:
        return works.none()
    ranks = {w.pk: rank for w in works if (rank := match_score(w, normalized)) is not None}
    return works.filter(pk__in=ranks).annotate(relevance=Case(
        *(When(pk__in=[pk for pk, value in ranks.items() if value[0] == rank], then=Value(rank))
          for rank in range(5)),
        default=Value(5), output_field=IntegerField()),
        relevance_distance=Case(
            *(When(pk__in=[pk for pk, value in ranks.items() if value[1] == distance], then=Value(distance))
              for distance in sorted({value[1] for value in ranks.values()})),
            default=Value(0), output_field=IntegerField()))

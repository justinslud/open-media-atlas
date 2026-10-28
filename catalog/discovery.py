"""Modest catalog discovery on Django's existing database and source snapshots."""
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.db.models import prefetch_related_objects

from .models import Credit, FeaturedWork
from .presentation import BOOK_TYPES, match_score, normalize_search

# Django renders a wide prefetch predicate as a long OR chain. SQLite refuses
# expression trees deeper than 1000, so wide prefetches are loaded in batches.
PREFETCH_BATCH = 250
CATALOG_PREFETCHES = ('credits__agent', 'source_records')


def catalog_queryset(public):
    return public.select_related('work_type').annotate(
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


# Ambient records stay public and reachable, but they are not browsing material:
# a random Open Library slice is a reference tail, not a curated shelf.
AMBIENT_DEPTH = "ambient"


def browsable(works):
    """Exclude ambient reference records from browsing surfaces."""
    return works.exclude(depth=AMBIENT_DEPTH)


DISCOVERY_ORDER = ('-selected', '-known_title', '-has_creator', '-editorial', '-reviewed_connection', 'title', 'id')


def load_related(works):
    """Evaluate works with their related rows, batched to stay under SQLite limits."""
    items = list(works.prefetch_related(None))
    for start in range(0, len(items), PREFETCH_BATCH):
        prefetch_related_objects(items[start:start + PREFETCH_BATCH], *CATALOG_PREFETCHES)
    return items


def filter_public_type(works, code):
    # The raw supplier type is retained. Membership uses the same evidence-backed
    # presentation as result/detail labels, including already-cached novel claims.
    members = {
        'book': BOOK_TYPES,
        'unclassified': {'creative-work', 'unknown'},
        'written-work': {'literary-work', 'written-work'},
    }.get(code, {code})
    ids = [work.pk for work in load_related(works) if work.public_type_code in members]
    return works.filter(pk__in=ids)


# Distances beyond this are indistinguishable in practice, and collapsing them
# keeps the generated CASE expression small enough for SQLite's tree-depth limit.
MAX_RELEVANCE_DISTANCE = 40


def search(works, query):
    normalized = normalize_search(query)
    if not normalized:
        return works.none()
    ranks = {w.pk: rank for w in load_related(works) if (rank := match_score(w, normalized)) is not None}
    distances = {pk: min(value[1], MAX_RELEVANCE_DISTANCE) for pk, value in ranks.items()}
    return works.filter(pk__in=ranks).annotate(relevance=Case(
        *(When(pk__in=[pk for pk, value in ranks.items() if value[0] == rank], then=Value(rank))
          for rank in range(5)),
        default=Value(5), output_field=IntegerField()),
        relevance_distance=Case(
            *(When(pk__in=[pk for pk, distance in distances.items() if distance == value], then=Value(value))
              for value in sorted(set(distances.values()))),
            default=Value(0), output_field=IntegerField()))

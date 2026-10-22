"""Transparent metadata-richness signals for browsing.

This is deliberately separate from publication triage. Triage answers "is this
edge safe to publish?"; richness answers "which records are useful to surface
first?" It is not an editorial quality score and does not infer importance.
"""
from .presentation import normalize_search

GENERIC_TYPES = {"book", "creative-work", "literary-work", "written-work", "unknown"}


def sitelink_count(work):
    for record in work.source_records.all():
        payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
        if str(payload.get("id", "")).startswith("Q"):
            sitelinks = payload.get("sitelinks", {})
            if isinstance(sitelinks, dict):
                return len(sitelinks)
    return 0


def work_language(work):
    versions = list(work.versions.all())
    for version in versions:
        if version.kind == "original" and version.language:
            return version.language
    for version in versions:
        if version.language:
            return version.language
    return ""


def metadata_richness(work):
    """Return a bounded score plus human-readable signals.

    The score only reflects data already present in OMA. It is used for
    ordering and timeline highlights, never for publication decisions.
    """
    score = 0
    signals = []
    sitelinks = sitelink_count(work)
    if sitelinks:
        score += min(sitelinks, 25) * 2
        signals.append(f"{sitelinks} sitelink{'s' if sitelinks != 1 else ''}")
    if work.image_url:
        score += 6
        signals.append("licensed image")
    if work.description:
        score += 2
        signals.append("description")
    language = work_language(work)
    if language:
        score += 4
        signals.append(f"language: {language}")
    evidence = work.date_evidence if isinstance(work.date_evidence, dict) else {}
    precision = evidence.get("precision")
    if precision == 11:
        score += 4
        signals.append("full date")
    elif precision == 10:
        score += 3
        signals.append("month-level date")
    elif work.first_publication_year:
        score += 2
        signals.append("year")
    if work.public_type_code not in GENERIC_TYPES:
        score += 3
        signals.append("specific type")
    if work.has_known_title:
        score += 2
        signals.append("known title")
    return {"score": score, "signals": signals}


def select_timeline_highlights(events, limit=12):
    """Pick a varied, metadata-rich subset while keeping chronology.

    The full timeline stays available for research. Highlights favour records
    with more source metadata, then fill gaps with the first event of each type,
    the earliest event, and the latest event. Duplicate display titles are
    avoided so an eponymous adaptation does not crowd out the overview.
    """
    if len(events) <= limit:
        return list(events)

    selected = []
    seen_ids = set()
    seen_titles = set()
    seen_types = set()

    def add(event):
        work = event["work"]
        title = normalize_search(work.display_title)
        if len(selected) >= limit or work.pk in seen_ids or title in seen_titles:
            return
        selected.append(event)
        seen_ids.add(work.pk)
        seen_titles.add(title)
        seen_types.add(work.public_type_code)

    for event in sorted(events, key=lambda item: (
        -item.get("prominence", 0),
        item["year"],
        normalize_search(item["work"].display_title),
        item["work"].pk,
    ))[:max(4, limit // 2)]:
        add(event)
    for event in events:
        if event["work"].public_type_code not in seen_types:
            add(event)
    add(events[0])
    add(events[-1])
    for event in events:
        if len(selected) >= limit:
            break
        add(event)
    selected.sort(key=lambda item: (
        item["year"], normalize_search(item["work"].display_title), item["work"].pk
    ))
    return selected

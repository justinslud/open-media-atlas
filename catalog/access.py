"""Small access-link projection and review payloads; no remote fetching."""
import json
from urllib.parse import urlencode
from django.core.exceptions import ValidationError
from django.urls import reverse
from .models import AccessLink
from .provenance import safe_url

LINK_FIELDS = ("provider", "url", "category", "version_id", "release_id", "scope_note", "language", "region", "restrictions", "last_checked", "active")


def link_snapshot(link):
    values = {field: getattr(link, field) for field in LINK_FIELDS}
    values["last_checked"] = str(link.last_checked) if link.last_checked else None
    values["source_url"] = link.source_url
    values["reviewed_at"] = str(link.reviewed_at) if link.reviewed_at else None
    return json.dumps(values, sort_keys=True)


def proposed_link(proposal):
    try:
        values = json.loads(proposal.proposed_value)
        if not isinstance(values, dict) or set(values) != set(LINK_FIELDS):
            raise ValueError
        if not isinstance(values.get("active", True), bool):
            raise ValueError
        link = AccessLink(work=proposal.work, **values)
        if proposal.target_access_link_id:
            link.pk = proposal.target_access_link_id
            link._state.adding = False
        elif not link.active:
            raise ValidationError("A removal report must identify an existing link.")
        link.full_clean()
        return link
    except (ValueError, TypeError) as error:
        raise ValidationError("Invalid access-link proposal.") from error


def access_context(work):
    groups = {"direct": [], "offers": [], "reference": [], "search": []}
    for link in work.access_links.all():
        url = safe_url(link.url)
        if not link.active or not url:
            continue
        group = ("direct" if link.category in {"full", "excerpt"} else
                 "offers" if link.category in {"borrow", "buy", "rent", "subscription"} else
                 "search" if link.category == "search" else "reference")
        scope = link.scope_note
        if link.release_id:
            scope = f"{link.release.version.label} — {link.release.edition_name or link.release.title}" + (f" · {scope}" if scope else "")
        elif link.version_id:
            scope = link.version.label + (f" · {scope}" if scope else "")
        else:
            scope = scope or "Edition / version not specified"
        groups[group].append({"link": link, "url": url, "scope": scope,
            "title": f"Search {link.provider}" if group == "search" else f"{link.provider} — {link.get_category_display()}",
            "entry": {"value": link.get_category_display(), "state": "Human-reviewed description" if link.reviewed_at else "Recorded description; human review not recorded",
                      "source": "Supporting source" if link.source_url else "", "url": safe_url(link.source_url), "reviewed_at": link.reviewed_at},
            "correction_url": reverse("suggest-access", args=[work.pk]) + f"?link={link.pk}"})
    has_access = bool(groups["direct"] or groups["offers"])
    medium = work.work_type.medium
    heading = {"text": "Read", "screen": "Watch", "audio": "Listen"}.get(medium, "Access options")
    # Search is navigation, never an asserted match or copy. Avoid searching unknown titles.
    if not has_access and not groups["search"] and work.has_known_title and not work.is_demo:
        provider = "Open Library" if medium == "text" else "Internet Archive"
        url = ("https://openlibrary.org/search?" + urlencode({"q": work.title}) if medium == "text" else
               "https://archive.org/search?" + urlencode({"query": work.title}))
        groups["search"].append({"url": url, "title": f"Search {provider}"})
    references = [{"title": link.source.title, "url": safe_url(link.source.url), "note": link.note} for link in work.source_links.all()]
    return {"access_heading": heading, "access_groups": groups, "has_access": has_access, "reference_links": references}

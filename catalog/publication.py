"""Shared publication rules: what counts as a seed, and what is fit to publish.

Triage, promotion, and audits must agree on these definitions. Keeping them in
one module stops the pipeline from generating proposals against works that its
own triage rule would reject.
"""
from .models import Work

# A seed is a work OMA deliberately uses as a relationship anchor.
SEED_SCOPES = ("editorial", "public", "any")

# "book" is a real public type here; only supplier placeholders count as generic.
GENERIC_TYPE_CODES = {"creative-work", "literary-work", "written-work", "unknown"}

MAX_TITLE_LENGTH = 80

WARNING_LABELS = {
    "no_date": "no recorded year",
    "no_creator": "no credited creator",
    "generic_type": "generic or unclassified type",
    "long_title": f"title longer than {MAX_TITLE_LENGTH} characters",
    "placeholder_title": "title is empty or a bare QID",
    "demo_work": "demo fixture record",
    "undated_ok": "undated records stay draft unless forced",
}

# Warnings that block promotion unless the caller explicitly allows them.
BLOCKING_WARNINGS = {"placeholder_title", "demo_work"}


def is_seed(work, scope="editorial"):
    """Return True when the work may act as a relationship seed for this scope."""
    if scope not in SEED_SCOPES:
        raise ValueError(f"unknown seed scope: {scope}")
    if work.visibility != Work.Visibility.PUBLIC:
        return False
    if scope == "editorial":
        return work.depth == "editorial"
    return True


def publication_warnings(work):
    """Return machine-readable reasons the work is not ready for public display."""
    warnings = []
    if not work.first_publication_year:
        warnings.append("no_date")
    if not work.credits.exists():
        warnings.append("no_creator")
    if work.work_type_id in GENERIC_TYPE_CODES:
        warnings.append("generic_type")
    title = (work.title or "").strip()
    if not title or (title.upper().startswith("Q") and title[1:].isdigit()):
        warnings.append("placeholder_title")
    elif len(title) > MAX_TITLE_LENGTH:
        warnings.append("long_title")
    if work.is_demo:
        warnings.append("demo_work")
    return warnings


def blocking_reasons(work, require=()):
    """Return the reasons a promotion attempt must refuse this work."""
    warnings = publication_warnings(work)
    reasons = [code for code in warnings if code in BLOCKING_WARNINGS]
    for code in require:
        if code in warnings and code not in reasons:
            reasons.append(code)
    return reasons

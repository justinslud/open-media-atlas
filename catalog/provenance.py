"""Public, allowlisted evidence presentation. Never expose raw payloads or review notes."""
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.urls import reverse
from django.db import transaction
from .models import FieldEvidence, ImportedWorkState

FIELDS = {"title": "Primary title", "work_type": "Work type", "first_publication_date_text": "Displayed date"}


def safe_url(value):
    if not isinstance(value, str):
        return ""
    try:
        URLValidator(schemes=["http", "https"])(value)
        from urllib.parse import urlsplit
        if urlsplit(value).username or urlsplit(value).password:
            return ""
        return value
    except (ValidationError, ValueError):
        return ""


def value_for(work, field):
    return str(getattr(work, "work_type_id" if field == "work_type" else field))


@transaction.atomic
def record_evidence(work, field, value, **metadata):
    if field not in FIELDS:
        raise ValueError("Unsupported provenance field")
    type(work).objects.select_for_update().get(pk=work.pk)
    FieldEvidence.objects.filter(work=work, field_name=field, current=True).update(current=False)
    return FieldEvidence.objects.create(work=work, field_name=field, value=str(value), **metadata)


def track_edit(previous, current):
    for field in FIELDS:
        old, new = value_for(previous, field), value_for(current, field)
        if old != new:
            if not FieldEvidence.objects.filter(work=current, field_name=field).exists():
                metadata = {}
                revision = previous.contribution_revisions.filter(field_name=field, kind="correction").first()
                if revision and revision.new_value == old:
                    metadata = {"source_url": revision.source_url, "origin": "reviewed", "reviewed_at": revision.created_at}
                elif field == "first_publication_date_text":
                    evidence = previous.date_evidence if isinstance(previous.date_evidence, dict) else {}
                    if evidence.get("date_text") == old and safe_url(evidence.get("source_url")):
                        metadata = {"source_url": evidence["source_url"]}
                FieldEvidence.objects.create(work=current, field_name=field, value=old, current=False, **metadata)
            record_evidence(current, field, new)


def imported_fields(work, record, *, title, date, created=False, changed=(), type_note=""):
    """Only fields actually written by this import acquire a supplier association."""
    for field, value in (("title", title), ("first_publication_date_text", date), ("work_type", work.work_type_id)):
        if (created or field in changed) and str(value) == value_for(work, field):
            payload = record.raw_payload
            qid = payload.get("id", "") if isinstance(payload, dict) else ""
            url = f"https://www.wikidata.org/wiki/{qid}" if qid else f"https://openlibrary.org/works/{record.external_key}"
            note = type_note if field == "work_type" else ""
            if field == "first_publication_date_text" and qid:
                note = "Supplier date formatted at its recorded precision; publication preferred over inception, then supplier preferred rank when it uniquely resolves the value."
            record_evidence(work, field, value, source=record.source, source_record=record,
                            source_url=url, origin="imported", note=note, retrieved_at=record.retrieved_at)


def item(value, source="", url="", state="Recorded supplier value; selection history not recorded", **extra):
    return dict(value=value, source=source, url=safe_url(url), state=state, **extra)


def work_provenance(work):
    records = list(work.source_records.all())
    ledger = list(work.field_evidence.all())
    revisions = list(work.contribution_revisions.all())
    result = {}
    for field, label in FIELDS.items():
        value = value_for(work, field)
        entries, history, alternatives = [], [], []
        rows = [row for row in ledger if row.field_name == field]
        for row in rows:
            entry = item(row.value, row.source.title if row.source_id else "Recorded supporting source" if row.source_url else "", row.source_url,
                         state=("Human-reviewed" if row.origin == "reviewed" and row.reviewed_at else
                                f"Imported from {row.source.title}" if row.origin == "imported" and row.source_id else
                                "Recorded supporting source; human review not recorded" if row.source_url else "Source not recorded for this field"),
                         note=row.note, retrieved_at=row.retrieved_at, reviewed_at=row.reviewed_at)
            (entries if row.current and row.value == value else history).append(entry)
        if not rows:
            field_revisions = [revision for revision in revisions if revision.field_name == field and revision.kind == "correction"]
            for index, revision in enumerate(field_revisions):
                if revision.field_name == field and revision.kind == "correction":
                    entry = item(revision.new_value, "Reviewed correction source", revision.source_url,
                                 "Human-reviewed", reviewed_at=revision.created_at)
                    (entries if index == 0 and revision.new_value == value else history).append(entry)
            if field == "first_publication_date_text":
                evidence = work.date_evidence if isinstance(work.date_evidence, dict) else {}
                if evidence.get("date_text") == value and safe_url(evidence.get("source_url")) and not entries:
                    entries.append(item(value, "Recorded date source", evidence["source_url"], "Recorded supporting source; human review not recorded"))
        for record in records:
            payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
            candidate = None
            if field == "title":
                try:
                    candidate = record.work_state.imported_title
                except ImportedWorkState.DoesNotExist:
                    pass
            if field == "first_publication_date_text":
                try:
                    candidate = record.work_state.imported_date_text
                except ImportedWorkState.DoesNotExist:
                    pass
            qid = payload.get("id", "")
            url = f"https://www.wikidata.org/wiki/{qid}" if qid else f"https://openlibrary.org/works/{record.external_key}"
            if candidate:
                entry = item(candidate, record.source.title, url, retrieved_at=record.retrieved_at)
                if candidate != value:
                    alternatives.append(entry)
                elif not rows and not entries:
                    entries.append(entry)
            if field == "first_publication_date_text" and qid:
                from .dates import wikidata_date
                # Each stored statement may contain a real alternative; do not fetch it.
                for prop in ("P577", "P571"):
                    for claim in payload.get("claims", {}).get(prop, []):
                        text, _, _, kind, _ = wikidata_date({"id": qid, "claims": {prop: [claim]}})
                        if text and text != value:
                            alternatives.append(item(text, record.source.title, url, note=f"Recorded {kind} assertion ({prop}); may differ in scope or precision.", retrieved_at=record.retrieved_at))
        if field == "work_type":
            from .importers.wikidata import TYPE_MAP, claim_ids
            for record in records:
                payload = record.raw_payload
                if not isinstance(payload, dict):
                    continue
                codes = {TYPE_MAP[q][0] for prop in ("P31", "P7937") for q in claim_ids(payload, prop) if q in TYPE_MAP}
                for code in sorted(codes - {work.public_type_code}):
                    alternatives.append(item(code, record.source.title, f"https://www.wikidata.org/wiki/{payload.get('id', '')}",
                                             note="Stored supplier classification; broader and more specific types may coexist.", retrieved_at=record.retrieved_at))
        displayed = work.display_title if field == "title" else work.public_type_label if field == "work_type" else value
        meaning = {"title": "Primary catalog title.", "work_type": "Public format label derived from the catalog classification.",
                   "first_publication_date_text": work.date_label + ". An import or retrieval date is not a verification date."}[field]
        if field == "title" and displayed != value:
            meaning += " Title is missing; the display combines format, year when available, and creator or catalog ID."
        if field == "work_type":
            meaning += f" Catalog type code: {value}; public label: {displayed}."
            if work.public_type_code != value:
                meaning += " Existing display policy selects the uniquely supported specific classification in stored Wikidata P31/P7937 assertions."
                from .importers.wikidata import TYPE_MAP, claim_ids
                for record in records:
                    payload = record.raw_payload
                    if not isinstance(payload, dict):
                        continue
                    codes = {TYPE_MAP[q][0] for prop in ("P31", "P7937") for q in claim_ids(payload, prop) if q in TYPE_MAP}
                    if work.public_type_code in codes:
                        entries.append(item(displayed, record.source.title, f"https://www.wikidata.org/wiki/{payload.get('id', '')}",
                                            "Derived from stored supplier classifications; human review not recorded", retrieved_at=record.retrieved_at))
        alternatives = list({(entry["value"], entry["source"], entry["note"] if "note" in entry else ""): entry for entry in alternatives}.values())
        conflict = field == "title" and any(
            selected.get("url") and alternative.get("url") and selected["source"] != alternative["source"]
            for selected in entries for alternative in alternatives)
        result[field] = dict(conflict=conflict, label=label, value=displayed, meaning=meaning, entries=entries,
                             history=history, alternatives=alternatives, target=f"Work {work.pk}",
                             correction_url=reverse("suggest-correction", args=[work.pk]) + f"?field={field}")
    return result


def relationship_provenance(rel):
    evidence = rel.evidence if isinstance(rel.evidence, dict) else {}
    # Only a persisted review timestamp is a dated human review.
    reviewed = evidence.get("relationship_type_reviewed_at") or evidence.get("reviewed_at")
    entry = item(rel.scope_note, rel.source.title, evidence.get("relationship_type_source_url") or rel.evidence_url or rel.source.url,
                 "Human-reviewed" if reviewed else "Accepted catalog connection; human review date not recorded",
                 note=rel.scope_note, retrieved_at=evidence.get("retrieved_at"), reviewed_at=reviewed)
    if evidence.get("source_invalidated"):
        entry = item(rel.scope_note, state="Source not recorded for this field")
    entries = [entry]
    if evidence.get("scope_note_source_url"):
        entries.append(item(rel.scope_note, "Reviewed relationship note source", evidence["scope_note_source_url"],
                            "Human-reviewed", reviewed_at=evidence.get("scope_note_reviewed_at")))
    return dict(label="Direct relationship", value=rel.display_label, target=f"Relationship {rel.pk}",
                meaning="Direct catalog connection. Relationship review does not establish authorization or rights.",
                entries=entries, history=[item(row.get("value", ""), "Previous correction source", row.get("source_url", ""), "Historical value") for row in evidence.get("correction_history", []) if isinstance(row, dict)], alternatives=[],
                correction_url=reverse("suggest-correction", args=[rel.from_work_id]) + f"?field=relationship_type&relationship={rel.pk}")


def rights_provenance(rel):
    evidence = rel.evidence if isinstance(rel.evidence, dict) else {}
    matching = evidence.get("authorization_statement_value", rel.authorization_statement) == rel.authorization_statement
    reviewed = evidence.get("authorization_statement_reviewed_at") if matching else None
    url = evidence.get("authorization_statement_source_url") if matching else None
    return dict(label="Attributed rights statement", value=rel.authorization_statement,
                meaning="A recorded statement attributed to its source; OMA does not adjudicate rights or infer adaptation authorization.",
                target=f"Relationship {rel.pk}",
                entries=[item(rel.authorization_statement, "Reviewed rights statement source" if url else rel.source.title, (url or rel.evidence_url or rel.source.url) if matching else "",
                              "Source not recorded for this field" if not matching else "Human-reviewed" if reviewed else "Attributed source statement; separate field review not recorded", reviewed_at=reviewed)],
                history=[item(row.get("value", ""), "Previous statement source", row.get("source_url", ""), "Historical value") for row in evidence.get("correction_history", []) if isinstance(row, dict) and row.get("field") == "authorization_statement"],
                alternatives=[], correction_url=reverse("suggest-correction", args=[rel.from_work_id]) + f"?field=authorization_statement&relationship={rel.pk}")

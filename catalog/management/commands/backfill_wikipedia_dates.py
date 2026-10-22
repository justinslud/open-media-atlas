"""Recover first-publication / first-release years from Wikipedia infoboxes.

This is a conservative, provenance-preserving tertiary-source pass. It reads
only the page's infobox, recognises explicit date fields, stores the exact
revision it used in a Wikipedia SourceRecord, and marks the resulting work date
as unverified. It never edits a work that already has a year and never touches
restricted film databases.
"""
import hashlib
import json
import re
import time
import unicodedata
from datetime import date
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import ImportRelationshipProposal, Source, SourceRecord, Work

YEAR = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)")
YEAR_RANGE = re.compile(r"\d{4}\s*[-–—]\s*\d{4}")
INFOBOX_START = re.compile(
    r"\{\{\s*((?:Infobox|Infoboîte|Infoboks|Ficha|Карточка|信息框|インフォボックス)[^\n{}|]*)",
    re.I,
)
USER_AGENT = "OpenMediaAtlas/0.1 (local research; Wikipedia infobox provenance)"

# Normalised infobox field names. Normalisation lower-cases, turns underscores
# into spaces, and strips Latin accents. Local-language names are included where
# the field is unambiguous.
DATE_FIELDS = {
    # English
    "released", "release date", "release", "first released", "first release",
    "original release", "original air date",
    "first aired", "airdate", "air date", "first air date", "first run",
    "pub date", "publication date", "published", "published date",
    "date published", "first published", "first publication",
    "premiere", "premiere date", "first performance", "opening date",
    "productions", "production", "inception",
    # German
    "erstausstrahlung", "erstsendung", "erstveroffentlichung",
    "veroffentlichung", "veroffentlichungsdatum", "urauffuhrung",
    "erstauffuhrung", "publikation", "erscheinungsdatum", "ua", "ejahr",
    # French
    "date de sortie", "sortie", "premiere", "date de premiere",
    "premiere publication", "publication", "prepublication", "diffusion",
    "date de diffusion", "premiere diffusion",
    # Italian
    "data di uscita", "uscita", "prima", "pubblicazione",
    "data di pubblicazione",
    # Spanish
    "fecha de estreno", "estreno", "fecha de publicacion", "publicacion",
    "lanzamiento",
    # Portuguese
    "data de lancamento", "lancamento", "estreia", "publicacao",
    "data de estreia",
    # Russian
    "дата выхода", "выход", "премьера", "дата премьеры", "публикация",
    "дата публикации", "издание",
    # Polish
    "data premiery", "premiera", "wydanie", "data wydania", "publikacja",
    # Czech
    "premiera", "vydani", "publikace", "datum vydani",
    # Norwegian
    "forste sending", "utgivelse", "publisering",
}
# ``premiere`` is in both the French and Czech lists above; Python keeps one.
DATE_TEMPLATE_NAMES = {
    "start date", "start date and age", "film date", "release date",
    "premiere date", "first aired", "airdate", "date", "datum",
    "date de sortie", "sortie", "premiere", "urauffuhrung",
    "erstausstrahlung", "data", "fecha", "data di uscita",
    "publication date", "pub date",
}
CONTEXT_FIELDS = {
    "author", "director", "developer", "network", "country", "language",
    "genre", "based on", "starring", "composer", "lyricist", "book",
    "productions", "premiere", "released", "pub date", "publication date",
}
LANGUAGE_PRIORITY = {
    "en": 0, "de": 1, "fr": 2, "it": 3, "es": 4, "pt": 5, "ru": 6,
    "pl": 7, "cs": 8, "nl": 9, "sv": 10, "no": 11, "da": 12, "fi": 13,
    "hu": 14, "ro": 15, "tr": 16, "ja": 17, "zh": 18,
}
KIND_PRIORITY = {
    "first_performance": 0, "first_release": 0, "first_publication": 0,
    "production": 1, "release": 1, "publication": 1,
}


def normalise(value):
    value = unicodedata.normalize("NFKD", (value or "").replace("_", " "))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().lower()


MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7,
    "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
    # German
    "januar": 1, "februar": 2, "marz": 3, "mai": 5, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
    # French
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "dicembre": 12,
    # Spanish / Portuguese
    "enero": 1, "febrero": 2, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "marco": 3, "maio": 5, "junho": 6,
    "julho": 7, "setembro": 9, "outubro": 10, "novembro": 11,
    "dezembro": 12,
    # Russian genitive forms commonly used in dates
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
    "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
    "ноября": 11, "декабря": 12,
}
MONTH_WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ\u0400-\u04FF]+\.?"


def strip_refs(value):
    value = re.sub(r"<ref[^>]*/>", "", value or "", flags=re.I)
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.I | re.S)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    return value


def split_top_level(body, separator="|"):
    parts, buf = [], []
    curly = square = 0
    index = 0
    while index < len(body):
        if body.startswith("{{", index):
            curly += 1
            buf.append("{{")
            index += 2
        elif body.startswith("}}", index):
            curly = max(0, curly - 1)
            buf.append("}}")
            index += 2
        elif body.startswith("[[", index):
            square += 1
            buf.append("[[")
            index += 2
        elif body.startswith("]]", index):
            square = max(0, square - 1)
            buf.append("]]")
            index += 2
        elif body[index] == separator and curly == 0 and square == 0:
            parts.append("".join(buf))
            buf = []
            index += 1
        else:
            buf.append(body[index])
            index += 1
    parts.append("".join(buf))
    return parts


def balanced_template(text, start):
    depth = 0
    index = start
    while index < len(text):
        if text.startswith("{{", index):
            depth += 1
            index += 2
        elif text.startswith("}}", index):
            depth -= 1
            index += 2
            if depth == 0:
                return text[start + 2:index - 2]
        else:
            index += 1
    return ""


def parse_infobox_fields(body):
    fields = {}
    for chunk in split_top_level(body)[1:]:
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = normalise(key)
        if not key:
            continue
        fields.setdefault(key, value.strip())
    return fields


def extract_infobox(wikitext):
    candidates = []
    for match in INFOBOX_START.finditer(wikitext or ""):
        body = balanced_template(wikitext, match.start())
        if not body:
            continue
        fields = parse_infobox_fields(body)
        if fields:
            candidates.append({"template": match.group(1).strip(), "fields": fields})
    if not candidates:
        return None
    for candidate in candidates:
        if any(normalise(name) in DATE_FIELDS for name in candidate["fields"]):
            return candidate
    return candidates[0]


def _date_from_parts(year, month=None, day=None):
    if not 1500 <= year <= 2199:
        return None
    if month is not None and not 1 <= month <= 12:
        return None
    if day is not None and not 1 <= day <= 31:
        return None
    if day is not None and month is not None:
        try:
            date(year, month, day)
        except ValueError:
            return None
    if day is not None and month is not None:
        text = f"{year}-{month:02d}-{day:02d}"
        precision = 11
    elif month is not None:
        text = f"{year}-{month:02d}"
        precision = 10
    else:
        text = str(year)
        precision = 9
    return {"year": year, "text": text, "precision": precision}


def month_name_dates(value):
    text = re.sub(r"https?://\S+", "", strip_refs(value or ""))
    found, seen, full_keys = [], set(), set()

    def add(year, month=None, day=None):
        parsed = _date_from_parts(year, month, day)
        if not parsed:
            return
        key = (parsed["text"], parsed["precision"])
        if key in seen:
            return
        seen.add(key)
        parsed.update({"template": "", "raw": text[:500]})
        found.append(parsed)
        if month is not None:
            full_keys.add((year, month))

    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        add(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    for match in re.finditer(
        rf"\b(\d{{1,2}})\s+({MONTH_WORD})\s+(\d{{4}})\b", text, re.I
    ):
        month = MONTHS.get(normalise(match.group(2)).strip("."))
        if month:
            add(int(match.group(3)), month, int(match.group(1)))
    for match in re.finditer(
        rf"\b({MONTH_WORD})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text, re.I
    ):
        month = MONTHS.get(normalise(match.group(1)).strip("."))
        if month:
            add(int(match.group(3)), month, int(match.group(2)))
    for match in re.finditer(
        rf"\b({MONTH_WORD})\s+(\d{{4}})\b", text, re.I
    ):
        month = MONTHS.get(normalise(match.group(1)).strip("."))
        if month and (int(match.group(2)), month) not in full_keys:
            add(int(match.group(2)), month)
    return found


def dates_in_field(value):
    clean = strip_refs(value or "")
    found = []
    for template in re.findall(r"\{\{([^{}]*)\}\}", clean):
        parts = [part.strip() for part in template.split("|")]
        name = normalise(parts[0]).removeprefix("template:")
        if name not in DATE_TEMPLATE_NAMES:
            continue
        named = {}
        positional = []
        for part in parts[1:]:
            if "=" in part:
                key, item = part.split("=", 1)
                named[normalise(key)] = item.strip()
            elif part:
                positional.append(part)
        if named.get("year", "").isdigit():
            parsed = _date_from_parts(
                int(named["year"]),
                int(named["month"]) if named.get("month", "").isdigit() else None,
                int(named["day"]) if named.get("day", "").isdigit() else None,
            )
            if parsed:
                parsed.update({"template": name, "raw": template[:500]})
                found.append(parsed)
            continue
        # Positional date templates: 1985 | 6 | 7 and repeated triples.
        flat = "|" + "|".join(positional)
        pattern = re.compile(r"(?:^|\|)\s*(\d{4})(?:\s*\|\s*(\d{1,2}))?(?:\s*\|\s*(\d{1,2}))?")
        for match in pattern.finditer(flat):
            year = int(match.group(1))
            month = int(match.group(2)) if match.group(2) else None
            day = int(match.group(3)) if match.group(3) else None
            parsed = _date_from_parts(year, month, day)
            if parsed:
                parsed.update({"template": name, "raw": template[:500]})
                found.append(parsed)
    if found:
        return found
    month_dates = month_name_dates(clean)
    if month_dates:
        return month_dates
    plain = re.sub(r"https?://\S+", "", clean)
    result = []
    for year in YEAR.findall(plain):
        parsed = _date_from_parts(int(year))
        if parsed:
            parsed.update({"template": "", "raw": clean[:500]})
            result.append(parsed)
    return result


def date_kind_for_field(field, medium):
    field = normalise(field)
    if field in {"productions", "production"}:
        return "production"
    if field in {"ejahr", "inception"}:
        return "inception"
    if field in {"premiere", "premiere date", "first performance", "ua",
                 "urauffuhrung", "erstauffuhrung", "prima"}:
        return "release" if medium in {"screen", "audio", "text", "interactive"} else "first_performance"
    if field in {"opening date"}:
        return "first_performance" if medium == "stage" else "release"
    if medium == "stage" and field == "first run":
        return "first_performance"
    if field in {"first aired", "airdate", "air date", "first air date",
                 "original air date", "first run", "first released",
                 "first release", "erstausstrahlung", "erstsendung",
                 "diffusion", "date de diffusion", "premiere diffusion",
                 "estreia"}:
        return "first_release"
    if field in {"first published", "first publication", "premiere publication",
                 "prepublication"}:
        return "first_publication"
    if field in {"released", "release date", "release", "original release",
                 "sortie", "date de sortie", "data di uscita", "uscita",
                 "lanzamiento", "lancamento", "data de lancamento", "выход",
                 "дата выхода", "wydanie", "data wydania", "vydani"}:
        return "publication" if medium == "text" else "release"
    if field in {"pub date", "publication date", "published", "published date",
                 "date published", "publication", "publikation",
                 "публикация", "дата публикации", "издание", "publikacja",
                 "publikace", "издание"}:
        return "publication"
    if medium == "stage":
        return "production"
    if medium in {"screen", "audio", "interactive"}:
        return "release"
    return "publication"


def parse_infobox_dates(wikitext, medium):
    infobox = extract_infobox(wikitext)
    if not infobox:
        return None
    candidates = []
    for field, value in infobox["fields"].items():
        if normalise(field) not in DATE_FIELDS:
            continue
        for parsed in dates_in_field(value):
            candidates.append({
                **parsed,
                "field": field,
                "kind": date_kind_for_field(field, medium),
                "source_value": strip_refs(value).strip()[:500],
            })
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        row["year"],
        row["precision"],
        row["text"],
        KIND_PRIORITY.get(row["kind"], 9),
        normalise(row["field"]),
    ))
    selected = candidates[0]
    same_date = {(row["text"], row["precision"]) for row in candidates}
    text = selected["text"] if len(same_date) == 1 else str(selected["year"])
    context = {}
    for field, value in infobox["fields"].items():
        if normalise(field) in CONTEXT_FIELDS:
            context[field] = strip_refs(value).strip()[:500]
    return {
        "template": infobox["template"],
        "year": selected["year"],
        "text": text,
        "kind": selected["kind"],
        "selected": selected,
        "candidates": candidates,
        "context": context,
        "rule": (
            f"Wikipedia infobox field '{selected['field']}'; earliest date; "
            "tertiary source, not independently verified"
        ),
    }


def sitelinks_for(record):
    payload = record.raw_payload if record and isinstance(record.raw_payload, dict) else {}
    sitelinks = payload.get("sitelinks") or {}
    links = []
    for key, value in sitelinks.items():
        if not key.endswith("wiki") or key in {"commonswiki", "specieswiki", "metawiki"}:
            continue
        language = key[:-4]
        title = value.get("title", "") if isinstance(value, dict) else str(value)
        if title:
            links.append((language, title))
    links.sort(key=lambda item: (LANGUAGE_PRIORITY.get(item[0], 99), item[0]))
    return links


def fetch_page(language, title, attempts=4):
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "revisions", "rvprop": "content|ids|timestamp",
        "rvslots": "main", "titles": title, "redirects": "1", "maxlag": "5",
    }
    url = f"https://{language}.wikipedia.org/w/api.php?{urlencode(params)}"
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            page = (payload.get("query", {}).get("pages") or [{}])[0]
            if page.get("missing") or not page.get("revisions"):
                return None
            revision = page["revisions"][0]
            return {
                "pageid": page.get("pageid", ""),
                "title": page.get("title", title),
                "language": language,
                "revision_id": revision.get("revid", ""),
                "revision_timestamp": revision.get("timestamp", ""),
                "wikitext": revision.get("slots", {}).get("main", {}).get("content", ""),
            }
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    return None


def revision_url(page):
    title = quote(page["title"].replace(" ", "_"))
    if page.get("revision_id"):
        return (
            f"https://{page['language']}.wikipedia.org/w/index.php?"
            f"title={title}&oldid={page['revision_id']}"
        )
    return f"https://{page['language']}.wikipedia.org/wiki/{title}"


class Command(BaseCommand):
    help = "Backfill missing years from Wikipedia infobox date fields (CC BY-SA, provenance stored)."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("pending", "public", "all"), default="pending")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--ids", help="Comma-separated work IDs to retry.")
        parser.add_argument("--attempts", type=int, default=3, help="Languages to try per work.")
        parser.add_argument("--delay", type=float, default=2.0, help="Seconds between works; keep Wikipedia happy.")

    def handle(self, *args, **options):
        works = Work.objects.filter(is_demo=False, first_publication_year__isnull=True)
        if options["scope"] == "pending":
            pending_ids = set()
            for proposal in ImportRelationshipProposal.objects.filter(status="pending").select_related("from_work"):
                if not proposal.from_work.first_publication_year:
                    pending_ids.add(proposal.from_work_id)
            works = works.filter(pk__in=pending_ids)
        elif options["scope"] == "public":
            works = works.filter(visibility=Work.Visibility.PUBLIC)
        if options["ids"]:
            ids = [int(item) for item in options["ids"].split(",") if item.strip().isdigit()]
            works = works.filter(pk__in=ids)
        works = list(works.select_related("work_type").prefetch_related("source_records__source"))
        if options["limit"]:
            works = works[: options["limit"]]
        report = {
            "confirm": options["confirm"],
            "scope": options["scope"],
            "updated": [],
            "unresolved": [],
            "errors": [],
        }
        wikipedia, _ = Source.objects.get_or_create(
            title="Wikipedia", defaults={"kind": "webpage", "url": "https://www.wikipedia.org/"}
        )
        for work in works:
            record = next(
                (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                None,
            )
            links = sitelinks_for(record)
            if not links:
                report["unresolved"].append({"work": work.pk, "title": work.title, "reason": "no Wikipedia sitelink"})
                continue
            chosen = None
            used_page = None
            for language, title in links[: options["attempts"]]:
                try:
                    page = fetch_page(language, title)
                except Exception as exc:
                    report["errors"].append({
                        "work": work.pk, "title": work.title, "language": language,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                if not page:
                    continue
                try:
                    chosen = parse_infobox_dates(page["wikitext"], work.work_type.medium)
                except Exception as exc:
                    report["errors"].append({
                        "work": work.pk, "title": work.title, "language": language,
                        "error": f"parse {type(exc).__name__}: {exc}",
                    })
                    chosen = None
                if chosen:
                    used_page = page
                    break
                time.sleep(0.5)
            if not chosen or not used_page:
                report["unresolved"].append({
                    "work": work.pk, "title": work.title,
                    "reason": "no recognised infobox date on tried pages",
                    "tried": links[: options["attempts"]],
                })
                continue
            selected = chosen["selected"]
            url = revision_url(used_page)
            evidence = {
                "date_text": chosen["text"],
                "property": "wikipedia_infobox",
                "source": "Wikipedia",
                "source_url": url,
                "license": "CC BY-SA 4.0",
                "attribution": "Wikipedia contributors",
                "page_title": used_page["title"],
                "language": used_page["language"],
                "revision_id": used_page["revision_id"],
                "revision_timestamp": used_page["revision_timestamp"],
                "field": selected["field"],
                "template": chosen["template"],
                "selection_rule": chosen["rule"],
                "meaning_unverified": True,
                "candidates": [
                    {
                        "text": row["text"], "year": row["year"],
                        "precision": row["precision"], "field": row["field"],
                        "template": row.get("template", ""),
                        "source_value": row.get("source_value", "")[:300],
                    }
                    for row in chosen["candidates"]
                ],
            }
            if chosen.get("context"):
                evidence["infobox_context"] = chosen["context"]
            report["updated"].append({
                "work": work.pk, "title": work.title, "year": chosen["year"],
                "text": chosen["text"], "kind": chosen["kind"],
                "language": used_page["language"], "page": used_page["title"],
                "field": selected["field"],
            })
            if options["confirm"]:
                payload = {
                    "pageid": used_page["pageid"],
                    "title": used_page["title"],
                    "language": used_page["language"],
                    "url": url,
                    "revision_id": used_page["revision_id"],
                    "revision_timestamp": used_page["revision_timestamp"],
                    "license": "CC BY-SA 4.0",
                    "attribution": "Wikipedia contributors",
                    "infobox_template": chosen["template"],
                    "date_candidates": evidence["candidates"],
                    "context": chosen.get("context", {}),
                }
                SourceRecord.objects.update_or_create(
                    source=wikipedia,
                    external_key=f"{used_page['language']}wiki:{used_page['pageid'] or used_page['title']}"[:200],
                    defaults={
                        "matched_work": work,
                        "payload_hash": hashlib.sha256(
                            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest(),
                        "raw_payload": payload,
                        "retrieved_at": timezone.now(),
                    },
                )
                Work.objects.filter(pk=work.pk).update(
                    first_publication_year=chosen["year"],
                    first_publication_date_text=chosen["text"],
                    date_kind=chosen["kind"],
                    date_evidence=evidence,
                    updated_at=timezone.now(),
                )
            time.sleep(options["delay"])
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))

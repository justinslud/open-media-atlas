"""Recover production years from two open performing-arts sources.

- IDU (Arts and Theatre Institute, Czechia): P12930 play pages and the
  CC BY 4.0 ``inscenace`` open-data catalogue.
- SPAP / performing-arts.ch (SAPA Foundation, Switzerland): P8974 work URIs and
  the CC0 SPARQL endpoint.

Only the earliest documented production/season is used. The command never
guesses from a title and never writes unless ``--confirm`` is passed.
"""
import base64
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import Work

IDU_PAGE = "https://vis.idu.cz/Productions.aspx?playIds={play_id}&sourceIds={play_id}&tab=source"
IDU_DATASET = "https://opendata.idu.cz/data/inscenace.csv"
IDU_LICENSE = "CC BY 4.0"
SPAP_ENDPOINT = "https://qlever.performing-arts.ch"
SPAP_LICENSE = "CC0 1.0"
SPAP_QUERY = """\
PREFIX frbroo: <http://iflastandards.info/ns/fr/frbr/frbroo/>
PREFIX cidoc: <http://www.cidoc-crm.org/cidoc-crm/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?performance ?season ?begin ?label WHERE {{
  ?performance a frbroo:F31_Performance ;
    frbroo:R25_performed <{work_uri}> ;
    cidoc:P10_falls_within ?season .
  OPTIONAL {{ ?season cidoc:P4_has_time-span ?ts .
              ?ts cidoc:P82a_begin_of_the_begin ?begin . }}
  OPTIONAL {{ ?season rdfs:label ?label .
              FILTER(LANG(?label) = "en") }}
}} ORDER BY ?begin
"""
YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")
USER_AGENT = "OpenMediaAtlas/0.1 (local research; contact: local)"


def fetch(url, accept="text/html"):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def idu_productions(html):
    """Parse production rows embedded in the IDU ASP.NET view state."""
    match = re.search(r'id="__VIEWSTATE" value="([^"]+)"', html)
    if not match:
        return []
    raw = base64.b64decode(match.group(1)).decode("utf-8", "ignore")
    parts = re.split(r"ProductionDetail\.aspx\?id=(\d+)", raw)
    rows = []
    seen = set()
    for index in range(1, len(parts), 2):
        production_id = parts[index]
        before, after = parts[index - 1], parts[index + 1]
        years = YEAR.findall(after[:1200])
        if not years:
            continue
        year = min(int(value) for value in years)
        titles = re.findall(r"\x05[\x00-\x1f]([^\x00-\x1f]{2,200})", before[-500:])
        title = titles[-1].strip() if titles else ""
        key = (production_id, year)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "production_id": production_id,
            "title": title,
            "year": year,
            "url": f"https://vis.idu.cz/ProductionDetail.aspx?id={production_id}&mode=0",
        })
    return rows


def spap_performances(work_uri):
    query = SPAP_QUERY.format(work_uri=work_uri)
    url = f"{SPAP_ENDPOINT}?{urlencode({'query': query})}"
    payload = json.loads(fetch(url, "application/sparql-results+json"))
    rows = []
    for binding in payload.get("results", {}).get("bindings", []):
        begin = (binding.get("begin") or {}).get("value", "")
        label = (binding.get("label") or {}).get("value", "")
        found = YEAR.findall(begin) or YEAR.findall(label)
        if not found:
            continue
        rows.append({
            "performance": (binding.get("performance") or {}).get("value", ""),
            "season": (binding.get("season") or {}).get("value", ""),
            "begin": begin,
            "label": label,
            "year": int(found[0]),
        })
    return rows


class Command(BaseCommand):
    help = "Fill missing production years from IDU OpenData and SPAP (CC0)."

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=("all", "idu", "spap"), default="all")
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--ids", help="Comma-separated work IDs to limit the pass.")

    def handle(self, *args, **options):
        works = Work.objects.filter(is_demo=False, first_publication_year__isnull=True)
        if options["ids"]:
            ids = [int(item) for item in options["ids"].split(",") if item.strip().isdigit()]
            works = works.filter(pk__in=ids)
        works = list(
            works.select_related("work_type").prefetch_related("source_records__source")
        )
        report = {
            "confirm": options["confirm"],
            "source": options["source"],
            "updated": [],
            "unresolved": [],
            "errors": [],
        }
        candidates = []
        for work in works:
            record = next(
                (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                None,
            )
            payload = record.raw_payload if record and isinstance(record.raw_payload, dict) else {}
            claims = payload.get("claims", {})
            if options["source"] in {"all", "idu"} and claims.get("P12930"):
                play_id = claims["P12930"][0].get("mainsnak", {}).get("datavalue", {}).get("value")
                if play_id:
                    candidates.append(("idu", work, str(play_id)))
            if options["source"] in {"all", "spap"} and claims.get("P8974"):
                spap_id = claims["P8974"][0].get("mainsnak", {}).get("datavalue", {}).get("value")
                if spap_id:
                    candidates.append(("spap", work, str(spap_id)))
        if options["limit"]:
            candidates = candidates[: options["limit"]]

        for source, work, external_id in candidates:
            try:
                if source == "idu":
                    page_url = IDU_PAGE.format(play_id=external_id)
                    rows = idu_productions(fetch(page_url))
                    if not rows:
                        report["unresolved"].append({"work": work.pk, "title": work.title, "reason": "no IDU production rows"})
                        continue
                    earliest = min(rows, key=lambda row: (row["year"], row["production_id"]))
                    year, text = earliest["year"], str(earliest["year"])
                    evidence = {
                        "date_text": text,
                        "property": "P12930",
                        "source_url": page_url,
                        "source": "IDU Virtual Study of the Theatre Institute",
                        "dataset_url": IDU_DATASET,
                        "license": IDU_LICENSE,
                        "selection_rule": "earliest documented IDU production premiere; may be a local production",
                        "candidates": rows,
                    }
                else:
                    uuid = external_id[2:] if external_id.startswith("w/") else external_id
                    work_uri = f"http://data.performing-arts.ch/w/{uuid}"
                    rows = spap_performances(work_uri)
                    if not rows:
                        report["unresolved"].append({"work": work.pk, "title": work.title, "reason": "no SPAP performance rows"})
                        continue
                    earliest = min(rows, key=lambda row: (row["year"], row["begin"]))
                    year = earliest["year"]
                    text = f"{year}/{str(year + 1)[-2:]}" if earliest["begin"] else str(year)
                    evidence = {
                        "date_text": text,
                        "property": "P8974",
                        "source_url": f"https://www.performing-arts.ch/w/{uuid}",
                        "source": "Swiss Performing Arts Platform (SAPA Foundation)",
                        "dataset_url": SPAP_ENDPOINT,
                        "license": SPAP_LICENSE,
                        "selection_rule": "earliest documented SPAP season/performance; season start used",
                        "candidates": rows,
                    }
                report["updated"].append({
                    "work": work.pk,
                    "title": work.title,
                    "year": year,
                    "text": text,
                    "source": source,
                    "external_id": external_id,
                })
                if options["confirm"]:
                    Work.objects.filter(pk=work.pk).update(
                        first_publication_year=year,
                        first_publication_date_text=text,
                        date_kind="production",
                        date_evidence=evidence,
                        updated_at=timezone.now(),
                    )
                time.sleep(0.15)
            except Exception as exc:  # network/source failure must be explicit
                report["errors"].append({
                    "work": work.pk,
                    "title": work.title,
                    "source": source,
                    "error": f"{type(exc).__name__}: {exc}",
                })
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))

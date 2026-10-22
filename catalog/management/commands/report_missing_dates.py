"""Report remaining undated works with their public/proprietary source links.

The report is a review aid. It does not fetch dates from restricted sites and
it never edits works.
"""
import csv
import json
import sys
from urllib.parse import quote

from django.core.management.base import BaseCommand
from django.db.models import Q

from catalog.models import ImportRelationshipProposal, Work

SOURCE_LINKS = {
    "P345": ("IMDb", "https://www.imdb.com/title/{value}/"),
    "P4947": ("TMDB movie", "https://www.themoviedb.org/movie/{value}"),
    "P4983": ("TMDB TV", "https://www.themoviedb.org/tv/{value}"),
    "P2529": ("ČSFD", "https://www.csfd.cz/film/{value}/"),
    "P2603": ("Kinopoisk", "https://www.kinopoisk.ru/film/{value}/"),
    "P1219": ("Internet Broadway Database", "https://www.ibdb.com/broadway-show/{value}"),
    "P8974": ("SPAP", "https://www.performing-arts.ch/w/{value}"),
    "P12930": ("IDU", "https://vis.idu.cz/Productions.aspx?playIds={value}&sourceIds={value}&tab=source"),
    "P4282": ("LUMIERE", "https://lumiere.obs.coe.int/web/film_info/?id={value}"),
    "P6127": ("Letterboxd", "https://letterboxd.com/film/{value}/"),
    "P8013": ("Trakt", "https://trakt.tv/movies/{value}"),
    "P12196": ("TheTVDB movie", "https://thetvdb.com/movies/{value}"),
    "P4835": ("TheTVDB series", "https://thetvdb.com/series/{value}"),
    "P4529": ("Douban", "https://movie.douban.com/subject/{value}/"),
    "P2704": ("EIDR", "https://ui.eidr.org/view/content?id={value}"),
    "P8383": ("Goodreads", "https://www.goodreads.com/work/{value}"),
}
PERMISSIVE = {"Wikidata", "IDU", "SPAP", "Wikipedia"}
RESTRICTED = {
    "IMDb", "TMDB movie", "TMDB TV", "ČSFD", "Kinopoisk",
    "Internet Broadway Database", "LUMIERE", "Letterboxd", "Trakt",
    "TheTVDB movie", "TheTVDB series", "Douban", "EIDR", "Goodreads",
}


def wiki_url(payload):
    sitelinks = payload.get("sitelinks") or {}
    for key in ("enwiki", "dewiki", "cswiki", "frwiki", "itwiki", "eswiki", "ruwiki", "plwiki"):
        if key in sitelinks:
            lang = key[:-4]
            value = sitelinks[key]
            title = value.get("title", "") if isinstance(value, dict) else str(value)
            if title:
                return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
    for key, value in sitelinks.items():
        if key.endswith("wiki") and key not in {"commonswiki", "specieswiki", "metawiki"}:
            lang = key[:-4]
            title = value.get("title", "") if isinstance(value, dict) else str(value)
            if title:
                return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
    return ""


def external_sources(payload):
    found = []
    for prop, claims in (payload.get("claims") or {}).items():
        if prop not in SOURCE_LINKS:
            continue
        name, template = SOURCE_LINKS[prop]
        for claim in claims:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not value:
                continue
            if prop == "P8974" and value.startswith("w/"):
                value = value[2:]
            url = template.format(value=value)
            status = "permissive" if name in PERMISSIVE else "restricted"
            found.append({"name": name, "property": prop, "value": value, "url": url, "status": status})
    return found


class Command(BaseCommand):
    help = "Report undated works with Wikidata, Wikipedia, and external-source links."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("pending", "public", "all"), default="pending")
        parser.add_argument("--format", choices=("csv", "json"), default="csv")
        parser.add_argument("--output", default="")

    def handle(self, *args, **options):
        works = Work.objects.filter(is_demo=False, first_publication_year__isnull=True)
        targets = {}
        if options["scope"] == "pending":
            pending = ImportRelationshipProposal.objects.filter(status="pending").select_related(
                "from_work", "to_work"
            )
            for proposal in pending:
                if proposal.from_work.first_publication_year:
                    continue
                targets.setdefault(proposal.from_work_id, set()).add(proposal.to_work.title)
            works = works.filter(pk__in=targets)
        elif options["scope"] == "public":
            works = works.filter(visibility=Work.Visibility.PUBLIC)

        rows = []
        for work in works.select_related("work_type").prefetch_related("source_records__source"):
            record = next(
                (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                None,
            )
            payload = record.raw_payload if record and isinstance(record.raw_payload, dict) else {}
            qid = payload.get("id") or (record.external_key if record else "")
            sources = external_sources(payload)
            wikipedia = wiki_url(payload)
            permissive = {item["name"] for item in sources if item["status"] == "permissive"}
            if wikipedia:
                permissive.add("Wikipedia")
            if not permissive:
                permissive.add("Wikidata")
            date_props = sorted(
                prop for prop, claims in (payload.get("claims") or {}).items()
                if prop in {"P577", "P1191", "P1619", "P580", "P582", "P585", "P571", "P2754", "P10135"}
                and claims
            )
            rows.append({
                "work_id": work.pk,
                "title": work.title,
                "type": work.work_type.label,
                "qid": qid,
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
                "wikipedia_url": wikipedia,
                "pending_targets": " | ".join(sorted(targets.get(work.pk, []))),
                "date_properties_present": ",".join(date_props),
                "external_ids": " | ".join(
                    f"{item['name']} ({item['property']}={item['value']}, {item['status']}): {item['url']}"
                    for item in sources
                ),
                "permissive_sources": ", ".join(sorted(permissive)),
                "restricted_sources": ", ".join(sorted({item["name"] for item in sources if item["status"] == "restricted"})),
            })
        rows.sort(key=lambda row: (row["title"].lower(), row["work_id"]))
        if options["format"] == "json":
            output = json.dumps(rows, indent=2, ensure_ascii=False)
        else:
            buffer = []
            writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()) if rows else [
                "work_id", "title", "type", "qid", "wikidata_url", "wikipedia_url",
                "pending_targets", "date_properties_present", "external_ids",
                "permissive_sources", "restricted_sources",
            ])
            writer.writeheader()
            writer.writerows(rows)
            output = ""
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as handle:
                if options["format"] == "json":
                    handle.write(output)
                else:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [
                        "work_id", "title", "type", "qid", "wikidata_url", "wikipedia_url",
                        "pending_targets", "date_properties_present", "external_ids",
                        "permissive_sources", "restricted_sources",
                    ])
                    writer.writeheader()
                    writer.writerows(rows)
        else:
            self.stdout.write(output)

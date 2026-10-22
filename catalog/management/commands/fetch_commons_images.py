"""Fetch licensed Wikimedia Commons images from stored Wikidata P18 claims."""
import html
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

from catalog.models import SourceRecord, Work

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "OpenMediaAtlas/1.0 (bounded golden-set and public-work image metadata)"


def plain_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(value).split())


class Command(BaseCommand):
    help = "Fetch remote Commons thumbnails and license metadata for golden, adaptation, or public works."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("golden", "public-adaptations", "public"), default="golden")
        parser.add_argument("--ids", help="Comma-separated work IDs, bypassing --scope.")
        parser.add_argument("--manifest", default="data/wikidata-golden-20.json")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--width", type=int, default=480)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--overwrite", action="store_true")

    def get_json(self, params):
        request = Request(
            f"{API}?{urlencode(params)}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except (URLError, TimeoutError, json.JSONDecodeError):
                if attempt == 2:
                    raise
            time.sleep(1.5 * (attempt + 1))

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 100:
            raise CommandError("--limit must be 1..100")
        if not 100 <= options["width"] <= 1200:
            raise CommandError("--width must be 100..1200")
        targets = []
        if options["ids"]:
            ids = [int(item) for item in options["ids"].split(",") if item.strip().isdigit()]
            works = (
                Work.objects.filter(pk__in=ids, is_demo=False)
                .select_related("work_type")
                .prefetch_related("source_records__source")
                .order_by("title", "pk")
            )
            for work in works[: options["limit"]]:
                record = next(
                    (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                    None,
                )
                targets.append((record.external_key if record else "", work, record))
        elif options["scope"] == "golden":
            try:
                manifest = json.loads(Path(options["manifest"]).read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"invalid manifest: {exc}") from exc
            for seed in manifest.get("seeds", [])[: options["limit"]]:
                work = (
                    Work.objects.filter(
                        identifiers__scheme="wikidata", identifiers__value=seed["qid"]
                    )
                    .distinct()
                    .first()
                )
                record = SourceRecord.objects.filter(
                    source__title="Wikidata", external_key=seed["qid"]
                ).first()
                targets.append((seed["qid"], work, record))
        else:
            works = (
                Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False)
                .select_related("work_type")
                .prefetch_related("source_records__source")
                .order_by("title", "pk")
            )
            if options["scope"] == "public-adaptations":
                works = works.filter(depth="index")
            for work in works[: options["limit"]]:
                record = next(
                    (item for item in work.source_records.all() if item.source.title == "Wikidata"),
                    None,
                )
                targets.append((record.external_key if record else "", work, record))
        updated, missing, skipped = [], [], []
        for qid, work, record in targets:
            if not qid or not work or not record:
                missing.append({"qid": qid, "reason": "work or source record missing"})
                continue
            if work.image_url and not options["overwrite"]:
                skipped.append({"qid": qid, "work": work.pk, "reason": "image already set"})
                continue
            payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
            filenames = []
            for claim in payload.get("claims", {}).get("P18", []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, str) and value.strip():
                    filenames.append(value.strip())
            if not filenames:
                missing.append({"qid": qid, "work": work.pk, "reason": "no P18"})
                continue
            title = f"File:{filenames[0]}"
            try:
                data = self.get_json(
                    {
                        "action": "query",
                        "format": "json",
                        "formatversion": "2",
                        "prop": "imageinfo",
                        "iiprop": "url|extmetadata",
                        "iiurlwidth": str(options["width"]),
                        "titles": title,
                    }
                )
                page = next(iter(data.get("query", {}).get("pages", [])), {})
                info = (page.get("imageinfo") or [{}])[0]
                image_url = (info.get("thumburl") or info.get("url") or "").split("?", 1)[0]
                source_url = info.get("descriptionurl")
                metadata = info.get("extmetadata", {})
                artist = plain_text(metadata.get("Artist", {}).get("value"))
                license_name = plain_text(metadata.get("LicenseShortName", {}).get("value"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
                missing.append({"qid": qid, "work": work.pk, "reason": str(exc)})
                continue
            if not image_url or not source_url:
                missing.append({"qid": qid, "work": work.pk, "reason": "Commons returned no image URL"})
                continue
            if not options["dry_run"]:
                work.image_url = image_url
                work.image_source_url = source_url
                work.image_attribution = artist[:300] or "Wikimedia Commons contributor"
                work.image_license = (license_name or "Unknown")[:120]
                work.save(
                    update_fields=(
                        "image_url",
                        "image_source_url",
                        "image_attribution",
                        "image_license",
                        "updated_at",
                    )
                )
            updated.append(
                {
                    "qid": qid,
                    "work": work.pk,
                    "title": work.title,
                    "file": filenames[0],
                    "license": license_name,
                    "artist": artist,
                }
            )
            time.sleep(0.25)
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "updated": updated,
                        "missing": missing,
                        "skipped": skipped,
                        "scope": options["scope"],
                        "dry_run": options["dry_run"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        )

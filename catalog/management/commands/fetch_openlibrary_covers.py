"""Fetch bounded, attributed Open Library cover URLs for selected works.

This stores a remote cover URL and its source page, not an image file. Covers on
Open Library do not carry a uniform reuse license, so the default is an
explicit "unknown; link only" note. The public page must show that limitation.
"""
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

from catalog.models import ExternalIdentifier, Work

USER_AGENT = "OpenMediaAtlas/1.0 (bounded golden-set cover lookup)"


def first_cover(payload):
    covers = payload.get("covers") or []
    return next((value for value in covers if isinstance(value, int) and value > 0), None)


class Command(BaseCommand):
    help = "Fetch remote Open Library cover URLs for a bounded seed manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="data/wikidata-golden-20.json")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--overwrite", action="store_true")

    def get_json(self, url):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
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
        try:
            manifest = json.loads(Path(options["manifest"]).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid manifest: {exc}") from exc
        seeds = manifest.get("seeds", [])[: options["limit"]]
        updated, missing, skipped = [], [], []
        for seed in seeds:
            work = (
                Work.objects.filter(
                    identifiers__scheme="wikidata", identifiers__value=seed["qid"]
                )
                .distinct()
                .first()
            )
            if not work:
                missing.append({"qid": seed["qid"], "reason": "work not in catalog"})
                continue
            if work.image_url and not options["overwrite"]:
                skipped.append({"qid": seed["qid"], "work": work.pk, "reason": "image already set"})
                continue
            olids = list(
                ExternalIdentifier.objects.filter(
                    work=work, scheme="ol_work", value__startswith="OL", value__endswith="W"
                ).values_list("value", flat=True)
            )
            cover_id = None
            source_id = None
            for olid in olids:
                try:
                    payload = self.get_json(f"https://openlibrary.org/works/{olid}.json")
                    cover_id = first_cover(payload)
                    source_id = olid
                    if cover_id:
                        break
                    editions = self.get_json(
                        f"https://openlibrary.org/works/{olid}/editions.json?limit=50"
                    )
                    for edition in editions.get("entries", []):
                        cover_id = first_cover(edition)
                        if cover_id:
                            break
                    if cover_id:
                        break
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    self.stderr.write(f"{seed['qid']} {olid}: {exc}")
            if not cover_id:
                missing.append({"qid": seed["qid"], "work": work.pk, "reason": "no Open Library cover"})
                continue
            image_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
            source_url = f"https://openlibrary.org/works/{source_id}"
            if not options["dry_run"]:
                work.image_url = image_url
                work.image_source_url = source_url
                work.image_attribution = f"Cover via Open Library ({source_id})"
                work.image_license = "Unknown; remote cover, source link only"
                work.save(update_fields=("image_url", "image_source_url", "image_attribution", "image_license", "updated_at"))
            updated.append({"qid": seed["qid"], "work": work.pk, "title": work.title, "cover_id": cover_id})
            time.sleep(0.3)
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "updated": updated,
                        "missing": missing,
                        "skipped": skipped,
                        "dry_run": options["dry_run"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        )

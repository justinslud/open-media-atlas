"""Add exact-ID reading links for public-domain books from cached Wikidata claims."""
import json

from django.core.management.base import BaseCommand

from catalog.models import AccessLink, Work


class Command(BaseCommand):
    help = "Create Gutenberg and Open Library links for golden books using exact IDs."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=("golden", "public"), default="golden")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        works = Work.objects.filter(is_demo=False, work_type__medium__in=("text", "stage"))
        if options["scope"] == "golden":
            works = works.filter(depth="editorial", visibility=Work.Visibility.PUBLIC)
        else:
            works = works.filter(visibility=Work.Visibility.PUBLIC)
        report = {"gutenberg_created": [], "openlibrary_created": [], "skipped": [], "confirm": options["confirm"]}
        for work in works.prefetch_related("source_records", "identifiers", "access_links"):
            record = work.source_records.filter(source__title="Wikidata").first()
            payload = record.raw_payload if record and isinstance(record.raw_payload, dict) else {}
            qid = payload.get("id", "")
            source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""
            gutenberg_ids = []
            for claim in payload.get("claims", {}).get("P2034", []):
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if value:
                    gutenberg_ids.append(str(value))
            for gid in dict.fromkeys(gutenberg_ids):
                url = f"https://www.gutenberg.org/ebooks/{gid}"
                if work.access_links.filter(provider="Project Gutenberg", url=url).exists():
                    report["skipped"].append({"work": work.pk, "provider": "Project Gutenberg", "id": gid})
                    continue
                report["gutenberg_created"].append({"work": work.pk, "title": work.title, "id": gid})
                if options["confirm"]:
                    AccessLink.objects.create(
                        work=work,
                        provider="Project Gutenberg",
                        url=url,
                        category=AccessLink.Category.FULL,
                        scope_note="Project Gutenberg ebook; verify the edition and local copyright.",
                        restrictions="US public domain; local law may differ.",
                        source_url=source_url,
                        active=True,
                    )
                break
            olids = list(work.identifiers.filter(scheme="ol_work", value__startswith="OL", value__endswith="W").values_list("value", flat=True))
            if olids:
                url = f"https://openlibrary.org/works/{olids[0]}"
                if work.access_links.filter(provider="Open Library", url=url).exists():
                    report["skipped"].append({"work": work.pk, "provider": "Open Library", "id": olids[0]})
                else:
                    report["openlibrary_created"].append({"work": work.pk, "title": work.title, "id": olids[0]})
                    if options["confirm"]:
                        AccessLink.objects.create(
                            work=work,
                            provider="Open Library",
                            url=url,
                            category=AccessLink.Category.CATALOG,
                            scope_note="Open Library catalog record; availability and lending status not verified.",
                            source_url=source_url,
                            active=True,
                        )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))

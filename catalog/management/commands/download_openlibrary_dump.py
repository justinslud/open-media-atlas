from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from catalog.importers.openlibrary_bulk import BulkImportError, download
class Command(BaseCommand):
    help="Stream one pinned dump to local storage and reject truncation/checksum mismatch."
    def add_arguments(self,p):
        p.add_argument("url"); p.add_argument("destination",type=Path); p.add_argument("--sha256")
    def handle(self,*args,**o):
        try: result=download(o["url"],o["destination"],o["sha256"])
        except BulkImportError as exc: raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"bytes={result['bytes']} sha256={result['sha256']}"))

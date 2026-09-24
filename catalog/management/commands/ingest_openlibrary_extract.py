import json, resource, time
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from catalog.importers.openlibrary_bulk import IMPORTER_VERSION, BulkImportError, db_size, ingest_record, validate_extract
from catalog.models import ImportItem, ImportRun, Source

class Command(BaseCommand):
    help="Validate or ingest an Open Library extract as draft catalog records."
    def add_arguments(self,p):
        p.add_argument("extract",type=Path); p.add_argument("--dry-run",action="store_true"); p.add_argument("--resume-run",type=int); p.add_argument("--batch-size",type=int,default=50); p.add_argument("--max-runtime",type=int,default=14400); p.add_argument("--report",type=Path)
    def handle(self,*args,**o):
        if not 1<=o["batch_size"]<=500: raise CommandError("--batch-size must be between 1 and 500")
        try: manifest,records=validate_extract(o["extract"])
        except (BulkImportError,OSError,ValueError,json.JSONDecodeError) as exc: raise CommandError(str(exc)) from exc
        if o["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"valid extract records={manifest['artifact']['records']} sha256={manifest['artifact']['sha256']}")); return
        source,_=Source.objects.get_or_create(title="Open Library",defaults={"kind":"dataset","url":"https://openlibrary.org/developers/dumps","notes":"Open Library bulk dump metadata; no rights conclusion."})
        if o["resume_run"]:
            try: run=ImportRun.objects.get(pk=o["resume_run"],source=source)
            except ImportRun.DoesNotExist as exc: raise CommandError("Resume run not found for Open Library") from exc
            if run.manifest.get("artifact",{}).get("sha256")!=manifest["artifact"]["sha256"]: raise CommandError("Resume extract does not match the run manifest")
        else: run=ImportRun.objects.create(source=source,manifest=manifest,importer_version=IMPORTER_VERSION,requested_keys=[])
        done=set(run.items.exclude(status="failed").values_list("external_key",flat=True)); stats={k:0 for k in ("created","updated","unchanged","skipped","conflicted","failed")}; before=db_size(); started=time.monotonic(); stopped=False
        with records.open() as stream:
            for number,line in enumerate(stream,1):
                row=json.loads(line); key=str(row["work"]["key"]).removeprefix("/works/")
                if key in done: stats["skipped"]+=1; continue
                if o["max_runtime"] and time.monotonic()-started>=o["max_runtime"]: stopped=True; break
                try:
                    with transaction.atomic(): status,work,message=ingest_record(row,source)
                except Exception as exc: status="failed"; work=None; message=str(exc)[:1000]
                ImportItem.objects.update_or_create(run=run,external_key=key,defaults={"status":status,"work":work,"message":message}); stats[status]+=1
                if number%o["batch_size"]==0: self.stdout.write(f"processed={number} stats={stats}")
        run.stats={**run.stats,"phase":"ingestion_stopped" if stopped else "complete","snapshot_date":manifest.get("snapshot_date"),**stats,"ingest_elapsed_seconds":round(time.monotonic()-started,3),"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"database_bytes_before":before,"database_bytes_after":db_size(),"gracefully_stopped":stopped,"extract":str(o["extract"])}
        run.status=ImportRun.Status.RUNNING if stopped else (ImportRun.Status.COMPLETED_WITH_ERRORS if stats["failed"] else ImportRun.Status.COMPLETED); run.finished_at=None if stopped else timezone.now(); run.save(update_fields=("stats","status","finished_at"))
        report=o["report"] or o["extract"]/f"ingest-run-{run.pk}.json"; report.write_text(json.dumps({"run_id":run.pk,**run.stats},indent=2,sort_keys=True)+"\n")
        self.stdout.write(self.style.WARNING(f"run={run.pk} stopped; resume with --resume-run {run.pk}") if stopped else self.style.SUCCESS(f"run={run.pk} stats={stats}"))

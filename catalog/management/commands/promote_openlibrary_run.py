from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import ImportRun, Work
class Command(BaseCommand):
    help="Explicitly publish draft works created by a reviewed import run."
    def add_arguments(self,p):
        p.add_argument("run_id",type=int)
        p.add_argument("--confirm",action="store_true")
        p.add_argument("--allow-errors",action="store_true",help="Publish successful items from a completed-with-errors run after reviewing every failure")
        p.add_argument("--limit",type=int,default=5000)
    def handle(self,*args,**o):
        try: run=ImportRun.objects.get(pk=o["run_id"])
        except ImportRun.DoesNotExist as exc: raise CommandError("Import run not found") from exc
        failed=run.items.filter(status="failed").count()
        ids=list(run.items.filter(status="created",work__visibility=Work.Visibility.DRAFT).values_list("work_id",flat=True)[:o["limit"]])
        if not o["confirm"]:
            suffix=f"; {failed} failed items require --allow-errors with --confirm" if failed else ""
            self.stdout.write(f"would promote {len(ids)} draft works from run {run.pk}{suffix}; inspect admin then add --confirm")
            return
        allowed=(run.status==ImportRun.Status.COMPLETED or
                 (run.status==ImportRun.Status.COMPLETED_WITH_ERRORS and o["allow_errors"]))
        if not allowed:
            raise CommandError("Run must be completed; for a reviewed completed-with-errors run, add --allow-errors")
        with transaction.atomic(): changed=Work.objects.filter(pk__in=ids,visibility=Work.Visibility.DRAFT).update(visibility=Work.Visibility.PUBLIC)
        self.stdout.write(self.style.SUCCESS(f"promoted={changed} run={run.pk} failed_items_acknowledged={failed if o['allow_errors'] else 0}"))

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from catalog.models import ImportRun, Work
class Command(BaseCommand):
    help="Explicitly publish draft works created by a reviewed completed import run."
    def add_arguments(self,p): p.add_argument("run_id",type=int); p.add_argument("--confirm",action="store_true"); p.add_argument("--limit",type=int,default=5000)
    def handle(self,*args,**o):
        try: run=ImportRun.objects.get(pk=o["run_id"])
        except ImportRun.DoesNotExist as exc: raise CommandError("Import run not found") from exc
        ids=list(run.items.filter(status="created",work__visibility=Work.Visibility.DRAFT).values_list("work_id",flat=True)[:o["limit"]])
        if not o["confirm"]: self.stdout.write(f"would promote {len(ids)} draft works from run {run.pk}; inspect admin then add --confirm"); return
        if run.status!=ImportRun.Status.COMPLETED: raise CommandError("Only a completed, error-free run can be promoted")
        with transaction.atomic(): changed=Work.objects.filter(pk__in=ids,visibility=Work.Visibility.DRAFT).update(visibility=Work.Visibility.PUBLIC)
        self.stdout.write(self.style.SUCCESS(f"promoted={changed} run={run.pk}"))

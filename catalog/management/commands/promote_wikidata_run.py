from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from catalog.models import ImportRelationshipProposal, ImportRun, Work

class Command(BaseCommand):
    help="Publish reviewed Wikidata draft endpoints and approve selected relationship proposals."
    def add_arguments(self,p):
        p.add_argument("run_id",type=int); p.add_argument("--reviewer",required=True)
        p.add_argument("--statement",action="append",default=[],help="Approved statement ID; repeat for each assertion")
        p.add_argument("--publish-endpoints",action="store_true"); p.add_argument("--confirm",action="store_true")
    def handle(self,*args,**o):
        try: run=ImportRun.objects.get(pk=o["run_id"]); reviewer=get_user_model().objects.get(username=o["reviewer"])
        except (ImportRun.DoesNotExist,get_user_model().DoesNotExist) as exc: raise CommandError("run or reviewer not found") from exc
        proposals=run.relationship_proposals.filter(status="pending",statement_id__in=o["statement"])
        missing=set(o["statement"])-set(proposals.values_list("statement_id",flat=True))
        if missing: raise CommandError(f"not pending in this run: {', '.join(sorted(missing))}")
        work_ids=set(proposals.values_list("from_work_id",flat=True))|set(proposals.values_list("to_work_id",flat=True))
        self.stdout.write(f"would approve {proposals.count()} relationship(s) and publish {len(work_ids) if o['publish_endpoints'] else 0} endpoint(s)")
        if not o["confirm"]: return
        with transaction.atomic():
            if o["publish_endpoints"]: Work.objects.filter(pk__in=work_ids,visibility=Work.Visibility.DRAFT).update(visibility=Work.Visibility.PUBLIC)
            for proposal in proposals.select_related("from_work","to_work","relationship_type","source"): proposal.approve(reviewer)
        self.stdout.write(self.style.SUCCESS("approved explicitly selected Wikidata assertions"))

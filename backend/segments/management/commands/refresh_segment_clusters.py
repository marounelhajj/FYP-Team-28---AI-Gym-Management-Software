from django.core.management.base import BaseCommand

from segments.clustering import refresh_due, run_clustering
from segments.models import ClusterRun


class Command(BaseCommand):
    help = "Recalculate the suggested member segments (behavioural clusters). Weekly by default."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if this week's run already exists.")

    def handle(self, *args, **options):
        run = run_clustering(trigger=ClusterRun.Trigger.MANUAL) if options["force"] else refresh_due()
        if run is None:
            self.stdout.write("Suggested segments are already up to date this week.")
            return
        self.stdout.write(
            f"{run.members_clustered} members, k={run.k}, silhouette={run.silhouette} ({run.model_version})"
        )
        for g in run.groups.all():
            self.stdout.write(f"  {g.size:>4}  {g.name}")

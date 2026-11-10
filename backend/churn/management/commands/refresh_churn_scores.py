from datetime import date

from django.core.management.base import BaseCommand, CommandError

from members.models import Member

from churn.models import ChurnRun
from churn.scoring import refresh_branch

# Re-scores members and saves this week's at-risk list (SCRUM-118).
#
#   python manage.py refresh_churn_scores                 every branch
#   python manage.py refresh_churn_scores --branch Hamra  one branch
#   python manage.py refresh_churn_scores --as-of 2026-10-05   a past week
#
# For a cron / Task Scheduler setup instead of the built-in weekly thread
# (CHURN_AUTORUN=false), e.g. every Monday at 03:00:
#
#   0 3 * * 1  cd /path/to/backend && .venv/bin/python manage.py refresh_churn_scores


class Command(BaseCommand):
    help = "Scores members' churn risk and saves the week's at-risk list per branch."

    def add_arguments(self, parser):
        parser.add_argument("--branch", choices=Member.Branch.values)
        parser.add_argument("--as-of", help="Score as of this date (YYYY-MM-DD) instead of today.")

    def handle(self, *args, **options):
        as_of = None
        if options["as_of"]:
            try:
                as_of = date.fromisoformat(options["as_of"])
            except ValueError as exc:
                raise CommandError("--as-of must be YYYY-MM-DD") from exc
        branches = [options["branch"]] if options["branch"] else Member.Branch.values
        for branch in branches:
            run = refresh_branch(branch, as_of=as_of, trigger=ChurnRun.Trigger.COMMAND)
            model = f", model {run.model.version}" if run.model else ""
            self.stdout.write(f"{branch}: {run.members_scored} members scored ({run.method}{model}) for week of {run.week_start}")

import logging
import threading
import time

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.db import close_old_connections
from django.utils import timezone

from members.models import Member

from . import config
from .features import week_start
from .models import ChurnRun

logger = logging.getLogger(__name__)

# The weekly refresh of the at-risk list (SCRUM-118: "The list is
# refreshed weekly").
#
# Same no-extra-service approach as the reminders (notifications/scheduler.py):
# a background thread in the web server checks every
# SCHEDULER_INTERVAL_SECONDS whether each branch has a list for the current
# week (weeks start on Monday) and makes the missing ones. The first check
# after Monday 00:00 therefore makes the new week's lists.
#
# Set CHURN_AUTORUN=false to switch the thread off and run the management
# command from the server's own scheduler instead, e.g. every Monday 03:00:
#
#   0 3 * * 1  cd /path/to/backend && .venv/bin/python manage.py refresh_churn_scores
#
# Opening the list before the weekly run has happened makes that week's
# list on the spot too (scoring.ensure_current), so it is never missing.


def refresh_due(today=None):
    from .scoring import refresh_branch

    today = today or timezone.localdate()
    monday = week_start(today)
    done = []
    for branch in Member.Branch.values:
        if not ChurnRun.objects.filter(branch=branch, week_start=monday).exists():
            refresh_branch(branch, trigger=ChurnRun.Trigger.SCHEDULED)
            done.append(branch)
    return done


_started = False
_lock = threading.Lock()


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run_forever, name="churn-weekly", daemon=True).start()


def _run_forever():
    while True:
        try:
            refreshed = refresh_due()
            if refreshed:
                logger.info("At-risk lists refreshed for %s", ", ".join(refreshed))
        except Exception:
            logger.exception("At-risk refresh failed; trying again next time")
        finally:
            close_old_connections()
        time.sleep(config.SCHEDULER_INTERVAL_SECONDS)


class ChurnSchedulerMiddleware:
    def __init__(self, get_response):
        if settings.CHURN_AUTORUN:
            start()
        raise MiddlewareNotUsed

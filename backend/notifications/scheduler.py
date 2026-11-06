import logging
import threading
import time

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.db import close_old_connections

logger = logging.getLogger(__name__)

# Sends reminders on time without any extra service to install (no Celery,
# Redis or cron): one background thread in the web server process wakes up
# every REMINDER_INTERVAL_SECONDS and runs reminders.send_due().
#
# It's started by the middleware below, which Django builds once per server
# process when it starts serving - so it runs under "manage.py runserver"
# (only in the process that serves requests, not the auto-reloader watching
# the files) and under a production server alike, but never during migrate,
# tests or other commands. It then removes itself (MiddlewareNotUsed), so it
# costs requests nothing.
#
# send_due() is safe to run from several places at once, so a server with
# more than one worker process is fine. Set REMINDERS_AUTORUN=false to switch
# the thread off and run "python manage.py send_reminders" from the server's
# own scheduler (cron, Windows Task Scheduler) instead.

_started = False
_lock = threading.Lock()


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run_forever, name="reminders", daemon=True).start()
    logger.info("Reminders: checking every %s seconds", settings.REMINDER_INTERVAL_SECONDS)


def _run_forever():
    from .reminders import send_due

    while True:
        try:
            send_due()
        except Exception:
            logger.exception("Reminders: a run failed; trying again next time")
        finally:
            close_old_connections()
        time.sleep(settings.REMINDER_INTERVAL_SECONDS)


class ReminderSchedulerMiddleware:
    def __init__(self, get_response):
        if settings.REMINDERS_AUTORUN:
            start()
        raise MiddlewareNotUsed

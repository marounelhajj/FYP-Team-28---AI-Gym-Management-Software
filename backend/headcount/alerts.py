import logging

from django.utils import timezone

from administration.models import StaffAccount
from notifications.models import StaffNotification

from .models import BranchCapacity

logger = logging.getLogger(__name__)

# The branch capacity alert (SCRUM-128), as a small state machine stored on
# BranchCapacity:
#
#   quiet  --(headcount >= threshold)-->  alert  (notify the branch's staff, once)
#   alert  --(headcount < clear_below)--> quiet
#
# clear_below sits a few people under the threshold, so one person walking
# in and out at the line doesn't raise a new alert every time. Each switch
# is a conditional UPDATE, so two check-ins landing together raise it once.
#
# There's no cron here (same as close_stale_sessions), so it is re-checked
# whenever headcount changes - a check-in or check-out at the desk or a door -
# and whenever the Live Headcount dashboard polls.


def notify_branch_staff(branch, kind, title, message, now):
    recipients = StaffAccount.objects.filter(branch=branch, is_active=True)
    StaffNotification.objects.bulk_create(
        StaffNotification(recipient=r, kind=kind, branch=branch, title=title, message=message, created_at=now)
        for r in recipients
    )


def check_capacity(branch, count=None, now=None):
    from .views import current_headcount

    setting = BranchCapacity.objects.filter(branch=branch).first()
    if setting is None:
        return None
    now = now or timezone.now()
    if count is None:
        count = current_headcount(branch, now)

    if not setting.alert_active and count >= setting.threshold:
        raised = BranchCapacity.objects.filter(pk=setting.pk, alert_active=False).update(
            alert_active=True, alert_raised_at=now, alert_count=count,
        )
        if raised:
            notify_branch_staff(
                branch, StaffNotification.Kind.CAPACITY_ALERT, f"{branch} is near capacity",
                f"{count} people inside, alert level {setting.threshold} of {setting.max_capacity}. "
                "Consider pausing walk-ins or opening more floor space.",
                now,
            )
    elif setting.alert_active and count < setting.clear_below:
        BranchCapacity.objects.filter(pk=setting.pk, alert_active=True).update(alert_active=False, alert_cleared_at=now)

    setting.refresh_from_db()
    return setting


# Never let the alert break the check-in it follows.
def check_capacity_safely(branch):
    try:
        check_capacity(branch)
    except Exception:
        logger.exception("Couldn't check the capacity alert for %s", branch)

from datetime import timedelta

from django.db import models
from django.db.models import DateTimeField, ExpressionWrapper, F, Value
from django.utils import timezone

from members.models import Member

# A member who never checks out is checked out automatically this long after
# they checked in (SCRUM-127), so live headcount doesn't grow forever and
# they aren't refused as "Already checked in" on their next visit.
AUTO_CHECKOUT_AFTER = timedelta(hours=4)


class CheckIn(models.Model):
    class Result(models.TextChoices):
        ALLOWED = "Allowed", "Allowed"
        DENIED = "Denied", "Denied"

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="check_ins")
    result = models.CharField(max_length=10, choices=Result.choices)
    # The reason entry was refused (e.g. "Frozen", "Cancelled", "Already
    # checked in") - blank when result is Allowed.
    reason = models.CharField(max_length=30, blank=True)
    checked_in_at = models.DateTimeField(auto_now_add=True)
    # Null while the member is still inside - that's what makes a row an
    # "open session". Only ever set on an Allowed row, by checking out.
    checked_out_at = models.DateTimeField(null=True, blank=True)
    # True when close_stale_sessions() closed it, not the front desk.
    auto_checked_out = models.BooleanField(default=False)
    # The branch they entered (SCRUM-127): the receptionist's branch when
    # their account has one, otherwise the member's home branch.
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, blank=True)
    # The door reader that scanned the card; null when done at the front desk.
    door = models.ForeignKey("doors.Door", on_delete=models.SET_NULL, null=True, blank=True, related_name="check_ins")

    class Meta:
        ordering = ["-checked_in_at"]
        indexes = [models.Index(fields=["branch", "checked_in_at"], name="checkin_branch_time_idx")]

    def __str__(self):
        return f"{self.member.name} - {self.result} @ {self.checked_in_at}"


# The member's current visit (let in, not out yet), or None if they aren't inside.
def open_session(member):
    return CheckIn.objects.filter(
        member=member, result=CheckIn.Result.ALLOWED, checked_out_at__isnull=True,
    ).order_by("-checked_in_at").first()


# Closes every open session older than AUTO_CHECKOUT_AFTER, as if the member
# had checked out exactly that long after checking in. Runs lazily (there's
# no Celery/cron in this project) wherever an accurate "who is inside" is
# needed: checking in or out, and reading the headcount. One bulk UPDATE.
def close_stale_sessions(now=None):
    now = now or timezone.now()
    return CheckIn.objects.filter(
        result=CheckIn.Result.ALLOWED, checked_out_at__isnull=True, checked_in_at__lte=now - AUTO_CHECKOUT_AFTER,
    ).update(
        checked_out_at=ExpressionWrapper(F("checked_in_at") + Value(AUTO_CHECKOUT_AFTER), output_field=DateTimeField()),
        auto_checked_out=True,
    )


# User story: "As a receptionist, I want to flag a suspicious or duplicate
# check in attempt, so that I can prevent membership sharing or fraudulent
# access."
#
# At most one flag per attempt. While a member has an Open or Confirmed flag,
# the front desk is warned to check photo ID every time they check in; a
# Dismissed flag (false alarm) no longer warns.
class CheckInFlag(models.Model):
    class Reason(models.TextChoices):
        DUPLICATE = "Duplicate check-in", "Duplicate check-in"
        SHARING = "Membership sharing", "Membership sharing"
        CARD_MISUSE = "Card misuse", "Card misuse"
        OTHER = "Other", "Other"

    class Status(models.TextChoices):
        OPEN = "Open", "Open"
        CONFIRMED = "Confirmed", "Confirmed"
        DISMISSED = "Dismissed", "Dismissed"

    check_in = models.OneToOneField(CheckIn, on_delete=models.CASCADE, related_name="flag")
    reason = models.CharField(max_length=30, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    flagged_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    flagged_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    resolved_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-flagged_at", "-id"]

    def __str__(self):
        return f"{self.reason} - {self.check_in} ({self.status})"


# A member's Open or Confirmed flags. While they have any, the front desk is
# told to check their photo ID, and door readers send them to the desk
# instead of opening (an unattended door can't check ID).
def active_flags(member):
    return CheckInFlag.objects.filter(check_in__member=member).exclude(status=CheckInFlag.Status.DISMISSED)

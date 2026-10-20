from django.db import models
from django.utils import timezone


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

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.member.name} - {self.result} @ {self.checked_in_at}"


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

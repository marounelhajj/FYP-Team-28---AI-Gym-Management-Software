from django.db import models
from django.utils import timezone

from administration.models import StaffAccount
from members.models import Member

# In-app notifications for staff, shown under the bell in the top bar.
#
# First used by the branch capacity alert (SCRUM-128): when a branch's
# headcount crosses its alert threshold, every active staff account at that
# branch gets one. There is no shift or "on duty" record in this project yet,
# so "on-duty staff" means everyone whose account belongs to the branch; when
# shifts exist, narrow the recipients in headcount.alerts.notify_branch_staff.


class StaffNotification(models.Model):
    class Kind(models.TextChoices):
        CAPACITY_ALERT = "capacity_alert", "Branch near capacity"

    recipient = models.ForeignKey(StaffAccount, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, blank=True)
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=300)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="notification_unread_idx")]

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"


# The member side: shown under the bell in the member's top bar, and emailed
# too (see notifications.delivery.notify_member).
#
# First used by class waitlists: "As a member, I want to join a waitlist for a
# full class and be notified automatically when a spot opens up, so that I
# don't have to keep checking manually."
class MemberNotification(models.Model):
    class Kind(models.TextChoices):
        WAITLIST_SPOT = "waitlist_spot", "Booked into a spot from the waitlist"
        WAITLIST_SKIPPED = "waitlist_skipped", "A waitlist spot couldn't be taken"
        WAITLIST_CLOSED = "waitlist_closed", "Waitlist closed"
        CLASS_CANCELLED = "class_cancelled", "Class cancelled"

    recipient = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=400)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # When the email copy went out; empty if it wasn't sent (no address, or
    # the mail server failed - the in-app one is there either way).
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="member_notification_unread_idx")]

    def __str__(self):
        return f"{self.recipient.name}: {self.title}"

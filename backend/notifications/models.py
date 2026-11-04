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

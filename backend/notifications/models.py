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
        PAY_RATE_CHANGED = "pay_rate_changed", "Your pay rate changed"

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
        CLASS_CHANGED = "class_changed", "Class time, studio or coach changed"
        PT_CANCELLED = "pt_cancelled", "Private session cancelled by the gym"
        CLASS_REMINDER = "class_reminder", "Upcoming class reminder"
        PT_REMINDER = "pt_reminder", "Upcoming private session reminder"
        RENEWAL_REMINDER = "renewal_reminder", "Membership renewal reminder"

    recipient = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=600)
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


# User story: "As a member, I want to receive notifications before an upcoming
# class or when my membership is about to renew, so that I don't miss sessions
# or get charged unexpectedly."
#
# How a member wants to be reminded. No row means the defaults below - every
# member gets reminders without having to set anything up first.
class NotificationSettings(models.Model):
    # How long before a class or private session the second reminder goes (0 = none).
    CLASS_MINUTES_CHOICES = (0, 30, 60, 120, 180)
    # How many days before the renewal date the first reminder goes (0 = none);
    # a last one always follows the day before.
    RENEWAL_DAYS_CHOICES = (0, 1, 3, 7, 14)

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="notification_settings")
    class_day_before = models.BooleanField(default=True)
    class_minutes_before = models.PositiveSmallIntegerField(default=60)
    renewal_days_before = models.PositiveSmallIntegerField(default=7)
    # Email a copy of every notification, not just show it in the app.
    email = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notification settings for {self.member.name}"


# One row per reminder that went out (or was passed over because a later one
# for the same thing was already due). The key is unique, so however often
# the reminder job runs - even two at once - nobody is reminded twice.
#
# Keys: "class:<booking>:<start>:<minutes>", "pt:<session>:<start>:<minutes>",
# "renewal:<member>:<renewal date>:<days>". The start time and renewal date are
# part of it, so a class that's moved or a membership that's renewed gets
# fresh reminders for the new time.
class SentReminder(models.Model):
    class Kind(models.TextChoices):
        CLASS = "class", "Class"
        PT = "pt", "Private session"
        RENEWAL = "renewal", "Renewal"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="sent_reminders")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    key = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    # Empty when it was skipped: a later reminder for the same thing was due too.
    notification = models.ForeignKey(MemberNotification, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.key

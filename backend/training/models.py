from django.db import models
from django.utils import timezone

from members.models import Member

# Training data for the AI models (SCRUM-73).
#
# User story: "As a system administrator, I want check-ins, cancellations,
# no-shows, and trainer accept/reject decisions logged as training data from
# first release, so that the models have a dataset to learn from later."
#
# One append-only row per event, written by training.events.log_training_event()
# from the view that performed the action. Rows can't be edited (save() on an
# existing row and queryset update() both raise), but they can be deleted:
# a member's data deletion request removes their events
# (training.events.delete_training_events_for_member), and so does deleting
# the member outright (on_delete=CASCADE).
#
# Branches are plain names in this codebase (Member.Branch), not a table,
# so "branch id" is the branch name.


class TrainingEventImmutable(Exception):
    pass


class TrainingEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise TrainingEventImmutable("Training events can't be changed.")


class TrainingEvent(models.Model):
    class EventType(models.TextChoices):
        CHECK_IN = "check_in", "Check-in"
        CANCELLATION = "cancellation", "Membership cancellation"
        NO_SHOW = "no_show", "No-show"
        TRAINER_ACCEPT = "trainer_accept", "Trainer accepted"
        TRAINER_REJECT = "trainer_reject", "Trainer rejected"

    event_type = models.CharField(max_length=20, choices=EventType.choices)
    # When it happened, in UTC (USE_TZ = True stores every datetime as UTC).
    occurred_at = models.DateTimeField(default=timezone.now)
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="training_events")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    # The coach involved, for trainer accept/reject (and later, no-shows on a
    # PT session). Kept when the account is removed, just without the link.
    trainer = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    # The class session or PT booking the event is about, once those exist.
    session_id = models.CharField(max_length=64, blank=True)
    # Small bits of extra context, e.g. {"checkInId": 12, "method": "qr"}.
    # Never names, emails or phone numbers - the member is already linked above.
    payload = models.JSONField(default=dict, blank=True)

    objects = TrainingEventQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "occurred_at"], name="training_branch_time_idx"),
            models.Index(fields=["member", "occurred_at"], name="training_member_time_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise TrainingEventImmutable("Training events can't be changed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event_type} - member {self.member_id} @ {self.branch} ({self.occurred_at:%Y-%m-%d %H:%M})"

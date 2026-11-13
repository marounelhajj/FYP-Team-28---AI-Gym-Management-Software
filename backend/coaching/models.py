from django.db import models

from administration.models import StaffAccount
from classes.models import PTSession
from members.models import Member
from progress.models import WorkoutEntry

# User story: "As a coach, I want to log client workout sessions and progress
# notes, so that I can track each client's development over time."
#
# The method (what personal trainers and strength coaches commonly use):
#   * A training log per session - each exercise as sets x reps @ kg, with how
#     hard it felt (RPE, 1-10). Same shape as the member's own log (SCRUM-60),
#     so both feed one strength history.
#   * A SOAP progress note: Subjective (how the client felt), Objective (what
#     was done or measured), Assessment (the coach's judgement - coaches only)
#     and Plan (what's next, shown when the next session is logged).
#   * SMART goals - specific, measured, with a date - whose progress is worked
#     out from the logged numbers (coaching/progress.py), not guessed.
#
# Private sessions only: a group class is attendance, not one-to-one coaching.


class SessionLog(models.Model):
    session = models.OneToOneField(PTSession, on_delete=models.CASCADE, related_name="log")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="coach_session_logs")
    coach = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="session_logs")
    subjective = models.CharField(max_length=1000, blank=True)
    objective = models.CharField(max_length=1000, blank=True)
    # The coach's own judgement: shown to coaches, never to the member.
    assessment = models.CharField(max_length=1000, blank=True)
    plan = models.CharField(max_length=1000, blank=True)
    # Measured in the session (re-assessment), alongside what the member logs themselves.
    body_weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    # How hard the whole session was, 1-10.
    session_rpe = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-session__starts_at", "-id"]

    def __str__(self):
        return f"{self.member.name} with {self.coach.full_name}, session {self.session_id}"


class LoggedExercise(models.Model):
    log = models.ForeignKey(SessionLog, on_delete=models.CASCADE, related_name="exercises")
    order = models.PositiveSmallIntegerField(default=0)
    exercise = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=WorkoutEntry.Kind.choices)
    sets = models.PositiveSmallIntegerField(null=True, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rpe = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.exercise} ({self.log})"


class ClientGoal(models.Model):
    class Kind(models.TextChoices):
        STRENGTH = "strength", "Lift a weight (estimated 1-rep max)"
        BODY_WEIGHT = "body_weight", "Reach a body weight"
        CUSTOM = "custom", "Other (marked by the coach)"

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        ACHIEVED = "Achieved", "Achieved"
        DROPPED = "Dropped", "Dropped"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="goals")
    set_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=120)
    exercise = models.CharField(max_length=80, blank=True)
    # Where the client stood when the goal was set (None: no data yet), and where they're going.
    start_value = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    target_value = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    target_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    closed_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_date", "id"]

    def __str__(self):
        return f"{self.member.name}: {self.title} ({self.status})"

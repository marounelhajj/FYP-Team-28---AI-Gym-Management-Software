from django.db import models
from django.utils import timezone

from members.models import Member

# At-risk members (SCRUM-118).
#
# User story: "As a branch manager, I want to view a ranked list of members
# at risk of leaving, so that I know who to contact first."
#
# Once a week every non-cancelled member of a branch is scored 0-100
# (churn.scoring.score_members) and the result is saved as that week's
# snapshot: one ChurnScore row per member, plus one ChurnRun row saying
# when, how (rules or the branch's learned model) and by whom. The list a
# branch manager sees is the snapshot for the current week. Branches are
# plain names in this codebase (Member.Branch), not a table.


class Method(models.TextChoices):
    RULES = "rules", "Rule-based"
    MODEL = "model", "Learned model"


# One trained model per branch and training run. Small: a handful of
# coefficients and the standardization used for them, so it is stored as
# JSON in the database - there is no model file.
class ChurnModel(models.Model):
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    version = models.CharField(max_length=60, unique=True)
    trained_at = models.DateTimeField(default=timezone.now)
    # Training only used cutoffs up to this date (no peeking past it).
    trained_as_of = models.DateField()
    features = models.JSONField(default=list)
    coefficients = models.JSONField(default=list)
    intercept = models.FloatField(default=0)
    means = models.JSONField(default=list)
    stds = models.JSONField(default=list)
    # {"auc", "precisionAtN", "baseRate", "n", "holdoutExamples", ...}
    metrics = models.JSONField(default=dict)
    examples = models.PositiveIntegerField(default=0)
    cancellations = models.PositiveIntegerField(default=0)
    members = models.PositiveIntegerField(default=0)
    # False when it was trained but didn't validate well enough to be used.
    usable = models.BooleanField(default=False)

    class Meta:
        ordering = ["-trained_at", "-id"]

    def __str__(self):
        return f"{self.version} ({'usable' if self.usable else 'not used'})"


class ChurnRun(models.Model):
    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Weekly schedule"
        MANUAL = "manual", "Refresh now"
        # The list was opened and this week's hadn't been made yet.
        ON_DEMAND = "on_demand", "Opened before the weekly run"
        COMMAND = "command", "Management command"

    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    # Monday of the week the snapshot belongs to.
    week_start = models.DateField()
    # The date the features were computed as of (today for a live run).
    as_of = models.DateField()
    ran_at = models.DateTimeField(default=timezone.now)
    method = models.CharField(max_length=10, choices=Method.choices)
    model = models.ForeignKey(ChurnModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs")
    # Why the rules were used, when they were ("not enough history: ...").
    method_note = models.CharField(max_length=255, blank=True)
    members_scored = models.PositiveIntegerField(default=0)
    trigger = models.CharField(max_length=10, choices=Trigger.choices)
    triggered_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-ran_at", "-id"]
        indexes = [models.Index(fields=["branch", "week_start"], name="churn_run_branch_week_idx")]

    def __str__(self):
        return f"{self.branch} week of {self.week_start} ({self.method}, {self.members_scored} members)"


class ChurnScore(models.Model):
    run = models.ForeignKey(ChurnRun, on_delete=models.CASCADE, related_name="scores")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    week_start = models.DateField()
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="churn_scores")
    rank = models.PositiveIntegerField()
    score = models.PositiveSmallIntegerField()
    level = models.CharField(max_length=10)
    method = models.CharField(max_length=10, choices=Method.choices)
    model_version = models.CharField(max_length=60, blank=True)
    # Top contributing features, largest first:
    # [{"feature": "attendance_drop", "points": 18.2}, ...]
    reasons = models.JSONField(default=list)
    # The raw feature values the score was computed from (numbers only).
    features = models.JSONField(default=dict)

    class Meta:
        ordering = ["branch", "week_start", "rank"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "week_start", "member"], name="one_churn_score_per_member_week"),
        ]
        indexes = [models.Index(fields=["branch", "week_start", "rank"], name="churn_score_list_idx")]

    def __str__(self):
        return f"#{self.rank} {self.member_id} {self.score} ({self.branch}, {self.week_start})"

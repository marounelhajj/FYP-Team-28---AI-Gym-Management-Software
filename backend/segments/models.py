from django.db import models
from django.utils import timezone

from administration.models import StaffAccount

# Member segmentation (SCRUM-43).
#
# User story: "As a marketing staff member, I want to segment members by
# behavior or demographics, so that I can send targeted communications."
#
# Two kinds of segment, one table:
#   * rule-based: a set of filters, all combined with AND (segments/filters.py);
#   * saved from a suggested cluster: the filters hold {"clusterGroup": <id>},
#     i.e. "the members the clustering run put in that group", and can still
#     be narrowed with the normal filters.
#
# Segments are organisation-wide. Who sees which members is decided when a
# segment is evaluated, not stored here (segments/scope.py): a general
# manager or marketing staff see every branch, a branch manager only their
# own branch's members.


class Segment(models.Model):
    class Source(models.TextChoices):
        RULES = "rules", "Built from filters"
        CLUSTER = "cluster", "Saved from a suggested segment"

    name = models.CharField(max_length=60)
    description = models.CharField(max_length=300, blank=True)
    # Normalised by filters.clean_filters before saving.
    filters = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.RULES)
    created_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


# Suggested segments: one row per clustering run (weekly with the churn job,
# or on demand), and one ClusterGroup per cluster it found.
class ClusterRun(models.Model):
    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Weekly run"
        MANUAL = "manual", "Run on demand"

    ran_at = models.DateTimeField(default=timezone.now)
    # The Monday of the week it ran in: the weekly job runs once per week.
    week_start = models.DateField(db_index=True)
    trigger = models.CharField(max_length=10, choices=Trigger.choices)
    triggered_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    model_version = models.CharField(max_length=40)
    seed = models.PositiveIntegerField()
    k = models.PositiveSmallIntegerField(null=True, blank=True)
    silhouette = models.FloatField(null=True, blank=True)
    # Every k that was tried: [{"k": 3, "silhouette": 0.41}, ...]
    candidates = models.JSONField(default=list)
    members_clustered = models.PositiveIntegerField(default=0)
    feature_names = models.JSONField(default=list)
    # Per-feature mean and spread used to scale the features: {"name": [mean, sd]}.
    scaler = models.JSONField(default=dict)
    # Set when there were too few active members to cluster.
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-ran_at", "-id"]

    def __str__(self):
        return f"Clusters {self.ran_at:%Y-%m-%d} (k={self.k}, {self.members_clustered} members)"


class ClusterGroup(models.Model):
    run = models.ForeignKey(ClusterRun, on_delete=models.CASCADE, related_name="groups")
    # 0 = largest cluster.
    position = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=400)
    size = models.PositiveIntegerField()
    # The cluster centre in plain units: {"visitsPerWeek": 3.1, "meanHour": 18.4, ...}
    centroid = models.JSONField(default=dict)
    member_ids = models.JSONField(default=list)

    class Meta:
        ordering = ["run", "position"]

    def __str__(self):
        return f"{self.name} ({self.size})"

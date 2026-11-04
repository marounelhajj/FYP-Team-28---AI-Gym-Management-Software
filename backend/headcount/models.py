import math

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from administration.models import StaffAccount
from members.models import Member

# User story (SCRUM-128): "As a branch manager, I want to be alerted when
# headcount approaches the branch capacity limit, so that I can act before
# the floor becomes unsafe or unpleasant."
#
# One row per branch: the most people the floor should hold and the share of
# that at which staff are alerted (90% by default). The alert's own state
# lives here too, so it fires once per crossing - see headcount/alerts.py.
#
# A branch with no row has no capacity set: no alert, and members get no
# busy level for it (SCRUM-77).

DEFAULT_ALERT_PERCENT = 90
# The alert clears only once headcount is this share of capacity below the
# threshold, so a count hovering at the line doesn't flicker on and off.
CLEAR_MARGIN_PERCENT = 5


class BranchCapacity(models.Model):
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, unique=True)
    max_capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5000)])
    alert_percent = models.PositiveSmallIntegerField(
        default=DEFAULT_ALERT_PERCENT, validators=[MinValueValidator(10), MaxValueValidator(100)],
    )
    alert_active = models.BooleanField(default=False)
    alert_raised_at = models.DateTimeField(null=True, blank=True)
    alert_cleared_at = models.DateTimeField(null=True, blank=True)
    # The headcount that set the alert off.
    alert_count = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch"]
        verbose_name_plural = "branch capacities"

    def __str__(self):
        return f"{self.branch}: {self.max_capacity} people, alert at {self.alert_percent}%"

    # Headcount at or above this raises the alert.
    @property
    def threshold(self):
        return max(1, math.ceil(self.max_capacity * self.alert_percent / 100))

    # Headcount below this clears it again (threshold minus CLEAR_MARGIN_PERCENT
    # of capacity, at least one person).
    @property
    def clear_below(self):
        margin = max(1, math.ceil(self.max_capacity * CLEAR_MARGIN_PERCENT / 100))
        return max(0, self.threshold - margin)

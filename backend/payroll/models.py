from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from administration.models import StaffAccount

# User story: "As a coach, I want to view my completed session count and
# earnings for the current pay period, so that I can verify my pay is
# correct."
#
# Nothing in the app knew what a coach earns, so the story needs pay rates
# first. A coach is paid by the hour taught: one rate for group classes, one
# for private training, set by their branch manager. A rate applies from its
# effective date until the next one, so a raise mid-month pays the old rate
# for sessions before it and the new rate after - and every session in a
# statement says which rate it was paid at.

MAX_HOURLY = 500


class CoachPayRate(models.Model):
    coach = models.ForeignKey(StaffAccount, on_delete=models.CASCADE, related_name="pay_rates")
    # US dollars per hour taught.
    class_hourly = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURLY)],
    )
    pt_hourly = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(MAX_HOURLY)],
    )
    effective_from = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    set_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["coach", "effective_from"], name="one_pay_rate_per_coach_per_day"),
        ]

    def __str__(self):
        return f"{self.coach.full_name}: ${self.class_hourly}/h classes, ${self.pt_hourly}/h PT from {self.effective_from}"

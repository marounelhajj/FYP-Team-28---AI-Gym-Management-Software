from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from members.models import Member

# User story: "As a general manager, I want to view expense and revenue
# data for each branch, so that I can monitor financial performance and
# compare branches."
#
# Revenue already exists - it's billing.Payment.amount, summed by the
# paying member's branch (see finance/views.py). Nothing anywhere tracked
# a branch's running costs, so Expense is the one new thing this story
# needed: a simple, manually-recorded cost (rent, payroll, ...). Recording
# one requires manage_billing - defined in
# administration.models.PERMISSION_CHOICES already, just not enforced
# anywhere until now; viewing the revenue/expense report requires
# view_financial_reports (same story - already seeded for System
# Administrator, General Manager and Branch Manager, unused until now).


class Expense(models.Model):
    class Category(models.TextChoices):
        RENT = "Rent", "Rent"
        PAYROLL = "Payroll", "Payroll"
        UTILITIES = "Utilities", "Utilities"
        EQUIPMENT = "Equipment & Maintenance", "Equipment & Maintenance"
        MARKETING = "Marketing", "Marketing"
        OTHER = "Other", "Other"

    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    category = models.CharField(max_length=30, choices=Category.choices)
    amount = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)])
    # The date the cost was actually incurred (a receipt date, a pay
    # period), separate from created_at (when it was typed into the
    # system) - they drift apart whenever an expense is entered late.
    incurred_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-incurred_on", "-id"]

    def __str__(self):
        return f"{self.branch} - {self.category}: {self.amount} ({self.incurred_on})"

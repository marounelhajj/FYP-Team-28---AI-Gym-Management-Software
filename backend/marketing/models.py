from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from administration.models import StaffAccount
from members.models import Member

# User story: "As a general manager, I want to view the marketing
# campaigns and strategies being run at each branch, so that I can assess
# alignment with overall brand direction and spending."
#
# manage_marketing_campaigns already existed in administration's
# PERMISSION_CHOICES and was already seeded onto the Marketing Staff role,
# but nothing anywhere used it - there was no campaign to manage.
# MarketingCampaign is the one new thing this story needs: a branch-local
# campaign with its strategy (what it's for, read by a General Manager to
# judge "alignment with brand direction") and budget/spend (the other half
# of the story). Viewing the cross-branch report requires a new, separate
# permission (view_marketing_campaigns, General Manager only) - the same
# split already used for finance's view_financial_reports vs
# manage_billing: reading the comparison and running a campaign are
# different privileges.


class MarketingCampaign(models.Model):
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    name = models.CharField(max_length=80)
    # The actual plan/approach, not just a label - what a General Manager
    # reads to judge brand alignment.
    strategy = models.TextField(blank=True)
    budget = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    amount_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaigns_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "id"]

    # Same shape as plans.BranchPromotion.status - Scheduled before it
    # starts, Running within its dates, Expired once past end_date,
    # Cancelled whenever is_active is turned off (at any point).
    @property
    def status(self):
        today = timezone.localdate()
        if not self.is_active:
            return "Cancelled"
        if today < self.start_date:
            return "Scheduled"
        if today > self.end_date:
            return "Expired"
        return "Running"

    def __str__(self):
        return f"{self.name} @ {self.branch}"

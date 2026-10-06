from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from administration.models import StaffAccount
from members.models import Member

CENT = Decimal("0.01")


# An organization-wide membership plan / pricing tier. Plans are defined
# once by a General Manager and apply to every branch - there is
# deliberately no branch field, so the base price is the same everywhere.
# Branches can only move away from it through a BranchPromotion, and only
# by up to max_promo_discount_percent, which the General Manager controls.
#
# Plans are archived (is_active=False) rather than deleted: existing
# members may still be on a plan that is no longer sold to new customers.
class MembershipPlan(models.Model):
    class BillingCycle(models.TextChoices):
        MONTHLY = "Monthly", "Monthly"
        QUARTERLY = "Quarterly", "Quarterly"
        SEMI_ANNUAL = "Semi-Annual", "Semi-Annual"
        ANNUAL = "Annual", "Annual"

    # How many months each billing cycle covers - used to compute a
    # comparable monthly price across tiers with different cycles.
    CYCLE_MONTHS = {
        BillingCycle.MONTHLY: 1,
        BillingCycle.QUARTERLY: 3,
        BillingCycle.SEMI_ANNUAL: 6,
        BillingCycle.ANNUAL: 12,
    }

    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    billing_cycle = models.CharField(max_length=20, choices=BillingCycle.choices, default=BillingCycle.MONTHLY)
    features = models.JSONField(default=list, blank=True)
    max_promo_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("20.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["price", "name"]

    @property
    def monthly_equivalent(self):
        months = self.CYCLE_MONTHS.get(self.billing_cycle, 1)
        return (Decimal(self.price) / months).quantize(CENT)

    @property
    def max_promo_discount_amount(self):
        return (Decimal(self.price) * Decimal(self.max_promo_discount_percent) / 100).quantize(CENT)

    def __str__(self):
        return f"{self.name} (${self.price} / {self.billing_cycle})"


# A time-boxed, branch-local discount on one organization-wide plan.
#
# The discount is always capped at the plan's max_promo_discount_percent,
# both when the promotion is saved (see the write serializer) and again
# whenever a price is computed - so if the General Manager later lowers the
# cap, running promotions shrink to fit instead of breaking consistency.
class BranchPromotion(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "Percent", "Percent"
        FIXED = "Fixed", "Fixed amount"

    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, related_name="promotions")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    name = models.CharField(max_length=80)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    discount_value = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="promotions_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "id"]

    def requested_discount_amount(self):
        price = Decimal(self.plan.price)
        if self.discount_type == self.DiscountType.PERCENT:
            return (price * Decimal(self.discount_value) / 100).quantize(CENT)
        return Decimal(self.discount_value).quantize(CENT)

    def discount_amount(self):
        return min(self.requested_discount_amount(), self.plan.max_promo_discount_amount)

    def effective_price(self):
        return max(Decimal(self.plan.price) - self.discount_amount(), Decimal("0.00"))

    def is_running(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self.is_active and self.plan.is_active and self.start_date <= on_date <= self.end_date

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
        return f"{self.name} - {self.plan.name} @ {self.branch}"

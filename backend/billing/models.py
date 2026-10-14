import calendar
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

DURATION_MONTHS = {"1 Month": 1, "1 Year": 12}
CENT = Decimal("0.01")

YEARLY_MULTIPLIER = 12
YEARLY_PROMO_DISCOUNT = Decimal("20.00")


# The monthly price is never hardcoded here - it's looked up from the
# General Manager-editable plans.MembershipPlan catalog (deferred import to
# keep billing/models.py free of a top-level plans import), normalized to
# a monthly figure via CYCLE_MONTHS in case the plan itself isn't billed
# monthly. If the member's branch has a running BranchPromotion on this
# plan, the best one is applied before the monthly figure is derived - so
# a branch promotion discounts both the "1 Month" and "1 Year" price, same
# as it discounts the branch's advertised rate (see plans.views.branch_pricing,
# which this mirrors).
#
# A year then costs 12x that (possibly already-discounted) monthly price,
# minus a flat $20 annual-prepay promo - e.g. Basic ($25/mo) is
# $300 - $20 = $280/yr. Centralized here so every caller of Payment.record()
# prices a year the same way.
def price_for(plan, duration, branch=None):
    from plans.models import BranchPromotion, MembershipPlan

    membership_plan = MembershipPlan.objects.get(name__iexact=plan, is_active=True)
    cycle_months = MembershipPlan.CYCLE_MONTHS.get(membership_plan.billing_cycle, 1)
    cycle_price = Decimal(membership_plan.price)

    if branch:
        today = timezone.localdate()
        best_promo = None
        for promo in BranchPromotion.objects.filter(
            plan=membership_plan, branch=branch, is_active=True,
            start_date__lte=today, end_date__gte=today,
        ):
            if best_promo is None or promo.discount_amount() > best_promo.discount_amount():
                best_promo = promo
        if best_promo is not None:
            cycle_price = membership_plan.price - best_promo.discount_amount()

    monthly = (cycle_price / cycle_months).quantize(CENT)

    if duration == Payment.Duration.ONE_YEAR:
        return monthly * YEARLY_MULTIPLIER - YEARLY_PROMO_DISCOUNT
    return monthly


def _add_months(start_date, months):
    # Month-aware date math (e.g. Jan 31 + 1 month -> Feb 28), stdlib only -
    # no need for python-dateutil for just this.
    month_index = start_date.month - 1 + months
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return start_date.replace(year=year, month=month, day=day)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "Cash", "Cash"
        CARD = "Card", "Card"
        BANK_TRANSFER = "Bank Transfer", "Bank Transfer"

    class Duration(models.TextChoices):
        ONE_MONTH = "1 Month", "1 Month"
        ONE_YEAR = "1 Year", "1 Year"

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)])
    method = models.CharField(max_length=20, choices=Method.choices)
    duration = models.CharField(max_length=10, choices=Duration.choices)
    paid_at = models.DateTimeField(auto_now_add=True)
    # Persisted (not computed on the fly) so a payment's expiry never
    # silently shifts if the duration->months mapping ever changes later.
    expires_at = models.DateField()
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.member.name} - {self.amount} ({self.method}, {self.duration})"

    # Shared creation path for both "first payment at registration" and a
    # later renewal - the one place subscription expiry math, pricing, and
    # reactivation live, so the flows can't drift apart.
    #
    # plan is a required, explicit choice every time (not inferred/reused
    # from the member's existing plan) - this is how a receptionist can
    # change a member's plan at renewal time, and how the plan they picked
    # at registration/signup gets recorded here too. amount is NEVER
    # accepted from the client - it's always price_for(plan, duration), so
    # whoever is taking the payment can't enter an arbitrary amount, by
    # construction, not just by UI convention.
    #
    # Renewing before the current expiry stacks the new period on top of
    # whatever time is left; renewing after expiry starts fresh from today
    # - a lapsed period isn't carried over. Either way, the member is
    # (re)activated: this is the only thing that ever sets status back to
    # Active - nothing reactivates a member automatically.
    @staticmethod
    def record(member, plan, method, duration, note=""):
        from members.models import Member

        amount = price_for(plan, duration, branch=member.branch)
        today = timezone.localdate()
        anchor = max(today, member.subscription_expires_at) if member.subscription_expires_at else today
        expires_at = _add_months(anchor, DURATION_MONTHS[duration])

        with transaction.atomic():
            payment = Payment.objects.create(
                member=member, amount=amount, method=method, duration=duration,
                expires_at=expires_at, note=note,
            )
            member.membership_plan = plan
            member.status = Member.Status.ACTIVE
            member.subscription_expires_at = expires_at
            member.save(update_fields=["membership_plan", "status", "subscription_expires_at"])
        return payment

import calendar
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

DURATION_MONTHS = {"1 Month": 1, "1 Year": 12}

# Fixed, organization-wide MONTHLY price per membership plan - not
# editable by whoever is taking the payment. Keyed by the plain plan name
# (matches members.Member.Plan's string values) rather than importing that
# enum here, to keep billing/models.py free of a top-level members import.
PLAN_PRICES = {
    "Basic": Decimal("25.00"),
    "Standard": Decimal("40.00"),
    "Premium": Decimal("50.00"),
}

YEARLY_MULTIPLIER = 12
YEARLY_PROMO_DISCOUNT = Decimal("20.00")


# A year costs 12x the monthly price (the full annual rate), minus a flat
# $20 promo - e.g. Basic ($25/mo) is $300 - $20 = $280/yr. Centralized here
# so every caller of Payment.record() prices a year the same way.
def price_for(plan, duration):
    monthly = PLAN_PRICES[plan]
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

        amount = price_for(plan, duration)
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

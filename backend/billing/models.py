import calendar
from dataclasses import dataclass
from datetime import date
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
# which this mirrors). Returns (monthly price, promotion applied or None).
def _monthly_price(plan, branch=None):
    from plans.models import BranchPromotion, MembershipPlan

    membership_plan = MembershipPlan.objects.get(name__iexact=plan, is_active=True)
    cycle_months = MembershipPlan.CYCLE_MONTHS.get(membership_plan.billing_cycle, 1)
    cycle_price = Decimal(membership_plan.price)

    best_promo = None
    if branch:
        today = timezone.localdate()
        for promo in BranchPromotion.objects.filter(
            plan=membership_plan, branch=branch, is_active=True,
            start_date__lte=today, end_date__gte=today,
        ):
            if best_promo is None or promo.discount_amount() > best_promo.discount_amount():
                best_promo = promo
        if best_promo is not None:
            cycle_price = membership_plan.price - best_promo.discount_amount()

    return (cycle_price / cycle_months).quantize(CENT), best_promo


def _add_months(start_date, months):
    # Month-aware date math (e.g. Jan 31 + 1 month -> Feb 28), stdlib only -
    # no need for python-dateutil for just this.
    month_index = start_date.month - 1 + months
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return start_date.replace(year=year, month=month, day=day)


@dataclass(frozen=True)
class RenewalQuote:
    amount: Decimal
    # The undiscounted 12x monthly price of a "1 Year" renewal (shown struck
    # through next to amount); None for "1 Month".
    original_amount: Decimal | None
    promotion: str | None
    starts_on: date
    expires_at: date


# What a payment for this plan/duration would charge right now and the
# period it would cover - the single source of truth for both the quote a
# receptionist reads out before charging and the Payment actually recorded.
#
# A year costs 12x the (possibly branch-discounted) monthly price, minus a
# flat $20 annual-prepay promo - e.g. Basic ($25/mo) is $300 - $20 = $280/yr.
# Renewing before the current expiry stacks the new period on top of the
# time that's left; renewing after it lapsed starts fresh from today.
def renewal_quote(member, plan, duration):
    monthly, promo = _monthly_price(plan, member.branch)
    if duration == Payment.Duration.ONE_YEAR:
        original_amount = monthly * YEARLY_MULTIPLIER
        amount = original_amount - YEARLY_PROMO_DISCOUNT
    else:
        original_amount, amount = None, monthly

    today = timezone.localdate()
    starts_on = max(today, member.subscription_expires_at) if member.subscription_expires_at else today
    return RenewalQuote(
        amount=amount,
        original_amount=original_amount,
        promotion=promo.name if promo else None,
        starts_on=starts_on,
        expires_at=_add_months(starts_on, DURATION_MONTHS[duration]),
    )


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
    # e.g. "Card ending 4242" when the member paid with their method on file -
    # a snapshot, so history stays accurate after that card is replaced.
    method_detail = models.CharField(max_length=150, blank=True)
    duration = models.CharField(max_length=10, choices=Duration.choices)
    paid_at = models.DateTimeField(auto_now_add=True)
    # Persisted (not computed on the fly) so a payment's expiry never
    # silently shifts if the duration->months mapping ever changes later.
    expires_at = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    # The staff member who took the payment; null for an online signup.
    recorded_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-paid_at", "-id"]

    def __str__(self):
        return f"{self.member.name} - {self.amount} ({self.method}, {self.duration})"

    # Shared creation path for the first payment (registration or online
    # signup) and every later renewal - the one place pricing, expiry math
    # and reactivation live, so the flows can't drift apart.
    #
    # plan is an explicit choice every time (this is also how a plan changes
    # at renewal), and amount is NEVER accepted from the client - it's always
    # renewal_quote()'s price. This is the only thing that ever sets a
    # member's status back to Active; nothing renews automatically.
    @staticmethod
    def record(member, plan, method, duration, note="", recorded_by=None):
        from members.models import Member

        with transaction.atomic():
            # Locked so two simultaneous renewals can't both stack onto the same old expiry.
            locked = Member.objects.select_for_update().get(pk=member.pk)
            quote = renewal_quote(locked, plan, duration)
            on_file = payment_method_on_file(locked)
            payment = Payment.objects.create(
                member=member, amount=quote.amount, method=method, duration=duration,
                expires_at=quote.expires_at, note=note, recorded_by=recorded_by,
                method_detail=on_file.reference() if on_file and on_file.method == method else "",
            )
            member.membership_plan = plan
            member.status = Member.Status.ACTIVE
            member.subscription_expires_at = quote.expires_at
            member.save(update_fields=["membership_plan", "status", "subscription_expires_at"])
        return payment


# How a member prefers to pay for renewals, kept current by the front desk.
# Reference details only: the card itself is charged on the desk terminal,
# so the full card number and CVV are never collected or stored.
class PaymentMethod(models.Model):
    member = models.OneToOneField("members.Member", on_delete=models.CASCADE, related_name="payment_method")
    method = models.CharField(max_length=20, choices=Payment.Method.choices)
    card_holder_name = models.CharField(max_length=150, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)
    card_expiry_month = models.PositiveSmallIntegerField(null=True, blank=True)
    card_expiry_year = models.PositiveSmallIntegerField(null=True, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_last4 = models.CharField(max_length=4, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    def __str__(self):
        return f"{self.member.name}: {self.reference() or self.method}"

    def reference(self):
        if self.method == Payment.Method.CARD:
            return f"Card ending {self.card_last4}"
        if self.method == Payment.Method.BANK_TRANSFER:
            return f"{self.bank_name} account ending {self.bank_account_last4}"
        return ""

    # A card is valid through the last day of its expiry month.
    def card_valid_through(self):
        if self.method != Payment.Method.CARD or not (self.card_expiry_month and self.card_expiry_year):
            return None
        last_day = calendar.monthrange(self.card_expiry_year, self.card_expiry_month)[1]
        return date(self.card_expiry_year, self.card_expiry_month, last_day)

    def card_expired(self):
        valid_through = self.card_valid_through()
        return valid_through is not None and valid_through < timezone.localdate()


def payment_method_on_file(member):
    return PaymentMethod.objects.select_related("member", "updated_by").filter(member=member).first()

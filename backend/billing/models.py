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
    # through next to amount); None for "1 Month". With an offer code it's the
    # undiscounted price for either duration.
    original_amount: Decimal | None
    promotion: str | None
    starts_on: date
    expires_at: date
    # A marketing offer code (marketing.offers), when it's what priced this:
    # the code, what it took off, and the campaign. offer_note says why a
    # code that was entered isn't used (or was capped).
    offer_code: str | None = None
    offer_discount: Decimal | None = None
    offer_note: str | None = None
    offer_campaign: object = None


# What a payment for this plan/duration would charge right now and the
# period it would cover - the single source of truth for both the quote a
# receptionist reads out before charging and the Payment actually recorded.
#
# A year costs 12x the (possibly branch-discounted) monthly price, minus a
# flat $20 annual-prepay promo - e.g. Basic ($25/mo) is $300 - $20 = $280/yr.
# Renewing before the current expiry stacks the new period on top of the
# time that's left; renewing after it lapsed starts fresh from today.
#
# `offer` is a marketing campaign whose code the member gave (already checked
# by marketing.offers.check_offer). It doesn't stack with a branch promotion:
# the code is taken off the plan's full price for the period, and whichever
# of the two is cheaper for the member is used. Either way the discount is
# capped by the plan's max_promo_discount_percent - the General Manager's
# limit applies to marketing's codes as much as to branch promotions.
def renewal_quote(member, plan, duration, offer=None):
    monthly, promo = _monthly_price(plan, member.branch)
    year = duration == Payment.Duration.ONE_YEAR
    if year:
        original_amount = monthly * YEARLY_MULTIPLIER
        amount = original_amount - YEARLY_PROMO_DISCOUNT
    else:
        original_amount, amount = None, monthly

    offer_code = offer_discount = offer_note = offer_campaign = None
    if offer is not None:
        full, cap, membership_plan = _full_price(plan, DURATION_MONTHS[duration])
        wanted = offer.discount_on(full)
        off = min(wanted, cap)
        with_code = max(full - off - (YEARLY_PROMO_DISCOUNT if year else Decimal("0")), Decimal("0.00"))
        if off <= 0:
            offer_note = f"The {membership_plan.name} plan can't be discounted, so {offer.offer_code} isn't used."
        elif with_code >= amount:
            offer_note = (
                f'The branch offer "{promo.name}" already gives a better price, so {offer.offer_code} isn\'t used.'
                if promo else f"{offer.offer_code} doesn't lower this price, so it isn't used."
            )
        else:
            amount, original_amount, promo = with_code, full, None
            offer_code, offer_discount, offer_campaign = offer.offer_code, off, offer
            if off < wanted:
                offer_note = (
                    f"Capped at {membership_plan.max_promo_discount_percent.normalize():f}% - the most a "
                    f"{membership_plan.name} membership can be discounted."
                )

    today = timezone.localdate()
    starts_on = max(today, member.subscription_expires_at) if member.subscription_expires_at else today
    return RenewalQuote(
        amount=amount,
        original_amount=original_amount,
        promotion=promo.name if promo else None,
        starts_on=starts_on,
        expires_at=_add_months(starts_on, DURATION_MONTHS[duration]),
        offer_code=offer_code,
        offer_discount=offer_discount,
        offer_note=offer_note,
        offer_campaign=offer_campaign,
    )


# The plan's undiscounted price for `months` (no branch promotion), and the
# most a promotion may take off it.
def _full_price(plan, months):
    from plans.models import MembershipPlan

    membership_plan = MembershipPlan.objects.get(name__iexact=plan, is_active=True)
    cycle_months = MembershipPlan.CYCLE_MONTHS.get(membership_plan.billing_cycle, 1)
    full = (Decimal(membership_plan.price) / cycle_months).quantize(CENT) * months
    cap = (full * Decimal(membership_plan.max_promo_discount_percent) / 100).quantize(CENT)
    return full, cap, membership_plan


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
    #
    # `offer`: a marketing campaign whose code the member gave - its use is
    # recorded in the same transaction, so if it can't be (just fully claimed,
    # or used at another desk a moment ago) marketing.offers.OfferError is
    # raised and no payment is recorded either.
    @staticmethod
    def record(member, plan, method, duration, note="", recorded_by=None, offer=None):
        from members.models import Member

        with transaction.atomic():
            # A brand new member's first payment vs. an existing member's
            # renewal/reactivation - same note convention finance.views
            # already reads (note.startswith("First payment")) to split
            # revenue, reused here to tag the redemption the same way.
            is_signup = note.startswith("First payment")
            # Locked so two simultaneous renewals can't both stack onto the same old expiry.
            locked = Member.objects.select_for_update().get(pk=member.pk)
            quote = renewal_quote(locked, plan, duration, offer=offer)
            on_file = payment_method_on_file(locked)
            if quote.offer_code:
                note = f"{note} · offer {quote.offer_code} (-${quote.offer_discount:.2f})".strip(" ·")
            payment = Payment.objects.create(
                member=member, amount=quote.amount, method=method, duration=duration,
                expires_at=quote.expires_at, note=note, recorded_by=recorded_by,
                method_detail=on_file.reference() if on_file and on_file.method == method else "",
            )
            if quote.offer_code:
                from marketing.models import CampaignRedemption
                from marketing.offers import redeem

                use = CampaignRedemption.Use.SIGNUP if is_signup else CampaignRedemption.Use.MEMBERSHIP
                redeem(
                    quote.offer_campaign, locked, use,
                    amount_before=quote.amount + quote.offer_discount, discount=quote.offer_discount,
                    amount_paid=quote.amount, by=recorded_by, payment=payment,
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

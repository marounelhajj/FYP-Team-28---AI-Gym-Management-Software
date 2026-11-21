from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
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


CENT = Decimal("0.01")


# User story: "As a marketing staff member, I want to create and schedule
# promotional campaigns with a target segment and offer code, so that I can
# launch promotions without needing developer help."
#
# A campaign can now carry an offer: a code (e.g. SUMMER20), what it takes
# off (a percentage or a fixed amount), what it can be used on (membership
# renewals, shop purchases, or both) and an optional cap on uses. It also
# has a target segment - which of the branch's members it's for - built
# from the member's status, plan, renewal date, last visit and join date.
#
# Nothing has to be switched on by hand: on the start date the offer is sent
# to everyone in the segment (marketing.offers.send_due, run by the same
# background thread as the reminders), the code starts working at the front
# desk and the till, and it stops working after the end date.
class MarketingCampaign(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "Percent", "Percent off"
        FIXED = "Fixed", "Amount off"

    class AppliesTo(models.TextChoices):
        MEMBERSHIP = "Membership", "Membership renewals"
        SHOP = "Shop", "Shop purchases"
        BOTH = "Both", "Renewals and shop purchases"

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

    # --- The offer (all empty for a campaign without one, e.g. brand ads) ---
    # Stored in capitals; looked up case-insensitively. Two campaigns may only
    # share a code if their dates don't overlap (checked by the serializer).
    offer_code = models.CharField(max_length=20, blank=True, db_index=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, blank=True)
    discount_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    applies_to = models.CharField(max_length=12, choices=AppliesTo.choices, blank=True)
    # Total uses across all members (first come, first served); null = no cap.
    # Each member can use a code once either way.
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    # Marketing's own words, sent above the code and its terms.
    offer_message = models.CharField(max_length=400, blank=True)
    # Send the offer to the segment (in the app, and by email to those who
    # get emails) when the campaign starts. Off = the code is shared some
    # other way (flyers, social media) but still only works for the segment.
    notify_audience = models.BooleanField(default=True)
    # When the offer first went out (null until then).
    launched_at = models.DateTimeField(null=True, blank=True)

    # --- The target segment: the campaign branch's members who match ALL of
    # these. Lists hold Member.Status values / plan names; no plans = any plan.
    segment_statuses = models.JSONField(default=list, blank=True)
    segment_plans = models.JSONField(default=list, blank=True)
    # Active members whose membership renews in the next N days.
    segment_renewal_within_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Members who haven't been in for N days (no allowed check-in).
    segment_inactive_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Members who joined in the last N days.
    segment_joined_within_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "id"]

    @property
    def has_offer(self):
        return bool(self.offer_code)

    def is_running(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self.is_active and self.start_date <= on_date <= self.end_date

    # The offer and its audience can't change once members may have been
    # told about it or used it.
    @property
    def offer_locked(self):
        return self.launched_at is not None or self.start_date <= timezone.localdate() or not self.is_active

    # A sign-up's first payment is still a membership transaction - a
    # Membership (or Both) offer covers it the same as a renewal does.
    def covers(self, use):
        if use == CampaignRedemption.Use.SIGNUP:
            use = CampaignRedemption.Use.MEMBERSHIP
        return self.applies_to in (use, self.AppliesTo.BOTH)

    # What the code takes off `amount` - never more than the amount itself.
    def discount_on(self, amount):
        amount = Decimal(amount)
        if self.discount_type == self.DiscountType.PERCENT:
            off = (amount * Decimal(self.discount_value) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            off = Decimal(self.discount_value).quantize(CENT)
        return min(off, amount)

    @property
    def discount_label(self):
        if not self.has_offer:
            return ""
        value = Decimal(self.discount_value)
        if self.discount_type == self.DiscountType.PERCENT:
            return f"{value.normalize():f}% off"
        return f"${value:.2f} off"

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


# One row per member the offer was sent to - so nobody gets it twice, however
# often the launch job runs (even two at once: the pair is unique), and so a
# member who was sent the code can still use it after they stop matching the
# segment (e.g. a "hasn't been in for 30 days" member who comes back in).
class CampaignRecipient(models.Model):
    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.CASCADE, related_name="recipients")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="campaign_offers")
    sent_at = models.DateTimeField(default=timezone.now)
    # False when they only got it in the app (no email, or emails turned off).
    by_email = models.BooleanField(default=False)

    class Meta:
        ordering = ["-sent_at", "id"]
        constraints = [models.UniqueConstraint(fields=["campaign", "member"], name="campaign_recipient_once")]


# One use of an offer code: on a membership payment or on a shop sale. A
# voided sale gives the use back (voided_at set) so the member can use the
# code again - the constraint only counts uses that still stand.
class CampaignRedemption(models.Model):
    class Use(models.TextChoices):
        MEMBERSHIP = "Membership", "Membership renewal"
        SHOP = "Shop", "Shop purchase"
        # A brand new member's first payment, not an existing member's
        # renewal - counted separately everywhere (marketing.offers.results,
        # the campaign screens) so a campaign's new-customer sign-ups and its
        # existing-member engagement don't get blended into one number.
        SIGNUP = "Signup", "New member sign-up"

    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.PROTECT, related_name="redemptions")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="offer_redemptions")
    use = models.CharField(max_length=12, choices=Use.choices)
    payment = models.OneToOneField(
        "billing.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="offer_redemption",
    )
    sale = models.OneToOneField(
        "retail.Sale", on_delete=models.SET_NULL, null=True, blank=True, related_name="offer_redemption",
    )
    # The price before the code, what it took off, and what was charged.
    amount_before = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    redeemed_at = models.DateTimeField(default=timezone.now)
    redeemed_by = models.ForeignKey(
        StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-redeemed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "member"], condition=Q(voided_at__isnull=True), name="offer_used_once_per_member",
            ),
        ]

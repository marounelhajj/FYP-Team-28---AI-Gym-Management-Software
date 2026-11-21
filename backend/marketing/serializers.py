from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from members.models import Member

from . import offers
from .models import MarketingCampaign

# Model field -> the API name an error about it is reported under.
API_NAMES = {
    "branch": "branch", "start_date": "startDate", "end_date": "endDate",
    "offer_code": "offerCode", "discount_type": "discountType", "discount_value": "discountValue",
    "applies_to": "appliesTo", "max_redemptions": "maxRedemptions", "offer_message": "offerMessage",
    "notify_audience": "notifyAudience", "segment_statuses": "segment", "segment_plans": "segment",
    "segment_renewal_within_days": "segment", "segment_inactive_days": "segment",
    "segment_joined_within_days": "segment",
}
OFFER_FIELDS = ("offer_code", "discount_type", "discount_value", "applies_to", "offer_message", "notify_audience")
SEGMENT_FIELDS = (
    "segment_statuses", "segment_plans", "segment_renewal_within_days", "segment_inactive_days",
    "segment_joined_within_days",
)
# What can't change once a campaign has started (or been cancelled): members
# may already have the code and its terms, and the audience it was sent to.
LOCKED_FIELDS = ("branch", "start_date") + OFFER_FIELDS + SEGMENT_FIELDS
MAX_PERCENT = Decimal("100")
MAX_FIXED = Decimal("1000")


def segment_data(campaign):
    return {
        "statuses": campaign.segment_statuses or list(offers.DEFAULT_STATUSES),
        "plans": campaign.segment_plans or [],
        "renewalWithinDays": campaign.segment_renewal_within_days,
        "inactiveDays": campaign.segment_inactive_days,
        "joinedWithinDays": campaign.segment_joined_within_days,
        "description": offers.describe_segment(campaign),
    }


class MarketingCampaignSerializer(serializers.ModelSerializer):
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    amountSpent = serializers.DecimalField(source="amount_spent", max_digits=10, decimal_places=2)
    isActive = serializers.BooleanField(source="is_active")
    status = serializers.CharField(read_only=True)
    createdBy = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    offerCode = serializers.CharField(source="offer_code")
    discountType = serializers.CharField(source="discount_type")
    discountValue = serializers.DecimalField(source="discount_value", max_digits=8, decimal_places=2, allow_null=True)
    discountLabel = serializers.CharField(source="discount_label", read_only=True)
    appliesTo = serializers.CharField(source="applies_to")
    maxRedemptions = serializers.IntegerField(source="max_redemptions", allow_null=True)
    offerMessage = serializers.CharField(source="offer_message")
    notifyAudience = serializers.BooleanField(source="notify_audience")
    launchedAt = serializers.SerializerMethodField()
    offerLocked = serializers.BooleanField(source="offer_locked", read_only=True)
    segment = serializers.SerializerMethodField()
    # Filled by the views from offers.results() (context["results"]).
    results = serializers.SerializerMethodField()

    class Meta:
        model = MarketingCampaign
        fields = [
            "id", "branch", "name", "strategy", "budget", "amountSpent",
            "startDate", "endDate", "isActive", "status", "createdBy",
            "offerCode", "discountType", "discountValue", "discountLabel", "appliesTo", "maxRedemptions",
            "offerMessage", "notifyAudience", "launchedAt", "offerLocked", "segment", "results",
        ]

    def get_launchedAt(self, obj):
        return timezone.localtime(obj.launched_at).strftime("%Y-%m-%d %H:%M") if obj.launched_at else None

    def get_segment(self, obj):
        return segment_data(obj)

    def get_results(self, obj):
        found = self.context.get("results")
        if found is None:
            found = offers.results([obj.id])
        return found.get(obj.id)


class SegmentSerializer(serializers.Serializer):
    statuses = serializers.ListField(
        child=serializers.ChoiceField(choices=Member.Status.choices), allow_empty=False, required=False,
        error_messages={"empty": "Pick at least one kind of member."},
    )
    plans = serializers.ListField(child=serializers.CharField(max_length=60), required=False)
    renewalWithinDays = serializers.IntegerField(min_value=1, max_value=90, required=False, allow_null=True)
    inactiveDays = serializers.IntegerField(min_value=7, max_value=365, required=False, allow_null=True)
    joinedWithinDays = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    def validate_statuses(self, value):
        return [s for s in Member.Status.values if s in value]

    def validate_plans(self, value):
        from plans.models import MembershipPlan

        names = {name.lower(): name for name in MembershipPlan.objects.values_list("name", flat=True)}
        chosen = []
        for raw in value:
            name = names.get(" ".join(raw.split()).lower())
            if name is None:
                raise serializers.ValidationError(f'There\'s no "{raw}" plan.')
            if name not in chosen:
                chosen.append(name)
        return chosen

    def validate(self, attrs):
        statuses = attrs.get("statuses") or list(offers.DEFAULT_STATUSES)
        if attrs.get("renewalWithinDays") and Member.Status.ACTIVE not in statuses:
            raise serializers.ValidationError({
                "renewalWithinDays": ["Only active members have a renewal coming up - include Active members."],
            })
        return attrs


# Used by POST /api/marketing/campaigns and PATCH /api/marketing/campaigns/<id>.
# Cancelling a campaign is PATCH { isActive: false }, same convention as
# plans.BranchPromotionWriteSerializer.
class MarketingCampaignWriteSerializer(serializers.ModelSerializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    budget = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    amountSpent = serializers.DecimalField(
        source="amount_spent", max_digits=10, decimal_places=2, min_value=0, required=False,
    )
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    isActive = serializers.BooleanField(source="is_active", required=False)
    # Blank = a campaign without an offer (e.g. brand awareness ads).
    offerCode = serializers.CharField(source="offer_code", max_length=40, required=False, allow_blank=True)
    discountType = serializers.ChoiceField(
        source="discount_type", choices=MarketingCampaign.DiscountType.choices, required=False, allow_blank=True,
    )
    discountValue = serializers.DecimalField(
        source="discount_value", max_digits=8, decimal_places=2, required=False, allow_null=True,
    )
    appliesTo = serializers.ChoiceField(
        source="applies_to", choices=MarketingCampaign.AppliesTo.choices, required=False, allow_blank=True,
    )
    maxRedemptions = serializers.IntegerField(
        source="max_redemptions", min_value=1, max_value=100000, required=False, allow_null=True,
    )
    offerMessage = serializers.CharField(source="offer_message", max_length=400, required=False, allow_blank=True)
    notifyAudience = serializers.BooleanField(source="notify_audience", required=False)
    segment = SegmentSerializer(required=False)

    class Meta:
        model = MarketingCampaign
        fields = [
            "branch", "name", "strategy", "budget", "amountSpent", "startDate", "endDate", "isActive",
            "offerCode", "discountType", "discountValue", "appliesTo", "maxRedemptions", "offerMessage",
            "notifyAudience", "segment",
        ]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Campaign name is required.")
        return value

    def validate_offerCode(self, value):
        code = offers.normalize_code(value)
        if code and not offers.CODE_PATTERN.match(code):
            raise serializers.ValidationError("Use 3 to 20 letters, numbers or dashes, e.g. SUMMER20.")
        return code

    def validate_offerMessage(self, value):
        return " ".join(value.split())

    def validate(self, attrs):
        instance = self.instance
        segment = attrs.pop("segment", None)
        if segment is not None:
            attrs["segment_statuses"] = segment.get("statuses") or list(offers.DEFAULT_STATUSES)
            attrs["segment_plans"] = segment.get("plans", [])
            attrs["segment_renewal_within_days"] = segment.get("renewalWithinDays")
            attrs["segment_inactive_days"] = segment.get("inactiveDays")
            attrs["segment_joined_within_days"] = segment.get("joinedWithinDays")

        # On PATCH only some fields are sent - fill the rest from the
        # existing campaign so every check below sees the whole campaign.
        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field, default) if instance else default

        # Sent with a new value (the edit form sends every field back).
        def changed(field):
            return field in attrs and (instance is None or attrs[field] != getattr(instance, field))

        start_date = current("start_date")
        end_date = current("end_date")
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"endDate": ["End date can't be before the start date."]})

        if instance is not None:
            self._check_locked(instance, attrs)

        today = timezone.localdate()
        code = current("offer_code", "")
        if not code:
            # No offer: nothing about one is kept.
            if instance is None or "offer_code" in attrs:
                attrs.update(discount_type="", discount_value=None, applies_to="", max_redemptions=None, offer_message="")
            return attrs

        errors = {}
        discount_type = current("discount_type", "")
        value = current("discount_value")
        if not discount_type:
            errors["discountType"] = ["Choose a percentage or an amount off."]
        if value is None or value <= 0:
            errors["discountValue"] = ["Enter how much the code takes off."]
        elif discount_type == MarketingCampaign.DiscountType.PERCENT and value > MAX_PERCENT:
            errors["discountValue"] = ["A percentage can't be more than 100."]
        elif discount_type == MarketingCampaign.DiscountType.FIXED and value > MAX_FIXED:
            errors["discountValue"] = [f"An amount off can be at most ${MAX_FIXED:.0f}."]
        if not current("applies_to", ""):
            errors["appliesTo"] = ["Choose what the code can be used on."]

        # A new offer, or a scheduled one being moved, can't be in the past.
        if instance is None or not instance.offer_locked:
            if changed("start_date") and start_date < today:
                errors["startDate"] = ["An offer can't start in the past - start it today or later."]
        if changed("end_date") and end_date < today:
            errors["endDate"] = ["An offer can't end in the past." if instance is None or not instance.offer_locked
                                 else "To stop the offer now, cancel the campaign."]

        if changed("offer_code") or changed("start_date") or changed("end_date"):
            clash = MarketingCampaign.objects.filter(
                offer_code=code, is_active=True, start_date__lte=end_date, end_date__gte=start_date,
            )
            if instance is not None:
                clash = clash.exclude(pk=instance.pk)
            clash = clash.first()
            if clash:
                errors["offerCode"] = [
                    f'{code} is already used by "{clash.name}" at {clash.branch} '
                    f"({offers._day(clash.start_date)} to {offers._day(clash.end_date)}). Pick another code or other dates."
                ]

        cap = current("max_redemptions")
        if instance is not None and cap is not None and changed("max_redemptions"):
            used = instance.redemptions.filter(voided_at__isnull=True).count()
            if cap < used:
                errors["maxRedemptions"] = [f"It's been used {used} times already - the limit can't go below that."]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _check_locked(self, instance, attrs):
        if not instance.is_active and attrs.get("is_active") is True:
            raise serializers.ValidationError({"isActive": ["A cancelled campaign can't be restarted - start a new one."]})
        if not instance.offer_locked:
            return
        changed = [f for f in LOCKED_FIELDS if f in attrs and attrs[f] != getattr(instance, f)]
        if not changed:
            return
        if not instance.has_offer:
            # A campaign without an offer (e.g. ads) can still be re-dated as
            # before - it just can't be given an offer once it's under way.
            if attrs.get("offer_code"):
                raise serializers.ValidationError({"offerCode": [
                    "An offer can only be added before a campaign starts - start a new campaign for it.",
                ]})
            return
        if not instance.is_active:
            why = "This campaign was cancelled"
        elif instance.status == "Expired":
            why = "This campaign has ended"
        else:
            why = "This campaign has already started"
        raise serializers.ValidationError({
            API_NAMES[changed[0]]: [
                f"{why}, so its branch, start date, offer and audience can't change. "
                "Start a new campaign for a different offer."
            ],
        })


# POST /api/marketing/audience - the audience a segment would reach, before
# the campaign is saved.
class AudiencePreviewSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    segment = SegmentSerializer(required=False)

from decimal import Decimal

from rest_framework import serializers

from members.models import Member

from .models import BranchPromotion, MembershipPlan


class MembershipPlanSerializer(serializers.ModelSerializer):
    billingCycle = serializers.CharField(source="billing_cycle")
    monthlyEquivalent = serializers.DecimalField(
        source="monthly_equivalent", max_digits=8, decimal_places=2, read_only=True
    )
    maxPromoDiscountPercent = serializers.DecimalField(
        source="max_promo_discount_percent", max_digits=5, decimal_places=2
    )
    isActive = serializers.BooleanField(source="is_active")
    updatedAt = serializers.DateTimeField(source="updated_at", format="%Y-%m-%d", read_only=True)

    class Meta:
        model = MembershipPlan
        fields = [
            "id", "name", "description", "price", "billingCycle", "monthlyEquivalent",
            "features", "maxPromoDiscountPercent", "isActive", "updatedAt",
        ]


# Used by POST /api/plans and PATCH /api/plans/<id>.
#
# User story: "As a general manager, I want to set organization-wide
# membership plans and pricing tiers, so that pricing stays consistent
# across branches while still allowing local promotions."
#
# maxPromoDiscountPercent is the guardrail on "local promotions": no branch
# promotion can take more than this percentage off the plan's price.
# Archiving / restoring a plan is just PATCH { isActive: false / true }.
class MembershipPlanWriteSerializer(serializers.ModelSerializer):
    billingCycle = serializers.ChoiceField(
        source="billing_cycle", choices=MembershipPlan.BillingCycle.choices, required=False
    )
    isActive = serializers.BooleanField(source="is_active", required=False)
    price = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0)
    features = serializers.JSONField(required=False)
    maxPromoDiscountPercent = serializers.DecimalField(
        source="max_promo_discount_percent", max_digits=5, decimal_places=2,
        min_value=0, max_value=100, required=False,
    )

    class Meta:
        model = MembershipPlan
        fields = ["name", "description", "price", "billingCycle", "features", "maxPromoDiscountPercent", "isActive"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Plan name is required.")
        # Case-insensitive uniqueness, so "Premium" and "premium" can't
        # both exist as separate tiers.
        clash = MembershipPlan.objects.filter(name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f'A plan named "{value}" already exists.')
        return value

    def validate_features(self, value):
        if not isinstance(value, list) or not all(isinstance(f, str) for f in value):
            raise serializers.ValidationError("features must be a list of strings.")
        return [f.strip() for f in value if f.strip()]


class BranchPromotionSerializer(serializers.ModelSerializer):
    planId = serializers.IntegerField(source="plan_id", read_only=True)
    planName = serializers.CharField(source="plan.name", read_only=True)
    basePrice = serializers.DecimalField(source="plan.price", max_digits=8, decimal_places=2, read_only=True)
    discountType = serializers.CharField(source="discount_type")
    discountValue = serializers.DecimalField(source="discount_value", max_digits=8, decimal_places=2)
    discountAmount = serializers.SerializerMethodField()
    effectivePrice = serializers.SerializerMethodField()
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    isActive = serializers.BooleanField(source="is_active")
    status = serializers.CharField(read_only=True)
    createdBy = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model = BranchPromotion
        fields = [
            "id", "planId", "planName", "branch", "name", "basePrice", "discountType",
            "discountValue", "discountAmount", "effectivePrice", "startDate", "endDate",
            "isActive", "status", "createdBy",
        ]

    def get_discountAmount(self, obj):
        return f"{obj.discount_amount():.2f}"

    def get_effectivePrice(self, obj):
        return f"{obj.effective_price():.2f}"


# Used by POST /api/plans/promotions and PATCH /api/plans/promotions/<id>.
#
# Enforces the "consistent across branches" half of the story: a local
# promotion may only discount (never raise) a plan's organization-wide
# price, and never by more than the plan's maxPromoDiscountPercent.
# Cancelling a promotion is PATCH { isActive: false }.
class BranchPromotionWriteSerializer(serializers.ModelSerializer):
    planId = serializers.PrimaryKeyRelatedField(source="plan", queryset=MembershipPlan.objects.all())
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    discountType = serializers.ChoiceField(
        source="discount_type", choices=BranchPromotion.DiscountType.choices, required=False
    )
    discountValue = serializers.DecimalField(
        source="discount_value", max_digits=8, decimal_places=2, min_value=Decimal("0.01")
    )
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    isActive = serializers.BooleanField(source="is_active", required=False)

    class Meta:
        model = BranchPromotion
        fields = ["planId", "branch", "name", "discountType", "discountValue", "startDate", "endDate", "isActive"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Promotion name is required.")
        return value

    def validate(self, attrs):
        # On PATCH only some fields are sent - fill the rest from the
        # existing promotion so cross-field checks still see the full picture.
        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default) if self.instance else default

        plan = current("plan")
        discount_type = current("discount_type", BranchPromotion.DiscountType.PERCENT)
        discount_value = current("discount_value")
        start_date = current("start_date")
        end_date = current("end_date")

        if self.instance is None and not plan.is_active:
            raise serializers.ValidationError({"planId": ["Can't promote an archived plan."]})

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"endDate": ["End date can't be before the start date."]})

        price = Decimal(plan.price)
        cap_percent = Decimal(plan.max_promo_discount_percent)
        if discount_type == BranchPromotion.DiscountType.PERCENT:
            requested_percent = Decimal(discount_value)
        else:
            requested_percent = (Decimal(discount_value) / price * 100) if price else Decimal("100")

        if requested_percent > cap_percent:
            raise serializers.ValidationError({"discountValue": [
                f"{plan.name} allows branch discounts of up to {cap_percent.normalize():f}% "
                f"(${plan.max_promo_discount_amount}). Ask the general manager to raise the cap."
            ]})

        return attrs

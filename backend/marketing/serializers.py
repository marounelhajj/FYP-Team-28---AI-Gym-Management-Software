from decimal import Decimal

from rest_framework import serializers

from members.models import Member

from .models import MarketingCampaign


class MarketingCampaignSerializer(serializers.ModelSerializer):
    startDate = serializers.DateField(source="start_date")
    endDate = serializers.DateField(source="end_date")
    amountSpent = serializers.DecimalField(source="amount_spent", max_digits=10, decimal_places=2)
    isActive = serializers.BooleanField(source="is_active")
    status = serializers.CharField(read_only=True)
    createdBy = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model = MarketingCampaign
        fields = [
            "id", "branch", "name", "strategy", "budget", "amountSpent",
            "startDate", "endDate", "isActive", "status", "createdBy",
        ]


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

    class Meta:
        model = MarketingCampaign
        fields = ["branch", "name", "strategy", "budget", "amountSpent", "startDate", "endDate", "isActive"]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Campaign name is required.")
        return value

    def validate(self, attrs):
        # On PATCH only some fields are sent - fill the rest from the
        # existing campaign so the date-order check still sees both ends.
        def current(field, default=None):
            if field in attrs:
                return attrs[field]
            return getattr(self.instance, field, default) if self.instance else default

        start_date = current("start_date")
        end_date = current("end_date")
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"endDate": ["End date can't be before the start date."]})
        return attrs

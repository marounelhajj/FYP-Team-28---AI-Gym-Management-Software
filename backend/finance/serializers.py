from django.utils import timezone
from rest_framework import serializers

from members.models import Member

from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    incurredOn = serializers.DateField(source="incurred_on", format="%Y-%m-%d")
    recordedBy = serializers.CharField(source="recorded_by.full_name", default=None)
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d %H:%M")

    class Meta:
        model = Expense
        fields = ["id", "branch", "category", "amount", "incurredOn", "note", "recordedBy", "createdAt"]


# POST /api/finance/expenses. incurredOn defaults to today when left out -
# amount is the only thing that really has to be typed in by hand.
class ExpenseWriteSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    category = serializers.ChoiceField(choices=Expense.Category.choices)
    amount = serializers.DecimalField(max_digits=8, decimal_places=2)
    incurredOn = serializers.DateField(source="incurred_on", required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate(self, attrs):
        attrs.setdefault("incurred_on", timezone.localdate())
        attrs.setdefault("note", "")
        return attrs

from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from members.models import Member

MAX_LINES = 50


def _cost(required=True):
    return serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("10000"),
        required=required, allow_null=not required,
    )


# POST /api/purchasing/suppliers and PATCH /api/purchasing/suppliers/<id>
class SupplierSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    contactName = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    email = serializers.EmailField(error_messages={"invalid": "Enter the email purchase orders should go to."})
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, trim_whitespace=True)
    supplies = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=True)
    leadTimeDays = serializers.IntegerField(min_value=0, max_value=90, required=False)
    active = serializers.BooleanField(required=False)


# PATCH /api/purchasing/products/<id>/sourcing
class SourcingSerializer(serializers.Serializer):
    supplierId = serializers.IntegerField(required=False, allow_null=True)
    unitCost = _cost(required=False)
    reorderLevel = serializers.IntegerField(min_value=0, max_value=10000, required=False)


class LineSerializer(serializers.Serializer):
    productId = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)
    unitCost = _cost(required=False)

    def validate(self, attrs):
        if not attrs.get("productId") and len(" ".join((attrs.get("description") or "").split())) < 2:
            raise serializers.ValidationError({"description": ["Say what you need, e.g. \"Disinfectant spray 5 L\"."]})
        return attrs


# POST /api/purchasing/orders
class OrderSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices, required=False)
    supplierId = serializers.IntegerField()
    neededBy = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
    lines = LineSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one item.")
        if len(value) > MAX_LINES:
            raise serializers.ValidationError(f"Up to {MAX_LINES} items per order - split it into two.")
        products = [line["productId"] for line in value if line.get("productId")]
        if len(products) != len(set(products)):
            raise serializers.ValidationError("A product is listed twice - put it on one line.")
        return value

    def validate_neededBy(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("That date has passed.")
        return value


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class ReceiveSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField(), allow_empty=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=True)

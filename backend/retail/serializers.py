from collections import Counter
from decimal import Decimal

from rest_framework import serializers

from members.models import Member

from .models import Product, Sale, SaleItem

DATETIME = "%Y-%m-%d %H:%M"
MAX_QUANTITY = 99


class ProductSerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active")
    # {branch: quantity on the shelf}, every branch listed.
    stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "category", "price", "isActive", "stock"]

    def get_stock(self, obj):
        counts = {row.branch: row.quantity for row in obj.stock.all()}
        return {branch: counts.get(branch, 0) for branch in Member.Branch.values}


# POST /api/retail/products (all fields) and PATCH /api/retail/products/<id> (any).
class ProductWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    category = serializers.ChoiceField(choices=Product.Category.choices)
    price = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"))
    isActive = serializers.BooleanField(required=False)

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Give the product a name.")
        taken = Product.objects.filter(name__iexact=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("There's already a product with this name.")
        return value


# POST /api/retail/products/<id>/stock - a delivery (+) or a correction (-).
class StockChangeSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    change = serializers.IntegerField(min_value=-999, max_value=999)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate_change(self, value):
        if value == 0:
            raise serializers.ValidationError("Enter how many units arrived (or were removed).")
        return value


class SaleItemInputSerializer(serializers.Serializer):
    productId = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)


# POST /api/retail/sales. Only product IDs and quantities come from the till:
# prices are always the catalog's, never the client's.
class SaleCreateSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices, required=False)
    items = SaleItemInputSerializer(many=True, allow_empty=False)
    paymentMethod = serializers.ChoiceField(choices=Sale.PaymentMethod.choices)
    amountTendered = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    memberId = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    # The total the receptionist showed the customer; a mismatch means a price changed.
    expectedTotal = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)

    def validate_items(self, value):
        quantities = Counter()
        for line in value:
            quantities[line["productId"]] += line["quantity"]
        if any(quantity > MAX_QUANTITY for quantity in quantities.values()):
            raise serializers.ValidationError(f"At most {MAX_QUANTITY} of one product per sale.")
        return dict(quantities)

    def validate_memberId(self, value):
        if value is not None and not Member.objects.filter(id=value).exists():
            raise serializers.ValidationError(f"No member found with ID {value}.")
        return value


class SaleItemSerializer(serializers.ModelSerializer):
    productId = serializers.IntegerField(source="product_id")
    productName = serializers.CharField(source="product_name")
    unitPrice = serializers.DecimalField(source="unit_price", max_digits=8, decimal_places=2)
    lineTotal = serializers.DecimalField(source="line_total", max_digits=10, decimal_places=2)

    class Meta:
        model = SaleItem
        fields = ["productId", "productName", "unitPrice", "quantity", "lineTotal"]


class SaleSerializer(serializers.ModelSerializer):
    memberId = serializers.IntegerField(source="member_id", allow_null=True)
    memberName = serializers.CharField(source="member.name", default=None)
    paymentMethod = serializers.CharField(source="payment_method")
    amountTendered = serializers.DecimalField(source="amount_tendered", max_digits=10, decimal_places=2, allow_null=True)
    changeDue = serializers.DecimalField(source="change_due", max_digits=10, decimal_places=2, allow_null=True)
    soldBy = serializers.CharField(source="sold_by.full_name", default=None)
    soldAt = serializers.DateTimeField(source="sold_at", format=DATETIME)
    voided = serializers.SerializerMethodField()
    voidedAt = serializers.DateTimeField(source="voided_at", format=DATETIME, allow_null=True)
    voidedBy = serializers.CharField(source="voided_by.full_name", default=None)
    voidReason = serializers.CharField(source="void_reason")
    items = SaleItemSerializer(many=True)

    class Meta:
        model = Sale
        fields = [
            "id", "branch", "memberId", "memberName", "paymentMethod", "total", "amountTendered", "changeDue",
            "soldBy", "soldAt", "voided", "voidedAt", "voidedBy", "voidReason", "items",
        ]

    def get_voided(self, obj):
        return obj.voided_at is not None


class VoidSaleSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)

    def validate_reason(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Say why the sale is being voided.")
        return value

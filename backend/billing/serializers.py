import re

from django.utils import timezone
from rest_framework import serializers

from .models import Payment, PaymentMethod

LAST4 = re.compile(r"^\d{4}$")


class PaymentSerializer(serializers.ModelSerializer):
    paidAt = serializers.DateTimeField(source="paid_at", format="%Y-%m-%d %H:%M")
    expiresAt = serializers.DateField(source="expires_at", format="%Y-%m-%d")
    methodDetail = serializers.CharField(source="method_detail")
    recordedBy = serializers.CharField(source="recorded_by.full_name", default=None)

    class Meta:
        model = Payment
        fields = ["id", "amount", "method", "methodDetail", "duration", "paidAt", "expiresAt", "note", "recordedBy"]


class PaymentMethodSerializer(serializers.ModelSerializer):
    cardHolderName = serializers.CharField(source="card_holder_name")
    cardLast4 = serializers.CharField(source="card_last4")
    cardExpiryMonth = serializers.IntegerField(source="card_expiry_month")
    cardExpiryYear = serializers.IntegerField(source="card_expiry_year")
    bankName = serializers.CharField(source="bank_name")
    bankAccountLast4 = serializers.CharField(source="bank_account_last4")
    summary = serializers.SerializerMethodField()
    cardExpired = serializers.SerializerMethodField()
    cardExpiresBeforeRenewal = serializers.SerializerMethodField()
    updatedAt = serializers.DateTimeField(source="updated_at", format="%Y-%m-%d %H:%M")
    updatedBy = serializers.CharField(source="updated_by.full_name", default=None)

    class Meta:
        model = PaymentMethod
        fields = [
            "method", "cardHolderName", "cardLast4", "cardExpiryMonth", "cardExpiryYear",
            "bankName", "bankAccountLast4", "summary", "cardExpired", "cardExpiresBeforeRenewal",
            "updatedAt", "updatedBy",
        ]

    def get_summary(self, obj):
        if obj.card_valid_through():
            return f"{obj.reference()} (exp {obj.card_expiry_month:02d}/{obj.card_expiry_year})"
        return obj.reference() or obj.method

    def get_cardExpired(self, obj):
        return obj.card_expired()

    # Still valid today, but it won't be by the time the next renewal is due.
    def get_cardExpiresBeforeRenewal(self, obj):
        valid_through = obj.card_valid_through()
        renewal_due = obj.member.subscription_expires_at
        return bool(valid_through and renewal_due and not obj.card_expired() and valid_through < renewal_due)


# PUT /api/members/<id>/payment-method. Only the details for the chosen
# method are kept; the other method's details are cleared.
class PaymentMethodWriteSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    cardHolderName = serializers.CharField(max_length=150, required=False, allow_blank=True)
    cardLast4 = serializers.CharField(required=False, allow_blank=True)
    cardExpiryMonth = serializers.IntegerField(required=False, allow_null=True)
    cardExpiryYear = serializers.IntegerField(required=False, allow_null=True)
    bankName = serializers.CharField(max_length=100, required=False, allow_blank=True)
    bankAccountLast4 = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        method = attrs["method"]
        details = {
            "method": method, "card_holder_name": "", "card_last4": "", "card_expiry_month": None,
            "card_expiry_year": None, "bank_name": "", "bank_account_last4": "",
        }
        errors = {}

        if method == Payment.Method.CARD:
            name = " ".join(attrs.get("cardHolderName", "").split())
            last4 = attrs.get("cardLast4", "").strip()
            month = attrs.get("cardExpiryMonth")
            year = attrs.get("cardExpiryYear")
            if not name:
                errors["cardHolderName"] = ["Enter the name on the card."]
            if not LAST4.match(last4):
                errors["cardLast4"] = ["Enter only the last 4 digits of the card, never the full number."]
            if month is None or not 1 <= month <= 12:
                errors["cardExpiryMonth"] = ["Choose the card's expiry month."]
            if year is None or not 2000 <= year <= 2100:
                errors["cardExpiryYear"] = ["Choose the card's expiry year."]
            elif month is not None and 1 <= month <= 12:
                today = timezone.localdate()
                if (year, month) < (today.year, today.month):
                    errors["cardExpiryYear"] = ["This card has expired. Ask the member for a current card."]
            details.update(card_holder_name=name, card_last4=last4, card_expiry_month=month, card_expiry_year=year)

        elif method == Payment.Method.BANK_TRANSFER:
            bank = " ".join(attrs.get("bankName", "").split())
            last4 = attrs.get("bankAccountLast4", "").strip()
            if not bank:
                errors["bankName"] = ["Enter the member's bank."]
            if not LAST4.match(last4):
                errors["bankAccountLast4"] = ["Enter the last 4 digits of the account or IBAN."]
            details.update(bank_name=bank, bank_account_last4=last4)

        if errors:
            raise serializers.ValidationError(errors)
        return details


class RenewalQuoteSerializer(serializers.Serializer):
    membershipPlan = serializers.CharField()
    duration = serializers.ChoiceField(choices=Payment.Duration.choices)

    def validate_membershipPlan(self, value):
        from members.serializers import validate_active_plan_name

        return validate_active_plan_name(value)


# POST /api/members/<id>/payments - renews (or reactivates) an existing
# member. Never takes an amount: it's always renewal_quote()'s price.
# Context: "payment_method" = the member's PaymentMethod on file, or None.
class PaymentCreateSerializer(RenewalQuoteSerializer):
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    # The price the receptionist was shown; if it no longer matches, the
    # payment is refused instead of charging a different amount.
    expectedAmount = serializers.DecimalField(max_digits=8, decimal_places=2, required=False)

    def validate(self, attrs):
        on_file = self.context.get("payment_method")
        if attrs["method"] == Payment.Method.CARD and on_file and on_file.card_expired():
            raise serializers.ValidationError({"method": [
                f"The card on file expired {on_file.card_expiry_month:02d}/{on_file.card_expiry_year}. "
                "Update the payment method before charging it, or choose another method."
            ]})
        return attrs

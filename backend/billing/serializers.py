from rest_framework import serializers

from members.models import Member
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    paidAt = serializers.DateTimeField(source="paid_at", format="%Y-%m-%d %H:%M")
    expiresAt = serializers.DateField(source="expires_at", format="%Y-%m-%d")

    class Meta:
        model = Payment
        fields = ["id", "amount", "method", "duration", "paidAt", "expiresAt", "note"]


# Used by POST /api/members/<id>/payments to record a renewal payment for
# an existing member (see Payment.record()). No profile fields (the member
# already exists) and no amount (it's always price_for(membershipPlan,
# duration), never accepted from the client). membershipPlan IS required
# here, same as at registration - the receptionist explicitly picks the
# plan every time a payment is recorded, which is also how a member's plan
# can be changed at renewal (upgrade/downgrade), not just carried over.
#
# User story: "As a receptionist, I want to process a new member's first
# payment during registration, so that their membership is activated
# immediately." - extended so a lapsed/expiring member can be repaid for
# and reactivated the same way, instead of the subscription auto-renewing.
class PaymentCreateSerializer(serializers.Serializer):
    membershipPlan = serializers.ChoiceField(choices=Member.Plan.choices)
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    duration = serializers.ChoiceField(choices=Payment.Duration.choices)

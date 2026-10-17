from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from members.models import Member
from members.serializers import MemberSerializer

from .models import Payment, PaymentMethod, payment_method_on_file, renewal_quote
from .serializers import (
    PaymentCreateSerializer, PaymentMethodSerializer, PaymentMethodWriteSerializer, PaymentSerializer,
    RenewalQuoteSerializer,
)

# User story: "As a receptionist, I want to process membership renewals and update payment methods for
# existing members, so that recurring billing stays accurate for members who prefer in person help."

RECENT_PAYMENTS = 10


def _get_member(member_id):
    member = Member.objects.select_related("waiver__witnessed_by").filter(id=member_id).first()
    if member is None:
        return None, Response({"error": f"Member {member_id} not found"}, status=404)
    return member, None


def _quote_data(quote):
    return {
        "amount": f"{quote.amount:.2f}",
        "originalAmount": f"{quote.original_amount:.2f}" if quote.original_amount is not None else None,
        "promotion": quote.promotion,
        "startsOn": quote.starts_on,
        "expiresAt": quote.expires_at,
    }


# GET /api/members/<id>/billing - the member, their payment method on file, and recent payments.
@api_view(["GET"])
def member_billing(request, member_id):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied
    member, missing = _get_member(member_id)
    if missing:
        return missing

    member.refresh_expiry_status()
    on_file = payment_method_on_file(member)
    payments = member.payments.select_related("recorded_by")
    return Response({
        "member": MemberSerializer(member).data,
        "paymentMethod": PaymentMethodSerializer(on_file).data if on_file else None,
        "payments": PaymentSerializer(payments[:RECENT_PAYMENTS], many=True).data,
        "paymentCount": payments.count(),
    })


# PUT /api/members/<id>/payment-method - add or replace the member's payment method on file.
@api_view(["PUT"])
def member_payment_method(request, member_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied
    member, missing = _get_member(member_id)
    if missing:
        return missing

    serializer = PaymentMethodWriteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    on_file, _ = PaymentMethod.objects.update_or_create(
        member=member, defaults={**serializer.validated_data, "updated_by": account},
    )
    return Response(PaymentMethodSerializer(on_file).data)


# GET /api/members/<id>/renewal-quote?membershipPlan=&duration= - the exact price and period before charging.
@api_view(["GET"])
def member_renewal_quote(request, member_id):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied
    member, missing = _get_member(member_id)
    if missing:
        return missing

    serializer = RenewalQuoteSerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    data = serializer.validated_data
    return Response(_quote_data(renewal_quote(member, data["membershipPlan"], data["duration"])))


# POST /api/members/<id>/payments
# Body: { membershipPlan, method, duration, expectedAmount? } - renews an
# Active member (the new period stacks on the time left) or reactivates a
# Frozen/Cancelled one (starting today). See Payment.record().
@api_view(["POST"])
def member_payment(request, member_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied
    member, missing = _get_member(member_id)
    if missing:
        return missing

    serializer = PaymentCreateSerializer(data=request.data, context={"payment_method": payment_method_on_file(member)})
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data

    expected = data.get("expectedAmount")
    if expected is not None:
        quote = renewal_quote(member, data["membershipPlan"], data["duration"])
        if quote.amount != expected:
            return Response({
                "error": f"The price is now ${quote.amount:.2f} - it changed since this form was opened. "
                         "Review it and confirm again.",
                "quote": _quote_data(quote),
            }, status=409)

    member.refresh_expiry_status()
    note = "Renewal" if member.status == Member.Status.ACTIVE else "Reactivation"
    payment = Payment.record(
        member, data["membershipPlan"], data["method"], data["duration"], note=note, recorded_by=account,
    )
    response_data = MemberSerializer(member).data
    response_data["payment"] = PaymentSerializer(payment).data
    return Response(response_data, status=201)

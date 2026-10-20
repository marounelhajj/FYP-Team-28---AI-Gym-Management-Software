from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
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


# Member-session counterpart of _get_member above - looks the member up
# from request.session["member_id"] (set by members.auth_views.login/signup)
# instead of a URL id, and never a staff session (separate session key, same
# separation members.auth_views already keeps between member and staff).
def _get_member_from_session(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return None, Response({"error": "Not authenticated."}, status=401)
    member = Member.objects.filter(id=member_id).first()
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


# Saves the payment method on file and audit-logs the change as the masked
# one-line summary ("Card ending 4242 (exp 09/2028)") - never the raw fields.
def _set_payment_method(request, member, actor, validated_data, updated_by):
    before = payment_method_on_file(member)
    before_summary = PaymentMethodSerializer(before).data["summary"] if before else None
    on_file, _ = PaymentMethod.objects.update_or_create(
        member=member, defaults={**validated_data, "updated_by": updated_by},
    )
    after_summary = PaymentMethodSerializer(on_file).data["summary"]
    if before_summary != after_summary:
        who = f"{member.name} changed their" if actor is member else f"Changed {member.name}'s"
        record(
            request, AuditLog.Action.PAYMENT_METHOD_UPDATED, actor=actor, target=member,
            summary=f"{who} payment method to {after_summary}",
            details={"changes": {"paymentMethod": [before_summary, after_summary]}},
        )
    return on_file


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

    on_file = _set_payment_method(request, member, account, serializer.validated_data, updated_by=account)
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
    record(
        request, AuditLog.Action.PAYMENT_RECORDED, actor=account, target=member,
        summary=f"{note}: {member.name} paid ${payment.amount:.2f} by {payment.method} "
                f"for {member.membership_plan} (valid until {payment.expires_at})",
        details={"type": note, "plan": member.membership_plan, "amount": f"{payment.amount:.2f}",
                 "method": payment.method, "duration": payment.duration, "expiresAt": str(payment.expires_at)},
    )
    response_data = MemberSerializer(member).data
    response_data["payment"] = PaymentSerializer(payment).data
    return Response(response_data, status=201)


# GET /api/members/me/payment-method - the logged-in member's own payment method on file.
# PUT /api/members/me/payment-method - add or replace it themselves.
#
# User story: "As a member, I want to update my saved payment method and
# personal profile information myself in the app, so that I don't need to
# visit the front desk for routine changes." Self-service counterpart to
# member_payment_method above: same model and serializers, but
# authenticated by the member's own session instead of a staff permission,
# and updated_by is left null (no staff member performed this edit).
@api_view(["GET", "PUT"])
def my_payment_method(request):
    member, denied = _get_member_from_session(request)
    if denied:
        return denied

    if request.method == "GET":
        on_file = payment_method_on_file(member)
        # Wrapped (not a bare Response(None)) because DRF's JSONRenderer
        # turns a top-level None into an EMPTY body, not JSON "null" - which
        # breaks response.json() on both the test client and fetch() in the
        # browser. member_billing above avoids this the same way, nesting
        # paymentMethod inside a dict instead of returning it bare.
        return Response({"paymentMethod": PaymentMethodSerializer(on_file).data if on_file else None})

    serializer = PaymentMethodWriteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    on_file = _set_payment_method(request, member, member, serializer.validated_data, updated_by=None)
    return Response(PaymentMethodSerializer(on_file).data)


# GET /api/members/me/billing - the logged-in member's own recent payments.
#
# User story: "As a member, I want to view my membership details and
# billing history, so that I can track payments and my renewal date."
# Membership details (plan, status, renewal date) are already available
# from GET /api/members/me (MemberSerializer already includes
# subscriptionExpiresAt) - this adds the one piece that wasn't exposed to
# members yet: payment history. Self-service counterpart to member_billing
# above, scoped by session instead of a staff permission; same
# RECENT_PAYMENTS limit and PaymentSerializer so the shape matches what
# the receptionist sees.
@api_view(["GET"])
def my_billing(request):
    member, denied = _get_member_from_session(request)
    if denied:
        return denied

    payments = member.payments.select_related("recorded_by")
    return Response({
        "payments": PaymentSerializer(payments[:RECENT_PAYMENTS], many=True).data,
        "paymentCount": payments.count(),
    })

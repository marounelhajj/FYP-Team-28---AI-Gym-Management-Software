from django.contrib.auth.hashers import check_password
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.log import changes, record
from audit.models import AuditLog
from billing.serializers import PaymentSerializer
from . import qr
from .models import Member
from .serializers import MemberProfileUpdateSerializer, MemberSerializer, MemberSignupSerializer

# Member sign-in/sign-up. Separate session key ("member_id") from staff
# ("staff_account_id" in administration/auth_views.py) so the two account
# types can never be confused with each other, and logging in as one kind
# of account clears any session for the other.


def _session_payload(member):
    return MemberSerializer(member).data


def _profile_snapshot(member):
    return {"name": member.name, "email": member.email, "phone": member.phone}


# POST /api/members/signup
# Body: { name, email, phone, branch, membershipPlan, username, password,
#         paymentAmount, paymentMethod, paymentDuration }
# 201 + member/session payload (plus "firstPayment") on success - a
# self-signed-up member is not Active until they pay here either, same
# rule as a receptionist's walk-in registration. Also logs the new member in.
# 400 + field errors (e.g. username/email already taken) on failure.
@api_view(["POST"])
def signup(request):
    serializer = MemberSignupSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    member = serializer.save()
    payment = member.first_payment
    record(
        request, AuditLog.Action.MEMBER_SIGNED_UP, actor=member, target=member,
        summary=f"{member.name} signed up online on {member.membership_plan} (paid ${payment.amount:.2f})",
        details={"plan": member.membership_plan, "amount": f"{payment.amount:.2f}", "method": payment.method},
    )

    request.session.pop("staff_account_id", None)
    request.session["member_id"] = member.id
    data = _session_payload(member)
    data["firstPayment"] = PaymentSerializer(member.first_payment).data
    return Response(data, status=201)


# POST /api/members/login
# Body: { username, password }
# 200 + member/session payload on success.
# 401 + {"error": ...} if the username/password don't match any account -
# including members who were walk-in registered and never set a password.
@api_view(["POST"])
def login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    try:
        member = Member.objects.get(username=username)
    except Member.DoesNotExist:
        return Response({"error": "Invalid username or password."}, status=401)

    if not member.password_hash or not check_password(password, member.password_hash):
        return Response({"error": "Invalid username or password."}, status=401)

    request.session.pop("staff_account_id", None)
    request.session["member_id"] = member.id
    member.refresh_expiry_status()
    return Response(_session_payload(member))


# POST /api/members/logout
@api_view(["POST"])
def logout(request):
    request.session.flush()
    return Response({"ok": True})


# GET   /api/members/me - the logged-in member's own profile.
# PATCH /api/members/me - edit it themselves (name/email/phone only - see
#       MemberProfileUpdateSerializer).
#
# User story (PATCH): "As a member, I want to update my saved payment
# method and personal profile information myself in the app, so that I
# don't need to visit the front desk for routine changes."
@api_view(["GET", "PATCH"])
def me(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return Response({"error": "Not authenticated."}, status=401)

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        request.session.flush()
        return Response({"error": "Not authenticated."}, status=401)

    if request.method == "PATCH":
        serializer = MemberProfileUpdateSerializer(member, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        before = _profile_snapshot(member)
        member = serializer.save()
        changed = changes(before, _profile_snapshot(member))
        if changed:
            record(
                request, AuditLog.Action.MEMBER_PROFILE_UPDATED, actor=member, target=member,
                summary=f"{member.name} edited their profile ({', '.join(sorted(changed))})",
                details={"changes": changed},
            )
        return Response(_session_payload(member))

    member.refresh_expiry_status()
    return Response(_session_payload(member))


# GET /api/members/me/qr
# The logged-in member's check-in QR code (SCRUM-33), shown on their
# dashboard: { membershipId, payload, qrCode (SVG data URI) }.
@api_view(["GET"])
def my_qr(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)
    payload = qr.payload_for(member)
    return Response({"membershipId": member.id, "payload": payload, "qrCode": qr.svg_data_uri(payload)})

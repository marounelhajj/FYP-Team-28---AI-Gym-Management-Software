from django.contrib.auth.hashers import check_password
from rest_framework.decorators import api_view
from rest_framework.response import Response

from billing.serializers import PaymentSerializer
from . import qr
from .models import Member
from .serializers import MemberSerializer, MemberSignupSerializer

# Member sign-in/sign-up. Separate session key ("member_id") from staff
# ("staff_account_id" in administration/auth_views.py) so the two account
# types can never be confused with each other, and logging in as one kind
# of account clears any session for the other.


def _session_payload(member):
    return MemberSerializer(member).data


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
    return Response(_session_payload(member))


# POST /api/members/logout
@api_view(["POST"])
def logout(request):
    request.session.flush()
    return Response({"ok": True})


# GET /api/members/me
@api_view(["GET"])
def me(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return Response({"error": "Not authenticated."}, status=401)

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        request.session.flush()
        return Response({"error": "Not authenticated."}, status=401)

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

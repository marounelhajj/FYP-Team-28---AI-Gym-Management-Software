from django.contrib.auth.hashers import check_password
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.log import changes, record
from audit.models import AuditLog
from billing.serializers import PaymentSerializer
from . import qr
from .models import Member
from .serializers import MemberProfileUpdateSerializer, MemberSerializer, MemberSignupSerializer, WaiverSignatureFields
from .models import Waiver
from .waiver_records import client_ip, sign, waiver_payload

# Member sign-in/sign-up. Separate session key ("member_id") from staff
# ("staff_account_id" in administration/auth_views.py) so the two account
# types can never be confused with each other, and logging in as one kind
# of account clears any session for the other.


def _session_payload(member):
    return MemberSerializer(member).data


def _profile_snapshot(member):
    return {
        "name": member.name, "email": member.email, "phone": member.phone,
        "dateOfBirth": member.date_of_birth.isoformat() if member.date_of_birth else None,
    }


# POST /api/members/signup
# Body: { name, email, phone, branch, membershipPlan, username, password,
#         paymentAmount, paymentMethod, paymentDuration }
# 201 + member/session payload (plus "firstPayment") on success - a
# self-signed-up member is not Active until they pay here either, same
# rule as a receptionist's walk-in registration. Also logs the new member in.
# 400 + field errors (e.g. username/email already taken) on failure.
@api_view(["POST"])
def signup(request):
    serializer = MemberSignupSerializer(data=request.data, context={"ip": client_ip(request)})
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    from marketing.offers import OfferError

    try:
        member = serializer.save()
    except OfferError as error:
        return Response({"error": {"offerCode": [error.message]}}, status=400)
    payment = member.first_payment
    used = getattr(payment, "offer_redemption", None)
    referrer = getattr(member, "referred_by", None)
    details = {"plan": member.membership_plan, "amount": f"{payment.amount:.2f}", "method": payment.method}
    if used:
        details.update(offerCode=used.campaign.offer_code, discount=f"{used.discount:.2f}")
    if referrer:
        details.update(referredBy=referrer.name, referralCode=referrer.referral_code)
    record(
        request, AuditLog.Action.MEMBER_SIGNED_UP, actor=member, target=member,
        summary=f"{member.name} signed up online on {member.membership_plan} (paid ${payment.amount:.2f})"
                + (f" with offer {used.campaign.offer_code}" if used else "")
                + (f", referred by {referrer.name}" if referrer else ""),
        details=details,
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


class ResignSerializer(WaiverSignatureFields):
    # Not editable: the signature has to match the name on their record.
    name = serializers.CharField()


# GET  /api/members/me/waiver - the member's own signed waiver: current
#      record, earlier signatures, and whether they need to sign the new
#      version. Members only ever see their own (SCRUM-83).
# POST /api/members/me/waiver {liabilityWaiverAccepted,
#      healthDisclaimerAccepted, signatureName} - sign the current version
#      after the wording changed. 400 if they're already up to date.
@api_view(["GET", "POST"])
def my_waiver(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)

    if request.method == "POST":
        waiver = getattr(member, "waiver", None) if hasattr(member, "waiver") else None
        if waiver is not None and not waiver.needs_resign:
            return Response({"error": "Your waiver is already up to date."}, status=400)
        fields = ResignSerializer(data={**request.data, "name": member.name})
        if not fields.is_valid():
            return Response({"error": fields.errors}, status=400)
        data = dict(fields.validated_data)
        data.pop("name", None)
        signature = WaiverSignatureFields.pop_signature(data)
        waiver = sign(member, signature, Waiver.SignedVia.ONLINE, ip=client_ip(request))
        record(
            request, AuditLog.Action.WAIVER_SIGNED, actor=member, target=member,
            summary=f"{member.name} signed waiver version {waiver.waiver_version}",
            details={"waiverVersion": waiver.waiver_version},
        )
        member.refresh_from_db()
    return Response(waiver_payload(member))

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from members.models import Member
from members.serializers import MemberSerializer
from .models import CheckIn
from .serializers import CheckInCreateSerializer, CheckInSerializer


def _open_session(member):
    return CheckIn.objects.filter(
        member=member, result=CheckIn.Result.ALLOWED, checked_out_at__isnull=True,
    ).order_by("-checked_in_at").first()


def _lookup_member(membership_id):
    try:
        return Member.objects.get(id=membership_id), None
    except Member.DoesNotExist:
        return None, Response({"error": f"No member found with ID {membership_id}."}, status=404)


# GET  /api/checkins          - most recent check-ins (default 20, ?limit= to adjust)
# POST /api/checkins          - check a member in by membership ID (or, in
#                                future, a scanned QR code decoding to the
#                                same ID)
#
# POST body: { membershipId } or { qrCode } (members/qr.py)
# Only Active members can check in, and only once - trying to check in
# again while already inside (an open session: Allowed, not yet checked
# out) is itself refused and logged as Denied ("Already checked in"),
# same as a Frozen/Cancelled member would be. member.status reflects the
# live, just-verified status (see
# members.models.Member.refresh_expiry_status) - a member whose
# subscription quietly lapsed is correctly caught and denied here, not
# let in on a stale "Active" value.
# On success: 201 + { member: {...}, checkIn: {...} }.
# On an unknown ID: 404. On a non-numeric/missing ID: 400.
#
# User story: "As a receptionist, I want to check in members via QR code
# or membership ID, so that I can quickly verify membership status and
# control entry."
@api_view(["GET", "POST"])
def checkin_list(request):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    if request.method == "POST":
        serializer = CheckInCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)

        member, error = _lookup_member(serializer.validated_data["membershipId"])
        if error:
            return error

        member.refresh_expiry_status()

        if member.status != Member.Status.ACTIVE:
            check_in = CheckIn.objects.create(member=member, result=CheckIn.Result.DENIED, reason=member.status)
        elif _open_session(member):
            check_in = CheckIn.objects.create(
                member=member, result=CheckIn.Result.DENIED, reason="Already checked in",
            )
        else:
            check_in = CheckIn.objects.create(member=member, result=CheckIn.Result.ALLOWED)

        return Response(
            {"member": MemberSerializer(member).data, "checkIn": CheckInSerializer(check_in).data},
            status=201,
        )

    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))

    recent = CheckIn.objects.select_related("member").all()[:limit]
    return Response({"results": CheckInSerializer(recent, many=True).data})


# POST /api/checkins/checkout
# Body: { membershipId } or { qrCode }
# Closes a member's open check-in session and reports how long they were
# in (CheckInSerializer's "duration"). A member can't check out without
# having checked in first (no open session -> 400), and - same rule as
# checking in - only an Active member can check out; this is a straight
# error response, not a new logged row, since there's no new entry event
# to record (the still-open session is left exactly as it was).
#
# User story: extends "...check in members via QR code or membership ID,
# so that I can quickly verify membership status and control entry" with
# the matching exit half of that control.
@api_view(["POST"])
def checkout(request):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    serializer = CheckInCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    member, error = _lookup_member(serializer.validated_data["membershipId"])
    if error:
        return error

    member.refresh_expiry_status()

    session = _open_session(member)
    if not session:
        return Response({"error": f"{member.name} hasn't checked in."}, status=400)

    if member.status != Member.Status.ACTIVE:
        return Response({"error": "Only active members can check out."}, status=400)

    session.checked_out_at = timezone.now()
    session.save(update_fields=["checked_out_at"])

    return Response({"member": MemberSerializer(member).data, "checkIn": CheckInSerializer(session).data})

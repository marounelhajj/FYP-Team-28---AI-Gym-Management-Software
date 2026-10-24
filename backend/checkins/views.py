from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from members.access import door_access
from members.models import Member
from members.serializers import MemberSerializer
from training.events import log_training_event
from training.models import TrainingEvent
from .models import CheckIn, CheckInFlag, active_flags, close_stale_sessions, open_session
from .serializers import (
    CheckInCreateSerializer, CheckInFlagCreateSerializer, CheckInFlagResolveSerializer, CheckInSerializer,
    FlaggedAttemptSerializer,
)


# Where the member is entering: the receptionist's branch when their
# account has one, otherwise the member's home branch.
def _desk_branch(account, member):
    return account.branch or member.branch


def _lookup_member(membership_id):
    try:
        return Member.objects.get(id=membership_id), None
    except Member.DoesNotExist:
        return None, Response({"error": f"No member found with ID {membership_id}."}, status=404)


# A scanned QR code from a card that has since been reissued (lost/stolen).
def _is_replaced_card(member, validated_data):
    card_number = validated_data.get("cardNumber")
    return card_number is not None and card_number != member.access_card_number


# Shown on every check-in by a member with Open or Confirmed flags, so the
# desk checks photo ID before letting them in. None when there's nothing to warn about.
def _flag_warning(member):
    flags = active_flags(member)
    latest = flags.first()
    if latest is None:
        return None
    return {
        "count": flags.count(),
        "confirmed": flags.filter(status=CheckInFlag.Status.CONFIRMED).count(),
        "latestReason": latest.reason,
        "latestFlaggedAt": timezone.localtime(latest.flagged_at).strftime("%Y-%m-%d"),
    }


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
    account, denied = authorize(request, "manage_members")
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
        close_stale_sessions()
        branch = _desk_branch(account, member)
        access = door_access(member, serializer.validated_data.get("cardNumber"))

        if not access.granted:
            check_in = CheckIn.objects.create(
                member=member, branch=branch, result=CheckIn.Result.DENIED, reason=access.reason,
            )
        elif open_session(member):
            check_in = CheckIn.objects.create(
                member=member, branch=branch, result=CheckIn.Result.DENIED, reason="Already checked in",
            )
        else:
            check_in = CheckIn.objects.create(member=member, branch=branch, result=CheckIn.Result.ALLOWED)
            # Training data (SCRUM-73): only real visits, not refused attempts.
            log_training_event(
                TrainingEvent.EventType.CHECK_IN, member=member, branch=branch,
                occurred_at=check_in.checked_in_at,
                payload={
                    "checkInId": check_in.id,
                    "method": "qr" if "cardNumber" in serializer.validated_data else "membership_id",
                },
            )

        return Response(
            {
                "member": MemberSerializer(member).data,
                "checkIn": CheckInSerializer(check_in).data,
                "access": {"granted": access.granted, "message": access.message},
                "flagWarning": _flag_warning(member),
            },
            status=201,
        )

    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))

    recent = CheckIn.objects.select_related("member", "door", "flag__flagged_by", "flag__resolved_by")[:limit]
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
    close_stale_sessions()

    if _is_replaced_card(member, serializer.validated_data):
        return Response(
            {"error": f"This card was replaced and no longer works. Use {member.name}'s new card or membership ID."},
            status=400,
        )

    session = open_session(member)
    if not session:
        return Response({"error": f"{member.name} hasn't checked in."}, status=400)

    if member.status != Member.Status.ACTIVE:
        return Response({"error": "Only active members can check out."}, status=400)

    session.checked_out_at = timezone.now()
    session.save(update_fields=["checked_out_at"])

    return Response({"member": MemberSerializer(member).data, "checkIn": CheckInSerializer(session).data})


# POST /api/checkins/<id>/flag - mark a check-in attempt as suspicious.
# Body: { reason, note? }. 400 if the attempt is already flagged.
#
# User story: "As a receptionist, I want to flag a suspicious or duplicate
# check in attempt, so that I can prevent membership sharing or fraudulent access."
@api_view(["POST"])
def flag_checkin(request, checkin_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied

    check_in = CheckIn.objects.select_related("member").filter(id=checkin_id).first()
    if check_in is None:
        return Response({"error": f"Check-in {checkin_id} not found."}, status=404)

    serializer = CheckInFlagCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    flag, created = CheckInFlag.objects.get_or_create(
        check_in=check_in, defaults={**serializer.validated_data, "flagged_by": account},
    )
    if not created:
        return Response({"error": "This check-in attempt is already flagged."}, status=400)

    member = check_in.member
    record(
        request, AuditLog.Action.CHECKIN_FLAGGED, actor=account, target=member,
        summary=f"Flagged a check-in attempt by {member.name} ({flag.reason.lower()})",
        details={
            "checkInId": check_in.id, "attempt": check_in.reason or check_in.result,
            "reason": flag.reason, "note": flag.note,
        },
    )
    return Response(FlaggedAttemptSerializer(flag).data, status=201)


# GET /api/checkins/flags?status=Open|Confirmed|Dismissed|all (default Open)
# The flagged attempts to review, newest first, plus how many are still open.
@api_view(["GET"])
def flag_list(request):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    status = request.query_params.get("status", CheckInFlag.Status.OPEN)
    flags = CheckInFlag.objects.select_related("check_in__member", "flagged_by", "resolved_by")
    if status != "all":
        if status not in CheckInFlag.Status.values:
            return Response({"error": f'Invalid status "{status}".'}, status=400)
        flags = flags.filter(status=status)

    return Response({
        "results": FlaggedAttemptSerializer(flags[:100], many=True).data,
        "openCount": CheckInFlag.objects.filter(status=CheckInFlag.Status.OPEN).count(),
    })


# POST /api/checkins/flags/<id>/resolve - Body: { outcome: Confirmed|Dismissed, note? }
# Confirmed keeps warning the desk at this member's check-ins; Dismissed (a
# false alarm) stops warning. A flag can only be resolved once.
@api_view(["POST"])
def resolve_flag(request, flag_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied

    flag = CheckInFlag.objects.select_related("check_in__member", "flagged_by").filter(id=flag_id).first()
    if flag is None:
        return Response({"error": f"Flag {flag_id} not found."}, status=404)
    if flag.status != CheckInFlag.Status.OPEN:
        return Response({"error": f"This flag was already {flag.status.lower()}."}, status=400)

    serializer = CheckInFlagResolveSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    flag.status = serializer.validated_data["outcome"]
    flag.resolution_note = serializer.validated_data["note"]
    flag.resolved_by = account
    flag.resolved_at = timezone.now()
    flag.save(update_fields=["status", "resolution_note", "resolved_by", "resolved_at"])

    member = flag.check_in.member
    verdict = "Confirmed" if flag.status == CheckInFlag.Status.CONFIRMED else "Dismissed"
    record(
        request, AuditLog.Action.CHECKIN_FLAG_RESOLVED, actor=account, target=member,
        summary=f"{verdict} a flagged check-in by {member.name} ({flag.reason.lower()})",
        details={"flagId": flag.id, "outcome": flag.status, "note": flag.resolution_note},
    )
    return Response(FlaggedAttemptSerializer(flag).data)

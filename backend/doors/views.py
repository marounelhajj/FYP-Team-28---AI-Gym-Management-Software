from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import changes, record
from audit.models import AuditLog
from checkins.models import CheckIn, active_flags, close_stale_sessions, open_session
from checkins.serializers import CheckInSerializer
from members import qr
from members.access import door_access
from members.models import Member
from training.events import log_training_event
from training.models import TrainingEvent

from .models import Door, hash_door_key
from .serializers import DoorScanSerializer, DoorSerializer, DoorWriteSerializer

# User story: "As a receptionist, I want door access to be granted or revoked
# automatically based on membership status, so that entry control stays in
# sync with payments without manual card management."

MANAGE_PERMISSION = "manage_doors"


# Door readers sign in with their key in the X-Door-Key header.
def _authenticate_door(request):
    key = (request.headers.get("X-Door-Key") or "").strip()
    door = Door.objects.filter(key_hash=hash_door_key(key)).first() if key else None
    if door is None:
        return None, Response({"error": "Unknown door key."}, status=401)
    if not door.is_active:
        return None, Response({"error": "This door reader has been disabled."}, status=403)
    return door, None


def _decision(door, granted, message, member=None):
    return {
        "granted": granted,
        "door": door.kind,
        "message": message,
        "member": {"id": member.id, "firstName": member.name.split()[0]} if member else None,
    }


# An entrance opens only if the shared access rule allows this card right now
# and the member isn't already inside. Every scan is kept as a check-in row,
# refused ones included, so the front desk sees door activity too.
def _enter(door, member, card_number):
    with transaction.atomic():
        # Serialises scans of the same member, so two doors can't both let one card in.
        Member.objects.select_for_update().filter(pk=member.pk).first()
        access = door_access(member, card_number)
        if not access.granted:
            CheckIn.objects.create(
                member=member, branch=door.branch, door=door, result=CheckIn.Result.DENIED, reason=access.reason,
            )
            return _decision(door, False, access.message, member)
        # A flagged member needs their photo ID checked, which only staff can do.
        # Deliberately vague on a public screen.
        if active_flags(member).exists():
            CheckIn.objects.create(
                member=member, branch=door.branch, door=door, result=CheckIn.Result.DENIED, reason="ID check required",
            )
            return _decision(door, False, "This card needs a staff check today.", member)
        if open_session(member):
            CheckIn.objects.create(
                member=member, branch=door.branch, door=door, result=CheckIn.Result.DENIED, reason="Already checked in",
            )
            return _decision(door, False, "This card is already inside - it hasn't been scanned out.", member)
        check_in = CheckIn.objects.create(member=member, branch=door.branch, door=door, result=CheckIn.Result.ALLOWED)

    log_training_event(
        TrainingEvent.EventType.CHECK_IN, member=member, branch=door.branch, occurred_at=check_in.checked_in_at,
        payload={"checkInId": check_in.id, "method": "door", "doorId": door.id},
    )
    return _decision(door, True, f"Welcome, {member.name.split()[0]}! {access.message}", member)


# Exits always open, even for a membership revoked while the member was
# inside: nobody is ever locked in. Scanning out just closes their visit.
def _exit(door, member):
    first_name = member.name.split()[0]
    session = open_session(member)
    if session is None:
        return _decision(door, True, f"Goodbye, {first_name}.", member)
    session.checked_out_at = timezone.now()
    session.save(update_fields=["checked_out_at"])
    duration = CheckInSerializer(session).data["duration"]
    return _decision(door, True, f"Goodbye, {first_name} - you were in for {duration}.", member)


# GET /api/doors/self - which door this key belongs to (the door screen's setup check).
@api_view(["GET"])
def door_self(request):
    door, denied = _authenticate_door(request)
    if denied:
        return denied
    return Response({"name": door.name, "branch": door.branch, "kind": door.kind})


# POST /api/doors/scan - Body: { qrCode }. Header: X-Door-Key.
# 200 + { granted, door, message, member } for every scan, so the device only
# has to read "granted". Doors accept signed QR codes only: a membership ID
# isn't secret, so it's never enough to open a door on its own.
@api_view(["POST"])
def door_scan(request):
    door, denied = _authenticate_door(request)
    if denied:
        return denied
    Door.objects.filter(pk=door.pk).update(last_seen_at=timezone.now())

    serializer = DoorScanSerializer(data=request.data)
    card = qr.read(serializer.validated_data["qrCode"]) if serializer.is_valid() else None
    if card is None:
        return Response(_decision(door, False, "Not a valid Fitness Factory membership code."))
    member = Member.objects.filter(id=card[0]).first()
    if member is None:
        return Response(_decision(door, False, "This membership no longer exists."))

    member.refresh_expiry_status()
    close_stale_sessions()
    if door.kind == Door.Kind.EXIT:
        return Response(_exit(door, member))
    return Response(_enter(door, member, card[1]))


# GET  /api/doors - every door reader.
# POST /api/doors - add one. Body: { name, branch, kind }. 201 + { door, key }:
#      the key is only ever shown here (and when it's replaced).
@api_view(["GET", "POST"])
def door_list(request):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied

    if request.method == "GET":
        doors = Door.objects.select_related("created_by")
        return Response({"results": DoorSerializer(doors, many=True).data})

    serializer = DoorWriteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    door = Door(name=data["name"], branch=data["branch"], kind=data["kind"], created_by=account)
    key = door.set_new_key()
    door.save()
    record(
        request, AuditLog.Action.DOOR_CREATED, actor=account, target=door, branch=door.branch,
        summary=f"Added door reader {door.name} ({door.kind.lower()}, {door.branch})",
    )
    return Response({"door": DoorSerializer(door).data, "key": key}, status=201)


# PATCH /api/doors/<id> - rename, move, change kind, or enable/disable.
# A disabled door's key is refused at once, e.g. for a lost tablet.
@api_view(["PATCH"])
def door_detail(request, door_id):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied
    door = Door.objects.select_related("created_by").filter(id=door_id).first()
    if door is None:
        return Response({"error": f"Door {door_id} not found."}, status=404)

    serializer = DoorWriteSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    before = DoorSerializer(door).data
    fields = {"name": "name", "branch": "branch", "kind": "kind", "isActive": "is_active"}
    for key, value in serializer.validated_data.items():
        setattr(door, fields[key], value)
    door.save()
    changed = changes(before, DoorSerializer(door).data)
    if changed:
        record(
            request, AuditLog.Action.DOOR_UPDATED, actor=account, target=door, branch=door.branch,
            summary=f"Edited door reader {door.name} ({', '.join(sorted(changed))})", details={"changes": changed},
        )
    return Response(DoorSerializer(door).data)


# POST /api/doors/<id>/rotate-key - issue a new key; the old one stops working at once.
@api_view(["POST"])
def door_rotate_key(request, door_id):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied
    door = Door.objects.select_related("created_by").filter(id=door_id).first()
    if door is None:
        return Response({"error": f"Door {door_id} not found."}, status=404)

    key = door.set_new_key()
    door.save(update_fields=["key_hash"])
    record(
        request, AuditLog.Action.DOOR_KEY_ROTATED, actor=account, target=door, branch=door.branch,
        summary=f"Replaced the key of door reader {door.name}",
    )
    return Response({"door": DoorSerializer(door).data, "key": key})

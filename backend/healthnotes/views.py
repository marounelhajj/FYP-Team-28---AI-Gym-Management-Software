from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import get_staff_account
from audit.log import record
from audit.models import AuditLog
from classes.models import GymClass, PTSession
from classes.serializers import GymClassSerializer, PTSessionSerializer
from members.models import Member

from . import access
from .models import HealthDeclaration, HealthNote
from .serializers import HealthNoteSerializer

# User story: "As a coach, I want to view a client's health restrictions and
# injuries before starting a session, so that I can adapt the workout safely."
#
# Two sides:
#   * The member keeps their own health notes (under /api/members/me/health).
#     The member is always the session's - never an id in the request.
#   * The coach reads them, never changes them: a briefing per class or
#     private session, and per client from My Clients. Who may read what is
#     in healthnotes/access.py. Each time a coach opens someone's notes it's
#     written to the audit log (once a day per coach and member or class),
#     without any of the health details themselves.

MAX_ACTIVE = 20
SHARED_WITH = (
    "Only the coach of a class or private session you've booked can see this, so they can adapt the workout. "
    "The front desk and managers can't."
)


def _member(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


def _choices(enum):
    return [{"value": value, "label": label} for value, label in enum.choices]


def _my_payload(member):
    declaration = HealthDeclaration.objects.filter(member=member).first()
    notes = list(member.health_notes.all())
    reviewed_on = timezone.localtime(declaration.reviewed_at).date() if declaration else None
    return {
        "active": HealthNoteSerializer([n for n in notes if n.status == HealthNote.Status.ACTIVE], many=True).data,
        "recovered": HealthNoteSerializer([n for n in notes if n.status == HealthNote.Status.RESOLVED], many=True).data,
        "reviewedOn": reviewed_on,
        "needsReview": bool(reviewed_on and (timezone.localdate() - reviewed_on).days > access.STALE_DAYS),
        "maxActive": MAX_ACTIVE,
        "sharedWith": SHARED_WITH,
        "choices": {
            "kind": _choices(HealthNote.Kind), "bodyArea": _choices(HealthNote.BodyArea),
            "severity": _choices(HealthNote.Severity),
        },
    }


def _reviewed(member):
    HealthDeclaration.objects.update_or_create(member=member, defaults={"reviewed_at": timezone.now()})


# Why this member can't have (another) active note like this one, or None.
def _active_problem(member, title, exclude_id=None):
    active = member.health_notes.filter(status=HealthNote.Status.ACTIVE).exclude(id=exclude_id)
    if active.filter(title__iexact=title).exists():
        return 400, {"title": ["You already have an active note with this name - edit that one instead."]}
    if active.count() >= MAX_ACTIVE:
        return 409, f"You can have up to {MAX_ACTIVE} active notes - mark one as recovered or delete it first."
    return None


# GET  /api/members/me/health - the member's own notes (active and recovered),
#      when they last confirmed them, and the pick-lists for the form.
# POST /api/members/me/health - add one:
#      { kind, severity, title, bodyArea?, details?, since? }.
@api_view(["GET", "POST"])
def my_health(request):
    member, denied = _member(request)
    if denied:
        return denied
    if request.method == "POST":
        serializer = HealthNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        with transaction.atomic():
            # Locked, so two taps on Save can't both slip past the checks below.
            Member.objects.select_for_update().get(pk=member.pk)
            problem = _active_problem(member, serializer.validated_data["title"])
            if problem:
                return Response({"error": problem[1]}, status=problem[0])
            serializer.save(member=member, status=HealthNote.Status.ACTIVE, resolved_on=None)
            _reviewed(member)
        return Response(_my_payload(member), status=201)
    return Response(_my_payload(member))


# PATCH  /api/members/me/health/<id> - edit one of your own; status "Resolved"
#        marks it recovered (it stays in your history), "Active" brings it back.
# DELETE /api/members/me/health/<id> - remove it for good.
@api_view(["PATCH", "DELETE"])
def my_health_note(request, note_id):
    member, denied = _member(request)
    if denied:
        return denied
    note = HealthNote.objects.filter(id=note_id, member=member).first()
    if note is None:
        return Response({"error": "Health note not found."}, status=404)
    if request.method == "DELETE":
        note.delete()
        _reviewed(member)
        return Response(_my_payload(member))

    serializer = HealthNoteSerializer(note, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    status = data.get("status", note.status)
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        if status == HealthNote.Status.ACTIVE:
            problem = _active_problem(member, data.get("title", note.title), exclude_id=note.id)
            if problem:
                return Response({"error": problem[1]}, status=problem[0])
        extra = {}
        if status != note.status:
            extra["resolved_on"] = timezone.localdate() if status == HealthNote.Status.RESOLVED else None
        serializer.save(**extra)
        _reviewed(member)
    return Response(_my_payload(member))


# POST /api/members/me/health/confirm - "this is complete and up to date":
# with no active notes it means "nothing to declare", which the coach sees
# instead of "hasn't filled this in".
@api_view(["POST"])
def my_health_confirm(request):
    member, denied = _member(request)
    if denied:
        return denied
    _reviewed(member)
    return Response(_my_payload(member))


# --- the coach's read-only view ----------------------------------------------

def _coach(request):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return account, None


# One audit entry per coach, target and day - opening the same briefing again
# doesn't fill the log.
def _audit(request, coach, target, summary, branch, details):
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    seen = AuditLog.objects.filter(
        action=AuditLog.Action.HEALTH_VIEWED, actor_staff=coach, target_type=target._meta.model_name,
        target_id=str(target.pk), created_at__gte=today,
    )
    if not seen.exists():
        record(request, AuditLog.Action.HEALTH_VIEWED, actor=coach, target=target, summary=summary, branch=branch,
               details=details)


def _entries(member_ids):
    found = access.briefs(member_ids)
    return [access.member_entry(m, found[m.id]) for m in access.members_by_name(member_ids)]


def _split(entries):
    return {
        "restricted": [e for e in entries if e["status"] == "restrictions"],
        "undeclared": [{"memberId": e["memberId"], "name": e["name"]} for e in entries if e["status"] == "undeclared"],
        "clear": [
            {"memberId": e["memberId"], "name": e["name"], "reviewedOn": e["reviewedOn"], "stale": e["stale"],
             "recentlyRecovered": e["recentlyRecovered"]}
            for e in entries if e["status"] == "clear"
        ],
    }


# GET /api/health-notes/classes/<id> - the health briefing for a class: the
# booked members who have restrictions (with their notes, most limiting
# first), those who never filled it in, and those with nothing to declare.
# 403 unless you're the class's coach; 409 once its window has closed.
@api_view(["GET"])
def class_briefing(request, class_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    gym_class = GymClass.objects.select_related("coach", "class_type").filter(id=class_id).first()
    if gym_class is None:
        return Response({"error": f"Class {class_id} not found."}, status=404)
    if gym_class.coach_id != coach.id:
        return Response({"error": "Only the coach of this class can see its health briefing."}, status=403)
    if gym_class.status == GymClass.Status.CANCELLED:
        return Response({"error": "This class was cancelled."}, status=409)
    if not access.class_is_open(gym_class):
        return Response({"error": "The health briefing closes 24 hours after the class ends."}, status=409)

    entries = _entries(access.class_member_ids(gym_class))
    _audit(
        request, coach, gym_class, f"{coach.full_name} opened the health briefing for {gym_class.name}",
        gym_class.branch, {"classId": gym_class.id, "members": len(entries)},
    )
    return Response({"class": GymClassSerializer(gym_class).data, "booked": len(entries), **_split(entries)})


# GET /api/health-notes/pt-sessions/<id> - the same for one private session.
@api_view(["GET"])
def pt_briefing(request, session_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    session = PTSession.objects.select_related("coach", "member").filter(id=session_id).first()
    if session is None:
        return Response({"error": f"Session {session_id} not found."}, status=404)
    if session.coach_id != coach.id:
        return Response({"error": "Only the coach of this session can see its health briefing."}, status=403)
    if session.status == PTSession.Status.CANCELLED:
        return Response({"error": "This session was cancelled."}, status=409)
    if not access.pt_is_open(session):
        return Response({"error": "This session was too long ago to still show the member's health notes."}, status=409)

    member = session.member
    _audit(request, coach, member, f"{coach.full_name} viewed {member.name}'s health notes", session.branch,
           {"ptSessionId": session.id})
    return Response({"session": PTSessionSerializer(session).data, "member": _entries([member.id])[0]})


# GET /api/health-notes/members/<id> - one client's health notes, from My
# Clients. 403 unless the member has a class or private session with you
# coming up (or just behind - see access.py).
@api_view(["GET"])
def member_briefing(request, member_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    if member_id not in access.viewable_member_ids(coach, [member_id]):
        return Response({
            "error": "You can see a member's health notes only around a class or private session they have with you.",
        }, status=403)
    member = Member.objects.get(id=member_id)
    _audit(request, coach, member, f"{coach.full_name} viewed {member.name}'s health notes", member.branch, {})
    return Response({"member": _entries([member.id])[0]})

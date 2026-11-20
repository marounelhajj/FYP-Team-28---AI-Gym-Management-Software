from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.models import StaffAccount
from administration.permissions import authorize, get_staff_account
from audit.log import record
from audit.models import AuditLog
from headcount.views import resolve_branch
from notifications.models import StaffNotification
from notifications.reminders import class_changed

from . import rules
from .models import CoverRequest, GymClass

# User story: "As a branch manager, I want to reassign a class to a substitute
# coach when the original coach cancels last minute, so that the session
# isn't lost."
#
#   * The coach says "I can't make it" from My Schedule (with why). Their
#     branch's managers are alerted at once - urgently if the class is within
#     URGENT_HOURS - and the class shows "Needs cover" on the calendar. The
#     coach stays on it until someone takes over, so it's never left empty,
#     and can withdraw the request if they can make it after all.
#   * The manager opens "Find a substitute": every coach who can teach at the
#     branch, free ones first, each marked busy if they already teach, have a
#     private session or are off at that time, and how often they've taught
#     this class type. Picking one reassigns the class - also straight away,
#     without a request, when the manager hears about it first.
#   * It works until the class ends: a coach who simply doesn't turn up can be
#     replaced after the start, and the session still happens.
#   * The substitute and the original coach are told; members booked in are
#     told who's coaching now (not once it has started - they're in the room).
#     Pay, attendance and the health briefing all follow the class's coach,
#     so they move to the substitute with it. Every reassignment is audited.
#
# Only this one session changes - a repeating series keeps its regular coach.

EDIT = "manage_class_schedule"
ALL_BRANCHES = "view_all_branches"
URGENT_HOURS = 3


def _when(gym_class):
    starts = timezone.localtime(gym_class.starts_at)
    today = timezone.localdate()
    day = "today" if starts.date() == today else "tomorrow" if starts.date() == today + timedelta(days=1) else f"{starts:%a %d %b}"
    return f"{day} at {starts:%H:%M}"


def _managers(branch):
    found = []
    for account in StaffAccount.objects.filter(is_active=True, branch=branch).select_related("role"):
        if EDIT in account.role.permissions:
            found.append(account)
    return found


def _notify(recipients, gym_class, title, message):
    StaffNotification.objects.bulk_create(
        StaffNotification(recipient=r, kind=StaffNotification.Kind.COVER, branch=gym_class.branch,
                          title=title[:120], message=message[:300])
        for r in recipients
    )


# Open requests for classes that ended without a substitute are closed, so
# they stop showing as needing one. Cheap, and run whenever requests are read.
def close_stale(now=None):
    now = now or timezone.now()
    CoverRequest.objects.filter(status=CoverRequest.Status.OPEN, gym_class__ends_at__lte=now).update(
        status=CoverRequest.Status.CLOSED, resolved_at=now,
    )


def close_for_cancelled(class_ids):
    CoverRequest.objects.filter(status=CoverRequest.Status.OPEN, gym_class_id__in=class_ids).update(
        status=CoverRequest.Status.CLOSED, resolved_at=timezone.now(),
    )


def request_payload(r):
    return {
        "id": r.id,
        "classId": r.gym_class_id,
        "status": r.status,
        "reason": r.reason,
        "originalCoach": r.original_coach.full_name,
        "reportedBy": r.reported_by.full_name if r.reported_by else None,
        "substitute": r.substitute.full_name if r.substitute else None,
        "createdAt": timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
    }


# Why this class can't change coach now, as (status, message), or None.
def _class_problem(gym_class, now=None):
    now = now or timezone.now()
    if gym_class.status == GymClass.Status.CANCELLED:
        return 409, "This class was cancelled."
    if gym_class.ends_at <= now:
        return 409, "This class has already taken place."
    return None


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, trim_whitespace=True, error_messages={
        "blank": "Say why, e.g. \"Sick\" or \"Car broke down\".", "required": "Say why, e.g. \"Sick\".",
    })


# --- the coach -----------------------------------------------------------------

def _own_class(request, class_id):
    account = get_staff_account(request)
    if account is None:
        return None, None, Response({"error": "Not authenticated."}, status=401)
    gym_class = GymClass.objects.select_related("coach").filter(id=class_id).first()
    if gym_class is None:
        return None, None, Response({"error": f"Class {class_id} not found."}, status=404)
    if gym_class.coach_id != account.id:
        return None, None, Response({"error": "You can only report classes you're teaching."}, status=403)
    return account, gym_class, None


# POST   /api/classes/me/classes/<id>/cover - Body: { reason } - "I can't make it".
# DELETE /api/classes/me/classes/<id>/cover - "I can make it after all" (while no one has taken over).
@api_view(["POST", "DELETE"])
def my_cover_request(request, class_id):
    account, gym_class, denied = _own_class(request, class_id)
    if denied:
        return denied
    open_request = gym_class.cover_requests.filter(status=CoverRequest.Status.OPEN).first()

    if request.method == "DELETE":
        if open_request is None:
            return Response({"error": "There's no open request for this class."}, status=404)
        open_request.status, open_request.resolved_at = CoverRequest.Status.WITHDRAWN, timezone.now()
        open_request.save(update_fields=["status", "resolved_at"])
        _notify(_managers(gym_class.branch), gym_class, f"No cover needed: {gym_class.name} {_when(gym_class)}",
                f"{account.full_name} can teach it after all.")
        return Response(request_payload(open_request))

    problem = _class_problem(gym_class)
    if problem:
        return Response({"error": problem[1]}, status=problem[0])
    serializer = ReasonSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reason = serializer.validated_data["reason"]
    try:
        with transaction.atomic():
            cover = CoverRequest.objects.create(gym_class=gym_class, original_coach=account, reason=reason, reported_by=account)
    except IntegrityError:
        return Response({"error": "You've already asked for cover for this class."}, status=409)
    soon = gym_class.starts_at - timezone.now() <= timedelta(hours=URGENT_HOURS)
    managers = _managers(gym_class.branch)
    _notify(managers, gym_class, f"{'Urgent: ' if soon else ''}Cover needed - {gym_class.name} {_when(gym_class)}",
            f"{account.full_name} can't teach it: {reason}. {gym_class.room or gym_class.branch}, "
            f"{gym_class.bookings.filter(status='Booked').count()} booked. Open the class to find a substitute.")
    record(
        request, AuditLog.Action.CLASS_COVER_REQUESTED, actor=account, target=gym_class, branch=gym_class.branch,
        summary=f"{account.full_name} asked for cover for {rules.describe(gym_class)}", details={"reason": reason},
    )
    return Response({**request_payload(cover), "managersNotified": len(managers)}, status=201)


# --- the branch manager --------------------------------------------------------

def _managed_class(request, class_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return None, None, denied
    gym_class = GymClass.objects.select_related("coach", "class_type").filter(id=class_id).first()
    if gym_class is None:
        return None, None, Response({"error": f"Class {class_id} not found."}, status=404)
    if ALL_BRANCHES not in account.role.permissions and account.branch != gym_class.branch:
        return None, None, Response({"error": "You can only manage classes at your own branch."}, status=403)
    return account, gym_class, None


def _candidate(coach, gym_class):
    problems = rules.slot_problems(
        branch=gym_class.branch, coach=coach, room="", starts_at=gym_class.starts_at, ends_at=gym_class.ends_at,
        exclude_ids=[gym_class.id],
    )
    past = GymClass.objects.filter(coach=coach, class_type=gym_class.class_type, status=GymClass.Status.SCHEDULED,
                                   ends_at__lte=timezone.now())
    day = timezone.localtime(gym_class.starts_at).date()
    same_day = GymClass.objects.filter(coach=coach, status=GymClass.Status.SCHEDULED, starts_at__date=day).exclude(id=gym_class.id)
    last = past.order_by("-starts_at").first()
    return {
        "id": coach.id,
        "name": coach.full_name,
        "branch": coach.branch or None,
        "available": not problems,
        "busyReason": problems[0] if problems else "",
        "taughtThisType": past.count(),
        "lastTaughtThisType": timezone.localtime(last.starts_at).date() if last else None,
        "classesThatDay": same_day.count(),
    }


# GET /api/classes/<id>/substitutes - who could take this class: every coach who
# can teach at its branch, free ones first, then those who know the class best.
@api_view(["GET"])
def substitutes(request, class_id):
    account, gym_class, denied = _managed_class(request, class_id)
    if denied:
        return denied
    close_stale()
    candidates = [_candidate(c, gym_class) for c in rules.eligible_coaches(gym_class.branch).exclude(id=gym_class.coach_id)]
    candidates.sort(key=lambda c: (not c["available"], -c["taughtThisType"], c["name"]))
    open_request = gym_class.cover_requests.filter(status=CoverRequest.Status.OPEN).select_related(
        "original_coach", "reported_by").first()
    return Response({
        "classId": gym_class.id,
        "name": gym_class.name,
        "date": timezone.localtime(gym_class.starts_at).date(),
        "startTime": f"{timezone.localtime(gym_class.starts_at):%H:%M}",
        "endTime": f"{timezone.localtime(gym_class.ends_at):%H:%M}",
        "room": gym_class.room,
        "currentCoach": {"id": gym_class.coach_id, "name": gym_class.coach.full_name, "active": gym_class.coach.is_active},
        "started": gym_class.has_started,
        "problem": (_class_problem(gym_class) or (None, ""))[1],
        "coverRequest": request_payload(open_request) if open_request else None,
        "candidates": candidates,
    })


class AssignSerializer(serializers.Serializer):
    coachId = serializers.IntegerField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True)


# POST /api/classes/<id>/substitute - Body: { coachId, reason? }. The reason is
# needed unless the coach already asked for cover (theirs is used).
@api_view(["POST"])
def assign_substitute(request, class_id):
    account, gym_class, denied = _managed_class(request, class_id)
    if denied:
        return denied
    serializer = AssignSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data

    with transaction.atomic():
        # Locked: the class, so two managers can't each assign someone; the
        # substitute, so they can't be booked twice for the same time.
        gym_class = GymClass.objects.select_for_update().select_related("coach", "class_type").get(pk=gym_class.pk)
        problem = _class_problem(gym_class)
        if problem:
            return Response({"error": problem[1]}, status=problem[0])
        substitute = StaffAccount.objects.select_for_update().filter(id=data["coachId"]).first()
        if substitute is not None and substitute.id == gym_class.coach_id:
            return Response({"error": {"coachId": [f"{substitute.full_name} is already teaching this class."]}}, status=400)
        problem = rules.coach_problem(substitute, gym_class.branch)
        if problem:
            return Response({"error": {"coachId": [problem]}}, status=400)
        clashes = rules.slot_problems(
            branch=gym_class.branch, coach=substitute, room="", starts_at=gym_class.starts_at, ends_at=gym_class.ends_at,
            exclude_ids=[gym_class.id],
        )
        if clashes:
            return Response({"error": {"coachId": clashes}}, status=409)
        open_request = gym_class.cover_requests.filter(status=CoverRequest.Status.OPEN).first()
        reason = data.get("reason") or (open_request.reason if open_request else "")
        if not reason:
            return Response({"error": {"reason": ["Say why the coach is being replaced, e.g. \"Called in sick\"."]}}, status=400)

        original = gym_class.coach
        was = {"starts_at": gym_class.starts_at, "ends_at": gym_class.ends_at, "room": gym_class.room, "coach": original.full_name}
        gym_class.coach = substitute
        gym_class.save(update_fields=["coach", "updated_at"])
        now = timezone.now()
        cover = open_request or CoverRequest(gym_class=gym_class, original_coach=original, reported_by=account)
        cover.reason, cover.status, cover.substitute, cover.resolved_by, cover.resolved_at = (
            reason, CoverRequest.Status.COVERED, substitute, account, now,
        )
        cover.save()

        started = gym_class.starts_at <= now
        if not started:
            class_changed(gym_class, was)   # booked members hear who's coaching now
        where = f"{gym_class.room + ', ' if gym_class.room else ''}{gym_class.branch}"
        _notify([substitute], gym_class, f"You're covering {gym_class.name} {_when(gym_class)}",
                f"{account.full_name} assigned you to cover for {original.full_name} ({where}). It's on your My Schedule.")
        if original.is_active:
            _notify([original], gym_class, f"{substitute.full_name} is covering your {gym_class.name} {_when(gym_class)}",
                    f"Reason: {reason}. It's no longer on your schedule.")
        record(
            request, AuditLog.Action.CLASS_COVER_ASSIGNED, actor=account, target=gym_class, branch=gym_class.branch,
            summary=f"{substitute.full_name} covers {rules.describe(gym_class)} for {original.full_name}",
            details={"from": original.full_name, "to": substitute.full_name, "reason": reason, "afterStart": started},
        )
    return Response({**request_payload(cover), "membersNotified": not started})


# GET /api/classes/cover-requests?branch= - the branch's classes still waiting
# for a substitute, soonest first.
@api_view(["GET"])
def open_requests(request):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject="the class schedule")
    if error:
        return error
    close_stale()
    found = CoverRequest.objects.filter(status=CoverRequest.Status.OPEN, gym_class__branch=branch).select_related(
        "gym_class", "original_coach", "reported_by").order_by("gym_class__starts_at")
    results = []
    for r in found:
        c = r.gym_class
        results.append({
            **request_payload(r),
            "className": c.name,
            "date": timezone.localtime(c.starts_at).date(),
            "startTime": f"{timezone.localtime(c.starts_at):%H:%M}",
            "endTime": f"{timezone.localtime(c.ends_at):%H:%M}",
            "started": c.has_started,
            "urgent": c.starts_at - timezone.now() <= timedelta(hours=URGENT_HOURS),
            "booked": c.bookings.filter(status="Booked").count(),
        })
    return Response({"branch": branch, "results": results})

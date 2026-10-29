import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.models import StaffAccount
from administration.permissions import authorize
from audit.log import changes, record
from audit.models import AuditLog
from headcount.views import resolve_branch
from members.access import door_access
from members.models import Member

from . import rules
from .models import ClassBooking, ClassType, GymClass, PTAvailability, PTSession
from .serializers import (
    WEEKDAYS, CancelClassSerializer, ClassTypeSerializer, ClassTypeWriteSerializer, GymClassCreateSerializer,
    GymClassSerializer, GymClassUpdateSerializer, MyBookingSerializer, PTBookSerializer, PTHoursCreateSerializer,
    PTHoursSerializer, PTSessionSerializer, RosterEntrySerializer, StaffCancelPTSerializer,
)

# User story: "As a branch manager, I want to create and edit class schedules
# and assign coaches to time slots, so that I can build the weekly class
# calendar for my branch."
#
# Editing needs manage_class_schedule (Branch Manager, System Administrator).
# The front desk (manage_members) can look at the calendar but not change it.
# Same branch rule as headcount and finance: a Branch Manager only ever sees
# and changes their own branch; view_all_branches picks any.

EDIT = "manage_class_schedule"
VIEW = "manage_members"
ALL_BRANCHES = "view_all_branches"
SUBJECT = "the class schedule"


# Ordered explicitly: Meta.ordering isn't applied to a query with an aggregate.
def _with_counts(queryset):
    return queryset.select_related("coach", "class_type").annotate(
        booked_count=Count("bookings", filter=Q(bookings__status=ClassBooking.Status.BOOKED)),
    ).order_by("starts_at", "id")


def _parse_day(value):
    if not value:
        return timezone.localdate(), None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, Response({"error": "week must be a date (YYYY-MM-DD)."}, status=400)


# The week's seven days, with which of them are already over - decided by the
# server clock in Beirut time (settings.TIME_ZONE), not the browser's. The
# calendar runs its live clock from nowIso, so it shows Beirut time even on a
# laptop set to another time zone.
def _week_payload(start):
    now = timezone.localtime()
    today = now.date()
    offset = now.strftime("%z")
    days = [start + timedelta(days=i) for i in range(7)]
    return {
        "weekStart": start,
        "weekEnd": days[-1],
        "today": today,
        "now": f"{now:%H:%M}",
        "nowIso": now.isoformat(timespec="seconds"),
        "timeZone": timezone.get_current_timezone_name(),
        "utcOffset": f"{offset[:3]}:{offset[3:]}",
        "days": [{"date": d, "isPast": d < today, "isToday": d == today} for d in days],
    }


def _may_use_branch(account, branch):
    return ALL_BRANCHES in account.role.permissions or account.branch == branch


def _class_or_error(account, class_id):
    gym_class = _with_counts(GymClass.objects.filter(id=class_id)).first()
    if gym_class is None:
        return None, Response({"error": f"Class {class_id} not found."}, status=404)
    if not _may_use_branch(account, gym_class.branch):
        return None, Response({"error": "You can only see classes at your own branch."}, status=403)
    return gym_class, None


def _locked(gym_class):
    if gym_class.status == GymClass.Status.CANCELLED:
        message = "This class was cancelled - it can't be changed."
    elif gym_class.ends_at <= timezone.now():
        message = "This class has already taken place - past classes are view-only."
    else:
        message = "This class has already started - it can't be changed now."
    return Response({"error": message}, status=409)


# The class itself, or it and every later class in its weekly series that
# hasn't started yet.
def _targets(gym_class, scope):
    if scope != "following" or not gym_class.series:
        return [gym_class]
    return list(_with_counts(GymClass.objects.filter(
        series=gym_class.series, status=GymClass.Status.SCHEDULED,
        starts_at__gte=gym_class.starts_at, starts_at__gt=timezone.now(),
    )))


def _serialized(ids):
    return GymClassSerializer(_with_counts(GymClass.objects.filter(id__in=ids)), many=True).data


def _series_note(count):
    return f" and {count - 1} later class{'es' if count > 2 else ''} in its series" if count > 1 else ""


# GET  /api/classes?week=YYYY-MM-DD&branch= - the week (Monday to Sunday) that
#      contains `week` (default: this week), every class in it, and which days
#      are past. 200 + {branch, branches, weekStart, weekEnd, today, now, days,
#      canEdit, classes}.
# POST /api/classes - add a class: { branch?, classTypeId, description?, coachId,
#      room?, date, startTime "HH:MM", durationMinutes?, capacity?, repeatWeeks? }.
#      Spots default to the type's maximum and can't go above it; the length
#      defaults to the type's. repeatWeeks N puts the same slot on the
#      calendar every week for N weeks.
@api_view(["GET", "POST"])
def class_list(request):
    if request.method == "POST":
        return _create_classes(request)

    account, denied = authorize(request, EDIT, VIEW)
    if denied:
        return denied
    branch, branches, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    day, error = _parse_day(request.query_params.get("week"))
    if error:
        return error

    rules.settle_attendance()
    start, window_start, window_end = rules.week_bounds(day)
    classes = _with_counts(GymClass.objects.filter(branch=branch, starts_at__gte=window_start, starts_at__lt=window_end))
    sessions = rules.booked_pt().filter(branch=branch, starts_at__gte=window_start, starts_at__lt=window_end)
    return Response({
        "branch": branch,
        "branches": branches,
        **_week_payload(start),
        "canEdit": EDIT in account.role.permissions,
        "classes": GymClassSerializer(classes, many=True).data,
        # Booked private training, so the week shows each coach's whole load.
        "ptSessions": PTSessionSerializer(sessions.select_related("coach", "member"), many=True).data,
    })


def _create_classes(request):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    serializer = GymClassCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    branch, _, error = resolve_branch(account, data.get("branch"), subject=SUBJECT)
    if error:
        return error

    class_type = ClassType.objects.filter(id=data["classTypeId"]).first()
    problem = rules.class_type_problem(class_type, branch)
    if problem:
        return Response({"error": {"classTypeId": [problem]}}, status=400)
    capacity = data.get("capacity", class_type.max_capacity)
    duration = data.get("durationMinutes", class_type.default_duration_minutes)
    problem = rules.capacity_problem(class_type, capacity)
    if problem:
        return Response({"error": {"capacity": [problem]}}, status=400)

    coach = StaffAccount.objects.filter(id=data["coachId"]).first()
    problem = rules.coach_problem(coach, branch)
    if problem:
        return Response({"error": {"coachId": [problem]}}, status=400)
    problems = rules.time_problems(data["date"], data["startTime"], duration)
    if problems:
        return Response({"error": problems}, status=400)

    weeks = data["repeatWeeks"]
    if data["date"] + timedelta(weeks=weeks - 1) > timezone.localdate() + timedelta(days=rules.MAX_DAYS_AHEAD):
        return Response(
            {"error": {"repeatWeeks": [f"The last class would be more than {rules.MAX_DAYS_AHEAD} days ahead."]}},
            status=400,
        )
    # Each week's slot is built from the local date and time, so 18:00 stays
    # 18:00 across a daylight-saving change.
    slots = []
    for week in range(weeks):
        starts_at = rules.local_datetime(data["date"] + timedelta(weeks=week), data["startTime"])
        slots.append((starts_at, starts_at + timedelta(minutes=duration)))

    with transaction.atomic():
        # One request at a time checks and books a given coach's time.
        StaffAccount.objects.select_for_update().filter(pk=coach.pk).first()
        conflicts = []
        for starts_at, ends_at in slots:
            conflicts += rules.slot_problems(
                branch=branch, coach=coach, room=data["room"], starts_at=starts_at, ends_at=ends_at,
            )
        if conflicts:
            return Response({"error": {"conflicts": conflicts}}, status=409)
        series = uuid.uuid4() if weeks > 1 else None
        created = [
            GymClass.objects.create(
                branch=branch, class_type=class_type, name=class_type.name, description=data["description"],
                coach=coach, room=data["room"], starts_at=starts_at, ends_at=ends_at, capacity=capacity,
                series=series, created_by=account,
            )
            for starts_at, ends_at in slots
        ]

    first = created[0]
    record(
        request, AuditLog.Action.CLASS_CREATED, actor=account, target=first, branch=branch,
        summary=f"Scheduled {rules.describe(first)} with {coach.full_name}"
                + (f", every week for {weeks} weeks" if weeks > 1 else ""),
        details={"classIds": [c.id for c in created], "coachId": coach.id, "room": first.room, "capacity": first.capacity},
    )
    return Response({"classes": _serialized([c.id for c in created])}, status=201)


# GET   /api/classes/<id> - the class with its roster (who booked, and for a
#       finished class whether they came). seriesFollowing = how many classes
#       an edit with scope "following" would change.
# PATCH /api/classes/<id> - change the type, coach, studio, time, spots... of a
#       class that hasn't started (spots stay within its type's maximum).
#       scope "following" also changes the later classes in its weekly series.
@api_view(["GET", "PATCH"])
def class_detail(request, class_id):
    if request.method == "PATCH":
        return _update_classes(request, class_id)

    account, denied = authorize(request, EDIT, VIEW)
    if denied:
        return denied
    rules.settle_attendance()
    gym_class, error = _class_or_error(account, class_id)
    if error:
        return error
    roster = gym_class.bookings.select_related("member").order_by("status", "booked_at", "id")
    return Response({
        **GymClassSerializer(gym_class).data,
        "roster": RosterEntrySerializer(roster, many=True).data,
        "seriesFollowing": len(_targets(gym_class, "following")) if gym_class.is_editable else 0,
        "canEdit": EDIT in account.role.permissions,
    })


def _update_classes(request, class_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    gym_class, error = _class_or_error(account, class_id)
    if error:
        return error
    if not gym_class.is_editable:
        return _locked(gym_class)

    serializer = GymClassUpdateSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = dict(serializer.validated_data)
    scope = data.pop("scope", "one")
    if scope == "following" and "date" in data:
        if data.pop("date") != timezone.localtime(gym_class.starts_at).date():
            return Response(
                {"error": {"date": ["Move repeating classes one at a time - each keeps its own date."]}}, status=400,
            )

    coach = gym_class.coach
    if "coachId" in data:
        coach = StaffAccount.objects.filter(id=data["coachId"]).first()
        problem = rules.coach_problem(coach, gym_class.branch)
        if problem:
            return Response({"error": {"coachId": [problem]}}, status=400)
    new_type = None
    if data.get("classTypeId", gym_class.class_type_id) != gym_class.class_type_id:
        new_type = ClassType.objects.filter(id=data["classTypeId"]).first()
        problem = rules.class_type_problem(new_type, gym_class.branch)
        if problem:
            return Response({"error": {"classTypeId": [problem]}}, status=400)

    targets = _targets(gym_class, scope)
    ids = [t.id for t in targets]
    plans = []
    conflicts = []
    for target in targets:
        local_start = timezone.localtime(target.starts_at)
        day = data.get("date", local_start.date())
        start_time = data.get("startTime", local_start.time().replace(second=0, microsecond=0))
        duration = data.get("durationMinutes", int((target.ends_at - target.starts_at).total_seconds() // 60))
        starts_at = rules.local_datetime(day, start_time)
        ends_at = starts_at + timedelta(minutes=duration)
        moved = (starts_at, ends_at) != (target.starts_at, target.ends_at)
        if moved:
            problems = rules.time_problems(day, start_time, duration)
            if problems:
                return Response({"error": problems}, status=400)
        class_type = new_type or target.class_type
        capacity = data.get("capacity", target.capacity)
        if new_type and "capacity" not in data:
            capacity = min(capacity, new_type.max_capacity)
        problem = rules.capacity_problem(class_type, capacity)
        if problem:
            return Response({"error": {"capacity": [problem]}}, status=400)
        if capacity < target.booked_count:
            conflicts.append(
                f"{rules.describe(target)} already has {target.booked_count} bookings - "
                "the capacity can't go below that.",
            )
        plans.append((target, starts_at, ends_at, moved, capacity))

    with transaction.atomic():
        StaffAccount.objects.select_for_update().filter(pk=coach.pk).first()
        for target, starts_at, ends_at, moved, _ in plans:
            room = data.get("room", target.room)
            if moved or coach.pk != target.coach_id or room.lower() != target.room.lower():
                conflicts += rules.slot_problems(
                    branch=target.branch, coach=coach, room=room, starts_at=starts_at, ends_at=ends_at, exclude_ids=ids,
                )
            if moved:
                names = rules.member_clashes(target, starts_at, ends_at, ids)
                if names:
                    conflicts.append(
                        f"Can't move {rules.describe(target)}: {', '.join(names)} "
                        f"{'is' if len(names) == 1 else 'are'} booked into another class at the new time.",
                    )
        if conflicts:
            return Response({"error": {"conflicts": conflicts}}, status=409)

        before = GymClassSerializer(gym_class).data
        for target, starts_at, ends_at, _, capacity in plans:
            if new_type:
                target.class_type, target.name = new_type, new_type.name
            target.description = data.get("description", target.description)
            target.room = data.get("room", target.room)
            target.capacity = capacity
            target.coach = coach
            target.starts_at, target.ends_at = starts_at, ends_at
            target.save()

    updated = _serialized(ids)
    after = next(c for c in updated if c["id"] == gym_class.id)
    changed = changes(
        before, after,
        ignore=("booked", "spotsLeft", "state", "editable", "coachActive", "coachName", "classTypeId", "maxCapacity"),
    )
    if changed:
        record(
            request, AuditLog.Action.CLASS_UPDATED, actor=account, target=gym_class, branch=gym_class.branch,
            summary=f"Edited {rules.describe(gym_class)}{_series_note(len(ids))} ({', '.join(sorted(changed))})",
            details={"changes": changed, "classIds": ids},
        )
    return Response({"classes": updated})


# POST /api/classes/<id>/cancel - Body: { reason?, scope? }. Takes a class that
# hasn't started off the calendar (it stays visible, marked cancelled) and
# releases every booking in it.
@api_view(["POST"])
def cancel_class(request, class_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    gym_class, error = _class_or_error(account, class_id)
    if error:
        return error
    if not gym_class.is_editable:
        return _locked(gym_class)
    serializer = CancelClassSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reason = serializer.validated_data["reason"].strip()

    ids = [t.id for t in _targets(gym_class, serializer.validated_data["scope"])]
    now = timezone.now()
    with transaction.atomic():
        GymClass.objects.filter(id__in=ids).update(
            status=GymClass.Status.CANCELLED, cancelled_at=now, cancelled_by=account, cancel_reason=reason,
            updated_at=now,
        )
        released = ClassBooking.objects.filter(gym_class_id__in=ids, status=ClassBooking.Status.BOOKED).update(
            status=ClassBooking.Status.CANCELLED, cancelled_at=now, cancel_reason="Class cancelled by the gym",
        )

    record(
        request, AuditLog.Action.CLASS_CANCELLED, actor=account, target=gym_class, branch=gym_class.branch,
        summary=f"Cancelled {rules.describe(gym_class)}{_series_note(len(ids))}"
                + (f" - {released} booking{'s' if released != 1 else ''} released" if released else ""),
        details={"classIds": ids, "reason": reason, "releasedBookings": released},
    )
    return Response({"classes": _serialized(ids), "releasedBookings": released})


def _busy_label(gym_class, branch, with_day):
    starts, ends = timezone.localtime(gym_class.starts_at), timezone.localtime(gym_class.ends_at)
    day = f" on {starts:%a %d %b}" if with_day else ""
    where = "" if gym_class.branch == branch else f" at {gym_class.branch}"
    return f"{gym_class.name}{day} {starts:%H:%M}–{ends:%H:%M}{where}"


# GET /api/classes/availability?branch=&date=&startTime=&durationMinutes=&repeatWeeks=&excludeId=
# Who and what is already taken in a slot, so the class form can grey out a
# busy coach or studio before anything is saved (saving checks it again):
# 200 + {"coaches": {coachId: "Boxing 18:00–19:00 at Jnah"}, "studios":
# [{"name", "takenBy"}]}. A coach is busy at any branch; studios are the
# branch's own (every studio a class there has used). repeatWeeks checks the
# same slot that many weeks running; excludeId is the class being edited.
@api_view(["GET"])
def availability(request):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    params = request.query_params
    branch, _, error = resolve_branch(account, params.get("branch"), subject=SUBJECT)
    if error:
        return error
    try:
        day = date.fromisoformat(params.get("date", ""))
        start_time = datetime.strptime(params.get("startTime", ""), "%H:%M").time()
        duration = int(params.get("durationMinutes", ""))
        weeks = int(params.get("repeatWeeks") or 1)
        exclude_id = int(params.get("excludeId") or 0)
    except ValueError:
        return Response({"error": "Give date (YYYY-MM-DD), startTime (HH:MM) and durationMinutes."}, status=400)
    if not (rules.MIN_DURATION <= duration <= rules.MAX_DURATION and 1 <= weeks <= rules.MAX_REPEAT_WEEKS):
        return Response({"error": "durationMinutes or repeatWeeks is out of range."}, status=400)

    live = GymClass.objects.filter(status=GymClass.Status.SCHEDULED).exclude(id=exclude_id)
    busy_coaches, taken_rooms = {}, {}
    for week in range(weeks):
        starts_at = rules.local_datetime(day + timedelta(weeks=week), start_time)
        ends_at = starts_at + timedelta(minutes=duration)
        for c in rules.overlapping(live, starts_at, ends_at).order_by("starts_at"):
            label = _busy_label(c, branch, with_day=weeks > 1)
            busy_coaches.setdefault(c.coach_id, label)
            if c.branch == branch and c.room:
                taken_rooms.setdefault(c.room.lower(), label)
        for session in rules.overlapping(rules.booked_pt(), starts_at, ends_at):
            starts, ends = timezone.localtime(session.starts_at), timezone.localtime(session.ends_at)
            day = f" on {starts:%a %d %b}" if weeks > 1 else ""
            busy_coaches.setdefault(session.coach_id, f"Private training{day} {starts:%H:%M}–{ends:%H:%M}")

    studios = {}
    for room in GymClass.objects.filter(branch=branch).exclude(room="").order_by("room").values_list("room", flat=True):
        studios.setdefault(room.lower(), room)
    return Response({
        "coaches": busy_coaches,
        "studios": [
            {"name": name, "takenBy": taken_rooms.get(key)}
            for key, name in sorted(studios.items())
        ],
    })


# GET /api/classes/coaches?branch= - coaches who can teach at the branch:
# active staff with the Coach job title, from that branch or not tied to one.
@api_view(["GET"])
def coach_list(request):
    account, denied = authorize(request, EDIT, VIEW)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    return Response({
        "branch": branch,
        "results": [{"id": c.id, "name": c.full_name, "branch": c.branch or None} for c in rules.eligible_coaches(branch)],
    })


# --- Class types and their maximum capacity ---
#
# User story: "As a branch manager, I want to set maximum capacity per class
# type, so that I can prevent overbooking and keep sessions safe."

def _upcoming(class_types):
    return _with_counts(GymClass.objects.filter(
        class_type__in=class_types, status=GymClass.Status.SCHEDULED, starts_at__gt=timezone.now(),
    ))


def _type_stats(class_types):
    stats = {t.id: {"upcomingClasses": 0, "mostBooked": 0} for t in class_types}
    for c in _upcoming(class_types):
        entry = stats[c.class_type_id]
        entry["upcomingClasses"] += 1
        entry["mostBooked"] = max(entry["mostBooked"], c.booked_count)
    return stats


def _type_payload(class_type):
    return ClassTypeSerializer(class_type, context={"stats": _type_stats([class_type])}).data


# GET  /api/classes/types?branch=&includeArchived=true - the branch's class types.
# POST /api/classes/types - add one: { branch?, name, maxCapacity, defaultDurationMinutes?, description? }.
@api_view(["GET", "POST"])
def class_type_list(request):
    if request.method == "POST":
        account, denied = authorize(request, EDIT)
        if denied:
            return denied
        branch, _, error = resolve_branch(account, request.data.get("branch"), subject=SUBJECT)
        if error:
            return error
        serializer = ClassTypeWriteSerializer(data=request.data, context={"branch": branch})
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        data = serializer.validated_data
        class_type = ClassType.objects.create(
            branch=branch, name=data["name"], max_capacity=data["maxCapacity"],
            default_duration_minutes=data["defaultDurationMinutes"], description=data["description"],
        )
        record(
            request, AuditLog.Action.CLASS_TYPE_CREATED, actor=account, target=class_type, branch=branch,
            summary=f"Added class type {class_type.name} at {branch} (max {class_type.max_capacity} people)",
            details={"maxCapacity": class_type.max_capacity},
        )
        return Response(_type_payload(class_type), status=201)

    account, denied = authorize(request, EDIT, VIEW)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    types = ClassType.objects.filter(branch=branch).order_by("name")
    if request.query_params.get("includeArchived") != "true":
        types = types.filter(is_active=True)
    types = list(types)
    return Response({
        "branch": branch,
        "canEdit": EDIT in account.role.permissions,
        "results": ClassTypeSerializer(types, many=True, context={"stats": _type_stats(types)}).data,
    })


# PATCH /api/classes/types/<id> - rename, change the maximum or default length,
# archive or restore. A new maximum carries over to the type's upcoming
# classes: any with more spots than the new maximum are cut down to it, and
# when the maximum goes up, classes that were at the old maximum go up with
# it (a class given fewer spots on purpose keeps them). It's refused while
# an upcoming class already has more bookings than the new maximum - those
# people have to be moved first. Classes that have started are never touched.
@api_view(["PATCH"])
def class_type_detail(request, type_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    class_type = ClassType.objects.filter(id=type_id).first()
    if class_type is None:
        return Response({"error": f"Class type {type_id} not found."}, status=404)
    if not _may_use_branch(account, class_type.branch):
        return Response({"error": "You can only manage class types at your own branch."}, status=403)
    serializer = ClassTypeWriteSerializer(
        class_type, data=request.data, partial=True, context={"branch": class_type.branch},
    )
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    before = _type_payload(class_type)

    with transaction.atomic():
        ClassType.objects.select_for_update().filter(pk=class_type.pk).first()
        upcoming = list(_upcoming([class_type]))
        old_max = class_type.max_capacity
        new_max = data.get("maxCapacity", old_max)
        too_full = [c for c in upcoming if c.booked_count > new_max]
        if too_full:
            return Response({"error": {"conflicts": [
                f"{rules.describe(c)} already has {c.booked_count} bookings - more than {new_max}."
                for c in too_full
            ]}}, status=409)

        new_name = data.get("name", class_type.name)
        adjusted = []
        for c in upcoming:
            changed = False
            if c.capacity > new_max or (new_max > old_max and c.capacity == old_max):
                c.capacity, changed = new_max, True
                adjusted.append(c.id)
            if c.name != new_name:
                c.name, changed = new_name, True
            if changed:
                c.save(update_fields=["capacity", "name", "updated_at"])

        class_type.name = new_name
        class_type.max_capacity = new_max
        class_type.default_duration_minutes = data.get("defaultDurationMinutes", class_type.default_duration_minutes)
        class_type.description = data.get("description", class_type.description)
        class_type.is_active = data.get("isActive", class_type.is_active)
        class_type.save()

    after = _type_payload(class_type)
    changed = changes(before, after, ignore=("upcomingClasses", "mostBookedUpcoming"))
    if changed:
        summary = f"Edited class type {class_type.name} at {class_type.branch} ({', '.join(sorted(changed))})"
        if adjusted:
            summary += f" - {len(adjusted)} upcoming class{'es' if len(adjusted) != 1 else ''} now hold {new_max}"
        record(
            request, AuditLog.Action.CLASS_TYPE_UPDATED, actor=account, target=class_type, branch=class_type.branch,
            summary=summary, details={"changes": changed, "adjustedClassIds": adjusted},
        )
    return Response({**after, "adjustedClasses": len(adjusted)})


# --- The member side: booking a spot (routed under /api/members/me/classes) ---

def _member_from_session(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


def _for_member(gym_class, booking):
    return {**GymClassSerializer(gym_class).data, "myBooking": MyBookingSerializer(booking).data if booking else None}


def _class_with_counts(class_id):
    return _with_counts(GymClass.objects.filter(pk=class_id)).get()


# GET /api/members/me/classes?week= - the member's own branch's classes that
# week, with their reservation (if any) on each, plus their upcoming
# reservations and whether they may book at all right now.
@api_view(["GET"])
def my_classes(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    member.refresh_expiry_status()
    day, error = _parse_day(request.query_params.get("week"))
    if error:
        return error

    rules.settle_attendance()
    start, window_start, window_end = rules.week_bounds(day)
    classes = list(_with_counts(
        GymClass.objects.filter(branch=member.branch, starts_at__gte=window_start, starts_at__lt=window_end),
    ))
    # Latest booking per class: a re-booking after a cancellation wins.
    mine = {b.gym_class_id: b for b in member.class_bookings.filter(gym_class__in=classes).order_by("booked_at", "id")}
    upcoming = member.class_bookings.filter(
        status=ClassBooking.Status.BOOKED, gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__ends_at__gt=timezone.now(),
    ).select_related("gym_class__coach").order_by("gym_class__starts_at")[:20]
    upcoming_pt = rules.booked_pt().filter(member=member, ends_at__gt=timezone.now()).select_related("coach", "member")
    access = door_access(member)
    return Response({
        "branch": member.branch,
        **_week_payload(start),
        "classes": [_for_member(c, mine.get(c.id)) for c in classes],
        "upcoming": [_for_member(b.gym_class, b) for b in upcoming],
        "upcomingPt": PTSessionSerializer(upcoming_pt, many=True).data,
        "canBook": access.granted,
        "bookingBlockedReason": None if access.granted else access.message,
        "bookableUntil": member.subscription_expires_at,
    })


def _booking_problem(member, gym_class):
    if gym_class.status == GymClass.Status.CANCELLED:
        return Response({"error": "This class was cancelled."}, status=400)
    if gym_class.has_started:
        return Response({"error": "This class has already started - booking is closed."}, status=400)
    if gym_class.branch != member.branch:
        return Response({"error": f"You can only book classes at your own branch ({member.branch})."}, status=403)
    access = door_access(member)
    if not access.granted:
        return Response({"error": f"You can't book classes right now: {access.message}"}, status=403)
    class_day = timezone.localtime(gym_class.starts_at).date()
    if member.subscription_expires_at < class_day:
        return Response({
            "error": f"Your membership runs until {member.subscription_expires_at:%d %b %Y} - "
                     "renew it to book classes after that date.",
        }, status=403)
    if ClassBooking.objects.filter(gym_class=gym_class, member=member, status=ClassBooking.Status.BOOKED).exists():
        return Response({"error": "You've already reserved a spot in this class."}, status=400)
    # The class's spots, and never past its type's safety limit.
    if rules.booked_count(gym_class) >= min(gym_class.capacity, gym_class.class_type.max_capacity):
        return Response({"error": "This class is full."}, status=409)
    clash = rules.member_busy(member, gym_class.starts_at, gym_class.ends_at)
    if clash:
        return Response({
            "error": f"You're already booked into {clash} - you can't take two classes at the same time.",
        }, status=409)
    return None


# POST /api/members/me/classes/<id>/book - reserve a spot.
@api_view(["POST"])
def book_class(request, class_id):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    member.refresh_expiry_status()
    with transaction.atomic():
        # Locks the member (no two overlapping bookings from two tabs) and the
        # class (no overbooking its last spot).
        Member.objects.select_for_update().filter(pk=member.pk).first()
        gym_class = GymClass.objects.select_for_update().filter(id=class_id).first()
        if gym_class is None:
            return Response({"error": f"Class {class_id} not found."}, status=404)
        problem = _booking_problem(member, gym_class)
        if problem:
            return problem
        booking = ClassBooking.objects.create(gym_class=gym_class, member=member)
    return Response(_for_member(_class_with_counts(gym_class.pk), booking), status=201)


# POST /api/members/me/classes/<id>/cancel - give a reserved spot back, any
# time before the class starts.
@api_view(["POST"])
def cancel_booking(request, class_id):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    booking = member.class_bookings.filter(
        gym_class_id=class_id, status=ClassBooking.Status.BOOKED,
    ).select_related("gym_class").first()
    if booking is None:
        return Response({"error": "You don't have a reservation for this class."}, status=404)
    if booking.gym_class.has_started:
        return Response({"error": "This class has already started - the reservation can't be cancelled now."}, status=400)
    booking.status = ClassBooking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancel_reason = "Cancelled by you"
    booking.save(update_fields=["status", "cancelled_at", "cancel_reason"])
    return Response(_for_member(_class_with_counts(class_id), booking))


# --- Private training (PT) ---
#
# User story: "As a member, I want to browse and book available classes or PT
# sessions directly through the app, so that I can reserve my spot without
# contacting the front desk."
#
# A branch manager publishes each coach's weekly PT hours; members book a free
# session inside them. Coaches have no screens of their own yet, so a session
# is confirmed as soon as it's booked (the hours are the coach's offer).

def _sessions_in_hours(hours):
    count = 0
    for session in rules.booked_pt().filter(coach=hours.coach, branch=hours.branch, starts_at__gt=timezone.now()):
        local = timezone.localtime(session.starts_at)
        if local.weekday() == hours.weekday and hours.start_time <= local.time() < hours.end_time:
            count += 1
    return count


# GET  /api/classes/pt-hours?branch= - every coach at the branch with their weekly
#      PT hours there, and the branch's upcoming booked sessions.
# POST /api/classes/pt-hours - add hours: { branch?, coachId, weekday (0 = Monday),
#      startTime, endTime, sessionMinutes }. A coach's hours can't overlap on the
#      same weekday, at any branch.
@api_view(["GET", "POST"])
def pt_hours_list(request):
    if request.method == "POST":
        account, denied = authorize(request, EDIT)
        if denied:
            return denied
        serializer = PTHoursCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        data = serializer.validated_data
        branch, _, error = resolve_branch(account, data.get("branch"), subject=SUBJECT)
        if error:
            return error
        coach = StaffAccount.objects.filter(id=data["coachId"]).first()
        problem = rules.coach_problem(coach, branch)
        if problem:
            return Response({"error": {"coachId": [problem]}}, status=400)
        with transaction.atomic():
            StaffAccount.objects.select_for_update().filter(pk=coach.pk).first()
            clash = PTAvailability.objects.filter(
                coach=coach, weekday=data["weekday"], start_time__lt=data["endTime"], end_time__gt=data["startTime"],
            ).first()
            if clash:
                where = "" if clash.branch == branch else f" at {clash.branch}"
                return Response({"error": {"conflicts": [
                    f"{coach.full_name} already has PT hours on {WEEKDAYS[clash.weekday]} "
                    f"{clash.start_time:%H:%M}-{clash.end_time:%H:%M}{where}.",
                ]}}, status=409)
            hours = PTAvailability.objects.create(
                coach=coach, branch=branch, weekday=data["weekday"], start_time=data["startTime"],
                end_time=data["endTime"], session_minutes=data["sessionMinutes"],
            )
        record(
            request, AuditLog.Action.PT_HOURS_ADDED, actor=account, target=coach, branch=branch,
            summary=f"Added PT hours for {coach.full_name} at {branch}: {WEEKDAYS[hours.weekday]} "
                    f"{hours.start_time:%H:%M}-{hours.end_time:%H:%M} ({hours.session_minutes}-minute sessions)",
            details={"ptHoursId": hours.id},
        )
        return Response(PTHoursSerializer(hours).data, status=201)

    account, denied = authorize(request, EDIT, VIEW)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    coaches = list(rules.eligible_coaches(branch))
    hours = defaultdict(list)
    for block in PTAvailability.objects.filter(coach__in=coaches, branch=branch):
        hours[block.coach_id].append(block)
    sessions = rules.booked_pt().filter(branch=branch, ends_at__gt=timezone.now()).select_related("coach", "member")
    return Response({
        "branch": branch,
        "canEdit": EDIT in account.role.permissions,
        "sessionLengths": list(rules.PT_SESSION_LENGTHS),
        "coaches": [
            {"id": c.id, "name": c.full_name, "branch": c.branch or None,
             "hours": PTHoursSerializer(hours[c.id], many=True).data}
            for c in coaches
        ],
        "sessions": PTSessionSerializer(sessions[:200], many=True).data,
    })


# DELETE /api/classes/pt-hours/<id> - stop offering those hours. Sessions
# members already booked in them stay booked.
@api_view(["DELETE"])
def pt_hours_detail(request, hours_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    hours = PTAvailability.objects.select_related("coach").filter(id=hours_id).first()
    if hours is None:
        return Response({"error": f"PT hours {hours_id} not found."}, status=404)
    if not _may_use_branch(account, hours.branch):
        return Response({"error": "You can only change PT hours at your own branch."}, status=403)
    kept = _sessions_in_hours(hours)
    label = f"{WEEKDAYS[hours.weekday]} {hours.start_time:%H:%M}-{hours.end_time:%H:%M}"
    coach, branch = hours.coach, hours.branch
    hours.delete()
    record(
        request, AuditLog.Action.PT_HOURS_REMOVED, actor=account, target=coach, branch=branch,
        summary=f"Removed PT hours for {coach.full_name} at {branch}: {label}",
        details={"bookedSessionsKept": kept},
    )
    return Response({"removed": hours_id, "bookedSessionsKept": kept})


# POST /api/classes/pt-sessions/<id>/cancel - Body: { reason? }. The gym cancels
# a booked session that hasn't started (the coach is ill, say).
@api_view(["POST"])
def staff_cancel_pt(request, session_id):
    account, denied = authorize(request, EDIT)
    if denied:
        return denied
    session = PTSession.objects.select_related("coach", "member").filter(id=session_id).first()
    if session is None:
        return Response({"error": f"Session {session_id} not found."}, status=404)
    if not _may_use_branch(account, session.branch):
        return Response({"error": "You can only manage sessions at your own branch."}, status=403)
    if session.status == PTSession.Status.CANCELLED:
        return Response({"error": "This session was already cancelled."}, status=400)
    if session.has_started:
        return Response({"error": "This session has already started - it can't be cancelled now."}, status=409)
    serializer = StaffCancelPTSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reason = serializer.validated_data["reason"].strip()
    session.status = PTSession.Status.CANCELLED
    session.cancelled_at = timezone.now()
    session.cancel_reason = f"Cancelled by the gym{': ' + reason if reason else ''}"[:120]
    session.save(update_fields=["status", "cancelled_at", "cancel_reason"])
    when = timezone.localtime(session.starts_at)
    record(
        request, AuditLog.Action.PT_SESSION_CANCELLED, actor=account, target=session.member, branch=session.branch,
        summary=f"Cancelled {session.member.name}'s private session with {session.coach.full_name} "
                f"on {when:%a %d %b %H:%M}",
        details={"ptSessionId": session.id, "reason": reason},
    )
    return Response(PTSessionSerializer(session).data)


def _member_coach(member, coach_id):
    try:
        return rules.eligible_coaches(member.branch).filter(id=int(coach_id)).first()
    except (TypeError, ValueError):
        return None


# GET /api/members/me/coaches - the coaches at the member's branch: what they
# teach in the next four weeks, their PT hours, and their next free session.
@api_view(["GET"])
def my_coaches(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    now = timezone.now()
    coaches = list(rules.eligible_coaches(member.branch))
    teaches = defaultdict(set)
    for coach_id, name in GymClass.objects.filter(
        coach__in=coaches, branch=member.branch, status=GymClass.Status.SCHEDULED,
        starts_at__gt=now, starts_at__lt=now + timedelta(days=28),
    ).values_list("coach_id", "name"):
        teaches[coach_id].add(name)
    hours = defaultdict(list)
    for block in PTAvailability.objects.filter(coach__in=coaches, branch=member.branch):
        hours[block.coach_id].append(block)

    today = timezone.localdate()
    fortnight = [today + timedelta(days=i) for i in range(14)]
    results = []
    for coach in coaches:
        first_open = None
        if hours[coach.id]:
            slots = rules.pt_slots(coach, member.branch, fortnight, member)
            first_open = next((s for s in slots if s["state"] == "open"), None)
        results.append({
            "id": coach.id,
            "name": coach.full_name,
            "teaches": sorted(teaches[coach.id]),
            "ptHours": PTHoursSerializer(hours[coach.id], many=True).data,
            "nextOpen": {"date": first_open["date"], "startTime": first_open["startTime"]} if first_open else None,
        })
    return Response({"branch": member.branch, "coaches": results})


# GET /api/members/me/pt-slots?coachId=&week= - one coach's private sessions that
# week at the member's branch, each with its state for this member (see
# rules.pt_slots), plus whether they may book at all.
@api_view(["GET"])
def my_pt_slots(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    member.refresh_expiry_status()
    coach = _member_coach(member, request.query_params.get("coachId"))
    if coach is None:
        return Response({"error": "That coach doesn't offer private training at your branch."}, status=404)
    day, error = _parse_day(request.query_params.get("week"))
    if error:
        return error
    rules.settle_attendance()
    start = rules.week_start(day)
    access = door_access(member)
    return Response({
        "branch": member.branch,
        **_week_payload(start),
        "coach": {"id": coach.id, "name": coach.full_name},
        "hours": PTHoursSerializer(PTAvailability.objects.filter(coach=coach, branch=member.branch), many=True).data,
        "slots": rules.pt_slots(coach, member.branch, [start + timedelta(days=i) for i in range(7)], member),
        "canBook": access.granted,
        "bookingBlockedReason": None if access.granted else access.message,
        "bookableUntil": member.subscription_expires_at,
        "upcomingSessions": rules.booked_pt().filter(member=member, ends_at__gt=timezone.now()).count(),
        "maxUpcomingSessions": rules.MAX_UPCOMING_PT,
    })


# POST /api/members/me/pt-sessions - Body: { coachId, startsAt "YYYY-MM-DDTHH:MM", note? }.
# Books one of the coach's free sessions (an "open" slot from /me/pt-slots).
@api_view(["POST"])
def book_pt(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    member.refresh_expiry_status()
    serializer = PTBookSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    coach = _member_coach(member, data["coachId"])
    if coach is None:
        return Response({"error": "That coach doesn't offer private training at your branch."}, status=404)
    starts_at = data["startsAt"]
    local = timezone.localtime(starts_at)
    access = door_access(member)
    if not access.granted:
        return Response({"error": f"You can't book private training right now: {access.message}"}, status=403)
    if member.subscription_expires_at < local.date():
        return Response({
            "error": f"Your membership runs until {member.subscription_expires_at:%d %b %Y} - "
                     "renew it to book sessions after that date.",
        }, status=403)

    with transaction.atomic():
        # One booking at a time per member and per coach.
        Member.objects.select_for_update().filter(pk=member.pk).first()
        StaffAccount.objects.select_for_update().filter(pk=coach.pk).first()
        key = f"{local:%Y-%m-%dT%H:%M}"
        slot = next((s for s in rules.pt_slots(coach, member.branch, [local.date()], member) if s["startsAt"] == key), None)
        if slot is None:
            return Response({"error": f"That isn't one of {coach.full_name}'s private training times."}, status=400)
        refusals = {
            "yours": (400, "You've already booked this session."),
            "taken": (409, "Someone has just booked that session - pick another time."),
            "coach_busy": (409, f"{coach.full_name} is teaching a class then."),
            "closed": (400, "That session has already started." if starts_at <= timezone.now()
                       else "Private training has to be booked at least an hour ahead."),
        }
        if slot["state"] in refusals:
            status, message = refusals[slot["state"]]
            return Response({"error": message}, status=status)
        ends_at = rules.local_datetime(local.date(), time.fromisoformat(slot["endTime"]))
        if slot["state"] == "clash":
            clash = rules.member_busy(member, starts_at, ends_at)
            return Response({"error": f"You're already booked into {clash} then."}, status=409)
        if rules.booked_pt().filter(member=member, ends_at__gt=timezone.now()).count() >= rules.MAX_UPCOMING_PT:
            return Response({
                "error": f"You can hold up to {rules.MAX_UPCOMING_PT} upcoming private sessions - "
                         "cancel one or wait until one has taken place.",
            }, status=409)
        try:
            with transaction.atomic():
                session = PTSession.objects.create(
                    coach=coach, member=member, branch=member.branch, starts_at=starts_at, ends_at=ends_at,
                    note=data["note"].strip(),
                )
        except IntegrityError:
            return Response({"error": "Someone has just booked that session - pick another time."}, status=409)
    return Response(PTSessionSerializer(session).data, status=201)


# POST /api/members/me/pt-sessions/<id>/cancel - give a session back, any time
# before it starts.
@api_view(["POST"])
def cancel_my_pt(request, session_id):
    member, denied = _member_from_session(request)
    if denied:
        return denied
    session = member.pt_sessions.filter(
        id=session_id, status=PTSession.Status.BOOKED,
    ).select_related("coach", "member").first()
    if session is None:
        return Response({"error": "You don't have that session booked."}, status=404)
    if session.has_started:
        return Response({"error": "This session has already started - it can't be cancelled now."}, status=400)
    session.status = PTSession.Status.CANCELLED
    session.cancelled_at = timezone.now()
    session.cancel_reason = "Cancelled by you"
    session.save(update_fields=["status", "cancelled_at", "cancel_reason"])
    return Response(PTSessionSerializer(session).data)

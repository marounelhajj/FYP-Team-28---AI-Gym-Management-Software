from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from classes.models import ClassBooking, PTSession
from progress.models import EXERCISES, BodyMetric, WorkoutEntry

from .models import ClientGoal, LoggedExercise, SessionLog

# How a client's development is measured - shared by the coach's view of a
# client and the member's own "My progress".
#
#   * Strength: for each exercise, the best estimated 1-rep max on each day,
#     from the Epley formula, weight x (1 + reps / 30). Only sets of 1-12 reps
#     count towards it (the estimate gets unreliable past that); every set
#     counts towards volume (sets x reps x kg). Both the coach's session logs
#     and the member's own log feed it. A day that beats every earlier day is
#     a personal record.
#   * Body weight: the member's own weigh-ins and the weights the coach
#     measured in sessions (the coach's wins on a day with both).
#   * Goals: progress from where the client stood when the goal was set to
#     the target, using the best lift since then or the latest weight.
#   * Attendance: of the last ATTENDANCE_DAYS, private sessions and classes
#     attended against those booked.

KG = Decimal("0.1")
MAX_E1RM_REPS = 12
ATTENDANCE_DAYS = 90
MAX_POINTS = 100


def name_key(name):
    return " ".join(name.split()).lower()


# "squat" and "Squat " are the same exercise; a listed one keeps the list's spelling.
LISTED = {name_key(name): name for name in EXERCISES}


def epley(weight, reps):
    if not weight or not reps or reps > MAX_E1RM_REPS:
        return None
    if reps == 1:
        return Decimal(weight).quantize(KG)
    return (Decimal(weight) * (1 + Decimal(reps) / 30)).quantize(KG, rounding=ROUND_HALF_UP)


def _num(value):
    return None if value is None else f"{Decimal(value).quantize(KG)}"


def set_summary(sets, reps, weight):
    return f"{sets} × {reps}" + (f" @ {Decimal(weight).normalize():f} kg" if weight else "")


# Every strength set the member did: (date, exercise name, sets, reps, kg, source).
def _strength_sets(member):
    for w in WorkoutEntry.objects.filter(member=member, kind=WorkoutEntry.Kind.STRENGTH):
        yield w.performed_on, w.exercise, w.sets, w.reps, w.weight_kg, "self"
    rows = LoggedExercise.objects.filter(log__member=member, kind=WorkoutEntry.Kind.STRENGTH).select_related("log__session")
    for e in rows:
        yield timezone.localtime(e.log.session.starts_at).date(), e.exercise, e.sets, e.reps, e.weight_kg, "coach"


# {exercise key: {"name", "points": [...] oldest first}} - one point per day.
def strength_history(member):
    days = {}
    for day, name, sets, reps, weight, source in _strength_sets(member):
        if not sets or not reps:
            continue
        key = name_key(name)
        entry = days.setdefault(key, {"name": LISTED.get(key) or " ".join(name.split()), "days": {}})
        point = entry["days"].setdefault(day, {"date": day, "e1rm": None, "volume": Decimal(0), "best": "", "sources": set()})
        point["sources"].add(source)
        if weight:
            point["volume"] += Decimal(sets) * reps * Decimal(weight)
        estimate = epley(weight, reps)
        if estimate is not None and (point["e1rm"] is None or estimate > point["e1rm"]):
            point["e1rm"], point["best"] = estimate, set_summary(sets, reps, weight)
    history = {}
    for key, entry in days.items():
        points, best = [], None
        for day in sorted(entry["days"]):
            p = entry["days"][day]
            record = p["e1rm"] is not None and (best is None or p["e1rm"] > best)
            if record:
                best = p["e1rm"]
            points.append({**p, "record": record and len(points) > 0})
        history[key] = {"name": entry["name"], "points": points[-MAX_POINTS:], "best": best}
    return history


def strength_payload(history):
    result = []
    for entry in history.values():
        weighted = [p for p in entry["points"] if p["e1rm"] is not None]
        if not weighted:
            continue
        first, last = weighted[0]["e1rm"], weighted[-1]["e1rm"]
        result.append({
            "exercise": entry["name"],
            "sessions": len(entry["points"]),
            "best": _num(entry["best"]),
            "latest": _num(last),
            "change": _num(last - first),
            "records": sum(1 for p in entry["points"] if p["record"]),
            "points": [
                {"date": p["date"], "e1rm": _num(p["e1rm"]), "volume": _num(p["volume"]), "bestSet": p["best"],
                 "record": p["record"], "source": "coach" if "coach" in p["sources"] else "self"}
                for p in weighted
            ],
        })
    # The exercises trained most often first.
    return sorted(result, key=lambda e: (-e["sessions"], e["exercise"].lower()))


# Body weight by day, oldest first: [{date, kg, source}].
def body_weight_history(member):
    by_day = {m.measured_on: (m.weight_kg, "self") for m in BodyMetric.objects.filter(member=member)}
    for log in SessionLog.objects.filter(member=member, body_weight_kg__isnull=False).select_related("session"):
        by_day[timezone.localtime(log.session.starts_at).date()] = (log.body_weight_kg, "coach")
    return [{"date": day, "kg": kg, "source": source} for day, (kg, source) in sorted(by_day.items())][-MAX_POINTS:]


def current_value(kind, exercise, member, since=None, strength=None, weights=None):
    if kind == ClientGoal.Kind.STRENGTH:
        entry = (strength if strength is not None else strength_history(member)).get(name_key(exercise))
        if not entry:
            return None
        values = [p["e1rm"] for p in entry["points"] if p["e1rm"] is not None and (since is None or p["date"] >= since)]
        return max(values) if values else None
    if kind == ClientGoal.Kind.BODY_WEIGHT:
        weights = weights if weights is not None else body_weight_history(member)
        return weights[-1]["kg"] if weights else None
    return None


def goal_payload(goal, strength, weights, today=None):
    today = today or timezone.localdate()
    set_on = timezone.localtime(goal.created_at).date()
    current = current_value(goal.kind, goal.exercise, goal.member, since=set_on, strength=strength, weights=weights)
    baseline = goal.start_value
    if baseline is None and goal.kind == ClientGoal.Kind.STRENGTH:
        entry = strength.get(name_key(goal.exercise))
        later = [p["e1rm"] for p in (entry["points"] if entry else []) if p["e1rm"] is not None and p["date"] >= set_on]
        baseline = later[0] if later else None
    elif baseline is None and goal.kind == ClientGoal.Kind.BODY_WEIGHT:
        later = [w["kg"] for w in weights if w["date"] >= set_on]
        baseline = later[0] if later else None

    percent, reached = None, None
    target = goal.target_value
    if goal.kind != ClientGoal.Kind.CUSTOM and current is not None and target is not None:
        losing = goal.kind == ClientGoal.Kind.BODY_WEIGHT and baseline is not None and target < baseline
        reached = current <= target if losing else current >= target
        if baseline is not None and target != baseline:
            percent = int(max(0, min(100, (current - baseline) / (target - baseline) * 100)))
        else:
            percent = 100 if reached else 0
    active = goal.status == ClientGoal.Status.ACTIVE
    return {
        "id": goal.id,
        "kind": goal.kind,
        "title": goal.title,
        "exercise": goal.exercise,
        "start": _num(baseline),
        "target": _num(target),
        "current": _num(current),
        "unit": "kg" if goal.kind != ClientGoal.Kind.CUSTOM else "",
        "percent": percent,
        "reached": reached,
        "targetDate": goal.target_date,
        "daysLeft": (goal.target_date - today).days,
        "overdue": active and goal.target_date < today and not reached,
        "status": goal.status,
        "closedOn": goal.closed_on,
        "note": goal.note,
        "setBy": goal.set_by.full_name if goal.set_by else None,
        "setOn": set_on,
    }


def goals_payload(member, strength, weights):
    goals = [goal_payload(g, strength, weights) for g in member.goals.select_related("set_by")]
    order = {ClientGoal.Status.ACTIVE: 0, ClientGoal.Status.ACHIEVED: 1, ClientGoal.Status.DROPPED: 2}
    return sorted(goals, key=lambda g: (order[g["status"]], str(g["targetDate"])))


def attendance(member, now=None):
    now = now or timezone.now()
    since = now - timedelta(days=ATTENDANCE_DAYS)
    pt = PTSession.objects.filter(member=member, status=PTSession.Status.BOOKED, ends_at__lte=now, starts_at__gte=since)
    classes = ClassBooking.objects.filter(
        member=member, status=ClassBooking.Status.BOOKED, gym_class__status="Scheduled",
        gym_class__ends_at__lte=now, gym_class__starts_at__gte=since,
    )
    attended = ClassBooking.Attendance.ATTENDED
    no_show = ClassBooking.Attendance.NO_SHOW
    return {
        "days": ATTENDANCE_DAYS,
        "privateSessions": {"booked": pt.count(), "attended": pt.filter(attendance=attended).count(),
                            "noShows": pt.filter(attendance=no_show).count()},
        "classes": {"booked": classes.count(), "attended": classes.filter(attendance=attended).count(),
                    "noShows": classes.filter(attendance=no_show).count()},
    }


def exercise_payload(e):
    return {
        "exercise": e.exercise, "kind": e.kind, "sets": e.sets, "reps": e.reps,
        "weightKg": _num(e.weight_kg) if e.weight_kg is not None else None,
        "durationMinutes": e.duration_minutes,
        "distanceKm": f"{e.distance_km}" if e.distance_km is not None else None,
        "rpe": e.rpe, "note": e.note,
        "estimated1rm": _num(epley(e.weight_kg, e.reps)) if e.kind == WorkoutEntry.Kind.STRENGTH else None,
    }


# One session's log. for_coach=False leaves out the coach's private assessment.
def log_payload(log, for_coach, viewer=None, now=None):
    session = log.session
    start, end = timezone.localtime(session.starts_at), timezone.localtime(session.ends_at)
    data = {
        "id": log.id,
        "sessionId": session.id,
        "date": start.date(),
        "startTime": f"{start:%H:%M}",
        "endTime": f"{end:%H:%M}",
        "branch": session.branch,
        "coachName": log.coach.full_name,
        "subjective": log.subjective,
        "objective": log.objective,
        "plan": log.plan,
        "bodyWeightKg": _num(log.body_weight_kg),
        "sessionRpe": log.session_rpe,
        "exercises": [exercise_payload(e) for e in log.exercises.all()],
        "updatedAt": timezone.localtime(log.updated_at).strftime("%Y-%m-%d %H:%M"),
    }
    if for_coach:
        from .access import edit_problem
        data["assessment"] = log.assessment
        data["canEdit"] = viewer is not None and edit_problem(viewer, session, now) is None
    return data


def progress(member, for_coach, viewer=None, now=None):
    strength = strength_history(member)
    weights = body_weight_history(member)
    logs = SessionLog.objects.filter(member=member).select_related("session", "coach").prefetch_related("exercises")
    return {
        "member": {"id": member.id, "name": member.name, "branch": member.branch},
        "goals": goals_payload(member, strength, weights),
        "strength": strength_payload(strength),
        "bodyWeight": [{"date": w["date"], "kg": _num(w["kg"]), "source": w["source"]} for w in weights],
        "attendance": attendance(member, now),
        "logs": [log_payload(log, for_coach, viewer, now) for log in logs[:50]],
        "logCount": logs.count(),
    }

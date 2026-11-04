from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import get_staff_account
from classes.models import PTSession
from members.models import Member
from training.events import log_training_event
from training.models import TrainingEvent

from .models import EXERCISES, BodyMetric, WorkoutEntry
from .serializers import BodyMetricSerializer, WorkoutSerializer

# User story (SCRUM-60): "As a member, I want to log my own workouts and body
# metrics between sessions, so that my coach and the AI system have
# up-to-date data to base recommendations on."
#
# Members change only their own entries (the member is always the session's,
# never an id in the request). A coach can read - never change - the log of
# members they are *assigned* to. The data model has no explicit "my coach"
# field, so assigned means: the member has booked a private training session
# with that coach (classes.PTSession, past or upcoming, not cancelled). Group
# class coaches are not assigned - a class can hold twenty strangers.

HISTORY_LIMIT = 200


def _member(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


def _workout_payload(entry):
    return {
        "exercise": entry.exercise, "kind": entry.kind, "sets": entry.sets, "reps": entry.reps,
        "weightKg": str(entry.weight_kg) if entry.weight_kg is not None else None,
        "durationMinutes": entry.duration_minutes,
        "distanceKm": str(entry.distance_km) if entry.distance_km is not None else None,
        "date": entry.performed_on.isoformat(),
    }


def _metric_payload(metric):
    return {
        field: (str(getattr(metric, attr)) if getattr(metric, attr) is not None else None)
        for field, attr in [("weightKg", "weight_kg"), ("bodyFatPercent", "body_fat_percent"),
                            ("waistCm", "waist_cm"), ("chestCm", "chest_cm"), ("hipsCm", "hips_cm")]
    } | {"date": metric.measured_on.isoformat()}


# The free-text note stays out of the AI log: it can hold anything.
def _log(event_type, member, entry_id, payload):
    log_training_event(event_type, member=member, session_id=str(entry_id), payload=payload)


def _exercises():
    return [{"name": name, "kind": kind} for name, kind in EXERCISES.items()]


# GET  /api/members/me/workouts - the member's own workouts, newest first, and the exercise list.
# POST /api/members/me/workouts - log one: { date, exercise, kind?, sets?, reps?, weightKg?,
#                                  durationMinutes?, distanceKm?, note? }.
@api_view(["GET", "POST"])
def my_workouts(request):
    member, denied = _member(request)
    if denied:
        return denied
    if request.method == "POST":
        serializer = WorkoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        entry = serializer.save(member=member)
        _log(TrainingEvent.EventType.WORKOUT_LOGGED, member, entry.pk, _workout_payload(entry))
        return Response(WorkoutSerializer(entry).data, status=201)
    entries = member.workouts.all()[:HISTORY_LIMIT]
    return Response({"results": WorkoutSerializer(entries, many=True).data, "exercises": _exercises()})


# PATCH  /api/members/me/workouts/<id> - edit one of your own.
# DELETE /api/members/me/workouts/<id>
@api_view(["PATCH", "DELETE"])
def my_workout_detail(request, entry_id):
    member, denied = _member(request)
    if denied:
        return denied
    entry = WorkoutEntry.objects.filter(id=entry_id, member=member).first()
    if entry is None:
        return Response({"error": "Workout not found."}, status=404)
    if request.method == "DELETE":
        entry.delete()
        return Response(status=204)
    serializer = WorkoutSerializer(entry, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    return Response(WorkoutSerializer(serializer.save()).data)


# GET  /api/members/me/metrics - the member's body metrics, newest first.
# POST /api/members/me/metrics - { date, weightKg, bodyFatPercent?, waistCm?, chestCm?, hipsCm?, note? }.
@api_view(["GET", "POST"])
def my_metrics(request):
    member, denied = _member(request)
    if denied:
        return denied
    if request.method == "POST":
        serializer = BodyMetricSerializer(data=request.data, context={"member": member})
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        metric = serializer.save(member=member)
        _log(TrainingEvent.EventType.METRICS_LOGGED, member, metric.pk, _metric_payload(metric))
        return Response(BodyMetricSerializer(metric).data, status=201)
    metrics = member.body_metrics.all()[:HISTORY_LIMIT]
    return Response({"results": BodyMetricSerializer(metrics, many=True).data})


# PATCH  /api/members/me/metrics/<id>
# DELETE /api/members/me/metrics/<id>
@api_view(["PATCH", "DELETE"])
def my_metric_detail(request, metric_id):
    member, denied = _member(request)
    if denied:
        return denied
    metric = BodyMetric.objects.filter(id=metric_id, member=member).first()
    if metric is None:
        return Response({"error": "Measurement not found."}, status=404)
    if request.method == "DELETE":
        metric.delete()
        return Response(status=204)
    serializer = BodyMetricSerializer(metric, data=request.data, partial=True, context={"member": member})
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    return Response(BodyMetricSerializer(serializer.save()).data)


# --- the coach's read-only view ----------------------------------------------


def assigned_members(coach):
    ids = PTSession.objects.filter(coach=coach, status=PTSession.Status.BOOKED).values("member_id")
    return Member.objects.filter(id__in=ids).order_by("name")


def _coach(request):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return account, None


# GET /api/progress/clients - the signed-in coach's assigned members, with
# when each last logged something.
@api_view(["GET"])
def coach_clients(request):
    coach, denied = _coach(request)
    if denied:
        return denied
    results = []
    for m in assigned_members(coach):
        last_workout = m.workouts.values_list("performed_on", flat=True).first()
        last_metric = m.body_metrics.values_list("measured_on", flat=True).first()
        results.append({
            "memberId": m.id, "name": m.name, "branch": m.branch,
            "workouts": m.workouts.count(), "lastWorkout": last_workout, "lastMetrics": last_metric,
        })
    return Response({"results": results})


# GET /api/progress/clients/<member_id> - that member's workouts and metrics,
# read-only. 403 unless the signed-in coach is assigned to the member.
@api_view(["GET"])
def coach_client_detail(request, member_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    member = assigned_members(coach).filter(id=member_id).first()
    if member is None:
        return Response({"error": "You can only see the training log of members you coach."}, status=403)
    return Response({
        "member": {"id": member.id, "name": member.name, "branch": member.branch},
        "workouts": WorkoutSerializer(member.workouts.all()[:HISTORY_LIMIT], many=True).data,
        "metrics": BodyMetricSerializer(member.body_metrics.all()[:HISTORY_LIMIT], many=True).data,
        "readOnly": True,
    })

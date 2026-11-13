from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.models import StaffAccount
from administration.permissions import get_staff_account
from classes.models import ClassBooking, PTSession
from classes.serializers import PTSessionSerializer
from members.models import Member
from progress.models import EXERCISES
from training.events import log_training_event
from training.models import TrainingEvent

from . import progress
from .access import EDIT_DAYS, coaches_member, edit_problem
from .models import ClientGoal, LoggedExercise, SessionLog
from .serializers import GoalSerializer, SessionLogSerializer

# User story: "As a coach, I want to log client workout sessions and progress
# notes, so that I can track each client's development over time."
#
#   GET/PUT/DELETE /api/coaching/pt-sessions/<id>/log - the coach logs a
#       private session: exercises, a SOAP note, optionally body weight.
#   GET  /api/coaching/clients/<id>/progress - a client's development: goals,
#       strength per exercise, body weight, attendance, every session's notes.
#   POST /api/coaching/clients/<id>/goals, PATCH /api/coaching/goals/<id>.
#   GET  /api/members/me/progress - the member's own, minus private assessments.
#
# Rules are in coaching/access.py. Logging a session marks it Attended - the
# coach's word over the automatic check-in match - and sends the exercises
# (never the notes) to the AI training-data log.

MAX_ACTIVE_GOALS = 10


def _coach(request):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    if account.job_title != StaffAccount.JobTitle.COACH:
        return None, Response({"error": "Only coaches keep client training logs."}, status=403)
    return account, None


def _exercise_choices():
    return [{"name": name, "kind": kind} for name, kind in EXERCISES.items()]


def _previous_plan(member, before):
    log = (
        SessionLog.objects.filter(member=member, session__starts_at__lt=before).exclude(plan="")
        .select_related("session", "coach").order_by("-session__starts_at").first()
    )
    if log is None:
        return None
    return {"date": timezone.localtime(log.session.starts_at).date(), "coachName": log.coach.full_name, "plan": log.plan}


def _last_exercises(member, before):
    log = (
        SessionLog.objects.filter(member=member, session__starts_at__lt=before).select_related("session")
        .prefetch_related("exercises").order_by("-session__starts_at").first()
    )
    return [progress.exercise_payload(e) for e in log.exercises.all()] if log else []


def _form_payload(coach, session):
    problem = edit_problem(coach, session)
    log = SessionLog.objects.filter(session=session).select_related("coach", "session").prefetch_related("exercises").first()
    return {
        "session": PTSessionSerializer(session).data,
        "member": {"id": session.member.id, "name": session.member.name},
        "log": progress.log_payload(log, True, coach) if log else None,
        "canEdit": problem is None,
        "cannotEditReason": problem[1] if problem else "",
        "editDays": EDIT_DAYS,
        "previousPlan": _previous_plan(session.member, session.starts_at),
        "lastExercises": _last_exercises(session.member, session.starts_at),
        "exerciseChoices": _exercise_choices(),
    }


def _save_log(coach, session, data):
    with transaction.atomic():
        # Locked, so a double tap on Save can't create the log twice.
        PTSession.objects.select_for_update().get(pk=session.pk)
        log, _ = SessionLog.objects.update_or_create(
            session=session,
            defaults={
                "member": session.member, "coach": coach,
                "subjective": data.get("subjective", ""), "objective": data.get("objective", ""),
                "assessment": data.get("assessment", ""), "plan": data.get("plan", ""),
                "body_weight_kg": data.get("bodyWeightKg"), "session_rpe": data.get("sessionRpe"),
            },
        )
        log.exercises.all().delete()
        LoggedExercise.objects.bulk_create([
            LoggedExercise(
                log=log, order=i, exercise=e["exercise"], kind=e["kind"], sets=e.get("sets"), reps=e.get("reps"),
                weight_kg=e.get("weightKg"), duration_minutes=e.get("durationMinutes"),
                distance_km=e.get("distanceKm"), rpe=e.get("rpe"), note=e.get("note", ""),
            )
            for i, e in enumerate(data.get("exercises", []))
        ])
        PTSession.objects.filter(pk=session.pk).update(attendance=ClassBooking.Attendance.ATTENDED)
    log_training_event(
        TrainingEvent.EventType.SESSION_LOGGED, member=session.member, branch=session.branch, trainer=coach,
        session_id=f"pt:{session.pk}", occurred_at=session.starts_at,
        payload={
            "exercises": [
                {k: (str(v) if v is not None and k in ("weightKg", "distanceKm") else v)
                 for k, v in e.items() if k in ("exercise", "kind", "sets", "reps", "weightKg", "durationMinutes", "distanceKm", "rpe")}
                for e in data.get("exercises", [])
            ],
            "sessionRpe": data.get("sessionRpe"),
            "bodyWeightKg": str(data["bodyWeightKg"]) if data.get("bodyWeightKg") is not None else None,
        },
    )
    return log


@api_view(["GET", "PUT", "DELETE"])
def session_log(request, session_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    session = PTSession.objects.select_related("coach", "member").filter(id=session_id).first()
    if session is None:
        return Response({"error": f"Session {session_id} not found."}, status=404)
    if session.coach_id != coach.id:
        return Response({"error": "Only the coach of this session can log it."}, status=403)
    if request.method == "GET":
        return Response(_form_payload(coach, session))

    problem = edit_problem(coach, session)
    if problem:
        return Response({"error": problem[1]}, status=problem[0])
    if request.method == "DELETE":
        deleted, _ = SessionLog.objects.filter(session=session).delete()
        if not deleted:
            return Response({"error": "This session hasn't been logged."}, status=404)
        return Response(_form_payload(coach, session))

    serializer = SessionLogSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    _save_log(coach, session, serializer.validated_data)
    return Response(_form_payload(coach, session))


def _client(request, member_id):
    coach, denied = _coach(request)
    if denied:
        return None, None, denied
    member = coaches_member(coach, member_id)
    if member is None:
        return None, None, Response({"error": "You can only see the progress of members you coach."}, status=403)
    return coach, member, None


@api_view(["GET"])
def client_progress(request, member_id):
    coach, member, denied = _client(request, member_id)
    if denied:
        return denied
    return Response({
        **progress.progress(member, for_coach=True, viewer=coach),
        "goalKinds": [{"value": v, "label": label} for v, label in ClientGoal.Kind.choices],
        "exerciseChoices": _exercise_choices(),
        "maxActiveGoals": MAX_ACTIVE_GOALS,
    })


def _goal_response(goal, status=200):
    member = goal.member
    strength, weights = progress.strength_history(member), progress.body_weight_history(member)
    return Response(progress.goal_payload(goal, strength, weights), status=status)


@api_view(["POST"])
def add_goal(request, member_id):
    coach, member, denied = _client(request, member_id)
    if denied:
        return denied
    serializer = GoalSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        if member.goals.filter(status=ClientGoal.Status.ACTIVE).count() >= MAX_ACTIVE_GOALS:
            return Response({"error": f"{member.name} already has {MAX_ACTIVE_GOALS} active goals - close one first."}, status=409)
        start = progress.current_value(data["kind"], data["exercise"], member)
        if start is not None and data["targetValue"] is not None:
            already = (start >= data["targetValue"]) if data["kind"] == ClientGoal.Kind.STRENGTH else start == data["targetValue"]
            if already:
                return Response({"error": {"targetValue": [f"{member.name.split()[0]} is already at {start} kg - set a target beyond it."]}}, status=400)
        goal = ClientGoal.objects.create(
            member=member, set_by=coach, kind=data["kind"], title=data["title"], exercise=data["exercise"],
            start_value=start, target_value=data["targetValue"], target_date=data["targetDate"],
            note=data.get("note", ""),
        )
    return _goal_response(goal, status=201)


@api_view(["PATCH"])
def goal_detail(request, goal_id):
    coach, denied = _coach(request)
    if denied:
        return denied
    goal = ClientGoal.objects.select_related("member", "set_by").filter(id=goal_id).first()
    if goal is None or coaches_member(coach, goal.member_id) is None:
        return Response({"error": "Goal not found."}, status=404)
    if "kind" in request.data and request.data["kind"] != goal.kind:
        return Response({"error": {"kind": ["A goal's type can't change - add a new goal instead."]}}, status=400)
    serializer = GoalSerializer(goal, data={**request.data, "kind": goal.kind}, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    status = data.get("status", goal.status)
    if status == ClientGoal.Status.ACTIVE and goal.status != ClientGoal.Status.ACTIVE:
        if goal.member.goals.filter(status=ClientGoal.Status.ACTIVE).count() >= MAX_ACTIVE_GOALS:
            return Response({"error": f"There are already {MAX_ACTIVE_GOALS} active goals."}, status=409)
    goal.title = data.get("title", goal.title)
    goal.exercise = data.get("exercise", goal.exercise)
    goal.target_value = data.get("targetValue", goal.target_value)
    goal.target_date = data.get("targetDate", goal.target_date)
    goal.note = data.get("note", goal.note)
    if status != goal.status:
        goal.closed_on = None if status == ClientGoal.Status.ACTIVE else timezone.localdate()
        goal.status = status
    goal.save()
    return _goal_response(goal)


# GET /api/members/me/progress - the member's own progress: their goals, their
# strength and weight over time, and what their coaches logged (exercises,
# how they felt, what was done, the plan - not the coaches' assessments).
@api_view(["GET"])
def my_progress(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)
    return Response(progress.progress(member, for_coach=False))

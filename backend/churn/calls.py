from datetime import date

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from headcount.views import resolve_branch
from members.models import Member
from training.events import log_training_event
from training.models import TrainingEvent

from .features import week_start
from .models import ChurnScore, RetentionCall
from .reasons import explain

# Logging retention calls (SCRUM-68).
#
# Staff with log_retention_calls (receptionists and branch managers) log a
# call from the at-risk list: the outcome, an optional note and an optional
# follow-up date. The rules:
#
#   * Reached / Saved / Cancelled anyway: the member was contacted, so they
#     come off this week's active call list.
#   * No answer: they stay on the list until the end of the week, so the
#     call can be tried again.
#   * "Cancelled anyway" only records what the member said; the membership
#     itself is cancelled through the usual front-desk flow.
#
# Each call is written to the audit log (SCRUM-124) and to the AI training
# data (SCRUM-73) as a "retention_call" event carrying the member's score,
# level, reasons and scoring method at the time - the labelled data for a
# future model. Notes stay out of the training event (they're free text and
# could hold personal details).

LOG = "log_retention_calls"
VIEW = "view_at_risk_members"
MANAGE = "manage_at_risk_list"
NOTE_MAX = 500


def call_data(call):
    return {
        "id": call.pk,
        "outcome": call.outcome,
        "outcomeLabel": call.get_outcome_display(),
        "note": call.note,
        "followUpOn": call.follow_up_on,
        "calledAt": call.called_at,
        "calledBy": call.called_by_name,
        "weekStart": call.week_start,
        "level": call.level,
        "reasons": [r["text"] for r in call.reasons if isinstance(r, dict) and "text" in r],
    }


# {member_id: [calls this week, newest first]} for a branch-week.
def calls_this_week(branch, monday):
    out = {}
    for call in RetentionCall.objects.filter(branch=branch, week_start=monday).order_by("-called_at", "-id"):
        out.setdefault(call.member_id, []).append(call)
    return out


def contacted(calls):
    return any(c.contacted for c in calls)


def _parse(body):
    errors = {}
    outcome = (body.get("outcome") or "").strip()
    if outcome not in RetentionCall.Outcome.values:
        errors["outcome"] = f"Choose one of: {', '.join(RetentionCall.Outcome.labels)}."
    note = (body.get("note") or "").strip()
    if len(note) > NOTE_MAX:
        errors["note"] = f"Keep the note under {NOTE_MAX} characters."
    follow_up = body.get("followUpOn") or None
    if follow_up:
        try:
            follow_up = date.fromisoformat(str(follow_up))
        except ValueError:
            errors["followUpOn"] = "Use a date like 2026-11-20."
        else:
            if follow_up < timezone.localdate():
                errors["followUpOn"] = "The follow-up date can't be in the past."
    return outcome, note, follow_up, errors


# POST /api/churn/calls {memberId, outcome, note?, followUpOn?}
@api_view(["POST"])
def log_call(request):
    account, denied = authorize(request, LOG)
    if denied:
        return denied
    body = request.data or {}
    try:
        member = Member.objects.get(pk=int(body.get("memberId")))
    except (Member.DoesNotExist, TypeError, ValueError):
        return Response({"error": "Member not found."}, status=404)
    _, _, error = resolve_branch(account, member.branch, subject="at-risk members")
    if error:
        return error

    outcome, note, follow_up, errors = _parse(body)
    if errors:
        return Response({"error": errors}, status=400)

    monday = week_start(timezone.localdate())
    entry = (ChurnScore.objects.filter(member=member, branch=member.branch, week_start=monday)
             .select_related("run").first())
    if entry is None:
        return Response({"error": f"{member.name} isn't on this week's at-risk list."}, status=400)

    reasons = explain(entry.reasons, entry.features, entry.run.as_of)
    call = RetentionCall.objects.create(
        member=member, branch=member.branch, week_start=monday, outcome=outcome, note=note, follow_up_on=follow_up,
        called_by=account, called_by_name=account.full_name, churn_score=entry, score=entry.score,
        level=entry.level, rank=entry.rank, method=entry.method, model_version=entry.model_version,
        reasons=[{"feature": r["feature"], **text} for r, text in zip(entry.reasons, reasons)],
    )
    record(
        request, AuditLog.Action.RETENTION_CALL_LOGGED, actor=account, target=member,
        summary=f"Logged a retention call to {member.name}: {call.get_outcome_display()}",
        details={"outcome": outcome, "followUpOn": follow_up.isoformat() if follow_up else None,
                 "weekStart": monday.isoformat(), "score": entry.score},
    )
    log_training_event(
        TrainingEvent.EventType.RETENTION_CALL, member=member, branch=member.branch, session_id=f"call:{call.pk}",
        payload={
            "callId": call.pk, "outcome": outcome, "contacted": call.contacted, "weekStart": monday.isoformat(),
            "score": entry.score, "level": entry.level, "rank": entry.rank, "method": entry.method,
            "modelVersion": entry.model_version, "reasons": [r["feature"] for r in entry.reasons],
            "followUp": follow_up is not None,
        },
    )
    return Response(call_data(call), status=201)


# GET /api/churn/members/<id>/calls - the member's call history, newest first.
@api_view(["GET"])
def member_calls(request, member_id):
    account, denied = authorize(request, VIEW, MANAGE, LOG, "manage_members")
    if denied:
        return denied
    try:
        member = Member.objects.get(pk=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)
    _, _, error = resolve_branch(account, member.branch, subject="retention calls")
    if error:
        return error
    calls = RetentionCall.objects.filter(member=member)
    return Response({"memberId": member.pk, "calls": [call_data(c) for c in calls]})

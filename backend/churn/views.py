from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from headcount.views import resolve_branch

from . import config
from .accuracy import branch_accuracy
from .calls import LOG, call_data, calls_this_week, contacted
from .features import week_start
from .models import BranchCallSettings, ChurnRun, ChurnScore, RetentionCall
from .reasons import explain
from .scoring import ensure_current, refresh_branch

# The At-Risk Members page (SCRUM-118).
#
# view_at_risk_members opens the list; manage_at_risk_list also lets the
# caller refresh it; log_retention_calls (SCRUM-68) lets them log calls. The branch rule is the same as every branch screen
# (headcount.views.resolve_branch): a branch manager only ever gets their own
# branch - asking for another is a 403 - and a role with view_all_branches
# (General Manager) picks any.

VIEW = "view_at_risk_members"
MANAGE = "manage_at_risk_list"
SUBJECT = "at-risk members"


def _run_data(run):
    model = run.model
    return {
        "id": run.pk,
        "weekStart": run.week_start,
        "asOf": run.as_of,
        "ranAt": run.ran_at,
        "trigger": run.trigger,
        "triggerLabel": run.get_trigger_display(),
        "triggeredBy": run.triggered_by.full_name if run.triggered_by else None,
        "method": run.method,
        "methodLabel": run.get_method_display(),
        "methodNote": run.method_note,
        "membersScored": run.members_scored,
        "model": None if model is None else {
            "version": model.version,
            "trainedAt": model.trained_at,
            "auc": model.metrics.get("auc"),
            "precisionAtN": model.metrics.get("precisionAtN"),
            "n": model.metrics.get("n"),
            "baseRate": model.metrics.get("baseRate"),
            "examples": model.examples,
            "cancellations": model.cancellations,
        },
    }


def member_row(score, calls=()):
    member = score.member
    return {
        "rank": score.rank,
        "memberId": member.pk,
        "name": member.name,
        "status": member.status,
        "score": score.score,
        "level": score.level,
        "method": score.method,
        # Plain language only: never the points or feature names (SCRUM-119).
        "reasons": explain(score.reasons, score.features, score.run.as_of),
        "lastVisit": score.features.get("last_visit"),
        "membershipEndsAt": member.subscription_expires_at,
        # SCRUM-68: calls logged this week, newest first.
        "callsThisWeek": [call_data(c) for c in calls],
    }


def list_payload(account, branch, branches, run):
    scores = (
        ChurnScore.objects.filter(run=run).select_related("member", "run").order_by("rank")
    )
    calls = calls_this_week(branch, run.week_start)
    active, below_cap, done = [], [], []
    for s in scores:
        member_calls = calls.get(s.member_id, [])
        row = member_row(s, member_calls)
        # Contacted this week (anything but "no answer"): off the active list.
        if contacted(member_calls):
            done.append(row)
        # SCRUM-120: the top `call_capacity` ranks are this week's calls;
        # everyone else stays visible, collapsed, below the cap.
        elif s.rank <= run.call_capacity:
            active.append(row)
        else:
            below_cap.append(row)
    permissions = account.role.permissions
    return {
        "branch": branch,
        "branches": branches,
        "canChooseBranch": len(branches) > 1,
        "canRefresh": MANAGE in permissions,
        "canLogCalls": LOG in permissions,
        "outcomes": [{"value": v, "label": l} for v, l in RetentionCall.Outcome.choices],
        "run": _run_data(run),
        "members": active,
        "belowCap": below_cap,
        "contacted": done,
        "capacity": {
            "weekly": run.call_capacity,
            "default": config.DEFAULT_CALL_CAPACITY,
            "max": config.MAX_CALL_CAPACITY,
            "canEdit": MANAGE in permissions,
        },
        "accuracy": branch_accuracy(branch),
    }


# GET /api/churn/at-risk?branch=Hamra
#     This week's ranked list, highest risk first. If the weekly job hasn't
#     made this week's list yet, it is made now.
@api_view(["GET"])
def at_risk_list(request):
    account, denied = authorize(request, VIEW, MANAGE, LOG)
    if denied:
        return denied
    branch, branches, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    run = ensure_current(branch)
    return Response(list_payload(account, branch, branches, run))


# POST /api/churn/refresh {"branch": "Hamra"}
#     "Refresh now": re-scores the branch and replaces this week's list.
@api_view(["POST"])
def refresh(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    branch, branches, error = resolve_branch(account, (request.data or {}).get("branch"), subject=SUBJECT)
    if error:
        return error
    run = refresh_branch(branch, trigger=ChurnRun.Trigger.MANUAL, staff=account)
    return Response(list_payload(account, branch, branches, run))



# PUT /api/churn/capacity {"branch": "Hamra", "weeklyCapacity": 5}
#     SCRUM-120: how many calls the branch's staff can make per week. Takes
#     effect on this week's list straight away (and on every list after).
@api_view(["PUT"])
def capacity(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    body = request.data or {}
    branch, branches, error = resolve_branch(account, body.get("branch"), subject=SUBJECT)
    if error:
        return error
    try:
        weekly = int(body.get("weeklyCapacity"))
    except (TypeError, ValueError):
        weekly = None
    if weekly is None or not 1 <= weekly <= config.MAX_CALL_CAPACITY:
        return Response(
            {"error": {"weeklyCapacity": f"Enter a whole number from 1 to {config.MAX_CALL_CAPACITY}."}}, status=400,
        )

    setting, _ = BranchCallSettings.objects.get_or_create(
        branch=branch, defaults={"weekly_capacity": config.DEFAULT_CALL_CAPACITY},
    )
    previous = setting.weekly_capacity
    setting.weekly_capacity = weekly
    setting.updated_by = account
    setting.save()
    run = ensure_current(branch)
    if run.week_start == week_start(timezone.localdate()):
        ChurnRun.objects.filter(branch=branch, week_start=run.week_start).update(call_capacity=weekly)
        run.refresh_from_db()
    if previous != weekly:
        record(
            request, AuditLog.Action.CALL_CAPACITY_UPDATED, actor=account, branch=branch,
            summary=f"Set {branch}'s weekly call capacity to {weekly} (was {previous})",
            details={"changes": {"weeklyCapacity": [previous, weekly]}},
        )
    return Response(list_payload(account, branch, branches, run))

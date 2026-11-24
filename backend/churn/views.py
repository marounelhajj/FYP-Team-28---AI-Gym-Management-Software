from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from headcount.views import resolve_branch

from .models import ChurnRun, ChurnScore
from .scoring import ensure_current, refresh_branch

# The At-Risk Members page (SCRUM-118).
#
# view_at_risk_members opens the list; manage_at_risk_list also lets the
# caller refresh it. The branch rule is the same as every branch screen
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


def member_row(score):
    member = score.member
    return {
        "rank": score.rank,
        "memberId": member.pk,
        "name": member.name,
        "status": member.status,
        "score": score.score,
        "level": score.level,
        "method": score.method,
        "reasons": score.reasons,
        "lastVisit": score.features.get("last_visit"),
        "membershipEndsAt": member.subscription_expires_at,
    }


def list_payload(account, branch, branches, run):
    scores = (
        ChurnScore.objects.filter(run=run).select_related("member").order_by("rank")
    )
    return {
        "branch": branch,
        "branches": branches,
        "canChooseBranch": len(branches) > 1,
        "canRefresh": MANAGE in account.role.permissions,
        "run": _run_data(run),
        "members": [member_row(s) for s in scores],
    }


# GET /api/churn/at-risk?branch=Hamra
#     This week's ranked list, highest risk first. If the weekly job hasn't
#     made this week's list yet, it is made now.
@api_view(["GET"])
def at_risk_list(request):
    account, denied = authorize(request, VIEW, MANAGE)
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


from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from checkins.models import AUTO_CHECKOUT_AFTER, CheckIn, close_stale_sessions
from members.models import Member

VIEW_PERMISSION = "view_branch_headcount"
# Lets a role pick any branch (General Manager). Without it, a role only
# ever sees the branch on its own staff account.
ALL_BRANCHES_PERMISSION = "view_all_branches"
# How often the dashboard polls - sent to the client so it isn't hardcoded twice.
REFRESH_SECONDS = 15


# Which branch the caller may see. Enforced here, not just in the UI: a
# Branch Manager asking for another branch gets 403, not that branch's data.
# Returns (branch, branches_they_can_pick, None) or (None, None, error).
def resolve_branch(account, requested):
    all_branches = list(Member.Branch.values)
    requested = (requested or "").strip()
    if requested and requested not in all_branches:
        return None, None, Response(
            {"error": f'Invalid branch "{requested}". Must be one of: {", ".join(all_branches)}'}, status=400,
        )

    if ALL_BRANCHES_PERMISSION in account.role.permissions:
        return requested or account.branch or all_branches[0], all_branches, None

    if not account.branch:
        return None, None, Response(
            {"error": "Your account isn't assigned to a branch yet. Ask a System Administrator to set one."},
            status=403,
        )
    if requested and requested != account.branch:
        return None, None, Response({"error": "You can only see headcount for your own branch."}, status=403)
    return account.branch, [account.branch], None


# Members inside a branch right now: allowed check-ins with no check-out yet.
# Stale sessions are closed first, so anyone in for over AUTO_CHECKOUT_AFTER
# has already been checked out automatically.
def current_headcount(branch, now=None):
    close_stale_sessions(now)
    return CheckIn.objects.filter(
        branch=branch, result=CheckIn.Result.ALLOWED, checked_out_at__isnull=True,
    ).count()


# GET /api/headcount/live?branch=Hamra
#
# How many members are inside one branch right now. A Branch Manager always
# gets their own branch (branch can be omitted); a General Manager
# (view_all_branches) can ask for any. 200 + {"branch", "count", "asOf",
# "branches", "canChooseBranch", "autoCheckoutHours", "refreshSeconds"}.
# The dashboard polls this every refreshSeconds.
#
# User story (SCRUM-127): "As a branch manager, I want to view live
# headcount for my branch on a dashboard, so that I can see how full the gym
# is right now."
@api_view(["GET"])
def live_headcount(request):
    account, denied = authorize(request, VIEW_PERMISSION)
    if denied:
        return denied

    branch, branches, error = resolve_branch(account, request.query_params.get("branch"))
    if error:
        return error

    now = timezone.now()
    return Response({
        "branch": branch,
        "count": current_headcount(branch, now),
        "asOf": now,
        "branches": branches,
        "canChooseBranch": len(branches) > 1,
        "autoCheckoutHours": int(AUTO_CHECKOUT_AFTER.total_seconds() // 3600),
        "refreshSeconds": REFRESH_SECONDS,
    })

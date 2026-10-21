from collections import defaultdict
from datetime import datetime, time, timedelta

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
# How many past same-weekdays the hourly chart averages over (SCRUM-129).
WEEKS_COMPARED = 6


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


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


# Headcount per hour for a set of days at one branch: for each (day, hour),
# how many different members were inside at any point during that hour.
# A session runs from check-in to check-out; a still-open session runs to
# `now` (stale ones were closed by close_stale_sessions first). Only counts
# leave this function - never who.
def hourly_counts(branch, days, now):
    if not days:
        return {}
    wanted = set(days)
    start = _day_start(min(days)) - AUTO_CHECKOUT_AFTER  # sessions running over midnight
    end = _day_start(max(days) + timedelta(days=1))
    sessions = CheckIn.objects.filter(
        branch=branch, result=CheckIn.Result.ALLOWED, checked_in_at__gte=start, checked_in_at__lt=end,
    ).values_list("member_id", "checked_in_at", "checked_out_at")

    inside = defaultdict(set)
    for member_id, checked_in_at, checked_out_at in sessions:
        session_end = min(checked_out_at or now, now)
        hour = timezone.localtime(checked_in_at).replace(minute=0, second=0, microsecond=0)
        while hour < session_end:
            if hour.date() in wanted:
                inside[(hour.date(), hour.hour)].add(member_id)
            hour += timedelta(hours=1)
    return {key: len(members) for key, members in inside.items()}


# GET /api/headcount/hourly?branch=Hamra
#
# Today's headcount hour by hour, next to the average for the same weekday
# over the last WEEKS_COMPARED weeks (only weeks since the branch's first
# check-in count, so a new branch isn't dragged down by empty weeks). Same
# branch rule and permission as /api/headcount/live.
#
# 200 + {"branch", "date", "weekday", "currentHour", "weeksCompared", "asOf",
#        "hours": [{"hour": 0-23, "today": int|null, "weekdayAverage": float|null}]}
# "today" is null for hours that haven't started yet; "weekdayAverage" is
# null when there are no past weeks to compare with. Aggregated counts only:
# no member ids or names anywhere in the response.
#
# User story (SCRUM-129): "As a branch manager, I want to view headcount by
# hour for the current day, so that I can see when my peaks actually fall."
@api_view(["GET"])
def hourly_headcount(request):
    account, denied = authorize(request, VIEW_PERMISSION)
    if denied:
        return denied

    branch, _, error = resolve_branch(account, request.query_params.get("branch"))
    if error:
        return error

    close_stale_sessions()
    now = timezone.now()
    today = timezone.localdate(now)
    current_hour = timezone.localtime(now).hour

    first = (
        CheckIn.objects.filter(branch=branch, result=CheckIn.Result.ALLOWED)
        .order_by("checked_in_at").values_list("checked_in_at", flat=True).first()
    )
    first_day = timezone.localdate(first) if first else today
    past_days = [
        day for day in (today - timedelta(weeks=week) for week in range(1, WEEKS_COMPARED + 1))
        if day >= first_day
    ]

    counts = hourly_counts(branch, [today, *past_days], now)
    hours = []
    for hour in range(24):
        average = None
        if past_days:
            average = round(sum(counts.get((day, hour), 0) for day in past_days) / len(past_days), 1)
        hours.append({
            "hour": hour,
            "today": counts.get((today, hour), 0) if hour <= current_hour else None,
            "weekdayAverage": average,
        })

    return Response({
        "branch": branch,
        "date": today,
        "weekday": today.strftime("%A"),
        "currentHour": current_hour,
        "weeksCompared": len(past_days),
        "asOf": now,
        "hours": hours,
    })

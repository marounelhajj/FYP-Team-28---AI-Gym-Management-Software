from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from checkins.models import CheckIn
from members.models import Member

from .models import BranchCapacity
from .views import WEEKS_COMPARED, current_headcount, hourly_counts

# User story (SCRUM-77): "As a member, I want to see how busy my branch is
# right now and at typical hours, so that I can plan my visit around peak
# times."
#
# Members never see a headcount, only a level: the share of the branch's
# capacity (SCRUM-128) that is inside, put into one of LEVELS. "Typical" is
# the historical average for each hour of a weekday over the last
# WEEKS_COMPARED weeks - the same aggregation as the branch manager's hourly
# chart (SCRUM-129, headcount.views.hourly_counts). There is no occupancy
# forecast model in the codebase yet; when one exists, swap it in for the
# average in _typical() and keep the same response.
#
# Nothing member-level leaves this module: hourly_counts only returns counts,
# and the response only carries level names, never a count or a share.

LEVELS = ["Quiet", "Moderate", "Busy", "Very busy"]
# Upper bounds (share of capacity) of the first three levels; anything at or
# above the last bound is "Very busy".
LEVEL_BOUNDS = [0.30, 0.60, 0.85]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def busy_level(count, capacity):
    share = count / capacity
    for index, bound in enumerate(LEVEL_BOUNDS):
        if share < bound:
            return index
    return len(LEVEL_BOUNDS)


def _level(index):
    return {"level": LEVELS[index], "levelIndex": index}


# The past same-weekdays to average: the last WEEKS_COMPARED dates that fall
# on `weekday` before today, and only those since the branch's first check-in.
def _past_days(branch, weekday, today):
    first = (
        CheckIn.objects.filter(branch=branch, result=CheckIn.Result.ALLOWED)
        .order_by("checked_in_at").values_list("checked_in_at", flat=True).first()
    )
    if first is None:
        return []
    first_day = timezone.localdate(first)
    back = (today.weekday() - weekday) % 7 or 7
    latest = today - timedelta(days=back)
    return [d for d in (latest - timedelta(weeks=w) for w in range(WEEKS_COMPARED)) if d >= first_day]


def _typical(branch, capacity, weekday, today, now):
    days = _past_days(branch, weekday, today)
    counts = hourly_counts(branch, days, now) if days else {}
    hours = []
    for hour in range(24):
        if not days:
            break
        average = sum(counts.get((day, hour), 0) for day in days) / len(days)
        # An hour nobody has used in the period is shown as closed, not "Quiet".
        if average == 0:
            continue
        hours.append({"hour": hour, **_level(busy_level(average, capacity))})
    return {"weekday": WEEKDAYS[weekday], "weekdayIndex": weekday, "weeksCompared": len(days), "hours": hours}


# GET /api/members/me/busy?branch=&weekday=0-6
#
# The signed-in member's home branch by default; any branch can be asked
# for. weekday defaults to today.
#
# 200 + {"branch", "homeBranch", "branches", "available", "now": {level, levelIndex} | null,
#        "asOf", "levels", "weekdays", "today", "typical": {weekday, weekdayIndex, weeksCompared,
#        "label": "Typical", hours: [{hour, level, levelIndex}]}}
# available is false (and now/typical empty) when the branch has no
# capacity set, since a level needs one.
@api_view(["GET"])
def my_branch_busy(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)

    branches = list(Member.Branch.values)
    branch = (request.query_params.get("branch") or member.branch).strip()
    if branch not in branches:
        return Response({"error": f'Invalid branch "{branch}". Must be one of: {", ".join(branches)}'}, status=400)

    now = timezone.now()
    today = timezone.localdate(now)
    weekday = request.query_params.get("weekday")
    if weekday in (None, ""):
        weekday = today.weekday()
    elif not (str(weekday).isdigit() and 0 <= int(weekday) <= 6):
        return Response({"error": "weekday must be 0 (Monday) to 6 (Sunday)."}, status=400)
    weekday = int(weekday)

    payload = {
        "branch": branch,
        "homeBranch": member.branch,
        "branches": branches,
        "asOf": timezone.localtime(now).strftime("%H:%M"),
        "levels": LEVELS,
        "weekdays": WEEKDAYS,
        "today": today.weekday(),
    }
    setting = BranchCapacity.objects.filter(branch=branch).first()
    if setting is None:
        return Response({**payload, "available": False, "now": None,
                         "typical": {"weekday": WEEKDAYS[weekday], "weekdayIndex": weekday, "weeksCompared": 0,
                                     "label": "Typical", "hours": []}})

    capacity = setting.max_capacity
    return Response({
        **payload,
        "available": True,
        "now": _level(busy_level(current_headcount(branch, now), capacity)),
        "typical": {**_typical(branch, capacity, weekday, today, now), "label": "Typical"},
    })

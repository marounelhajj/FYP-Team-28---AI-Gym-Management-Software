from collections import defaultdict

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from headcount.views import resolve_branch

from . import rules
from .models import ClassBooking, GymClass
from .serializers import GymClassSerializer
from .views import ALL_BRANCHES, EDIT, _parse_day, _week_payload, _with_counts

# User story (SCRUM-22): "As a general manager, I want to view the class
# reservation schedule for each branch, so that I can monitor class
# utilization and demand."
#
# Read-only. view_class_reservations is the General Manager's way in (they
# don't run a branch's calendar, so they don't have manage_class_schedule);
# a Branch Manager can see the same page for their own branch. Branch rule
# as everywhere else: view_all_branches picks any branch, otherwise only
# your own.
#
# Fill rate = booked spots / spots offered, over classes that weren't
# cancelled. Demand also counts the waitlist: members who wanted a spot in
# a full class and didn't get one. Attendance is only counted for classes
# that have ended.

VIEW_RESERVATIONS = "view_class_reservations"
SUBJECT = "class reservations"


def _percent(part, whole):
    return round(part * 100 / whole) if whole else None


def _with_reservation_counts(queryset):
    return _with_counts(queryset).annotate(
        attended_count=Count("bookings", filter=Q(bookings__status=ClassBooking.Status.BOOKED,
                                                  bookings__attendance=ClassBooking.Attendance.ATTENDED), distinct=True),
        no_show_count=Count("bookings", filter=Q(bookings__status=ClassBooking.Status.BOOKED,
                                                 bookings__attendance=ClassBooking.Attendance.NO_SHOW), distinct=True),
    )


# Totals over a list of annotated classes.
def _totals(classes):
    running = [c for c in classes if c.status == GymClass.Status.SCHEDULED]
    spots = sum(c.capacity for c in running)
    booked = sum(c.booked_count for c in running)
    attended = sum(c.attended_count for c in running)
    no_shows = sum(c.no_show_count for c in running)
    return {
        "classes": len(running),
        "cancelled": len(classes) - len(running),
        "spots": spots,
        "booked": booked,
        "fillPercent": _percent(booked, spots),
        "waitlisted": sum(c.waiting_count for c in running),
        "fullClasses": sum(1 for c in running if c.booked_count >= c.capacity),
        "attended": attended,
        "noShows": no_shows,
        "attendancePercent": _percent(attended, attended + no_shows),
    }


def _row(gym_class):
    return {
        **GymClassSerializer(gym_class).data,
        "fillPercent": _percent(gym_class.booked_count, gym_class.capacity),
        "attended": gym_class.attended_count,
        "noShows": gym_class.no_show_count,
        "ended": gym_class.ends_at <= timezone.now(),
    }


# GET /api/classes/reservations?week=YYYY-MM-DD&branch= - the week (Monday
#     to Sunday) containing `week` at one branch: every class with its
#     reservations (booked / spots, waitlist, attendance once it's over),
#     totals for the week, totals per class type, and the same week's totals
#     for each branch the caller can see, to compare them.
@api_view(["GET"])
def class_reservations(request):
    account, denied = authorize(request, VIEW_RESERVATIONS, EDIT)
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
    week = list(_with_reservation_counts(
        GymClass.objects.filter(branch__in=branches, starts_at__gte=window_start, starts_at__lt=window_end),
    ))
    by_branch = defaultdict(list)
    for c in week:
        by_branch[c.branch].append(c)
    here = by_branch[branch]

    by_type = defaultdict(list)
    for c in here:
        by_type[c.name].append(c)
    types = sorted(
        ({"name": name, **_totals(group)} for name, group in by_type.items()),
        key=lambda t: (-(t["fillPercent"] or 0), t["name"]),
    )

    return Response({
        "branch": branch,
        "branches": branches,
        "canSeeAllBranches": ALL_BRANCHES in account.role.permissions,
        **_week_payload(start),
        "summary": _totals(here),
        "byClassType": types,
        "branchSummaries": [{"branch": b, **_totals(by_branch[b])} for b in branches],
        "classes": [_row(c) for c in here],
    })

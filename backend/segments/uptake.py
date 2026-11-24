from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from classes.models import ClassBooking, PTSession
from retail.models import SaleItem

from .profiles import start_of
from .scope import MANAGE, VIEW, narrow
from .trends import _series
from .views import _today, _who

# Class and service uptake per segment (SCRUM-113).
#
# User story: "As a marketing staff member, I want to view class and service
# uptake per segment, so that I can see which offerings each group actually
# uses."
#
# Offerings: each class type, personal training, and each shop (point of
# sale) category. For each one, the share of the series' members who used it
# at least once in the date range, and the average uses per member. A cell
# is highlighted when the segment is well above or below the all-members
# figure: at least 1.5x (or at most two-thirds) AND at least 10 percentage
# points apart.

HIGHLIGHT_RATIO = 1.5
HIGHLIGHT_POINTS = 10
PT_OFFERING = "Personal training"
MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


def _usage(member_ids, start, end):
    """{offering: {member_id: uses}} for the given members and date range (inclusive)."""
    usage = defaultdict(lambda: defaultdict(int))
    lo, hi = start_of(start), start_of(end + timedelta(days=1))
    now = timezone.now()
    for member_id, type_name in ClassBooking.objects.filter(
        member_id__in=member_ids, attendance=ClassBooking.Attendance.ATTENDED,
        gym_class__starts_at__gte=lo, gym_class__starts_at__lt=hi,
    ).values_list("member_id", "gym_class__class_type__name"):
        usage[type_name][member_id] += 1
    for (member_id,) in PTSession.objects.filter(
        member_id__in=member_ids, starts_at__gte=lo, starts_at__lt=hi, starts_at__lte=now,
    ).exclude(status=PTSession.Status.CANCELLED).exclude(
        attendance=ClassBooking.Attendance.NO_SHOW,
    ).values_list("member_id"):
        usage[PT_OFFERING][member_id] += 1
    for member_id, category, quantity in SaleItem.objects.filter(
        sale__member_id__in=member_ids, sale__voided_at__isnull=True, sale__sold_at__gte=lo, sale__sold_at__lt=hi,
    ).values_list("sale__member_id", "product__category", "quantity"):
        usage[f"Shop: {category}"][member_id] += quantity
    return usage


def _offering_kind(name):
    if name == PT_OFFERING:
        return "pt"
    if name.startswith("Shop: "):
        return "shop"
    return "class"


def compute_uptake(series, start, end):
    """series: [(key, name, [Profile])]; the first one is the all-members baseline."""
    all_ids = sorted({p.id for _, _, profiles in series for p in profiles})
    usage = _usage(all_ids, start, end)
    order = {"class": 0, "pt": 1, "shop": 2}
    offerings = sorted(usage, key=lambda o: (order[_offering_kind(o)], o))

    out_series = []
    baseline = None
    for key, name, profiles in series:
        ids = {p.id for p in profiles}
        size = len(ids)
        cells = {}
        for offering in offerings:
            users = [m for m in usage[offering] if m in ids]
            uses = sum(usage[offering][m] for m in users)
            pct = round(len(users) / size * 100, 1) if size else 0.0
            cells[offering] = {
                "users": len(users), "uptakePct": pct,
                "usesPerMember": round(uses / size, 2) if size else 0.0, "highlight": None,
            }
            if baseline is not None:
                base = baseline[offering]["uptakePct"]
                if pct >= base * HIGHLIGHT_RATIO and pct - base >= HIGHLIGHT_POINTS:
                    cells[offering]["highlight"] = "above"
                elif pct <= base / HIGHLIGHT_RATIO and base - pct >= HIGHLIGHT_POINTS:
                    cells[offering]["highlight"] = "below"
        if baseline is None:
            baseline = cells
        out_series.append({"key": key, "name": name, "size": size, "cells": cells})
    return {
        "from": start, "to": end,
        "offerings": [{"name": o, "kind": _offering_kind(o)} for o in offerings],
        "series": out_series,
    }


# --- API ---

def _date_range(request, today):
    def parse(name):
        raw = (request.query_params.get(name) or "").strip()
        if not raw:
            return None
        return date.fromisoformat(raw)

    try:
        start, end = parse("from"), parse("to")
    except ValueError:
        return None, None, Response({"error": "Dates must be YYYY-MM-DD."}, status=400)
    end = end or today
    start = start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        return None, None, Response({"error": "The start date must be before the end date."}, status=400)
    if (end - start).days >= MAX_RANGE_DAYS:
        return None, None, Response({"error": "Choose a range of a year or less."}, status=400)
    return start, end, None




# GET /api/segments/uptake?segments=1,2&branch=&from=&to=
@api_view(["GET"])
def uptake(request):
    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    branches, error = narrow(account, request.query_params.get("branch"))
    if error:
        return error
    today = _today()
    start, end, error = _date_range(request, today)
    if error:
        return error
    series, _, error = _series(request, branches, today)
    if error:
        return error
    return Response({"branches": branches, **compute_uptake(series, start, end)})

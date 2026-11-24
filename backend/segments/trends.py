from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import filters as seg_filters
from .scope import MANAGE, VIEW, narrow
from .views import MAX_COMPARE, _get_segment, _profiles, _today, _who

# Attendance trends by branch and segment (SCRUM-112).
#
# User story: "As a marketing staff member, I want to view attendance trends
# over time by branch and member segment, so that I can see where engagement
# is growing or falling."
#
# Visits per active member per week or month, so a bigger segment doesn't
# look more engaged just because it's bigger, with raw totals alongside. A
# visit is a day the member checked in or attended a class, counted once
# (profiles.py). "Active members" in a period = the series' members who had
# joined by the end of that period. Segment membership is today's: the
# chart shows how today's segment behaved over time. Up to 3 segments are
# compared with "All members" on one chart; each line shows its % change
# from the previous period.

WEEKS = 12
MONTHS = 6


def _month_start(d):
    return d.replace(day=1)


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def periods(granularity, today):
    """The last complete weeks (Mon-Sun) or months, oldest first: [(start, end, label)]."""
    out = []
    if granularity == "week":
        this_monday = today - timedelta(days=today.weekday())
        for i in range(WEEKS, 0, -1):
            start = this_monday - timedelta(weeks=i)
            end = start + timedelta(days=6)
            out.append((start, end, f"{start:%d %b}"))
    else:
        this_month = _month_start(today)
        for i in range(MONTHS, 0, -1):
            start = _add_months(this_month, -i)
            end = _add_months(start, 1) - timedelta(days=1)
            out.append((start, end, f"{start:%b %Y}"))
    return out


def _pct_change(new, old):
    if old in (None, 0):
        return None
    return round((new - old) / old * 100, 1)


def trend_series(name, profiles, spans, key=None):
    points = []
    for start, end, _ in spans:
        active = [p for p in profiles if p.join_date <= end]
        visits = sum(1 for p in active for d in p.visit_days if start <= d <= end)
        points.append({
            "activeMembers": len(active),
            "visits": visits,
            "visitsPerMember": round(visits / len(active), 2) if active else 0.0,
        })
    change = {"visitsPerMember": None, "visits": None}
    if len(points) >= 2:
        change = {
            "visitsPerMember": _pct_change(points[-1]["visitsPerMember"], points[-2]["visitsPerMember"]),
            "visits": _pct_change(points[-1]["visits"], points[-2]["visits"]),
        }
    return {"key": key, "name": name, "size": len(profiles), "points": points, "change": change}


def compute_trends(series, granularity, today=None):
    """series: [(key, name, [Profile])]."""
    today = today or timezone.localdate()
    spans = periods(granularity, today)
    return {
        "granularity": granularity,
        "periods": [{"start": s, "end": e, "label": label} for s, e, label in spans],
        "series": [trend_series(name, profiles, spans, key) for key, name, profiles in series],
    }


# --- API ---

def _series(request, branches, today, ids_param="segments"):
    """[(key, name, profiles)] with "All members" first, or an error response."""
    raw = (request.query_params.get(ids_param) or "").strip()
    ids = []
    for part in [p for p in raw.split(",") if p.strip()]:
        try:
            ids.append(int(part))
        except ValueError:
            return None, None, Response({"error": f"Invalid segment id: {part}"}, status=400)
    ids = list(dict.fromkeys(ids))
    if len(ids) > MAX_COMPARE:
        return None, None, Response({"error": f"Compare at most {MAX_COMPARE} segments at a time."}, status=400)
    profiles = _profiles(branches, today)
    out = [("all", "All members", seg_filters.apply(profiles, {}, today))]
    segments = []
    for segment_id in ids:
        segment, error = _get_segment(segment_id, branches)
        if error:
            return None, None, error
        segments.append(segment)
        out.append((segment.pk, segment.name, seg_filters.apply(profiles, segment.filters, today)))
    return out, segments, None


def _granularity(request):
    value = (request.query_params.get("period") or "week").strip()
    if value not in ("week", "month"):
        return None, Response({"error": 'period must be "week" or "month".'}, status=400)
    return value, None




# GET /api/segments/trends?segments=1,2&branch=&period=week|month
@api_view(["GET"])
def trends(request):
    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    branches, error = narrow(account, request.query_params.get("branch"))
    if error:
        return error
    granularity, error = _granularity(request)
    if error:
        return error
    today = _today()
    series, _, error = _series(request, branches, today)
    if error:
        return error
    return Response({"branches": branches, **compute_trends(series, granularity, today)})

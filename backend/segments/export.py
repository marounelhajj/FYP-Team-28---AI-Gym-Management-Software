import csv
import io

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.log import record
from audit.models import AuditLog

from . import filters as seg_filters
from .scope import EXPORT_MEMBERS, MANAGE, VIEW, narrow
from .trends import _granularity, _series, compute_trends
from .uptake import _date_range, compute_uptake
from .views import _get_segment, _profiles, _today, _who

# Export engagement data for a segment (SCRUM-114).
#
# User story: "As a marketing staff member, I want to export engagement data
# for a selected segment, so that I can use it in campaign planning."
#
# Two CSVs, both of the current filtered view and both written to the audit
# log (user, segment, filters, export type, row count):
#   * aggregate - the attendance-trend (SCRUM-112) and uptake (SCRUM-113)
#     numbers. Anyone who can see the analytics, held to their branch.
#   * members   - member id, first name, email, branch, plan, visits in the
#     range, last visit, churn risk level. Only roles with
#     export_segment_members (General Manager, Marketing Staff). Members who
#     opted out of marketing, and members whose data was deleted (SCRUM-62),
#     are never in it.


def _safe(value):
    # Spreadsheet formula injection: a cell starting with = + - @ is text.
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _csv_response(rows, filename):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow([_safe(v) for v in row])
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# GET /api/segments/export?type=aggregate&segments=1,2&branch=&period=&from=&to=
# GET /api/segments/export?type=members&segment=1&branch=&from=&to=
# SCRUM-114: a CSV of the current filtered view, written to the audit log.
@api_view(["GET"])
def export(request):
    kind = (request.query_params.get("type") or "aggregate").strip()
    if kind not in ("aggregate", "members"):
        return Response({"error": 'type must be "aggregate" or "members".'}, status=400)
    needed = (EXPORT_MEMBERS,) if kind == "members" else (VIEW, MANAGE)
    account, branches, error = _who(request, *needed)
    if error:
        return error
    branches, error = narrow(account, request.query_params.get("branch"))
    if error:
        return error
    today = _today()
    start, end, error = _date_range(request, today)
    if error:
        return error
    stamp = today.isoformat()

    if kind == "members":
        raw = (request.query_params.get("segment") or "").strip()
        if not raw.isdigit():
            return Response({"error": "Choose a segment to export."}, status=400)
        segment, error = _get_segment(int(raw), branches)
        if error:
            return error
        profiles = _profiles(branches, today)
        members = [
            p for p in seg_filters.apply(profiles, segment.filters, today)
            # Privacy: never members who opted out of marketing, or whose
            # data was deleted (anonymized) through SCRUM-62.
            if not p.opted_out and not p.anonymized
        ]
        members.sort(key=lambda p: p.id)
        rows = [["member_id", "first_name", "email", "branch", "plan", "visits_in_range", "last_visit", "risk_level"]]
        for p in members:
            visits = sum(1 for d in p.visit_days if start <= d <= end)
            rows.append([
                p.id, (p.name.split() or [""])[0], p.email, p.branch, p.plan, visits,
                p.last_visit.isoformat() if p.last_visit else "", p.risk_level or "",
            ])
        excluded = len(seg_filters.apply(profiles, segment.filters, today)) - len(members)
        details = {
            "exportType": kind, "segmentId": segment.pk, "segmentName": segment.name,
            "filters": segment.filters, "branches": branches, "from": start.isoformat(), "to": end.isoformat(),
            "rows": len(members), "excludedForPrivacy": excluded,
        }
        record(
            request, AuditLog.Action.SEGMENT_EXPORTED, actor=account, target=segment,
            summary=f'Exported the member list of "{segment.name}" ({len(members)} rows)',
            branch=branches[0] if len(branches) == 1 else None, details=details,
        )
        return _csv_response(rows, f"segment-{segment.pk}-members-{stamp}.csv")

    granularity, error = _granularity(request)
    if error:
        return error
    series, segments, error = _series(request, branches, today)
    if error:
        return error
    trend = compute_trends(series, granularity, today)
    up = compute_uptake(series, start, end)
    rows = [["section", "series", "period_or_offering", "from", "to", "active_members", "visits",
             "visits_per_member", "users", "uptake_pct", "uses_per_member"]]
    for s in trend["series"]:
        for period, point in zip(trend["periods"], s["points"]):
            rows.append(["attendance_trend", s["name"], period["label"], period["start"], period["end"],
                         point["activeMembers"], point["visits"], point["visitsPerMember"], "", "", ""])
    for s in up["series"]:
        for offering in up["offerings"]:
            cell = s["cells"][offering["name"]]
            rows.append(["uptake", s["name"], offering["name"], start, end, s["size"], "", "",
                         cell["users"], cell["uptakePct"], cell["usesPerMember"]])
    data_rows = len(rows) - 1
    record(
        request, AuditLog.Action.SEGMENT_EXPORTED, actor=account,
        target=segments[0] if len(segments) == 1 else None,
        summary=f"Exported segment engagement data ({data_rows} rows)",
        branch=branches[0] if len(branches) == 1 else None,
        details={
            "exportType": kind, "segmentIds": [s.pk for s in segments], "segmentNames": [s.name for s in segments],
            "filters": {"branches": branches, "period": granularity, "from": start.isoformat(), "to": end.isoformat()},
            "rows": data_rows,
        },
    )
    return _csv_response(rows, f"segment-engagement-{stamp}.csv")

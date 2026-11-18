from collections import defaultdict
from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from feedback.models import CoachFeedback
from members.models import Member
from payroll.pay import available_periods, period_key

from . import rules
from .models import AREAS, BranchSurvey, Complaint
from .rules import ALL_BRANCHES, MANAGE

# User story (SCRUM-23): "As a general manager, I want to view customer
# reviews, feedback, and suggestions across branches, so that I can identify
# recurring service issues ..." (the Jira title is cut off there).
#
# The company-wide counterpart of the branch manager's Member Feedback page:
# every branch side by side for one month, from the feedback members already
# leave - branch surveys (NPS, five service areas, comments), complaints,
# and coach ratings (SCRUM-40). Read-only; answering stays on Member Feedback.
#
# "Recurring" is spelled out so the page can say why something is flagged:
#   * a complaint category reported at RECURRING_BRANCHES or more branches,
#     or RECURRING_COUNT or more times in the month, anywhere;
#   * a service area averaging below WEAK_AREA (out of 5) at a branch, from
#     at least MIN_RATINGS ratings - one bad survey doesn't make a trend.

RECURRING_BRANCHES = 2
RECURRING_COUNT = 3
WEAK_AREA = 3.0
MIN_RATINGS = 3
FEED_LIMIT = 60
SUBJECT = "feedback across branches"


def _round(value):
    return None if value is None else round(value, 1)


def _month_end(start):
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _in_month(queryset, field, start, end):
    return queryset.filter(**{f"{field}__gte": rules._local(start), f"{field}__lt": rules._local(end + timedelta(days=1))})


def _branch_row(branch, start, end, previous_start, previous_end, now):
    surveys = rules._period_surveys(branch, start, end)
    score = rules.nps(surveys.values_list("nps", flat=True))
    before = rules.nps(rules._period_surveys(branch, previous_start, previous_end).values_list("nps", flat=True))
    averages = rules._averages(surveys)
    areas = {key: {"average": _round(averages[key][0]), "count": averages[key][1]} for key, _ in AREAS}
    rated = [(key, a["average"]) for key, a in areas.items() if a["average"] is not None]
    coach = _in_month(CoachFeedback.objects.filter(branch=branch), "session_ends_at", start, end).aggregate(
        average=Avg("rating"), count=Count("id"))
    counts = rules.complaint_counts(branch, start, end, now)
    return {
        "branch": branch,
        "nps": score["score"],
        "responses": score["responses"],
        "npsChange": score["score"] - before["score"] if score["score"] is not None and before["score"] is not None else None,
        "areas": areas,
        "weakestArea": min(rated, key=lambda r: r[1])[0] if rated else None,
        "coachAverage": _round(coach["average"]),
        "coachRatings": coach["count"],
        "complaints": {k: counts[k] for k in ("received", "resolved", "open", "inProgress", "overdue", "escalatedOpen")},
    }


def _company(branches, start, end):
    surveys = [s for b in branches for s in rules._period_surveys(b, start, end)]
    score = rules.nps(s.nps for s in surveys)
    areas = {}
    for key, _ in AREAS:
        values = [getattr(s, key) for s in surveys if getattr(s, key) is not None]
        areas[key] = {"average": _round(sum(values) / len(values)) if values else None, "count": len(values)}
    return {"nps": score["score"], "responses": score["responses"], "areas": areas}


def recurring_issues(branch_rows, start, end):
    complaints = _in_month(Complaint.objects.filter(branch__in=[r["branch"] for r in branch_rows]), "created_at", start, end)
    by_category = defaultdict(lambda: defaultdict(int))
    for row in complaints.values("category", "branch").annotate(n=Count("id")):
        by_category[row["category"]][row["branch"]] += row["n"]
    categories = []
    for category, per_branch in by_category.items():
        total = sum(per_branch.values())
        categories.append({
            "category": category,
            "label": Complaint.Category(category).label,
            "total": total,
            "branches": [{"branch": b, "count": n} for b, n in sorted(per_branch.items(), key=lambda kv: (-kv[1], kv[0]))],
            "recurring": len(per_branch) >= RECURRING_BRANCHES or total >= RECURRING_COUNT,
        })
    categories.sort(key=lambda c: (not c["recurring"], -c["total"], c["label"]))

    weak_areas = []
    for key, label in AREAS:
        weak = [
            {"branch": r["branch"], "average": r["areas"][key]["average"]}
            for r in branch_rows
            if r["areas"][key]["average"] is not None and r["areas"][key]["count"] >= MIN_RATINGS
            and r["areas"][key]["average"] < WEAK_AREA
        ]
        if weak:
            weak_areas.append({"key": key, "label": label, "branches": sorted(weak, key=lambda w: w["average"])})
    weak_areas.sort(key=lambda a: (-len(a["branches"]), a["label"]))
    return categories, weak_areas


# What members wrote this month, newest first, from every branch: survey
# comments (anonymous ones stay anonymous), coach-rating comments and
# complaint subjects.
def feed(branches, start, end):
    items = []
    surveys = BranchSurvey.objects.filter(branch__in=branches).exclude(comment="").select_related("member")
    for s in _in_month(surveys, "created_at", start, end)[:FEED_LIMIT]:
        hidden = s.anonymous or s.member is None
        items.append({
            "kind": "survey", "id": f"s{s.id}", "branch": s.branch, "at": s.created_at, "text": s.comment,
            "score": s.nps, "scale": 10, "who": None if hidden else s.member.name,
        })
    ratings = CoachFeedback.objects.filter(branch__in=branches).exclude(comment="").select_related("member", "coach")
    for f in _in_month(ratings, "session_ends_at", start, end).order_by("-created_at")[:FEED_LIMIT]:
        items.append({
            "kind": "coach", "id": f"c{f.id}", "branch": f.branch, "at": f.created_at, "text": f.comment,
            "score": f.rating, "scale": 5, "who": f.member.name, "about": f"{f.coach.full_name} · {f.session_name}",
        })
    complaints = Complaint.objects.filter(branch__in=branches).select_related("member")
    for c in _in_month(complaints, "created_at", start, end)[:FEED_LIMIT]:
        items.append({
            "kind": "complaint", "id": f"k{c.id}", "branch": c.branch, "at": c.created_at, "text": c.subject,
            "score": None, "scale": None, "who": c.member.name if c.member else None,
            "about": Complaint.Category(c.category).label, "status": c.status, "escalated": c.escalated_at is not None,
        })
    items.sort(key=lambda i: i["at"], reverse=True)
    for item in items:
        item["at"] = timezone.localtime(item["at"]).strftime("%Y-%m-%d %H:%M")
    return items[:FEED_LIMIT]


# GET /api/branch-feedback/overview?period=YYYY-MM - every branch's month
# side by side, the recurring issues, and what members wrote.
@api_view(["GET"])
def overview(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    if ALL_BRANCHES not in account.role.permissions:
        return Response({"error": "Only roles that see every branch can compare them."}, status=403)
    from .views import _month_before, _period

    period, error = _period(request)
    if error:
        return error
    start, end = period
    previous_start, previous_end = _month_before(start)
    now = timezone.now()
    branches = list(Member.Branch.values)
    rows = [_branch_row(b, start, end, previous_start, previous_end, now) for b in branches]
    categories, weak_areas = recurring_issues(rows, start, end)
    return Response({
        "period": {"key": period_key(start), "label": f"{start:%B %Y}", "start": start, "end": _month_end(start)},
        "periods": available_periods(),
        "areaLabels": [{"key": k, "label": label} for k, label in AREAS],
        "rules": {"recurringBranches": RECURRING_BRANCHES, "recurringCount": RECURRING_COUNT,
                  "weakArea": WEAK_AREA, "minRatings": MIN_RATINGS, "responseHours": rules.RESPONSE_HOURS},
        "company": {
            **_company(branches, start, end),
            "complaints": sum(r["complaints"]["received"] for r in rows),
            "openComplaints": sum(r["complaints"]["open"] + r["complaints"]["inProgress"] for r in rows),
            "overdue": sum(r["complaints"]["overdue"] for r in rows),
            "escalatedOpen": sum(r["complaints"]["escalatedOpen"] for r in rows),
        },
        "branches": rows,
        "recurringComplaints": categories,
        "weakAreas": weak_areas,
        "feed": feed(branches, start, end),
    })

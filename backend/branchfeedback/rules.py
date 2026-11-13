from datetime import datetime, time, timedelta

from django.db.models import Avg, Count
from django.utils import timezone

from checkins.models import CheckIn
from feedback.models import CoachFeedback
from .models import AREAS, BranchSurvey, Complaint

# The rules and numbers behind branch feedback, in one place.
#
#   * A member can rate a branch they have visited (an allowed check-in there)
#     in the last VISIT_DAYS, once every SURVEY_EVERY_DAYS per branch - so the
#     results come from real, recent visitors and one person can't flood them.
#   * A member can complain about their own branch, or one they've visited
#     recently, with up to MAX_UNRESOLVED complaints open at once.
#   * A complaint should get a first answer within RESPONSE_HOURS; after that
#     it's overdue. Safety complaints are urgent. A member can reply to a
#     resolved complaint within REOPEN_DAYS, which reopens it.
#   * Net Promoter Score: % promoters (9-10) minus % detractors (0-6), from
#     -100 to 100. Area scores are the average of the 1-5 ratings given.

SURVEY_EVERY_DAYS = 30
VISIT_DAYS = 60
MAX_UNRESOLVED = 5
RESPONSE_HOURS = 48
REOPEN_DAYS = 14
# Viewing and answering a branch's feedback (Branch Manager, General Manager,
# System Administrator); view_all_branches picks any branch.
MANAGE = "manage_member_feedback"
ALL_BRANCHES = "view_all_branches"


def visited_branches(member, now=None):
    now = now or timezone.now()
    return set(
        CheckIn.objects.filter(
            member=member, result=CheckIn.Result.ALLOWED, checked_in_at__gte=now - timedelta(days=VISIT_DAYS),
        ).exclude(branch="").values_list("branch", flat=True),
    )


def complaint_branches(member, now=None):
    return sorted(visited_branches(member, now) | {member.branch})


# (can survey, date they can next, last survey) per branch the member visited.
def survey_status(member, now=None):
    now = now or timezone.now()
    result = []
    for branch in sorted(visited_branches(member, now)):
        last = BranchSurvey.objects.filter(member=member, branch=branch).order_by("-created_at").first()
        next_at = last.created_at + timedelta(days=SURVEY_EVERY_DAYS) if last else None
        result.append({
            "branch": branch,
            "canSurvey": next_at is None or next_at <= now,
            "nextOn": timezone.localtime(next_at).date() if next_at and next_at > now else None,
            "lastOn": timezone.localtime(last.created_at).date() if last else None,
        })
    return result


def survey_problem(member, branch, now=None):
    now = now or timezone.now()
    if branch not in visited_branches(member, now):
        return 403, f"You can rate a branch you've visited in the last {VISIT_DAYS} days."
    last = BranchSurvey.objects.filter(member=member, branch=branch).order_by("-created_at").first()
    if last and last.created_at + timedelta(days=SURVEY_EVERY_DAYS) > now:
        next_on = timezone.localtime(last.created_at + timedelta(days=SURVEY_EVERY_DAYS)).date()
        return 409, f"You rated {branch} recently - you can rate it again from {next_on:%d %b %Y}."
    return None


def nps(scores):
    scores = list(scores)
    if not scores:
        return {"score": None, "responses": 0, "promoters": 0, "passives": 0, "detractors": 0}
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return {
        "score": round((promoters - detractors) * 100 / len(scores)),
        "responses": len(scores),
        "promoters": promoters,
        "passives": len(scores) - promoters - detractors,
        "detractors": detractors,
    }


def _local(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _period_surveys(branch, start, end):
    return BranchSurvey.objects.filter(branch=branch, created_at__gte=_local(start), created_at__lt=_local(end + timedelta(days=1)))


def _averages(surveys):
    aggregates = surveys.aggregate(**{f"{key}_avg": Avg(key) for key, _ in AREAS},
                                   **{f"{key}_n": Count(key) for key, _ in AREAS})
    return {key: (aggregates[f"{key}_avg"], aggregates[f"{key}_n"]) for key, _ in AREAS}


def _round(value):
    return None if value is None else round(value, 1)


def overdue(complaint, now=None):
    now = now or timezone.now()
    return (
        complaint.status != Complaint.Status.RESOLVED and complaint.first_response_at is None
        and complaint.created_at + timedelta(hours=RESPONSE_HOURS) < now
    )


def _hours(delta):
    return round(delta.total_seconds() / 3600, 1)


def complaint_counts(branch, start, end, now=None):
    now = now or timezone.now()
    unresolved = list(Complaint.objects.filter(branch=branch).exclude(status=Complaint.Status.RESOLVED))
    in_period = Complaint.objects.filter(branch=branch, created_at__gte=_local(start), created_at__lt=_local(end + timedelta(days=1)))
    answered = [c for c in in_period if c.first_response_at]
    return {
        "open": sum(1 for c in unresolved if c.status == Complaint.Status.OPEN),
        "inProgress": sum(1 for c in unresolved if c.status == Complaint.Status.IN_PROGRESS),
        "overdue": sum(1 for c in unresolved if overdue(c, now)),
        "urgentOpen": sum(1 for c in unresolved if c.urgent),
        "received": in_period.count(),
        "resolved": Complaint.objects.filter(
            branch=branch, resolved_at__gte=_local(start), resolved_at__lt=_local(end + timedelta(days=1)),
        ).count(),
        "averageFirstResponseHours": (
            round(sum(_hours(c.first_response_at - c.created_at) for c in answered) / len(answered), 1) if answered else None
        ),
        "byCategory": [
            {"category": row["category"], "count": row["n"]}
            for row in in_period.values("category").annotate(n=Count("id")).order_by("-n", "category")
        ],
    }


def survey_payload(s, show_member=True):
    hidden = s.anonymous or s.member is None or not show_member
    return {
        "id": s.id,
        "date": timezone.localtime(s.created_at).date(),
        "member": None if hidden else {"id": s.member.id, "name": s.member.name},
        "anonymous": s.anonymous,
        "nps": s.nps,
        "areas": {key: getattr(s, key) for key, _ in AREAS},
        "comment": s.comment,
    }


# Everything the branch manager's feedback page shows for one branch and month.
def summary(branch, start, end, previous_start, previous_end, trend_periods, now=None):
    now = now or timezone.now()
    surveys = _period_surveys(branch, start, end)
    previous = _period_surveys(branch, previous_start, previous_end)
    current_nps = nps(surveys.values_list("nps", flat=True))
    previous_nps = nps(previous.values_list("nps", flat=True))

    now_avg, before_avg = _averages(surveys), _averages(previous)
    areas = []
    for key, label in AREAS:
        average, count = now_avg[key]
        prev, _ = before_avg[key]
        areas.append({
            "key": key, "label": label, "average": _round(average), "count": count, "previousAverage": _round(prev),
            "change": _round(average - prev) if average is not None and prev is not None else None,
        })
    rated = [a for a in areas if a["average"] is not None]
    weakest = min(rated, key=lambda a: a["average"])["key"] if rated else None

    trend = []
    for key, label, p_start, p_end in trend_periods:
        values = nps(_period_surveys(branch, p_start, p_end).values_list("nps", flat=True))
        trend.append({"period": key, "label": label, "nps": values["score"], "responses": values["responses"]})

    coach_rows = (
        CoachFeedback.objects.filter(branch=branch, session_ends_at__gte=_local(start), session_ends_at__lt=_local(end + timedelta(days=1)))
        .values("coach_id", "coach__full_name").annotate(average=Avg("rating"), count=Count("id")).order_by("-count", "coach__full_name")
    )
    comments = surveys.exclude(comment="").select_related("member")[:50]
    return {
        "nps": {**current_nps, "previousScore": previous_nps["score"], "previousResponses": previous_nps["responses"]},
        "areas": areas,
        "weakestArea": weakest,
        "trend": trend,
        "comments": [survey_payload(s) for s in comments],
        "commentCount": surveys.exclude(comment="").count(),
        "complaints": complaint_counts(branch, start, end, now),
        "coachRatings": [
            {"coachId": r["coach_id"], "name": r["coach__full_name"], "average": round(r["average"], 1), "count": r["count"]}
            for r in coach_rows
        ],
    }


def message_payload(m, for_staff):
    if m.author_staff_id:
        author, role = (m.author_staff.full_name if m.author_staff else "Staff"), "staff"
    else:
        author, role = (m.author_member.name if m.author_member else "Member"), "member"
    data = {
        "id": m.id, "author": author, "role": role, "body": m.body,
        "at": timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M"),
    }
    if for_staff:
        data["internal"] = m.internal
    return data


def complaint_payload(c, for_staff, now=None, with_messages=True):
    now = now or timezone.now()
    messages = list(c.messages.all()) if with_messages else []
    if not for_staff:
        messages = [m for m in messages if not m.internal]
    resolved_recently = c.resolved_at and c.resolved_at + timedelta(days=REOPEN_DAYS) >= now
    data = {
        "id": c.id,
        "branch": c.branch,
        "category": c.category,
        "categoryLabel": Complaint.Category(c.category).label,
        "subject": c.subject,
        "description": c.description,
        "status": c.status,
        "urgent": c.urgent,
        "createdAt": timezone.localtime(c.created_at).strftime("%Y-%m-%d %H:%M"),
        "updatedAt": timezone.localtime(c.updated_at).strftime("%Y-%m-%d %H:%M"),
        "resolvedAt": timezone.localtime(c.resolved_at).strftime("%Y-%m-%d %H:%M") if c.resolved_at else None,
        "firstResponseHours": _hours(c.first_response_at - c.created_at) if c.first_response_at else None,
        "messages": [message_payload(m, for_staff) for m in messages],
        # A member can reply until it's resolved, and for a while after (which reopens it).
        "canReply": c.status != Complaint.Status.RESOLVED or bool(resolved_recently),
    }
    if for_staff:
        age = now - c.created_at
        data.update({
            "member": None if c.member is None else {"id": c.member.id, "name": c.member.name, "branch": c.member.branch},
            "ageHours": _hours(age),
            "overdue": overdue(c, now),
            "respondBy": timezone.localtime(c.created_at + timedelta(hours=RESPONSE_HOURS)).strftime("%Y-%m-%d %H:%M"),
            "messageCount": len(messages),
            "resolvedBy": c.resolved_by.full_name if c.resolved_by else None,
        })
    return data


def staff_to_notify(branch, urgent):
    from administration.models import StaffAccount

    found = []
    for account in StaffAccount.objects.filter(is_active=True).select_related("role"):
        permissions = account.role.permissions
        if MANAGE not in permissions:
            continue
        if account.branch == branch or (urgent and ALL_BRANCHES in permissions):
            found.append(account)
    return found

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize, get_staff_account
from classes import rules
from classes.models import ClassBooking, GymClass, PTSession
from members.models import Member

from .models import CoachFeedback

# User story (SCRUM-40): "As a member, I want to rate and leave feedback for
# my coach after a session, so that I can help improve service quality."
#
# A member can rate a class or private session only if they attended it (the
# attendance settled from check-ins or marked by the coach, see
# classes.rules.settle_attendance), and only within WINDOW_DAYS of it ending.
# Inside that window they can also change what they wrote; after it the
# rating is final. The member is always the session's - never an id in the
# request - so nobody can rate on someone else's behalf.

WINDOW_DAYS = 14
COMMENT_LIMIT = 500
HISTORY_LIMIT = 100


def _member(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


def _window_start(now):
    return now - timedelta(days=WINDOW_DAYS)


def _stamp(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _attended_bookings(member, now):
    return ClassBooking.objects.filter(
        member=member, status=ClassBooking.Status.BOOKED, attendance=ClassBooking.Attendance.ATTENDED,
        gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__ends_at__lte=now, gym_class__ends_at__gt=_window_start(now),
    ).select_related("gym_class__coach")


def _attended_pt(member, now):
    return rules.booked_pt().filter(
        member=member, attendance=ClassBooking.Attendance.ATTENDED,
        ends_at__lte=now, ends_at__gt=_window_start(now),
    ).select_related("coach")


def _to_rate(member, now):
    sessions = [
        {
            "kind": "class", "sessionId": b.gym_class_id, "name": b.gym_class.name,
            "coach": {"id": b.gym_class.coach_id, "name": b.gym_class.coach.full_name},
            "startsAt": _stamp(b.gym_class.starts_at), "endsAt": b.gym_class.ends_at,
            "rateBy": _stamp(b.gym_class.ends_at + timedelta(days=WINDOW_DAYS)),
        }
        for b in _attended_bookings(member, now).filter(feedback__isnull=True)
    ] + [
        {
            "kind": "pt", "sessionId": s.pk, "name": "Private training",
            "coach": {"id": s.coach_id, "name": s.coach.full_name},
            "startsAt": _stamp(s.starts_at), "endsAt": s.ends_at,
            "rateBy": _stamp(s.ends_at + timedelta(days=WINDOW_DAYS)),
        }
        for s in _attended_pt(member, now).filter(feedback__isnull=True)
    ]
    sessions.sort(key=lambda s: s["endsAt"], reverse=True)
    for s in sessions:
        del s["endsAt"]
    return sessions


def _editable(feedback, now):
    return feedback.session_ends_at > _window_start(now)


def _payload(feedback, now):
    return {
        "id": feedback.pk, "kind": feedback.kind, "sessionId": feedback.session_id,
        "name": feedback.session_name, "coachName": feedback.coach.full_name, "branch": feedback.branch,
        "sessionAt": _stamp(feedback.session_starts_at), "rating": feedback.rating, "comment": feedback.comment,
        "createdAt": _stamp(feedback.created_at), "editable": _editable(feedback, now),
    }


# The rating and comment from a request body, or an error message.
def _clean(data, partial=False):
    cleaned = {}
    if "rating" in data or not partial:
        rating = data.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            return None, "Choose a rating from 1 to 5 stars."
        cleaned["rating"] = rating
    if "comment" in data:
        comment = data.get("comment")
        if comment is None:
            comment = ""
        if not isinstance(comment, str):
            return None, "The comment must be text."
        comment = comment.strip()
        if len(comment) > COMMENT_LIMIT:
            return None, f"Keep the comment under {COMMENT_LIMIT} characters."
        cleaned["comment"] = comment
    if partial and not cleaned:
        return None, "Nothing to change."
    return cleaned, None


# GET  /api/members/me/feedback - the sessions the member can still rate,
#      newest first, and the ratings they've already left.
# POST /api/members/me/feedback - { kind: "class"|"pt", sessionId, rating 1-5, comment? }.
#      sessionId is the class id for a class, the session id for PT.
#      201 + the rating. 404 if it isn't a session they attended in the last
#      WINDOW_DAYS days, 409 if they've already rated it.
@api_view(["GET", "POST"])
def my_feedback(request):
    member, denied = _member(request)
    if denied:
        return denied
    rules.settle_attendance()
    now = timezone.now()

    if request.method == "GET":
        given = member.coach_feedback.select_related("coach")[:HISTORY_LIMIT]
        return Response({
            "toRate": _to_rate(member, now),
            "given": [_payload(f, now) for f in given],
            "windowDays": WINDOW_DAYS,
        })

    cleaned, error = _clean(request.data)
    if error:
        return Response({"error": error}, status=400)
    kind, session_id = request.data.get("kind"), request.data.get("sessionId")
    if kind not in ("class", "pt") or isinstance(session_id, bool) or not isinstance(session_id, int):
        return Response({"error": "Say which session you're rating."}, status=400)

    if kind == "class":
        booking = _attended_bookings(member, now).filter(gym_class_id=session_id).first()
        if booking is None:
            return _not_rateable(member, kind, session_id)
        c = booking.gym_class
        fields = {"class_booking": booking, "coach": c.coach, "branch": c.branch, "session_name": c.name,
                  "session_starts_at": c.starts_at, "session_ends_at": c.ends_at}
    else:
        session = _attended_pt(member, now).filter(pk=session_id).first()
        if session is None:
            return _not_rateable(member, kind, session_id)
        fields = {"pt_session": session, "coach": session.coach, "branch": session.branch,
                  "session_name": "Private training", "session_starts_at": session.starts_at,
                  "session_ends_at": session.ends_at}

    try:
        with transaction.atomic():
            feedback = CoachFeedback.objects.create(member=member, **fields, **cleaned)
    except IntegrityError:
        return Response({"error": "You've already rated this session."}, status=409)
    return Response(_payload(feedback, now), status=201)


# Why this session can't be rated, in words the member understands.
def _not_rateable(member, kind, session_id):
    if kind == "class":
        already = CoachFeedback.objects.filter(member=member, class_booking__gym_class_id=session_id).exists()
    else:
        already = CoachFeedback.objects.filter(member=member, pt_session_id=session_id).exists()
    if already:
        return Response({"error": "You've already rated this session."}, status=409)
    return Response({
        "error": f"You can only rate a session you attended, within {WINDOW_DAYS} days of it ending.",
    }, status=404)


# PATCH /api/members/me/feedback/<id> - { rating?, comment? }: change your
#       own rating while the window is open. 409 once it has closed.
@api_view(["PATCH"])
def my_feedback_detail(request, feedback_id):
    member, denied = _member(request)
    if denied:
        return denied
    feedback = member.coach_feedback.select_related("coach").filter(pk=feedback_id).first()
    if feedback is None:
        return Response({"error": "Rating not found."}, status=404)
    now = timezone.now()
    if not _editable(feedback, now):
        return Response({"error": f"Ratings can only be changed within {WINDOW_DAYS} days of the session."}, status=409)
    cleaned, error = _clean(request.data, partial=True)
    if error:
        return Response({"error": error}, status=400)
    for field, value in cleaned.items():
        setattr(feedback, field, value)
    feedback.save(update_fields=[*cleaned, "updated_at"])
    return Response(_payload(feedback, now))


# --- the coach's side --------------------------------------------------------

# User story (SCRUM-37): "As a coach, I want to view ratings and feedback left
# by my clients, so that I can improve my coaching approach."
#
# A coach only ever sees the ratings left for them. No permission is needed,
# the same as My Schedule and My Clients: the query is scoped to the
# signed-in staff account, so anyone else just gets an empty list.

COACH_LIMIT = 200
RECENT_DAYS = 30


def _average(queryset):
    value = queryset.aggregate(avg=Avg("rating"))["avg"]
    return None if value is None else round(value, 2)


# GET /api/feedback/me?rating=1-5&withComments=1 - the signed-in coach's
#     ratings: an overall summary (count, average, how many of each star, the
#     last RECENT_DAYS days), the average per class (and for private
#     training), and the ratings themselves, newest first. The filters only
#     narrow the list, never the summary.
@api_view(["GET"])
def coach_ratings(request):
    coach = get_staff_account(request)
    if coach is None:
        return Response({"error": "Not authenticated."}, status=401)

    mine = CoachFeedback.objects.filter(coach=coach)
    counts = dict(mine.order_by().values("rating").annotate(n=Count("id")).values_list("rating", "n"))
    recent = mine.filter(created_at__gte=timezone.now() - timedelta(days=RECENT_DAYS))
    by_session = (mine.values("session_name").annotate(count=Count("id"), average=Avg("rating"))
                  .order_by("-count", "session_name"))

    listed = mine.select_related("member")
    rating = request.query_params.get("rating")
    if rating:
        if rating not in {"1", "2", "3", "4", "5"}:
            return Response({"error": "rating must be 1 to 5."}, status=400)
        listed = listed.filter(rating=int(rating))
    if request.query_params.get("withComments") in ("1", "true"):
        listed = listed.exclude(comment="")

    return Response({
        "coach": {"id": coach.pk, "name": coach.full_name},
        "summary": {
            "count": sum(counts.values()),
            "average": _average(mine),
            "stars": {str(n): counts.get(n, 0) for n in range(5, 0, -1)},
            "recent": {"days": RECENT_DAYS, "count": recent.count(), "average": _average(recent)},
        },
        "bySession": [
            {"name": row["session_name"], "count": row["count"], "average": round(row["average"], 2)}
            for row in by_session
        ],
        "results": [
            {
                "id": f.pk, "kind": f.kind, "memberName": f.member.name, "sessionName": f.session_name,
                "sessionAt": _stamp(f.session_starts_at), "branch": f.branch, "rating": f.rating,
                "comment": f.comment, "createdAt": _stamp(f.created_at),
            }
            for f in listed[:COACH_LIMIT]
        ],
        "matching": listed.count(),
    })


# --- the general manager's side ---------------------------------------------

# User story: "As a general manager, I want to view personal trainer ratings
# by branch, so that I can inform staffing, coaching, and incentive
# decisions."
#
# Grouped by CoachFeedback.branch - where the session actually happened, not
# a coach's home branch - so a floating coach's sessions still land under
# whichever branch they were delivered at, same as everywhere else branch
# shows up on a rating/session. Every branch is always listed, even at zero
# (same idea as audit.views.retention_report and finance.views.financial_report),
# and each branch lists its coaches ranked by average rating (best first) so
# a GM can spot who to recognise or who needs coaching without digging.

RATINGS_PERMISSION = "view_coach_ratings"


# GET /api/feedback/report?branch= - every branch the caller can see (or
#     just one, narrowed with ?branch=), each with its overall rating count,
#     average and star breakdown, plus its coaches ranked by average rating.
@api_view(["GET"])
def ratings_by_branch(request):
    _, denied = authorize(request, RATINGS_PERMISSION)
    if denied:
        return denied

    requested = (request.query_params.get("branch") or "").strip()
    if requested and requested not in Member.Branch.values:
        return Response({
            "error": f'Invalid branch "{requested}". Must be one of: {", ".join(Member.Branch.values)}',
        }, status=400)
    branch_list = [requested] if requested else list(Member.Branch.values)

    all_ratings = CoachFeedback.objects.filter(branch__in=branch_list)

    branches = []
    for branch in branch_list:
        rows = all_ratings.filter(branch=branch)
        counts = dict(rows.order_by().values("rating").annotate(n=Count("id")).values_list("rating", "n"))
        by_coach = (rows.values("coach_id", "coach__full_name").annotate(count=Count("id"), average=Avg("rating"))
                    .order_by("-average", "-count", "coach__full_name"))
        branches.append({
            "branch": branch,
            "count": sum(counts.values()),
            "average": _average(rows),
            "stars": {str(n): counts.get(n, 0) for n in range(5, 0, -1)},
            "coaches": [
                {"id": row["coach_id"], "name": row["coach__full_name"], "count": row["count"],
                 "average": round(row["average"], 2)}
                for row in by_coach
            ],
        })

    return Response({
        "branches": branches,
        "totals": {"count": all_ratings.count(), "average": _average(all_ratings)},
    })

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

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

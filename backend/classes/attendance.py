from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import get_staff_account
from members.models import Member
from training.events import log_training_event
from training.models import TrainingEvent

from .models import ClassBooking, GymClass
from .serializers import DATETIME, GymClassSerializer

# User story (SCRUM-36): "As a coach, I want to mark attendance for my classes,
# so that the system keeps accurate participation records."
#
# Who may mark, enforced here rather than by a role permission (coaches hold
# none - see seed_staff):
#   * the class's own coach, from the moment it starts until
#     MARKING_WINDOW after it ends;
#   * a branch manager (manage_class_schedule) at that branch - or any branch
#     with view_all_branches - at any time after it starts, so a mistake
#     can still be fixed once the coach's window has closed.
# Nobody marks a class that hasn't started or was cancelled.
#
# A hand mark always wins over the automatic one: rules.settle_attendance
# only fills bookings that are still blank, so a coach's mark is never
# overwritten. Each change is written to the AI training-data log
# (SCRUM-73) as attended / no_show, once per change.

MARKING_WINDOW = timedelta(hours=24)
MANAGE = "manage_class_schedule"
ALL_BRANCHES = "view_all_branches"
OUTCOMES = {ClassBooking.Attendance.ATTENDED, ClassBooking.Attendance.NO_SHOW}


def _is_manager(account, gym_class):
    permissions = account.role.permissions
    return MANAGE in permissions and (ALL_BRANCHES in permissions or account.branch == gym_class.branch)


# (can_mark, why_not) for this account on this class right now.
def marking_state(account, gym_class, now=None):
    now = now or timezone.now()
    if gym_class.status == GymClass.Status.CANCELLED:
        return False, "This class was cancelled."
    if now < gym_class.starts_at:
        return False, "Attendance opens when the class starts."
    if _is_manager(account, gym_class):
        return True, ""
    if now > gym_class.ends_at + MARKING_WINDOW:
        return False, "Attendance closed 24 hours after the class ended. Ask a branch manager to change it."
    return True, ""


def _class_for(request, class_id):
    account = get_staff_account(request)
    if account is None:
        return None, None, Response({"error": "Not authenticated."}, status=401)
    gym_class = GymClass.objects.select_related("coach", "class_type").filter(id=class_id).first()
    if gym_class is None:
        return None, None, Response({"error": f"Class {class_id} not found."}, status=404)
    if gym_class.coach_id != account.id and not _is_manager(account, gym_class):
        return None, None, Response(
            {"error": "Only this class's coach or a branch manager at its branch can take attendance."}, status=403,
        )
    return account, gym_class, None


def _entry(booking):
    marked_at = booking.attendance_marked_at
    return {
        "bookingId": booking.id,
        "memberId": booking.member_id,
        "memberName": booking.member.name,
        "attendance": booking.attendance,
        "walkIn": booking.walk_in,
        "markedBy": booking.attendance_marked_by.full_name if booking.attendance_marked_by else None,
        "markedAt": timezone.localtime(marked_at).strftime(DATETIME) if marked_at else None,
    }


def _payload(account, gym_class):
    can_mark, reason = marking_state(account, gym_class)
    roster = (
        gym_class.bookings.filter(status=ClassBooking.Status.BOOKED)
        .select_related("member", "attendance_marked_by").order_by("member__name", "id")
    )
    entries = [_entry(b) for b in roster]
    return {
        "class": GymClassSerializer(gym_class).data,
        "roster": entries,
        "counts": {
            "booked": sum(1 for e in entries if not e["walkIn"]),
            "walkIns": sum(1 for e in entries if e["walkIn"]),
            "attended": sum(1 for e in entries if e["attendance"] == ClassBooking.Attendance.ATTENDED),
            "noShows": sum(1 for e in entries if e["attendance"] == ClassBooking.Attendance.NO_SHOW),
            "unmarked": sum(1 for e in entries if not e["attendance"]),
        },
        "canMark": can_mark,
        "cannotMarkReason": reason,
        "coachWindowClosesAt": timezone.localtime(gym_class.ends_at + MARKING_WINDOW).strftime(DATETIME),
        "isManager": _is_manager(account, gym_class),
    }


def _log(booking, gym_class, account, outcome):
    event = TrainingEvent.EventType.ATTENDED if outcome == ClassBooking.Attendance.ATTENDED else TrainingEvent.EventType.NO_SHOW
    log_training_event(
        event, member=booking.member, branch=gym_class.branch, trainer=gym_class.coach,
        session_id=str(booking.pk),
        payload={
            "classId": gym_class.pk, "className": gym_class.name, "source": "manual",
            "markedBy": "coach" if account.id == gym_class.coach_id else "manager", "walkIn": booking.walk_in,
        },
    )


def _mark(booking, gym_class, account, outcome):
    previous = booking.attendance
    booking.attendance = outcome
    booking.attendance_marked_by = account
    booking.attendance_marked_at = timezone.now()
    booking.save(update_fields=["attendance", "attendance_marked_by", "attendance_marked_at"])
    if previous != outcome:
        _log(booking, gym_class, account, outcome)


# GET  /api/classes/<id>/attendance - the roster with each member's mark.
# POST /api/classes/<id>/attendance - Body: { bookingId, attendance: "Attended" | "No-show" }.
#
# 200 + {"class", "roster": [{bookingId, memberId, memberName, attendance,
#        walkIn, markedBy, markedAt}], "counts", "canMark", "cannotMarkReason",
#        "coachWindowClosesAt", "isManager"}; POST returns the same payload.
@api_view(["GET", "POST"])
def class_attendance(request, class_id):
    account, gym_class, error = _class_for(request, class_id)
    if error:
        return error
    if request.method == "GET":
        return Response(_payload(account, gym_class))

    can_mark, reason = marking_state(account, gym_class)
    if not can_mark:
        return Response({"error": reason}, status=409 if "opens" in reason or "cancelled" in reason else 403)
    outcome = request.data.get("attendance")
    if outcome not in OUTCOMES:
        return Response({"error": {"attendance": ['Choose "Attended" or "No-show".']}}, status=400)
    booking = (
        gym_class.bookings.filter(id=request.data.get("bookingId"), status=ClassBooking.Status.BOOKED)
        .select_related("member").first()
    )
    if booking is None:
        return Response({"error": "That member isn't booked into this class."}, status=404)
    _mark(booking, gym_class, account, outcome)
    return Response(_payload(account, gym_class))


# POST /api/classes/<id>/attendance/walk-ins - Body: { memberId }.
# Adds someone who came without booking, marked Attended. A member who is
# already on the list is just marked Attended instead of being added twice.
@api_view(["POST"])
def class_walk_in(request, class_id):
    account, gym_class, error = _class_for(request, class_id)
    if error:
        return error
    can_mark, reason = marking_state(account, gym_class)
    if not can_mark:
        return Response({"error": reason}, status=409 if "opens" in reason or "cancelled" in reason else 403)

    member_id = request.data.get("memberId")
    member = Member.objects.filter(id=member_id).first() if str(member_id or "").isdigit() else None
    if member is None:
        return Response({"error": {"memberId": ["No member has that membership ID."]}}, status=400)
    if member.status == Member.Status.CANCELLED:
        return Response({"error": {"memberId": [f"{member.name}'s membership is cancelled."]}}, status=400)

    booking = gym_class.bookings.filter(member=member, status=ClassBooking.Status.BOOKED).first()
    if booking is None:
        try:
            with transaction.atomic():
                booking = ClassBooking.objects.create(
                    gym_class=gym_class, member=member, booked_by=account, walk_in=True,
                )
        except IntegrityError:
            booking = gym_class.bookings.get(member=member, status=ClassBooking.Status.BOOKED)
    booking.member = member
    _mark(booking, gym_class, account, ClassBooking.Attendance.ATTENDED)
    return Response(_payload(account, gym_class), status=201)

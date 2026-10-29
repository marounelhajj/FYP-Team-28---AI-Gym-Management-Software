from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from administration.models import StaffAccount
from checkins.models import AUTO_CHECKOUT_AFTER, CheckIn
from training.events import log_training_event
from training.models import TrainingEvent

from .models import ClassBooking, GymClass, PTAvailability, PTSession

# The scheduling rules shared by the manager's calendar and member booking.

MIN_DURATION = 15
MAX_DURATION = 240
MAX_CAPACITY = 100
MAX_REPEAT_WEEKS = 12
# How far ahead a class can be put on the calendar.
MAX_DAYS_AHEAD = 365

# Private training: the session lengths a coach's hours can be cut into, how
# much notice a coach gets (no booking a session that starts within the
# hour), and how many upcoming sessions one member can hold at once, so a few
# people can't take every slot.
PT_SESSION_LENGTHS = (30, 45, 60, 90)
PT_NOTICE = timedelta(hours=1)
MAX_UPCOMING_PT = 4


def local_datetime(day, clock):
    return timezone.make_aware(datetime.combine(day, clock))


def week_start(day):
    return day - timedelta(days=day.weekday())


def week_bounds(day):
    start = week_start(day)
    return start, local_datetime(start, time.min), local_datetime(start + timedelta(days=7), time.min)


def describe(gym_class):
    starts, ends = timezone.localtime(gym_class.starts_at), timezone.localtime(gym_class.ends_at)
    return f"{gym_class.name} on {starts:%a %d %b} {starts:%H:%M}-{ends:%H:%M}"


def overlapping(queryset, starts_at, ends_at):
    return queryset.filter(starts_at__lt=ends_at, ends_at__gt=starts_at)


def describe_pt(session):
    starts, ends = timezone.localtime(session.starts_at), timezone.localtime(session.ends_at)
    return f"a private training session on {starts:%a %d %b} {starts:%H:%M}-{ends:%H:%M}"


def booked_pt():
    return PTSession.objects.filter(status=PTSession.Status.BOOKED)


# What a member is already booked into between starts_at and ends_at - a
# class or a private session - as words for a message, or None. Nobody can
# be in two places at once.
def member_busy(member, starts_at, ends_at, exclude_booking_ids=(), exclude_pt_ids=()):
    clash = ClassBooking.objects.filter(
        member=member, status=ClassBooking.Status.BOOKED, gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__starts_at__lt=ends_at, gym_class__ends_at__gt=starts_at,
    ).exclude(id__in=exclude_booking_ids).select_related("gym_class").first()
    if clash:
        return describe(clash.gym_class)
    session = overlapping(booked_pt().filter(member=member), starts_at, ends_at).exclude(id__in=exclude_pt_ids).first()
    return describe_pt(session) if session else None


# Field errors for a proposed day/start/duration, or {} when it's fine. Past
# days, and times that have already gone by today, can't be scheduled.
def time_problems(day, start_time, duration):
    today = timezone.localdate()
    if day < today:
        return {"date": ["That day has already passed - past days are view-only."]}
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        return {"date": [f"Classes can be scheduled up to {MAX_DAYS_AHEAD} days ahead."]}
    if start_time.minute % 5 or start_time.second:
        return {"startTime": ["Use 5-minute steps (for example 18:00 or 18:05)."]}
    starts_at = local_datetime(day, start_time)
    if starts_at <= timezone.now():
        return {"startTime": ["That time has already passed today."]}
    if timezone.localtime(starts_at + timedelta(minutes=duration)).date() != day:
        return {"durationMinutes": ["A class has to finish by midnight."]}
    return {}


# Why this staff account can't teach a class at `branch`, or None.
def coach_problem(coach, branch):
    if coach is None:
        return "Choose a coach."
    if coach.job_title != StaffAccount.JobTitle.COACH:
        return f"{coach.full_name} isn't a coach."
    if not coach.is_active:
        return f"{coach.full_name}'s account is deactivated."
    if coach.branch and coach.branch != branch:
        return f"{coach.full_name} coaches at {coach.branch}, not {branch}."
    return None


# Why a class can't be scheduled as this type at `branch`, or None.
def class_type_problem(class_type, branch):
    if class_type is None:
        return "Choose a class type."
    if class_type.branch != branch:
        return f"{class_type.name} is a {class_type.branch} class type, not {branch}."
    if not class_type.is_active:
        return f"{class_type.name} is archived - restore it under Class types first."
    return None


# The safety limit: no class gets more spots than its type allows.
def capacity_problem(class_type, capacity):
    if capacity > class_type.max_capacity:
        return (
            f"{class_type.name} holds at most {class_type.max_capacity} people at {class_type.branch} - "
            "lower the spots, or raise the maximum under Class types."
        )
    return None


def eligible_coaches(branch):
    return StaffAccount.objects.filter(job_title=StaffAccount.JobTitle.COACH, is_active=True).filter(
        Q(branch=branch) | Q(branch__isnull=True) | Q(branch=""),
    ).order_by("full_name")


# Clashes for one class slot: the coach teaching something else at the same
# time (at any branch - nobody can be in two places), or the studio already
# in use. Two classes at the same time with different coaches are fine.
def slot_problems(*, branch, coach, room, starts_at, ends_at, exclude_ids=()):
    live = GymClass.objects.filter(status=GymClass.Status.SCHEDULED).exclude(id__in=exclude_ids)
    problems = []
    clash = overlapping(live.filter(coach=coach), starts_at, ends_at).first()
    if clash:
        where = "" if clash.branch == branch else f" at {clash.branch}"
        problems.append(f"{coach.full_name} already teaches {describe(clash)}{where}.")
    session = overlapping(booked_pt().filter(coach=coach), starts_at, ends_at).first()
    if session:
        problems.append(f"{coach.full_name} has {describe_pt(session)} with a member.")
    if room:
        clash = overlapping(live.filter(branch=branch, room__iexact=room), starts_at, ends_at).first()
        if clash:
            problems.append(f"{clash.room} is already in use for {describe(clash)}.")
    return problems


# Booked members of `gym_class` who'd end up in two classes at once if it
# moved to the new slot. Classes in `moving_ids` are being moved together,
# so they don't count against each other.
def member_clashes(gym_class, starts_at, ends_at, moving_ids):
    booked = ClassBooking.objects.filter(gym_class=gym_class, status=ClassBooking.Status.BOOKED).values("member_id")
    clashes = ClassBooking.objects.filter(
        member_id__in=booked, status=ClassBooking.Status.BOOKED, gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__starts_at__lt=ends_at, gym_class__ends_at__gt=starts_at,
    ).exclude(gym_class_id__in=moving_ids)
    sessions = overlapping(booked_pt().filter(member_id__in=booked), starts_at, ends_at)
    return sorted({b.member.name for b in clashes.select_related("member")} | {s.member.name for s in sessions.select_related("member")})


def booked_count(gym_class):
    return gym_class.bookings.filter(status=ClassBooking.Status.BOOKED).count()


# Ends every future booking a member holds - class spots and private sessions -
# when their membership is frozen, cancelled or erased, so they go back to
# other members.
def release_future_bookings(member, reason):
    now = timezone.now()
    classes = ClassBooking.objects.filter(
        member=member, status=ClassBooking.Status.BOOKED, gym_class__starts_at__gt=now,
    ).update(status=ClassBooking.Status.CANCELLED, cancelled_at=now, cancel_reason=reason[:60])
    sessions = booked_pt().filter(member=member, starts_at__gt=now).update(
        status=PTSession.Status.CANCELLED, cancelled_at=now, cancel_reason=reason[:120],
    )
    return classes + sessions


def _was_inside(member_id, branch, starts_at, ends_at):
    return CheckIn.objects.filter(
        member_id=member_id, result=CheckIn.Result.ALLOWED, branch=branch,
        checked_in_at__lt=ends_at, checked_in_at__gte=starts_at - AUTO_CHECKOUT_AFTER,
    ).filter(Q(checked_out_at__isnull=True) | Q(checked_out_at__gt=starts_at)).exists()


# Private training sessions for one coach at one branch across `days`, each
# with what it means for `member` (if given):
#   yours      - the member's own session
#   taken      - another member booked it
#   coach_busy - the coach teaches a group class then
#   closed     - already started, or starts within PT_NOTICE
#   clash      - the member is booked into something else then
#   open       - free to book
def pt_slots(coach, branch, days, member=None, now=None):
    now = now or timezone.now()
    windows = list(PTAvailability.objects.filter(coach=coach, branch=branch).order_by("start_time"))
    if not windows or not days:
        return []
    start, end = local_datetime(days[0], time.min), local_datetime(days[-1] + timedelta(days=1), time.min)
    classes = list(overlapping(GymClass.objects.filter(coach=coach, status=GymClass.Status.SCHEDULED), start, end))
    sessions = list(overlapping(booked_pt().filter(coach=coach), start, end))
    mine = []
    if member is not None:
        mine = [
            (b.gym_class.starts_at, b.gym_class.ends_at)
            for b in ClassBooking.objects.filter(
                member=member, status=ClassBooking.Status.BOOKED, gym_class__status=GymClass.Status.SCHEDULED,
                gym_class__starts_at__lt=end, gym_class__ends_at__gt=start,
            ).select_related("gym_class")
        ] + [(s.starts_at, s.ends_at) for s in overlapping(booked_pt().filter(member=member), start, end)]

    slots = []
    for day in days:
        for window in (w for w in windows if w.weekday == day.weekday()):
            step = timedelta(minutes=window.session_minutes)
            slot_start, limit = local_datetime(day, window.start_time), local_datetime(day, window.end_time)
            while slot_start + step <= limit:
                slot_end = slot_start + step
                session = next((s for s in sessions if s.starts_at < slot_end and s.ends_at > slot_start), None)
                if session and member is not None and session.member_id == member.id:
                    state = "yours"
                elif session:
                    state = "taken"
                elif any(c.starts_at < slot_end and c.ends_at > slot_start for c in classes):
                    state = "coach_busy"
                elif slot_start <= now + PT_NOTICE:
                    state = "closed"
                elif any(s < slot_end and e > slot_start for s, e in mine):
                    state = "clash"
                else:
                    state = "open"
                local_start, local_end = timezone.localtime(slot_start), timezone.localtime(slot_end)
                slots.append({
                    "date": day.isoformat(),
                    "startTime": f"{local_start:%H:%M}",
                    "endTime": f"{local_end:%H:%M}",
                    "startsAt": f"{local_start:%Y-%m-%dT%H:%M}",
                    "state": state,
                    "sessionId": session.id if state == "yours" else None,
                })
                slot_start = slot_end
    return slots


# Marks every booking of a finished class as Attended or No-show, from the
# member's check-ins: someone who was inside the branch at some point during
# the class attended it. Runs lazily whenever a schedule is opened (same
# no-cron approach as close_stale_sessions). A no-show is logged as AI
# training data (SCRUM-73), once.
def settle_attendance(now=None, limit=500):
    now = now or timezone.now()
    pending = ClassBooking.objects.filter(
        status=ClassBooking.Status.BOOKED, attendance="",
        gym_class__status=GymClass.Status.SCHEDULED, gym_class__ends_at__lte=now,
    ).select_related("gym_class__coach", "member")[:limit]
    for booking in pending:
        c = booking.gym_class
        was_inside = _was_inside(booking.member_id, c.branch, c.starts_at, c.ends_at)
        outcome = ClassBooking.Attendance.ATTENDED if was_inside else ClassBooking.Attendance.NO_SHOW
        # Conditional update, so two requests settling at once log a no-show only once.
        if ClassBooking.objects.filter(pk=booking.pk, attendance="").update(attendance=outcome) and not was_inside:
            log_training_event(
                TrainingEvent.EventType.NO_SHOW, member=booking.member, branch=c.branch, trainer=c.coach,
                session_id=str(booking.pk), occurred_at=c.ends_at,
                payload={"classId": c.pk, "className": c.name},
            )

    # Private sessions the same way. session_id is "pt:<id>", so it can't be
    # mistaken for a class booking id.
    finished = booked_pt().filter(attendance="", ends_at__lte=now).select_related("coach", "member")[:limit]
    for session in finished:
        was_inside = _was_inside(session.member_id, session.branch, session.starts_at, session.ends_at)
        outcome = ClassBooking.Attendance.ATTENDED if was_inside else ClassBooking.Attendance.NO_SHOW
        if PTSession.objects.filter(pk=session.pk, attendance="").update(attendance=outcome) and not was_inside:
            log_training_event(
                TrainingEvent.EventType.NO_SHOW, member=session.member, branch=session.branch, trainer=session.coach,
                session_id=f"pt:{session.pk}", occurred_at=session.ends_at, payload={"ptSessionId": session.pk},
            )

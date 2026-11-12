from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q
from django.utils import timezone

from classes import rules
from classes.models import ClassBooking, GymClass, PTSession

from .models import CoachPayRate

# How a coach's pay for a period is worked out - one place, used by the
# coach's own statement and by the branch manager's view of it.
#
# The pay period is the calendar month, Beirut time. A session belongs to the
# period it starts in (a class at 23:30 on the 31st is that month's).
#
# What's paid:
#   * a group class the coach taught that has ended and wasn't cancelled -
#     whether or not anyone came (they turned up to teach it);
#   * a private session that has ended and wasn't cancelled - including when
#     the member didn't show, since the slot was theirs.
# Each is paid at the rate in effect on its date, for its length:
# rate x minutes / 60, rounded to the cent. The period total is the sum of
# those lines, so it always matches what the statement lists.
# Not paid (but listed, so the coach can check): sessions the gym or member
# cancelled. Not paid yet: sessions still to come or in progress.

CENT = Decimal("0.01")
# How far back a coach can look: this month and the eleven before it.
MONTHS_BACK = 11


def _month_start(day):
    return day.replace(day=1)


def _add_months(day, months):
    index = day.month - 1 + months
    return date(day.year + index // 12, index % 12 + 1, 1)


def period_key(day):
    return f"{day:%Y-%m}"


def available_periods(today=None):
    today = today or timezone.localdate()
    current = _month_start(today)
    return [period_key(_add_months(current, -n)) for n in range(MONTHS_BACK + 1)]


# (first day, last day, None) for "YYYY-MM" (default: this month), or (None, None, error message).
def parse_period(value, today=None):
    today = today or timezone.localdate()
    if not value:
        start = _month_start(today)
    else:
        try:
            start = datetime.strptime(value, "%Y-%m").date()
        except ValueError:
            return None, None, "Use a pay period like 2026-11."
        if start > today:
            return None, None, "That pay period hasn't started yet."
        if period_key(start) not in available_periods(today):
            return None, None, f"You can look back {MONTHS_BACK} months at most."
    return start, _add_months(start, 1) - timedelta(days=1), None


def _local(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def rates_for(coach):
    return list(CoachPayRate.objects.filter(coach=coach).order_by("effective_from", "id"))


# The rate in effect on `day` (rates oldest first), or None.
def rate_on(rates, day):
    found = None
    for rate in rates:
        if rate.effective_from > day:
            break
        found = rate
    return found


def money(value):
    return None if value is None else f"{value.quantize(CENT, rounding=ROUND_HALF_UP)}"


def _pay(hourly, minutes):
    return (hourly * minutes / Decimal(60)).quantize(CENT, rounding=ROUND_HALF_UP)


def rate_payload(rate):
    if rate is None:
        return None
    return {
        "id": rate.id,
        "classHourly": money(rate.class_hourly),
        "ptHourly": money(rate.pt_hourly),
        "effectiveFrom": rate.effective_from.isoformat(),  # also stored in audit details (JSON)
        "note": rate.note,
        "setBy": rate.set_by.full_name if rate.set_by else None,
    }


def _state(starts_at, ends_at, cancelled, now):
    if cancelled:
        return "cancelled"
    if ends_at <= now:
        return "completed"
    return "in_progress" if starts_at <= now else "upcoming"


def _line(kind, item_id, starts_at, ends_at, title, branch, state, rates, detail, reason=""):
    local_start, local_end = timezone.localtime(starts_at), timezone.localtime(ends_at)
    minutes = int((ends_at - starts_at).total_seconds() // 60)
    rate = rate_on(rates, local_start.date())
    hourly = None if rate is None else (rate.class_hourly if kind == "class" else rate.pt_hourly)
    amount = None if hourly is None or state == "cancelled" else _pay(hourly, minutes)
    return {
        "kind": kind,
        "id": item_id,
        "date": local_start.date(),
        "startTime": f"{local_start:%H:%M}",
        "endTime": f"{local_end:%H:%M}",
        "minutes": minutes,
        "title": title,
        "branch": branch,
        "state": state,
        "detail": detail,
        "reason": reason,
        "hourlyRate": money(hourly) if state != "cancelled" else None,
        "amount": money(amount),
        "_amount": amount,
    }


def _class_lines(coach, start, end, rates, now):
    classes = GymClass.objects.filter(coach=coach, starts_at__gte=start, starts_at__lt=end).annotate(
        booked=Count("bookings", filter=Q(bookings__status=ClassBooking.Status.BOOKED, bookings__walk_in=False)),
        walk_ins=Count("bookings", filter=Q(bookings__status=ClassBooking.Status.BOOKED, bookings__walk_in=True)),
        attended=Count("bookings", filter=Q(
            bookings__status=ClassBooking.Status.BOOKED, bookings__attendance=ClassBooking.Attendance.ATTENDED,
        )),
    )
    lines = []
    for c in classes:
        cancelled = c.status == GymClass.Status.CANCELLED
        state = _state(c.starts_at, c.ends_at, cancelled, now)
        if state == "completed":
            walk_ins = f", {c.walk_ins} walk-in{'' if c.walk_ins == 1 else 's'}" if c.walk_ins else ""
            detail = f"{c.attended} attended of {c.booked} booked{walk_ins}"
            if c.attended == 0:
                detail += " - no one came, still paid"
        else:
            detail = f"{c.booked} booked"
        reason = f"Cancelled by the gym{': ' + c.cancel_reason if c.cancel_reason else ''}" if cancelled else ""
        lines.append(_line("class", c.id, c.starts_at, c.ends_at, c.name, c.branch, state, rates, detail, reason))
    return lines


def _pt_lines(coach, start, end, rates, now):
    lines = []
    for s in PTSession.objects.filter(coach=coach, starts_at__gte=start, starts_at__lt=end).select_related("member"):
        cancelled = s.status == PTSession.Status.CANCELLED
        state = _state(s.starts_at, s.ends_at, cancelled, now)
        detail = ""
        if state == "completed":
            if s.attendance == ClassBooking.Attendance.NO_SHOW:
                detail = "Member didn't show - still paid"
            elif s.attendance == ClassBooking.Attendance.ATTENDED:
                detail = "Attended"
        lines.append(_line(
            "pt", s.id, s.starts_at, s.ends_at, f"Private training · {s.member.name}", s.branch, state, rates, detail,
            s.cancel_reason if cancelled else "",
        ))
    return lines


def _total(lines):
    return sum((line["_amount"] for line in lines if line["_amount"] is not None), Decimal("0"))


def _clean(lines):
    return [{k: v for k, v in line.items() if k != "_amount"} for line in lines]


# The coach's pay for one period: every session in it, what's paid so far, and
# what the rest of the period would add if taught as scheduled.
def statement(coach, period_start, period_end, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    rules.settle_attendance(now)
    rates = rates_for(coach)
    start, end = _local(period_start), _local(period_end + timedelta(days=1))
    lines = sorted(
        _class_lines(coach, start, end, rates, now) + _pt_lines(coach, start, end, rates, now),
        key=lambda line: (line["date"], line["startTime"], line["kind"], line["id"]),
    )
    completed = [line for line in lines if line["state"] == "completed"]
    coming = [line for line in lines if line["state"] in ("upcoming", "in_progress")]
    cancelled = [line for line in lines if line["state"] == "cancelled"]
    unrated = [line for line in completed if line["_amount"] is None]

    in_period = [r for r in rates if period_start < r.effective_from <= period_end]
    return {
        "coach": {"id": coach.id, "name": coach.full_name, "branch": coach.branch},
        "period": {
            "key": period_key(period_start),
            "label": f"{period_start:%B %Y}",
            "start": period_start,
            "end": period_end,
            "isCurrent": period_start <= today <= period_end,
            "daysLeft": max(0, (period_end - today).days) if period_start <= today <= period_end else 0,
        },
        "periods": available_periods(today),
        "currency": "USD",
        "summary": {
            "completed": len(completed),
            "classes": sum(1 for line in completed if line["kind"] == "class"),
            "privateSessions": sum(1 for line in completed if line["kind"] == "pt"),
            "minutes": sum(line["minutes"] for line in completed),
            "earnings": money(_total(completed)),
            "unrated": len(unrated),
            "upcoming": len(coming),
            "upcomingMinutes": sum(line["minutes"] for line in coming),
            "upcomingEstimate": money(_total(coming)),
            "upcomingUnrated": sum(1 for line in coming if line["_amount"] is None),
            "cancelled": len(cancelled),
        },
        "rates": {
            "atPeriodStart": rate_payload(rate_on(rates, period_start)),
            "changedDuringPeriod": [rate_payload(r) for r in in_period],
            "current": rate_payload(rate_on(rates, today)),
            "scheduled": [rate_payload(r) for r in rates if r.effective_from > today],
        },
        "completed": _clean(completed),
        "upcoming": _clean(coming),
        "cancelled": _clean(cancelled),
    }

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.utils import timezone

from billing.models import Payment, payment_method_on_file, renewal_quote
from classes.models import ClassBooking, GymClass, PTSession
from members.models import Member

from .delivery import notify_member
from .models import MemberNotification, NotificationSettings, SentReminder

# User story: "As a member, I want to receive notifications before an upcoming
# class or when my membership is about to renew, so that I don't miss sessions
# or get charged unexpectedly."
#
# How it works:
#   * Classes and private sessions: a reminder the day before (24 hours) and
#     one shortly before (an hour by default). Each member picks their own in
#     the app, or turns them off.
#   * Renewal: a reminder some days before the renewal date (7 by default) and
#     a last one the day before, at 09:00 Beirut time. Renewals are never
#     charged automatically in this gym (see billing.Payment.record), so the
#     reminder says what renewing will cost, which payment method is on file -
#     and warns if that card runs out first - and that nothing will be charged
#     without them.
#   * send_due() finds everything due and sends it. It runs every minute in
#     the background (notifications/scheduler.py) and as
#     "python manage.py send_reminders" for a server's own scheduler.
#
# Rules that keep reminders useful rather than noisy:
#   * A reminder whose time had already passed when the class was booked (or
#     the membership paid for) isn't sent - they know.
#   * If several are due at once (the server was off for a while), only the
#     latest is sent, worded for the actual time left.
#   * Once a closer reminder went out, an earlier one is never sent after it.
#   * Cancelled bookings, cancelled classes, frozen and cancelled members get
#     no class reminders; cancelled members get no renewal reminders.
#   * A class that moves gets fresh reminders for its new time, and everyone
#     booked into it is told it moved.

Kind = MemberNotification.Kind

DAY_BEFORE = 24 * 60  # minutes
RENEWAL_HOUR = time(9, 0)
CLASS_HORIZON = timedelta(minutes=DAY_BEFORE)
RENEWAL_HORIZON_DAYS = max(NotificationSettings.RENEWAL_DAYS_CHOICES)
# How far ahead the settings screen lists what's coming.
PREVIEW_DAYS = 8


def defaults():
    return NotificationSettings()


def settings_for(member_ids):
    found = {s.member_id: s for s in NotificationSettings.objects.filter(member_id__in=member_ids)}
    return {member_id: found.get(member_id) or defaults() for member_id in member_ids}


def class_offsets(prefs):
    offsets = set()
    if prefs.class_day_before:
        offsets.add(DAY_BEFORE)
    if prefs.class_minutes_before:
        offsets.add(prefs.class_minutes_before)
    return offsets


# The chosen number of days, then the day before.
def renewal_offsets(prefs):
    if not prefs.renewal_days_before:
        return set()
    return {prefs.renewal_days_before, 1}


def _stamp(moment):
    return moment.astimezone(dt_timezone.utc).strftime("%Y%m%d%H%M")


def _renewal_at(expires, days):
    return timezone.make_aware(datetime.combine(expires - timedelta(days=days), RENEWAL_HOUR))


# {key without the offset: offsets already handled} for these members' recent reminders.
def _handled(kind, member_ids, since):
    handled = {}
    for key in SentReminder.objects.filter(kind=kind, member_id__in=member_ids, created_at__gte=since).values_list(
        "key", flat=True,
    ):
        base, offset = key.rsplit(":", 1)
        handled.setdefault(base, set()).add(int(offset))
    return handled


# Given {offset: when it's due}, what was already handled and when the thing
# was booked/paid for: the offsets due now (furthest first) and when the next
# one is due. Never one further out than a reminder already handled.
def _schedule(times, since, now, handled):
    closest = min(handled, default=None)
    live = sorted(
        (at, offset) for offset, at in times.items()
        if (since is None or at >= since) and (closest is None or offset < closest)
    )
    due = [offset for at, offset in live if at <= now]
    upcoming = next((at for at, _ in live if at > now), None)
    return due, upcoming


# Marks every due offset handled and sends one notification. False when
# another run sent it first (the unique key), so nothing goes out twice.
def _send(member, kind, base, due, notification_kind, title, message):
    keys = [f"{base}:{offset}" for offset in due]
    try:
        with transaction.atomic():
            SentReminder.objects.bulk_create([SentReminder(member=member, kind=kind, key=key) for key in keys])
            notification = notify_member(member, notification_kind, title, message)
            SentReminder.objects.filter(key=keys[-1]).update(notification=notification)
    except IntegrityError:
        return False
    return True


def _day_phrase(moment, now):
    local, today = timezone.localtime(moment), timezone.localdate(now)
    if local.date() == today:
        return f"today at {local:%H:%M}"
    if local.date() == today + timedelta(days=1):
        return f"tomorrow at {local:%H:%M}"
    return f"on {local:%a %d %b} at {local:%H:%M}"


def _time_left(moment, now):
    minutes = max(1, round((moment - now).total_seconds() / 60))
    if minutes < 90:
        return f"in {minutes} minute{'' if minutes == 1 else 's'}"
    return f"in about {round(minutes / 60)} hours"


def _slot(starts_at, ends_at):
    starts, ends = timezone.localtime(starts_at), timezone.localtime(ends_at)
    return f"{starts:%a %d %b}, {starts:%H:%M}-{ends:%H:%M}"


# --- classes and private sessions ---

def _class_text(booking, now):
    c = booking.gym_class
    where = ", ".join(part for part in (c.room, c.branch) if part)
    return (
        f"Reminder: {c.name} {_day_phrase(c.starts_at, now)}",
        f"{c.name} with {c.coach.full_name}, {_slot(c.starts_at, c.ends_at)}, {where}. It starts "
        f"{_time_left(c.starts_at, now)}. Can't make it? Cancel in the app so someone on the waitlist gets your spot.",
    )


def _pt_text(session, now):
    return (
        f"Reminder: private training {_day_phrase(session.starts_at, now)}",
        f"Your session with {session.coach.full_name}, {_slot(session.starts_at, session.ends_at)}, at "
        f"{session.branch}. It starts {_time_left(session.starts_at, now)}. Can't make it? Cancel it in the app so "
        "the time goes to someone else.",
    )


def _upcoming_classes(now, until, member=None):
    bookings = ClassBooking.objects.filter(
        status=ClassBooking.Status.BOOKED, gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__starts_at__gt=now, gym_class__starts_at__lte=until, member__status=Member.Status.ACTIVE,
    ).select_related("gym_class__coach", "member")
    return bookings.filter(member=member) if member else bookings


def _upcoming_sessions(now, until, member=None):
    sessions = PTSession.objects.filter(
        status=PTSession.Status.BOOKED, starts_at__gt=now, starts_at__lte=until, member__status=Member.Status.ACTIVE,
    ).select_related("coach", "member")
    return sessions.filter(member=member) if member else sessions


# (kind, base key, member, starts_at, booked_at, text function, item) for every booked class and session.
def _bookable_items(bookings, sessions):
    for b in bookings:
        c = b.gym_class
        yield SentReminder.Kind.CLASS, f"class:{b.id}:{_stamp(c.starts_at)}", b.member, c.starts_at, b.booked_at, b
    for s in sessions:
        yield SentReminder.Kind.PT, f"pt:{s.id}:{_stamp(s.starts_at)}", s.member, s.starts_at, s.booked_at, s


def _session_reminders(now):
    items = list(_bookable_items(_upcoming_classes(now, now + CLASS_HORIZON), _upcoming_sessions(now, now + CLASS_HORIZON)))
    member_ids = {member.id for _, _, member, _, _, _ in items}
    prefs = settings_for(member_ids)
    since = now - CLASS_HORIZON - timedelta(days=2)
    handled = {kind: _handled(kind, member_ids, since) for kind in SentReminder.Kind.values}
    sent = 0
    for kind, base, member, starts_at, booked_at, item in items:
        times = {offset: starts_at - timedelta(minutes=offset) for offset in class_offsets(prefs[member.id])}
        due, _ = _schedule(times, booked_at, now, handled[kind].get(base, set()))
        if not due:
            continue
        if kind == SentReminder.Kind.CLASS:
            title, message = _class_text(item, now)
            notification_kind = Kind.CLASS_REMINDER
        else:
            title, message = _pt_text(item, now)
            notification_kind = Kind.PT_REMINDER
        sent += _send(member, kind, base, due, notification_kind, title, message)
    return sent


# --- renewals ---

def _last_payment(member):
    return Payment.objects.filter(member=member).order_by("-paid_at", "-id").first()


def renewal_text(member, now):
    from plans.models import MembershipPlan

    expires = member.subscription_expires_at
    days_left = (expires - timezone.localdate(now)).days
    date_label = f"{expires:%a %d %b}"
    due = "today" if days_left <= 0 else "tomorrow" if days_left == 1 else f"in {days_left} days"
    title = f"Membership renewal due {due} ({date_label})"

    frozen = " is frozen and" if member.status == Member.Status.FROZEN else ""
    parts = [f"Your {member.membership_plan} membership{frozen} runs until {date_label}."]
    last = _last_payment(member)
    duration = last.duration if last else Payment.Duration.ONE_MONTH
    try:
        quote = renewal_quote(member, member.membership_plan, duration)
    except MembershipPlan.DoesNotExist:
        parts.append(f"The {member.membership_plan} plan isn't offered any more - the front desk can move you to a current plan.")
    else:
        price = f"Renewing for {duration.lower()} costs ${quote.amount}"
        if quote.promotion:
            price += f" with the {quote.promotion} promotion"
        if last and last.duration == duration and last.amount != quote.amount:
            price += f" (you paid ${last.amount} last time)"
        parts.append(price + ".")

    on_file = payment_method_on_file(member)
    if on_file is None:
        parts.append("No payment method is on file - you can add one in the app.")
    else:
        parts.append(f"On file: {on_file.reference() or on_file.method}.")
        valid_through = on_file.card_valid_through()
        if valid_through and valid_through < expires:
            parts.append(f"That card expires {valid_through:%m/%Y} - update it in the app first.")
    parts.append(
        "Nothing is charged automatically: renew at the front desk to keep going, or your check-in code stops "
        f"working after {date_label}.",
    )
    return title, " ".join(parts)


# Everyone whose renewal reminders could be due now - or, for one member's
# preview, their next renewal however far off it is.
def _renewing_members(today, member=None):
    members = Member.objects.filter(
        status__in=[Member.Status.ACTIVE, Member.Status.FROZEN], subscription_expires_at__gte=today,
    )
    if member:
        return members.filter(pk=member.pk)
    return members.filter(subscription_expires_at__lte=today + timedelta(days=RENEWAL_HORIZON_DAYS))


def _renewal_plan(member, prefs, now, handled):
    expires = member.subscription_expires_at
    base = f"renewal:{member.id}:{expires:%Y%m%d}"
    times = {days: _renewal_at(expires, days) for days in renewal_offsets(prefs)}
    last = _last_payment(member)
    due, upcoming = _schedule(times, last.paid_at if last else None, now, handled.get(base, set()))
    return base, due, upcoming


def _renewal_reminders(now):
    members = list(_renewing_members(timezone.localdate(now)))
    member_ids = {m.id for m in members}
    prefs = settings_for(member_ids)
    handled = _handled(SentReminder.Kind.RENEWAL, member_ids, now - timedelta(days=RENEWAL_HORIZON_DAYS + 2))
    sent = 0
    for member in members:
        base, due, _ = _renewal_plan(member, prefs[member.id], now, handled)
        if due:
            title, message = renewal_text(member, now)
            sent += _send(member, SentReminder.Kind.RENEWAL, base, due, Kind.RENEWAL_REMINDER, title, message)
    return sent


# Sends every reminder that's due. Safe to run as often as you like, and from
# more than one place at once. Returns how many went out.
def send_due(now=None):
    now = now or timezone.now()
    return _session_reminders(now) + _renewal_reminders(now)


# What this member will be reminded about next, soonest first - shown in the
# app so they can see their settings at work.
def upcoming(member, now=None):
    now = now or timezone.now()
    prefs = settings_for([member.id])[member.id]
    until = now + timedelta(days=PREVIEW_DAYS)
    items = list(_bookable_items(_upcoming_classes(now, until, member), _upcoming_sessions(now, until, member)))
    since = now - timedelta(days=RENEWAL_HORIZON_DAYS + 2)
    handled = {kind: _handled(kind, [member.id], since) for kind in SentReminder.Kind.values}
    found = []
    for kind, base, _, starts_at, booked_at, item in items:
        times = {offset: starts_at - timedelta(minutes=offset) for offset in class_offsets(prefs)}
        due, next_at = _schedule(times, booked_at, now, handled[kind].get(base, set()))
        at = now if due else next_at
        if at:
            about = item.gym_class.name if kind == SentReminder.Kind.CLASS else f"Private training with {item.coach.full_name}"
            found.append((at, kind, f"{about} · {timezone.localtime(starts_at):%a %d %b %H:%M}"))
    for renewing in _renewing_members(timezone.localdate(now), member):
        _, due, next_at = _renewal_plan(renewing, prefs, now, handled[SentReminder.Kind.RENEWAL])
        at = now if due else next_at
        if at:
            found.append((at, SentReminder.Kind.RENEWAL, f"Renewal date · {renewing.subscription_expires_at:%a %d %b}"))
    found.sort(key=lambda item: item[0])
    return [
        {"kind": kind, "about": about, "sendAt": timezone.localtime(at).strftime("%Y-%m-%d %H:%M")}
        for at, kind, about in found
    ]


# --- changes to something already booked ---

# A manager moved a class, or changed its studio or coach: everyone booked is
# told what changed. `before` holds the old starts_at, ends_at, room and coach name.
def class_changed(gym_class, before):
    changes = []
    if (before["starts_at"], before["ends_at"]) != (gym_class.starts_at, gym_class.ends_at):
        changes.append(f"it's now {_slot(gym_class.starts_at, gym_class.ends_at)} (was {_slot(before['starts_at'], before['ends_at'])})")
    if before["room"].lower() != gym_class.room.lower():
        changes.append(f"it's now in {gym_class.room or 'a studio still to be confirmed'}"
                       + (f" (was {before['room']})" if before["room"] else ""))
    if before["coach"] != gym_class.coach.full_name:
        changes.append(f"{gym_class.coach.full_name} is coaching it instead of {before['coach']}")
    if not changes:
        return
    old_day = timezone.localtime(before["starts_at"])
    for booking in gym_class.bookings.filter(status=ClassBooking.Status.BOOKED).select_related("member"):
        notify_member(
            booking.member, Kind.CLASS_CHANGED, f"{gym_class.name} on {old_day:%a %d %b} has changed",
            f"The gym changed a class you're booked into: {'; '.join(changes)}. You're still booked in. If it no "
            "longer suits you, cancel in the app so someone on the waitlist gets your spot.",
        )


def pt_cancelled_by_gym(session, reason):
    because = f" Reason: {reason}." if reason else ""
    notify_member(
        session.member, Kind.PT_CANCELLED,
        f"Private training {_day_phrase(session.starts_at, timezone.now())} was cancelled",
        f"The gym cancelled your session with {session.coach.full_name}, {_slot(session.starts_at, session.ends_at)}."
        f"{because} Book another time in the app.",
    )

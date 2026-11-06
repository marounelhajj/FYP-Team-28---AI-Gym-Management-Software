from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from notifications.delivery import notify_member
from notifications.models import MemberNotification

from . import rules
from .models import ClassBooking, GymClass, WaitlistEntry

# User story: "As a member, I want to join a waitlist for a full class and be
# notified automatically when a spot opens up, so that I don't have to keep
# checking manually."
#
# How it works:
#   * A member joins the waitlist of a class that is full. They queue in the
#     order they joined.
#   * Whenever a spot opens - a member cancels, the desk removes a booking, a
#     membership is frozen or cancelled, a manager gives the class more spots -
#     fill() books the first member still waiting into it, there and then,
#     and tells them (in the app and by email). Nobody has to race for it.
#   * If the person first in line can't take the spot any more (their
#     membership lapsed, they booked something else at that time...), they're
#     told why and the spot goes to the next one.
#   * The waitlist closes when the class starts or is cancelled; whoever is
#     still waiting is told.

Kind = MemberNotification.Kind
Status = WaitlistEntry.Status

# How many waitlists one member can be on at once, so a few people can't sit
# in every queue.
MAX_WAITLISTS = 5


def waiting():
    return WaitlistEntry.objects.filter(status=Status.WAITING)


def position(entry):
    ahead = waiting().filter(gym_class_id=entry.gym_class_id).filter(
        Q(joined_at__lt=entry.joined_at) | Q(joined_at=entry.joined_at, id__lt=entry.id),
    )
    return ahead.count() + 1


def _when(gym_class):
    starts = timezone.localtime(gym_class.starts_at)
    return f"{starts:%a %d %b} at {starts:%H:%M}"


def _end(entry, status, note, booking=None):
    entry.status = status
    entry.note = note[:200]
    entry.resolved_at = timezone.now()
    entry.booking = booking
    entry.save(update_fields=["status", "note", "resolved_at", "booking"])


# Why this member can't join this class's waitlist, as (http status, message), or None.
def join_problem(member, gym_class):
    problem = rules.booking_problem(member, gym_class, check_capacity=False)
    if problem:
        return problem
    if waiting().filter(gym_class=gym_class, member=member).exists():
        return 400, "You're already on the waitlist for this class."
    if rules.spots_left(gym_class) > 0:
        return 409, "There's a free spot in this class - book it instead."
    if waiting().filter(member=member, gym_class__starts_at__gt=timezone.now()).count() >= MAX_WAITLISTS:
        return 409, f"You can be on up to {MAX_WAITLISTS} waitlists at once - leave one to join another."
    return None


# Gives every open spot in the class to the members waiting for it, first come
# first served. Safe to call any time - it does nothing unless there's both a
# free spot and someone waiting. Returns the bookings it made.
def fill(gym_class_id):
    made = []
    with transaction.atomic():
        gym_class = GymClass.objects.select_for_update().select_related("class_type").filter(pk=gym_class_id).first()
        if gym_class is None or gym_class.status != GymClass.Status.SCHEDULED or gym_class.has_started:
            return made
        for entry in waiting().filter(gym_class=gym_class).select_related("member").order_by("joined_at", "id"):
            if rules.spots_left(gym_class) == 0:
                break
            member = entry.member
            member.refresh_expiry_status()
            if ClassBooking.objects.filter(gym_class=gym_class, member=member, status=ClassBooking.Status.BOOKED).exists():
                _end(entry, Status.BOOKED, "You booked a spot in this class.")
                continue
            problem = rules.booking_problem(member, gym_class)
            if problem:
                _end(entry, Status.SKIPPED, f"A spot opened but you couldn't take it: {problem[1]}")
                notify_member(
                    member, Kind.WAITLIST_SKIPPED, f"A spot opened in {gym_class.name}, {_when(gym_class)}",
                    f"We couldn't book you into it: {problem[1]} You've been taken off the waitlist, and the spot "
                    "went to the next person in line.",
                )
                continue
            booking = ClassBooking.objects.create(gym_class=gym_class, member=member, from_waitlist=True)
            _end(entry, Status.BOOKED, "You got a spot from the waitlist.", booking)
            # Their other waitlists at the same time can't work out any more.
            for other in waiting().filter(
                member=member, gym_class__starts_at__lt=gym_class.ends_at, gym_class__ends_at__gt=gym_class.starts_at,
            ):
                _end(other, Status.LEFT, f"You got a spot in {gym_class.name} at the same time.")
            notify_member(
                member, Kind.WAITLIST_SPOT, f"You're in: {gym_class.name}, {_when(gym_class)}",
                "A spot opened up and you were next on the waitlist, so we booked you in. Can't make it? Cancel it "
                "in the app so the next person gets the spot.",
            )
            made.append(booking)
    return made


# A member booked straight into a class they were waiting for (the desk, or a
# spot that freed up with nobody ahead of them): their place in line is done.
def booked_directly(member, gym_class):
    for entry in waiting().filter(gym_class=gym_class, member=member):
        _end(entry, Status.BOOKED, "You booked a spot in this class.")


# Takes a member off every waitlist (their membership was frozen, cancelled or erased).
def leave_all(member, reason):
    waiting().filter(member=member).update(status=Status.LEFT, note=reason[:200], resolved_at=timezone.now())


# Tells everyone in or waiting for these classes that they were cancelled.
# `released` are the bookings the cancellation ended.
def class_cancelled(gym_classes, released, reason):
    because = f" Reason: {reason}." if reason else ""
    for booking in released:
        c = booking.gym_class
        notify_member(
            booking.member, Kind.CLASS_CANCELLED, f"{c.name} on {_when(c)} was cancelled",
            f"The gym cancelled this class, so your spot has been released.{because}",
        )
    for gym_class in gym_classes:
        for entry in waiting().filter(gym_class=gym_class).select_related("member"):
            _end(entry, Status.CLOSED, "The class was cancelled.")
            notify_member(
                entry.member, Kind.CLASS_CANCELLED, f"{gym_class.name} on {_when(gym_class)} was cancelled",
                f"The gym cancelled this class, so you've been taken off its waitlist.{because}",
            )


# Closes the waitlists of classes that have started without a spot coming up,
# and tells whoever was still waiting. Each entry is closed by a conditional
# update, so two requests sweeping at once tell a member only once.
def close_started(now=None):
    now = now or timezone.now()
    stale = waiting().filter(gym_class__starts_at__lte=now).select_related("gym_class", "member")[:500]
    for entry in stale:
        closed = WaitlistEntry.objects.filter(pk=entry.pk, status=Status.WAITING).update(
            status=Status.CLOSED, note="The class started before a spot opened.", resolved_at=now,
        )
        if closed:
            c = entry.gym_class
            notify_member(
                entry.member, Kind.WAITLIST_CLOSED, f"No spot opened in {c.name}, {_when(c)}",
                "The class started before anyone gave up their spot, so you've been taken off the waitlist.",
            )

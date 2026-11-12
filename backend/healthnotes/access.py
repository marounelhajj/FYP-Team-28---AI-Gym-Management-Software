from datetime import timedelta

from django.utils import timezone

from classes.models import ClassBooking, GymClass, PTSession
from members.models import Member

from .models import HealthDeclaration, HealthNote

# Who may read a member's health notes, and what they're shown.
#
# Health information is the most sensitive thing the app holds, so the rule
# is narrow: only the coach who is about to train the member (or just did).
#   * A class: its coach, for the members booked into it, until
#     CLASS_WINDOW after it ends (the same window they have for attendance).
#     Never for a cancelled class.
#   * A private session: its coach, while it's booked, until PT_LOOKBACK after
#     it ends - long enough to plan the next one from My Clients.
# A booking that's cancelled (by the member, or because the membership was
# frozen or cancelled) ends the access with it. Managers and the front desk
# have none.

CLASS_WINDOW = timedelta(hours=24)
PT_LOOKBACK = timedelta(days=30)
# A recovered injury still matters to a coach for a while.
RECENT_DAYS = 90
# Past this, the coach is told the information may be out of date.
STALE_DAYS = 180

SEVERITY_ORDER = [HealthNote.Severity.MILD, HealthNote.Severity.MODERATE, HealthNote.Severity.SEVERE]


def class_is_open(gym_class, now=None):
    now = now or timezone.now()
    return gym_class.status == GymClass.Status.SCHEDULED and gym_class.ends_at + CLASS_WINDOW >= now


def pt_is_open(session, now=None):
    now = now or timezone.now()
    return session.status == PTSession.Status.BOOKED and session.ends_at + PT_LOOKBACK >= now


def class_member_ids(gym_class):
    return list(
        gym_class.bookings.filter(status=ClassBooking.Status.BOOKED).values_list("member_id", flat=True),
    )


# The ids (among `member_ids`, or all) of members this coach may see right now.
def viewable_member_ids(coach, member_ids=None, now=None):
    now = now or timezone.now()
    pt = PTSession.objects.filter(coach=coach, status=PTSession.Status.BOOKED, ends_at__gte=now - PT_LOOKBACK)
    booked = ClassBooking.objects.filter(
        status=ClassBooking.Status.BOOKED, gym_class__coach=coach, gym_class__status=GymClass.Status.SCHEDULED,
        gym_class__ends_at__gte=now - CLASS_WINDOW,
    )
    if member_ids is not None:
        pt, booked = pt.filter(member_id__in=member_ids), booked.filter(member_id__in=member_ids)
    return set(pt.values_list("member_id", flat=True)) | set(booked.values_list("member_id", flat=True))


def _note(note):
    return {
        "id": note.id, "kind": note.kind, "bodyArea": note.body_area, "severity": note.severity, "title": note.title,
        "details": note.details, "since": note.since, "status": note.status, "resolvedOn": note.resolved_on,
        "updatedOn": timezone.localtime(note.updated_at).date(),
    }


def _most_severe_first(notes):
    return sorted(notes, key=lambda n: (-SEVERITY_ORDER.index(n.severity), n.title.lower()))


# What a coach sees for each member: {member id: {...}}.
#   status "restrictions" - has active notes (listed, most limiting first);
#          "clear"        - told us there's nothing to declare;
#          "undeclared"   - never filled it in: ask before starting.
def briefs(member_ids, today=None):
    today = today or timezone.localdate()
    member_ids = list(member_ids)
    active, recovered = {}, {}
    notes = HealthNote.objects.filter(member_id__in=member_ids)
    for note in notes.filter(status=HealthNote.Status.ACTIVE):
        active.setdefault(note.member_id, []).append(note)
    for note in notes.filter(status=HealthNote.Status.RESOLVED, resolved_on__gte=today - timedelta(days=RECENT_DAYS)):
        recovered.setdefault(note.member_id, []).append(note)
    reviewed = dict(HealthDeclaration.objects.filter(member_id__in=member_ids).values_list("member_id", "reviewed_at"))

    result = {}
    for member_id in member_ids:
        mine = _most_severe_first(active.get(member_id, []))
        reviewed_on = timezone.localtime(reviewed[member_id]).date() if member_id in reviewed else None
        if mine:
            status = "restrictions"
        elif reviewed_on:
            status = "clear"
        else:
            status = "undeclared"
        result[member_id] = {
            "status": status,
            "activeCount": len(mine),
            "severity": mine[0].severity if mine else None,
            "reviewedOn": reviewed_on,
            "stale": bool(reviewed_on and (today - reviewed_on).days > STALE_DAYS),
            "active": [_note(n) for n in mine],
            "recentlyRecovered": [
                _note(n) for n in sorted(recovered.get(member_id, []), key=lambda n: n.resolved_on, reverse=True)
            ],
        }
    return result


# The short version, for a badge next to a name.
def _badge(brief):
    return {key: brief[key] for key in ("status", "activeCount", "severity", "stale")}


def _counts(found):
    return {
        "booked": len(found),
        "restricted": sum(1 for b in found if b["status"] == "restrictions"),
        "undeclared": sum(1 for b in found if b["status"] == "undeclared"),
        "severe": sum(1 for b in found if b["severity"] == HealthNote.Severity.SEVERE),
    }


# Badges for a coach's own week (classes.views.my_schedule): how many members
# of each class have something to know about, and each private client's
# status. Sessions whose window has closed aren't in it.
def schedule_badges(classes, sessions, now=None):
    now = now or timezone.now()
    open_classes = [c for c in classes if class_is_open(c, now)]
    open_sessions = [s for s in sessions if pt_is_open(s, now)]
    by_class = {}
    for class_id, member_id in ClassBooking.objects.filter(
        gym_class__in=open_classes, status=ClassBooking.Status.BOOKED,
    ).values_list("gym_class_id", "member_id"):
        by_class.setdefault(class_id, []).append(member_id)
    member_ids = {m for ids in by_class.values() for m in ids} | {s.member_id for s in open_sessions}
    found = briefs(member_ids)
    return {
        "classes": {str(c.id): _counts([found[m] for m in by_class.get(c.id, [])]) for c in open_classes},
        "ptSessions": {str(s.id): _badge(found[s.member_id]) for s in open_sessions},
    }


# Badges for My Clients (progress.views.coach_clients): None for a client
# whose last session is too long ago to still see their health notes.
def client_badges(coach, member_ids):
    allowed = viewable_member_ids(coach, member_ids)
    found = briefs(allowed)
    return {member_id: (_badge(found[member_id]) if member_id in allowed else None) for member_id in member_ids}


def member_entry(member, brief):
    return {"memberId": member.id, "name": member.name, **brief}


def members_by_name(member_ids):
    return list(Member.objects.filter(id__in=member_ids).order_by("name", "id"))

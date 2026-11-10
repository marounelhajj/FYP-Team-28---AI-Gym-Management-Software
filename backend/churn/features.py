from bisect import bisect_left
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone

from audit.models import AuditLog
from billing.models import Payment
from checkins.models import CheckIn
from classes.models import ClassBooking, PTSession
from members.models import Member
from training.models import TrainingEvent

from . import config

# The features both scoring methods use, computed "as of" a date from data
# the app already keeps:
#
#   attendance     allowed check-ins (checkins.CheckIn, SCRUM-33)
#   no-shows       class bookings / PT sessions marked No-show (SCRUM-36)
#   payments       billing.Payment (SCRUM-39/55/107). There is no record of
#                  a *failed* payment in this app - payments are only stored
#                  once made - so the payment signal is a subscription that
#                  lapsed and wasn't renewed, or renewals paid late.
#   freezes        a freeze running now (status Frozen with a subscription
#                  still valid), and past freezes from the audit log
#                  ("member.frozen" / "member.resumed", SCRUM-41/124)
#   cancellations  the "cancellation" training event (SCRUM-73), falling
#                  back to the audit log - used as the model's label
#
# Everything is loaded once per branch (BranchHistory) and then evaluated
# in memory for any date, so the model can be trained on many past cutoffs
# without a query per member per cutoff, and a past cutoff never sees data
# from after it.


def day_end(day):
    # The first moment after `day` in the gym's local time: "as of 10 Nov"
    # includes everything that happened on 10 Nov.
    return timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


def week_start(day):
    return day - timedelta(days=day.weekday())


@dataclass
class Features:
    visits_recent: int
    visits_prior: int
    recent_per_week: float
    prior_per_week: float
    last_visit: str | None
    days_since_last_visit: int | None
    no_shows: int
    lapsed: bool
    lapsed_since: str | None
    late_payments: int
    last_late_payment: str | None
    last_late_days: int | None
    freeze_active: bool
    past_freezes: int
    last_freeze: str | None
    tenure_days: int
    membership_ends: str | None
    days_to_renewal: int | None

    def as_dict(self):
        return asdict(self)


def _clamp(value):
    return max(0.0, min(1.0, value))


# Turns raw features into 0-1 risk signals, one per RULE_WEIGHTS key. The
# learned model uses the same signals as its inputs.
def signals(f):
    if isinstance(f, dict):
        f = Features(**f)
    if f.prior_per_week > 0:
        attendance_drop = _clamp((f.prior_per_week - f.recent_per_week) / f.prior_per_week)
    else:
        attendance_drop = 0.0

    if f.days_since_last_visit is None:
        # Never checked in: worrying once they've had a couple of weeks to start.
        inactivity = 1.0 if f.tenure_days > 14 else 0.5
    else:
        span = config.INACTIVE_FULL_DAYS - config.INACTIVE_FROM_DAYS
        inactivity = _clamp((f.days_since_last_visit - config.INACTIVE_FROM_DAYS) / span)

    no_shows = _clamp(f.no_shows / config.NO_SHOWS_FULL)
    payment = 1.0 if f.lapsed else _clamp(0.5 * f.late_payments)
    freeze = 1.0 if f.freeze_active else (0.5 if f.past_freezes else 0.0)

    if f.tenure_days <= 30:
        new_member = 1.0
    elif f.tenure_days <= config.NEW_MEMBER_DAYS:
        new_member = 1.0 - 0.6 * (f.tenure_days - 30) / (config.NEW_MEMBER_DAYS - 30)
    else:
        new_member = 0.0

    if not f.lapsed and f.days_to_renewal is not None and 0 <= f.days_to_renewal <= config.RENEWAL_WINDOW_DAYS:
        renewal_soon = 1.0 - 0.7 * f.days_to_renewal / config.RENEWAL_WINDOW_DAYS
    else:
        renewal_soon = 0.0

    return {
        "attendance_drop": attendance_drop,
        "inactivity": inactivity,
        "no_shows": no_shows,
        "payment": payment,
        "freeze": freeze,
        "new_member": new_member,
        "renewal_soon": renewal_soon,
    }


FEATURE_KEYS = list(config.RULE_WEIGHTS)


def _weeks_between(start, end, cap):
    if end <= start:
        return 0
    return min(cap, (end - start).total_seconds() / (7 * 86400))


def _iso(value):
    return value.isoformat() if value else None


class BranchHistory:
    """Everything needed to compute features for a set of members, loaded once."""

    def __init__(self, members):
        self.members = {m.pk: m for m in members}
        ids = list(self.members)
        self.visits = defaultdict(list)
        for member_id, at in (
            CheckIn.objects.filter(member_id__in=ids, result=CheckIn.Result.ALLOWED)
            .order_by("checked_in_at").values_list("member_id", "checked_in_at")
        ):
            self.visits[member_id].append(at)

        self.no_shows = defaultdict(list)
        for member_id, at in ClassBooking.objects.filter(
            member_id__in=ids, status=ClassBooking.Status.BOOKED, attendance=ClassBooking.Attendance.NO_SHOW,
        ).values_list("member_id", "gym_class__starts_at"):
            self.no_shows[member_id].append(at)
        for member_id, at in PTSession.objects.filter(
            member_id__in=ids, attendance=ClassBooking.Attendance.NO_SHOW,
        ).values_list("member_id", "starts_at"):
            self.no_shows[member_id].append(at)
        for times in self.no_shows.values():
            times.sort()

        self.payments = defaultdict(list)
        for member_id, paid_at, expires_at in (
            Payment.objects.filter(member_id__in=ids).order_by("paid_at", "id")
            .values_list("member_id", "paid_at", "expires_at")
        ):
            self.payments[member_id].append((paid_at, expires_at))

        # Freeze / resume / cancel events from the audit log, oldest first.
        self.status_events = defaultdict(list)
        actions = [AuditLog.Action.MEMBER_FROZEN, AuditLog.Action.MEMBER_RESUMED, AuditLog.Action.MEMBER_CANCELLED]
        for target_id, action, at in (
            AuditLog.objects.filter(target_type="member", target_id__in=[str(i) for i in ids], action__in=actions)
            .order_by("created_at", "id").values_list("target_id", "action", "created_at")
        ):
            self.status_events[int(target_id)].append((at, action))

        self.cancelled_at = {}
        for member_id, at in (
            TrainingEvent.objects.filter(member_id__in=ids, event_type=TrainingEvent.EventType.CANCELLATION)
            .order_by("occurred_at").values_list("member_id", "occurred_at")
        ):
            self.cancelled_at.setdefault(member_id, at)
        for member_id, events in self.status_events.items():
            if member_id not in self.cancelled_at:
                for at, action in events:
                    if action == AuditLog.Action.MEMBER_CANCELLED:
                        self.cancelled_at[member_id] = at
                        break

    @classmethod
    def for_branch(cls, branch):
        return cls(Member.objects.filter(branch=branch))

    def cancellation_date(self, member_id):
        at = self.cancelled_at.get(member_id)
        return timezone.localtime(at).date() if at else None

    def earliest_activity(self):
        dates = [m.join_date for m in self.members.values()]
        return min(dates) if dates else None

    # Features for one member as of the end of `as_of`. live=True means
    # "right now": the member's current status and expiry are trusted
    # directly instead of being rebuilt from history.
    def features(self, member_id, as_of, live=False):
        member = self.members[member_id]
        end = day_end(as_of)
        recent_start = end - timedelta(weeks=config.RECENT_WEEKS)
        prior_start = recent_start - timedelta(weeks=config.PRIOR_WEEKS)

        visits = self.visits.get(member_id, [])
        upto = bisect_left(visits, end)
        recent = upto - bisect_left(visits, recent_start)
        prior = bisect_left(visits, recent_start) - bisect_left(visits, prior_start)
        last_visit = timezone.localtime(visits[upto - 1]).date() if upto else None

        no_shows = self.no_shows.get(member_id, [])
        no_show_count = bisect_left(no_shows, end) - bisect_left(no_shows, end - timedelta(days=config.NO_SHOW_WINDOW_DAYS))

        payments = [(paid, expires) for paid, expires in self.payments.get(member_id, []) if paid < end]
        if live:
            expires = member.subscription_expires_at
        else:
            expires = max((e for _, e in payments), default=None)
        lapsed = expires is None or expires < as_of

        history_start = as_of - timedelta(days=config.HISTORY_WINDOW_DAYS)
        late, last_late, last_late_days = 0, None, None
        for (_, previous_expiry), (paid, _) in zip(payments, payments[1:]):
            paid_day = timezone.localtime(paid).date()
            days_late = (paid_day - previous_expiry).days
            if paid_day >= history_start and days_late > config.LATE_PAYMENT_GRACE_DAYS:
                late += 1
                last_late, last_late_days = paid_day, days_late

        events = [(at, action) for at, action in self.status_events.get(member_id, []) if at < end]
        freezes = [timezone.localtime(at).date() for at, action in events if action == AuditLog.Action.MEMBER_FROZEN]
        if live:
            freeze_active = member.status == Member.Status.FROZEN and not lapsed
        else:
            last = next((action for _, action in reversed(events)
                         if action in (AuditLog.Action.MEMBER_FROZEN, AuditLog.Action.MEMBER_RESUMED)), None)
            freeze_active = last == AuditLog.Action.MEMBER_FROZEN and not lapsed
        past_freezes = sum(1 for d in freezes if d >= history_start)

        # A member who joined inside a window is averaged over the weeks they
        # were actually a member, so a newer member's rate isn't diluted.
        member_since = day_end(member.join_date - timedelta(days=1))
        recent_weeks = _weeks_between(max(recent_start, member_since), end, config.RECENT_WEEKS)
        prior_weeks = _weeks_between(max(prior_start, member_since), recent_start, config.PRIOR_WEEKS)

        return Features(
            visits_recent=recent,
            visits_prior=prior,
            recent_per_week=round(recent / recent_weeks, 2) if recent_weeks else 0.0,
            # Less than a week of membership before the recent window: no baseline.
            prior_per_week=round(prior / prior_weeks, 2) if prior_weeks >= 1 else 0.0,
            last_visit=_iso(last_visit),
            days_since_last_visit=(as_of - last_visit).days if last_visit else None,
            no_shows=no_show_count,
            lapsed=lapsed,
            lapsed_since=_iso(expires + timedelta(days=1)) if lapsed and expires else None,
            late_payments=late,
            last_late_payment=_iso(last_late),
            last_late_days=last_late_days,
            freeze_active=freeze_active,
            past_freezes=past_freezes,
            last_freeze=_iso(freezes[-1]) if freezes else None,
            tenure_days=max(0, (as_of - member.join_date).days),
            membership_ends=_iso(expires),
            days_to_renewal=(expires - as_of).days if expires else None,
        )

    # Members who were members (joined, not yet cancelled) at the end of `as_of`.
    def eligible(self, as_of):
        out = []
        for member_id, member in self.members.items():
            if member.join_date > as_of:
                continue
            cancelled = self.cancellation_date(member_id)
            if cancelled is not None and cancelled <= as_of:
                continue
            out.append(member_id)
        return out


def scoreable_members(branch):
    return Member.objects.filter(branch=branch).exclude(status=Member.Status.CANCELLED)


def live_history(branch):
    return BranchHistory(scoreable_members(branch))


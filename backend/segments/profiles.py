from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max, Sum
from django.utils import timezone

from billing.models import Payment
from checkins.models import CheckIn
from churn.models import ChurnScore
from classes.models import ClassBooking, PTSession
from members.models import Member
from notifications.models import NotificationSettings
from retail.models import Sale

# One behaviour profile per member, built in a handful of queries, used by
# the segment filters (filters.py) and the clustering (clustering.py).
#
# A "visit" is a day the member checked in or attended a class, counted once
# per day (attending a class usually means checking in too, so counting both
# would double it).

# Opted out of marketing = the member turned "Offers and promotions" off in
# their notification settings (notifications.NotificationSettings.offers),
# the same switch campaign offers already respect.

RECENT_DAYS = 90          # class types attended, PT client, visit mix, spend
FREQUENCY_WEEKS = 4       # "visits per week (last 4 weeks)"
ANONYMIZED_EMAIL_SUFFIX = "@deleted.invalid"   # members.privacy.anonymize_member


@dataclass
class Profile:
    id: int
    name: str
    email: str
    branch: str
    plan: str
    status: str
    join_date: date
    date_of_birth: date | None
    opted_out: bool
    anonymized: bool
    subscription_expires_at: date | None
    visit_days: set = field(default_factory=set)        # every visit day on record
    last_visit: date | None = None
    visits_last_4_weeks: int = 0
    class_types: set = field(default_factory=set)       # attended in the last 90 days
    class_visits_90: int = 0
    pt_sessions_90: int = 0
    gym_visits_90: int = 0
    visit_hours_90: list = field(default_factory=list)
    spend_90: Decimal = Decimal("0")
    risk_level: str | None = None

    def age(self, today):
        if self.date_of_birth is None:
            return None
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def tenure_months(self, today):
        return max(0, (today - self.join_date).days) / 30.44

    def visits_per_week(self):
        return self.visits_last_4_weeks / FREQUENCY_WEEKS

    def days_since_last_visit(self, today):
        return None if self.last_visit is None else (today - self.last_visit).days

    def renewal_in_days(self, today):
        if self.subscription_expires_at is None:
            return None
        return (self.subscription_expires_at - today).days

    @property
    def pt_client(self):
        return self.pt_sessions_90 > 0


def start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def build_profiles(members, today=None):
    """Profiles for the given Member queryset, keyed by member id."""
    today = today or timezone.localdate()
    now = timezone.now()
    recent_start = today - timedelta(days=RECENT_DAYS - 1)
    freq_start = today - timedelta(days=FREQUENCY_WEEKS * 7 - 1)

    profiles = {}
    for m in members.only(
        "id", "name", "email", "branch", "membership_plan", "status", "join_date", "date_of_birth",
        "subscription_expires_at",
    ):
        profiles[m.id] = Profile(
            id=m.id, name=m.name, email=m.email, branch=m.branch, plan=m.membership_plan, status=m.status,
            join_date=m.join_date, date_of_birth=m.date_of_birth, opted_out=False,
            anonymized=m.email.endswith(ANONYMIZED_EMAIL_SUFFIX),
            subscription_expires_at=m.subscription_expires_at,
        )
    if not profiles:
        return profiles
    ids = list(profiles)
    for member_id in NotificationSettings.objects.filter(member_id__in=ids, offers=False).values_list("member_id", flat=True):
        profiles[member_id].opted_out = True

    # Check-ins (allowed only): every visit day, plus time of day for the recent ones.
    recent_checkin_days = defaultdict(set)
    for member_id, at in CheckIn.objects.filter(
        member_id__in=ids, result=CheckIn.Result.ALLOWED,
    ).values_list("member_id", "checked_in_at"):
        local = timezone.localtime(at)
        p = profiles[member_id]
        p.visit_days.add(local.date())
        if local.date() >= recent_start:
            if local.date() not in recent_checkin_days[member_id]:
                p.visit_hours_90.append(local.hour + local.minute / 60)
            recent_checkin_days[member_id].add(local.date())

    # Classes attended.
    recent_class_days = defaultdict(set)
    for member_id, starts_at, type_name in ClassBooking.objects.filter(
        member_id__in=ids, attendance=ClassBooking.Attendance.ATTENDED,
    ).values_list("member_id", "gym_class__starts_at", "gym_class__class_type__name"):
        local = timezone.localtime(starts_at)
        p = profiles[member_id]
        p.visit_days.add(local.date())
        if local.date() >= recent_start:
            p.class_types.add(type_name)
            p.class_visits_90 += 1
            if local.date() not in recent_class_days[member_id]:
                recent_class_days[member_id].add(local.date())
                if local.date() not in recent_checkin_days[member_id]:
                    p.visit_hours_90.append(local.hour + local.minute / 60)

    # PT sessions that happened (not cancelled, not a no-show, already started).
    for member_id, starts_at in PTSession.objects.filter(
        member_id__in=ids, starts_at__gte=start_of(recent_start),
        starts_at__lte=now,
    ).exclude(status=PTSession.Status.CANCELLED).exclude(
        attendance=ClassBooking.Attendance.NO_SHOW,
    ).values_list("member_id", "starts_at"):
        profiles[member_id].pt_sessions_90 += 1

    for p in profiles.values():
        if p.visit_days:
            p.last_visit = max(p.visit_days)
            p.visits_last_4_weeks = sum(1 for d in p.visit_days if freq_start <= d <= today)
        recent_days = recent_checkin_days[p.id] | recent_class_days[p.id]
        # Gym-floor visits: recent visit days that weren't a class or PT day.
        p.gym_visits_90 = max(0, len(recent_days) - len(recent_class_days[p.id]) - p.pt_sessions_90)

    # Spend in the last 90 days: membership payments + point-of-sale purchases.
    since = start_of(recent_start)
    for row in Payment.objects.filter(member_id__in=ids, paid_at__gte=since).values("member_id").annotate(t=Sum("amount")):
        profiles[row["member_id"]].spend_90 += row["t"] or 0
    for row in Sale.objects.filter(
        member_id__in=ids, sold_at__gte=since, voided_at__isnull=True,
    ).values("member_id").annotate(t=Sum("total")):
        profiles[row["member_id"]].spend_90 += row["t"] or 0

    # Churn risk level from each member's latest weekly score (SCRUM-118).
    latest = (
        ChurnScore.objects.filter(member_id__in=ids).values("member_id").annotate(w=Max("week_start"))
    )
    latest_week = {r["member_id"]: r["w"] for r in latest}
    for member_id, week, level in ChurnScore.objects.filter(member_id__in=ids).values_list(
        "member_id", "week_start", "level",
    ):
        if latest_week.get(member_id) == week:
            profiles[member_id].risk_level = level

    return profiles


def members_in_branches(branches):
    return Member.objects.filter(branch__in=branches)

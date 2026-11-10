import json
import random
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from administration.models import StaffAccount
from audit.models import AuditLog
from billing.models import Payment
from checkins.models import CheckIn
from churn.features import week_start
from churn.models import BranchCallSettings, ChurnRun, ChurnScore, RetentionCall
from churn.reasons import explain
from churn.scoring import refresh_branch
from churn.testing import backdating
from classes.models import ClassBooking, ClassType, GymClass
from members.models import Member, Waiver
from members.waiver import WAIVER_VERSION
from training.models import TrainingEvent

from .seed_demo import FIRST, LAST, at
from .seed_demo_sprint3 import Command as SprintThreeSeed

# The Sprint 4 demo database (docs/sprint4-demo-script.md): the at-risk
# members feature (SCRUM-118, 119, 120, 68).
#
#   GYM_DB_PATH=demo/.data/demo.sqlite3 python manage.py seed_demo_sprint4 --credentials demo/.data/credentials.json
#
# Everything the Sprint 3 seed makes, plus:
#
#   * Hamra, the established branch: ~240 more members with seven months of
#     check-ins, monthly or yearly payments (some paid late), freezes,
#     class no-shows and ~55 cancellations - enough labelled history for the
#     learned model (30 cancellations / 200 members, see churn/config.py).
#     A handful of named members show clear warning signs right now.
#   * Zalka, a branch that opened seven weeks ago: a few members and only
#     recent check-ins, so it falls back to the rule-based score.
#   * Eight past weekly at-risk lists for Hamra, with retention calls on
#     them, so the accuracy panel has finished weeks to measure.
#   * A weekly call capacity of 5 at Hamra in past weeks and 8 this week, so
#     the demo can lower it to 5 and the cap is visible.
#
# Same guards as seed_demo: a separate database only, and every login gets
# a fresh password written only to --credentials (git-ignored).

HAMRA, ZALKA = "Hamra", "Zalka"
HISTORY_MEMBERS = 240
PAST_WEEKS = 8

# Named Hamra members with a clear pattern right now.
# Names outside the seed's random first/last name lists, so they're unique.
SHOWCASE = [
    # key, name, plan
    ("fading", "Joelle Abi Nader", "Standard"),
    ("noShows", "Karl Tannous", "Premium"),
    ("lapsed", "Maya Sfeir", "Basic"),
    ("frozen", "Georges Bitar", "Standard"),
    ("newbie", "Lynn Azar", "Basic"),
    ("latePayer", "Wissam Hobeika", "Standard"),
    ("renewing", "Rita Zogheib", "Premium"),
]
# Calls the Hamra team could make in past weeks (SCRUM-120), small so the cap
# shows; this week starts at 8 and the demo lowers it to 5.
HAMRA_CAPACITY = 5
HAMRA_CAPACITY_THIS_WEEK = 8


class Command(SprintThreeSeed):
    help = "Seeds the Sprint 4 demo database (Sprint 3 data plus churn history, at-risk lists and calls)."

    def handle(self, *args, **options):
        super().handle(*args, **options)
        self.rng = random.Random(118)
        self.today = timezone.localdate()
        self.now = timezone.now()
        self.desk = StaffAccount.objects.get(username="dsarkis")
        self.checkins, self.payments, self.audit, self.events, self.bookings = [], [], [], [], []
        self.classes = self.past_classes()
        names = {m.name for m in Member.objects.all()} | {name for _, name, _ in SHOWCASE}

        for i in range(HISTORY_MEMBERS):
            name = self.unique_name(names)
            self.history_member(name, i)
        showcase = {key: self.showcase_member(key, name, plan) for key, name, plan in SHOWCASE}
        self.new_branch(names)
        self.flush()

        # Past weekly lists (oldest first), then this week's.
        BranchCallSettings.objects.update_or_create(branch=HAMRA, defaults={"weekly_capacity": HAMRA_CAPACITY})
        for weeks_back in range(PAST_WEEKS, 0, -1):
            as_of = week_start(self.today) - timedelta(days=7 * weeks_back)
            refresh_branch(HAMRA, as_of=as_of, trigger=ChurnRun.Trigger.SCHEDULED)
        self.after_backfill()
        # This week starts at 8 calls, so the demo can lower it to 5 and show the trim.
        BranchCallSettings.objects.filter(branch=HAMRA).update(weekly_capacity=HAMRA_CAPACITY_THIS_WEEK)
        for branch in Member.Branch.values:
            refresh_branch(branch, trigger=ChurnRun.Trigger.SCHEDULED)

        path = Path(options["credentials"])
        credentials = json.loads(path.read_text())
        showcase.update(self.zalka_showcase)
        credentials["named"]["atRisk"] = {key: {"id": m.pk, "name": m.name} for key, m in showcase.items()}
        path.write_text(json.dumps(credentials, indent=2))
        runs = ChurnRun.objects.filter(week_start=week_start(self.today))
        summary = ", ".join(f"{r.branch}: {r.method}" for r in runs)
        self.stdout.write(self.style.SUCCESS(f"Sprint 4 data ready ({summary})."))

    # Retention calls on each past week's call list (SCRUM-68), with outcomes
    # that fit what each member went on to do, so the accuracy panel
    # (SCRUM-120) has finished weeks to measure.
    def after_backfill(self):
        rng = self.rng
        cancelled = {
            e.member_id: timezone.localtime(e.occurred_at).date()
            for e in TrainingEvent.objects.filter(event_type=TrainingEvent.EventType.CANCELLATION)
        }
        events = []
        for run in ChurnRun.objects.filter(branch=HAMRA).order_by("week_start"):
            for entry in ChurnScore.objects.filter(run=run, rank__lte=run.call_capacity).select_related("member"):
                if rng.random() < 0.15:
                    continue  # the team didn't get to everyone every week
                left = cancelled.get(entry.member_id)
                leaving = left is not None and run.as_of < left <= run.as_of + timedelta(days=30)
                if leaving:
                    outcome = rng.choice(["cancelled_anyway", "reached", "no_answer"])
                else:
                    outcome = rng.choices(["saved", "reached", "no_answer"], [45, 40, 15])[0]
                called_at = at(run.as_of + timedelta(days=rng.randint(0, 3)), rng.randint(10, 18), rng.randint(0, 59))
                reasons = explain(entry.reasons, entry.features, run.as_of)
                call = RetentionCall.objects.create(
                    member=entry.member, branch=HAMRA, week_start=run.week_start, outcome=outcome, called_at=called_at,
                    called_by=self.desk, called_by_name=self.desk.full_name, churn_score=entry, score=entry.score,
                    level=entry.level, rank=entry.rank, method=entry.method, model_version=entry.model_version,
                    reasons=[{"feature": r["feature"], **t} for r, t in zip(entry.reasons, reasons)],
                    note=rng.choice(["", "", "Busy at work this month", "Will think about it", "Coming back next week"]),
                )
                events.append(TrainingEvent(
                    event_type=TrainingEvent.EventType.RETENTION_CALL, member=entry.member, branch=HAMRA,
                    occurred_at=called_at, session_id=f"call:{call.pk}",
                    payload={"callId": call.pk, "outcome": outcome, "contacted": outcome != "no_answer",
                             "weekStart": run.week_start.isoformat(), "score": entry.score, "level": entry.level,
                             "rank": entry.rank, "method": entry.method, "modelVersion": entry.model_version,
                             "reasons": [r["feature"] for r in entry.reasons], "followUp": False},
                ))
        TrainingEvent.objects.bulk_create(events)

    # --- helpers ----------------------------------------------------------

    def unique_name(self, taken):
        while True:
            name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
            if name not in taken:
                taken.add(name)
                return name
            # Fall back to a middle initial once the simple names run out.
            name = f"{self.rng.choice(FIRST)} {chr(65 + self.rng.randint(0, 25))}. {self.rng.choice(LAST)}"
            if name not in taken:
                taken.add(name)
                return name

    def create_member(self, name, branch, plan, joined):
        member = Member.objects.create(
            name=name, email=name.lower().replace(" ", ".").replace("..", ".") + f"{self.rng.randint(10, 99)}@example.com",
            phone=f"+961 7{self.rng.randint(1000000, 9999999)}", branch=branch, membership_plan=plan,
            join_date=joined, status=Member.Status.ACTIVE,
        )
        Waiver.objects.create(
            member=member, signature_name=name, health_disclaimer_accepted=True, liability_waiver_accepted=True,
            waiver_version=WAIVER_VERSION, signed_via=Waiver.SignedVia.FRONT_DESK, signed_at=at(joined, 10),
        )
        self.audit_entry(AuditLog.Action.MEMBER_REGISTERED, member, at(joined, 10), f"Registered {name} on {plan}", staff=True)
        return member

    def audit_entry(self, action, member, when, summary, staff=False):
        entry = AuditLog(action=action, summary=summary, created_at=when, branch=member.branch, ip_address="127.0.0.1",
                         target_type="member", target_id=str(member.pk), target_label=member.name)
        if staff:
            entry.actor_type = AuditLog.ActorType.STAFF
            entry.actor_staff = self.desk
            entry.actor_name, entry.actor_username, entry.actor_role = self.desk.full_name, self.desk.username, self.desk.role.name
        else:
            entry.actor_type = AuditLog.ActorType.MEMBER
            entry.actor_member = member
            entry.actor_name, entry.actor_role = member.name, "Member"
        self.audit.append(entry)

    # Visits between two dates (inclusive) at `per_week` on average.
    def visit(self, member, start, end, per_week):
        day = start
        while day <= end and day <= self.today:
            if self.rng.random() < per_week / 7:
                start_at = at(day, self.rng.choice([7, 8, 12, 17, 18, 19, 20]), self.rng.randint(0, 59))
                if start_at < self.now - timedelta(hours=5):
                    self.checkins.append(CheckIn(
                        member=member, result=CheckIn.Result.ALLOWED, branch=member.branch,
                        checked_in_at=start_at, checked_out_at=start_at + timedelta(minutes=self.rng.randint(40, 95)),
                    ))
            day += timedelta(days=1)

    # Monthly (or yearly) payments from joining until `until`. late: set of
    # renewal numbers paid `late_days` after the previous expiry.
    def pay(self, member, until, yearly=False, late=(), late_days=8):
        step = 365 if yearly else 30
        paid_on, number, expires = member.join_date, 0, None
        while paid_on <= until:
            if number in late:
                paid_on += timedelta(days=late_days)
                if paid_on > until:
                    break
            expires = paid_on + timedelta(days=step)
            self.payments.append(Payment(
                member=member, amount="480.00" if yearly else "40.00", method=self.rng.choice(["Cash", "Card"]),
                duration="1 Year" if yearly else "1 Month", expires_at=expires,
                paid_at=at(paid_on, self.rng.randint(9, 19), self.rng.randint(0, 59)),
                note="First payment at registration" if number == 0 else "Renewal", recorded_by=self.desk,
            ))
            number += 1
            paid_on = expires
        return expires

    def no_show(self, member, day):
        used = {b.gym_class.pk for b in self.bookings if b.member is member}
        options = [c for c in self.classes if c.pk not in used and timezone.localtime(c.starts_at).date() <= self.today]
        gym_class = min(options, key=lambda c: abs((timezone.localtime(c.starts_at).date() - day).days))
        self.bookings.append(ClassBooking(gym_class=gym_class, member=member, attendance=ClassBooking.Attendance.NO_SHOW))

    def cancel(self, member, day):
        when = at(day, self.rng.randint(9, 20))
        member.status = Member.Status.CANCELLED
        self.audit_entry(AuditLog.Action.MEMBER_CANCELLED, member, when, f"{member.name} cancelled their membership in the app")
        self.events.append(TrainingEvent(event_type=TrainingEvent.EventType.CANCELLATION, member=member, branch=member.branch,
                                         occurred_at=when, payload={"channel": "app"}))

    def freeze(self, member, day, resume=None):
        self.audit_entry(AuditLog.Action.MEMBER_FROZEN, member, at(day, 11), f"{member.name} froze their membership in the app")
        if resume:
            self.audit_entry(AuditLog.Action.MEMBER_RESUMED, member, at(resume, 11), f"{member.name} resumed their membership")

    def past_classes(self):
        coach = StaffAccount.objects.get(username="hnasser")
        spin = ClassType.objects.filter(branch=HAMRA, name="Spinning").first()
        out = []
        for back in range(3, 220, 3):
            starts = at(self.today - timedelta(days=back), 18)
            out.append(GymClass.objects.create(
                branch=HAMRA, class_type=spin, name="Spinning", coach=coach, room="Cycle Studio",
                capacity=spin.max_capacity, starts_at=starts, ends_at=starts + timedelta(minutes=45),
            ))
        return out

    # --- Hamra's history -------------------------------------------------

    def history_member(self, name, i):
        rng = self.rng
        fate = rng.choices(["healthy", "churned", "early"], [72, 21, 7])[0]
        joined = self.today - timedelta(days=rng.randint(200, 330) if fate != "early" else rng.randint(60, 300))
        plan = rng.choice(["Basic", "Standard", "Standard", "Premium"])
        member = self.create_member(name, HAMRA, plan, joined)
        rate = rng.uniform(1.5, 4.2)
        yearly = fate == "healthy" and rng.random() < 0.4

        if fate == "healthy":
            # A few healthy members have a quiet patch too, so warning signs aren't perfect.
            self.visit(member, joined, self.today, rate)
            if rng.random() < 0.3:
                # A quiet patch (holiday, injury, exams) that they came back from.
                dip = self.today - timedelta(days=rng.randint(20, 170))
                length = timedelta(days=rng.randint(14, 32))
                self.checkins = [c for c in self.checkins if not (c.member is member and dip <= timezone.localtime(c.checked_in_at).date() < dip + length)]
            late = {rng.randint(1, 5)} if rng.random() < 0.15 else ()
            member.subscription_expires_at = self.pay(member, self.today, yearly=yearly, late=late)
            if rng.random() < 0.06:
                start = self.today - timedelta(days=rng.randint(60, 170))
                self.freeze(member, start, resume=start + timedelta(days=14))
        else:
            if fate == "early":
                cancel_day = joined + timedelta(days=rng.randint(35, 85))
            else:
                cancel_day = self.today - timedelta(days=rng.randint(8, 190))
                cancel_day = max(cancel_day, joined + timedelta(days=100))
            cancel_day = min(cancel_day, self.today - timedelta(days=3))
            if rng.random() < 0.35:
                # Some leave with no warning in their visits.
                fade = cancel_day - timedelta(days=rng.randint(3, 10))
                self.visit(member, joined, fade, rate)
            else:
                fade = cancel_day - timedelta(days=rng.randint(25, 45))
                self.visit(member, joined, fade, rate)
                self.visit(member, fade, cancel_day - timedelta(days=12), rate * rng.uniform(0.15, 0.5))
            late = {rng.randint(1, 3)} if rng.random() < 0.45 else ()
            member.subscription_expires_at = self.pay(member, cancel_day - timedelta(days=1), late=late, late_days=rng.randint(6, 14))
            if rng.random() < 0.3:
                self.freeze(member, fade + timedelta(days=rng.randint(0, 10)))
            for _ in range(rng.choice([0, 0, 1, 2, 3])):
                self.no_show(member, fade + timedelta(days=rng.randint(0, 20)))
            self.cancel(member, cancel_day)
        member.save()

    # --- Members with clear warning signs right now ------------------------

    def showcase_member(self, key, name, plan):
        t, rng = self.today, self.rng
        joined = t - timedelta(days=42 if key == "newbie" else rng.randint(240, 320))
        member = self.create_member(name, HAMRA, plan, joined)
        if key == "fading":
            # Three visits a week, down to one in the last month; renews in 12 days.
            self.visit(member, joined, t - timedelta(days=29), 3.2)
            for back in (25, 17, 9, 3):
                self.visit(member, t - timedelta(days=back), t - timedelta(days=back), 7)
            self.pay(member, t - timedelta(days=19))
            member.subscription_expires_at = t + timedelta(days=12)
        elif key == "noShows":
            self.visit(member, joined, t - timedelta(days=30), 2.8)
            self.visit(member, t - timedelta(days=29), t, 0.8)
            for back in (6, 13):
                self.no_show(member, t - timedelta(days=back))
            member.subscription_expires_at = self.pay(member, t)
        elif key == "lapsed":
            # Renewal overdue since 9 days ago, not seen in three weeks.
            self.visit(member, joined, t - timedelta(days=22), 2.5)
            self.pay(member, t - timedelta(days=40))
            member.subscription_expires_at = t - timedelta(days=9)
            member.status = Member.Status.FROZEN
        elif key == "frozen":
            self.visit(member, joined, t - timedelta(days=16), 3)
            self.freeze(member, t - timedelta(days=120), resume=t - timedelta(days=100))
            self.freeze(member, t - timedelta(days=15))
            member.subscription_expires_at = self.pay(member, t)
            member.status = Member.Status.FROZEN
        elif key == "newbie":
            for back in (40, 33, 19):
                self.visit(member, t - timedelta(days=back), t - timedelta(days=back), 7)
            member.subscription_expires_at = self.pay(member, t)
        elif key == "latePayer":
            self.visit(member, joined, t - timedelta(days=28), 3)
            self.visit(member, t - timedelta(days=27), t, 1.2)
            member.subscription_expires_at = self.pay(member, t, late={5, 7}, late_days=10)
        elif key == "renewing":
            # Healthy attendance, but the membership ends in 5 days.
            self.visit(member, joined, t, 3)
            self.pay(member, t - timedelta(days=26))
            member.subscription_expires_at = t + timedelta(days=5)
        member.save()
        return member

    # --- Zalka: opened seven weeks ago -------------------------------------

    def new_branch(self, names):
        t = self.today
        # The Sprint 2 seed's Zalka members joined when the branch opened.
        for member in Member.objects.filter(branch=ZALKA):
            joined = t - timedelta(days=self.rng.randint(35, 49))
            Member.objects.filter(pk=member.pk).update(join_date=joined, status=Member.Status.ACTIVE,
                                                       subscription_expires_at=t + timedelta(days=self.rng.randint(3, 25)))
            member.join_date = joined
            self.visit(member, joined, t, self.rng.uniform(1.5, 3.5))
        # Two with warning signs: stopped coming after a good start, and a no-show who is fading.
        quiet = self.create_member(self.unique_name(names), ZALKA, "Standard", t - timedelta(days=44))
        for back in (43, 41, 38, 36, 34, 31, 29, 27, 24):
            self.visit(quiet, t - timedelta(days=back), t - timedelta(days=back), 7)
        quiet.subscription_expires_at = t + timedelta(days=4)
        quiet.save()
        drifting = self.create_member(self.unique_name(names), ZALKA, "Basic", t - timedelta(days=48))
        for back in (47, 45, 42, 40, 38, 35, 33, 31, 20, 9):
            self.visit(drifting, t - timedelta(days=back), t - timedelta(days=back), 7)
        drifting.subscription_expires_at = t - timedelta(days=3)
        drifting.status = Member.Status.FROZEN
        drifting.save()
        self.zalka_showcase = {"zalkaQuiet": quiet, "zalkaLapsed": drifting}
        for i in range(7):
            joined = t - timedelta(days=self.rng.randint(5, 45))
            member = self.create_member(self.unique_name(names), ZALKA, "Basic", joined)
            rate = 0.4 if i < 2 else self.rng.uniform(1.5, 3.5)
            self.visit(member, joined, t, rate)
            member.subscription_expires_at = self.pay(member, t)
            member.save()

    def flush(self):
        with backdating(CheckIn, "checked_in_at"), backdating(Payment, "paid_at"):
            CheckIn.objects.bulk_create(self.checkins, batch_size=2000)
            Payment.objects.bulk_create(self.payments, batch_size=2000)
        AuditLog.objects.bulk_create(self.audit, batch_size=2000)
        TrainingEvent.objects.bulk_create(self.events, batch_size=2000)
        ClassBooking.objects.bulk_create(self.bookings, batch_size=2000)

import io
import json
import random
import time as clock
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.utils import timezone

from administration.models import StaffAccount
from billing.models import Payment
from branchfeedback.models import BranchSurvey, Complaint, ComplaintMessage
from checkins.models import CheckIn
from churn.models import RetentionCall
from classes import rules
from classes.models import ClassBooking, ClassType, CoverRequest, GymClass, PTSession, TimeOff
from coaching.models import ClientGoal, LoggedExercise, SessionLog
from feedback.models import CoachFeedback
from finance.models import Expense
from healthnotes.models import HealthDeclaration, HealthNote
from loyalty.models import LoyaltyPointEntry
from loyalty.points import award_class_attendance, award_pt_attendance, award_referral, balance
from marketing import offers
from marketing.models import CampaignRecipient, CampaignRedemption, MarketingCampaign
from members.models import Member
from notifications.models import StaffNotification
from payroll.models import CoachPayRate
from purchasing import orders as purchasing_rules
from purchasing.models import PurchaseOrder, PurchaseOrderLine, PurchaseReceipt, Supplier
from retail.models import BranchStock, Product, Sale, SaleItem
from segments.clustering import run_clustering
from training.events import log_training_event
from training.models import TrainingEvent

from .seed_demo import at
from .seed_demo_sprint4 import HAMRA, ZALKA, Command as SprintFourSeed

JNAH, ACHRAFIEH = "Jnah", "Achrafieh"

# The full Sprint 4 demo database (docs/sprint4-demo-script.md): everything
# seed_demo_sprint4 makes (the at-risk stories), plus data for every other
# Sprint 4 story.
#
#   GYM_DB_PATH=demo/.data/demo.sqlite3 python manage.py seed_demo_sprint4_full --credentials demo/.data/credentials.json
#
# Same guards as seed_demo: a separate database only, fresh passwords written
# only to --credentials (git-ignored).
#
# Member segments (SCRUM-43): Hamra's members get a habit ("persona") so the
# suggested segments have real groups to find - early-morning PT clients,
# evening class-goers, lunchtime gym-floor regulars, late-evening gym-floor
# regulars - on top of the newcomers who drift away that the Sprint 4 seed
# already makes. Each habit also shops differently at the desk (SCRUM-113's
# shop uptake per segment).
#
# The other Sprint 4 stories, in the order they're seeded:
#   * Before the shared bulk flush (so the churn refresh scores them):
#     Achrafieh as a mid-size branch (SCRUM-51/105) and Lea's loyalty history
#     with a referred friend (SCRUM-130/131).
#   * After the churn refresh: persona classes and PT, coach stories (health
#     notes SCRUM-85, session logs SCRUM-35, pay rates SCRUM-79, a class
#     needing a substitute SCRUM-89), member feedback and complaints
#     (SCRUM-54/94/23/24), Achrafieh's shop and costs (SCRUM-105), stock and
#     supply orders (SCRUM-21/53), campaigns (SCRUM-78/63/44), shop sales by
#     Hamra members, a retention-call follow-up (SCRUM-68) - and last, the
#     suggested segments (SCRUM-43) are clustered from all of it.

PERSONAS = {
    # name: (weight, check-in hours, classes per visit, PT per visit)
    "morning_pt": (16, [6, 7, 7, 8], 0.0, 0.45),
    "evening_classes": (30, [17, 18, 18, 19], 0.7, 0.0),
    "lunch_floor": (24, [11, 12, 12, 13], 0.0, 0.0),
    "late_floor": (30, [20, 20, 21, 21], 0.05, 0.0),
}
PT_COACHES = ["hnasser", "raoun", "osaleh", "lmansour", "jkaram"]
# What each habit buys at the desk: (chance a member shops at all, category weights).
SHOPPING = {
    "morning_pt": (0.65, {"Supplements": 6, "Drinks": 2, "Merchandise": 1}),
    "evening_classes": (0.4, {"Drinks": 5, "Supplements": 1, "Merchandise": 1}),
    "lunch_floor": (0.25, {"Drinks": 3, "Supplements": 2, "Merchandise": 1}),
    "late_floor": (0.35, {"Merchandise": 3, "Supplements": 3, "Drinks": 2}),
}

# SCRUM-51 / 105: Achrafieh, an established mid-size branch.
ACHRAFIEH_MEMBERS = 70
ACHRAFIEH_CANCELLED = 8
# SCRUM-130 / 131: Lea's fixed referral code (only ABCDEFGHJKLMNPQRSTUVWXYZ23456789) and the friend who used it.
LEA_REFERRAL_CODE = "LEA28H"
REFERRED_FRIEND = ("Chloe Rahme", "Standard")
# SCRUM-21 / 53: shelf counts per branch (Hamra, Achrafieh, Jnah, Zalka). Reorder levels come from
# seed_suppliers: Choc 10, Vanilla 10, Bar 40, Creatine 10, Water 60, Sports 24, Shaker 10, T-shirt 8, Towel 15, Gloves 6.
STOCK_BRANCHES = (HAMRA, ACHRAFIEH, JNAH, ZALKA)
STOCK = {
    "Whey Protein 1kg (Chocolate)": (14, 13, 12, 1),
    "Whey Protein 1kg (Vanilla)": (3, 14, 12, 11),
    "Protein Bar": (55, 48, 2, 44),
    "Creatine 300g": (2, 15, 14, 12),
    "Water Bottle 500ml": (110, 90, 0, 75),
    "Sports Drink": (40, 30, 3, 0),
    "Fitness Factory Shaker": (22, 18, 15, 12),
    "Fitness Factory T-Shirt": (18, 12, 10, 9),
    "Gym Towel": (6, 20, 18, 16),
    "Lifting Gloves": (9, 2, 8, 7),
}


class Command(SprintFourSeed):
    help = "Seeds the full Sprint 4 demo database (every Sprint 4 story)."

    def handle(self, *args, **options):
        started = clock.monotonic()
        self.persona_rng = random.Random(43)
        self.persona = {}
        super().handle(*args, **options)

        path = Path(options["credentials"])
        credentials = json.loads(path.read_text())
        named = credentials["named"]
        self.staff_by = {a.username: a for a in StaffAccount.objects.all()}

        self.persona_activity()                                  # SCRUM-43 (before clustering)
        self.seed_health_notes(credentials)                      # SCRUM-85 (first: Dana's PT makes Hadi busy for SCRUM-89)
        self.seed_session_logs(credentials)                      # SCRUM-35
        self.seed_pay_rates()                                    # SCRUM-79
        self.seed_cover(credentials)                             # SCRUM-89
        named["feedback"] = self.seed_feedback(credentials)      # SCRUM-54 / 94 / 23 / 24
        self.achrafieh_money()                                   # SCRUM-105
        named["supplyOrders"] = self.stock_and_orders()          # SCRUM-21 / 53
        named["campaigns"] = self.seed_campaigns()               # SCRUM-78 / 63 / 44
        self.member_shop_sales(named)                            # SCRUM-113 shop uptake per segment
        self.retention_follow_up()                               # SCRUM-68
        lea = Member.objects.get(pk=named["memberLogin"]["id"])
        self.loyalty["balanceAtSeed"] = balance(lea)
        named["loyalty"] = self.loyalty                          # SCRUM-130 / 131
        path.write_text(json.dumps(credentials, indent=2))

        # Last: the suggested segments (SCRUM-43), clustered from everything above.
        run = run_clustering()
        self.stdout.write(f"Suggested segments: {run.members_clustered} members, k={run.k}, silhouette={run.silhouette}")
        for g in run.groups.all():
            self.stdout.write(f"  {g.size:>4}  {g.name}")
        self.stdout.write(self.style.SUCCESS(f"Full Sprint 4 demo data ready in {clock.monotonic() - started:.0f}s."))

    # Runs inside the Sprint 4 seed, right before its bulk flush and the churn
    # refresh, so these members' check-ins and payments are backdated and scored
    # like everyone else's. Both keep self.rng where it was, so the at-risk and
    # accuracy data the Sprint 4 seed draws afterwards stays the same.
    def new_branch(self, names):
        super().new_branch(names)
        state = self.rng.getstate()
        self.achrafieh(names)
        self.seed_loyalty(Member.objects.get(username="lea.haddad").pk)
        self.rng.setstate(state)

    # --- personas (SCRUM-43) ---------------------------------------------

    def create_member(self, name, branch, plan, joined):
        member = super().create_member(name, branch, plan, joined)
        if branch == HAMRA:
            names = list(PERSONAS)
            self.persona[member] = self.persona_rng.choices(names, [PERSONAS[n][0] for n in names])[0]
        return member

    def visit(self, member, start, end, per_week):
        persona = self.persona.get(member)
        if persona is None:
            return super().visit(member, start, end, per_week)
        hours = PERSONAS[persona][1]
        day = start
        while day <= end and day <= self.today:
            if self.rng.random() < per_week / 7:
                start_at = at(day, self.rng.choice(hours), self.rng.randint(0, 59))
                if start_at < self.now - timedelta(hours=5):
                    self.checkins.append(CheckIn(
                        member=member, result=CheckIn.Result.ALLOWED, branch=member.branch,
                        checked_in_at=start_at, checked_out_at=start_at + timedelta(minutes=self.rng.randint(40, 95)),
                    ))
            day += timedelta(days=1)

    def persona_activity(self):
        """Classes for the class-goers and PT sessions for the PT clients, on their visit days (last 120 days)."""
        rng = self.persona_rng
        since = self.today - timedelta(days=120)
        coaches = list(StaffAccount.objects.filter(username__in=PT_COACHES))
        evening_types = list(ClassType.objects.filter(branch=HAMRA, name__in=["Spinning", "HIIT", "Body Pump", "Zumba"]))
        evening_coach = StaffAccount.objects.get(username="raoun")
        days_by_member = {}
        for c in CheckIn.objects.filter(branch=HAMRA, checked_in_at__date__gte=since).values_list("member_id", "checked_in_at"):
            days_by_member.setdefault(c[0], []).append(timezone.localtime(c[1]))
        classes = {}
        bookings, sessions, taken = [], [], set()
        for member, persona in self.persona.items():
            _, _, class_rate, pt_rate = PERSONAS[persona]
            for visit in sorted(days_by_member.get(member.pk, [])):
                if class_rate and rng.random() < class_rate:
                    ctype = rng.choice(evening_types)
                    key = (visit.date(), ctype.pk)
                    if key not in classes:
                        starts = at(visit.date(), 18, 30)
                        classes[key] = GymClass.objects.create(
                            branch=HAMRA, class_type=ctype, name=ctype.name, coach=evening_coach, room="Studio B",
                            capacity=ctype.max_capacity, starts_at=starts, ends_at=starts + timedelta(minutes=50),
                        )
                    bookings.append(ClassBooking(gym_class=classes[key], member=member,
                                                 attendance=ClassBooking.Attendance.ATTENDED))
                if pt_rate and rng.random() < pt_rate:
                    coach = rng.choice(coaches)
                    starts = visit.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=rng.choice([0, 30]))
                    if (coach.pk, starts) in taken or starts > self.now - timedelta(hours=2):
                        continue
                    taken.add((coach.pk, starts))
                    sessions.append(PTSession(coach=coach, member=member, branch=HAMRA, starts_at=starts,
                                              ends_at=starts + timedelta(hours=1),
                                              attendance=ClassBooking.Attendance.ATTENDED))
        # One booking per member per class.
        seen, unique = set(), []
        for b in bookings:
            if (b.gym_class.pk, b.member.pk) not in seen:
                seen.add((b.gym_class.pk, b.member.pk))
                unique.append(b)
        existing = set(PTSession.objects.values_list("coach_id", "starts_at"))
        sessions = [s for s in sessions if (s.coach_id, s.starts_at) not in existing]
        ClassBooking.objects.bulk_create(unique, batch_size=2000)
        PTSession.objects.bulk_create(sessions, batch_size=2000)
        self.stdout.write(f"Personas: {len(self.persona)} Hamra members, {len(unique)} class visits, {len(sessions)} PT sessions.")

    # --- before the flush: Achrafieh (SCRUM-51/105), Lea's points (SCRUM-130/131)

    # An established mid-size branch on monthly payments, a few of whom
    # cancelled (about 88% retention): amber between Hamra (red) and Jnah and
    # Zalka (green) on the retention comparison.
    def achrafieh(self, names):
        self.rng.seed(51)
        rng, t = self.rng, self.today
        for i in range(ACHRAFIEH_MEMBERS):
            joined = t - timedelta(days=rng.randint(90, 260))
            plan = rng.choice(["Basic", "Standard", "Standard", "Premium"])
            member = self.create_member(self.unique_name(names), ACHRAFIEH, plan, joined)
            if i < ACHRAFIEH_CANCELLED:
                cancel_day = t - timedelta(days=rng.randint(10, 80))
                self.visit(member, joined, cancel_day - timedelta(days=30), rng.uniform(1.5, 3))
                member.subscription_expires_at = self.pay(member, cancel_day - timedelta(days=1))
                if rng.random() < 0.5:
                    self.freeze(member, cancel_day - timedelta(days=20))
                self.cancel(member, cancel_day)
            else:
                self.visit(member, joined, t, rng.uniform(1.5, 3.5))
                member.subscription_expires_at = self.pay(member, t)
            member.save()

    # Lea's loyalty history: 10 points per attended class or private session,
    # 50 for a friend who joined with her code. Points go through the real
    # loyalty.points functions; earned_at is moved back to when each was earned.
    # One Spinning booking 3 days ago is left unsettled on purpose: the app's
    # own settle_attendance pays it out live at the first schedule request.
    def seed_loyalty(self, lea_id):
        self.rng.seed(130)
        now, today = self.now, self.today
        lea = Member.objects.get(pk=lea_id)
        Member.objects.filter(pk=lea.pk).update(referral_code=LEA_REFERRAL_CODE)
        lea.referral_code = LEA_REFERRAL_CODE

        def inside(start, end):
            self.checkins.append(CheckIn(member=lea, result=CheckIn.Result.ALLOWED, branch=HAMRA,
                                         checked_in_at=start - timedelta(minutes=12),
                                         checked_out_at=end + timedelta(minutes=18)))

        # self.classes: Hamra Spinning every 3 days (index 0 = 3 days ago).
        pending = self.classes[0]
        ClassBooking.objects.create(gym_class=pending, member=lea, booked_at=pending.starts_at - timedelta(days=1))
        inside(pending.starts_at, pending.ends_at)
        for c in self.classes[1:5]:  # 6, 9, 12 and 15 days ago
            booking = ClassBooking.objects.create(gym_class=c, member=lea, booked_at=c.starts_at - timedelta(days=2),
                                                  attendance=ClassBooking.Attendance.ATTENDED)
            inside(c.starts_at, c.ends_at)
            entry, _ = award_class_attendance(booking)
            LoyaltyPointEntry.objects.filter(pk=entry.pk).update(earned_at=c.ends_at + timedelta(minutes=5))
        # Her private session with Hadi 5 days ago (Sprint 3 seed), already Attended.
        for session in PTSession.objects.filter(member=lea, attendance=ClassBooking.Attendance.ATTENDED, ends_at__lte=now):
            inside(session.starts_at, session.ends_at)
            entry, _ = award_pt_attendance(session)
            LoyaltyPointEntry.objects.filter(pk=entry.pk).update(earned_at=session.ends_at + timedelta(minutes=5))

        # A friend who joined with her code 19 days ago and trains regularly.
        name, plan = REFERRED_FRIEND
        joined = today - timedelta(days=19)
        friend = self.create_member(name, HAMRA, plan, joined)
        self.visit(friend, joined, today, 3.0)
        friend.subscription_expires_at = self.pay(friend, today)
        friend.save()
        entry, _ = award_referral(lea, friend)
        LoyaltyPointEntry.objects.filter(pk=entry.pk).update(earned_at=at(joined, 10, 5))
        self.loyalty = {"referralCode": LEA_REFERRAL_CODE, "friend": name, "friendId": friend.pk,
                        "pendingClassId": pending.pk}

    # --- coach stories (SCRUM-85, 35, 79, 89) ----------------------------

    def free_slot(self, earliest, minutes, checks):
        start = earliest.replace(second=0, microsecond=0)
        start += timedelta(minutes=(-start.minute) % 15)
        for _ in range(32):
            end = start + timedelta(minutes=minutes)
            if all(not rules.slot_problems(branch=HAMRA, coach=c, room=room, starts_at=start, ends_at=end) for c, room in checks):
                return start, end
            start += timedelta(minutes=15)
        return start, start + timedelta(minutes=minutes)

    # SCRUM-85: Dana Aoun's private session with Hadi later today, her injuries
    # and conditions, and health notes for the live Spinning class's roster.
    def seed_health_notes(self, credentials):
        now, today, N = timezone.now(), timezone.localdate(), HealthNote
        hadi = self.staff_by["hnasser"]
        dana = Member.objects.get(pk=credentials["named"]["card"]["id"])
        # After the live class ends.
        start, end = self.free_slot(now + timedelta(minutes=165), 60, [(hadi, "")])
        pt = PTSession.objects.create(coach=hadi, member=dana, branch=HAMRA, starts_at=start, ends_at=end,
                                      note="Shoulder rehab and conditioning", booked_at=now - timedelta(days=1))
        N.objects.create(member=dana, kind=N.Kind.INJURY, body_area=N.BodyArea.SHOULDER, severity=N.Severity.SEVERE,
                         title="Rotator cuff tear, right shoulder",
                         details="Physio cleared light band work only. No overhead pressing, push-ups or pull-ups.",
                         since=today - timedelta(days=35))
        N.objects.create(member=dana, kind=N.Kind.CONDITION, body_area=N.BodyArea.HEART, severity=N.Severity.MILD,
                         title="Exercise-induced asthma", details="Inhaler in her bag. Long warm-up; stop if she is wheezing.",
                         since=today - timedelta(days=900))
        N.objects.create(member=dana, kind=N.Kind.INJURY, body_area=N.BodyArea.ANKLE, severity=N.Severity.MILD,
                         title="Sprained left ankle", status=N.Status.RESOLVED,
                         since=today - timedelta(days=80), resolved_on=today - timedelta(days=40))
        HealthDeclaration.objects.update_or_create(member=dana, defaults={"reviewed_at": now - timedelta(days=6)})
        # The live class: 2 restricted (one severe), 2 clear (one recently recovered), the rest undeclared.
        live = GymClass.objects.get(pk=credentials["named"]["liveClass"]["id"])
        roster = [b.member for b in live.bookings.filter(status=ClassBooking.Status.BOOKED).select_related("member").order_by("id")
                  if b.member_id != dana.pk]
        back, knee, clear1, clear2 = roster[:4]
        N.objects.create(member=back, kind=N.Kind.INJURY, body_area=N.BodyArea.BACK, severity=N.Severity.SEVERE,
                         title="Herniated disc, L5-S1", details="Stay seated on the bike; no standing climbs.",
                         since=today - timedelta(days=120))
        N.objects.create(member=knee, kind=N.Kind.INJURY, body_area=N.BodyArea.KNEE, severity=N.Severity.MODERATE,
                         title="Meniscus repair, left knee", details="Moderate resistance, no sprints.",
                         since=today - timedelta(days=200))
        N.objects.create(member=clear2, kind=N.Kind.INJURY, body_area=N.BodyArea.LEG, severity=N.Severity.MILD,
                         title="Pulled hamstring", status=N.Status.RESOLVED, since=today - timedelta(days=50),
                         resolved_on=today - timedelta(days=20))
        for m in (back, knee, clear1, clear2):
            HealthDeclaration.objects.update_or_create(
                member=m, defaults={"reviewed_at": now - timedelta(days=self.persona_rng.randint(3, 40))})
        credentials["named"]["healthBriefing"] = {"ptId": pt.id, "member": dana.name, "classId": live.id,
                                                  "startTime": f"{timezone.localtime(start):%H:%M}"}

    # SCRUM-35: three logged sessions with Lea (SOAP notes, exercises, goals),
    # and today's session, finished but not logged yet - the coach logs it live.
    def seed_session_logs(self, credentials):
        now, today = timezone.now(), timezone.localdate()
        hadi = self.staff_by["hnasser"]
        lea = Member.objects.get(pk=credentials["named"]["memberLogin"]["id"])
        recent = PTSession.objects.filter(coach=hadi, member=lea).order_by("-starts_at").first()  # Sprint 3's, 5 days ago
        sessions = []
        for back in (19, 12):
            starts = rules.local_datetime(today - timedelta(days=back), time(10, 0))
            session = PTSession.objects.create(
                coach=hadi, member=lea, branch=HAMRA, starts_at=starts, ends_at=starts + timedelta(hours=1),
                note="Squat form and conditioning", booked_at=starts - timedelta(days=3),
                attendance=ClassBooking.Attendance.ATTENDED)
            sessions.append(session)
            # She checked in for it, so it earned her points like the others (SCRUM-130).
            checkin = CheckIn.objects.create(member=lea, result=CheckIn.Result.ALLOWED, branch=HAMRA)
            CheckIn.objects.filter(pk=checkin.pk).update(checked_in_at=starts - timedelta(minutes=10),
                                                         checked_out_at=starts + timedelta(minutes=75))
            entry, _ = award_pt_attendance(session)
            LoyaltyPointEntry.objects.filter(pk=entry.pk).update(earned_at=session.ends_at + timedelta(minutes=5))
        sessions.append(recent)
        history = [
            ([("Squat", 4, 8, "65", 7, "Box squat to parallel"), ("Deadlift", 3, 5, "80", 7, ""), ("Lat pulldown", 3, 10, "37.5", 6, "")],
             "Right knee a bit stiff after a long day at work.", "Box squats to parallel, no pain. Hinge pattern solid.",
             "Knee tolerates load. Keep depth controlled.", "Squat 70 kg 4x8, deadlift 85 kg.", "73.4", 7),
            ([("Squat", 4, 8, "70", 8, "Box squat to parallel"), ("Deadlift", 3, 5, "85", 7, ""), ("Lat pulldown", 3, 10, "40", 7, "")],
             "Felt strong, slept 8 hours.", "All sets clean, last squat set slowed.", "Progressing on plan.",
             "Squat 72.5 kg, keep the box.", "73.1", 8),
            ([("Squat", 4, 8, "72.5", 8, "Box squat to parallel"), ("Deadlift", 3, 5, "87.5", 8, ""), ("Lat pulldown", 3, 10, "42.5", 7, "")],
             "Knee fine, a little tired from exams.", "Squat depth consistent, no pain.", "Ready for 75 kg next time.",
             "Squat 75 kg for 4x8, keep box to parallel. Add lunges if the knee is quiet.", "72.9", 8),
        ]
        for session, (exercises, s, o, a, p, kg, rpe) in zip(sessions, history):
            log = SessionLog.objects.create(session=session, member=lea, coach=hadi, subjective=s, objective=o,
                                            assessment=a, plan=p, body_weight_kg=Decimal(kg), session_rpe=rpe)
            SessionLog.objects.filter(pk=log.pk).update(created_at=session.ends_at + timedelta(minutes=20),
                                                        updated_at=session.ends_at + timedelta(minutes=20))
            LoggedExercise.objects.bulk_create(
                LoggedExercise(log=log, order=i, exercise=name, kind="strength", sets=sets, reps=reps,
                               weight_kg=Decimal(w), rpe=r, note=note)
                for i, (name, sets, reps, w, r, note) in enumerate(exercises))
            PTSession.objects.filter(pk=session.pk).update(attendance=ClassBooking.Attendance.ATTENDED)
            # The same training event the app logs when a coach saves a session (coaching/views.py).
            log_training_event(
                TrainingEvent.EventType.SESSION_LOGGED, member=lea, branch=HAMRA, trainer=hadi,
                session_id=f"pt:{session.pk}", occurred_at=session.starts_at,
                payload={"exercises": [{"exercise": n, "kind": "strength", "sets": st, "reps": rp, "weightKg": w, "rpe": r}
                                       for n, st, rp, w, r, _ in exercises],
                         "sessionRpe": rpe, "bodyWeightKg": kg},
            )
        # Today's session: started 100 minutes ago, finished 40 minutes ago, not logged yet.
        starts = (now - timedelta(minutes=100)).replace(second=0, microsecond=0)
        today_pt = PTSession.objects.create(
            coach=hadi, member=lea, branch=HAMRA, starts_at=starts, ends_at=starts + timedelta(hours=1),
            note="Squat progression, right knee", booked_at=now - timedelta(days=2),
            attendance=ClassBooking.Attendance.ATTENDED)
        # SMART goals, set at the first session (Epley: 65 kg x 8 reps = 82.3 kg e1RM).
        squat = ClientGoal.objects.create(
            member=lea, set_by=hadi, kind=ClientGoal.Kind.STRENGTH, title="Squat 100 kg (estimated 1-rep max)",
            exercise="Squat", start_value=Decimal("82.3"), target_value=Decimal("100.0"),
            target_date=today + timedelta(days=60), note="Box squat to parallel until the knee is clear")
        weight = ClientGoal.objects.create(
            member=lea, set_by=hadi, kind=ClientGoal.Kind.BODY_WEIGHT, title="Reach 71 kg",
            start_value=Decimal("74.8"), target_value=Decimal("71.0"), target_date=today + timedelta(days=45))
        ClientGoal.objects.filter(pk__in=[squat.pk, weight.pk]).update(created_at=sessions[0].starts_at)
        # Lea's knee, shown in the log form's "Health notes (1)".
        HealthNote.objects.create(
            member=lea, kind=HealthNote.Kind.INJURY, body_area=HealthNote.BodyArea.KNEE,
            severity=HealthNote.Severity.MODERATE, title="Patellar tendinopathy, right knee",
            details="No jumping or deep squats until January. Box squats to parallel are fine.",
            since=today - timedelta(days=50))
        HealthDeclaration.objects.update_or_create(member=lea, defaults={"reviewed_at": now - timedelta(days=12)})
        credentials["named"]["ptToLog"] = {"id": today_pt.id, "member": lea.name}

    # SCRUM-79: pay rates for every coach since well before this pay period,
    # a raise for Hadi in this period, and one class the gym called off.
    def seed_pay_rates(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        s = self.staff_by
        karim, admin = s["kabboud"], s["mfakhoury"]
        since = month_start - timedelta(days=150)
        for username, cls, pt, by in [("hnasser", "18.00", "30.00", karim), ("raoun", "18.00", "30.00", karim),
                                      ("osaleh", "20.00", "32.00", karim), ("lmansour", "18.00", "30.00", s["jnassar"]),
                                      ("jkaram", "16.00", "28.00", admin)]:
            CoachPayRate.objects.create(coach=s[username], class_hourly=Decimal(cls), pt_hourly=Decimal(pt),
                                        effective_from=since, note="Starting rate", set_by=by)
        raise_day = max(month_start + timedelta(days=1), today - timedelta(days=7))
        if raise_day <= today:
            CoachPayRate.objects.create(coach=s["hnasser"], class_hourly=Decimal("20.00"), pt_hourly=Decimal("35.00"),
                                        effective_from=raise_day, note="Annual raise", set_by=karim)
            StaffNotification.objects.create(
                recipient=s["hnasser"], kind=StaffNotification.Kind.PAY_RATE_CHANGED, branch=HAMRA,
                title="Your pay rate was updated",
                message=(f"{karim.full_name} set your pay to $20.00/hour for classes and $35.00/hour for private training "
                         f"from {raise_day:%d %b %Y}. See My Pay for how it applies to your sessions."),
                created_at=timezone.make_aware(datetime.combine(raise_day - timedelta(days=1), time(16, 0))))
        off_day = month_start + timedelta(days=2)
        if off_day < today:
            spin = ClassType.objects.get(branch=HAMRA, name="Spinning")
            starts = rules.local_datetime(off_day, time(6, 0))
            GymClass.objects.create(
                branch=HAMRA, class_type=spin, name="Spinning", coach=s["hnasser"], room="Cycle Studio",
                capacity=spin.max_capacity, starts_at=starts, ends_at=starts + timedelta(minutes=45),
                status=GymClass.Status.CANCELLED, cancelled_at=starts - timedelta(hours=14), cancelled_by=karim,
                cancel_reason="Cycle Studio air-con repair")

    # SCRUM-89: Omar called in sick for tonight's HIIT; Rita (who has covered
    # his HIIT before) is free, Joe is off, so the finder has a clear pick.
    def seed_cover(self, credentials):
        now, today, s = timezone.now(), timezone.localdate(), self.staff_by
        omar, rita, joe, karim = s["osaleh"], s["raoun"], s["jkaram"], s["kabboud"]
        hiit = ClassType.objects.get(branch=HAMRA, name="HIIT")
        capacity = min(20, hiit.max_capacity)
        for weeks_back in (2, 5, 9):
            starts = rules.local_datetime(today - timedelta(weeks=weeks_back), time(20, 0))
            past = GymClass.objects.create(branch=HAMRA, class_type=hiit, name="HIIT", coach=rita, room="Studio B",
                                           capacity=capacity, starts_at=starts, ends_at=starts + timedelta(hours=1))
            CoverRequest.objects.create(
                gym_class=past, original_coach=omar, reason="Family emergency", reported_by=omar,
                status=CoverRequest.Status.COVERED, substitute=rita, resolved_by=karim,
                created_at=starts - timedelta(hours=3), resolved_at=starts - timedelta(hours=2))
        start, end = self.free_slot(now + timedelta(minutes=120), 60, [(omar, "Studio B"), (rita, "")])
        cover = GymClass.objects.create(branch=HAMRA, class_type=hiit, name="HIIT", coach=omar, room="Studio B",
                                        capacity=capacity, starts_at=start, ends_at=end)
        lea_id = credentials["named"]["memberLogin"]["id"]
        pool = list(Member.objects.filter(branch=HAMRA, status=Member.Status.ACTIVE).exclude(pk=lea_id).order_by("pk"))
        for m in self.persona_rng.sample(pool, 9):
            ClassBooking.objects.create(gym_class=cover, member=m,
                                        booked_at=now - timedelta(days=self.persona_rng.randint(1, 4)))
        # Joe is off then, so the finder shows a busy coach with a reason.
        TimeOff.objects.create(coach=joe, starts_at=start - timedelta(hours=1), ends_at=end + timedelta(hours=1),
                               reason="Dentist appointment")
        reason = "Sick - fever since this morning"
        CoverRequest.objects.create(gym_class=cover, original_coach=omar, reason=reason, reported_by=omar,
                                    created_at=now - timedelta(minutes=25))
        local = timezone.localtime(start)
        StaffNotification.objects.create(
            recipient=karim, kind=StaffNotification.Kind.COVER, branch=HAMRA,
            title=f"Urgent: Cover needed - HIIT today at {local:%H:%M}",
            message=f"{omar.full_name} can't teach it: {reason}. Studio B, 9 booked. Open the class to find a substitute.",
            created_at=now - timedelta(minutes=25))
        credentials["named"]["coverClass"] = {"id": cover.id, "name": "HIIT", "startTime": f"{local:%H:%M}",
                                              "original": omar.full_name, "substitute": rita.full_name}

    # --- member feedback (SCRUM-54, 94, 23, 24) ---------------------------

    # A month of branch surveys at every branch, complaints (one already
    # escalated from Jnah, one overdue at Hamra that the branch manager
    # escalates in the demo) and more coach ratings at Hamra and Jnah.
    def seed_feedback(self, credentials):
        rng = random.Random(54)
        now, today = timezone.now(), self.today
        named = credentials["named"]
        skip = {named["memberLogin"]["id"], named["deleteLogin"]["id"]}  # keep the demo logins clean
        pools = {}
        for b in Member.Branch.values:
            qs = Member.objects.filter(branch=b).exclude(pk__in=skip).order_by("pk")
            pools[b] = list(qs.filter(status=Member.Status.ACTIVE)) or list(qs)
        kabboud, jnassar, rhaddad = self.staff_by["kabboud"], self.staff_by["jnassar"], self.staff_by["rhaddad"]

        month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time(0, 30)))
        span = max(now - timedelta(hours=2) - month_start, timedelta(minutes=30))

        def this_month(frac):  # 0 = start of the month, 1 = two hours ago
            return month_start + span * frac

        def month_back(n, day):
            first = today.replace(day=1)
            for _ in range(n):
                first = (first - timedelta(days=1)).replace(day=1)
            return timezone.make_aware(datetime.combine(first.replace(day=day), time(rng.randint(9, 20), rng.randint(0, 59))))

        def survey(branch, row, when):
            nps, clean, equip, staff, classes, atmos, comment, anon = row
            s = BranchSurvey.objects.create(
                member=rng.choice(pools[branch]), branch=branch, nps=nps, cleanliness=clean, equipment=equip,
                staff=staff, classes=classes, atmosphere=atmos, comment=comment, anonymous=anon)
            BranchSurvey.objects.filter(pk=s.pk).update(created_at=when)

        # This month. Hamra: NPS +20, crowding & atmosphere 2.5 (weak). Jnah: NPS 0, cleanliness 2.7 (weak).
        # Achrafieh: +33. Zalka: +75 (top).
        this_months = {
            HAMRA: [
                (10, 5, 5, 5, 5, 3, "Coaches are great, the 6pm rush is the only downside.", False),
                (9, 5, 4, 5, 5, 3, "", False),
                (9, 4, 4, 5, 4, 2, "Love the classes. Evenings are packed though.", True),
                (8, 4, 4, 4, 4, 3, "", False),
                (7, 4, 3, 4, 4, 2, "Hard to get a squat rack after 6pm.", False),
                (10, 5, 5, 5, 5, 4, "Reception staff always remember my name.", False),
                (6, 3, 3, 4, 3, 2, "Too crowded in the evenings, waited 15 minutes for a bench.", False),
                (5, 4, 2, 3, None, 2, "Two treadmills have been out of order for weeks.", False),
                (9, 5, 4, 5, 5, 3, "", True),
                (3, 3, 2, 3, 3, 1, "Changing rooms are packed and the showers run cold.", False),
            ],
            JNAH: [
                (8, 2, 4, 4, 4, 4, "Friendly team but the floor near the weights is never mopped.", False),
                (6, 2, 3, 4, 3, 4, "Bathrooms need more frequent cleaning.", False),
                (9, 3, 4, 5, 4, 5, "Quiet and relaxed, perfect for morning sessions.", False),
                (4, 2, 3, 3, None, 4, "Dirty towels left on the benches all day.", True),
                (7, 3, 4, 4, 3, 4, "", False),
                (10, 4, 5, 5, 5, 5, "Lara's HIIT class is the best in Beirut.", False),
            ],
            ACHRAFIEH: [
                (9, 4, 4, 4, 4, 4, "Bright, modern space.", False),
                (7, 4, 3, 4, 4, 3, "", False),
                (8, 2, 3, 4, 4, 3, "Locker room smelled bad on Saturday.", False),
            ],
            ZALKA: [
                (10, 5, 5, 5, 4, 5, "New equipment, spotless.", False),
                (9, 5, 5, 4, 4, 5, "", False),
                (8, 5, 4, 4, 3, 4, "Wish there were more evening classes.", False),
                (9, 5, 5, 5, 4, 5, "", True),
            ],
        }
        for branch, rows in this_months.items():
            for i, row in enumerate(rows):
                survey(branch, row, this_month((i + 1) / (len(rows) + 1)))
        # Earlier months (the NPS trend, and Hamra dropping from +50 to +20).
        history = {
            HAMRA: [[10, 9, 9, 10, 8, 7, 9, 6], [9, 10, 8, 7, 9, 6], [10, 9, 9, 8, 6, 9, 7], [9, 9, 10, 7, 8, 5], [10, 9, 8, 9, 6]],
            JNAH: [[9, 8, 7, 10, 6], [8, 9, 7, 6], [9, 7, 8]],
        }
        for branch, months in history.items():
            for back, scores in enumerate(months, start=1):
                for i, nps in enumerate(scores):
                    survey(branch, (nps, rng.randint(3, 5), rng.randint(3, 5), rng.randint(4, 5), rng.choice([3, 4, 5, None]),
                                    rng.randint(3, 4), "", rng.random() < 0.2), month_back(back, 2 + i * 3))

        used = set()

        def complainer(branch):
            m = next(m for m in pools[branch] if m.pk not in used)
            used.add(m.pk)
            return m

        def complaint(branch, category, subject, description, created, *, status=Complaint.Status.OPEN,
                      answer=None, answered_after=None, staff=None, resolved_after=None, followup=None):
            member = complainer(branch)
            c = Complaint.objects.create(member=member, branch=branch, category=category, subject=subject,
                                         description=description, status=status,
                                         urgent=category == Complaint.Category.SAFETY)
            fields = {"created_at": created, "updated_at": created}
            if answer:
                when = created + answered_after
                m = ComplaintMessage.objects.create(complaint=c, author_staff=staff, body=answer)
                ComplaintMessage.objects.filter(pk=m.pk).update(created_at=when)
                fields.update(first_response_at=when, updated_at=when)
            if followup:
                body, after = followup
                m = ComplaintMessage.objects.create(complaint=c, author_member=member, body=body)
                ComplaintMessage.objects.filter(pk=m.pk).update(created_at=created + after)
                fields["updated_at"] = created + after
            if status == Complaint.Status.RESOLVED:
                fields.update(resolved_at=created + resolved_after, resolved_by=staff, updated_at=created + resolved_after)
            Complaint.objects.filter(pk=c.pk).update(**fields)
            c.refresh_from_db()
            return c

        C, S = Complaint.Category, Complaint.Status
        # Hamra: the one the branch manager escalates in the demo - open, never answered, overdue, member chasing.
        escalate = complaint(HAMRA, C.EQUIPMENT, "Treadmills 3 and 4 broken for three weeks",
                             "Both treadmills by the window have had an out-of-order sign since the start of the month. "
                             "In the evening there is a queue for the two that still work.",
                             now - timedelta(days=3, hours=4),
                             followup=("Still broken today, and nobody has replied.", timedelta(days=2)))
        complaint(HAMRA, C.CROWDING, "Can't get a squat rack after 6pm",
                  "Every evening all three racks are taken and people hold them for 40 minutes.",
                  this_month(0.35), status=S.IN_PROGRESS, staff=kabboud, answered_after=timedelta(hours=6),
                  answer="Thanks for flagging this. We're adding a fourth rack and a 30-minute limit at peak times.")
        complaint(HAMRA, C.CLEANLINESS, "Cold water in the women's showers",
                  "The showers in the women's changing room have been cold for a few days.",
                  now - timedelta(hours=20))
        complaint(HAMRA, C.SAFETY, "Loose cable on the lat pulldown machine",
                  "The cable is fraying near the pulley. Someone could get hurt.", this_month(0.15),
                  status=S.RESOLVED, staff=kabboud, answered_after=timedelta(hours=2), resolved_after=timedelta(days=1),
                  answer="Machine taken out of use right away; the cable was replaced this morning. Thank you.")
        complaint(HAMRA, C.BILLING, "Charged twice this month",
                  "My card was charged twice for the monthly renewal.", this_month(0.5),
                  status=S.RESOLVED, staff=kabboud, answered_after=timedelta(hours=5), resolved_after=timedelta(days=1),
                  answer="Sorry about that. The duplicate charge has been refunded to your card.")
        # Jnah: already escalated by Joe Nassar, so the GM's queue has something from a second branch.
        reason = "Repair quote is $2,400, over the branch budget. Needs head-office approval."
        ac = complaint(JNAH, C.EQUIPMENT, "Air conditioning broken in the main studio",
                       "Classes in the main studio are unbearable, it was over 30 degrees during HIIT.",
                       this_month(0.25), status=S.IN_PROGRESS, staff=jnassar, answered_after=timedelta(hours=3),
                       answer="We know, and we're getting a technician in. Classes will use fans until then.")
        escalated_at = min(ac.created_at + timedelta(days=1), now - timedelta(hours=3))
        Complaint.objects.filter(pk=ac.pk).update(escalated_at=escalated_at, escalated_by=jnassar, escalation_reason=reason)
        note = ComplaintMessage.objects.create(complaint=ac, author_staff=jnassar, internal=True,
                                               body=f"Escalated to the general manager: {reason}")
        ComplaintMessage.objects.filter(pk=note.pk).update(created_at=escalated_at)
        StaffNotification.objects.create(
            recipient=rhaddad, kind=StaffNotification.Kind.ESCALATED_COMPLAINT, branch=JNAH,
            title=f"Escalated from Jnah: {ac.subject}"[:120], message=f"{jnassar.full_name}: {reason}"[:300],
            created_at=escalated_at, read_at=escalated_at + timedelta(hours=2))  # already read; the demo's is the new one
        complaint(JNAH, C.CLEANLINESS, "Towels and bathrooms not cleaned",
                  "Used towels stay on the benches all day and the bathroom bins overflow.", this_month(0.6))
        complaint(ACHRAFIEH, C.CLEANLINESS, "Locker room smell",
                  "The men's locker room smelled bad all weekend.", this_month(0.4), status=S.RESOLVED,
                  staff=None, answered_after=timedelta(hours=8), resolved_after=timedelta(days=1),
                  answer="The drain was blocked; it has been cleared and deep-cleaned.")
        complaint(ZALKA, C.CLASSES, "More evening classes please",
                  "There is nothing after 7pm on weekdays.", this_month(0.7))

        # More coach ratings (SCRUM-24): Omar a weaker Hamra coach, Joe Karam good at Hamra but weaker at Jnah,
        # Lara the Jnah stand-out. One rating per attended booking, one per member per coach. Where a branch
        # has too few attended class bookings (Jnah is quiet), the rest are for private sessions.
        def rate(branch, username, stars, comments):
            coach = self.staff_by[username]
            bookings = ClassBooking.objects.filter(
                gym_class__branch=branch, gym_class__coach=coach,
                attendance=ClassBooking.Attendance.ATTENDED, feedback__isnull=True,
                gym_class__ends_at__lt=now, gym_class__ends_at__gte=now - timedelta(days=28),
            ).select_related("gym_class", "member").order_by("-gym_class__starts_at")
            seen, stars = set(), list(stars)
            for b in bookings:
                if not stars:
                    break
                if b.member_id in seen:
                    continue
                seen.add(b.member_id)
                n = stars.pop(0)
                f = CoachFeedback.objects.create(
                    member=b.member, coach=coach, class_booking=b, branch=branch,
                    session_name=b.gym_class.name, session_starts_at=b.gym_class.starts_at,
                    session_ends_at=b.gym_class.ends_at, rating=n, comment=rng.choice(comments[n]))
                CoachFeedback.objects.filter(pk=f.pk).update(created_at=b.gym_class.ends_at + timedelta(hours=2))
            others = [m for m in pools[branch] if m.pk not in seen]
            for i, n in enumerate(stars):
                starts = rules.local_datetime(today - timedelta(days=3 + 3 * i), time(9 + i % 3, 0))
                if PTSession.objects.filter(coach=coach, starts_at=starts).exists() or not others:
                    continue
                session = PTSession.objects.create(coach=coach, member=others.pop(0), branch=branch, starts_at=starts,
                                                   ends_at=starts + timedelta(hours=1), booked_at=starts - timedelta(days=2),
                                                   attendance=ClassBooking.Attendance.ATTENDED)
                f = CoachFeedback.objects.create(
                    member=session.member, coach=coach, pt_session=session, branch=branch, session_name="Private training",
                    session_starts_at=session.starts_at, session_ends_at=session.ends_at, rating=n,
                    comment=rng.choice(comments[n]))
                CoachFeedback.objects.filter(pk=f.pk).update(created_at=session.ends_at + timedelta(hours=2))

        rate(HAMRA, "osaleh", [4, 3, 4, 2, 3, 4, 3, 5], {
            5: ["Great energy."], 4: ["Tough workout, good music.", ""], 3: ["Fine, but he rarely corrects form.", ""],
            2: ["Started ten minutes late again."]})
        rate(HAMRA, "jkaram", [5, 5, 4, 5], {5: ["Zumba with Joe is the highlight of my week.", ""], 4: ["Fun class."]})
        rate(JNAH, "lmansour", [5, 5, 4, 5, 5, 4, 5], {
            5: ["Lara's HIIT is brilliant.", "Pushes you just the right amount.", ""], 4: ["Great class, studio was hot.", ""]})
        rate(JNAH, "jkaram", [3, 4, 2, 3], {
            4: ["Good technique tips."], 3: ["Boxing class felt disorganised.", ""], 2: ["Not enough gloves for everyone."]})

        return {"escalate": {"id": escalate.id, "subject": escalate.subject},
                "jnahEscalated": {"id": ac.id, "subject": ac.subject}}

    # --- money and stock (SCRUM-105, 21, 53) -----------------------------

    # SCRUM-105: Achrafieh's shop sales and running costs (smaller than Hamra's),
    # so it ranks second and on track; Jnah stays the branch running at a loss.
    def achrafieh_money(self):
        rng = random.Random(105)
        products = list(Product.objects.all())
        for _ in range(45):
            day = self.today - timedelta(days=rng.randint(0, 55))
            items = [(p, rng.randint(1, 2)) for p in rng.sample(products, rng.randint(1, 3))]
            total = sum((p.price * q for p, q in items), Decimal("0"))
            sold_at = at(day, rng.randint(8, 20), rng.randint(0, 59))
            if sold_at > self.now:
                sold_at = self.now - timedelta(minutes=rng.randint(10, 120))
            sale = Sale.objects.create(branch=ACHRAFIEH, payment_method=rng.choice(["Cash", "Card"]), total=total,
                                       sold_at=sold_at)
            SaleItem.objects.bulk_create(
                SaleItem(sale=sale, product=p, product_name=p.name, unit_price=p.price, quantity=q, line_total=p.price * q)
                for p, q in items)
        first = self.today.replace(day=1)
        last_month = (first - timedelta(days=1)).replace(day=1)
        for month in (last_month, first):
            for category, amount, day in [("Rent", 700, 1), ("Payroll", 900, 5), ("Utilities", 160, 8)]:
                incurred = month.replace(day=day)
                if incurred <= self.today:
                    Expense.objects.create(branch=ACHRAFIEH, category=category, amount=amount, incurred_on=incurred)

    # SCRUM-21 / 53: suppliers and reorder levels, uneven shelves per branch
    # (Hamra low on Vanilla whey, Creatine and towels), a delivered order and
    # one on its way at Hamra, and a Jnah order waiting for the General Manager.
    def stock_and_orders(self):
        call_command("seed_suppliers", verbosity=0, stdout=io.StringIO())
        for name, counts in STOCK.items():
            product = Product.objects.get(name=name)
            for branch, qty in zip(STOCK_BRANCHES, counts):
                BranchStock.objects.update_or_create(product=product, branch=branch, defaults={"quantity": qty})

        suppliers = {s.name: s for s in Supplier.objects.all()}
        products = {p.name: p for p in Product.objects.all()}
        karim, joe = self.staff_by["kabboud"], self.staff_by["jnassar"]

        def place(branch, supplier, by, status, days_ago, lines, **fields):
            created = self.now - timedelta(days=days_ago)
            total = sum((Decimal(cost) * qty for _, qty, cost in lines), Decimal("0"))
            order = PurchaseOrder.objects.create(branch=branch, supplier=suppliers[supplier], status=status,
                                                 total=total, requested_by=by, **fields)
            done = status == PurchaseOrder.Status.RECEIVED
            PurchaseOrderLine.objects.bulk_create(
                PurchaseOrderLine(order=order, product=products.get(item), description=item, quantity=qty,
                                  unit_cost=Decimal(cost), received_quantity=qty if done else 0)
                for item, qty, cost in lines)
            PurchaseOrder.objects.filter(pk=order.pk).update(created_at=created, updated_at=created)
            order.refresh_from_db()
            return order, created

        # Delivered 2 weeks ago (auto-approved: under $500).
        received, placed = place(HAMRA, "NutriPro Lebanon", karim, PurchaseOrder.Status.RECEIVED, 16,
                                 [("Protein Bar", 40, "1.60"), ("Water Bottle 500ml", 100, "0.35")], auto_approved=True)
        PurchaseOrder.objects.filter(pk=received.pk).update(approved_at=placed, sent_at=placed + timedelta(minutes=1),
                                                             closed_at=placed + timedelta(days=3))
        expense = Expense.objects.create(branch=HAMRA, category=Expense.Category.SUPPLIES, amount=received.total,
                                         incurred_on=timezone.localdate(placed + timedelta(days=3)),
                                         note=f"{received.number} from NutriPro Lebanon", recorded_by=karim)
        receipt = PurchaseReceipt.objects.create(
            order=received, received_by=karim, amount=received.total, expense=expense,
            items=[{"lineId": line.id, "description": line.description, "quantity": line.quantity}
                   for line in received.lines.all()])
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(received_at=placed + timedelta(days=3))

        # On its way (sent 2 days ago).
        shirts, placed = place(HAMRA, "ActiveWear Co.", karim, PurchaseOrder.Status.ORDERED, 2,
                               [("Fitness Factory T-Shirt", 10, "7.00")], auto_approved=True)
        PurchaseOrder.objects.filter(pk=shirts.pk).update(approved_at=placed, sent_at=placed + timedelta(minutes=1))

        # Jnah's cleaning supplies, $548 - over the limit, so it waits for the GM.
        pending, _ = place(JNAH, "CleanCare Supplies", joe, PurchaseOrder.Status.PENDING, 1,
                           [("Disinfectant spray 5 L", 40, "9.50"), ("Paper towel rolls (case of 12)", 12, "14.00")],
                           needed_by=self.today + timedelta(days=5), note="Deliver before 10 am")
        purchasing_rules.notify(
            purchasing_rules.approvers(exclude=joe), pending, f"Approve {pending.number}: ${pending.total:.2f} for Jnah",
            f"{joe.full_name} wants to order from CleanCare Supplies. Orders of $500.00 or more need your approval - "
            "open Supply Orders.")
        return {"pendingJnah": {"id": pending.id, "number": pending.number, "total": f"{pending.total:.2f}"},
                "hamraLow": ["Whey Protein 1kg (Vanilla)", "Creatine 300g", "Gym Towel"]}

    # --- campaigns (SCRUM-78, 63, 44) --------------------------------------

    # All by Nadine Khalil: a running renewal offer and a finished shop offer
    # at Hamra, awareness ads over budget, Zalka's opening offer with sign-ups,
    # a scheduled and a cancelled one at Jnah, an expired one at Achrafieh.
    # No campaign uses COMEBACK15: the demo creates that one live.
    def seed_campaigns(self):
        t, now, rng = self.today, timezone.now(), random.Random(63)
        nadine = self.staff_by["nkhalil"]
        use = CampaignRedemption.Use

        def campaign(branch, name, strategy, budget, spent, start, end, **extra):
            c, _ = MarketingCampaign.objects.update_or_create(
                branch=branch, name=name,
                defaults={"strategy": strategy, "budget": Decimal(budget), "amount_spent": Decimal(spent),
                          "start_date": start, "end_date": end, "created_by": nadine, **extra})
            return c

        def offer(code, kind, value, applies, **extra):
            return {"offer_code": code, "discount_type": kind, "discount_value": Decimal(value), "applies_to": applies,
                    "notify_audience": True, "segment_statuses": [Member.Status.ACTIVE], **extra}

        def send(c, member, when):
            CampaignRecipient.objects.get_or_create(
                campaign=c, member=member, defaults={"sent_at": max(when, c.launched_at), "by_email": rng.random() < 0.7})

        # Same bookkeeping as billing.Payment.record with an offer: the payment
        # carries the discounted amount and the code in its note.
        def redeem_payment(c, payment, how):
            if CampaignRedemption.objects.filter(campaign=c, member=payment.member, voided_at__isnull=True).exists() \
                    or CampaignRedemption.objects.filter(payment=payment).exists():
                return False
            before = Decimal(payment.amount)
            off = c.discount_on(before)
            Payment.objects.filter(pk=payment.pk).update(
                amount=before - off, note=f"{payment.note} · offer {c.offer_code} (-${off:.2f})")
            CampaignRedemption.objects.create(
                campaign=c, member=payment.member, use=how, payment=payment, amount_before=before, discount=off,
                amount_paid=before - off, redeemed_at=payment.paid_at, redeemed_by=payment.recorded_by or self.desk)
            return True

        # 1. Hamra, running: 20% off renewals for members renewing within 14 days.
        start = t - timedelta(days=20)
        renew = campaign(
            HAMRA, "Renew & Save",
            "Keep members who are about to renew: 20% off the renewal for anyone whose membership ends in the next "
            "two weeks. Cheaper than winning them back later.",
            "500.00", "310.00", start, t + timedelta(days=10),
            **offer("RENEW20", MarketingCampaign.DiscountType.PERCENT, "20", MarketingCampaign.AppliesTo.MEMBERSHIP,
                    segment_renewal_within_days=14, launched_at=at(start, 7),
                    offer_message="Thanks for training with us - renew before your membership ends and save."))
        payers = {}
        for p in Payment.objects.filter(member__branch=HAMRA, note="Renewal", duration="1 Month",
                                        paid_at__gte=renew.launched_at).select_related("member").order_by("paid_at"):
            payers.setdefault(p.member_id, p)
        payers = list(payers.values())
        for p in payers:  # each was sent it a few days before their renewal
            send(renew, p.member, at(timezone.localtime(p.paid_at).date() - timedelta(days=rng.randint(2, 13)), 7))
        for m in offers.audience(renew):  # due now: already sent, so the live sender adds nobody mid-recording
            send(renew, m, now - timedelta(days=rng.randint(1, 3)))
        for p in rng.sample(payers, min(len(payers), max(8, len(payers) * 2 // 5))):
            redeem_payment(renew, p, use.MEMBERSHIP)

        # 2. Hamra, expired: 15% off at the shop for a week.
        start = t - timedelta(days=40)
        fuel = campaign(
            HAMRA, "Protein Week",
            "Push supplement and drink sales at the Hamra shop for one week: 15% off for active members, announced in the app.",
            "150.00", "150.00", start, start + timedelta(days=6),
            **offer("FUEL15", MarketingCampaign.DiscountType.PERCENT, "15", MarketingCampaign.AppliesTo.SHOP,
                    launched_at=at(start, 7)))
        pool = sorted(Member.objects.filter(branch=HAMRA, status=Member.Status.ACTIVE, join_date__lt=start), key=lambda m: m.pk)
        pool = rng.sample(pool, min(70, len(pool)))
        for m in pool:
            send(fuel, m, fuel.launched_at)
        products = list(Product.objects.filter(category__in=[Product.Category.SUPPLEMENTS, Product.Category.DRINKS]))
        for m in rng.sample(pool, min(13, len(pool))):
            lines = [(p, rng.randint(1, 2)) for p in rng.sample(products, rng.randint(1, 2))]
            subtotal = sum((p.price * q for p, q in lines), Decimal("0"))
            off = fuel.discount_on(subtotal)
            sold_at = at(start + timedelta(days=rng.randint(0, 6)), rng.randint(8, 18), rng.randint(0, 59))
            sale = Sale.objects.create(branch=HAMRA, member=m, payment_method=rng.choice(["Cash", "Card"]),
                                       total=subtotal - off, discount=off, offer_code=fuel.offer_code,
                                       sold_by=self.desk, sold_at=sold_at)
            SaleItem.objects.bulk_create(
                SaleItem(sale=sale, product=p, product_name=p.name, unit_price=p.price, quantity=q, line_total=p.price * q)
                for p, q in lines)
            CampaignRedemption.objects.create(campaign=fuel, member=m, use=use.SHOP, sale=sale, amount_before=subtotal,
                                              discount=off, amount_paid=subtotal - off, redeemed_at=sold_at,
                                              redeemed_by=self.desk)

        # 3. Hamra, running, no offer, over budget (red on both screens).
        campaign(
            HAMRA, "Instagram Brand Ads",
            "Sponsored reels of our classes and coaches to build the Fitness Zone name around Hamra and AUB. "
            "Awareness only - no offer code.",
            "300.00", "345.00", t - timedelta(days=30), t + timedelta(days=30))

        # 4. Zalka, running since opening: $5 off joining (sign-ups) or a renewal.
        start = t - timedelta(days=49)
        opening = campaign(
            ZALKA, "Zalka Grand Opening",
            "Fill the new branch: $5 off joining or renewing during the first two months, on flyers around Zalka and in the app.",
            "1200.00", "900.00", start, t + timedelta(days=11),
            **offer("OPENZALKA", MarketingCampaign.DiscountType.FIXED, "5.00", MarketingCampaign.AppliesTo.MEMBERSHIP,
                    segment_joined_within_days=60, launched_at=at(start, 7),
                    offer_message="Welcome to Fitness Zone Zalka!"))
        signed = set()
        for p in Payment.objects.filter(member__branch=ZALKA, note__startswith="First payment",
                                        paid_at__gte=opening.launched_at).select_related("member").order_by("paid_at"):
            if redeem_payment(opening, p, use.SIGNUP):
                signed.add(p.member_id)
        for m in offers.audience(opening).exclude(id__in=signed):
            send(opening, m, at(m.join_date, 7))
        for p in (Payment.objects.filter(member__branch=ZALKA, note="Renewal", paid_at__gte=opening.launched_at)
                  .exclude(member_id__in=signed).select_related("member").order_by("paid_at")):
            redeem_payment(opening, p, use.MEMBERSHIP)

        # 5. Jnah, scheduled: not sent yet, capped at 30 uses.
        campaign(
            JNAH, "Jnah Student Week",
            "Back-to-uni push for students near Jnah: 20% off renewals on the Basic plan, first 30 uses.",
            "250.00", "0.00", t + timedelta(days=5), t + timedelta(days=12),
            **offer("STUDENT20", MarketingCampaign.DiscountType.PERCENT, "20", MarketingCampaign.AppliesTo.MEMBERSHIP,
                    segment_plans=["Basic"], max_redemptions=30))
        # 6. Jnah, cancelled; 7. Achrafieh, finished. Neither has an offer.
        campaign(
            JNAH, "Corporate Flyers",
            "Flyers in office buildings around Jnah for company memberships. Stopped early: hardly any calls came in.",
            "200.00", "80.00", t - timedelta(days=20), t + timedelta(days=10), is_active=False)
        campaign(
            ACHRAFIEH, "Achrafieh Open Day",
            "A free open day with trial classes and a DJ, to show the neighbourhood the refurbished floor.",
            "400.00", "380.00", t - timedelta(days=60), t - timedelta(days=59))

        return {c.offer_code or c.name: {"id": c.id, "name": c.name, "branch": c.branch}
                for c in MarketingCampaign.objects.all()}

    # --- shop sales by Hamra members (SCRUM-113 shop uptake per segment) ---

    # Members buy at the desk in the last 30 days the way their habit suggests:
    # the morning PT clients buy supplements, the class-goers drinks, the
    # late-evening crowd merchandise and supplements.
    def member_shop_sales(self, named):
        rng = random.Random(113)
        skip = {named["memberLogin"]["id"], named["deleteLogin"]["id"]}
        by_category = {}
        for p in Product.objects.filter(is_active=True):
            by_category.setdefault(p.category, []).append(p)
        count = 0
        for member, persona in sorted(self.persona.items(), key=lambda mp: mp[0].pk):
            if member.status != Member.Status.ACTIVE or member.pk in skip:
                continue
            chance, taste = SHOPPING[persona]
            if rng.random() >= chance:
                continue
            categories, weights = zip(*taste.items())
            for _ in range(rng.randint(1, 3)):
                category = rng.choices(categories, weights)[0]
                lines = [(p, rng.randint(1, 2)) for p in rng.sample(by_category[category], min(2, rng.randint(1, 2)))]
                total = sum((p.price * q for p, q in lines), Decimal("0"))
                sold_at = at(self.today - timedelta(days=rng.randint(0, 29)), rng.choice(PERSONAS[persona][1]),
                             rng.randint(0, 59))
                if sold_at > self.now:
                    sold_at = self.now - timedelta(minutes=rng.randint(10, 120))
                sale = Sale.objects.create(branch=HAMRA, member=member, payment_method=rng.choice(["Cash", "Card"]),
                                           total=total, sold_by=self.desk, sold_at=sold_at)
                SaleItem.objects.bulk_create(
                    SaleItem(sale=sale, product=p, product_name=p.name, unit_price=p.price, quantity=q,
                             line_total=p.price * q)
                    for p, q in lines)
                count += 1
        self.stdout.write(f"Shop: {count} sales by Hamra members in the last 30 days.")

    # SCRUM-68: one past call with a follow-up date, so the member's
    # "Retention calls" history shows it.
    def retention_follow_up(self):
        call = RetentionCall.objects.filter(branch=HAMRA, outcome="reached").order_by("-called_at").first()
        if call:
            RetentionCall.objects.filter(pk=call.pk).update(follow_up_on=self.today + timedelta(days=2))

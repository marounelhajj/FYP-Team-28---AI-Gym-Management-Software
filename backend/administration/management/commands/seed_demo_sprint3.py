import json
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.utils import timezone

from administration.models import StaffAccount
from billing.models import Payment
from checkins.models import CheckIn
from classes.models import ClassBooking, ClassType, GymClass, PTSession, TimeOff
from classes.rules import local_datetime
from feedback.models import CoachFeedback
from headcount.models import BranchCapacity
from members.models import Member
from notifications.models import NotificationSettings
from progress.models import BodyMetric, WorkoutEntry

from .seed_demo import Command as SprintTwoSeed

# The Sprint 3 demo database (docs/sprint3-demo-script.md):
#
#   GYM_DB_PATH=demo/.data/demo.sqlite3 python manage.py seed_demo_sprint3 --credentials demo/.data/credentials.json
#
# Everything the Sprint 2 seed makes (staff with enrolled authenticators,
# members, payments, four weeks of check-ins, ...), plus the class calendar
# (seed_classes: coaches, PT hours, a four-week timetable), bookings across
# this week's classes, one class in progress right now for the attendance
# story, the member's coach relationship and training log, a coach time-off
# block, and branch capacities. The v2 recording (all 17 Sprint 3 stories) adds a
# full class with a booked member who will cancel and a first-in-line waitlister
# (SCRUM-80), a class starting within the hour and a membership renewing soon
# (SCRUM-61), attended classes with coach ratings (SCRUM-40, 37), and three
# weeks of past classes at both branches, Hamra busy and Jnah quiet (SCRUM-22).
# Same guards as seed_demo: a separate
# database only, and fresh passwords written only to --credentials.


class Command(SprintTwoSeed):
    help = "Seeds the Sprint 3 demo database (Sprint 2 data plus classes, bookings, training logs and capacities)."

    def handle(self, *args, **options):
        super().handle(*args, **options)
        rng = random.Random(33)
        now = timezone.now()
        today = timezone.localdate()
        call_command("seed_classes", verbosity=0)

        path = Path(options["credentials"])
        credentials = json.loads(path.read_text())
        named = credentials["named"]
        lea = Member.objects.get(pk=named["memberLogin"]["id"])
        coach = StaffAccount.objects.get(username="hnasser")
        active = list(Member.objects.filter(status=Member.Status.ACTIVE, branch="Hamra").exclude(pk=lea.pk))

        # Bookings across the coming week's classes: Hamra 30-70% full, Jnah (the
        # quieter branch) 10-30%, each from its own branch's members.
        pools = {b: list(Member.objects.filter(status=Member.Status.ACTIVE, branch=b).exclude(pk=lea.pk))
                 for b in ("Hamra", "Jnah")}
        for gym_class in GymClass.objects.filter(starts_at__gte=now, starts_at__lt=now + timedelta(days=7)):
            pool = pools.get(gym_class.branch) or active
            low, high = (0.3, 0.7) if gym_class.branch == "Hamra" else (0.1, 0.3)
            for member in rng.sample(pool, min(len(pool), max(1, int(gym_class.capacity * rng.uniform(low, high))))):
                ClassBooking.objects.get_or_create(gym_class=gym_class, member=member, status=ClassBooking.Status.BOOKED)

        # A Spinning class that started a quarter of an hour ago, for SCRUM-36.
        spin = ClassType.objects.filter(branch="Hamra", name="Spinning").first()
        live = GymClass.objects.create(
            branch="Hamra", class_type=spin, name="Spinning", coach=coach, room="Cycle Studio", capacity=spin.max_capacity,
            starts_at=now - timedelta(minutes=15), ends_at=now + timedelta(minutes=150),
        )
        roster = rng.sample(active, 6)
        for member in roster:
            ClassBooking.objects.create(gym_class=live, member=member, booked_at=now - timedelta(days=1))
        walk_in = next(m for m in active if m not in roster)

        # Lea trains privately with Hadi (so he is her assigned coach, SCRUM-60).
        last_session = now - timedelta(days=5)
        PTSession.objects.create(
            coach=coach, member=lea, branch="Hamra", starts_at=last_session, ends_at=last_session + timedelta(hours=1),
            note="Squat form and conditioning", attendance=ClassBooking.Attendance.ATTENDED,
        )
        # A block of time off next week (SCRUM-100).
        off = timezone.localtime(now).replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=8)
        TimeOff.objects.create(coach=coach, starts_at=off, ends_at=off + timedelta(hours=3), reason="Physio appointment")

        # Three weeks of Lea's own training log, weight trending down.
        plan = [("Squat", 4, 8, "70"), ("Bench press", 4, 8, "42.5"), ("Deadlift", 3, 5, "85"), ("Lat pulldown", 3, 10, "40")]
        for back in range(21, 0, -2):
            day = today - timedelta(days=back)
            if back % 4 == 1:
                WorkoutEntry.objects.create(member=lea, performed_on=day, exercise="Running", kind="cardio",
                                            duration_minutes=rng.choice([25, 30, 35]), distance_km=Decimal(rng.choice(["4.2", "5.0", "5.6"])))
            else:
                name, sets, reps, weight = plan[back % len(plan)]
                WorkoutEntry.objects.create(member=lea, performed_on=day, exercise=name, kind="strength",
                                            sets=sets, reps=reps, weight_kg=Decimal(weight) + (21 - back) // 6 * Decimal("2.5"))
        for i, weight in enumerate(["74.8", "74.3", "73.9", "73.6", "73.0"]):
            BodyMetric.objects.create(member=lea, measured_on=today - timedelta(days=28 - i * 7), weight_kg=Decimal(weight),
                                      body_fat_percent=Decimal(str(round(24.5 - i * 0.4, 1))), waist_cm=Decimal(str(80 - i)))

        coaches = {a.username: a for a in StaffAccount.objects.filter(username__in=["hnasser", "raoun", "osaleh", "lmansour", "jkaram"])}
        karim = Member.objects.get(pk=named["deleteLogin"]["id"])
        others = [m for m in pools["Hamra"] if m.pk != karim.pk]
        self.seed_waitlist(rng, today, coaches, karim, others, credentials)
        self.seed_reminders(rng, now, today, coaches, lea, others)
        self.seed_past_classes(rng, now, today, pools, lea)

        # Capacities: Hamra gets its real value in the demo (the branch manager
        # sets it); a starting value here keeps member busy levels working.
        BranchCapacity.objects.update_or_create(branch="Hamra", defaults={"max_capacity": 60})
        BranchCapacity.objects.update_or_create(branch="Jnah", defaults={"max_capacity": 40})

        credentials["named"]["liveClass"] = {"id": live.id, "name": live.name}
        credentials["named"]["walkIn"] = {"id": walk_in.id, "name": walk_in.name}
        # Members the front desk can check in (nobody who is already inside right now).
        inside = set(CheckIn.objects.filter(checked_out_at__isnull=True).values_list("member_id", flat=True))
        credentials["named"]["checkInPool"] = [
            {"id": m.id, "name": m.name} for m in active if m not in roster and m != walk_in and m.pk not in inside
        ][:8]
        path.write_text(json.dumps(credentials, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"Sprint 3 data ready: {GymClass.objects.count()} classes, {ClassBooking.objects.count()} bookings, "
            f"{WorkoutEntry.objects.count()} workouts."
        ))

    # SCRUM-80: a small Boxing class two days from now, full. Karim holds a
    # spot and cancels it in the demo; Lea joins the (empty) waitlist first, so
    # she is the one who gets the spot and the notification.
    def seed_waitlist(self, rng, today, coaches, karim, others, credentials):
        boxing = ClassType.objects.get(branch="Hamra", name="Boxing")
        starts = local_datetime(today + timedelta(days=2), time(19, 30))
        full = GymClass.objects.create(
            branch="Hamra", class_type=boxing, name="Boxing Bootcamp", coach=coaches["osaleh"], room="Boxing Ring",
            capacity=6, starts_at=starts, ends_at=starts + timedelta(minutes=60),
        )
        for member in [karim, *rng.sample(others, 5)]:
            ClassBooking.objects.create(gym_class=full, member=member, booked_at=timezone.now() - timedelta(days=3))
        # Karim's membership runs well past the class.
        Member.objects.filter(pk=karim.pk).update(subscription_expires_at=today + timedelta(days=20))
        credentials["named"]["fullClass"] = {"id": full.id, "name": full.name}

    # SCRUM-61: a Yoga class starting in 50 minutes that Lea booked two days ago,
    # and her membership renewing in 12 days (she asked for the 14-day heads-up).
    def seed_reminders(self, rng, now, today, coaches, lea, others):
        yoga = ClassType.objects.get(branch="Hamra", name="Yoga")
        soon = GymClass.objects.create(
            branch="Hamra", class_type=yoga, name="Yoga", coach=coaches["raoun"], room="Rooftop Terrace", capacity=12,
            starts_at=now + timedelta(minutes=50), ends_at=now + timedelta(minutes=110),
        )
        ClassBooking.objects.create(gym_class=soon, member=lea, booked_at=now - timedelta(days=2))
        for member in rng.sample(others, 4):
            ClassBooking.objects.create(gym_class=soon, member=member, booked_at=now - timedelta(days=1))
        last = Payment.objects.filter(member=lea).order_by("-paid_at").first()
        Payment.objects.filter(pk=last.pk).update(
            paid_at=timezone.make_aware(datetime.combine(today - timedelta(days=18), time(10, 0))),
            expires_at=today + timedelta(days=12),
        )
        Member.objects.filter(pk=lea.pk).update(subscription_expires_at=today + timedelta(days=12))
        NotificationSettings.objects.update_or_create(member=lea, defaults={"renewal_days_before": 14})

    # SCRUM-22 / 40 / 37: the timetable's first week repeated for the three weeks
    # before it, plus this week's classes that are already over, with bookings and
    # attendance. Hamra fills up and mostly shows up; Jnah is quiet. Members rate
    # the classes they attended.
    def seed_past_classes(self, rng, now, today, pools, lea):
        monday = today - timedelta(days=today.weekday())
        template = list(
            GymClass.objects.filter(
                starts_at__gte=local_datetime(monday, time(0, 0)),
                starts_at__lt=local_datetime(monday + timedelta(days=7), time(0, 0)),
            ).exclude(room__in=["Boxing Ring", "Rooftop Terrace"])
        )
        past = [c for c in template if c.ends_at <= now]
        for weeks_back in (1, 2, 3):
            for c in template:
                local = timezone.localtime(c.starts_at)
                starts = local_datetime(local.date() - timedelta(days=7 * weeks_back), local.time())
                past.append(GymClass.objects.create(
                    branch=c.branch, class_type=c.class_type, name=c.name, coach=c.coach, room=c.room, capacity=c.capacity,
                    starts_at=starts, ends_at=starts + (c.ends_at - c.starts_at),
                ))
        # One class the gym called off, so the cancelled counts have something to show.
        called_off = next(c for c in reversed(past) if c.branch == "Jnah" and c.ends_at < now - timedelta(days=8))
        GymClass.objects.filter(pk=called_off.pk).update(
            status=GymClass.Status.CANCELLED, cancelled_at=called_off.starts_at - timedelta(days=1), cancel_reason="Coach unwell",
        )
        attended_by_coach = {}
        for c in past:
            if c.pk == called_off.pk:
                continue
            hamra = c.branch == "Hamra"
            pool = pools[c.branch]
            fill = rng.uniform(0.7, 1.0) if hamra else rng.uniform(0.12, 0.35)
            show = 0.88 if hamra else 0.72
            for member in rng.sample(pool, min(len(pool), c.capacity, max(1, round(c.capacity * fill)))):
                came = rng.random() < show
                booking = ClassBooking.objects.create(
                    gym_class=c, member=member, booked_at=c.starts_at - timedelta(days=rng.randint(1, 5)),
                    attendance=ClassBooking.Attendance.ATTENDED if came else ClassBooking.Attendance.NO_SHOW,
                )
                if came and hamra and c.coach.username in ("hnasser", "raoun") and c.ends_at > now - timedelta(days=21):
                    attended_by_coach.setdefault(c.coach.username, []).append(booking)

        comments = {
            5: ["Best spin class in town, great energy.", "Pushes you without making you feel bad.",
                "Loved the playlist and the pacing.", ""],
            4: ["Solid session, a bit crowded at the back.", "Good class, would like longer stretching.", ""],
            3: ["Fine, but the room was hot.", "Okay class. Started a few minutes late."],
            2: ["Too many people for the space."],
            1: ["Class was cancelled on me last minute."],
        }
        spread = {"hnasser": [5, 5, 5, 4, 5, 4, 3, 5, 4, 2], "raoun": [5, 4, 5, 4, 4, 3, 5, 4]}
        for username, bookings in attended_by_coach.items():
            seen = set()
            ratings = spread[username]
            for booking in bookings:
                if booking.member_id in seen or not ratings:
                    continue
                seen.add(booking.member_id)
                stars = ratings.pop(0)
                feedback = CoachFeedback.objects.create(
                    member=booking.member, coach=booking.gym_class.coach, class_booking=booking, branch="Hamra",
                    session_name=booking.gym_class.name, session_starts_at=booking.gym_class.starts_at,
                    session_ends_at=booking.gym_class.ends_at, rating=stars, comment=rng.choice(comments[stars]),
                )
                CoachFeedback.objects.filter(pk=feedback.pk).update(created_at=booking.gym_class.ends_at + timedelta(hours=3))

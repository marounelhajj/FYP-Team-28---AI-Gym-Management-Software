import json
import random
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.utils import timezone

from administration.models import StaffAccount
from classes.models import ClassBooking, ClassType, GymClass, PTSession, TimeOff
from headcount.models import BranchCapacity
from members.models import Member
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
# block, and branch capacities. Same guards as seed_demo: a separate
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

        # Bookings across this week's classes: 30-70% full, so spots-left vary.
        for gym_class in GymClass.objects.filter(starts_at__gte=now, starts_at__lt=now + timedelta(days=7)):
            pool = [m for m in active if m.branch == gym_class.branch] or active
            for member in rng.sample(pool, min(len(pool), int(gym_class.capacity * rng.uniform(0.3, 0.7)))):
                ClassBooking.objects.get_or_create(gym_class=gym_class, member=member, status=ClassBooking.Status.BOOKED)

        # A Spinning class that started a quarter of an hour ago, for SCRUM-36.
        spin = ClassType.objects.filter(branch="Hamra", name="Spinning").first()
        live = GymClass.objects.create(
            branch="Hamra", class_type=spin, name="Spinning", coach=coach, room="Cycle Studio", capacity=spin.max_capacity,
            starts_at=now - timedelta(minutes=15), ends_at=now + timedelta(minutes=30),
        )
        roster = [lea, *rng.sample(active, 5)]
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

        # Capacities: Hamra gets its real value in the demo (the branch manager
        # sets it); a starting value here keeps member busy levels working.
        BranchCapacity.objects.update_or_create(branch="Hamra", defaults={"max_capacity": 60})
        BranchCapacity.objects.update_or_create(branch="Jnah", defaults={"max_capacity": 40})

        credentials["named"]["liveClass"] = {"id": live.id, "name": live.name}
        credentials["named"]["walkIn"] = {"id": walk_in.id, "name": walk_in.name}
        credentials["named"]["checkInPool"] = [
            {"id": m.id, "name": m.name} for m in active if m not in roster and m != walk_in
        ][:8]
        path.write_text(json.dumps(credentials, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"Sprint 3 data ready: {GymClass.objects.count()} classes, {ClassBooking.objects.count()} bookings, "
            f"{WorkoutEntry.objects.count()} workouts."
        ))

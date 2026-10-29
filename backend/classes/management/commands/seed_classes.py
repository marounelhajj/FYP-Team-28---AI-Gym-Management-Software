import uuid
from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from administration.management.commands.seed_staff import DEMO_PASSWORD, ROLES, STAFF_ACCOUNTS
from administration.models import Role, StaffAccount
from classes.models import ClassType, GymClass, PTAvailability
from classes.rules import local_datetime, week_start

# Demo class calendar for local development: the coaches from seed_staff (added
# to an existing database if they're missing), a class type per branch and
# class (its maximum capacity is the capacity below), and a weekly timetable
# from the start of this week for WEEKS weeks - so the past days of this week
# show up as view-only. Some slots run at the same time with different
# coaches, and Joe Karam teaches at two branches on Friday, back to back.

WEEKS = 4

# weekday (0 = Monday): (start, minutes, class, coach username, studio, capacity)
TIMETABLE = {
    "Hamra": {
        0: [("07:00", 45, "Spinning", "hnasser", "Cycle Studio", 16), ("07:00", 60, "Yoga", "raoun", "Studio A", 18),
            ("18:00", 60, "HIIT", "osaleh", "Studio B", 20), ("19:30", 60, "Pilates", "raoun", "Studio A", 15)],
        1: [("08:00", 60, "Body Pump", "osaleh", "Studio B", 20), ("12:30", 45, "Core & Abs", "hnasser", "Studio A", 15),
            ("18:00", 60, "Boxing", "osaleh", "Studio B", 14), ("18:00", 45, "Spinning", "hnasser", "Cycle Studio", 16)],
        2: [("07:00", 60, "Yoga", "raoun", "Studio A", 18), ("18:00", 60, "CrossFit", "osaleh", "Studio B", 16),
            ("19:00", 60, "Zumba", "raoun", "Studio A", 25)],
        3: [("07:00", 45, "Spinning", "hnasser", "Cycle Studio", 16), ("18:00", 60, "HIIT", "osaleh", "Studio B", 20),
            ("18:00", 60, "Yoga Flow", "raoun", "Studio A", 18), ("19:30", 45, "Spinning", "hnasser", "Cycle Studio", 16)],
        4: [("08:00", 60, "Pilates", "raoun", "Studio A", 15), ("17:30", 60, "Boxing", "osaleh", "Studio B", 14),
            ("19:00", 60, "Zumba", "jkaram", "Studio A", 25)],
        5: [("10:00", 60, "Body Pump", "osaleh", "Studio B", 20), ("10:00", 60, "Yoga", "raoun", "Studio A", 18),
            ("11:30", 45, "Spinning", "hnasser", "Cycle Studio", 16)],
        6: [("10:00", 75, "Stretch & Mobility", "raoun", "Studio A", 20)],
    },
    "Jnah": {
        0: [("18:00", 60, "HIIT", "lmansour", "Main Studio", 20)],
        2: [("18:00", 60, "Zumba", "lmansour", "Main Studio", 25)],
        4: [("18:00", 60, "Boxing", "jkaram", "Main Studio", 14)],
    },
}


# Weekly private training hours: (coach, branch, weekday, start, end, minutes per session).
PT_HOURS = [
    ("hnasser", "Hamra", 0, "09:00", "12:00", 60),
    ("hnasser", "Hamra", 2, "09:00", "12:00", 60),
    ("raoun", "Hamra", 1, "14:00", "17:00", 60),
    ("raoun", "Hamra", 3, "14:00", "17:00", 60),
    ("osaleh", "Hamra", 4, "09:00", "12:00", 45),
    ("osaleh", "Hamra", 5, "13:00", "16:00", 60),
    ("jkaram", "Hamra", 5, "17:00", "19:00", 60),
    ("lmansour", "Jnah", 1, "09:00", "12:00", 60),
]


class Command(BaseCommand):
    help = "Seeds coach accounts, their private training hours and a demo weekly class calendar."

    def handle(self, *args, **options):
        coaches = self.ensure_coaches()

        if not PTAvailability.objects.exists():
            for username, branch, weekday, start, end, minutes in PT_HOURS:
                PTAvailability.objects.create(
                    coach=coaches[username], branch=branch, weekday=weekday, start_time=time.fromisoformat(start),
                    end_time=time.fromisoformat(end), session_minutes=minutes,
                )
            self.stdout.write(f"Added {len(PT_HOURS)} blocks of private training hours.")

        if GymClass.objects.exists():
            self.stdout.write(self.style.WARNING("Classes already exist - skipping the demo calendar."))
            return

        monday = week_start(timezone.localdate())
        created = 0
        for branch, days in TIMETABLE.items():
            for weekday, slots in days.items():
                for start, minutes, name, username, room, capacity in slots:
                    class_type, _ = ClassType.objects.get_or_create(
                        branch=branch, name=name,
                        defaults={"max_capacity": capacity, "default_duration_minutes": minutes},
                    )
                    if capacity > class_type.max_capacity:
                        class_type.max_capacity = capacity
                        class_type.save(update_fields=["max_capacity"])
                    series = uuid.uuid4()
                    clock = time.fromisoformat(start)
                    for week in range(WEEKS):
                        starts_at = local_datetime(monday + timedelta(days=weekday, weeks=week), clock)
                        GymClass.objects.create(
                            branch=branch, class_type=class_type, name=name, coach=coaches[username], room=room,
                            capacity=capacity, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=minutes),
                            series=series,
                        )
                        created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} classes over {WEEKS} weeks from {monday}."))

    def ensure_coaches(self):
        role_data = next(r for r in ROLES if r["name"] == "Coach")
        role, _ = Role.objects.get_or_create(
            name="Coach", defaults={"description": role_data["description"], "permissions": role_data["permissions"]},
        )
        coaches = {}
        for data in STAFF_ACCOUNTS:
            if data["job_title"] != StaffAccount.JobTitle.COACH:
                continue
            account = StaffAccount.objects.filter(username=data["username"]).first()
            if account is None:
                account = StaffAccount(
                    full_name=data["full_name"], email=data["email"], username=data["username"],
                    job_title=StaffAccount.JobTitle.COACH, role=role, branch=data.get("branch"),
                )
                account.set_password(DEMO_PASSWORD)
                account.save()
                self.stdout.write(f"Added coach {account.full_name} ({account.branch or 'any branch'}).")
            coaches[account.username] = account
        return coaches

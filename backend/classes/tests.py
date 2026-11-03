from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from checkins.models import CheckIn, CheckInFlag
from members import qr
from members.models import Member, Waiver
from training.models import TrainingEvent

from . import rules
from .models import ClassBooking, ClassType, GymClass, PTAvailability, PTSession, TimeOff
from .rules import local_datetime

PASSWORD = "ChangeMe123!"


def _staff(username, permissions, branch=None, job_title=StaffAccount.JobTitle.BRANCH_MANAGER, active=True):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(full_name=username.title(), email=f"{username}@gym.com", username=username,
                           job_title=job_title, role=role, branch=branch, is_active=active)
    account.set_password(PASSWORD)
    account.save()
    return account


def _coach(username, branch="Hamra", active=True):
    return _staff(username, [], branch=branch, job_title=StaffAccount.JobTitle.COACH, active=active)


def _member(name, username, branch="Hamra", days_valid=60, status=Member.Status.ACTIVE):
    today = timezone.localdate()
    member = Member(name=name, email=f"{username}@example.com", phone="70000000", branch=branch, join_date=today,
                    username=username, status=status, subscription_expires_at=today + timedelta(days=days_valid))
    member.set_password(PASSWORD)
    member.save()
    return member


def _type(name, max_capacity=20, branch="Hamra", minutes=60):
    return ClassType.objects.create(branch=branch, name=name, max_capacity=max_capacity, default_duration_minutes=minutes)


def _day(offset):
    return timezone.localdate() + timedelta(days=offset)


def _class(name, coach, day, start="18:00", minutes=60, branch="Hamra", room="", capacity=10, series=None,
           class_type=None):
    if class_type is None:
        class_type, _ = ClassType.objects.get_or_create(
            branch=branch, name=name, defaults={"max_capacity": max(capacity, 20), "default_duration_minutes": minutes},
        )
    starts_at = local_datetime(day, time.fromisoformat(start))
    return GymClass.objects.create(name=class_type.name, class_type=class_type, coach=coach, branch=branch, room=room,
                                   capacity=capacity, series=series, starts_at=starts_at,
                                   ends_at=starts_at + timedelta(minutes=minutes))


def _book(member, gym_class):
    return ClassBooking.objects.create(member=member, gym_class=gym_class)


def _member_login(client, username):
    res = client.post("/api/members/login", {"username": username, "password": PASSWORD}, content_type="application/json")
    assert res.status_code == 200, res.content


# User story: "As a branch manager, I want to create and edit class schedules
# and assign coaches to time slots, so that I can build the weekly class
# calendar for my branch."
class ClassScheduleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        _staff("admin", ["manage_class_schedule", "view_all_branches"], job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        _staff("mkt", ["manage_marketing_campaigns"], job_title=StaffAccount.JobTitle.MARKETING_STAFF)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lara = _coach("lara", branch="Jnah")
        cls.joe = _coach("joe", branch=None)
        cls.gone = _coach("gone", active=False)
        cls.spinning = _type("Spinning", max_capacity=16)
        cls.yoga = _type("Yoga", max_capacity=18)
        cls.hiit = _type("HIIT", max_capacity=20)
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def setUp(self):
        staff_login(self.client, "bm", PASSWORD)

    def body(self, **overrides):
        data = {"classTypeId": self.spinning.id, "coachId": self.hadi.id, "date": str(_day(1)), "startTime": "18:00",
                "durationMinutes": 60, "capacity": 12, "room": ""}
        data.update(overrides)
        return data

    def create(self, **overrides):
        return self.client.post("/api/classes", self.body(**overrides), content_type="application/json")

    def patch(self, gym_class, **changes):
        return self.client.patch(f"/api/classes/{gym_class.id}", changes, content_type="application/json")

    def conflicts(self, res):
        self.assertEqual(res.status_code, 409, res.content)
        return " ".join(res.json()["error"]["conflicts"])

    # --- the real calendar, in Beirut time ---
    def test_the_week_runs_monday_to_sunday_and_marks_past_days_and_today(self):
        today = timezone.localdate()
        body = self.client.get("/api/classes").json()
        self.assertEqual(body["weekStart"], str(today - timedelta(days=today.weekday())))
        self.assertEqual(len(body["days"]), 7)
        for day in body["days"]:
            self.assertEqual(day["isToday"], day["date"] == str(today))
            self.assertEqual(day["isPast"], day["date"] < str(today))
        self.assertEqual((body["branch"], body["canEdit"]), ("Hamra", True))
        later = self.client.get(f"/api/classes?week={_day(14)}").json()
        self.assertFalse(any(d["isPast"] or d["isToday"] for d in later["days"]))
        self.assertEqual(self.client.get("/api/classes?week=next").status_code, 400)

    def test_the_calendar_runs_on_beirut_time(self):
        body = self.client.get("/api/classes").json()
        self.assertEqual(body["timeZone"], "Asia/Beirut")
        self.assertIn(body["utcOffset"], ("+02:00", "+03:00"))  # winter / summer time
        server_now = datetime.fromisoformat(body["nowIso"])
        self.assertTrue(body["nowIso"].endswith(body["utcOffset"]))
        self.assertLess(abs((server_now - timezone.now()).total_seconds()), 60)
        self.assertEqual(body["today"], str(server_now.date()))

    def test_a_class_is_scheduled_with_a_coach_and_shows_on_its_week(self):
        res = self.create(room="Cycle Studio")
        self.assertEqual(res.status_code, 201, res.content)
        created = res.json()["classes"][0]
        self.assertEqual((created["name"], created["coachName"], created["startTime"], created["endTime"]),
                         ("Spinning", "Hadi", "18:00", "19:00"))
        self.assertEqual((created["state"], created["editable"], created["spotsLeft"], created["maxCapacity"]),
                         ("upcoming", True, 12, 16))
        week = self.client.get(f"/api/classes?week={_day(1)}").json()
        self.assertIn(created["id"], [c["id"] for c in week["classes"]])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_CREATED).exists())

    def test_a_days_classes_come_back_in_time_order(self):
        self.create(startTime="18:00")
        _class("Early Yoga", self.rita, _day(1), start="07:00")
        week = self.client.get(f"/api/classes?week={_day(1)}").json()["classes"]
        self.assertEqual([c["startTime"] for c in week if c["date"] == str(_day(1))], ["07:00", "18:00"])

    # --- coaches and studios can't be in two places at once ---
    def test_classes_can_run_at_the_same_time_with_different_coaches(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create(classTypeId=self.yoga.id, coachId=self.rita.id).status_code, 201)

    def test_a_coach_cannot_teach_two_overlapping_classes(self):
        self.create()
        self.assertIn("Hadi already teaches Spinning", self.conflicts(self.create(classTypeId=self.hiit.id, startTime="18:30")))
        self.assertEqual(self.create(classTypeId=self.hiit.id, startTime="19:00").status_code, 201)  # back to back

    def test_a_coach_clash_counts_at_every_branch(self):
        _class("Boxing", self.joe, _day(1), branch="Jnah")
        self.assertIn("at Jnah", self.conflicts(self.create(coachId=self.joe.id, startTime="18:30")))

    def test_a_studio_cannot_hold_two_classes_at_once(self):
        self.create(room="Studio A")
        self.assertIn("Studio A is already in use", self.conflicts(self.create(coachId=self.rita.id, room="studio a")))
        self.assertEqual(self.create(coachId=self.rita.id, room="Studio B").status_code, 201)

    def test_only_an_active_coach_from_the_branch_can_be_assigned(self):
        for coach_id, message in [(self.bm.id, "isn't a coach"), (self.gone.id, "deactivated"),
                                  (self.lara.id, "coaches at Jnah"), (9999, "Choose a coach")]:
            res = self.create(coachId=coach_id)
            self.assertEqual(res.status_code, 400)
            self.assertIn(message, res.json()["error"]["coachId"][0])
        self.assertEqual(self.create(coachId=self.joe.id).status_code, 201)  # not tied to a branch

    def availability(self, **params):
        query = {"date": str(_day(1)), "startTime": "18:00", "durationMinutes": 60, **params}
        return self.client.get("/api/classes/availability", query)

    def test_the_form_is_told_which_coaches_and_studios_are_already_taken(self):
        spin = _class("Spinning", self.hadi, _day(1), room="Cycle Studio")
        _class("Boxing", self.joe, _day(1), start="18:30", branch="Jnah", room="Ring")
        _class("Yoga", self.rita, _day(1), start="07:00", room="Studio A")
        body = self.availability().json()
        self.assertEqual(body["coaches"], {str(self.hadi.id): "Spinning 18:00–19:00", str(self.joe.id): "Boxing 18:30–19:30 at Jnah"})
        self.assertEqual(body["studios"], [{"name": "Cycle Studio", "takenBy": "Spinning 18:00–19:00"},
                                           {"name": "Studio A", "takenBy": None}])

        # The class being edited doesn't block itself, and back-to-back is free.
        editing = self.availability(excludeId=spin.id).json()
        self.assertEqual((list(editing["coaches"]), editing["studios"][0]["takenBy"]), ([str(self.joe.id)], None))
        self.assertNotIn(str(self.hadi.id), self.availability(startTime="19:00").json()["coaches"])

        # Repeating weekly checks every week of the run.
        _class("HIIT", self.rita, _day(15), room="Studio A")
        weekly = self.availability(repeatWeeks=3).json()
        label = f"HIIT on {_day(15):%a %d %b} 18:00–19:00"
        self.assertEqual((weekly["coaches"][str(self.rita.id)], weekly["studios"][1]["takenBy"]), (label, label))

        self.assertEqual(self.availability(startTime="6pm").status_code, 400)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.availability().status_code, 403)

    def test_the_coach_list_is_the_branchs_active_coaches(self):
        names = [c["name"] for c in self.client.get("/api/classes/coaches").json()["results"]]
        self.assertEqual(names, ["Hadi", "Joe", "Rita"])

    # --- the past is view-only ---
    def test_past_days_and_times_that_have_gone_by_cannot_be_scheduled(self):
        self.assertIn("date", self.create(date=str(_day(-1))).json()["error"])
        self.assertIn("startTime", self.create(date=str(_day(0)), startTime="00:00").json()["error"])
        self.assertIn("durationMinutes", self.create(startTime="23:30").json()["error"])
        self.assertIn("startTime", self.create(startTime="18:07").json()["error"])
        self.assertIn("durationMinutes", self.create(durationMinutes=10).json()["error"])
        self.assertIn("date", self.create(date=str(_day(400))).json()["error"])

    def test_started_or_finished_classes_can_be_viewed_but_not_changed(self):
        yesterday = _class("Yoga", self.rita, _day(-1))
        now = timezone.localtime()
        running = GymClass.objects.create(name="HIIT", class_type=self.hiit, coach=self.hadi, branch="Hamra", capacity=10,
                                          starts_at=now - timedelta(minutes=10), ends_at=now + timedelta(minutes=50))
        for gym_class, state in [(yesterday, "finished"), (running, "in_progress")]:
            detail = self.client.get(f"/api/classes/{gym_class.id}").json()
            self.assertEqual((detail["state"], detail["editable"]), (state, False))
            self.assertEqual(self.patch(gym_class, room="Changed").status_code, 409)
            self.assertEqual(self.client.post(f"/api/classes/{gym_class.id}/cancel").status_code, 409)
        self.assertIn("view-only", self.patch(yesterday, room="Changed").json()["error"])

    # --- repeating every week ---
    def test_repeat_weekly_puts_the_slot_on_every_week_or_nothing(self):
        res = self.create(repeatWeeks=4)
        classes = res.json()["classes"]
        self.assertEqual([c["date"] for c in classes], [str(_day(1 + 7 * w)) for w in range(4)])
        self.assertEqual(len({c["seriesId"] for c in classes}), 1)
        self.assertTrue(all(c["startTime"] == "18:00" for c in classes))

        _class("Boxing", self.rita, _day(15), start="18:30")
        self.assertIn("Rita already teaches Boxing", self.conflicts(self.create(coachId=self.rita.id, repeatWeeks=3)))
        self.assertEqual(GymClass.objects.filter(coach=self.rita).count(), 1)

    # --- editing ---
    def test_editing_a_class_rechecks_clashes_but_not_against_itself(self):
        gym_class = GymClass.objects.get(id=self.create().json()["classes"][0]["id"])
        res = self.patch(gym_class, startTime="18:30", coachId=self.rita.id, capacity=8, room="Studio A")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["classes"][0]["startTime"], res.json()["classes"][0]["coachName"]), ("18:30", "Rita"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_UPDATED).exists())

        _class("Yoga", self.hadi, _day(1), start="20:00")
        self.assertIn("Hadi already teaches Yoga", self.conflicts(self.patch(gym_class, coachId=self.hadi.id, startTime="19:30")))

    def test_capacity_cannot_drop_below_the_people_already_booked(self):
        gym_class = _class("Spinning", self.hadi, _day(1))
        _book(self.lea, gym_class)
        _book(self.sami, gym_class)
        self.assertIn("already has 2 bookings", self.conflicts(self.patch(gym_class, capacity=1)))
        self.assertEqual(self.patch(gym_class, capacity=2).status_code, 200)

    def test_a_class_cannot_be_moved_onto_another_class_its_members_booked(self):
        early = _class("Spinning", self.hadi, _day(1), start="18:00")
        late = _class("Yoga", self.rita, _day(1), start="20:00")
        _book(self.lea, early)
        _book(self.lea, late)
        self.assertIn("Lea Haddad is booked into another class", self.conflicts(self.patch(late, startTime="18:30")))
        self.assertEqual(self.patch(late, startTime="19:00").status_code, 200)

    def test_this_and_following_changes_the_rest_of_the_series_only(self):
        created = self.create(repeatWeeks=3).json()["classes"]
        second = GymClass.objects.get(id=created[1]["id"])
        res = self.patch(second, coachId=self.rita.id, startTime="17:00", scope="following")
        self.assertEqual([c["coachName"] for c in res.json()["classes"]], ["Rita", "Rita"])
        coaches = [c.coach.full_name for c in GymClass.objects.filter(id__in=[c["id"] for c in created]).order_by("starts_at")]
        self.assertEqual(coaches, ["Hadi", "Rita", "Rita"])
        move = self.patch(second, date=str(_day(9)), scope="following")
        self.assertIn("date", move.json()["error"])

    # --- cancelling ---
    def test_cancelling_a_class_releases_its_bookings_and_frees_the_coach(self):
        gym_class = _class("Spinning", self.hadi, _day(1))
        booking = _book(self.lea, gym_class)
        res = self.client.post(f"/api/classes/{gym_class.id}/cancel", {"reason": "Coach is sick"}, content_type="application/json")
        self.assertEqual((res.json()["releasedBookings"], res.json()["classes"][0]["state"]), (1, "cancelled"))
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.cancel_reason), ("Cancelled", "Class cancelled by the gym"))
        self.assertEqual(self.create().status_code, 201)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_CANCELLED).exists())

    def test_a_series_can_be_cancelled_from_one_class_onwards(self):
        created = self.create(repeatWeeks=3).json()["classes"]
        self.client.post(f"/api/classes/{created[1]['id']}/cancel", {"scope": "following"}, content_type="application/json")
        statuses = list(GymClass.objects.filter(id__in=[c["id"] for c in created]).order_by("starts_at").values_list("status", flat=True))
        self.assertEqual(statuses, ["Scheduled", "Cancelled", "Cancelled"])

    # --- who can do what ---
    def test_branch_managers_stay_on_their_own_branch(self):
        jnah = _class("Zumba", self.lara, _day(1), branch="Jnah")
        self.assertEqual(self.client.get("/api/classes?branch=Jnah").status_code, 403)
        self.assertEqual(self.client.get(f"/api/classes/{jnah.id}").status_code, 403)
        self.assertEqual(self.patch(jnah, room="Mine").status_code, 403)
        self.assertEqual(self.create(branch="Jnah").status_code, 403)
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.client.get("/api/classes?branch=Jnah").json()["classes"][0]["id"], jnah.id)

    def test_the_front_desk_can_look_but_not_change(self):
        gym_class = _class("Spinning", self.hadi, _day(1))
        staff_login(self.client, "desk", PASSWORD)
        self.assertFalse(self.client.get("/api/classes").json()["canEdit"])
        self.assertEqual(self.client.get(f"/api/classes/{gym_class.id}").status_code, 200)
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.patch(gym_class, room="x").status_code, 403)
        staff_login(self.client, "mkt", PASSWORD)
        self.assertEqual(self.client.get("/api/classes").status_code, 403)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/classes").status_code, 401)

    # --- attendance, once a class is over ---
    def test_finished_classes_mark_who_came_from_check_ins_and_log_no_shows(self):
        gym_class = _class("Yoga", self.rita, _day(-1))
        came, missed = _book(self.lea, gym_class), _book(self.sami, gym_class)
        visit = CheckIn.objects.create(member=self.lea, branch="Hamra", result=CheckIn.Result.ALLOWED)
        CheckIn.objects.filter(id=visit.id).update(checked_in_at=gym_class.starts_at - timedelta(minutes=10))

        roster = self.client.get(f"/api/classes/{gym_class.id}").json()["roster"]
        self.assertEqual({r["memberName"]: r["attendance"] for r in roster}, {"Lea Haddad": "Attended", "Sami Khoury": "No-show"})
        self.client.get("/api/classes")
        no_shows = TrainingEvent.objects.filter(event_type=TrainingEvent.EventType.NO_SHOW)
        self.assertEqual([(e.member_id, e.trainer_id, e.session_id) for e in no_shows], [(self.sami.id, self.rita.id, str(missed.id))])
        self.assertTrue(came)


# User story: "As a branch manager, I want to set maximum capacity per class
# type, so that I can prevent overbooking and keep sessions safe."
class ClassTypeCapacityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        _staff("admin", ["manage_class_schedule", "view_all_branches"], job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.spinning = _type("Spinning", max_capacity=16, minutes=45)
        cls.pilates = _type("Pilates", max_capacity=8)
        cls.members = [_member(f"Member {i}", f"m{i}") for i in range(3)]

    def setUp(self):
        staff_login(self.client, "bm", PASSWORD)

    def add_type(self, **body):
        return self.client.post("/api/classes/types", body, content_type="application/json")

    def edit_type(self, class_type, **changes):
        return self.client.patch(f"/api/classes/types/{class_type.id}", changes, content_type="application/json")

    def schedule(self, **overrides):
        body = {"classTypeId": self.spinning.id, "coachId": self.hadi.id, "date": str(_day(1)), "startTime": "18:00"}
        body.update(overrides)
        return self.client.post("/api/classes", body, content_type="application/json")

    def spinning_class(self, day=1, capacity=16, start="18:00"):
        return _class("Spinning", self.hadi, _day(day), start=start, capacity=capacity, class_type=self.spinning)

    def test_a_branch_manager_sets_up_class_types_with_a_maximum(self):
        res = self.add_type(name="  Body   Pump ", maxCapacity=20, defaultDurationMinutes=50)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["name"], res.json()["maxCapacity"], res.json()["branch"]), ("Body Pump", 20, "Hamra"))
        self.assertIn("already has a body pump", self.add_type(name="body pump", maxCapacity=5).json()["error"]["name"][0])
        for bad in (0, 101):
            self.assertIn("maxCapacity", self.add_type(name=f"Spin {bad}", maxCapacity=bad).json()["error"])
        self.assertIn("defaultDurationMinutes", self.add_type(name="Odd", maxCapacity=5, defaultDurationMinutes=47).json()["error"])
        names = [t["name"] for t in self.client.get("/api/classes/types").json()["results"]]
        self.assertEqual(names, ["Body Pump", "Pilates", "Spinning"])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_TYPE_CREATED).exists())
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.add_type(branch="Jnah", name="Body Pump", maxCapacity=12).status_code, 201)

    def test_a_class_gets_the_types_maximum_and_length_unless_told_otherwise_and_never_more(self):
        created = self.schedule().json()["classes"][0]
        self.assertEqual((created["capacity"], created["maxCapacity"], created["durationMinutes"]), (16, 16, 45))
        res = self.schedule(startTime="20:00", capacity=17)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Spinning holds at most 16 people at Hamra", res.json()["error"]["capacity"][0])
        self.assertEqual(self.schedule(startTime="20:00", capacity=10).json()["classes"][0]["capacity"], 10)

    def test_lowering_the_maximum_cuts_upcoming_classes_down_but_never_past_ones(self):
        full_size, smaller = self.spinning_class(capacity=16), self.spinning_class(capacity=10, start="20:00")
        past = self.spinning_class(day=-1, capacity=16)
        res = self.edit_type(self.spinning, maxCapacity=12)
        self.assertEqual((res.status_code, res.json()["maxCapacity"], res.json()["adjustedClasses"]), (200, 12, 1))
        for gym_class, expected in [(full_size, 12), (smaller, 10), (past, 16)]:
            gym_class.refresh_from_db()
            self.assertEqual(gym_class.capacity, expected)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_TYPE_UPDATED).exists())

    def test_raising_the_maximum_lifts_the_classes_that_were_at_the_old_one(self):
        at_max, smaller = self.spinning_class(capacity=16), self.spinning_class(capacity=10, start="20:00")
        self.assertEqual(self.edit_type(self.spinning, maxCapacity=20).json()["adjustedClasses"], 1)
        at_max.refresh_from_db()
        smaller.refresh_from_db()
        self.assertEqual((at_max.capacity, smaller.capacity), (20, 10))

    def test_the_maximum_cannot_go_below_people_already_booked(self):
        gym_class = self.spinning_class()
        for member in self.members:
            _book(member, gym_class)
        self.assertEqual(self.client.get("/api/classes/types").json()["results"][1]["mostBookedUpcoming"], 3)
        res = self.edit_type(self.spinning, maxCapacity=2)
        self.assertEqual(res.status_code, 409)
        self.assertIn("already has 3 bookings - more than 2", res.json()["error"]["conflicts"][0])
        self.spinning.refresh_from_db()
        gym_class.refresh_from_db()
        self.assertEqual((self.spinning.max_capacity, gym_class.capacity), (16, 16))
        self.assertEqual(self.edit_type(self.spinning, maxCapacity=3).status_code, 200)

    def test_bookings_stop_at_the_types_maximum(self):
        # A class over its type's limit (e.g. left from before the limit existed) still fills only to the limit.
        tight = _type("Reformer", max_capacity=2)
        gym_class = _class("Reformer", self.hadi, _day(1), capacity=5, class_type=tight)
        for member in self.members[:2]:
            _book(member, gym_class)
        _member_login(self.client, "m2")
        res = self.client.post(f"/api/members/me/classes/{gym_class.id}/book")
        self.assertEqual(res.status_code, 409)
        self.assertIn("full", res.json()["error"])

    def test_archived_types_cannot_be_scheduled_but_their_classes_stay(self):
        upcoming = self.spinning_class()
        self.assertEqual(self.edit_type(self.spinning, isActive=False).status_code, 200)
        self.assertNotIn("Spinning", [t["name"] for t in self.client.get("/api/classes/types").json()["results"]])
        archived = self.client.get("/api/classes/types?includeArchived=true").json()["results"]
        self.assertIn(("Spinning", False), [(t["name"], t["isActive"]) for t in archived])
        self.assertIn("archived", self.schedule(startTime="20:00").json()["error"]["classTypeId"][0])
        upcoming.refresh_from_db()
        self.assertEqual(upcoming.status, GymClass.Status.SCHEDULED)
        res = self.client.patch(f"/api/classes/{upcoming.id}", {"classTypeId": self.spinning.id, "room": "Studio C"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)  # its own classes can still be edited
        self.edit_type(self.spinning, isActive=True)
        self.assertEqual(self.schedule(startTime="20:00").status_code, 201)

    def test_renaming_a_type_renames_upcoming_classes_only(self):
        upcoming, past = self.spinning_class(), self.spinning_class(day=-1)
        self.edit_type(self.spinning, name="Indoor Cycling")
        upcoming.refresh_from_db()
        past.refresh_from_db()
        self.assertEqual((upcoming.name, past.name), ("Indoor Cycling", "Spinning"))

    def test_switching_a_class_to_a_smaller_type_has_to_fit(self):
        gym_class = self.spinning_class(capacity=12)
        res = self.client.patch(f"/api/classes/{gym_class.id}", {"classTypeId": self.pilates.id}, content_type="application/json")
        self.assertEqual((res.json()["classes"][0]["name"], res.json()["classes"][0]["capacity"]), ("Pilates", 8))
        res = self.client.patch(f"/api/classes/{gym_class.id}", {"capacity": 9}, content_type="application/json")
        self.assertIn("Pilates holds at most 8", res.json()["error"]["capacity"][0])

        crowded = self.spinning_class(start="20:00")
        for member in self.members:
            _book(member, crowded)
        tiny = _type("Private", max_capacity=2)
        res = self.client.patch(f"/api/classes/{crowded.id}", {"classTypeId": tiny.id}, content_type="application/json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("already has 3 bookings", res.json()["error"]["conflicts"][0])

    def test_class_types_belong_to_one_branch(self):
        jnah_type = _type("Zumba", branch="Jnah")
        self.assertEqual(self.edit_type(jnah_type, maxCapacity=5).status_code, 403)
        self.assertEqual(self.add_type(branch="Jnah", name="Yoga", maxCapacity=5).status_code, 403)
        self.assertIn("is a Jnah class type", self.schedule(classTypeId=jnah_type.id).json()["error"]["classTypeId"][0])
        staff_login(self.client, "desk", PASSWORD)
        listing = self.client.get("/api/classes/types").json()
        self.assertEqual((listing["canEdit"], len(listing["results"])), (False, 2))
        self.assertEqual(self.add_type(name="Boxing", maxCapacity=10).status_code, 403)
        self.assertEqual(self.edit_type(self.spinning, maxCapacity=10).status_code, 403)


# The member's side of the calendar: reserving a spot.
class ClassBookingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.spin = _class("Spinning", cls.hadi, _day(1), start="18:00", capacity=1)
        cls.yoga = _class("Yoga", cls.rita, _day(1), start="18:30")
        cls.late = _class("Pilates", cls.rita, _day(1), start="20:00")

    def setUp(self):
        _member_login(self.client, "lea")

    def book(self, gym_class):
        return self.client.post(f"/api/members/me/classes/{gym_class.id}/book")

    def test_a_member_reserves_and_gives_back_a_spot(self):
        res = self.book(self.spin)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["myBooking"]["status"], res.json()["spotsLeft"]), ("Booked", 0))
        week = self.client.get(f"/api/members/me/classes?week={_day(1)}").json()
        self.assertEqual([c["name"] for c in week["upcoming"]], ["Spinning"])
        self.assertTrue(week["canBook"])
        self.assertEqual(week["timeZone"], "Asia/Beirut")

        res = self.client.post(f"/api/members/me/classes/{self.spin.id}/cancel")
        self.assertEqual((res.json()["myBooking"]["status"], res.json()["spotsLeft"]), ("Cancelled", 1))
        self.assertEqual(self.book(self.spin).status_code, 201)  # can book again

    def test_a_member_cannot_take_two_classes_at_the_same_time(self):
        self.book(self.spin)
        res = self.book(self.yoga)
        self.assertEqual(res.status_code, 409)
        self.assertIn("can't take two classes at the same time", res.json()["error"])
        self.assertEqual(self.book(self.late).status_code, 201)

    def test_full_classes_and_double_bookings_are_refused(self):
        self.assertEqual(self.book(self.spin).status_code, 201)
        self.assertEqual(self.book(self.spin).status_code, 400)
        _member_login(self.client, "sami")
        self.assertIn("full", self.book(self.spin).json()["error"])

    def test_booking_needs_a_membership_that_covers_the_class(self):
        Member.objects.filter(id=self.lea.id).update(status=Member.Status.FROZEN)
        self.assertIn("frozen", self.book(self.late).json()["error"])
        Member.objects.filter(id=self.lea.id).update(status=Member.Status.ACTIVE, subscription_expires_at=timezone.localdate())
        self.assertIn("renew it", self.book(self.late).json()["error"])

    def test_only_upcoming_classes_at_the_members_branch_can_be_booked(self):
        jnah = _class("Zumba", self.rita, _day(2), branch="Jnah")
        self.assertEqual(self.book(jnah).status_code, 403)
        past = _class("Yoga", self.rita, _day(-1))
        self.assertIn("already started", self.book(past).json()["error"])
        GymClass.objects.filter(id=self.late.id).update(status=GymClass.Status.CANCELLED)
        self.assertIn("cancelled", self.book(self.late).json()["error"])
        self.assertEqual(self.client.post("/api/members/me/classes/9999/book").status_code, 404)

    def test_a_reservation_cannot_be_cancelled_once_the_class_starts(self):
        past = _class("Yoga", self.rita, _day(-1))
        _book(self.lea, past)
        self.assertIn("already started", self.client.post(f"/api/members/me/classes/{past.id}/cancel").json()["error"])

    def test_freezing_or_cancelling_a_membership_frees_future_spots(self):
        self.book(self.spin)
        self.client.post("/api/members/me/freeze")
        booking = ClassBooking.objects.get(member=self.lea, gym_class=self.spin)
        self.assertEqual((booking.status, booking.cancel_reason), ("Cancelled", "Membership frozen"))
        _member_login(self.client, "sami")
        self.assertEqual(self.book(self.spin).status_code, 201)

    def test_bookings_are_part_of_the_members_data_export(self):
        self.book(self.spin)
        export = self.client.get("/api/members/me/export").json()
        self.assertEqual([(b["className"], b["status"]) for b in export["classBookings"]], [("Spinning", "Booked")])


def _hours(coach, day, start, end, minutes=60, branch="Hamra"):
    return PTAvailability.objects.create(coach=coach, branch=branch, weekday=day.weekday(), session_minutes=minutes,
                                         start_time=time.fromisoformat(start), end_time=time.fromisoformat(end))


# User story: "As a member, I want to browse and book available classes or PT
# sessions directly through the app, so that I can reserve my spot without
# contacting the front desk."
class PrivateTrainingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.joe = _coach("joe", branch=None)
        cls.lara = _coach("lara", branch="Jnah")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.day = _day(2)
        cls.hadi_hours = _hours(cls.hadi, cls.day, "09:00", "12:00")  # sessions at 09:00, 10:00, 11:00

    def setUp(self):
        _member_login(self.client, "lea")

    def slots(self, coach=None, day=None):
        coach, day = coach or self.hadi, day or self.day
        body = self.client.get(f"/api/members/me/pt-slots?coachId={coach.id}&week={day}").json()
        return {s["startTime"]: s["state"] for s in body["slots"] if s["date"] == str(day)}

    def book(self, start, coach=None, day=None, note=""):
        coach, day = coach or self.hadi, day or self.day
        body = {"coachId": coach.id, "startsAt": f"{day}T{start}", "note": note}
        return self.client.post("/api/members/me/pt-sessions", body, content_type="application/json")

    def session(self, member, start, coach=None, day=None):
        starts_at = local_datetime(day or self.day, time.fromisoformat(start))
        return PTSession.objects.create(coach=coach or self.hadi, member=member, branch="Hamra", starts_at=starts_at,
                                        ends_at=starts_at + timedelta(hours=1))

    def test_members_see_the_branchs_coaches_with_what_they_teach_and_their_pt_hours(self):
        _class("Spinning", self.hadi, self.day, start="18:00")
        coaches = {c["name"]: c for c in self.client.get("/api/members/me/coaches").json()["coaches"]}
        self.assertEqual(list(coaches), ["Hadi", "Joe", "Rita"])  # the branch's coaches and floating ones
        hadi = coaches["Hadi"]
        self.assertEqual(hadi["teaches"], ["Spinning"])
        self.assertEqual((hadi["ptHours"][0]["startTime"], hadi["ptHours"][0]["endTime"]), ("09:00", "12:00"))
        self.assertEqual(hadi["nextOpen"], {"date": str(self.day), "startTime": "09:00"})
        self.assertEqual((coaches["Rita"]["ptHours"], coaches["Rita"]["nextOpen"]), ([], None))
        self.assertEqual(self.client.get(f"/api/members/me/pt-slots?coachId={self.lara.id}").status_code, 404)

    def test_hours_are_cut_into_sessions_showing_what_is_free(self):
        _class("HIIT", self.hadi, self.day, start="11:00")
        self.session(self.sami, "10:00")
        _book(self.lea, _class("Yoga", self.rita, self.day, start="09:00"))
        self.assertEqual(self.slots(), {"09:00": "clash", "10:00": "taken", "11:00": "coach_busy"})
        early = rules.pt_slots(self.hadi, "Hamra", [_day(9)], now=local_datetime(_day(9), time(8, 30)))
        self.assertEqual([s["state"] for s in early], ["closed", "open", "open"])  # 09:00 is under an hour away

    def test_a_member_books_a_free_session_and_nobody_else_can_take_it(self):
        res = self.book("09:00", note="Knee rehab")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["coachName"], res.json()["startTime"], res.json()["endTime"], res.json()["note"]),
                         ("Hadi", "09:00", "10:00", "Knee rehab"))
        self.assertEqual(self.slots()["09:00"], "yours")
        upcoming = self.client.get("/api/members/me/classes").json()["upcomingPt"]
        self.assertEqual([s["startTime"] for s in upcoming], ["09:00"])

        _member_login(self.client, "sami")
        self.assertEqual(self.slots()["09:00"], "taken")
        res = self.book("09:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("just booked", res.json()["error"])

    def test_only_real_free_sessions_can_be_booked(self):
        self.assertIn("isn't one of", self.book("12:00").json()["error"])
        self.assertIn("isn't one of", self.book("09:30").json()["error"])
        _hours(self.rita, _day(0), "00:00", "00:30", minutes=30)
        self.assertIn("already started", self.book("00:00", coach=self.rita, day=_day(0)).json()["error"])
        _class("HIIT", self.hadi, self.day, start="11:00")
        self.assertIn("teaching a class", self.book("11:00").json()["error"])
        _book(self.lea, _class("Yoga", self.rita, self.day, start="10:00"))
        res = self.book("10:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("already booked into Yoga", res.json()["error"])
        self.assertEqual(self.book("09:00", coach=self.lara).status_code, 404)

    def test_a_member_holds_at_most_four_upcoming_sessions(self):
        _hours(self.hadi, _day(3), "09:00", "12:00")
        for start, day in [("09:00", self.day), ("10:00", self.day), ("11:00", self.day), ("09:00", _day(3))]:
            self.assertEqual(self.book(start, day=day).status_code, 201)
        res = self.book("10:00", day=_day(3))
        self.assertEqual(res.status_code, 409)
        self.assertIn("up to 4", res.json()["error"])

    def test_booking_needs_a_membership_that_covers_the_session(self):
        Member.objects.filter(id=self.lea.id).update(status=Member.Status.FROZEN)
        self.assertIn("frozen", self.book("09:00").json()["error"])
        Member.objects.filter(id=self.lea.id).update(status=Member.Status.ACTIVE, subscription_expires_at=_day(1))
        self.assertIn("renew it", self.book("09:00").json()["error"])

    def test_private_training_and_classes_never_overlap(self):
        self.book("09:00")
        # The coach can't be given a class during the session...
        staff_login(self.client, "bm", PASSWORD)
        spin = _type("Spinning")
        res = self.client.post("/api/classes", {"classTypeId": spin.id, "coachId": self.hadi.id, "date": str(self.day),
                                                "startTime": "09:30", "durationMinutes": 60}, content_type="application/json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("private training session", " ".join(res.json()["error"]["conflicts"]))
        busy = self.client.get("/api/classes/availability", {"date": str(self.day), "startTime": "09:30", "durationMinutes": 60})
        self.assertEqual(busy.json()["coaches"][str(self.hadi.id)], "Private training 09:00–10:00")
        # ...and the member can't take a class during it.
        yoga = _class("Yoga", self.rita, self.day, start="09:00")
        _member_login(self.client, "lea")
        res = self.client.post(f"/api/members/me/classes/{yoga.id}/book")
        self.assertEqual(res.status_code, 409)
        self.assertIn("private training session", res.json()["error"])

    def test_sessions_can_be_given_back_cancelled_by_the_gym_or_released(self):
        session_id = self.book("09:00").json()["id"]
        res = self.client.post(f"/api/members/me/pt-sessions/{session_id}/cancel")
        self.assertEqual(res.json()["state"], "cancelled")
        self.assertEqual(self.slots()["09:00"], "open")

        session_id = self.book("09:00").json()["id"]
        staff_login(self.client, "bm", PASSWORD)
        res = self.client.post(f"/api/classes/pt-sessions/{session_id}/cancel", {"reason": "Coach is ill"},
                               content_type="application/json")
        self.assertEqual(res.json()["cancelReason"], "Cancelled by the gym: Coach is ill")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PT_SESSION_CANCELLED).exists())

        _member_login(self.client, "lea")
        self.book("10:00")
        self.client.post("/api/members/me/freeze")
        self.assertEqual(PTSession.objects.filter(member=self.lea, cancel_reason="Membership frozen").count(), 1)

        past = self.session(self.sami, "09:00", day=_day(-1))
        self.assertTrue(past.has_started)
        _member_login(self.client, "sami")
        self.assertIn("already started", self.client.post(f"/api/members/me/pt-sessions/{past.id}/cancel").json()["error"])

    def test_managers_publish_pt_hours_that_never_overlap(self):
        staff_login(self.client, "bm", PASSWORD)

        def add(**body):
            data = {"coachId": self.hadi.id, "weekday": self.day.weekday(), "startTime": "13:00", "endTime": "15:00",
                    "sessionMinutes": 60, **body}
            return self.client.post("/api/classes/pt-hours", data, content_type="application/json")

        self.assertEqual(add().status_code, 201)
        self.assertIn("already has PT hours", " ".join(add(startTime="14:00", endTime="16:00").json()["error"]["conflicts"]))
        _hours(self.joe, self.day, "10:00", "12:00", branch="Jnah")
        self.assertIn("at Jnah", " ".join(add(coachId=self.joe.id, startTime="11:00", endTime="13:00").json()["error"]["conflicts"]))
        self.assertIn("coaches at Jnah", add(coachId=self.lara.id).json()["error"]["coachId"][0])
        self.assertIn("endTime", add(startTime="15:00", endTime="14:00").json()["error"])
        self.assertIn("endTime", add(startTime="16:00", endTime="16:30").json()["error"])
        self.assertIn("sessionMinutes", add(sessionMinutes=50).json()["error"])

        listing = self.client.get("/api/classes/pt-hours").json()
        hadi = next(c for c in listing["coaches"] if c["name"] == "Hadi")
        self.assertEqual([(h["startTime"], h["endTime"]) for h in hadi["hours"]], [("09:00", "12:00"), ("13:00", "15:00")])

        self.session(self.lea, "09:00")
        res = self.client.delete(f"/api/classes/pt-hours/{self.hadi_hours.id}")
        self.assertEqual(res.json()["bookedSessionsKept"], 1)
        self.assertTrue(PTSession.objects.filter(member=self.lea, status="Booked").exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PT_HOURS_ADDED).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PT_HOURS_REMOVED).exists())

        staff_login(self.client, "desk", PASSWORD)
        self.assertFalse(self.client.get("/api/classes/pt-hours").json()["canEdit"])
        self.assertEqual(add(startTime="18:00", endTime="19:00").status_code, 403)

    def test_the_managers_week_shows_booked_sessions(self):
        self.book("10:00")
        staff_login(self.client, "bm", PASSWORD)
        sessions = self.client.get(f"/api/classes?week={self.day}").json()["ptSessions"]
        self.assertEqual([(s["coachName"], s["memberName"], s["startTime"]) for s in sessions], [("Hadi", "Lea Haddad", "10:00")])

    def test_finished_sessions_are_marked_and_no_shows_logged(self):
        missed = self.session(self.lea, "09:00", day=_day(-1))
        self.client.get(f"/api/members/me/pt-slots?coachId={self.hadi.id}")
        missed.refresh_from_db()
        self.assertEqual(missed.attendance, "No-show")
        event = TrainingEvent.objects.get(event_type=TrainingEvent.EventType.NO_SHOW)
        self.assertEqual((event.member_id, event.trainer_id, event.session_id), (self.lea.id, self.hadi.id, f"pt:{missed.id}"))

    def test_sessions_are_part_of_the_members_data_export(self):
        self.book("11:00", note="Posture")
        export = self.client.get("/api/members/me/export").json()
        self.assertEqual([(s["coach"], s["note"], s["status"]) for s in export["ptSessions"]], [("Hadi", "Posture", "Booked")])


# User story: "As a coach, I want to view my daily and weekly schedule of
# classes and PT sessions, so that I can plan my working day."
class MyScheduleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.day = _day(2)

    def _pt_session(self, member, coach, start, day=None):
        starts_at = local_datetime(day or self.day, time.fromisoformat(start))
        return PTSession.objects.create(coach=coach, member=member, branch="Hamra", starts_at=starts_at,
                                        ends_at=starts_at + timedelta(hours=1))

    def schedule(self, week=None):
        url = "/api/classes/me/schedule"
        if week:
            url += f"?week={week}"
        return self.client.get(url)

    def test_requires_a_staff_session(self):
        self.assertEqual(self.schedule().status_code, 401)

    def test_a_coach_sees_only_their_own_classes_and_pt_sessions(self):
        mine = _class("Spinning", self.hadi, self.day, start="18:00")
        _book(self.lea, mine)
        _class("Yoga", self.rita, self.day, start="19:00")  # not Hadi's
        self._pt_session(self.sami, self.hadi, "09:00")
        self._pt_session(self.lea, self.rita, "10:00")  # not Hadi's

        staff_login(self.client, "hadi", PASSWORD)
        body = self.schedule(self.day).json()
        self.assertEqual(body["coachName"], "Hadi")
        self.assertEqual([c["name"] for c in body["classes"]], ["Spinning"])
        self.assertEqual(body["classes"][0]["booked"], 1)
        self.assertEqual([(s["memberName"], s["startTime"]) for s in body["ptSessions"]], [("Sami Khoury", "09:00")])

    def test_no_permission_is_required_just_your_own_data(self):
        # "bm" (a Branch Manager, not a Coach) has manage_class_schedule but
        # no classes of their own - the endpoint still works, just empty.
        _class("Spinning", self.hadi, self.day, start="18:00")
        staff_login(self.client, "bm", PASSWORD)
        body = self.schedule(self.day).json()
        self.assertEqual((body["classes"], body["ptSessions"]), ([], []))

    def test_a_cancelled_class_still_shows_so_the_coach_knows_their_day_cleared(self):
        cancelled = _class("HIIT", self.hadi, self.day, start="17:00")
        GymClass.objects.filter(id=cancelled.id).update(status=GymClass.Status.CANCELLED)
        staff_login(self.client, "hadi", PASSWORD)
        body = self.schedule(self.day).json()
        self.assertEqual(body["classes"][0]["state"], "cancelled")

    def test_the_week_runs_monday_to_sunday_around_the_given_date(self):
        staff_login(self.client, "hadi", PASSWORD)
        body = self.schedule(self.day).json()
        self.assertEqual(len(body["days"]), 7)
        self.assertTrue(body["weekStart"] <= str(self.day) <= body["weekEnd"])


# User story: "As a coach, I want to set my own availability for personal
# training sessions, so that members can book time with me directly instead
# of going through the front desk."
class MyPTHoursTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.hadi = _coach("hadi", branch="Hamra")
        cls.rita = _coach("rita", branch="Hamra")
        cls.joe = _coach("joe", branch=None)

    def hours(self):
        return self.client.get("/api/classes/me/pt-hours")

    def add(self, **overrides):
        body = {"weekday": 0, "startTime": "09:00", "endTime": "12:00", "sessionMinutes": 60}
        body.update(overrides)
        return self.client.post("/api/classes/me/pt-hours", body, content_type="application/json")

    def remove(self, hours_id):
        return self.client.delete(f"/api/classes/me/pt-hours/{hours_id}")

    def test_requires_authentication(self):
        self.assertEqual(self.hours().status_code, 401)
        self.assertEqual(self.add().status_code, 401)

    def test_only_a_coach_can_use_it(self):
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.hours().status_code, 403)
        self.assertEqual(self.add().status_code, 403)

    def test_a_coach_tied_to_a_branch_gets_hours_there_without_asking(self):
        staff_login(self.client, "hadi", PASSWORD)
        res = self.add()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["branch"], "Hamra")
        listed = self.hours().json()
        self.assertEqual(listed["branches"], ["Hamra"])
        self.assertEqual([h["branch"] for h in listed["hours"]], ["Hamra"])

    def test_a_coach_tied_to_a_branch_cannot_set_hours_elsewhere(self):
        staff_login(self.client, "hadi", PASSWORD)
        res = self.add(branch="Jnah")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Hamra", res.json()["error"]["branch"][0])

    def test_a_floating_coach_must_choose_a_branch(self):
        staff_login(self.client, "joe", PASSWORD)
        res = self.add()
        self.assertEqual(res.status_code, 400)
        self.assertIn("Choose which branch", res.json()["error"]["branch"][0])
        self.assertEqual(self.hours().json()["branches"], list(Member.Branch.values))

    def test_a_floating_coach_can_pick_any_branch(self):
        staff_login(self.client, "joe", PASSWORD)
        res = self.add(branch="Zalka")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["branch"], "Zalka")

    def test_overlapping_hours_on_the_same_weekday_are_refused(self):
        staff_login(self.client, "hadi", PASSWORD)
        self.add(startTime="09:00", endTime="12:00")
        res = self.add(startTime="11:00", endTime="13:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("already have PT hours", res.json()["error"]["conflicts"][0])

    def test_a_coach_can_only_remove_their_own_hours(self):
        staff_login(self.client, "hadi", PASSWORD)
        mine = self.add().json()
        staff_login(self.client, "rita", PASSWORD)
        theirs = self.add(startTime="14:00", endTime="16:00").json()
        self.assertEqual(self.remove(mine["id"]).status_code, 404)  # not Rita's
        res = self.remove(theirs["id"])
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(PTAvailability.objects.filter(id=theirs["id"]).exists(), False)
        self.assertEqual(PTAvailability.objects.filter(id=mine["id"]).exists(), True)

    def test_removing_hours_keeps_sessions_already_booked_in_them(self):
        staff_login(self.client, "hadi", PASSWORD)
        added = self.add(**{"weekday": _day(2).weekday(), "startTime": "09:00", "endTime": "12:00"}).json()
        member = _member("Lea Haddad", "lea")
        _ = PTSession.objects.create(coach=self.hadi, member=member, branch="Hamra",
                                     starts_at=local_datetime(_day(2), time.fromisoformat("09:00")),
                                     ends_at=local_datetime(_day(2), time.fromisoformat("10:00")))
        res = self.remove(added["id"])
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["bookedSessionsKept"], 1)
        self.assertEqual(PTSession.objects.filter(coach=self.hadi).count(), 1)

    def test_it_writes_to_the_audit_log(self):
        staff_login(self.client, "hadi", PASSWORD)
        added = self.add().json()
        entry = AuditLog.objects.filter(action=AuditLog.Action.PT_HOURS_ADDED).latest("id")
        self.assertEqual((entry.actor_name, entry.branch), ("Hadi", "Hamra"))
        self.remove(added["id"])
        removed = AuditLog.objects.filter(action=AuditLog.Action.PT_HOURS_REMOVED).latest("id")
        self.assertEqual(removed.actor_name, "Hadi")


# User story: "As a coach, I want to block off time on my calendar when
# I'm unavailable, so that members can't book me during that time."
class MyTimeOffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.hadi = _coach("hadi", branch="Hamra")
        cls.rita = _coach("rita", branch="Hamra")
        cls.lea = _member("Lea Haddad", "lea")
        cls.day = _day(2)

    def _range(self, start="09:00", end="12:00", day=None):
        day = day or self.day
        return f"{day}T{start}", f"{day}T{end}"

    def block(self, start="09:00", end="12:00", day=None, reason=""):
        starts_at, ends_at = self._range(start, end, day)
        return self.client.post("/api/classes/me/time-off",
                                {"startsAt": starts_at, "endsAt": ends_at, "reason": reason},
                                content_type="application/json")

    def list_blocks(self):
        return self.client.get("/api/classes/me/time-off")

    def remove(self, block_id):
        return self.client.delete(f"/api/classes/me/time-off/{block_id}")

    def test_requires_authentication(self):
        self.assertEqual(self.list_blocks().status_code, 401)
        self.assertEqual(self.block().status_code, 401)

    def test_only_a_coach_can_use_it(self):
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.list_blocks().status_code, 403)
        self.assertEqual(self.block().status_code, 403)

    def test_a_coach_can_block_time_off_and_see_it_listed(self):
        staff_login(self.client, "hadi", PASSWORD)
        res = self.block(reason="Vacation")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["reason"], body["state"]), ("Vacation", "upcoming"))
        listed = self.list_blocks().json()
        self.assertEqual(listed["coachName"], "Hadi")
        self.assertEqual([b["id"] for b in listed["blocks"]], [body["id"]])

    def test_end_must_be_after_start(self):
        staff_login(self.client, "hadi", PASSWORD)
        res = self.block(start="10:00", end="09:00")
        self.assertEqual(res.status_code, 400)
        self.assertIn("after the start", res.json()["error"]["endsAt"][0])

    def test_cannot_block_a_time_already_in_the_past(self):
        staff_login(self.client, "hadi", PASSWORD)
        res = self.block(day=_day(-2))
        self.assertEqual(res.status_code, 400)
        self.assertIn("already in the past", res.json()["error"]["endsAt"][0])

    def test_overlapping_blocks_are_refused(self):
        staff_login(self.client, "hadi", PASSWORD)
        self.block(start="09:00", end="12:00")
        res = self.block(start="11:00", end="13:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("overlaps time off you've already blocked", res.json()["error"]["conflicts"][0])

    def test_a_block_over_a_class_the_coach_already_teaches_is_refused(self):
        _class("Spinning", self.hadi, self.day, start="10:00")
        staff_login(self.client, "hadi", PASSWORD)
        res = self.block(start="09:00", end="12:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("Spinning", res.json()["error"]["conflicts"][0])

    def test_a_block_over_a_booked_pt_session_is_refused(self):
        starts_at = local_datetime(self.day, time.fromisoformat("10:00"))
        PTSession.objects.create(coach=self.hadi, member=self.lea, branch="Hamra", starts_at=starts_at,
                                 ends_at=starts_at + timedelta(hours=1))
        staff_login(self.client, "hadi", PASSWORD)
        res = self.block(start="09:00", end="12:00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("private training session", res.json()["error"]["conflicts"][0])

    def test_a_coach_can_only_remove_their_own_block(self):
        staff_login(self.client, "hadi", PASSWORD)
        mine = self.block().json()
        staff_login(self.client, "rita", PASSWORD)
        theirs = self.block(start="14:00", end="16:00").json()
        self.assertEqual(self.remove(mine["id"]).status_code, 404)  # not Rita's
        res = self.remove(theirs["id"])
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(TimeOff.objects.filter(id=theirs["id"]).exists(), False)
        self.assertEqual(TimeOff.objects.filter(id=mine["id"]).exists(), True)

    def test_removing_a_block_opens_the_time_back_up_for_members(self):
        _hours(self.hadi, self.day, "09:00", "12:00")
        staff_login(self.client, "hadi", PASSWORD)
        added = self.block(start="09:00", end="10:00").json()
        self.assertEqual(rules.pt_slots(self.hadi, "Hamra", [self.day])[0]["state"], "blocked")
        self.remove(added["id"])
        self.assertEqual(rules.pt_slots(self.hadi, "Hamra", [self.day])[0]["state"], "open")

    def test_a_member_cannot_book_a_blocked_slot(self):
        _hours(self.hadi, self.day, "09:00", "12:00")
        staff_login(self.client, "hadi", PASSWORD)
        self.block(start="09:00", end="10:00")
        _member_login(self.client, "lea")
        res = self.client.post("/api/members/me/pt-sessions",
                               {"coachId": self.hadi.id, "startsAt": f"{self.day}T09:00"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 409)
        self.assertIn("isn't available", res.json()["error"])

    def test_a_coachs_schedule_includes_their_time_off(self):
        staff_login(self.client, "hadi", PASSWORD)
        self.block(start="09:00", end="10:00", reason="Dentist")
        body = self.client.get(f"/api/classes/me/schedule?week={self.day}").json()
        self.assertEqual([(t["reason"], t["state"]) for t in body["timeOff"]], [("Dentist", "upcoming")])

    def test_it_writes_to_the_audit_log(self):
        staff_login(self.client, "hadi", PASSWORD)
        added = self.block(reason="Vacation").json()
        entry = AuditLog.objects.filter(action=AuditLog.Action.TIME_OFF_ADDED).latest("id")
        self.assertEqual((entry.actor_name, entry.branch), ("Hadi", "Hamra"))
        self.remove(added["id"])
        removed = AuditLog.objects.filter(action=AuditLog.Action.TIME_OFF_REMOVED).latest("id")
        self.assertEqual(removed.actor_name, "Hadi")


# User story: "As a receptionist, I want to view the daily class schedule and
# open slots, so that I can answer member questions and book walk-ins into
# classes."
class FrontDeskClassTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        receptionist = StaffAccount.JobTitle.RECEPTIONIST
        _staff("desk", ["manage_members"], branch="Hamra", job_title=receptionist)
        _staff("jnahdesk", ["manage_members"], branch="Jnah", job_title=receptionist)
        _staff("floater", ["manage_members"], job_title=receptionist)
        _staff("admin", ["manage_members", "manage_class_schedule", "view_all_branches"],
               job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        _staff("gm", ["view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.nour = _member("Nour Saad", "nour", branch="Jnah")
        cls.tomorrow = _day(1)
        cls.spin = _class("Spinning", cls.hadi, cls.tomorrow, start="18:00", capacity=2, room="Cycle Studio")
        cls.yoga = _class("Yoga", cls.rita, cls.tomorrow, start="18:30", capacity=5)

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def day(self, date=None, **params):
        query = {**({"date": str(date)} if date else {}), **params}
        return self.client.get("/api/classes/day", query)

    def search(self, gym_class, q):
        return self.client.get(f"/api/classes/{gym_class.id}/member-search", {"q": q})

    def book(self, gym_class, member):
        member_id = member.id if hasattr(member, "id") else member
        return self.client.post(f"/api/classes/{gym_class.id}/bookings", {"memberId": member_id},
                                content_type="application/json")

    def remove(self, gym_class, booking_id):
        return self.client.post(f"/api/classes/{gym_class.id}/bookings/{booking_id}/cancel")

    def running_class(self):
        now = timezone.localtime()
        return GymClass.objects.create(
            name="HIIT", class_type=_type("HIIT"), coach=self.rita, branch="Hamra", capacity=5,
            starts_at=now - timedelta(minutes=10), ends_at=now + timedelta(minutes=50),
        )

    # --- the day's schedule and open slots ---
    def test_a_day_lists_its_classes_in_order_with_the_spots_still_open(self):
        _book(self.lea, self.spin)
        body = self.day(self.tomorrow).json()
        self.assertEqual((body["branch"], body["date"], body["isPast"], body["isToday"]),
                         ("Hamra", str(self.tomorrow), False, False))
        rows = [(c["name"], c["startTime"], c["coachName"], c["room"], c["booked"], c["spotsLeft"]) for c in body["classes"]]
        self.assertEqual(rows, [("Spinning", "18:00", "Hadi", "Cycle Studio", 1, 1), ("Yoga", "18:30", "Rita", "", 0, 5)])
        self.assertEqual(body["summary"], {"classes": 2, "openClasses": 2, "openSpots": 6, "fullClasses": 0})
        self.assertTrue(body["canBookMembers"])
        self.assertFalse(body["canEdit"])
        self.assertEqual(body["timeZone"], "Asia/Beirut")

    def test_the_day_defaults_to_today_in_beirut_and_rejects_a_bad_date(self):
        self.assertEqual(self.day().json()["date"], str(timezone.localdate()))
        self.assertTrue(self.day().json()["isToday"])
        res = self.day(date="tomorrow")
        self.assertEqual(res.status_code, 400)
        self.assertIn("date must be a date", res.json()["error"])

    def test_only_classes_that_can_still_be_booked_count_as_open(self):
        _book(self.lea, self.spin)
        _book(self.sami, self.spin)  # full
        cancelled = _class("Boxing", self.rita, self.tomorrow, start="07:00", capacity=9)
        GymClass.objects.filter(id=cancelled.id).update(status=GymClass.Status.CANCELLED)
        summary = self.day(self.tomorrow).json()["summary"]
        self.assertEqual(summary, {"classes": 2, "openClasses": 1, "openSpots": 5, "fullClasses": 1})

        self.running_class()
        today = self.day().json()
        self.assertEqual([c["state"] for c in today["classes"]], ["in_progress"])
        self.assertEqual((today["summary"]["classes"], today["summary"]["openSpots"]), (1, 0))

        past = _class("Pilates", self.rita, _day(-1), capacity=9)
        body = self.day(_day(-1)).json()
        self.assertTrue(body["isPast"])
        self.assertEqual(([c["id"] for c in body["classes"]], body["summary"]["openSpots"]), ([past.id], 0))

    def test_open_spots_never_count_past_the_types_maximum(self):
        tight = _type("Reformer", max_capacity=2)
        _class("Reformer", self.rita, _day(2), capacity=5, class_type=tight)
        self.assertEqual(self.day(_day(2)).json()["classes"][0]["spotsLeft"], 2)

    def test_the_next_open_class_is_offered_when_this_day_has_none(self):
        _book(self.lea, self.spin)
        body = self.day().json()  # nothing today; the first class with a free spot is tomorrow's Spinning
        self.assertEqual(body["nextOpen"]["id"], self.spin.id)
        self.assertEqual(body["nextOpen"]["spotsLeft"], 1)
        _book(self.sami, self.spin)
        self.assertEqual(self.day().json()["nextOpen"]["id"], self.yoga.id)  # Spinning filled up
        GymClass.objects.filter(id=self.yoga.id).update(status=GymClass.Status.CANCELLED)
        self.assertIsNone(self.day().json()["nextOpen"])

    def test_the_day_stays_on_the_receptionists_own_branch(self):
        _class("Zumba", self.rita, self.tomorrow, branch="Jnah")
        self.assertEqual(self.day(self.tomorrow, branch="Jnah").status_code, 403)
        staff_login(self.client, "floater", PASSWORD)
        self.assertIn("isn't assigned to a branch", self.day().json()["error"])
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.day(self.tomorrow, branch="Jnah").json()["classes"][0]["name"], "Zumba")
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.day().status_code, 403)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.day().status_code, 401)

    # --- finding the member at the desk ---
    def test_a_member_is_found_by_name_id_phone_or_card(self):
        self.assertEqual([m["name"] for m in self.search(self.yoga, "hadd").json()["results"]], ["Lea Haddad"])
        self.assertEqual([m["id"] for m in self.search(self.yoga, str(self.sami.id)).json()["results"]], [self.sami.id])
        Member.objects.filter(id=self.lea.id).update(phone="70123456")
        self.assertEqual([m["id"] for m in self.search(self.yoga, "123456").json()["results"]], [self.lea.id])
        card = qr.payload_for(self.lea)
        self.assertEqual([m["id"] for m in self.search(self.yoga, card).json()["results"]], [self.lea.id])
        self.assertEqual(self.search(self.yoga, "").json()["results"], [])
        self.assertEqual(self.search(self.yoga, "nobody here").json()["results"], [])

    def test_odd_searches_are_handled(self):
        self.assertEqual(self.search(self.yoga, "99999999999999999999999").json()["results"], [])
        self.assertEqual(self.search(self.yoga, "²").json()["results"], [])
        arabic_id = str(self.lea.id).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
        self.assertEqual(self.search(self.yoga, arabic_id).json()["results"][0]["id"], self.lea.id)
        res = self.search(self.yoga, "FFM1:1:forged")
        self.assertEqual(res.status_code, 400)
        self.assertIn("isn't a valid", res.json()["error"])

    def test_a_replaced_card_is_refused(self):
        old_card = qr.payload_for(self.lea)
        Member.objects.filter(id=self.lea.id).update(access_card_number=2)
        res = self.search(self.yoga, old_card)
        self.assertEqual(res.status_code, 400)
        self.assertIn("replaced", res.json()["error"])

    def test_search_says_who_can_be_booked_and_why_not(self):
        Member.objects.filter(id=self.sami.id).update(status=Member.Status.FROZEN)
        frozen = self.search(self.yoga, "Sami").json()["results"][0]
        self.assertFalse(frozen["canBook"])
        self.assertIn("Sami Khoury can't be booked right now", frozen["reason"])

        free = self.search(self.yoga, "Lea").json()["results"][0]
        self.assertEqual((free["canBook"], free["reason"], free["visiting"]), (True, None, False))
        self.assertFalse(free["flagged"])
        self.assertFalse(free["waiverOnFile"])

        _book(self.lea, self.spin)  # overlaps Yoga
        clashing = self.search(self.yoga, "Lea").json()["results"][0]
        self.assertIn("they can't take two classes", clashing["reason"])

    def test_search_warns_about_a_flagged_member_or_a_missing_waiver_but_allows_booking(self):
        visit = CheckIn.objects.create(member=self.lea, branch="Hamra", result=CheckIn.Result.ALLOWED)
        CheckInFlag.objects.create(check_in=visit, reason=CheckInFlag.Reason.SHARING)
        found = self.search(self.yoga, "Lea").json()["results"][0]
        self.assertEqual((found["flagged"], found["waiverOnFile"], found["canBook"]), (True, False, True))
        Waiver.objects.create(member=self.lea, signature_name="Lea Haddad", health_disclaimer_accepted=True,
                              liability_waiver_accepted=True, waiver_version="1", signed_via=Waiver.SignedVia.ONLINE)
        self.assertTrue(self.search(self.yoga, "Lea").json()["results"][0]["waiverOnFile"])
        self.assertEqual(self.book(self.yoga, self.lea).status_code, 201)

    # --- booking a walk-in ---
    def test_the_desk_books_a_member_who_then_sees_it_in_the_app(self):
        res = self.book(self.yoga, self.lea)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["class"]["spotsLeft"], res.json()["class"]["booked"]), (4, 1))
        self.assertEqual((res.json()["booking"]["memberName"], res.json()["booking"]["bookedBy"]), ("Lea Haddad", "Desk"))

        roster = self.client.get(f"/api/classes/{self.yoga.id}").json()
        self.assertEqual([(r["memberName"], r["bookedBy"]) for r in roster["roster"]], [("Lea Haddad", "Desk")])
        self.assertTrue(roster["canBookMembers"])

        entry = AuditLog.objects.filter(action=AuditLog.Action.CLASS_DESK_BOOKED).latest("id")
        self.assertEqual((entry.actor_name, entry.target_label, entry.branch), ("Desk", "Lea Haddad", "Hamra"))

        _member_login(self.client, "lea")
        upcoming = self.client.get(f"/api/members/me/classes?week={self.tomorrow}").json()["upcoming"]
        self.assertEqual([c["name"] for c in upcoming], ["Yoga"])

    def test_a_self_service_booking_shows_no_receptionist(self):
        _book(self.lea, self.yoga)
        roster = self.client.get(f"/api/classes/{self.yoga.id}").json()["roster"]
        self.assertIsNone(roster[0]["bookedBy"])

    def test_a_full_class_is_full_for_the_desk_too(self):
        self.assertEqual(self.book(self.spin, self.lea).status_code, 201)
        self.assertEqual(self.book(self.spin, self.sami).status_code, 201)
        res = self.book(self.spin, self.nour)
        self.assertEqual(res.status_code, 409)
        self.assertIn("full", res.json()["error"])
        self.assertEqual(ClassBooking.objects.filter(gym_class=self.spin, status="Booked").count(), 2)

    def test_a_member_cannot_be_booked_twice_or_into_overlapping_things(self):
        self.book(self.spin, self.lea)
        res = self.book(self.spin, self.lea)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already has a spot", res.json()["error"])

        res = self.book(self.yoga, self.lea)
        self.assertEqual(res.status_code, 409)
        self.assertIn("already booked into Spinning", res.json()["error"])

        starts_at = self.yoga.starts_at
        PTSession.objects.create(coach=self.hadi, member=self.sami, branch="Hamra", starts_at=starts_at,
                                 ends_at=starts_at + timedelta(hours=1))
        res = self.book(self.yoga, self.sami)
        self.assertEqual(res.status_code, 409)
        self.assertIn("private training session", res.json()["error"])

    def test_only_a_valid_membership_can_be_booked(self):
        for status in (Member.Status.FROZEN, Member.Status.CANCELLED):
            Member.objects.filter(id=self.lea.id).update(status=status)
            res = self.book(self.yoga, self.lea)
            self.assertEqual(res.status_code, 403, status)
            self.assertIn("Lea Haddad can't be booked", res.json()["error"])

        # Paid until today, class tomorrow: renew first.
        Member.objects.filter(id=self.lea.id).update(status=Member.Status.ACTIVE, subscription_expires_at=timezone.localdate())
        res = self.book(self.yoga, self.lea)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Lea Haddad's membership runs until", res.json()["error"])

        # Lapsed yesterday and still marked Active: caught at the desk, not trusted.
        Member.objects.filter(id=self.lea.id).update(subscription_expires_at=_day(-1))
        self.assertEqual(self.book(self.yoga, self.lea).status_code, 403)
        self.assertEqual(Member.objects.get(id=self.lea.id).status, Member.Status.FROZEN)

    def test_only_classes_that_have_not_started_can_be_booked(self):
        running = self.running_class()
        self.assertIn("already started", self.book(running, self.lea).json()["error"])
        past = _class("Pilates", self.rita, _day(-1), capacity=9)
        self.assertEqual(self.book(past, self.lea).status_code, 400)
        self.assertFalse(self.client.get(f"/api/classes/{past.id}").json()["canBookMembers"])
        GymClass.objects.filter(id=self.yoga.id).update(status=GymClass.Status.CANCELLED)
        self.assertIn("cancelled", self.book(self.yoga, self.lea).json()["error"])
        self.assertFalse(self.client.get(f"/api/classes/{self.yoga.id}").json()["canBookMembers"])

    def test_bad_requests(self):
        self.assertEqual(self.book(self.yoga, 999999).status_code, 404)
        res = self.client.post(f"/api/classes/{self.yoga.id}/bookings", {}, content_type="application/json")
        self.assertIn("memberId", res.json()["error"])
        self.assertEqual(self.client.post("/api/classes/999999/bookings", {"memberId": self.lea.id},
                                          content_type="application/json").status_code, 404)

    def test_a_member_visiting_from_another_branch_can_be_booked_at_the_desk(self):
        found = self.search(self.yoga, "Nour").json()["results"][0]
        self.assertEqual((found["visiting"], found["branch"], found["canBook"]), (True, "Jnah", True))
        self.assertEqual(self.book(self.yoga, self.nour).status_code, 201)
        # Booking their own way into another branch's class is still refused.
        _member_login(self.client, "nour")
        self.assertEqual(self.client.post(f"/api/members/me/classes/{self.spin.id}/book").status_code, 403)

    def test_the_desk_stays_on_its_own_branch(self):
        staff_login(self.client, "jnahdesk", PASSWORD)
        self.assertEqual(self.book(self.yoga, self.nour).status_code, 403)
        self.assertEqual(self.search(self.yoga, "Lea").status_code, 403)
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.book(self.yoga, self.nour).status_code, 201)

    def test_only_the_front_desk_can_search_or_book(self):
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.search(self.yoga, "Lea").status_code, 403)
        self.assertEqual(self.book(self.yoga, self.lea).status_code, 403)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.book(self.yoga, self.lea).status_code, 401)
        _member_login(self.client, "lea")  # a member's session isn't a staff one
        self.assertEqual(self.book(self.yoga, self.sami).status_code, 401)

    # --- taking a booking back ---
    def test_removing_a_booking_frees_the_spot_and_tells_the_member(self):
        booking_id = self.book(self.spin, self.lea).json()["booking"]["bookingId"]
        res = self.remove(self.spin, booking_id)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["class"]["spotsLeft"], res.json()["booking"]["status"]), (2, "Cancelled"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CLASS_DESK_BOOKING_REMOVED).exists())
        self.assertEqual(self.remove(self.spin, booking_id).status_code, 404)  # only once
        self.assertEqual(self.book(self.spin, self.lea).status_code, 201)  # they can come back

        _book(self.sami, self.yoga)
        self.remove(self.yoga, ClassBooking.objects.get(member=self.sami, gym_class=self.yoga).id)
        _member_login(self.client, "sami")
        mine = next(c for c in self.client.get(f"/api/members/me/classes?week={self.tomorrow}").json()["classes"]
                    if c["id"] == self.yoga.id)
        self.assertEqual(mine["myBooking"]["cancelReason"], "Removed at the front desk")

    def test_bookings_are_frozen_once_a_class_starts(self):
        running = self.running_class()
        booking = _book(self.lea, running)
        res = self.remove(running, booking.id)
        self.assertEqual(res.status_code, 409)
        self.assertIn("already started", res.json()["error"])
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Booked")

    def test_a_booking_can_only_be_removed_through_its_own_class_and_branch(self):
        booking = _book(self.lea, self.yoga)
        self.assertEqual(self.remove(self.spin, booking.id).status_code, 404)
        staff_login(self.client, "jnahdesk", PASSWORD)
        self.assertEqual(self.remove(self.yoga, booking.id).status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "Booked")

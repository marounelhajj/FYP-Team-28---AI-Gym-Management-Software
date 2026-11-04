from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from training.models import TrainingEvent

from . import rules
from .models import ClassBooking, ClassType, GymClass
from .tests import PASSWORD, _coach, _member, _member_login, _staff


def _class_at(coach, starts_at, minutes=60, branch="Hamra", status=GymClass.Status.SCHEDULED):
    class_type, _ = ClassType.objects.get_or_create(branch=branch, name="Spinning", defaults={"max_capacity": 20})
    return GymClass.objects.create(
        name="Spinning", class_type=class_type, coach=coach, branch=branch, capacity=10, status=status,
        starts_at=starts_at, ends_at=starts_at + timedelta(minutes=minutes),
    )


# User story (SCRUM-36): "As a coach, I want to mark attendance for my classes,
# so that the system keeps accurate participation records."
class ClassAttendanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.coach = _coach("hadi")
        cls.other_coach = _coach("rita")
        cls.bm = _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.jnah_bm = _staff("jbm", ["manage_class_schedule", "manage_members"], branch="Jnah")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.walkin = _member("Nour Walk", "nour")

        now = timezone.now()
        cls.running = _class_at(cls.coach, now - timedelta(minutes=20))
        cls.lea_booking = ClassBooking.objects.create(member=cls.lea, gym_class=cls.running)
        cls.sami_booking = ClassBooking.objects.create(member=cls.sami, gym_class=cls.running)
        cls.future = _class_at(cls.coach, now + timedelta(hours=3))
        ClassBooking.objects.create(member=cls.lea, gym_class=cls.future)
        cls.recent = _class_at(cls.coach, now - timedelta(hours=24))  # ended 23h ago
        cls.recent_booking = ClassBooking.objects.create(member=cls.lea, gym_class=cls.recent)
        cls.old = _class_at(cls.coach, now - timedelta(hours=26))  # ended 25h ago
        cls.old_booking = ClassBooking.objects.create(member=cls.lea, gym_class=cls.old)

    def login(self, username):
        staff_login(self.client, username, PASSWORD)

    def mark(self, gym_class, booking, outcome):
        return self.client.post(
            f"/api/classes/{gym_class.id}/attendance", {"bookingId": booking.id, "attendance": outcome},
            content_type="application/json",
        )

    def walk_in(self, gym_class, member_id):
        return self.client.post(
            f"/api/classes/{gym_class.id}/attendance/walk-ins", {"memberId": member_id}, content_type="application/json",
        )

    def events(self, event_type):
        return TrainingEvent.objects.filter(event_type=event_type)

    # --- marking ----------------------------------------------------------

    def test_coach_sees_the_booked_members_of_their_class(self):
        self.login("hadi")
        res = self.client.get(f"/api/classes/{self.running.id}/attendance")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual([e["memberName"] for e in body["roster"]], ["Lea Haddad", "Sami Khoury"])
        self.assertTrue(body["canMark"])
        self.assertEqual(body["counts"]["unmarked"], 2)

    def test_cancelled_bookings_are_not_on_the_roster(self):
        ClassBooking.objects.filter(pk=self.sami_booking.pk).update(status=ClassBooking.Status.CANCELLED)
        self.login("hadi")
        roster = self.client.get(f"/api/classes/{self.running.id}/attendance").json()["roster"]
        self.assertEqual([e["memberName"] for e in roster], ["Lea Haddad"])

    def test_coach_marks_attended_and_no_show(self):
        self.login("hadi")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 200)
        res = self.mark(self.running, self.sami_booking, "No-show")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["counts"], {"booked": 2, "walkIns": 0, "attended": 1, "noShows": 1, "unmarked": 0})

        self.lea_booking.refresh_from_db()
        self.assertEqual(self.lea_booking.attendance, "Attended")
        self.assertEqual(self.lea_booking.attendance_marked_by, self.coach)
        self.assertIsNotNone(self.lea_booking.attendance_marked_at)

    def test_rejects_an_unknown_outcome_or_booking(self):
        self.login("hadi")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Late").status_code, 400)
        res = self.client.post(f"/api/classes/{self.running.id}/attendance", {"bookingId": 999999, "attendance": "Attended"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 404)

    def test_a_coach_can_add_a_walk_in(self):
        self.login("hadi")
        res = self.walk_in(self.running, self.walkin.id)
        self.assertEqual(res.status_code, 201, res.content)
        booking = ClassBooking.objects.get(gym_class=self.running, member=self.walkin)
        self.assertTrue(booking.walk_in)
        self.assertEqual(booking.attendance, "Attended")
        self.assertEqual(res.json()["counts"]["walkIns"], 1)

    def test_walk_in_of_someone_already_booked_just_marks_them(self):
        self.login("hadi")
        self.assertEqual(self.walk_in(self.running, self.lea.id).status_code, 201)
        self.assertEqual(ClassBooking.objects.filter(gym_class=self.running, member=self.lea).count(), 1)
        self.lea_booking.refresh_from_db()
        self.assertEqual(self.lea_booking.attendance, "Attended")
        self.assertFalse(self.lea_booking.walk_in)

    def test_walk_in_needs_a_real_member(self):
        self.login("hadi")
        self.assertEqual(self.walk_in(self.running, 999999).status_code, 400)
        self.assertEqual(self.walk_in(self.running, "abc").status_code, 400)

    def test_a_hand_mark_is_never_overwritten_by_the_automatic_settling(self):
        self.login("hadi")
        self.mark(self.running, self.lea_booking, "No-show")
        rules.settle_attendance(now=self.running.ends_at + timedelta(minutes=5))
        self.lea_booking.refresh_from_db()
        self.assertEqual(self.lea_booking.attendance, "No-show")
        self.assertEqual(self.events("no_show").filter(session_id=str(self.lea_booking.id)).count(), 1)

    # --- who may mark -----------------------------------------------------

    def test_another_coach_cannot_take_attendance(self):
        self.login("rita")
        self.assertEqual(self.client.get(f"/api/classes/{self.running.id}/attendance").status_code, 403)
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 403)
        self.assertEqual(self.walk_in(self.running, self.walkin.id).status_code, 403)

    def test_front_desk_cannot_take_attendance(self):
        self.login("desk")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 403)

    def test_a_member_cannot_take_attendance(self):
        _member_login(self.client, "lea")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 401)

    def test_branch_manager_can_mark_any_class_at_their_branch(self):
        self.login("bm")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 200)
        self.lea_booking.refresh_from_db()
        self.assertEqual(self.lea_booking.attendance_marked_by, self.bm)

    def test_branch_manager_of_another_branch_cannot(self):
        self.login("jbm")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 403)

    # --- the window -------------------------------------------------------

    def test_nobody_marks_a_class_that_has_not_started(self):
        booking = self.future.bookings.get()
        self.login("hadi")
        res = self.mark(self.future, booking, "Attended")
        self.assertEqual(res.status_code, 409)
        self.assertFalse(self.client.get(f"/api/classes/{self.future.id}/attendance").json()["canMark"])

    def test_nobody_marks_a_cancelled_class(self):
        GymClass.objects.filter(pk=self.running.pk).update(status=GymClass.Status.CANCELLED)
        self.login("bm")
        self.assertEqual(self.mark(self.running, self.lea_booking, "Attended").status_code, 409)

    def test_coach_can_mark_until_24_hours_after_the_class_ends(self):
        self.login("hadi")
        self.assertEqual(self.mark(self.recent, self.recent_booking, "Attended").status_code, 200)

    def test_after_24_hours_only_a_branch_manager_can_change_it(self):
        self.login("hadi")
        res = self.mark(self.old, self.old_booking, "Attended")
        self.assertEqual(res.status_code, 403)
        self.assertIn("24 hours", res.json()["error"])
        self.assertEqual(self.walk_in(self.old, self.walkin.id).status_code, 403)
        self.assertFalse(self.client.get(f"/api/classes/{self.old.id}/attendance").json()["canMark"])

        self.client.post("/api/auth/logout")
        self.login("bm")
        self.assertEqual(self.mark(self.old, self.old_booking, "Attended").status_code, 200)

    # --- training data (SCRUM-73) -----------------------------------------

    def test_marks_are_written_to_the_training_log(self):
        self.login("hadi")
        self.mark(self.running, self.lea_booking, "Attended")
        self.mark(self.running, self.sami_booking, "No-show")

        attended = self.events("attended").get()
        self.assertEqual(attended.member, self.lea)
        self.assertEqual(attended.trainer, self.coach)
        self.assertEqual(attended.session_id, str(self.lea_booking.id))
        self.assertEqual(attended.payload["source"], "manual")
        no_show = self.events("no_show").get()
        self.assertEqual(no_show.member, self.sami)
        self.assertEqual(no_show.branch, "Hamra")

    def test_marking_the_same_outcome_twice_logs_it_once(self):
        self.login("hadi")
        self.mark(self.running, self.lea_booking, "Attended")
        self.mark(self.running, self.lea_booking, "Attended")
        self.assertEqual(self.events("attended").count(), 1)

    def test_a_correction_logs_the_new_outcome(self):
        self.login("hadi")
        self.mark(self.running, self.lea_booking, "No-show")
        self.mark(self.running, self.lea_booking, "Attended")
        self.assertEqual(self.events("no_show").count(), 1)
        self.assertEqual(self.events("attended").count(), 1)

    def test_a_walk_in_is_logged_as_attended(self):
        self.login("hadi")
        self.walk_in(self.running, self.walkin.id)
        event = self.events("attended").get()
        self.assertEqual(event.member, self.walkin)
        self.assertTrue(event.payload["walkIn"])

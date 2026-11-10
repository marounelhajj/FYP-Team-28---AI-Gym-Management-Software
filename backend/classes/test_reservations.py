from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login

from .models import ClassBooking, GymClass, WaitlistEntry
from .tests import PASSWORD, _class, _coach, _day, _member, _staff

GM = ["view_class_reservations", "view_all_branches", "view_financial_reports"]


def _book(gym_class, *members, attendance=""):
    for m in members:
        ClassBooking.objects.create(gym_class=gym_class, member=m, attendance=attendance)


class ClassReservationsTests(TestCase):
    def setUp(self):
        self.gm = _staff("rhaddad", GM, job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        self.bm = _staff("kabboud", ["manage_class_schedule", "manage_members"], branch="Hamra")
        coach, jnah_coach = _coach("hnasser"), _coach("lmansour", branch="Jnah")
        self.members = [_member(f"Member {i}", f"m{i}") for i in range(6)]
        # Next week (always in the future, whatever the day today): at Hamra
        # a full yoga with a waitlist, a half-empty spin and a cancelled
        # class; one class at Jnah. Last week (always over): a yoga with
        # attendance settled. The week after next has one more class.
        today = timezone.localdate()
        self.monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        start = (self.monday - today).days
        self.week = f"?branch=Hamra&week={self.monday.isoformat()}"

        self.yoga = _class("Yoga", coach, _day(start + 2), capacity=3)
        _book(self.yoga, *self.members[:3])
        WaitlistEntry.objects.create(gym_class=self.yoga, member=self.members[3])
        self.spin = _class("Spin", coach, _day(start + 2), start="19:30", capacity=4)
        _book(self.spin, *self.members[:2])
        cancelled = _class("Boxing", coach, _day(start + 3), start="07:00", capacity=10)
        cancelled.status = GymClass.Status.CANCELLED
        cancelled.save()
        _book(_class("Pilates", jnah_coach, _day(start + 2), branch="Jnah", capacity=10), self.members[4])
        _class("Spin", coach, _day(start + 7), capacity=10)

        self.past = _class("Yoga", coach, _day(start - 12), start="06:00", capacity=3)
        _book(self.past, *self.members[:2], attendance=ClassBooking.Attendance.ATTENDED)
        _book(self.past, self.members[2], attendance=ClassBooking.Attendance.NO_SHOW)

    def get(self, query=""):
        return self.client.get(f"/api/classes/reservations{query}")

    def test_general_manager_sees_a_branch_week(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get(self.week).json()
        self.assertEqual(body["branch"], "Hamra")
        self.assertTrue(body["canSeeAllBranches"])
        self.assertEqual([c["name"] for c in body["classes"]], ["Yoga", "Spin", "Boxing"])
        yoga = body["classes"][0]
        self.assertEqual((yoga["booked"], yoga["capacity"], yoga["fillPercent"], yoga["waitlistCount"], yoga["ended"]),
                         (3, 3, 100, 1, False))

    def test_week_totals_leave_out_cancelled_classes(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        summary = self.get(self.week).json()["summary"]
        self.assertEqual(summary, {
            "classes": 2, "cancelled": 1, "spots": 7, "booked": 5, "fillPercent": 71, "waitlisted": 1,
            "fullClasses": 1, "attended": 0, "noShows": 0, "attendancePercent": None,
        })

    def test_attendance_is_counted_once_classes_are_over(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get(f"?branch=Hamra&week={(self.monday - timedelta(days=14)).isoformat()}").json()
        past = body["classes"][0]
        self.assertEqual((past["id"], past["attended"], past["noShows"], past["ended"]), (self.past.id, 2, 1, True))
        self.assertEqual((body["summary"]["attended"], body["summary"]["attendancePercent"]), (2, 67))

    def test_totals_per_class_type_busiest_first(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        types = self.get(self.week).json()["byClassType"]
        self.assertEqual([(t["name"], t["classes"], t["booked"], t["fillPercent"]) for t in types],
                         [("Yoga", 1, 3, 100), ("Spin", 1, 2, 50), ("Boxing", 0, 0, None)])

    def test_every_branch_is_summarized_for_comparison(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get(self.week).json()
        by_branch = {b["branch"]: b for b in body["branchSummaries"]}
        self.assertEqual(set(by_branch), set(body["branches"]))
        self.assertEqual((by_branch["Hamra"]["booked"], by_branch["Jnah"]["booked"]), (5, 1))
        self.assertEqual(by_branch["Jnah"]["fillPercent"], 10)
        jnah = self.get(f"?branch=Jnah&week={self.monday.isoformat()}").json()
        self.assertEqual([c["name"] for c in jnah["classes"]], ["Pilates"])

    def test_each_week_is_separate(self):
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get(f"?branch=Hamra&week={(self.monday + timedelta(days=7)).isoformat()}").json()
        self.assertEqual([c["name"] for c in body["classes"]], ["Spin"])
        self.assertEqual(body["summary"]["fillPercent"], 0)

    def test_branch_manager_is_held_to_their_branch(self):
        staff_login(self.client, "kabboud", PASSWORD)
        body = self.get().json()
        self.assertEqual((body["branch"], body["branches"], body["canSeeAllBranches"]), ("Hamra", ["Hamra"], False))
        self.assertEqual([b["branch"] for b in body["branchSummaries"]], ["Hamra"])
        self.assertEqual(self.get("?branch=Jnah").status_code, 403)

    def test_roles_without_the_permission_are_refused(self):
        _staff("dsarkis", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff_login(self.client, "dsarkis", PASSWORD)
        self.assertEqual(self.get().status_code, 403)
        self.client.post("/api/auth/logout")
        _coach("raoun")
        staff_login(self.client, "raoun", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_requires_a_staff_session_and_valid_input(self):
        self.assertEqual(self.get().status_code, 401)
        staff_login(self.client, "rhaddad", PASSWORD)
        self.assertEqual(self.get("?branch=Nowhere").status_code, 400)
        self.assertEqual(self.get("?week=soon").status_code, 400)

    def test_seeded_general_manager_role_has_the_permission(self):
        from administration.management.commands.seed_staff import ROLES

        gm = next(r for r in ROLES if r["name"] == "General Manager")
        self.assertIn("view_class_reservations", gm["permissions"])

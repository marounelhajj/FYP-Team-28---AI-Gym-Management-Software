from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from classes.models import ClassBooking, PTSession
from classes.tests import PASSWORD, _class, _coach, _day, _member
from members import privacy

from .models import CoachFeedback
from .views import WINDOW_DAYS


def _attended(gym_class, member, attendance=ClassBooking.Attendance.ATTENDED):
    return ClassBooking.objects.create(gym_class=gym_class, member=member, attendance=attendance)


def _pt(coach, member, day_offset, attendance=ClassBooking.Attendance.ATTENDED):
    starts_at = timezone.now().replace(microsecond=0) + timedelta(days=day_offset)
    return PTSession.objects.create(coach=coach, member=member, branch="Hamra", starts_at=starts_at,
                                    ends_at=starts_at + timedelta(hours=1), attendance=attendance)


class MemberFeedbackTests(TestCase):
    def setUp(self):
        self.coach = _coach("hnasser")
        self.member = _member("Lina Haddad", "lina")
        self.other = _member("Sami Khoury", "sami")
        self.yoga = _class("Yoga", self.coach, _day(-2))
        self.booking = _attended(self.yoga, self.member)
        self.login(self.member)

    def login(self, member):
        self.client.post("/api/members/login", {"username": member.username, "password": PASSWORD},
                         content_type="application/json")

    def rate(self, kind="class", session_id=None, rating=5, comment="Great class"):
        body = {"kind": kind, "sessionId": self.yoga.id if session_id is None else session_id, "rating": rating}
        if comment is not None:
            body["comment"] = comment
        return self.client.post("/api/members/me/feedback", body, content_type="application/json")

    def test_attended_class_is_listed_to_rate(self):
        body = self.client.get("/api/members/me/feedback").json()
        self.assertEqual(body["windowDays"], WINDOW_DAYS)
        self.assertEqual([(s["kind"], s["sessionId"], s["coach"]["name"]) for s in body["toRate"]],
                         [("class", self.yoga.id, self.coach.full_name)])
        self.assertEqual(body["given"], [])

    def test_member_rates_a_class_they_attended(self):
        res = self.rate(rating=4, comment="  Good pace, a bit crowded  ")
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual((body["rating"], body["comment"], body["coachName"]), (4, "Good pace, a bit crowded", "Hnasser"))
        self.assertTrue(body["editable"])

        feedback = CoachFeedback.objects.get()
        self.assertEqual((feedback.coach, feedback.class_booking, feedback.session_name), (self.coach, self.booking, "Yoga"))
        listing = self.client.get("/api/members/me/feedback").json()
        self.assertEqual(listing["toRate"], [])
        self.assertEqual([g["id"] for g in listing["given"]], [feedback.id])

    def test_comment_is_optional(self):
        self.assertEqual(self.rate(comment=None).status_code, 201)
        self.assertEqual(CoachFeedback.objects.get().comment, "")

    def test_member_rates_a_private_session(self):
        session = _pt(self.coach, self.member, -1)
        res = self.rate(kind="pt", session_id=session.id, rating=5)
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["name"], "Private training")
        self.assertEqual(CoachFeedback.objects.get().pt_session, session)

    def test_cannot_rate_the_same_session_twice(self):
        self.rate()
        res = self.rate(rating=1)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(CoachFeedback.objects.get().rating, 5)

    def test_cannot_rate_a_no_show_or_unattended_session(self):
        self.booking.attendance = ClassBooking.Attendance.NO_SHOW
        self.booking.save()
        self.assertEqual(self.rate().status_code, 404)

        # Never checked in, so settling attendance marks it a no-show.
        spin = _class("Spin", self.coach, _day(-1))
        _attended(spin, self.member, attendance="")
        self.assertEqual(self.rate(session_id=spin.id).status_code, 404)
        self.assertEqual(ClassBooking.objects.get(gym_class=spin).attendance, ClassBooking.Attendance.NO_SHOW)

    def test_cannot_rate_a_session_that_has_not_happened(self):
        later = _class("Pilates", self.coach, _day(2))
        _attended(later, self.member)
        self.assertEqual(self.rate(session_id=later.id).status_code, 404)

    def test_cannot_rate_after_the_window_closes(self):
        old = _class("Boxing", self.coach, _day(-WINDOW_DAYS - 1))
        _attended(old, self.member)
        self.assertEqual(self.rate(session_id=old.id).status_code, 404)
        self.assertNotIn(old.id, [s["sessionId"] for s in self.client.get("/api/members/me/feedback").json()["toRate"]])

    def test_cannot_rate_someone_elses_session(self):
        session = _pt(self.coach, self.other, -1)
        self.assertEqual(self.rate(kind="pt", session_id=session.id).status_code, 404)

    def test_rating_is_validated(self):
        for rating in (0, 6, "5", True, None):
            self.assertEqual(self.rate(rating=rating).status_code, 400, rating)
        self.assertEqual(self.rate(comment="x" * 501).status_code, 400)
        self.assertEqual(self.rate(kind="gym").status_code, 400)
        self.assertFalse(CoachFeedback.objects.exists())

    def test_member_can_edit_within_the_window(self):
        feedback_id = self.rate(rating=3).json()["id"]
        res = self.client.patch(f"/api/members/me/feedback/{feedback_id}", {"rating": 5, "comment": "Grew on me"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.json()["rating"], res.json()["comment"]), (5, "Grew on me"))

    def test_rating_is_final_after_the_window(self):
        feedback_id = self.rate().json()["id"]
        CoachFeedback.objects.filter(pk=feedback_id).update(
            session_ends_at=timezone.now() - timedelta(days=WINDOW_DAYS + 1),
        )
        res = self.client.patch(f"/api/members/me/feedback/{feedback_id}", {"rating": 1},
                                content_type="application/json")
        self.assertEqual(res.status_code, 409)
        self.assertFalse(self.client.get("/api/members/me/feedback").json()["given"][0]["editable"])

    def test_member_cannot_edit_someone_elses_rating(self):
        feedback_id = self.rate().json()["id"]
        self.client.post("/api/members/logout")
        self.login(self.other)
        res = self.client.patch(f"/api/members/me/feedback/{feedback_id}", {"rating": 1},
                                content_type="application/json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(CoachFeedback.objects.get().rating, 5)

    def test_requires_a_member_session(self):
        self.client.post("/api/members/logout")
        self.assertEqual(self.client.get("/api/members/me/feedback").status_code, 401)
        self.assertEqual(self.rate().status_code, 401)

    def test_export_includes_ratings_and_deletion_erases_the_comment(self):
        self.rate(rating=4, comment="Loved it")
        exported = privacy.build_export(self.member)["coachFeedback"]
        self.assertEqual([(f["rating"], f["comment"], f["session"]) for f in exported], [(4, "Loved it", "Yoga")])

        privacy.anonymize_member(self.member)
        feedback = CoachFeedback.objects.get()
        self.assertEqual((feedback.rating, feedback.comment), (4, ""))

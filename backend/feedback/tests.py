from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from classes.models import ClassBooking, PTSession
from classes.tests import PASSWORD, _class, _coach, _day, _member, _staff
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


def _feedback(member, gym_class, rating, comment="", days_ago=1):
    booking = _attended(gym_class, member)
    feedback = CoachFeedback.objects.create(
        member=member, coach=gym_class.coach, class_booking=booking, branch=gym_class.branch,
        session_name=gym_class.name, session_starts_at=gym_class.starts_at, session_ends_at=gym_class.ends_at,
        rating=rating, comment=comment,
    )
    CoachFeedback.objects.filter(pk=feedback.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    return feedback


class CoachRatingsTests(TestCase):
    def setUp(self):
        self.coach = _coach("hnasser")
        self.other_coach = _coach("raoun")
        self.lina = _member("Lina Haddad", "lina")
        self.sami = _member("Sami Khoury", "sami")
        yoga, spin = _class("Yoga", self.coach, _day(-2)), _class("Spin", self.coach, _day(-1), start="19:00")
        _feedback(self.lina, yoga, 5, "Loved the flow", days_ago=2)
        _feedback(self.sami, yoga, 3, days_ago=40)
        _feedback(self.lina, spin, 4, "Music too loud")
        _feedback(self.sami, _class("Boxing", self.other_coach, _day(-1)), 1, "Not for me")

    def get(self, query=""):
        return self.client.get(f"/api/feedback/me{query}")

    def test_coach_sees_only_their_own_ratings(self):
        staff_login(self.client, "hnasser", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["coach"]["name"], self.coach.full_name)
        self.assertEqual([r["sessionName"] for r in body["results"]], ["Spin", "Yoga", "Yoga"])
        self.assertNotIn("Not for me", [r["comment"] for r in body["results"]])
        self.assertEqual(body["results"][0]["memberName"], "Lina Haddad")

    def test_summary_counts_stars_and_recent_average(self):
        staff_login(self.client, "hnasser", PASSWORD)
        summary = self.get().json()["summary"]
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["average"], 4.0)
        self.assertEqual(summary["stars"], {"5": 1, "4": 1, "3": 1, "2": 0, "1": 0})
        self.assertEqual(summary["recent"], {"days": 30, "count": 2, "average": 4.5})

    def test_average_per_session(self):
        staff_login(self.client, "hnasser", PASSWORD)
        by_session = self.get().json()["bySession"]
        self.assertEqual(by_session, [{"name": "Yoga", "count": 2, "average": 4.0},
                                      {"name": "Spin", "count": 1, "average": 4.0}])

    def test_filters_narrow_the_list_not_the_summary(self):
        staff_login(self.client, "hnasser", PASSWORD)
        body = self.get("?rating=5").json()
        self.assertEqual([r["rating"] for r in body["results"]], [5])
        self.assertEqual((body["matching"], body["summary"]["count"]), (1, 3))
        with_comments = self.get("?withComments=1").json()["results"]
        self.assertEqual([r["comment"] for r in with_comments], ["Music too loud", "Loved the flow"])
        self.assertEqual(self.get("?rating=9").status_code, 400)

    def test_coach_with_no_ratings_gets_an_empty_summary(self):
        _coach("omar")
        staff_login(self.client, "omar", PASSWORD)
        body = self.get().json()
        self.assertEqual((body["summary"]["count"], body["summary"]["average"], body["results"]), (0, None, []))

    def test_other_staff_do_not_see_coaches_ratings(self):
        _staff("kabboud", ["manage_class_schedule", "manage_members"], branch="Hamra")
        staff_login(self.client, "kabboud", PASSWORD)
        self.assertEqual(self.get().json()["results"], [])

    def test_requires_a_staff_session(self):
        self.assertEqual(self.get().status_code, 401)
        self.client.post("/api/members/login", {"username": "lina", "password": PASSWORD},
                         content_type="application/json")
        self.assertEqual(self.get().status_code, 401)

    def test_deleted_members_ratings_stay_anonymized(self):
        privacy.anonymize_member(self.lina)
        staff_login(self.client, "hnasser", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["summary"]["count"], 3)
        lina_rows = [r for r in body["results"] if r["rating"] in (4, 5)]
        self.assertTrue(all(r["comment"] == "" and r["memberName"] != "Lina Haddad" for r in lina_rows))


# User story: "As a general manager, I want to view personal trainer
# ratings by branch, so that I can inform staffing, coaching, and
# incentive decisions."
class RatingsByBranchTests(TestCase):
    def setUp(self):
        self.hadi = _coach("hadi", branch="Hamra")
        self.rita = _coach("rita", branch="Hamra")
        self.lara = _coach("lara", branch="Jnah")
        self.lina = _member("Lina Haddad", "lina")
        self.sami = _member("Sami Khoury", "sami")
        _feedback(self.lina, _class("Yoga", self.hadi, _day(-2), branch="Hamra"), 5)
        _feedback(self.sami, _class("Spin", self.hadi, _day(-1), branch="Hamra"), 3)
        _feedback(self.lina, _class("Boxing", self.rita, _day(-3), branch="Hamra"), 4)
        _feedback(self.sami, _class("Pilates", self.lara, _day(-1), branch="Jnah"), 2)

    def get(self, query=""):
        return self.client.get(f"/api/feedback/report{query}")

    def gm(self):
        return _staff("rhaddad", ["view_coach_ratings"], branch=None, job_title=StaffAccount.JobTitle.GENERAL_MANAGER)

    def test_requires_authentication(self):
        self.assertEqual(self.get().status_code, 401)

    def test_requires_the_permission(self):
        _staff("kabboud", ["manage_class_schedule", "manage_members"], branch="Hamra")
        staff_login(self.client, "kabboud", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_every_branch_is_listed_even_with_no_ratings(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get().json()
        self.assertEqual([b["branch"] for b in body["branches"]], ["Hamra", "Achrafieh", "Jnah", "Zalka"])
        achrafieh = next(b for b in body["branches"] if b["branch"] == "Achrafieh")
        self.assertEqual((achrafieh["count"], achrafieh["average"], achrafieh["coaches"]), (0, None, []))

    def test_branch_totals_and_star_breakdown(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        hamra = next(b for b in self.get().json()["branches"] if b["branch"] == "Hamra")
        self.assertEqual(hamra["count"], 3)
        self.assertEqual(hamra["average"], 4.0)
        self.assertEqual(hamra["stars"], {"5": 1, "4": 1, "3": 1, "2": 0, "1": 0})

    def test_coaches_within_a_branch_are_ranked_by_average(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        hamra = next(b for b in self.get().json()["branches"] if b["branch"] == "Hamra")
        self.assertEqual(
            [(c["name"], c["count"], c["average"]) for c in hamra["coaches"]],
            [("Hadi", 2, 4.0), ("Rita", 1, 4.0)],
        )  # tied average, so the richer sample (more ratings) sorts first

    def test_narrowing_to_one_branch(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        body = self.get("?branch=Jnah").json()
        self.assertEqual([b["branch"] for b in body["branches"]], ["Jnah"])
        self.assertEqual(body["totals"], {"count": 1, "average": 2.0})

    def test_invalid_branch_is_rejected(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        self.assertEqual(self.get("?branch=Nowhere").status_code, 400)

    def test_totals_combine_every_branch(self):
        self.gm()
        staff_login(self.client, "rhaddad", PASSWORD)
        self.assertEqual(self.get().json()["totals"], {"count": 4, "average": 3.5})

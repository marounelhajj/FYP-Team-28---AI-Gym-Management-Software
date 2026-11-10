import re
from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from administration.testing import staff_login

from . import config
from .features import live_history
from .reasons import explain
from .scoring import rule_score, score_members
from .testing import PASSWORD, froze, member, payment, regular, staff, visits

AS_OF = date(2026, 11, 10)
BASE = {
    "visits_recent": 4, "visits_prior": 24, "recent_per_week": 1.0, "prior_per_week": 3.0,
    "last_visit": "2026-11-08", "days_since_last_visit": 2, "no_shows": 0, "lapsed": False,
    "lapsed_since": None, "late_payments": 0, "last_late_payment": None, "last_late_days": None,
    "freeze_active": False, "past_freezes": 0, "last_freeze": None, "tenure_days": 400,
    "membership_ends": "2026-12-20", "days_to_renewal": 40,
}


def one(feature, **changes):
    [reason] = explain([{"feature": feature, "points": 10}], {**BASE, **changes}, AS_OF)
    return reason


# User story (SCRUM-119): "As a branch manager, I want each at-risk member to
# show the two or three reasons behind their ranking, so that staff know
# what to talk about on the call."
#
# AC: shown in plain language, not raw scores - one sentence per reason type,
# with the member's real numbers.
class PlainLanguageTests(SimpleTestCase):
    def test_attendance_change(self):
        self.assertEqual(one("attendance_drop")["text"], "Visits dropped from 3 a week to 1 a week")
        self.assertEqual(
            one("attendance_drop", recent_per_week=0.0, prior_per_week=2.5)["text"],
            "Visits dropped from 2.5 a week to none in the last 4 weeks",
        )

    def test_inactivity(self):
        self.assertEqual(
            one("inactivity", days_since_last_visit=23, last_visit="2026-10-18")["text"],
            "Hasn't visited in 23 days (last visit 18 Oct)",
        )
        self.assertEqual(one("inactivity", days_since_last_visit=None, last_visit=None)["text"],
                         "Hasn't checked in once since joining")

    def test_missed_sessions(self):
        self.assertEqual(one("no_shows", no_shows=2)["text"], "Missed 2 booked classes or sessions in the last 30 days")
        self.assertEqual(one("no_shows", no_shows=1)["text"], "Missed 1 booked class or session in the last 30 days")

    def test_failed_or_late_payments(self):
        self.assertEqual(one("payment", lapsed=True, lapsed_since="2026-11-04")["text"],
                         "Membership payment overdue since 4 Nov")
        self.assertEqual(
            one("payment", late_payments=1, last_late_payment="2026-10-12", last_late_days=9)["text"],
            "Last renewal was paid 9 days late, on 12 Oct",
        )
        self.assertEqual(
            one("payment", late_payments=2, last_late_payment="2026-10-12", last_late_days=9)["text"],
            "Last renewal was paid 9 days late, on 12 Oct (2 late payments in 6 months)",
        )

    def test_freeze(self):
        self.assertEqual(one("freeze", freeze_active=True, last_freeze="2026-10-27", past_freezes=1)["text"],
                         "Membership frozen since 27 Oct")
        self.assertEqual(one("freeze", past_freezes=1, last_freeze="2026-07-14")["text"],
                         "Froze their membership on 14 Jul")

    def test_tenure(self):
        self.assertEqual(one("new_member", tenure_days=42)["text"], "Joined 6 weeks ago")
        self.assertEqual(one("new_member", tenure_days=10)["text"], "Joined 10 days ago")

    def test_renewal(self):
        self.assertEqual(one("renewal_soon", days_to_renewal=12, membership_ends="2026-11-22")["text"],
                         "Membership ends in 12 days (22 Nov)")
        self.assertEqual(one("renewal_soon", days_to_renewal=0, membership_ends="2026-11-10")["text"],
                         "Membership ends today")

    def test_dates_in_another_year_show_the_year(self):
        self.assertEqual(one("freeze", past_freezes=1, last_freeze="2025-12-30")["text"],
                         "Froze their membership on 30 Dec 2025")

    def test_every_reason_has_a_short_talking_point_and_no_internal_names(self):
        for feature in config.RULE_WEIGHTS:
            reason = one(feature, no_shows=2, lapsed=True, lapsed_since="2026-11-04", last_freeze="2026-10-01",
                         freeze_active=True, past_freezes=1, days_to_renewal=12, tenure_days=42)
            self.assertTrue(reason["talkingPoint"].endswith("."), feature)
            self.assertLess(len(reason["talkingPoint"]), 120, feature)
            for text in reason.values():
                self.assertNotIn("_", text)
                self.assertNotIn("score", text.lower())
                self.assertNotIn("points", text.lower())

    def test_unknown_or_incomplete_reasons_are_skipped(self):
        self.assertEqual(explain([{"feature": "mystery", "points": 9}], BASE, AS_OF), [])
        self.assertEqual(explain([{"feature": "no_shows", "points": 9}], {}, AS_OF), [])


# The right two or three reasons come out for crafted members.
class TopReasonTests(TestCase):
    def reasons_for(self, m):
        return {member_id: [r["feature"] for r in reasons] for member_id, _, reasons in score_members("Hamra")}[m.pk]

    def test_dropping_visits_and_renewal_soon(self):
        m = member("Rana Fading", expires_in=12)
        regular(m, per_week=3, recent_per_week=1)
        self.assertEqual(self.reasons_for(m)[:2], ["attendance_drop", "renewal_soon"])

    def test_lapsed_payment_and_inactivity(self):
        m = member("Mira Lapsed", expires_in=-9)
        regular(m, per_week=3, skip_recent_weeks=4)
        reasons = self.reasons_for(m)
        self.assertEqual(set(reasons), {"attendance_drop", "inactivity", "payment"})

    def test_new_member_who_has_not_come_in(self):
        m = member("Yara New", joined_days_ago=20)
        reasons = self.reasons_for(m)
        self.assertEqual(reasons[0], "inactivity")
        self.assertIn("new_member", reasons)

    def test_frozen_member(self):
        m = member("Elie Frozen", status="Frozen")
        regular(m, per_week=3, skip_recent_weeks=2)
        froze(m, 15)
        self.assertIn("freeze", self.reasons_for(m))

    def test_late_payer(self):
        today = timezone.localdate()
        m = member("Walid Late", expires_in=20)
        regular(m, per_week=3)
        payment(m, 70, -40)
        payment(m, 30, 20)  # paid 10 days after the previous expiry
        f = live_history("Hamra").features(m.pk, today, live=True)
        self.assertEqual(f.late_payments, 1)
        self.assertEqual(f.last_late_days, 10)
        _, reasons = rule_score(f.as_dict())
        self.assertIn("payment", [r["feature"] for r in reasons])

    def test_at_most_three_reasons_and_none_for_a_healthy_member(self):
        healthy = member("Hala Healthy")
        regular(healthy, per_week=3)
        self.assertEqual(self.reasons_for(healthy), [])
        busy = member("Many Problems", expires_in=-3, joined_days_ago=60)
        visits(busy, [50, 45, 40])
        self.assertLessEqual(len(self.reasons_for(busy)), 3)


class ReasonsApiTests(TestCase):
    def test_list_shows_sentences_and_talking_points_only(self):
        staff("hamrabm", ["view_at_risk_members"], branch="Hamra")
        m = member("Rana Fading", expires_in=12)
        regular(m, per_week=3, recent_per_week=1)
        staff_login(self.client, "hamrabm", PASSWORD)
        row = self.client.get("/api/churn/at-risk").json()["members"][0]
        self.assertEqual(row["reasons"][0]["text"], "Visits dropped from 3 a week to 1 a week")
        ends = timezone.localdate() + timedelta(days=12)
        self.assertIn(f"Membership ends in 12 days ({ends.day} {ends:%b}", row["reasons"][1]["text"])
        for reason in row["reasons"]:
            self.assertEqual(set(reason), {"text", "talkingPoint"})
            self.assertIsNone(re.search(r"attendance_drop|renewal_soon|points", str(reason)))

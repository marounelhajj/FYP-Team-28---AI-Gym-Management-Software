from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from classes.models import ClassBooking, GymClass, PTSession
from classes.rules import local_datetime
from classes.tests import PASSWORD, _book, _class, _coach, _member, _member_login, _staff
from notifications.models import StaffNotification

from . import pay
from .models import CoachPayRate

# Every test runs at noon on 15 November 2026, Beirut time: the pay period
# is November, October is the last closed one.
NOW = timezone.make_aware(datetime(2026, 11, 15, 12, 0))


def _on(day, start="10:00", minutes=60):
    starts = local_datetime(day, time.fromisoformat(start))
    return starts, starts + timedelta(minutes=minutes)


def _pt(coach, member, day, start="10:00", minutes=60, **extra):
    starts, ends = _on(day, start, minutes)
    return PTSession.objects.create(coach=coach, member=member, branch=coach.branch or "Hamra", starts_at=starts,
                                    ends_at=ends, **extra)


def _rate(coach, effective_from, class_hourly="20", pt_hourly="30"):
    return CoachPayRate.objects.create(coach=coach, effective_from=effective_from, class_hourly=Decimal(class_hourly),
                                       pt_hourly=Decimal(pt_hourly))


class FrozenClock(TestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)


# User story: "As a coach, I want to view my completed session count and
# earnings for the current pay period, so that I can verify my pay is correct."
class CoachStatementTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea", days_valid=400)
        cls.sami = _member("Sami Khoury", "sami", days_valid=400)

    def setUp(self):
        super().setUp()
        staff_login(self.client, "hadi", PASSWORD)

    def mine(self, period=None):
        return self.client.get("/api/payroll/me", {"period": period} if period else {})

    def test_completed_sessions_are_paid_by_the_hour_at_the_rate_on_their_day(self):
        _rate(self.hadi, date(2026, 10, 1))
        spin = _class("Spinning", self.hadi, date(2026, 11, 3), start="18:00", minutes=60)
        _book(self.lea, spin)
        ClassBooking.objects.filter(gym_class=spin).update(attendance=ClassBooking.Attendance.ATTENDED)
        _class("Yoga", self.hadi, date(2026, 11, 10), start="07:00", minutes=50)       # 20 x 50/60 = 16.67
        _pt(self.hadi, self.lea, date(2026, 11, 12), minutes=45)                        # 30 x 45/60 = 22.50

        body = self.mine().json()
        self.assertEqual(body["period"]["key"], "2026-11")
        self.assertEqual(body["period"]["label"], "November 2026")
        self.assertTrue(body["period"]["isCurrent"])
        summary = body["summary"]
        self.assertEqual((summary["completed"], summary["classes"], summary["privateSessions"]), (3, 2, 1))
        self.assertEqual((summary["minutes"], summary["earnings"], summary["unrated"]), (155, "59.17", 0))
        lines = [(l["title"], l["minutes"], l["hourlyRate"], l["amount"]) for l in body["completed"]]
        self.assertEqual(lines, [
            ("Spinning", 60, "20.00", "20.00"), ("Yoga", 50, "20.00", "16.67"),
            ("Private training · Lea Haddad", 45, "30.00", "22.50"),
        ])
        self.assertEqual(body["completed"][0]["detail"], "1 attended of 1 booked")
        # The total is exactly the sum of the lines the coach can see.
        self.assertEqual(sum(Decimal(l["amount"]) for l in body["completed"]), Decimal(summary["earnings"]))

    def test_a_raise_mid_month_pays_each_session_at_its_own_rate(self):
        _rate(self.hadi, date(2026, 10, 1), class_hourly="20")
        _rate(self.hadi, date(2026, 11, 10), class_hourly="25")
        _class("Spinning", self.hadi, date(2026, 11, 9), start="18:00")
        _class("Spinning", self.hadi, date(2026, 11, 10), start="18:00")
        body = self.mine().json()
        self.assertEqual([l["amount"] for l in body["completed"]], ["20.00", "25.00"])
        self.assertEqual(body["summary"]["earnings"], "45.00")
        self.assertEqual(body["rates"]["atPeriodStart"]["classHourly"], "20.00")
        self.assertEqual([r["classHourly"] for r in body["rates"]["changedDuringPeriod"]], ["25.00"])
        self.assertEqual(body["rates"]["current"]["classHourly"], "25.00")

    def test_without_a_rate_the_sessions_still_count_and_are_flagged(self):
        _class("Spinning", self.hadi, date(2026, 11, 3))
        _rate(self.hadi, date(2026, 11, 8))
        _class("Spinning", self.hadi, date(2026, 11, 9))
        body = self.mine().json()
        self.assertEqual([l["amount"] for l in body["completed"]], [None, "20.00"])
        self.assertEqual((body["summary"]["completed"], body["summary"]["earnings"], body["summary"]["unrated"]),
                         (2, "20.00", 1))

        CoachPayRate.objects.all().delete()
        body = self.mine().json()
        self.assertEqual((body["summary"]["earnings"], body["summary"]["unrated"], body["rates"]["current"]), ("0.00", 2, None))

    def test_empty_classes_and_member_no_shows_are_still_paid(self):
        _rate(self.hadi, date(2026, 11, 1))
        empty = _class("Spinning", self.hadi, date(2026, 11, 4))
        _book(self.lea, empty)
        ClassBooking.objects.filter(gym_class=empty).update(attendance=ClassBooking.Attendance.NO_SHOW)
        _pt(self.hadi, self.sami, date(2026, 11, 5), attendance=ClassBooking.Attendance.NO_SHOW)
        body = self.mine().json()
        self.assertEqual([l["amount"] for l in body["completed"]], ["20.00", "30.00"])
        self.assertIn("no one came, still paid", body["completed"][0]["detail"])
        self.assertEqual(body["completed"][1]["detail"], "Member didn't show - still paid")

    def test_cancelled_sessions_are_listed_but_not_paid(self):
        _rate(self.hadi, date(2026, 11, 1))
        gone = _class("Spinning", self.hadi, date(2026, 11, 6))
        GymClass.objects.filter(pk=gone.pk).update(status=GymClass.Status.CANCELLED, cancel_reason="Coach ill")
        _pt(self.hadi, self.lea, date(2026, 11, 7), status=PTSession.Status.CANCELLED, cancel_reason="Cancelled by you")
        body = self.mine().json()
        self.assertEqual((body["summary"]["completed"], body["summary"]["earnings"], body["summary"]["cancelled"]), (0, "0.00", 2))
        self.assertEqual([(l["reason"], l["amount"]) for l in body["cancelled"]],
                         [("Cancelled by the gym: Coach ill", None), ("Cancelled by you", None)])

    def test_sessions_still_to_come_are_an_estimate_not_pay(self):
        _rate(self.hadi, date(2026, 11, 1))
        _rate(self.hadi, date(2026, 11, 20), class_hourly="40")     # a raise already planned
        _class("Spinning", self.hadi, date(2026, 11, 15), start="11:30", minutes=60)   # in progress at noon
        _class("Spinning", self.hadi, date(2026, 11, 22), start="18:00")
        _class("Spinning", self.hadi, date(2026, 12, 1), start="18:00")              # next period
        body = self.mine().json()
        self.assertEqual(body["summary"]["completed"], 0)
        self.assertEqual([l["state"] for l in body["upcoming"]], ["in_progress", "upcoming"])
        self.assertEqual((body["summary"]["upcoming"], body["summary"]["upcomingEstimate"]), (2, "60.00"))
        self.assertEqual([r["classHourly"] for r in body["rates"]["scheduled"]], ["40.00"])
        self.assertEqual(body["period"]["daysLeft"], 15)

    def test_a_session_belongs_to_the_month_it_starts_in(self):
        _rate(self.hadi, date(2026, 10, 1))
        _class("Late spin", self.hadi, date(2026, 10, 31), start="23:30", minutes=60)
        self.assertEqual(self.mine().json()["summary"]["completed"], 0)
        october = self.mine("2026-10").json()
        self.assertEqual(([l["title"] for l in october["completed"]], october["period"]["isCurrent"]), (["Late spin"], False))

    def test_only_your_own_sessions(self):
        _rate(self.hadi, date(2026, 11, 1))
        _rate(self.rita, date(2026, 11, 1))
        _class("Pilates", self.rita, date(2026, 11, 3))
        _pt(self.rita, self.lea, date(2026, 11, 4))
        self.assertEqual(self.mine().json()["summary"]["completed"], 0)
        # A class handed to another coach is theirs.
        spin = _class("Spinning", self.hadi, date(2026, 11, 5))
        GymClass.objects.filter(pk=spin.pk).update(coach=self.rita)
        self.assertEqual(self.mine().json()["summary"]["completed"], 0)

    def test_which_pay_periods_can_be_opened(self):
        body = self.mine().json()
        self.assertEqual((body["periods"][0], body["periods"][-1], len(body["periods"])), ("2026-11", "2025-12", 12))
        self.assertEqual(self.mine("2025-12").status_code, 200)
        for bad in ("2025-11", "2026-12", "11-2026", "2026-13", "soon"):
            res = self.mine(bad)
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("period", res.json()["error"])

    def test_coaches_only(self):
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.mine().status_code, 403)
        self.client.logout()
        self.assertEqual(self.mine().status_code, 401)
        _member_login(self.client, "lea")
        self.assertEqual(self.mine().status_code, 401)


# The branch manager's side: setting rates, and seeing the same statement.
class PayRateManagementTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", ["manage_class_schedule", "manage_billing"], branch="Hamra")
        _staff("jnah_bm", ["manage_billing"], branch="Jnah")
        _staff("admin", ["manage_billing", "view_all_branches"], job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.lara = _coach("lara", branch="Jnah")
        cls.joe = _staff("joe", [], branch=None, job_title=StaffAccount.JobTitle.COACH)  # works at every branch
        cls.lea = _member("Lea Haddad", "lea", days_valid=400)

    def setUp(self):
        super().setUp()
        staff_login(self.client, "bm", PASSWORD)

    def set_rate(self, coach, **changes):
        body = {"classHourly": "22.50", "ptHourly": "35", "effectiveFrom": "2026-11-15", **changes}
        return self.client.post(f"/api/payroll/coaches/{coach.id}/rates", body, content_type="application/json")

    def test_setting_a_rate_is_audited_and_the_coach_is_told(self):
        res = self.set_rate(self.hadi, note="Annual raise")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["classHourly"], res.json()["ptHourly"], res.json()["setBy"]), ("22.50", "35.00", "Bm"))
        entry = AuditLog.objects.get(action=AuditLog.Action.PAY_RATE_SET)
        self.assertEqual((entry.target_label, entry.branch), ("Hadi", "Hamra"))
        self.assertIn("$22.50/hour for classes", entry.summary)
        note = StaffNotification.objects.get(recipient=self.hadi)
        self.assertEqual(note.kind, StaffNotification.Kind.PAY_RATE_CHANGED)
        self.assertIn("today", note.message)

    def test_the_same_date_again_replaces_the_rate(self):
        self.set_rate(self.hadi)
        res = self.set_rate(self.hadi, classHourly="24")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(CoachPayRate.objects.get(coach=self.hadi).class_hourly, Decimal("24"))
        latest = AuditLog.objects.filter(action=AuditLog.Action.PAY_RATE_SET).order_by("-id").first()
        self.assertEqual((latest.details["before"]["classHourly"], latest.details["after"]["classHourly"]), ("22.50", "24.00"))

    def test_a_closed_pay_period_can_never_change(self):
        res = self.set_rate(self.hadi, effectiveFrom="2026-10-31")
        self.assertEqual(res.status_code, 400)
        self.assertIn("01 Nov 2026 or later", res.json()["error"]["effectiveFrom"][0])
        # Back to the start of the open period is fine - it re-prices this month.
        _class("Spinning", self.hadi, date(2026, 11, 2))
        self.assertEqual(self.set_rate(self.hadi, effectiveFrom="2026-11-01").status_code, 201)
        statement = self.client.get(f"/api/payroll/coaches/{self.hadi.id}").json()
        self.assertEqual(statement["summary"]["earnings"], "22.50")

    def test_what_a_rate_must_be(self):
        for changes, field in [({"classHourly": "-1"}, "classHourly"), ({"ptHourly": "501"}, "ptHourly"),
                               ({"classHourly": "12.345"}, "classHourly"), ({"classHourly": "abc"}, "classHourly"),
                               ({"effectiveFrom": "2027-12-01"}, "effectiveFrom"), ({"effectiveFrom": ""}, "effectiveFrom"),
                               ({"note": "x" * 201}, "note")]:
            res = self.set_rate(self.hadi, **changes)
            self.assertEqual(res.status_code, 400, changes)
            self.assertIn(field, res.json()["error"], changes)
        res = self.client.post(f"/api/payroll/coaches/{self.hadi.id}/rates", {}, content_type="application/json")
        self.assertEqual(set(res.json()["error"]), {"classHourly", "ptHourly", "effectiveFrom"})
        self.assertFalse(CoachPayRate.objects.exists())
        # Zero is allowed (a coach paid only for one kind of session).
        self.assertEqual(self.set_rate(self.hadi, classHourly="0").status_code, 201)

    def test_branch_rules_for_who_manages_whose_pay(self):
        self.assertEqual(self.set_rate(self.lara).status_code, 403)   # another branch
        self.assertEqual(self.set_rate(self.joe).status_code, 403)    # not tied to a branch
        staff_login(self.client, "jnah_bm", PASSWORD)
        self.assertEqual(self.set_rate(self.lara).status_code, 201)
        self.assertEqual(self.set_rate(self.hadi).status_code, 403)
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.set_rate(self.joe).status_code, 201)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.set_rate(self.hadi).status_code, 403)
        staff_login(self.client, "hadi", PASSWORD)                    # coaches can't set their own pay
        self.assertEqual(self.set_rate(self.hadi).status_code, 403)

    def test_not_for_a_non_coach_a_missing_one_or_a_deactivated_one(self):
        desk = StaffAccount.objects.get(username="desk")
        self.assertEqual(self.set_rate(desk).status_code, 404)
        self.assertEqual(self.client.post("/api/payroll/coaches/999999/rates", {}, content_type="application/json").status_code, 404)
        StaffAccount.objects.filter(pk=self.hadi.pk).update(is_active=False)
        self.assertEqual(self.set_rate(self.hadi).status_code, 409)

    def test_only_a_change_that_hasnt_started_can_be_withdrawn(self):
        current = _rate(self.hadi, date(2026, 11, 1))
        planned = _rate(self.hadi, date(2026, 12, 1), class_hourly="30")
        res = self.client.delete(f"/api/payroll/coaches/{self.hadi.id}/rates/{current.id}")
        self.assertEqual(res.status_code, 409)
        res = self.client.delete(f"/api/payroll/coaches/{self.lara.id}/rates/{planned.id}")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.delete(f"/api/payroll/coaches/{self.hadi.id}/rates/999999").status_code, 404)
        res = self.client.delete(f"/api/payroll/coaches/{self.hadi.id}/rates/{planned.id}")
        self.assertEqual(res.status_code, 204)
        self.assertEqual(list(CoachPayRate.objects.values_list("id", flat=True)), [current.id])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PAY_RATE_REMOVED).exists())
        self.assertIn("won't happen", StaffNotification.objects.get(recipient=self.hadi).message)

    def test_the_overview_lists_only_this_managers_coaches(self):
        _rate(self.hadi, date(2026, 11, 1))
        _class("Spinning", self.hadi, date(2026, 11, 2))
        _pt(self.hadi, self.lea, date(2026, 11, 20))
        body = self.client.get("/api/payroll/coaches").json()
        self.assertEqual([c["name"] for c in body["results"]], ["Hadi"])
        hadi = body["results"][0]
        self.assertEqual((hadi["summary"]["completed"], hadi["summary"]["earnings"], hadi["summary"]["upcoming"]), (1, "20.00", 1))
        self.assertEqual(hadi["currentRate"]["classHourly"], "20.00")
        self.assertEqual(str(body["earliestEffectiveFrom"]), "2026-11-01")
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual({c["name"] for c in self.client.get("/api/payroll/coaches").json()["results"]}, {"Hadi", "Lara", "Joe"})

    def test_the_manager_sees_the_coachs_own_statement_and_rate_history(self):
        _rate(self.hadi, date(2026, 10, 1))
        _rate(self.hadi, date(2026, 11, 10), class_hourly="25")
        _class("Spinning", self.hadi, date(2026, 11, 12))
        body = self.client.get(f"/api/payroll/coaches/{self.hadi.id}").json()
        self.assertEqual([r["effectiveFrom"] for r in body["rateHistory"]], ["2026-11-10", "2026-10-01"])
        staff_login(self.client, "hadi", PASSWORD)
        mine = self.client.get("/api/payroll/me").json()
        self.assertEqual(mine["completed"], body["completed"])
        self.assertEqual(mine["summary"], body["summary"])
        self.assertNotIn("rateHistory", mine)
        self.assertEqual(self.client.get(f"/api/payroll/coaches/{self.hadi.id}").status_code, 403)

    def test_rate_lookup(self):
        rates = [_rate(self.hadi, date(2026, 10, 1)), _rate(self.hadi, date(2026, 11, 10))]
        self.assertIsNone(pay.rate_on(rates, date(2026, 9, 30)))
        self.assertEqual(pay.rate_on(rates, date(2026, 11, 9)), rates[0])
        self.assertEqual(pay.rate_on(rates, date(2026, 11, 10)), rates[1])

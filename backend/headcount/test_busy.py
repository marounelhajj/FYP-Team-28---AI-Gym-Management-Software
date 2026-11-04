import json
from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from checkins.models import CheckIn
from members.models import Member

from .busy import busy_level
from .models import BranchCapacity

PASSWORD = "Password123!"


def _member(name, username=None, branch="Hamra"):
    member = Member(
        name=name, email=f"{name.split()[0].lower()}{name.split()[-1].lower()}@example.com", phone="1", branch=branch,
        join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30), username=username,
    )
    if username:
        member.set_password(PASSWORD)
    member.save()
    return member


def _visit_at(member, branch, local_dt, minutes=45):
    check_in = CheckIn.objects.create(member=member, branch=branch, result=CheckIn.Result.ALLOWED)
    CheckIn.objects.filter(id=check_in.id).update(
        checked_in_at=local_dt, checked_out_at=local_dt + timedelta(minutes=minutes),
    )


def _local(day, hour, minute=5):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


# User story (SCRUM-77): "As a member, I want to see how busy my branch is
# right now and at typical hours, so that I can plan my visit around peak
# times."
class BusyLevelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = _member("Lea Haddad", "lea")
        cls.crowd = [_member(f"Crowd Person{i}") for i in range(12)]
        cls.jnah_crowd = [_member(f"Jnah Person{i}", branch="Jnah") for i in range(6)]
        BranchCapacity.objects.create(branch="Hamra", max_capacity=10)
        BranchCapacity.objects.create(branch="Jnah", max_capacity=20)

        today = timezone.localdate()
        cls.last_week = today - timedelta(days=7)
        cls.two_weeks = today - timedelta(days=14)
        # 18:00 on the same weekday: 6 then 2 people -> average 4 of 10 -> Moderate.
        for m in cls.crowd[:6]:
            _visit_at(m, "Hamra", _local(cls.last_week, 18))
        for m in cls.crowd[:2]:
            _visit_at(m, "Hamra", _local(cls.two_weeks, 18))
        # 07:00: 8 then 10 -> average 9 of 10 -> Very busy.
        for m in cls.crowd[:8]:
            _visit_at(m, "Hamra", _local(cls.last_week, 7))
        for m in cls.crowd[:10]:
            _visit_at(m, "Hamra", _local(cls.two_weeks, 7))
        # The day before last week's date (another weekday), 12:00: 7 people -> Busy.
        cls.other_day = cls.last_week - timedelta(days=1)
        for m in cls.crowd[:7]:
            _visit_at(m, "Hamra", _local(cls.other_day, 12))

    def setUp(self):
        res = self.client.post("/api/members/login", {"username": "lea", "password": PASSWORD}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)

    def busy(self, query="", expect=200):
        res = self.client.get(f"/api/members/me/busy{query}")
        self.assertEqual(res.status_code, expect, res.content)
        return res.json()

    def inside_now(self, members, branch="Hamra"):
        for m in members:
            CheckIn.objects.create(member=m, branch=branch, result=CheckIn.Result.ALLOWED)

    # --- levels -----------------------------------------------------------

    def test_busy_level_thresholds(self):
        names = ["Quiet", "Moderate", "Busy", "Very busy"]
        cases = {0: "Quiet", 29: "Quiet", 30: "Moderate", 59: "Moderate", 60: "Busy", 84: "Busy", 85: "Very busy", 130: "Very busy"}
        for count, expected in cases.items():
            self.assertEqual(names[busy_level(count, 100)], expected, count)

    def test_current_level_for_the_home_branch(self):
        self.inside_now(self.crowd[:4])
        body = self.busy()
        self.assertEqual(body["branch"], "Hamra")
        self.assertEqual(body["homeBranch"], "Hamra")
        self.assertTrue(body["available"])
        self.assertEqual(body["now"], {"level": "Moderate", "levelIndex": 1})

    def test_a_full_floor_is_very_busy(self):
        self.inside_now(self.crowd[:9])
        self.assertEqual(self.busy()["now"]["level"], "Very busy")

    def test_switching_to_another_branch(self):
        self.inside_now(self.jnah_crowd[:6], branch="Jnah")
        body = self.busy("?branch=Jnah")
        self.assertEqual(body["branch"], "Jnah")
        self.assertEqual(body["now"]["level"], "Moderate")  # 6 of 20
        self.busy("?branch=Atlantis", expect=400)

    def test_a_branch_without_capacity_has_no_level(self):
        body = self.busy("?branch=Zalka")
        self.assertFalse(body["available"])
        self.assertIsNone(body["now"])

    # --- typical by weekday ----------------------------------------------

    def test_typical_defaults_to_today_and_averages_past_weeks(self):
        body = self.busy()
        typical = body["typical"]
        self.assertEqual(typical["label"], "Typical")
        self.assertEqual(typical["weekdayIndex"], timezone.localdate().weekday())
        self.assertEqual(typical["weeksCompared"], 2)
        by_hour = {h["hour"]: h["level"] for h in typical["hours"]}
        self.assertEqual(by_hour, {7: "Very busy", 18: "Moderate"})

    def test_another_weekday_can_be_picked(self):
        body = self.busy(f"?weekday={self.other_day.weekday()}")
        self.assertEqual(body["typical"]["weekday"], self.other_day.strftime("%A"))
        # That weekday's latest date is yesterday (nobody came) plus the one a week before it:
        # 7 + 0 over 2 weeks = 3.5 of 10 -> Moderate.
        self.assertEqual(body["typical"]["weeksCompared"], 2)
        self.assertEqual({h["hour"]: h["level"] for h in body["typical"]["hours"]}, {12: "Moderate"})

    def test_weekday_is_validated(self):
        self.busy("?weekday=7", expect=400)
        self.busy("?weekday=monday", expect=400)

    # --- privacy ----------------------------------------------------------

    def test_response_has_no_member_level_data(self):
        self.inside_now(self.crowd[:4])
        text = json.dumps(self.busy())
        for member in self.crowd[:10]:
            self.assertNotIn(member.name, text)
            self.assertNotIn(member.email, text)
        for forbidden in ('"count"', '"memberId"', '"members"', '"share"'):
            self.assertNotIn(forbidden, text)

    def test_needs_a_member_session(self):
        self.client.post("/api/members/logout")
        self.busy(expect=401)

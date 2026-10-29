import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from checkins.models import CheckIn
from members.models import Member

PASSWORD = "ChangeMe123!"
# Wednesday 21 October 2026, 15:30 UTC. These tests are written in UTC hours,
# so the class runs with TIME_ZONE = UTC; test_hours_follow_the_server_time_zone
# checks the real setting (Beirut).
NOW = datetime(2026, 10, 21, 15, 30, tzinfo=dt_timezone.utc)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_timezone.utc)


def _staff(username, role, job_title, branch=None):
    account = StaffAccount(
        full_name=username.title(), email=f"{username}@gym.com", username=username,
        job_title=job_title, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


def _visit(member, start, end=None, branch="Hamra", result=CheckIn.Result.ALLOWED):
    check_in = CheckIn.objects.create(member=member, branch=branch, result=result)
    CheckIn.objects.filter(id=check_in.id).update(checked_in_at=start, checked_out_at=end)


# User story (SCRUM-129): "As a branch manager, I want to view headcount by
# hour for the current day, so that I can see when my peaks actually fall."
@override_settings(TIME_ZONE="UTC")
class HourlyHeadcountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Job = StaffAccount.JobTitle
        bm_role = Role.objects.create(name="Branch Manager", permissions=["view_branch_headcount"])
        gm_role = Role.objects.create(name="General Manager", permissions=["view_branch_headcount", "view_all_branches"])
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        _staff("hamrabm", bm_role, Job.BRANCH_MANAGER, branch="Hamra")
        _staff("gm", gm_role, Job.GENERAL_MANAGER)
        _staff("desk", desk_role, Job.RECEPTIONIST, branch="Hamra")
        cls.members = [
            Member.objects.create(
                name=f"Member {i}", email=f"m{i}@example.com", phone="1", branch="Hamra",
                join_date=date(2026, 1, 1), subscription_expires_at=date(2027, 1, 1),
            )
            for i in range(4)
        ]

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, query=""):
        return self.client.get(f"/api/headcount/hourly{query}")

    def hours(self, body):
        return {h["hour"]: h for h in body["hours"]}

    # AC: hourly breakdown for today.
    def test_hourly_breakdown_for_today(self):
        a, b, c, _ = self.members
        _visit(a, at(21, 9, 15), at(21, 10, 45))  # inside during 9 and 10
        _visit(b, at(21, 10, 0), at(21, 11, 0))   # 10 only (out on the hour)
        _visit(c, at(21, 14, 50))                 # still inside: 14 and 15
        _visit(a, at(21, 15, 5), result=CheckIn.Result.DENIED)
        _visit(b, at(21, 15, 0), branch="Jnah")

        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        hours = self.hours(body)
        self.assertEqual((body["branch"], body["date"], body["weekday"]), ("Hamra", "2026-10-21", "Wednesday"))
        self.assertEqual(body["currentHour"], 15)
        self.assertEqual(len(body["hours"]), 24)
        self.assertEqual([hours[h]["today"] for h in range(8, 17)], [0, 1, 2, 0, 0, 0, 1, 1, None])
        self.assertIsNone(hours[23]["today"])

    def test_a_member_inside_twice_in_one_hour_counts_once(self):
        a = self.members[0]
        _visit(a, at(21, 9, 0), at(21, 9, 20))
        _visit(a, at(21, 9, 40), at(21, 9, 50))
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.hours(self.get().json())[9]["today"], 1)

    # A session still open after 4 hours ends at the 4-hour mark.
    def test_forgotten_check_out_stops_counting_after_four_hours(self):
        _visit(self.members[0], at(21, 8, 30))
        staff_login(self.client, "hamrabm", PASSWORD)
        hours = self.hours(self.get().json())
        self.assertEqual([hours[h]["today"] for h in range(8, 14)], [1, 1, 1, 1, 1, 0])

    # AC: comparison against the same weekday average.
    def test_same_weekday_average(self):
        a, b, c, d = self.members
        # First check-in ever: 3 weeks ago, so 3 Wednesdays are compared.
        sep30 = datetime(2026, 9, 30, 18, tzinfo=dt_timezone.utc)
        _visit(a, sep30, sep30 + timedelta(minutes=90))  # Wed 30 Sep: 18 -> 1, 19 -> 1
        _visit(b, sep30 + timedelta(minutes=10), sep30 + timedelta(minutes=50))  # 18 -> 2
        _visit(a, at(7, 18, 0), at(7, 19, 0))    # Wed 7 Oct
        _visit(c, at(7, 18, 30), at(7, 18, 45))  # 18 -> 2
        _visit(d, at(14, 18, 0), at(14, 18, 30))  # Wed 14 Oct: 18 -> 1
        _visit(d, at(15, 18, 0), at(15, 19, 0))  # a Thursday - not compared

        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        hours = self.hours(body)
        self.assertEqual(body["weeksCompared"], 3)
        self.assertEqual(hours[18]["weekdayAverage"], round(5 / 3, 1))
        self.assertEqual(hours[19]["weekdayAverage"], round(1 / 3, 1))
        self.assertEqual(hours[6]["weekdayAverage"], 0)

    def test_only_the_last_six_weeks_are_compared(self):
        _visit(self.members[0], datetime(2026, 8, 26, 18, tzinfo=dt_timezone.utc))  # 8 weeks ago
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["weeksCompared"], 6)
        self.assertEqual(self.hours(body)[18]["weekdayAverage"], 0)

    def test_no_history_means_no_average(self):
        _visit(self.members[0], at(21, 9, 0), at(21, 10, 0))
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["weeksCompared"], 0)
        self.assertTrue(all(h["weekdayAverage"] is None for h in body["hours"]))

    # AC: no individual member is identifiable.
    def test_response_has_only_aggregated_counts(self):
        _visit(self.members[0], at(21, 9, 0), at(21, 10, 0))
        _visit(self.members[1], at(14, 9, 0), at(14, 10, 0))
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        self.assertEqual(
            set(body), {"branch", "date", "weekday", "currentHour", "weeksCompared", "asOf", "timeZone", "hours"},
        )
        self.assertTrue(all(set(h) == {"hour", "today", "weekdayAverage"} for h in body["hours"]))
        raw = json.dumps(body)
        for member in self.members:
            self.assertNotIn(member.name, raw)
            self.assertNotIn(member.email, raw)
        self.assertNotIn("member", raw.lower())

    # With the real setting, 15:05 UTC is 18:05 in Beirut: still summer time
    # (UTC+3) on 21 October - the clocks go back on the 25th.
    @override_settings(TIME_ZONE="Asia/Beirut")
    def test_hours_follow_the_server_time_zone(self):
        _visit(self.members[0], at(21, 15, 5))
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        self.assertEqual((body["timeZone"], body["currentHour"]), ("Asia/Beirut", 18))
        self.assertEqual(self.hours(body)[18]["today"], 1)

    # Same branch rule as live headcount (SCRUM-127).
    def test_branch_permissions(self):
        self.assertEqual(self.get().status_code, 401)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.get().status_code, 403)
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get("?branch=Jnah").status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.get("?branch=Jnah").json()["branch"], "Jnah")

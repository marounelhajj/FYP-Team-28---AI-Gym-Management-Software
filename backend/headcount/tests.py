from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from checkins.models import AUTO_CHECKOUT_AFTER, CheckIn, close_stale_sessions
from members.models import Member

PASSWORD = "ChangeMe123!"


def _staff(username, role, job_title, branch=None):
    account = StaffAccount(
        full_name=username.title(), email=f"{username}@gym.com", username=username,
        job_title=job_title, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


def _member(name, branch="Hamra"):
    return Member.objects.create(
        name=name, email=f"{name.split()[0].lower()}@example.com", phone="1", branch=branch,
        join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30),
    )


# Puts a check-in row in the past (checked_in_at is auto_now_add).
def _visit(member, branch, minutes_ago, checked_out_minutes_ago=None, result=CheckIn.Result.ALLOWED):
    now = timezone.now()
    check_in = CheckIn.objects.create(member=member, branch=branch, result=result)
    CheckIn.objects.filter(id=check_in.id).update(
        checked_in_at=now - timedelta(minutes=minutes_ago),
        checked_out_at=None if checked_out_minutes_ago is None else now - timedelta(minutes=checked_out_minutes_ago),
    )
    check_in.refresh_from_db()
    return check_in


class HeadcountTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        Job = StaffAccount.JobTitle
        bm_role = Role.objects.create(name="Branch Manager", permissions=["manage_members", "view_branch_headcount"])
        gm_role = Role.objects.create(name="General Manager", permissions=["view_branch_headcount", "view_all_branches"])
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        _staff("hamrabm", bm_role, Job.BRANCH_MANAGER, branch="Hamra")
        _staff("nobranchbm", bm_role, Job.BRANCH_MANAGER)
        _staff("gm", gm_role, Job.GENERAL_MANAGER)
        _staff("hamradesk", desk_role, Job.RECEPTIONIST, branch="Hamra")
        _staff("jnahdesk", desk_role, Job.RECEPTIONIST, branch="Jnah")
        cls.lea = _member("Lea Haddad")
        cls.sami = _member("Sami Khoury")
        cls.rana = _member("Rana Aoun", branch="Jnah")

    def get(self, query=""):
        return self.client.get(f"/api/headcount/live{query}")

    def post(self, path, body):
        return self.client.post(path, body, content_type="application/json")


# User story (SCRUM-127): "As a branch manager, I want to view live headcount
# for my branch on a dashboard, so that I can see how full the gym is right now."
class LiveHeadcountTests(HeadcountTestCase):
    # AC: headcount is derived from check-ins and check-outs.
    def test_count_follows_check_ins_and_check_outs(self):
        staff_login(self.client, "hamradesk", PASSWORD)
        self.post("/api/checkins", {"membershipId": self.lea.id})
        self.post("/api/checkins", {"membershipId": self.sami.id})

        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get().json()["count"], 2)

        staff_login(self.client, "hamradesk", PASSWORD)
        self.post("/api/checkins/checkout", {"membershipId": self.lea.id})
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get().json()["count"], 1)

    def test_only_allowed_open_sessions_at_that_branch_count(self):
        _visit(self.lea, "Hamra", minutes_ago=30)
        _visit(self.sami, "Hamra", minutes_ago=90, checked_out_minutes_ago=20)
        _visit(self.sami, "Hamra", minutes_ago=5, result=CheckIn.Result.DENIED)
        _visit(self.rana, "Jnah", minutes_ago=10)
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get().json()["count"], 1)

    def test_check_in_is_counted_at_the_desk_branch(self):
        staff_login(self.client, "jnahdesk", PASSWORD)
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.json()["checkIn"]["branch"], "Jnah")
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.get("?branch=Jnah").json()["count"], 1)
        self.assertEqual(self.get("?branch=Hamra").json()["count"], 0)

    def test_response_shape(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["branch"], "Hamra")
        self.assertEqual(body["branches"], ["Hamra"])
        self.assertFalse(body["canChooseBranch"])
        self.assertEqual(body["autoCheckoutHours"], 4)
        self.assertEqual(body["refreshSeconds"], 15)
        self.assertTrue(body["asOf"].endswith("Z"))


class AutoCheckoutTests(HeadcountTestCase):
    def test_sessions_older_than_four_hours_are_closed(self):
        stale = _visit(self.lea, "Hamra", minutes_ago=5 * 60)
        fresh = _visit(self.sami, "Hamra", minutes_ago=60)

        self.assertEqual(close_stale_sessions(), 1)
        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertTrue(stale.auto_checked_out)
        self.assertEqual(stale.checked_out_at, stale.checked_in_at + AUTO_CHECKOUT_AFTER)
        self.assertIsNone(fresh.checked_out_at)
        self.assertFalse(fresh.auto_checked_out)

    def test_stale_sessions_drop_out_of_the_headcount(self):
        _visit(self.lea, "Hamra", minutes_ago=5 * 60)
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get().json()["count"], 0)

    # Before this, a member who forgot to check out was refused as "Already
    # checked in" on every later visit.
    def test_forgotten_check_out_does_not_block_next_visit(self):
        _visit(self.lea, "Hamra", minutes_ago=20 * 60)
        staff_login(self.client, "hamradesk", PASSWORD)
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.json()["checkIn"]["result"], "Allowed")


# A Branch Manager sees only their own branch; a General Manager can pick
# any. Enforced by the server.
class BranchPermissionTests(HeadcountTestCase):
    def test_requires_view_branch_headcount(self):
        self.assertEqual(self.get().status_code, 401)
        staff_login(self.client, "hamradesk", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_branch_manager_cannot_see_another_branch(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get("?branch=Hamra").status_code, 200)
        res = self.get("?branch=Jnah")
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("count", res.json())

    def test_branch_manager_without_a_branch_is_refused(self):
        staff_login(self.client, "nobranchbm", PASSWORD)
        res = self.get()
        self.assertEqual(res.status_code, 403)
        self.assertIn("isn't assigned to a branch", res.json()["error"])

    def test_general_manager_can_pick_any_branch(self):
        _visit(self.rana, "Jnah", minutes_ago=10)
        staff_login(self.client, "gm", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["branch"], "Hamra")
        self.assertEqual(body["branches"], ["Hamra", "Achrafieh", "Jnah", "Zalka"])
        self.assertTrue(body["canChooseBranch"])
        self.assertEqual(self.get("?branch=Jnah").json()["count"], 1)

    def test_invalid_branch(self):
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.get("?branch=Paris").status_code, 400)

    def test_a_revoked_permission_takes_effect_immediately(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        role = Role.objects.get(name="Branch Manager")
        role.permissions = ["manage_members"]
        role.save()
        self.assertEqual(self.get().status_code, 403)


class MigrationBackfillTests(TestCase):
    def test_existing_check_ins_get_the_member_branch(self):
        from importlib import import_module
        from django.apps import apps

        member = _member("Lea Haddad", branch="Zalka")
        check_in = CheckIn.objects.create(member=member, result=CheckIn.Result.ALLOWED)
        self.assertEqual(check_in.branch, "")

        migration = import_module("checkins.migrations.0004_checkin_branch_auto_checkout")
        migration.backfill_branch(apps, None)
        check_in.refresh_from_db()
        self.assertEqual(check_in.branch, "Zalka")

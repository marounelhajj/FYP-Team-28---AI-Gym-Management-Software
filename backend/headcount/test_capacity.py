from datetime import date, timedelta

from django.test import TestCase

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from checkins.models import CheckIn
from members.models import Member
from notifications.models import StaffNotification

from .alerts import check_capacity
from .models import BranchCapacity
from .tests import PASSWORD, _staff, _visit

Job = StaffAccount.JobTitle


def _members(count, branch="Hamra"):
    return [
        Member.objects.create(
            name=f"Member {branch} {i}", email=f"m{branch}{i}@example.com", phone="1", branch=branch,
            join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30),
        )
        for i in range(count)
    ]


# User story (SCRUM-128): "As a branch manager, I want to be alerted when
# headcount approaches the branch capacity limit, so that I can act before
# the floor becomes unsafe or unpleasant."
class CapacityAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        bm_role = Role.objects.create(name="Branch Manager", permissions=["manage_members", "view_branch_headcount"])
        gm_role = Role.objects.create(name="General Manager", permissions=["view_branch_headcount", "view_all_branches"])
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        coach_role = Role.objects.create(name="Coach", permissions=[])
        cls.bm = _staff("hamrabm", bm_role, Job.BRANCH_MANAGER, branch="Hamra")
        cls.gm = _staff("gm", gm_role, Job.GENERAL_MANAGER)
        cls.desk = _staff("hamradesk", desk_role, Job.RECEPTIONIST, branch="Hamra")
        cls.coach = _staff("hamracoach", coach_role, Job.COACH, branch="Hamra")
        cls.jnah_desk = _staff("jnahdesk", desk_role, Job.RECEPTIONIST, branch="Jnah")
        cls.gone = _staff("formerdesk", desk_role, Job.RECEPTIONIST, branch="Hamra")
        StaffAccount.objects.filter(pk=cls.gone.pk).update(is_active=False)
        cls.hamra = _members(12)
        cls.jnah = _members(12, branch="Jnah")
        # Hamra: 10 people, alert at 90% -> 9, clears below 9 - 1 = 8.
        BranchCapacity.objects.create(branch="Hamra", max_capacity=10)

    def inside(self, members, count, branch="Hamra"):
        for member in members[:count]:
            _visit(member, branch, minutes_ago=10)

    def leave(self, members, count):
        CheckIn.objects.filter(member__in=members[:count], checked_out_at__isnull=True).update(checked_out_at=CheckIn.objects.first().checked_in_at)

    def alerts(self, recipient=None):
        qs = StaffNotification.objects.filter(kind=StaffNotification.Kind.CAPACITY_ALERT)
        return qs.filter(recipient=recipient) if recipient else qs

    # --- thresholds -------------------------------------------------------

    def test_threshold_defaults_to_90_percent_with_a_clearing_margin(self):
        setting = BranchCapacity.objects.get(branch="Hamra")
        self.assertEqual((setting.threshold, setting.clear_below), (9, 8))
        big = BranchCapacity(branch="Jnah", max_capacity=200, alert_percent=80)
        self.assertEqual((big.threshold, big.clear_below), (160, 150))

    def test_below_the_threshold_nothing_happens(self):
        self.inside(self.hamra, 8)
        setting = check_capacity("Hamra")
        self.assertFalse(setting.alert_active)
        self.assertEqual(self.alerts().count(), 0)

    def test_crossing_up_raises_one_alert_for_the_branch_staff(self):
        self.inside(self.hamra, 9)
        setting = check_capacity("Hamra")
        self.assertTrue(setting.alert_active)
        self.assertEqual(setting.alert_count, 9)
        recipients = set(self.alerts().values_list("recipient__username", flat=True))
        # Everyone at Hamra who is still active - not Jnah, not the GM, not a deactivated account.
        self.assertEqual(recipients, {"hamrabm", "hamradesk", "hamracoach"})

    def test_staying_above_does_not_repeat_it(self):
        self.inside(self.hamra, 9)
        check_capacity("Hamra")
        self.inside(self.hamra[9:], 2)
        check_capacity("Hamra")
        check_capacity("Hamra")
        self.assertEqual(self.alerts(self.bm).count(), 1)

    def test_dropping_into_the_margin_keeps_it_and_below_clears_it(self):
        self.inside(self.hamra, 9)
        check_capacity("Hamra")
        self.assertTrue(check_capacity("Hamra", count=8).alert_active)  # 8 is not below clear_below (8)
        cleared = check_capacity("Hamra", count=7)
        self.assertFalse(cleared.alert_active)
        self.assertIsNotNone(cleared.alert_cleared_at)

    def test_rising_again_after_clearing_alerts_again(self):
        check_capacity("Hamra", count=9)
        check_capacity("Hamra", count=5)
        check_capacity("Hamra", count=10)
        self.assertEqual(self.alerts(self.bm).count(), 2)

    def test_thresholds_are_per_branch(self):
        BranchCapacity.objects.create(branch="Jnah", max_capacity=20, alert_percent=50)  # alert at 10
        self.inside(self.jnah, 9, branch="Jnah")
        self.assertFalse(check_capacity("Jnah").alert_active)
        self.inside(self.jnah[9:], 1, branch="Jnah")
        self.assertTrue(check_capacity("Jnah").alert_active)
        self.assertEqual(set(self.alerts().values_list("recipient__username", flat=True)), {"jnahdesk"})
        self.assertFalse(BranchCapacity.objects.get(branch="Hamra").alert_active)

    def test_a_branch_without_capacity_never_alerts(self):
        self.inside(self.jnah, 12, branch="Jnah")
        self.assertIsNone(check_capacity("Jnah"))
        self.assertEqual(self.alerts().count(), 0)

    def test_a_desk_check_in_that_crosses_the_line_raises_it(self):
        self.inside(self.hamra, 8)
        staff_login(self.client, "hamradesk", PASSWORD)
        res = self.client.post("/api/checkins", {"membershipId": self.hamra[8].id}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(BranchCapacity.objects.get(branch="Hamra").alert_active)
        self.assertEqual(self.alerts(self.desk).count(), 1)

    # --- dashboard and settings ------------------------------------------

    def test_dashboard_shows_the_alert_and_capacity(self):
        self.inside(self.hamra, 9)
        staff_login(self.client, "hamrabm", PASSWORD)
        body = self.client.get("/api/headcount/live").json()
        self.assertEqual(body["capacity"], {"maxCapacity": 10, "alertPercent": 90, "threshold": 9, "clearBelow": 8})
        self.assertTrue(body["alert"]["active"])
        self.assertEqual(body["alert"]["count"], 9)

    def test_dashboard_without_a_capacity_setting(self):
        staff_login(self.client, "gm", PASSWORD)
        body = self.client.get("/api/headcount/live?branch=Jnah").json()
        self.assertIsNone(body["capacity"])
        self.assertEqual(body["alert"], {"active": False})

    def test_branch_manager_sets_their_own_branch(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        res = self.client.put("/api/headcount/capacity", {"maxCapacity": 50, "alertPercent": 80}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["capacity"]["threshold"], 40)
        self.assertEqual(BranchCapacity.objects.get(branch="Hamra").updated_by, self.bm)

    def test_branch_manager_cannot_set_another_branch(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        res = self.client.put("/api/headcount/capacity", {"branch": "Jnah", "maxCapacity": 50}, content_type="application/json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(BranchCapacity.objects.filter(branch="Jnah").exists())

    def test_general_manager_sets_any_branch_with_the_default_percent(self):
        staff_login(self.client, "gm", PASSWORD)
        res = self.client.put("/api/headcount/capacity", {"branch": "Jnah", "maxCapacity": 40}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["capacity"]["alertPercent"], 90)

    def test_front_desk_cannot_change_capacity(self):
        staff_login(self.client, "hamradesk", PASSWORD)
        res = self.client.put("/api/headcount/capacity", {"maxCapacity": 5}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_capacity_is_validated(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        for body in ({"maxCapacity": 0}, {"maxCapacity": "lots"}, {"maxCapacity": 10, "alertPercent": 150}):
            res = self.client.put("/api/headcount/capacity", body, content_type="application/json")
            self.assertEqual(res.status_code, 400, body)

    def test_lowering_the_threshold_below_the_current_count_alerts_at_once(self):
        self.inside(self.hamra, 6)
        staff_login(self.client, "hamrabm", PASSWORD)
        res = self.client.put("/api/headcount/capacity", {"maxCapacity": 10, "alertPercent": 50}, content_type="application/json")
        self.assertTrue(res.json()["alert"]["active"])

    # --- notifications ----------------------------------------------------

    def test_staff_read_their_own_notifications(self):
        check_capacity("Hamra", count=9)
        staff_login(self.client, "hamradesk", PASSWORD)
        body = self.client.get("/api/notifications").json()
        self.assertEqual(body["unread"], 1)
        self.assertEqual(body["results"][0]["title"], "Hamra is near capacity")
        note_id = body["results"][0]["id"]
        self.assertEqual(self.client.post(f"/api/notifications/{note_id}/read").status_code, 200)
        self.assertEqual(self.client.get("/api/notifications").json()["unread"], 0)

    def test_nobody_reads_someone_elses_notification(self):
        check_capacity("Hamra", count=9)
        other = self.alerts(self.bm).get()
        staff_login(self.client, "jnahdesk", PASSWORD)
        self.assertEqual(self.client.post(f"/api/notifications/{other.id}/read").status_code, 404)
        other.refresh_from_db()
        self.assertIsNone(other.read_at)

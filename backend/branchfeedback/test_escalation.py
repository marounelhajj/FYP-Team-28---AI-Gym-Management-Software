from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from classes.tests import PASSWORD, _member, _staff
from notifications.models import MemberNotification, StaffNotification

from .models import Complaint
from .tests import COMPLAINT, FEEDBACK, FrozenClock

# SCRUM-94: a branch manager escalating a complaint to the general manager.


class EscalationTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", [FEEDBACK, "manage_members"], branch="Hamra")
        cls.jnah_bm = _staff("jnah_bm", [FEEDBACK], branch="Jnah")
        cls.gm = _staff("gm", [FEEDBACK, "view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        # Sees every branch too, but isn't a general manager: not notified while there is one.
        cls.admin = _staff("admin", [FEEDBACK, "view_all_branches"], job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        cls.lea = _member("Lea Haddad", "lea")

    def setUp(self):
        super().setUp()
        self.complaint = Complaint.objects.create(member=self.lea, **COMPLAINT)
        staff_login(self.client, "bm", PASSWORD)

    def escalate(self, complaint=None, reason="Third time this month - needs a new treadmill, over my budget."):
        return self.client.post(f"/api/branch-feedback/complaints/{(complaint or self.complaint).id}/escalate",
                                {"reason": reason}, content_type="application/json")

    def complaints(self, **params):
        return self.client.get("/api/branch-feedback/complaints", params).json()

    def test_one_click_escalation_reaches_the_general_manager(self):
        res = self.escalate()
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["escalation"]["by"], "Bm")
        self.assertTrue(body["escalation"]["reason"].startswith("Third time"))
        # It stays the branch's case, open, with the reason noted for staff only.
        self.assertEqual(body["status"], "Open")
        note = body["messages"][-1]
        self.assertTrue(note["internal"])
        self.assertIn("Escalated to the general manager", note["body"])

        [alert] = StaffNotification.objects.filter(kind=StaffNotification.Kind.ESCALATED_COMPLAINT)
        self.assertEqual((alert.recipient, alert.branch), (self.gm, "Hamra"))
        self.assertIn("Treadmill 3 is broken", alert.title)
        self.assertIn("Third time", alert.message)

        told = MemberNotification.objects.get(recipient=self.lea, kind=MemberNotification.Kind.COMPLAINT_UPDATE)
        self.assertIn("head office", told.title)
        # ...but never the internal reason.
        self.assertNotIn("budget", told.message)

        entry = AuditLog.objects.get(action=AuditLog.Action.COMPLAINT_ESCALATED)
        self.assertEqual((entry.branch, entry.details["complaintId"]), ("Hamra", self.complaint.id))

    def test_member_never_sees_the_reason(self):
        self.escalate()
        from classes.tests import _member_login

        self.client.post("/api/auth/logout")
        _member_login(self.client, "lea")
        [mine] = self.client.get("/api/members/me/branch-feedback").json()["complaints"]
        self.assertNotIn("escalation", mine)
        self.assertEqual(mine["messages"], [])

    def test_escalated_once_and_never_once_resolved(self):
        self.assertEqual(self.escalate().status_code, 200)
        self.assertEqual(self.escalate().status_code, 409)
        resolved = Complaint.objects.create(member=self.lea, **{**COMPLAINT, "subject": "Old one"}, status=Complaint.Status.RESOLVED)
        self.assertEqual(self.escalate(resolved).status_code, 409)
        self.assertFalse(Complaint.objects.get(pk=resolved.pk).escalated_at)

    def test_a_reason_is_required(self):
        res = self.escalate(reason="   ")
        self.assertEqual(res.status_code, 400)
        self.assertIn("reason", res.json()["error"])
        self.assertEqual(self.escalate(reason="x" * 501).status_code, 400)
        self.assertIsNone(Complaint.objects.get().escalated_at)

    def test_only_the_complaints_own_branch_can_escalate_it(self):
        self.client.post("/api/auth/logout")
        staff_login(self.client, "jnah_bm", PASSWORD)
        self.assertEqual(self.escalate().status_code, 403)
        self.client.post("/api/auth/logout")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.escalate().status_code, 403)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.escalate().status_code, 401)

    def test_the_general_manager_cant_escalate_to_themselves(self):
        self.client.post("/api/auth/logout")
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.escalate().status_code, 403)

    def test_general_manager_sees_escalations_from_every_branch(self):
        jnah = Complaint.objects.create(member=self.lea, **{**COMPLAINT, "branch": "Jnah", "subject": "Showers cold"})
        Complaint.objects.create(member=self.lea, **{**COMPLAINT, "subject": "Not escalated"})
        self.escalate()
        self.client.post("/api/auth/logout")
        staff_login(self.client, "jnah_bm", PASSWORD)
        self.escalate(jnah)

        self.client.post("/api/auth/logout")
        staff_login(self.client, "gm", PASSWORD)
        body = self.complaints(status="escalated", scope="all")
        self.assertTrue(body["allBranches"])
        self.assertEqual({c["subject"] for c in body["results"]}, {"Treadmill 3 is broken", "Showers cold"})
        # Without scope=all it's one branch, like every other filter.
        body = self.complaints(status="escalated", branch="Jnah")
        self.assertEqual([c["subject"] for c in body["results"]], ["Showers cold"])
        # The summary counts open escalations per branch.
        counts = self.client.get("/api/branch-feedback/summary", {"branch": "Hamra"}).json()["complaints"]
        self.assertEqual(counts["escalatedOpen"], 1)

    def test_a_branch_manager_cant_widen_the_scope(self):
        jnah = Complaint.objects.create(member=self.lea, **{**COMPLAINT, "branch": "Jnah"})
        Complaint.objects.filter(pk=jnah.pk).update(escalated_at=self.complaint.created_at)
        self.escalate()
        body = self.complaints(status="escalated", scope="all")
        self.assertFalse(body["allBranches"])
        self.assertEqual([c["id"] for c in body["results"]], [self.complaint.id])

    def test_resolving_it_tells_the_branch_manager_who_escalated(self):
        self.escalate()
        self.client.post("/api/auth/logout")
        staff_login(self.client, "gm", PASSWORD)
        res = self.client.patch(f"/api/branch-feedback/complaints/{self.complaint.id}",
                                {"status": "Resolved", "message": "New treadmill ordered for Hamra."},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["escalation"]["by"], "Bm")         # still on record
        alert = StaffNotification.objects.get(recipient=self.bm, kind=StaffNotification.Kind.ESCALATED_COMPLAINT)
        self.assertIn("resolved", alert.title)
        # Gone from the open escalations queue.
        self.assertEqual(self.complaints(status="escalated", scope="all")["results"], [])

    def test_without_a_general_manager_the_overseers_are_told(self):
        self.gm.is_active = False
        self.gm.save()
        self.escalate()
        [alert] = StaffNotification.objects.filter(kind=StaffNotification.Kind.ESCALATED_COMPLAINT)
        self.assertEqual(alert.recipient, self.admin)

    def test_branch_manager_still_answers_and_resolves_it(self):
        self.escalate()
        res = self.client.patch(f"/api/branch-feedback/complaints/{self.complaint.id}",
                                {"status": "Resolved", "message": "Fixed it after all."}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        # Resolved by the one who escalated it: nobody to tell.
        self.assertFalse(StaffNotification.objects.filter(recipient=self.bm).exists())

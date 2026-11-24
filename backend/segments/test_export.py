import csv
import io

from django.test import TestCase
from django.utils import timezone

from administration.testing import staff_login
from audit.models import AuditLog
from members.privacy import anonymize_member

from .models import Segment
from .testing import PASSWORD, attended_class, branch_manager, marketing, member, opt_out, risk, staff, visits

# User story (SCRUM-114): "As a marketing staff member, I want to export
# engagement data for a selected segment, so that I can use it in campaign
# planning."


def rows(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))


class ExportTests(TestCase):
    def setUp(self):
        self.ana = member("Ana Active", branch="Hamra")
        visits(self.ana, [1, 3, 40])
        risk(self.ana, "High")
        self.opted = member("Omar Optout", branch="Hamra")
        opt_out(self.opted)
        self.gone = member("Gail Gone", branch="Hamra")
        anonymize_member(self.gone)
        self.gone.status = "Active"
        self.gone.save(update_fields=["status"])
        self.jnah = member("Jad Jnah", branch="Jnah")
        attended_class(self.jnah, "Yoga", 2, )
        self.segment = Segment.objects.create(name="Everyone", filters={"statuses": ["Active"]})
        marketing()
        staff_login(self.client, "nadine", PASSWORD)

    def test_member_list_export(self):
        res = self.client.get("/api/segments/export", {"type": "members", "segment": self.segment.pk})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", res["Content-Disposition"])
        data = rows(res)
        self.assertEqual(data[0], ["member_id", "first_name", "email", "branch", "plan", "visits_in_range",
                                   "last_visit", "risk_level"])
        by_id = {int(r[0]): r for r in data[1:]}
        # Privacy: no opted-out member, no deleted (anonymized) member.
        self.assertEqual(set(by_id), {self.ana.pk, self.jnah.pk})
        ana = by_id[self.ana.pk]
        self.assertEqual(ana[1:5], ["Ana", self.ana.email, "Hamra", "Basic"])
        self.assertEqual(ana[5], "2")  # 40 days ago is outside the default 30-day range
        self.assertEqual(ana[7], "High")

    def test_member_list_export_is_audited(self):
        self.client.get("/api/segments/export", {"type": "members", "segment": self.segment.pk})
        entry = AuditLog.objects.get(action=AuditLog.Action.SEGMENT_EXPORTED)
        self.assertEqual(entry.actor_username, "nadine")
        self.assertEqual(entry.target_id, str(self.segment.pk))
        self.assertEqual(entry.details["exportType"], "members")
        self.assertEqual(entry.details["segmentName"], "Everyone")
        self.assertEqual(entry.details["filters"], {"statuses": ["Active"]})
        self.assertEqual(entry.details["rows"], 2)
        self.assertEqual(entry.details["excludedForPrivacy"], 2)

    def test_aggregate_export_is_the_current_view_and_audited(self):
        res = self.client.get("/api/segments/export", {"type": "aggregate", "segments": self.segment.pk,
                                                       "branch": "Hamra", "period": "month"})
        self.assertEqual(res.status_code, 200, res.content)
        data = rows(res)
        self.assertEqual(data[0][0], "section")
        sections = {r[0] for r in data[1:]}
        self.assertEqual(sections, {"attendance_trend"})  # no class or shop use at Hamra in range
        self.assertEqual(sum(1 for r in data[1:] if r[1] == "Everyone"), 6)
        self.assertEqual(sum(1 for r in data[1:] if r[1] == "All members"), 6)
        # No names or emails in the aggregate export.
        self.assertNotIn(self.ana.email, res.content.decode())
        entry = AuditLog.objects.get(action=AuditLog.Action.SEGMENT_EXPORTED)
        self.assertEqual(entry.details["exportType"], "aggregate")
        self.assertEqual(entry.details["filters"]["branches"], ["Hamra"])
        self.assertEqual(entry.details["filters"]["period"], "month")
        self.assertEqual(entry.details["rows"], len(data) - 1)
        self.assertEqual(entry.branch, "Hamra")

    def test_aggregate_export_includes_uptake(self):
        res = self.client.get("/api/segments/export", {"type": "aggregate"})
        data = rows(res)
        uptake = [r for r in data if r[0] == "uptake"]
        self.assertTrue(any(r[2] == "Yoga" for r in uptake))

    def test_only_gm_and_marketing_export_member_lists(self):
        branch_manager()
        self.client.logout()
        staff_login(self.client, "hamrabm", PASSWORD)
        res = self.client.get("/api/segments/export", {"type": "members", "segment": self.segment.pk})
        self.assertEqual(res.status_code, 403)
        # A branch manager can still export the aggregate numbers for their branch.
        res = self.client.get("/api/segments/export", {"type": "aggregate"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AuditLog.objects.get(action=AuditLog.Action.SEGMENT_EXPORTED).branch, "Hamra")
        self.assertEqual(self.client.get("/api/segments/export", {"type": "aggregate", "branch": "Jnah"}).status_code, 403)

    def test_gm_can_export_member_lists(self):
        staff("gm", ["view_all_branches", "view_member_segments", "export_segment_members"], role_name="GM")
        self.client.logout()
        staff_login(self.client, "gm", PASSWORD)
        res = self.client.get("/api/segments/export", {"type": "members", "segment": self.segment.pk})
        self.assertEqual(res.status_code, 200)

    def test_validation(self):
        self.assertEqual(self.client.get("/api/segments/export", {"type": "pdf"}).status_code, 400)
        self.assertEqual(self.client.get("/api/segments/export", {"type": "members"}).status_code, 400)
        self.assertEqual(self.client.get("/api/segments/export", {"type": "members", "segment": 999}).status_code, 404)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.SEGMENT_EXPORTED).exists())

    def test_spreadsheet_formulas_are_neutralised(self):
        evil = member("=HYPERLINK(1) Evil", branch="Hamra")
        res = self.client.get("/api/segments/export", {"type": "members", "segment": self.segment.pk})
        first_names = [r[1] for r in rows(res)[1:]]
        self.assertIn("'=HYPERLINK(1)", first_names)
        self.assertTrue(evil.pk)
        _ = timezone.now()

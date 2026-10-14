from datetime import date, timedelta

from django.test import TestCase

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from members import qr
from members.models import Member

PASSWORD = "ChangeMe123!"


# User story (SCRUM-33): "As a receptionist, I want to check in members via
# QR code or membership ID, so that I can quickly verify membership status
# and control entry."
class QrCheckInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        desk = StaffAccount(
            full_name="Desk", email="desk@gym.com", username="desk",
            job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
        )
        desk.set_password(PASSWORD)
        desk.save()
        cls.lea = Member(
            name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra",
            join_date=date.today(), username="lea",
            subscription_expires_at=date.today() + timedelta(days=30),
        )
        cls.lea.set_password(PASSWORD)
        cls.lea.save()
        cls.other = Member.objects.create(
            name="Sami Khoury", email="sami@example.com", phone="2", branch="Jnah",
            join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30),
        )

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def post(self, path, body):
        return self.client.post(path, body, content_type="application/json")

    def test_check_in_and_out_with_qr_code(self):
        payload = qr.payload_for(self.lea)
        res = self.post("/api/checkins", {"qrCode": payload})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["member"]["name"], "Lea Haddad")
        self.assertEqual(res.json()["checkIn"]["result"], "Allowed")

        res = self.post("/api/checkins/checkout", {"qrCode": payload})
        self.assertEqual(res.status_code, 200, res.content)

    def test_membership_id_still_works(self):
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.status_code, 201)

    def test_forged_or_edited_codes_are_refused(self):
        genuine = qr.payload_for(self.lea)
        edited = genuine.replace(f":{self.lea.id}:", f":{self.other.id}:")
        for code in [f"FFM1:{self.other.id}", edited, "hello", genuine + "x"]:
            res = self.post("/api/checkins", {"qrCode": code})
            self.assertEqual(res.status_code, 400, code)
            self.assertIn("qrCode", res.json()["error"])

    def test_needs_an_id_or_a_code(self):
        res = self.post("/api/checkins", {})
        self.assertEqual(res.status_code, 400)
        self.assertIn("membershipId", res.json()["error"])

    def test_member_gets_their_own_qr_code(self):
        self.client.post("/api/auth/logout")
        self.post("/api/members/login", {"username": "lea", "password": PASSWORD})
        res = self.client.get("/api/members/me/qr")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["membershipId"], self.lea.id)
        self.assertEqual(qr.member_id_from(res.json()["payload"]), self.lea.id)
        self.assertTrue(res.json()["qrCode"].startswith("data:image/svg+xml"))

    def test_qr_endpoint_needs_a_member_session(self):
        self.assertEqual(self.client.get("/api/members/me/qr").status_code, 401)

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog
from billing.models import Payment, PaymentMethod
from checkins.models import CheckIn
from training.models import TrainingEvent

from .models import AccessCardReissue, Member, Waiver

PASSWORD = "Password123!"


def make_member(name, username, email, branch="Hamra"):
    member = Member(
        name=name, email=email, phone="70123456", branch=branch, join_date=date.today(), username=username,
        subscription_expires_at=date.today() + timedelta(days=30),
    )
    member.set_password(PASSWORD)
    member.save()
    Payment.objects.create(
        member=member, amount=Decimal("35.00"), method="Card", method_detail="Card ending 4242",
        duration="1 Month", expires_at=member.subscription_expires_at, note="First payment",
    )
    Waiver.objects.create(
        member=member, signature_name=name, health_disclaimer_accepted=True, liability_waiver_accepted=True,
        waiver_version="1", signed_via=Waiver.SignedVia.ONLINE,
    )
    PaymentMethod.objects.create(
        member=member, method="Card", card_holder_name=name, card_last4="4242", card_expiry_month=12,
        card_expiry_year=2030,
    )
    CheckIn.objects.create(member=member, result="Allowed", branch=branch)
    TrainingEvent.objects.create(event_type="check_in", member=member, branch=branch, payload={"method": "qr"})
    return member


# User story (SCRUM-62): "As a member, I want to request an export or
# deletion of my personal data, so that I have control over my own privacy."
class MemberDataPrivacyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = make_member("Lea Haddad", "lea", "lea@example.com")
        cls.sami = make_member("Sami Khoury", "sami", "sami@example.com", branch="Jnah")

    def login(self, username):
        res = self.client.post("/api/members/login", {"username": username, "password": PASSWORD}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)

    def delete(self, **overrides):
        body = {"password": PASSWORD, "confirm": "DELETE", **overrides}
        return self.client.post("/api/members/me/delete", body, content_type="application/json")

    # --- export -------------------------------------------------------

    def test_export_requires_a_member_session(self):
        self.assertEqual(self.client.get("/api/members/me/export").status_code, 401)

    def test_export_is_a_json_download_with_everything_about_the_member(self):
        self.login("lea")
        res = self.client.get("/api/members/me/export")
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res["Content-Disposition"])
        data = res.json()

        self.assertEqual(data["profile"]["name"], "Lea Haddad")
        self.assertEqual(data["profile"]["email"], "lea@example.com")
        self.assertEqual(data["membership"]["plan"], "Basic")
        self.assertEqual([p["amount"] for p in data["payments"]], ["35.00"])
        self.assertEqual(len(data["checkIns"]), 1)
        self.assertEqual(data["waiver"]["signatureName"], "Lea Haddad")
        self.assertEqual(len(data["trainingEvents"]), 1)
        self.assertEqual(data["paymentMethod"]["cardLast4"], "4242")

    def test_export_never_contains_credentials_or_full_card_numbers(self):
        self.login("lea")
        body = self.client.get("/api/members/me/export").content.decode()
        self.assertNotIn("password", body.lower())
        self.assertNotIn(self.lea.password_hash, body)

    def test_export_contains_only_the_requesters_data(self):
        self.login("lea")
        body = self.client.get("/api/members/me/export").content.decode()
        self.assertNotIn("Sami", body)
        self.assertNotIn("sami@example.com", body)
        self.assertNotIn("Jnah", body)

    def test_a_member_cannot_export_someone_else(self):
        self.login("lea")
        # No id is accepted anywhere: a query param or path can't redirect the export.
        res = self.client.get(f"/api/members/me/export?memberId={self.sami.id}")
        self.assertEqual(res.json()["profile"]["id"], self.lea.id)
        self.assertEqual(self.client.get(f"/api/members/{self.sami.id}/export").status_code, 404)

    def test_export_is_audited(self):
        self.login("lea")
        self.client.get("/api/members/me/export")
        entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_DATA_EXPORTED)
        self.assertEqual(entry.actor_member, self.lea)
        self.assertEqual(entry.target_id, str(self.lea.id))

    # --- deletion -----------------------------------------------------

    def test_deletion_requires_a_member_session(self):
        self.assertEqual(self.delete().status_code, 401)

    def test_deletion_needs_the_confirmation_word_and_the_right_password(self):
        self.login("lea")
        self.assertEqual(self.delete(confirm="").status_code, 400)
        self.assertEqual(self.delete(confirm="delete me").status_code, 400)
        self.assertEqual(self.delete(password="wrong").status_code, 403)
        self.lea.refresh_from_db()
        self.assertEqual(self.lea.name, "Lea Haddad")
        self.assertEqual(self.client.get("/api/members/me").status_code, 200)

    def test_deletion_anonymizes_the_member_and_signs_them_out(self):
        self.login("lea")
        res = self.delete()
        self.assertEqual(res.status_code, 200, res.content)

        self.lea.refresh_from_db()
        self.assertEqual(self.lea.name, f"Deleted member #{self.lea.id}")
        self.assertNotIn("lea", self.lea.email)
        self.assertEqual(self.lea.phone, "")
        self.assertIsNone(self.lea.username)
        self.assertIsNone(self.lea.password_hash)
        self.assertEqual(self.lea.status, Member.Status.CANCELLED)
        self.assertEqual(self.lea.access_card_number, 2)

        self.assertEqual(self.client.get("/api/members/me").status_code, 401)

    def test_deleted_member_can_no_longer_log_in(self):
        self.login("lea")
        self.delete()
        res = self.client.post("/api/members/login", {"username": "lea", "password": PASSWORD}, content_type="application/json")
        self.assertEqual(res.status_code, 401)

    def test_deletion_keeps_payments_and_waiver_but_anonymizes_them(self):
        self.login("lea")
        self.delete()

        payment = Payment.objects.get(member=self.lea)
        self.assertEqual(payment.amount, Decimal("35.00"))
        waiver = Waiver.objects.get(member=self.lea)
        self.assertEqual(waiver.signature_name, "[removed]")
        self.assertTrue(waiver.liability_waiver_accepted)
        self.assertEqual(waiver.waiver_version, "1")
        self.assertEqual(CheckIn.objects.filter(member=self.lea).count(), 1)

    def test_deletion_removes_training_events_and_payment_method(self):
        AccessCardReissue.objects.create(member=self.lea, card_number=2, reason="Lost", note="Lea lost it")
        self.login("lea")
        self.delete()

        self.assertFalse(TrainingEvent.objects.filter(member=self.lea).exists())
        self.assertFalse(PaymentMethod.objects.filter(member=self.lea).exists())
        self.assertFalse(AccessCardReissue.objects.filter(member=self.lea).exists())

    def test_deletion_leaves_other_members_untouched(self):
        self.login("lea")
        self.delete()
        self.sami.refresh_from_db()
        self.assertEqual(self.sami.name, "Sami Khoury")
        self.assertTrue(TrainingEvent.objects.filter(member=self.sami).exists())
        self.assertTrue(Payment.objects.filter(member=self.sami).exists())

    def test_deletion_scrubs_audit_entries_but_keeps_them(self):
        self.login("lea")
        self.client.patch("/api/members/me", {"name": "Lea H", "phone": "99999999"}, content_type="application/json")
        before = AuditLog.objects.filter(actor_member=self.lea).count()
        self.assertGreater(before, 0)

        self.delete()

        entries = AuditLog.objects.filter(actor_member=self.lea)
        self.assertEqual(entries.count(), before + 1)
        for entry in entries:
            blob = f"{entry.actor_name}{entry.actor_username}{entry.summary}{entry.target_label}{entry.details}"
            self.assertNotIn("Lea", blob.replace("Deleted member", ""))
            self.assertNotIn("99999999", blob)
            self.assertIsNone(entry.ip_address)
        # Kept entries still say what happened.
        self.assertTrue(entries.filter(action=AuditLog.Action.MEMBER_PROFILE_UPDATED).exists())

    def test_deletion_is_audited(self):
        self.login("lea")
        self.delete()
        entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_DATA_DELETED)
        self.assertEqual(entry.actor_member, self.lea)
        self.assertEqual(entry.target_id, str(self.lea.id))
        self.assertNotIn("Lea", entry.summary + entry.actor_name + entry.target_label)
        self.assertLess(abs((timezone.now() - entry.created_at).total_seconds()), 60)

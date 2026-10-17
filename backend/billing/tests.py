from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from members.models import Member
from plans.models import MembershipPlan

from .models import Payment, PaymentMethod, _add_months

PASSWORD = "ChangeMe123!"


def _staff(username, full_name, permissions):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(
        full_name=full_name, email=f"{username}@gym.com", username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


# User story: "As a receptionist, I want to process membership renewals and update payment methods for
# existing members, so that recurring billing stays accurate for members who prefer in person help."
class RenewalAndPaymentMethodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="25.00")
        MembershipPlan.objects.create(name="Premium", price="50.00")
        _staff("desk", "Dana Desk", ["manage_members"])
        _staff("mkt", "Mark Eting", ["manage_marketing_campaigns"])
        today = timezone.localdate()
        cls.active = Member.objects.create(
            name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra", join_date=today,
            membership_plan="Basic", subscription_expires_at=today + timedelta(days=10),
        )
        cls.lapsed = Member.objects.create(
            name="Sami Khoury", email="sami@example.com", phone="2", branch="Jnah", join_date=today,
            membership_plan="Basic", subscription_expires_at=today - timedelta(days=3),
        )

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)
        self.today = timezone.localdate()

    def put_method(self, member, **body):
        return self.client.put(f"/api/members/{member.id}/payment-method", body, content_type="application/json")

    def renew(self, member, **body):
        payload = {"membershipPlan": "Basic", "method": "Cash", "duration": "1 Month", **body}
        return self.client.post(f"/api/members/{member.id}/payments", payload, content_type="application/json")

    def card(self, **overrides):
        return {
            "method": "Card", "cardHolderName": "Lea Haddad", "cardLast4": "4242",
            "cardExpiryMonth": 8, "cardExpiryYear": self.today.year + 2, **overrides,
        }

    # --- payment method on file ---
    def test_card_on_file_keeps_reference_details_only(self):
        res = self.put_method(self.active, **self.card())
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["summary"], f"Card ending 4242 (exp 08/{self.today.year + 2})")
        self.assertEqual(body["updatedBy"], "Dana Desk")
        self.assertFalse(body["cardExpired"])
        self.assertEqual(PaymentMethod.objects.get(member=self.active).card_last4, "4242")

    def test_full_card_number_or_non_digits_are_refused(self):
        for last4 in ("4242424242424242", "42a2", ""):
            res = self.put_method(self.active, **self.card(cardLast4=last4))
            self.assertEqual(res.status_code, 400, last4)
            self.assertIn("cardLast4", res.json()["error"])
        self.assertFalse(PaymentMethod.objects.exists())

    def test_card_needs_holder_and_expiry(self):
        res = self.put_method(self.active, method="Card", cardLast4="4242")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["error"]), {"cardHolderName", "cardExpiryMonth", "cardExpiryYear"})

    def test_expired_card_is_refused(self):
        last_month = self.today.replace(day=1) - timedelta(days=1)
        res = self.put_method(self.active, **self.card(cardExpiryMonth=last_month.month, cardExpiryYear=last_month.year))
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json()["error"]["cardExpiryYear"][0])

    def test_card_valid_this_month_is_accepted(self):
        res = self.put_method(self.active, **self.card(cardExpiryMonth=self.today.month, cardExpiryYear=self.today.year))
        self.assertEqual(res.status_code, 200, res.content)

    def test_switching_to_cash_clears_card_details(self):
        self.put_method(self.active, **self.card())
        res = self.put_method(self.active, method="Cash")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["summary"], "Cash")
        on_file = PaymentMethod.objects.get(member=self.active)
        self.assertEqual((on_file.card_last4, on_file.card_expiry_year), ("", None))

    def test_bank_transfer_needs_bank_and_account_digits(self):
        res = self.put_method(self.active, method="Bank Transfer")
        self.assertEqual(set(res.json()["error"]), {"bankName", "bankAccountLast4"})
        res = self.put_method(self.active, method="Bank Transfer", bankName=" Bank  Audi ", bankAccountLast4="7788")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["summary"], "Bank Audi account ending 7788")

    def test_flags_a_card_that_expires_before_the_next_renewal(self):
        Member.objects.filter(id=self.active.id).update(subscription_expires_at=date(self.today.year + 1, 6, 1))
        body = self.put_method(self.active, **self.card(cardExpiryMonth=12, cardExpiryYear=self.today.year)).json()
        self.assertTrue(body["cardExpiresBeforeRenewal"])

    # --- billing summary and quote ---
    def test_billing_summary_lists_method_and_newest_payments_first(self):
        self.put_method(self.active, **self.card())
        self.renew(self.active, method="Card")
        self.renew(self.active, duration="1 Year")
        res = self.client.get(f"/api/members/{self.active.id}/billing")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["member"]["id"], self.active.id)
        self.assertEqual(body["paymentMethod"]["cardLast4"], "4242")
        self.assertEqual(body["paymentCount"], 2)
        self.assertEqual([p["duration"] for p in body["payments"]], ["1 Year", "1 Month"])
        self.assertEqual(body["payments"][1]["methodDetail"], "Card ending 4242")

    def test_billing_summary_without_method_on_file(self):
        body = self.client.get(f"/api/members/{self.lapsed.id}/billing").json()
        self.assertIsNone(body["paymentMethod"])
        self.assertEqual(body["payments"], [])
        # The lapsed member reads as Frozen, not a stale Active.
        self.assertEqual(body["member"]["status"], "Frozen")

    def test_quote_for_early_renewal_stacks_on_current_expiry(self):
        res = self.client.get(f"/api/members/{self.active.id}/renewal-quote?membershipPlan=Basic&duration=1 Month")
        self.assertEqual(res.status_code, 200, res.content)
        expiry = self.today + timedelta(days=10)
        self.assertEqual(res.json(), {
            "amount": "25.00", "originalAmount": None, "promotion": None,
            "startsOn": expiry.isoformat(), "expiresAt": _add_months(expiry, 1).isoformat(),
        })

    def test_quote_for_lapsed_member_starts_today_with_yearly_discount(self):
        res = self.client.get(f"/api/members/{self.lapsed.id}/renewal-quote?membershipPlan=premium&duration=1 Year")
        body = res.json()
        self.assertEqual((body["amount"], body["originalAmount"]), ("580.00", "600.00"))
        self.assertEqual(body["startsOn"], self.today.isoformat())
        self.assertEqual(body["expiresAt"], _add_months(self.today, 12).isoformat())

    def test_quote_rejects_unknown_plan_and_duration(self):
        res = self.client.get(f"/api/members/{self.active.id}/renewal-quote?membershipPlan=Gold&duration=2 Weeks")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["error"]), {"membershipPlan", "duration"})

    # --- processing a renewal ---
    def test_renewal_with_card_on_file_extends_and_records_who_and_what(self):
        self.put_method(self.active, **self.card())
        res = self.renew(self.active, method="Card", expectedAmount="25.00")
        self.assertEqual(res.status_code, 201, res.content)
        payment = res.json()["payment"]
        self.assertEqual(payment["methodDetail"], "Card ending 4242")
        self.assertEqual(payment["recordedBy"], "Dana Desk")
        self.assertEqual(payment["note"], "Renewal")
        new_expiry = _add_months(self.today + timedelta(days=10), 1)
        self.assertEqual(res.json()["subscriptionExpiresAt"], new_expiry.isoformat())
        self.assertEqual(res.json()["status"], "Active")

    def test_paying_another_way_is_one_off(self):
        self.put_method(self.active, **self.card())
        res = self.renew(self.active, method="Cash")
        self.assertEqual(res.json()["payment"]["methodDetail"], "")
        self.assertEqual(PaymentMethod.objects.get(member=self.active).method, "Card")

    def test_lapsed_member_is_reactivated_from_today(self):
        res = self.renew(self.lapsed)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["status"], "Active")
        self.assertEqual(res.json()["subscriptionExpiresAt"], _add_months(self.today, 1).isoformat())
        self.assertEqual(res.json()["payment"]["note"], "Reactivation")

    def test_plan_can_change_at_renewal(self):
        res = self.renew(self.active, membershipPlan="Premium", expectedAmount="50.00")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Member.objects.get(id=self.active.id).membership_plan, "Premium")

    def test_expired_card_on_file_cannot_be_charged(self):
        last_month = self.today.replace(day=1) - timedelta(days=1)
        PaymentMethod.objects.create(
            member=self.active, method="Card", card_holder_name="Lea Haddad", card_last4="1111",
            card_expiry_month=last_month.month, card_expiry_year=last_month.year,
        )
        res = self.renew(self.active, method="Card")
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json()["error"]["method"][0])
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.renew(self.active, method="Cash").status_code, 201)

    def test_price_change_since_quote_is_refused(self):
        res = self.renew(self.active, expectedAmount="20.00")
        self.assertEqual(res.status_code, 409)
        self.assertIn("$25.00", res.json()["error"])
        self.assertEqual(res.json()["quote"]["amount"], "25.00")
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(Member.objects.get(id=self.active.id).subscription_expires_at, self.today + timedelta(days=10))

    def test_amount_is_never_taken_from_the_client(self):
        res = self.renew(self.active, amount="1.00")
        self.assertEqual(res.json()["payment"]["amount"], "25.00")

    def test_walk_in_registration_records_the_receptionist(self):
        res = self.client.post("/api/members", {
            "name": "Nour Saad", "email": "nour@example.com", "phone": "3", "branch": "Zalka",
            "membershipPlan": "Basic", "paymentMethod": "Cash", "paymentDuration": "1 Month",
            "liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True, "signatureName": "Nour Saad",
        }, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["firstPayment"]["recordedBy"], "Dana Desk")

    # --- access ---
    def test_needs_manage_members(self):
        urls = [
            ("get", f"/api/members/{self.active.id}/billing"),
            ("put", f"/api/members/{self.active.id}/payment-method"),
            ("get", f"/api/members/{self.active.id}/renewal-quote?membershipPlan=Basic&duration=1 Month"),
            ("post", f"/api/members/{self.active.id}/payments"),
        ]
        self.client.post("/api/auth/logout")
        for verb, url in urls:
            self.assertEqual(getattr(self.client, verb)(url, {}, content_type="application/json").status_code, 401, url)
        staff_login(self.client, "mkt", PASSWORD)
        for verb, url in urls:
            self.assertEqual(getattr(self.client, verb)(url, {}, content_type="application/json").status_code, 403, url)

    def test_unknown_member(self):
        self.assertEqual(self.client.get("/api/members/9999/billing").status_code, 404)
        self.assertEqual(self.put_method(Member(id=9999), method="Cash").status_code, 404)

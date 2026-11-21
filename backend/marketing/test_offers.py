from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from billing.models import Payment
from checkins.models import CheckIn
from classes.tests import PASSWORD, _member, _member_login, _staff
from members.models import Member
from notifications.models import MemberNotification, NotificationSettings
from plans.models import BranchPromotion, MembershipPlan
from retail.models import BranchStock, Product, Sale

from . import offers
from .models import CampaignRecipient, CampaignRedemption, MarketingCampaign

# User story: "As a marketing staff member, I want to create and schedule
# promotional campaigns with a target segment and offer code, so that I can
# launch promotions without needing developer help."


def _today():
    return timezone.localdate()


def _at(hour, day=None):
    return timezone.make_aware(datetime.combine(day or _today(), time(hour, 0)))


class OfferTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basic = MembershipPlan.objects.create(name="Basic", price="25.00")  # discounts capped at 20%
        cls.premium = MembershipPlan.objects.create(name="Premium", price="50.00", max_promo_discount_percent="30.00")
        cls.mkt = _staff("mkt", ["manage_marketing_campaigns"], job_title=StaffAccount.JobTitle.MARKETING_STAFF)
        cls.gm = _staff("gm", ["view_marketing_campaigns"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        cls.desk = _staff("desk", ["manage_members", "process_sales"], branch="Hamra",
                          job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.jnah_desk = _staff("jdesk", ["manage_members", "process_sales"], branch="Jnah",
                               job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.maya = _member("Maya Saad", "maya", days_valid=10)
        cls.omar = _member("Omar Haddad", "omar", days_valid=60)
        cls.rana = _member("Rana Khoury", "rana", branch="Jnah", days_valid=10)
        cls.water = Product.objects.create(name="Water", category="Drinks", price="2.00")
        cls.shaker = Product.objects.create(name="Shaker", category="Merchandise", price="12.50")
        for product in (cls.water, cls.shaker):
            for branch in ("Hamra", "Jnah"):
                BranchStock.objects.create(product=product, branch=branch, quantity=50)

    def _login(self, account):
        res = staff_login(self.client, account.username, PASSWORD)
        self.assertEqual(res.status_code, 200)

    def _campaign(self, code="SUMMER20", branch="Hamra", start=0, length=10, kind="Percent", value="20",
                  applies="Both", statuses=("Active",), **extra):
        return MarketingCampaign.objects.create(
            branch=branch, name=extra.pop("name", "Summer Push"), budget="500.00",
            start_date=_today() + timedelta(days=start), end_date=_today() + timedelta(days=start + length),
            offer_code=code, discount_type=kind, discount_value=Decimal(value), applies_to=applies,
            segment_statuses=list(statuses), **extra,
        )

    def _payload(self, **overrides):
        data = {
            "branch": "Hamra", "name": "Summer Push", "budget": "500.00",
            "startDate": str(_today()), "endDate": str(_today() + timedelta(days=10)),
            "offerCode": "summer20", "discountType": "Percent", "discountValue": "20", "appliesTo": "Both",
            "segment": {"statuses": ["Active"]},
        }
        data.update(overrides)
        return data

    def _quote(self, member, code="SUMMER20", plan="Basic", duration="1 Month"):
        params = {"membershipPlan": plan, "duration": duration}
        if code is not None:
            params["offerCode"] = code
        return self.client.get(f"/api/members/{member.id}/renewal-quote", params)

    def _pay(self, member, code="SUMMER20", plan="Basic", duration="1 Month", **extra):
        body = {"membershipPlan": plan, "method": "Cash", "duration": duration, "offerCode": code, **extra}
        return self.client.post(f"/api/members/{member.id}/payments", body, content_type="application/json")

    def _sell(self, items, member=None, code="SUMMER20", **extra):
        body = {
            "items": [{"productId": p.id, "quantity": q} for p, q in items], "paymentMethod": "Card",
            "memberId": member.id if member else None, "offerCode": code, **extra,
        }
        return self.client.post("/api/retail/sales", body, content_type="application/json")


class CreatingCampaignTests(OfferTestBase):
    def setUp(self):
        self._login(self.mkt)

    def test_marketing_staff_create_a_campaign_with_an_offer_and_segment(self):
        res = self.client.post("/api/marketing/campaigns", self._payload(
            segment={"statuses": ["Active"], "plans": ["basic"], "renewalWithinDays": 14},
            maxRedemptions=50, offerMessage="  Summer is here!  ",
        ), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data["offerCode"], "SUMMER20")
        self.assertEqual(data["discountLabel"], "20% off")
        self.assertEqual(data["status"], "Running")
        self.assertEqual(data["offerMessage"], "Summer is here!")
        self.assertEqual(data["segment"]["plans"], ["Basic"])
        self.assertEqual(
            data["segment"]["description"], "Active members at Hamra on the Basic plan, renewing in the next 14 days",
        )
        # Maya renews in 10 days; Omar in 60.
        self.assertEqual(data["audience"]["count"], 1)
        self.assertEqual(data["results"], {
            "sent": 0, "redeemed": 0, "discountGiven": "0.00", "revenue": "0.00",
            "signups": 0, "signupDiscountGiven": "0.00", "signupRevenue": "0.00", "totalRevenue": "0.00",
        })
        entry = AuditLog.objects.get(action=AuditLog.Action.CAMPAIGN_CREATED)
        self.assertIn("with offer SUMMER20 (20% off)", entry.summary)

    def test_a_campaign_without_an_offer_still_works_as_before(self):
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Billboards", "budget": "900.00", "startDate": "2026-01-01", "endDate": "2026-01-31",
        }, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["offerCode"], "")

    def test_the_code_must_look_like_a_code(self):
        for bad in ("ab", "SUM!", "X" * 21):
            res = self.client.post("/api/marketing/campaigns", self._payload(offerCode=bad), content_type="application/json")
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("offerCode", res.json()["error"])
        res = self.client.post("/api/marketing/campaigns", self._payload(offerCode=" back to-gym 5 "),
                               content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["offerCode"], "BACKTO-GYM5")

    def test_an_offer_needs_its_terms(self):
        res = self.client.post("/api/marketing/campaigns", self._payload(discountType="", discountValue=None, appliesTo=""),
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["error"]), {"discountType", "discountValue", "appliesTo"})

    def test_discount_limits(self):
        res = self.client.post("/api/marketing/campaigns", self._payload(discountValue="120"), content_type="application/json")
        self.assertIn("100", res.json()["error"]["discountValue"][0])
        res = self.client.post("/api/marketing/campaigns", self._payload(discountValue="0"), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/marketing/campaigns", self._payload(discountType="Fixed", discountValue="5000"),
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_an_offer_cannot_be_scheduled_in_the_past(self):
        yesterday = str(_today() - timedelta(days=1))
        res = self.client.post("/api/marketing/campaigns", self._payload(startDate=yesterday), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("startDate", res.json()["error"])
        res = self.client.post("/api/marketing/campaigns", self._payload(startDate="2026-01-01", endDate="2026-01-05"),
                               content_type="application/json")
        self.assertIn("endDate", res.json()["error"])

    def test_a_code_cannot_be_shared_by_overlapping_campaigns(self):
        self._campaign(code="SUMMER20", start=0, length=10, branch="Jnah")
        res = self.client.post("/api/marketing/campaigns", self._payload(
            startDate=str(_today() + timedelta(days=5)), endDate=str(_today() + timedelta(days=20)),
        ), content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertIn('already used by "Summer Push" at Jnah', res.json()["error"]["offerCode"][0])
        # After the first one ends it's free again...
        res = self.client.post("/api/marketing/campaigns", self._payload(
            startDate=str(_today() + timedelta(days=11)), endDate=str(_today() + timedelta(days=20)),
        ), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)

    def test_a_cancelled_campaigns_code_can_be_reused(self):
        self._campaign(code="SUMMER20", is_active=False)
        res = self.client.post("/api/marketing/campaigns", self._payload(), content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)

    def test_segment_checks(self):
        res = self.client.post("/api/marketing/campaigns", self._payload(segment={"plans": ["Gold"]}),
                               content_type="application/json")
        self.assertIn("Gold", str(res.json()["error"]["segment"]))
        res = self.client.post("/api/marketing/campaigns", self._payload(
            segment={"statuses": ["Cancelled"], "renewalWithinDays": 7},
        ), content_type="application/json")
        self.assertIn("renewalWithinDays", res.json()["error"]["segment"])
        res = self.client.post("/api/marketing/campaigns", self._payload(segment={"statuses": []}),
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/marketing/campaigns", self._payload(segment={"inactiveDays": 3}),
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)

    def test_only_marketing_can_create(self):
        self.client.logout()
        self._login(self.desk)
        res = self.client.post("/api/marketing/campaigns", self._payload(), content_type="application/json")
        self.assertEqual(res.status_code, 403)


class EditingCampaignTests(OfferTestBase):
    def setUp(self):
        self._login(self.mkt)

    def _patch(self, campaign, body):
        return self.client.patch(f"/api/marketing/campaigns/{campaign.id}", body, content_type="application/json")

    def test_a_scheduled_offer_can_still_be_changed(self):
        campaign = self._campaign(start=3)
        res = self._patch(campaign, {"discountValue": "25", "segment": {"statuses": ["Active", "Frozen"]}})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["discountLabel"], "25% off")
        self.assertEqual(res.json()["segment"]["statuses"], ["Active", "Frozen"])
        res = self._patch(campaign, {"startDate": str(_today() - timedelta(days=1))})
        self.assertEqual(res.status_code, 400)

    def test_once_running_the_offer_and_audience_are_fixed(self):
        campaign = self._campaign(start=0)
        for body in ({"discountValue": "30"}, {"offerCode": "OTHER1"}, {"segment": {"statuses": ["Frozen"]}},
                     {"startDate": str(_today() + timedelta(days=1))}, {"branch": "Jnah"}):
            res = self._patch(campaign, body)
            self.assertEqual(res.status_code, 400, body)
            self.assertIn("already started", str(res.json()["error"]))
        # The rest can change, and sending back unchanged values is fine (the form sends everything).
        res = self._patch(campaign, {
            "amountSpent": "120.00", "endDate": str(_today() + timedelta(days=30)), "offerCode": "summer20",
            "discountValue": "20.00", "segment": {"statuses": ["Active"]}, "name": "Summer Push (extended)",
        })
        self.assertEqual(res.status_code, 200, res.content)
        earlier = self._campaign(code="EARLY", start=-5)
        res = self._patch(earlier, {"endDate": str(_today() - timedelta(days=1))})
        self.assertIn("cancel the campaign", res.json()["error"]["endDate"][0])

    def test_an_offer_cannot_be_added_to_a_campaign_already_running(self):
        campaign = self._campaign(code="", kind="", value="0", applies="")
        res = self._patch(campaign, {"offerCode": "LATE10", "discountType": "Percent", "discountValue": "10", "appliesTo": "Shop"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("before a campaign starts", res.json()["error"]["offerCode"][0])

    def test_a_cancelled_campaign_cannot_be_restarted(self):
        campaign = self._campaign(is_active=False)
        res = self._patch(campaign, {"isActive": True})
        self.assertEqual(res.status_code, 400)
        self.assertIn("isActive", res.json()["error"])

    def test_the_use_limit_cannot_go_below_what_has_been_used(self):
        campaign = self._campaign(start=0, max_redemptions=5)
        for member in (self.maya, self.omar):
            CampaignRedemption.objects.create(campaign=campaign, member=member, use="Shop", amount_before=10,
                                              discount=2, amount_paid=8)
        res = self._patch(campaign, {"maxRedemptions": 1})
        self.assertIn("used 2 times", res.json()["error"]["maxRedemptions"][0])
        self.assertEqual(self._patch(campaign, {"maxRedemptions": 10}).status_code, 200)

    def test_cancelling_tells_everyone_who_got_the_offer_and_has_not_used_it(self):
        campaign = self._campaign(start=0)
        offers.send_due(now=_at(10))
        CampaignRedemption.objects.create(campaign=campaign, member=self.maya, use="Shop", amount_before=10,
                                          discount=2, amount_paid=8)
        res = self._patch(campaign, {"isActive": False})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["withdrawnNotices"], 1)
        self.assertTrue(MemberNotification.objects.filter(recipient=self.omar, title__startswith="Offer withdrawn").exists())
        self.assertFalse(MemberNotification.objects.filter(recipient=self.maya, title__startswith="Offer withdrawn").exists())
        self.assertIn("told the offer is withdrawn", AuditLog.objects.filter(action=AuditLog.Action.CAMPAIGN_UPDATED).first().summary)

    def test_detail_shows_audience_and_recent_uses(self):
        campaign = self._campaign(start=0)
        CampaignRedemption.objects.create(campaign=campaign, member=self.maya, use="Shop", amount_before=10,
                                          discount=2, amount_paid=8, redeemed_by=self.desk)
        res = self.client.get(f"/api/marketing/campaigns/{campaign.id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["audience"]["count"], 2)
        self.assertEqual(res.json()["recentUses"][0]["member"], "Maya Saad")
        self.assertEqual(res.json()["results"]["redeemed"], 1)


class AudienceTests(OfferTestBase):
    def _ids(self, **segment):
        draft = MarketingCampaign(branch="Hamra", segment_statuses=segment.pop("statuses", ["Active"]), **segment)
        return set(offers.audience(draft).values_list("name", flat=True))

    def test_each_filter(self):
        lapsed = _member("Lapsed Lea", "lea", days_valid=-3)  # still marked Active, but it ran out
        _member("Frozen Fadi", "fadi", status=Member.Status.FROZEN)
        _member("Gone Ghada", "ghada", status=Member.Status.CANCELLED)
        erased = _member("Deleted member", "erased", status=Member.Status.CANCELLED)
        Member.objects.filter(pk=erased.pk).update(email=f"deleted-member-{erased.pk}@deleted.invalid")
        Member.objects.filter(pk=self.omar.pk).update(membership_plan="Premium", join_date=_today() - timedelta(days=100))

        self.assertEqual(self._ids(), {"Maya Saad", "Omar Haddad"})  # Rana is at Jnah
        self.assertEqual(self._ids(statuses=["Frozen"]), {"Lapsed Lea", "Frozen Fadi"})
        self.assertEqual(self._ids(statuses=["Cancelled"]), {"Gone Ghada"})
        self.assertEqual(self._ids(segment_plans=["Premium"]), {"Omar Haddad"})
        self.assertEqual(self._ids(segment_renewal_within_days=14), {"Maya Saad"})
        self.assertEqual(self._ids(segment_joined_within_days=30), {"Maya Saad"})
        self.assertNotIn(lapsed.name, self._ids(statuses=["Active"]))

    def test_inactive_means_no_allowed_check_in_in_that_many_days(self):
        CheckIn.objects.create(member=self.maya, result=CheckIn.Result.ALLOWED, branch="Hamra")
        old = CheckIn.objects.create(member=self.omar, result=CheckIn.Result.ALLOWED, branch="Hamra")
        CheckIn.objects.filter(pk=old.pk).update(checked_in_at=timezone.now() - timedelta(days=45))
        CheckIn.objects.create(member=self.omar, result=CheckIn.Result.DENIED, branch="Hamra", reason="Frozen")
        self.assertEqual(self._ids(segment_inactive_days=30), {"Omar Haddad"})

    def test_preview_counts_who_it_reaches_and_how(self):
        NotificationSettings.objects.create(member=self.omar, offers=False)
        _member("Nour Email-off", "nour")
        NotificationSettings.objects.create(member=Member.objects.get(username="nour"), email=False)
        self._login(self.mkt)
        res = self.client.post("/api/marketing/audience", {"branch": "Hamra", "segment": {"statuses": ["Active"]}},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {
            "count": 3, "reachable": 2, "byEmail": 1, "optedOut": 1, "description": "Active members at Hamra",
        })


class LaunchTests(OfferTestBase):
    def test_the_offer_goes_out_on_the_start_date_during_the_day(self):
        campaign = self._campaign(start=0, offer_message="Summer is here!")
        self.assertEqual(offers.send_due(now=_at(7)), 0)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(offers.send_due(now=_at(10)), 2)
        self.assertEqual(set(campaign.recipients.values_list("member__username", flat=True)), {"maya", "omar"})
        note = MemberNotification.objects.get(recipient=self.maya)
        self.assertEqual(note.kind, MemberNotification.Kind.OFFER)
        self.assertIn("20% off", note.title)
        self.assertTrue(note.message.startswith("Summer is here! Use code SUMMER20 at the Hamra front desk or shop"))
        self.assertEqual(len(mail.outbox), 2)
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.launched_at)
        # Nobody gets it twice.
        self.assertEqual(offers.send_due(now=_at(11)), 0)
        self.assertEqual(MemberNotification.objects.count(), 2)

    def test_members_who_join_the_segment_later_get_it_too(self):
        self._campaign(start=0)
        offers.send_due(now=_at(10))
        _member("Late Layla", "layla")
        self.assertEqual(offers.send_due(now=_at(12)), 1)
        self.assertTrue(MemberNotification.objects.filter(recipient__username="layla").exists())

    def test_not_sent_before_the_start_or_when_switched_off(self):
        self._campaign(start=2)
        self._campaign(code="QUIET", start=0, notify_audience=False)
        self._campaign(code="GONE", start=0, is_active=False)
        self._campaign(code="", kind="", value="0", applies="")  # no offer at all
        self.assertEqual(offers.send_due(now=_at(10)), 0)

    def test_members_who_turned_offers_off_are_skipped_and_email_follows_their_setting(self):
        campaign = self._campaign(start=0)
        NotificationSettings.objects.create(member=self.omar, offers=False)
        NotificationSettings.objects.create(member=self.maya, email=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(offers.send_due(now=_at(10)), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(campaign.recipients.get(member=self.maya).by_email)
        self.assertFalse(campaign.recipients.filter(member=self.omar).exists())
        # Turning offers back on while it runs still gets it to them.
        NotificationSettings.objects.filter(member=self.omar).update(offers=True)
        self.assertEqual(offers.send_due(now=_at(11)), 1)

    def test_the_reminders_command_also_sends_offers(self):
        from io import StringIO

        from django.core.management import call_command
        from unittest import mock

        self._campaign(start=0)
        out = StringIO()
        with mock.patch("django.utils.timezone.now", return_value=_at(10)):
            call_command("send_reminders", stdout=out)
        self.assertIn("Sent 2 offers.", out.getvalue())


class MembershipRedemptionTests(OfferTestBase):
    def setUp(self):
        self._login(self.desk)

    def test_quote_with_a_code(self):
        self._campaign(value="20")
        res = self._quote(self.maya)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["amount"], "20.00")
        self.assertEqual(res.json()["originalAmount"], "25.00")
        self.assertEqual(res.json()["offerCode"], "SUMMER20")
        self.assertEqual(res.json()["offerDiscount"], "5.00")
        year = self._quote(self.maya, duration="1 Year").json()
        self.assertEqual(year["amount"], "220.00")  # 300 - 60 (20%) - 20 annual prepay
        self.assertEqual(year["originalAmount"], "300.00")

    def test_codes_are_capped_by_the_plans_discount_limit(self):
        self._campaign(value="50", code="HALF")
        res = self._quote(self.maya, code="half").json()
        self.assertEqual(res["amount"], "20.00")
        self.assertIn("Capped at 20%", res["offerNote"])

    def test_a_better_branch_promotion_wins_and_the_code_is_not_used(self):
        BranchPromotion.objects.create(plan=self.basic, branch="Hamra", name="Hamra Opening", discount_value="20",
                                       start_date=_today(), end_date=_today() + timedelta(days=5))
        self._campaign(value="10")
        res = self._quote(self.maya).json()
        self.assertEqual(res["amount"], "20.00")
        self.assertIsNone(res["offerCode"])
        self.assertIn('"Hamra Opening" already gives a better price', res["offerNote"])
        self.assertEqual(self._pay(self.maya, expectedAmount="20.00").status_code, 201)
        self.assertFalse(CampaignRedemption.objects.exists())

    def test_paying_with_a_code_records_the_use(self):
        campaign = self._campaign(value="3", kind="Fixed")
        res = self._pay(self.maya, expectedAmount="22.00")
        self.assertEqual(res.status_code, 201, res.content)
        payment = Payment.objects.get(member=self.maya)
        self.assertEqual(payment.amount, Decimal("22.00"))
        self.assertIn("offer SUMMER20 (-$3.00)", payment.note)
        used = CampaignRedemption.objects.get()
        self.assertEqual((used.campaign, used.member, used.payment, used.use), (campaign, self.maya, payment, "Membership"))
        self.assertEqual((used.amount_before, used.discount, used.amount_paid), (Decimal("25.00"), Decimal("3.00"), Decimal("22.00")))
        entry = AuditLog.objects.get(action=AuditLog.Action.PAYMENT_RECORDED)
        self.assertEqual(entry.details["offerCode"], "SUMMER20")
        # One use per member.
        res = self._pay(self.maya)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already used SUMMER20", res.json()["error"]["offerCode"][0])

    def test_the_price_check_uses_the_discounted_price(self):
        self._campaign()
        res = self._pay(self.maya, expectedAmount="25.00")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["quote"]["amount"], "20.00")

    def test_codes_that_cannot_be_used(self):
        self._campaign(code="SHOPONLY", applies="Shop")
        self._campaign(code="SOON", start=3)
        self._campaign(code="OLD", start=-20, length=5)
        self._campaign(code="PULLED", is_active=False)
        self._campaign(code="JNAH10", branch="Jnah")
        cases = {
            "NOPE": 'no offer with the code "NOPE"',
            "shoponly": "is for shop purchases, not membership renewals",
            "SOON": "isn't on yet",
            "OLD": "ended on",
            "PULLED": "withdrawn",
            "JNAH10": "is for Jnah members, and Maya Saad is a Hamra member",
        }
        for code, message in cases.items():
            res = self._quote(self.maya, code=code)
            self.assertEqual(res.status_code, 400, code)
            self.assertIn(message, res.json()["error"]["offerCode"][0], code)

    def test_only_the_segment_can_use_it_but_recipients_keep_it(self):
        campaign = self._campaign(segment_renewal_within_days=14)
        res = self._quote(self.omar)  # renews in 60 days
        self.assertEqual(res.status_code, 400)
        self.assertIn("isn't for Omar Haddad", res.json()["error"]["offerCode"][0])
        # Sent the offer while in the segment, Omar keeps it after leaving it.
        CampaignRecipient.objects.create(campaign=campaign, member=self.omar)
        self.assertEqual(self._quote(self.omar).status_code, 200)

    def test_a_capped_offer_runs_out(self):
        campaign = self._campaign(max_redemptions=1)
        self.assertEqual(self._pay(self.maya).status_code, 201)
        res = self._quote(self.omar)
        self.assertIn("fully claimed", res.json()["error"]["offerCode"][0])
        # And if it runs out between the check and the charge, nothing is charged.
        with self.assertRaises(offers.OfferError):
            Payment.record(self.omar, "Basic", "Cash", "1 Month", offer=campaign)
        self.assertFalse(Payment.objects.filter(member=self.omar).exists())

    def test_the_same_member_at_two_desks_at_once(self):
        campaign = self._campaign()
        CampaignRedemption.objects.create(campaign=campaign, member=self.maya, use="Shop", amount_before=10,
                                          discount=2, amount_paid=8)
        with self.assertRaisesMessage(offers.OfferError, "one use per member"):
            offers.redeem(campaign, self.maya, "Membership", amount_before=25, discount=5, amount_paid=20)


class ShopRedemptionTests(OfferTestBase):
    def setUp(self):
        self._login(self.desk)

    def test_a_sale_with_a_code(self):
        campaign = self._campaign(value="10")
        res = self._sell([(self.shaker, 2)], member=self.maya, expectedTotal="22.50")
        self.assertEqual(res.status_code, 201, res.content)
        sale = res.json()
        self.assertEqual((sale["subtotal"], sale["discount"], sale["total"], sale["offerCode"]),
                         ("25.00", "2.50", "22.50", "SUMMER20"))
        used = CampaignRedemption.objects.get()
        self.assertEqual((used.campaign, used.sale_id, used.amount_paid), (campaign, sale["id"], Decimal("22.50")))
        self.assertIn("with offer SUMMER20 (-$2.50)", AuditLog.objects.get(action=AuditLog.Action.RETAIL_SALE).summary)

    def test_the_till_can_check_a_code_first(self):
        self._campaign(value="10")
        res = self.client.get("/api/retail/offer", {"code": "summer20", "memberId": self.maya.id, "subtotal": "25.00"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["discount"], res.json()["total"]), ("2.50", "22.50"))
        res = self.client.get("/api/retail/offer", {"code": "summer20", "subtotal": "25.00"})
        self.assertIn("Add the member", res.json()["error"]["offerCode"][0])

    def test_a_code_needs_a_member_on_the_sale(self):
        self._campaign()
        res = self._sell([(self.water, 1)])
        self.assertEqual(res.status_code, 400)
        self.assertIn("Add the member", res.json()["error"]["offerCode"][0])
        self.assertEqual(Sale.objects.count(), 0)

    def test_a_renewals_only_code_or_another_branch(self):
        self._campaign(code="RENEW", applies="Membership")
        res = self._sell([(self.water, 1)], member=self.maya, code="RENEW")
        self.assertIn("is for membership renewals, not shop purchases", res.json()["error"]["offerCode"][0])
        self._campaign(code="HAMRA5")
        self.client.logout()
        self._login(self.jnah_desk)
        res = self._sell([(self.water, 1)], member=self.maya, code="HAMRA5")
        self.assertIn("is a Hamra offer - it can't be used at Jnah", res.json()["error"]["offerCode"][0])

    def test_a_fixed_discount_never_goes_below_zero(self):
        self._campaign(kind="Fixed", value="5")
        res = self._sell([(self.water, 1)], member=self.maya)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["discount"], res.json()["total"]), ("2.00", "0.00"))

    def test_cash_must_cover_the_discounted_total(self):
        self._campaign(value="10")
        res = self._sell([(self.shaker, 2)], member=self.maya, paymentMethod="Cash", amountTendered="22.50")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["changeDue"], "0.00")

    def test_voiding_the_sale_gives_the_use_back(self):
        self._campaign()
        sale_id = self._sell([(self.water, 1)], member=self.maya).json()["id"]
        res = self._sell([(self.water, 1)], member=self.maya)
        self.assertIn("already used", res.json()["error"]["offerCode"][0])
        res = self.client.post(f"/api/retail/sales/{sale_id}/void", {"reason": "Rang up twice"}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIsNotNone(CampaignRedemption.objects.get(sale_id=sale_id).voided_at)
        self.assertEqual(self._sell([(self.water, 1)], member=self.maya).status_code, 201)


class MemberSideTests(OfferTestBase):
    def test_members_see_the_offers_they_can_still_use(self):
        campaign = self._campaign()
        self._campaign(code="NOTFORME", segment_plans=["Premium"], name="Premium push")
        offers.send_due(now=_at(10))
        _member_login(self.client, "maya")
        res = self.client.get("/api/members/me/offers")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([o["code"] for o in res.json()["results"]], ["SUMMER20"])
        CampaignRedemption.objects.create(campaign=campaign, member=self.maya, use="Shop", amount_before=10,
                                          discount=2, amount_paid=8)
        self.assertEqual(self.client.get("/api/members/me/offers").json()["results"], [])

    def test_members_can_turn_offers_off(self):
        _member_login(self.client, "maya")
        res = self.client.patch("/api/members/me/reminders", {"offers": False}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(res.json()["settings"]["offers"])
        self.assertFalse(NotificationSettings.objects.get(member=self.maya).offers)

    def test_offers_need_a_member_session(self):
        self.assertEqual(self.client.get("/api/members/me/offers").status_code, 401)


class ReportTests(OfferTestBase):
    def test_the_general_managers_report_shows_each_offers_results(self):
        campaign = self._campaign()
        offers.send_due(now=_at(10))
        CampaignRedemption.objects.create(campaign=campaign, member=self.maya, use="Shop", amount_before="10.00",
                                          discount="2.00", amount_paid="8.00")
        self._login(self.gm)
        res = self.client.get("/api/marketing/report", {"branch": "Hamra"})
        row = res.json()["branches"][0]["campaigns"][0]
        self.assertEqual(row["offerCode"], "SUMMER20")
        self.assertEqual(row["results"], {
            "sent": 2, "redeemed": 1, "discountGiven": "2.00", "revenue": "8.00",
            "signups": 0, "signupDiscountGiven": "0.00", "signupRevenue": "0.00", "totalRevenue": "8.00",
        })


# User story: "As a marketing staff member, I want to track sign-ups and
# redemptions generated by each individual campaign, so that I can measure
# ROI and reallocate budget accordingly."
#
# A sign-up is a brand new member's first payment, made while registering -
# there's no existing Member row yet for check_offer's member-shaped checks
# (one-use-per-member, audience) to run against, so they're skipped; the
# branch, running-window and capped checks still apply.
class SignupRedemptionTests(OfferTestBase):
    def _walk_in(self, branch="Hamra", plan="Basic", code="SUMMER20", **extra):
        body = {
            "name": "Tina Nassar", "email": "tina@example.com", "phone": "71111111", "branch": branch,
            "membershipPlan": plan, "paymentMethod": "Cash", "paymentDuration": "1 Month",
            "liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True, "signatureName": "Tina Nassar",
            "offerCode": code, **extra,
        }
        return self.client.post("/api/members", body, content_type="application/json")

    def _signup(self, branch="Hamra", plan="Basic", code="SUMMER20", **extra):
        body = {
            "name": "Tina Nassar", "email": "tina@example.com", "phone": "71111111", "branch": branch,
            "membershipPlan": plan, "username": "tina", "password": "Password123!",
            "paymentMethod": "Cash", "paymentDuration": "1 Month",
            "liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True, "signatureName": "Tina Nassar",
            "offerCode": code, **extra,
        }
        return self.client.post("/api/members/signup", body, content_type="application/json")

    def _registration_quote(self, branch="Hamra", plan="Basic", duration="1 Month", code="SUMMER20"):
        params = {"membershipPlan": plan, "duration": duration}
        if branch is not None:
            params["branch"] = branch
        if code is not None:
            params["offerCode"] = code
        return self.client.get("/api/members/registration-quote", params)

    def test_registration_quote_previews_the_discount(self):
        self._campaign(value="20")
        res = self._registration_quote()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["amount"], "20.00")
        self.assertEqual(res.json()["originalAmount"], "25.00")
        self.assertEqual(res.json()["offerCode"], "SUMMER20")
        self.assertEqual(res.json()["offerDiscount"], "5.00")

    def test_registration_quote_without_a_code_is_unaffected(self):
        self._campaign()
        res = self._registration_quote(code=None)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["amount"], "25.00")
        self.assertNotIn("offerCode", res.json())

    def test_a_walk_in_registration_with_a_code_records_a_signup_redemption(self):
        campaign = self._campaign(value="3", kind="Fixed")
        self._login(self.desk)
        res = self._walk_in()
        self.assertEqual(res.status_code, 201, res.content)
        member = Member.objects.get(email="tina@example.com")
        payment = Payment.objects.get(member=member)
        self.assertEqual(payment.amount, Decimal("22.00"))
        self.assertIn("offer SUMMER20 (-$3.00)", payment.note)
        used = CampaignRedemption.objects.get()
        self.assertEqual(
            (used.campaign, used.member, used.payment, used.use), (campaign, member, payment, "Signup"),
        )
        self.assertEqual(
            (used.amount_before, used.discount, used.amount_paid),
            (Decimal("25.00"), Decimal("3.00"), Decimal("22.00")),
        )
        entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_REGISTERED)
        self.assertEqual(entry.details["offerCode"], "SUMMER20")
        self.assertIn("with offer SUMMER20", entry.summary)

    def test_an_online_signup_with_a_code_records_a_signup_redemption(self):
        campaign = self._campaign(value="20", kind="Percent")
        res = self._signup()
        self.assertEqual(res.status_code, 201, res.content)
        member = Member.objects.get(username="tina")
        payment = Payment.objects.get(member=member)
        self.assertEqual(payment.amount, Decimal("20.00"))
        used = CampaignRedemption.objects.get()
        self.assertEqual((used.campaign, used.member, used.use), (campaign, member, "Signup"))
        entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_SIGNED_UP)
        self.assertEqual(entry.details["offerCode"], "SUMMER20")

    def test_two_new_members_can_each_use_the_same_code(self):
        self._campaign(value="3", kind="Fixed")
        self._login(self.desk)
        first = self._walk_in()
        self.assertEqual(first.status_code, 201, first.content)
        second = self._walk_in(
            email="rita@example.com", phone="71222222", signatureName="Rita Fares", name="Rita Fares",
        )
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(CampaignRedemption.objects.filter(use="Signup").count(), 2)

    def test_a_shop_only_code_cannot_be_used_at_registration(self):
        self._campaign(code="SHOPONLY", applies="Shop")
        res = self._registration_quote(code="shoponly")
        self.assertEqual(res.status_code, 400)
        self.assertIn("is for shop purchases, not new member sign-ups", res.json()["error"]["offerCode"][0])

    def test_codes_that_cannot_be_used_at_registration(self):
        self._campaign(code="SOON", start=3)
        self._campaign(code="OLD", start=-20, length=5)
        self._campaign(code="PULLED", is_active=False)
        self._campaign(code="JNAH10", branch="Jnah")
        cases = {
            "NOPE": 'no offer with the code "NOPE"',
            "SOON": "isn't on yet",
            "OLD": "ended on",
            "PULLED": "withdrawn",
            "JNAH10": "it can't be used at Hamra",
        }
        for code, message in cases.items():
            res = self._registration_quote(code=code)
            self.assertEqual(res.status_code, 400, code)
            self.assertIn(message, res.json()["error"]["offerCode"][0], code)

    def test_a_signup_offer_is_not_limited_by_the_target_segment(self):
        # Segment targeting (status/plan/renewal window) is only meaningful
        # for an existing member - a brand new sign-up is never "Active",
        # never on a plan yet, so a segment-restricted code must still work.
        self._campaign(segment_plans=["Premium"], segment_renewal_within_days=14)
        res = self._registration_quote()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["offerCode"], "SUMMER20")

    def test_a_capped_offer_runs_out_for_signups_too(self):
        self._campaign(max_redemptions=1)
        self._login(self.desk)
        first = self._walk_in()
        self.assertEqual(first.status_code, 201, first.content)
        res = self._registration_quote()
        self.assertIn("fully claimed", res.json()["error"]["offerCode"][0])
        second = self._walk_in(
            email="rita@example.com", phone="71222222", signatureName="Rita Fares", name="Rita Fares",
        )
        self.assertEqual(second.status_code, 400)
        self.assertIn("offerCode", second.json()["error"])
        self.assertFalse(Member.objects.filter(email="rita@example.com").exists())

    def test_a_membership_redemption_does_not_count_as_a_signup(self):
        # An existing member renewing with a code is still "Membership", not
        # "Signup" - the split in offers.results() depends on this.
        self._campaign(value="3", kind="Fixed")
        self._login(self.desk)
        res = self.client.post(
            f"/api/members/{self.maya.id}/payments",
            {"membershipPlan": "Basic", "method": "Cash", "duration": "1 Month", "offerCode": "SUMMER20"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        used = CampaignRedemption.objects.get()
        self.assertEqual(used.use, "Membership")

    def test_results_splits_signups_from_other_redemptions(self):
        campaign = self._campaign(value="3", kind="Fixed")
        self._login(self.desk)
        self.assertEqual(self._walk_in().status_code, 201)  # Signup: paid 22.00, discount 3.00
        CampaignRedemption.objects.create(
            campaign=campaign, member=self.maya, use="Shop", amount_before="10.00", discount="2.00",
            amount_paid="8.00",
        )
        result = offers.results([campaign.id])[campaign.id]
        self.assertEqual(result["signups"], 1)
        self.assertEqual(result["signupDiscountGiven"], "3.00")
        self.assertEqual(result["signupRevenue"], "22.00")
        self.assertEqual(result["redeemed"], 1)
        self.assertEqual(result["discountGiven"], "2.00")
        self.assertEqual(result["revenue"], "8.00")
        self.assertEqual(result["totalRevenue"], "30.00")

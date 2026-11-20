from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from classes.tests import PASSWORD, _staff
from finance.models import Expense
from notifications.models import StaffNotification
from retail.models import BranchStock, Product

from .models import ProductSourcing, PurchaseOrder, Supplier

BARS = {"productId": None, "quantity": 20}
SPRAY = {"description": "Disinfectant spray 5 L", "quantity": 2, "unitCost": "15.00"}


# User story: "As a branch manager, I want to submit supply reorder requests
# through the system, so that restocking doesn't depend on manual phone calls
# to vendors."
class PurchasingBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", ["manage_retail_products"], branch="Hamra")
        _staff("jnah_bm", ["manage_retail_products"], branch="Jnah")
        cls.gm = _staff("gm", ["manage_retail_products", "approve_purchase_orders", "view_all_branches"],
                        job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        cls.admin = _staff("admin", ["approve_purchase_orders", "view_all_branches"],
                           job_title=StaffAccount.JobTitle.SYSTEM_ADMINISTRATOR)
        _staff("desk", ["process_sales"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.nutri = Supplier.objects.create(name="NutriCo", email="orders@nutrico.test", lead_time_days=3)
        cls.clean = Supplier.objects.create(name="CleanPro", email="sales@cleanpro.test", lead_time_days=1)
        cls.old = Supplier.objects.create(name="Old Supplies", email="old@old.test", is_active=False)
        cls.bars = Product.objects.create(name="Protein bar", category="Supplements", price=Decimal("3.00"))
        cls.water = Product.objects.create(name="Water 500 ml", category="Drinks", price=Decimal("1.00"))
        cls.shirt = Product.objects.create(name="Gym T-shirt", category="Merchandise", price=Decimal("15.00"))
        ProductSourcing.objects.create(product=cls.bars, supplier=cls.nutri, unit_cost=Decimal("1.20"), reorder_level=10)
        ProductSourcing.objects.create(product=cls.water, supplier=cls.nutri, unit_cost=Decimal("0.40"), reorder_level=24)
        BranchStock.objects.create(product=cls.bars, branch="Hamra", quantity=4)
        BranchStock.objects.create(product=cls.water, branch="Hamra", quantity=30)

    def setUp(self):
        staff_login(self.client, "bm", PASSWORD)

    def place(self, lines=None, supplier=None, **fields):
        body = {"supplierId": (supplier or self.nutri).id,
                "lines": lines if lines is not None else [{**BARS, "productId": self.bars.id}, SPRAY], **fields}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/purchasing/orders", body, content_type="application/json")

    def act(self, order_id, action, body=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/purchasing/orders/{order_id}/{action}", body or {}, content_type="application/json")

    def big(self):
        return self.place([{"productId": self.bars.id, "quantity": 500}])     # $600

    def notes(self, username):
        return list(StaffNotification.objects.filter(recipient__username=username).values_list("title", flat=True))


class PlacingOrdersTests(PurchasingBase):
    def test_low_stock_is_suggested_by_supplier_until_it_is_on_order(self):
        meta = self.client.get("/api/purchasing/meta").json()
        self.assertEqual((meta["branch"], meta["approvalLimit"], meta["canOrder"], meta["canApprove"]), ("Hamra", "500.00", True, False))
        [group] = meta["lowStock"]
        self.assertEqual((group["supplierName"], [(p["name"], p["inStock"], p["suggested"]) for p in group["products"]]),
                         ("NutriCo", [("Protein bar", 4, 16)]))
        self.place([{"productId": self.bars.id, "quantity": 16}])
        meta = self.client.get("/api/purchasing/meta").json()
        self.assertEqual(meta["lowStock"], [])
        bars = next(p for p in meta["products"] if p["name"] == "Protein bar")
        self.assertEqual((bars["inStock"], bars["onOrder"], bars["low"]), (4, 16, False))

    def test_a_small_order_goes_straight_to_the_supplier(self):
        res = self.place(note="Deliver before 10 am please.")
        self.assertEqual(res.status_code, 201, res.content)
        order = res.json()
        self.assertEqual((order["status"], order["autoApproved"], order["total"]), ("Ordered", True, "54.00"))
        self.assertEqual([(l["description"], l["quantity"], l["unitCost"]) for l in order["lines"]],
                         [("Protein bar", 20, "1.20"), ("Disinfectant spray 5 L", 2, "15.00")])
        [email] = mail.outbox
        self.assertEqual((email.to, email.reply_to), (["orders@nutrico.test"], ["bm@gym.com"]))
        self.assertIn(order["number"], email.subject)
        self.assertIn("20 x Protein bar @ $1.20 = $24.00", email.body)
        self.assertIn("Total: $54.00", email.body)
        self.assertIn("Deliver before 10 am please.", email.body)
        self.assertIsNotNone(PurchaseOrder.objects.get().sent_at)
        self.assertEqual(self.notes("gm") + self.notes("admin"), [])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PURCHASE_ORDER_CREATED).exists())

    def test_a_big_order_waits_for_head_office(self):
        res = self.big()
        self.assertEqual((res.json()["status"], res.json()["total"]), ("Pending approval", "600.00"))
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self.notes("gm"), [f"Approve {res.json()['number']}: $600.00 for Hamra"])
        self.assertEqual(len(self.notes("admin")), 1)
        self.assertEqual(self.notes("bm"), [])
        self.assertFalse(res.json()["canApprove"])                # a branch manager never approves

    def test_what_an_order_must_be(self):
        archived = Product.objects.create(name="Old shaker", category="Merchandise", price=Decimal("5"), is_active=False)
        cases = [
            ([], "lines"),
            ([{**SPRAY}] * 51, "lines"),
            ([{"productId": self.bars.id, "quantity": 1}, {"productId": self.bars.id, "quantity": 2}], "lines"),
            ([{"description": "x", "quantity": 1, "unitCost": "1"}], "lines"),
            ([{"productId": self.shirt.id, "quantity": 5}], "lines"),             # no cost on file
            ([{"productId": archived.id, "quantity": 5, "unitCost": "1"}], "lines"),
            ([{**SPRAY, "quantity": 0}], "lines"),
            ([{**SPRAY, "unitCost": "-1"}], "lines"),
            ([{**SPRAY, "unitCost": "0"}], "lines"),                              # comes to $0
        ]
        for lines, field in cases:
            res = self.place(lines)
            self.assertEqual(res.status_code, 400, lines)
            self.assertIn(field, res.json()["error"], lines)
        self.assertIn("supplierId", self.place(supplier=self.old).json()["error"])
        past = str(timezone.localdate() - timedelta(days=1))
        self.assertIn("neededBy", self.place(neededBy=past).json()["error"])
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_a_product_without_a_cost_on_file_takes_one_given(self):
        res = self.place([{"productId": self.shirt.id, "quantity": 10, "unitCost": "6.50"}])
        self.assertEqual(res.json()["total"], "65.00")

    def test_needed_sooner_than_the_supplier_delivers_is_flagged(self):
        tomorrow = str(timezone.localdate() + timedelta(days=1))
        self.assertTrue(self.place(neededBy=tomorrow).json()["rush"])
        self.assertFalse(self.place([SPRAY], supplier=self.clean, neededBy=tomorrow).json()["rush"])

    def test_branch_rules(self):
        self.assertEqual(self.place(branch="Jnah").status_code, 403)
        mine = self.place().json()
        staff_login(self.client, "jnah_bm", PASSWORD)
        self.assertEqual(self.client.get(f"/api/purchasing/orders/{mine['id']}").status_code, 403)
        self.assertEqual(self.client.get("/api/purchasing/orders", {"branch": "Hamra"}).status_code, 403)
        self.assertEqual(self.client.get("/api/purchasing/orders").json()["results"], [])
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.place(branch="Jnah").json()["branch"], "Jnah")
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/purchasing/meta").status_code, 403)
        self.assertEqual(self.place().status_code, 403)


class ApprovalTests(PurchasingBase):
    def test_approving_sends_it_and_tells_the_branch(self):
        order = self.big().json()
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual([o["number"] for o in self.client.get("/api/purchasing/approvals").json()["results"]], [order["number"]])
        res = self.act(order["id"], "approve")
        self.assertEqual((res.json()["status"], res.json()["approvedBy"], res.json()["autoApproved"]), ("Ordered", "Gm", False))
        self.assertEqual([m.to for m in mail.outbox], [["orders@nutrico.test"]])
        self.assertEqual(self.notes("bm"), [f"Approved: {order['number']}"])
        self.assertEqual(self.act(order["id"], "approve").status_code, 409)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PURCHASE_ORDER_APPROVED).exists())

    def test_nobody_approves_their_own_order(self):
        staff_login(self.client, "gm", PASSWORD)
        order = self.big().json()
        self.assertFalse(order["canApprove"])
        self.assertEqual(self.act(order["id"], "approve").status_code, 403)
        self.assertEqual(self.notes("admin"), [f"Approve {order['number']}: $600.00 for Hamra"])   # not the GM themself
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.act(order["id"], "approve").json()["status"], "Ordered")

    def test_rejecting_needs_a_reason_and_tells_the_branch(self):
        order = self.big().json()
        staff_login(self.client, "gm", PASSWORD)
        self.assertIn("reason", self.act(order["id"], "reject", {"reason": " "}).json()["error"])
        res = self.act(order["id"], "reject", {"reason": "Too many - order 200 for now."})
        self.assertEqual((res.json()["status"], res.json()["rejectionReason"]), ("Rejected", "Too many - order 200 for now."))
        self.assertEqual(self.notes("bm"), [f"Rejected: {order['number']}"])
        self.assertEqual(mail.outbox, [])

    def test_only_approvers_approve(self):
        order = self.big().json()
        self.assertEqual(self.act(order["id"], "approve").status_code, 403)
        self.assertEqual(self.client.get("/api/purchasing/approvals").status_code, 403)


class DeliveryTests(PurchasingBase):
    def setUp(self):
        super().setUp()
        self.order = self.place().json()
        self.bars_line, self.spray_line = (l["id"] for l in self.order["lines"])

    def receive(self, *items, order=None):
        body = {"items": [{"lineId": line, "quantity": qty} for line, qty in items]}
        return self.act((order or self.order)["id"], "receive", body)

    def test_a_delivery_in_two_parts_fills_the_shelf_and_the_expenses(self):
        res = self.receive((self.bars_line, 12))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["status"], res.json()["lines"][0]["outstanding"]), ("Partly received", 8))
        self.assertEqual(BranchStock.objects.get(product=self.bars, branch="Hamra").quantity, 16)
        expense = Expense.objects.get()
        self.assertEqual((expense.branch, expense.category, expense.amount), ("Hamra", "Supplies & stock", Decimal("14.40")))
        self.assertIn(self.order["number"], expense.note)

        res = self.receive((self.bars_line, 8), (self.spray_line, 2))
        self.assertEqual(res.json()["status"], "Received")
        self.assertEqual(BranchStock.objects.get(product=self.bars, branch="Hamra").quantity, 24)
        self.assertEqual(sorted(Expense.objects.values_list("amount", flat=True)), [Decimal("14.40"), Decimal("39.60")])
        self.assertEqual([r["amount"] for r in res.json()["receipts"]], ["14.40", "39.60"])
        self.assertEqual(self.receive((self.bars_line, 1)).status_code, 409)       # nothing left to receive

    def test_a_new_product_gets_a_shelf_row_at_that_branch(self):
        order = self.place([{"productId": self.shirt.id, "quantity": 5, "unitCost": "6.00"}]).json()
        self.receive((order["lines"][0]["id"], 5), order=order)
        self.assertEqual(BranchStock.objects.get(product=self.shirt, branch="Hamra").quantity, 5)

    def test_what_a_delivery_must_be(self):
        self.assertEqual(self.receive((self.bars_line, 21)).status_code, 400)          # more than ordered
        self.assertEqual(self.receive((self.bars_line, 0)).status_code, 400)
        self.assertEqual(self.receive((999999, 1)).status_code, 400)
        self.assertEqual(self.act(self.order["id"], "receive", {"items": [{"lineId": "x"}]}).status_code, 400)
        self.assertEqual(BranchStock.objects.get(product=self.bars, branch="Hamra").quantity, 4)
        pending = self.big().json()
        self.assertEqual(self.receive((pending["lines"][0]["id"], 1), order=pending).status_code, 409)
        staff_login(self.client, "jnah_bm", PASSWORD)
        self.assertEqual(self.receive((self.bars_line, 1)).status_code, 403)
        staff_login(self.client, "gm", PASSWORD)                                       # sees it, but doesn't receive here
        self.assertEqual(self.receive((self.bars_line, 1)).status_code, 200)

    def test_closing_an_order_whose_rest_will_never_come(self):
        self.assertEqual(self.act(self.order["id"], "close", {"reason": "x"}).status_code, 409)   # nothing arrived yet
        self.receive((self.bars_line, 20))
        res = self.act(self.order["id"], "close", {"reason": "Spray discontinued"})
        self.assertEqual((res.json()["status"], res.json()["closedShort"], res.json()["cancelReason"]),
                         ("Received", True, "Spray discontinued"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PURCHASE_ORDER_CLOSED).exists())

    def test_cancelling_tells_the_supplier_only_if_it_was_sent(self):
        pending = self.big().json()
        res = self.act(pending["id"], "cancel", {"reason": "Ordered by phone already"})
        self.assertEqual(res.json()["status"], "Cancelled")
        self.assertEqual(len(mail.outbox), 1)                                          # just the first order
        res = self.act(self.order["id"], "cancel", {"reason": "Found stock at Jnah"})
        self.assertEqual(res.json()["status"], "Cancelled")
        self.assertEqual(mail.outbox[-1].subject, f"Cancelled: purchase order {self.order['number']}")
        self.assertIn("Found stock at Jnah", mail.outbox[-1].body)

    def test_no_cancelling_once_deliveries_started(self):
        self.receive((self.bars_line, 5))
        self.assertEqual(self.act(self.order["id"], "cancel", {"reason": "x"}).status_code, 409)

    def test_a_failed_email_is_kept_and_can_be_sent_again(self):
        with mock.patch("purchasing.orders.EmailMessage.send", side_effect=OSError("mail server down")):
            order = self.place([SPRAY], supplier=self.clean).json()
        stored = PurchaseOrder.objects.get(pk=order["id"])
        self.assertEqual((stored.status, stored.sent_at, stored.send_error), ("Ordered", None, "mail server down"))
        self.assertEqual(self.act(order["id"], "resend").status_code, 200)
        stored.refresh_from_db()   # the email goes once the request's changes are saved
        self.assertEqual((stored.send_error, stored.sent_at is not None), ("", True))
        self.assertEqual(mail.outbox[-1].to, ["sales@cleanpro.test"])


class SupplierTests(PurchasingBase):
    def test_the_general_manager_keeps_the_supplier_list(self):
        self.assertEqual(len(self.client.get("/api/purchasing/suppliers").json()["results"]), 3)     # branch managers can see it
        body = {"name": "Towel House", "email": "hello@towels.test", "phone": "01 234 567", "supplies": "Towels", "leadTimeDays": 5}
        self.assertEqual(self.client.post("/api/purchasing/suppliers", body, content_type="application/json").status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        res = self.client.post("/api/purchasing/suppliers", body, content_type="application/json")
        self.assertEqual((res.status_code, res.json()["leadTimeDays"], res.json()["active"]), (201, 5, True))
        self.assertIn("name", self.client.post("/api/purchasing/suppliers", body, content_type="application/json").json()["error"])
        self.assertIn("email", self.client.post("/api/purchasing/suppliers", {**body, "name": "X", "email": "nope"},
                                                content_type="application/json").json()["error"])
        res = self.client.patch(f"/api/purchasing/suppliers/{res.json()['id']}", {"active": False}, content_type="application/json")
        self.assertFalse(res.json()["active"])
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.SUPPLIER_SAVED).exists())

    def test_product_sourcing(self):
        url = f"/api/purchasing/products/{self.shirt.id}/sourcing"
        self.assertEqual(self.client.patch(url, {"unitCost": "6"}, content_type="application/json").status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        self.assertIn("supplierId", self.client.patch(url, {"supplierId": self.old.id}, content_type="application/json").json()["error"])
        res = self.client.patch(url, {"supplierId": self.clean.id, "unitCost": "6.50", "reorderLevel": 3}, content_type="application/json")
        self.assertEqual(res.json(), {"productId": self.shirt.id, "supplierId": self.clean.id, "unitCost": "6.50", "reorderLevel": 3})
        meta = self.client.get("/api/purchasing/meta", {"branch": "Hamra"}).json()
        shirt = next(p for p in meta["products"] if p["name"] == "Gym T-shirt")
        self.assertEqual((shirt["supplierName"], shirt["low"], shirt["suggested"]), ("CleanPro", True, 6))

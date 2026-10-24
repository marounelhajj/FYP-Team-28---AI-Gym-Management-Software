from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from members.models import Member

from .models import BranchStock, Product, Sale

PASSWORD = "ChangeMe123!"


def _staff(username, permissions, branch=None):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(full_name=username.title(), email=f"{username}@gym.com", username=username,
                           job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role, branch=branch)
    account.set_password(PASSWORD)
    account.save()


def _product(name, price, stock=10, category="Drinks", active=True):
    product = Product.objects.create(name=name, category=category, price=price, is_active=active)
    for branch in Member.Branch.values:
        BranchStock.objects.create(product=product, branch=branch, quantity=stock)
    return product


# User story: "As a receptionist, I want to process point-of-sale purchases
# for retail items (protein, water bottles, merchandise), so that I can
# handle in-person retail sales."
class PointOfSaleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("desk", ["process_sales"], branch="Hamra")
        _staff("floater", ["process_sales"])
        _staff("gm", ["manage_retail_products", "view_all_branches", "view_financial_reports"])
        _staff("bm", ["manage_retail_products", "process_sales"], branch="Jnah")
        _staff("mkt", ["manage_marketing_campaigns"])
        cls.water = _product("Water Bottle", "1.00", stock=20)
        cls.protein = _product("Whey Protein", "45.00", stock=2, category="Supplements")
        cls.old = _product("Old Shirt", "9.00", category="Merchandise", active=False)
        cls.lea = Member.objects.create(name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra",
                                        join_date=timezone.localdate())

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def post(self, path, body=None):
        return self.client.post(path, body or {}, content_type="application/json")

    def sell(self, items, method="Cash", **extra):
        body = {"items": [{"productId": p.id, "quantity": q} for p, q in items], "paymentMethod": method, **extra}
        return self.post("/api/retail/sales", body)

    def stock(self, product, branch="Hamra"):
        return BranchStock.objects.get(product=product, branch=branch).quantity

    # --- ringing up a sale ---
    def test_cash_sale_is_priced_from_the_catalog_takes_stock_and_gives_change(self):
        res = self.sell([(self.water, 3), (self.protein, 1)], amountTendered="50.00", price="0.01")
        self.assertEqual(res.status_code, 201, res.content)
        sale = res.json()
        self.assertEqual((sale["total"], sale["amountTendered"], sale["changeDue"]), ("48.00", "50.00", "2.00"))
        self.assertEqual((sale["branch"], sale["soldBy"]), ("Hamra", "Desk"))
        self.assertEqual([(i["productName"], i["unitPrice"], i["quantity"], i["lineTotal"]) for i in sale["items"]],
                         [("Water Bottle", "1.00", 3, "3.00"), ("Whey Protein", "45.00", 1, "45.00")])
        self.assertEqual((self.stock(self.water), self.stock(self.protein)), (17, 1))
        self.assertEqual(self.stock(self.water, "Jnah"), 20)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.RETAIL_SALE).exists())

    def test_card_sale_takes_no_cash_and_can_be_linked_to_a_member(self):
        res = self.sell([(self.water, 1)], method="Card", memberId=self.lea.id)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["memberName"], res.json()["amountTendered"], res.json()["changeDue"]),
                         ("Lea Haddad", None, None))
        self.assertEqual(self.sell([(self.water, 1)], method="Card", memberId=9999).status_code, 400)

    def test_member_lookup_by_id_or_card(self):
        from members import qr

        self.assertEqual(self.client.get(f"/api/retail/member?code={self.lea.id}").json()["name"], "Lea Haddad")
        self.assertEqual(self.client.get(f"/api/retail/member?code={qr.payload_for(self.lea)}").json()["id"], self.lea.id)
        self.assertEqual(self.client.get("/api/retail/member?code=9999").status_code, 404)
        self.assertEqual(self.client.get("/api/retail/member?code=FFM1:1:forged").status_code, 400)
        old_card = qr.payload_for(self.lea)
        Member.objects.filter(id=self.lea.id).update(access_card_number=2)
        self.assertIn("replaced", self.client.get(f"/api/retail/member?code={old_card}").json()["error"])

    def test_cannot_sell_more_than_the_branch_has(self):
        res = self.sell([(self.protein, 3)], amountTendered="200")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only 2 x Whey Protein left at Hamra.", res.json()["error"]["items"])
        self.assertEqual((self.stock(self.protein), Sale.objects.count()), (2, 0))

    def test_the_last_unit_can_be_sold_once(self):
        self.assertEqual(self.sell([(self.protein, 2)], amountTendered="90").status_code, 201)
        self.assertEqual(self.sell([(self.protein, 1)], amountTendered="45").status_code, 400)

    def test_basket_rules(self):
        merged = self.sell([(self.water, 2), (self.water, 3)], amountTendered="5")
        self.assertEqual([(i["productName"], i["quantity"]) for i in merged.json()["items"]], [("Water Bottle", 5)])
        self.assertEqual(self.sell([], amountTendered="5").status_code, 400)
        self.assertEqual(self.sell([(self.water, 0)], amountTendered="5").status_code, 400)
        self.assertEqual(self.sell([(self.water, 60), (self.water, 60)], amountTendered="500").status_code, 400)

    def test_archived_or_unknown_products_cannot_be_sold(self):
        res = self.sell([(self.old, 1)], amountTendered="10")
        self.assertIn("Old Shirt is no longer sold.", res.json()["error"]["items"])
        unknown = self.post("/api/retail/sales", {"items": [{"productId": 9999, "quantity": 1}],
                                                  "paymentMethod": "Card"})
        self.assertEqual(unknown.status_code, 400)

    def test_cash_must_cover_the_total(self):
        for tendered in (None, "2.99"):
            res = self.sell([(self.water, 3)], amountTendered=tendered)
            self.assertEqual(res.status_code, 400, tendered)
            self.assertIn("amountTendered", res.json()["error"])

    def test_a_price_change_mid_sale_is_refused(self):
        res = self.sell([(self.water, 2)], amountTendered="5", expectedTotal="1.50")
        self.assertEqual(res.status_code, 409)
        self.assertIn("$2.00", res.json()["error"])
        self.assertEqual((Sale.objects.count(), self.stock(self.water)), (0, 20))

    def test_sales_come_off_the_receptionists_own_branch(self):
        self.assertEqual(self.sell([(self.water, 1)], method="Card", branch="Jnah").status_code, 403)
        staff_login(self.client, "floater", PASSWORD)
        self.assertIn("branch", self.sell([(self.water, 1)], method="Card").json()["error"])
        res = self.sell([(self.water, 1)], method="Card", branch="Zalka")
        self.assertEqual(res.json()["branch"], "Zalka")
        self.assertEqual(self.stock(self.water, "Zalka"), 19)

    # --- voids and the day's takings ---
    def test_voiding_puts_stock_back_and_drops_it_from_the_takings(self):
        sale_id = self.sell([(self.protein, 2)], amountTendered="90").json()["id"]
        self.sell([(self.water, 1)], method="Card")
        self.assertIn("reason", self.post(f"/api/retail/sales/{sale_id}/void", {"reason": "  "}).json()["error"])

        res = self.post(f"/api/retail/sales/{sale_id}/void", {"reason": "Customer changed their mind"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["voided"], res.json()["voidedBy"]), (True, "Desk"))
        self.assertEqual(self.stock(self.protein), 2)
        self.assertEqual(self.post(f"/api/retail/sales/{sale_id}/void", {"reason": "again"}).status_code, 400)

        summary = self.client.get("/api/retail/sales").json()["summary"]
        self.assertEqual(summary, {"sales": 1, "total": "1.00", "cash": "0.00", "card": "1.00", "voided": 1})
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.RETAIL_SALE_VOIDED).exists())

    def test_only_a_manager_can_void_a_sale_from_a_previous_day(self):
        sale_id = self.sell([(self.water, 1)], method="Card").json()["id"]
        Sale.objects.filter(id=sale_id).update(sold_at=timezone.now() - timedelta(days=2))
        self.assertEqual(self.post(f"/api/retail/sales/{sale_id}/void", {"reason": "Late"}).status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.post(f"/api/retail/sales/{sale_id}/void", {"reason": "Late"}).status_code, 200)

    def test_a_receptionist_only_sees_and_voids_their_own_branchs_sales(self):
        staff_login(self.client, "bm", PASSWORD)
        jnah_sale = self.sell([(self.water, 1)], method="Card").json()["id"]
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/retail/sales").json()["results"], [])
        self.assertEqual(self.client.get("/api/retail/sales?branch=Jnah").status_code, 403)
        self.assertEqual(self.post(f"/api/retail/sales/{jnah_sale}/void", {"reason": "x"}).status_code, 403)

    def test_past_days_can_be_looked_up(self):
        sale_id = self.sell([(self.water, 1)], method="Card").json()["id"]
        Sale.objects.filter(id=sale_id).update(sold_at=timezone.now() - timedelta(days=1))
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertEqual(len(self.client.get(f"/api/retail/sales?date={yesterday}").json()["results"]), 1)
        self.assertEqual(self.client.get("/api/retail/sales").json()["results"], [])
        self.assertEqual(self.client.get("/api/retail/sales?date=yesterday").status_code, 400)

    # --- catalog and stock ---
    def test_managers_add_and_edit_products_and_old_receipts_keep_their_price(self):
        sale_id = self.sell([(self.water, 1)], method="Card").json()["id"]
        staff_login(self.client, "gm", PASSWORD)
        created = self.post("/api/retail/products", {"name": " Gym  Bag ", "category": "Merchandise", "price": "30"})
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual((created.json()["name"], created.json()["stock"]["Zalka"]), ("Gym Bag", 0))
        self.assertIn("name", self.post("/api/retail/products", {"name": "gym bag", "category": "Other", "price": "1"}).json()["error"])

        self.client.patch(f"/api/retail/products/{self.water.id}", {"price": "1.50"}, content_type="application/json")
        staff_login(self.client, "desk", PASSWORD)
        old = next(s for s in self.client.get("/api/retail/sales").json()["results"] if s["id"] == sale_id)
        self.assertEqual(old["items"][0]["unitPrice"], "1.00")
        self.assertEqual(self.sell([(self.water, 2)], method="Card").json()["total"], "3.00")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.RETAIL_PRODUCT_UPDATED).exists())

    def test_archived_products_leave_the_till_but_stay_in_the_catalog(self):
        names = [p["name"] for p in self.client.get("/api/retail/products").json()["results"]]
        self.assertNotIn("Old Shirt", names)
        everything = self.client.get("/api/retail/products?includeArchived=true").json()["results"]
        self.assertIn("Old Shirt", [p["name"] for p in everything])

    def test_stock_deliveries_and_corrections(self):
        staff_login(self.client, "bm", PASSWORD)
        res = self.post(f"/api/retail/products/{self.protein.id}/stock", {"branch": "Jnah", "change": 10, "note": "Delivery"})
        self.assertEqual(res.json()["stock"]["Jnah"], 12)
        self.assertEqual(self.post(f"/api/retail/products/{self.protein.id}/stock", {"branch": "Hamra", "change": 5}).status_code, 403)
        too_many = self.post(f"/api/retail/products/{self.protein.id}/stock", {"branch": "Jnah", "change": -13})
        self.assertIn("change", too_many.json()["error"])
        self.assertEqual(self.post(f"/api/retail/products/{self.protein.id}/stock", {"branch": "Jnah", "change": 0}).status_code, 400)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.post(f"/api/retail/products/{self.protein.id}/stock", {"branch": "Hamra", "change": -1}).json()["stock"]["Hamra"], 1)
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.RETAIL_STOCK_ADJUSTED).count(), 2)

    def test_permissions(self):
        self.assertEqual(self.post("/api/retail/products", {"name": "X", "category": "Other", "price": "1"}).status_code, 403)
        self.assertEqual(self.post(f"/api/retail/products/{self.water.id}/stock", {"branch": "Hamra", "change": 1}).status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.sell([(self.water, 1)], method="Card").status_code, 403)
        staff_login(self.client, "mkt", PASSWORD)
        for url in ("/api/retail/meta", "/api/retail/products", "/api/retail/sales"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/retail/products").status_code, 401)

    def test_till_setup_tells_the_receptionist_their_branch(self):
        meta = self.client.get("/api/retail/meta").json()
        self.assertEqual((meta["fixedBranch"], meta["canSell"], meta["canManage"]), ("Hamra", True, False))

    # --- finance ---
    def test_retail_sales_count_as_branch_revenue_until_voided(self):
        kept = self.sell([(self.protein, 1)], method="Card").json()["id"]
        voided = self.sell([(self.water, 4)], method="Card").json()["id"]
        self.post(f"/api/retail/sales/{voided}/void", {"reason": "Mistake"})
        staff_login(self.client, "gm", PASSWORD)
        hamra = next(b for b in self.client.get("/api/finance/report").json()["branches"] if b["branch"] == "Hamra")
        self.assertEqual((hamra["revenue"], hamra["revenueBySource"]["retail"]), ("45.00", "45.00"))
        self.assertTrue(kept)

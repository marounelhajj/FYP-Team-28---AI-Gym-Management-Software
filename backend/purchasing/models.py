from django.core.validators import MinValueValidator
from django.db import models

from administration.models import StaffAccount
from finance.models import Expense
from members.models import Member
from retail.models import Product

# User story: "As a branch manager, I want to submit supply reorder requests
# through the system, so that restocking doesn't depend on manual phone calls
# to vendors."
#
#   * Supplier - a company the gym buys from. Not a user: it never logs in. It
#     gets purchase orders by email. The General Manager keeps the list.
#   * ProductSourcing - for a product the front desk sells: who it's usually
#     bought from, what it costs the gym, and the stock level at which a branch
#     should reorder it.
#   * PurchaseOrder / PurchaseOrderLine - a branch's order to one supplier:
#     catalog products (their stock goes up when delivered) and/or other
#     supplies (cleaning products, towels, parts) that aren't sold.
#   * PurchaseReceipt - one delivery against an order (partial ones too), and
#     the expense it was recorded as.
#
# The rules (approval limit, who approves, emailing the supplier, receiving)
# are in purchasing/orders.py.


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    contact_name = models.CharField(max_length=120, blank=True)
    # Where purchase orders are sent - so it's required.
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    supplies = models.CharField(max_length=300, blank=True)
    # Usual days from order to delivery; an order needed sooner is flagged.
    lead_time_days = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "name"]

    def __str__(self):
        return self.name


class ProductSourcing(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="sourcing")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    # What one unit costs the gym (not the shelf price).
    unit_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    # A branch at or below this many on the shelf is told to reorder; 0 = never.
    reorder_level = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.name} from {self.supplier or 'no supplier'}"


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = "Pending approval", "Waiting for the General Manager"
        ORDERED = "Ordered", "Sent to the supplier"
        PARTIAL = "Partly received", "Partly delivered"
        RECEIVED = "Received", "Delivered"
        REJECTED = "Rejected", "Rejected"
        CANCELLED = "Cancelled", "Cancelled"

    branch = models.CharField(max_length=30, choices=Member.Branch.choices, db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    needed_by = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    requested_by = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Approved automatically (under the limit) or by someone - never both.
    auto_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    rejection_reason = models.CharField(max_length=300, blank=True)
    # When the purchase order last went to the supplier, and why it failed if it did.
    sent_at = models.DateTimeField(null=True, blank=True)
    send_error = models.CharField(max_length=300, blank=True)
    cancelled_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cancel_reason = models.CharField(max_length=300, blank=True)
    # Closed with items still missing (the supplier can't deliver them).
    closed_short = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def number(self):
        return f"PO-{self.created_at:%Y}-{self.id:04d}"

    def __str__(self):
        return f"{self.number} {self.branch} -> {self.supplier.name} ({self.status})"


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    # Empty for supplies that aren't in the retail catalog.
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    description = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=8, decimal_places=2)
    received_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]

    @property
    def line_total(self):
        return self.quantity * self.unit_cost

    @property
    def outstanding(self):
        return self.quantity - self.received_quantity

    def __str__(self):
        return f"{self.quantity} x {self.description}"


class PurchaseReceipt(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="receipts")
    received_by = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="+")
    received_at = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # [{lineId, description, quantity}] - what came in this delivery.
    items = models.JSONField(default=list)
    note = models.CharField(max_length=300, blank=True)
    expense = models.OneToOneField(Expense, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchase_receipt")

    class Meta:
        ordering = ["received_at", "id"]

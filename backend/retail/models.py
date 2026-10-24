from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from members.models import Member

# User story: "As a receptionist, I want to process point-of-sale purchases
# for retail items (protein, water bottles, merchandise), so that I can
# handle in-person retail sales."


# Something the front desk sells. One price for every branch; how many are on
# the shelf is tracked per branch (BranchStock). Archived rather than deleted,
# so past sales still point at it.
class Product(models.Model):
    class Category(models.TextChoices):
        SUPPLEMENTS = "Supplements", "Supplements"
        DRINKS = "Drinks", "Drinks"
        MERCHANDISE = "Merchandise", "Merchandise"
        OTHER = "Other", "Other"

    name = models.CharField(max_length=80, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} (${self.price})"


class BranchStock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "branch"], name="one_stock_row_per_branch")]

    def __str__(self):
        return f"{self.product.name} @ {self.branch}: {self.quantity}"


# One checkout at the front desk. Prices are copied onto its items, so the
# receipt never changes when a price does. A voided sale stays on record
# (with who voided it and why) but no longer counts as revenue.
class Sale(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "Cash", "Cash"
        CARD = "Card", "Card"

    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    # Optional: the member it was sold to; null for a walk-in customer.
    member = models.ForeignKey(
        "members.Member", on_delete=models.SET_NULL, null=True, blank=True, related_name="retail_purchases",
    )
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    # Cash only: what the customer handed over and the change given back.
    amount_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_due = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sold_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    sold_at = models.DateTimeField(default=timezone.now, db_index=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-sold_at", "-id"]

    def __str__(self):
        return f"Sale #{self.id} - ${self.total} ({self.branch})"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=80)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveSmallIntegerField()
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

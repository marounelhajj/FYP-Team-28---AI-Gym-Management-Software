from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import changes, record
from audit.models import AuditLog
from members import qr
from members.models import Member

from .models import BranchStock, Product, Sale, SaleItem
from .serializers import (
    ProductSerializer, ProductWriteSerializer, SaleCreateSerializer, SaleSerializer, StockChangeSerializer,
    VoidSaleSerializer,
)

# User story: "As a receptionist, I want to process point-of-sale purchases
# for retail items (protein, water bottles, merchandise), so that I can
# handle in-person retail sales."

SELL = "process_sales"
MANAGE = "manage_retail_products"
ALL_BRANCHES = "view_all_branches"


def _products():
    return Product.objects.prefetch_related("stock")


def _sales():
    return Sale.objects.select_related("member", "sold_by", "voided_by").prefetch_related(
        Prefetch("items", queryset=SaleItem.objects.order_by("id")),
    )


# Which branch's shelf a sale comes off: always the receptionist's own branch
# when their account has one; otherwise they pick it at the till.
def _sale_branch(account, requested):
    if account.branch:
        if requested and requested != account.branch:
            return None, Response({"error": "You can only sell from your own branch's stock."}, status=403)
        return account.branch, None
    if not requested:
        return None, Response({"error": {"branch": ["Choose the branch you're selling at."]}}, status=400)
    return requested, None


# Same branch rule as the finance and headcount screens: view_all_branches
# may touch any branch, everyone else only their own.
def _may_manage_branch(account, branch):
    return ALL_BRANCHES in account.role.permissions or account.branch == branch


def _local_day_bounds(day):
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


# GET /api/retail/meta - what the till and the catalog screen need to set up.
@api_view(["GET"])
def retail_meta(request):
    account, denied = authorize(request, SELL, MANAGE)
    if denied:
        return denied
    permissions = account.role.permissions
    return Response({
        "branches": list(Member.Branch.values),
        "categories": list(Product.Category.values),
        # Set when sales always come off this branch's shelf.
        "fixedBranch": account.branch or None,
        "canSell": SELL in permissions,
        "canManage": MANAGE in permissions,
        "manageableBranches": [b for b in Member.Branch.values if _may_manage_branch(account, b)],
    })


# GET /api/retail/member?code=<membership ID or scanned card QR> - who a sale
# is for, so the till can show the name before charging. Linking a member is
# optional; it only puts the purchase on their record.
@api_view(["GET"])
def member_lookup(request):
    _, denied = authorize(request, SELL)
    if denied:
        return denied
    code = (request.query_params.get("code") or "").strip()
    card = qr.read(code) if code.startswith(qr.PREFIX) else None
    if card is None and not code.isdigit():
        return Response({"error": "Enter a membership ID or scan the member's card."}, status=400)
    member_id, card_number = card if card else (int(code), None)
    member = Member.objects.filter(id=member_id).first()
    if member is None:
        return Response({"error": f"No member found with ID {member_id}."}, status=404)
    if card_number is not None and card_number != member.access_card_number:
        return Response({"error": "This card was replaced - ask for the member's current card or ID."}, status=400)
    return Response({"id": member.id, "name": member.name, "branch": member.branch, "status": member.status})


# GET  /api/retail/products?includeArchived=true - the catalog with stock per branch.
# POST /api/retail/products - add a product: { name, category, price }.
@api_view(["GET", "POST"])
def product_list(request):
    if request.method == "GET":
        _, denied = authorize(request, SELL, MANAGE)
        if denied:
            return denied
        products = _products()
        if request.query_params.get("includeArchived") != "true":
            products = products.filter(is_active=True)
        return Response({"results": ProductSerializer(products, many=True).data})

    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    serializer = ProductWriteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    with transaction.atomic():
        product = Product.objects.create(name=data["name"], category=data["category"], price=data["price"])
        BranchStock.objects.bulk_create(BranchStock(product=product, branch=b) for b in Member.Branch.values)
    record(
        request, AuditLog.Action.RETAIL_PRODUCT_CREATED, actor=account, target=product, branch="",
        summary=f"Added retail product {product.name} at ${product.price:.2f}",
    )
    return Response(ProductSerializer(_products().get(pk=product.pk)).data, status=201)


# PATCH /api/retail/products/<id> - rename, re-price, re-categorise, or archive/restore.
# A new price applies to future sales only; past receipts keep the old one.
@api_view(["PATCH"])
def product_detail(request, product_id):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    product = _products().filter(id=product_id).first()
    if product is None:
        return Response({"error": f"Product {product_id} not found."}, status=404)

    serializer = ProductWriteSerializer(product, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    before = ProductSerializer(product).data
    fields = {"name": "name", "category": "category", "price": "price", "isActive": "is_active"}
    for key, value in serializer.validated_data.items():
        setattr(product, fields[key], value)
    product.save()
    after = ProductSerializer(product).data
    changed = changes(before, after, ignore=("stock",))
    if changed:
        record(
            request, AuditLog.Action.RETAIL_PRODUCT_UPDATED, actor=account, target=product, branch="",
            summary=f"Edited retail product {product.name} ({', '.join(sorted(changed))})",
            details={"changes": changed},
        )
    return Response(after)


# POST /api/retail/products/<id>/stock - Body: { branch, change, note? }.
# A delivery adds stock, a negative change corrects it (damaged, miscounted).
# The shelf can't go below zero.
@api_view(["POST"])
def product_stock(request, product_id):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    product = Product.objects.filter(id=product_id).first()
    if product is None:
        return Response({"error": f"Product {product_id} not found."}, status=404)

    serializer = StockChangeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    if not _may_manage_branch(account, data["branch"]):
        return Response({"error": "You can only change stock at your own branch."}, status=403)

    with transaction.atomic():
        row, _ = BranchStock.objects.select_for_update().get_or_create(product=product, branch=data["branch"])
        if row.quantity + data["change"] < 0:
            return Response(
                {"error": {"change": [f"Only {row.quantity} in stock at {row.branch} - can't remove {-data['change']}."]}},
                status=400,
            )
        before = row.quantity
        row.quantity += data["change"]
        row.save(update_fields=["quantity"])
    record(
        request, AuditLog.Action.RETAIL_STOCK_ADJUSTED, actor=account, target=product, branch=row.branch,
        summary=f"{'Received' if data['change'] > 0 else 'Removed'} {abs(data['change'])} x {product.name} "
                f"at {row.branch} ({before} -> {row.quantity})",
        details={"change": data["change"], "before": before, "after": row.quantity, "note": data["note"]},
    )
    return Response(ProductSerializer(_products().get(pk=product.pk)).data)


# GET  /api/retail/sales?date=YYYY-MM-DD&branch= - one day's sales (default today), newest
#      first, with the day's totals. A receptionist with a branch sees their own branch.
# POST /api/retail/sales - ring up a sale. See SaleCreateSerializer for the body.
@api_view(["GET", "POST"])
def sale_list(request):
    if request.method == "GET":
        account, denied = authorize(request, SELL, MANAGE)
        if denied:
            return denied
        return _day_of_sales(account, request.query_params)

    account, denied = authorize(request, SELL)
    if denied:
        return denied
    serializer = SaleCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    branch, error = _sale_branch(account, data.get("branch"))
    if error:
        return error

    quantities = data["items"]
    with transaction.atomic():
        # Locks this branch's shelf rows, so two tills can't sell the last unit twice.
        rows = {
            row.product_id: row
            for row in BranchStock.objects.select_for_update().select_related("product").filter(
                branch=branch, product_id__in=quantities,
            )
        }
        products = {p.id: p for p in Product.objects.filter(id__in=quantities)}
        problems = []
        for product_id, quantity in quantities.items():
            product = products.get(product_id)
            if product is None or not product.is_active:
                problems.append(f"{product.name if product else f'Product {product_id}'} is no longer sold.")
                continue
            in_stock = rows[product_id].quantity if product_id in rows else 0
            if in_stock < quantity:
                problems.append(f"Only {in_stock} x {product.name} left at {branch}.")
        if problems:
            return Response({"error": {"items": problems}}, status=400)

        total = sum((products[pid].price * qty for pid, qty in quantities.items()), Decimal("0"))
        expected = data.get("expectedTotal")
        if expected is not None and expected != total:
            return Response({
                "error": f"The total is now ${total:.2f} - a price changed since this sale was started. "
                         "Check the basket and charge again.",
                "total": f"{total:.2f}",
            }, status=409)

        tendered = change_due = None
        if data["paymentMethod"] == Sale.PaymentMethod.CASH:
            tendered = data.get("amountTendered")
            if tendered is None or tendered < total:
                return Response(
                    {"error": {"amountTendered": [f"Cash received must cover the total of ${total:.2f}."]}}, status=400,
                )
            change_due = tendered - total

        sale = Sale.objects.create(
            branch=branch, member_id=data.get("memberId"), payment_method=data["paymentMethod"], total=total,
            amount_tendered=tendered, change_due=change_due, sold_by=account,
        )
        SaleItem.objects.bulk_create(
            SaleItem(
                sale=sale, product=products[pid], product_name=products[pid].name, unit_price=products[pid].price,
                quantity=qty, line_total=products[pid].price * qty,
            )
            for pid, qty in quantities.items()
        )
        for pid, qty in quantities.items():
            rows[pid].quantity -= qty
            rows[pid].save(update_fields=["quantity"])

    item_count = sum(quantities.values())
    record(
        request, AuditLog.Action.RETAIL_SALE, actor=account, target=sale.member or sale, branch=branch,
        summary=f"Sold {item_count} item{'s' if item_count != 1 else ''} for ${total:.2f} "
                f"({sale.payment_method.lower()}, sale #{sale.id})",
        details={"saleId": sale.id, "total": f"{total:.2f}", "method": sale.payment_method},
    )
    return Response(SaleSerializer(_sales().get(pk=sale.pk)).data, status=201)


def _day_of_sales(account, params):
    raw_date = params.get("date")
    try:
        day = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        return Response({"error": "date must be YYYY-MM-DD."}, status=400)

    requested = params.get("branch")
    if requested and requested not in Member.Branch.values:
        return Response({"error": f'Invalid branch "{requested}".'}, status=400)
    if account.branch and ALL_BRANCHES not in account.role.permissions:
        if requested and requested != account.branch:
            return Response({"error": "You can only see your own branch's sales."}, status=403)
        requested = account.branch

    start, end = _local_day_bounds(day)
    sales = _sales().filter(sold_at__gte=start, sold_at__lt=end)
    if requested:
        sales = sales.filter(branch=requested)
    sales = list(sales[:200])
    counted = [s for s in sales if s.voided_at is None]
    return Response({
        "date": day,
        "branch": requested or None,
        "results": SaleSerializer(sales, many=True).data,
        "summary": {
            "sales": len(counted),
            "total": f"{sum((s.total for s in counted), Decimal('0')):.2f}",
            "cash": f"{sum((s.total for s in counted if s.payment_method == Sale.PaymentMethod.CASH), Decimal('0')):.2f}",
            "card": f"{sum((s.total for s in counted if s.payment_method == Sale.PaymentMethod.CARD), Decimal('0')):.2f}",
            "voided": len(sales) - len(counted),
        },
    })


# POST /api/retail/sales/<id>/void - Body: { reason }. Undoes a sale: the stock
# goes back on the shelf and it stops counting as revenue, but it stays on
# record. A receptionist can void today's sales at their branch; an older sale
# needs someone who manages retail.
@api_view(["POST"])
def void_sale(request, sale_id):
    account, denied = authorize(request, SELL, MANAGE)
    if denied:
        return denied
    sale = _sales().filter(id=sale_id).first()
    if sale is None:
        return Response({"error": f"Sale {sale_id} not found."}, status=404)
    if sale.voided_at is not None:
        return Response({"error": "This sale was already voided."}, status=400)
    if account.branch and ALL_BRANCHES not in account.role.permissions and sale.branch != account.branch:
        return Response({"error": "You can only void sales made at your own branch."}, status=403)
    if timezone.localtime(sale.sold_at).date() != timezone.localdate() and MANAGE not in account.role.permissions:
        return Response({"error": "Only a manager can void a sale from a previous day."}, status=403)

    serializer = VoidSaleSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    with transaction.atomic():
        # Re-checked under a lock, so two clicks on "Void" can't put the stock back twice.
        if Sale.objects.select_for_update().filter(id=sale.id, voided_at__isnull=False).exists():
            return Response({"error": "This sale was already voided."}, status=400)
        for item in sale.items.all():
            row, _ = BranchStock.objects.select_for_update().get_or_create(product_id=item.product_id, branch=sale.branch)
            row.quantity += item.quantity
            row.save(update_fields=["quantity"])
        sale.voided_at = timezone.now()
        sale.voided_by = account
        sale.void_reason = serializer.validated_data["reason"]
        sale.save(update_fields=["voided_at", "voided_by", "void_reason"])
    record(
        request, AuditLog.Action.RETAIL_SALE_VOIDED, actor=account, target=sale.member or sale, branch=sale.branch,
        summary=f"Voided sale #{sale.id} (${sale.total:.2f}): {sale.void_reason}",
        details={"saleId": sale.id, "total": f"{sale.total:.2f}", "reason": sale.void_reason},
    )
    return Response(SaleSerializer(_sales().get(pk=sale.pk)).data)

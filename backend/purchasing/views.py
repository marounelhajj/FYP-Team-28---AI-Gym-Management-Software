from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from finance.models import Expense
from headcount.views import resolve_branch
from retail.models import BranchStock, Product

from . import orders as rules
from .models import ProductSourcing, PurchaseOrder, PurchaseOrderLine, PurchaseReceipt, Supplier
from .orders import APPROVE, ORDER, money
from .serializers import OrderSerializer, ReasonSerializer, ReceiveSerializer, SourcingSerializer, SupplierSerializer

# User story: "As a branch manager, I want to submit supply reorder requests
# through the system, so that restocking doesn't depend on manual phone calls
# to vendors."
#
#   /api/purchasing/meta                       what the order screen needs (suppliers, products, low stock)
#   /api/purchasing/orders                     list / place orders
#   /api/purchasing/orders/<id>[/approve|/reject|/cancel|/receive|/close|/resend]
#   /api/purchasing/approvals                  orders waiting for an approver, every branch
#   /api/purchasing/suppliers[/<id>]           the supplier list
#   /api/purchasing/products/<id>/sourcing     a product's supplier, cost and reorder level
#
# The rules are in purchasing/orders.py.

SUBJECT = "supply orders"
STATUS_FILTERS = {
    "open": rules.OPEN,
    "pending": [PurchaseOrder.Status.PENDING],
    "closed": [PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.REJECTED, PurchaseOrder.Status.CANCELLED],
}


def _orders():
    return PurchaseOrder.objects.select_related(
        "supplier", "requested_by", "approved_by", "rejected_by", "cancelled_by",
    ).prefetch_related(Prefetch("lines", queryset=PurchaseOrderLine.objects.order_by("id")))


def _supplier_payload(s):
    return {"id": s.id, "name": s.name, "contactName": s.contact_name, "email": s.email, "phone": s.phone,
            "supplies": s.supplies, "leadTimeDays": s.lead_time_days, "active": s.is_active}


# GET /api/purchasing/meta?branch= - suppliers, the catalog with this branch's
# stock and what's on order, and what's running low (grouped by supplier).
@api_view(["GET"])
def meta(request):
    account, denied = authorize(request, ORDER, APPROVE)
    if denied:
        return denied
    branch, branches, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    products = rules.product_rows(branch)
    low = defaultdict(list)
    for p in products:
        if p["low"]:
            low[(p["supplierId"], p["supplierName"])].append(p)
    return Response({
        "branch": branch,
        "branches": branches,
        "approvalLimit": money(rules.APPROVAL_LIMIT),
        "canOrder": rules.can(account, ORDER),
        "canApprove": rules.can(account, APPROVE),
        "suppliers": [_supplier_payload(s) for s in Supplier.objects.all()],
        "products": products,
        "lowStock": [
            {"supplierId": supplier_id, "supplierName": name, "products": items}
            for (supplier_id, name), items in sorted(low.items(), key=lambda kv: (kv[0][1] is None, kv[0][1] or ""))
        ],
        "pendingApprovals": PurchaseOrder.objects.filter(status=PurchaseOrder.Status.PENDING).exclude(
            requested_by=account).count() if rules.can(account, APPROVE) else 0,
    })


def _place(request, account, data, branch):
    supplier = Supplier.objects.filter(id=data["supplierId"]).first()
    if supplier is None or not supplier.is_active:
        return Response({"error": {"supplierId": ["Pick an active supplier."]}}, status=400)
    products = {p.id: p for p in Product.objects.filter(id__in=[l["productId"] for l in data["lines"] if l.get("productId")])}
    sourcing = {s.product_id: s for s in ProductSourcing.objects.filter(product_id__in=products)}
    line_errors, lines = {}, []
    for i, line in enumerate(data["lines"]):
        product = products.get(line.get("productId")) if line.get("productId") else None
        if line.get("productId") and (product is None or not product.is_active):
            line_errors[str(i)] = {"productId": ["That product isn't sold any more."]}
            continue
        cost = line.get("unitCost")
        if cost is None and product is not None and product.id in sourcing:
            cost = sourcing[product.id].unit_cost
        if cost is None:
            line_errors[str(i)] = {"unitCost": [f"What does {product.name if product else 'it'} cost? No cost is on file."]}
            continue
        description = product.name if product else " ".join(line["description"].split())
        lines.append(PurchaseOrderLine(product=product, description=description, quantity=line["quantity"], unit_cost=cost))
    if line_errors:
        return Response({"error": {"lines": line_errors}}, status=400)
    total = sum((line.line_total for line in lines), Decimal("0"))
    if total <= 0:
        return Response({"error": {"lines": ["The order comes to $0.00 - check the costs."]}}, status=400)

    auto = total < rules.APPROVAL_LIMIT
    now = timezone.now()
    with transaction.atomic():
        order = PurchaseOrder.objects.create(
            branch=branch, supplier=supplier, needed_by=data.get("neededBy"), note=data.get("note", ""), total=total,
            requested_by=account,
            status=PurchaseOrder.Status.ORDERED if auto else PurchaseOrder.Status.PENDING,
            auto_approved=auto, approved_at=now if auto else None,
        )
        for line in lines:
            line.order = order
        PurchaseOrderLine.objects.bulk_create(lines)
        record(
            request, AuditLog.Action.PURCHASE_ORDER_CREATED, actor=account, target=order, branch=branch,
            summary=f"{order.number}: ${money(total)} from {supplier.name} for {branch}"
                    f"{' (approved automatically)' if auto else ' - waiting for approval'}",
            details={"total": money(total), "supplier": supplier.name, "lines": len(lines), "autoApproved": auto},
        )
        if auto:
            rules.email_order(order)
        else:
            rules.notify(
                rules.approvers(exclude=account), order, f"Approve {order.number}: ${money(total)} for {branch}",
                f"{account.full_name} wants to order from {supplier.name}. Orders of ${money(rules.APPROVAL_LIMIT)} "
                "or more need your approval - open Supply Orders.",
            )
    return Response(rules.order_payload(_orders().get(pk=order.pk), account), status=201)


# GET  /api/purchasing/orders?branch=&status=open|pending|closed|all
# POST /api/purchasing/orders - Body: { branch?, supplierId, neededBy?, note?,
#      lines: [{ productId? | description, quantity, unitCost? }] }. A catalog
#      product's cost defaults to its sourcing cost.
@api_view(["GET", "POST"])
def order_list(request):
    if request.method == "POST":
        account, denied = authorize(request, ORDER)
        if denied:
            return denied
        serializer = OrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        data = serializer.validated_data
        branch, _, error = resolve_branch(account, data.get("branch"), subject=SUBJECT)
        if error:
            return error
        return _place(request, account, data, branch)

    account, denied = authorize(request, ORDER, APPROVE)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    status = request.query_params.get("status", "all")
    if status not in (*STATUS_FILTERS, "all"):
        return Response({"error": {"status": ["Use open, pending, closed or all."]}}, status=400)
    found = _orders().filter(branch=branch)
    if status != "all":
        found = found.filter(status__in=STATUS_FILTERS[status])
    return Response({"branch": branch, "results": [rules.order_payload(o, account) for o in found[:200]]})


# GET /api/purchasing/approvals - every branch's orders waiting for approval, oldest first.
@api_view(["GET"])
def approvals(request):
    account, denied = authorize(request, APPROVE)
    if denied:
        return denied
    found = _orders().filter(status=PurchaseOrder.Status.PENDING).order_by("created_at")
    return Response({"results": [rules.order_payload(o, account) for o in found]})


def _order_for(request, order_id, *permissions):
    account, denied = authorize(request, *permissions)
    if denied:
        return None, None, denied
    order = _orders().filter(id=order_id).first()
    if order is None:
        return None, None, Response({"error": "Order not found."}, status=404)
    if not rules.can(account, APPROVE) and not rules.may_use_branch(account, order.branch):
        return None, None, Response({"error": "You can only see your own branch's orders."}, status=403)
    return account, order, None


def _locked(order_id):
    return PurchaseOrder.objects.select_for_update().get(pk=order_id)


def _done(account, order_id, status=200):
    return Response(rules.order_payload(_orders().get(pk=order_id), account), status=status)


@api_view(["GET"])
def order_detail(request, order_id):
    account, order, denied = _order_for(request, order_id, ORDER, APPROVE)
    if denied:
        return denied
    return Response(rules.order_payload(order, account))


# POST /api/purchasing/orders/<id>/approve - sends it to the supplier.
@api_view(["POST"])
def approve(request, order_id):
    account, order, denied = _order_for(request, order_id, APPROVE)
    if denied:
        return denied
    if order.requested_by_id == account.id:
        return Response({"error": "Someone else has to approve an order you placed."}, status=403)
    with transaction.atomic():
        order = _locked(order.pk)
        if order.status != PurchaseOrder.Status.PENDING:
            return Response({"error": f"This order is {order.status.lower()} - nothing to approve."}, status=409)
        order.status, order.approved_by, order.approved_at = PurchaseOrder.Status.ORDERED, account, timezone.now()
        order.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        rules.email_order(order)
        rules.notify([order.requested_by], order, f"Approved: {order.number}",
                     f"{account.full_name} approved your ${money(order.total)} order from {order.supplier.name}. "
                     "It has been sent to the supplier.")
        record(request, AuditLog.Action.PURCHASE_ORDER_APPROVED, actor=account, target=order, branch=order.branch,
               summary=f"Approved {order.number} (${money(order.total)})", details={"total": money(order.total)})
    return _done(account, order.pk)


# POST /api/purchasing/orders/<id>/reject - Body: { reason }.
@api_view(["POST"])
def reject(request, order_id):
    account, order, denied = _order_for(request, order_id, APPROVE)
    if denied:
        return denied
    serializer = ReasonSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reason = serializer.validated_data["reason"]
    with transaction.atomic():
        order = _locked(order.pk)
        if order.status != PurchaseOrder.Status.PENDING:
            return Response({"error": f"This order is {order.status.lower()} - it can't be rejected now."}, status=409)
        order.status, order.rejected_by, order.rejection_reason = PurchaseOrder.Status.REJECTED, account, reason
        order.save(update_fields=["status", "rejected_by", "rejection_reason", "updated_at"])
        rules.notify([order.requested_by], order, f"Rejected: {order.number}", f"{account.full_name}: {reason}")
        record(request, AuditLog.Action.PURCHASE_ORDER_REJECTED, actor=account, target=order, branch=order.branch,
               summary=f"Rejected {order.number}", details={"reason": reason})
    return _done(account, order.pk)


# POST /api/purchasing/orders/<id>/cancel - Body: { reason }. Before anything
# arrives; the supplier is told if the order had already gone to them.
@api_view(["POST"])
def cancel(request, order_id):
    account, order, denied = _order_for(request, order_id, ORDER, APPROVE)
    if denied:
        return denied
    if not rules.order_payload(order, account)["canCancel"]:
        return Response({"error": "This order can't be cancelled - it's closed or deliveries have started."}, status=409)
    serializer = ReasonSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reason = serializer.validated_data["reason"]
    with transaction.atomic():
        order = _locked(order.pk)
        if order.status not in (PurchaseOrder.Status.PENDING, PurchaseOrder.Status.ORDERED):
            return Response({"error": "This order can't be cancelled any more."}, status=409)
        was_sent = order.status == PurchaseOrder.Status.ORDERED
        order.status, order.cancelled_by, order.cancel_reason = PurchaseOrder.Status.CANCELLED, account, reason
        order.save(update_fields=["status", "cancelled_by", "cancel_reason", "updated_at"])
        if was_sent:
            rules.email_cancellation(order, reason)
        record(request, AuditLog.Action.PURCHASE_ORDER_CANCELLED, actor=account, target=order, branch=order.branch,
               summary=f"Cancelled {order.number}", details={"reason": reason, "supplierTold": was_sent})
    return _done(account, order.pk)


# POST /api/purchasing/orders/<id>/receive - Body: { items: [{ lineId, quantity }], note? }.
# What arrived in this delivery: catalog products go onto the branch's shelf,
# and its cost is recorded as a branch expense.
@api_view(["POST"])
def receive(request, order_id):
    account, order, denied = _order_for(request, order_id, ORDER)
    if denied:
        return denied
    if not rules.may_use_branch(account, order.branch):
        return Response({"error": "Only the branch that ordered it can receive it."}, status=403)
    serializer = ReceiveSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    wanted = {}
    for item in serializer.validated_data["items"]:
        try:
            line_id, quantity = int(item.get("lineId")), int(item.get("quantity") or 0)
        except (TypeError, ValueError):
            return Response({"error": {"items": ["Each item needs a lineId and a quantity."]}}, status=400)
        if quantity < 0:
            return Response({"error": {"items": ["Quantities can't be negative."]}}, status=400)
        if quantity:
            wanted[line_id] = wanted.get(line_id, 0) + quantity
    if not wanted:
        return Response({"error": {"items": ["Enter how many of something arrived."]}}, status=400)

    with transaction.atomic():
        order = _locked(order.pk)
        if order.status not in rules.RECEIVABLE:
            return Response({"error": f"This order is {order.status.lower()} - there's nothing to receive."}, status=409)
        lines = {line.id: line for line in order.lines.select_for_update()}
        problems = []
        for line_id, quantity in wanted.items():
            line = lines.get(line_id)
            if line is None:
                problems.append(f"Line {line_id} isn't on this order.")
            elif quantity > line.outstanding:
                problems.append(f"Only {line.outstanding} more {line.description} {'is' if line.outstanding == 1 else 'are'} expected.")
        if problems:
            return Response({"error": {"items": problems}}, status=400)

        amount, items = Decimal("0"), []
        for line_id, quantity in wanted.items():
            line = lines[line_id]
            line.received_quantity += quantity
            line.save(update_fields=["received_quantity"])
            amount += line.unit_cost * quantity
            items.append({"lineId": line.id, "description": line.description, "quantity": quantity})
            if line.product_id:
                stock, _ = BranchStock.objects.select_for_update().get_or_create(product_id=line.product_id, branch=order.branch)
                stock.quantity += quantity
                stock.save(update_fields=["quantity"])
        expense = None
        if amount > 0:
            expense = Expense.objects.create(
                branch=order.branch, category=Expense.Category.SUPPLIES, amount=amount, incurred_on=timezone.localdate(),
                note=f"{order.number} from {order.supplier.name}"[:255], recorded_by=account,
            )
        PurchaseReceipt.objects.create(order=order, received_by=account, amount=amount, items=items,
                                       note=serializer.validated_data.get("note", ""), expense=expense)
        complete = all(line.outstanding == 0 for line in lines.values())
        order.status = PurchaseOrder.Status.RECEIVED if complete else PurchaseOrder.Status.PARTIAL
        order.closed_at = timezone.now() if complete else None
        order.save(update_fields=["status", "closed_at", "updated_at"])
        record(request, AuditLog.Action.PURCHASE_ORDER_RECEIVED, actor=account, target=order, branch=order.branch,
               summary=f"Received {sum(i['quantity'] for i in items)} item(s) on {order.number} (${money(amount)})",
               details={"items": items, "amount": money(amount), "complete": complete})
    return _done(account, order.pk)


# POST /api/purchasing/orders/<id>/close - Body: { reason }. The rest of a
# partly delivered order will never come: stop waiting for it.
@api_view(["POST"])
def close_short(request, order_id):
    account, order, denied = _order_for(request, order_id, ORDER)
    if denied:
        return denied
    serializer = ReasonSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    with transaction.atomic():
        order = _locked(order.pk)
        if order.status != PurchaseOrder.Status.PARTIAL or not rules.may_use_branch(account, order.branch):
            return Response({"error": "Only a partly delivered order can be closed."}, status=409)
        order.status, order.closed_short, order.closed_at = PurchaseOrder.Status.RECEIVED, True, timezone.now()
        order.cancel_reason, order.cancelled_by = serializer.validated_data["reason"], account
        order.save(update_fields=["status", "closed_short", "closed_at", "cancel_reason", "cancelled_by", "updated_at"])
        record(request, AuditLog.Action.PURCHASE_ORDER_CLOSED, actor=account, target=order, branch=order.branch,
               summary=f"Closed {order.number} with items missing", details={"reason": order.cancel_reason})
    return _done(account, order.pk)


# POST /api/purchasing/orders/<id>/resend - email the purchase order again.
@api_view(["POST"])
def resend(request, order_id):
    account, order, denied = _order_for(request, order_id, ORDER)
    if denied:
        return denied
    if order.status not in rules.RECEIVABLE or not rules.may_use_branch(account, order.branch):
        return Response({"error": "Only an order that's with the supplier can be sent again."}, status=409)
    with transaction.atomic():
        rules.email_order(order)
    return _done(account, order.pk)


# --- suppliers and product sourcing (approvers) ----------------------------------

def _save_supplier(supplier, data):
    fields = {"name": "name", "contactName": "contact_name", "email": "email", "phone": "phone",
              "supplies": "supplies", "leadTimeDays": "lead_time_days", "active": "is_active"}
    for key, attr in fields.items():
        if key in data:
            setattr(supplier, attr, " ".join(data[key].split()) if key == "name" else data[key])
    supplier.save()


# GET  /api/purchasing/suppliers - the list (anyone who orders sees it).
# POST /api/purchasing/suppliers - add one (approvers).
@api_view(["GET", "POST"])
def supplier_list(request):
    if request.method == "GET":
        _, denied = authorize(request, ORDER, APPROVE)
        if denied:
            return denied
        return Response({"results": [_supplier_payload(s) for s in Supplier.objects.all()]})
    account, denied = authorize(request, APPROVE)
    if denied:
        return denied
    serializer = SupplierSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    try:
        with transaction.atomic():
            supplier = Supplier()
            _save_supplier(supplier, serializer.validated_data)
    except IntegrityError:
        return Response({"error": {"name": ["There's already a supplier with this name."]}}, status=400)
    record(request, AuditLog.Action.SUPPLIER_SAVED, actor=account, target=supplier, summary=f"Added supplier {supplier.name}")
    return Response(_supplier_payload(supplier), status=201)


# PATCH /api/purchasing/suppliers/<id> - edit, or active=false to stop using them.
@api_view(["PATCH"])
def supplier_detail(request, supplier_id):
    account, denied = authorize(request, APPROVE)
    if denied:
        return denied
    supplier = Supplier.objects.filter(id=supplier_id).first()
    if supplier is None:
        return Response({"error": "Supplier not found."}, status=404)
    serializer = SupplierSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    try:
        with transaction.atomic():
            _save_supplier(supplier, serializer.validated_data)
    except IntegrityError:
        return Response({"error": {"name": ["There's already a supplier with this name."]}}, status=400)
    record(request, AuditLog.Action.SUPPLIER_SAVED, actor=account, target=supplier, summary=f"Edited supplier {supplier.name}",
           details={"changed": sorted(serializer.validated_data)})
    return Response(_supplier_payload(supplier))


# PATCH /api/purchasing/products/<id>/sourcing - Body: { supplierId?, unitCost?, reorderLevel? }.
@api_view(["PATCH"])
def product_sourcing(request, product_id):
    account, denied = authorize(request, APPROVE)
    if denied:
        return denied
    product = Product.objects.filter(id=product_id).first()
    if product is None:
        return Response({"error": "Product not found."}, status=404)
    serializer = SourcingSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    sourcing, _ = ProductSourcing.objects.get_or_create(product=product)
    if "supplierId" in data:
        supplier = Supplier.objects.filter(id=data["supplierId"], is_active=True).first() if data["supplierId"] else None
        if data["supplierId"] and supplier is None:
            return Response({"error": {"supplierId": ["Pick an active supplier."]}}, status=400)
        sourcing.supplier = supplier
    if "unitCost" in data:
        sourcing.unit_cost = data["unitCost"]
    if "reorderLevel" in data:
        sourcing.reorder_level = data["reorderLevel"]
    sourcing.save()
    return Response({
        "productId": product.id, "supplierId": sourcing.supplier_id,
        "unitCost": money(sourcing.unit_cost) if sourcing.unit_cost is not None else None,
        "reorderLevel": sourcing.reorder_level,
    })

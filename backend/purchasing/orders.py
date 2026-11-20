import logging
from datetime import timedelta
from decimal import Decimal

from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from administration.models import StaffAccount
from notifications.models import StaffNotification
from retail.models import BranchStock, Product

from .models import ProductSourcing, PurchaseOrder, PurchaseOrderLine

logger = logging.getLogger(__name__)

# The rules for supply orders, in one place.
#
#   * Who: a role with manage_retail_products (Branch Manager, General Manager)
#     orders and receives for its own branch - any branch with
#     view_all_branches. APPROVE (General Manager, System Administrator)
#     approves the big ones and keeps the supplier list and product sourcing.
#   * An order under APPROVAL_LIMIT is approved on the spot and emailed to the
#     supplier straight away - restocking a $40 box of bars shouldn't wait on
#     head office. At or above it, it waits for an approver, who is alerted.
#     Nobody approves their own order.
#   * The purchase order goes to the supplier's email once approved (and a
#     cancellation, if an order already sent is cancelled). The supplier
#     replies or delivers as they do today; no supplier account is needed.
#     A failed send is kept on the order and can be retried.
#   * Deliveries are received line by line, partial ones too: catalog products
#     go onto the branch's shelf, and each delivery is recorded as a branch
#     expense (Supplies & stock) for what it cost. An order whose rest will
#     never come can be closed short.

ORDER = "manage_retail_products"
APPROVE = "approve_purchase_orders"
ALL_BRANCHES = "view_all_branches"
APPROVAL_LIMIT = Decimal("500.00")
OPEN = [PurchaseOrder.Status.PENDING, PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL]
RECEIVABLE = [PurchaseOrder.Status.ORDERED, PurchaseOrder.Status.PARTIAL]


def money(value):
    return f"{Decimal(value):.2f}"


def can(account, permission):
    return permission in account.role.permissions


def may_use_branch(account, branch):
    return can(account, ALL_BRANCHES) or account.branch == branch


def approvers(exclude=None):
    found = []
    for account in StaffAccount.objects.filter(is_active=True).select_related("role"):
        if can(account, APPROVE) and account != exclude:
            found.append(account)
    return found


def notify(recipients, order, title, message):
    StaffNotification.objects.bulk_create(
        StaffNotification(recipient=r, kind=StaffNotification.Kind.PURCHASE, branch=order.branch,
                          title=title[:120], message=message[:300])
        for r in recipients
    )


def is_rush(order):
    if not order.needed_by:
        return False
    return order.needed_by < timezone.localdate(order.created_at) + timedelta(days=order.supplier.lead_time_days)


# --- emailing the supplier -------------------------------------------------------

def _order_text(order):
    lines = "\n".join(
        f"  {line.quantity} x {line.description} @ ${money(line.unit_cost)} = ${money(line.line_total)}"
        for line in order.lines.all()
    )
    requester = order.requested_by
    parts = [
        f"Purchase order {order.number}",
        f"From: Fitness Factory, {order.branch} branch",
        f"Ordered by: {requester.full_name} ({requester.email})",
    ]
    if order.needed_by:
        parts.append(f"Needed by: {order.needed_by:%a %d %b %Y}")
    parts += ["", "Items:", lines, f"Total: ${money(order.total)}"]
    if order.note:
        parts += ["", f"Note: {order.note}"]
    parts += ["", "Please reply to this email to confirm the order and the delivery date.", "", "Fitness Factory"]
    return "\n".join(parts)


def _send(order_id, subject, body):
    order = PurchaseOrder.objects.select_related("supplier", "requested_by").get(pk=order_id)
    message = EmailMessage(subject=subject, body=body, to=[order.supplier.email], reply_to=[order.requested_by.email])
    try:
        message.send()
    except Exception as exc:  # the order stands; it can be sent again
        logger.exception("Couldn't email purchase order %s", order.number)
        PurchaseOrder.objects.filter(pk=order_id).update(send_error=str(exc)[:300] or "The mail server refused it.")
        return
    PurchaseOrder.objects.filter(pk=order_id).update(sent_at=timezone.now(), send_error="")


# Sent once the change that prompted it is saved, so nobody is emailed an
# order that was rolled back.
def email_order(order):
    transaction.on_commit(lambda: _send(order.pk, f"Purchase order {order.number} - Fitness Factory {order.branch}",
                                        _order_text(order)))


def email_cancellation(order, reason):
    body = (f"Purchase order {order.number} from Fitness Factory {order.branch} is cancelled - please don't deliver it."
            f"\n\nReason: {reason}\n\nSorry for any trouble.\n\nFitness Factory")
    transaction.on_commit(lambda: _send(order.pk, f"Cancelled: purchase order {order.number}", body))


# --- stock and suggestions ------------------------------------------------------

def incoming(branch):
    rows = PurchaseOrderLine.objects.filter(
        order__branch=branch, order__status__in=OPEN, product__isnull=False,
    ).values("product_id").annotate(n=Sum(F("quantity") - F("received_quantity")))
    return {r["product_id"]: r["n"] for r in rows}


def product_rows(branch):
    stock = dict(BranchStock.objects.filter(branch=branch).values_list("product_id", "quantity"))
    on_order = incoming(branch)
    sourcing = {s.product_id: s for s in ProductSourcing.objects.select_related("supplier")}
    rows = []
    for p in Product.objects.filter(is_active=True).order_by("category", "name"):
        s = sourcing.get(p.id)
        level = s.reorder_level if s else 0
        have, coming = stock.get(p.id, 0), on_order.get(p.id, 0)
        low = level > 0 and have + coming <= level
        rows.append({
            "id": p.id, "name": p.name, "category": p.category, "price": money(p.price),
            "supplierId": s.supplier_id if s and s.supplier and s.supplier.is_active else None,
            "supplierName": s.supplier.name if s and s.supplier else None,
            "unitCost": money(s.unit_cost) if s and s.unit_cost is not None else None,
            "reorderLevel": level,
            "inStock": have,
            "onOrder": coming,
            "low": low,
            # Enough to get back to twice the reorder level.
            "suggested": max(level * 2 - have - coming, 1) if low else 0,
        })
    return rows


# --- what the screens get --------------------------------------------------------

def order_payload(order, account):
    lines = list(order.lines.all())
    receipts = list(order.receipts.select_related("received_by"))
    received_any = any(line.received_quantity for line in lines)
    ordering = can(account, ORDER) and may_use_branch(account, order.branch)
    approving = can(account, APPROVE)
    return {
        "id": order.id,
        "number": order.number,
        "branch": order.branch,
        "supplier": {"id": order.supplier_id, "name": order.supplier.name, "email": order.supplier.email,
                     "phone": order.supplier.phone, "leadTimeDays": order.supplier.lead_time_days},
        "status": order.status,
        "statusLabel": PurchaseOrder.Status(order.status).label,
        "total": money(order.total),
        "neededBy": order.needed_by,
        "rush": is_rush(order),
        "note": order.note,
        "requestedBy": order.requested_by.full_name,
        "createdAt": timezone.localtime(order.created_at).strftime("%Y-%m-%d %H:%M"),
        "autoApproved": order.auto_approved,
        "approvedBy": order.approved_by.full_name if order.approved_by else None,
        "approvedAt": timezone.localtime(order.approved_at).strftime("%Y-%m-%d %H:%M") if order.approved_at else None,
        "rejectedBy": order.rejected_by.full_name if order.rejected_by else None,
        "rejectionReason": order.rejection_reason,
        "sentAt": timezone.localtime(order.sent_at).strftime("%Y-%m-%d %H:%M") if order.sent_at else None,
        "sendError": order.send_error,
        "cancelledBy": order.cancelled_by.full_name if order.cancelled_by else None,
        "cancelReason": order.cancel_reason,
        "closedShort": order.closed_short,
        "lines": [
            {"id": line.id, "productId": line.product_id, "description": line.description, "quantity": line.quantity,
             "unitCost": money(line.unit_cost), "lineTotal": money(line.line_total),
             "received": line.received_quantity, "outstanding": line.outstanding}
            for line in lines
        ],
        "receipts": [
            {"receivedBy": r.received_by.full_name, "receivedAt": timezone.localtime(r.received_at).strftime("%Y-%m-%d %H:%M"),
             "amount": money(r.amount), "items": r.items, "note": r.note}
            for r in receipts
        ],
        "canApprove": approving and order.status == PurchaseOrder.Status.PENDING and order.requested_by_id != account.id,
        "canReceive": ordering and order.status in RECEIVABLE,
        "canCancel": (ordering or approving) and order.status in (PurchaseOrder.Status.PENDING, PurchaseOrder.Status.ORDERED)
        and not received_any,
        "canResend": ordering and order.status in RECEIVABLE,
        "canClose": ordering and order.status == PurchaseOrder.Status.PARTIAL,
    }

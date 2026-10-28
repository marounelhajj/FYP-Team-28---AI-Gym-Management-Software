import json

from django.contrib.auth.hashers import check_password
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.log import record
from audit.models import AuditLog
from billing.models import PaymentMethod
from checkins.models import CheckInFlag
from training.events import delete_training_events_for_member

from .models import AccessCardReissue, Member

# User story (SCRUM-62): "As a member, I want to request an export or
# deletion of my personal data, so that I have control over my own privacy."
#
# Export: one JSON file with everything held about the signed-in member.
# It is built from the member's own session only - there is no member id
# in the URL, so nobody can ask for someone else's.
#
# Deletion - the retention rule:
#   * Personal data is REMOVED outright: login credentials, contact details,
#     the payment method on file, access-card reissue notes, check-in flag
#     notes, and every AI training event (training.events.
#     delete_training_events_for_member).
#   * Records the gym has to keep are KEPT but ANONYMIZED, not hard-deleted:
#       - the Member row itself, so the records below keep their anchor
#         (name, email, phone replaced; username/password cleared; status
#         Cancelled; the access card is revoked),
#       - payments (financial records; amounts and dates stay, the person
#         behind them does not),
#       - the signed waiver (liability protection; version, ticks and date
#         stay, the typed signature name is replaced),
#       - check-ins (kept for branch headcount history; they only point at
#         the anonymized member),
#       - audit log entries (permanent by design, SCRUM-124): entries by or
#         about the member keep their action, time and branch, but names,
#         free-text summaries, IP address and profile-change values are scrubbed.
#   * The deletion request itself is then written to the audit log.

CONFIRM_WORD = "DELETE"
REDACTED = "[removed]"
EXPORT_FORMAT_VERSION = 1
SCRUBBED_DETAIL_KEYS = {"changes", "name", "email", "phone"}


def anonymized_name(member):
    return f"Deleted member #{member.pk}"


def _stamp(value):
    return value.isoformat() if value else None


def _waiver_of(member):
    return getattr(member, "waiver", None) if hasattr(member, "waiver") else None


def build_export(member):
    payment_method = PaymentMethod.objects.filter(member=member).first()
    waiver = _waiver_of(member)
    return {
        "exportFormatVersion": EXPORT_FORMAT_VERSION,
        "exportedAt": timezone.now().isoformat(),
        "profile": {
            "id": member.pk,
            "name": member.name,
            "email": member.email,
            "phone": member.phone,
            "username": member.username,
            "branch": member.branch,
            "joinDate": _stamp(member.join_date),
            "accessCardNumber": member.access_card_number,
        },
        "membership": {
            "plan": member.membership_plan,
            "status": member.status,
            "subscriptionExpiresAt": _stamp(member.subscription_expires_at),
        },
        # Last four digits only - the full card or account number is never stored.
        "paymentMethod": None if payment_method is None else {
            "method": payment_method.method,
            "summary": payment_method.reference() or payment_method.method,
            "cardHolderName": payment_method.card_holder_name,
            "cardLast4": payment_method.card_last4,
            "cardExpiryMonth": payment_method.card_expiry_month,
            "cardExpiryYear": payment_method.card_expiry_year,
            "bankName": payment_method.bank_name,
            "bankAccountLast4": payment_method.bank_account_last4,
        },
        "payments": [
            {
                "id": p.pk, "amount": f"{p.amount:.2f}", "method": p.method, "methodDetail": p.method_detail,
                "duration": p.duration, "paidAt": _stamp(p.paid_at), "expiresAt": _stamp(p.expires_at), "note": p.note,
            }
            for p in member.payments.all()
        ],
        "checkIns": [
            {
                "id": c.pk, "result": c.result, "reason": c.reason, "branch": c.branch,
                "checkedInAt": _stamp(c.checked_in_at), "checkedOutAt": _stamp(c.checked_out_at),
            }
            for c in member.check_ins.all()
        ],
        "waiver": None if waiver is None else {
            "signatureName": waiver.signature_name,
            "waiverVersion": waiver.waiver_version,
            "healthDisclaimerAccepted": waiver.health_disclaimer_accepted,
            "liabilityWaiverAccepted": waiver.liability_waiver_accepted,
            "signedVia": waiver.signed_via,
            "signedAt": _stamp(waiver.signed_at),
        },
        "accessCardReissues": [
            {"cardNumber": r.card_number, "reason": r.reason, "note": r.note, "reissuedAt": _stamp(r.reissued_at)}
            for r in member.card_reissues.all()
        ],
        "retailPurchases": [
            {"id": s.pk, "total": f"{s.total:.2f}", "soldAt": _stamp(s.sold_at), "voided": s.voided_at is not None}
            for s in member.retail_purchases.all()
        ],
        "trainingEvents": [
            {
                "eventType": e.event_type, "occurredAt": _stamp(e.occurred_at), "branch": e.branch,
                "sessionId": e.session_id, "payload": e.payload,
            }
            for e in member.training_events.all()
        ],
    }


# Audit entries are immutable on purpose (AuditLog.save/delete and the
# queryset's update/delete all refuse). A data-deletion request is the one
# case that must reach into them, so this goes straight to the base
# QuerySet.update, skipping AuditLogQuerySet's guard. Nothing else should.
def _scrub_audit_entries(member):
    label = anonymized_name(member)
    by_member = AuditLog.objects.filter(actor_member=member)
    about_member = AuditLog.objects.filter(target_type="member", target_id=str(member.pk))

    models.QuerySet.update(
        by_member, actor_name=label, actor_username="", ip_address=None, summary=f"{label} action",
    )
    models.QuerySet.update(about_member.exclude(actor_member=member), summary=f"Action on {label}")
    models.QuerySet.update(about_member, target_label=label)

    # details can hold the old and new name/email/phone of a profile edit.
    for entry in AuditLog.objects.filter(models.Q(actor_member=member) | models.Q(target_type="member", target_id=str(member.pk))):
        scrubbed = {k: v for k, v in (entry.details or {}).items() if k not in SCRUBBED_DETAIL_KEYS}
        if scrubbed != entry.details:
            models.QuerySet.update(AuditLog.objects.filter(pk=entry.pk), details=scrubbed)


def anonymize_member(member):
    with transaction.atomic():
        member.name = anonymized_name(member)
        member.email = f"deleted-member-{member.pk}@deleted.invalid"
        member.phone = ""
        member.username = None
        member.password_hash = None
        member.status = Member.Status.CANCELLED
        # Revokes the QR / door card (it is signed with this number).
        member.access_card_number += 1
        member.save()

        waiver = _waiver_of(member)
        if waiver is not None:
            waiver.signature_name = REDACTED
            waiver.save(update_fields=["signature_name"])

        PaymentMethod.objects.filter(member=member).delete()
        AccessCardReissue.objects.filter(member=member).delete()
        CheckInFlag.objects.filter(check_in__member=member).update(note="", resolution_note="")
        delete_training_events_for_member(member.pk)
        _scrub_audit_entries(member)


def _member_from_session(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


# GET /api/members/me/export
# The signed-in member's own data as a downloadable JSON file. Audited.
@api_view(["GET"])
def my_data_export(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied

    data = build_export(member)
    record(
        request, AuditLog.Action.MEMBER_DATA_EXPORTED, actor=member, target=member,
        summary=f"{member.name} exported their personal data",
        details={
            "payments": len(data["payments"]), "checkIns": len(data["checkIns"]),
            "trainingEvents": len(data["trainingEvents"]),
        },
    )
    response = HttpResponse(json.dumps(data, indent=2, cls=DjangoJSONEncoder), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="fitness-zone-my-data-{member.pk}.json"'
    return response


# POST /api/members/me/delete
# Body: { password, confirm: "DELETE" } - both are required, so a stray
# click or a borrowed phone can't erase an account.
# 200 + {"ok": true} after anonymizing (see the retention rule at the top of
# this file); the session is flushed, so the member is signed out and
# can't log in again. 400 if the confirmation word is missing, 403 if the
# password is wrong.
@api_view(["POST"])
def my_data_delete(request):
    member, denied = _member_from_session(request)
    if denied:
        return denied

    if (request.data.get("confirm") or "").strip() != CONFIRM_WORD:
        return Response({"error": f"Type {CONFIRM_WORD} to confirm."}, status=400)
    password = request.data.get("password") or ""
    if not member.password_hash or not check_password(password, member.password_hash):
        return Response({"error": "That password isn't right."}, status=403)

    branch = member.branch
    anonymize_member(member)
    entry = record(
        request, AuditLog.Action.MEMBER_DATA_DELETED, actor=member, target=member, branch=branch,
        summary=f"{anonymized_name(member)} requested deletion of their personal data",
        details={"memberId": member.pk},
    )
    # Same rule as the scrub above: no IP address stays attached to a deleted member.
    models.QuerySet.update(AuditLog.objects.filter(pk=entry.pk), ip_address=None)
    request.session.flush()
    return Response({"ok": True})

from django.db import transaction
from django.utils import timezone

from . import waiver as wording
from .models import Waiver, WaiverSignature

# Recording waiver signatures (SCRUM-83).
#
# Every signature - at walk-in registration, at online signup, or a member
# re-signing after the wording changed - goes through sign(): it stores one
# WaiverSignature row (member, version, signed name, time, IP address and a
# snapshot of the exact text) and makes it the member's current Waiver.


def client_ip(request):
    if request is None:
        return None
    return (request.META.get("REMOTE_ADDR") or "").strip() or None


def sign(member, signature, signed_via, *, witnessed_by=None, ip=None, now=None):
    """signature: the dict WaiverSignatureFields.pop_signature() returns."""
    now = now or timezone.now()
    fields = {
        "signature_name": signature["signature_name"],
        "health_disclaimer_accepted": signature["health_disclaimer_accepted"],
        "liability_waiver_accepted": signature["liability_waiver_accepted"],
        # Always the version whose text is being stored, read at signing time.
        "waiver_version": wording.WAIVER_VERSION,
        "text_snapshot": wording.current_text(),
        "signed_via": signed_via,
        "witnessed_by": witnessed_by,
        "ip_address": ip,
        "signed_at": now,
    }
    with transaction.atomic():
        WaiverSignature.objects.create(member=member, **fields)
        waiver, _ = Waiver.objects.update_or_create(member=member, defaults=fields)
    return waiver


def record_data(signature):
    """A signed record as staff (and the member themselves) see it."""
    return {
        "signatureName": signature.signature_name,
        "waiverVersion": signature.waiver_version,
        "liabilityWaiverAccepted": signature.liability_waiver_accepted,
        "healthDisclaimerAccepted": signature.health_disclaimer_accepted,
        "signedVia": signature.signed_via,
        "witnessedBy": signature.witnessed_by.full_name if signature.witnessed_by else None,
        "ipAddress": signature.ip_address,
        "signedAt": signature.signed_at,
        "text": signature.text_snapshot,
    }


def waiver_payload(member):
    waiver = getattr(member, "waiver", None) if hasattr(member, "waiver") else None
    return {
        "memberId": member.pk,
        "currentVersion": wording.WAIVER_VERSION,
        "onFile": waiver is not None,
        "needsResign": waiver is None or waiver.needs_resign,
        "current": None if waiver is None else record_data(waiver),
        "history": [record_data(s) for s in member.waiver_signatures.select_related("witnessed_by")],
    }

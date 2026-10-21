from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from billing.serializers import PaymentSerializer
from plans.models import MembershipPlan
from training.events import log_training_event
from training.models import TrainingEvent

from . import qr
from .models import AccessCardReissue, Member
from .waiver import HEALTH_DISCLAIMER_TEXT, LIABILITY_WAIVER_TEXT, WAIVER_VERSION
from .serializers import (
    AccessCardReissueCreateSerializer, AccessCardReissueSerializer, MemberCreateSerializer, MemberSerializer,
)


# Every customer without a valid subscription - it expired, or they never
# paid for one - is Frozen. Subscriptions don't auto-renew, so this runs
# lazily on every directory read (no Celery/cron in this project) as one
# bulk UPDATE. Nothing reverses it automatically - only Payment.record()
# (a registration or a renewal) sets Active again. Cancelled members are
# left as they are.
def _freeze_lapsed_members():
    Member.objects.filter(status=Member.Status.ACTIVE).filter(
        Q(subscription_expires_at__isnull=True) | Q(subscription_expires_at__lt=timezone.localdate())
    ).update(status=Member.Status.FROZEN)


# Member-session counterpart to authorize() above - looks the member up
# from request.session["member_id"] instead of a staff permission. Same
# pattern as billing.views._get_member_from_session (separate module,
# same shape - members and billing each own their slice of session lookup
# rather than importing across apps for one helper).
def _get_member_from_session(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return None, Response({"error": "Not authenticated."}, status=401)
    member = Member.objects.filter(id=member_id).first()
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


# GET  /api/members/  - search/filter/paginate the member directory
# POST /api/members/  - register a new walk-in member and their first payment
#
# GET query params (all optional, all combinable):
#   q        - case-insensitive substring match on member name
#   status   - exact match: Active | Frozen | Cancelled
#   branch   - exact match: Hamra | Achrafieh | Jnah | Zalka
#   limit    - max results to return (default 25, max 100)
#   offset   - pagination offset (default 0)
#
# User story (GET): "As a receptionist, I want to search and filter the
# member directory by name, membership status, or branch, so that I can
# quickly find a member's record."
#
# POST body: { name, email, phone, branch, membershipPlan, paymentMethod, paymentDuration }
# On success: 201 + the created member plus a "firstPayment" block
# (amount, method, paidAt, note) confirming what activated the membership.
# The amount is never part of the request body - see MemberCreateSerializer.
# On validation failure: 400 + {"error": {field: [messages]}}.
#
# User story (POST): "As a receptionist, I want to register a new walk-in
# member's profile and membership plan, so that I can onboard new customers
# on the spot." / "As a receptionist, I want to process a new member's first
# payment during registration, so that their membership is activated
# immediately."
@api_view(["GET", "POST"])
def member_list(request):
    # The directory holds personal data: staff with manage_members only.
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied

    if request.method == "POST":
        # The receptionist is recorded as the witness on the member's waiver.
        serializer = MemberCreateSerializer(data=request.data, context={"staff_account": account})
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        member = serializer.save()
        data = MemberSerializer(member).data
        data["firstPayment"] = PaymentSerializer(member.first_payment).data
        payment = member.first_payment
        record(
            request, AuditLog.Action.MEMBER_REGISTERED, actor=account, target=member,
            summary=f"Registered walk-in member {member.name} on {member.membership_plan} "
                    f"(paid ${payment.amount:.2f} by {payment.method})",
            details={"plan": member.membership_plan, "amount": f"{payment.amount:.2f}", "method": payment.method},
        )
        return Response(data, status=201)

    _freeze_lapsed_members()

    q = request.query_params.get("q")
    status_param = request.query_params.get("status")
    branch = request.query_params.get("branch")

    try:
        limit = int(request.query_params.get("limit", 25))
    except ValueError:
        limit = 25
    limit = max(1, min(limit, 100))

    try:
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        offset = 0
    offset = max(0, offset)

    valid_statuses = [choice.value for choice in Member.Status]
    valid_branches = [choice.value for choice in Member.Branch]

    if status_param and status_param not in valid_statuses:
        return Response(
            {"error": f'Invalid status "{status_param}". Must be one of: {", ".join(valid_statuses)}'},
            status=400,
        )
    if branch and branch not in valid_branches:
        return Response(
            {"error": f'Invalid branch "{branch}". Must be one of: {", ".join(valid_branches)}'},
            status=400,
        )

    queryset = Member.objects.select_related("waiver__witnessed_by").all()
    if q and q.strip():
        queryset = queryset.filter(name__icontains=q.strip())
    if status_param:
        queryset = queryset.filter(status=status_param)
    if branch:
        queryset = queryset.filter(branch=branch)

    total = queryset.count()
    page = queryset[offset : offset + limit]
    serialized = MemberSerializer(page, many=True).data

    return Response({"total": total, "limit": limit, "offset": offset, "results": serialized})


# GET /api/members/meta/
# Returns the valid filter values so the frontend dropdowns never hardcode
# a list that can drift out of sync with the model's choices. "plans" is
# the plans the General Manager currently sells (cheapest first), so the
# walk-in and online signup forms always offer the real tiers. There's no
# price data here anymore - forms get live, branch-aware pricing from
# GET /api/plans/pricing (see frontend's fetchBranchPricing), which also
# factors in any running BranchPromotion, so the price preview can never
# drift out of sync with what Payment.record() actually charges.
@api_view(["GET"])
def member_meta(request):
    return Response(
        {
            "branches": [choice.value for choice in Member.Branch],
            "statuses": [choice.value for choice in Member.Status],
            "plans": list(MembershipPlan.objects.filter(is_active=True).values_list("name", flat=True)),
        }
    )


# GET /api/members/waiver
# Public: the liability waiver + health disclaimer text both signup forms
# show, and its version (recorded with each signature). See waiver.py.
@api_view(["GET"])
def waiver_text(request):
    return Response({
        "version": WAIVER_VERSION,
        "liabilityWaiver": LIABILITY_WAIVER_TEXT,
        "healthDisclaimer": HEALTH_DISCLAIMER_TEXT,
    })


# GET /api/members/<id>/
@api_view(["GET"])
def member_detail(request, member_id):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    try:
        member = Member.objects.select_related("waiver__witnessed_by").get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)

    member.refresh_expiry_status()

    return Response(MemberSerializer(member).data)


# POST /api/members/<id>/cancel
# Ends a subscribed member's subscription - sets status to Cancelled. No
# body needed. subscription_expires_at is left as-is (so the date it would
# have lapsed on stays visible in history) - it's status that governs
# everything: a Cancelled member is excluded from the lazy "freeze lapsed
# members" sweep (which only ever touches Active members) and reactivating
# them later still goes through the normal Payment.record() path (the
# "Subscribe" button), same as any Frozen member.
#
# User story: "As a receptionist, I want to process a new member's first
# payment during registration, so that their membership is activated
# immediately." - the natural counterpart: ending a subscription for a
# currently-subscribed member.
@api_view(["POST"])
def member_cancel(request, member_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)

    previous = member.status
    member.status = Member.Status.CANCELLED
    member.save(update_fields=["status"])
    record(
        request, AuditLog.Action.MEMBER_CANCELLED, actor=account, target=member,
        summary=f"Cancelled {member.name}'s membership at the front desk", details={"previousStatus": previous},
    )
    log_training_event(
        TrainingEvent.EventType.CANCELLATION, member=member,
        payload={"previousStatus": previous, "channel": "front_desk"},
    )
    return Response(MemberSerializer(member).data)


# POST /api/members/me/freeze
# POST /api/members/me/resume
# POST /api/members/me/cancel
#
# User story: "As a member, I want to freeze or cancel my membership
# through the app, so that I have control over my subscription without a
# front-desk visit." No body needed on any of the three.
#
# Freeze/resume is new - there was no manual freeze anywhere before this
# (Frozen was only ever set automatically by refresh_expiry_status/the
# lapsed-members sweep above). Keeping it a simple status toggle: freezing
# doesn't touch subscription_expires_at, so the days spent frozen still
# count against it - no pause-the-billing-clock tracking for this pass.
# Cancel is the self-service twin of member_cancel below, same effect,
# just scoped by session instead of a staff permission.


# Only an Active member (one with a currently valid subscription) can
# freeze - refresh_expiry_status() runs first so a member whose
# subscription already quietly lapsed is correctly left Frozen for the
# real reason (nothing to freeze, they need to renew) rather than this
# endpoint doing it again.
@api_view(["POST"])
def my_freeze(request):
    member, denied = _get_member_from_session(request)
    if denied:
        return denied

    member.refresh_expiry_status()
    if member.status == Member.Status.FROZEN:
        return Response({"error": "Your membership is already frozen."}, status=400)
    if member.status == Member.Status.CANCELLED:
        return Response({"error": "A cancelled membership can't be frozen."}, status=400)

    member.status = Member.Status.FROZEN
    member.save(update_fields=["status"])
    record(request, AuditLog.Action.MEMBER_FROZEN, actor=member, target=member, summary=f"{member.name} froze their membership")
    return Response(MemberSerializer(member).data)


# Undoes a self-service freeze for free - but only when
# subscription_expires_at is still in the future, i.e. the freeze really
# was voluntary (my_freeze above only ever freezes an Active - so a
# currently-valid - subscription). If the subscription has since lapsed
# while frozen, this refuses: same rule as everywhere else in this app,
# "only Payment.record() (a renewal) sets a member back to Active" - this
# can't be the one place that quietly lets that slide.
@api_view(["POST"])
def my_resume(request):
    member, denied = _get_member_from_session(request)
    if denied:
        return denied

    if member.status == Member.Status.ACTIVE:
        return Response({"error": "Your membership is already active."}, status=400)
    if member.status == Member.Status.CANCELLED:
        return Response(
            {"error": "A cancelled membership can't be resumed - renew at the front desk to rejoin."}, status=400,
        )
    if not member.has_valid_subscription():
        return Response(
            {"error": "Your subscription has expired - renew at the front desk to reactivate."}, status=400,
        )

    member.status = Member.Status.ACTIVE
    member.save(update_fields=["status"])
    record(request, AuditLog.Action.MEMBER_RESUMED, actor=member, target=member, summary=f"{member.name} resumed their membership")
    return Response(MemberSerializer(member).data)


# Self-service twin of member_cancel below - same effect (status ->
# Cancelled, subscription_expires_at left as-is), scoped by session
# instead of a staff permission. Permissive about the member's current
# status, same as member_cancel.
@api_view(["POST"])
def my_cancel(request):
    member, denied = _get_member_from_session(request)
    if denied:
        return denied

    previous = member.status
    member.status = Member.Status.CANCELLED
    member.save(update_fields=["status"])
    record(
        request, AuditLog.Action.MEMBER_CANCELLED, actor=member, target=member,
        summary=f"{member.name} cancelled their membership in the app", details={"previousStatus": previous},
    )
    log_training_event(
        TrainingEvent.EventType.CANCELLATION, member=member, payload={"previousStatus": previous, "channel": "app"},
    )
    return Response(MemberSerializer(member).data)


def _access_card_data(member):
    reissues = member.card_reissues.select_related("reissued_by")
    latest = reissues.first()
    payload = qr.payload_for(member)
    return {
        "member": MemberSerializer(member).data,
        "card": {
            "number": member.access_card_number,
            # The original card dates from sign-up; a reissued one from its reissue.
            "issuedOn": timezone.localtime(latest.reissued_at).date() if latest else member.join_date,
            "issuedBy": latest.reissued_by.full_name if latest and latest.reissued_by else None,
            "payload": payload,
            "qrCode": qr.svg_data_uri(payload),
        },
        "history": AccessCardReissueSerializer(reissues, many=True).data,
    }


# GET  /api/members/<id>/access-card - the member's current access card (QR code) and its reissue history.
# POST /api/members/<id>/access-card - reissue it. Body: { reason, note?, identityConfirmed }.
# The previous card stops working immediately (members/qr.py).
@api_view(["GET", "POST"])
def member_access_card(request, member_id):
    account, denied = authorize(request, "manage_members")
    if denied:
        return denied

    member = Member.objects.select_related("waiver__witnessed_by").filter(id=member_id).first()
    if member is None:
        return Response({"error": f"Member {member_id} not found"}, status=404)
    member.refresh_expiry_status()

    if request.method == "GET":
        return Response(_access_card_data(member))

    serializer = AccessCardReissueCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    with transaction.atomic():
        # Locked so two reissues at once can't hand out the same card number.
        member.access_card_number = Member.objects.select_for_update().get(pk=member.pk).access_card_number + 1
        member.save(update_fields=["access_card_number"])
        AccessCardReissue.objects.create(
            member=member, card_number=member.access_card_number, reissued_by=account,
            reason=serializer.validated_data["reason"], note=serializer.validated_data["note"],
        )
        record(
            request, AuditLog.Action.ACCESS_CARD_REISSUED, actor=account, target=member,
            summary=f"Reissued {member.name}'s access card (card {member.access_card_number}, "
                    f"{serializer.validated_data['reason'].lower()})",
            details={"cardNumber": member.access_card_number, "reason": serializer.validated_data["reason"],
                     "note": serializer.validated_data["note"]},
        )
    return Response(_access_card_data(member), status=201)

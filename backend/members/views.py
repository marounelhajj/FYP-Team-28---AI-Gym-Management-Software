from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from billing.models import PLAN_PRICES, Payment, price_for
from billing.serializers import PaymentCreateSerializer, PaymentSerializer
from .models import Member
from .serializers import MemberSerializer, MemberCreateSerializer


# Subscriptions don't auto-renew: this is the only place that ever flips a
# lapsed member's status from Active to Frozen (every customer without a
# valid/current subscription is Frozen, same status a staff-initiated
# freeze uses), run lazily on every read (no Celery/cron in this project)
# as a single bulk UPDATE rather than a per-row loop. Nothing ever reverses
# this automatically - only Payment.record() (a new registration or a
# renewal) sets Active again.
def _freeze_lapsed_members():
    Member.objects.filter(
        status=Member.Status.ACTIVE,
        subscription_expires_at__lt=timezone.localdate(),
    ).update(status=Member.Status.FROZEN)


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
    if request.method == "POST":
        serializer = MemberCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        member = serializer.save()
        data = MemberSerializer(member).data
        data["firstPayment"] = PaymentSerializer(member.first_payment).data
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

    queryset = Member.objects.all()
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
# a list that can drift out of sync with the model's choices, plus the
# price for each plan (billing.models.price_for) so forms can display what
# a plan costs without letting anyone type their own amount. yearlyPrices
# gives both the undiscounted ("original") and actual ("discounted") 1-year
# price, so the UI can show the promo as a struck-through old price next
# to the real one - the frontend never computes this itself.
@api_view(["GET"])
def member_meta(request):
    return Response(
        {
            "branches": [choice.value for choice in Member.Branch],
            "statuses": [choice.value for choice in Member.Status],
            "plans": [choice.value for choice in Member.Plan],
            "planPrices": {plan: str(price) for plan, price in PLAN_PRICES.items()},
            "yearlyPrices": {
                plan: {
                    "original": str(monthly * 12),
                    "discounted": str(price_for(plan, Payment.Duration.ONE_YEAR)),
                }
                for plan, monthly in PLAN_PRICES.items()
            },
        }
    )


# GET /api/members/<id>/
@api_view(["GET"])
def member_detail(request, member_id):
    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)

    member.refresh_expiry_status()

    return Response(MemberSerializer(member).data)


# POST /api/members/<id>/payments
# Body: { membershipPlan, method, duration } - amount is never accepted
# here either, it's price_for(membershipPlan, duration) (see
# Payment.record()). membershipPlan is required and explicit every time -
# this is also how a receptionist changes a member's plan at renewal.
# Records a new payment for an EXISTING member - the "repay to reactivate"
# action for a lapsed (Frozen) subscription, or an early renewal for a
# still-Active one. See Payment.record() for the expiry/reactivation logic.
#
# User story: "As a receptionist, I want to process a new member's first
# payment during registration, so that their membership is activated
# immediately." - extended to cover repayment after the subscription
# expires, since it's deliberately not auto-renewed.
@api_view(["POST"])
def member_payment(request, member_id):
    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)

    serializer = PaymentCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)

    data = serializer.validated_data
    payment = Payment.record(
        member, data["membershipPlan"], data["method"], data["duration"], note="Renewal payment",
    )
    response_data = MemberSerializer(member).data
    response_data["payment"] = PaymentSerializer(payment).data
    return Response(response_data, status=201)


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
    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)

    member.status = Member.Status.CANCELLED
    member.save(update_fields=["status"])
    return Response(MemberSerializer(member).data)

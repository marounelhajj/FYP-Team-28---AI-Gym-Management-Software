from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.models import StaffAccount
from members.models import Member

from .models import BranchPromotion, MembershipPlan
from .serializers import (
    BranchPromotionSerializer,
    BranchPromotionWriteSerializer,
    MembershipPlanSerializer,
    MembershipPlanWriteSerializer,
)

MANAGE_PLANS_PERMISSION = "manage_membership_plans"
MANAGE_PROMOTIONS_PERMISSION = "manage_branch_promotions"


# Reading plans/promotions/pricing is open to any screen (e.g. the
# receptionist's registration form will need prices), but changing them
# requires a logged-in, active staff account whose role grants at least one
# of `permissions`. Returns (account, None) if allowed, else (None, error).
def _require_permission(request, *permissions):
    account_id = request.session.get("staff_account_id")
    account = None
    if account_id:
        account = StaffAccount.objects.select_related("role").filter(id=account_id, is_active=True).first()

    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    if not any(p in account.role.permissions for p in permissions):
        return None, Response({"error": "You don't have permission to do that."}, status=403)
    return account, None


def _validate_branch(branch):
    valid_branches = [choice.value for choice in Member.Branch]
    if branch and branch not in valid_branches:
        return Response(
            {"error": f'Invalid branch "{branch}". Must be one of: {", ".join(valid_branches)}'},
            status=400,
        )
    return None


# GET  /api/plans  - list membership plans (cheapest first)
# POST /api/plans  - create a new organization-wide plan
#
# GET query params (optional):
#   isActive  - "true" | "false" (omit to get both active and archived)
#
# POST body: { name, description, price, billingCycle, features, maxPromoDiscountPercent }
# On success: 201 + the created plan.
# On validation failure: 400 + {"error": {field: [messages]}}.
#
# User story: "As a general manager, I want to set organization-wide
# membership plans and pricing tiers, so that pricing stays consistent
# across branches while still allowing local promotions."
@api_view(["GET", "POST"])
def plan_list(request):
    if request.method == "POST":
        _, denied = _require_permission(request, MANAGE_PLANS_PERMISSION)
        if denied:
            return denied
        serializer = MembershipPlanWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        plan = serializer.save()
        return Response(MembershipPlanSerializer(plan).data, status=201)

    queryset = MembershipPlan.objects.all()
    active_param = request.query_params.get("isActive")
    if active_param is not None:
        queryset = queryset.filter(is_active=active_param.lower() == "true")

    serialized = MembershipPlanSerializer(queryset, many=True).data
    return Response({"total": len(serialized), "results": serialized})


# GET   /api/plans/<id>  - fetch one plan
# PATCH /api/plans/<id>  - edit pricing/details/promo cap, or archive/restore
#                          via { isActive: false / true }
@api_view(["GET", "PATCH"])
def plan_detail(request, plan_id):
    try:
        plan = MembershipPlan.objects.get(id=plan_id)
    except MembershipPlan.DoesNotExist:
        return Response({"error": f"Plan {plan_id} not found"}, status=404)

    if request.method == "PATCH":
        _, denied = _require_permission(request, MANAGE_PLANS_PERMISSION)
        if denied:
            return denied
        serializer = MembershipPlanWriteSerializer(plan, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        plan = serializer.save()

    return Response(MembershipPlanSerializer(plan).data)


# GET /api/plans/meta
# Returns the valid billing cycles, branches and discount types so the
# plan/promotion forms never hardcode lists that can drift from the models.
@api_view(["GET"])
def plan_meta(request):
    return Response({
        "billingCycles": [choice.value for choice in MembershipPlan.BillingCycle],
        "branches": [choice.value for choice in Member.Branch],
        "discountTypes": [{"value": c.value, "label": c.label} for c in BranchPromotion.DiscountType],
    })


# GET  /api/plans/promotions  - list branch promotions
# POST /api/plans/promotions  - create a local promotion for one branch
#
# GET query params (all optional, all combinable):
#   branch   - exact match: Hamra | Achrafieh | Jnah | Zalka
#   planId   - exact match on plan id
#
# POST body: { planId, branch, name, discountType, discountValue, startDate, endDate }
# Rejected (400) if the discount exceeds the plan's maxPromoDiscountPercent.
#
# Branch managers (manage_branch_promotions) and general managers
# (manage_membership_plans) can both create promotions.
@api_view(["GET", "POST"])
def promotion_list(request):
    if request.method == "POST":
        account, denied = _require_permission(request, MANAGE_PROMOTIONS_PERMISSION, MANAGE_PLANS_PERMISSION)
        if denied:
            return denied
        serializer = BranchPromotionWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        promotion = serializer.save(created_by=account)
        return Response(BranchPromotionSerializer(promotion).data, status=201)

    branch = request.query_params.get("branch")
    invalid = _validate_branch(branch)
    if invalid:
        return invalid

    queryset = BranchPromotion.objects.select_related("plan", "created_by").all()
    if branch:
        queryset = queryset.filter(branch=branch)
    plan_id = request.query_params.get("planId")
    if plan_id:
        queryset = queryset.filter(plan_id=plan_id)

    serialized = BranchPromotionSerializer(queryset, many=True).data
    return Response({"total": len(serialized), "results": serialized})


# GET   /api/plans/promotions/<id>  - fetch one promotion
# PATCH /api/plans/promotions/<id>  - edit, or cancel via { isActive: false }
@api_view(["GET", "PATCH"])
def promotion_detail(request, promotion_id):
    try:
        promotion = BranchPromotion.objects.select_related("plan", "created_by").get(id=promotion_id)
    except BranchPromotion.DoesNotExist:
        return Response({"error": f"Promotion {promotion_id} not found"}, status=404)

    if request.method == "PATCH":
        _, denied = _require_permission(request, MANAGE_PROMOTIONS_PERMISSION, MANAGE_PLANS_PERMISSION)
        if denied:
            return denied
        serializer = BranchPromotionWriteSerializer(promotion, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        promotion = serializer.save()

    return Response(BranchPromotionSerializer(promotion).data)


# GET /api/plans/pricing?branch=Hamra
# What each active plan actually costs at one branch today: the
# organization-wide base price, minus the best running promotion for that
# branch (if any), capped at the plan's maxPromoDiscountPercent.
@api_view(["GET"])
def branch_pricing(request):
    branch = request.query_params.get("branch")
    if not branch:
        return Response({"error": "branch is required."}, status=400)
    invalid = _validate_branch(branch)
    if invalid:
        return invalid

    today = timezone.localdate()
    plans = MembershipPlan.objects.filter(is_active=True)
    running = BranchPromotion.objects.select_related("plan").filter(
        branch=branch, is_active=True, start_date__lte=today, end_date__gte=today, plan__is_active=True,
    )

    best_by_plan = {}
    for promo in running:
        best = best_by_plan.get(promo.plan_id)
        if best is None or promo.discount_amount() > best.discount_amount():
            best_by_plan[promo.plan_id] = promo

    results = []
    for plan in plans:
        promo = best_by_plan.get(plan.id)
        results.append({
            "planId": plan.id,
            "name": plan.name,
            "billingCycle": plan.billing_cycle,
            "basePrice": f"{plan.price:.2f}",
            "effectivePrice": f"{promo.effective_price() if promo else plan.price:.2f}",
            "promotion": {"id": promo.id, "name": promo.name, "endDate": promo.end_date} if promo else None,
        })
    return Response({"branch": branch, "date": today, "results": results})

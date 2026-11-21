from decimal import Decimal

from django.utils import timezone

from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import changes, record
from audit.models import AuditLog
from members.models import Member

from . import offers
from .models import MarketingCampaign
from .serializers import AudiencePreviewSerializer, MarketingCampaignSerializer, MarketingCampaignWriteSerializer

# Running a campaign (Marketing Staff's own screen) and viewing the
# cross-branch comparison (the General Manager's) are different
# privileges - same split as finance's manage_billing vs
# view_financial_reports.
MANAGE_PERMISSION = "manage_marketing_campaigns"
REPORT_PERMISSION = "view_marketing_campaigns"


def _campaigns():
    return MarketingCampaign.objects.select_related("created_by")


def _snapshot(campaign):
    data = dict(MarketingCampaignSerializer(campaign, context={"results": {campaign.id: None}}).data)
    data["segment"] = {k: v for k, v in data["segment"].items() if k != "description"}
    return {
        k: v for k, v in data.items()
        if k not in ("status", "createdBy", "results", "launchedAt", "offerLocked", "discountLabel")
    }


# The list/report rows, with each campaign's results in two extra queries.
def _serialize(campaigns):
    campaigns = list(campaigns)
    context = {"results": offers.results([c.id for c in campaigns])}
    return MarketingCampaignSerializer(campaigns, many=True, context=context).data


def _detail(campaign):
    data = dict(MarketingCampaignSerializer(campaign).data)
    if campaign.has_offer and campaign.status in ("Scheduled", "Running"):
        data["audience"] = offers.audience_summary(campaign)
    return data


# GET  /api/marketing/campaigns?branch=&isActive= - every campaign (Marketing
#      Staff's own management screen), newest-starting first.
# POST /api/marketing/campaigns - start a new campaign at one branch.
#
# Gated on manage_marketing_campaigns - the permission already existed,
# seeded onto the Marketing Staff role, but nothing used it until now.
@api_view(["GET", "POST"])
def campaign_list(request):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied

    if request.method == "POST":
        serializer = MarketingCampaignWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        campaign = serializer.save(created_by=account)
        offer = f" with offer {campaign.offer_code} ({campaign.discount_label})" if campaign.has_offer else ""
        record(
            request, AuditLog.Action.CAMPAIGN_CREATED, actor=account, target=campaign, branch=campaign.branch,
            summary=f"Started marketing campaign {campaign.name} at {campaign.branch}{offer}",
            details=_snapshot(campaign),
        )
        return Response(_detail(campaign), status=201)

    branch = (request.query_params.get("branch") or "").strip()
    if branch and branch not in Member.Branch.values:
        return Response(
            {"error": f'Invalid branch "{branch}". Must be one of: {", ".join(Member.Branch.values)}'}, status=400,
        )
    queryset = _campaigns()
    if branch:
        queryset = queryset.filter(branch=branch)
    if request.query_params.get("isActive") in ("true", "false"):
        queryset = queryset.filter(is_active=request.query_params["isActive"] == "true")

    serialized = _serialize(queryset)
    return Response({"total": len(serialized), "results": serialized})


# GET   /api/marketing/campaigns/<id> - one campaign, its audience right now
#       (while it's scheduled or running) and the latest uses of its code.
# PATCH /api/marketing/campaigns/<id> - edit, or cancel via { isActive: false }.
#       Once a campaign has started its offer and audience are fixed (see
#       MarketingCampaignWriteSerializer); cancelling one whose offer already
#       went out tells the members who got it that it's withdrawn.
@api_view(["GET", "PATCH"])
def campaign_detail(request, campaign_id):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied
    campaign = _campaigns().filter(id=campaign_id).first()
    if campaign is None:
        return Response({"error": f"Campaign {campaign_id} not found."}, status=404)

    if request.method == "GET":
        data = _detail(campaign)
        uses = campaign.redemptions.select_related("member", "redeemed_by")[:RECENT_USES]
        data["recentUses"] = [_use_data(r) for r in uses]
        return Response(data)

    serializer = MarketingCampaignWriteSerializer(campaign, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    was_active = campaign.is_active
    before = _snapshot(campaign)
    campaign = serializer.save()
    changed = changes(before, _snapshot(campaign))
    told = 0
    if was_active and not campaign.is_active and campaign.has_offer:
        told = offers.notify_withdrawn(campaign)
    if changed:
        summary = f"Edited marketing campaign {campaign.name} at {campaign.branch} ({', '.join(sorted(changed))})"
        if was_active and not campaign.is_active:
            summary = f"Cancelled marketing campaign {campaign.name} at {campaign.branch}"
            if told:
                summary += f" ({told} member{'s' if told != 1 else ''} told the offer is withdrawn)"
        record(
            request, AuditLog.Action.CAMPAIGN_UPDATED, actor=account, target=campaign, branch=campaign.branch,
            summary=summary, details={"changes": changed},
        )
    data = _detail(campaign)
    data["withdrawnNotices"] = told
    return Response(data)


RECENT_USES = 50


def _use_data(r):
    return {
        "id": r.id,
        "member": r.member.name,
        "memberId": r.member_id,
        "use": r.use,
        "saleId": r.sale_id,
        "amountBefore": f"{r.amount_before:.2f}",
        "discount": f"{r.discount:.2f}",
        "amountPaid": f"{r.amount_paid:.2f}",
        "redeemedAt": timezone.localtime(r.redeemed_at).strftime("%Y-%m-%d %H:%M"),
        "redeemedBy": r.redeemed_by.full_name if r.redeemed_by else None,
        "voided": r.voided_at is not None,
    }


# POST /api/marketing/audience - Body: { branch, segment } - how many members
# a segment reaches right now (and how many by email, or have offers turned
# off), so the form can show it live while the segment is built.
@api_view(["POST"])
def audience_preview(request):
    _, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied
    serializer = AudiencePreviewSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    segment = data.get("segment") or {}
    draft = MarketingCampaign(
        branch=data["branch"],
        segment_statuses=segment.get("statuses") or list(offers.DEFAULT_STATUSES),
        segment_plans=segment.get("plans", []),
        segment_renewal_within_days=segment.get("renewalWithinDays"),
        segment_inactive_days=segment.get("inactiveDays"),
        segment_joined_within_days=segment.get("joinedWithinDays"),
    )
    return Response(offers.audience_summary(draft))


# GET /api/members/me/offers - the offers the signed-in member was sent and
# can still use today.
@api_view(["GET"])
def my_offers(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)
    return Response({"results": offers.offers_for(member)})


# GET /api/marketing/meta - branches, for either screen's branch picker, and
# what the campaign form offers: plans (with the General Manager's cap on how
# much a membership can be discounted), member statuses, discount types and
# what a code can be used on.
@api_view(["GET"])
def marketing_meta(request):
    from plans.models import MembershipPlan

    _, denied = authorize(request, MANAGE_PERMISSION, REPORT_PERMISSION)
    if denied:
        return denied
    return Response({
        "branches": list(Member.Branch.values),
        "plans": [
            {"name": p.name, "active": p.is_active, "maxDiscountPercent": f"{p.max_promo_discount_percent:.2f}"}
            for p in MembershipPlan.objects.order_by("-is_active", "price", "name")
        ],
        "statuses": [{"value": v, "label": offers.STATUS_WORDS[v].capitalize()} for v in Member.Status.values],
        "discountTypes": [{"value": v, "label": label} for v, label in MarketingCampaign.DiscountType.choices],
        "appliesTo": [{"value": v, "label": label} for v, label in MarketingCampaign.AppliesTo.choices],
        "sendFrom": offers.SEND_FROM.strftime("%H:%M"),
        "today": timezone.localdate(),
    })


# GET /api/marketing/report?branch= - every branch the General Manager can
# compare, each with its campaigns, total budget and total spent so far.
# Every branch is always listed, even with no campaigns running, same
# convention as audit.views.retention_report and finance.views.financial_report.
#
# User story: "As a general manager, I want to view the marketing
# campaigns and strategies being run at each branch, so that I can assess
# alignment with overall brand direction and spending."
@api_view(["GET"])
def campaign_report(request):
    _, denied = authorize(request, REPORT_PERMISSION)
    if denied:
        return denied

    requested = (request.query_params.get("branch") or "").strip()
    if requested and requested not in Member.Branch.values:
        return Response(
            {"error": f'Invalid branch "{requested}". Must be one of: {", ".join(Member.Branch.values)}'}, status=400,
        )
    branch_list = [requested] if requested else list(Member.Branch.values)

    all_campaigns = _campaigns().filter(branch__in=branch_list)

    branches = []
    totals = {"budget": Decimal("0"), "spent": Decimal("0")}
    for branch in branch_list:
        rows = list(all_campaigns.filter(branch=branch))
        budget = sum((c.budget for c in rows), Decimal("0"))
        spent = sum((c.amount_spent for c in rows), Decimal("0"))
        totals["budget"] += budget
        totals["spent"] += spent
        branches.append({
            "branch": branch,
            "campaignCount": len(rows),
            "budget": f"{budget:.2f}",
            "spent": f"{spent:.2f}",
            "campaigns": _serialize(rows),
        })

    return Response({
        "branches": branches,
        "totals": {"budget": f"{totals['budget']:.2f}", "spent": f"{totals['spent']:.2f}"},
    })

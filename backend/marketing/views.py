from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import changes, record
from audit.models import AuditLog
from members.models import Member

from .models import MarketingCampaign
from .serializers import MarketingCampaignSerializer, MarketingCampaignWriteSerializer

# Running a campaign (Marketing Staff's own screen) and viewing the
# cross-branch comparison (the General Manager's) are different
# privileges - same split as finance's manage_billing vs
# view_financial_reports.
MANAGE_PERMISSION = "manage_marketing_campaigns"
REPORT_PERMISSION = "view_marketing_campaigns"


def _campaigns():
    return MarketingCampaign.objects.select_related("created_by")


def _snapshot(campaign):
    data = dict(MarketingCampaignSerializer(campaign).data)
    return {k: v for k, v in data.items() if k not in ("status", "createdBy")}


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
        record(
            request, AuditLog.Action.CAMPAIGN_CREATED, actor=account, target=campaign, branch=campaign.branch,
            summary=f"Started marketing campaign {campaign.name} at {campaign.branch}",
            details=_snapshot(campaign),
        )
        return Response(MarketingCampaignSerializer(campaign).data, status=201)

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

    serialized = MarketingCampaignSerializer(queryset, many=True).data
    return Response({"total": len(serialized), "results": serialized})


# PATCH /api/marketing/campaigns/<id> - edit, or cancel via { isActive: false }.
@api_view(["PATCH"])
def campaign_detail(request, campaign_id):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied
    campaign = _campaigns().filter(id=campaign_id).first()
    if campaign is None:
        return Response({"error": f"Campaign {campaign_id} not found."}, status=404)

    serializer = MarketingCampaignWriteSerializer(campaign, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    before = _snapshot(campaign)
    campaign = serializer.save()
    changed = changes(before, _snapshot(campaign))
    if changed:
        record(
            request, AuditLog.Action.CAMPAIGN_UPDATED, actor=account, target=campaign, branch=campaign.branch,
            summary=f"Edited marketing campaign {campaign.name} at {campaign.branch} ({', '.join(sorted(changed))})",
            details={"changes": changed},
        )
    return Response(MarketingCampaignSerializer(campaign).data)


# GET /api/marketing/meta - branches, for either screen's branch picker.
@api_view(["GET"])
def marketing_meta(request):
    _, denied = authorize(request, MANAGE_PERMISSION, REPORT_PERMISSION)
    if denied:
        return denied
    return Response({"branches": list(Member.Branch.values)})


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
            "campaigns": MarketingCampaignSerializer(rows, many=True).data,
        })

    return Response({
        "branches": branches,
        "totals": {"budget": f"{totals['budget']:.2f}", "spent": f"{totals['spent']:.2f}"},
    })

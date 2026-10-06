from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize

from .models import Member
from .serializers import MemberSerializer, MemberCreateSerializer


# GET  /api/members/  - search/filter/paginate the member directory
# POST /api/members/  - register a new walk-in member
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
# POST body: { name, email, phone, branch, membershipPlan }
# On success: 201 + the created member (same shape as a GET result).
# On validation failure: 400 + {"error": {field: [messages]}}.
#
# User story (POST): "As a receptionist, I want to register a new walk-in
# member's profile and membership plan, so that I can onboard new customers
# on the spot."
@api_view(["GET", "POST"])
def member_list(request):
    # The directory holds personal data: staff with manage_members only.
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    if request.method == "POST":
        serializer = MemberCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        member = serializer.save()
        return Response(MemberSerializer(member).data, status=201)

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
# a list that can drift out of sync with the model's choices.
@api_view(["GET"])
def member_meta(request):
    return Response(
        {
            "branches": [choice.value for choice in Member.Branch],
            "statuses": [choice.value for choice in Member.Status],
            "plans": [choice.value for choice in Member.Plan],
        }
    )


# GET /api/members/<id>/
@api_view(["GET"])
def member_detail(request, member_id):
    _, denied = authorize(request, "manage_members")
    if denied:
        return denied

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        return Response({"error": f"Member {member_id} not found"}, status=404)
    return Response(MemberSerializer(member).data)

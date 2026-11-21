from rest_framework.decorators import api_view
from rest_framework.response import Response

from members.models import Member

from . import points


# GET /api/members/me/loyalty - the logged-in member's own points balance,
# referral code (to hand to a friend), and how each entry was earned.
#
# User story: "As a member, I want to earn loyalty points for attending
# sessions and referring friends, so that my consistency is rewarded."
@api_view(["GET"])
def my_loyalty(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return Response({"error": "Not authenticated."}, status=401)
    return Response(points.summary(member))

from django.contrib.auth.hashers import check_password
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Member
from .serializers import MemberSerializer, MemberSignupSerializer

# Member sign-in/sign-up. Separate session key ("member_id") from staff
# ("staff_account_id" in administration/auth_views.py) so the two account
# types can never be confused with each other, and logging in as one kind
# of account clears any session for the other.


def _session_payload(member):
    return MemberSerializer(member).data


# POST /api/members/signup
# Body: { name, email, phone, branch, membershipPlan, username, password }
# 201 + member/session payload on success (also logs the new member in).
# 400 + field errors (e.g. username/email already taken) on failure.
@api_view(["POST"])
def signup(request):
    serializer = MemberSignupSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    member = serializer.save()

    request.session.pop("staff_account_id", None)
    request.session["member_id"] = member.id
    return Response(_session_payload(member), status=201)


# POST /api/members/login
# Body: { username, password }
# 200 + member/session payload on success.
# 401 + {"error": ...} if the username/password don't match any account -
# including members who were walk-in registered and never set a password.
@api_view(["POST"])
def login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    try:
        member = Member.objects.get(username=username)
    except Member.DoesNotExist:
        return Response({"error": "Invalid username or password."}, status=401)

    if not member.password_hash or not check_password(password, member.password_hash):
        return Response({"error": "Invalid username or password."}, status=401)

    request.session.pop("staff_account_id", None)
    request.session["member_id"] = member.id
    return Response(_session_payload(member))


# POST /api/members/logout
@api_view(["POST"])
def logout(request):
    request.session.flush()
    return Response({"ok": True})


# GET /api/members/me
@api_view(["GET"])
def me(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return Response({"error": "Not authenticated."}, status=401)

    try:
        member = Member.objects.get(id=member_id)
    except Member.DoesNotExist:
        request.session.flush()
        return Response({"error": "Not authenticated."}, status=401)

    return Response(_session_payload(member))

from rest_framework.response import Response

from members.models import Member

# Who sees which members (SCRUM-43: "Segments are org-wide for the general
# manager and marketing staff; a branch manager sees segments limited to
# their branch").
#
# Org-wide: any role with view_all_branches (General Manager) or
# manage_member_segments (Marketing Staff). Everyone else is held to the
# branch on their staff account; asking for another branch is a 403, the
# same rule as every other branch screen (headcount.views.resolve_branch).

ALL_BRANCHES = "view_all_branches"
MANAGE = "manage_member_segments"
VIEW = "view_member_segments"
EXPORT_MEMBERS = "export_segment_members"


def visible_branches(account):
    """(branches, error_response)."""
    permissions = account.role.permissions
    if ALL_BRANCHES in permissions or MANAGE in permissions:
        return list(Member.Branch.values), None
    if not account.branch:
        return None, Response(
            {"error": "Your account isn't assigned to a branch yet. Ask a System Administrator to set one."},
            status=403,
        )
    return [account.branch], None


def narrow(account, requested):
    """Branches to report on for an optional ?branch= (branches, error)."""
    branches, error = visible_branches(account)
    if error:
        return None, error
    requested = (requested or "").strip()
    if not requested:
        return branches, None
    if requested not in Member.Branch.values:
        return None, Response(
            {"error": f'Invalid branch "{requested}". Must be one of: {", ".join(Member.Branch.values)}'}, status=400,
        )
    if requested not in branches:
        return None, Response({"error": "You can only see members of your own branch."}, status=403)
    return [requested], None


def segment_visible(segment, branches):
    """A segment limited to other branches is hidden from a branch manager."""
    wanted = segment.filters.get("branches")
    return not wanted or bool(set(wanted) & set(branches))

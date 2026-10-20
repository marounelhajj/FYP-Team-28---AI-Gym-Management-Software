from administration.models import StaffAccount
from members.models import Member

from .models import AuditLog

# The one way entries get written. Views call record() right after the
# action succeeds (or, for failed sign-ins, right after it's refused):
#
#   record(request, AuditLog.Action.PLAN_UPDATED, actor=account, target=plan,
#          summary=f"Edited plan {plan.name}", details={"changes": changes(before, after)})
#
# `actor` is the StaffAccount or Member who did it (None when nobody is
# signed in). `target` is the model instance it was done to.


def _client_ip(request):
    ip = (request.META.get("REMOTE_ADDR") or "").strip()
    return ip or None


def _target_label(target):
    for attr in ("full_name", "name", "username"):
        value = getattr(target, attr, None)
        if value:
            return str(value)[:200]
    return str(target)[:200]


def record(request, action, *, actor=None, target=None, summary, branch=None, details=None, actor_username=None):
    entry = AuditLog(action=action, summary=summary[:255], details=details or {}, ip_address=_client_ip(request))

    if isinstance(actor, StaffAccount):
        entry.actor_type = AuditLog.ActorType.STAFF
        entry.actor_staff = actor
        entry.actor_name = actor.full_name
        entry.actor_username = actor.username
        entry.actor_role = actor.role.name
    elif isinstance(actor, Member):
        entry.actor_type = AuditLog.ActorType.MEMBER
        entry.actor_member = actor
        entry.actor_name = actor.name
        entry.actor_username = actor.username or ""
        entry.actor_role = "Member"
    else:
        entry.actor_type = AuditLog.ActorType.ANONYMOUS
    if actor_username is not None:
        entry.actor_username = actor_username[:60]

    if target is not None:
        entry.target_type = target._meta.model_name
        entry.target_id = str(target.pk)
        entry.target_label = _target_label(target)

    if branch is None:
        branch = getattr(target, "branch", None) or getattr(actor, "branch", None) or ""
    entry.branch = branch

    entry.save()
    return entry


# {field: [old, new]} for every key whose value differs between two
# snapshots (e.g. a serializer's .data before and after an edit).
def changes(before, after, ignore=()):
    return {
        key: [before.get(key), after.get(key)]
        for key in after
        if key not in ignore and before.get(key) != after.get(key)
    }

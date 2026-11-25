from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from classes.models import ClassType
from members.models import Member
from plans.models import MembershipPlan

from . import filters as seg_filters
from .clustering import latest_run, run_clustering
from .models import ClusterGroup, ClusterRun, Segment
from .profiles import build_profiles
from .scope import EXPORT_MEMBERS, MANAGE, VIEW, narrow, segment_visible, visible_branches

# Member segments (SCRUM-43). See segments/models.py and scope.py.
#
# view_member_segments: see segments, their counts, trends and uptake, and
#   export the aggregate numbers (General Manager, Marketing Staff, Branch
#   Manager - the last held to their own branch).
# manage_member_segments: also create/edit/delete segments, run the
#   clustering and save a suggested segment (General Manager, Marketing Staff).
# export_segment_members: export a segment's member list (General Manager,
#   Marketing Staff). Opted-out and deleted members are never in it.

MAX_COMPARE = 3


def _today():
    return timezone.localdate()


def _who(request, *permissions):
    account, error = authorize(request, *permissions)
    if error:
        return None, None, error
    branches, error = visible_branches(account)
    if error:
        return None, None, error
    return account, branches, None


def _profiles(branches, today):
    return build_profiles(Member.objects.filter(branch__in=branches), today)


def _evaluate(filters, profiles, today):
    return seg_filters.apply(profiles, filters, today)


def _counts(members):
    opted_out = sum(1 for p in members if p.opted_out)
    return {"count": len(members), "optedOut": opted_out, "targetable": len(members) - opted_out}


def segment_data(segment, profiles=None, today=None):
    data = {
        "id": segment.pk,
        "name": segment.name,
        "description": segment.description,
        "filters": segment.filters,
        "summary": seg_filters.describe(segment.filters),
        "source": segment.source,
        "createdBy": segment.created_by.full_name if segment.created_by else None,
        "createdAt": segment.created_at,
        "updatedAt": segment.updated_at,
    }
    if profiles is not None:
        data.update(_counts(_evaluate(segment.filters, profiles, today)))
    return data


def _read_segment_body(body, existing=None):
    """(name, description, filters, error_response)."""
    body = body if isinstance(body, dict) else {}
    name = body.get("name", existing.name if existing else "")
    name = " ".join(str(name or "").split())
    if not name:
        return None, None, None, Response({"error": {"name": ["Give the segment a name."]}}, status=400)
    if len(name) > 60:
        return None, None, None, Response({"error": {"name": ["Keep the name to 60 characters."]}}, status=400)
    clash = Segment.objects.filter(name__iexact=name)
    if existing:
        clash = clash.exclude(pk=existing.pk)
    if clash.exists():
        return None, None, None, Response({"error": {"name": ["There is already a segment with that name."]}}, status=400)
    description = str(body.get("description", existing.description if existing else "") or "").strip()
    if len(description) > 300:
        return None, None, None, Response({"error": {"description": ["Keep it to 300 characters."]}}, status=400)
    try:
        filters = seg_filters.clean_filters(body.get("filters", existing.filters if existing else {}))
    except seg_filters.FilterError as e:
        return None, None, None, Response({"error": {"filters": [str(e)]}}, status=400)
    return name, description, filters, None


# GET /api/segments/meta - what the filter builder can offer, and what the caller may do.
@api_view(["GET"])
def meta(request):
    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    permissions = account.role.permissions
    plans = list(MembershipPlan.objects.values_list("name", flat=True).order_by("name"))
    class_types = sorted(set(ClassType.objects.filter(branch__in=branches).values_list("name", flat=True)))
    return Response({
        "branches": branches,
        "orgWide": len(branches) > 1,
        "statuses": list(Member.Status.values),
        "defaultStatuses": list(seg_filters.DEFAULT_STATUSES),
        "plans": plans,
        "classTypes": class_types,
        "riskLevels": seg_filters.RISK_LEVELS,
        "canManage": MANAGE in permissions,
        "canExportMembers": EXPORT_MEMBERS in permissions,
        "maxCompare": MAX_COMPARE,
    })


# GET /api/segments - every segment the caller can see, with live counts.
# POST /api/segments {name, description, filters} - create one.
@api_view(["GET", "POST"])
def segment_list(request):
    if request.method == "POST":
        account, branches, error = _who(request, MANAGE)
        if error:
            return error
        name, description, filters, error = _read_segment_body(request.data)
        if error:
            return error
        segment = Segment.objects.create(
            name=name, description=description, filters=filters,
            source=Segment.Source.CLUSTER if "clusterGroup" in filters else Segment.Source.RULES,
            created_by=account, updated_by=account,
        )
        record(
            request, AuditLog.Action.SEGMENT_SAVED, actor=account, target=segment,
            summary=f'Created segment "{segment.name}"', details={"filters": filters},
        )
        today = _today()
        return Response(segment_data(segment, _profiles(branches, today), today), status=201)

    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    today = _today()
    profiles = _profiles(branches, today)
    segments = [s for s in Segment.objects.select_related("created_by") if segment_visible(s, branches)]
    return Response({
        "branches": branches,
        "segments": [segment_data(s, profiles, today) for s in segments],
    })


# POST /api/segments/preview {filters} - the live count while filters change.
@api_view(["POST"])
def preview(request):
    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    try:
        filters = seg_filters.clean_filters((request.data or {}).get("filters"))
    except seg_filters.FilterError as e:
        return Response({"error": {"filters": [str(e)]}}, status=400)
    today = _today()
    members = _evaluate(filters, _profiles(branches, today), today)
    return Response({**_counts(members), "summary": seg_filters.describe(filters), "filters": filters})


def _get_segment(segment_id, branches):
    segment = Segment.objects.select_related("created_by").filter(pk=segment_id).first()
    if segment is None or not segment_visible(segment, branches):
        return None, Response({"error": "Segment not found."}, status=404)
    return segment, None


# GET/PUT/DELETE /api/segments/<id>
@api_view(["GET", "PUT", "PATCH", "DELETE"])
def segment_detail(request, segment_id):
    if request.method == "GET":
        account, branches, error = _who(request, VIEW, MANAGE)
    else:
        account, branches, error = _who(request, MANAGE)
    if error:
        return error
    segment, error = _get_segment(segment_id, branches)
    if error:
        return error
    today = _today()

    if request.method == "DELETE":
        name = segment.name
        record(
            request, AuditLog.Action.SEGMENT_DELETED, actor=account, target=segment,
            summary=f'Deleted segment "{name}"', details={"filters": segment.filters},
        )
        segment.delete()
        return Response({"ok": True})

    if request.method in ("PUT", "PATCH"):
        name, description, filters, error = _read_segment_body(request.data, existing=segment)
        if error:
            return error
        segment.name, segment.description, segment.filters = name, description, filters
        segment.updated_by, segment.updated_at = account, timezone.now()
        segment.save()
        record(
            request, AuditLog.Action.SEGMENT_SAVED, actor=account, target=segment,
            summary=f'Edited segment "{segment.name}"', details={"filters": filters},
        )

    return Response(segment_data(segment, _profiles(branches, today), today))


def _run_data(run, branches):
    if run is None:
        return None
    visible = set(Member.objects.filter(branch__in=branches).values_list("id", flat=True))
    return {
        "id": run.pk,
        "ranAt": run.ran_at,
        "trigger": run.trigger,
        "triggerLabel": run.get_trigger_display(),
        "modelVersion": run.model_version,
        "k": run.k,
        "silhouette": run.silhouette,
        "candidates": run.candidates,
        "membersClustered": run.members_clustered,
        "features": run.feature_names,
        "note": run.note,
        "groups": [
            {
                "id": g.pk,
                "name": g.name,
                "description": g.description,
                "size": g.size,
                # A branch manager sees how many of the cluster are in their branch.
                "sizeInScope": sum(1 for m in g.member_ids if m in visible),
                "centroid": g.centroid,
                "savedAs": [
                    {"id": s.pk, "name": s.name}
                    for s in Segment.objects.filter(filters__clusterGroup=g.pk)
                ],
            }
            for g in run.groups.all()
        ],
    }


# GET /api/segments/clusters - the latest suggested segments.
@api_view(["GET"])
def clusters(request):
    account, branches, error = _who(request, VIEW, MANAGE)
    if error:
        return error
    return Response({"run": _run_data(latest_run(), branches)})


# POST /api/segments/clusters/run - recalculate now.
@api_view(["POST"])
def clusters_run(request):
    account, branches, error = _who(request, MANAGE)
    if error:
        return error
    run = run_clustering(trigger=ClusterRun.Trigger.MANUAL, by=account)
    record(
        request, AuditLog.Action.SEGMENT_CLUSTERS_RUN, actor=account,
        summary=f"Recalculated suggested segments ({run.k or 0} groups, {run.members_clustered} members)",
        details={"runId": run.pk, "k": run.k, "silhouette": run.silhouette, "modelVersion": run.model_version},
    )
    run = ClusterRun.objects.prefetch_related("groups").get(pk=run.pk)
    return Response({"run": _run_data(run, branches)}, status=201)


# POST /api/segments/clusters/<group_id>/save {name?, description?} - keep a suggested segment.
@api_view(["POST"])
def cluster_save(request, group_id):
    account, branches, error = _who(request, MANAGE)
    if error:
        return error
    group = ClusterGroup.objects.filter(pk=group_id).first()
    if group is None:
        return Response({"error": "Suggested segment not found."}, status=404)
    body = request.data if isinstance(request.data, dict) else {}
    data = {
        "name": body.get("name") or group.name,
        "description": body.get("description") or group.description[:300],
        "filters": {"clusterGroup": group.pk},
    }
    name, description, filters, error = _read_segment_body(data)
    if error:
        return error
    segment = Segment.objects.create(
        name=name, description=description, filters=filters, source=Segment.Source.CLUSTER,
        created_by=account, updated_by=account,
    )
    record(
        request, AuditLog.Action.SEGMENT_SAVED, actor=account, target=segment,
        summary=f'Saved suggested segment "{group.name}" as "{segment.name}"',
        details={"filters": filters, "clusterRunId": group.run_id},
    )
    today = _today()
    return Response(segment_data(segment, _profiles(branches, today), today), status=201)

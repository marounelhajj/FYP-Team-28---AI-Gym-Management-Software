from django.db import migrations

# SCRUM-43/112/113/114: the seeded roles get the segment permissions on
# databases seeded before they existed. Marketing Staff and the General
# Manager build segments and can export member lists; a Branch Manager can
# see segments, trends and uptake for their own branch. Roles can be changed
# in the Admin Console afterwards.

GRANTS = {
    "Marketing Staff": ["manage_member_segments", "view_member_segments", "export_segment_members"],
    "General Manager": ["manage_member_segments", "view_member_segments", "export_segment_members"],
    "Branch Manager": ["view_member_segments"],
}


def grant(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for name, permissions in GRANTS.items():
        for role in Role.objects.filter(name=name):
            missing = [p for p in permissions if p not in role.permissions]
            if missing:
                role.permissions = [*role.permissions, *missing]
                role.save(update_fields=["permissions"])


def revoke(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for name, permissions in GRANTS.items():
        for role in Role.objects.filter(name=name):
            role.permissions = [p for p in role.permissions if p not in permissions]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("segments", "0001_initial"),
        ("administration", "0005_branch_manager_manages_expenses"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

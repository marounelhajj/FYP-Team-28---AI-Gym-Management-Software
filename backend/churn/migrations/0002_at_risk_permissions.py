from django.db import migrations

# SCRUM-118: the seeded Branch Manager and General Manager roles get the
# at-risk list on databases seeded before these permissions existed. A
# Branch Manager is still held to their own branch by the server; the
# General Manager's view_all_branches lets them pick any. Roles can be
# changed in the Admin Console afterwards.

GRANTS = {
    "Branch Manager": ["view_at_risk_members", "manage_at_risk_list"],
    "General Manager": ["view_at_risk_members", "manage_at_risk_list"],
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
        ("churn", "0001_initial"),
        ("administration", "0005_branch_manager_manages_expenses"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

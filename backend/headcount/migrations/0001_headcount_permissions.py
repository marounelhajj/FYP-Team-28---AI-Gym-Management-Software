from django.db import migrations

# Live headcount (SCRUM-127) is a Branch Manager screen, and a General
# Manager can look at any branch. Grants the new permissions to the seeded
# roles on databases seeded before they existed. Roles can still be changed
# in the Admin Console afterwards.

GRANTS = {
    "Branch Manager": ["view_branch_headcount"],
    "General Manager": ["view_branch_headcount", "view_all_branches"],
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
        ("administration", "0003_staff_two_factor"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

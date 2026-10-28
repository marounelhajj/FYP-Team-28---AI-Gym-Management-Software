from django.db import migrations

# Branch Finances (SCRUM-26): a Branch Manager records, edits and deletes
# their own branch's expenses, which needs manage_billing. Today that
# permission only gates the expense endpoints, and the server keeps a Branch
# Manager to their own branch (finance/views.py). Grants it on databases
# seeded before; roles can still be changed in the Admin Console.

GRANTS = {"Branch Manager": ["manage_billing"]}


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
        ("administration", "0004_system_administrator_sees_all_branches"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

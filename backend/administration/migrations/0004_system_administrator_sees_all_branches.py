from django.db import migrations

# The System Administrator role can open the Financial Report and Expenses
# (view_financial_reports, manage_billing) but isn't tied to a branch, so
# without view_all_branches those screens refused it ("Your account isn't
# assigned to a branch yet"). It's an organisation-wide role: grant it on
# databases seeded before. Roles can still be changed in the Admin Console.

GRANTS = {"System Administrator": ["view_all_branches"]}


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

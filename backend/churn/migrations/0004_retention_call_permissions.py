from django.db import migrations

# SCRUM-68: receptionists and branch managers log retention calls from the
# at-risk list, so the seeded Receptionist role can now open the list and
# both roles can log calls. A receptionist is held to their own branch like
# everywhere else; they can't refresh the list or change the call capacity.

GRANTS = {
    "Receptionist": ["view_at_risk_members", "log_retention_calls"],
    "Branch Manager": ["log_retention_calls"],
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
        ("churn", "0003_retentioncall"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

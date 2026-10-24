from django.db import migrations

# Receptionists and Branch Managers ring up sales; General Managers and
# Branch Managers look after the catalog and stock. Grants the new
# permissions to the seeded roles on databases seeded before they existed;
# roles can still be changed in the Admin Console afterwards.

GRANTS = {
    "Receptionist": ["process_sales"],
    "Branch Manager": ["process_sales", "manage_retail_products"],
    "General Manager": ["manage_retail_products"],
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
        ("retail", "0001_retail"),
        ("administration", "0003_staff_two_factor"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

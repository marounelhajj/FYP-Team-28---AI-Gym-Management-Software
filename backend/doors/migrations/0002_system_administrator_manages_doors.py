from django.db import migrations

# Door readers are set up by a System Administrator. Grants the new
# permission to the seeded role on databases seeded before it existed; roles
# can still be changed in the Admin Console afterwards.

GRANTS = {"System Administrator": ["manage_doors"]}


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
        ("doors", "0001_door"),
        ("administration", "0003_staff_two_factor"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

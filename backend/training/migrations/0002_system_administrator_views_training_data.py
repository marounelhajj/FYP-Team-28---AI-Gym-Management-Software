from django.db import migrations

# The training-event query endpoint (SCRUM-73) is for System Administrators,
# so the seeded "System Administrator" role gets view_training_data on
# databases seeded before the permission existed. Roles can still be
# changed in the Admin Console afterwards.

PERMISSION = "view_training_data"


def grant(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name="System Administrator"):
        if PERMISSION not in role.permissions:
            role.permissions = [*role.permissions, PERMISSION]
            role.save(update_fields=["permissions"])


def revoke(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name="System Administrator"):
        if PERMISSION in role.permissions:
            role.permissions = [p for p in role.permissions if p != PERMISSION]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0001_initial"),
        ("administration", "0003_staff_two_factor"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

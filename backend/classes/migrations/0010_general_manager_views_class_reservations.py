from django.db import migrations

# SCRUM-22 is a General Manager story ("...view the class reservation
# schedule for each branch, so that I can monitor class utilization and
# demand"), so the seeded General Manager role gets view_class_reservations
# on databases that were seeded before this permission existed. Roles can
# still be changed in the Admin Console afterwards.

PERMISSION = "view_class_reservations"


def grant(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name="General Manager"):
        if PERMISSION not in role.permissions:
            role.permissions = [*role.permissions, PERMISSION]
            role.save(update_fields=["permissions"])


def revoke(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name="General Manager"):
        if PERMISSION in role.permissions:
            role.permissions = [p for p in role.permissions if p != PERMISSION]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("classes", "0009_waitlist"),
        ("administration", "0005_branch_manager_manages_expenses"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

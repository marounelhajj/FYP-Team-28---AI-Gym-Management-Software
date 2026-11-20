from django.db import migrations

# "As a branch manager, I want to submit supply reorder requests..." - big
# orders are approved by head office: the seeded General Manager and System
# Administrator roles get the new permission on databases seeded before it
# existed. Roles can still be changed in the Admin Console afterwards.

PERMISSION = "approve_purchase_orders"
ROLES = ["General Manager", "System Administrator"]


def grant(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name__in=ROLES):
        if PERMISSION not in role.permissions:
            role.permissions = [*role.permissions, PERMISSION]
            role.save(update_fields=["permissions"])


def revoke(apps, schema_editor):
    Role = apps.get_model("administration", "Role")
    for role in Role.objects.filter(name__in=ROLES):
        if PERMISSION in role.permissions:
            role.permissions = [p for p in role.permissions if p != PERMISSION]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0001_initial"),
        ("administration", "0005_branch_manager_manages_expenses"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

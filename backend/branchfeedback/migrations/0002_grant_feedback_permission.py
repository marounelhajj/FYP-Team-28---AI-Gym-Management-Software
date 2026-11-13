from django.db import migrations

# "As a branch manager, I want to view member feedback and complaints specific
# to my branch..." - the seeded Branch Manager role gets the new permission,
# and so do the General Manager and System Administrator (who see every
# branch: the company-wide view), on databases seeded before it existed.
# Roles can still be changed in the Admin Console afterwards.

PERMISSION = "manage_member_feedback"
ROLES = ["Branch Manager", "General Manager", "System Administrator"]


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
        ("branchfeedback", "0001_initial"),
        ("administration", "0005_branch_manager_manages_expenses"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

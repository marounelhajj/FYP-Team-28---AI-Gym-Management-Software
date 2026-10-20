from django.db import migrations

# SCRUM-125 is a General Manager story ("...search and filter the audit
# log... so that I can investigate a specific incident"), so the seeded
# General Manager role gets view_audit_log on databases that were seeded
# before this permission was part of it. Roles can still be changed in
# the Admin Console afterwards.

PERMISSION = "view_audit_log"


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
        ("audit", "0001_initial"),
        ("administration", "0003_staff_two_factor"),
    ]

    operations = [migrations.RunPython(grant, revoke)]

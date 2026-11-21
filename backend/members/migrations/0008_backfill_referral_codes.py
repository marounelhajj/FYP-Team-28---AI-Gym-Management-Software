import secrets

from django.db import migrations, models

# Easy to read out loud/type in: no 0/O or 1/I, which look alike on a
# handwritten receipt or a phone screen. Kept in sync with
# members.models.REFERRAL_CODE_ALPHABET/REFERRAL_CODE_LENGTH - this
# migration can't import that module (migrations must stand on their own),
# so it's copied here, once, for members that already existed when the
# referral_code field was added.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 6


def backfill_referral_codes(apps, schema_editor):
    Member = apps.get_model("members", "Member")
    used = set(Member.objects.exclude(referral_code="").values_list("referral_code", flat=True))
    for member in Member.objects.filter(referral_code=""):
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
            if code not in used:
                used.add(code)
                break
        member.referral_code = code
        member.save(update_fields=["referral_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0007_member_referral_code"),
    ]

    operations = [
        migrations.RunPython(backfill_referral_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="member",
            name="referral_code",
            field=models.CharField(max_length=8, unique=True),
        ),
    ]

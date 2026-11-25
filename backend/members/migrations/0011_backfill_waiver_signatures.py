from django.db import migrations

# SCRUM-83: one WaiverSignature per signature. Waivers signed before the
# history table existed get their row now. Version 2026-10 is the only
# wording there has ever been, so its text is the text they agreed to; any
# other version gets no snapshot rather than a wrong one. The IP address
# wasn't recorded then, so it stays empty.


def backfill(apps, schema_editor):
    from members.waiver import WAIVER_VERSION, current_text

    Waiver = apps.get_model("members", "Waiver")
    WaiverSignature = apps.get_model("members", "WaiverSignature")
    text = current_text()
    for w in Waiver.objects.all():
        snapshot = text if w.waiver_version == WAIVER_VERSION else ""
        if not w.text_snapshot:
            w.text_snapshot = snapshot
            w.save(update_fields=["text_snapshot"])
        if not WaiverSignature.objects.filter(member_id=w.member_id).exists():
            WaiverSignature.objects.create(
                member_id=w.member_id, signature_name=w.signature_name,
                health_disclaimer_accepted=w.health_disclaimer_accepted,
                liability_waiver_accepted=w.liability_waiver_accepted, waiver_version=w.waiver_version,
                text_snapshot=snapshot, signed_via=w.signed_via, witnessed_by_id=w.witnessed_by_id,
                ip_address=w.ip_address, signed_at=w.signed_at,
            )


class Migration(migrations.Migration):
    dependencies = [("members", "0010_waiver_signature_records")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

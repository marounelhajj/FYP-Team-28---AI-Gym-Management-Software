import segno
from django.core import signing

# Member check-in QR codes (SCRUM-33: "check in members via QR code or
# membership ID").
#
# The code a member shows at the front desk holds "FFM1:<id>:<signature>",
# signed with SECRET_KEY, so a code can't be made up from a guessed
# membership ID or edited to someone else's. A reissued card (see
# Member.access_card_number) also signs its card number in -
# "FFM1:<id>:<card>:<signature>" - so a lost or stolen earlier card can be
# told apart and refused. The original card keeps the shorter form, so codes
# handed out before reissuing existed still work. The membership ID typed
# at the desk keeps working alongside it.

PREFIX = "FFM1:"
_signer = signing.Signer(salt="fitness-factory.member-qr")


def payload_for(member):
    value = str(member.id) if member.access_card_number == 1 else f"{member.id}:{member.access_card_number}"
    return PREFIX + _signer.sign(value)


# (membership ID, card number) from a scanned payload, or None if it isn't
# a genuine, untampered Fitness Factory code.
def read(payload):
    payload = (payload or "").strip()
    if not payload.startswith(PREFIX):
        return None
    try:
        parts = [int(part) for part in _signer.unsign(payload[len(PREFIX):]).split(":")]
    except (signing.BadSignature, ValueError):
        return None
    if len(parts) == 1:
        return parts[0], 1
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def member_id_from(payload):
    card = read(payload)
    return card[0] if card else None


def svg_data_uri(payload):
    return segno.make(payload, error="m").svg_data_uri(scale=6, border=2)

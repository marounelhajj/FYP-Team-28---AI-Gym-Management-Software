import segno
from django.core import signing

# Member check-in QR codes (SCRUM-33: "check in members via QR code or
# membership ID").
#
# The code a member shows at the front desk holds "FFM1:<id>:<signature>",
# signed with SECRET_KEY, so a code can't be made up from a guessed
# membership ID or edited to someone else's. It never expires: it's the
# member's card, like a printed one. The membership ID typed at the desk
# keeps working alongside it.

PREFIX = "FFM1:"
_signer = signing.Signer(salt="fitness-factory.member-qr")


def payload_for(member):
    return PREFIX + _signer.sign(str(member.id))


# Membership ID from a scanned payload, or None if it isn't a genuine,
# untampered Fitness Factory code.
def member_id_from(payload):
    payload = (payload or "").strip()
    if not payload.startswith(PREFIX):
        return None
    try:
        return int(_signer.unsign(payload[len(PREFIX):]))
    except (signing.BadSignature, ValueError):
        return None


def svg_data_uri(payload):
    return segno.make(payload, error="m").svg_data_uri(scale=6, border=2)

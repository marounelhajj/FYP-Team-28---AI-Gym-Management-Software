from dataclasses import dataclass
from datetime import date

from .models import Member

# User story: "As a receptionist, I want door access to be granted or revoked
# automatically based on membership status, so that entry control stays in
# sync with payments without manual card management."
#
# The single rule for whether a member's card opens the gym. Nothing about
# access is stored or switched by hand: it's worked out from the membership
# every time a card is scanned (at a door or the front desk), so a payment,
# a lapse, a freeze/resume, a cancellation or a card reissue takes effect on
# the very next scan.


@dataclass(frozen=True)
class DoorAccess:
    granted: bool
    # Short label stored on a refused CheckIn ("" when granted).
    reason: str
    # What the door / front desk shows.
    message: str
    valid_until: date | None


# card_number: the card a scanned QR code was issued as, or None when nothing
# was scanned (membership ID typed at the desk, or just showing the status).
# Call member.refresh_expiry_status() first so the status isn't stale.
def door_access(member, card_number=None):
    expiry = member.subscription_expires_at
    if card_number is not None and card_number != member.access_card_number:
        return DoorAccess(False, "Replaced card", "This card was replaced and no longer opens the doors.", None)
    if member.status == Member.Status.CANCELLED:
        return DoorAccess(False, "Cancelled", "Membership cancelled.", None)
    if expiry is None:
        return DoorAccess(False, "No subscription", "No paid subscription yet.", None)
    if not member.has_valid_subscription():
        return DoorAccess(False, "Expired", f"Subscription expired on {expiry:%Y-%m-%d}.", None)
    if member.status == Member.Status.FROZEN:
        return DoorAccess(False, "Frozen", "Membership is frozen - resume it to get back in.", None)
    return DoorAccess(True, "", f"Open until {expiry:%Y-%m-%d}.", expiry)

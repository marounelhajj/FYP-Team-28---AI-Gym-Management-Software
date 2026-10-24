import hashlib
import secrets

from django.db import models

from members.models import Member

KEY_PREFIX = "door_"


def hash_door_key(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# A card reader on a gym door (a tablet or turnstile at the entrance or exit).
# It signs in with its own secret key, not a staff account, so an unattended
# device never holds a session that could open member data. Only a hash of
# the key is stored; the key itself is shown once, when it's created.
class Door(models.Model):
    class Kind(models.TextChoices):
        ENTRANCE = "Entrance", "Entrance"
        EXIT = "Exit", "Exit"

    name = models.CharField(max_length=80)
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    # Fixed per door on the server, so a device can't switch itself from
    # "entrance" to "exit" (exits always open).
    kind = models.CharField(max_length=10, choices=Kind.choices)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["branch", "name"]

    def __str__(self):
        return f"{self.name} ({self.branch}, {self.kind})"

    # Replaces the key (the old one stops working at once) and returns the new one.
    def set_new_key(self):
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        self.key_hash = hash_door_key(key)
        return key

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

# Time-based one-time passwords (RFC 6238) for staff two-factor sign-in.
#
# Same parameters Google Authenticator, Microsoft Authenticator, Authy etc.
# use by default: HMAC-SHA1, 6 digits, 30-second steps. A code from the step
# before or after the current one is still accepted (+/-1 step) to allow for
# a phone clock that is a few seconds off.

DIGITS = 6
STEP_SECONDS = 30
TOLERANCE_STEPS = 1
ISSUER = "Fitness Zone"


def generate_secret():
    # 20 random bytes = 160 bits, the size RFC 4226 recommends. Base32 is
    # what authenticator apps expect when the secret is typed in by hand.
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def code_at_step(secret, step):
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def code_at(secret, now=None):
    return code_at_step(secret, current_step(now))


# Returns the matching step number, or None. Steps at or before
# `last_used_step` are refused so a code that was already used to sign in
# can't be replayed within its 90-second validity window.
def verify(secret, code, now=None, last_used_step=None):
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - TOLERANCE_STEPS, step + TOLERANCE_STEPS + 1):
        if last_used_step is not None and candidate <= last_used_step:
            continue
        if hmac.compare_digest(code_at_step(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret, account_name):
    label = quote(f"{ISSUER}:{account_name}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


# --- Secret storage ---
# The TOTP secret is encrypted at rest with Fernet (AES-128-CBC + HMAC).
# The key comes from TOTP_ENCRYPTION_KEY in settings (read from the
# environment) and falls back to one derived from SECRET_KEY for local dev,
# so the database alone is never enough to read a secret.

def _fernet():
    key = getattr(settings, "TOTP_ENCRYPTION_KEY", "") or ""
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(token):
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except InvalidToken:
        return None


# --- Backup codes ---
# Shown once after enrollment, then only their hashes are kept. They are
# random (50 bits each), so a plain SHA-256 is enough - no need for a slow
# password hash, which would make checking ten of them noticeably slow.

BACKUP_CODE_COUNT = 10
_BACKUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I


def generate_backup_codes(count=BACKUP_CODE_COUNT):
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_backup_code(code):
    return (code or "").strip().upper().replace("-", "").replace(" ", "")


def hash_backup_code(code):
    return hashlib.sha256(normalize_backup_code(code).encode("ascii", "ignore")).hexdigest()

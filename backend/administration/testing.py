from . import totp
from .models import StaffAccount

# Test helper: a full staff sign-in (password + second factor) for tests
# whose subject is something other than two-factor itself. Enrolls the
# account on its first login, the same way a real person would.


def staff_login(client, username, password):
    res = client.post("/api/auth/login", {"username": username, "password": password}, content_type="application/json")
    if res.status_code != 200:
        return res

    body = res.json()
    account = StaffAccount.objects.get(username=username)
    if body["twoFactor"] == "enroll":
        secret = body["enrollment"]["secret"]
    else:
        secret = totp.decrypt_secret(account.totp_secret_encrypted)

    # A code can't be used twice, so a second login inside the same 30s step
    # needs the next step's code (still within the +/-1 step tolerance).
    step = totp.current_step()
    if account.totp_last_used_step is not None and step <= account.totp_last_used_step:
        step = account.totp_last_used_step + 1
        if step > totp.current_step() + totp.TOLERANCE_STEPS:
            StaffAccount.objects.filter(id=account.id).update(totp_last_used_step=None)
            step = totp.current_step()

    return client.post("/api/auth/2fa/verify", {"code": totp.code_at_step(secret, step)}, content_type="application/json")

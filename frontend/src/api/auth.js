// Thin wrapper around the /api/auth endpoints. Session-based: the backend
// sets a cookie on login, so these calls don't carry a token around - the
// browser sends the cookie automatically on same-origin requests.

async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  const err = new Error(body.error || `Request failed with status ${res.status}`);
  // A gym member's own login typed into the staff form (see LoginPage.jsx).
  err.memberAccount = body.memberAccount === true;
  return err;
}

// Step 1 of staff sign-in. Resolves to {twoFactor: "verify"}, or
// {twoFactor: "enroll", enrollment: {secret, otpauthUri, qrCode}} for an
// account that hasn't set up its authenticator app yet. No session yet.
export async function login(username, password) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Step 2: a 6-digit authenticator code or a backup code. Resolves to the
// signed-in account; right after enrollment it also carries backupCodes.
export async function verifyTwoFactor(code) {
  const res = await fetch("/api/auth/2fa/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
}

// Used on app load to restore a session after a page refresh. Resolves to
// null (rather than throwing) when there's no active session, since "not
// logged in yet" is an expected state here, not an error.
export async function fetchCurrentUser() {
  const res = await fetch("/api/auth/me");
  if (!res.ok) return null;
  return res.json();
}

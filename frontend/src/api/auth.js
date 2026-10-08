// Thin wrapper around the /api/auth endpoints. Session-based: the backend
// sets a cookie on login, so these calls don't carry a token around - the
// browser sends the cookie automatically on same-origin requests.

async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  return new Error(body.error || `Request failed with status ${res.status}`);
}

export async function login(username, password) {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
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

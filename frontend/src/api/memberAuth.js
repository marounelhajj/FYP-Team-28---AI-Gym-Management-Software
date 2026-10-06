// Thin wrapper around the /api/members/{signup,login,logout,me} endpoints.
// Session-based, same pattern as api/auth.js (staff) but a separate
// session key server-side - a member session and a staff session can
// never be mixed up.

async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  const err = new Error(typeof body.error === "string" ? body.error : "Something went wrong.");
  err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
  return err;
}

export async function signupMember(data) {
  const res = await fetch("/api/members/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function loginMember(username, password) {
  const res = await fetch("/api/members/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function logoutMember() {
  await fetch("/api/members/logout", { method: "POST" });
}

// Used on app load to restore a session after a page refresh. Resolves to
// null (rather than throwing) when there's no active member session.
export async function fetchCurrentMember() {
  const res = await fetch("/api/members/me");
  if (!res.ok) return null;
  return res.json();
}

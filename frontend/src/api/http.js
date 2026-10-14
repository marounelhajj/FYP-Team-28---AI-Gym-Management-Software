// Shared error handling for the staff-facing API wrappers.
//
// 401 means the staff session is gone (expired, or the account was
// deactivated while logged in), so we tell App to drop back to the login
// screen. 403 means the session is fine but the role doesn't allow the
// call (e.g. a System Administrator just removed a permission from it);
// callers show the server's message and the screen stays put.
export async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  const err = new Error(typeof body.error === "string" ? body.error : `Request failed with status ${res.status}`);
  err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
  err.status = res.status;
  if (res.status === 401) window.dispatchEvent(new Event("auth:expired"));
  return err;
}

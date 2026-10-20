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

// The logged-in member's check-in QR code (SCRUM-33):
// { membershipId, payload, qrCode (SVG data URI) }.
export async function fetchMyQrCode() {
  const res = await fetch("/api/members/me/qr");
  if (!res.ok) throw await parseError(res);
  return res.json();
}


// PATCH /api/members/me - a member editing their own name/email/phone.
//
// User story: "As a member, I want to update my saved payment method and
// personal profile information myself in the app, so that I don't need to
// visit the front desk for routine changes."
export async function updateMyProfile(data) {
  const res = await fetch("/api/members/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// GET /api/members/me/payment-method - the logged-in member's own payment
// method on file, or null if nothing's on file yet.
export async function fetchMyPaymentMethod() {
  const res = await fetch("/api/members/me/payment-method");
  if (!res.ok) throw await parseError(res);
  const body = await res.json();
  return body.paymentMethod;
}

// PUT /api/members/me/payment-method - add or replace it themselves. Same
// shape as api/members.js's updatePaymentMethod (the receptionist
// version), just scoped to the logged-in member instead of a member id.
export async function updateMyPaymentMethod(data) {
  const res = await fetch("/api/members/me/payment-method", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// GET /api/members/me/billing - the logged-in member's own recent payments
// and total count: { payments, paymentCount }. Membership details (plan,
// status, renewal date) come from fetchCurrentMember()/MemberSerializer
// instead - this is just payment history.
export async function fetchMyBilling() {
  const res = await fetch("/api/members/me/billing");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

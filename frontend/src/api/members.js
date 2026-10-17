// Thin wrapper around the /api/members endpoints.
// Swap the base URL here if the backend ever moves off the Vite proxy.

import { parseError } from "./http.js";

export async function fetchMembers({ q, status, branch, limit = 25, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (branch) params.set("branch", branch);
  params.set("limit", limit);
  params.set("offset", offset);

  const res = await fetch(`/api/members?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Public: { version, liabilityWaiver, healthDisclaimer } - the agreement
// both signup forms show (see components/WaiverSection.jsx).
export async function fetchWaiverText() {
  const res = await fetch("/api/members/waiver");
  if (!res.ok) throw new Error("Failed to load the waiver");
  return res.json();
}

export async function fetchMemberFilterOptions() {
  const res = await fetch("/api/members/meta");
  if (!res.ok) throw new Error("Failed to load filter options");
  return res.json();
}

// Registers a new walk-in member AND their first payment in one call -
// status defaults to Active, the join date defaults to today, and
// subscriptionExpiresAt is set from paymentDuration (1 Month / 1 Year) -
// all server-side. There's no amount param: the price is looked up
// server-side (billing/models.py renewal_quote), never client-supplied.
// The response includes a "firstPayment" block
// confirming what was charged and when it expires. The subscription does
// not auto-renew; see recordPayment() below for repaying after it lapses.
// Also carries the new member's signed waiver (SCRUM-83):
// liabilityWaiverAccepted, healthDisclaimerAccepted and signatureName.
export async function createMember({
  name, email, phone, branch, membershipPlan, paymentMethod, paymentDuration,
  liabilityWaiverAccepted, healthDisclaimerAccepted, signatureName,
}) {
  const res = await fetch("/api/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name, email, phone, branch, membershipPlan, paymentMethod, paymentDuration,
      liabilityWaiverAccepted, healthDisclaimerAccepted, signatureName,
    }),
  });

  const body = await res.json().catch(() => ({}));

  if (res.status === 401) window.dispatchEvent(new Event("auth:expired"));
  if (!res.ok) {
    // body.error is a dict of field -> [messages] from the serializer,
    // e.g. { name: ["This field is required."] }, so the form can show
    // errors next to the right field instead of one generic message.
    const err = new Error(typeof body.error === "string" ? body.error : "Couldn't register member");
    err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
    throw err;
  }

  return body; // the newly created member + firstPayment, same shape as a GET result plus that block
}

// { member, paymentMethod (or null), payments (10 most recent), paymentCount }
export async function fetchMemberBilling(memberId) {
  const res = await fetch(`/api/members/${memberId}/billing`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// { amount, originalAmount, promotion, startsOn, expiresAt } - exactly what
// recordPayment() would charge and the period it would cover, right now.
export async function fetchRenewalQuote(memberId, { membershipPlan, duration }) {
  const params = new URLSearchParams({ membershipPlan, duration });
  const res = await fetch(`/api/members/${memberId}/renewal-quote?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Adds or replaces the member's payment method on file. Card and bank
// details are reference-only (last 4 digits, expiry) - never a full number.
export async function updatePaymentMethod(memberId, details) {
  const res = await fetch(`/api/members/${memberId}/payment-method`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(details),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Renews an existing member (an Active subscription is extended from its
// current expiry) or reactivates a Frozen/Cancelled one (from today).
// expectedAmount is the quoted price the receptionist charged; if the price
// changed since, the server refuses with 409 instead of recording another amount.
export async function recordPayment(memberId, { membershipPlan, method, duration, expectedAmount }) {
  const res = await fetch(`/api/members/${memberId}/payments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ membershipPlan, method, duration, expectedAmount }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json(); // the updated member + "payment" block
}

// Ends a subscribed member's subscription - sets status to Cancelled.
// They can be re-subscribed later the same way as any Frozen member
// (recordPayment above), which reactivates them.
export async function cancelMembership(memberId) {
  const res = await fetch(`/api/members/${memberId}/cancel`, { method: "POST" });
  if (!res.ok) throw await parseError(res);
  return res.json(); // the updated member
}

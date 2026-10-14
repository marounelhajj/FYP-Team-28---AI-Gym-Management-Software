// Thin wrapper around the /api/checkins endpoints.

import { parseError } from "./http.js";

// `code` is what was typed or scanned: a membership ID (digits), or the
// payload of a member's check-in QR code (backend/members/qr.py), which a
// camera scan or a USB scanner typing into the field both produce.
function codeBody(code) {
  const text = String(code).trim();
  return /^\d+$/.test(text) ? { membershipId: Number(text) } : { qrCode: text };
}

// Checks a member in by membership ID or QR code. Returns { member,
// checkIn } - member.status is the just-verified, live value (a lapsed
// subscription is caught here, not left stale).
export async function checkIn(code) {
  const res = await fetch("/api/checkins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(codeBody(code)),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchRecentCheckIns(limit = 20) {
  const res = await fetch(`/api/checkins?limit=${limit}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Checks a member out of their open session by membership ID or QR code. Fails
// (400) if they never checked in, or if they're not currently Active -
// same rule as checking in, applied on the way out too. Returns
// { member, checkIn } - checkIn.duration is how long they were in
// ("Xh Ym"), only ever present on a checked-out row.
export async function checkOut(code) {
  const res = await fetch("/api/checkins/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(codeBody(code)),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

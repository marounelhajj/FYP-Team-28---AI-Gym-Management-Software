// Thin wrapper around the /api/checkins endpoints.

async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  const err = new Error(typeof body.error === "string" ? body.error : "Couldn't check in that member");
  err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
  return err;
}

// Checks a member in by membership ID (their Member.id - typed, or in
// the future decoded from a scanned QR code before being sent here).
// Returns { member, checkIn } - member.status is the just-verified,
// live value (a lapsed subscription is caught here, not left stale).
export async function checkIn(membershipId) {
  const res = await fetch("/api/checkins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ membershipId }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchRecentCheckIns(limit = 20) {
  const res = await fetch(`/api/checkins?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load recent check-ins");
  return res.json();
}

// Checks a member out of their open session by membership ID. Fails
// (400) if they never checked in, or if they're not currently Active -
// same rule as checking in, applied on the way out too. Returns
// { member, checkIn } - checkIn.duration is how long they were in
// ("Xh Ym"), only ever present on a checked-out row.
export async function checkOut(membershipId) {
  const res = await fetch("/api/checkins/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ membershipId }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

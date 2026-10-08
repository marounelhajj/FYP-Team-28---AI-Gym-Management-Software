// Thin wrapper around the /api/members endpoints.
// Swap the base URL here if the backend ever moves off the Vite proxy.

export async function fetchMembers({ q, status, branch, limit = 25, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (branch) params.set("branch", branch);
  params.set("limit", limit);
  params.set("offset", offset);

  const res = await fetch(`/api/members?${params.toString()}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed with status ${res.status}`);
  }
  return res.json();
}

export async function fetchMemberFilterOptions() {
  const res = await fetch("/api/members/meta");
  if (!res.ok) throw new Error("Failed to load filter options");
  return res.json();
}

// Registers a new walk-in member and records their signed digital waiver +
// health disclaimer, in one call. Status defaults to Active and the join
// date defaults to today - both are set server-side, not passed here.
export async function createMember({
  name,
  email,
  phone,
  branch,
  membershipPlan,
  signatureName,
  healthDisclaimerAccepted,
  liabilityWaiverAccepted,
}) {
  const res = await fetch("/api/members", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      email,
      phone,
      branch,
      membershipPlan,
      signatureName,
      healthDisclaimerAccepted,
      liabilityWaiverAccepted,
    }),
  });

  const body = await res.json().catch(() => ({}));

  if (!res.ok) {
    // body.error is a dict of field -> [messages] from the serializer,
    // e.g. { name: ["This field is required."] }, so the form can show
    // errors next to the right field instead of one generic message.
    const err = new Error(typeof body.error === "string" ? body.error : "Couldn't register member");
    err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
    throw err;
  }

  return body; // the newly created member, same shape as a GET result (includes "waiver")
}

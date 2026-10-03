// Thin wrapper around the /api/staff, /api/roles and /api/permissions
// endpoints used by the System Administrator console.

async function parseError(res) {
  const body = await res.json().catch(() => ({}));
  const err = new Error(typeof body.error === "string" ? body.error : `Request failed with status ${res.status}`);
  err.fieldErrors = body.error && typeof body.error === "object" ? body.error : null;
  return err;
}

// --- Staff accounts ---
// User story: "As a system administrator, I want to create, edit and
// deactivate staff login accounts, so that only current staff can sign in
// to the system."

export async function fetchStaff({ q, roleId, isActive } = {}) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (roleId) params.set("roleId", roleId);
  if (isActive !== undefined && isActive !== "") params.set("isActive", isActive);

  const res = await fetch(`/api/staff?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function createStaffAccount(data) {
  const res = await fetch("/api/staff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Also used to deactivate/reactivate an account via { isActive: false/true }.
export async function updateStaffAccount(id, data) {
  const res = await fetch(`/api/staff/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- Roles & permissions ---
// User story: "As a system administrator, I want to define roles with
// specific permission sets, so that access matches each job function."

export async function fetchRoles() {
  const res = await fetch("/api/roles");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function createRole(data) {
  const res = await fetch("/api/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function updateRole(id, data) {
  const res = await fetch(`/api/roles/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchPermissions() {
  const res = await fetch("/api/permissions");
  if (!res.ok) throw new Error("Failed to load permissions");
  return res.json();
}

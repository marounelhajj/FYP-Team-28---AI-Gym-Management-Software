// Door readers (/api/doors).

import { parseError } from "./http.js";

// --- Used by the door screen itself, which signs in with its door key ---
// (not a staff session, so a 401 here must not log anyone out).

async function doorRequest(path, key, options = {}) {
  const res = await fetch(`/api/doors${path}`, {
    ...options,
    headers: { ...options.headers, "X-Door-Key": key },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.error || `Request failed with status ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

// { name, branch, kind } for the door this key belongs to.
export function fetchDoorSelf(key) {
  return doorRequest("/self", key);
}

// { granted, door, message, member } - whether to open for this QR code.
export function scanAtDoor(key, qrCode) {
  return doorRequest("/scan", key, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qrCode }),
  });
}

// --- Managing door readers (System Administrator, manage_doors) ---

export async function fetchDoors() {
  const res = await fetch("/api/doors");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Returns { door, key }. The key is only ever shown at this point.
export async function createDoor({ name, branch, kind }) {
  const res = await fetch("/api/doors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, branch, kind }),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function updateDoor(doorId, changes) {
  const res = await fetch(`/api/doors/${doorId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Returns { door, key }; the door's old key stops working immediately.
export async function rotateDoorKey(doorId) {
  const res = await fetch(`/api/doors/${doorId}/rotate-key`, { method: "POST" });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

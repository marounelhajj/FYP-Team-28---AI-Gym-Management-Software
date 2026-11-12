// Health notes: the member's own injuries and restrictions, and the coach's
// read-only briefing before a class or private session.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
}

// The member's side - every call returns the member's whole, updated list.
export const fetchMyHealth = () => request("/api/members/me/health");
export const addHealthNote = (data) => send("POST", "/api/members/me/health", data);
export const updateHealthNote = (id, data) => send("PATCH", `/api/members/me/health/${id}`, data);
export const deleteHealthNote = (id) => request(`/api/members/me/health/${id}`, { method: "DELETE" });
export const confirmMyHealth = () => send("POST", "/api/members/me/health/confirm");

// The coach's side.
export const fetchClassHealthBriefing = (classId) => request(`/api/health-notes/classes/${classId}`);
export const fetchPtHealthBriefing = (sessionId) => request(`/api/health-notes/pt-sessions/${sessionId}`);
export const fetchClientHealth = (memberId) => request(`/api/health-notes/members/${memberId}`);

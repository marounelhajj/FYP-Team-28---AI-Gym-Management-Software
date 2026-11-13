// Coach session logs, client progress and goals; and the member's own progress.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const fetchSessionLog = (sessionId) => request(`/api/coaching/pt-sessions/${sessionId}/log`);
export const saveSessionLog = (sessionId, data) => send("PUT", `/api/coaching/pt-sessions/${sessionId}/log`, data);
export const deleteSessionLog = (sessionId) => request(`/api/coaching/pt-sessions/${sessionId}/log`, { method: "DELETE" });

export const fetchClientProgress = (memberId) => request(`/api/coaching/clients/${memberId}/progress`);
export const addClientGoal = (memberId, data) => send("POST", `/api/coaching/clients/${memberId}/goals`, data);
export const updateClientGoal = (goalId, data) => send("PATCH", `/api/coaching/goals/${goalId}`, data);

export const fetchMyProgress = () => request("/api/members/me/progress");

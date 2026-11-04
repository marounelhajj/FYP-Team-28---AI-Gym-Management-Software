// SCRUM-60: the member's own training log (workouts and body metrics) and the
// coach's read-only view of their clients' logs.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.status === 204 ? null : res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const fetchMyWorkouts = () => request("/api/members/me/workouts");
export const addWorkout = (data) => send("POST", "/api/members/me/workouts", data);
export const updateWorkout = (id, data) => send("PATCH", `/api/members/me/workouts/${id}`, data);
export const deleteWorkout = (id) => request(`/api/members/me/workouts/${id}`, { method: "DELETE" });

export const fetchMyMetrics = () => request("/api/members/me/metrics");
export const addMetric = (data) => send("POST", "/api/members/me/metrics", data);
export const updateMetric = (id, data) => send("PATCH", `/api/members/me/metrics/${id}`, data);
export const deleteMetric = (id) => request(`/api/members/me/metrics/${id}`, { method: "DELETE" });

export const fetchMyClients = () => request("/api/progress/clients");
export const fetchClientLog = (memberId) => request(`/api/progress/clients/${memberId}`);

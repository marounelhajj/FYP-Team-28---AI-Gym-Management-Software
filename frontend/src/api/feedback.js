// SCRUM-40: a member rating the coach of a class or private session they
// attended, and changing that rating while the window is open.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.status === 204 ? null : res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const fetchMyFeedback = () => request("/api/members/me/feedback");
export const rateSession = (data) => send("POST", "/api/members/me/feedback", data);
export const updateFeedback = (id, data) => send("PATCH", `/api/members/me/feedback/${id}`, data);

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

// SCRUM-37: the signed-in coach's ratings. filters: { rating?, withComments? }.
export function fetchMyRatings({ rating, withComments } = {}) {
  const params = new URLSearchParams();
  if (rating) params.set("rating", rating);
  if (withComments) params.set("withComments", "1");
  const query = params.toString();
  return request(`/api/feedback/me${query ? `?${query}` : ""}`);
}

// General manager's view: ratings by branch. { branch?: one branch name,
// else every branch }. Each branch: { branch, count, average, stars,
// coaches: [{ id, name, count, average }] ranked best first. Plus "totals"
// across whatever branches are in view.
//
// User story: "As a general manager, I want to view personal trainer
// ratings by branch, so that I can inform staffing, coaching, and
// incentive decisions."
export function fetchRatingsByBranch(branch) {
  const query = branch ? `?branch=${encodeURIComponent(branch)}` : "";
  return request(`/api/feedback/report${query}`);
}

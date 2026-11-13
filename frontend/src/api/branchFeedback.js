// Branch feedback: members' surveys and complaints, and the branch manager's
// view of them.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

function query(url, params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return qs ? `${url}?${qs}` : url;
}

// The member's side - each call returns the member's whole, updated picture.
export const fetchMyBranchFeedback = () => request("/api/members/me/branch-feedback");
export const submitSurvey = (data) => send("POST", "/api/members/me/branch-feedback/surveys", data);
export const submitComplaint = (data) => send("POST", "/api/members/me/complaints", data);
export const replyToMyComplaint = (id, body) => send("POST", `/api/members/me/complaints/${id}/messages`, { body });

// The manager's side.
export const fetchFeedbackSummary = (params) => request(query("/api/branch-feedback/summary", params));
export const fetchComplaints = (params) => request(query("/api/branch-feedback/complaints", params));
export const fetchComplaint = (id) => request(`/api/branch-feedback/complaints/${id}`);
export const replyToComplaint = (id, body, internal) =>
  send("POST", `/api/branch-feedback/complaints/${id}/messages`, { body, internal });
export const setComplaintStatus = (id, status, message) =>
  send("PATCH", `/api/branch-feedback/complaints/${id}`, { status, message });

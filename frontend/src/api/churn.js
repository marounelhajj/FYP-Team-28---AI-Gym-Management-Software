// Thin wrapper around /api/churn - the At-Risk Members list (SCRUM-118).

import { parseError } from "./http.js";

async function request(path, options = {}) {
  const res = await fetch(`/api/churn${path}`, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function send(method, path, body) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

// branch is optional: a Branch Manager always gets their own branch.
// Returns { branch, branches, canChooseBranch, canRefresh, run, members }.
export function fetchAtRisk(branch) {
  return request(`/at-risk${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`);
}

// "Refresh now": re-scores the branch. Same shape as fetchAtRisk.
export function refreshAtRisk(branch) {
  return send("POST", "/refresh", { branch });
}

// SCRUM-68: log a retention call. outcome: reached | no_answer | saved |
// cancelled_anyway. note and followUpOn (YYYY-MM-DD) are optional.
export function logRetentionCall({ memberId, outcome, note, followUpOn }) {
  return send("POST", "/calls", { memberId, outcome, note, followUpOn: followUpOn || null });
}

// SCRUM-68: a member's retention calls, newest first. Returns { memberId, calls }.
export function fetchMemberCalls(memberId) {
  return request(`/members/${memberId}/calls`);
}

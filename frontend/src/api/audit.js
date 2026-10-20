// Thin wrapper around /api/audit-log (SCRUM-124/125).

import { parseError } from "./http.js";

function filterParams({ user, action, branch, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (user) params.set("user", user);
  if (action) params.set("action", action);
  if (branch) params.set("branch", branch);
  if (dateFrom) params.set("dateFrom", dateFrom);
  if (dateTo) params.set("dateTo", dateTo);
  return params;
}

// User story: "As a general manager, I want to search and filter the audit
// log by user, action type, branch and date range, so that I can
// investigate a specific incident."
export async function fetchAuditLog(filters = {}, { limit = 50, offset = 0 } = {}) {
  const params = filterParams(filters);
  params.set("limit", limit);
  params.set("offset", offset);
  const res = await fetch(`/api/audit-log?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchAuditLogMeta() {
  const res = await fetch("/api/audit-log/meta");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

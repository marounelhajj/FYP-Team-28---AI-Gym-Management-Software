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

// User story (SCRUM-126): "As a general manager, I want to export a
// filtered audit log, so that I can share evidence in a dispute or review."
// Downloads every entry matching `filters` (not just the page on screen)
// as a CSV file. Fetched rather than linked to, so an error (e.g. the role
// lost view_audit_log) shows on screen instead of replacing the page.
export async function downloadAuditLogCsv(filters = {}) {
  const res = await fetch(`/api/audit-log/export?${filterParams(filters).toString()}`);
  if (!res.ok) throw await parseError(res);

  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : "audit-log.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return Number(res.headers.get("X-Export-Rows") || 0);
}

export async function fetchAuditLogMeta() {
  const res = await fetch("/api/audit-log/meta");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

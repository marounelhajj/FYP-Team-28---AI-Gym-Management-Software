// Thin wrapper around /api/finance/{report,expenses,meta}.
//
// User story: "As a general manager, I want to view expense and revenue
// data for each branch, so that I can monitor financial performance and
// compare branches."

import { parseError } from "./http.js";

function filterParams({ branch, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (branch) params.set("branch", branch);
  if (dateFrom) params.set("dateFrom", dateFrom);
  if (dateTo) params.set("dateTo", dateTo);
  return params;
}

export async function fetchFinancialReport(filters = {}) {
  const res = await fetch(`/api/finance/report?${filterParams(filters).toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchFinanceMeta() {
  const res = await fetch("/api/finance/meta");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchExpenses(filters = {}, { limit = 25, offset = 0 } = {}) {
  const params = filterParams(filters);
  params.set("limit", limit);
  params.set("offset", offset);
  const res = await fetch(`/api/finance/expenses?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function recordExpense(data) {
  const res = await fetch("/api/finance/expenses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

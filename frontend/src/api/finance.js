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

// SCRUM-26: one branch's revenue, expenses and net for a period.
// filters: { branch?, period: "this_month" | "last_month" | "custom", dateFrom?, dateTo? }
export async function fetchBranchFinances(filters = {}) {
  const params = filterParams(filters);
  if (filters.period) params.set("period", filters.period);
  const res = await fetch(`/api/finance/branch?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function updateExpense(id, data) {
  const res = await fetch(`/api/finance/expenses/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function deleteExpense(id) {
  const res = await fetch(`/api/finance/expenses/${id}`, { method: "DELETE" });
  if (!res.ok) throw await parseError(res);
}

// SCRUM-105: every branch's revenue over a period, ranked, with the
// reasons a branch is flagged as underperforming.
// params: { period, dateFrom?, dateTo? } - period is this_month, last_month,
// this_quarter, last_quarter, this_year or custom.
export async function fetchBranchComparison({ period, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  if (period === "custom") {
    if (dateFrom) params.set("dateFrom", dateFrom);
    if (dateTo) params.set("dateTo", dateTo);
  }
  const res = await fetch(`/api/finance/compare?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

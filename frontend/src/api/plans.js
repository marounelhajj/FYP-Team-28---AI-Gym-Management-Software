// Thin wrapper around the /api/plans endpoints.
//
// User story: "As a general manager, I want to set organization-wide
// membership plans and pricing tiers, so that pricing stays consistent
// across branches while still allowing local promotions."

import { parseError } from "./http.js";

export async function fetchPlans({ isActive } = {}) {
  const params = new URLSearchParams();
  if (isActive !== undefined && isActive !== "") params.set("isActive", isActive);

  const res = await fetch(`/api/plans?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function fetchPlanMeta() {
  const res = await fetch("/api/plans/meta");
  if (!res.ok) throw new Error("Failed to load plan options");
  return res.json();
}

export async function createPlan(data) {
  const res = await fetch("/api/plans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Also used to archive/restore a plan via { isActive: false/true }.
export async function updatePlan(id, data) {
  const res = await fetch(`/api/plans/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- Branch promotions ---
// Local, time-boxed discounts on an organization-wide plan. The backend
// rejects any discount above the plan's maxPromoDiscountPercent.

export async function fetchPromotions({ branch, planId } = {}) {
  const params = new URLSearchParams();
  if (branch) params.set("branch", branch);
  if (planId) params.set("planId", planId);

  const res = await fetch(`/api/plans/promotions?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function createPromotion(data) {
  const res = await fetch("/api/plans/promotions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Also used to cancel a promotion via { isActive: false }.
export async function updatePromotion(id, data) {
  const res = await fetch(`/api/plans/promotions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// What each active plan costs at one branch today (base price minus the
// best running promotion there, if any).
export async function fetchBranchPricing(branch) {
  const res = await fetch(`/api/plans/pricing?branch=${encodeURIComponent(branch)}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

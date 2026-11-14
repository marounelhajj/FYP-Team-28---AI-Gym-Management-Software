// Thin wrapper around the /api/marketing endpoints.
//
// User story: "As a general manager, I want to view the marketing
// campaigns and strategies being run at each branch, so that I can assess
// alignment with overall brand direction and spending."

import { parseError } from "./http.js";

export async function fetchMarketingMeta() {
  const res = await fetch("/api/marketing/meta");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- Marketing Staff's own screen: run campaigns ---

export async function fetchCampaigns({ branch, isActive } = {}) {
  const params = new URLSearchParams();
  if (branch) params.set("branch", branch);
  if (isActive !== undefined && isActive !== "") params.set("isActive", isActive);

  const res = await fetch(`/api/marketing/campaigns?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function createCampaign(data) {
  const res = await fetch("/api/marketing/campaigns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// Also used to cancel a campaign via { isActive: false }.
export async function updateCampaign(id, data) {
  const res = await fetch(`/api/marketing/campaigns/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

// --- General Manager's screen: compare branches ---

export async function fetchCampaignReport(branch) {
  const params = new URLSearchParams();
  if (branch) params.set("branch", branch);

  const res = await fetch(`/api/marketing/report?${params.toString()}`);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

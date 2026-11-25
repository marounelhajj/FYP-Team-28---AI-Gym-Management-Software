// Thin wrapper around /api/segments (SCRUM-43, SCRUM-112, SCRUM-113, SCRUM-114).

import { parseError } from "./http.js";

async function request(path, options = {}) {
  const res = await fetch(`/api/segments${path}`, options);
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

// GET /api/segments/meta - what the filter builder can offer, and what the caller may do.
export function fetchSegmentsMeta() {
  return request("/meta");
}

// GET /api/segments - every segment the caller can see, with live counts.
export function fetchSegments() {
  return request("");
}

// POST /api/segments {name, description, filters} - create one.
export function createSegment({ name, description, filters }) {
  return send("POST", "", { name, description, filters });
}

// PUT /api/segments/<id> {name, description, filters} - update an existing segment.
export function updateSegment(id, { name, description, filters }) {
  return send("PUT", `/${id}`, { name, description, filters });
}

// DELETE /api/segments/<id> - delete a segment.
export function deleteSegment(id) {
  return send("DELETE", `/${id}`);
}

// POST /api/segments/preview {filters} - live count while filters change.
export function previewSegmentFilters(filters) {
  return send("POST", "/preview", { filters });
}

// GET /api/segments/clusters - latest suggested segments.
export function fetchClusters() {
  return request("/clusters");
}

// POST /api/segments/clusters/run - recalculate clusters now.
export function runClusters() {
  return send("POST", "/clusters/run", {});
}

// POST /api/segments/clusters/<groupId>/save {name?} - keep a suggested segment.
export function saveClusterGroup(groupId, name) {
  return send("POST", `/clusters/${groupId}/save`, name ? { name } : {});
}

// GET /api/segments/trends?segments=1,2&branch=&period=week|month
export function fetchTrends({ segments, branch, period } = {}) {
  const q = new URLSearchParams();
  if (segments !== undefined && segments !== null && segments !== "") {
    q.set("segments", Array.isArray(segments) ? segments.join(",") : segments);
  }
  if (branch) q.set("branch", branch);
  if (period) q.set("period", period);
  const qs = q.toString();
  return request(`/trends${qs ? `?${qs}` : ""}`);
}

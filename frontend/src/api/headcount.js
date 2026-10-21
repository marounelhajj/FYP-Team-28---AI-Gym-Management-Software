// Thin wrapper around the /api/headcount endpoints.

import { parseError } from "./http.js";

// A request that hangs (backend stuck, network half-down) counts as a drop
// after this long, so the dashboard can show "Reconnecting" instead of
// waiting forever.
const TIMEOUT_MS = 8000;

// branch is optional: a Branch Manager always gets their own branch, a
// General Manager gets the one asked for (or a default). Returns
// { branch, count, asOf, branches, canChooseBranch, autoCheckoutHours,
// refreshSeconds }.
export async function fetchLiveHeadcount(branch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const query = branch ? `?branch=${encodeURIComponent(branch)}` : "";
    const res = await fetch(`/api/headcount/live${query}`, { signal: controller.signal });
    if (!res.ok) throw await parseError(res);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Today's headcount hour by hour plus the same-weekday average. Counts only.
// Returns { branch, date, weekday, currentHour, weeksCompared, asOf,
// hours: [{ hour, today, weekdayAverage }] }.
export async function fetchHourlyHeadcount(branch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const query = branch ? `?branch=${encodeURIComponent(branch)}` : "";
    const res = await fetch(`/api/headcount/hourly${query}`, { signal: controller.signal });
    if (!res.ok) throw await parseError(res);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

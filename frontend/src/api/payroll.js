// Coach pay: the coach's own statement per pay period, and the branch
// manager's rates and view of their coaches' statements.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res);
  return res.status === 204 ? null : res.json();
}

const withPeriod = (url, period) => (period ? `${url}?period=${encodeURIComponent(period)}` : url);

export const fetchMyPay = (period) => request(withPeriod("/api/payroll/me", period));

export const fetchCoachPayList = (period) => request(withPeriod("/api/payroll/coaches", period));
export const fetchCoachStatement = (coachId, period) => request(withPeriod(`/api/payroll/coaches/${coachId}`, period));
export const setCoachRate = (coachId, data) =>
  request(`/api/payroll/coaches/${coachId}/rates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
export const removeCoachRate = (coachId, rateId) =>
  request(`/api/payroll/coaches/${coachId}/rates/${rateId}`, { method: "DELETE" });

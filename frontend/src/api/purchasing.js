// Supply orders: a branch's purchase orders to suppliers, head office's
// approvals, and the supplier list / product sourcing behind them.

import { parseError } from "./http.js";

async function request(url, options = {}) {
  const res = await fetch(`/api/purchasing${url}`, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function send(method, url, body) {
  return request(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
}

function query(params) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return qs ? `?${qs}` : "";
}

export const fetchPurchasingMeta = (branch) => request(`/meta${query({ branch })}`);
export const fetchOrders = (branch, status) => request(`/orders${query({ branch, status })}`);
export const fetchApprovals = () => request("/approvals");
export const fetchOrder = (id) => request(`/orders/${id}`);
export const placeOrder = (data) => send("POST", "/orders", data);
export const approveOrder = (id) => send("POST", `/orders/${id}/approve`);
export const rejectOrder = (id, reason) => send("POST", `/orders/${id}/reject`, { reason });
export const cancelOrder = (id, reason) => send("POST", `/orders/${id}/cancel`, { reason });
export const receiveOrder = (id, items, note) => send("POST", `/orders/${id}/receive`, { items, note });
export const closeOrder = (id, reason) => send("POST", `/orders/${id}/close`, { reason });
export const resendOrder = (id) => send("POST", `/orders/${id}/resend`);

export const fetchSuppliers = () => request("/suppliers");
export const addSupplier = (data) => send("POST", "/suppliers", data);
export const updateSupplier = (id, data) => send("PATCH", `/suppliers/${id}`, data);
export const updateSourcing = (productId, data) => send("PATCH", `/products/${productId}/sourcing`, data);

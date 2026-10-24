// Thin wrapper around /api/retail (point of sale + the shop catalog).
//
// User story: "As a receptionist, I want to process point-of-sale purchases
// for retail items (protein, water bottles, merchandise), so that I can
// handle in-person retail sales."

import { parseError } from "./http.js";

async function request(path, options = {}) {
  const res = await fetch(`/api/retail${path}`, options);
  if (!res.ok) {
    const err = await parseError(res);
    // A 409 on a sale carries the up-to-date total alongside the message.
    if (res.status === 409) err.conflict = true;
    throw err;
  }
  return res.json();
}

function send(method, path, body) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// { branches, categories, fixedBranch, canSell, canManage, manageableBranches }
export function fetchRetailMeta() {
  return request("/meta");
}

// { results: [{ id, name, category, price, isActive, stock: { branch: qty } }] }
export function fetchProducts({ includeArchived = false } = {}) {
  return request(`/products${includeArchived ? "?includeArchived=true" : ""}`);
}

export function createProduct(data) {
  return send("POST", "/products", data);
}

export function updateProduct(productId, changes) {
  return send("PATCH", `/products/${productId}`, changes);
}

// change > 0 receives a delivery, change < 0 corrects the count.
export function adjustStock(productId, { branch, change, note }) {
  return send("POST", `/products/${productId}/stock`, { branch, change, note });
}

// { id, name, branch, status } from a membership ID or a scanned card QR.
export function lookupMember(code) {
  return request(`/member?code=${encodeURIComponent(code)}`);
}

// Body: { branch?, items: [{ productId, quantity }], paymentMethod, amountTendered?, memberId?, expectedTotal }
export function createSale(data) {
  return send("POST", "/sales", data);
}

// { date, branch, results: [sale...], summary: { sales, total, cash, card, voided } }
export function fetchSales({ date, branch } = {}) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (branch) params.set("branch", branch);
  return request(`/sales?${params.toString()}`);
}

export function voidSale(saleId, reason) {
  return send("POST", `/sales/${saleId}/void`, { reason });
}

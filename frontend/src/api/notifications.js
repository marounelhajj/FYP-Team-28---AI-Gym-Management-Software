// The signed-in staff member's own in-app notifications (SCRUM-128 capacity
// alerts, for now).

import { parseError } from "./http.js";

export async function fetchNotifications() {
  const res = await fetch("/api/notifications");
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function markNotificationRead(id) {
  const res = await fetch(`/api/notifications/${id}/read`, { method: "POST" });
  if (!res.ok) throw await parseError(res);
}

export async function markAllNotificationsRead() {
  const res = await fetch("/api/notifications/read-all", { method: "POST" });
  if (!res.ok) throw await parseError(res);
}

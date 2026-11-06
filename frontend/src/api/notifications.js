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

// The signed-in member's own notifications (waitlist spots, cancelled
// classes), same shape as the staff ones - so the same bell shows them.
async function memberFetch(path, options) {
  const res = await fetch(`/api/members/me/notifications${path}`, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export const memberNotificationsApi = {
  fetch: () => memberFetch(""),
  markRead: (id) => memberFetch(`/${id}/read`, { method: "POST" }),
  markAllRead: () => memberFetch("/read-all", { method: "POST" }),
};

export const staffNotificationsApi = {
  fetch: fetchNotifications,
  markRead: markNotificationRead,
  markAllRead: markAllNotificationsRead,
};

// Thin wrapper around /api/classes (the branch's class calendar) and the
// member's own booking endpoints under /api/members/me/classes.
//
// User story: "As a branch manager, I want to create and edit class schedules
// and assign coaches to time slots, so that I can build the weekly class
// calendar for my branch."

import { parseError } from "./http.js";

async function staffRequest(path, options = {}) {
  const res = await fetch(`/api/classes${path}`, options);
  if (!res.ok) throw await parseError(res);
  return res.json();
}

function staffSend(method, path, body) {
  return staffRequest(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function query({ week, branch } = {}) {
  const params = new URLSearchParams();
  if (week) params.set("week", week);
  if (branch) params.set("branch", branch);
  const text = params.toString();
  return text ? `?${text}` : "";
}

// { branch, branches, weekStart, weekEnd, today, now, days: [{ date, isPast, isToday }], canEdit, classes }
export function fetchSchedule(filters) {
  return staffRequest(query(filters));
}

// The class plus { roster, seriesFollowing, canEdit, canBookMembers }.
export function fetchClass(classId) {
  return staffRequest(`/${classId}`);
}

// --- The front desk: one day's classes, and booking members into them ---

// { branch, branches, date, isPast, isToday, today, nowIso, timeZone, utcOffset, canEdit, canBookMembers,
//   classes, summary: { classes, openClasses, openSpots, fullClasses }, nextOpen }
export function fetchClassDay({ date, branch } = {}) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (branch) params.set("branch", branch);
  return staffRequest(`/day?${params.toString()}`);
}

// q is a name, a membership ID, a phone number or a scanned card.
// { results: [{ id, name, phone, branch, status, visiting, flagged, waiverOnFile, canBook, reason }] }
export function searchMembersForClass(classId, q) {
  return staffRequest(`/${classId}/member-search?${new URLSearchParams({ q }).toString()}`);
}

// Resolves to { class, booking }.
export function bookMemberAtDesk(classId, memberId) {
  return staffSend("POST", `/${classId}/bookings`, { memberId });
}

export function removeDeskBooking(classId, bookingId) {
  return staffRequest(`/${classId}/bookings/${bookingId}/cancel`, { method: "POST" });
}

export function fetchCoaches(branch) {
  return staffRequest(`/coaches${query({ branch })}`);
}

// The signed-in coach's own week: { coachId, coachName, weekStart, weekEnd, today, now, days,
// classes, ptSessions } - same shapes as fetchSchedule's classes and fetchPtHours's sessions,
// just filtered down to this coach. Works for any signed-in staff account; a non-coach just
// gets an empty week back (nobody but a coach is ever assigned to a class or PT hours).
export function fetchMySchedule(week) {
  return staffRequest(`/me/schedule${query({ week })}`);
}

// --- The coach's own PT hours (self-service) ---

// { coachId, coachName, branches, sessionLengths, hours, sessions }
export function fetchMyPtHours() {
  return staffRequest("/me/pt-hours");
}

// Body: { branch? (only needed if not tied to one branch), weekday (0 = Monday),
// startTime, endTime, sessionMinutes }
export function addMyPtHours(data) {
  return staffSend("POST", "/me/pt-hours", data);
}

// Resolves to { removed, bookedSessionsKept }.
export function removeMyPtHours(hoursId) {
  return staffRequest(`/me/pt-hours/${hoursId}`, { method: "DELETE" });
}

// --- The coach's own time off (self-service) ---
// User story: "As a coach, I want to block off time on my calendar when
// I'm unavailable, so that members can't book me during that time."

// { coachId, coachName, blocks: [{ id, coachId, startsAt, endsAt, reason, state }] }
export function fetchMyTimeOff() {
  return staffRequest("/me/time-off");
}

// Body: { startsAt, endsAt ("YYYY-MM-DDTHH:MM", local Beirut time), reason? }.
// A clash with a class/PT session or existing block comes back as a 409
// with err.fieldErrors.conflicts.
export function addMyTimeOff(data) {
  return staffSend("POST", "/me/time-off", data);
}

// Resolves to { removed }.
export function removeMyTimeOff(timeOffId) {
  return staffRequest(`/me/time-off/${timeOffId}`, { method: "DELETE" });
}

// Who's already taken in a slot: { coaches: { coachId: "Boxing 18:00–19:00 at Jnah" },
// studios: [{ name, takenBy }] } - so the form can grey them out before saving.
export function fetchAvailability({ branch, date, startTime, durationMinutes, repeatWeeks, excludeId }) {
  const params = new URLSearchParams({ date, startTime, durationMinutes: String(durationMinutes) });
  if (branch) params.set("branch", branch);
  if (repeatWeeks > 1) params.set("repeatWeeks", String(repeatWeeks));
  if (excludeId) params.set("excludeId", String(excludeId));
  return staffRequest(`/availability?${params.toString()}`);
}

// Body: { branch?, name, description?, coachId, room?, date, startTime, durationMinutes, capacity, repeatWeeks? }
// Resolves to { classes: [...] }. A clash comes back as a 409 with err.fieldErrors.conflicts.
export function createClass(data) {
  return staffSend("POST", "", data);
}

// changes + scope: "one" | "following".
export function updateClass(classId, changes) {
  return staffSend("PATCH", `/${classId}`, changes);
}

export function cancelClass(classId, { reason, scope }) {
  return staffSend("POST", `/${classId}/cancel`, { reason, scope });
}

// --- Class types and their maximum capacity ---

// { branch, canEdit, results: [{ id, name, maxCapacity, defaultDurationMinutes, description, isActive,
//   upcomingClasses, mostBookedUpcoming }] }
export function fetchClassTypes(branch, { includeArchived = false } = {}) {
  const params = new URLSearchParams();
  if (branch) params.set("branch", branch);
  if (includeArchived) params.set("includeArchived", "true");
  return staffRequest(`/types?${params.toString()}`);
}

// Body: { branch?, name, maxCapacity, defaultDurationMinutes?, description? }
export function createClassType(data) {
  return staffSend("POST", "/types", data);
}

// Resolves to the type plus { adjustedClasses }: how many upcoming classes
// had their spots changed to fit a new maximum. A maximum below an upcoming
// class's bookings comes back as a 409 with err.fieldErrors.conflicts.
export function updateClassType(typeId, changes) {
  return staffSend("PATCH", `/types/${typeId}`, changes);
}

// --- Private training hours and sessions (staff) ---

// { branch, canEdit, sessionLengths, coaches: [{ id, name, branch, hours: [...] }], sessions: [...] }
export function fetchPtHours(branch) {
  return staffRequest(`/pt-hours${query({ branch })}`);
}

// Body: { branch?, coachId, weekday (0 = Monday), startTime, endTime, sessionMinutes }
export function addPtHours(data) {
  return staffSend("POST", "/pt-hours", data);
}

// Resolves to { removed, bookedSessionsKept }.
export function removePtHours(hoursId) {
  return staffRequest(`/pt-hours/${hoursId}`, { method: "DELETE" });
}

export function cancelPtSessionAsStaff(sessionId, reason) {
  return staffSend("POST", `/pt-sessions/${sessionId}/cancel`, { reason });
}

// --- The member's own bookings (member session, not staff) ---

async function memberRequest(path, options = {}) {
  const res = await fetch(`/api/members/me${path}`, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(typeof body.error === "string" ? body.error : "Something went wrong.");
    err.status = res.status;
    throw err;
  }
  return body;
}

function memberSend(path, body) {
  return memberRequest(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

// { branch, weekStart, weekEnd, today, now, days, classes (each with myBooking),
//   upcoming, upcomingPt, canBook, bookingBlockedReason, bookableUntil }
export function fetchMyClasses(week) {
  return memberRequest(`/classes${query({ week })}`);
}

export function bookClass(classId) {
  return memberSend(`/classes/${classId}/book`);
}

export function cancelMyBooking(classId) {
  return memberSend(`/classes/${classId}/cancel`);
}

// { branch, coaches: [{ id, name, teaches, ptHours, nextOpen }] }
export function fetchMyCoaches() {
  return memberRequest("/coaches");
}

// One coach's private sessions that week: { coach, hours, days, slots: [{ date, startTime, endTime,
// startsAt, state, sessionId }], canBook, bookingBlockedReason, bookableUntil, upcomingSessions, ... }
export function fetchPtSlots(coachId, week) {
  const params = new URLSearchParams({ coachId: String(coachId) });
  if (week) params.set("week", week);
  return memberRequest(`/pt-slots?${params.toString()}`);
}

export function bookPtSession({ coachId, startsAt, note }) {
  return memberSend("/pt-sessions", { coachId, startsAt, note });
}

export function cancelMyPtSession(sessionId) {
  return memberSend(`/pt-sessions/${sessionId}/cancel`);
}

// SCRUM-36: a class's attendance sheet. The coach marks their own classes;
// a branch manager any class at their branch.
export function fetchAttendance(classId) {
  return staffRequest(`/${classId}/attendance`);
}

export function markAttendance(classId, bookingId, attendance) {
  return staffSend("POST", `/${classId}/attendance`, { bookingId, attendance });
}

export function addWalkIn(classId, memberId) {
  return staffSend("POST", `/${classId}/attendance/walk-ins`, { memberId });
}

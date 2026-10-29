// Calendar dates arrive from the server as "YYYY-MM-DD" in the branch's local
// time. They're handled as plain local dates here (never through UTC), so a
// day can't slip by one in a browser set to another time zone.

function parse(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function toIso(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function addDays(iso, days) {
  const date = parse(iso);
  date.setDate(date.getDate() + days);
  return toIso(date);
}

// "Thu 29 Oct"
export function formatDay(iso) {
  return parse(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

// "Thu" and "29", for compact day pickers.
export function weekdayShort(iso) {
  return parse(iso).toLocaleDateString("en-GB", { weekday: "short" });
}

export function dayOfMonth(iso) {
  return parse(iso).getDate();
}

// "Thursday 29 October 2026"
export function formatLongDay(iso) {
  return parse(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

// "26 Oct – 1 Nov 2026"
export function weekLabel(startIso, endIso) {
  const start = parse(startIso);
  const end = parse(endIso);
  const startText = start.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(start.getFullYear() !== end.getFullYear() ? { year: "numeric" } : {}),
  });
  const endText = end.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return `${startText} – ${endText}`;
}

import { useCallback, useEffect, useState } from "react";
import { fetchMySchedule } from "../../api/classes.js";
import { addDays, dayOfMonth, formatLongDay, weekdayShort, weekLabel } from "./dates.js";
import useServerClock, { offsetLabel } from "./useServerClock.js";

// A coach's own daily/weekly schedule: their classes and private training
// sessions, read-only (editing a class or PT hours is the branch manager's
// job - see ClassSchedule.jsx and PTHoursManager.jsx). The list reloads
// every 30 seconds, same as the member's class list, so a class the branch
// manager just cancelled or moved shows up without a refresh.
//
// User story: "As a coach, I want to view my daily and weekly schedule of
// classes and PT sessions, so that I can plan my working day."

const REFRESH_MS = 30000;

function itemsFor(data) {
  const classes = (data.classes || []).map((c) => ({
    id: `class-${c.id}`,
    date: c.date,
    startTime: c.startTime,
    endTime: c.endTime,
    kind: "Class",
    title: c.name,
    detail: `${c.booked} of ${c.capacity} booked${c.room ? ` · ${c.room}` : ""}`,
    branch: c.branch,
    state: c.state,
    cancelReason: c.cancelReason,
  }));
  const pt = (data.ptSessions || []).map((s) => ({
    id: `pt-${s.id}`,
    date: s.date,
    startTime: s.startTime,
    endTime: s.endTime,
    kind: "Private training",
    title: s.memberName,
    detail: s.note || "No notes from the member.",
    branch: s.branch,
    state: s.state,
    cancelReason: s.cancelReason,
  }));
  return [...classes, ...pt].sort((a, b) => a.startTime.localeCompare(b.startTime));
}

export default function MySchedule() {
  const [week, setWeek] = useState(null);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const clock = useServerClock(data?.nowIso, data?.timeZone);

  const load = useCallback(() => {
    return fetchMySchedule(week)
      .then((body) => {
        setData(body);
        setError(null);
        setSelected((current) => (body.days.some((d) => d.date === current) ? current : (body.days.find((d) => d.isToday) || body.days[0]).date));
      })
      .catch((err) => setError(err.message));
  }, [week]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (error && !data) return <div style={styles.errorBox}>Couldn't load your schedule: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading your schedule...</p>;

  const day = data.days.find((d) => d.date === selected) || data.days[0];
  const items = itemsFor(data);
  const dayItems = items.filter((i) => i.date === day.date);
  const isThisWeek = data.days.some((d) => d.isToday);
  const branches = [...new Set(items.map((i) => i.branch))];

  return (
    <div>
      {error && <div style={styles.errorBox}>{error}</div>}
      {branches.length > 1 && (
        <p style={styles.multiBranchNote}>
          You're teaching across more than one branch this week: {branches.join(", ")}.
        </p>
      )}

      <div style={styles.weekBar}>
        <button type="button" onClick={() => setWeek(addDays(data.weekStart, -7))} style={styles.navButton} aria-label="Previous week">
          ‹
        </button>
        <span style={styles.weekLabel}>{weekLabel(data.weekStart, data.weekEnd)}</span>
        <button type="button" onClick={() => setWeek(addDays(data.weekStart, 7))} style={styles.navButton} aria-label="Next week">
          ›
        </button>
        {!isThisWeek && (
          <button type="button" onClick={() => setWeek(null)} style={styles.linkButton}>
            This week
          </button>
        )}
      </div>

      <p style={styles.clockNote}>
        All times are Beirut time ({offsetLabel(data.utcOffset)}) · now <strong>{clock.time}</strong>, {clock.day}
      </p>

      <div style={styles.strip} role="tablist" aria-label="Days">
        {data.days.map((d) => {
          const count = items.filter((i) => i.date === d.date && i.state !== "cancelled").length;
          const active = d.date === day.date;
          return (
            <button
              key={d.date}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setSelected(d.date)}
              style={{
                ...styles.dayButton,
                ...(d.isPast ? styles.dayPast : null),
                ...(d.isToday ? styles.dayToday : null),
                ...(active ? styles.dayActive : null),
              }}
            >
              <span style={styles.dayWeekday}>{d.isToday ? "Today" : weekdayShort(d.date)}</span>
              <span style={styles.dayNumber}>{dayOfMonth(d.date)}</span>
              <span style={styles.dayCount}>{count ? `${count} booking${count === 1 ? "" : "s"}` : "Free"}</span>
            </button>
          );
        })}
      </div>

      <div style={styles.dayTitle}>
        {formatLongDay(day.date)}
        {day.isPast && <span style={styles.pastTag}>Past</span>}
      </div>

      {dayItems.length === 0 && <div style={styles.empty}>Nothing on your schedule this day.</div>}

      {dayItems.map((item) => (
        <ScheduleRow key={item.id} item={item} />
      ))}
    </div>
  );
}

function ScheduleRow({ item }) {
  let tag = null;
  if (item.state === "cancelled") {
    tag = <span style={styles.cancelledTag}>Cancelled{item.cancelReason ? `: ${item.cancelReason}` : ""}</span>;
  } else if (item.state === "in_progress") {
    tag = <span style={styles.liveTag}>In progress</span>;
  } else if (item.state === "finished") {
    tag = <span style={styles.doneTag}>Finished</span>;
  }

  return (
    <div style={{ ...styles.card, ...(item.state !== "upcoming" && item.state !== "in_progress" ? styles.cardMuted : null) }}>
      <div style={styles.cardTime}>
        <span>{item.startTime}</span>
        <span style={styles.cardEnd}>{item.endTime}</span>
      </div>
      <div style={styles.cardBody}>
        <span style={{ ...styles.cardTitle, textDecoration: item.state === "cancelled" ? "line-through" : "none" }}>
          {item.kind === "Private training" ? `Private training · ${item.title}` : item.title}
        </span>
        <span style={styles.cardMeta}>
          {item.kind}
          {item.branch && ` · ${item.branch}`}
        </span>
        {item.state !== "cancelled" && <span style={styles.cardDetail}>{item.detail}</span>}
      </div>
      <div style={styles.cardTag}>{tag}</div>
    </div>
  );
}

const styles = {
  muted: { fontSize: 12, color: "#888", margin: "6px 0" },
  empty: {
    padding: 14,
    border: "1px dashed #d0d0d5",
    borderRadius: 10,
    fontSize: 13,
    color: "#888",
    textAlign: "center",
    marginBottom: 8,
  },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  multiBranchNote: { background: "#fff7e0", color: "#7a5600", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  weekBar: { display: "flex", alignItems: "center", gap: 8, marginBottom: 10 },
  navButton: {
    width: 32,
    height: 32,
    fontSize: 18,
    lineHeight: 1,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  weekLabel: { fontSize: 14, fontWeight: 700, flex: 1, textAlign: "center" },
  clockNote: { fontSize: 12, color: "#666", margin: "0 0 8px", textAlign: "center" },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer" },
  strip: { display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 4, marginBottom: 12 },
  dayButton: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 1,
    padding: "6px 2px",
    border: "1px solid #e4e4e8",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
    fontFamily: "inherit",
    color: "#1a1a1a",
    minWidth: 0,
  },
  dayPast: { background: "#ececf0", color: "#8a8a93", borderColor: "#dcdce2" },
  dayToday: { borderColor: "#124096", boxShadow: "inset 0 0 0 1px #124096" },
  dayActive: { background: "#124096", color: "#fff", borderColor: "#124096" },
  dayWeekday: { fontSize: 11, fontWeight: 600 },
  dayNumber: { fontSize: 16, fontWeight: 800 },
  dayCount: { fontSize: 9, opacity: 0.8, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" },
  dayTitle: { display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, margin: "4px 0 8px" },
  pastTag: { fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 999, background: "#dcdce2", color: "#555" },
  card: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: 12,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 8,
  },
  cardMuted: { background: "#f7f7f9", color: "#77777f" },
  cardTime: { display: "flex", flexDirection: "column", alignItems: "center", width: 44, flexShrink: 0, fontSize: 14, fontWeight: 700 },
  cardEnd: { fontSize: 11, fontWeight: 500, opacity: 0.7 },
  cardBody: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  cardTitle: { fontSize: 14, fontWeight: 700 },
  cardMeta: { fontSize: 12, opacity: 0.8 },
  cardDetail: { fontSize: 12, opacity: 0.7 },
  cardTag: { flexShrink: 0 },
  liveTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  doneTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e4e4e8", color: "#555" },
  cancelledTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
};

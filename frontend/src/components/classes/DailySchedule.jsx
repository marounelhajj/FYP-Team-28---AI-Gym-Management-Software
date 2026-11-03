import { useCallback, useEffect, useState } from "react";
import { fetchClassDay } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { addDays, formatDay, formatLongDay } from "./dates.js";

// User story: "As a receptionist, I want to view the daily class schedule and
// open slots, so that I can answer member questions and book walk-ins into
// classes."
//
// One day's classes at the branch, soonest first, with the spots still open.
// Reloads every 30 seconds, so spots members take in the app show up here.
// "Open" comes from the server: a class that has started isn't an open slot.
// Booking itself happens in the class's details (DeskBooking.jsx).

const REFRESH_MS = 30000;
const LOW_SPOTS = 3;

export default function DailySchedule({ branch, refreshKey, onOpen }) {
  const [date, setDate] = useState(null); // null = today, whatever day that is by now
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [coachFilter, setCoachFilter] = useState("");
  const [openOnly, setOpenOnly] = useState(false);

  const load = useCallback(() => {
    return fetchClassDay({ date, branch })
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [date, branch]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load, refreshKey]);

  if (!data) return error ? <div style={styles.errorBox}>Couldn&apos;t load the day: {error}</div> : <p style={styles.muted}>Loading...</p>;

  const isOpen = (c) => c.state === "upcoming" && c.spotsLeft > 0;
  const typeNames = [...new Set(data.classes.map((c) => c.name))].sort();
  const coachNames = [...new Set(data.classes.map((c) => c.coachName))].sort();
  const visible = data.classes.filter(
    (c) => (!typeFilter || c.name === typeFilter) && (!coachFilter || c.coachName === coachFilter) && (!openOnly || isOpen(c)),
  );
  const filtering = typeFilter || coachFilter || openOnly;
  const { summary, nextOpen } = data;

  return (
    <div>
      <div style={styles.toolbar}>
        <div style={styles.dayNav}>
          <button type="button" onClick={() => setDate(addDays(data.date, -1))} style={styles.navButton} aria-label="Previous day">
            ‹
          </button>
          <button type="button" onClick={() => setDate(null)} disabled={data.isToday} style={styles.todayButton}>
            Today
          </button>
          <button type="button" onClick={() => setDate(addDays(data.date, 1))} style={styles.navButton} aria-label="Next day">
            ›
          </button>
          <span style={styles.dayLabel}>{formatLongDay(data.date)}</span>
          {data.isToday && <span style={styles.todayBadge}>Today</span>}
          {data.isPast && <span style={styles.pastBadge}>Past · view only</span>}
        </div>
        <label style={styles.jump}>
          <span style={styles.jumpLabel}>Go to</span>
          <input
            type="date"
            value={data.date}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            style={styles.select}
            aria-label="Go to date"
          />
        </label>
      </div>

      {error && <div style={styles.errorBox}>Couldn&apos;t refresh the day: {error}</div>}

      <div style={styles.stats}>
        <Stat label="Classes" value={summary.classes} />
        <Stat label="With open slots" value={summary.openClasses} strong={summary.openClasses > 0} />
        <Stat label="Open spots" value={summary.openSpots} strong={summary.openSpots > 0} />
        <Stat label="Full" value={summary.fullClasses} warn={summary.fullClasses > 0} />
      </div>

      {!data.isPast && summary.openClasses === 0 && nextOpen && (
        <div style={styles.nextBox}>
          <span>
            {summary.classes === 0 ? "No classes" : "No open slots"} {data.isToday ? "left today" : "this day"}. Next open:{" "}
            <strong>
              {nextOpen.name}, {formatDay(nextOpen.date)} at {nextOpen.startTime}
            </strong>{" "}
            ({nextOpen.spotsLeft} spot{nextOpen.spotsLeft === 1 ? "" : "s"}).
          </span>
          <button type="button" onClick={() => setDate(nextOpen.date)} style={styles.linkButton}>
            Go to that day
          </button>
        </div>
      )}

      {data.classes.length > 0 && (
        <div style={styles.filters}>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Class type" style={styles.select}>
            <option value="">All classes</option>
            {typeNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <select value={coachFilter} onChange={(e) => setCoachFilter(e.target.value)} aria-label="Coach" style={styles.select}>
            <option value="">All coaches</option>
            {coachNames.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <label style={styles.checkbox}>
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
            Open slots only
          </label>
        </div>
      )}

      {visible.length === 0 ? (
        <div style={styles.empty}>
          {filtering && data.classes.length > 0 ? "No classes match." : "No classes on this day."}
        </div>
      ) : (
        <ul style={styles.list}>
          {visible.map((c) => (
            <ClassRow key={c.id} gymClass={c} canBook={data.canBookMembers} isOpen={isOpen(c)} onOpen={() => onOpen(c)} />
          ))}
        </ul>
      )}
      <p style={styles.muted}>Times are Beirut time. Spots update every 30 seconds.</p>
    </div>
  );
}

function ClassRow({ gymClass: c, canBook, isOpen, onOpen }) {
  const cancelled = c.state === "cancelled";
  const over = c.state === "finished" || c.state === "in_progress" || cancelled;
  return (
    <li style={{ ...styles.row, ...(over ? styles.rowMuted : null) }}>
      <div style={styles.time}>
        <span style={styles.start}>{c.startTime}</span>
        <span style={styles.end}>{c.endTime}</span>
      </div>
      <div style={styles.body}>
        <span style={{ ...styles.name, textDecoration: cancelled ? "line-through" : "none" }}>{c.name}</span>
        <span style={styles.meta}>
          {c.coachName}
          {c.room && ` · ${c.room}`}
        </span>
        {cancelled && c.cancelReason && <span style={styles.cancelNote}>{c.cancelReason}</span>}
      </div>
      <div style={styles.spots}>
        <Spots gymClass={c} />
      </div>
      <button
        type="button"
        onClick={onOpen}
        style={isOpen && canBook ? styles.bookButton : styles.viewButton}
        aria-label={`${isOpen && canBook ? "Book a member into" : "View"} ${c.name} at ${c.startTime}`}
      >
        {isOpen && canBook ? "Book member" : "View"}
      </button>
    </li>
  );
}

function Spots({ gymClass: c }) {
  if (c.state === "cancelled") return <span style={{ ...styles.tag, ...styles.tagCancelled }}>Cancelled</span>;
  if (c.state === "finished") return <span style={{ ...styles.tag, ...styles.tagDone }}>Finished</span>;
  if (c.state === "in_progress") return <span style={{ ...styles.tag, ...styles.tagLive }}>In progress</span>;
  if (c.spotsLeft === 0) return <span style={{ ...styles.tag, ...styles.tagFull }}>Full</span>;
  return (
    <span style={c.spotsLeft <= LOW_SPOTS ? styles.spotsLow : styles.spotsOpen}>
      {c.spotsLeft} spot{c.spotsLeft === 1 ? "" : "s"} left
      <span style={styles.spotsOf}> of {Math.min(c.capacity, c.maxCapacity)}</span>
    </span>
  );
}

function Stat({ label, value, strong, warn }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statLabel}>{label}</div>
      <div style={{ ...styles.statValue, color: strong ? "#129638" : warn ? "#a15c00" : "#1a1a1a" }}>{value}</div>
    </div>
  );
}

const styles = {
  muted: { fontSize: 12, color: "#888", margin: "10px 0 0" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  toolbar: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 },
  dayNav: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  navButton: {
    width: 36,
    height: 36,
    fontSize: 20,
    lineHeight: 1,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  todayButton: {
    height: 36,
    padding: "0 14px",
    fontSize: 14,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  dayLabel: { fontSize: 17, fontWeight: 700, marginLeft: 6 },
  todayBadge: { padding: "2px 8px", borderRadius: 999, background: "#124096", color: "#fff", fontSize: 11, fontWeight: 700 },
  pastBadge: { padding: "2px 8px", borderRadius: 999, background: "#dcdce2", color: "#555", fontSize: 11, fontWeight: 600 },
  jump: { display: "flex", alignItems: "center", gap: 8 },
  jumpLabel: { fontSize: 13, fontWeight: 600, color: "#444" },
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff" },
  stats: { display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 },
  stat: { flex: "1 1 110px", border: "1px solid #e4e4e8", borderRadius: 10, padding: "10px 12px", background: "#fff" },
  statLabel: { fontSize: 12, color: "#666", fontWeight: 600 },
  statValue: { fontSize: 22, fontWeight: 800, marginTop: 2, fontVariantNumeric: "tabular-nums" },
  nextBox: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
    background: "#fff7e0",
    color: "#7a5600",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 12,
  },
  linkButton: { border: "none", background: "none", padding: 0, color: "#124096", fontSize: 14, fontWeight: 600, cursor: "pointer" },
  filters: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 },
  checkbox: { display: "inline-flex", alignItems: "center", gap: 6, fontSize: 14, color: "#444" },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 14, color: "#888", textAlign: "center" },
  list: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  row: { display: "flex", alignItems: "center", flexWrap: "wrap", gap: 14, padding: "12px 14px", borderBottom: "1px solid #f0f0f3" },
  rowMuted: { background: "#f7f7f9", color: "#77777f" },
  time: { display: "flex", flexDirection: "column", alignItems: "center", width: 48, flexShrink: 0 },
  start: { fontSize: 16, fontWeight: 800, fontVariantNumeric: "tabular-nums" },
  end: { fontSize: 12, opacity: 0.7, fontVariantNumeric: "tabular-nums" },
  body: { flex: "1 1 160px", minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  name: { fontSize: 15, fontWeight: 700 },
  meta: { fontSize: 13, opacity: 0.85 },
  cancelNote: { fontSize: 12, color: "#b3261e" },
  spots: { flexShrink: 0, minWidth: 130, textAlign: "right" },
  spotsOpen: { fontSize: 14, fontWeight: 700, color: "#0f6e2b" },
  spotsLow: { fontSize: 14, fontWeight: 700, color: "#a15c00" },
  spotsOf: { fontWeight: 400, color: "#888" },
  tag: { fontSize: 12, fontWeight: 700, padding: "3px 8px", borderRadius: 4, whiteSpace: "nowrap" },
  tagLive: { background: "#e3f5e8", color: "#0f6e2b" },
  tagDone: { background: "#e4e4e8", color: "#555" },
  tagCancelled: { background: "#fdeceb", color: "#b3261e" },
  tagFull: { background: "#fff1d6", color: "#8a5300" },
  bookButton: {
    flexShrink: 0,
    width: 118,
    padding: "8px 0",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.green,
    cursor: "pointer",
  },
  viewButton: {
    flexShrink: 0,
    width: 118,
    padding: "8px 0",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#333",
    cursor: "pointer",
  },
};

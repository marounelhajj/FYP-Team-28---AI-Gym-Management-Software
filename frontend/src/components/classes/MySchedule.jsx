import { useCallback, useEffect, useState } from "react";
import { fetchMySchedule } from "../../api/classes.js";
import { addDays, dayOfMonth, formatLongDay, weekdayShort, weekLabel } from "./dates.js";
import useServerClock, { offsetLabel } from "./useServerClock.js";
import AttendanceSheet from "./AttendanceSheet.jsx";
import HealthBriefing from "../health/HealthBriefing.jsx";
import SessionLogForm from "../coaching/SessionLogForm.jsx";
import { BADGE_TONES, healthBadge } from "../health/HealthViews.jsx";

// A coach's own daily/weekly schedule: their classes and private training
// sessions, read-only (editing a class or PT hours is the branch manager's
// job - see ClassSchedule.jsx and PTHoursManager.jsx). The list reloads
// every 30 seconds, same as the member's class list, so a class the branch
// manager just cancelled or moved shows up without a refresh.
//
// User story: "As a coach, I want to view my daily and weekly schedule of
// classes and PT sessions, so that I can plan my working day."
//
// Each class and private session that's coming up (or just over) also shows
// what the coach needs to know about its members' health, and opens the
// health briefing: "As a coach, I want to view a client's health restrictions
// and injuries before starting a session, so that I can adapt the workout
// safely." (HealthBriefing.jsx)
//
// Time-off blocks (see MyAvailability.jsx... actually MyTimeOff.jsx - "As a
// coach, I want to block off time on my calendar when I'm unavailable, so
// that members can't book me during that time") show up here too, split
// into one row per day they touch so a multi-day block reads naturally in
// a day-by-day agenda.

const REFRESH_MS = 30000;

// TimeOffSerializer gives "YYYY-MM-DD HH:MM" (already Beirut time, see
// classes/serializers.py's DATETIME format) - parsed as a plain local Date,
// same convention as dates.js, never through UTC.
function parseServerDateTime(value) {
  const [datePart, timePart] = value.split(" ");
  const [y, m, d] = datePart.split("-").map(Number);
  const [h, min] = (timePart || "00:00").split(":").map(Number);
  return new Date(y, m - 1, d, h, min);
}

function dayBounds(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return [new Date(y, m - 1, d, 0, 0), new Date(y, m - 1, d, 23, 59)];
}

function fmtTime(dt) {
  return `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
}

// The health line for a class: how many of its members need something adapted.
function classHealthBadge(counts) {
  if (!counts) return null;
  if (counts.booked === 0) return { text: "No one booked yet", tone: "grey" };
  if (counts.restricted > 0) {
    const text = `${counts.restricted} with health notes${counts.undeclared ? ` · ${counts.undeclared} not declared` : ""}`;
    return { text, tone: counts.severe ? "red" : "amber" };
  }
  if (counts.undeclared > 0) return { text: `${counts.undeclared} not declared`, tone: "grey" };
  return { text: "No restrictions", tone: "green" };
}

function itemsFor(data) {
  const health = data.health || { classes: {}, ptSessions: {} };
  const classes = (data.classes || []).map((c) => ({
    id: `class-${c.id}`,
    classId: c.id,
    date: c.date,
    startTime: c.startTime,
    endTime: c.endTime,
    kind: "Class",
    title: c.name,
    detail: `${c.booked} of ${c.capacity} booked${c.room ? ` · ${c.room}` : ""}`,
    branch: c.branch,
    state: c.state,
    cancelReason: c.cancelReason,
    health: c.state === "cancelled" ? null : classHealthBadge(health.classes[c.id]),
    briefing: { kind: "class", id: c.id },
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
    health: s.state === "cancelled" ? null : healthBadge(health.ptSessions[s.id]),
    briefing: { kind: "pt", id: s.id },
    ptId: s.id,
    logged: (data.ptLogged || []).includes(s.id),
  }));
  const timeOff = (data.timeOff || []).flatMap((block) => {
    const blockStart = parseServerDateTime(block.startsAt);
    const blockEnd = parseServerDateTime(block.endsAt);
    return (data.days || []).flatMap((d) => {
      const [dayStart, dayEnd] = dayBounds(d.date);
      if (blockStart > dayEnd || blockEnd < dayStart) return [];
      const segStart = blockStart > dayStart ? blockStart : dayStart;
      const segEnd = blockEnd < dayEnd ? blockEnd : dayEnd;
      return [{
        id: `timeoff-${block.id}-${d.date}`,
        date: d.date,
        startTime: fmtTime(segStart),
        endTime: fmtTime(segEnd),
        kind: "Time off",
        title: block.reason || "Unavailable",
        detail: "",
        branch: null,
        state: block.state,
        cancelReason: "",
      }];
    });
  });
  return [...classes, ...pt, ...timeOff].sort((a, b) => a.startTime.localeCompare(b.startTime));
}

export default function MySchedule() {
  const [week, setWeek] = useState(null);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [attendanceFor, setAttendanceFor] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [logFor, setLogFor] = useState(null);
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
        <ScheduleRow
          key={item.id}
          item={item}
          onAttendance={() => setAttendanceFor(item.classId)}
          onHealth={() => setBriefing(item.briefing)}
          onLog={() => setLogFor(item.ptId)}
        />
      ))}

      {attendanceFor && (
        <AttendanceSheet classId={attendanceFor} onClose={() => setAttendanceFor(null)} onChanged={load} />
      )}
      {logFor && (
        <SessionLogForm
          sessionId={logFor}
          onClose={() => {
            setLogFor(null);
            load();
          }}
        />
      )}
      {briefing && <HealthBriefing kind={briefing.kind} id={briefing.id} onClose={() => setBriefing(null)} />}
    </div>
  );
}

function ScheduleRow({ item, onAttendance, onHealth, onLog }) {
  // Coaching notes can be written once a private session starts.
  const canLog = item.kind === "Private training" && (item.state === "in_progress" || item.state === "finished");
  // SCRUM-36: attendance opens when a class starts.
  const canTakeAttendance = item.kind === "Class" && (item.state === "in_progress" || item.state === "finished");
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
          {item.kind === "Private training" || item.kind === "Time off"
            ? `${item.kind} · ${item.title}`
            : item.title}
        </span>
        <span style={styles.cardMeta}>
          {item.kind}
          {item.branch && ` · ${item.branch}`}
        </span>
        {item.state !== "cancelled" && <span style={styles.cardDetail}>{item.detail}</span>}
        {item.health && (
          <span style={{ ...styles.healthBadge, ...BADGE_TONES[item.health.tone] }}>{item.health.text}</span>
        )}
      </div>
      <div style={styles.cardTag}>
        {tag}
        {item.health && (
          <button type="button" onClick={onHealth} style={styles.healthButton} aria-label={`Health briefing for ${item.title}`}>
            Health briefing
          </button>
        )}
        {canLog && (
          <button type="button" onClick={onLog} style={item.logged ? styles.loggedButton : styles.attendanceButton} aria-label={`${item.logged ? "View log" : "Log session"} for ${item.title}`}>
            {item.logged ? "✓ Logged" : "Log session"}
          </button>
        )}
        {canTakeAttendance && (
          <button type="button" onClick={onAttendance} style={styles.attendanceButton}>
            Attendance
          </button>
        )}
      </div>
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
  cardTag: { flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 },
  healthBadge: { alignSelf: "flex-start", fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, marginTop: 2 },
  healthButton: {
    height: 30,
    padding: "0 12px",
    border: "1px solid #124096",
    borderRadius: 8,
    background: "#fff",
    color: "#124096",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  loggedButton: {
    height: 30,
    padding: "0 12px",
    border: "1px solid #129638",
    borderRadius: 8,
    background: "#e3f5e8",
    color: "#0f6e2b",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  attendanceButton: {
    height: 30,
    padding: "0 12px",
    border: "none",
    borderRadius: 8,
    background: "#124096",
    color: "#fff",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  liveTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  doneTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e4e4e8", color: "#555" },
  cancelledTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
};

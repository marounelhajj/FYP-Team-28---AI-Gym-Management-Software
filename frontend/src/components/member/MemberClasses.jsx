import { useCallback, useEffect, useState } from "react";
import { bookClass, cancelMyBooking, fetchMyClasses } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { addDays, dayOfMonth, formatDay, formatLongDay, weekdayShort, weekLabel } from "../classes/dates.js";
import useServerClock, { offsetLabel } from "../classes/useServerClock.js";

// The member's view of their branch's class calendar (built by the branch
// manager on the Class Schedule screen): pick a day, reserve a spot, or give
// one back. The server enforces every rule - one class at a time, no full or
// past classes, a membership that's valid on the class date - and this only
// explains up front why a button is disabled. Times are Beirut time, and the
// list reloads every 30 seconds - a live calendar: spots others take, a class
// filling up or starting all show up without a refresh. A day where every
// upcoming class is full is marked "Full".

const REFRESH_MS = 30000;

const toMinutes = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

function overlaps(a, b) {
  return a.id !== b.id && a.date === b.date && toMinutes(a.startTime) < toMinutes(b.endTime) && toMinutes(a.endTime) > toMinutes(b.startTime);
}

export default function MemberClasses() {
  const [week, setWeek] = useState(null);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [coachFilter, setCoachFilter] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const clock = useServerClock(data?.nowIso, data?.timeZone);

  const load = useCallback(() => {
    return fetchMyClasses(week)
      .then((body) => {
        setData(body);
        setError(null);
        // Opens on the first day that still has a class to book (today, if
        // something is still to come), not on a day where everything is over.
        setSelected((current) => {
          if (body.days.some((d) => d.date === current)) return current;
          const bookable = body.classes.find((c) => c.state === "upcoming");
          return (
            bookable?.date ||
            (body.days.find((d) => d.isToday) || body.days.find((d) => !d.isPast) || body.days[0]).date
          );
        });
      })
      .catch((err) => setError(err.message));
  }, [week]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  async function act(gymClass, action) {
    setBusyId(gymClass.id);
    setActionError(null);
    try {
      if (action === "book") {
        await bookClass(gymClass.id);
        setNotice(`You're booked into ${gymClass.name} on ${formatDay(gymClass.date)} at ${gymClass.startTime}.`);
      } else {
        await cancelMyBooking(gymClass.id);
        setNotice(`Your spot in ${gymClass.name} on ${formatDay(gymClass.date)} was given back.`);
      }
      await load();
    } catch (err) {
      setActionError(err.message);
      load();
    } finally {
      setBusyId(null);
    }
  }

  if (error && !data) return <div style={styles.errorBox}>Couldn't load classes: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading classes...</p>;

  const day = data.days.find((d) => d.date === selected) || data.days[0];
  const mine = (c) => c.myBooking?.status === "Booked";
  // "Free spots only" still shows the member's own classes.
  const matches = (c) =>
    (!typeFilter || c.name === typeFilter) &&
    (!coachFilter || String(c.coachId) === coachFilter) &&
    (!freeOnly || mine(c) || (c.state === "upcoming" && c.spotsLeft > 0));
  const dayClasses = data.classes.filter((c) => c.date === day.date && matches(c));
  const typeNames = [...new Set(data.classes.map((c) => c.name))].sort();
  const coachList = [...new Map(data.classes.map((c) => [String(c.coachId), c.coachName])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1]),
  );
  // Private sessions count as being busy too (ids prefixed so they can't match a class id).
  const ptCommitments = (data.upcomingPt || []).map((s) => ({
    id: `pt-${s.id}`,
    name: `private training with ${s.coachName}`,
    date: s.date,
    startTime: s.startTime,
    endTime: s.endTime,
  }));
  const reserved = [...data.upcoming, ...data.classes.filter(mine), ...ptCommitments];
  const isThisWeek = data.days.some((d) => d.isToday);
  const filtering = typeFilter || coachFilter || freeOnly;

  return (
    <div>
      {!data.canBook && (
        <div style={styles.warnBox}>You can't reserve classes right now: {data.bookingBlockedReason}</div>
      )}
      {notice && <div style={styles.successBox}>{notice}</div>}
      {actionError && <div style={styles.errorBox}>{actionError}</div>}

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

      <div style={styles.filters}>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Class type" style={styles.filterSelect}>
          <option value="">All classes</option>
          {typeNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <select value={coachFilter} onChange={(e) => setCoachFilter(e.target.value)} aria-label="Coach" style={styles.filterSelect}>
          <option value="">All coaches</option>
          {coachList.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <label style={styles.freeOnly}>
          <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
          Free spots only
        </label>
      </div>

      <div style={styles.strip} role="tablist" aria-label="Days">
        {data.days.map((d) => {
          const onDay = data.classes.filter((c) => c.date === d.date && c.state !== "cancelled" && matches(c));
          const bookable = onDay.filter((c) => c.state === "upcoming");
          const full = bookable.length > 0 && bookable.every((c) => c.spotsLeft === 0 && !mine(c));
          const count = onDay.length;
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
              <span style={full && !active ? { ...styles.dayCount, ...styles.dayFull } : styles.dayCount}>
                {full ? "Full" : count ? `${count} class${count === 1 ? "" : "es"}` : "—"}
              </span>
            </button>
          );
        })}
      </div>

      <div style={styles.dayTitle}>
        {formatLongDay(day.date)}
        {day.isPast && <span style={styles.pastTag}>Past</span>}
      </div>
      {day.isPast && <p style={styles.muted}>This day has passed - you can see what was on, but not book.</p>}
      {dayClasses.length === 0 && (
        <div style={styles.empty}>{filtering ? "No classes match on this day." : "No classes this day."}</div>
      )}

      {dayClasses.map((c) => (
        <ClassRow
          key={c.id}
          gymClass={c}
          data={data}
          clash={reserved.find((r) => overlaps(r, c))}
          busy={busyId === c.id}
          onBook={() => act(c, "book")}
          onCancel={() => act(c, "cancel")}
        />
      ))}

      {data.canBook && data.bookableUntil && (
        <p style={styles.muted}>You can book classes up to {formatDay(data.bookableUntil)}, your renewal date.</p>
      )}
    </div>
  );
}

function ClassRow({ gymClass: c, data, clash, busy, onBook, onCancel }) {
  const mine = c.myBooking?.status === "Booked";
  let action;
  if (c.state === "cancelled") {
    action = <span style={styles.cancelledTag}>Cancelled</span>;
  } else if (c.state === "finished") {
    action = mine ? (
      <span style={c.myBooking.attendance === "No-show" ? styles.missedTag : styles.doneTag}>
        {c.myBooking.attendance === "No-show" ? "Missed" : "Attended"}
      </span>
    ) : (
      <span style={styles.doneTag}>Finished</span>
    );
  } else if (c.state === "in_progress") {
    action = <span style={styles.liveTag}>{mine ? "You're in · in progress" : "In progress"}</span>;
  } else if (mine) {
    action = (
      <button type="button" onClick={onCancel} disabled={busy} style={styles.cancelButton}>
        {busy ? "..." : "Cancel"}
      </button>
    );
  } else {
    let reason = null;
    if (!data.canBook) reason = "Reserve";
    else if (data.bookableUntil && c.date > data.bookableUntil) reason = "After renewal";
    else if (c.spotsLeft === 0) reason = "Full";
    else if (clash) reason = "Clashes";
    action = reason ? (
      <button type="button" disabled style={styles.disabledButton}>
        {reason}
      </button>
    ) : (
      <button type="button" onClick={onBook} disabled={busy} style={styles.bookButton}>
        {busy ? "..." : "Reserve"}
      </button>
    );
  }

  const muted = c.state !== "upcoming";
  return (
    <div style={{ ...styles.classCard, ...(muted ? styles.classMuted : null), ...(mine ? styles.classMine : null) }}>
      <div style={styles.classTime}>
        <span>{c.startTime}</span>
        <span style={styles.classEnd}>{c.endTime}</span>
      </div>
      <div style={styles.classBody}>
        <span style={{ ...styles.className, textDecoration: c.state === "cancelled" ? "line-through" : "none" }}>
          {c.name}
          {mine && c.state === "upcoming" && <span style={styles.reservedTag}>Reserved</span>}
        </span>
        <span style={styles.classMeta}>
          {c.coachName}
          {c.room && ` · ${c.room}`}
          {c.state === "upcoming" && ` · ${c.spotsLeft} of ${c.capacity} spots left`}
        </span>
        {!mine && c.state === "upcoming" && clash && (
          <span style={styles.clashNote}>
            You're booked into {clash.name} {clash.startTime}–{clash.endTime} at the same time.
          </span>
        )}
        {c.myBooking?.status === "Cancelled" && c.myBooking.cancelReason && c.myBooking.cancelReason !== "Cancelled by you" && (
          <span style={styles.clashNote}>Your reservation was cancelled: {c.myBooking.cancelReason}.</span>
        )}
      </div>
      <div style={styles.classAction}>{action}</div>
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
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  warnBox: { background: "#fff7e0", color: "#7a5600", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
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
  filters: { display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 10 },
  filterSelect: {
    flex: "1 1 120px",
    minWidth: 0,
    padding: "7px 8px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
  },
  freeOnly: { display: "inline-flex", alignItems: "center", gap: 5, fontSize: 13, color: "#444", whiteSpace: "nowrap" },
  dayFull: { color: "#b3261e", fontWeight: 700, opacity: 1 },
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
  classCard: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: 12,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 8,
  },
  classMuted: { background: "#f7f7f9", color: "#77777f" },
  classMine: { borderColor: "#129638", boxShadow: "inset 3px 0 0 #129638" },
  classTime: { display: "flex", flexDirection: "column", alignItems: "center", width: 44, flexShrink: 0, fontSize: 14, fontWeight: 700 },
  classEnd: { fontSize: 11, fontWeight: 500, opacity: 0.7 },
  classBody: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  className: { fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  classMeta: { fontSize: 12, opacity: 0.8 },
  clashNote: { fontSize: 11, color: "#a15c00" },
  classAction: { flexShrink: 0 },
  bookButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.green,
    cursor: "pointer",
  },
  cancelButton: {
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #de0b12",
    borderRadius: 6,
    background: "#fff",
    color: "#de0b12",
    cursor: "pointer",
  },
  disabledButton: {
    padding: "7px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #e4e4e8",
    borderRadius: 6,
    background: "#f3f3f5",
    color: "#999",
    cursor: "not-allowed",
  },
  reservedTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  liveTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  doneTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e4e4e8", color: "#555" },
  missedTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
  cancelledTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
  subTitle: { fontSize: 14, fontWeight: 700, margin: "16px 0 8px" },
  upcoming: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10 },
  upcomingRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10,
    padding: "10px 12px",
    borderBottom: "1px solid #f0f0f3",
    fontSize: 13,
  },
};

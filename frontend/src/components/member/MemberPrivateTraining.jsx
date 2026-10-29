import { useCallback, useEffect, useState } from "react";
import { bookPtSession, cancelMyPtSession, fetchMyCoaches, fetchPtSlots } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { addDays, dayOfMonth, formatDay, formatLongDay, weekdayShort, weekLabel } from "../classes/dates.js";
import useServerClock, { offsetLabel } from "../classes/useServerClock.js";

// User story: "As a member, I want to browse and book available classes or PT
// sessions directly through the app, so that I can reserve my spot without
// contacting the front desk."
//
// The coaches at the member's branch - what they teach and their private
// training hours - and, for one coach, every session in the week with its
// state (free, booked by someone else, coach teaching then, ...). Only free
// sessions can be booked; the server decides every state and checks again
// when booking. Reloads every 30 seconds, so sessions others book disappear.

const REFRESH_MS = 30000;
const SLOT_LABELS = {
  open: "Free",
  yours: "Yours",
  taken: "Booked",
  coach_busy: "Class",
  closed: "Closed",
  clash: "You're busy",
};

export default function MemberPrivateTraining() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [coach, setCoach] = useState(null);

  const load = useCallback(() => {
    return fetchMyCoaches()
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (coach) {
    return (
      <CoachSessions
        coach={coach}
        onBack={() => {
          setCoach(null);
          load();
        }}
      />
    );
  }
  if (error && !data) return <div style={styles.errorBox}>Couldn't load coaches: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading coaches...</p>;
  if (data.coaches.length === 0) return <div style={styles.empty}>No coaches at {data.branch} yet.</div>;

  return (
    <div>
      <p style={styles.intro}>Coaches at {data.branch}. Book a one-to-one session in a coach&apos;s private training hours.</p>
      {data.coaches.map((c) => (
        <div key={c.id} style={styles.coachCard}>
          <div style={styles.avatar} aria-hidden="true">
            {c.name
              .split(" ")
              .map((part) => part[0])
              .join("")
              .slice(0, 2)}
          </div>
          <div style={styles.coachBody}>
            <div style={styles.coachName}>{c.name}</div>
            <div style={styles.coachMeta}>
              {c.teaches.length ? `Teaches ${c.teaches.join(", ")}` : "No group classes coming up"}
            </div>
            <div style={styles.coachMeta}>
              {c.ptHours.length
                ? `Private training: ${c.ptHours.map((h) => `${h.day} ${h.startTime}–${h.endTime}`).join(" · ")}`
                : "No private training hours"}
            </div>
            {c.nextOpen && (
              <div style={styles.nextOpen}>
                Next free session: {formatDay(c.nextOpen.date)} at {c.nextOpen.startTime}
              </div>
            )}
            {c.ptHours.length > 0 && !c.nextOpen && <div style={styles.fullNote}>Fully booked for the next two weeks</div>}
          </div>
          {c.ptHours.length > 0 && (
            <button type="button" onClick={() => setCoach(c)} style={styles.seeButton}>
              See times
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function CoachSessions({ coach, onBack }) {
  const [week, setWeek] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [actionError, setActionError] = useState(null);
  const clock = useServerClock(data?.nowIso, data?.timeZone);

  const load = useCallback(() => {
    return fetchPtSlots(coach.id, week)
      .then((body) => {
        setData(body);
        setError(null);
        setSelected((current) => {
          if (body.days.some((d) => d.date === current)) return current;
          const firstFree = body.slots.find((s) => s.state === "open");
          return firstFree?.date || (body.days.find((d) => d.isToday) || body.days.find((d) => !d.isPast) || body.days[0]).date;
        });
      })
      .catch((err) => setError(err.message));
  }, [coach.id, week]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  // A session someone else just took stops being "chosen".
  const chosenSlot = chosen && data?.slots.find((s) => s.startsAt === chosen.startsAt);
  const chosenStillFree = chosenSlot?.state === "open";

  async function book() {
    setBusy(true);
    setActionError(null);
    try {
      await bookPtSession({ coachId: coach.id, startsAt: chosen.startsAt, note });
      setNotice(`Booked: private training with ${coach.name} on ${formatDay(chosen.date)} at ${chosen.startTime}.`);
      setChosen(null);
      setNote("");
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusy(false);
      load();
    }
  }

  async function cancel(slot) {
    setBusy(true);
    setActionError(null);
    try {
      await cancelMyPtSession(slot.sessionId);
      setNotice(`Your session on ${formatDay(slot.date)} at ${slot.startTime} was given back.`);
    } catch (err) {
      setActionError(err.message);
    } finally {
      setBusy(false);
      load();
    }
  }

  if (error && !data) return <div style={styles.errorBox}>Couldn't load sessions: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading sessions...</p>;

  const day = data.days.find((d) => d.date === selected) || data.days[0];
  const daySlots = data.slots.filter((s) => s.date === day.date);
  const isThisWeek = data.days.some((d) => d.isToday);
  const atLimit = data.upcomingSessions >= data.maxUpcomingSessions;

  return (
    <div>
      <button type="button" onClick={onBack} style={styles.backButton}>
        ← All coaches
      </button>
      <h3 style={styles.coachTitle}>Private training with {data.coach.name}</h3>
      <p style={styles.muted}>
        {data.hours.map((h) => `${h.day} ${h.startTime}–${h.endTime} (${h.sessionMinutes} min sessions)`).join(" · ")}
      </p>

      {!data.canBook && <div style={styles.warnBox}>You can&apos;t book right now: {data.bookingBlockedReason}</div>}
      {data.canBook && atLimit && (
        <div style={styles.warnBox}>
          You have {data.upcomingSessions} upcoming private sessions - the most you can hold at once. Cancel one to book another.
        </div>
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
        All times are Beirut time ({offsetLabel(data.utcOffset)}) · now <strong>{clock.time}</strong>
      </p>

      <div style={styles.strip} role="tablist" aria-label="Days">
        {data.days.map((d) => {
          const slots = data.slots.filter((s) => s.date === d.date);
          const free = slots.filter((s) => s.state === "open").length;
          const active = d.date === day.date;
          const label = slots.length === 0 ? "—" : free ? `${free} free` : d.isPast ? "Closed" : "Full";
          return (
            <button
              key={d.date}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                setSelected(d.date);
                setChosen(null);
              }}
              style={{
                ...styles.dayButton,
                ...(d.isPast ? styles.dayPast : null),
                ...(d.isToday ? styles.dayToday : null),
                ...(active ? styles.dayActive : null),
              }}
            >
              <span style={styles.dayWeekday}>{d.isToday ? "Today" : weekdayShort(d.date)}</span>
              <span style={styles.dayNumber}>{dayOfMonth(d.date)}</span>
              <span style={label === "Full" && !active ? { ...styles.dayCount, ...styles.dayFull } : styles.dayCount}>{label}</span>
            </button>
          );
        })}
      </div>

      <div style={styles.dayTitle}>{formatLongDay(day.date)}</div>
      {daySlots.length === 0 ? (
        <div style={styles.empty}>{data.coach.name} has no private training hours this day.</div>
      ) : (
        <>
          <div style={styles.slotGrid}>
            {daySlots.map((s) => {
              const isChosen = chosen?.startsAt === s.startsAt;
              const bookable = s.state === "open" && data.canBook && !atLimit;
              return (
                <button
                  key={s.startsAt}
                  type="button"
                  disabled={!(bookable || s.state === "yours")}
                  onClick={() => (s.state === "yours" ? setChosen(s) : setChosen(isChosen ? null : s))}
                  style={{ ...styles.slot, ...(SLOT_STYLES[s.state] || null), ...(isChosen ? styles.slotChosen : null) }}
                  aria-label={`${s.startTime} to ${s.endTime}: ${SLOT_LABELS[s.state]}`}
                >
                  <span style={styles.slotTime}>{s.startTime}</span>
                  <span style={styles.slotState}>{SLOT_LABELS[s.state]}</span>
                </button>
              );
            })}
          </div>
          <p style={styles.legend}>
            Only free sessions can be booked. &quot;Class&quot; means {data.coach.name} is teaching a group class then; &quot;You&apos;re busy&quot;
            means you&apos;re booked into something else.
          </p>
        </>
      )}

      {chosen && chosenSlot?.state === "yours" && (
        <div style={styles.confirm}>
          <strong>Your session with {data.coach.name}</strong>
          <div style={styles.confirmWhen}>
            {formatLongDay(chosen.date)} · {chosen.startTime}–{chosen.endTime}
          </div>
          <div style={styles.confirmActions}>
            <button type="button" onClick={() => setChosen(null)} style={styles.secondaryButton}>
              Keep it
            </button>
            <button type="button" onClick={() => cancel(chosenSlot)} disabled={busy} style={styles.cancelButton}>
              {busy ? "Cancelling..." : "Cancel session"}
            </button>
          </div>
        </div>
      )}
      {chosen && chosenSlot?.state !== "yours" && (
        <div style={styles.confirm}>
          <strong>Private training with {data.coach.name}</strong>
          <div style={styles.confirmWhen}>
            {formatLongDay(chosen.date)} · {chosen.startTime}–{chosen.endTime}
          </div>
          {!chosenStillFree && <div style={styles.errorBox}>Someone has just booked this session - pick another time.</div>}
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={200}
            placeholder="What would you like to work on? (optional)"
            aria-label="Note for the coach"
            style={styles.input}
          />
          <div style={styles.confirmActions}>
            <button type="button" onClick={() => setChosen(null)} style={styles.secondaryButton}>
              Cancel
            </button>
            <button
              type="button"
              onClick={book}
              disabled={busy || !chosenStillFree}
              style={busy || !chosenStillFree ? { ...styles.bookButton, ...styles.buttonDisabled } : styles.bookButton}
            >
              {busy ? "Booking..." : "Book session"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const SLOT_STYLES = {
  open: { borderColor: "#129638", color: "#0f6e2b", background: "#fff", cursor: "pointer" },
  yours: { borderColor: "#129638", color: "#fff", background: "#129638", cursor: "pointer" },
  taken: { background: "#ececf0", color: "#888", textDecoration: "line-through" },
  coach_busy: { background: "#ececf0", color: "#888" },
  closed: { background: "#f3f3f5", color: "#aaa" },
  clash: { background: "#fff7e0", color: "#8a5300", borderColor: "#f0d68a" },
};

const styles = {
  muted: { fontSize: 12, color: "#888", margin: "4px 0 10px" },
  intro: { fontSize: 13, color: "#555", margin: "0 0 10px" },
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
  coachCard: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: 12,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 8,
  },
  avatar: {
    width: 40,
    height: 40,
    flexShrink: 0,
    borderRadius: "50%",
    background: "#eef2fa",
    color: "#124096",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontWeight: 800,
    fontSize: 14,
  },
  coachBody: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  coachName: { fontSize: 15, fontWeight: 700 },
  coachMeta: { fontSize: 12, color: "#666" },
  nextOpen: { fontSize: 12, fontWeight: 700, color: "#0f6e2b" },
  fullNote: { fontSize: 12, fontWeight: 700, color: "#b3261e" },
  seeButton: {
    flexShrink: 0,
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.blue,
    cursor: "pointer",
  },
  backButton: { border: "none", background: "none", padding: 0, color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer" },
  coachTitle: { fontSize: 15, fontWeight: 700, margin: "8px 0 0" },
  weekBar: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 },
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
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer" },
  clockNote: { fontSize: 12, color: "#666", margin: "0 0 8px", textAlign: "center" },
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
  dayFull: { color: "#b3261e", fontWeight: 700, opacity: 1 },
  dayTitle: { fontSize: 14, fontWeight: 700, margin: "4px 0 8px" },
  slotGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(84px, 1fr))", gap: 6 },
  slot: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 1,
    padding: "8px 4px",
    border: "1px solid #e4e4e8",
    borderRadius: 8,
    fontFamily: "inherit",
    cursor: "not-allowed",
  },
  slotChosen: { boxShadow: "0 0 0 2px #124096", borderColor: "#124096" },
  slotTime: { fontSize: 15, fontWeight: 800 },
  slotState: { fontSize: 11, fontWeight: 600 },
  legend: { fontSize: 11, color: "#888", margin: "8px 0 0" },
  confirm: {
    marginTop: 12,
    padding: 14,
    border: "1px solid #124096",
    borderRadius: 10,
    background: "#f5f8ff",
    display: "flex",
    flexDirection: "column",
    gap: 8,
    fontSize: 14,
  },
  confirmWhen: { fontSize: 13, color: "#444" },
  confirmActions: { display: "flex", justifyContent: "flex-end", gap: 8 },
  input: {
    width: "100%",
    padding: "8px 10px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  bookButton: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.green,
    cursor: "pointer",
  },
  buttonDisabled: { background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  secondaryButton: {
    padding: "8px 12px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    cursor: "pointer",
  },
  cancelButton: {
    padding: "8px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #de0b12",
    borderRadius: 6,
    background: "#fff",
    color: "#de0b12",
    cursor: "pointer",
  },
};

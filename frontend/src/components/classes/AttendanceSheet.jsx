import { useCallback, useEffect, useState } from "react";
import { addWalkIn, fetchAttendance, markAttendance } from "../../api/classes.js";

// User story (SCRUM-36): "As a coach, I want to mark attendance for my
// classes, so that the system keeps accurate participation records."
//
// Opened from the coach's My Schedule and from a branch manager's class
// details. The server decides who may mark and until when (the coach until 24
// hours after the class ends, a branch manager any time after it starts); this
// sheet just shows the reason when marking is closed.
export default function AttendanceSheet({ classId, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [walkInId, setWalkInId] = useState("");
  const [walkInError, setWalkInError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    return fetchAttendance(classId)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [classId]);

  useEffect(() => {
    load();
  }, [load]);

  async function mark(entry, attendance) {
    setBusyId(entry.bookingId);
    setError(null);
    try {
      setData(await markAttendance(classId, entry.bookingId, attendance));
      setNotice(`${entry.memberName}: ${attendance}.`);
      onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function submitWalkIn(e) {
    e.preventDefault();
    setWalkInError(null);
    setBusyId("walk-in");
    try {
      const body = await addWalkIn(classId, walkInId.trim());
      setData(body);
      const added = body.roster.find((r) => String(r.memberId) === walkInId.trim());
      setNotice(`${added ? added.memberName : "Walk-in"} added as attended.`);
      setWalkInId("");
      onChanged?.();
    } catch (err) {
      setWalkInError(err.fieldErrors?.memberId?.[0] || err.message);
    } finally {
      setBusyId(null);
    }
  }

  const c = data?.class;
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Attendance">
        <div style={styles.header}>
          <div>
            <h2 style={styles.title}>Attendance{c ? ` · ${c.name}` : ""}</h2>
            {c && (
              <p style={styles.subtitle}>
                {c.date} · {c.startTime}–{c.endTime} · {c.branch}
                {c.room ? ` · ${c.room}` : ""}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {error && <div style={styles.errorBox}>{error}</div>}
        {notice && <div style={styles.successBox}>{notice}</div>}
        {!data && !error && <p style={styles.muted}>Loading...</p>}

        {data && (
          <>
            <div style={styles.counts}>
              <Count label="Attended" value={data.counts.attended} color="#0f6e2b" />
              <Count label="No-show" value={data.counts.noShows} color="#b3261e" />
              <Count label="Not marked" value={data.counts.unmarked} color="#555" />
              <Count label="Walk-ins" value={data.counts.walkIns} color="#124096" />
            </div>

            {!data.canMark && <div style={styles.lockBox}>{data.cannotMarkReason}</div>}
            {data.canMark && !data.isManager && (
              <p style={styles.muted}>You can change marks until {data.coachWindowClosesAt}.</p>
            )}

            {data.roster.length === 0 ? (
              <p style={styles.muted}>No one is booked into this class.</p>
            ) : (
              <ul style={styles.list}>
                {data.roster.map((entry) => (
                  <li key={entry.bookingId} style={styles.row}>
                    <div style={styles.who}>
                      <span style={styles.name}>{entry.memberName}</span>
                      <span style={styles.meta}>
                        #{entry.memberId}
                        {entry.walkIn ? " · walk-in" : ""}
                        {entry.markedBy ? ` · marked by ${entry.markedBy}` : entry.attendance ? " · from check-ins" : ""}
                      </span>
                    </div>
                    <div role="radiogroup" aria-label={`Attendance for ${entry.memberName}`} style={styles.toggle}>
                      {["Attended", "No-show"].map((option) => {
                        const selected = entry.attendance === option;
                        return (
                          <button
                            key={option}
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            disabled={!data.canMark || busyId === entry.bookingId}
                            onClick={() => mark(entry, option)}
                            style={{
                              ...styles.option,
                              ...(selected ? (option === "Attended" ? styles.attended : styles.noShow) : null),
                              ...(!data.canMark ? styles.optionDisabled : null),
                            }}
                          >
                            {option}
                          </button>
                        );
                      })}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {data.canMark && (
              <form onSubmit={submitWalkIn} style={styles.walkIn}>
                <label htmlFor="walk-in-id" style={styles.walkInLabel}>
                  Add a walk-in (came without booking)
                </label>
                <div style={styles.walkInRow}>
                  <input
                    id="walk-in-id"
                    value={walkInId}
                    onChange={(e) => setWalkInId(e.target.value)}
                    placeholder="Membership ID"
                    inputMode="numeric"
                    style={styles.input}
                  />
                  <button type="submit" disabled={!walkInId.trim() || busyId === "walk-in"} style={styles.primaryButton}>
                    {busyId === "walk-in" ? "Adding..." : "Add walk-in"}
                  </button>
                </div>
                {walkInError && <span style={styles.fieldError}>{walkInError}</span>}
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Count({ label, value, color }) {
  return (
    <div style={styles.count}>
      <span style={{ ...styles.countValue, color }}>{value}</span>
      <span style={styles.countLabel}>{label}</span>
    </div>
  );
}

const styles = {
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    zIndex: 50,
  },
  modal: {
    background: "#fff",
    borderRadius: 14,
    padding: 22,
    width: "100%",
    maxWidth: 560,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  muted: { fontSize: 13, color: "#777", margin: "6px 0 10px" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  lockBox: { background: "#f1f1f4", color: "#444", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  counts: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8, marginBottom: 12 },
  count: { display: "flex", flexDirection: "column", alignItems: "center", padding: "8px 4px", borderRadius: 10, background: "#f6f6f8" },
  countValue: { fontSize: 22, fontWeight: 800 },
  countLabel: { fontSize: 11, fontWeight: 700, color: "#666", textTransform: "uppercase", letterSpacing: 0.3 },
  list: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10 },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "10px 12px",
    borderBottom: "1px solid #f0f0f2",
    flexWrap: "wrap",
  },
  who: { display: "flex", flexDirection: "column", minWidth: 0 },
  name: { fontSize: 14, fontWeight: 700 },
  meta: { fontSize: 12, color: "#777" },
  toggle: { display: "flex", gap: 6 },
  option: {
    height: 34,
    padding: "0 12px",
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    fontSize: 13,
    fontWeight: 700,
    color: "#444",
    cursor: "pointer",
  },
  attended: { background: "#e3f5e8", borderColor: "#0f6e2b", color: "#0f6e2b", boxShadow: "inset 0 0 0 1px #0f6e2b" },
  noShow: { background: "#fdeceb", borderColor: "#b3261e", color: "#b3261e", boxShadow: "inset 0 0 0 1px #b3261e" },
  optionDisabled: { cursor: "default", opacity: 0.75 },
  walkIn: { marginTop: 14, display: "flex", flexDirection: "column", gap: 6 },
  walkInLabel: { fontSize: 13, fontWeight: 700 },
  walkInRow: { display: "flex", gap: 8 },
  input: { flex: 1, height: 38, padding: "0 12px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, minWidth: 0 },
  primaryButton: {
    height: 38,
    padding: "0 16px",
    border: "none",
    borderRadius: 8,
    background: "#124096",
    color: "#fff",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
  },
  fieldError: { fontSize: 12, color: "#b3261e" },
};

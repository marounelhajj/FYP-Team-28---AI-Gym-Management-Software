import { useCallback, useEffect, useState } from "react";
import { cancelMyBooking, cancelMyPtSession, fetchMyClasses } from "../../api/classes.js";
import { formatDay } from "../classes/dates.js";

// Everything the member has coming up - class spots and private sessions - in
// one list, soonest first, each with a Cancel button until it starts.

const REFRESH_MS = 30000;

export default function MyBookings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    return fetchMyClasses()
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function cancel(item) {
    setBusyKey(item.key);
    setError(null);
    try {
      if (item.kind === "class") await cancelMyBooking(item.id);
      else await cancelMyPtSession(item.id);
      setNotice(`${item.title} on ${formatDay(item.date)} at ${item.startTime} was cancelled.`);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyKey(null);
    }
  }

  if (error && !data) return <div style={styles.errorBox}>Couldn&apos;t load your bookings: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading...</p>;

  const items = [
    ...data.upcoming.map((c) => ({
      kind: "class", key: `class-${c.id}`, id: c.id, title: c.name, date: c.date, startTime: c.startTime,
      endTime: c.endTime, coach: c.coachName, where: c.room, state: c.state,
    })),
    ...data.upcomingPt.map((s) => ({
      kind: "pt", key: `pt-${s.id}`, id: s.id, title: "Private training", date: s.date, startTime: s.startTime,
      endTime: s.endTime, coach: s.coachName, where: s.note, state: s.state,
    })),
  ].sort((a, b) => `${a.date} ${a.startTime}`.localeCompare(`${b.date} ${b.startTime}`));

  return (
    <div>
      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}
      {items.length === 0 ? (
        <div style={styles.empty}>Nothing booked yet - reserve a class or a private session.</div>
      ) : (
        <ul style={styles.list}>
          {items.map((item) => (
            <li key={item.key} style={styles.row}>
              <span style={item.kind === "pt" ? styles.ptTag : styles.classTag}>{item.kind === "pt" ? "Private" : "Class"}</span>
              <span style={styles.body}>
                <strong>{item.title}</strong>
                <span style={styles.meta}>
                  {formatDay(item.date)} · {item.startTime}–{item.endTime} · {item.coach}
                  {item.where ? ` · ${item.where}` : ""}
                </span>
              </span>
              {item.state === "upcoming" ? (
                <button type="button" onClick={() => cancel(item)} disabled={busyKey === item.key} style={styles.cancelButton}>
                  {busyKey === item.key ? "..." : "Cancel"}
                </button>
              ) : (
                <span style={styles.liveTag}>In progress</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <p style={styles.muted}>Times are Beirut time. A booking can be cancelled until it starts.</p>
    </div>
  );
}

const styles = {
  muted: { fontSize: 12, color: "#888", margin: "8px 0" },
  empty: { padding: 14, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  list: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  row: { display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderBottom: "1px solid #f0f0f3", fontSize: 13 },
  body: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  meta: { fontSize: 12, color: "#666" },
  classTag: { fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "#eef2fa", color: "#124096" },
  ptTag: { fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  liveTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  cancelButton: {
    flexShrink: 0,
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #de0b12",
    borderRadius: 6,
    background: "#fff",
    color: "#de0b12",
    cursor: "pointer",
  },
};

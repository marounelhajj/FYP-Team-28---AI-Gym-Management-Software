import { useEffect, useState } from "react";
import { fetchClientHealth } from "../../api/health.js";
import { fetchClientLog, fetchMyClients } from "../../api/progress.js";
import { BADGE_TONES, MemberHealth, healthBadge } from "../health/HealthViews.jsx";
import ClientProgress from "../coaching/ClientProgress.jsx";
import { MetricList, WorkoutList } from "./TrainingLogViews.jsx";

// SCRUM-60, the coach's side: the members they coach (booked private
// training with them) and each one's self-logged workouts and body metrics,
// read-only. The server only ever returns members assigned to this coach.
//
// Each client's health notes come first ("As a coach, I want to view a
// client's health restrictions and injuries before starting a session, so
// that I can adapt the workout safely") - shown only while the client has a
// recent or upcoming session with this coach.
//
// Then their development ("As a coach, I want to log client workout sessions
// and progress notes, so that I can track each client's development over
// time"): goals, strength, body weight, attendance and session notes -
// see ../coaching/ClientProgress.jsx.
export default function MyClients() {
  const [clients, setClients] = useState(null);
  const [selected, setSelected] = useState(null);
  const [log, setLog] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchMyClients()
      .then((b) => {
        setClients(b.results);
        if (b.results.length) setSelected(b.results[0].memberId);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLog(null);
    setHealth(null);
    fetchClientLog(selected).then(setLog).catch((e) => setError(e.message));
    // Not an error when it's refused: the last session was just too long ago.
    fetchClientHealth(selected)
      .then((b) => setHealth({ member: b.member }))
      .catch((e) => setHealth({ unavailable: e.message }));
  }, [selected]);

  const badgeFor = (c) => healthBadge(c.health);

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>My Clients</h1>
      <p style={styles.subtitle}>Your private-training clients: health notes, goals and progress, your session notes, and what they log themselves.</p>
      {error && <div style={styles.errorBox}>{error}</div>}
      {clients && clients.length === 0 && <div style={styles.empty}>No private-training clients yet.</div>}
      {clients && clients.length > 0 && (
        <div style={styles.layout}>
          <ul style={styles.clientList} aria-label="Clients">
            {clients.map((c) => (
              <li key={c.memberId}>
                <button
                  type="button"
                  onClick={() => setSelected(c.memberId)}
                  aria-current={selected === c.memberId}
                  style={{ ...styles.client, ...(selected === c.memberId ? styles.clientSelected : null) }}
                >
                  <span style={styles.clientName}>{c.name}</span>
                  <span style={styles.clientMeta}>
                    {c.workouts} workout{c.workouts === 1 ? "" : "s"}
                    {c.lastWorkout ? ` · last ${c.lastWorkout}` : ""}
                  </span>
                  {badgeFor(c) && (
                    <span style={{ ...styles.healthBadge, ...BADGE_TONES[badgeFor(c).tone] }}>{badgeFor(c).text}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <section style={styles.detail} aria-label="Training log">
            {!log && <p style={styles.muted}>Loading...</p>}
            {log && (
              <>
                <div style={styles.detailHeader}>
                  <h2 style={styles.detailTitle}>{log.member.name}</h2>
                </div>
                <h3 style={styles.section}>Health &amp; injuries</h3>
                {!health && <p style={styles.muted}>Loading...</p>}
                {health?.member && <MemberHealth member={health.member} />}
                {health?.unavailable && <p style={styles.muted}>{health.unavailable}</p>}
                <h2 style={styles.part}>Progress</h2>
                <ClientProgress memberId={selected} />
                <h2 style={styles.part}>
                  Logged by {log.member.name.split(" ")[0]} <span style={styles.readOnly}>Read-only</span>
                </h2>
                <h3 style={styles.section}>Body measurements</h3>
                <MetricList metrics={log.metrics.slice(0, 5)} />
                <h3 style={styles.section}>Their own workouts</h3>
                <WorkoutList workouts={log.workouts.slice(0, 12)} />
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1000, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 16px" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 12, fontSize: 14, color: "#888", textAlign: "center" },
  muted: { fontSize: 13, color: "#888" },
  layout: { display: "grid", gridTemplateColumns: "minmax(200px, 260px) 1fr", gap: 16, alignItems: "start" },
  clientList: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  client: {
    width: "100%", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, padding: "10px 12px",
    border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit",
  },
  clientSelected: { borderColor: "#124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  clientName: { fontSize: 14, fontWeight: 700 },
  clientMeta: { fontSize: 12, color: "#666" },
  healthBadge: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, marginTop: 2 },
  detail: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff", minWidth: 0 },
  detailHeader: { display: "flex", alignItems: "center", gap: 10 },
  detailTitle: { fontSize: 18, fontWeight: 800, margin: 0 },
  readOnly: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: "#ececf0", color: "#555" },
  section: { fontSize: 14, fontWeight: 800, margin: "16px 0 8px" },
  part: { display: "flex", alignItems: "center", gap: 8, fontSize: 16, fontWeight: 800, margin: "22px 0 0", paddingTop: 14, borderTop: "1px solid #ececf0" },
};

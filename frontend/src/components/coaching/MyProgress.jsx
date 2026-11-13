import { useEffect, useState } from "react";
import { fetchMyProgress } from "../../api/coaching.js";
import { AttendanceTiles, BodyWeightPanel, GoalCard, LogTimeline, StrengthPanel } from "./ProgressViews.jsx";

// The member's own development, on their dashboard: the goals their coach set
// with them, strength and body weight over time (from their coach's session
// logs and their own training log), attendance, and what their coach wrote
// after each session - how they felt, what they did, the plan. The coach's
// private assessment isn't sent to the member at all.
export default function MyProgress() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchMyProgress().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div style={styles.errorBox}>Couldn&apos;t load your progress: {error}</div>;
  if (!data) return <p style={styles.muted}>Loading...</p>;

  const nothingYet = data.goals.length === 0 && data.logs.length === 0 && data.strength.length === 0 && data.bodyWeight.length === 0;
  if (nothingYet) {
    return (
      <div style={styles.card}>
        <p style={styles.muted}>
          Nothing to show yet. Your coach&apos;s notes and goals appear here after your private training sessions, along with
          your strength and weight from your training log.
        </p>
      </div>
    );
  }
  const active = data.goals.filter((g) => g.status === "Active");
  return (
    <section style={styles.card} aria-label="My progress">
      <h3 style={styles.section}>Goals</h3>
      {active.length === 0 ? (
        <p style={styles.muted}>No active goals - ask your coach to set one with you.</p>
      ) : (
        <ul style={styles.goals}>
          {active.map((g) => (
            <GoalCard key={g.id} goal={g} />
          ))}
        </ul>
      )}
      <h3 style={styles.section}>Strength</h3>
      <StrengthPanel strength={data.strength} />
      <h3 style={styles.section}>Body weight</h3>
      <BodyWeightPanel weights={data.bodyWeight} />
      <h3 style={styles.section}>Attendance</h3>
      <AttendanceTiles attendance={data.attendance} />
      <h3 style={styles.section}>From your coach ({data.logCount})</h3>
      <LogTimeline logs={data.logs.slice(0, 5)} />
    </section>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  section: { fontSize: 14, fontWeight: 800, margin: "14px 0 8px" },
  goals: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  muted: { fontSize: 13, color: "#888", margin: 0, lineHeight: 1.5 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
};

import { useCallback, useEffect, useState } from "react";
import { addClientGoal, fetchClientProgress, updateClientGoal } from "../../api/coaching.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import SessionLogForm from "./SessionLogForm.jsx";
import { AttendanceTiles, BodyWeightPanel, GoalCard, LogTimeline, StrengthPanel } from "./ProgressViews.jsx";

// The coach's view of one client's development (inside My Clients): goals
// with their progress, strength per exercise, body weight, attendance, and
// every session's notes from every coach who trains them.
//
// User story: "As a coach, I want to log client workout sessions and progress
// notes, so that I can track each client's development over time."

function plusMonths(months) {
  const d = new Date();
  d.setMonth(d.getMonth() + months);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ClientProgress({ memberId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [goalForm, setGoalForm] = useState(null);
  const [goalErrors, setGoalErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const [showClosed, setShowClosed] = useState(false);

  const load = useCallback(() => {
    return fetchClientProgress(memberId)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [memberId]);

  useEffect(() => {
    setData(null);
    setGoalForm(null);
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(t);
  }, [notice]);

  async function submitGoal(e) {
    e.preventDefault();
    setBusy(true);
    setGoalErrors({});
    try {
      await addClientGoal(memberId, { ...goalForm, targetValue: goalForm.targetValue === "" ? null : goalForm.targetValue });
      setGoalForm(null);
      setNotice("Goal added.");
      load();
    } catch (err) {
      setGoalErrors(err.fieldErrors || { general: [err.message] });
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(goal, status) {
    setError(null);
    try {
      await updateClientGoal(goal.id, { status });
      setNotice(status === "Active" ? "Goal reopened." : `Goal marked ${status.toLowerCase()}.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (error && !data) return <div style={styles.errorBox}>{error}</div>;
  if (!data) return <p style={styles.muted}>Loading progress...</p>;

  const active = data.goals.filter((g) => g.status === "Active");
  const closed = data.goals.filter((g) => g.status !== "Active");
  const goalError = (f) => goalErrors[f] && <span style={styles.fieldError}>{goalErrors[f][0]}</span>;
  const set = (f) => (e) => setGoalForm({ ...goalForm, [f]: e.target.value });

  return (
    <div>
      {notice && <div style={styles.successBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <div style={styles.sectionHead}>
        <h3 style={styles.section}>Goals</h3>
        {!goalForm && active.length < data.maxActiveGoals && (
          <button
            type="button"
            onClick={() => setGoalForm({ kind: "strength", exercise: data.strength[0]?.exercise || "Squat", targetValue: "", targetDate: plusMonths(3), title: "", note: "" })}
            style={styles.primaryButton}
          >
            + Add goal
          </button>
        )}
      </div>
      {goalForm && (
        <form onSubmit={submitGoal} style={styles.goalForm} aria-label="New goal">
          <label style={styles.field}>
            <span style={styles.label}>Type</span>
            <select value={goalForm.kind} onChange={set("kind")} style={styles.input}>
              {data.goalKinds.map((k) => (
                <option key={k.value} value={k.value}>{k.label}</option>
              ))}
            </select>
          </label>
          <div style={styles.formRow}>
            {goalForm.kind === "strength" && (
              <label style={styles.field}>
                <span style={styles.label}>Exercise</span>
                <input value={goalForm.exercise} onChange={set("exercise")} list="goal-exercises" style={styles.input} />
                <datalist id="goal-exercises">
                  {data.exerciseChoices.filter((c) => c.kind === "strength").map((c) => (
                    <option key={c.name} value={c.name} />
                  ))}
                </datalist>
                {goalError("exercise")}
              </label>
            )}
            {goalForm.kind !== "custom" && (
              <label style={styles.field}>
                <span style={styles.label}>{goalForm.kind === "strength" ? "Target 1-rep max (kg)" : "Target body weight (kg)"}</span>
                <input type="number" step="0.5" value={goalForm.targetValue} onChange={set("targetValue")} style={styles.input} />
                {goalError("targetValue")}
              </label>
            )}
            <label style={styles.field}>
              <span style={styles.label}>By</span>
              <input type="date" value={goalForm.targetDate} onChange={set("targetDate")} style={styles.input} />
              {goalError("targetDate")}
            </label>
          </div>
          <label style={styles.field}>
            <span style={styles.label}>{goalForm.kind === "custom" ? "Goal" : "Name (optional - filled in for you)"}</span>
            <input value={goalForm.title} onChange={set("title")} maxLength={120} placeholder={goalForm.kind === "custom" ? 'e.g. "Run 5 km without stopping"' : ""} style={styles.input} />
            {goalError("title")}
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Note (optional)</span>
            <input value={goalForm.note} onChange={set("note")} maxLength={300} style={styles.input} />
          </label>
          {goalErrors.general && <div style={styles.errorBox}>{goalErrors.general[0]}</div>}
          <p style={styles.hint}>
            {goalForm.kind === "custom"
              ? "You mark this one achieved yourself."
              : "Progress is worked out from what's logged - by you, other coaches, and the client."}
          </p>
          <div style={styles.actions}>
            <button type="button" onClick={() => setGoalForm(null)} style={styles.secondaryButton} disabled={busy}>Cancel</button>
            <button type="submit" style={styles.primaryButton} disabled={busy}>{busy ? "Saving..." : "Add goal"}</button>
          </div>
        </form>
      )}
      {active.length === 0 && !goalForm && <div style={styles.empty}>No active goals. Set a measurable target with a date.</div>}
      <ul style={styles.goals}>
        {active.map((g) => (
          <GoalCard
            key={g.id}
            goal={g}
            actions={
              <div style={styles.goalActions}>
                <button type="button" onClick={() => setStatus(g, "Achieved")} style={g.reached || g.kind === "custom" ? styles.greenButton : styles.smallButton} aria-label={`Mark ${g.title} achieved`}>
                  Mark achieved
                </button>
                <button type="button" onClick={() => setStatus(g, "Dropped")} style={styles.smallButton} aria-label={`Drop ${g.title}`}>
                  Drop
                </button>
              </div>
            }
          />
        ))}
      </ul>
      {closed.length > 0 && (
        <>
          <button type="button" onClick={() => setShowClosed((s) => !s)} style={styles.linkButton} aria-expanded={showClosed}>
            {showClosed ? "Hide" : "Show"} past goals ({closed.length})
          </button>
          {showClosed && (
            <ul style={{ ...styles.goals, marginTop: 6 }}>
              {closed.map((g) => (
                <GoalCard
                  key={g.id}
                  goal={g}
                  actions={
                    <div style={styles.goalActions}>
                      <button type="button" onClick={() => setStatus(g, "Active")} style={styles.smallButton}>Reopen</button>
                    </div>
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}

      <h3 style={styles.section}>Strength</h3>
      <StrengthPanel strength={data.strength} />

      <h3 style={styles.section}>Body weight</h3>
      <BodyWeightPanel weights={data.bodyWeight} />

      <h3 style={styles.section}>Attendance</h3>
      <AttendanceTiles attendance={data.attendance} />

      <h3 style={styles.section}>Session notes ({data.logCount})</h3>
      <LogTimeline logs={data.logs} onOpen={(log) => setEditing(log.sessionId)} />

      {editing && (
        <SessionLogForm
          sessionId={editing}
          onClose={() => {
            setEditing(null);
            load();
          }}
          onSaved={setNotice}
        />
      )}
    </div>
  );
}

const styles = {
  muted: { fontSize: 13, color: "#888" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 8 },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 8 },
  empty: { padding: 14, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  sectionHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, margin: "16px 0 8px" },
  section: { fontSize: 14, fontWeight: 800, margin: "16px 0 8px" },
  goals: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  goalActions: { display: "flex", gap: 6, marginTop: 4 },
  goalForm: { display: "flex", flexDirection: "column", gap: 8, padding: 12, border: "1px solid #dfe5f2", borderRadius: 10, background: "#f7f9fd", marginBottom: 8 },
  formRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 140 },
  label: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", boxSizing: "border-box", width: "100%" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  hint: { fontSize: 12, color: "#777", margin: 0 },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8 },
  primaryButton: { padding: "7px 12px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  greenButton: { padding: "5px 10px", fontSize: 12, fontWeight: 700, border: "none", borderRadius: 6, ...BUTTON_COLORS.green, cursor: "pointer" },
  secondaryButton: { padding: "7px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  smallButton: { padding: "5px 10px", fontSize: 12, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 6, background: "#f5f5f7", cursor: "pointer" },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer", padding: 0, marginTop: 6 },
};

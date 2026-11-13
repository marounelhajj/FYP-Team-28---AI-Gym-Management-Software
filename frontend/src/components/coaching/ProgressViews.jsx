import { useState } from "react";

// Read-only pieces for a client's development over time, shared by the
// coach's view of a client and the member's own "My progress":
// strength per exercise (estimated 1-rep max), body weight, goals with their
// progress, attendance, and the timeline of session notes.

export function formatDay(iso, withYear = false) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: withYear ? "numeric" : undefined,
  });
}

export function exerciseSummary(e) {
  if (e.kind === "cardio") {
    return [e.durationMinutes && `${e.durationMinutes} min`, e.distanceKm && `${Number(e.distanceKm)} km`].filter(Boolean).join(" · ");
  }
  return `${e.sets} × ${e.reps}${e.weightKg ? ` @ ${Number(e.weightKg)} kg` : ""}`;
}

// A line over time. points: [{date, value, label?, highlight?}] oldest first.
export function LineChart({ points, unit, label, color = "#124096" }) {
  if (points.length < 2) {
    return <div style={styles.empty}>Two or more entries are needed for a chart.</div>;
  }
  const W = 520;
  const H = 180;
  const pad = { l: 44, r: 14, t: 14, b: 26 };
  const values = points.map((p) => p.value);
  const spread = Math.max(...values) - Math.min(...values);
  const min = Math.floor(Math.min(...values) - Math.max(1, spread * 0.1));
  const max = Math.ceil(Math.max(...values) + Math.max(1, spread * 0.1));
  const x = (i) => pad.l + (i * (W - pad.l - pad.r)) / (points.length - 1);
  const y = (v) => pad.t + ((max - v) * (H - pad.t - pad.b)) / (max - min || 1);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={styles.chart}>
      {[min, (min + max) / 2, max].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="#ececf0" />
          <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#777">
            {Math.round(v)}
          </text>
        </g>
      ))}
      <path d={path} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={`${p.date}-${i}`} cx={x(i)} cy={y(p.value)} r={p.highlight ? 6 : 4} fill={p.highlight ? "#e8a600" : "#fff"} stroke={p.highlight ? "#a87700" : color} strokeWidth="2">
          <title>{`${formatDay(p.date, true)}: ${p.value} ${unit}${p.label ? ` (${p.label})` : ""}`}</title>
        </circle>
      ))}
      <text x={pad.l} y={H - 6} fontSize="11" fill="#777">{formatDay(points[0].date)}</text>
      <text x={W - pad.r} y={H - 6} fontSize="11" fill="#777" textAnchor="end">{formatDay(points[points.length - 1].date)}</text>
    </svg>
  );
}

export function StrengthPanel({ strength }) {
  const [selected, setSelected] = useState(null);
  if (strength.length === 0) {
    return <div style={styles.empty}>No weighted lifts logged yet. Log sets with a weight to see strength progress.</div>;
  }
  const current = strength.find((s) => s.exercise === selected) || strength[0];
  const change = Number(current.change);
  return (
    <div>
      <div style={styles.chipRow} role="tablist" aria-label="Exercise">
        {strength.slice(0, 8).map((s) => (
          <button
            key={s.exercise}
            type="button"
            role="tab"
            aria-selected={s.exercise === current.exercise}
            onClick={() => setSelected(s.exercise)}
            style={{ ...styles.chip, ...(s.exercise === current.exercise ? styles.chipActive : null) }}
          >
            {s.exercise}
          </button>
        ))}
      </div>
      <div style={styles.statRow}>
        <Stat label="Best estimated 1RM" value={`${Number(current.best)} kg`} />
        <Stat label="Latest" value={`${Number(current.latest)} kg`} />
        <Stat
          label="Change since first"
          value={`${change >= 0 ? "+" : ""}${change} kg`}
          tone={change > 0 ? "#0f6e2b" : change < 0 ? "#b3261e" : undefined}
        />
        <Stat label="Personal records" value={current.records} />
      </div>
      <LineChart
        unit="kg"
        label={`${current.exercise} estimated 1-rep max over time`}
        points={current.points.map((p) => ({ date: p.date, value: Number(p.e1rm), label: `${p.bestSet}${p.record ? ", personal record" : ""}`, highlight: p.record }))}
      />
      <p style={styles.hint}>
        Estimated 1-rep max = weight × (1 + reps ÷ 30), from the best set of each day (sets of up to 12 reps). Gold dots are personal records.
      </p>
    </div>
  );
}

export function BodyWeightPanel({ weights }) {
  if (weights.length === 0) return <div style={styles.empty}>No body weight recorded yet.</div>;
  const first = Number(weights[0].kg);
  const last = Number(weights[weights.length - 1].kg);
  return (
    <div>
      <LineChart unit="kg" color="#129638" label="Body weight over time" points={weights.map((w) => ({ date: w.date, value: Number(w.kg), label: w.source === "coach" ? "measured by coach" : "self-logged" }))} />
      <p style={styles.hint}>
        {weights.length === 1
          ? `${last} kg on ${formatDay(weights[0].date, true)}.`
          : `${first} kg → ${last} kg (${last - first >= 0 ? "+" : ""}${(last - first).toFixed(1)} kg) since ${formatDay(weights[0].date, true)}.`}
      </p>
    </div>
  );
}

export function AttendanceTiles({ attendance }) {
  const rate = (a) => (a.booked ? `${Math.round((a.attended / a.booked) * 100)}%` : "—");
  return (
    <div style={styles.statRow}>
      <Stat label={`Private sessions, last ${attendance.days} days`} value={`${attendance.privateSessions.attended} of ${attendance.privateSessions.booked}`} sub={`${rate(attendance.privateSessions)} attended`} />
      <Stat label={`Classes, last ${attendance.days} days`} value={`${attendance.classes.attended} of ${attendance.classes.booked}`} sub={`${rate(attendance.classes)} attended`} />
    </div>
  );
}

function Stat({ label, value, sub, tone }) {
  return (
    <div style={styles.stat}>
      <span style={styles.statLabel}>{label}</span>
      <span style={{ ...styles.statValue, ...(tone ? { color: tone } : null) }}>{value}</span>
      {sub && <span style={styles.statSub}>{sub}</span>}
    </div>
  );
}

const STATUS_TONES = {
  Achieved: { background: "#e3f5e8", color: "#0f6e2b" },
  Dropped: { background: "#ececf0", color: "#555" },
};

// One goal with its progress bar. `actions` renders the coach's buttons.
export function GoalCard({ goal, actions }) {
  const active = goal.status === "Active";
  return (
    <li style={{ ...styles.goal, ...(active ? null : styles.goalClosed) }}>
      <div style={styles.goalHead}>
        <span style={styles.goalTitle}>{goal.title}</span>
        {active ? (
          goal.reached ? (
            <span style={{ ...styles.tag, background: "#e3f5e8", color: "#0f6e2b" }}>Target reached</span>
          ) : goal.overdue ? (
            <span style={{ ...styles.tag, background: "#fdeceb", color: "#b3261e" }}>Past target date</span>
          ) : (
            <span style={styles.tagMuted}>{goal.daysLeft} day{goal.daysLeft === 1 ? "" : "s"} left</span>
          )
        ) : (
          <span style={{ ...styles.tag, ...STATUS_TONES[goal.status] }}>{goal.status}</span>
        )}
      </div>
      {goal.kind !== "custom" && (
        <>
          <div style={styles.bar} role="progressbar" aria-valuenow={goal.percent ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label={`${goal.title} progress`}>
            <div style={{ ...styles.barFill, width: `${goal.percent ?? 0}%`, ...(goal.reached ? styles.barDone : null) }} />
          </div>
          <span style={styles.goalMeta}>
            {goal.current ? `Now ${Number(goal.current)} kg` : "No measurement since it was set"}
            {goal.start && ` · started at ${Number(goal.start)} kg`} · target {Number(goal.target)} kg
            {goal.percent !== null && ` · ${goal.percent}%`}
          </span>
        </>
      )}
      <span style={styles.goalMeta}>
        By {formatDay(goal.targetDate, true)}
        {goal.setBy && ` · set by ${goal.setBy}`}
        {goal.closedOn && ` · ${goal.status.toLowerCase()} ${formatDay(goal.closedOn, true)}`}
      </span>
      {goal.note && <span style={styles.goalNote}>{goal.note}</span>}
      {actions}
    </li>
  );
}

const SOAP = [
  ["subjective", "How they felt"],
  ["objective", "What was done / measured"],
  ["assessment", "Coach's assessment"],
  ["plan", "Plan for next time"],
];

// Session notes, newest first. The member's copy simply has no assessment.
export function LogTimeline({ logs, onOpen }) {
  if (logs.length === 0) return <div style={styles.empty}>No sessions logged yet.</div>;
  return (
    <ol style={styles.timeline}>
      {logs.map((log) => (
        <li key={log.id} style={styles.entry}>
          <div style={styles.entryHead}>
            <span style={styles.entryDate}>
              {formatDay(log.date, true)} · {log.startTime}–{log.endTime}
            </span>
            <span style={styles.entryCoach}>
              {log.coachName}
              {log.sessionRpe ? ` · effort ${log.sessionRpe}/10` : ""}
              {log.bodyWeightKg ? ` · ${Number(log.bodyWeightKg)} kg` : ""}
            </span>
            {onOpen && log.canEdit && (
              <button type="button" onClick={() => onOpen(log)} style={styles.linkButton}>
                Edit
              </button>
            )}
          </div>
          {log.exercises.length > 0 && (
            <ul style={styles.exerciseList}>
              {log.exercises.map((e, i) => (
                <li key={i} style={styles.exercise}>
                  <strong>{e.exercise}</strong> {exerciseSummary(e)}
                  {e.rpe ? ` · RPE ${e.rpe}` : ""}
                  {e.note && <span style={styles.exerciseNote}> · {e.note}</span>}
                </li>
              ))}
            </ul>
          )}
          {SOAP.filter(([key]) => log[key]).map(([key, label]) => (
            <p key={key} style={key === "assessment" ? styles.privateNote : styles.note}>
              <span style={styles.noteLabel}>{label}{key === "assessment" ? " (coaches only)" : ""}:</span> {log[key]}
            </p>
          ))}
        </li>
      ))}
    </ol>
  );
}

export const styles = {
  empty: { padding: 14, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  chart: { width: "100%", height: "auto", display: "block" },
  hint: { fontSize: 12, color: "#777", margin: "4px 0 0", lineHeight: 1.45 },
  chipRow: { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 },
  chip: { padding: "5px 10px", fontSize: 12, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 999, background: "#fff", cursor: "pointer" },
  chipActive: { background: "#124096", borderColor: "#124096", color: "#fff" },
  statRow: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8, marginBottom: 10 },
  stat: { display: "flex", flexDirection: "column", gap: 2, padding: "8px 10px", borderRadius: 10, background: "#f6f6f8" },
  statLabel: { fontSize: 11, fontWeight: 600, color: "#666" },
  statValue: { fontSize: 18, fontWeight: 800 },
  statSub: { fontSize: 11, color: "#777" },
  goal: { display: "flex", flexDirection: "column", gap: 5, padding: "10px 12px", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  goalClosed: { background: "#f7f7f9", color: "#66666e" },
  goalHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 },
  goalTitle: { fontSize: 14, fontWeight: 700, minWidth: 0, overflowWrap: "anywhere" },
  goalMeta: { fontSize: 12, color: "#666" },
  goalNote: { fontSize: 12, color: "#444", fontStyle: "italic" },
  tag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4 },
  tagMuted: { flexShrink: 0, fontSize: 11, color: "#666" },
  bar: { height: 8, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  barFill: { height: "100%", background: "#124096", borderRadius: 999 },
  barDone: { background: "#129638" },
  timeline: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  entry: { padding: "10px 12px", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  entryHead: { display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 4 },
  entryDate: { fontSize: 13, fontWeight: 700 },
  entryCoach: { fontSize: 12, color: "#666", flex: 1 },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 12, fontWeight: 700, cursor: "pointer", padding: 0 },
  exerciseList: { listStyle: "none", margin: "0 0 6px", padding: 0, display: "flex", flexDirection: "column", gap: 2 },
  exercise: { fontSize: 13 },
  exerciseNote: { color: "#777" },
  note: { fontSize: 13, margin: "2px 0", lineHeight: 1.45 },
  privateNote: { fontSize: 13, margin: "2px 0", lineHeight: 1.45, background: "#f3ecfb", padding: "4px 8px", borderRadius: 6 },
  noteLabel: { fontWeight: 700, color: "#444" },
};

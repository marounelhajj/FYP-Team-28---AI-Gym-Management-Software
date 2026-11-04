// Read-only pieces shared by the member's own training log and the coach's
// view of a client (SCRUM-60): the workout list and the body-weight chart.

export function workoutSummary(w) {
  if (w.kind === "cardio") {
    return [w.durationMinutes && `${w.durationMinutes} min`, w.distanceKm && `${Number(w.distanceKm)} km`].filter(Boolean).join(" · ");
  }
  return `${w.sets} × ${w.reps}${w.weightKg ? ` @ ${Number(w.weightKg)} kg` : ""}`;
}

export function WorkoutList({ workouts, renderActions }) {
  if (workouts.length === 0) return <div style={styles.empty}>No workouts logged yet.</div>;
  return (
    <ul style={styles.list}>
      {workouts.map((w) => (
        <li key={w.id} style={styles.row}>
          <div style={styles.rowMain}>
            <span style={styles.rowTitle}>{w.exercise}</span>
            <span style={styles.rowMeta}>
              {w.date} · {workoutSummary(w)}
            </span>
            {w.note && <span style={styles.rowNote}>{w.note}</span>}
          </div>
          {renderActions && <div style={styles.rowActions}>{renderActions(w)}</div>}
        </li>
      ))}
    </ul>
  );
}

// Body weight over time, oldest to newest. Plain SVG, like the other charts here.
export function WeightChart({ metrics }) {
  const points = [...metrics].reverse().filter((m) => m.weightKg);
  if (points.length < 2) {
    return <div style={styles.empty}>Log your weight on two or more days to see a chart.</div>;
  }
  const W = 440;
  const H = 160;
  const pad = { l: 40, r: 12, t: 12, b: 26 };
  const values = points.map((p) => Number(p.weightKg));
  const min = Math.floor(Math.min(...values) - 1);
  const max = Math.ceil(Math.max(...values) + 1);
  const x = (i) => pad.l + (i * (W - pad.l - pad.r)) / (points.length - 1);
  const y = (v) => pad.t + ((max - v) * (H - pad.t - pad.b)) / (max - min || 1);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(p.weightKg)).toFixed(1)}`).join(" ");
  const first = values[0];
  const last = values[values.length - 1];
  const label = `Body weight from ${first} kg on ${points[0].date} to ${last} kg on ${points[points.length - 1].date}`;
  return (
    <figure style={styles.figure}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={styles.chart}>
        {[min, (min + max) / 2, max].map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="#ececf0" />
            <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#777">
              {Math.round(v)}
            </text>
          </g>
        ))}
        <path d={path} fill="none" stroke="#124096" strokeWidth="2.5" strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={p.id} cx={x(i)} cy={y(Number(p.weightKg))} r="4" fill="#fff" stroke="#124096" strokeWidth="2">
            <title>{`${p.date}: ${Number(p.weightKg)} kg`}</title>
          </circle>
        ))}
        <text x={pad.l} y={H - 6} fontSize="11" fill="#777">{points[0].date}</text>
        <text x={W - pad.r} y={H - 6} fontSize="11" fill="#777" textAnchor="end">{points[points.length - 1].date}</text>
      </svg>
      <figcaption style={styles.caption}>
        Body weight (kg): {first} → {last}
        <b style={{ color: last <= first ? "#1e7a34" : "#9a6100" }}>
          {" "}({last - first >= 0 ? "+" : ""}{(last - first).toFixed(1)} kg)
        </b>
      </figcaption>
    </figure>
  );
}

export function MetricList({ metrics, renderActions }) {
  if (metrics.length === 0) return <div style={styles.empty}>No measurements logged yet.</div>;
  return (
    <ul style={styles.list}>
      {metrics.map((m) => (
        <li key={m.id} style={styles.row}>
          <div style={styles.rowMain}>
            <span style={styles.rowTitle}>{Number(m.weightKg)} kg</span>
            <span style={styles.rowMeta}>
              {m.date}
              {m.bodyFatPercent && ` · ${Number(m.bodyFatPercent)}% body fat`}
              {m.waistCm && ` · waist ${Number(m.waistCm)} cm`}
              {m.chestCm && ` · chest ${Number(m.chestCm)} cm`}
              {m.hipsCm && ` · hips ${Number(m.hipsCm)} cm`}
            </span>
          </div>
          {renderActions && <div style={styles.rowActions}>{renderActions(m)}</div>}
        </li>
      ))}
    </ul>
  );
}

export const styles = {
  empty: { padding: 14, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  list: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10 },
  row: { display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderBottom: "1px solid #f0f0f2" },
  rowMain: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  rowTitle: { fontSize: 14, fontWeight: 700 },
  rowMeta: { fontSize: 12, color: "#666" },
  rowNote: { fontSize: 12, color: "#888", fontStyle: "italic" },
  rowActions: { display: "flex", gap: 6, flexShrink: 0 },
  figure: { margin: "0 0 12px" },
  chart: { width: "100%", height: "auto", display: "block" },
  caption: { fontSize: 13, color: "#444", marginTop: 4 },
};

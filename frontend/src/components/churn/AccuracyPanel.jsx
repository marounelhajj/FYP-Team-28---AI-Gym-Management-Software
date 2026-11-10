// User story (SCRUM-120): "...cap the at-risk list to the number of calls my
// staff can make per week, so that the list stays actionable."
// AC: accuracy is tracked against completed calls.
//
// This week's calls against the capacity, the same over every week's list,
// and - once enough weeks have had 30 days to play out - how many members on
// the call list cancelled within 30 days compared with everyone else
// (precision at N). Until then it says "Not enough data yet".

const pct = (rate) => (rate == null ? "-" : `${Math.round(rate * 100)}%`);

function Stat({ value, label, hint, tone }) {
  return (
    <div style={styles.stat}>
      <div style={{ ...styles.statValue, ...(tone ? { color: tone } : null) }}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
      {hint && <div style={styles.statHint}>{hint}</div>}
    </div>
  );
}

export default function AccuracyPanel({ accuracy, branch }) {
  if (!accuracy) return null;
  const { thisWeek, allWeeks, precision } = accuracy;
  return (
    <section style={styles.card} aria-label={`How the calls are working at ${branch}`}>
      <div style={styles.header}>
        <h2 style={styles.title}>How the calls are working</h2>
        <span style={styles.sub}>
          {allWeeks.weeks} weekly list{allWeeks.weeks === 1 ? "" : "s"} at {branch}
        </span>
      </div>

      <div style={styles.groupLabel}>This week</div>
      <div style={styles.stats}>
        <Stat value={`${thisWeek.contacted}/${thisWeek.capacity}`} label="Calls done" hint={`${thisWeek.toCall} still to call`} />
        <Stat value={thisWeek.saved} label="Saved" tone="#1e6b34" />
        <Stat value={thisWeek.noAnswer} label="No answer yet" hint="stay on the list for a retry" />
        <Stat value={thisWeek.cancelledAnyway} label="Cancelled anyway" tone={thisWeek.cancelledAnyway ? "#b3261e" : undefined} />
      </div>

      <div style={styles.groupLabel}>All weeks</div>
      <div style={styles.stats}>
        <Stat value={allWeeks.listed} label="Members on call lists" />
        <Stat value={allWeeks.contacted} label="Contacted" hint={pct(allWeeks.listed ? allWeeks.contacted / allWeeks.listed : null) + " of listed"} />
        <Stat value={allWeeks.saved} label="Saved" tone="#1e6b34" hint={allWeeks.contacted ? `${pct(allWeeks.saved / allWeeks.contacted)} of contacted` : undefined} />
      </div>

      <div style={styles.groupLabel}>Did the list pick the right people?</div>
      {precision.enough ? (
        <div style={styles.precision}>
          <div style={styles.bars}>
            <Bar label="On the call list" rate={precision.precisionAtN} detail={`${precision.listedCancelled} of ${precision.listed}`} color="#b3261e" />
            <Bar label="Everyone else" rate={precision.othersRate} detail={`${precision.othersCancelled} of ${precision.others}`} color="#9aa0ad" />
          </div>
          <p style={styles.explain}>
            Share who cancelled within {precision.labelDays} days of the list, over {precision.finishedWeeks} finished
            weeks{precision.lift ? <> - members on the list left <strong>{precision.lift}x</strong> as often</> : null}.
            {precision.contacted > 0 && (
              <> Of the listed members staff reached, {pct(precision.contactedRate)} still left.</>
            )}
          </p>
        </div>
      ) : (
        <div style={styles.notEnough}>
          <strong>Not enough data yet.</strong> This needs {precision.minWeeks} weeks whose lists are at least{" "}
          {precision.labelDays} days old, with {precision.minListed} members on them. So far: {precision.finishedWeeks}{" "}
          week{precision.finishedWeeks === 1 ? "" : "s"}, {precision.listed} member{precision.listed === 1 ? "" : "s"}.
        </div>
      )}
    </section>
  );
}

function Bar({ label, rate, detail, color }) {
  const width = Math.max(2, Math.round((rate || 0) * 100));
  return (
    <div style={styles.barRow}>
      <span style={styles.barLabel}>{label}</span>
      <span style={styles.barTrack} aria-hidden="true">
        <span style={{ ...styles.barFill, width: `${width}%`, background: color }} className="ap-grow" />
      </span>
      <span style={styles.barValue}>{pct(rate)}</span>
      <span style={styles.barDetail}>{detail}</span>
    </div>
  );
}

const styles = {
  card: { border: "1px solid #e4e4e8", borderRadius: 20, background: "#fff", padding: 20, marginBottom: 16, boxShadow: "0 2px 0 #e2e2e8" },
  header: { display: "flex", flexWrap: "wrap", alignItems: "baseline", justifyContent: "space-between", gap: 10, marginBottom: 6 },
  title: { fontSize: 18, fontWeight: 900, margin: 0 },
  sub: { fontSize: 13, color: "#666", fontWeight: 600 },
  groupLabel: { fontSize: 12, fontWeight: 800, color: "#666", textTransform: "uppercase", letterSpacing: 0.4, margin: "14px 0 8px" },
  stats: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 },
  stat: { padding: "12px 14px", border: "1px solid #ececf0", borderRadius: 14, background: "#fafafc" },
  statValue: { fontSize: 28, fontWeight: 900, fontVariantNumeric: "tabular-nums" },
  statLabel: { fontSize: 13, fontWeight: 800, color: "#444" },
  statHint: { fontSize: 12, color: "#888", marginTop: 2 },
  precision: { display: "flex", flexDirection: "column", gap: 10 },
  bars: { display: "flex", flexDirection: "column", gap: 8 },
  barRow: { display: "grid", gridTemplateColumns: "130px minmax(60px, 1fr) 48px 84px", alignItems: "center", gap: 10, fontSize: 14 },
  barLabel: { fontWeight: 800 },
  barTrack: { height: 14, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  barFill: { display: "block", height: "100%", borderRadius: 999, transformOrigin: "left" },
  barValue: { fontWeight: 900, fontVariantNumeric: "tabular-nums", textAlign: "right" },
  barDetail: { fontSize: 12, color: "#777", whiteSpace: "nowrap" },
  explain: { fontSize: 14, color: "#444", margin: 0 },
  notEnough: { padding: "14px 16px", border: "1px dashed #d0d0d5", borderRadius: 14, fontSize: 14, color: "#555", background: "#fafafc" },
};

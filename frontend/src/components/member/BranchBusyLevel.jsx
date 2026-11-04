import { useEffect, useState } from "react";
import { fetchBranchBusy } from "../../api/memberAuth.js";

// User story (SCRUM-77): "As a member, I want to see how busy my branch is
// right now and at typical hours, so that I can plan my visit around peak
// times."
//
// Only levels come from the server (Quiet / Moderate / Busy / Very busy) -
// never a headcount - so nobody can be picked out. "Typical" is the average
// of the same weekday over the last few weeks.
const COLORS = ["#1e7a34", "#4f7d12", "#b06a00", "#b3261e"];
const BG = ["#e3f5e8", "#eef6dc", "#fff1db", "#fdeceb"];
const SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const REFRESH_MS = 60000;

function hourLabel(hour) {
  const suffix = hour < 12 ? "am" : "pm";
  const h = hour % 12 === 0 ? 12 : hour % 12;
  return `${h}${suffix}`;
}

export default function BranchBusyLevel({ homeBranch }) {
  const [branch, setBranch] = useState(homeBranch);
  const [weekday, setWeekday] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchBranchBusy({ branch, weekday })
        .then((body) => !cancelled && (setData(body), setError(null)))
        .catch((err) => !cancelled && setError(err.message));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [branch, weekday]);

  const selectedDay = weekday ?? data?.today;
  const hours = data?.typical.hours || [];
  const first = hours.length ? Math.min(...hours.map((h) => h.hour)) : 6;
  const last = hours.length ? Math.max(...hours.map((h) => h.hour)) : 22;
  const byHour = Object.fromEntries(hours.map((h) => [h.hour, h]));
  const span = Array.from({ length: last - first + 1 }, (_, i) => first + i);

  return (
    <div style={styles.card}>
      <style>{CSS}</style>
      <div style={styles.header}>
        <span style={styles.title}>How busy is it?</span>
        <select
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          aria-label="Branch"
          className="bb-select"
          style={styles.select}
        >
          {(data?.branches || [homeBranch]).map((b) => (
            <option key={b} value={b}>
              {b}
              {b === homeBranch ? " (your branch)" : ""}
            </option>
          ))}
        </select>
      </div>

      {error && <div style={styles.errorBox}>{error}</div>}
      {data && !data.available && (
        <p style={styles.muted}>Busy levels aren't available for {data.branch} yet.</p>
      )}

      {data?.available && (
        <>
          <div style={styles.now} aria-live="polite">
            <span style={styles.nowLabel}>Right now</span>
            <span
              key={`${data.branch}-${data.now.level}`}
              className="bb-pop"
              style={{ ...styles.level, color: COLORS[data.now.levelIndex], background: BG[data.now.levelIndex] }}
            >
              {data.now.level}
            </span>
            <span style={styles.asOf}>as of {data.asOf}</span>
          </div>

          <div style={styles.typicalHeader}>
            <span style={styles.typicalTitle}>Typical {data.weekdays[selectedDay]}</span>
          </div>
          <div role="radiogroup" aria-label="Weekday" style={styles.days}>
            {SHORT.map((label, index) => {
              const selected = index === selectedDay;
              return (
                <button
                  key={label}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={data.weekdays[index]}
                  onClick={() => setWeekday(index)}
                  className="bb-press"
                  style={{ ...styles.day, ...(selected ? styles.daySelected : null) }}
                >
                  {index === data.today ? "Today" : label}
                </button>
              );
            })}
          </div>

          {hours.length === 0 ? (
            <p style={styles.muted}>Not enough visits on {data.weekdays[selectedDay]}s yet to show a typical day.</p>
          ) : (
            <>
              <div style={styles.bars} role="list" aria-label={`Typical busy level by hour on ${data.weekdays[selectedDay]}`}>
                {span.map((hour) => {
                  const h = byHour[hour];
                  return (
                    <div key={hour} role="listitem" style={styles.barCol} title={`${hourLabel(hour)}: ${h ? h.level : "Closed"}`}>
                      <div
                        className="bb-bar"
                        aria-label={`${hourLabel(hour)}: ${h ? h.level : "Closed"}`}
                        style={{
                          ...styles.bar,
                          height: h ? `${(h.levelIndex + 1) * 25}%` : 3,
                          background: h ? COLORS[h.levelIndex] : "#dcdce2",
                        }}
                      />
                      <span style={styles.barLabel}>{hour % 3 === 0 ? hourLabel(hour) : ""}</span>
                    </div>
                  );
                })}
              </div>
              <div style={styles.legend}>
                {data.levels.map((name, i) => (
                  <span key={name} style={styles.legendItem}>
                    <i style={{ ...styles.swatch, background: COLORS[i] }} /> {name}
                  </span>
                ))}
              </div>
              <p style={styles.note}>
                Based on the last {data.typical.weeksCompared} {data.weekdays[selectedDay]}
                {data.typical.weeksCompared === 1 ? "" : "s"}. Only busy levels are shown, never who is there.
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}

const CSS = `
.bb-select { appearance: none; -webkit-appearance: none; cursor: pointer; padding-right: 34px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23124096' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat; background-position: right 12px center; }
.bb-select:focus-visible, .bb-press:focus-visible { outline: 2px solid #124096; outline-offset: 2px; }
.bb-press { transition: transform 120ms ease, background 160ms ease, color 160ms ease; }
.bb-press:active { transform: scale(0.95); }
.bb-pop { animation: bb-pop 320ms cubic-bezier(0.34, 1.56, 0.64, 1); }
.bb-bar { transform-origin: bottom; animation: bb-grow 420ms ease-out both; transition: height 300ms ease; }
@keyframes bb-pop { from { transform: scale(0.9); opacity: 0.4; } to { transform: none; opacity: 1; } }
@keyframes bb-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@media (prefers-reduced-motion: reduce) { .bb-pop, .bb-bar { animation: none; transition: none; } .bb-press { transition: none; } }
`;

const styles = {
  card: { marginTop: 16, padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 },
  title: { fontSize: 16, fontWeight: 800 },
  select: {
    height: 38, padding: "0 12px", fontSize: 14, fontWeight: 700, color: "#124096", border: "1px solid #c5d0e8",
    borderRadius: 10, backgroundColor: "#eef2fa",
  },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginTop: 10 },
  muted: { fontSize: 13, color: "#777", margin: "10px 0 0" },
  now: { display: "flex", alignItems: "center", gap: 10, marginTop: 14, flexWrap: "wrap" },
  nowLabel: { fontSize: 13, fontWeight: 700, color: "#555" },
  level: { fontSize: 20, fontWeight: 900, padding: "6px 14px", borderRadius: 12 },
  asOf: { fontSize: 12, color: "#888" },
  typicalHeader: { marginTop: 18 },
  typicalTitle: { fontSize: 14, fontWeight: 800 },
  days: { display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 4, marginTop: 8, padding: 4, borderRadius: 12, background: "#ececf0" },
  day: { height: 34, border: "none", borderRadius: 9, background: "transparent", fontSize: 12, fontWeight: 800, color: "#555", cursor: "pointer" },
  daySelected: { background: "#fff", color: "#124096", boxShadow: "0 2px 6px rgba(18,64,150,0.2)" },
  bars: { display: "flex", alignItems: "flex-end", gap: 3, height: 110, marginTop: 14, paddingBottom: 18, position: "relative" },
  barCol: { flex: 1, height: "100%", display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "center", position: "relative" },
  bar: { width: "100%", borderRadius: "4px 4px 0 0" },
  barLabel: { position: "absolute", bottom: -18, fontSize: 10, color: "#777", whiteSpace: "nowrap" },
  legend: { display: "flex", flexWrap: "wrap", gap: 12, marginTop: 10, fontSize: 12, fontWeight: 700, color: "#555" },
  legendItem: { display: "inline-flex", alignItems: "center", gap: 5 },
  swatch: { display: "inline-block", width: 10, height: 10, borderRadius: 3 },
  note: { fontSize: 12, color: "#888", margin: "8px 0 0" },
};

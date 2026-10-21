import { useEffect, useRef, useState } from "react";
import HourlyChart from "./HourlyChart.jsx";
import { useLiveHeadcount } from "./useLiveHeadcount.js";

// User story (SCRUM-127): "As a branch manager, I want to view live
// headcount for my branch on a dashboard, so that I can see how full the gym
// is right now."
//
// A Branch Manager sees their own branch only; a General Manager gets a
// branch picker. The server enforces this too (headcount/views.py), the
// picker is just how a General Manager asks.

const BLUE = "#124096";

function formatTime(date) {
  return date ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

// Sunken tray with a raised pill that slides to the selected branch.
// Arrow keys move between branches, like any radio group.
function BranchPicker({ branches, value, onChange }) {
  const buttons = useRef([]);
  const index = Math.max(0, branches.indexOf(value));

  function onKeyDown(event) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + branches.length) % branches.length;
    onChange(branches[next]);
    buttons.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label="Branch"
      onKeyDown={onKeyDown}
      className="hc-tray"
      style={{ ...styles.tray, gridTemplateColumns: `repeat(${branches.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden="true"
        className="hc-pill"
        style={{
          ...styles.pill,
          width: `calc((100% - 8px) / ${branches.length})`,
          transform: `translateX(${index * 100}%)`,
        }}
      />
      {branches.map((branch, i) => {
        const selected = i === index;
        return (
          <button
            key={branch}
            ref={(el) => (buttons.current[i] = el)}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(branch)}
            className="hc-press hc-focus hc-tray-option"
            style={{ ...styles.trayOption, color: selected ? BLUE : "#5b6070" }}
          >
            {branch}
          </button>
        );
      })}
    </div>
  );
}

function StatusChip({ status, lastUpdated }) {
  if (status === "live") {
    return (
      <span style={{ ...styles.chip, ...styles.chipLive }} role="status">
        <span className="hc-live-dot" style={styles.liveDot} aria-hidden="true" />
        Live · updated {formatTime(lastUpdated)}
      </span>
    );
  }
  if (status === "reconnecting") {
    return (
      <span style={{ ...styles.chip, ...styles.chipReconnecting }} role="status">
        <span className="hc-spinner" style={styles.spinner} aria-hidden="true" />
        Reconnecting{lastUpdated ? ` · last updated ${formatTime(lastUpdated)}` : ""}
      </span>
    );
  }
  if (status === "loading") {
    return <span style={{ ...styles.chip, ...styles.chipMuted }}>Connecting…</span>;
  }
  return null;
}

export default function HeadcountDashboard() {
  // null = let the server pick (a Branch Manager's own branch, or a
  // General Manager's default).
  const [branch, setBranch] = useState(null);
  // Remembered across branch switches so the picker doesn't vanish while
  // the newly picked branch loads.
  const [branchOptions, setBranchOptions] = useState([]);
  const { data, status, error, lastUpdated } = useLiveHeadcount(branch);

  useEffect(() => {
    if (data?.branches) setBranchOptions(data.branches);
  }, [data]);

  const shownBranch = branch || data?.branch;
  const count = data?.count;
  const stale = status === "reconnecting";

  return (
    <div style={styles.page}>
      <style>{CSS}</style>
      <section style={styles.card} aria-labelledby="hc-title">
        <header className="hc-pad" style={styles.cardHeader}>
          <div>
            <h2 id="hc-title" style={styles.title}>
              Live headcount
            </h2>
            <div style={styles.subtitle}>{shownBranch ? `${shownBranch} branch` : " "}</div>
          </div>
          <div className="hc-tools" style={styles.tools}>
            {branchOptions.length > 1 && (
              <BranchPicker branches={branchOptions} value={shownBranch} onChange={setBranch} />
            )}
            <StatusChip status={status} lastUpdated={lastUpdated} />
          </div>
        </header>

        {status === "denied" ? (
          <div style={styles.denied} role="alert">
            <div style={styles.deniedTitle}>Headcount isn't available</div>
            <div>{error}</div>
          </div>
        ) : (
          <>
            <div className="hc-pad" style={styles.body}>
              <div style={styles.countRow} aria-live="polite" aria-atomic="true">
                <span
                  key={count ?? "none"}
                  className={count === undefined ? undefined : "hc-bump"}
                  style={{ ...styles.count, opacity: stale ? 0.5 : 1 }}
                >
                  {count ?? "–"}
                </span>
                <span style={styles.countLabel}>
                  {count === 1 ? "member" : "members"} inside now
                  {stale && <span style={styles.staleNote}>Last known count, not live</span>}
                </span>
              </div>
              <p style={styles.footnote}>
                Counted from check-ins and check-outs at this branch. Anyone still checked in after{" "}
                {data?.autoCheckoutHours ?? 4} hours is checked out automatically.
              </p>
            </div>
            <div className="hc-pad">
              <HourlyChart branch={branch} />
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// Keyframes, focus rings and reduced motion can't be expressed as inline
// styles, so they live here.
const CSS = `
@keyframes hc-bump { 0% { transform: scale(0.92); color: ${BLUE}; } 60% { transform: scale(1.04); } 100% { transform: scale(1); } }
@keyframes hc-breathe { 0%, 100% { box-shadow: 0 0 0 0 rgba(30, 122, 52, 0.45); } 50% { box-shadow: 0 0 0 6px rgba(30, 122, 52, 0); } }
@keyframes hc-spin { to { transform: rotate(360deg); } }
.hc-bump { display: inline-block; animation: hc-bump 420ms cubic-bezier(0.34, 1.56, 0.64, 1); transform-origin: left bottom; }
.hc-live-dot { animation: hc-breathe 2.4s ease-in-out infinite; }
.hc-spinner { animation: hc-spin 0.9s linear infinite; }
@keyframes hc-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
.hc-grow path { transform-box: fill-box; transform-origin: bottom; animation: hc-grow 520ms cubic-bezier(0.16, 1, 0.3, 1); }
.hc-pill { transition: transform 260ms cubic-bezier(0.16, 1, 0.3, 1); }
.hc-press { transition: transform 120ms ease, color 200ms ease; }
.hc-press:active { transform: scale(0.96); }
.hc-focus:focus-visible { outline: 2px solid ${BLUE}; outline-offset: 2px; }
.hc-pad { padding-left: 24px; padding-right: 24px; }
.hc-tray-option { padding: 0 14px; font-size: 15px; }
@media (max-width: 600px) {
  .hc-pad { padding-left: 16px; padding-right: 16px; }
  .hc-tools, .hc-tray { width: 100%; }
  .hc-tray-option { padding: 0 2px; font-size: 14px; }
}
@media (prefers-reduced-motion: reduce) {
  .hc-bump, .hc-live-dot, .hc-spinner, .hc-grow path { animation: none; }
  .hc-pill, .hc-press { transition: none; }
  .hc-press:active { transform: none; }
}
`;

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1000,
    margin: "0 auto",
    padding: "32px 16px",
    color: "#1a1a1a",
  },
  card: {
    background: "#fff",
    border: "1px solid #e4e4e8",
    borderRadius: 24,
    boxShadow: "0 1px 2px rgba(18, 64, 150, 0.06), 0 8px 24px rgba(18, 64, 150, 0.06)",
    overflow: "hidden",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 16,
    paddingTop: 20,
    paddingBottom: 20,
    borderBottom: "1px solid #eceef3",
  },
  title: { fontSize: 22, fontWeight: 800, margin: 0, letterSpacing: "-0.01em" },
  subtitle: { fontSize: 14, fontWeight: 600, color: "#666", marginTop: 2, minHeight: 18 },
  tools: { display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12 },
  tray: {
    position: "relative",
    display: "grid",
    padding: 4,
    minHeight: 48,
    borderRadius: 16,
    background: "#eceef3",
    boxShadow: "inset 0 2px 4px rgba(20, 30, 60, 0.12)",
  },
  pill: {
    position: "absolute",
    top: 4,
    bottom: 4,
    left: 4,
    borderRadius: 12,
    background: "#fff",
    boxShadow: "0 1px 1px rgba(20, 30, 60, 0.08), 0 3px 8px rgba(20, 30, 60, 0.16)",
  },
  trayOption: {
    position: "relative",
    minHeight: 40,
    border: "none",
    borderRadius: 12,
    background: "transparent",
    fontWeight: 800,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    minHeight: 36,
    padding: "0 14px",
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  chipLive: { background: "#e6f4ea", color: "#1e7a34" },
  chipReconnecting: { background: "#fff4e0", color: "#8a4b00" },
  chipMuted: { background: "#f0f0f3", color: "#666" },
  liveDot: { width: 8, height: 8, borderRadius: "50%", background: "#1e7a34" },
  spinner: {
    width: 12,
    height: 12,
    borderRadius: "50%",
    border: "2px solid rgba(138, 75, 0, 0.3)",
    borderTopColor: "#8a4b00",
  },
  body: { paddingTop: 28, paddingBottom: 24 },
  countRow: { display: "flex", alignItems: "flex-end", flexWrap: "wrap", columnGap: 16, rowGap: 4 },
  count: {
    fontSize: "clamp(80px, 18vw, 136px)",
    fontWeight: 800,
    lineHeight: 0.9,
    letterSpacing: "-0.04em",
    fontVariantNumeric: "tabular-nums",
    color: "#1a1a1a",
    transition: "opacity 200ms ease",
  },
  countLabel: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    paddingBottom: 10,
    fontSize: 22,
    fontWeight: 800,
    color: "#333",
  },
  staleNote: { fontSize: 13, fontWeight: 700, color: "#8a4b00" },
  footnote: { margin: "20px 0 0", fontSize: 13, color: "#666", maxWidth: 560, lineHeight: 1.5 },
  denied: { margin: 24, padding: 16, borderRadius: 16, background: "#fdecec", color: "#8f1d1d", fontSize: 14 },
  deniedTitle: { fontWeight: 800, marginBottom: 4 },
};

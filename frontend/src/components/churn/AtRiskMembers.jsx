import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAtRisk, refreshAtRisk } from "../../api/churn.js";
import AccessDenied from "../AccessDenied.jsx";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// User story (SCRUM-118): "As a branch manager, I want to view a ranked list
// of members at risk of leaving, so that I know who to contact first."
//
// This week's list for one branch, highest risk first. The list is made by
// a weekly job (churn/jobs.py); "Refresh now" re-scores on demand. A Branch
// Manager only ever gets their own branch (the server enforces it); a
// General Manager gets a branch picker.

const LEVELS = ["High", "Medium", "Low"];
const LEVEL_STYLES = {
  High: { background: "#fde7e6", color: "#b3261e", border: "#f3b9b5" },
  Medium: { background: "#fff3d6", color: "#8a5a00", border: "#f1d48f" },
  Low: { background: "#e8f3ea", color: "#1e6b34", border: "#bcdcc4" },
};

function formatDate(iso) {
  if (!iso) return "-";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function formatDateTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function daysFromToday(iso) {
  if (!iso) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Math.round((d - today) / 86400000);
}

function RiskBadge({ level, score }) {
  const s = LEVEL_STYLES[level] || LEVEL_STYLES.Low;
  return (
    <span style={{ ...styles.badge, background: s.background, color: s.color, borderColor: s.border }}>
      <span style={styles.badgeLevel}>{level}</span>
      <span style={styles.badgeScore}>{score}</span>
    </span>
  );
}

function MethodChip({ run }) {
  if (!run) return null;
  if (run.method === "model" && run.model) {
    const auc = run.model.auc != null ? ` · validated AUC ${run.model.auc.toFixed(2)}` : "";
    return <span style={{ ...styles.chip, ...styles.chipModel }} title={run.model.version}>Learned model{auc}</span>;
  }
  return <span style={styles.chip} title={run.methodNote}>Rule-based score</span>;
}

export default function AtRiskMembers() {
  const [branch, setBranch] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // "risk" = High and Medium: the people worth a call. "all" includes Low.
  const [level, setLevel] = useState("risk");
  const [query, setQuery] = useState("");

  const load = useCallback((which) => {
    setLoading(true);
    setError(null);
    return fetchAtRisk(which)
      .then((body) => {
        setData(body);
        if (!which) setBranch(body.branch);
      })
      .catch((e) => (e.status === 403 && !which ? setForbidden(true) : setError(e.message)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(branch);
    // Only re-run when the chosen branch changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branch]);

  function refreshNow() {
    setRefreshing(true);
    setError(null);
    refreshAtRisk(data.branch)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setRefreshing(false));
  }

  const members = data?.members || [];
  const counts = useMemo(() => {
    const c = { all: members.length, High: 0, Medium: 0, Low: 0 };
    members.forEach((m) => { c[m.level] += 1; });
    c.risk = c.High + c.Medium;
    return c;
  }, [members]);
  const atRisk = counts.risk;
  const inTab = (m) => level === "all" || m.level === level || (level === "risk" && m.level !== "Low");
  const shown = members.filter(
    (m) => inTab(m) && (!query || m.name.toLowerCase().includes(query.trim().toLowerCase())),
  );

  if (forbidden) return <AccessDenied message="Your role doesn't include the at-risk members list." />;

  return (
    <div style={styles.page}>
      <style>{CSS}</style>
      <header style={styles.header}>
        <h1 style={styles.title}>At-Risk Members</h1>
        <p style={styles.subtitle}>
          Members most likely to leave, ranked so the team knows who to call first. Made every Monday.
        </p>
      </header>

      {error && <div style={styles.errorBox} role="alert">{error}</div>}
      {!data && loading && <p style={styles.muted}>Loading...</p>}

      {data && (
        <section style={styles.card} aria-label={`At-risk members at ${data.branch}`}>
          <div style={styles.cardHeader}>
            <div style={styles.headline}>
              <span style={styles.count} key={`${data.branch}-${atRisk}`} className="ar-pop">{atRisk}</span>
              <span style={styles.countLabelStrong}>members at risk</span>
              <span style={styles.countLabel}>at {data.branch} this week</span>
            </div>
            <div style={styles.controls}>
              {data.canChooseBranch && (
                <label style={styles.inline}>
                  <span style={styles.srOnly}>Branch</span>
                  <select
                    className="ar-select"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    style={styles.select}
                    aria-label="Branch"
                  >
                    {data.branches.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </label>
              )}
              {data.canRefresh && (
                <button type="button" className="ar-press" onClick={refreshNow} disabled={refreshing} style={styles.primary}>
                  {refreshing ? "Refreshing..." : "Refresh now"}
                </button>
              )}
            </div>
          </div>

          <div style={styles.metaRow}>
            <MethodChip run={data.run} />
            <span style={styles.meta}>
              Updated {formatDateTime(data.run.ranAt)} · {data.run.triggerLabel.toLowerCase()}
              {data.run.triggeredBy ? ` by ${data.run.triggeredBy}` : ""} · {data.run.membersScored} members scored
            </span>
            {data.run.method === "rules" && data.run.methodNote && (
              <span style={styles.metaNote}>{data.run.methodNote}</span>
            )}
          </div>

          <div style={styles.toolRow}>
            <div style={styles.tray} role="tablist" aria-label="Risk level">
              {[["risk", "At risk"], ...LEVELS.map((l) => [l, l]), ["all", "All"]].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={level === key}
                  className="ar-tab"
                  onClick={() => setLevel(key)}
                  style={level === key ? { ...styles.tab, ...styles.tabSelected } : styles.tab}
                >
                  {label} <span style={styles.tabCount}>{counts[key]}</span>
                </button>
              ))}
            </div>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name"
              aria-label="Search members by name"
              style={styles.search}
              className="ar-input"
            />
          </div>

          <div style={styles.scroll} className="ar-body" data-loading={loading || refreshing}>
            {shown.length === 0 ? (
              <div style={styles.empty}>{!members.length ? "No members to score at this branch yet."
                : level === "risk" && !query ? "Nobody is at medium or high risk this week." : "No members match."}</div>
            ) : (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>#</th>
                    <th style={styles.th}>Member</th>
                    <th style={styles.th}>Risk</th>
                    <th style={styles.th}>Last visit</th>
                    <th style={styles.th}>Membership ends</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((m) => {
                    const ends = daysFromToday(m.membershipEndsAt);
                    return (
                      <tr key={m.memberId} className="ar-row">
                        <td style={styles.rank}>{m.rank}</td>
                        <td style={styles.tdName}>
                          {m.name}
                          {m.status !== "Active" && <span style={styles.status}>{m.status}</span>}
                        </td>
                        <td style={styles.td}><RiskBadge level={m.level} score={m.score} /></td>
                        <td style={styles.td}>{m.lastVisit ? formatDate(m.lastVisit) : "Never"}</td>
                        <td style={styles.td}>
                          {formatDate(m.membershipEndsAt)}
                          {ends != null && ends >= 0 && ends <= 30 && <span style={styles.soon}> · in {ends} day{ends === 1 ? "" : "s"}</span>}
                          {ends != null && ends < 0 && <span style={styles.lapsed}> · lapsed</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

const BLUE = "#124096";

const CSS = `
.ar-tab { transition: background 160ms ease, box-shadow 160ms ease, color 160ms ease, transform 120ms ease; }
.ar-tab:hover { color: ${BLUE}; }
.ar-tab:active, .ar-press:active:not(:disabled) { transform: scale(0.96); }
.ar-press { transition: transform 120ms ease, filter 120ms ease; }
.ar-press:hover:not(:disabled) { filter: brightness(1.08); }
.ar-press:disabled { opacity: 0.6; cursor: progress; }
.ar-body { transition: opacity 180ms ease; }
.ar-body[data-loading="true"] { opacity: 0.55; }
.ar-row { animation: ar-in 260ms ease-out both; }
.ar-row:hover td { background: #f6f8fd; }
.ar-pop { display: inline-block; animation: ar-pop 360ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.ar-select { appearance: none; -webkit-appearance: none; cursor: pointer; padding-right: 40px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23124096' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat; background-position: right 14px center; }
.ar-select option { font-weight: 600; color: #1a1a1a; background: #fff; }
.ar-select:focus-visible, .ar-tab:focus-visible, .ar-press:focus-visible, .ar-input:focus-visible { outline: 3px solid ${BLUE}; outline-offset: 2px; }
@keyframes ar-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes ar-pop { from { transform: scale(0.85); opacity: 0.4; } to { transform: none; opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .ar-tab, .ar-press, .ar-body { transition: none; }
  .ar-row, .ar-pop { animation: none; }
  .ar-tab:active, .ar-press:active:not(:disabled) { transform: none; }
}
`;

export const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  header: { marginBottom: 16 },
  title: { fontSize: 24, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 12, fontSize: 14, marginBottom: 12, fontWeight: 600 },
  muted: { fontSize: 13, color: "#888" },
  card: { border: "1px solid #e4e4e8", borderRadius: 20, background: "#fff", padding: 20, marginBottom: 16, boxShadow: "0 2px 0 #e2e2e8" },
  cardHeader: { display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 14, marginBottom: 10 },
  headline: { display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" },
  count: { fontSize: 36, fontWeight: 900, letterSpacing: -0.5, color: "#b3261e" },
  countLabelStrong: { fontSize: 18, fontWeight: 800 },
  countLabel: { fontSize: 14, fontWeight: 600, color: "#666" },
  controls: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 },
  inline: { display: "inline-flex" },
  srOnly: { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" },
  select: { height: 48, padding: "0 14px", fontSize: 15, fontWeight: 800, border: "1px solid #d0d0d5", borderRadius: 14, background: "#fff", color: "#1a1a1a", fontFamily: "inherit" },
  primary: { height: 48, padding: "0 20px", fontSize: 15, fontWeight: 800, border: "none", borderRadius: 14, ...BUTTON_COLORS.blue, cursor: "pointer", boxShadow: "0 3px 0 #0b2a66", fontFamily: "inherit" },
  metaRow: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 14 },
  chip: { fontSize: 12, fontWeight: 800, padding: "5px 10px", borderRadius: 999, background: "#ececf0", color: "#444", textTransform: "uppercase", letterSpacing: 0.4 },
  chipModel: { background: "#e6edfa", color: BLUE },
  meta: { fontSize: 13, color: "#666", fontWeight: 600 },
  metaNote: { fontSize: 12, color: "#888", flexBasis: "100%" },
  toolRow: { display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12 },
  tray: { display: "inline-flex", gap: 4, padding: 5, borderRadius: 16, background: "#e9e9ee", boxShadow: "inset 0 2px 4px rgba(0,0,0,0.12)", flexWrap: "wrap" },
  tab: { height: 38, padding: "0 16px", border: "none", borderRadius: 12, background: "transparent", fontSize: 14, fontWeight: 800, color: "#555", cursor: "pointer", whiteSpace: "nowrap", fontFamily: "inherit" },
  tabSelected: { background: "#fff", color: BLUE, boxShadow: "0 3px 8px rgba(18,64,150,0.22), 0 1px 0 rgba(255,255,255,0.9) inset" },
  tabCount: { fontWeight: 900, marginLeft: 4 },
  search: { height: 48, minWidth: 0, flex: "0 1 260px", padding: "0 14px", fontSize: 15, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 14, background: "#fff", fontFamily: "inherit" },
  scroll: { overflowX: "auto" },
  empty: { padding: 22, border: "1px dashed #d0d0d5", borderRadius: 14, fontSize: 14, color: "#888", textAlign: "center" },
  table: { width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 14 },
  th: { textAlign: "left", padding: "10px 12px", fontSize: 12, fontWeight: 800, color: "#666", borderBottom: "2px solid #ececf0", whiteSpace: "nowrap", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { padding: "12px", borderBottom: "1px solid #f0f0f3", whiteSpace: "nowrap", verticalAlign: "top" },
  tdName: { padding: "12px", borderBottom: "1px solid #f0f0f3", fontWeight: 800, verticalAlign: "top" },
  rank: { padding: "12px", borderBottom: "1px solid #f0f0f3", fontWeight: 900, fontSize: 16, color: "#999", fontVariantNumeric: "tabular-nums", width: 40, verticalAlign: "top" },
  status: { marginLeft: 8, fontSize: 11, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#e6edfa", color: BLUE },
  badge: { display: "inline-flex", alignItems: "center", gap: 8, padding: "4px 10px", borderRadius: 999, border: "1px solid", fontSize: 13 },
  badgeLevel: { fontWeight: 900 },
  badgeScore: { fontWeight: 800, fontVariantNumeric: "tabular-nums", opacity: 0.8 },
  soon: { color: "#8a5a00", fontWeight: 700 },
  lapsed: { color: "#b3261e", fontWeight: 700 },
};

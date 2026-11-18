import { useEffect, useState } from "react";
import { fetchFeedbackOverview } from "../../api/branchFeedback.js";
import { StatusTag } from "./ComplaintThread.jsx";

// User story (SCRUM-23): "As a general manager, I want to view customer
// reviews, feedback, and suggestions across branches, so that I can identify
// recurring service issues..."
//
// Every branch's month side by side - Net Promoter Score, the five service
// areas, coach ratings, complaints - then what keeps coming up (complaint
// categories reported at several branches or many times, service areas
// rated low), and everything members wrote this month in one feed. Read
// only: complaints are still answered from Member Feedback.

const RED = "#b3261e";
const GREEN = "#0f6e2b";

function periodLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function signed(n) {
  return n > 0 ? `+${n}` : `${n}`;
}

const FEED_KINDS = [
  ["", "Everything"],
  ["survey", "Surveys"],
  ["coach", "Coach ratings"],
  ["complaint", "Complaints"],
];

export default function FeedbackOverview() {
  const [period, setPeriod] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("");
  const [branch, setBranch] = useState("");

  useEffect(() => {
    fetchFeedbackOverview({ period })
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [period]);

  if (error && !data) return <div style={styles.page}><div style={styles.errorBox}>{error}</div></div>;
  if (!data) return <div style={styles.page}><p style={styles.muted}>Loading...</p></div>;

  const { company, rules } = data;
  const scored = data.branches.filter((b) => b.nps !== null);
  const best = scored.length > 1 ? Math.max(...scored.map((b) => b.nps)) : null;
  const worst = scored.length > 1 ? Math.min(...scored.map((b) => b.nps)) : null;
  const feed = data.feed.filter((i) => (!kind || i.kind === kind) && (!branch || i.branch === branch));

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Feedback Overview</h1>
      <p style={styles.subtitle}>
        What members say about every branch in {data.period.label}: surveys, coach ratings and complaints, side by side.
        Answer complaints from Member Feedback.
      </p>
      {error && <div style={styles.errorBox}>{error}</div>}

      <label style={styles.toolField}>
        <span style={styles.toolLabel}>Month</span>
        <select value={period || data.period.key} onChange={(e) => setPeriod(e.target.value)} style={styles.select} aria-label="Month">
          {data.periods.map((key, i) => (
            <option key={key} value={key}>{periodLabel(key)}{i === 0 ? " (current)" : ""}</option>
          ))}
        </select>
      </label>

      <div style={styles.tiles}>
        <Tile label="Company NPS" value={company.nps === null ? "—" : signed(company.nps)} sub="All branches, -100 to +100" strong />
        <Tile label="Survey responses" value={company.responses} sub={`${data.branches.filter((b) => b.responses).length} of ${data.branches.length} branches rated`} />
        <Tile
          label="Complaints this month"
          value={company.complaints}
          sub={`${company.openComplaints} open now${company.overdue ? ` · ${company.overdue} overdue` : ""}`}
          tone={company.overdue ? RED : null}
        />
        <Tile
          label="Escalated to you"
          value={company.escalatedOpen}
          sub={company.escalatedOpen ? "Open - see Member Feedback › Escalated" : "Nothing waiting"}
          tone={company.escalatedOpen ? "#6a2fa0" : null}
        />
      </div>

      <section style={styles.panel} aria-label="Branches side by side">
        <h2 style={styles.panelTitle}>Branches side by side</h2>
        <p style={styles.panelHint}>
          Service areas are the average rating out of 5: <span style={{ color: RED, fontWeight: 700 }}>red</span> below {rules.weakArea.toFixed(1)},{" "}
          <span style={{ color: GREEN, fontWeight: 700 }}>green</span> 4.0 or more.
        </p>
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={{ ...styles.th, ...styles.stickyCol }}>Branch</th>
                <th style={styles.thRight}>NPS</th>
                <th style={styles.thRight}>Responses</th>
                {data.areaLabels.map((a) => (
                  <th key={a.key} style={styles.thRight}>{a.label}</th>
                ))}
                <th style={styles.thRight}>Coaches</th>
                <th style={styles.thRight}>Complaints</th>
                <th style={styles.thRight}>Open</th>
                <th style={styles.thRight}>Overdue</th>
                <th style={styles.thRight}>Escalated</th>
              </tr>
            </thead>
            <tbody>
              {data.branches.map((b) => (
                <tr key={b.branch}>
                  <td style={{ ...styles.td, ...styles.stickyCol, fontWeight: 700 }}>
                    {b.branch}
                    {b.nps !== null && b.nps === best && <span style={styles.bestTag}>Top</span>}
                    {b.nps !== null && b.nps === worst && <span style={styles.worstTag}>Lowest</span>}
                  </td>
                  <td style={styles.tdRight}>
                    <strong>{b.nps === null ? "—" : signed(b.nps)}</strong>
                    {b.npsChange !== null && b.npsChange !== 0 && (
                      <div style={{ fontSize: 11, color: b.npsChange > 0 ? GREEN : RED }}>
                        {b.npsChange > 0 ? "▲" : "▼"} {Math.abs(b.npsChange)}
                      </div>
                    )}
                  </td>
                  <td style={styles.tdRight}>{b.responses}</td>
                  {data.areaLabels.map((a) => {
                    const area = b.areas[a.key];
                    const tone = area.average === null ? null : area.average < rules.weakArea ? RED : area.average >= 4 ? GREEN : null;
                    return (
                      <td key={a.key} style={{ ...styles.tdRight, color: tone || "#1a1a1a", fontWeight: tone ? 700 : 400 }} title={`${area.count} ratings`}>
                        {area.average === null ? "—" : area.average.toFixed(1)}
                      </td>
                    );
                  })}
                  <td style={styles.tdRight} title={`${b.coachRatings} ratings`}>{b.coachAverage === null ? "—" : `${b.coachAverage.toFixed(1)} ★`}</td>
                  <td style={styles.tdRight}>{b.complaints.received}</td>
                  <td style={styles.tdRight}>{b.complaints.open + b.complaints.inProgress}</td>
                  <td style={{ ...styles.tdRight, color: b.complaints.overdue ? RED : "#1a1a1a", fontWeight: b.complaints.overdue ? 700 : 400 }}>
                    {b.complaints.overdue}
                  </td>
                  <td style={styles.tdRight}>{b.complaints.escalatedOpen}</td>
                </tr>
              ))}
              <tr>
                <td style={{ ...styles.tdTotal, ...styles.stickyCol }}>All branches</td>
                <td style={styles.tdTotalRight}>{company.nps === null ? "—" : signed(company.nps)}</td>
                <td style={styles.tdTotalRight}>{company.responses}</td>
                {data.areaLabels.map((a) => (
                  <td key={a.key} style={styles.tdTotalRight}>
                    {company.areas[a.key].average === null ? "—" : company.areas[a.key].average.toFixed(1)}
                  </td>
                ))}
                <td style={styles.tdTotalRight} />
                <td style={styles.tdTotalRight}>{company.complaints}</td>
                <td style={styles.tdTotalRight}>{company.openComplaints}</td>
                <td style={styles.tdTotalRight}>{company.overdue}</td>
                <td style={styles.tdTotalRight}>{company.escalatedOpen}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div style={styles.grid}>
        <section style={styles.panel} aria-label="Recurring complaints">
          <h2 style={styles.panelTitle}>What members complain about</h2>
          <p style={styles.panelHint}>
            Recurring: reported at {rules.recurringBranches}+ branches, or {rules.recurringCount}+ times this month.
          </p>
          {data.recurringComplaints.length === 0 ? (
            <p style={styles.muted}>No complaints this month.</p>
          ) : (
            <ul style={styles.list}>
              {data.recurringComplaints.map((c) => (
                <li key={c.category} style={styles.issue}>
                  <div style={styles.issueHead}>
                    <span style={styles.issueLabel}>
                      {c.label}
                      {c.recurring && <span style={styles.recurringTag}>Recurring</span>}
                    </span>
                    <strong>{c.total}</strong>
                  </div>
                  <div style={styles.chips}>
                    {c.branches.map((b) => (
                      <span key={b.branch} style={styles.chip}>{b.branch} · {b.count}</span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section style={styles.panel} aria-label="Weak service areas">
          <h2 style={styles.panelTitle}>Service areas rated low</h2>
          <p style={styles.panelHint}>
            Averaging below {rules.weakArea.toFixed(1)} / 5 at a branch, from at least {rules.minRatings} ratings.
          </p>
          {data.weakAreas.length === 0 ? (
            <p style={styles.muted}>No service area is rated low anywhere this month.</p>
          ) : (
            <ul style={styles.list}>
              {data.weakAreas.map((a) => (
                <li key={a.key} style={styles.issue}>
                  <div style={styles.issueHead}>
                    <span style={styles.issueLabel}>
                      {a.label}
                      {a.branches.length >= rules.recurringBranches && <span style={styles.recurringTag}>{a.branches.length} branches</span>}
                    </span>
                  </div>
                  <div style={styles.chips}>
                    {a.branches.map((b) => (
                      <span key={b.branch} style={{ ...styles.chip, ...styles.weakChip }}>{b.branch} · {b.average.toFixed(1)}</span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section style={styles.panel} aria-label="What members wrote">
        <div style={styles.feedHead}>
          <h2 style={styles.panelTitle}>What members wrote</h2>
          <div style={styles.filters}>
            {FEED_KINDS.map(([key, label]) => (
              <button
                key={key || "all"}
                type="button"
                onClick={() => setKind(key)}
                aria-pressed={kind === key}
                style={{ ...styles.filterButton, ...(kind === key ? styles.filterActive : null) }}
              >
                {label}
              </button>
            ))}
            <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.select} aria-label="Branch">
              <option value="">All branches</option>
              {data.branches.map((b) => (
                <option key={b.branch} value={b.branch}>{b.branch}</option>
              ))}
            </select>
          </div>
        </div>
        {feed.length === 0 ? (
          <p style={styles.muted}>Nothing written {branch ? `about ${branch} ` : ""}this month.</p>
        ) : (
          <ul style={styles.feed}>
            {feed.map((item) => (
              <FeedItem key={item.id} item={item} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function FeedItem({ item }) {
  let badge;
  if (item.kind === "survey") {
    const tone = item.score >= 9 ? styles.promoter : item.score <= 6 ? styles.detractor : styles.passive;
    badge = <span style={{ ...styles.scoreChip, ...tone }} title="Likelihood to recommend, 0-10">{item.score}</span>;
  } else if (item.kind === "coach") {
    badge = <span style={{ ...styles.scoreChip, ...styles.coachChip }} title="Coach rating out of 5">{item.score}★</span>;
  } else {
    badge = <span style={{ ...styles.scoreChip, ...styles.complaintChip }} title="Complaint">!</span>;
  }
  const kindLabel = { survey: "Branch survey", coach: "Coach rating", complaint: "Complaint" }[item.kind];
  return (
    <li style={styles.feedItem}>
      {badge}
      <div style={styles.feedBody}>
        <div style={styles.feedText}>
          {item.text}
          {item.kind === "complaint" && <span style={{ marginLeft: 6 }}><StatusTag status={item.status} /></span>}
          {item.escalated && <span style={styles.escalatedTag}>Escalated</span>}
        </div>
        <div style={styles.feedMeta}>
          <strong>{item.branch}</strong> · {kindLabel}
          {item.about ? ` · ${item.about}` : ""} · {item.who || "Anonymous"} · {item.at}
        </div>
      </div>
    </li>
  );
}

function Tile({ label, value, sub, tone, strong }) {
  return (
    <div style={{ ...styles.tile, ...(strong ? styles.tileStrong : null) }}>
      <span style={styles.tileLabel}>{label}</span>
      <span style={{ ...styles.tileValue, ...(tone ? { color: tone } : null) }}>{value}</span>
      {sub && <span style={{ ...styles.tileSub, ...(tone ? { color: tone } : null) }}>{sub}</span>}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 14px" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  errorBox: { background: "#fdeceb", color: RED, padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  toolField: { display: "inline-flex", flexDirection: "column", gap: 4, marginBottom: 14 },
  toolLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  select: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit" },
  tiles: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 12 },
  tile: { display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  tileStrong: { border: "1px solid #124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  tileLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  tileValue: { fontSize: 26, fontWeight: 800 },
  tileSub: { fontSize: 12, color: "#666" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12, marginBottom: 12 },
  panel: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff", marginBottom: 12, minWidth: 0 },
  panelTitle: { fontSize: 15, fontWeight: 800, margin: "0 0 4px" },
  panelHint: { fontSize: 12, color: "#777", margin: "4px 0 10px" },
  tableWrap: { overflowX: "auto", WebkitOverflowScrolling: "touch" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 860 },
  th: { textAlign: "left", padding: "8px 8px", borderBottom: "2px solid #e4e4e8", fontSize: 12, color: "#555", whiteSpace: "nowrap" },
  thRight: { textAlign: "right", padding: "8px 8px", borderBottom: "2px solid #e4e4e8", fontSize: 12, color: "#555", whiteSpace: "nowrap" },
  td: { padding: "8px 8px", borderBottom: "1px solid #f0f0f2", whiteSpace: "nowrap" },
  tdRight: { padding: "8px 8px", borderBottom: "1px solid #f0f0f2", textAlign: "right", whiteSpace: "nowrap" },
  tdTotal: { padding: "8px 8px", fontWeight: 800, background: "#f7f7f9" },
  tdTotalRight: { padding: "8px 8px", fontWeight: 800, textAlign: "right", background: "#f7f7f9" },
  stickyCol: { position: "sticky", left: 0, background: "#fff", zIndex: 1 },
  bestTag: { marginLeft: 6, fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#e3f5e8", color: GREEN },
  worstTag: { marginLeft: 6, fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#fdeceb", color: RED },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 },
  issue: { display: "flex", flexDirection: "column", gap: 5 },
  issueHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, fontSize: 14 },
  issueLabel: { fontWeight: 600, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  recurringTag: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: "#fdeceb", color: RED },
  chips: { display: "flex", gap: 6, flexWrap: "wrap" },
  chip: { fontSize: 12, padding: "2px 8px", borderRadius: 999, background: "#f0f2f7", color: "#333" },
  weakChip: { background: "#fdeceb", color: RED },
  feedHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 },
  filters: { display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" },
  filterButton: { padding: "6px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 999, background: "#fff", cursor: "pointer" },
  filterActive: { background: "#124096", border: "1px solid #124096", color: "#fff" },
  feed: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 },
  feedItem: { display: "flex", gap: 10, alignItems: "flex-start", fontSize: 14 },
  feedBody: { flex: 1, minWidth: 0, lineHeight: 1.45, overflowWrap: "anywhere" },
  feedText: { display: "flex", alignItems: "center", flexWrap: "wrap", gap: 4 },
  feedMeta: { fontSize: 12, color: "#777", marginTop: 2 },
  scoreChip: { flexShrink: 0, minWidth: 28, height: 28, padding: "0 4px", boxSizing: "border-box", borderRadius: 999, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: "#fff" },
  promoter: { background: "#129638" },
  passive: { background: "#8a8f99" },
  detractor: { background: "#de0b12" },
  coachChip: { background: "#124096" },
  complaintChip: { background: "#8a5300" },
  escalatedTag: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: "#6a2fa0", color: "#fff" },
};

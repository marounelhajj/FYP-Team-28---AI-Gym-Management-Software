import { useCallback, useEffect, useState } from "react";
import { fetchComplaint, fetchComplaints, fetchFeedbackSummary, replyToComplaint, setComplaintStatus } from "../../api/branchFeedback.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import ComplaintThread, { StatusTag } from "./ComplaintThread.jsx";

// User story: "As a branch manager, I want to view member feedback and
// complaints specific to my branch, so that I can address local service
// issues directly rather than waiting on a company wide report."
//
// The branch's month at a glance - Net Promoter Score and the five service
// areas against last month, the weakest area flagged, members' comments, the
// coaches' ratings - and the complaints queue, where each complaint is
// answered and resolved. A Branch Manager is held to their own branch by the
// server; roles that see every branch get a branch picker (the company view).

function periodLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function signed(n) {
  return n > 0 ? `+${n}` : `${n}`;
}

export default function BranchFeedback() {
  const [branch, setBranch] = useState(null);
  const [period, setPeriod] = useState(null);
  const [summary, setSummary] = useState(null);
  const [complaints, setComplaints] = useState(null);
  const [filter, setFilter] = useState("open");
  const [category, setCategory] = useState("");
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState(null);

  const loadSummary = useCallback(() => {
    return fetchFeedbackSummary({ branch, period })
      .then((body) => {
        setSummary(body);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [branch, period]);

  const loadComplaints = useCallback(() => {
    return fetchComplaints({ branch, status: filter, category })
      .then((body) => setComplaints(body))
      .catch((e) => setError(e.message));
  }, [branch, filter, category]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadComplaints();
  }, [loadComplaints]);

  if (error && !summary) return <div style={styles.page}><div style={styles.errorBox}>{error}</div></div>;
  if (!summary) return <div style={styles.page}><p style={styles.muted}>Loading...</p></div>;

  const { nps, complaints: counts } = summary;
  const npsChange = nps.score !== null && nps.previousScore !== null ? nps.score - nps.previousScore : null;
  const previousLabel = summary.trend.length > 1 ? summary.trend[summary.trend.length - 2].label : "last month";

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Member Feedback · {summary.branch}</h1>
      <p style={styles.subtitle}>What members of {summary.branch} say about it, and their complaints to answer. Members rate a branch at most once a month.</p>
      {error && <div style={styles.errorBox}>{error}</div>}

      <div style={styles.toolbar}>
        {summary.branches.length > 1 && (
          <label style={styles.toolField}>
            <span style={styles.toolLabel}>Branch</span>
            <select value={summary.branch} onChange={(e) => setBranch(e.target.value)} style={styles.select} aria-label="Branch">
              {summary.branches.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </label>
        )}
        <label style={styles.toolField}>
          <span style={styles.toolLabel}>Month</span>
          <select value={period || summary.period.key} onChange={(e) => setPeriod(e.target.value)} style={styles.select} aria-label="Month">
            {summary.periods.map((key, i) => (
              <option key={key} value={key}>{periodLabel(key)}{i === 0 ? " (current)" : ""}</option>
            ))}
          </select>
        </label>
      </div>

      <div style={styles.tiles}>
        <Tile
          label="Net Promoter Score"
          value={nps.score === null ? "—" : signed(nps.score)}
          sub={npsChange === null ? "Scale -100 to +100" : `${signed(npsChange)} vs ${previousLabel}`}
          tone={npsChange === null ? null : npsChange >= 0 ? "#0f6e2b" : "#b3261e"}
          strong
        />
        <Tile label="Survey responses" value={nps.responses} sub={`${nps.previousResponses} in ${previousLabel}`} />
        <Tile
          label="Open complaints"
          value={counts.open + counts.inProgress}
          sub={counts.overdue ? `${counts.overdue} overdue (> ${summary.responseHours} h without an answer)` : "None overdue"}
          tone={counts.overdue ? "#b3261e" : null}
        />
        <Tile
          label="Average first answer"
          value={counts.averageFirstResponseHours === null ? "—" : `${counts.averageFirstResponseHours} h`}
          sub={`Target ${summary.responseHours} h · ${counts.received} received, ${counts.resolved} resolved this month`}
        />
      </div>

      <div style={styles.grid}>
        <section style={styles.panel} aria-label="Service areas">
          <h2 style={styles.panelTitle}>Service areas</h2>
          <p style={styles.panelHint}>Average rating, 1 (very poor) to 5 (excellent).</p>
          {summary.areas.map((a) => (
            <AreaBar key={a.key} area={a} weakest={summary.weakestArea === a.key} />
          ))}
        </section>
        <section style={styles.panel} aria-label="Score over time">
          <h2 style={styles.panelTitle}>Net Promoter Score, last 6 months</h2>
          <NpsTrend trend={summary.trend} />
          {nps.responses > 0 && <NpsSplit nps={nps} />}
          <p style={styles.panelHint}>Promoters rate 9-10, detractors 0-6. Score = % promoters - % detractors.</p>
        </section>
      </div>

      <section style={styles.panel} aria-label="Comments">
        <h2 style={styles.panelTitle}>What members said ({summary.commentCount})</h2>
        {summary.comments.length === 0 ? (
          <p style={styles.muted}>No comments this month.</p>
        ) : (
          <ul style={styles.comments}>
            {summary.comments.map((c) => (
              <li key={c.id} style={styles.comment}>
                <span style={{ ...styles.npsChip, ...(c.nps >= 9 ? styles.promoter : c.nps <= 6 ? styles.detractor : styles.passive) }} title="Likelihood to recommend">
                  {c.nps}
                </span>
                <div style={styles.commentBody}>
                  <div>{c.comment}</div>
                  <div style={styles.commentMeta}>{c.member ? c.member.name : "Anonymous"} · {c.date}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section style={styles.panel} aria-label="Complaints">
        <div style={styles.queueHead}>
          <h2 style={styles.panelTitle}>Complaints</h2>
          <div style={styles.filters}>
            {[["open", "Open"], ["resolved", "Resolved"], ["all", "All"]].map(([key, label]) => (
              <button key={key} type="button" onClick={() => setFilter(key)} aria-pressed={filter === key} style={{ ...styles.filterButton, ...(filter === key ? styles.filterActive : null) }}>
                {label}
              </button>
            ))}
            <select value={category} onChange={(e) => setCategory(e.target.value)} style={styles.select} aria-label="Category">
              <option value="">All categories</option>
              {(complaints?.categories || []).map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>
        {!complaints ? (
          <p style={styles.muted}>Loading...</p>
        ) : complaints.results.length === 0 ? (
          <p style={styles.muted}>{filter === "open" ? "No open complaints - nice." : "No complaints here."}</p>
        ) : (
          <ul style={styles.queue}>
            {complaints.results.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => setOpenId(c.id)} style={{ ...styles.queueRow, ...(c.overdue ? styles.overdueRow : null) }} aria-label={`Open complaint: ${c.subject}`}>
                  <div style={styles.queueMain}>
                    <span style={styles.queueTitle}>
                      {c.urgent && <span style={styles.urgentTag}>Urgent</span>}
                      {c.subject}
                    </span>
                    <span style={styles.queueMeta}>
                      {c.categoryLabel} · {c.member ? c.member.name : "Deleted member"} · {c.createdAt}
                      {c.messageCount ? ` · ${c.messageCount} message${c.messageCount === 1 ? "" : "s"}` : ""}
                    </span>
                  </div>
                  {c.overdue && <span style={styles.overdueTag}>Overdue</span>}
                  {!c.overdue && c.status === "Open" && <span style={styles.dueTag}>Answer by {c.respondBy.slice(5)}</span>}
                  <StatusTag status={c.status} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {summary.coachRatings.length > 0 && (
        <section style={styles.panel} aria-label="Coach ratings">
          <h2 style={styles.panelTitle}>Coach ratings this month</h2>
          <table style={styles.table}>
            <tbody>
              {summary.coachRatings.map((r) => (
                <tr key={r.coachId}>
                  <td style={styles.td}>{r.name}</td>
                  <td style={styles.tdRight}>
                    <strong>{r.average.toFixed(1)}</strong> / 5
                  </td>
                  <td style={styles.tdRight}>{r.count} rating{r.count === 1 ? "" : "s"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {openId && (
        <ComplaintModal
          complaintId={openId}
          responseHours={summary.responseHours}
          onClose={() => setOpenId(null)}
          onChanged={() => {
            loadComplaints();
            loadSummary();
          }}
        />
      )}
    </div>
  );
}

function Tile({ label, value, sub, tone, strong }) {
  return (
    <div style={{ ...styles.tile, ...(strong ? styles.tileStrong : null) }}>
      <span style={styles.tileLabel}>{label}</span>
      <span style={{ ...styles.tileValue, ...(tone && strong ? null : tone ? { color: tone } : null) }}>{value}</span>
      {sub && <span style={{ ...styles.tileSub, ...(tone ? { color: tone } : null) }}>{sub}</span>}
    </div>
  );
}

function AreaBar({ area, weakest }) {
  const pct = area.average === null ? 0 : (area.average / 5) * 100;
  return (
    <div style={styles.area}>
      <div style={styles.areaHead}>
        <span style={styles.areaLabel}>
          {area.label}
          {weakest && <span style={styles.weakTag}>Needs attention</span>}
        </span>
        <span style={styles.areaValue}>
          {area.average === null ? "No ratings" : area.average.toFixed(1)}
          {area.change !== null && area.change !== 0 && (
            <span style={{ color: area.change > 0 ? "#0f6e2b" : "#b3261e" }}> {area.change > 0 ? "▲" : "▼"} {Math.abs(area.change).toFixed(1)}</span>
          )}
        </span>
      </div>
      <div style={styles.bar} role="img" aria-label={`${area.label}: ${area.average ?? "no ratings"} out of 5 from ${area.count} ratings`}>
        <div style={{ ...styles.barFill, width: `${pct}%`, background: weakest ? "#de0b12" : area.average >= 4 ? "#129638" : "#124096" }} />
      </div>
      <span style={styles.areaCount}>{area.count} rating{area.count === 1 ? "" : "s"}</span>
    </div>
  );
}

// One bar per month from the zero line: up for a positive score, down for a negative one.
function NpsTrend({ trend }) {
  const W = 420;
  const H = 182;
  // Room above the top line for a +100 bar's label.
  const pad = { l: 34, r: 8, t: 22, b: 30 };
  const slot = (W - pad.l - pad.r) / trend.length;
  const y = (v) => pad.t + ((100 - v) * (H - pad.t - pad.b)) / 200;
  const label = trend.map((t) => `${t.label}: ${t.nps === null ? "no responses" : t.nps}`).join(", ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Net Promoter Score by month. ${label}`} style={styles.chart}>
      {[100, 50, 0, -50, -100].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke={v === 0 ? "#b9b9c2" : "#ececf0"} />
          <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="10" fill="#777">{v}</text>
        </g>
      ))}
      {trend.map((t, i) => {
        const x = pad.l + i * slot + slot * 0.2;
        const w = slot * 0.6;
        const top = t.nps === null ? y(0) : Math.min(y(0), y(t.nps));
        const height = t.nps === null ? 0 : Math.abs(y(t.nps) - y(0));
        return (
          <g key={t.period}>
            {t.nps !== null && <rect x={x} y={top} width={w} height={Math.max(height, 1)} rx="3" fill={t.nps >= 0 ? "#129638" : "#de0b12"} />}
            <text x={x + w / 2} y={t.nps === null || t.nps >= 0 ? top - 4 : top + height + 12} textAnchor="middle" fontSize="11" fontWeight="700" fill="#333">
              {t.nps === null ? "—" : t.nps}
            </text>
            <text x={x + w / 2} y={H - 14} textAnchor="middle" fontSize="10" fill="#777">{t.label.split(" ")[0]}</text>
            <text x={x + w / 2} y={H - 3} textAnchor="middle" fontSize="9" fill="#aaa">{t.responses} resp.</text>
          </g>
        );
      })}
    </svg>
  );
}

function NpsSplit({ nps }) {
  const parts = [
    ["Promoters", nps.promoters, "#129638"],
    ["Passives", nps.passives, "#c9cdd3"],
    ["Detractors", nps.detractors, "#de0b12"],
  ];
  return (
    <div>
      <div style={styles.split} role="img" aria-label={parts.map(([l, n]) => `${l} ${n}`).join(", ")}>
        {parts.map(([l, n, color]) => n > 0 && <div key={l} style={{ flex: n, background: color }} />)}
      </div>
      <div style={styles.splitLegend}>
        {parts.map(([l, n, color]) => (
          <span key={l}><span style={{ ...styles.dot, background: color }} /> {l} {n}</span>
        ))}
      </div>
    </div>
  );
}

function ComplaintModal({ complaintId, responseHours, onClose, onChanged }) {
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [text, setText] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchComplaint(complaintId).then(setC).catch((e) => setError(e.message));
  }, [complaintId]);

  async function run(action) {
    setBusy(true);
    setError(null);
    try {
      setC(await action());
      setText("");
      setInternal(false);
      onChanged();
    } catch (err) {
      setError(err.fieldErrors?.message?.[0] || err.fieldErrors?.body?.[0] || err.message);
    } finally {
      setBusy(false);
    }
  }

  const resolved = c?.status === "Resolved";
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Complaint">
        <div style={styles.modalHead}>
          <div>
            <h2 style={styles.modalTitle}>
              {c?.urgent && <span style={styles.urgentTag}>Urgent</span>}
              {c ? c.subject : "Complaint"}
            </h2>
            {c && (
              <p style={styles.modalSub}>
                {c.categoryLabel} · {c.branch} · {c.member ? `${c.member.name} (#${c.member.id})` : "Deleted member"}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">&times;</button>
        </div>
        {error && <div style={styles.errorBox}>{error}</div>}
        {!c && !error && <p style={styles.muted}>Loading...</p>}
        {c && (
          <>
            <div style={styles.statusLine}>
              <StatusTag status={c.status} />
              {c.overdue && <span style={styles.overdueTag}>Overdue - no answer in {responseHours} h</span>}
              {!c.overdue && c.firstResponseHours === null && !resolved && <span style={styles.dueTag}>Answer by {c.respondBy}</span>}
              {c.firstResponseHours !== null && <span style={styles.muted}>First answered after {c.firstResponseHours} h</span>}
              {resolved && <span style={styles.muted}>Resolved {c.resolvedAt}{c.resolvedBy ? ` by ${c.resolvedBy}` : ""}</span>}
            </div>
            <ComplaintThread complaint={c} viewer="staff" />
            <div style={styles.replyBox}>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={1000}
                rows={3}
                placeholder={internal ? "A note for staff only - the member won't see it." : resolved ? "Reopen the complaint to reply to the member." : "Reply to the member - they're notified in the app and by email."}
                aria-label="Reply"
                style={{ ...styles.textarea, ...(internal ? styles.internalArea : null) }}
              />
              <div style={styles.replyActions}>
                <label style={styles.check}>
                  <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
                  Internal note (staff only)
                </label>
                <span style={{ flex: 1 }} />
                {resolved ? (
                  <button type="button" onClick={() => run(() => setComplaintStatus(c.id, "Open"))} style={styles.secondaryButton} disabled={busy}>Reopen</button>
                ) : (
                  <button
                    type="button"
                    onClick={() => run(() => setComplaintStatus(c.id, "Resolved", internal ? "" : text))}
                    style={styles.greenButton}
                    disabled={busy}
                    title="Resolve - your text above is sent to the member as the resolution"
                  >
                    {text.trim() && !internal ? "Send & resolve" : "Mark resolved"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => run(() => replyToComplaint(c.id, text, internal))}
                  style={styles.primaryButton}
                  disabled={busy || !text.trim() || (resolved && !internal)}
                >
                  {internal ? "Add note" : "Send reply"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 14px" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  toolbar: { display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" },
  toolField: { display: "flex", flexDirection: "column", gap: 4 },
  toolLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  select: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit" },
  tiles: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 12 },
  tile: { display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  tileStrong: { borderColor: "#124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  tileLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  tileValue: { fontSize: 26, fontWeight: 800 },
  tileSub: { fontSize: 12, color: "#666" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12, marginBottom: 12 },
  panel: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff", marginBottom: 12 },
  panelTitle: { fontSize: 15, fontWeight: 800, margin: "0 0 4px" },
  panelHint: { fontSize: 12, color: "#777", margin: "6px 0 8px" },
  area: { display: "flex", flexDirection: "column", gap: 3, marginBottom: 10 },
  areaHead: { display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 },
  areaLabel: { fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 },
  areaValue: { fontSize: 14, fontWeight: 800 },
  areaCount: { fontSize: 11, color: "#888" },
  weakTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
  bar: { height: 10, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999 },
  chart: { width: "100%", height: "auto", display: "block" },
  split: { display: "flex", height: 12, borderRadius: 999, overflow: "hidden", margin: "8px 0 4px", background: "#ececf0" },
  splitLegend: { display: "flex", gap: 12, fontSize: 12, color: "#555", flexWrap: "wrap" },
  dot: { display: "inline-block", width: 8, height: 8, borderRadius: 999, marginRight: 2 },
  comments: { listStyle: "none", margin: "8px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  comment: { display: "flex", gap: 10, alignItems: "flex-start", fontSize: 14 },
  commentBody: { flex: 1, minWidth: 0, lineHeight: 1.45, overflowWrap: "anywhere" },
  commentMeta: { fontSize: 12, color: "#777", marginTop: 2 },
  npsChip: { flexShrink: 0, width: 28, height: 28, borderRadius: 999, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: "#fff" },
  promoter: { background: "#129638" },
  passive: { background: "#8a8f99" },
  detractor: { background: "#de0b12" },
  queueHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 },
  filters: { display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" },
  filterButton: { padding: "6px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 999, background: "#fff", cursor: "pointer" },
  filterActive: { background: "#124096", borderColor: "#124096", color: "#fff" },
  queue: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  queueRow: { width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  overdueRow: { borderColor: "#f1b0ad", background: "#fff8f7" },
  queueMain: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  queueTitle: { fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 },
  queueMeta: { fontSize: 12, color: "#777" },
  urgentTag: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, ...BUTTON_COLORS.red, marginRight: 6 },
  overdueTag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#fdeceb", color: "#b3261e" },
  dueTag: { flexShrink: 0, fontSize: 11, color: "#8a5300" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14, marginTop: 6 },
  td: { padding: "6px 0", borderBottom: "1px solid #f0f0f2" },
  tdRight: { padding: "6px 0", borderBottom: "1px solid #f0f0f2", textAlign: "right" },
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 50 },
  modal: { background: "#fff", borderRadius: 14, padding: 22, width: "100%", maxWidth: 640, maxHeight: "90vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 12, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: "#1a1a1a" },
  modalHead: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  modalTitle: { fontSize: 18, fontWeight: 800, margin: 0, display: "flex", alignItems: "center" },
  modalSub: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  statusLine: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  replyBox: { display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid #ececf0", paddingTop: 10 },
  textarea: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit", resize: "vertical", boxSizing: "border-box", width: "100%" },
  internalArea: { background: "#faf6fe", borderColor: "#d8c5ee" },
  replyActions: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  check: { display: "flex", alignItems: "center", gap: 6, fontSize: 13 },
  primaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  greenButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.green, cursor: "pointer" },
  secondaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
};

import { useEffect, useState } from "react";
import { fetchReservations } from "../../api/classes.js";
import { addDays, formatDay, weekLabel } from "./dates.js";

// User story (SCRUM-22): "As a general manager, I want to view the class
// reservation schedule for each branch, so that I can monitor class
// utilization and demand."
//
// Read-only. One branch's week: how full each class is, who's waiting for a
// spot, and (once a class is over) how many of the booked members came.
// The cards across the top compare every branch the account can see for
// the same week; clicking one switches to it.

const pct = (value) => (value == null ? "-" : `${value}%`);

// Green when well used, amber when half full, grey when mostly empty.
function fillColor(percent) {
  if (percent == null) return "#c8c8cf";
  if (percent >= 90) return "#129638";
  if (percent >= 50) return "#e8a400";
  return "#9aa0ad";
}

function FillBar({ booked, capacity, percent }) {
  return (
    <div style={styles.fill}>
      <div style={styles.fillTrack} aria-hidden="true">
        <div style={{ ...styles.fillBar, width: `${Math.min(100, percent || 0)}%`, background: fillColor(percent) }} />
      </div>
      <span style={styles.fillText}>{booked}/{capacity}</span>
    </div>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
      {hint && <div style={styles.statHint}>{hint}</div>}
    </div>
  );
}

export default function ClassReservations() {
  const [branch, setBranch] = useState("");
  const [week, setWeek] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchReservations({ week, branch })
      .then((body) => {
        if (cancelled) return;
        setData(body);
        if (!branch) setBranch(body.branch);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [week, branch]);

  const summary = data?.summary;
  const isThisWeek = data && data.days.some((d) => d.isToday);
  const byDay = data ? data.days.map((d) => ({ ...d, classes: data.classes.filter((c) => c.date === d.date) })) : [];

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Class Reservations</h1>
      <p style={styles.subtitle}>How full each branch's classes are, and where demand outruns the spots. View only.</p>
      {error && <div style={styles.errorBox}>{error}</div>}
      {!data && !error && <p style={styles.muted}>Loading...</p>}

      {data && (
        <>
          <div style={styles.toolbar}>
            <div style={styles.weekNav}>
              <button type="button" onClick={() => setWeek(addDays(data.weekStart, -7))} style={styles.navButton} aria-label="Previous week">‹</button>
              <button type="button" onClick={() => setWeek(null)} disabled={isThisWeek} style={styles.todayButton}>This week</button>
              <button type="button" onClick={() => setWeek(addDays(data.weekStart, 7))} style={styles.navButton} aria-label="Next week">›</button>
              <span style={styles.weekLabel}>{weekLabel(data.weekStart, data.weekEnd)}</span>
            </div>
            {data.branches.length > 1 && (
              <label style={styles.field}>
                <span style={styles.fieldLabel}>Branch</span>
                <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.select}>
                  {data.branches.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              </label>
            )}
            {loading && <span style={styles.muted}>Updating...</span>}
          </div>

          {data.branchSummaries.length > 1 && (
            <section aria-label="Branches this week" style={styles.branchGrid}>
              {data.branchSummaries.map((b) => (
                <button
                  key={b.branch}
                  type="button"
                  onClick={() => setBranch(b.branch)}
                  aria-pressed={b.branch === data.branch}
                  style={{ ...styles.branchCard, ...(b.branch === data.branch ? styles.branchCardSelected : null) }}
                >
                  <span style={styles.branchName}>{b.branch}</span>
                  <span style={{ ...styles.branchFill, color: fillColor(b.fillPercent) }}>{pct(b.fillPercent)}</span>
                  <span style={styles.branchMeta}>
                    {b.booked}/{b.spots} spots · {b.classes} class{b.classes === 1 ? "" : "es"}
                    {b.waitlisted ? ` · ${b.waitlisted} waiting` : ""}
                  </span>
                </button>
              ))}
            </section>
          )}

          <section aria-label={`${data.branch} this week`} style={styles.stats}>
            <Stat label="Fill rate" value={pct(summary.fillPercent)} hint={`${summary.booked} of ${summary.spots} spots booked`} />
            <Stat label="Classes" value={summary.classes} hint={summary.cancelled ? `${summary.cancelled} cancelled` : "none cancelled"} />
            <Stat label="Full classes" value={summary.fullClasses} />
            <Stat label="On waitlists" value={summary.waitlisted} hint="wanted a spot in a full class" />
            <Stat
              label="Showed up"
              value={pct(summary.attendancePercent)}
              hint={summary.attended + summary.noShows ? `${summary.attended} came, ${summary.noShows} no-shows` : "no finished classes yet"}
            />
          </section>

          {data.byClassType.length > 0 && (
            <section style={styles.card} aria-label="By class">
              <h2 style={styles.cardTitle}>By class, busiest first</h2>
              <div style={styles.scroll}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Class</th>
                      <th style={styles.th}>Sessions</th>
                      <th style={styles.th}>Booked</th>
                      <th style={styles.th}>Waitlist</th>
                      <th style={styles.th}>Showed up</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.byClassType.map((t) => (
                      <tr key={t.name}>
                        <td style={styles.tdStrong}>{t.name}</td>
                        <td style={styles.td}>{t.classes}{t.cancelled ? ` (+${t.cancelled} cancelled)` : ""}</td>
                        <td style={styles.td}><FillBar booked={t.booked} capacity={t.spots} percent={t.fillPercent} /></td>
                        <td style={styles.td}>{t.waitlisted}</td>
                        <td style={styles.td}>{pct(t.attendancePercent)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section style={styles.card} aria-label="Schedule">
            <h2 style={styles.cardTitle}>Schedule at {data.branch}</h2>
            {data.classes.length === 0 && <div style={styles.empty}>No classes scheduled this week.</div>}
            {data.classes.length > 0 && (
              <div style={styles.scroll}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Time</th>
                      <th style={styles.th}>Class</th>
                      <th style={styles.th}>Coach</th>
                      <th style={styles.th}>Booked</th>
                      <th style={styles.th}>Waitlist</th>
                      <th style={styles.th}>Attendance</th>
                    </tr>
                  </thead>
                  {byDay.filter((d) => d.classes.length > 0).map((d) => (
                    <tbody key={d.date}>
                      <tr>
                        <th colSpan={6} scope="colgroup" style={styles.dayRow}>
                          {formatDay(d.date)}{d.isToday ? " · today" : ""}
                        </th>
                      </tr>
                      {d.classes.map((c) => {
                        const cancelled = c.status === "Cancelled";
                        return (
                          <tr key={c.id} style={cancelled ? styles.cancelledRow : null}>
                            <td style={styles.td}>{c.startTime}–{c.endTime}</td>
                            <td style={styles.tdStrong}>
                              {c.name}
                              {c.room && <span style={styles.roomText}> · {c.room}</span>}
                            </td>
                            <td style={styles.td}>{c.coachName}</td>
                            <td style={styles.td}>
                              {cancelled
                                ? <span style={styles.badge}>Cancelled</span>
                                : <FillBar booked={c.booked} capacity={c.capacity} percent={c.fillPercent} />}
                            </td>
                            <td style={styles.td}>{c.waitlistCount || "-"}</td>
                            <td style={styles.td}>
                              {cancelled ? "-"
                                : !c.ended ? "Upcoming"
                                : c.booked === 0 ? "No bookings"
                                : `${c.attended} came · ${c.noShows} no-show${c.noShows === 1 ? "" : "s"}`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  ))}
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 16px" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  muted: { fontSize: 13, color: "#888" },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 12, fontSize: 14, color: "#888", textAlign: "center" },
  toolbar: { display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap", marginBottom: 14 },
  weekNav: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  navButton: { width: 36, height: 36, fontSize: 20, lineHeight: 1, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  todayButton: { height: 36, padding: "0 14px", fontSize: 14, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  weekLabel: { fontSize: 17, fontWeight: 700, marginLeft: 6 },
  field: { display: "flex", flexDirection: "column", gap: 4 },
  fieldLabel: { fontSize: 12, fontWeight: 700, color: "#444" },
  select: { height: 36, padding: "0 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontWeight: 600 },
  branchGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 14 },
  branchCard: {
    display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, padding: "12px 14px", border: "1px solid #e4e4e8",
    borderRadius: 12, background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit",
  },
  branchCardSelected: { border: "1px solid #124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  branchName: { fontSize: 14, fontWeight: 800 },
  branchFill: { fontSize: 24, fontWeight: 800 },
  branchMeta: { fontSize: 12, color: "#666" },
  stats: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 14 },
  stat: { padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  statValue: { fontSize: 24, fontWeight: 800 },
  statLabel: { fontSize: 13, fontWeight: 700, color: "#444" },
  statHint: { fontSize: 12, color: "#888", marginTop: 2 },
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff", marginBottom: 14, minWidth: 0 },
  cardTitle: { fontSize: 15, fontWeight: 800, margin: "0 0 10px" },
  scroll: { overflowX: "auto" },
  table: { width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", fontSize: 12, fontWeight: 700, color: "#666", borderBottom: "1px solid #e4e4e8", whiteSpace: "nowrap" },
  td: { padding: "8px 10px", borderBottom: "1px solid #f0f0f3", whiteSpace: "nowrap" },
  tdStrong: { padding: "8px 10px", borderBottom: "1px solid #f0f0f3", fontWeight: 700 },
  dayRow: { textAlign: "left", padding: "12px 10px 6px", fontSize: 13, fontWeight: 800, color: "#124096", borderBottom: "1px solid #e4e4e8" },
  cancelledRow: { color: "#999" },
  roomText: { fontWeight: 400, color: "#888" },
  badge: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: "#ececf0", color: "#666" },
  fill: { display: "flex", alignItems: "center", gap: 8 },
  fillTrack: { width: 90, height: 8, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  fillBar: { height: "100%", borderRadius: 999 },
  fillText: { fontVariantNumeric: "tabular-nums", minWidth: 44 },
};

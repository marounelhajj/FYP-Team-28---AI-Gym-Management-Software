// One coach's pay for one pay period, as the server works it out
// (payroll/pay.py): the totals, the rates that applied, and every session
// with the rate and amount it was paid - so each figure can be checked
// line by line. Shared by the coach's own My Pay and the branch manager's
// view of it.

const KIND_LABELS = { class: "Class", pt: "Private" };

export function formatMoney(value) {
  if (value === null || value === undefined) return "—";
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatHours(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function formatDay(iso, withYear = false) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: withYear ? undefined : "short",
    day: "numeric",
    month: "short",
    year: withYear ? "numeric" : undefined,
  });
}

export function periodLabel(key) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function rateText(rate) {
  return `${formatMoney(rate.classHourly)}/h classes · ${formatMoney(rate.ptHourly)}/h private training`;
}

// A CSV of the statement, to compare against a payslip or keep.
function downloadCsv(data) {
  const rows = [["Date", "Start", "End", "Minutes", "Type", "Session", "Branch", "Status", "Rate per hour", "Amount", "Note"]];
  const add = (lines, status) =>
    lines.forEach((l) =>
      rows.push([l.date, l.startTime, l.endTime, l.minutes, KIND_LABELS[l.kind], l.title, l.branch, status,
        l.hourlyRate ?? "", l.amount ?? "", l.reason || l.detail]),
    );
  add(data.completed, "Completed");
  add(data.upcoming, "Not yet taught");
  add(data.cancelled, "Cancelled");
  rows.push([]);
  rows.push(["Total earned", "", "", data.summary.minutes, "", `${data.summary.completed} sessions`, "", "", "", data.summary.earnings, ""]);
  const csv = rows.map((r) => r.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `pay-${data.coach.name.toLowerCase().replaceAll(" ", "-")}-${data.period.key}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function PayStatement({ data, period, onPeriod, loading }) {
  const { summary, rates } = data;
  const changed = rates.changedDuringPeriod;
  return (
    <div>
      <div style={styles.toolbar}>
        <label style={styles.periodField}>
          <span style={styles.periodLabel}>Pay period</span>
          <select value={period || data.period.key} onChange={(e) => onPeriod(e.target.value)} style={styles.select} aria-label="Pay period">
            {data.periods.map((key, i) => (
              <option key={key} value={key}>
                {periodLabel(key)}
                {i === 0 ? " (current)" : ""}
              </option>
            ))}
          </select>
        </label>
        <span style={styles.range}>
          {formatDay(data.period.start, true)} – {formatDay(data.period.end, true)}
          {data.period.isCurrent && ` · ${data.period.daysLeft} day${data.period.daysLeft === 1 ? "" : "s"} left`}
          {loading && " · updating..."}
        </span>
        <button type="button" onClick={() => downloadCsv(data)} style={styles.csvButton}>
          Download CSV
        </button>
      </div>

      <div style={styles.tiles}>
        <Tile label="Completed sessions" value={summary.completed} sub={`${summary.classes} class${summary.classes === 1 ? "" : "es"} · ${summary.privateSessions} private`} />
        <Tile label="Hours taught" value={formatHours(summary.minutes)} />
        <Tile label={data.period.isCurrent ? "Earned so far" : "Earned"} value={formatMoney(summary.earnings)} strong />
        {data.period.isCurrent && (
          <Tile
            label="Still to come this period"
            value={summary.upcoming ? `+${formatMoney(summary.upcomingEstimate)}` : "—"}
            sub={summary.upcoming ? `${summary.upcoming} session${summary.upcoming === 1 ? "" : "s"} · estimate if taught` : "Nothing else scheduled"}
          />
        )}
      </div>

      {summary.unrated > 0 && (
        <div style={styles.warnBox}>
          {summary.unrated} completed session{summary.unrated === 1 ? " has" : "s have"} no pay rate for {summary.unrated === 1 ? "its" : "their"} date,
          so {summary.unrated === 1 ? "it isn't" : "they aren't"} in the total. Ask your branch manager to set your rate.
        </div>
      )}

      <div style={styles.rateBox}>
        <div style={styles.rateTitle}>Rates for this period</div>
        {rates.atPeriodStart ? (
          <div style={styles.rateLine}>
            From {formatDay(data.period.start)}: {rateText(rates.atPeriodStart)}
          </div>
        ) : (
          !changed.length && <div style={styles.rateLine}>No pay rate set yet.</div>
        )}
        {changed.map((r) => (
          <div key={r.id} style={styles.rateLine}>
            From {formatDay(r.effectiveFrom)}: {rateText(r)}
            {r.note && <span style={styles.rateNote}> · {r.note}</span>}
          </div>
        ))}
        {data.period.isCurrent &&
          rates.scheduled.map((r) => (
            <div key={r.id} style={styles.rateScheduled}>
              Coming {formatDay(r.effectiveFrom, true)}: {rateText(r)}
            </div>
          ))}
        <div style={styles.rateHint}>Each session is paid at its rate × its length. Sessions that ran over or started late are paid as scheduled.</div>
      </div>

      <h3 style={styles.section}>Completed ({summary.completed})</h3>
      {data.completed.length === 0 ? (
        <div style={styles.empty}>No completed sessions in this period yet.</div>
      ) : (
        <LineTable lines={data.completed} total={summary.earnings} minutes={summary.minutes} />
      )}

      {data.upcoming.length > 0 && (
        <>
          <h3 style={styles.section}>Not taught yet ({data.upcoming.length})</h3>
          <p style={styles.muted}>Paid once they've ended. Amounts are what they'll pay at the rate for their date.</p>
          <LineTable lines={data.upcoming} muted />
        </>
      )}

      {data.cancelled.length > 0 && (
        <>
          <h3 style={styles.section}>Cancelled - not paid ({data.cancelled.length})</h3>
          <LineTable lines={data.cancelled} muted cancelled />
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub, strong }) {
  return (
    <div style={{ ...styles.tile, ...(strong ? styles.tileStrong : null) }}>
      <span style={styles.tileLabel}>{label}</span>
      <span style={styles.tileValue}>{value}</span>
      {sub && <span style={styles.tileSub}>{sub}</span>}
    </div>
  );
}

function LineTable({ lines, total, minutes, muted, cancelled }) {
  return (
    <div style={styles.tableWrap}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Date</th>
            <th style={styles.th}>Session</th>
            <th style={styles.th}>Length</th>
            {!cancelled && <th style={styles.thRight}>Rate</th>}
            <th style={styles.thRight}>{cancelled ? "Reason" : "Amount"}</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={`${l.kind}-${l.id}`} style={muted ? styles.rowMuted : null}>
              <td style={styles.tdNoWrap}>
                {formatDay(l.date)}
                <div style={styles.cellSub}>
                  {l.startTime}–{l.endTime}
                </div>
              </td>
              <td style={styles.td}>
                <span style={l.kind === "pt" ? styles.ptTag : styles.classTag}>{KIND_LABELS[l.kind]}</span> {l.title}
                <div style={styles.cellSub}>
                  {l.branch}
                  {l.detail && ` · ${l.detail}`}
                  {l.state === "in_progress" && " · in progress"}
                </div>
              </td>
              <td style={styles.tdNoWrap}>{formatHours(l.minutes)}</td>
              {!cancelled && <td style={styles.tdRight}>{l.hourlyRate ? `${formatMoney(l.hourlyRate)}/h` : <span style={styles.noRate}>No rate</span>}</td>}
              <td style={cancelled ? styles.tdReason : styles.tdAmount}>{cancelled ? l.reason || "Cancelled" : formatMoney(l.amount)}</td>
            </tr>
          ))}
        </tbody>
        {total !== undefined && (
          <tfoot>
            <tr>
              <td style={styles.tfoot} colSpan={2}>
                Total
              </td>
              <td style={styles.tfoot}>{formatHours(minutes)}</td>
              <td style={styles.tfoot} />
              <td style={{ ...styles.tfoot, textAlign: "right" }}>{formatMoney(total)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

export const styles = {
  toolbar: { display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap", marginBottom: 14 },
  periodField: { display: "flex", flexDirection: "column", gap: 4 },
  periodLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit" },
  range: { fontSize: 13, color: "#666", paddingBottom: 9, flex: 1 },
  csvButton: { padding: "8px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  tiles: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 14 },
  tile: { display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  tileStrong: { borderColor: "#124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  tileLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  tileValue: { fontSize: 24, fontWeight: 800 },
  tileSub: { fontSize: 12, color: "#666" },
  warnBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 12, lineHeight: 1.45 },
  rateBox: { padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fafafb", marginBottom: 6 },
  rateTitle: { fontSize: 13, fontWeight: 700, marginBottom: 6 },
  rateLine: { fontSize: 13, marginBottom: 3 },
  rateNote: { color: "#666" },
  rateScheduled: { fontSize: 13, color: "#124096", marginBottom: 3 },
  rateHint: { fontSize: 12, color: "#777", marginTop: 6 },
  section: { fontSize: 15, fontWeight: 800, margin: "18px 0 8px" },
  muted: { fontSize: 12, color: "#777", margin: "-4px 0 8px" },
  empty: { padding: 16, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  tableWrap: { border: "1px solid #e4e4e8", borderRadius: 10, overflow: "auto", background: "#fff" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" },
  thRight: { textAlign: "right", padding: "8px 10px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" },
  td: { padding: "8px 10px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top" },
  tdNoWrap: { padding: "8px 10px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", whiteSpace: "nowrap" },
  tdRight: { padding: "8px 10px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", whiteSpace: "nowrap", textAlign: "right" },
  tdAmount: { padding: "8px 10px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", whiteSpace: "nowrap", textAlign: "right", fontWeight: 700 },
  tdReason: { padding: "8px 10px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", textAlign: "right", color: "#b3261e" },
  rowMuted: { color: "#66666e", background: "#fafafb" },
  cellSub: { fontSize: 11, color: "#888", marginTop: 2 },
  classTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#eef2fa", color: "#124096" },
  ptTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#f3ecfb", color: "#6a2fa0" },
  noRate: { fontSize: 11, fontWeight: 700, color: "#8a5300" },
  tfoot: { padding: "10px", fontWeight: 800, borderTop: "2px solid #e4e4e8", background: "#fafafb" },
};

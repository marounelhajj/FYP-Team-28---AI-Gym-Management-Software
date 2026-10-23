import { useEffect, useState } from "react";
import { fetchAuditLogMeta, fetchRetentionReport } from "../../api/audit.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const PAGE_SIZE = 25;
const EMPTY_FILTERS = { branch: "", dateFrom: "", dateTo: "" };

const ACTION_LABELS = {
  "member.frozen": "Frozen",
  "member.cancelled": "Cancelled",
};
const ACTION_COLORS = {
  "member.frozen": BUTTON_COLORS.blue,
  "member.cancelled": BUTTON_COLORS.red,
};

function formatWhen(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// A branch's own freeze/cancel counts against the heaviest branch in view,
// so an outlier is visible at a glance without needing a chart library.
function BranchBar({ value, max }) {
  const width = max === 0 ? 0 : Math.max(4, Math.round((value / max) * 100));
  return (
    <div style={styles.barTrack}>
      <div style={{ ...styles.barFill, width: `${width}%` }} />
    </div>
  );
}

// General Manager (and System Administrator, from the Admin Console) view
// of freezes and cancellations across branches - a focused read of the
// audit log (reuses its model, permission and branch/date filters), not a
// second place anything gets logged.
//
// User story: "As a general manager, I want to view a history of
// membership freezes and cancellations by branch, so that I can spot
// patterns affecting retention."
export default function RetentionReport() {
  const [branches, setBranches] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ branches: [], totals: { frozen: 0, cancelled: 0, total: 0 }, events: { total: 0, results: [] } });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchAuditLogMeta()
      .then((meta) => setBranches(meta.branches))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchRetentionReport(filters, { limit: PAGE_SIZE, offset })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filters, offset]);

  function setFilter(key, value) {
    setFilters((f) => (f[key] === value ? f : { ...f, [key]: value }));
    setOffset(0);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setOffset(0);
  }

  const hasFilters = Object.values(filters).some(Boolean);
  const maxTotal = Math.max(1, ...data.branches.map((b) => b.total));
  const events = data.events.results;
  const from = data.events.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.events.total);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>Retention: Freezes &amp; Cancellations</h1>
        <p style={styles.subtitle}>
          How often members freeze or cancel their membership, broken down by branch, so a branch-specific problem
          doesn't hide in the org-wide number.
        </p>
      </div>

      <div style={styles.filters}>
        <label style={styles.field}>
          <span style={styles.fieldLabel}>Branch</span>
          <select value={filters.branch} onChange={(e) => setFilter("branch", e.target.value)} style={styles.input}>
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>From</span>
          <input
            type="date"
            value={filters.dateFrom}
            max={filters.dateTo || undefined}
            onChange={(e) => setFilter("dateFrom", e.target.value)}
            style={styles.input}
          />
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>To</span>
          <input
            type="date"
            value={filters.dateTo}
            min={filters.dateFrom || undefined}
            onChange={(e) => setFilter("dateTo", e.target.value)}
            style={styles.input}
          />
        </label>

        {hasFilters && (
          <button onClick={clearFilters} style={styles.clearButton}>
            Clear filters
          </button>
        )}
      </div>

      {error && <div style={styles.errorBox}>Couldn't load the report: {error}</div>}

      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Branch</th>
              <th style={styles.th}>Frozen</th>
              <th style={styles.th}>Cancelled</th>
              <th style={styles.th}>Total</th>
              <th style={styles.th}></th>
            </tr>
          </thead>
          <tbody>
            {data.branches.map((b) => (
              <tr key={b.branch}>
                <td style={{ ...styles.td, fontWeight: 600 }}>{b.branch}</td>
                <td style={styles.td}>{b.frozen}</td>
                <td style={styles.td}>{b.cancelled}</td>
                <td style={{ ...styles.td, fontWeight: 600 }}>{b.total}</td>
                <td style={{ ...styles.td, width: 160 }}>
                  <BranchBar value={b.total} max={maxTotal} />
                </td>
              </tr>
            ))}
          </tbody>
          {data.branches.length > 0 && (
            <tfoot>
              <tr>
                <td style={{ ...styles.td, ...styles.totalRow }}>All branches</td>
                <td style={{ ...styles.td, ...styles.totalRow }}>{data.totals.frozen}</td>
                <td style={{ ...styles.td, ...styles.totalRow }}>{data.totals.cancelled}</td>
                <td style={{ ...styles.td, ...styles.totalRow }}>{data.totals.total}</td>
                <td style={{ ...styles.td, ...styles.totalRow }}></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <h2 style={styles.sectionTitle}>History</h2>
      {loading && <div style={styles.empty}>Loading...</div>}
      {!loading && events.length === 0 && <div style={styles.empty}>No freezes or cancellations match these filters.</div>}

      {!loading && events.length > 0 && (
        <>
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>When</th>
                  <th style={styles.th}>Branch</th>
                  <th style={styles.th}>Action</th>
                  <th style={styles.th}>Member</th>
                  <th style={styles.th}>Summary</th>
                </tr>
              </thead>
              <tbody>
                {events.map((entry) => (
                  <tr key={entry.id}>
                    <td style={styles.td}>{formatWhen(entry.createdAt)}</td>
                    <td style={styles.td}>{entry.branch || "—"}</td>
                    <td style={styles.td}>
                      <span style={{ ...styles.badge, ...(ACTION_COLORS[entry.action] || {}) }}>
                        {ACTION_LABELS[entry.action] || entry.actionLabel}
                      </span>
                    </td>
                    <td style={styles.td}>{entry.targetLabel || "—"}</td>
                    <td style={styles.td}>{entry.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={styles.pager}>
            <span style={styles.countRow}>
              {data.events.total === 0 ? "No entries" : `${from}-${to} of ${data.events.total}`}
            </span>
            <div style={styles.pagerButtons}>
              <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} style={styles.pageButton}>
                Previous
              </button>
              <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={to >= data.events.total} style={styles.pageButton}>
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1100,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  filters: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: 12,
    padding: 14,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 16,
  },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "1 1 150px", minWidth: 0 },
  fieldLabel: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: {
    padding: "8px 10px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    width: "100%",
    boxSizing: "border-box",
  },
  clearButton: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    color: "#444",
    cursor: "pointer",
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  tableWrap: {
    overflowX: "auto",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 16,
  },
  table: { width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "middle" },
  totalRow: { fontWeight: 700, background: "#fafafb", borderTop: "2px solid #e4e4e8", borderBottom: "none" },
  barTrack: { height: 8, borderRadius: 999, background: "#eef1f8", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999, background: "#124096" },
  sectionTitle: { fontSize: 16, fontWeight: 700, margin: "4px 0 10px" },
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  badge: {
    display: "inline-block",
    fontSize: 12,
    fontWeight: 600,
    padding: "3px 9px",
    borderRadius: 999,
    whiteSpace: "nowrap",
  },
  pager: { display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 },
  countRow: { fontSize: 13, color: "#666" },
  pagerButtons: { display: "flex", gap: 8 },
  pageButton: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#444",
    cursor: "pointer",
  },
};

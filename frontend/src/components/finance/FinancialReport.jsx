import { useEffect, useState } from "react";
import { fetchFinanceMeta, fetchFinancialReport } from "../../api/finance.js";

const EMPTY_FILTERS = { branch: "", dateFrom: "", dateTo: "" };

function money(value) {
  return `$${value}`;
}

// A branch's revenue/expenses against the biggest number in view, so an
// outlier branch is visible at a glance without a chart library - same
// idea as audit/RetentionReport.jsx's BranchBar.
function CompareBar({ value, max, color }) {
  const width = max === 0 ? 0 : Math.max(2, Math.round((Number(value) / max) * 100));
  return (
    <div style={styles.barTrack}>
      <div style={{ ...styles.barFill, width: `${width}%`, background: color }} />
    </div>
  );
}

function CategoryBreakdown({ expensesByCategory }) {
  const entries = Object.entries(expensesByCategory || {});
  if (entries.length === 0) return null;
  return (
    <div style={styles.cellSub}>
      {entries.map(([category, amount]) => `${category}: $${amount}`).join(" · ")}
    </div>
  );
}

// General Manager (and System Administrator, from the Admin Console) view
// of revenue and expenses by branch - revenue is billing.Payment.amount,
// summed by the paying member's branch; expenses come from the Expense
// ledger (see the "Expenses" screen, manage_billing). A Branch Manager
// (view_financial_reports only, no view_all_branches) only ever sees
// their own branch - enforced server-side, this screen just has no
// branch picker to show them in that case.
//
// User story: "As a general manager, I want to view expense and revenue
// data for each branch, so that I can monitor financial performance and
// compare branches."
export default function FinancialReport() {
  const [branches, setBranches] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [data, setData] = useState({ branches: [], totals: { revenue: "0.00", expenses: "0.00", net: "0.00" } });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchFinanceMeta()
      .then((meta) => setBranches(meta.branches))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchFinancialReport(filters)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filters]);

  function setFilter(key, value) {
    setFilters((f) => (f[key] === value ? f : { ...f, [key]: value }));
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
  }

  const hasFilters = Object.values(filters).some(Boolean);
  const maxRevenue = Math.max(1, ...data.branches.map((b) => Number(b.revenue)));
  const maxExpenses = Math.max(1, ...data.branches.map((b) => Number(b.expenses)));
  const netIsNegative = Number(data.totals.net) < 0;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>Financial Report</h1>
        <p style={styles.subtitle}>
          Revenue and expenses by branch, so a branch-specific problem doesn't hide in the org-wide number.
        </p>
      </div>

      <div style={styles.filters}>
        {branches.length > 1 && (
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
        )}

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
      {loading && <div style={styles.empty}>Loading...</div>}

      {!loading && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Branch</th>
                <th style={styles.th}>Revenue</th>
                <th style={styles.th}>Expenses</th>
                <th style={styles.th}>Net</th>
              </tr>
            </thead>
            <tbody>
              {data.branches.map((b) => (
                <tr key={b.branch}>
                  <td style={{ ...styles.td, fontWeight: 600 }}>{b.branch}</td>
                  <td style={styles.td}>
                    {money(b.revenue)}
                    <CompareBar value={b.revenue} max={maxRevenue} color="#0f6e2b" />
                  </td>
                  <td style={styles.td}>
                    {money(b.expenses)}
                    <CompareBar value={b.expenses} max={maxExpenses} color="#b3261e" />
                    <CategoryBreakdown expensesByCategory={b.expensesByCategory} />
                  </td>
                  <td style={{ ...styles.td, fontWeight: 600, color: Number(b.net) < 0 ? "#b3261e" : "#0f6e2b" }}>
                    {money(b.net)}
                  </td>
                </tr>
              ))}
            </tbody>
            {data.branches.length > 0 && (
              <tfoot>
                <tr>
                  <td style={{ ...styles.td, ...styles.totalRow }}>All branches</td>
                  <td style={{ ...styles.td, ...styles.totalRow }}>{money(data.totals.revenue)}</td>
                  <td style={{ ...styles.td, ...styles.totalRow }}>{money(data.totals.expenses)}</td>
                  <td style={{ ...styles.td, ...styles.totalRow, color: netIsNegative ? "#b3261e" : "#0f6e2b" }}>
                    {money(data.totals.net)}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1000,
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
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  tableWrap: {
    overflowX: "auto",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
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
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "top" },
  totalRow: { fontWeight: 700, background: "#fafafb", borderTop: "2px solid #e4e4e8", borderBottom: "none" },
  barTrack: { height: 6, width: 140, borderRadius: 999, background: "#eef1f8", overflow: "hidden", marginTop: 4 },
  barFill: { height: "100%", borderRadius: 999 },
  cellSub: { fontSize: 11, color: "#888", marginTop: 4 },
};

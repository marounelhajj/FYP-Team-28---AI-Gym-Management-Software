import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteExpense,
  fetchBranchFinances,
  fetchExpenses,
  fetchFinanceMeta,
  recordExpense,
  updateExpense,
} from "../../api/finance.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const PERIODS = [
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "custom", label: "Custom" },
];
const SOURCE_LABELS = { firstPayments: "First payments", renewals: "Renewals", retail: "Retail sales" };
const GREEN = "#0f6e2b";
const RED = "#b3261e";
const EMPTY_FORM = { category: "", amount: "", incurredOn: "", note: "" };

function money(value) {
  const n = Number(value);
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function isoDate(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Branch Manager view of one branch's money for a period: revenue by source,
// expenses by category, net, a revenue-vs-expenses chart, and the expense
// ledger they maintain (add / edit / delete). The server holds a Branch
// Manager to their own branch (finance.views.branch_finances reuses the live
// headcount rule from SCRUM-127); a General Manager gets a branch picker.
//
// User story (SCRUM-26): "As a branch manager, I want to view my branch's
// expenses and revenue, so that I can manage the local budget."
export default function BranchFinances() {
  const [meta, setMeta] = useState({ branches: [], categories: [] });
  const [branch, setBranch] = useState("");
  const [period, setPeriod] = useState("this_month");
  const [custom, setCustom] = useState(() => {
    const today = new Date();
    return { dateFrom: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)), dateTo: isoDate(today) };
  });
  const [summary, setSummary] = useState(null);
  const [expenses, setExpenses] = useState({ total: 0, results: [] });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

  const [editing, setEditing] = useState(null); // null | "new" | expense
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    fetchFinanceMeta()
      .then(setMeta)
      .catch(() => {});
  }, []);

  const customReady = period !== "custom" || (custom.dateFrom && custom.dateTo && custom.dateFrom <= custom.dateTo);

  useEffect(() => {
    if (!customReady) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const range = period === "custom" ? custom : {};
    fetchBranchFinances({ branch, period, ...range })
      .then(async (data) => {
        // The ledger needs manage_billing; a role that can only view the
        // numbers still gets the summary, just with an empty list.
        const list = await fetchExpenses(
          { branch: data.branch, dateFrom: data.dateFrom, dateTo: data.dateTo },
          { limit: 100 },
        ).catch(() => ({ total: 0, results: [] }));
        if (cancelled) return;
        setSummary(data);
        setExpenses(list);
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [branch, period, custom, customReady, reloadKey]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  function openForm(expense) {
    setFieldErrors({});
    setFormError(null);
    setEditing(expense || "new");
    setForm(
      expense
        ? { category: expense.category, amount: expense.amount, incurredOn: expense.incurredOn, note: expense.note }
        : { ...EMPTY_FORM, category: meta.categories[0] || "", incurredOn: isoDate(new Date()) },
    );
  }

  function closeForm() {
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  async function saveExpense(e) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    setFieldErrors({});
    try {
      const body = { ...form, branch: summary.branch };
      if (editing === "new") await recordExpense(body);
      else await updateExpense(editing.id, body);
      setNotice(editing === "new" ? "Expense added." : "Expense updated.");
      closeForm();
      setReloadKey((k) => k + 1);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setFormError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function removeExpense(expense) {
    setSaving(true);
    setError(null);
    try {
      await deleteExpense(expense.id);
      setDeletingId(null);
      setNotice("Expense deleted.");
      setReloadKey((k) => k + 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const net = summary ? Number(summary.net) : 0;
  const canManage = summary?.canManageExpenses;

  return (
    <div style={styles.page}>
      <style>{CSS}</style>
      <div style={styles.header}>
        <h1 style={styles.title}>Branch Finances</h1>
        <p style={styles.subtitle}>Revenue, expenses and net for one branch, so you can manage the local budget.</p>
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <section style={styles.card} aria-label="Branch summary">
        <div style={styles.cardHeader}>
          <div style={styles.headline}>
            <span style={styles.count}>{summary ? summary.branch : "—"}</span>
            <span style={styles.countLabel}>
              {summary ? `${summary.dateFrom} to ${summary.dateTo}` : "Loading"}
            </span>
          </div>

          <div style={styles.controls}>
            <div role="radiogroup" aria-label="Period" style={styles.tray}>
              {PERIODS.map((p) => {
                const selected = p.value === period;
                return (
                  <button
                    key={p.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    className="bf-tab"
                    onClick={() => setPeriod(p.value)}
                    style={selected ? { ...styles.tab, ...styles.tabSelected } : styles.tab}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>

            {summary?.canChooseBranch && (
              <label style={styles.field}>
                <span style={styles.srOnly}>Branch</span>
                <select
                  value={branch || summary.branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="bf-select"
                  style={styles.select}
                  aria-label="Branch"
                >
                  {summary.branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>

        {period === "custom" && (
          <div style={styles.customRow}>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>From</span>
              <input
                type="date"
                value={custom.dateFrom}
                max={custom.dateTo || undefined}
                onChange={(e) => setCustom((c) => ({ ...c, dateFrom: e.target.value }))}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>To</span>
              <input
                type="date"
                value={custom.dateTo}
                min={custom.dateFrom || undefined}
                onChange={(e) => setCustom((c) => ({ ...c, dateTo: e.target.value }))}
                style={styles.input}
              />
            </label>
            {!customReady && <span style={styles.hint}>Choose a start date on or before the end date.</span>}
          </div>
        )}

        {summary && (
          <div style={{ opacity: loading ? 0.55 : 1 }} className="bf-body">
            <div style={styles.kpis}>
              <Kpi label="Revenue" value={money(summary.revenue)} color={GREEN} />
              <Kpi label="Expenses" value={money(summary.expenses)} color={RED} />
              <Kpi label="Net" value={money(summary.net)} color={net < 0 ? RED : GREEN} strong />
            </div>

            <Chart series={summary.series} granularity={summary.granularity} />

            <div style={styles.breakdowns}>
              <Breakdown
                title="Revenue by source"
                color={GREEN}
                rows={Object.entries(summary.revenueBySource).map(([key, amount]) => [SOURCE_LABELS[key] || key, amount])}
                total={summary.revenue}
              />
              <Breakdown
                title="Expenses by category"
                color={RED}
                rows={Object.entries(summary.expensesByCategory)}
                total={summary.expenses}
                empty="No expenses in this period."
              />
            </div>
          </div>
        )}
      </section>

      <section style={{ ...styles.card, marginTop: 20 }} aria-label="Expenses">
        <div style={styles.cardHeader}>
          <div style={styles.headline}>
            <span style={styles.countLabelStrong}>Expenses</span>
            <span style={styles.count}>{expenses.total}</span>
          </div>
          {canManage && !editing && (
            <button type="button" className="bf-press" onClick={() => openForm(null)} style={styles.primaryButton}>
              Add expense
            </button>
          )}
        </div>

        {editing && (
          <form onSubmit={saveExpense} style={styles.form} aria-label={editing === "new" ? "Add expense" : "Edit expense"}>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>Category</span>
              <select
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                className="bf-select"
                style={styles.select}
              >
                {meta.categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              {fieldErrors.category && <span style={styles.fieldError}>{fieldErrors.category}</span>}
            </label>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>Amount ($)</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                style={styles.input}
                required
              />
              {fieldErrors.amount && <span style={styles.fieldError}>{fieldErrors.amount}</span>}
            </label>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>Date</span>
              <input
                type="date"
                value={form.incurredOn}
                onChange={(e) => setForm((f) => ({ ...f, incurredOn: e.target.value }))}
                style={styles.input}
                required
              />
              {fieldErrors.incurredOn && <span style={styles.fieldError}>{fieldErrors.incurredOn}</span>}
            </label>
            <label style={{ ...styles.field, flex: "2 1 220px" }}>
              <span style={styles.fieldLabel}>Note</span>
              <input
                type="text"
                value={form.note}
                maxLength={255}
                onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                style={styles.input}
              />
            </label>
            {formError && <div style={{ ...styles.errorBox, flexBasis: "100%" }}>{formError}</div>}
            <div style={styles.formActions}>
              <button type="button" onClick={closeForm} disabled={saving} className="bf-press" style={styles.secondaryButton}>
                Cancel
              </button>
              <button type="submit" disabled={saving} className="bf-press" style={styles.primaryButton}>
                {saving ? "Saving..." : editing === "new" ? "Add expense" : "Save changes"}
              </button>
            </div>
          </form>
        )}

        {expenses.results.length === 0 ? (
          <div style={styles.empty}>No expenses recorded for this period.</div>
        ) : (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Date</th>
                  <th style={styles.th}>Category</th>
                  <th style={styles.th}>Note</th>
                  <th style={{ ...styles.th, textAlign: "right" }}>Amount</th>
                  {canManage && <th style={styles.th} />}
                </tr>
              </thead>
              <tbody>
                {expenses.results.map((x) => (
                  <tr key={x.id}>
                    <td style={styles.tdNoWrap}>{x.incurredOn}</td>
                    <td style={{ ...styles.td, fontWeight: 700 }}>{x.category}</td>
                    <td style={{ ...styles.td, color: "#666" }}>{x.note || "—"}</td>
                    <td style={{ ...styles.tdNoWrap, textAlign: "right", fontWeight: 800 }}>{money(x.amount)}</td>
                    {canManage && (
                      <td style={{ ...styles.tdNoWrap, textAlign: "right" }}>
                        {deletingId === x.id ? (
                          <span style={styles.rowActions}>
                            <button type="button" className="bf-press" disabled={saving} onClick={() => setDeletingId(null)} style={styles.smallButton}>
                              Keep
                            </button>
                            <button type="button" className="bf-press" disabled={saving} onClick={() => removeExpense(x)} style={styles.dangerButton}>
                              {saving ? "Deleting..." : "Delete"}
                            </button>
                          </span>
                        ) : (
                          <span style={styles.rowActions}>
                            <button
                              type="button"
                              className="bf-press"
                              onClick={() => openForm(x)}
                              style={styles.smallButton}
                              aria-label={`Edit ${x.category} expense of ${money(x.amount)} on ${x.incurredOn}`}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="bf-press"
                              onClick={() => setDeletingId(x.id)}
                              style={styles.smallButton}
                              aria-label={`Delete ${x.category} expense of ${money(x.amount)} on ${x.incurredOn}`}
                            >
                              Delete
                            </button>
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {expenses.total > expenses.results.length && (
          <div style={styles.hint}>
            Showing the {expenses.results.length} most recent of {expenses.total} expenses.
          </div>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value, color, strong }) {
  return (
    <div style={{ ...styles.kpi, ...(strong ? styles.kpiStrong : null) }}>
      <div style={styles.kpiLabel}>{label}</div>
      <div style={{ ...styles.kpiValue, color }}>{value}</div>
    </div>
  );
}

function Breakdown({ title, rows, total, color, empty }) {
  const sum = Number(total) || 0;
  return (
    <div style={styles.breakdown}>
      <h3 style={styles.breakdownTitle}>{title}</h3>
      {rows.length === 0 && <div style={styles.hint}>{empty}</div>}
      {rows.map(([name, amount]) => {
        const pct = sum === 0 ? 0 : Math.round((Number(amount) / sum) * 100);
        return (
          <div key={name} style={styles.breakdownRow}>
            <div style={styles.breakdownLine}>
              <span style={styles.breakdownName}>{name}</span>
              <span style={styles.breakdownAmount}>{money(amount)}</span>
            </div>
            <div style={styles.barTrack} aria-hidden="true">
              <div style={{ ...styles.barFill, width: `${Math.max(pct, Number(amount) > 0 ? 3 : 0)}%`, background: color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Grouped bars (revenue / expenses) per day, or per month for long ranges.
// Plain SVG: the app has no chart library.
function Chart({ series, granularity }) {
  const W = 720;
  const H = 230;
  const pad = { top: 12, right: 8, bottom: 28, left: 52 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;

  const { max, ticks } = useMemo(() => {
    // At least 3 so an empty (or tiny) period still gets whole-dollar ticks.
    const top = Math.max(3, ...series.flatMap((p) => [Number(p.revenue), Number(p.expenses)]));
    const step = niceStep(top / 3);
    const maxValue = step * Math.ceil(top / step);
    return { max: maxValue, ticks: [0, 1, 2, 3].map((i) => (maxValue / 3) * i) };
  }, [series]);

  const slot = innerW / Math.max(1, series.length);
  const barW = Math.max(2, Math.min(18, slot * 0.36));
  const labelEvery = Math.max(1, Math.ceil(series.length / 8));
  const anyData = series.some((p) => Number(p.revenue) > 0 || Number(p.expenses) > 0);
  const y = (v) => pad.top + innerH - (v / max) * innerH;

  const label = (key) => (granularity === "month" ? key : key.slice(5).replace("-", "/"));
  const summary = `Revenue versus expenses, ${series.length} ${granularity === "month" ? "months" : "days"}.`;

  return (
    <figure style={styles.chartFigure}>
      <div style={styles.legend}>
        <span style={styles.legendItem}>
          <i style={{ ...styles.swatch, background: GREEN }} /> Revenue
        </span>
        <span style={styles.legendItem}>
          <i style={{ ...styles.swatch, background: RED }} /> Expenses
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} style={styles.chart}>
        <title>{summary}</title>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={W - pad.right} y1={y(t)} y2={y(t)} stroke="#ececf0" />
            <text x={pad.left - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#666">
              {`$${Math.round(t).toLocaleString("en-US")}`}
            </text>
          </g>
        ))}
        {series.map((p, i) => {
          const cx = pad.left + slot * i + slot / 2;
          const rev = Number(p.revenue);
          const exp = Number(p.expenses);
          return (
            <g key={p.date}>
              <title>{`${p.date}: revenue ${money(p.revenue)}, expenses ${money(p.expenses)}`}</title>
              {rev > 0 && (
                <rect className="bf-bar" x={cx - barW - 1} y={y(rev)} width={barW} height={pad.top + innerH - y(rev)} rx="2" fill={GREEN} />
              )}
              {exp > 0 && (
                <rect className="bf-bar" x={cx + 1} y={y(exp)} width={barW} height={pad.top + innerH - y(exp)} rx="2" fill={RED} />
              )}
              {i % labelEvery === 0 && (
                <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="#666">
                  {label(p.date)}
                </text>
              )}
            </g>
          );
        })}
        {!anyData && (
          <text x={W / 2} y={H / 2} textAnchor="middle" fontSize="14" fill="#888">
            No revenue or expenses in this period.
          </text>
        )}
      </svg>
    </figure>
  );
}

// 1, 2, 5, 10, 20, 50... at or above the raw step, for readable axis ticks.
function niceStep(raw) {
  const exp = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const fraction = raw / exp;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * exp;
}

const CSS = `
.bf-tab { transition: background 160ms ease, box-shadow 160ms ease, color 160ms ease, transform 120ms ease; }
.bf-tab:hover { color: #124096; }
.bf-tab:active, .bf-press:active { transform: scale(0.96); }
.bf-press { transition: transform 120ms ease, filter 120ms ease; }
.bf-press:hover:not(:disabled) { filter: brightness(0.96); }
.bf-body { transition: opacity 180ms ease; }
.bf-bar { transform-box: fill-box; transform-origin: bottom; animation: bf-grow 420ms ease-out both; }
.bf-select { appearance: none; -webkit-appearance: none; cursor: pointer; padding-right: 40px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23124096' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat; background-position: right 14px center; }
.bf-select:focus-visible, .bf-tab:focus-visible, .bf-press:focus-visible { outline: 3px solid #124096; outline-offset: 2px; }
.bf-select option { font-weight: 600; color: #1a1a1a; background: #fff; }
@keyframes bf-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@media (prefers-reduced-motion: reduce) {
  .bf-tab, .bf-press, .bf-body { transition: none; }
  .bf-bar { animation: none; }
  .bf-tab:active, .bf-press:active { transform: none; }
}
`;

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1000,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { marginBottom: 16 },
  title: { fontSize: 24, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  card: { border: "1px solid #e4e4e8", borderRadius: 20, background: "#fff", padding: 20 },
  cardHeader: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 14,
    marginBottom: 16,
  },
  headline: { display: "flex", alignItems: "baseline", gap: 10 },
  count: { fontSize: 32, fontWeight: 900, letterSpacing: -0.5 },
  countLabel: { fontSize: 14, fontWeight: 600, color: "#666" },
  countLabelStrong: { fontSize: 18, fontWeight: 800 },
  controls: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 },
  tray: {
    display: "inline-flex",
    gap: 4,
    padding: 5,
    borderRadius: 16,
    background: "#e9e9ee",
    boxShadow: "inset 0 2px 4px rgba(0,0,0,0.12)",
  },
  tab: {
    height: 38,
    padding: "0 16px",
    border: "none",
    borderRadius: 12,
    background: "transparent",
    fontSize: 14,
    fontWeight: 800,
    color: "#555",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  tabSelected: {
    background: "#fff",
    color: "#124096",
    boxShadow: "0 3px 8px rgba(18,64,150,0.22), 0 1px 0 rgba(255,255,255,0.9) inset",
  },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "1 1 150px", minWidth: 0 },
  fieldLabel: { fontSize: 12, fontWeight: 800, color: "#444" },
  fieldError: { fontSize: 12, color: RED },
  srOnly: { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" },
  input: {
    height: 48,
    padding: "0 14px",
    fontSize: 15,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 14,
    background: "#fff",
    width: "100%",
    boxSizing: "border-box",
  },
  select: {
    height: 48,
    padding: "0 14px",
    fontSize: 15,
    fontWeight: 800,
    color: "#124096",
    border: "1px solid #c5d0e8",
    borderRadius: 14,
    backgroundColor: "#eef2fa",
    width: "100%",
    boxSizing: "border-box",
    minWidth: 150,
  },
  customRow: { display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 12, marginBottom: 16 },
  kpis: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12, marginBottom: 18 },
  kpi: { padding: "14px 16px", borderRadius: 16, background: "#f6f6f8", border: "1px solid #ececf0" },
  kpiStrong: { background: "#fff", border: "2px solid #1a1a1a" },
  kpiLabel: { fontSize: 12, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "#666" },
  kpiValue: { fontSize: 30, fontWeight: 900, marginTop: 4, letterSpacing: -0.5 },
  chartFigure: { margin: "0 0 18px", padding: 0 },
  chart: { width: "100%", height: "auto", display: "block" },
  legend: { display: "flex", gap: 16, fontSize: 13, fontWeight: 700, marginBottom: 6 },
  legendItem: { display: "inline-flex", alignItems: "center", gap: 6 },
  swatch: { display: "inline-block", width: 12, height: 12, borderRadius: 4 },
  breakdowns: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20 },
  breakdown: { minWidth: 0 },
  breakdownTitle: { fontSize: 15, fontWeight: 800, margin: "0 0 10px" },
  breakdownRow: { marginBottom: 10 },
  breakdownLine: { display: "flex", justifyContent: "space-between", fontSize: 14, marginBottom: 4 },
  breakdownName: { fontWeight: 700 },
  breakdownAmount: { fontWeight: 800 },
  barTrack: { height: 8, borderRadius: 4, background: "#ececf0", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 4, transition: "width 300ms ease" },
  primaryButton: {
    height: 48,
    padding: "0 22px",
    border: "none",
    borderRadius: 14,
    ...BUTTON_COLORS.blue,
    fontSize: 15,
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 3px 0 rgba(0,0,0,0.25)",
  },
  secondaryButton: {
    height: 48,
    padding: "0 20px",
    border: "1px solid #d0d0d5",
    borderRadius: 14,
    background: "#f5f5f7",
    fontSize: 15,
    fontWeight: 800,
    color: "#444",
    cursor: "pointer",
  },
  smallButton: {
    height: 36,
    padding: "0 14px",
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#f5f5f7",
    fontSize: 13,
    fontWeight: 800,
    cursor: "pointer",
  },
  dangerButton: {
    height: 36,
    padding: "0 14px",
    border: "none",
    borderRadius: 10,
    ...BUTTON_COLORS.red,
    fontSize: 13,
    fontWeight: 800,
    cursor: "pointer",
  },
  rowActions: { display: "inline-flex", gap: 8 },
  form: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-start",
    gap: 12,
    padding: 16,
    marginBottom: 16,
    borderRadius: 16,
    background: "#f6f6f8",
    border: "1px solid #ececf0",
  },
  formActions: { display: "flex", gap: 10, flexBasis: "100%", justifyContent: "flex-end" },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 14 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    background: "#fafafa",
    borderBottom: "1px solid #e4e4e8",
    fontWeight: 800,
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: 0.3,
    color: "#555",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 14px", borderBottom: "1px solid #f0f0f2", verticalAlign: "middle" },
  tdNoWrap: { padding: "10px 14px", borderBottom: "1px solid #f0f0f2", verticalAlign: "middle", whiteSpace: "nowrap" },
  empty: { fontSize: 14, color: "#888", padding: "16px 0", textAlign: "center" },
  hint: { fontSize: 13, color: "#888", marginTop: 6 },
  errorBox: { background: "#fdeceb", color: RED, padding: "10px 14px", borderRadius: 12, fontSize: 14, marginBottom: 14 },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "10px 14px", borderRadius: 12, fontSize: 14, marginBottom: 14 },
};

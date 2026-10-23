import { useEffect, useState } from "react";
import { fetchExpenses, fetchFinanceMeta, recordExpense } from "../../api/finance.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const PAGE_SIZE = 25;
const EMPTY_FORM = { branch: "", category: "", amount: "", incurredOn: "", note: "" };

// Records the branch running costs (rent, payroll, ...) that
// finance/FinancialReport.jsx compares against revenue - that report has
// nothing to show on the expense side until something is entered here.
// Gated on manage_billing, a different permission from the report's
// view_financial_reports (see finance/views.py for why).
//
// User story: "As a general manager, I want to view expense and revenue
// data for each branch, so that I can monitor financial performance and
// compare branches." (the write side this depends on)
export default function ExpenseLedger() {
  const [branches, setBranches] = useState([]);
  const [categories, setCategories] = useState([]);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ total: 0, results: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [savedNotice, setSavedNotice] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    fetchFinanceMeta()
      .then((meta) => {
        setBranches(meta.branches);
        setCategories(meta.categories);
        setForm((f) => ({ ...f, branch: f.branch || meta.branches[0] || "" }));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchExpenses({}, { limit: PAGE_SIZE, offset })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [offset, reloadKey]);

  useEffect(() => {
    if (!savedNotice) return;
    const timer = setTimeout(() => setSavedNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [savedNotice]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    try {
      await recordExpense({ ...form, incurredOn: form.incurredOn || undefined });
      setForm((f) => ({ ...EMPTY_FORM, branch: f.branch }));
      setShowForm(false);
      setSavedNotice("Expense recorded.");
      setOffset(0);
      setReloadKey((k) => k + 1);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const from = data.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.total);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Expenses</h1>
          <p style={styles.subtitle}>
            Rent, payroll and other branch running costs - the expense side of the Financial Report.
          </p>
        </div>
        <button onClick={() => setShowForm(true)} style={styles.addButton}>
          Record expense
        </button>
      </div>

      {savedNotice && <div style={styles.successBox}>{savedNotice}</div>}
      {error && <div style={styles.errorBox}>Couldn't load expenses: {error}</div>}

      {!loading && data.results.length === 0 && <div style={styles.empty}>No expenses recorded yet.</div>}

      {data.results.length > 0 && (
        <>
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Date</th>
                  <th style={styles.th}>Branch</th>
                  <th style={styles.th}>Category</th>
                  <th style={styles.th}>Amount</th>
                  <th style={styles.th}>Note</th>
                  <th style={styles.th}>Recorded by</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((x) => (
                  <tr key={x.id}>
                    <td style={styles.td}>{x.incurredOn}</td>
                    <td style={styles.td}>{x.branch}</td>
                    <td style={styles.td}>{x.category}</td>
                    <td style={{ ...styles.td, fontWeight: 600 }}>${x.amount}</td>
                    <td style={styles.td}>{x.note || "—"}</td>
                    <td style={styles.td}>{x.recordedBy || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={styles.pager}>
            <span style={styles.countRow}>{`${from}-${to} of ${data.total}`}</span>
            <div style={styles.pagerButtons}>
              <button onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} style={styles.pageButton}>
                Previous
              </button>
              <button onClick={() => setOffset(offset + PAGE_SIZE)} disabled={to >= data.total} style={styles.pageButton}>
                Next
              </button>
            </div>
          </div>
        </>
      )}

      {showForm && (
        <div style={styles.overlay} onClick={() => setShowForm(false)}>
          <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div style={styles.modalHeader}>
              <h2 style={styles.modalTitle}>Record Expense</h2>
              <button onClick={() => setShowForm(false)} style={styles.closeButton} aria-label="Close">
                &times;
              </button>
            </div>

            <form onSubmit={handleSubmit}>
              <Field label="Branch" error={fieldErrors.branch}>
                <select value={form.branch} onChange={(e) => update("branch", e.target.value)} style={styles.input}>
                  {branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Category" error={fieldErrors.category}>
                <select value={form.category} onChange={(e) => update("category", e.target.value)} style={styles.input}>
                  <option value="">Choose a category</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Amount" error={fieldErrors.amount}>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={form.amount}
                  onChange={(e) => update("amount", e.target.value)}
                  style={styles.input}
                  autoFocus
                />
              </Field>

              <Field label="Date incurred" error={fieldErrors.incurredOn}>
                <input
                  type="date"
                  value={form.incurredOn}
                  onChange={(e) => update("incurredOn", e.target.value)}
                  style={styles.input}
                />
              </Field>

              <Field label="Note (optional)" error={fieldErrors.note}>
                <input
                  type="text"
                  value={form.note}
                  onChange={(e) => update("note", e.target.value)}
                  style={styles.input}
                />
              </Field>

              {submitError && <div style={styles.errorBox}>{submitError}</div>}

              <div style={styles.actions}>
                <button type="button" onClick={() => setShowForm(false)} style={styles.cancelButton}>
                  Cancel
                </button>
                <button type="submit" disabled={submitting || !form.category} style={styles.submitButton}>
                  {submitting ? "Saving..." : "Save expense"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.label}>{label}</label>
      {children}
      {message && <div style={styles.fieldError}>{message}</div>}
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
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  addButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  successBox: {
    background: "#e3f5e8",
    color: "#0f6e2b",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
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
    marginBottom: 12,
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
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 420,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  field: { marginBottom: 14 },
  label: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
  },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 },
  cancelButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  submitButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
};

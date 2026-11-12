import { useCallback, useEffect, useState } from "react";
import { fetchCoachPayList, fetchCoachStatement, removeCoachRate, setCoachRate } from "../../api/payroll.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import PayStatement, { formatDay, formatHours, formatMoney, periodLabel } from "./PayStatement.jsx";

// The branch manager's side of: "As a coach, I want to view my completed
// session count and earnings for the current pay period, so that I can
// verify my pay is correct."
//
// Every coach this manager looks after, with their hourly rates and the
// period's totals; setting a new rate (from today, a later date, or back to
// the start of the open pay period); and the coach's own statement, so a
// pay question is answered from the same numbers the coach sees.

export default function CoachPayManager() {
  const [period, setPeriod] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [rateFor, setRateFor] = useState(null);
  const [statementFor, setStatementFor] = useState(null);

  const load = useCallback(() => {
    return fetchCoachPayList(period)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Coach Pay</h1>
      <p style={styles.subtitle}>
        Hourly rates for your coaches and what they've earned this pay period. Coaches see the same statement under My Pay.
      </p>
      {notice && <div style={styles.successBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}
      {!data && !error && <p style={styles.muted}>Loading...</p>}

      {data && (
        <>
          <label style={styles.periodField}>
            <span style={styles.periodLabel}>Pay period</span>
            <select value={period || data.period.key} onChange={(e) => setPeriod(e.target.value)} style={styles.select} aria-label="Pay period">
              {data.periods.map((key, i) => (
                <option key={key} value={key}>
                  {periodLabel(key)}
                  {i === 0 ? " (current)" : ""}
                </option>
              ))}
            </select>
          </label>

          {data.results.length === 0 ? (
            <div style={styles.empty}>No coaches at your branch.</div>
          ) : (
            <div style={styles.tableWrap}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Coach</th>
                    <th style={styles.th}>Current rate</th>
                    <th style={styles.thRight}>Completed</th>
                    <th style={styles.thRight}>Hours</th>
                    <th style={styles.thRight}>Earned</th>
                    <th style={styles.th} />
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((c) => (
                    <tr key={c.id} style={c.active ? null : styles.rowMuted}>
                      <td style={styles.td}>
                        <span style={styles.name}>{c.name}</span>
                        <div style={styles.cellSub}>
                          {c.branch || "All branches"}
                          {!c.active && " · deactivated"}
                        </div>
                      </td>
                      <td style={styles.td}>
                        {c.currentRate ? (
                          <>
                            {formatMoney(c.currentRate.classHourly)}/h classes
                            <div style={styles.cellSub}>{formatMoney(c.currentRate.ptHourly)}/h private training</div>
                          </>
                        ) : (
                          <span style={styles.noRate}>Not set</span>
                        )}
                        {c.scheduled.map((r) => (
                          <div key={r.id} style={styles.scheduled}>
                            From {formatDay(r.effectiveFrom, true)}: {formatMoney(r.classHourly)} / {formatMoney(r.ptHourly)}
                          </div>
                        ))}
                      </td>
                      <td style={styles.tdRight}>
                        {c.summary.completed}
                        {c.summary.unrated > 0 && <div style={styles.noRate}>{c.summary.unrated} without a rate</div>}
                      </td>
                      <td style={styles.tdRight}>{formatHours(c.summary.minutes)}</td>
                      <td style={styles.tdAmount}>{formatMoney(c.summary.earnings)}</td>
                      <td style={styles.tdActions}>
                        <div style={styles.actionButtons}>
                          <button type="button" onClick={() => setStatementFor(c)} style={styles.secondaryButton}>
                            Statement
                          </button>
                          {c.active && (
                            <button type="button" onClick={() => setRateFor(c)} style={styles.primaryButton} aria-label={`Set rate for ${c.name}`}>
                              Set rate
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {rateFor && data && (
        <RateForm
          coach={rateFor}
          earliest={data.earliestEffectiveFrom}
          maxHourly={data.maxHourly}
          onClose={() => setRateFor(null)}
          onSaved={(rate) => {
            setRateFor(null);
            setNotice(`${rateFor.name}: ${formatMoney(rate.classHourly)}/h classes, ${formatMoney(rate.ptHourly)}/h private training from ${formatDay(rate.effectiveFrom, true)}.`);
            load();
          }}
        />
      )}

      {statementFor && (
        <StatementModal
          coach={statementFor}
          initialPeriod={period}
          onClose={() => setStatementFor(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}

function localIso(day) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

function RateForm({ coach, earliest, maxHourly, onClose, onSaved }) {
  const todayIso = localIso(new Date());
  const [form, setForm] = useState({
    classHourly: coach.currentRate?.classHourly ?? "",
    ptHourly: coach.currentRate?.ptHourly ?? "",
    effectiveFrom: todayIso < earliest ? earliest : todayIso,
    note: "",
  });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  // Editing a field clears the server's complaint about it.
  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value });
    if (errors[field]) setErrors({ ...errors, [field]: undefined });
  };

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    setError(null);
    try {
      onSaved(await setCoachRate(coach.id, form));
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const fieldError = (f) => errors[f] && <span style={styles.fieldError}>{errors[f][0]}</span>;
  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={submit} role="dialog" aria-label="Set pay rate">
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>Set pay rate · {coach.name}</h2>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        {error && <div style={styles.errorBox}>{error}</div>}
        <div style={styles.formRow}>
          <label style={styles.field}>
            <span style={styles.label}>Group classes ($ per hour)</span>
            <input type="number" min="0" max={maxHourly} step="0.01" value={form.classHourly} onChange={set("classHourly")} style={styles.input} required />
            {fieldError("classHourly")}
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Private training ($ per hour)</span>
            <input type="number" min="0" max={maxHourly} step="0.01" value={form.ptHourly} onChange={set("ptHourly")} style={styles.input} required />
            {fieldError("ptHourly")}
          </label>
        </div>
        <label style={styles.field}>
          <span style={styles.label}>Starting from</span>
          <input type="date" min={earliest} value={form.effectiveFrom} onChange={set("effectiveFrom")} style={styles.input} required />
          <span style={styles.hint}>
            The earliest is {formatDay(earliest, true)}, the start of the open pay period - pay for closed periods can't change.
            Sessions on or after this date are paid at the new rate.
          </span>
          {fieldError("effectiveFrom")}
        </label>
        <label style={styles.field}>
          <span style={styles.label}>Note for the coach (optional)</span>
          <input value={form.note} onChange={set("note")} maxLength={200} placeholder="e.g. Annual raise" style={styles.input} />
          {fieldError("note")}
        </label>
        <p style={styles.hint}>{coach.name.split(" ")[0]} is notified, and the change is recorded in the audit log.</p>
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.secondaryButton} disabled={saving}>
            Cancel
          </button>
          <button type="submit" style={styles.primaryButton} disabled={saving}>
            {saving ? "Saving..." : "Save rate"}
          </button>
        </div>
      </form>
    </div>
  );
}

function StatementModal({ coach, initialPeriod, onClose, onChanged }) {
  const [period, setPeriod] = useState(initialPeriod);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    return fetchCoachStatement(coach.id, period)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [coach.id, period]);

  useEffect(() => {
    load();
  }, [load]);

  async function withdraw(rate) {
    setError(null);
    try {
      await removeCoachRate(coach.id, rate.id);
      await load();
      onChanged();
    } catch (err) {
      setError(err.message);
    }
  }

  // Only a change that hasn't started can be withdrawn (the server checks too).
  const todayIso = localIso(new Date());
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={{ ...styles.modal, maxWidth: 900 }} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Pay statement">
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>Pay statement · {coach.name}</h2>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        {error && <div style={styles.errorBox}>{error}</div>}
        {!data && !error && <p style={styles.muted}>Loading...</p>}
        {data && <PayStatement data={data} period={period} onPeriod={setPeriod} loading={loading} />}
        {data && (
          <>
            <h3 style={styles.section}>Rate history</h3>
            {data.rateHistory.length === 0 ? (
              <p style={styles.muted}>No rate set yet.</p>
            ) : (
              <ul style={styles.history}>
                {data.rateHistory.map((r) => (
                  <li key={r.id} style={styles.historyItem}>
                    <span>
                      From <strong>{formatDay(r.effectiveFrom, true)}</strong>: {formatMoney(r.classHourly)}/h classes ·{" "}
                      {formatMoney(r.ptHourly)}/h private
                      <span style={styles.cellSub}>
                        {r.setBy ? ` · set by ${r.setBy}` : ""}
                        {r.note ? ` · ${r.note}` : ""}
                      </span>
                    </span>
                    {r.effectiveFrom > todayIso && (
                      <button type="button" onClick={() => withdraw(r)} style={styles.linkDanger}>
                        Withdraw
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 16px" },
  muted: { fontSize: 13, color: "#888" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 12, fontSize: 14, color: "#888", textAlign: "center" },
  periodField: { display: "inline-flex", flexDirection: "column", gap: 4, marginBottom: 12 },
  periodLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit" },
  tableWrap: { border: "1px solid #e4e4e8", borderRadius: 12, overflow: "auto", background: "#fff" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 12px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" },
  thRight: { textAlign: "right", padding: "8px 12px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top" },
  tdRight: { padding: "10px 12px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", textAlign: "right", whiteSpace: "nowrap" },
  tdAmount: { padding: "10px 12px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", textAlign: "right", whiteSpace: "nowrap", fontWeight: 800 },
  tdActions: { padding: "10px 12px", borderBottom: "1px solid #f0f0f2", verticalAlign: "top", whiteSpace: "nowrap" },
  actionButtons: { display: "flex", gap: 6, justifyContent: "flex-end" },
  rowMuted: { color: "#77777f", background: "#fafafb" },
  name: { fontWeight: 700 },
  cellSub: { fontSize: 11, color: "#888", marginTop: 2 },
  noRate: { fontSize: 12, fontWeight: 700, color: "#8a5300" },
  scheduled: { fontSize: 11, color: "#124096", marginTop: 4 },
  primaryButton: { padding: "7px 12px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  secondaryButton: { padding: "7px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  linkDanger: { border: "none", background: "none", color: "#b3261e", fontSize: 12, fontWeight: 700, cursor: "pointer", flexShrink: 0 },
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 50 },
  modal: {
    background: "#fff",
    borderRadius: 14,
    padding: 22,
    width: "100%",
    maxWidth: 520,
    maxHeight: "90vh",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 12,
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  modalTitle: { fontSize: 19, fontWeight: 800, margin: 0 },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  formRow: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 },
  label: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit", boxSizing: "border-box", width: "100%" },
  hint: { fontSize: 12, color: "#777", margin: 0, lineHeight: 1.45 },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8 },
  section: { fontSize: 15, fontWeight: 800, margin: "8px 0 0" },
  history: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10 },
  historyItem: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "8px 12px", borderBottom: "1px solid #f0f0f2", fontSize: 13 },
};

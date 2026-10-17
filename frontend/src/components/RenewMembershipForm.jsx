import { useEffect, useState } from "react";
import { fetchMemberBilling, fetchRenewalQuote, recordPayment } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import PaymentMethodForm from "./PaymentMethodForm.jsx";
import SegmentedControl from "./SegmentedControl.jsx";

const STATUS_STYLES = { Active: BUTTON_COLORS.green, Frozen: BUTTON_COLORS.blue, Cancelled: BUTTON_COLORS.red };
const DURATION_OPTIONS = [
  { value: "1 Month", label: "1 Month" },
  { value: "1 Year", label: "1 Year", tag: "Save $20" },
];
const METHOD_OPTIONS = ["Cash", "Card", "Bank Transfer"].map((m) => ({ value: m, label: m }));

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Renews an Active member (the new period starts when the current one ends,
// so no paid days are lost) or re-subscribes a Frozen/Cancelled one (from
// today). The price and period come from the server's renewal quote, and
// the payment is refused if that price changes before it's confirmed.
export default function RenewMembershipForm({ member, plans, onClose, onRenewed }) {
  const [billing, setBilling] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState({
    membershipPlan: plans.includes(member.membershipPlan) ? member.membershipPlan : "",
    duration: "",
    method: "",
  });
  const [quote, setQuote] = useState(null);
  const [quoteError, setQuoteError] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteVersion, setQuoteVersion] = useState(0);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [showMethodForm, setShowMethodForm] = useState(false);

  const current = billing?.member ?? member;
  const isActive = current.status === "Active";
  const onFile = billing?.paymentMethod ?? null;
  const cardBlocked = form.method === "Card" && Boolean(onFile?.cardExpired);
  const today = localToday();

  useEffect(() => {
    fetchMemberBilling(member.id)
      .then((data) => {
        setBilling(data);
        // Default to how the member normally pays.
        if (data.paymentMethod) setForm((f) => (f.method ? f : { ...f, method: data.paymentMethod.method }));
      })
      .catch((err) => setLoadError(err.message));
  }, [member.id]);

  useEffect(() => {
    setQuote(null);
    setQuoteError(null);
    if (!form.membershipPlan || !form.duration) return undefined;
    let cancelled = false;
    setQuoteLoading(true);
    fetchRenewalQuote(member.id, { membershipPlan: form.membershipPlan, duration: form.duration })
      .then((data) => {
        if (!cancelled) setQuote(data);
      })
      .catch((err) => {
        if (!cancelled) setQuoteError(err.fieldErrors ? Object.values(err.fieldErrors).flat()[0] : err.message);
      })
      .finally(() => {
        if (!cancelled) setQuoteLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [member.id, form.membershipPlan, form.duration, quoteVersion]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    setFieldErrors((errs) => ({ ...errs, [field]: undefined }));
    setNotice(null);
  }

  function handleMethodSaved(saved) {
    setShowMethodForm(false);
    setBilling((b) => ({ ...b, paymentMethod: saved }));
    update("method", saved.method);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!quote || !form.method || cardBlocked) return;
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    setNotice(null);
    try {
      const updated = await recordPayment(member.id, { ...form, expectedAmount: quote.amount });
      onRenewed(updated);
    } catch (err) {
      if (err.status === 409) {
        setNotice(err.message);
        setQuoteVersion((v) => v + 1);
      } else if (err.fieldErrors) {
        setFieldErrors(err.fieldErrors);
      } else {
        setSubmitError(err.message);
      }
      setSubmitting(false);
    }
  }

  const statusStyle = STATUS_STYLES[current.status] || { background: "#eee", color: "#333" };
  const expiry = current.subscriptionExpiresAt;
  let subscriptionLine = "No subscription on file yet";
  if (expiry && isActive) subscriptionLine = `Active until ${expiry}`;
  else if (expiry && expiry < today) subscriptionLine = `Expired on ${expiry}`;
  else if (expiry) subscriptionLine = `Paid until ${expiry}`;

  const actionWord = isActive ? "Renew" : "Subscribe";
  const canSubmit = Boolean(quote && form.method && !cardBlocked && !submitting);

  return (
    <>
      <div style={styles.overlay} onClick={onClose}>
        <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
          <div style={styles.modalHeader}>
            <h2 style={styles.modalTitle}>{isActive ? "Renew Membership" : "Subscribe"}</h2>
            <button onClick={onClose} style={styles.closeButton} aria-label="Close">
              &times;
            </button>
          </div>

          <div style={styles.memberStrip}>
            <div>
              <div style={styles.memberName}>{current.name}</div>
              <div style={styles.memberMeta}>
                #{current.id} &middot; {current.branch} &middot; {subscriptionLine}
              </div>
            </div>
            <span style={{ ...styles.statusBadge, ...statusStyle }}>{current.status}</span>
          </div>

          {loadError && <div style={styles.errorBox}>Couldn't load this member's billing: {loadError}</div>}

          <form onSubmit={handleSubmit}>
            <Field label="Membership plan" error={fieldErrors.membershipPlan}>
              <select
                value={form.membershipPlan}
                onChange={(e) => update("membershipPlan", e.target.value)}
                style={styles.input}
              >
                <option value="">Select a plan...</option>
                {plans.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
              {form.membershipPlan && form.membershipPlan !== current.membershipPlan && (
                <div style={styles.hint}>
                  Changes the plan from {current.membershipPlan} to {form.membershipPlan}.
                </div>
              )}
            </Field>

            <Field label="Duration" error={fieldErrors.duration}>
              <SegmentedControl
                options={DURATION_OPTIONS}
                value={form.duration}
                onChange={(d) => update("duration", d)}
                ariaLabel="Subscription duration"
              />
            </Field>

            <Field
              label="Payment method"
              error={fieldErrors.method}
              action={
                billing && (
                  <button type="button" onClick={() => setShowMethodForm(true)} style={styles.linkButton}>
                    {onFile ? "Update method on file" : "Add method on file"}
                  </button>
                )
              }
            >
              <SegmentedControl
                options={METHOD_OPTIONS}
                value={form.method}
                onChange={(m) => update("method", m)}
                ariaLabel="Payment method"
              />
              <MethodOnFileNote onFile={onFile} method={form.method} billingLoaded={Boolean(billing)} />
            </Field>

            {quoteLoading && <div style={styles.quoteLoading}>Calculating price...</div>}
            {quoteError && <div style={styles.errorBox}>{quoteError}</div>}

            {quote && (
              <div style={styles.quoteCard}>
                <div style={styles.quoteLabel}>Price</div>
                {quote.originalAmount && (
                  <div style={styles.oldPriceRow}>
                    <span style={styles.oldPriceTag}>Old price</span>
                    <span style={styles.oldPriceAmount}>${quote.originalAmount}</span>
                  </div>
                )}
                <div style={styles.priceDisplay}>${quote.amount}</div>
                {quote.promotion && <div style={styles.promo}>Includes the "{quote.promotion}" branch offer</div>}

                <div style={styles.periodRow}>
                  <span style={styles.periodLabel}>Covers</span>
                  <span style={styles.periodValue}>
                    {quote.startsOn} &rarr; {quote.expiresAt}
                  </span>
                </div>
                {isActive && quote.startsOn > today && (
                  <div style={styles.hint}>
                    Starts when the current subscription ends, so no paid days are lost.
                  </div>
                )}
              </div>
            )}

            {notice && <div style={styles.noticeBox}>{notice}</div>}
            {submitError && <div style={styles.errorBox}>{submitError}</div>}

            <div style={styles.actions}>
              <button type="button" onClick={onClose} style={styles.cancelButton}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                style={canSubmit ? styles.submitButton : { ...styles.submitButton, ...styles.submitDisabled }}
              >
                {submitting
                  ? "Processing..."
                  : quote
                    ? `${actionWord} & charge $${quote.amount}`
                    : actionWord}
              </button>
            </div>
          </form>
        </div>
      </div>

      {showMethodForm && (
        <PaymentMethodForm
          member={current}
          current={onFile}
          onClose={() => setShowMethodForm(false)}
          onSaved={handleMethodSaved}
        />
      )}
    </>
  );
}

function MethodOnFileNote({ onFile, method, billingLoaded }) {
  if (!billingLoaded) return null;
  if (!onFile) {
    return <div style={styles.hint}>No payment method on file for this member yet.</div>;
  }
  if (method === "Card" && onFile.cardExpired) {
    return (
      <div style={{ ...styles.methodNote, ...styles.methodNoteDanger }}>
        The card on file has expired: <strong>{onFile.summary}</strong>. Update the method on file before
        charging a card.
      </div>
    );
  }
  if (method && method === onFile.method) {
    return (
      <div style={{ ...styles.methodNote, ...styles.methodNoteOk }}>
        Charging the method on file: <strong>{onFile.summary}</strong>
        {onFile.cardExpiresBeforeRenewal && (
          <div style={styles.methodNoteWarn}>This card expires before the next renewal is due.</div>
        )}
      </div>
    );
  }
  if (method) {
    return (
      <div style={styles.methodNote}>
        One-off payment. The method on file stays as it is: <strong>{onFile.summary}</strong>.
      </div>
    );
  }
  return null;
}

function Field({ label, error, action, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <div style={styles.labelRow}>
        <label style={styles.label}>{label}</label>
        {action}
      </div>
      {children}
      {message && <div style={styles.fieldError}>{message}</div>}
    </div>
  );
}

const styles = {
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
    maxWidth: 460,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: {
    border: "none",
    background: "transparent",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
    color: "#888",
  },
  memberStrip: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "12px 14px",
    marginBottom: 18,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fafafa",
  },
  memberName: { fontSize: 15, fontWeight: 700 },
  memberMeta: { fontSize: 12, color: "#666", marginTop: 2 },
  statusBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 22,
    width: 76,
    flexShrink: 0,
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
  },
  field: { marginBottom: 16 },
  labelRow: { display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 },
  label: { fontSize: 13, fontWeight: 600, color: "#444" },
  linkButton: {
    border: "none",
    background: "none",
    padding: 0,
    color: "#124096",
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  },
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
  hint: { fontSize: 12, color: "#777", marginTop: 6 },
  methodNote: {
    marginTop: 8,
    padding: "8px 10px",
    borderRadius: 8,
    fontSize: 12,
    lineHeight: 1.45,
    background: "#f5f5f7",
    color: "#555",
  },
  methodNoteOk: { background: "#eef7f0", color: "#1d5e2f" },
  methodNoteDanger: { background: "#fdeceb", color: "#b3261e" },
  methodNoteWarn: { marginTop: 4, color: "#8a5a00", fontWeight: 600 },
  quoteLoading: { fontSize: 13, color: "#666", marginBottom: 14 },
  quoteCard: {
    padding: "14px 16px",
    marginBottom: 14,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#f5f5f7",
  },
  quoteLabel: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: "#777",
    marginBottom: 4,
  },
  oldPriceRow: { display: "flex", alignItems: "center", gap: 6, marginBottom: 2 },
  oldPriceTag: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: "#999",
  },
  oldPriceAmount: { fontSize: 13, color: "#999", textDecoration: "line-through" },
  priceDisplay: { fontSize: 26, fontWeight: 800, color: "#1a1a1a" },
  promo: { fontSize: 12, color: "#1d5e2f", marginTop: 2 },
  periodRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
    paddingTop: 10,
    borderTop: "1px solid #e4e4e8",
    fontSize: 13,
  },
  periodLabel: { color: "#666" },
  periodValue: { fontWeight: 600 },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  noticeBox: {
    background: "#fff4e0",
    color: "#8a5a00",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 14,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 14,
  },
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
    ...BUTTON_COLORS.green,
    fontWeight: 600,
    cursor: "pointer",
  },
  submitDisabled: { opacity: 0.5, cursor: "not-allowed" },
};

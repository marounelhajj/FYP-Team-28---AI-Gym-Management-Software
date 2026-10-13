import { useState } from "react";
import { recordPayment } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import { getPriceInfo } from "../utils/pricing.js";

const PAYMENT_METHODS = ["Cash", "Card", "Bank Transfer"];
const PAYMENT_DURATIONS = ["1 Month", "1 Year"];

// The "repay to reactivate" action for a member whose subscription has
// lapsed (every customer without a valid subscription reads as Frozen -
// see the lazy sweep in members/views.py) - the system never auto-renews
// it, so this is the only way back to Active. Also usable to renew an
// Active member early, which stacks the new period on top of their
// remaining time (see billing/models.py Payment.record()).
//
// The receptionist picks the membership plan here explicitly every time
// (defaulting to the member's current one) - this is also how a plan
// upgrade/downgrade happens, not just a straight renewal. There's no
// amount field: pricing comes straight from GET /api/members/meta (meta
// prop, see utils/pricing.js) and is shown read-only, same reasoning as
// RegisterMemberForm.jsx.
export default function RecordPaymentForm({ member, meta, onClose, onRecorded }) {
  const [form, setForm] = useState({ membershipPlan: member.membershipPlan, method: "", duration: "" });
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const priceInfo = getPriceInfo(meta, form.membershipPlan, form.duration);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    try {
      const updated = await recordPayment(member.id, form);
      onRecorded(updated);
    } catch (err) {
      if (err.fieldErrors) {
        setFieldErrors(err.fieldErrors);
      } else {
        setSubmitError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>Subscribe</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <p style={styles.subtitle}>
          {member.name}
          {member.subscriptionExpiresAt && (
            <>
              {" "}
              &middot; {new Date(member.subscriptionExpiresAt) < new Date() ? "expired" : "expires"}{" "}
              {member.subscriptionExpiresAt}
            </>
          )}
        </p>

        <form onSubmit={handleSubmit}>
          <Field label="Membership plan" error={fieldErrors.membershipPlan}>
            <select
              value={form.membershipPlan}
              onChange={(e) => update("membershipPlan", e.target.value)}
              style={styles.input}
              autoFocus
            >
              <option value="">Select a plan...</option>
              {Object.keys(meta?.planPrices || {}).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Payment method" error={fieldErrors.method}>
            <select value={form.method} onChange={(e) => update("method", e.target.value)} style={styles.input}>
              <option value="">Select a payment method...</option>
              {PAYMENT_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Subscription duration" error={fieldErrors.duration}>
            <select value={form.duration} onChange={(e) => update("duration", e.target.value)} style={styles.input}>
              <option value="">Select a duration...</option>
              {PAYMENT_DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </Field>

          {priceInfo && (
            <Field label="Price">
              {priceInfo.hasPromo && (
                <div style={styles.oldPriceRow}>
                  <span style={styles.oldPriceTag}>Old price</span>
                  <span style={styles.oldPriceAmount}>${priceInfo.originalAmount}</span>
                </div>
              )}
              <div style={styles.priceDisplay}>${priceInfo.amount}</div>
            </Field>
          )}

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Subscribing..." : "Subscribe"}
            </button>
          </div>
        </form>
      </div>
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
    maxWidth: 380,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 13, color: "#666", margin: "0 0 16px" },
  closeButton: {
    border: "none",
    background: "transparent",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
    color: "#888",
  },
  field: { marginBottom: 14 },
  label: {
    display: "block",
    fontSize: 13,
    fontWeight: 600,
    marginBottom: 6,
    color: "#444",
  },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
  },
  priceDisplay: {
    padding: "10px 12px",
    fontSize: 20,
    fontWeight: 800,
    border: "1px solid #e4e4e8",
    borderRadius: 8,
    background: "#f5f5f7",
    color: "#1a1a1a",
  },
  oldPriceRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
  },
  oldPriceTag: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: "#999",
  },
  oldPriceAmount: {
    fontSize: 13,
    color: "#999",
    textDecoration: "line-through",
  },
  fieldError: {
    color: "#b3261e",
    fontSize: 12,
    marginTop: 4,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 10,
    marginTop: 18,
  },
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
};

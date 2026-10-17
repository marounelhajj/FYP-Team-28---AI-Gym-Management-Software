import { useState } from "react";
import { updatePaymentMethod } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import SegmentedControl from "./SegmentedControl.jsx";

const METHOD_OPTIONS = ["Cash", "Card", "Bank Transfer"].map((m) => ({ value: m, label: m }));
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

// Adds or replaces a member's payment method on file - the one renewals
// default to. Only reference details are kept: the card itself is charged
// on the desk terminal, so the full card number and CVV are never asked for.
export default function PaymentMethodForm({ member, current, onClose, onSaved }) {
  const thisYear = new Date().getFullYear();
  const years = Array.from({ length: 16 }, (_, i) => thisYear + i);
  const [form, setForm] = useState(() => ({
    method: current?.method || "",
    cardHolderName: current?.cardHolderName || member.name,
    cardLast4: current?.cardLast4 || "",
    // An expired card's dates are useless - start blank so new ones get picked.
    cardExpiryMonth: current?.cardExpired ? "" : current?.cardExpiryMonth ?? "",
    cardExpiryYear: current?.cardExpired ? "" : current?.cardExpiryYear ?? "",
    bankName: current?.bankName || "",
    bankAccountLast4: current?.bankAccountLast4 || "",
  }));
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function digitsOnly(value) {
    return value.replace(/\D/g, "").slice(0, 4);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.method) {
      setFieldErrors({ method: ["Choose how the member pays."] });
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    try {
      const saved = await updatePaymentMethod(member.id, {
        ...form,
        cardExpiryMonth: form.cardExpiryMonth === "" ? null : Number(form.cardExpiryMonth),
        cardExpiryYear: form.cardExpiryYear === "" ? null : Number(form.cardExpiryYear),
      });
      onSaved(saved);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{current ? "Update Payment Method" : "Add Payment Method"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        <p style={styles.subtitle}>
          {member.name} &middot; Membership ID #{member.id}
        </p>

        {current && (
          <div style={styles.currentBox}>
            <span style={styles.currentLabel}>Currently on file</span>
            <span style={styles.currentValue}>{current.summary}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <Field label="Payment method" error={fieldErrors.method}>
            <SegmentedControl
              options={METHOD_OPTIONS}
              value={form.method}
              onChange={(m) => update("method", m)}
              ariaLabel="Payment method"
            />
          </Field>

          {form.method === "Cash" && (
            <p style={styles.hint}>No details needed - the member pays in cash at the front desk.</p>
          )}

          {form.method === "Card" && (
            <>
              <Field label="Name on card" error={fieldErrors.cardHolderName}>
                <input
                  type="text"
                  value={form.cardHolderName}
                  onChange={(e) => update("cardHolderName", e.target.value)}
                  style={styles.input}
                  autoComplete="off"
                />
              </Field>

              <div style={styles.twoColumns}>
                <Field label="Card number" error={fieldErrors.cardLast4}>
                  <div style={styles.maskedRow}>
                    <span style={styles.mask}>&bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull;</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={form.cardLast4}
                      onChange={(e) => update("cardLast4", digitsOnly(e.target.value))}
                      placeholder="1234"
                      aria-label="Last 4 digits of the card"
                      style={styles.last4Input}
                      autoComplete="off"
                    />
                  </div>
                </Field>

                <Field label="Expiry" error={fieldErrors.cardExpiryMonth || fieldErrors.cardExpiryYear}>
                  <div style={styles.expiryRow}>
                    <select
                      value={form.cardExpiryMonth}
                      onChange={(e) => update("cardExpiryMonth", e.target.value)}
                      aria-label="Expiry month"
                      style={styles.input}
                    >
                      <option value="">MM</option>
                      {MONTHS.map((m) => (
                        <option key={m} value={m}>
                          {String(m).padStart(2, "0")}
                        </option>
                      ))}
                    </select>
                    <select
                      value={form.cardExpiryYear}
                      onChange={(e) => update("cardExpiryYear", e.target.value)}
                      aria-label="Expiry year"
                      style={styles.input}
                    >
                      <option value="">YYYY</option>
                      {years.map((y) => (
                        <option key={y} value={y}>
                          {y}
                        </option>
                      ))}
                    </select>
                  </div>
                </Field>
              </div>

              <p style={styles.hint}>
                Only the last 4 digits and the expiry date are kept, for reference. Never enter the full card
                number or the CVV - the card is charged on the desk terminal.
              </p>
            </>
          )}

          {form.method === "Bank Transfer" && (
            <div style={styles.twoColumns}>
              <Field label="Bank" error={fieldErrors.bankName}>
                <input
                  type="text"
                  value={form.bankName}
                  onChange={(e) => update("bankName", e.target.value)}
                  placeholder="e.g. Bank Audi"
                  style={styles.input}
                  autoComplete="off"
                />
              </Field>
              <Field label="Account / IBAN" error={fieldErrors.bankAccountLast4}>
                <div style={styles.maskedRow}>
                  <span style={styles.mask}>&bull;&bull;&bull;&bull;</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={form.bankAccountLast4}
                    onChange={(e) => update("bankAccountLast4", digitsOnly(e.target.value))}
                    placeholder="1234"
                    aria-label="Last 4 digits of the account or IBAN"
                    style={styles.last4Input}
                    autoComplete="off"
                  />
                </div>
              </Field>
            </div>
          )}

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : "Save payment method"}
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
    // Opens on top of the renewal form or the subscription details panel.
    zIndex: 1100,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 440,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
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
  currentBox: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10,
    padding: "10px 12px",
    marginBottom: 16,
    borderRadius: 8,
    background: "#f5f5f7",
    fontSize: 13,
  },
  currentLabel: { color: "#666" },
  currentValue: { fontWeight: 600, textAlign: "right" },
  field: { marginBottom: 14, minWidth: 0 },
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
  twoColumns: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  maskedRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "0 12px",
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
  },
  mask: { color: "#999", fontSize: 13, letterSpacing: 1, whiteSpace: "nowrap" },
  last4Input: {
    width: "100%",
    minWidth: 40,
    padding: "10px 0",
    fontSize: 14,
    border: "none",
    outline: "none",
    background: "transparent",
    letterSpacing: 2,
  },
  expiryRow: { display: "flex", gap: 6 },
  hint: { fontSize: 12, color: "#777", margin: "0 0 14px", lineHeight: 1.45 },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
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
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
};

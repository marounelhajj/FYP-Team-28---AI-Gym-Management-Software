import { useState } from "react";
import { createPromotion, updatePromotion } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

function todayIso() {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

// Works out what the promotion would do to the plan's price, mirroring the
// backend rules so the manager sees "over the cap" before submitting. The
// backend still enforces the cap - this is just a preview.
function previewDiscount(plan, discountType, discountValue) {
  const price = Number(plan.price);
  const value = Number(discountValue) || 0;
  const requested = discountType === "Percent" ? (price * value) / 100 : value;
  const cap = (price * Number(plan.maxPromoDiscountPercent)) / 100;
  return {
    price,
    cap,
    requested,
    overCap: requested > cap + 0.0001,
    effective: Math.max(price - Math.min(requested, cap), 0),
  };
}

// User story: "As a general manager, I want to set organization-wide
// membership plans and pricing tiers, so that pricing stays consistent
// across branches while still allowing local promotions."
//
// Used for both creating a new promotion and editing one - `promotion` is
// null for create, or the promotion being edited.
export default function PromotionForm({ promotion, plans, branches, discountTypes, defaultBranch, onClose, onSaved }) {
  const isEditing = Boolean(promotion);
  const [form, setForm] = useState(
    promotion
      ? {
          planId: promotion.planId,
          branch: promotion.branch,
          name: promotion.name,
          discountType: promotion.discountType,
          discountValue: promotion.discountValue,
          startDate: promotion.startDate,
          endDate: promotion.endDate,
        }
      : {
          planId: plans[0]?.id ?? "",
          branch: defaultBranch || branches[0] || "",
          name: "",
          discountType: "Percent",
          discountValue: "",
          startDate: todayIso(),
          endDate: todayIso(),
        }
  );
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const selectedPlan = plans.find((p) => p.id === Number(form.planId));
  const preview = selectedPlan ? previewDiscount(selectedPlan, form.discountType, form.discountValue) : null;

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    const payload = { ...form, planId: Number(form.planId) };

    try {
      const saved = isEditing ? await updatePromotion(promotion.id, payload) : await createPromotion(payload);
      onSaved(saved);
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
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Promotion" : "New Branch Promotion"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <Field label="Promotion name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              placeholder="e.g. Back to Uni"
              autoFocus
            />
          </Field>

          <div style={styles.row}>
            <Field label="Plan" error={fieldErrors.planId}>
              <select
                value={form.planId}
                onChange={(e) => update("planId", e.target.value)}
                style={styles.input}
                disabled={isEditing}
              >
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Branch" error={fieldErrors.branch}>
              <select value={form.branch} onChange={(e) => update("branch", e.target.value)} style={styles.input}>
                {branches.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div style={styles.row}>
            <Field label="Discount type" error={fieldErrors.discountType}>
              <select
                value={form.discountType}
                onChange={(e) => update("discountType", e.target.value)}
                style={styles.input}
              >
                {discountTypes.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label={form.discountType === "Percent" ? "Discount (%)" : "Discount (USD)"}
              error={fieldErrors.discountValue}
            >
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.discountValue}
                onChange={(e) => update("discountValue", e.target.value)}
                style={styles.input}
                placeholder="0"
              />
            </Field>
          </div>

          <div style={styles.row}>
            <Field label="Starts" error={fieldErrors.startDate}>
              <input
                type="date"
                value={form.startDate}
                onChange={(e) => update("startDate", e.target.value)}
                style={styles.input}
              />
            </Field>
            <Field label="Ends" error={fieldErrors.endDate}>
              <input
                type="date"
                value={form.endDate}
                onChange={(e) => update("endDate", e.target.value)}
                style={styles.input}
              />
            </Field>
          </div>

          {preview && (
            <div style={preview.overCap ? styles.previewWarn : styles.preview}>
              <div>
                {selectedPlan.name}: <s>${preview.price.toFixed(2)}</s>{" "}
                <strong>${preview.effective.toFixed(2)}</strong> at {form.branch}
              </div>
              <div style={styles.previewCap}>
                {preview.overCap
                  ? `Over the general manager's cap: max ${Number(selectedPlan.maxPromoDiscountPercent)}% ($${preview.cap.toFixed(2)}) off this plan.`
                  : `Cap for this plan: ${Number(selectedPlan.maxPromoDiscountPercent)}% ($${preview.cap.toFixed(2)}) off.`}
              </div>
            </div>
          )}

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Create promotion"}
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
    maxWidth: 480,
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
    marginBottom: 16,
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: {
    border: "none",
    background: "transparent",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
    color: "#888",
  },
  row: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 12,
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
    boxSizing: "border-box",
  },
  preview: {
    background: "#eef7f0",
    color: "#1d5e2f",
    padding: "10px 12px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  previewWarn: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 12px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  previewCap: { fontSize: 12, marginTop: 4 },
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
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
};

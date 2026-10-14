import { useState } from "react";
import { createPlan, updatePlan } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const EMPTY_FORM = {
  name: "",
  description: "",
  price: "",
  billingCycle: "Monthly",
  features: "",
  maxPromoDiscountPercent: "20",
};

// User story: "As a general manager, I want to set organization-wide
// membership plans and pricing tiers, so that pricing stays consistent
// across branches while still allowing local promotions."
//
// Used for both creating a new plan and editing an existing one - `plan`
// is null for create, or the plan being edited. Features are edited as one
// per line and sent to the API as a list.
export default function PlanForm({ plan, billingCycles, onClose, onSaved }) {
  const isEditing = Boolean(plan);
  const [form, setForm] = useState(
    plan
      ? {
          name: plan.name,
          description: plan.description,
          price: plan.price,
          billingCycle: plan.billingCycle,
          features: plan.features.join("\n"),
          maxPromoDiscountPercent: plan.maxPromoDiscountPercent,
        }
      : EMPTY_FORM
  );
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    const payload = {
      ...form,
      features: form.features.split("\n").map((f) => f.trim()).filter(Boolean),
    };

    try {
      const saved = isEditing ? await updatePlan(plan.id, payload) : await createPlan(payload);
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
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Plan" : "New Plan"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {isEditing && (
          <div style={styles.notice}>Price changes apply to every branch immediately.</div>
        )}

        <form onSubmit={handleSubmit}>
          <Field label="Plan name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              placeholder="e.g. Premium"
              autoFocus
            />
          </Field>

          <div style={styles.row}>
            <Field label="Price (USD)" error={fieldErrors.price}>
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.price}
                onChange={(e) => update("price", e.target.value)}
                style={styles.input}
                placeholder="0.00"
              />
            </Field>

            <Field label="Billing cycle" error={fieldErrors.billingCycle}>
              <select
                value={form.billingCycle}
                onChange={(e) => update("billingCycle", e.target.value)}
                style={styles.input}
              >
                {billingCycles.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Description" error={fieldErrors.description}>
            <input
              type="text"
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              style={styles.input}
              placeholder="Who this tier is for..."
            />
          </Field>

          <Field label="Max branch promotion discount (%)" error={fieldErrors.maxPromoDiscountPercent}>
            <input
              type="number"
              min="0"
              max="100"
              step="0.5"
              value={form.maxPromoDiscountPercent}
              onChange={(e) => update("maxPromoDiscountPercent", e.target.value)}
              style={styles.input}
            />
            <div style={styles.hint}>
              Branches can run local promotions on this plan, but never discount it by more than this. Set 0 to
              disallow promotions.
            </div>
          </Field>

          <Field label="Included features (one per line)" error={fieldErrors.features}>
            <textarea
              value={form.features}
              onChange={(e) => update("features", e.target.value)}
              style={{ ...styles.input, minHeight: 110, resize: "vertical", fontFamily: "inherit" }}
              placeholder={"Gym floor access\nUnlimited group classes"}
            />
          </Field>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Create plan"}
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
    maxWidth: 460,
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
  notice: {
    background: "#fff6e0",
    color: "#8a5a00",
    padding: "8px 12px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 14,
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
  hint: { fontSize: 12, color: "#888", marginTop: 4 },
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

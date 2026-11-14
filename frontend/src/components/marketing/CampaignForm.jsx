import { useState } from "react";
import { createCampaign, updateCampaign } from "../../api/marketing.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

function todayIso() {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

// Used for both starting a new campaign and editing one - `campaign` is
// null for create, or the campaign being edited.
export default function CampaignForm({ campaign, branches, defaultBranch, onClose, onSaved }) {
  const isEditing = Boolean(campaign);
  const [form, setForm] = useState(
    campaign
      ? {
          branch: campaign.branch,
          name: campaign.name,
          strategy: campaign.strategy,
          budget: campaign.budget,
          amountSpent: campaign.amountSpent,
          startDate: campaign.startDate,
          endDate: campaign.endDate,
        }
      : {
          branch: defaultBranch || branches[0] || "",
          name: "",
          strategy: "",
          budget: "",
          amountSpent: "0",
          startDate: todayIso(),
          endDate: todayIso(),
        }
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
    try {
      const saved = isEditing ? await updateCampaign(campaign.id, form) : await createCampaign(form);
      onSaved(saved);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Campaign" : "New Marketing Campaign"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <Field label="Campaign name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              placeholder="e.g. Summer Membership Push"
              autoFocus
            />
          </Field>

          <Field label="Branch" error={fieldErrors.branch}>
            <select
              value={form.branch}
              onChange={(e) => update("branch", e.target.value)}
              style={styles.input}
              disabled={isEditing}
            >
              {branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Strategy (what it is, and why)" error={fieldErrors.strategy}>
            <textarea
              value={form.strategy}
              onChange={(e) => update("strategy", e.target.value)}
              style={{ ...styles.input, minHeight: 80, resize: "vertical", fontFamily: "inherit" }}
              placeholder="e.g. Social ads targeting new students, tied to the back-to-school promotion."
            />
          </Field>

          <div style={styles.row}>
            <Field label="Budget ($)" error={fieldErrors.budget}>
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={form.budget}
                onChange={(e) => update("budget", e.target.value)}
                style={styles.input}
              />
            </Field>
            <Field label="Spent so far ($)" error={fieldErrors.amountSpent}>
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.amountSpent}
                onChange={(e) => update("amountSpent", e.target.value)}
                style={styles.input}
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

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Start campaign"}
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
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  row: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 },
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
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
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

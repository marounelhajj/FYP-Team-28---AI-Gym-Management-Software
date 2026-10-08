import { useState } from "react";
import { createMember } from "../api/members.js";
import { LIABILITY_WAIVER_TEXT, HEALTH_DISCLAIMER_TEXT } from "../data/waiverText.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";

// User story: "As a receptionist, I want to register a new walk-in
// member's profile and membership plan, so that I can onboard new
// customers on the spot."
//
// Also covers: "As a member, I want to sign a digital waiver and health
// disclaimer during signup, so that the gym has liability protection on
// file before I start training." - the receptionist fills in section 1,
// then hands the device to the member to read and sign section 2. One
// submit registers the member AND records the signed waiver together;
// the backend refuses to create the member at all unless both boxes are
// checked, so a member can never exist without liability protection on
// file.

const EMPTY_FORM = {
  name: "",
  email: "",
  phone: "",
  branch: "",
  membershipPlan: "",
  signatureName: "",
  healthDisclaimerAccepted: false,
  liabilityWaiverAccepted: false,
};

export default function RegisterMemberForm({ filterOptions, onClose, onRegistered }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  const canSubmit =
    form.liabilityWaiverAccepted && form.healthDisclaimerAccepted && form.signatureName.trim().length > 0;

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    try {
      const member = await createMember(form);
      onRegistered(member);
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
          <h2 style={styles.modalTitle}>Register New Member</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <SectionLabel>1. Member profile</SectionLabel>

          <Field label="Full name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              autoFocus
            />
          </Field>

          <Field label="Email" error={fieldErrors.email}>
            <input
              type="email"
              value={form.email}
              onChange={(e) => update("email", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Phone" error={fieldErrors.phone}>
            <input
              type="tel"
              value={form.phone}
              onChange={(e) => update("phone", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Branch" error={fieldErrors.branch}>
            <select
              value={form.branch}
              onChange={(e) => update("branch", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a branch...</option>
              {filterOptions.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Membership plan" error={fieldErrors.membershipPlan}>
            <select
              value={form.membershipPlan}
              onChange={(e) => update("membershipPlan", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a plan...</option>
              {(filterOptions.plans || []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>

          <SectionLabel>2. Waiver &amp; health disclaimer</SectionLabel>
          <p style={styles.sectionHint}>
            Please hand the device to the new member to read and sign below.
          </p>

          <div style={styles.waiverBox}>
            <strong style={styles.waiverHeading}>Liability Waiver</strong>
            <p style={styles.waiverText}>{LIABILITY_WAIVER_TEXT}</p>
            <strong style={styles.waiverHeading}>Health Disclaimer</strong>
            <p style={styles.waiverText}>{HEALTH_DISCLAIMER_TEXT}</p>
          </div>

          <CheckboxField error={fieldErrors.liabilityWaiverAccepted}>
            <input
              type="checkbox"
              checked={form.liabilityWaiverAccepted}
              onChange={(e) => update("liabilityWaiverAccepted", e.target.checked)}
              style={styles.checkbox}
            />
            <span>I have read and agree to the Liability Waiver above.</span>
          </CheckboxField>

          <CheckboxField error={fieldErrors.healthDisclaimerAccepted}>
            <input
              type="checkbox"
              checked={form.healthDisclaimerAccepted}
              onChange={(e) => update("healthDisclaimerAccepted", e.target.checked)}
              style={styles.checkbox}
            />
            <span>I have read and agree to the Health Disclaimer above.</span>
          </CheckboxField>

          <Field label="Type your full legal name to sign" error={fieldErrors.signatureName}>
            <input
              type="text"
              value={form.signatureName}
              onChange={(e) => update("signatureName", e.target.value)}
              placeholder="This serves as your digital signature"
              style={styles.input}
            />
          </Field>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !canSubmit}
              style={submitting || !canSubmit ? styles.submitButtonDisabled : styles.submitButton}
            >
              {submitting ? "Registering..." : "Complete registration & sign waiver"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SectionLabel({ children }) {
  return <div style={styles.sectionLabel}>{children}</div>;
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

function CheckboxField({ error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.checkboxLabel}>{children}</label>
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
  sectionLabel: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: "#1a56c4",
    marginTop: 18,
    marginBottom: 10,
  },
  sectionHint: {
    fontSize: 13,
    color: "#666",
    margin: "0 0 10px 0",
  },
  waiverBox: {
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fafafa",
    padding: "10px 12px",
    maxHeight: 160,
    overflowY: "auto",
    marginBottom: 12,
  },
  waiverHeading: {
    display: "block",
    fontSize: 12,
    marginTop: 8,
  },
  waiverText: {
    fontSize: 12,
    lineHeight: 1.5,
    color: "#444",
    margin: "4px 0 0 0",
  },
  field: { marginBottom: 14 },
  label: {
    display: "block",
    fontSize: 13,
    fontWeight: 600,
    marginBottom: 6,
    color: "#444",
  },
  checkboxLabel: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    fontSize: 13,
    color: "#333",
    cursor: "pointer",
  },
  checkbox: {
    marginTop: 2,
    flexShrink: 0,
    width: 16,
    height: 16,
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
  submitButtonDisabled: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    background: "#aab8d6",
    color: "#fff",
    fontWeight: 600,
    cursor: "not-allowed",
  },
};

import { useState } from "react";
import { createStaffAccount, updateStaffAccount } from "../../api/admin.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// Mirrors StaffAccount.JobTitle on the backend (administration/models.py).
const JOB_TITLES = [
  "System Administrator", "General Manager", "Branch Manager",
  "Receptionist", "Coach", "Marketing Staff",
];

const EMPTY_FORM = { fullName: "", email: "", username: "", jobTitle: "", roleId: "", password: "" };

// User story: "As a system administrator, I want to create, edit and
// deactivate staff login accounts, so that only current staff can sign in
// to the system."
//
// Used for both creating a new account and editing an existing one -
// `account` is null for create, or the staff account being edited.
export default function StaffAccountForm({ account, roles, onClose, onSaved }) {
  const isEditing = Boolean(account);
  const [form, setForm] = useState(
    account
      ? {
          fullName: account.fullName,
          email: account.email,
          username: account.username,
          jobTitle: account.jobTitle,
          roleId: String(account.roleId),
          password: "",
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
      fullName: form.fullName,
      email: form.email,
      username: form.username,
      jobTitle: form.jobTitle,
      roleId: Number(form.roleId),
    };
    // On create, password is required. On edit, only send it if the admin
    // actually typed a new one - an empty field means "leave it unchanged".
    if (!isEditing || form.password) {
      payload.password = form.password;
    }

    try {
      const saved = isEditing
        ? await updateStaffAccount(account.id, payload)
        : await createStaffAccount(payload);
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
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Staff Account" : "New Staff Account"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <Field label="Full name" error={fieldErrors.fullName}>
            <input
              type="text"
              value={form.fullName}
              onChange={(e) => update("fullName", e.target.value)}
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

          <Field label="Username" error={fieldErrors.username}>
            <input
              type="text"
              value={form.username}
              onChange={(e) => update("username", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Job title" error={fieldErrors.jobTitle}>
            <select
              value={form.jobTitle}
              onChange={(e) => update("jobTitle", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a job title...</option>
              {JOB_TITLES.map((title) => (
                <option key={title} value={title}>
                  {title}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Role" error={fieldErrors.roleId}>
            <select
              value={form.roleId}
              onChange={(e) => update("roleId", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a role...</option>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </Field>

          <Field
            label={isEditing ? "New password (leave blank to keep current)" : "Password"}
            error={fieldErrors.password}
          >
            <input
              type="password"
              value={form.password}
              onChange={(e) => update("password", e.target.value)}
              style={styles.input}
              placeholder={isEditing ? "••••••••" : ""}
            />
          </Field>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Create account"}
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
    maxWidth: 420,
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

import { useState } from "react";
import { createRole, updateRole } from "../../api/admin.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const EMPTY_FORM = { name: "", description: "", permissions: [] };

// User story: "As a system administrator, I want to define roles with
// specific permission sets, so that access matches each job function."
//
// Used for both creating a new role and editing an existing one - `role`
// is null for create, or the role being edited.
export default function RoleForm({ role, permissions, onClose, onSaved }) {
  const isEditing = Boolean(role);
  const [form, setForm] = useState(
    role
      ? { name: role.name, description: role.description, permissions: role.permissions }
      : EMPTY_FORM
  );
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function togglePermission(key) {
    setForm((f) => ({
      ...f,
      permissions: f.permissions.includes(key)
        ? f.permissions.filter((p) => p !== key)
        : [...f.permissions, key],
    }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    try {
      const saved = isEditing ? await updateRole(role.id, form) : await createRole(form);
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
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Role" : "New Role"}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <Field label="Role name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              autoFocus
            />
          </Field>

          <Field label="Description" error={fieldErrors.description}>
            <input
              type="text"
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              style={styles.input}
              placeholder="What this role is for..."
            />
          </Field>

          <Field label="Permissions" error={fieldErrors.permissions}>
            <div style={styles.permissionList}>
              {permissions.map((p) => (
                <label key={p.key} style={styles.permissionRow}>
                  <input
                    type="checkbox"
                    checked={form.permissions.includes(p.key)}
                    onChange={() => togglePermission(p.key)}
                  />
                  {p.label}
                </label>
              ))}
            </div>
          </Field>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Create role"}
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
    maxWidth: 440,
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
  permissionList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    padding: 12,
    maxHeight: 220,
    overflowY: "auto",
  },
  permissionRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 14,
    cursor: "pointer",
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

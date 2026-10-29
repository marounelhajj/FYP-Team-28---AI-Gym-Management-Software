import { useCallback, useEffect, useState } from "react";
import { createClassType, fetchClassTypes, updateClassType } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// User story: "As a branch manager, I want to set maximum capacity per class
// type, so that I can prevent overbooking and keep sessions safe."
//
// The kinds of class a branch runs and the most people each can safely hold
// there. Every class of a type gets at most that many spots (see
// backend/classes/views.py class_type_detail for how a new maximum carries
// over to upcoming classes). Read-only for the front desk.

const DURATIONS = [15, 20, 30, 45, 60, 75, 90, 105, 120, 150, 180, 240];

export default function ClassTypeManager({ branch, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState(null); // {} for a new type, or the type
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    return fetchClassTypes(branch, { includeArchived: true })
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, [branch]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  function changed(message) {
    setNotice(message);
    load();
    onChanged?.();
  }

  async function toggleArchived(classType) {
    try {
      await updateClassType(classType.id, { isActive: !classType.isActive });
      changed(
        classType.isActive
          ? `${classType.name} archived - it can't be scheduled until it's restored.` +
              (classType.upcomingClasses ? ` Its ${classType.upcomingClasses} upcoming classes stay on the calendar.` : "")
          : `${classType.name} can be scheduled again.`,
      );
    } catch (err) {
      setError(err.message);
    }
  }

  if (!data) return error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>;

  const visible = data.results.filter((t) => showArchived || t.isActive);
  const archivedCount = data.results.length - data.results.filter((t) => t.isActive).length;

  return (
    <div>
      <div style={styles.header}>
        <p style={styles.intro}>
          The most people each kind of class can safely hold at {data.branch} - bikes, mats, one coach&apos;s group. No class of a
          type can be given more spots, so it can never be overbooked.
        </p>
        {data.canEdit && (
          <button type="button" onClick={() => setEditing({})} style={styles.primaryButton}>
            Add class type
          </button>
        )}
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      {archivedCount > 0 && (
        <label style={styles.checkbox}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived ({archivedCount})
        </label>
      )}

      {data.results.length === 0 ? (
        <div style={styles.empty}>
          No class types at {data.branch} yet. Add the classes the branch runs - Spinning, Yoga, HIIT... - with how many
          people each can safely hold.
        </div>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Class type</th>
                <th style={styles.th}>Max capacity</th>
                <th style={styles.th}>Default length</th>
                <th style={styles.th}>Upcoming classes</th>
                <th style={styles.th}>Most booked</th>
                {data.canEdit && <th style={styles.th} />}
              </tr>
            </thead>
            <tbody>
              {visible.map((t) => (
                <tr key={t.id} style={t.isActive ? null : styles.archivedRow}>
                  <td style={{ ...styles.td, fontWeight: 700 }}>
                    {t.name}
                    {!t.isActive && <span style={styles.archivedTag}>Archived</span>}
                    {t.description && <div style={styles.cellSub}>{t.description}</div>}
                  </td>
                  <td style={styles.td}>
                    <span style={styles.capacity}>{t.maxCapacity}</span> people
                  </td>
                  <td style={styles.td}>{t.defaultDurationMinutes} min</td>
                  <td style={styles.td}>{t.upcomingClasses}</td>
                  <td style={styles.td}>
                    {t.upcomingClasses ? (
                      <span style={t.mostBookedUpcoming >= t.maxCapacity ? styles.fullText : null}>
                        {t.mostBookedUpcoming} / {t.maxCapacity}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  {data.canEdit && (
                    <td style={{ ...styles.td, whiteSpace: "nowrap", textAlign: "right" }}>
                      <button type="button" onClick={() => setEditing(t)} style={styles.rowButton}>
                        Edit
                      </button>
                      <button type="button" onClick={() => toggleArchived(t)} style={styles.rowButton}>
                        {t.isActive ? "Archive" : "Restore"}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <ClassTypeForm
          classType={editing.id ? editing : null}
          branch={data.branch}
          onClose={() => setEditing(null)}
          onSaved={(saved, isNew) => {
            setEditing(null);
            changed(
              isNew
                ? `${saved.name} added - up to ${saved.maxCapacity} people per class.`
                : `${saved.name} saved` +
                    (saved.adjustedClasses
                      ? ` - ${saved.adjustedClasses} upcoming class${saved.adjustedClasses === 1 ? "" : "es"} now hold${
                          saved.adjustedClasses === 1 ? "s" : ""
                        } ${saved.maxCapacity} people.`
                      : "."),
            );
          }}
        />
      )}
    </div>
  );
}

function ClassTypeForm({ classType, branch, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: classType?.name || "",
    maxCapacity: classType?.maxCapacity ?? 15,
    defaultDurationMinutes: classType?.defaultDurationMinutes ?? 60,
    description: classType?.description || "",
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));
  const newMax = Number(form.maxCapacity);
  const floor = classType?.mostBookedUpcoming || 0;
  const belowBookings = classType && newMax < floor;
  const durations = [...new Set([...DURATIONS, Number(form.defaultDurationMinutes)])].sort((a, b) => a - b);
  const cannotSave = saving || !form.name.trim() || !newMax || newMax < 1 || newMax > 100 || belowBookings;

  let impact = null;
  if (classType && classType.upcomingClasses && newMax && newMax !== classType.maxCapacity && !belowBookings) {
    impact =
      newMax < classType.maxCapacity
        ? `Upcoming ${classType.name} classes with more than ${newMax} spots will be cut to ${newMax}.`
        : `Upcoming ${classType.name} classes at the old maximum (${classType.maxCapacity}) will go up to ${newMax}.`;
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFieldErrors({});
    setConflicts([]);
    setError(null);
    const payload = {
      name: form.name,
      maxCapacity: newMax,
      defaultDurationMinutes: Number(form.defaultDurationMinutes),
      description: form.description,
    };
    try {
      const saved = classType ? await updateClassType(classType.id, payload) : await createClassType({ ...payload, branch });
      onSaved(saved, !classType);
    } catch (err) {
      if (err.fieldErrors?.conflicts) setConflicts(err.fieldErrors.conflicts);
      else if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
      setSaving(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={classType ? `Edit ${classType.name}` : "Add class type"}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{classType ? `Edit ${classType.name}` : `Add a class type · ${branch}`}</h2>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        <form onSubmit={submit}>
          <Field label="Name" error={fieldErrors.name}>
            <input value={form.name} onChange={(e) => update("name", e.target.value)} placeholder="e.g. Spinning" style={styles.input} autoFocus />
          </Field>
          <Field label="Maximum capacity (people per class)" error={fieldErrors.maxCapacity}>
            <input
              type="number"
              min={Math.max(1, floor)}
              max="100"
              value={form.maxCapacity}
              onChange={(e) => update("maxCapacity", e.target.value)}
              style={styles.input}
            />
          </Field>
          <p style={styles.hint}>The most people one {form.name.trim() || "class"} can safely hold at {branch}.</p>
          {belowBookings && (
            <div style={styles.errorBox}>
              An upcoming {classType.name} class already has {floor} bookings - the maximum can&apos;t go below {floor} until
              those people are moved.
            </div>
          )}
          {impact && <div style={styles.warnBox}>{impact} Classes that already started stay as they were.</div>}
          <Field label="Default length" error={fieldErrors.defaultDurationMinutes}>
            <select value={form.defaultDurationMinutes} onChange={(e) => update("defaultDurationMinutes", e.target.value)} style={styles.input}>
              {durations.map((m) => (
                <option key={m} value={m}>
                  {m} min
                </option>
              ))}
            </select>
          </Field>
          <Field label="Description (optional)" error={fieldErrors.description}>
            <input value={form.description} onChange={(e) => update("description", e.target.value)} style={styles.input} />
          </Field>

          {conflicts.length > 0 && (
            <div style={styles.errorBox}>
              <strong>Too many people are already booked:</strong>
              <ul style={styles.list}>
                {conflicts.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {error && <div style={styles.errorBox}>{error}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.secondaryButton}>
              Cancel
            </button>
            <button
              type="submit"
              disabled={cannotSave}
              style={cannotSave ? { ...styles.primaryButton, ...styles.buttonDisabled } : styles.primaryButton}
            >
              {saving ? "Saving..." : classType ? "Save changes" : "Add class type"}
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
  muted: { fontSize: 13, color: "#888" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 12 },
  intro: { fontSize: 14, color: "#555", margin: 0, maxWidth: 680, lineHeight: 1.5 },
  checkbox: { display: "inline-flex", alignItems: "center", gap: 6, fontSize: 14, color: "#444", marginBottom: 10 },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 14, color: "#777", textAlign: "center" },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "middle" },
  cellSub: { fontSize: 12, color: "#888", fontWeight: 400, marginTop: 2 },
  capacity: { fontSize: 18, fontWeight: 800, color: "#124096" },
  fullText: { color: "#b3261e", fontWeight: 700 },
  archivedRow: { color: "#999", background: "#fafafa" },
  archivedTag: { marginLeft: 8, padding: "2px 6px", borderRadius: 4, background: "#ececf0", color: "#666", fontSize: 11 },
  rowButton: {
    padding: "5px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    color: "#333",
    cursor: "pointer",
    marginLeft: 6,
  },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  warnBox: { background: "#fff7e0", color: "#7a5600", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 12 },
  list: { margin: "6px 0 0", paddingLeft: 18 },
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
    boxSizing: "border-box",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  field: { marginBottom: 12 },
  label: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  hint: { fontSize: 13, color: "#555", margin: "-4px 0 12px" },
  input: {
    width: "100%",
    padding: "9px 11px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 },
  primaryButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  buttonDisabled: { background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  secondaryButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

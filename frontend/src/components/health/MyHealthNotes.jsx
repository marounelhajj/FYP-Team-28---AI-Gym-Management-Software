import { useCallback, useEffect, useState } from "react";
import { addHealthNote, confirmMyHealth, deleteHealthNote, fetchMyHealth, updateHealthNote } from "../../api/health.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { HealthNoteItem, formatDay } from "./HealthViews.jsx";

// The member's side of: "As a coach, I want to view a client's health
// restrictions and injuries before starting a session, so that I can adapt
// the workout safely."
//
// On the member dashboard: the member lists their own injuries, medical
// conditions and restrictions, marks them recovered, or says there's nothing
// to declare. Only they can change this; the card says who gets to read it.

const EMPTY = { kind: "Injury", bodyArea: "General", severity: "Moderate", title: "", details: "", since: "" };
const DETAILS_LIMIT = 500;

export default function MyHealthNotes() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  // The open form: { id? , ...fields } or null.
  const [form, setForm] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [showRecovered, setShowRecovered] = useState(false);

  const load = useCallback(() => {
    fetchMyHealth().then(setData).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(t);
  }, [notice]);

  // Runs one change; every endpoint answers with the whole updated list.
  async function run(action, message) {
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      setData(await action());
      setNotice(message);
      return true;
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function openForm(note) {
    setError(null);
    setFieldErrors({});
    setConfirmDelete(null);
    setForm(
      note
        ? { id: note.id, kind: note.kind, bodyArea: note.bodyArea, severity: note.severity, title: note.title, details: note.details, since: note.since || "" }
        : { ...EMPTY },
    );
  }

  async function submit(e) {
    e.preventDefault();
    const { id, ...fields } = form;
    const body = { ...fields, since: fields.since || null };
    const ok = await run(
      () => (id ? updateHealthNote(id, body) : addHealthNote(body)),
      id ? "Saved." : "Added. Your coach will see it before your next session.",
    );
    if (ok) setForm(null);
  }

  if (!data) {
    return <div style={styles.card}>{error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>}</div>;
  }

  const full = data.active.length >= data.maxActive;
  const set = (field) => (e) => setForm({ ...form, [field]: e.target.value });
  const fieldError = (field) => fieldErrors[field] && <span style={styles.fieldError}>{fieldErrors[field][0]}</span>;

  return (
    <section style={styles.card} aria-label="Health and injuries">
      <p style={styles.privacy}>{data.sharedWith}</p>
      {notice && <div style={styles.successBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      {data.reviewedOn === null && data.active.length === 0 && (
        <div style={styles.askBox}>
          You haven&apos;t told us about your health yet. Add any injury or condition your coach should know about,
          or confirm there&apos;s nothing to declare.
        </div>
      )}
      {data.needsReview && (
        <div style={styles.askBox}>You last confirmed this on {formatDay(data.reviewedOn)}. Is it still up to date?</div>
      )}
      {data.reviewedOn !== null && data.active.length === 0 && !data.needsReview && (
        <div style={styles.clearBox}>Nothing to declare - confirmed {formatDay(data.reviewedOn)}.</div>
      )}

      {data.active.length > 0 && (
        <ul style={styles.list}>
          {data.active.map((note) => (
            <HealthNoteItem key={note.id} note={note}>
              {confirmDelete === note.id ? (
                <div style={styles.rowActions}>
                  <span style={styles.confirmText}>Delete this note for good?</span>
                  <button type="button" onClick={() => setConfirmDelete(null)} style={styles.smallButton} disabled={busy}>
                    Keep it
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await run(() => deleteHealthNote(note.id), "Deleted.");
                      setConfirmDelete(null);
                    }}
                    style={styles.dangerButton}
                    disabled={busy}
                  >
                    Delete
                  </button>
                </div>
              ) : (
                <div style={styles.rowActions}>
                  <button type="button" onClick={() => openForm(note)} style={styles.smallButton} disabled={busy}>
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => run(() => updateHealthNote(note.id, { status: "Resolved" }), "Marked as recovered.")}
                    style={styles.smallButton}
                    disabled={busy}
                    aria-label={`Mark ${note.title} as recovered`}
                  >
                    I&apos;ve recovered
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(note.id)}
                    style={styles.linkDanger}
                    disabled={busy}
                    aria-label={`Delete ${note.title}`}
                  >
                    Delete
                  </button>
                </div>
              )}
            </HealthNoteItem>
          ))}
        </ul>
      )}

      {form ? (
        <form onSubmit={submit} style={styles.form}>
          <div style={styles.formTitle}>{form.id ? "Edit note" : "Add an injury or restriction"}</div>
          <label style={styles.field}>
            <span style={styles.label}>What is it?</span>
            <input
              value={form.title}
              onChange={set("title")}
              maxLength={80}
              placeholder="e.g. Lower back pain, asthma, torn ACL (left knee)"
              style={styles.input}
              autoFocus
            />
            {fieldError("title")}
          </label>
          <div style={styles.formRow}>
            <label style={styles.field}>
              <span style={styles.label}>Type</span>
              <select value={form.kind} onChange={set("kind")} style={styles.input}>
                {data.choices.kind.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              {fieldError("kind")}
            </label>
            <label style={styles.field}>
              <span style={styles.label}>Body area</span>
              <select value={form.bodyArea} onChange={set("bodyArea")} style={styles.input}>
                {data.choices.bodyArea.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              {fieldError("bodyArea")}
            </label>
          </div>
          <label style={styles.field}>
            <span style={styles.label}>How much does it limit your training?</span>
            <select value={form.severity} onChange={set("severity")} style={styles.input}>
              {data.choices.severity.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
            {fieldError("severity")}
          </label>
          <label style={styles.field}>
            <span style={styles.label}>What should your coach avoid or adapt? (optional)</span>
            <textarea
              value={form.details}
              onChange={set("details")}
              maxLength={DETAILS_LIMIT}
              rows={3}
              placeholder="e.g. No jumping or deep squats. Doctor cleared light cycling."
              style={styles.textarea}
            />
            <span style={styles.hint}>{form.details.length}/{DETAILS_LIMIT}</span>
            {fieldError("details")}
          </label>
          <label style={styles.field}>
            <span style={styles.label}>Since (optional)</span>
            <input type="date" value={form.since} onChange={set("since")} style={styles.input} />
            {fieldError("since")}
          </label>
          <div style={styles.actions}>
            <button type="button" onClick={() => setForm(null)} style={styles.secondaryButton} disabled={busy}>
              Cancel
            </button>
            <button type="submit" style={styles.primaryButton} disabled={busy || !form.title.trim()}>
              {busy ? "Saving..." : form.id ? "Save changes" : "Add note"}
            </button>
          </div>
        </form>
      ) : (
        <div style={styles.actions}>
          {(data.reviewedOn === null || data.needsReview) && (
            <button type="button" onClick={() => run(confirmMyHealth, "Thanks - confirmed.")} style={styles.secondaryButton} disabled={busy}>
              {data.active.length === 0 ? "Nothing to declare" : "Yes, still up to date"}
            </button>
          )}
          <button
            type="button"
            onClick={() => openForm(null)}
            style={full ? styles.disabledButton : styles.primaryButton}
            disabled={busy || full}
            title={full ? `You can have up to ${data.maxActive} active notes.` : undefined}
          >
            + Add injury or restriction
          </button>
        </div>
      )}

      {data.recovered.length > 0 && (
        <div>
          <button type="button" onClick={() => setShowRecovered((s) => !s)} style={styles.linkButton} aria-expanded={showRecovered}>
            {showRecovered ? "Hide" : "Show"} recovered ({data.recovered.length})
          </button>
          {showRecovered && (
            <ul style={{ ...styles.list, marginTop: 8 }}>
              {data.recovered.map((note) => (
                <HealthNoteItem key={note.id} note={note}>
                  <div style={styles.rowActions}>
                    <button
                      type="button"
                      onClick={() => run(() => updateHealthNote(note.id, { status: "Active" }), "It's active again.")}
                      style={styles.smallButton}
                      disabled={busy}
                      aria-label={`${note.title} is back`}
                    >
                      It&apos;s back
                    </button>
                    <button
                      type="button"
                      onClick={() => run(() => deleteHealthNote(note.id), "Deleted.")}
                      style={styles.linkDanger}
                      disabled={busy}
                      aria-label={`Delete ${note.title}`}
                    >
                      Delete
                    </button>
                  </div>
                </HealthNoteItem>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", display: "flex", flexDirection: "column", gap: 10 },
  privacy: { fontSize: 12, color: "#666", margin: 0, lineHeight: 1.5 },
  muted: { fontSize: 13, color: "#888", margin: 0 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 13 },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "8px 12px", borderRadius: 8, fontSize: 13 },
  askBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 12px", borderRadius: 8, fontSize: 13, lineHeight: 1.45 },
  clearBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 12px", borderRadius: 8, fontSize: 13 },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  rowActions: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 6 },
  confirmText: { fontSize: 12, color: "#444", flex: 1 },
  smallButton: { padding: "5px 10px", fontSize: 12, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 6, background: "#f5f5f7", cursor: "pointer" },
  linkDanger: { border: "none", background: "none", color: "#b3261e", fontSize: 12, fontWeight: 600, cursor: "pointer", marginLeft: "auto" },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer", padding: 0 },
  dangerButton: { padding: "5px 10px", fontSize: 12, fontWeight: 700, border: "none", borderRadius: 6, ...BUTTON_COLORS.red, cursor: "pointer" },
  form: { display: "flex", flexDirection: "column", gap: 10, padding: 12, border: "1px solid #dfe5f2", borderRadius: 10, background: "#f7f9fd" },
  formTitle: { fontSize: 14, fontWeight: 700 },
  formRow: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 },
  label: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", boxSizing: "border-box", width: "100%" },
  textarea: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit", resize: "vertical", boxSizing: "border-box", width: "100%" },
  hint: { fontSize: 11, color: "#888" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" },
  primaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  disabledButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  secondaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
};

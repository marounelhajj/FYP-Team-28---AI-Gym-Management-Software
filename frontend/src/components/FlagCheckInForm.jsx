import { useState } from "react";
import { flagCheckIn } from "../api/checkins.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";

const REASONS = [
  { value: "Duplicate check-in", hint: "Tried to check in while this membership is already inside." },
  { value: "Membership sharing", hint: "The person isn't the member - the photo or ID doesn't match." },
  { value: "Card misuse", hint: "An old, replaced or someone else's card or QR code was used." },
  { value: "Other", hint: "Anything else that looked wrong (describe it in the note)." },
];

// The reason the desk would most likely pick for this kind of attempt.
function suggestedReason(checkIn) {
  if (checkIn.reason === "Already checked in") return "Duplicate check-in";
  if (checkIn.reason === "Replaced card") return "Card misuse";
  return "";
}

// Flags one check-in attempt as suspicious. The member is then flagged at
// every check-in (photo ID check) until the flag is dismissed.
export default function FlagCheckInForm({ checkIn, onClose, onFlagged }) {
  const [reason, setReason] = useState(() => suggestedReason(checkIn));
  const [note, setNote] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const noteRequired = reason === "Other";
  const canSubmit = Boolean(reason && (!noteRequired || note.trim()) && !submitting);
  const attempt = checkIn.result === "Allowed" ? "Allowed in" : `Denied (${checkIn.reason})`;

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    try {
      onFlagged(await flagCheckIn(checkIn.id, { reason, note }));
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <h2 style={styles.title}>Flag Check-In Attempt</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <div style={styles.attempt}>
          <div style={styles.attemptName}>
            {checkIn.memberName} <span style={styles.attemptId}>#{checkIn.memberId}</span>
          </div>
          <div style={styles.attemptMeta}>
            {checkIn.checkedInAt} &middot; {attempt}
          </div>
          {checkIn.suspicion && <div style={styles.suspicion}>{checkIn.suspicion}</div>}
        </div>

        <form onSubmit={handleSubmit}>
          <div style={styles.label}>What looked suspicious?</div>
          <div role="radiogroup" aria-label="Reason" style={styles.reasons}>
            {REASONS.map((r) => {
              const selected = reason === r.value;
              return (
                <button
                  key={r.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setReason(r.value)}
                  style={selected ? { ...styles.reason, ...styles.reasonSelected } : styles.reason}
                >
                  <span style={styles.reasonTitle}>{r.value}</span>
                  <span style={styles.reasonHint}>{r.hint}</span>
                </button>
              );
            })}
          </div>
          {fieldErrors.reason && <div style={styles.fieldError}>{fieldErrors.reason[0]}</div>}

          <label style={styles.label} htmlFor="flag-note">
            Note {noteRequired ? "(required)" : "(optional)"}
          </label>
          <input
            id="flag-note"
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={200}
            placeholder={noteRequired ? "What happened?" : "e.g. face didn't match the member photo"}
            style={styles.input}
          />
          {fieldErrors.note && <div style={styles.fieldError}>{fieldErrors.note[0]}</div>}

          <p style={styles.hint}>
            Until this flag is dismissed, the desk will be asked to check {checkIn.memberName}'s photo ID every time
            they check in.
          </p>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              style={canSubmit ? styles.submitButton : { ...styles.submitButton, ...styles.disabled }}
            >
              {submitting ? "Flagging..." : "Flag attempt"}
            </button>
          </div>
        </form>
      </div>
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
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  title: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  attempt: {
    padding: "12px 14px",
    marginBottom: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fafafa",
  },
  attemptName: { fontSize: 15, fontWeight: 700 },
  attemptId: { fontSize: 12, fontWeight: 600, color: "#888" },
  attemptMeta: { fontSize: 12, color: "#666", marginTop: 2 },
  suspicion: { fontSize: 12, color: "#8a5a00", fontWeight: 600, marginTop: 6 },
  label: { display: "block", fontSize: 13, fontWeight: 600, color: "#444", margin: "0 0 6px" },
  reasons: { display: "grid", gap: 8, marginBottom: 14 },
  reason: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 2,
    padding: "10px 12px",
    textAlign: "left",
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  reasonSelected: { border: "1px solid #de0b12", background: "#fdeceb", boxShadow: "inset 0 0 0 1px #de0b12" },
  reasonTitle: { fontSize: 14, fontWeight: 700, color: "#1a1a1a" },
  reasonHint: { fontSize: 12, color: "#666" },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    boxSizing: "border-box",
  },
  hint: { fontSize: 12, color: "#777", margin: "12px 0 0", lineHeight: 1.45 },
  fieldError: { color: "#b3261e", fontSize: 12, margin: "-8px 0 12px" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginTop: 12,
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
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
  disabled: { opacity: 0.5, cursor: "not-allowed" },
};

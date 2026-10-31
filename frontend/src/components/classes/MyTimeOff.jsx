import { useCallback, useEffect, useState } from "react";
import { addMyTimeOff, fetchMyTimeOff, removeMyTimeOff } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// A coach's own calendar blocks: time marked unavailable so members can't
// book a PT session into it (see members' MemberPrivateTraining.jsx, which
// shows it as "Unavailable") and so it can't be double-booked against a
// class or session already on the coach's schedule (see MySchedule.jsx).
//
// User story: "As a coach, I want to block off time on my calendar when
// I'm unavailable, so that members can't book me during that time."

const EMPTY = { start: "", end: "", reason: "" };

export default function MyTimeOff() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [formErrors, setFormErrors] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    return fetchMyTimeOff()
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    setFormErrors({});
    setConflicts([]);
    try {
      const saved = await addMyTimeOff({
        startsAt: form.start,
        endsAt: form.end,
        reason: form.reason.trim(),
      });
      setForm(EMPTY);
      setNotice(`Blocked ${saved.startsAt}–${saved.endsAt.slice(11)} - members can't book you then.`);
      load();
    } catch (err) {
      if (err.fieldErrors?.conflicts) setConflicts(err.fieldErrors.conflicts);
      else if (err.fieldErrors) setFormErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(block) {
    try {
      await removeMyTimeOff(block.id);
      setNotice(`Removed the block on ${block.startsAt}–${block.endsAt.slice(11)} - members can book you again then.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (!data) return error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>;

  const firstError = (key) => (Array.isArray(formErrors[key]) ? formErrors[key][0] : null);
  const upcoming = data.blocks.filter((b) => b.state !== "finished");
  const past = data.blocks.filter((b) => b.state === "finished");

  return (
    <div>
      <p style={styles.intro}>
        Block off time you're unavailable for private training. Members can't book a session into a block, and it
        can't overlap a class or session you already have.
      </p>
      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <form onSubmit={add} style={styles.addForm}>
        <Labeled label="From">
          <input
            type="datetime-local"
            value={form.start}
            onChange={(e) => update("start", e.target.value)}
            style={styles.input}
            required
          />
        </Labeled>
        <Labeled label="To">
          <input
            type="datetime-local"
            value={form.end}
            onChange={(e) => update("end", e.target.value)}
            style={styles.input}
            required
          />
        </Labeled>
        <Labeled label="Reason (optional)">
          <input
            type="text"
            value={form.reason}
            onChange={(e) => update("reason", e.target.value)}
            placeholder="e.g. Vacation"
            maxLength={200}
            style={{ ...styles.input, width: 180 }}
          />
        </Labeled>
        <button
          type="submit"
          disabled={saving || !form.start || !form.end}
          style={
            saving || !form.start || !form.end
              ? { ...styles.primaryButton, ...styles.buttonDisabled }
              : styles.primaryButton
          }
        >
          {saving ? "Blocking..." : "Block time off"}
        </button>
      </form>
      {(firstError("startsAt") || firstError("endsAt") || firstError("reason")) && (
        <div style={styles.errorBox}>{firstError("startsAt") || firstError("endsAt") || firstError("reason")}</div>
      )}
      {conflicts.length > 0 && <div style={styles.errorBox}>{conflicts.join(" ")}</div>}

      {upcoming.length === 0 && past.length === 0 ? (
        <div style={styles.empty}>You haven't blocked any time off.</div>
      ) : (
        <>
          {upcoming.length > 0 && (
            <div style={styles.list}>
              {upcoming.map((b) => (
                <BlockRow key={b.id} block={b} onRemove={remove} />
              ))}
            </div>
          )}
          {past.length > 0 && (
            <>
              <p style={styles.pastLabel}>Past</p>
              <div style={styles.list}>
                {past.map((b) => (
                  <BlockRow key={b.id} block={b} onRemove={remove} muted />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function BlockRow({ block, onRemove, muted }) {
  return (
    <div style={muted ? { ...styles.row, ...styles.rowMuted } : styles.row}>
      <div>
        <div style={styles.rowTime}>
          {block.startsAt}–{block.endsAt.slice(11)}
          {block.state === "in_progress" && <span style={styles.tag}>Now</span>}
        </div>
        {block.reason && <div style={styles.rowReason}>{block.reason}</div>}
      </div>
      {!muted && (
        <button type="button" onClick={() => onRemove(block)} style={styles.removeButton}>
          Remove
        </button>
      )}
    </div>
  );
}

function Labeled({ label, children }) {
  return (
    <label style={styles.labeled}>
      <span style={styles.label}>{label}</span>
      {children}
    </label>
  );
}

const styles = {
  muted: { fontSize: 12, color: "#888", margin: "0 0 10px" },
  intro: { fontSize: 14, color: "#555", margin: "0 0 12px", maxWidth: 760, lineHeight: 1.5 },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  empty: { padding: 16, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 14, color: "#888", textAlign: "center" },
  addForm: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: 10,
    padding: 14,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 12,
  },
  labeled: { display: "flex", flexDirection: "column", gap: 4 },
  label: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: {
    padding: "8px 10px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  primaryButton: {
    padding: "9px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
  buttonDisabled: { background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  pastLabel: { fontSize: 12, fontWeight: 600, color: "#888", margin: "16px 0 6px" },
  list: { display: "flex", flexDirection: "column", gap: 8 },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 14px",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  rowMuted: { background: "#f7f7f9", color: "#888" },
  rowTime: { fontSize: 14, fontWeight: 600, display: "flex", alignItems: "center", gap: 8 },
  rowReason: { fontSize: 13, color: "#777", marginTop: 2 },
  tag: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 7px",
    borderRadius: 999,
    background: "#124096",
    color: "#fff",
  },
  removeButton: {
    padding: "6px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    cursor: "pointer",
  },
};

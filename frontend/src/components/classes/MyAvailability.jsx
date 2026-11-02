import { useCallback, useEffect, useState } from "react";
import { addMyPtHours, fetchMyPtHours, removeMyPtHours } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// A coach's own private training hours: set when you're free, members book
// straight into it (cut into sessions of the length you choose - see
// PTBookSerializer / my_pt_slots), no front desk involved. A branch manager
// can still add or remove a coach's hours from the branch's PT hours
// screen (PTHoursManager.jsx) - this is the same data, just scoped to
// yourself and reachable without that permission.
//
// User story: "As a coach, I want to set my own availability for personal
// training sessions, so that members can book time with me directly
// instead of going through the front desk."

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));
const EMPTY = { branch: "", weekday: "0", start: "09:00", end: "12:00", sessionMinutes: "60" };

export default function MyAvailability() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [formErrors, setFormErrors] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    return fetchMyPtHours()
      .then((body) => {
        setData(body);
        setError(null);
        setForm((f) => (f.branch || body.branches.length !== 1 ? f : { ...f, branch: body.branches[0] }));
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
      const saved = await addMyPtHours({
        branch: form.branch || undefined,
        weekday: Number(form.weekday),
        startTime: form.start,
        endTime: form.end,
        sessionMinutes: Number(form.sessionMinutes),
      });
      setForm((f) => ({ ...EMPTY, branch: f.branch, weekday: f.weekday, sessionMinutes: f.sessionMinutes }));
      setNotice(`Added ${saved.day} ${saved.startTime}–${saved.endTime} at ${saved.branch} - members can book it now.`);
      load();
    } catch (err) {
      if (err.fieldErrors?.conflicts) setConflicts(err.fieldErrors.conflicts);
      else if (err.fieldErrors) setFormErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(hours) {
    try {
      const result = await removeMyPtHours(hours.id);
      setNotice(
        `Removed ${hours.day} ${hours.startTime}–${hours.endTime} at ${hours.branch}.` +
          (result.bookedSessionsKept
            ? ` ${result.bookedSessionsKept} session${result.bookedSessionsKept === 1 ? "" : "s"} already booked in it stay booked.`
            : ""),
      );
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (!data) return error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>;

  const firstError = (key) => (Array.isArray(formErrors[key]) ? formErrors[key][0] : null);
  const floating = data.branches.length > 1;

  return (
    <div>
      <p style={styles.intro}>
        Set the hours you're free for private training{floating ? "" : ` at ${data.branches[0]}`}. Members book a
        session straight into them, cut into the length you choose below - no front desk involved. A session can't
        be booked while you're teaching a class, and members need at least an hour's notice.
      </p>
      {data.sessions.length > 0 && (
        <p style={styles.muted}>
          You have {data.sessions.length} upcoming session{data.sessions.length === 1 ? "" : "s"} booked. Removing
          hours doesn't cancel a session already booked in them.
        </p>
      )}
      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <form onSubmit={add} style={styles.addForm}>
        {floating && (
          <Labeled label="Branch">
            <select value={form.branch} onChange={(e) => update("branch", e.target.value)} style={styles.input}>
              <option value="">Choose a branch</option>
              {data.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Labeled>
        )}
        <Labeled label="Every">
          <select value={form.weekday} onChange={(e) => update("weekday", e.target.value)} style={styles.input}>
            {DAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>
        </Labeled>
        <Labeled label="From (24h)">
          <TimePick value={form.start} onChange={(v) => update("start", v)} label="From" />
        </Labeled>
        <Labeled label="To">
          <TimePick value={form.end} onChange={(v) => update("end", v)} label="To" />
        </Labeled>
        <Labeled label="Sessions of">
          <select value={form.sessionMinutes} onChange={(e) => update("sessionMinutes", e.target.value)} style={styles.input}>
            {data.sessionLengths.map((m) => (
              <option key={m} value={m}>
                {m} min
              </option>
            ))}
          </select>
        </Labeled>
        <button
          type="submit"
          disabled={saving || (floating && !form.branch)}
          style={saving || (floating && !form.branch) ? { ...styles.primaryButton, ...styles.buttonDisabled } : styles.primaryButton}
        >
          {saving ? "Adding..." : "Add hours"}
        </button>
      </form>
      {(firstError("branch") || firstError("endTime") || firstError("startTime") || firstError("sessionMinutes")) && (
        <div style={styles.errorBox}>
          {firstError("branch") || firstError("endTime") || firstError("startTime") || firstError("sessionMinutes")}
        </div>
      )}
      {conflicts.length > 0 && <div style={styles.errorBox}>{conflicts.join(" ")}</div>}

      {data.hours.length === 0 ? (
        <div style={styles.empty}>You haven't set any private training hours yet.</div>
      ) : (
        <div style={styles.chips}>
          {data.hours.map((h) => (
            <span key={h.id} style={styles.chip}>
              {h.day} {h.startTime}–{h.endTime} · {h.sessionMinutes} min
              {floating && ` · ${h.branch}`}
              <button
                type="button"
                onClick={() => remove(h)}
                style={styles.chipRemove}
                aria-label={`Remove ${h.day} ${h.startTime} hours`}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function TimePick({ value, onChange, label }) {
  return (
    <span style={styles.timePick}>
      <select aria-label={`${label} hour`} value={value.slice(0, 2)} onChange={(e) => onChange(`${e.target.value}:${value.slice(3, 5)}`)} style={styles.input}>
        {HOURS.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
      <span>:</span>
      <select aria-label={`${label} minute`} value={value.slice(3, 5)} onChange={(e) => onChange(`${value.slice(0, 2)}:${e.target.value}`)} style={styles.input}>
        {MINUTES.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </span>
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
  timePick: { display: "inline-flex", alignItems: "center", gap: 3 },
  chips: { display: "flex", flexWrap: "wrap", gap: 6 },
  chip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "4px 8px",
    borderRadius: 999,
    background: "#e3f5e8",
    color: "#0f6e2b",
    fontSize: 12,
    fontWeight: 600,
  },
  chipRemove: { border: "none", background: "none", color: "#0f6e2b", fontSize: 15, lineHeight: 1, cursor: "pointer", padding: 0 },
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
};

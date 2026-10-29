import { useCallback, useEffect, useState } from "react";
import { addPtHours, cancelPtSessionAsStaff, fetchPtHours, removePtHours } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { formatDay } from "./dates.js";

// The branch manager's side of private training: each coach's weekly PT hours
// at the branch (what members can book into, cut into sessions of the chosen
// length) and the sessions members have booked. A coach's hours can't
// overlap, even across branches; removing hours keeps sessions already booked
// in them. The front desk sees this read-only.
//
// User story: "As a member, I want to browse and book available classes or PT
// sessions directly through the app, so that I can reserve my spot without
// contacting the front desk." (the hours members book into)

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));
const EMPTY = { coachId: "", weekday: "0", start: "09:00", end: "12:00", sessionMinutes: "60" };

export default function PTHoursManager({ branch, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [formErrors, setFormErrors] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [cancelling, setCancelling] = useState(null);

  const load = useCallback(() => {
    return fetchPtHours(branch)
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

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    setFormErrors({});
    setConflicts([]);
    try {
      const saved = await addPtHours({
        branch,
        coachId: Number(form.coachId),
        weekday: Number(form.weekday),
        startTime: form.start,
        endTime: form.end,
        sessionMinutes: Number(form.sessionMinutes),
      });
      // Keep the coach, day and session length for the next block of hours.
      setForm((f) => ({ ...EMPTY, coachId: f.coachId, weekday: f.weekday, sessionMinutes: f.sessionMinutes }));
      changed(`Added ${saved.day} ${saved.startTime}–${saved.endTime} for members to book.`);
    } catch (err) {
      if (err.fieldErrors?.conflicts) setConflicts(err.fieldErrors.conflicts);
      else if (err.fieldErrors) setFormErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(coach, hours) {
    try {
      const result = await removePtHours(hours.id);
      changed(
        `Removed ${coach.name}'s ${hours.day} ${hours.startTime}–${hours.endTime}.` +
          (result.bookedSessionsKept
            ? ` ${result.bookedSessionsKept} session${result.bookedSessionsKept === 1 ? "" : "s"} already booked in them stay booked.`
            : ""),
      );
    } catch (err) {
      setError(err.message);
    }
  }

  if (!data) return error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>;

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));
  const firstError = (key) => (Array.isArray(formErrors[key]) ? formErrors[key][0] : null);

  return (
    <div>
      <p style={styles.intro}>
        Members book one-to-one sessions inside these hours, cut into sessions of the length you choose. A session
        can&apos;t be booked while the coach is teaching a class, and members need at least an hour&apos;s notice.
      </p>
      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      {data.canEdit && (
        <form onSubmit={add} style={styles.addForm}>
          <Labeled label="Coach">
            <select value={form.coachId} onChange={(e) => update("coachId", e.target.value)} style={styles.input}>
              <option value="">Choose a coach</option>
              {data.coaches.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.branch ? "" : " (any branch)"}
                </option>
              ))}
            </select>
          </Labeled>
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
            disabled={saving || !form.coachId}
            style={saving || !form.coachId ? { ...styles.primaryButton, ...styles.buttonDisabled } : styles.primaryButton}
          >
            {saving ? "Adding..." : "Add hours"}
          </button>
        </form>
      )}
      {(firstError("coachId") || firstError("endTime") || firstError("startTime") || firstError("sessionMinutes")) && (
        <div style={styles.errorBox}>
          {firstError("coachId") || firstError("endTime") || firstError("startTime") || firstError("sessionMinutes")}
        </div>
      )}
      {conflicts.length > 0 && <div style={styles.errorBox}>{conflicts.join(" ")}</div>}

      <div style={styles.coachGrid}>
        {data.coaches.map((c) => (
          <div key={c.id} style={styles.coachCard}>
            <div style={styles.coachName}>
              {c.name}
              {!c.branch && <span style={styles.anyTag}>any branch</span>}
            </div>
            {c.hours.length === 0 ? (
              <div style={styles.muted}>No private training hours at {data.branch}.</div>
            ) : (
              <div style={styles.chips}>
                {c.hours.map((h) => (
                  <span key={h.id} style={styles.chip}>
                    {h.day} {h.startTime}–{h.endTime} · {h.sessionMinutes} min
                    {data.canEdit && (
                      <button
                        type="button"
                        onClick={() => remove(c, h)}
                        style={styles.chipRemove}
                        aria-label={`Remove ${c.name}'s ${h.day} ${h.startTime} hours`}
                      >
                        &times;
                      </button>
                    )}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <h3 style={styles.subTitle}>Booked sessions ({data.sessions.length})</h3>
      {data.sessions.length === 0 ? (
        <div style={styles.empty}>No private sessions booked yet.</div>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {["When", "Coach", "Member", "Note", ""].map((h) => (
                  <th key={h} style={styles.th}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id}>
                  <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                    {formatDay(s.date)} · {s.startTime}–{s.endTime}
                  </td>
                  <td style={styles.td}>{s.coachName}</td>
                  <td style={styles.td}>
                    {s.memberName} <span style={styles.muted}>· ID {s.memberId}</span>
                  </td>
                  <td style={styles.td}>{s.note || "—"}</td>
                  <td style={{ ...styles.td, textAlign: "right" }}>
                    {data.canEdit && s.state === "upcoming" && (
                      <button type="button" onClick={() => setCancelling(s)} style={styles.rowButton}>
                        Cancel
                      </button>
                    )}
                    {s.state === "in_progress" && <span style={styles.liveTag}>In progress</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {cancelling && (
        <CancelSessionDialog
          session={cancelling}
          onClose={() => setCancelling(null)}
          onCancelled={(s) => {
            setCancelling(null);
            changed(`${s.memberName}'s session with ${s.coachName} on ${formatDay(s.date)} at ${s.startTime} was cancelled.`);
          }}
        />
      )}
    </div>
  );
}

export function CancelSessionDialog({ session, onClose, onCancelled }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onCancelled(await cancelPtSessionAsStaff(session.id, reason));
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={submit} role="dialog" aria-label="Cancel session">
        <h2 style={styles.modalTitle}>Cancel this private session?</h2>
        <p style={styles.modalText}>
          {session.memberName} with {session.coachName}, {formatDay(session.date)} {session.startTime}–{session.endTime}. The
          member sees it as cancelled by the gym, with your reason.
        </p>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason, e.g. Coach is ill"
          maxLength={100}
          style={{ ...styles.input, width: "100%" }}
          autoFocus
        />
        {error && <div style={{ ...styles.errorBox, marginTop: 10 }}>{error}</div>}
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.secondaryButton}>
            Keep session
          </button>
          <button type="submit" disabled={saving} style={styles.dangerButton}>
            {saving ? "Cancelling..." : "Cancel session"}
          </button>
        </div>
      </form>
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
  muted: { fontSize: 12, color: "#888" },
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
  coachGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10, marginBottom: 18 },
  coachCard: { padding: 12, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  coachName: { fontSize: 15, fontWeight: 700, marginBottom: 6, display: "flex", alignItems: "center", gap: 6 },
  anyTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#eef2fa", color: "#124096" },
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
  subTitle: { fontSize: 16, fontWeight: 700, margin: "0 0 10px" },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 620, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "middle" },
  rowButton: {
    padding: "5px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #de0b12",
    borderRadius: 6,
    background: "#fff",
    color: "#de0b12",
    cursor: "pointer",
  },
  liveTag: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
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
  secondaryButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  dangerButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
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
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
    boxSizing: "border-box",
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: "0 0 8px" },
  modalText: { fontSize: 14, color: "#555", lineHeight: 1.5, margin: "0 0 12px" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 },
};

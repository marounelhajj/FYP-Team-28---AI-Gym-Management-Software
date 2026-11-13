import { useEffect, useState } from "react";
import { deleteSessionLog, fetchSessionLog, saveSessionLog } from "../../api/coaching.js";
import { fetchPtHealthBriefing } from "../../api/health.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { MemberHealth } from "../health/HealthViews.jsx";
import { LogTimeline, formatDay } from "./ProgressViews.jsx";

// User story: "As a coach, I want to log client workout sessions and progress
// notes, so that I can track each client's development over time."
//
// Opened from a private session on the coach's My Schedule: the exercises
// done (sets x reps @ kg, or minutes / km, with how hard each felt - RPE
// 1-10) and a SOAP note. Last session's plan and the client's health notes
// are shown on top, so the coach starts where they left off. The server
// decides when a log can be written (from the start of the session until a
// week after it) and keeps the assessment for coaches only.

const EMPTY_ROW = { exercise: "", kind: "strength", sets: "3", reps: "10", weightKg: "", durationMinutes: "", distanceKm: "", rpe: "", note: "" };

const NOTES = [
  ["subjective", "Subjective - how they felt", "Sleep, energy, soreness, pain, what they told you."],
  ["objective", "Objective - what was done or measured", "Form, range of motion, test results, anything you observed."],
  ["assessment", "Assessment - your judgement (coaches only)", "Is it working? Ready to progress? Anything to watch?"],
  ["plan", "Plan - next session", "Shown to you (and the client) when the next session is logged."],
];

function toRow(e) {
  const str = (v) => (v === null || v === undefined ? "" : String(v));
  return {
    exercise: e.exercise, kind: e.kind, sets: str(e.sets), reps: str(e.reps), weightKg: str(e.weightKg),
    durationMinutes: str(e.durationMinutes), distanceKm: str(e.distanceKm), rpe: str(e.rpe), note: e.note || "",
  };
}

function toBody(row) {
  const num = (v) => (v === "" ? null : v);
  const base = { exercise: row.exercise, kind: row.kind, rpe: num(row.rpe), note: row.note };
  return row.kind === "cardio"
    ? { ...base, durationMinutes: num(row.durationMinutes), distanceKm: num(row.distanceKm) }
    : { ...base, sets: num(row.sets), reps: num(row.reps), weightKg: num(row.weightKg) };
}

export default function SessionLogForm({ sessionId, onClose, onSaved }) {
  const [data, setData] = useState(null);
  const [health, setHealth] = useState(null);
  const [rows, setRows] = useState([]);
  const [notes, setNotes] = useState({ subjective: "", objective: "", assessment: "", plan: "" });
  const [bodyWeightKg, setBodyWeightKg] = useState("");
  const [sessionRpe, setSessionRpe] = useState("");
  const [errors, setErrors] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  function fill(body) {
    setData(body);
    const log = body.log;
    setRows(log ? log.exercises.map(toRow) : []);
    setNotes(log ? { subjective: log.subjective, objective: log.objective, assessment: log.assessment, plan: log.plan } : { subjective: "", objective: "", assessment: "", plan: "" });
    setBodyWeightKg(log?.bodyWeightKg ?? "");
    setSessionRpe(log?.sessionRpe ? String(log.sessionRpe) : "");
  }

  useEffect(() => {
    fetchSessionLog(sessionId).then(fill).catch((e) => setError(e.message));
    fetchPtHealthBriefing(sessionId)
      .then((b) => setHealth(b.member))
      .catch(() => setHealth(null));
  }, [sessionId]);

  const kindOf = (name) => data?.exerciseChoices.find((c) => c.name.toLowerCase() === name.trim().toLowerCase())?.kind;

  function setRow(i, field, value) {
    setRows((current) =>
      current.map((row, j) => {
        if (j !== i) return row;
        const next = { ...row, [field]: value };
        if (field === "exercise" && kindOf(value)) next.kind = kindOf(value);
        return next;
      }),
    );
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErrors(null);
    setError(null);
    try {
      const body = await saveSessionLog(sessionId, {
        exercises: rows.filter((r) => r.exercise.trim()).map(toBody),
        ...notes,
        bodyWeightKg: bodyWeightKg === "" ? null : bodyWeightKg,
        sessionRpe: sessionRpe === "" ? null : Number(sessionRpe),
      });
      fill(body);
      onSaved?.("Session logged.");
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      fill(await deleteSessionLog(sessionId));
      setConfirmDelete(false);
      onSaved?.("Log deleted.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const s = data?.session;
  // The server answers with messages for the whole list (["Up to 30..."]) or
  // per row, keyed by the row's position ({"1": {"reps": [...]}}).
  const listErrors = errors?.exercises;
  const wholeList = Array.isArray(listErrors) && typeof listErrors[0] === "string" ? listErrors : [];
  const rowErrors = listErrors && !wholeList.length ? listErrors : {};
  const generalErrors = [...(errors?.non_field_errors || []), ...wholeList];

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Session log">
        <div style={styles.header}>
          <div>
            <h2 style={styles.title}>Session log{data ? ` · ${data.member.name}` : ""}</h2>
            {s && <p style={styles.subtitle}>{formatDay(s.date, true)} · {s.startTime}–{s.endTime} · {s.branch}</p>}
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {error && <div style={styles.errorBox}>{error}</div>}
        {!data && !error && <p style={styles.muted}>Loading...</p>}

        {data && (
          <>
            {data.previousPlan && (
              <div style={styles.planBox}>
                <strong>Last plan</strong> ({formatDay(data.previousPlan.date, true)}, {data.previousPlan.coachName}): {data.previousPlan.plan}
              </div>
            )}
            {health && (health.status !== "clear" || health.recentlyRecovered.length > 0) && (
              <details style={styles.healthBox} open={health.status === "restrictions"}>
                <summary style={styles.healthSummary}>
                  Health notes{health.status === "restrictions" ? ` (${health.activeCount})` : ""}
                </summary>
                <MemberHealth member={health} />
              </details>
            )}

            {!data.canEdit ? (
              <>
                <div style={styles.lockBox}>{data.cannotEditReason}</div>
                {data.log ? <LogTimeline logs={[data.log]} /> : <p style={styles.muted}>This session wasn&apos;t logged.</p>}
              </>
            ) : (
              <form onSubmit={save} style={styles.form}>
                <div style={styles.sectionHead}>
                  <h3 style={styles.section}>Exercises</h3>
                  <div style={styles.sectionActions}>
                    {rows.length === 0 && data.lastExercises.length > 0 && (
                      <button type="button" onClick={() => setRows(data.lastExercises.map(toRow))} style={styles.secondaryButton}>
                        Repeat last session
                      </button>
                    )}
                    <button type="button" onClick={() => setRows([...rows, { ...EMPTY_ROW }])} style={styles.secondaryButton}>
                      + Add exercise
                    </button>
                  </div>
                </div>
                <datalist id="exercise-choices">
                  {data.exerciseChoices.map((c) => (
                    <option key={c.name} value={c.name} />
                  ))}
                </datalist>
                {rows.length === 0 && <p style={styles.muted}>No exercises yet - add them, or just write notes below.</p>}
                {rows.map((row, i) => {
                  const err = rowErrors[i] || {};
                  const firstError = Object.values(err)[0]?.[0];
                  return (
                    <div key={i} style={styles.row}>
                      <div style={styles.rowTop}>
                        <input
                          value={row.exercise}
                          onChange={(e) => setRow(i, "exercise", e.target.value)}
                          list="exercise-choices"
                          placeholder="Exercise"
                          aria-label={`Exercise ${i + 1}`}
                          style={{ ...styles.input, flex: 2, minWidth: 140 }}
                        />
                        {!kindOf(row.exercise) && row.exercise.trim() && (
                          <select value={row.kind} onChange={(e) => setRow(i, "kind", e.target.value)} style={styles.input} aria-label={`Type of exercise ${i + 1}`}>
                            <option value="strength">Strength</option>
                            <option value="cardio">Cardio</option>
                          </select>
                        )}
                        <button type="button" onClick={() => setRows(rows.filter((_, j) => j !== i))} style={styles.removeButton} aria-label={`Remove exercise ${i + 1}`}>
                          &times;
                        </button>
                      </div>
                      <div style={styles.rowFields}>
                        {row.kind === "cardio" ? (
                          <>
                            <Num label="Minutes" value={row.durationMinutes} onChange={(v) => setRow(i, "durationMinutes", v)} />
                            <Num label="km" value={row.distanceKm} step="0.01" onChange={(v) => setRow(i, "distanceKm", v)} />
                          </>
                        ) : (
                          <>
                            <Num label="Sets" value={row.sets} onChange={(v) => setRow(i, "sets", v)} />
                            <Num label="Reps" value={row.reps} onChange={(v) => setRow(i, "reps", v)} />
                            <Num label="kg" value={row.weightKg} step="0.5" onChange={(v) => setRow(i, "weightKg", v)} />
                          </>
                        )}
                        <Num label="RPE 1-10" value={row.rpe} onChange={(v) => setRow(i, "rpe", v)} />
                        <input
                          value={row.note}
                          onChange={(e) => setRow(i, "note", e.target.value)}
                          maxLength={200}
                          placeholder="Note (optional)"
                          aria-label={`Note for exercise ${i + 1}`}
                          style={{ ...styles.input, flex: 2, minWidth: 120 }}
                        />
                      </div>
                      {firstError && <span style={styles.fieldError}>{firstError}</span>}
                    </div>
                  );
                })}

                <h3 style={styles.section}>Progress note</h3>
                {NOTES.map(([key, label, hint]) => (
                  <label key={key} style={styles.field}>
                    <span style={styles.label}>{label}</span>
                    <textarea
                      value={notes[key]}
                      onChange={(e) => setNotes({ ...notes, [key]: e.target.value })}
                      maxLength={1000}
                      rows={2}
                      placeholder={hint}
                      style={{ ...styles.textarea, ...(key === "assessment" ? styles.privateField : null) }}
                    />
                    {errors?.[key] && <span style={styles.fieldError}>{errors[key][0]}</span>}
                  </label>
                ))}

                <div style={styles.inlineFields}>
                  <label style={styles.field}>
                    <span style={styles.label}>Body weight measured (kg, optional)</span>
                    <input type="number" step="0.1" value={bodyWeightKg} onChange={(e) => setBodyWeightKg(e.target.value)} style={styles.input} />
                    {errors?.bodyWeightKg && <span style={styles.fieldError}>{errors.bodyWeightKg[0]}</span>}
                  </label>
                  <label style={styles.field}>
                    <span style={styles.label}>Whole-session effort (RPE 1-10)</span>
                    <select value={sessionRpe} onChange={(e) => setSessionRpe(e.target.value)} style={styles.input}>
                      <option value="">—</option>
                      {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </label>
                </div>

                {generalErrors.length > 0 && <div style={styles.errorBox}>{generalErrors[0]}</div>}
                <p style={styles.hint}>
                  Saving marks the session as attended. You can change this log until {data.editDays} days after the session; then it locks.
                </p>
                <div style={styles.actions}>
                  {data.log &&
                    (confirmDelete ? (
                      <>
                        <span style={styles.confirmText}>Delete this log?</span>
                        <button type="button" onClick={() => setConfirmDelete(false)} style={styles.secondaryButton} disabled={busy}>Keep</button>
                        <button type="button" onClick={remove} style={styles.dangerButton} disabled={busy}>Delete</button>
                      </>
                    ) : (
                      <button type="button" onClick={() => setConfirmDelete(true)} style={styles.linkDanger} disabled={busy}>Delete log</button>
                    ))}
                  <span style={{ flex: 1 }} />
                  <button type="button" onClick={onClose} style={styles.secondaryButton} disabled={busy}>Done</button>
                  <button type="submit" style={styles.primaryButton} disabled={busy}>
                    {busy ? "Saving..." : data.log ? "Save changes" : "Save log"}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Num({ label, value, onChange, step = "1" }) {
  return (
    <label style={styles.numField}>
      <span style={styles.numLabel}>{label}</span>
      <input type="number" min="0" step={step} value={value} onChange={(e) => onChange(e.target.value)} style={styles.numInput} />
    </label>
  );
}

const styles = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 50 },
  modal: {
    background: "#fff",
    borderRadius: 14,
    padding: 22,
    width: "100%",
    maxWidth: 760,
    maxHeight: "92vh",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  lockBox: { background: "#f1f1f4", color: "#444", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  planBox: { background: "#eef2fa", color: "#1d2f5c", padding: "10px 14px", borderRadius: 8, fontSize: 13, lineHeight: 1.45 },
  healthBox: { border: "1px solid #f3d9a4", background: "#fffaf0", borderRadius: 8, padding: "8px 12px" },
  healthSummary: { fontSize: 13, fontWeight: 700, cursor: "pointer", marginBottom: 6 },
  form: { display: "flex", flexDirection: "column", gap: 8 },
  sectionHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" },
  sectionActions: { display: "flex", gap: 6 },
  section: { fontSize: 15, fontWeight: 800, margin: "6px 0 0" },
  row: { display: "flex", flexDirection: "column", gap: 6, padding: 10, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fafafb" },
  rowTop: { display: "flex", gap: 6, alignItems: "center" },
  rowFields: { display: "flex", gap: 6, flexWrap: "wrap", alignItems: "flex-end" },
  numField: { display: "flex", flexDirection: "column", gap: 2, width: 72 },
  numLabel: { fontSize: 11, color: "#666", fontWeight: 600 },
  numInput: { padding: "6px 8px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 6, width: "100%", boxSizing: "border-box" },
  input: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", boxSizing: "border-box" },
  removeButton: { border: "none", background: "none", fontSize: 20, color: "#999", cursor: "pointer", padding: "0 4px" },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 0 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  textarea: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit", resize: "vertical", boxSizing: "border-box", width: "100%" },
  privateField: { background: "#faf6fe", borderColor: "#d8c5ee" },
  inlineFields: { display: "flex", gap: 10, flexWrap: "wrap" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  hint: { fontSize: 12, color: "#777", margin: 0 },
  actions: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  confirmText: { fontSize: 13, color: "#444" },
  primaryButton: { padding: "8px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  secondaryButton: { padding: "7px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  dangerButton: { padding: "7px 12px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.red, cursor: "pointer" },
  linkDanger: { border: "none", background: "none", color: "#b3261e", fontSize: 13, fontWeight: 600, cursor: "pointer", padding: 0 },
};

import { useCallback, useEffect, useState } from "react";
import {
  addMetric, addWorkout, deleteMetric, deleteWorkout, fetchMyMetrics, fetchMyWorkouts, updateMetric, updateWorkout,
} from "../../api/progress.js";
import { MetricList, WeightChart, WorkoutList } from "./TrainingLogViews.jsx";

// User story (SCRUM-60): "As a member, I want to log my own workouts and body
// metrics between sessions, so that my coach and the AI system have
// up-to-date data to base recommendations on."
//
// The member's own log on their dashboard. Validation (ranges, units, no
// future dates) lives on the server; field errors come back next to the field.

const OTHER = "__other__";

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY_WORKOUT = { exercise: "", custom: "", kind: "strength", sets: "", reps: "", weightKg: "", durationMinutes: "", distanceKm: "", note: "" };
const EMPTY_METRIC = { weightKg: "", bodyFatPercent: "", waistCm: "", chestCm: "", hipsCm: "", note: "" };
const orNull = (v) => (v === "" || v === undefined ? null : v);

export default function MyTrainingLog() {
  const [tab, setTab] = useState("workouts");
  const [workouts, setWorkouts] = useState([]);
  const [exercises, setExercises] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [editing, setEditing] = useState(null); // { type, entry|null }
  const [form, setForm] = useState({});
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    fetchMyWorkouts().then((b) => (setWorkouts(b.results), setExercises(b.exercises))).catch((e) => setError(e.message));
    fetchMyMetrics().then((b) => setMetrics(b.results)).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(t);
  }, [notice]);

  const kindOf = (name) => exercises.find((e) => e.name === name)?.kind;

  function open(type, entry = null) {
    setErrors({});
    setError(null);
    setEditing({ type, entry });
    if (type === "workout") {
      const listed = entry && kindOf(entry.exercise);
      setForm(entry
        ? { ...EMPTY_WORKOUT, ...Object.fromEntries(Object.entries(entry).map(([k, v]) => [k, v ?? ""])),
            exercise: listed ? entry.exercise : OTHER, custom: listed ? "" : entry.exercise }
        : { ...EMPTY_WORKOUT, date: todayIso() });
    } else {
      setForm(entry ? { ...EMPTY_METRIC, ...Object.fromEntries(Object.entries(entry).map(([k, v]) => [k, v ?? ""])) } : { ...EMPTY_METRIC, date: todayIso() });
    }
  }

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    setError(null);
    try {
      const { type, entry } = editing;
      if (type === "workout") {
        const name = form.exercise === OTHER ? form.custom : form.exercise;
        const kind = kindOf(name) || form.kind;
        const body = {
          date: form.date, exercise: name, kind, note: form.note,
          sets: kind === "strength" ? orNull(form.sets) : null, reps: kind === "strength" ? orNull(form.reps) : null,
          weightKg: kind === "strength" ? orNull(form.weightKg) : null,
          durationMinutes: kind === "cardio" ? orNull(form.durationMinutes) : null,
          distanceKm: kind === "cardio" ? orNull(form.distanceKm) : null,
        };
        await (entry ? updateWorkout(entry.id, body) : addWorkout(body));
        setNotice(entry ? "Workout updated." : "Workout logged.");
      } else {
        const body = Object.fromEntries(Object.entries(form).filter(([k]) => k !== "id").map(([k, v]) => [k, k === "note" ? v : orNull(v)]));
        await (entry ? updateMetric(entry.id, body) : addMetric(body));
        setNotice(entry ? "Measurement updated." : "Measurement logged.");
      }
      setEditing(null);
      load();
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(type, entry) {
    setError(null);
    try {
      await (type === "workout" ? deleteWorkout(entry.id) : deleteMetric(entry.id));
      setNotice(type === "workout" ? "Workout deleted." : "Measurement deleted.");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const actions = (type) => (entry) => (
    <>
      <button type="button" onClick={() => open(type, entry)} style={styles.smallButton} aria-label={`Edit ${type} from ${entry.date}`}>
        Edit
      </button>
      <button type="button" onClick={() => remove(type, entry)} style={styles.smallButton} aria-label={`Delete ${type} from ${entry.date}`}>
        Delete
      </button>
    </>
  );

  const exerciseName = form.exercise === OTHER ? form.custom : form.exercise;
  const kind = kindOf(exerciseName) || form.kind;

  return (
    <div style={styles.card}>
      <div role="tablist" aria-label="Training log" style={styles.tabs}>
        {[["workouts", `Workouts ${workouts.length}`], ["metrics", `Body metrics ${metrics.length}`]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => { setTab(key); setEditing(null); }}
            style={{ ...styles.tab, ...(tab === key ? styles.tabSelected : null) }}>
            {label}
          </button>
        ))}
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      {!editing && (
        <button type="button" onClick={() => open(tab === "workouts" ? "workout" : "metric")} style={styles.primaryButton}>
          {tab === "workouts" ? "Log a workout" : "Log body metrics"}
        </button>
      )}

      {editing && (
        <form onSubmit={save} style={styles.form} aria-label={editing.type === "workout" ? "Workout" : "Body metrics"}>
          <Field label="Date" error={errors.date}>
            <input id="tl-date" type="date" max={todayIso()} value={form.date || ""} onChange={(e) => update("date", e.target.value)} style={styles.input} required />
          </Field>
          {editing.type === "workout" ? (
            <>
              <Field label="Exercise" error={errors.exercise} htmlFor="tl-exercise">
                <select id="tl-exercise" value={form.exercise} onChange={(e) => update("exercise", e.target.value)} style={styles.select} required>
                  <option value="">Choose an exercise</option>
                  {exercises.map((x) => (
                    <option key={x.name} value={x.name}>{x.name}</option>
                  ))}
                  <option value={OTHER}>Other (type it)</option>
                </select>
              </Field>
              {form.exercise === OTHER && (
                <>
                  <Field label="Exercise name" htmlFor="tl-custom">
                    <input id="tl-custom" value={form.custom} onChange={(e) => update("custom", e.target.value)} style={styles.input} maxLength={80} required />
                  </Field>
                  <Field label="Type" htmlFor="tl-kind">
                    <select id="tl-kind" value={form.kind} onChange={(e) => update("kind", e.target.value)} style={styles.select}>
                      <option value="strength">Strength</option>
                      <option value="cardio">Cardio</option>
                    </select>
                  </Field>
                </>
              )}
              {kind === "strength" ? (
                <div style={styles.row3}>
                  <Field label="Sets" error={errors.sets} htmlFor="tl-sets">
                    <input id="tl-sets" type="number" min="1" max="20" value={form.sets} onChange={(e) => update("sets", e.target.value)} style={styles.input} />
                  </Field>
                  <Field label="Reps" error={errors.reps} htmlFor="tl-reps">
                    <input id="tl-reps" type="number" min="1" max="100" value={form.reps} onChange={(e) => update("reps", e.target.value)} style={styles.input} />
                  </Field>
                  <Field label="Weight (kg)" error={errors.weightKg} htmlFor="tl-weight">
                    <input id="tl-weight" type="number" step="0.5" min="0" max="500" value={form.weightKg} onChange={(e) => update("weightKg", e.target.value)} style={styles.input} />
                  </Field>
                </div>
              ) : (
                <div style={styles.row3}>
                  <Field label="Duration (min)" error={errors.durationMinutes} htmlFor="tl-duration">
                    <input id="tl-duration" type="number" min="1" max="600" value={form.durationMinutes} onChange={(e) => update("durationMinutes", e.target.value)} style={styles.input} />
                  </Field>
                  <Field label="Distance (km)" error={errors.distanceKm} htmlFor="tl-distance">
                    <input id="tl-distance" type="number" step="0.1" min="0.1" max="200" value={form.distanceKm} onChange={(e) => update("distanceKm", e.target.value)} style={styles.input} />
                  </Field>
                </div>
              )}
            </>
          ) : (
            <>
              <div style={styles.row3}>
                <Field label="Body weight (kg)" error={errors.weightKg} htmlFor="tl-bw">
                  <input id="tl-bw" type="number" step="0.1" min="20" max="350" value={form.weightKg} onChange={(e) => update("weightKg", e.target.value)} style={styles.input} required />
                </Field>
                <Field label="Body fat (%)" error={errors.bodyFatPercent} htmlFor="tl-bf">
                  <input id="tl-bf" type="number" step="0.1" min="2" max="70" value={form.bodyFatPercent} onChange={(e) => update("bodyFatPercent", e.target.value)} style={styles.input} />
                </Field>
              </div>
              <div style={styles.row3}>
                {[["waistCm", "Waist (cm)"], ["chestCm", "Chest (cm)"], ["hipsCm", "Hips (cm)"]].map(([key, label]) => (
                  <Field key={key} label={label} error={errors[key]} htmlFor={`tl-${key}`}>
                    <input id={`tl-${key}`} type="number" step="0.5" min="30" max="250" value={form[key]} onChange={(e) => update(key, e.target.value)} style={styles.input} />
                  </Field>
                ))}
              </div>
            </>
          )}
          <Field label="Note (optional)" error={errors.note} htmlFor="tl-note">
            <input id="tl-note" value={form.note} maxLength={300} onChange={(e) => update("note", e.target.value)} style={styles.input} />
          </Field>
          <div style={styles.actions}>
            <button type="button" onClick={() => setEditing(null)} style={styles.secondaryButton}>Cancel</button>
            <button type="submit" disabled={saving} style={styles.primaryButton}>{saving ? "Saving..." : "Save"}</button>
          </div>
        </form>
      )}

      <div style={{ marginTop: 12 }}>
        {tab === "workouts" ? (
          <WorkoutList workouts={workouts} renderActions={actions("workout")} />
        ) : (
          <>
            <WeightChart metrics={metrics} />
            <MetricList metrics={metrics} renderActions={actions("metric")} />
          </>
        )}
      </div>
      <p style={styles.note}>Your coach can see this log (read-only) to plan your sessions.</p>
    </div>
  );
}

function Field({ label, error, htmlFor = "tl-date", children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label htmlFor={htmlFor} style={styles.label}>{label}</label>
      {children}
      {message && <span style={styles.fieldError}>{message}</span>}
    </div>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff" },
  tabs: { display: "flex", gap: 4, padding: 4, borderRadius: 12, background: "#ececf0", marginBottom: 12 },
  tab: { flex: 1, height: 36, border: "none", borderRadius: 9, background: "transparent", fontSize: 13, fontWeight: 800, color: "#555", cursor: "pointer" },
  tabSelected: { background: "#fff", color: "#124096", boxShadow: "0 2px 6px rgba(18,64,150,0.2)" },
  form: { display: "flex", flexDirection: "column", gap: 10, padding: 12, borderRadius: 12, background: "#f6f6f8", marginTop: 4 },
  row3: { display: "flex", gap: 8, flexWrap: "wrap" },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "1 1 120px", minWidth: 0 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  input: { height: 38, padding: "0 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", minWidth: 0 },
  select: { height: 38, padding: "0 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontWeight: 600 },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", gap: 8, justifyContent: "flex-end" },
  primaryButton: { height: 38, padding: "0 16px", border: "none", borderRadius: 8, background: "#124096", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  secondaryButton: { height: 38, padding: "0 14px", border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  smallButton: { padding: "5px 10px", fontSize: 12, border: "1px solid #d0d0d5", borderRadius: 6, background: "#f5f5f7", cursor: "pointer" },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  note: { fontSize: 12, color: "#888", margin: "10px 0 0" },
};

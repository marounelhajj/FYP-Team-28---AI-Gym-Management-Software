import { useEffect, useState } from "react";
import { saveCapacity } from "../../api/headcount.js";

const BLUE = "#124096";
const RED = "#b3261e";
const AMBER = "#9a6100";

// User story (SCRUM-128): "As a branch manager, I want to be alerted when
// headcount approaches the branch capacity limit, so that I can act before
// the floor becomes unsafe or unpleasant."
//
// Under the live count: how full the branch is against its capacity, and the
// settings (maximum people, alert at %). The banner for an active alert is
// AlertBanner below; the server decides when it raises and clears.
export default function CapacityPanel({ branch, count, capacity, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ maxCapacity: "", alertPercent: 90 });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);

  useEffect(() => {
    setEditing(false);
    setSaved(null);
  }, [branch]);

  const shown = saved || capacity;

  function open() {
    setForm({ maxCapacity: shown?.maxCapacity ?? "", alertPercent: shown?.alertPercent ?? 90 });
    setErrors({});
    setError(null);
    setEditing(true);
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setErrors({});
    setError(null);
    try {
      const body = await saveCapacity({ branch, maxCapacity: Number(form.maxCapacity), alertPercent: Number(form.alertPercent) });
      setSaved(body.capacity);
      setEditing(false);
      onSaved?.(body);
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const share = shown && typeof count === "number" ? Math.min(100, Math.round((count / shown.maxCapacity) * 100)) : null;
  const level = !shown || count === undefined ? null : count >= shown.threshold ? "alert" : count >= shown.clearBelow ? "near" : "ok";
  const fill = level === "alert" ? RED : level === "near" ? AMBER : BLUE;

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <div>
          <div style={styles.label}>Branch capacity</div>
          {shown ? (
            <div style={styles.value}>
              <b style={{ color: fill }}>{count ?? "–"}</b> of {shown.maxCapacity} people
              {share !== null && <span style={styles.share}> · {share}% full</span>}
            </div>
          ) : (
            <div style={styles.value}>Not set yet. Set it to get alerts when the floor fills up.</div>
          )}
        </div>
        {!editing && (
          <button type="button" onClick={open} className="hc-press hc-focus" style={styles.editButton}>
            {shown ? "Change capacity" : "Set capacity"}
          </button>
        )}
      </div>

      {shown && (
        <>
          <div style={styles.track} aria-hidden="true">
            <div style={{ ...styles.fill, width: `${share ?? 0}%`, background: fill }} />
            <div style={{ ...styles.marker, left: `${shown.alertPercent}%` }} />
          </div>
          <div style={styles.note}>
            Alert at {shown.threshold} people ({shown.alertPercent}%). It clears below {shown.clearBelow}, so it doesn't
            flicker at the line. Staff at this branch get a notification when it fires.
          </div>
        </>
      )}

      {editing && (
        <form onSubmit={submit} style={styles.form}>
          <label style={styles.field}>
            <span style={styles.fieldLabel}>Maximum people on the floor</span>
            <input
              type="number"
              min="1"
              max="5000"
              value={form.maxCapacity}
              onChange={(e) => setForm((f) => ({ ...f, maxCapacity: e.target.value }))}
              style={styles.input}
              required
            />
            {errors.maxCapacity && <span style={styles.error}>{errors.maxCapacity[0]}</span>}
          </label>
          <label style={styles.field}>
            <span style={styles.fieldLabel}>Alert when it reaches (%)</span>
            <input
              type="number"
              min="10"
              max="100"
              value={form.alertPercent}
              onChange={(e) => setForm((f) => ({ ...f, alertPercent: e.target.value }))}
              style={styles.input}
              required
            />
            {errors.alertPercent && <span style={styles.error}>{errors.alertPercent[0]}</span>}
          </label>
          {error && <div style={{ ...styles.error, flexBasis: "100%" }}>{error}</div>}
          <div style={styles.actions}>
            <button type="button" onClick={() => setEditing(false)} className="hc-press hc-focus" style={styles.secondaryButton}>
              Cancel
            </button>
            <button type="submit" disabled={saving} className="hc-press hc-focus" style={styles.primaryButton}>
              {saving ? "Saving..." : "Save capacity"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export function AlertBanner({ alert, capacity, count }) {
  if (!alert?.active || !capacity) return null;
  return (
    <div role="alert" className="hc-alert" style={styles.banner}>
      <span style={styles.bannerIcon} aria-hidden="true">!</span>
      <div>
        <div style={styles.bannerTitle}>Near capacity: {count ?? alert.count} of {capacity.maxCapacity} people inside</div>
        <div style={styles.bannerText}>
          Over the {capacity.alertPercent}% alert level since {alert.since}. Staff on site were notified. It clears once
          headcount drops below {capacity.clearBelow}.
        </div>
      </div>
    </div>
  );
}

const styles = {
  panel: { marginTop: 18, padding: 16, borderRadius: 16, background: "#f6f7fa", border: "1px solid #e6e8ee" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" },
  label: { fontSize: 12, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "#5b6070" },
  value: { fontSize: 16, fontWeight: 600, marginTop: 4 },
  share: { color: "#5b6070", fontWeight: 600 },
  track: { position: "relative", height: 12, borderRadius: 6, background: "#e1e4ec", marginTop: 12, overflow: "visible" },
  fill: { height: "100%", borderRadius: 6, transition: "width 400ms ease" },
  marker: { position: "absolute", top: -4, width: 3, height: 20, borderRadius: 2, background: "#1a1a1a", transform: "translateX(-1px)" },
  note: { fontSize: 13, color: "#5b6070", marginTop: 8, lineHeight: 1.5 },
  form: { display: "flex", flexWrap: "wrap", gap: 12, marginTop: 14 },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "1 1 200px" },
  fieldLabel: { fontSize: 13, fontWeight: 700 },
  input: { height: 44, padding: "0 12px", fontSize: 15, fontWeight: 600, border: "1px solid #cfd3dc", borderRadius: 12, background: "#fff" },
  error: { fontSize: 12, color: RED },
  actions: { display: "flex", gap: 10, flexBasis: "100%", justifyContent: "flex-end" },
  editButton: {
    height: 40, padding: "0 16px", border: "1px solid #cfd3dc", borderRadius: 12, background: "#fff",
    fontSize: 14, fontWeight: 800, color: BLUE, cursor: "pointer",
  },
  primaryButton: {
    height: 44, padding: "0 20px", border: "none", borderRadius: 12, background: BLUE, color: "#fff",
    fontSize: 14, fontWeight: 800, cursor: "pointer",
  },
  secondaryButton: {
    height: 44, padding: "0 18px", border: "1px solid #cfd3dc", borderRadius: 12, background: "#fff",
    fontSize: 14, fontWeight: 800, color: "#444", cursor: "pointer",
  },
  banner: {
    display: "flex", gap: 14, alignItems: "flex-start", padding: "14px 18px", borderRadius: 16,
    background: "#fdeceb", border: `2px solid ${RED}`, color: "#5c1410", marginBottom: 16,
  },
  bannerIcon: {
    flexShrink: 0, width: 30, height: 30, borderRadius: "50%", background: RED, color: "#fff",
    display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 900, fontSize: 18,
  },
  bannerTitle: { fontSize: 17, fontWeight: 800 },
  bannerText: { fontSize: 14, marginTop: 2, lineHeight: 1.45 },
};

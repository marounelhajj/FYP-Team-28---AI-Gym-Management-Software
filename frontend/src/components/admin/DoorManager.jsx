import { useEffect, useState } from "react";
import { createDoor, fetchDoors, rotateDoorKey, updateDoor } from "../../api/doors.js";
import { fetchMemberFilterOptions } from "../../api/members.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import SegmentedControl from "../SegmentedControl.jsx";

const KIND_OPTIONS = [
  { value: "Entrance", label: "Entrance" },
  { value: "Exit", label: "Exit" },
];
const EMPTY_FORM = { name: "", branch: "", kind: "Entrance" };

// Door readers: the tablets/turnstiles that let members in by scanning their
// QR code. They decide entry from each member's live membership, so nothing
// here is about individual members - only which doors exist and their keys.
export default function DoorManager() {
  const [doors, setDoors] = useState(null);
  const [branches, setBranches] = useState([]);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [issuedKey, setIssuedKey] = useState(null); // { door, key } - shown once
  const [busyId, setBusyId] = useState(null);

  function load() {
    fetchDoors()
      .then((data) => setDoors(data.results))
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    load();
    fetchMemberFilterOptions()
      .then((meta) => setBranches(meta.branches))
      .catch(() => {});
  }, []);

  async function handleCreate(e) {
    e.preventDefault();
    setSaving(true);
    setFieldErrors({});
    try {
      setIssuedKey(await createDoor(form));
      setForm(EMPTY_FORM);
      setShowForm(false);
      load();
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleRotate(door) {
    if (!window.confirm(`Replace the key of "${door.name}"? The door stops working until the new key is entered on it.`)) {
      return;
    }
    setBusyId(door.id);
    try {
      setIssuedKey(await rotateDoorKey(door.id));
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggle(door) {
    setBusyId(door.id);
    try {
      await updateDoor(door.id, { isActive: !door.isActive });
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Door Readers</h2>
          <p style={styles.subtitle}>
            Doors let members in by scanning their QR code and open only while their membership is paid and active -
            payments, freezes, cancellations and card reissues take effect on the next scan, with nothing to update by hand.
          </p>
        </div>
        {!showForm && (
          <button onClick={() => setShowForm(true)} style={styles.addButton}>
            + Add door
          </button>
        )}
      </div>

      {error && <div style={styles.errorBox}>{error}</div>}

      {showForm && (
        <form onSubmit={handleCreate} style={styles.formCard}>
          <div style={styles.formGrid}>
            <label style={styles.field}>
              <span style={styles.label}>Name</span>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Main entrance"
                maxLength={80}
                style={styles.input}
                autoFocus
              />
              {fieldErrors.name && <span style={styles.fieldError}>{fieldErrors.name[0]}</span>}
            </label>
            <label style={styles.field}>
              <span style={styles.label}>Branch</span>
              <select value={form.branch} onChange={(e) => setForm({ ...form, branch: e.target.value })} style={styles.input}>
                <option value="">Select a branch...</option>
                {branches.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
              {fieldErrors.branch && <span style={styles.fieldError}>{fieldErrors.branch[0]}</span>}
            </label>
            <div style={styles.field}>
              <span style={styles.label}>Type</span>
              <SegmentedControl
                options={KIND_OPTIONS}
                value={form.kind}
                onChange={(kind) => setForm({ ...form, kind })}
                ariaLabel="Door type"
              />
            </div>
          </div>
          <p style={styles.hint}>
            Entrances check the membership. Exits always open, so no one is ever locked in - scanning out just records
            that the member left.
          </p>
          <div style={styles.formActions}>
            <button type="button" onClick={() => setShowForm(false)} style={styles.secondaryButton}>
              Cancel
            </button>
            <button type="submit" disabled={saving} style={styles.addButton}>
              {saving ? "Adding..." : "Add door"}
            </button>
          </div>
        </form>
      )}

      {doors && doors.length === 0 && !showForm && <p style={styles.empty}>No door readers yet.</p>}

      {doors && doors.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Door</th>
                <th style={styles.th}>Branch</th>
                <th style={styles.th}>Type</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Last scan</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {doors.map((door) => (
                <tr key={door.id}>
                  <td style={{ ...styles.td, fontWeight: 600 }}>{door.name}</td>
                  <td style={styles.td}>{door.branch}</td>
                  <td style={styles.td}>{door.kind}</td>
                  <td style={styles.td}>
                    <span style={door.isActive ? styles.activeBadge : styles.disabledBadge}>
                      {door.isActive ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td style={{ ...styles.td, color: "#666" }}>{door.lastSeenAt || "Never"}</td>
                  <td style={{ ...styles.td, textAlign: "right", whiteSpace: "nowrap" }}>
                    <button onClick={() => handleRotate(door)} disabled={busyId === door.id} style={styles.secondaryButton}>
                      Replace key
                    </button>{" "}
                    <button
                      onClick={() => handleToggle(door)}
                      disabled={busyId === door.id}
                      style={door.isActive ? styles.disableButton : styles.enableButton}
                    >
                      {door.isActive ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {issuedKey && <KeyDialog issued={issuedKey} onClose={() => setIssuedKey(null)} />}
    </div>
  );
}

function KeyDialog({ issued, onClose }) {
  const [copied, setCopied] = useState(false);
  const doorUrl = `${window.location.origin}/door`;

  function copy() {
    navigator.clipboard?.writeText(issued.key).then(() => setCopied(true)).catch(() => {});
  }

  return (
    <div style={styles.overlay}>
      <div style={styles.modal} role="dialog" aria-label="Door key">
        <h3 style={styles.modalTitle}>Key for "{issued.door.name}"</h3>
        <p style={styles.modalText}>
          On the door's tablet, open <strong>{doorUrl}</strong> and paste this key. It won't be shown again - if it's
          lost, replace it.
        </p>
        <div style={styles.keyBox}>
          <code style={styles.key}>{issued.key}</code>
          <button type="button" onClick={copy} style={styles.secondaryButton}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <div style={styles.formActions}>
          <button type="button" onClick={onClose} style={styles.addButton}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 },
  title: { fontSize: 20, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 0", maxWidth: 640, lineHeight: 1.45 },
  addButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  secondaryButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  disableButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    cursor: "pointer",
  },
  enableButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.green,
    cursor: "pointer",
  },
  formCard: { border: "1px solid #e4e4e8", borderRadius: 10, padding: 16, marginBottom: 16, background: "#fafafa" },
  formGrid: { display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 12 },
  field: { display: "flex", flexDirection: "column", gap: 6 },
  label: { fontSize: 13, fontWeight: 600, color: "#444" },
  input: {
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    boxSizing: "border-box",
  },
  fieldError: { fontSize: 12, color: "#b3261e" },
  hint: { fontSize: 12, color: "#777", margin: "12px 0 0" },
  formActions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 14 },
  empty: { fontSize: 14, color: "#888" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  tableWrap: { border: "1px solid #e4e4e8", borderRadius: 10, overflow: "hidden" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    background: "#fafafa",
    borderBottom: "1px solid #e4e4e8",
    fontWeight: 600,
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: 0.3,
    color: "#555",
  },
  td: { padding: "10px 14px", borderBottom: "1px solid #f0f0f2" },
  activeBadge: { fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: 6, ...BUTTON_COLORS.green },
  disabledBadge: { fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: 6, background: "#e4e4e8", color: "#555" },
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
    maxWidth: 520,
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: "0 0 8px" },
  modalText: { fontSize: 13, color: "#555", lineHeight: 1.5, margin: "0 0 14px" },
  keyBox: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 12px",
    border: "1px solid #e4e4e8",
    borderRadius: 8,
    background: "#f5f5f7",
  },
  key: { flex: 1, fontSize: 13, wordBreak: "break-all" },
};

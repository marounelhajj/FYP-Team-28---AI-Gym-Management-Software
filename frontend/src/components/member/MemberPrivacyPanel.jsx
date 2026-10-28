import { useState } from "react";
import { deleteMyData, downloadMyData } from "../../api/memberAuth.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// User story (SCRUM-62): "As a member, I want to request an export or
// deletion of my personal data, so that I have control over my own privacy."
//
// Export downloads a JSON file straight away. Deletion is two steps: a
// warning first, then the password and the word DELETE - the server checks
// both. Payments, the signed waiver and audit entries are kept for the gym's
// records, but anonymized (see backend/members/privacy.py).
export default function MemberPrivacyPanel({ onDeleted }) {
  const [exporting, setExporting] = useState(false);
  const [exportedAs, setExportedAs] = useState(null);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState("");
  const [word, setWord] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function handleExport() {
    setError(null);
    setExportedAs(null);
    setExporting(true);
    try {
      setExportedAs(await downloadMyData());
    } catch (err) {
      setError(err.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleDelete(e) {
    e.preventDefault();
    setError(null);
    setDeleting(true);
    try {
      await deleteMyData(password, word);
      onDeleted();
    } catch (err) {
      setError(err.message);
      setDeleting(false);
    }
  }

  function cancel() {
    setConfirming(false);
    setPassword("");
    setWord("");
    setError(null);
  }

  return (
    <div style={styles.card}>
      <p style={styles.text}>
        Download a copy of everything we hold about you, or ask us to delete your personal data.
      </p>
      {error && <div style={styles.errorBox}>{error}</div>}
      {exportedAs && <div style={styles.successBox}>Downloaded {exportedAs}.</div>}

      <div style={styles.actions}>
        <button onClick={handleExport} disabled={exporting} style={styles.smallButton}>
          {exporting ? "Preparing..." : "Download my data"}
        </button>
        {!confirming && (
          <button onClick={() => setConfirming(true)} style={styles.dangerButton}>
            Delete my data
          </button>
        )}
      </div>

      {confirming && (
        <form onSubmit={handleDelete} style={styles.confirmBox}>
          <p style={styles.warning}>
            This removes your contact details and login, and signs you out for good. Payment and waiver
            records the gym must keep stay on file, but without your name, email or phone. This can't be undone.
          </p>
          <label style={styles.label} htmlFor="privacy-password">
            Your password
          </label>
          <input
            id="privacy-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={styles.input}
            autoComplete="current-password"
          />
          <label style={styles.label} htmlFor="privacy-confirm">
            Type DELETE to confirm
          </label>
          <input
            id="privacy-confirm"
            type="text"
            value={word}
            onChange={(e) => setWord(e.target.value)}
            style={styles.input}
            autoComplete="off"
          />
          <div style={styles.actions}>
            <button type="button" onClick={cancel} disabled={deleting} style={styles.smallButton}>
              Never mind
            </button>
            <button type="submit" disabled={deleting || !password || word !== "DELETE"} style={styles.dangerButton}>
              {deleting ? "Deleting..." : "Permanently delete my data"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  text: { fontSize: 13, color: "#444", margin: "0 0 12px" },
  actions: { display: "flex", gap: 10, flexWrap: "wrap" },
  smallButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  dangerButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
  confirmBox: { marginTop: 16, paddingTop: 14, borderTop: "1px solid #f0f0f2" },
  warning: { fontSize: 13, color: "#444", margin: "0 0 12px", lineHeight: 1.5 },
  label: { display: "block", fontSize: 13, fontWeight: 600, margin: "10px 0 4px" },
  input: {
    width: "100%",
    boxSizing: "border-box",
    padding: "8px 10px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    marginBottom: 6,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 10,
  },
  successBox: {
    background: "#e6f4ea",
    color: "#1e7a34",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 10,
  },
};

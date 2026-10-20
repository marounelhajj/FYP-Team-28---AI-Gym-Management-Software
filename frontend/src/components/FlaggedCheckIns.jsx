import { useEffect, useState } from "react";
import { fetchFlags, resolveFlag } from "../api/checkins.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import SegmentedControl from "./SegmentedControl.jsx";

const STATUS_OPTIONS = [
  { value: "Open", label: "Open" },
  { value: "Confirmed", label: "Confirmed" },
  { value: "Dismissed", label: "Dismissed" },
  { value: "all", label: "All" },
];
const STATUS_BADGES = {
  Open: { background: "#fff4e0", color: "#8a5a00" },
  Confirmed: BUTTON_COLORS.red,
  Dismissed: { background: "#f0f0f3", color: "#555" },
};
const EMPTY_TEXT = {
  Open: "No open flags. Flag a suspicious attempt from Recent Check-Ins.",
  Confirmed: "No confirmed flags.",
  Dismissed: "No dismissed flags.",
  all: "Nothing has been flagged yet.",
};

// Flagged check-in attempts to review. Confirming keeps warning the desk at
// that member's check-ins; dismissing (a false alarm) stops the warning.
export default function FlaggedCheckIns({ refreshKey, onResolved }) {
  const [status, setStatus] = useState("Open");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [resolving, setResolving] = useState(null); // { flagId, outcome }
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolveError, setResolveError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchFlags(status)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [status, refreshKey]);

  function startResolving(flagId, outcome) {
    setResolving({ flagId, outcome });
    setNote("");
    setResolveError(null);
  }

  async function handleResolve() {
    setBusy(true);
    setResolveError(null);
    try {
      await resolveFlag(resolving.flagId, { outcome: resolving.outcome, note });
      setResolving(null);
      setData(await fetchFlags(status));
      onResolved();
    } catch (err) {
      setResolveError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div style={styles.filterRow}>
        <SegmentedControl options={STATUS_OPTIONS} value={status} onChange={setStatus} ariaLabel="Flag status" />
      </div>

      {error && <div style={styles.errorBox}>Couldn't load flags: {error}</div>}
      {data && data.results.length === 0 && <p style={styles.emptyText}>{EMPTY_TEXT[status]}</p>}

      {data?.results.map((flag) => {
        const attempt = flag.checkIn;
        const isResolving = resolving?.flagId === flag.id;
        return (
          <div key={flag.id} style={styles.card}>
            <div style={styles.cardTop}>
              <span style={styles.reason}>{flag.reason}</span>
              <span style={{ ...styles.statusBadge, ...STATUS_BADGES[flag.status] }}>{flag.status}</span>
            </div>
            <div style={styles.member}>
              {attempt.memberName} <span style={styles.muted}>#{attempt.memberId} &middot; {flag.memberStatus}</span>
            </div>
            <div style={styles.meta}>
              Attempt {attempt.checkedInAt} &middot;{" "}
              {attempt.result === "Allowed" ? "Allowed in" : `Denied (${attempt.reason})`}
            </div>
            {flag.note && <div style={styles.note}>"{flag.note}"</div>}
            <div style={styles.meta}>
              Flagged by {flag.flaggedBy || "unknown"} &middot; {flag.flaggedAt}
            </div>

            {flag.status !== "Open" && (
              <div style={styles.resolution}>
                {flag.status} by {flag.resolvedBy || "unknown"} &middot; {flag.resolvedAt}
                {flag.resolutionNote && ` - "${flag.resolutionNote}"`}
              </div>
            )}

            {flag.status === "Open" && !isResolving && (
              <div style={styles.actions}>
                <button onClick={() => startResolving(flag.id, "Dismissed")} style={styles.dismissButton}>
                  Dismiss (false alarm)
                </button>
                <button onClick={() => startResolving(flag.id, "Confirmed")} style={styles.confirmButton}>
                  Confirm
                </button>
              </div>
            )}

            {isResolving && (
              <div style={styles.resolveBox}>
                <div style={styles.resolveText}>
                  {resolving.outcome === "Confirmed"
                    ? `Confirm this was misuse? ${attempt.memberName} will keep triggering a photo ID check at the desk.`
                    : `Dismiss this flag? ${attempt.memberName} will no longer trigger a photo ID check for it.`}
                </div>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  maxLength={200}
                  aria-label="Resolution note"
                  placeholder="Note (optional), e.g. spoke to the member"
                  style={styles.input}
                />
                {resolveError && <div style={styles.errorText}>{resolveError}</div>}
                <div style={styles.actions}>
                  <button onClick={() => setResolving(null)} style={styles.dismissButton} disabled={busy}>
                    Never mind
                  </button>
                  <button
                    onClick={handleResolve}
                    disabled={busy}
                    style={resolving.outcome === "Confirmed" ? styles.confirmButton : styles.solidGreyButton}
                  >
                    {busy ? "Saving..." : resolving.outcome === "Confirmed" ? "Yes, confirm" : "Yes, dismiss"}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const styles = {
  filterRow: { maxWidth: 420, marginBottom: 14 },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    padding: "12px 14px",
    marginBottom: 10,
    background: "#fff",
  },
  cardTop: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 6 },
  reason: { fontSize: 14, fontWeight: 800, color: "#b3261e" },
  statusBadge: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999 },
  member: { fontSize: 14, fontWeight: 700 },
  muted: { fontSize: 12, fontWeight: 400, color: "#888" },
  meta: { fontSize: 12, color: "#666", marginTop: 3 },
  note: { fontSize: 13, color: "#333", marginTop: 6, fontStyle: "italic" },
  resolution: {
    fontSize: 12,
    color: "#444",
    marginTop: 8,
    padding: "6px 10px",
    borderRadius: 6,
    background: "#f5f5f7",
  },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 },
  dismissButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  confirmButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    cursor: "pointer",
  },
  solidGreyButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 8,
    background: "#555",
    color: "#fff",
    cursor: "pointer",
  },
  resolveBox: { marginTop: 10, paddingTop: 10, borderTop: "1px solid #f0f0f2" },
  resolveText: { fontSize: 13, color: "#333", marginBottom: 8 },
  input: {
    width: "100%",
    padding: "8px 10px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    boxSizing: "border-box",
  },
  emptyText: { fontSize: 13, color: "#888" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  errorText: { fontSize: 12, color: "#b3261e", marginTop: 6 },
};

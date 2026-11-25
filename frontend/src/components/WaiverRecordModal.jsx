import { useEffect, useRef, useState } from "react";
import { fetchMemberWaiver } from "../api/members.js";
import { fetchMyWaiver } from "../api/memberAuth.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";

function formatDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// Modal displaying a member's signed waiver record (SCRUM-83).
// Reused by staff (SubscriptionDetails) and members (MemberDashboard).
export default function WaiverRecordModal({ memberId, fetchRecord, onClose }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const modalRef = useRef(null);

  useEffect(() => {
    const fetcher = fetchRecord
      ? fetchRecord
      : memberId !== undefined && memberId !== null
      ? () => fetchMemberWaiver(memberId)
      : fetchMyWaiver;

    fetcher()
      .then(setData)
      .catch((err) => setLoadError(err.message || "Failed to load waiver record"));
  }, [memberId, fetchRecord]);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    if (modalRef.current) {
      modalRef.current.focus();
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const current = data?.current;

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="waiver-record-title"
        tabIndex={-1}
        style={styles.modal}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={styles.modalHeader}>
          <h2 id="waiver-record-title" style={styles.modalTitle}>
            Signed Waiver Record
          </h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {!data && !loadError && <div style={styles.muted}>Loading waiver record...</div>}
        {loadError && <div style={styles.errorBox}>{loadError}</div>}

        {data && !current && (
          <div style={styles.emptyNotice}>No signed waiver record on file for this member.</div>
        )}

        {current && (
          <>
            <p style={styles.subtitle}>
              {current.signatureName} &middot; Version {current.waiverVersion}
            </p>

            <div style={styles.card}>
              <Row label="Signed name" value={current.signatureName} />
              <Row
                label="Version"
                value={
                  <span style={styles.versionWrap}>
                    <span>{current.waiverVersion}</span>
                    {data.needsResign && (
                      <span style={styles.badgeWarn}>Out of date — member must re-sign</span>
                    )}
                  </span>
                }
              />
              <Row label="Signed via" value={current.signedVia} />
              <Row label="Witnessed by" value={current.witnessedBy || "—"} />
              <Row label="Signed at" value={formatDateTime(current.signedAt)} />
              <Row label="IP address" value={current.ipAddress || "Not recorded"} />
              <Row
                label="Liability waiver"
                value={
                  <span style={current.liabilityWaiverAccepted ? styles.tickAccepted : styles.tickDeclined}>
                    {current.liabilityWaiverAccepted ? "✓ Accepted" : "✗ Not accepted"}
                  </span>
                }
              />
              <Row
                label="Health disclaimer"
                value={
                  <span style={current.healthDisclaimerAccepted ? styles.tickAccepted : styles.tickDeclined}>
                    {current.healthDisclaimerAccepted ? "✓ Accepted" : "✗ Not accepted"}
                  </span>
                }
              />
            </div>

            <h3 style={styles.sectionTitle}>Signed agreement text</h3>
            <div style={styles.textBox} tabIndex={0} aria-label="Signed waiver text">
              <pre style={styles.preText}>{current.text}</pre>
            </div>

            {data.history && data.history.length > 1 && (
              <>
                <h3 style={styles.sectionTitle}>Earlier signatures</h3>
                <div style={styles.historyList}>
                  {data.history.slice(1).map((h, idx) => (
                    <div key={idx} style={styles.historyRow}>
                      <div style={styles.historyMain}>
                        <div style={styles.historyVersion}>Version {h.waiverVersion}</div>
                        <div style={styles.historyMeta}>
                          Signed by {h.signatureName} &middot; {h.signedVia}
                          {h.witnessedBy ? ` &middot; Witnessed by ${h.witnessedBy}` : ""}
                          {" &middot; IP: "}{h.ipAddress || "Not recorded"}
                        </div>
                      </div>
                      <div style={styles.historyTime}>{formatDateTime(h.signedAt)}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}

        <div style={styles.footer}>
          <button type="button" onClick={onClose} style={styles.closeAction}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={styles.row}>
      <span style={styles.rowLabel}>{label}</span>
      <span style={styles.rowValue}>{value}</span>
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
    zIndex: 1100,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 580,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
    outline: "none",
  },
  modalHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 13, color: "#666", margin: "0 0 16px" },
  closeButton: {
    border: "none",
    background: "transparent",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
    color: "#888",
  },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "hidden",
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "10px 14px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 14,
  },
  rowLabel: { color: "#666", flexShrink: 0 },
  rowValue: { fontWeight: 600, textAlign: "right" },
  versionWrap: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
    justifyContent: "flex-end",
  },
  badgeWarn: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 6,
    background: "#fff4e0",
    color: "#8a5a00",
  },
  tickAccepted: {
    color: "#1d5e2f",
    fontWeight: 600,
  },
  tickDeclined: {
    color: "#b3261e",
    fontWeight: 600,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: "#555",
    margin: "20px 0 8px",
  },
  textBox: {
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fafafa",
    padding: "12px 14px",
    maxHeight: 220,
    overflowY: "auto",
  },
  preText: {
    margin: 0,
    fontFamily: "inherit",
    fontSize: 12,
    lineHeight: 1.6,
    color: "#333",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  historyList: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "hidden",
  },
  historyRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    gap: 12,
    padding: "10px 12px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 13,
  },
  historyMain: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    minWidth: 0,
  },
  historyVersion: {
    fontWeight: 600,
    color: "#1a1a1a",
  },
  historyMeta: {
    fontSize: 12,
    color: "#666",
  },
  historyTime: {
    fontSize: 12,
    color: "#888",
    whiteSpace: "nowrap",
    flexShrink: 0,
  },
  muted: { fontSize: 13, color: "#777", padding: "16px 0" },
  emptyNotice: {
    fontSize: 13,
    color: "#666",
    padding: 16,
    border: "1px dashed #d0d0d5",
    borderRadius: 10,
    textAlign: "center",
    margin: "12px 0",
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    margin: "10px 0",
  },
  footer: {
    display: "flex",
    justifyContent: "flex-end",
    marginTop: 20,
  },
  closeAction: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

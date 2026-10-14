import { useState } from "react";
import { cancelMembership } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";

// Read-only view of an Active member's subscription - where the expiry
// date lives now that it's no longer a column in the main directory
// table. Uses data already on the member row (no extra request needed).
// Also where a subscription gets ended: status -> Cancelled. A member
// cancelled this way can still be re-subscribed later (the "Subscribe"
// button), same as any Frozen member.
export default function SubscriptionDetails({ member, onClose, onCancelled }) {
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState(null);

  async function handleEndSubscription() {
    setCancelling(true);
    setError(null);
    try {
      const updated = await cancelMembership(member.id);
      onCancelled(updated);
    } catch (err) {
      setError(err.message);
      setCancelling(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>Subscription Details</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <p style={styles.subtitle}>{member.name}</p>

        <div style={styles.card}>
          <Row label="Membership ID" value={`#${member.id}`} />
          <Row label="Status" value={<span style={styles.statusBadge}>{member.status}</span>} />
          <Row label="Membership plan" value={member.membershipPlan} />
          <Row label="Branch" value={member.branch} />
          <Row label="Member since" value={member.joinDate} />
          <Row label="Subscription expires" value={member.subscriptionExpiresAt || "—"} />
        </div>

        {error && <div style={styles.errorBox}>{error}</div>}

        {confirming ? (
          <div style={styles.confirmBox}>
            <p style={styles.confirmText}>End this member's subscription? They can be re-subscribed later.</p>
            <div style={styles.actions}>
              <button onClick={() => setConfirming(false)} style={styles.closeAction} disabled={cancelling}>
                Never mind
              </button>
              <button onClick={handleEndSubscription} style={styles.confirmEndButton} disabled={cancelling}>
                {cancelling ? "Ending..." : "Yes, end subscription"}
              </button>
            </div>
          </div>
        ) : (
          <div style={styles.actions}>
            <button onClick={() => setConfirming(true)} style={styles.endButton}>
              End Subscription
            </button>
            <button onClick={onClose} style={styles.closeAction}>
              Close
            </button>
          </div>
        )}
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
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 380,
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
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
    padding: "10px 14px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 14,
  },
  rowLabel: { color: "#666" },
  rowValue: { fontWeight: 600 },
  statusBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 22,
    padding: "0 10px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    ...BUTTON_COLORS.green,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginTop: 14,
  },
  confirmBox: { marginTop: 16 },
  confirmText: { fontSize: 13, color: "#444", margin: "0 0 12px" },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 10,
    marginTop: 18,
  },
  closeAction: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  endButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
    marginRight: "auto",
  },
  confirmEndButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
};

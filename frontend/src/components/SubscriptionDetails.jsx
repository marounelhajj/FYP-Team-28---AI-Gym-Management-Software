import { useEffect, useState } from "react";
import { cancelMembership, fetchMemberBilling } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import PaymentMethodForm from "./PaymentMethodForm.jsx";

const STATUS_STYLES = { Active: BUTTON_COLORS.green, Frozen: BUTTON_COLORS.blue, Cancelled: BUTTON_COLORS.red };

// An Active member's subscription, payment method on file and payment
// history - and where it gets renewed or ended (status -> Cancelled; a
// cancelled member can be re-subscribed later with the "Subscribe" button).
export default function SubscriptionDetails({ member, onClose, onCancelled, onRenew }) {
  const [billing, setBilling] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState(null);
  const [showMethodForm, setShowMethodForm] = useState(false);
  const [methodSaved, setMethodSaved] = useState(false);

  const current = billing?.member ?? member;
  const onFile = billing?.paymentMethod ?? null;

  useEffect(() => {
    fetchMemberBilling(member.id)
      .then(setBilling)
      .catch((err) => setLoadError(err.message));
  }, [member.id]);

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

  function handleMethodSaved(saved) {
    setShowMethodForm(false);
    setBilling((b) => ({ ...b, paymentMethod: saved }));
    setMethodSaved(true);
  }

  return (
    <>
      <div style={styles.overlay} onClick={onClose}>
        <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
          <div style={styles.modalHeader}>
            <h2 style={styles.modalTitle}>Subscription Details</h2>
            <button onClick={onClose} style={styles.closeButton} aria-label="Close">
              &times;
            </button>
          </div>

          <p style={styles.subtitle}>{current.name}</p>

          <div style={styles.card}>
            <Row label="Membership ID" value={`#${current.id}`} />
            <Row
              label="Status"
              value={
                <span style={{ ...styles.statusBadge, ...(STATUS_STYLES[current.status] || BUTTON_COLORS.blue) }}>
                  {current.status}
                </span>
              }
            />
            <Row label="Membership plan" value={current.membershipPlan} />
            <Row label="Branch" value={current.branch} />
            <Row label="Member since" value={current.joinDate} />
            <Row label="Subscription expires" value={current.subscriptionExpiresAt || "—"} />
            <Row
              label="Waiver"
              value={
                current.waiver
                  ? `Signed ${current.waiver.signedAt.slice(0, 10)} (${current.waiver.signedVia}${
                      current.waiver.witnessedBy ? `, witnessed by ${current.waiver.witnessedBy}` : ""
                    })`
                  : "Not on file"
              }
            />
          </div>

          <h3 style={styles.sectionTitle}>Payment method on file</h3>
          <div style={styles.methodCard}>
            {!billing && !loadError && <span style={styles.muted}>Loading...</span>}
            {loadError && <span style={styles.errorText}>Couldn't load billing details: {loadError}</span>}
            {billing && (
              <>
                <div style={styles.methodInfo}>
                  {onFile ? (
                    <>
                      <div style={styles.methodSummary}>
                        {onFile.summary}
                        {onFile.cardExpired && <span style={styles.badgeDanger}>Expired</span>}
                        {onFile.cardExpiresBeforeRenewal && (
                          <span style={styles.badgeWarn}>Expires before next renewal</span>
                        )}
                      </div>
                      <div style={styles.muted}>
                        {onFile.method === "Card" && `${onFile.cardHolderName} · `}
                        Updated {onFile.updatedAt}
                        {onFile.updatedBy ? ` by ${onFile.updatedBy}` : ""}
                      </div>
                    </>
                  ) : (
                    <div style={styles.muted}>No payment method on file yet.</div>
                  )}
                  {methodSaved && <div style={styles.savedText}>Payment method updated.</div>}
                </div>
                <button
                  onClick={() => {
                    setMethodSaved(false);
                    setShowMethodForm(true);
                  }}
                  style={styles.secondaryButton}
                >
                  {onFile ? "Update" : "Add payment method"}
                </button>
              </>
            )}
          </div>

          <h3 style={styles.sectionTitle}>Payment history</h3>
          {billing && <PaymentHistory payments={billing.payments} total={billing.paymentCount} />}

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
              <button onClick={() => onRenew(current)} style={styles.renewButton}>
                Renew Membership
              </button>
            </div>
          )}
        </div>
      </div>

      {showMethodForm && (
        <PaymentMethodForm
          member={current}
          current={onFile}
          onClose={() => setShowMethodForm(false)}
          onSaved={handleMethodSaved}
        />
      )}
    </>
  );
}

function PaymentHistory({ payments, total }) {
  if (payments.length === 0) {
    return <div style={styles.emptyHistory}>No payments recorded yet.</div>;
  }
  return (
    <>
      <div style={styles.historyWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Date</th>
              <th style={styles.th}>Type</th>
              <th style={styles.th}>Amount</th>
              <th style={styles.th}>Paid with</th>
              <th style={styles.th}>Valid until</th>
              <th style={styles.th}>Taken by</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr key={p.id}>
                <td style={styles.tdNoWrap}>{p.paidAt.slice(0, 10)}</td>
                <td style={styles.td}>
                  {p.note || "Payment"}
                  <div style={styles.cellSub}>{p.duration}</div>
                </td>
                <td style={{ ...styles.tdNoWrap, fontWeight: 600 }}>${p.amount}</td>
                <td style={styles.td}>{p.methodDetail || p.method}</td>
                <td style={styles.tdNoWrap}>{p.expiresAt}</td>
                <td style={styles.td}>
                  {p.recordedBy || (p.note === "First payment at signup" ? "Online signup" : "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > payments.length && (
        <div style={styles.historyNote}>
          Showing the {payments.length} most recent of {total} payments.
        </div>
      )}
    </>
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
    maxWidth: 640,
    maxHeight: "90vh",
    overflowY: "auto",
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
    gap: 12,
    padding: "10px 14px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 14,
  },
  rowLabel: { color: "#666" },
  rowValue: { fontWeight: 600, textAlign: "right" },
  statusBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 22,
    padding: "0 10px",
    borderRadius: 6,
    fontSize: 12,
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
  methodCard: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "12px 14px",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
  },
  methodInfo: { minWidth: 0 },
  methodSummary: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 2,
  },
  badgeDanger: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 6,
    ...BUTTON_COLORS.red,
  },
  badgeWarn: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 6,
    background: "#fff4e0",
    color: "#8a5a00",
  },
  muted: { fontSize: 12, color: "#777" },
  errorText: { fontSize: 13, color: "#b3261e" },
  savedText: { fontSize: 12, color: "#1e7a34", fontWeight: 600, marginTop: 4 },
  secondaryButton: {
    flexShrink: 0,
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  historyWrap: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "auto",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    background: "#fafafa",
    borderBottom: "1px solid #e4e4e8",
    fontWeight: 600,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: 0.3,
    color: "#555",
    whiteSpace: "nowrap",
  },
  td: {
    padding: "8px 10px",
    borderBottom: "1px solid #f0f0f2",
    verticalAlign: "top",
  },
  tdNoWrap: {
    padding: "8px 10px",
    borderBottom: "1px solid #f0f0f2",
    verticalAlign: "top",
    whiteSpace: "nowrap",
  },
  cellSub: { fontSize: 11, color: "#888" },
  emptyHistory: {
    padding: "14px",
    border: "1px dashed #d0d0d5",
    borderRadius: 10,
    fontSize: 13,
    color: "#888",
    textAlign: "center",
  },
  historyNote: { fontSize: 12, color: "#888", marginTop: 6 },
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
  renewButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.green,
    fontWeight: 600,
    cursor: "pointer",
  },
};

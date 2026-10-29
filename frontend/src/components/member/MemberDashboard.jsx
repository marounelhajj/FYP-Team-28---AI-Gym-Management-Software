import { useEffect, useState } from "react";
import {
  cancelMyMembership,
  fetchMyBilling,
  fetchMyPaymentMethod,
  fetchMyQrCode,
  freezeMyMembership,
  resumeMyMembership,
} from "../../api/memberAuth.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import MemberBooking from "./MemberBooking.jsx";
import MemberPaymentMethodForm from "./MemberPaymentMethodForm.jsx";
import MemberPrivacyPanel from "./MemberPrivacyPanel.jsx";
import MemberProfileForm from "./MemberProfileForm.jsx";

const STATUS_STYLES = {
  Active: BUTTON_COLORS.green,
  Frozen: BUTTON_COLORS.blue,
  Cancelled: BUTTON_COLORS.red,
};

// Minimal placeholder landing page for a logged-in member - just enough to
// prove the signup/login loop actually works end-to-end. The real member
// portal (class booking, AI plans, billing, chatbot, etc.) is a separate,
// much larger set of backlog stories for a future pass.
// User story (profile + payment method editing): "As a member, I want to
// update my saved payment method and personal profile information myself
// in the app, so that I don't need to visit the front desk for routine
// changes."
// User story (billing history): "As a member, I want to view my
// membership details and billing history, so that I can track payments
// and my renewal date."
// User story (freeze/cancel): "As a member, I want to freeze or cancel my
// membership through the app, so that I have control over my
// subscription without a front-desk visit."
// User story (SCRUM-62): "As a member, I want to request an export or
// deletion of my personal data, so that I have control over my own privacy."
// Booking: classes, coaches and private training, and the member's own
// bookings (MemberBooking.jsx). Re-keyed on status, so freezing (which frees
// future spots and sessions) reloads it.
export default function MemberDashboard({ member: initialMember, onDeleted }) {
  const [member, setMember] = useState(initialMember);
  const statusStyle = STATUS_STYLES[member.status] || { background: "#eee", color: "#333" };
  const [qr, setQr] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState(null);
  const [billing, setBilling] = useState(null);
  const [billingError, setBillingError] = useState(null);
  const [showProfileForm, setShowProfileForm] = useState(false);
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [savedNotice, setSavedNotice] = useState(null);
  const [membershipError, setMembershipError] = useState(null);
  const [membershipBusy, setMembershipBusy] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  // Check-in QR code (SCRUM-33): shown at the front desk instead of
  // reading out the membership ID.
  useEffect(() => {
    fetchMyQrCode()
      .then(setQr)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMyPaymentMethod()
      .then(setPaymentMethod)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMyBilling()
      .then(setBilling)
      .catch((err) => setBillingError(err.message));
  }, []);

  // Auto-dismiss the "saved" banner after a few seconds, same pattern as
  // the receptionist's Member Directory.
  useEffect(() => {
    if (!savedNotice) return;
    const timer = setTimeout(() => setSavedNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [savedNotice]);

  function handleProfileSaved(updated) {
    setMember(updated);
    setShowProfileForm(false);
    setSavedNotice("Your profile was updated.");
  }

  function handlePaymentMethodSaved(saved) {
    setPaymentMethod(saved);
    setShowPaymentForm(false);
    setSavedNotice("Your payment method was updated.");
  }

  async function handleFreeze() {
    setMembershipError(null);
    setMembershipBusy(true);
    try {
      const updated = await freezeMyMembership();
      setMember(updated);
      setSavedNotice("Your membership is frozen. Resume it any time.");
    } catch (err) {
      setMembershipError(err.message);
    } finally {
      setMembershipBusy(false);
    }
  }

  async function handleResume() {
    setMembershipError(null);
    setMembershipBusy(true);
    try {
      const updated = await resumeMyMembership();
      setMember(updated);
      setSavedNotice("Your membership is active again.");
    } catch (err) {
      setMembershipError(err.message);
    } finally {
      setMembershipBusy(false);
    }
  }

  async function handleCancel() {
    setMembershipError(null);
    setMembershipBusy(true);
    try {
      const updated = await cancelMyMembership();
      setMember(updated);
      setConfirmingCancel(false);
      setSavedNotice("Your membership has been cancelled.");
    } catch (err) {
      setMembershipError(err.message);
    } finally {
      setMembershipBusy(false);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Welcome, {member.name.split(" ")[0]}</h1>
          <p style={styles.subtitle}>Your membership at a glance.</p>
        </div>
        <button onClick={() => setShowProfileForm(true)} style={styles.editButton}>
          Edit profile
        </button>
      </div>

      {savedNotice && <div style={styles.successBox}>{savedNotice}</div>}

      <div style={styles.card}>
        <Row label="Name" value={member.name} />
        <Row label="Email" value={member.email} />
        <Row label="Phone" value={member.phone} />
        <Row label="Branch" value={member.branch} />
        <Row label="Plan" value={member.membershipPlan} />
        <Row
          label="Status"
          value={
            <span style={{ ...styles.statusBadge, background: statusStyle.background, color: statusStyle.color }}>
              {member.status}
            </span>
          }
        />
        <Row label="Renewal date" value={member.subscriptionExpiresAt || "—"} />
        <Row label="Member since" value={member.joinDate} />
        <Row
          label="Waiver"
          value={member.waiver ? `Signed ${member.waiver.signedAt.slice(0, 10)}` : "Not on file - ask at the front desk"}
        />
      </div>

      {qr && (
        <div style={styles.qrCard}>
          <img src={qr.qrCode} alt={`Check-in QR code for membership #${qr.membershipId}`} style={styles.qrImage} />
          <div>
            <div style={styles.qrTitle}>Your check-in code</div>
            <div style={styles.qrText}>Show this at the front desk to check in.</div>
            <div style={styles.qrId}>Membership ID #{qr.membershipId}</div>
          </div>
        </div>
      )}

      <h2 style={styles.sectionTitle}>Book at {member.branch}</h2>
      <MemberBooking key={member.status} />

      <div style={styles.paymentCard}>
        <div style={styles.paymentCardHeader}>
          <span style={styles.paymentCardTitle}>Payment method</span>
          <button onClick={() => setShowPaymentForm(true)} style={styles.smallButton}>
            {paymentMethod ? "Update" : "Add"}
          </button>
        </div>
        <div style={styles.paymentCardValue}>
          {paymentMethod ? paymentMethod.summary : "Not on file - add one so renewals are one click."}
        </div>
      </div>

      <h2 style={styles.sectionTitle}>Billing history</h2>
      {billingError && <div style={styles.errorBox}>Couldn't load your billing history: {billingError}</div>}
      {billing && <BillingHistory payments={billing.payments} total={billing.paymentCount} />}

      <h2 style={styles.sectionTitle}>Membership controls</h2>
      {membershipError && <div style={styles.errorBox}>{membershipError}</div>}

      {member.status === "Cancelled" ? (
        <p style={styles.membershipNote}>
          Your membership is cancelled. Visit the front desk if you'd like to rejoin.
        </p>
      ) : (
        <div style={styles.membershipCard}>
          <div style={styles.membershipActions}>
            {member.status === "Frozen" ? (
              <button onClick={handleResume} disabled={membershipBusy} style={styles.smallButton}>
                {membershipBusy ? "Resuming..." : "Resume membership"}
              </button>
            ) : (
              <button onClick={handleFreeze} disabled={membershipBusy} style={styles.smallButton}>
                {membershipBusy ? "Freezing..." : "Freeze membership"}
              </button>
            )}
            <button
              onClick={() => setConfirmingCancel(true)}
              disabled={membershipBusy}
              style={styles.dangerButton}
            >
              Cancel membership
            </button>
          </div>

          {confirmingCancel && (
            <div style={styles.confirmBox}>
              <p style={styles.confirmText}>
                Cancel your membership? You'll need to visit the front desk to rejoin later.
              </p>
              <div style={styles.confirmActions}>
                <button
                  onClick={() => setConfirmingCancel(false)}
                  disabled={membershipBusy}
                  style={styles.smallButton}
                >
                  Never mind
                </button>
                <button onClick={handleCancel} disabled={membershipBusy} style={styles.dangerButton}>
                  {membershipBusy ? "Cancelling..." : "Yes, cancel"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <h2 style={styles.sectionTitle}>Your data &amp; privacy</h2>
      <MemberPrivacyPanel onDeleted={onDeleted} />

      <p style={styles.note}>The AI chatbot is coming in a future update.</p>

      {showProfileForm && (
        <MemberProfileForm member={member} onClose={() => setShowProfileForm(false)} onSaved={handleProfileSaved} />
      )}

      {showPaymentForm && (
        <MemberPaymentMethodForm
          member={member}
          current={paymentMethod}
          onClose={() => setShowPaymentForm(false)}
          onSaved={handlePaymentMethodSaved}
        />
      )}
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

// Read-only table of the member's own past payments - same columns as the
// receptionist-facing PaymentHistory in ../SubscriptionDetails.jsx (Date,
// Type, Amount, Paid with, Valid until), minus "Taken by": useful for
// staff reviewing a payment, not for a member checking their own history.
function BillingHistory({ payments, total }) {
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

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 480,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    marginBottom: 20,
  },
  title: { fontSize: 24, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  editButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  successBox: {
    background: "#e6f4ea",
    color: "#1e7a34",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  paymentCard: {
    marginTop: 16,
    padding: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  paymentCardHeader: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  paymentCardTitle: { fontSize: 14, fontWeight: 700 },
  paymentCardValue: { fontSize: 13, color: "#666", marginTop: 6 },
  smallButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "hidden",
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    padding: "12px 16px",
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
    width: 76,
    padding: "0 10px",
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1,
  },
  qrCard: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    marginTop: 16,
    padding: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  qrImage: { width: 132, height: 132, flexShrink: 0 },
  qrTitle: { fontSize: 16, fontWeight: 700 },
  qrText: { fontSize: 13, color: "#666", marginTop: 4 },
  qrId: { fontSize: 13, fontWeight: 600, marginTop: 10 },
  note: { fontSize: 13, color: "#888", marginTop: 20, textAlign: "center" },
  sectionTitle: { fontSize: 16, fontWeight: 700, margin: "24px 0 10px" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 10,
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
  membershipNote: {
    fontSize: 13,
    color: "#666",
    padding: 16,
    border: "1px dashed #d0d0d5",
    borderRadius: 10,
    textAlign: "center",
  },
  membershipCard: {
    padding: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  membershipActions: { display: "flex", gap: 10, flexWrap: "wrap" },
  dangerButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
  confirmBox: { marginTop: 14 },
  confirmText: { fontSize: 13, color: "#444", margin: "0 0 10px" },
  confirmActions: { display: "flex", gap: 10 },
};

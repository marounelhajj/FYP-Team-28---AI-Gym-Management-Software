import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const STATUS_STYLES = {
  Active: BUTTON_COLORS.green,
  Frozen: BUTTON_COLORS.blue,
  Cancelled: BUTTON_COLORS.red,
};

// Minimal placeholder landing page for a logged-in member - just enough to
// prove the signup/login loop actually works end-to-end. The real member
// portal (class booking, AI plans, billing, chatbot, etc.) is a separate,
// much larger set of backlog stories for a future pass.
export default function MemberDashboard({ member }) {
  const statusStyle = STATUS_STYLES[member.status] || { background: "#eee", color: "#333" };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Welcome, {member.name.split(" ")[0]}</h1>
      <p style={styles.subtitle}>Your membership at a glance.</p>

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
        <Row label="Member since" value={member.joinDate} />
      </div>

      <p style={styles.note}>
        Class booking, billing, and the AI chatbot are coming in a future update.
      </p>
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
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 480,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  title: { fontSize: 24, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4, marginBottom: 24 },
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
  note: { fontSize: 13, color: "#888", marginTop: 20, textAlign: "center" },
};

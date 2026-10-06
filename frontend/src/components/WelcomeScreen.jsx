import { BUTTON_COLORS } from "../styles/buttonColors.js";
import Logo from "./Logo.jsx";

// Shown once, right after a successful login (never on a restored session /
// page refresh), so it's unmistakable which account and role just signed
// in and which screen they're about to land on. Addresses the "login page
// isn't understandable" feedback: role is resolved server-side (see
// administration/auth_views.py) and this is where that outcome becomes
// visible, instead of silently routing in the background.
export default function WelcomeScreen({ account, destination, onContinue }) {
  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logoWrap}>
          <Logo size={40} showWordmark={false} />
        </div>

        <p style={styles.eyebrow}>Logged in successfully</p>
        <h1 style={styles.name}>{account.fullName}</h1>

        <span style={styles.roleBadge}>{account.roleName}</span>

        <p style={styles.destination}>
          Taking you to <strong>{destination}</strong>.
        </p>

        <button onClick={onContinue} style={styles.continueButton} autoFocus>
          Continue
        </button>
      </div>
    </div>
  );
}

const styles = {
  page: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#f5f5f7",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    padding: 20,
  },
  card: {
    background: "#fff",
    border: "1px solid #e4e4e8",
    borderRadius: 14,
    padding: "32px 28px",
    width: "100%",
    maxWidth: 360,
    textAlign: "center",
    boxShadow: "0 10px 40px rgba(0,0,0,0.06)",
  },
  logoWrap: { display: "flex", justifyContent: "center", marginBottom: 18 },
  eyebrow: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: 0.6,
    textTransform: "uppercase",
    color: "#129638",
    margin: "0 0 6px",
  },
  name: { fontSize: 20, fontWeight: 700, margin: "0 0 12px", color: "#1a1a1a" },
  roleBadge: {
    display: "inline-block",
    ...BUTTON_COLORS.blue,
    fontSize: 12,
    fontWeight: 700,
    padding: "4px 12px",
    borderRadius: 999,
    marginBottom: 16,
  },
  destination: { fontSize: 13, color: "#666", margin: "0 0 22px" },
  continueButton: {
    width: "100%",
    padding: "11px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.green,
    fontWeight: 600,
    cursor: "pointer",
  },
};

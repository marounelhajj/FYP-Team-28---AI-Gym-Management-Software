import { useState } from "react";
import { loginMember } from "../../api/memberAuth.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import Logo from "../Logo.jsx";

// Member sign-in. Mirrors the staff LoginPage but hits /api/members/login
// and links both ways to sign-up (prospective members) and to the staff
// login (so neither audience gets stuck on the wrong page).
export default function MemberLoginPage({ onLoggedIn, onSwitchToSignup, onSwitchToStaff }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const member = await loginMember(username, password);
      onLoggedIn(member);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logoWrap}>
          <Logo size={44} />
        </div>

        <h1 style={styles.title}>Member Login</h1>
        <p style={styles.subtitle}>Book classes, check your membership, and more.</p>

        <form onSubmit={handleSubmit}>
          <label style={styles.label}>Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={styles.input}
            autoFocus
            autoComplete="username"
          />

          <label style={styles.label}>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={styles.input}
            autoComplete="current-password"
          />

          {error && <div style={styles.errorBox}>{error}</div>}

          <button type="submit" disabled={submitting} style={styles.submitButton}>
            {submitting ? "Logging in..." : "Login"}
          </button>
        </form>

        <p style={styles.switchLine}>
          Don't have an account?{" "}
          <button type="button" onClick={onSwitchToSignup} style={styles.linkButton}>
            Sign up
          </button>
        </p>
        <p style={styles.switchLine}>
          Staff member?{" "}
          <button type="button" onClick={onSwitchToStaff} style={styles.linkButton}>
            Login here
          </button>
        </p>
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
    boxShadow: "0 10px 40px rgba(0,0,0,0.06)",
  },
  logoWrap: { display: "flex", justifyContent: "center", marginBottom: 20 },
  title: { fontSize: 20, fontWeight: 700, margin: "0 0 6px", textAlign: "center", color: "#1a1a1a" },
  subtitle: { fontSize: 13, color: "#666", textAlign: "center", margin: "0 0 24px" },
  label: {
    display: "block",
    fontSize: 13,
    fontWeight: 600,
    marginBottom: 6,
    color: "#444",
  },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    marginBottom: 16,
    boxSizing: "border-box",
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 16,
  },
  submitButton: {
    width: "100%",
    padding: "11px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
  switchLine: { fontSize: 13, color: "#666", textAlign: "center", margin: "14px 0 0" },
  linkButton: {
    border: "none",
    background: "none",
    color: "#124096",
    fontWeight: 600,
    fontSize: 13,
    cursor: "pointer",
    padding: 0,
  },
};

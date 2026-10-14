import { useState } from "react";
import { login, logout, verifyTwoFactor } from "../api/auth.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import Logo from "./Logo.jsx";

// Staff sign-in only. There is intentionally no sign-up link and no role
// picker here: staff accounts are provisioned by a System Administrator
// (Admin Console -> Staff Accounts -> + New Staff Account), never
// self-registered, and each account's role is resolved server-side from
// the account record on login - never chosen by the person signing in.
//
// Two-factor (SCRUM-87): after the password, the backend asks either for a
// code from the authenticator app ("verify") or, on an account's first
// login, to scan a QR code and confirm it ("enroll"). Enrollment ends on a
// one-time screen listing the backup codes.
export default function LoginPage({ onLoggedIn, onSwitchToMember, onBrowsePlans }) {
  const [step, setStep] = useState("password"); // password | verify | enroll | backupCodes
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState(null);
  const [signedIn, setSignedIn] = useState(null); // { account, backupCodes } after enrolling
  const [useBackupCode, setUseBackupCode] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handlePassword(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await login(username, password);
      setPassword("");
      setCode("");
      setEnrollment(result.enrollment || null);
      setStep(result.twoFactor === "enroll" ? "enroll" : "verify");
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCode(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { backupCodes, ...account } = await verifyTwoFactor(code);
      if (backupCodes) {
        setSignedIn({ account, backupCodes });
        setStep("backupCodes");
      } else {
        onLoggedIn(account);
      }
    } catch (err) {
      setError(err.message);
      setCode("");
      // The pending sign-in only lasts a few minutes; start over once it's gone.
      if (err.message.includes("Enter your password again")) startOver();
    } finally {
      setSubmitting(false);
    }
  }

  function startOver() {
    logout();
    setStep("password");
    setCode("");
    setEnrollment(null);
    setUseBackupCode(false);
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logoWrap}>
          <Logo size={44} />
        </div>

        {step === "password" && (
          <>
            <h1 style={styles.title}>Staff Login</h1>
            <p style={styles.subtitle}>
              Accounts are created by a System Administrator. Contact yours if you don't have one yet.
            </p>

            <form onSubmit={handlePassword}>
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
              Gym member?{" "}
              <button type="button" onClick={onSwitchToMember} style={styles.linkButton}>
                Login or sign up here
              </button>
            </p>
            <p style={styles.switchLine}>
              Thinking of joining?{" "}
              <button type="button" onClick={onBrowsePlans} style={styles.linkButton}>
                Browse membership plans
              </button>
            </p>
          </>
        )}

        {(step === "verify" || step === "enroll") && (
          <>
            <h1 style={styles.title}>{step === "enroll" ? "Set Up Two-Factor Sign-In" : "Two-Factor Sign-In"}</h1>

            {step === "enroll" ? (
              <>
                <p style={styles.subtitle}>
                  Staff accounts need a second step at login. Scan this QR code with an authenticator app
                  (Google Authenticator, Microsoft Authenticator, Authy...), then enter the 6-digit code it shows.
                </p>
                <img src={enrollment.qrCode} alt="QR code to add this account to an authenticator app" style={styles.qr} />
                <p style={styles.secretLabel}>Can't scan it? Enter this key in the app instead:</p>
                <code style={styles.secret}>{enrollment.secret.match(/.{1,4}/g).join(" ")}</code>
              </>
            ) : (
              <p style={styles.subtitle}>
                {useBackupCode
                  ? "Enter one of the backup codes you saved when you set up two-factor sign-in. Each code works once."
                  : "Enter the 6-digit code from your authenticator app."}
              </p>
            )}

            <form onSubmit={handleCode}>
              <label style={styles.label}>{useBackupCode ? "Backup code" : "Code"}</label>
              <input
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                style={{ ...styles.input, ...(useBackupCode ? null : styles.codeInput) }}
                autoFocus
                autoComplete="one-time-code"
                inputMode={useBackupCode ? "text" : "numeric"}
                maxLength={useBackupCode ? 11 : 6}
                placeholder={useBackupCode ? "XXXXX-XXXXX" : "123456"}
              />

              {error && <div style={styles.errorBox}>{error}</div>}

              <button type="submit" disabled={submitting || !code.trim()} style={styles.submitButton}>
                {submitting ? "Checking..." : step === "enroll" ? "Confirm and log in" : "Verify"}
              </button>
            </form>

            <p style={styles.switchLine}>
              {step === "verify" && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setUseBackupCode(!useBackupCode);
                      setCode("");
                      setError(null);
                    }}
                    style={styles.linkButton}
                  >
                    {useBackupCode ? "Use authenticator app code" : "Lost your phone? Use a backup code"}
                  </button>
                  <br />
                </>
              )}
              <button type="button" onClick={startOver} style={{ ...styles.linkButton, color: "#666", marginTop: 8 }}>
                Back to login
              </button>
            </p>
          </>
        )}

        {step === "backupCodes" && (
          <>
            <h1 style={styles.title}>Save Your Backup Codes</h1>
            <p style={styles.subtitle}>
              If you lose your phone, each of these codes lets you log in once. Store them somewhere safe, such as
              a password manager. They won't be shown again.
            </p>
            <ul style={styles.codeList}>
              {signedIn.backupCodes.map((c) => (
                <li key={c} style={styles.codeItem}>
                  {c}
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={() => navigator.clipboard?.writeText(signedIn.backupCodes.join("\n"))}
              style={styles.secondaryButton}
            >
              Copy codes
            </button>
            <button type="button" onClick={() => onLoggedIn(signedIn.account)} style={styles.submitButton}>
              I've saved them, continue
            </button>
          </>
        )}
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
  codeInput: { fontSize: 20, letterSpacing: 6, textAlign: "center", fontVariantNumeric: "tabular-nums" },
  qr: { display: "block", width: 180, height: 180, margin: "0 auto 12px" },
  secretLabel: { fontSize: 12, color: "#666", textAlign: "center", margin: "0 0 6px" },
  secret: {
    display: "block",
    fontSize: 13,
    textAlign: "center",
    background: "#f5f5f7",
    borderRadius: 8,
    padding: "8px 10px",
    marginBottom: 20,
    lineHeight: 1.6,
    userSelect: "all",
  },
  codeList: {
    listStyle: "none",
    padding: 0,
    margin: "0 0 16px",
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 8,
  },
  codeItem: {
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
    fontSize: 14,
    textAlign: "center",
    background: "#f5f5f7",
    borderRadius: 6,
    padding: "8px 4px",
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
  secondaryButton: {
    width: "100%",
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    fontWeight: 600,
    cursor: "pointer",
    marginBottom: 10,
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

import { useEffect, useState } from "react";
import { fetchWaiverText } from "../api/members.js";

// User story (SCRUM-83): "As a member, I want to sign a digital waiver and
// health disclaimer during signup, so that the gym has liability
// protection on file before I start training."
//
// Shared by the receptionist's walk-in form (RegisterMemberForm) and the
// online signup (MemberSignupPage), so whichever way someone joins they
// read and sign the same agreement. The text comes from the backend
// (GET /api/members/waiver), which also records its version with the
// signature. The backend refuses the whole registration unless both boxes
// are ticked and the signature matches `signerName`.
//
// `values` holds liabilityWaiverAccepted, healthDisclaimerAccepted and
// signatureName; `onChange(field, value)` updates one of them.
export const EMPTY_WAIVER = { liabilityWaiverAccepted: false, healthDisclaimerAccepted: false, signatureName: "" };

export function isWaiverComplete(values, signerName) {
  return (
    values.liabilityWaiverAccepted &&
    values.healthDisclaimerAccepted &&
    normalize(values.signatureName) !== "" &&
    normalize(values.signatureName) === normalize(signerName)
  );
}

function normalize(name) {
  return (name || "").trim().split(/\s+/).join(" ").toLowerCase();
}

export default function WaiverSection({ values, onChange, errors = {}, signerName, hint }) {
  const [text, setText] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    fetchWaiverText()
      .then(setText)
      .catch((err) => setLoadError(err.message));
  }, []);

  const signature = normalize(values.signatureName);
  const signatureMatches = signature !== "" && signature === normalize(signerName);

  return (
    <section style={styles.section} aria-labelledby="waiver-heading">
      <div id="waiver-heading" style={styles.heading}>
        Waiver &amp; health disclaimer
      </div>
      {hint && <p style={styles.hint}>{hint}</p>}

      <div style={styles.textBox} tabIndex={0} aria-label="Waiver and health disclaimer text">
        {loadError && <p style={styles.error}>Couldn't load the waiver: {loadError}</p>}
        {!text && !loadError && <p style={styles.text}>Loading...</p>}
        {text && (
          <>
            <strong style={styles.textHeading}>Liability waiver</strong>
            <p style={styles.text}>{text.liabilityWaiver}</p>
            <strong style={styles.textHeading}>Health disclaimer</strong>
            <p style={styles.text}>{text.healthDisclaimer}</p>
            <p style={styles.version}>Version {text.version}</p>
          </>
        )}
      </div>

      <Checkbox
        checked={values.liabilityWaiverAccepted}
        onChange={(v) => onChange("liabilityWaiverAccepted", v)}
        error={errors.liabilityWaiverAccepted}
      >
        I have read and agree to the liability waiver.
      </Checkbox>
      <Checkbox
        checked={values.healthDisclaimerAccepted}
        onChange={(v) => onChange("healthDisclaimerAccepted", v)}
        error={errors.healthDisclaimerAccepted}
      >
        I confirm the health disclaimer applies to me.
      </Checkbox>

      <label style={styles.label} htmlFor="waiver-signature">
        Signature: type your full name
      </label>
      <input
        id="waiver-signature"
        type="text"
        value={values.signatureName}
        onChange={(e) => onChange("signatureName", e.target.value)}
        placeholder={signerName || "Full name"}
        autoComplete="off"
        style={{ ...styles.signature, ...(signatureMatches ? styles.signatureSigned : null) }}
      />
      {signature !== "" && !signatureMatches && !errors.signatureName && (
        <div style={styles.mismatch}>Must match the full name entered above.</div>
      )}
      {errors.signatureName && <div style={styles.error}>{first(errors.signatureName)}</div>}
    </section>
  );
}

function Checkbox({ checked, onChange, error, children }) {
  return (
    <div style={styles.checkboxField}>
      <label style={styles.checkboxLabel}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          style={styles.checkbox}
        />
        <span>{children}</span>
      </label>
      {error && <div style={styles.error}>{first(error)}</div>}
    </div>
  );
}

function first(error) {
  return Array.isArray(error) ? error[0] : error;
}

const styles = {
  section: {
    borderTop: "1px solid #e4e4e8",
    marginTop: 6,
    paddingTop: 16,
    marginBottom: 14,
  },
  heading: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: "#124096",
    marginBottom: 6,
  },
  hint: { fontSize: 13, color: "#666", margin: "0 0 10px" },
  textBox: {
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fafafa",
    padding: "10px 12px",
    maxHeight: 150,
    overflowY: "auto",
    marginBottom: 12,
  },
  textHeading: { display: "block", fontSize: 12, color: "#1a1a1a", marginTop: 4 },
  text: { fontSize: 12, lineHeight: 1.5, color: "#444", margin: "4px 0 8px" },
  version: { fontSize: 11, color: "#999", margin: 0 },
  checkboxField: { marginBottom: 10 },
  checkboxLabel: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    fontSize: 13,
    color: "#1a1a1a",
    cursor: "pointer",
    lineHeight: 1.4,
  },
  checkbox: { width: 16, height: 16, marginTop: 1, flexShrink: 0, cursor: "pointer" },
  label: {
    display: "block",
    fontSize: 13,
    fontWeight: 600,
    margin: "14px 0 6px",
    color: "#444",
  },
  signature: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 18,
    fontStyle: "italic",
    fontFamily: "'Segoe Script', 'Brush Script MT', cursive",
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
  },
  signatureSigned: { borderColor: "#1d8a3e", background: "#f3faf5" },
  mismatch: { color: "#8a6100", fontSize: 12, marginTop: 4 },
  error: { color: "#b3261e", fontSize: 12, marginTop: 4 },
};

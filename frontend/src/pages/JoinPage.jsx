import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { createMember, fetchMemberFilterOptions } from "../api/members.js";
import { LIABILITY_WAIVER_TEXT, HEALTH_DISCLAIMER_TEXT } from "../data/waiverText.js";
import { PLAN_DETAILS } from "../data/planDetails.js";

// User story: "As a prospective member, I want to browse membership plans
// and sign up online, so that I can join a branch without visiting in
// person first."
//
// This is the public self-service door into the system - distinct from
// the receptionist's "Register New Member" action in the staff Member
// Directory, but it submits to the exact same POST /api/members endpoint.
// That endpoint already requires a signed waiver + health disclaimer to
// create a member (see the walk-in registration + digital waiver
// stories), so a prospective member signing up online goes through the
// same liability-protected path as a walk-in - there's no backend
// difference between the two, only who's filling in the form and where.
const EMPTY_FORM = {
  name: "",
  email: "",
  phone: "",
  branch: "",
  membershipPlan: "",
  signatureName: "",
  healthDisclaimerAccepted: false,
  liabilityWaiverAccepted: false,
};

export default function JoinPage() {
  const [filterOptions, setFilterOptions] = useState({ branches: [], statuses: [], plans: [] });
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [registeredMember, setRegisteredMember] = useState(null);

  const formRef = useRef(null);

  useEffect(() => {
    fetchMemberFilterOptions()
      .then(setFilterOptions)
      .catch(() => {
        // Non-fatal: plan cards / dropdowns just stay empty if this fails.
      });
  }, []);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function choosePlan(planName) {
    setForm((f) => ({ ...f, membershipPlan: planName }));
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const canSubmit =
    form.liabilityWaiverAccepted && form.healthDisclaimerAccepted && form.signatureName.trim().length > 0;

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    try {
      const member = await createMember(form);
      setRegisteredMember(member);
    } catch (err) {
      if (err.fieldErrors) {
        setFieldErrors(err.fieldErrors);
      } else {
        setSubmitError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (registeredMember) {
    return (
      <div style={styles.page}>
        <div style={styles.confirmationBox}>
          <div style={styles.confirmationEmoji}>🎉</div>
          <h1 style={styles.confirmationTitle}>Welcome, {registeredMember.name}!</h1>
          <p style={styles.confirmationText}>
            You're officially a member of our {registeredMember.branch} branch on the{" "}
            {registeredMember.membershipPlan} plan. Your liability waiver and health disclaimer are on
            file, so you're all set to start training.
          </p>
          <div style={styles.confirmationDetails}>
            <DetailRow label="Email" value={registeredMember.email} />
            <DetailRow label="Branch" value={registeredMember.branch} />
            <DetailRow label="Plan" value={registeredMember.membershipPlan} />
            <DetailRow label="Member since" value={registeredMember.joinDate} />
          </div>
          <p style={styles.confirmationFootnote}>
            Bring a valid ID on your first visit. We look forward to seeing you at the gym!
          </p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <div style={styles.hero}>
        <h1 style={styles.heroTitle}>Join us today</h1>
        <p style={styles.heroSubtitle}>
          Pick a plan and sign up online in a couple of minutes - no need to visit a branch first.
        </p>
      </div>

      <div style={styles.plansGrid}>
        {(filterOptions.plans || []).map((planName) => {
          const details = PLAN_DETAILS[planName] || {};
          const selected = form.membershipPlan === planName;
          return (
            <div key={planName} style={selected ? styles.planCardSelected : styles.planCard}>
              <div style={styles.planName}>{planName}</div>
              <div style={styles.planPrice}>
                {details.price}
                <span style={styles.planPeriod}>{details.period}</span>
              </div>
              <div style={styles.planTagline}>{details.tagline}</div>
              <ul style={styles.planFeatures}>
                {(details.features || []).map((f) => (
                  <li key={f} style={styles.planFeature}>
                    {f}
                  </li>
                ))}
              </ul>
              <button onClick={() => choosePlan(planName)} style={styles.planButton}>
                {selected ? "Selected" : "Choose this plan"}
              </button>
            </div>
          );
        })}
      </div>

      <div ref={formRef} style={styles.formCard}>
        <h2 style={styles.formTitle}>Create your membership</h2>

        <form onSubmit={handleSubmit}>
          <SectionLabel>1. Your details</SectionLabel>

          <Field label="Full name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Email" error={fieldErrors.email}>
            <input
              type="email"
              value={form.email}
              onChange={(e) => update("email", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Phone" error={fieldErrors.phone}>
            <input
              type="tel"
              value={form.phone}
              onChange={(e) => update("phone", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Branch" error={fieldErrors.branch}>
            <select
              value={form.branch}
              onChange={(e) => update("branch", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a branch...</option>
              {filterOptions.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Membership plan" error={fieldErrors.membershipPlan}>
            <select
              value={form.membershipPlan}
              onChange={(e) => update("membershipPlan", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a plan...</option>
              {(filterOptions.plans || []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>

          <SectionLabel>2. Waiver &amp; health disclaimer</SectionLabel>

          <div style={styles.waiverBox}>
            <strong style={styles.waiverHeading}>Liability Waiver</strong>
            <p style={styles.waiverText}>{LIABILITY_WAIVER_TEXT}</p>
            <strong style={styles.waiverHeading}>Health Disclaimer</strong>
            <p style={styles.waiverText}>{HEALTH_DISCLAIMER_TEXT}</p>
          </div>

          <CheckboxField error={fieldErrors.liabilityWaiverAccepted}>
            <input
              type="checkbox"
              checked={form.liabilityWaiverAccepted}
              onChange={(e) => update("liabilityWaiverAccepted", e.target.checked)}
              style={styles.checkbox}
            />
            <span>I have read and agree to the Liability Waiver above.</span>
          </CheckboxField>

          <CheckboxField error={fieldErrors.healthDisclaimerAccepted}>
            <input
              type="checkbox"
              checked={form.healthDisclaimerAccepted}
              onChange={(e) => update("healthDisclaimerAccepted", e.target.checked)}
              style={styles.checkbox}
            />
            <span>I have read and agree to the Health Disclaimer above.</span>
          </CheckboxField>

          <Field label="Type your full legal name to sign" error={fieldErrors.signatureName}>
            <input
              type="text"
              value={form.signatureName}
              onChange={(e) => update("signatureName", e.target.value)}
              placeholder="This serves as your digital signature"
              style={styles.input}
            />
          </Field>

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <button
            type="submit"
            disabled={submitting || !canSubmit}
            style={submitting || !canSubmit ? styles.submitButtonDisabled : styles.submitButton}
          >
            {submitting ? "Signing you up..." : "Complete sign up"}
          </button>
        </form>
      </div>

      <div style={styles.staffLinkRow}>
        <Link to="/" style={styles.staffLink}>
          Staff member? Go to the Member Directory
        </Link>
      </div>
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div style={styles.detailRow}>
      <span style={styles.detailLabel}>{label}</span>
      <span style={styles.detailValue}>{value}</span>
    </div>
  );
}

function SectionLabel({ children }) {
  return <div style={styles.sectionLabel}>{children}</div>;
}

function Field({ label, error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.label}>{label}</label>
      {children}
      {message && <div style={styles.fieldError}>{message}</div>}
    </div>
  );
}

function CheckboxField({ error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.checkboxLabel}>{children}</label>
      {message && <div style={styles.fieldError}>{message}</div>}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 900,
    margin: "0 auto",
    padding: "40px 20px 60px",
    color: "#1a1a1a",
  },
  hero: { textAlign: "center", marginBottom: 32 },
  heroTitle: { fontSize: 32, fontWeight: 800, margin: 0 },
  heroSubtitle: { fontSize: 15, color: "#666", marginTop: 8 },
  plansGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: 16,
    marginBottom: 40,
  },
  planCard: {
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    padding: 20,
    background: "#fff",
  },
  planCardSelected: {
    border: "2px solid #1a56c4",
    borderRadius: 12,
    padding: 19,
    background: "#f3f6fd",
  },
  planName: { fontSize: 14, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "#1a56c4" },
  planPrice: { fontSize: 28, fontWeight: 800, marginTop: 8 },
  planPeriod: { fontSize: 14, fontWeight: 500, color: "#777" },
  planTagline: { fontSize: 13, color: "#666", marginTop: 4, marginBottom: 12 },
  planFeatures: { margin: 0, padding: 0, listStyle: "none" },
  planFeature: {
    fontSize: 13,
    color: "#333",
    padding: "6px 0",
    borderTop: "1px solid #f0f0f2",
  },
  planButton: {
    width: "100%",
    marginTop: 14,
    padding: "10px 14px",
    fontSize: 14,
    fontWeight: 600,
    border: "1px solid #1a56c4",
    borderRadius: 8,
    background: "#fff",
    color: "#1a56c4",
    cursor: "pointer",
  },
  formCard: {
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    padding: 28,
    background: "#fff",
  },
  formTitle: { fontSize: 20, fontWeight: 700, margin: "0 0 18px 0" },
  sectionLabel: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: "#1a56c4",
    marginTop: 18,
    marginBottom: 10,
  },
  waiverBox: {
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fafafa",
    padding: "10px 12px",
    maxHeight: 160,
    overflowY: "auto",
    marginBottom: 12,
  },
  waiverHeading: { display: "block", fontSize: 12, marginTop: 8 },
  waiverText: { fontSize: 12, lineHeight: 1.5, color: "#444", margin: "4px 0 0 0" },
  field: { marginBottom: 14 },
  label: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
  checkboxLabel: { display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "#333", cursor: "pointer" },
  checkbox: { marginTop: 2, flexShrink: 0, width: 16, height: 16 },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
  },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  submitButton: {
    width: "100%",
    marginTop: 8,
    padding: "12px 16px",
    fontSize: 15,
    border: "none",
    borderRadius: 8,
    background: "#1a56c4",
    color: "#fff",
    fontWeight: 700,
    cursor: "pointer",
  },
  submitButtonDisabled: {
    width: "100%",
    marginTop: 8,
    padding: "12px 16px",
    fontSize: 15,
    border: "none",
    borderRadius: 8,
    background: "#aab8d6",
    color: "#fff",
    fontWeight: 700,
    cursor: "not-allowed",
  },
  staffLinkRow: { textAlign: "center", marginTop: 24 },
  staffLink: { fontSize: 13, color: "#888" },
  confirmationBox: {
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    padding: "40px 32px",
    background: "#fff",
    textAlign: "center",
    maxWidth: 520,
    margin: "40px auto",
  },
  confirmationEmoji: { fontSize: 40 },
  confirmationTitle: { fontSize: 24, fontWeight: 800, margin: "8px 0" },
  confirmationText: { fontSize: 14, color: "#555", lineHeight: 1.6 },
  confirmationDetails: {
    marginTop: 20,
    borderTop: "1px solid #f0f0f2",
    paddingTop: 16,
    textAlign: "left",
  },
  detailRow: {
    display: "flex",
    justifyContent: "space-between",
    padding: "6px 0",
    fontSize: 13,
  },
  detailLabel: { color: "#888" },
  detailValue: { fontWeight: 600 },
  confirmationFootnote: { fontSize: 12, color: "#999", marginTop: 20 },
};

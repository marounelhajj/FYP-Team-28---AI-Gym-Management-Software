import { useEffect, useState } from "react";
import { signupMember } from "../../api/memberAuth.js";
import { fetchMemberFilterOptions } from "../../api/members.js";
import { fetchBranchPricing } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { getPriceInfo } from "../../utils/pricing.js";
import Logo from "../Logo.jsx";
import WaiverSection, { EMPTY_WAIVER, isWaiverComplete } from "../WaiverSection.jsx";

const EMPTY_FORM = {
  name: "", email: "", phone: "", branch: "", membershipPlan: "", username: "", password: "",
  paymentMethod: "", paymentDuration: "",
  ...EMPTY_WAIVER,
};
const PAYMENT_METHODS = ["Cash", "Card", "Bank Transfer"];
const PAYMENT_DURATIONS = ["1 Month", "1 Year"];

const CYCLE_TEXT = {
  Monthly: "per month",
  Quarterly: "per quarter",
  "Semi-Annual": "every 6 months",
  Annual: "per year",
};

// User story: "As a prospective member, I want to browse membership plans
// and sign up online, so that I can join a branch without visiting in
// person first." A self-signed-up member isn't Active until they pay
// here either - same rule as a receptionist's walk-in registration (see
// backend/members/serializers.py MemberSignupSerializer).
//
// `initialSelection` ({ planName, branch, duration }) comes from PlanBrowser's
// "Join" button so the plan, branch and duration just compared are pre-filled.
//
// Ends with the digital waiver + health disclaimer (SCRUM-83); signing up
// isn't possible until it's signed.
export default function MemberSignupPage({ initialSelection, onSignedUp, onSwitchToLogin, onSwitchToStaff, onBrowsePlans }) {
  const [form, setForm] = useState({
    ...EMPTY_FORM,
    membershipPlan: initialSelection?.planName || "",
    branch: initialSelection?.branch || "",
    paymentDuration: initialSelection?.duration || "",
  });
  const [filterOptions, setFilterOptions] = useState({ branches: [], plans: [] });
  const [quote, setQuote] = useState(null); // pricing row for the chosen plan at the chosen branch
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const priceInfo = getPriceInfo(quote?.effectivePrice, form.paymentDuration);
  const waiverSigned = isWaiverComplete(form, form.name);

  useEffect(() => {
    fetchMemberFilterOptions()
      .then(setFilterOptions)
      .catch(() => {});
  }, []);

  // Show what the chosen plan actually costs at the chosen branch today
  // (organization-wide price minus any running local promotion).
  useEffect(() => {
    setQuote(null);
    if (!form.branch || !form.membershipPlan) return;
    let cancelled = false;
    fetchBranchPricing(form.branch)
      .then((data) => {
        if (!cancelled) setQuote(data.results.find((row) => row.name === form.membershipPlan) || null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [form.branch, form.membershipPlan]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    try {
      const member = await signupMember(form);
      onSignedUp(member);
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

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logoWrap}>
          <Logo size={44} />
        </div>

        <h1 style={styles.title}>Join Fitness Factory</h1>
        <p style={styles.subtitle}>
          Pick a branch and plan, and you're in.{" "}
          <button type="button" onClick={onBrowsePlans} style={styles.linkButton}>
            Compare plans
          </button>
        </p>

        <form onSubmit={handleSubmit}>
          <Field label="Full name" error={fieldErrors.name}>
            <input
              type="text"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              style={styles.input}
              autoFocus
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
            <select value={form.branch} onChange={(e) => update("branch", e.target.value)} style={styles.input}>
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

          {quote && (
            <div style={styles.quote}>
              <div>
                {quote.promotion && <s style={styles.quoteOld}>${quote.basePrice}</s>}{" "}
                <strong>${quote.effectivePrice}</strong> {CYCLE_TEXT[quote.billingCycle] || ""} at {form.branch}
              </div>
              {quote.promotion && (
                <div style={styles.quotePromo}>
                  {quote.promotion.name} offer, until {quote.promotion.endDate}
                </div>
              )}
            </div>
          )}

          <Field label="Username" error={fieldErrors.username}>
            <input
              type="text"
              value={form.username}
              onChange={(e) => update("username", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Password" error={fieldErrors.password}>
            <input
              type="password"
              value={form.password}
              onChange={(e) => update("password", e.target.value)}
              style={styles.input}
            />
          </Field>

          <Field label="Payment method" error={fieldErrors.paymentMethod}>
            <select
              value={form.paymentMethod}
              onChange={(e) => update("paymentMethod", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a payment method...</option>
              {PAYMENT_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Subscription duration" error={fieldErrors.paymentDuration}>
            <select
              value={form.paymentDuration}
              onChange={(e) => update("paymentDuration", e.target.value)}
              style={styles.input}
            >
              <option value="">Select a duration...</option>
              {PAYMENT_DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </Field>

          {priceInfo && (
            <Field label="Price">
              {priceInfo.hasPromo && (
                <div style={styles.oldPriceRow}>
                  <span style={styles.oldPriceTag}>Old price</span>
                  <span style={styles.oldPriceAmount}>${priceInfo.originalAmount}</span>
                </div>
              )}
              <div style={styles.priceDisplay}>${priceInfo.amount}</div>
            </Field>
          )}

          <WaiverSection
            values={form}
            onChange={update}
            errors={fieldErrors}
            signerName={form.name}
            hint="Please read before your first session."
          />

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <button
            type="submit"
            disabled={submitting || !waiverSigned}
            style={{ ...styles.submitButton, ...(waiverSigned ? null : styles.submitDisabled) }}
          >
            {submitting ? "Creating account..." : waiverSigned ? "Sign waiver & join" : "Sign the waiver to join"}
          </button>
        </form>

        <p style={styles.switchLine}>
          Already have an account?{" "}
          <button type="button" onClick={onSwitchToLogin} style={styles.linkButton}>
            Login
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
    maxWidth: 380,
    maxHeight: "92vh",
    overflowY: "auto",
    boxShadow: "0 10px 40px rgba(0,0,0,0.06)",
  },
  logoWrap: { display: "flex", justifyContent: "center", marginBottom: 20 },
  title: { fontSize: 20, fontWeight: 700, margin: "0 0 6px", textAlign: "center", color: "#1a1a1a" },
  subtitle: { fontSize: 13, color: "#666", textAlign: "center", margin: "0 0 24px" },
  field: { marginBottom: 14 },
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
    boxSizing: "border-box",
  },
  priceDisplay: {
    padding: "10px 12px",
    fontSize: 20,
    fontWeight: 800,
    border: "1px solid #e4e4e8",
    borderRadius: 8,
    background: "#f5f5f7",
    color: "#1a1a1a",
  },
  oldPriceRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
  },
  oldPriceTag: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: "#999",
  },
  oldPriceAmount: {
    fontSize: 13,
    color: "#999",
    textDecoration: "line-through",
  },
  fieldError: {
    color: "#b3261e",
    fontSize: 12,
    marginTop: 4,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 16,
  },
  quote: {
    background: "#eef7f0",
    color: "#1d5e2f",
    padding: "10px 12px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  quoteOld: { color: "#888", fontWeight: 400 },
  quotePromo: { fontSize: 12, marginTop: 2 },
  submitButton: {
    width: "100%",
    padding: "11px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    marginTop: 4,
  },
  submitDisabled: { opacity: 0.5, cursor: "not-allowed" },
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

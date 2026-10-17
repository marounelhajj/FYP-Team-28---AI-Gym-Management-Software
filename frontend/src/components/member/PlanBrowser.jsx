import { useEffect, useState } from "react";
import { fetchBranchPricing, fetchPlanMeta, fetchPlans } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { getPriceInfo } from "../../utils/pricing.js";
import Logo from "../Logo.jsx";
import SegmentedControl from "../SegmentedControl.jsx";

const CYCLE_MONTHS = { Monthly: 1, Quarterly: 3, "Semi-Annual": 6, Annual: 12 };
const DURATION_OPTIONS = [
  { value: "1 Month", label: "1 Month" },
  { value: "1 Year", label: "1 Year", tag: "Save $20" },
];

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

// The monthly price every duration is priced from, branch promotion
// included - mirrors billing/models.py _monthly_price.
function monthlyPrice(plan, local) {
  const cyclePrice = Number(local ? local.effectivePrice : plan.price);
  return Math.round((cyclePrice / (CYCLE_MONTHS[plan.billingCycle] || 1)) * 100) / 100;
}

// Public, no-login plan catalogue - the "browse" half of the story.
//
// User story (SCRUM-66): "As a prospective member, I want to browse
// membership plans and sign up online, so that I can join a branch without
// visiting in person first."
//
// Shows the plans the General Manager currently sells (SCRUM-49). Picking a
// branch swaps in that branch's actual price today, including any running
// local promotion. "Join" hands the chosen plan + branch to the signup form.
export default function PlanBrowser({ initialBranch, onChoosePlan, onSwitchToLogin, onSwitchToStaff }) {
  const [plans, setPlans] = useState([]);
  const [branches, setBranches] = useState([]);
  const [branch, setBranch] = useState(initialBranch || "");
  const [duration, setDuration] = useState("1 Month");
  const [pricing, setPricing] = useState({}); // planId -> pricing row for the selected branch
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([fetchPlans({ isActive: "true" }), fetchPlanMeta()])
      .then(([planData, meta]) => {
        setPlans(planData.results);
        setBranches(meta.branches);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!branch) {
      setPricing({});
      return;
    }
    fetchBranchPricing(branch)
      .then((data) => setPricing(Object.fromEntries(data.results.map((row) => [row.planId, row]))))
      .catch(() => setPricing({}));
  }, [branch]);

  return (
    <div style={styles.page}>
      <div style={styles.topBar}>
        <Logo size={34} />
        <div style={styles.topLinks}>
          <button type="button" onClick={onSwitchToLogin} style={styles.linkButton}>
            Member login
          </button>
          <button type="button" onClick={onSwitchToStaff} style={styles.linkButtonMuted}>
            Staff
          </button>
        </div>
      </div>

      <div style={styles.content}>
        <h1 style={styles.title}>Choose your membership</h1>
        <p style={styles.subtitle}>
          Same plans at every Fitness Factory branch. Pick your branch to see today's price, including any local offers.
          Pay monthly, or for a whole year at once and save $20.
        </p>

        <div style={styles.branchRow} role="group" aria-label="Branch">
          <button type="button" onClick={() => setBranch("")} style={branch === "" ? styles.pillActive : styles.pill}>
            Any branch
          </button>
          {branches.map((b) => (
            <button key={b} type="button" onClick={() => setBranch(b)} style={branch === b ? styles.pillActive : styles.pill}>
              {b}
            </button>
          ))}
        </div>

        <div style={styles.durationRow}>
          <SegmentedControl
            options={DURATION_OPTIONS}
            value={duration}
            onChange={setDuration}
            ariaLabel="Subscription duration"
          />
        </div>

        {loading && <div style={styles.meta}>Loading plans...</div>}
        {error && <div style={styles.errorBox}>Couldn't load plans: {error}</div>}
        {!loading && !error && plans.length === 0 && (
          <div style={styles.meta}>No plans are on offer right now. Please check back soon.</div>
        )}

        <div style={styles.grid}>
          {plans.map((plan) => {
            const local = pricing[plan.id];
            const promo = local?.promotion;
            const yearly = duration === "1 Year";
            const price = getPriceInfo(monthlyPrice(plan, local), duration);
            return (
              <div key={plan.id} style={promo ? styles.cardPromo : styles.card}>
                {promo && <div style={styles.promoBanner}>{promo.name}: until {promo.endDate}</div>}

                <h2 style={styles.cardTitle}>{plan.name}</h2>
                {plan.description && <p style={styles.cardDescription}>{plan.description}</p>}

                <div style={styles.priceRow}>
                  {yearly ? (
                    <s style={styles.oldPrice}>{money(price.originalAmount)}</s>
                  ) : (
                    promo && <s style={styles.oldPrice}>{money(local.basePrice)}</s>
                  )}
                  <span style={styles.price}>{money(price.amount)}</span>
                  <span style={styles.priceSuffix}>{yearly ? "/ year" : "/ month"}</span>
                </div>
                {yearly && <div style={styles.monthly}>Paid once a year, about {money(price.amount / 12)} / month</div>}

                {plan.features.length > 0 && (
                  <ul style={styles.featureList}>
                    {plan.features.map((f) => (
                      <li key={f} style={styles.feature}>
                        {f}
                      </li>
                    ))}
                  </ul>
                )}

                <button
                  type="button"
                  onClick={() => onChoosePlan({ planName: plan.name, branch, duration })}
                  style={styles.joinButton}
                >
                  Join with {plan.name} for {duration.toLowerCase()}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const pill = {
  padding: "8px 14px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 999,
  cursor: "pointer",
};

const card = {
  display: "flex",
  flexDirection: "column",
  background: "#fff",
  borderRadius: 12,
  padding: 20,
  position: "relative",
};

const styles = {
  page: {
    minHeight: "100vh",
    background: "#f5f5f7",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
  },
  topBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "10px 20px",
    background: "#fff",
    borderBottom: "1px solid #e4e4e8",
  },
  topLinks: { display: "flex", alignItems: "center", gap: 16 },
  linkButton: {
    border: "none",
    background: "none",
    color: "#124096",
    fontWeight: 600,
    fontSize: 14,
    cursor: "pointer",
    padding: 0,
  },
  linkButtonMuted: {
    border: "none",
    background: "none",
    color: "#888",
    fontWeight: 600,
    fontSize: 13,
    cursor: "pointer",
    padding: 0,
  },
  content: { maxWidth: 1000, margin: "0 auto", padding: "32px 20px 48px" },
  title: { fontSize: 26, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "6px 0 20px", maxWidth: 560 },
  branchRow: { display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 },
  durationRow: { maxWidth: 320, marginBottom: 24 },
  pill: { ...pill, border: "1px solid #d0d0d5", background: "#fff", color: "#444" },
  pillActive: { ...pill, border: "1px solid #124096", background: "#124096", color: "#fff" },
  meta: { fontSize: 14, color: "#666", padding: "12px 0" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
    gap: 22,
    paddingTop: 12,
  },
  card: { ...card, border: "1px solid #e4e4e8" },
  cardPromo: { ...card, border: "2px solid #129638", padding: 19 },
  promoBanner: {
    position: "absolute",
    top: -12,
    left: 16,
    maxWidth: "calc(100% - 32px)",
    background: "#129638",
    color: "#fff",
    fontSize: 12,
    fontWeight: 700,
    padding: "4px 10px",
    borderRadius: 999,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  cardTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  cardDescription: { fontSize: 13, color: "#666", margin: "6px 0 0" },
  priceRow: { display: "flex", alignItems: "baseline", flexWrap: "wrap", gap: 6, marginTop: 14 },
  oldPrice: { fontSize: 15, color: "#999" },
  price: { fontSize: 30, fontWeight: 800 },
  priceSuffix: { fontSize: 13, color: "#666" },
  monthly: { fontSize: 12, color: "#888", marginTop: 2 },
  featureList: { margin: "14px 0 0", paddingLeft: 18, flex: 1 },
  feature: { fontSize: 13, color: "#333", marginBottom: 4 },
  joinButton: {
    marginTop: 18,
    padding: "11px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
};

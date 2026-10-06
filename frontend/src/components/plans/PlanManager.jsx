import { useEffect, useState } from "react";
import { fetchPlans, fetchPlanMeta, updatePlan } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import PlanForm from "./PlanForm.jsx";

const CYCLE_SUFFIX = {
  Monthly: "/ month",
  Quarterly: "/ quarter",
  "Semi-Annual": "/ 6 months",
  Annual: "/ year",
};

function formatPrice(value) {
  return `$${Number(value).toFixed(2)}`;
}

// General Manager persona screen.
//
// User story: "As a general manager, I want to set organization-wide
// membership plans and pricing tiers, so that pricing stays consistent
// across branches while still allowing local promotions."
//
// Plans have no branch - every plan shown here is what every branch sells.
export default function PlanManager() {
  const [plans, setPlans] = useState([]);
  const [billingCycles, setBillingCycles] = useState([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or a plan object

  function loadPlans() {
    setLoading(true);
    setError(null);
    fetchPlans()
      .then((data) => setPlans(data.results))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadPlans();
    fetchPlanMeta()
      .then((meta) => setBillingCycles(meta.billingCycles))
      .catch(() => {});
  }, []);

  function handleSaved() {
    setFormTarget(null);
    loadPlans();
  }

  async function toggleArchived(plan) {
    setActionError(null);
    try {
      await updatePlan(plan.id, { isActive: !plan.isActive });
      loadPlans();
    } catch (err) {
      setActionError(err.message);
    }
  }

  const activePlans = plans.filter((p) => p.isActive);
  const archivedPlans = plans.filter((p) => !p.isActive);
  const visiblePlans = showArchived ? archivedPlans : activePlans;

  return (
    <div style={styles.page}>
      <div style={styles.banner}>
        <span style={styles.gmTag}>GM</span>
        <div>
          <h1 style={styles.bannerTitle}>Membership Plans & Pricing</h1>
          <p style={styles.bannerSubtitle}>
            Organization-wide tiers. Base prices apply to every branch; branches can only discount within your caps.
          </p>
        </div>
      </div>

      <div style={styles.header}>
        <div style={styles.toggleGroup}>
          <button onClick={() => setShowArchived(false)} style={!showArchived ? styles.toggleActive : styles.toggle}>
            Active ({activePlans.length})
          </button>
          <button onClick={() => setShowArchived(true)} style={showArchived ? styles.toggleActive : styles.toggle}>
            Archived ({archivedPlans.length})
          </button>
        </div>
        <button onClick={() => setFormTarget("new")} style={styles.newButton}>
          + New Plan
        </button>
      </div>

      {loading && <div style={styles.meta}>Loading plans...</div>}
      {error && <div style={styles.errorBox}>Couldn't load plans: {error}</div>}
      {actionError && <div style={styles.errorBox}>{actionError}</div>}

      {!loading && !error && visiblePlans.length === 0 && (
        <div style={styles.empty}>
          {showArchived ? "No archived plans." : "No active plans yet. Create the first tier to start selling memberships."}
        </div>
      )}

      {!loading && !error && visiblePlans.length > 0 && (
        <div style={styles.grid}>
          {visiblePlans.map((plan) => (
            <div key={plan.id} style={plan.isActive ? styles.card : styles.cardArchived}>
              <div style={styles.cardHeader}>
                <h3 style={styles.cardTitle}>{plan.name}</h3>
                <span style={styles.cycleBadge}>{plan.billingCycle}</span>
              </div>

              <div style={styles.priceRow}>
                <span style={styles.price}>{formatPrice(plan.price)}</span>
                <span style={styles.priceSuffix}>{CYCLE_SUFFIX[plan.billingCycle] || ""}</span>
              </div>
              {plan.billingCycle !== "Monthly" && (
                <div style={styles.monthly}>≈ {formatPrice(plan.monthlyEquivalent)} / month</div>
              )}

              {plan.description && <p style={styles.cardDescription}>{plan.description}</p>}

              <div style={styles.capRow}>
                {Number(plan.maxPromoDiscountPercent) > 0
                  ? `Branch promos: up to ${Number(plan.maxPromoDiscountPercent)}% off`
                  : "Branch promos: not allowed"}
              </div>

              {plan.features.length > 0 && (
                <ul style={styles.featureList}>
                  {plan.features.map((f) => (
                    <li key={f} style={styles.feature}>
                      {f}
                    </li>
                  ))}
                </ul>
              )}

              <div style={styles.cardFooter}>
                <span style={styles.updated}>Updated {plan.updatedAt}</span>
                <div style={styles.cardActions}>
                  <button onClick={() => toggleArchived(plan)} style={styles.secondaryButton}>
                    {plan.isActive ? "Archive" : "Restore"}
                  </button>
                  <button onClick={() => setFormTarget(plan)} style={styles.secondaryButton}>
                    Edit
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {formTarget && (
        <PlanForm
          plan={formTarget === "new" ? null : formTarget}
          billingCycles={billingCycles}
          onClose={() => setFormTarget(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1000,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  banner: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    background: "#0f2a5c",
    color: "#fff",
    padding: "20px 24px",
    borderRadius: 10,
    marginBottom: 20,
  },
  gmTag: {
    flexShrink: 0,
    background: "#129638",
    color: "#fff",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 1,
    padding: "4px 10px",
    borderRadius: 6,
  },
  bannerTitle: { fontSize: 20, fontWeight: 700, margin: 0 },
  bannerSubtitle: { fontSize: 13, color: "#c6d2ea", margin: "4px 0 0" },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 12,
    marginBottom: 20,
  },
  toggleGroup: { display: "flex", gap: 6 },
  toggle: {
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 999,
    background: "#fff",
    color: "#555",
    cursor: "pointer",
  },
  toggleActive: {
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #124096",
    borderRadius: 999,
    background: "#eef1f8",
    color: "#124096",
    cursor: "pointer",
  },
  newButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  meta: { fontSize: 13, color: "#666" },
  empty: { fontSize: 14, color: "#888", padding: "24px 0" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
    gap: 14,
  },
  card: {
    display: "flex",
    flexDirection: "column",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    padding: 16,
    background: "#fff",
  },
  cardArchived: {
    display: "flex",
    flexDirection: "column",
    border: "1px dashed #d0d0d5",
    borderRadius: 10,
    padding: 16,
    background: "#fafafa",
    opacity: 0.8,
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  cardTitle: { fontSize: 16, fontWeight: 700, margin: 0 },
  cycleBadge: {
    flexShrink: 0,
    fontSize: 11,
    fontWeight: 600,
    padding: "3px 9px",
    borderRadius: 999,
    background: "#eef1f8",
    color: "#124096",
  },
  priceRow: { display: "flex", alignItems: "baseline", gap: 6, marginTop: 12 },
  price: { fontSize: 28, fontWeight: 800, color: "#1a1a1a" },
  priceSuffix: { fontSize: 13, color: "#666" },
  monthly: { fontSize: 12, color: "#888", marginTop: 2 },
  cardDescription: { fontSize: 13, color: "#666", margin: "10px 0 0" },
  capRow: {
    fontSize: 12,
    fontWeight: 600,
    color: "#8a5a00",
    background: "#fff6e0",
    borderRadius: 6,
    padding: "4px 8px",
    marginTop: 10,
    alignSelf: "flex-start",
  },
  featureList: { margin: "10px 0 0", paddingLeft: 18 },
  feature: { fontSize: 13, color: "#333", marginBottom: 3 },
  cardFooter: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
    marginTop: "auto",
    paddingTop: 14,
  },
  updated: { fontSize: 12, color: "#999" },
  cardActions: { display: "flex", gap: 6 },
  secondaryButton: {
    padding: "5px 10px",
    fontSize: 12,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

import { useEffect, useState } from "react";
import { fetchBranchPricing, fetchPlanMeta, fetchPlans, fetchPromotions, updatePromotion } from "../../api/plans.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import PromotionForm from "./PromotionForm.jsx";

const STATUS_COLORS = {
  Running: { background: "#e3f5e8", color: "#129638" },
  Scheduled: { background: "#eef1f8", color: "#124096" },
  Expired: { background: "#f0f0f3", color: "#777" },
  Cancelled: { background: "#fdeceb", color: "#b3261e" },
};

function describeDiscount(promo) {
  return promo.discountType === "Percent"
    ? `${Number(promo.discountValue)}% off`
    : `$${Number(promo.discountValue).toFixed(2)} off`;
}

// Branch-level promotions screen, used by Branch Managers and General
// Managers.
//
// User story: "As a general manager, I want to set organization-wide
// membership plans and pricing tiers, so that pricing stays consistent
// across branches while still allowing local promotions."
//
// Branches can only discount an organization-wide plan, within the cap the
// General Manager set on that plan - so prices drift locally but never
// beyond what the organization allows.
export default function PromotionManager() {
  const [promotions, setPromotions] = useState([]);
  const [plans, setPlans] = useState([]);
  const [meta, setMeta] = useState({ branches: [], discountTypes: [] });
  const [branch, setBranch] = useState("");
  const [pricing, setPricing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or a promotion object

  function loadPromotions() {
    setLoading(true);
    setError(null);
    fetchPromotions({ branch })
      .then((data) => setPromotions(data.results))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));

    if (branch) {
      fetchBranchPricing(branch)
        .then(setPricing)
        .catch(() => setPricing(null));
    } else {
      setPricing(null);
    }
  }

  useEffect(() => {
    fetchPlanMeta()
      .then(setMeta)
      .catch(() => {});
    fetchPlans({ isActive: "true" })
      .then((data) => setPlans(data.results))
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadPromotions();
  }, [branch]);

  function handleSaved() {
    setFormTarget(null);
    loadPromotions();
  }

  async function cancelPromotion(promo) {
    setActionError(null);
    try {
      await updatePromotion(promo.id, { isActive: false });
      loadPromotions();
    } catch (err) {
      setActionError(err.message);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Branch Promotions</h1>
          <p style={styles.subtitle}>
            Run local deals on organization-wide plans. Discounts are capped per plan by the general manager.
          </p>
        </div>
        <button
          onClick={() => setFormTarget("new")}
          style={styles.newButton}
          disabled={plans.length === 0}
          title={plans.length === 0 ? "No active plans to promote yet" : undefined}
        >
          + New Promotion
        </button>
      </div>

      <div style={styles.filterRow}>
        <label style={styles.filterLabel}>
          Branch
          <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.select}>
            <option value="">All branches</option>
            {meta.branches.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
      </div>

      {pricing && (
        <div style={styles.pricingStrip}>
          <div style={styles.pricingTitle}>Today's prices at {pricing.branch}</div>
          <div style={styles.pricingGrid}>
            {pricing.results.map((p) => (
              <div key={p.planId} style={styles.pricingItem}>
                <div style={styles.pricingName}>{p.name}</div>
                <div>
                  {p.promotion && <s style={styles.basePrice}>${p.basePrice}</s>}{" "}
                  <strong style={p.promotion ? styles.promoPrice : undefined}>${p.effectivePrice}</strong>
                </div>
                {p.promotion && <div style={styles.pricingPromo}>{p.promotion.name}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && <div style={styles.meta}>Loading promotions...</div>}
      {error && <div style={styles.errorBox}>Couldn't load promotions: {error}</div>}
      {actionError && <div style={styles.errorBox}>{actionError}</div>}

      {!loading && !error && promotions.length === 0 && (
        <div style={styles.empty}>No promotions{branch ? ` at ${branch}` : ""} yet.</div>
      )}

      {!loading && !error && promotions.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Promotion</th>
                <th style={styles.th}>Plan</th>
                <th style={styles.th}>Branch</th>
                <th style={styles.th}>Discount</th>
                <th style={styles.th}>Price</th>
                <th style={styles.th}>Dates</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {promotions.map((promo) => {
                const editable = promo.status === "Running" || promo.status === "Scheduled";
                return (
                  <tr key={promo.id}>
                    <td style={styles.td}>
                      <div style={styles.promoName}>{promo.name}</div>
                      {promo.createdBy && <div style={styles.createdBy}>by {promo.createdBy}</div>}
                    </td>
                    <td style={styles.td}>{promo.planName}</td>
                    <td style={styles.td}>{promo.branch}</td>
                    <td style={styles.td}>{describeDiscount(promo)}</td>
                    <td style={styles.td}>
                      <s style={styles.basePrice}>${promo.basePrice}</s> <strong>${promo.effectivePrice}</strong>
                    </td>
                    <td style={styles.td}>
                      {promo.startDate} → {promo.endDate}
                    </td>
                    <td style={styles.td}>
                      <span style={{ ...styles.badge, ...STATUS_COLORS[promo.status] }}>{promo.status}</span>
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      {editable && (
                        <>
                          <button onClick={() => setFormTarget(promo)} style={styles.secondaryButton}>
                            Edit
                          </button>{" "}
                          <button onClick={() => cancelPromotion(promo)} style={styles.secondaryButton}>
                            Cancel
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {formTarget && (
        <PromotionForm
          promotion={formTarget === "new" ? null : formTarget}
          plans={plans}
          branches={meta.branches}
          discountTypes={meta.discountTypes}
          defaultBranch={branch}
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
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: 16,
    marginBottom: 16,
  },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
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
  filterRow: { display: "flex", gap: 12, marginBottom: 16 },
  filterLabel: { display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#444" },
  select: {
    padding: "8px 10px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
  },
  pricingStrip: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    padding: 14,
    marginBottom: 16,
  },
  pricingTitle: { fontSize: 13, fontWeight: 700, color: "#444", marginBottom: 10 },
  pricingGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
    gap: 10,
  },
  pricingItem: { fontSize: 14 },
  pricingName: { fontSize: 12, color: "#666", marginBottom: 2 },
  pricingPromo: { fontSize: 11, color: "#129638", fontWeight: 600, marginTop: 2 },
  promoPrice: { color: "#129638" },
  basePrice: { color: "#999", fontWeight: 400 },
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
  tableWrap: {
    overflowX: "auto",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "top" },
  promoName: { fontWeight: 600 },
  createdBy: { fontSize: 12, color: "#999", marginTop: 2 },
  badge: {
    fontSize: 12,
    fontWeight: 600,
    padding: "3px 9px",
    borderRadius: 999,
    whiteSpace: "nowrap",
  },
  secondaryButton: {
    padding: "5px 10px",
    fontSize: 12,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

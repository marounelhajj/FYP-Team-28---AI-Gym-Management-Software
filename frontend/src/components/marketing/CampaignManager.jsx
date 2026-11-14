import { useEffect, useState } from "react";
import { fetchCampaigns, fetchMarketingMeta, updateCampaign } from "../../api/marketing.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import CampaignForm from "./CampaignForm.jsx";

const STATUS_COLORS = {
  Running: { background: "#e3f5e8", color: "#129638" },
  Scheduled: { background: "#eef1f8", color: "#124096" },
  Expired: { background: "#f0f0f3", color: "#777" },
  Cancelled: { background: "#fdeceb", color: "#b3261e" },
};

// Marketing Staff's own screen for running campaigns branch by branch.
// Gated on manage_marketing_campaigns. A General Manager doesn't manage
// campaigns here - they compare them across branches on the separate
// "Campaigns by Branch" report (see CampaignsByBranch.jsx).
export default function CampaignManager() {
  const [campaigns, setCampaigns] = useState([]);
  const [meta, setMeta] = useState({ branches: [] });
  const [branch, setBranch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or a campaign object

  function load() {
    setLoading(true);
    setError(null);
    fetchCampaigns({ branch })
      .then((data) => setCampaigns(data.results))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchMarketingMeta().then(setMeta).catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [branch]);

  function handleSaved() {
    setFormTarget(null);
    load();
  }

  async function cancelCampaign(campaign) {
    setActionError(null);
    try {
      await updateCampaign(campaign.id, { isActive: false });
      load();
    } catch (err) {
      setActionError(err.message);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Marketing Campaigns</h1>
          <p style={styles.subtitle}>What's running at each branch, its strategy, and its budget vs. spend.</p>
        </div>
        <button onClick={() => setFormTarget("new")} style={styles.newButton} disabled={meta.branches.length === 0}>
          + New Campaign
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

      {loading && <div style={styles.meta}>Loading campaigns...</div>}
      {error && <div style={styles.errorBox}>Couldn't load campaigns: {error}</div>}
      {actionError && <div style={styles.errorBox}>{actionError}</div>}

      {!loading && !error && campaigns.length === 0 && (
        <div style={styles.empty}>No campaigns{branch ? ` at ${branch}` : ""} yet.</div>
      )}

      {!loading && !error && campaigns.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Campaign</th>
                <th style={styles.th}>Branch</th>
                <th style={styles.th}>Budget</th>
                <th style={styles.th}>Spent</th>
                <th style={styles.th}>Dates</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const editable = c.status === "Running" || c.status === "Scheduled";
                const overBudget = Number(c.amountSpent) > Number(c.budget);
                return (
                  <tr key={c.id}>
                    <td style={styles.td}>
                      <div style={styles.campaignName}>{c.name}</div>
                      {c.strategy && <div style={styles.strategy}>{c.strategy}</div>}
                      {c.createdBy && <div style={styles.createdBy}>by {c.createdBy}</div>}
                    </td>
                    <td style={styles.td}>{c.branch}</td>
                    <td style={styles.td}>${c.budget}</td>
                    <td style={{ ...styles.td, color: overBudget ? "#b3261e" : undefined, fontWeight: overBudget ? 700 : 400 }}>
                      ${c.amountSpent}
                    </td>
                    <td style={styles.td}>
                      {c.startDate} → {c.endDate}
                    </td>
                    <td style={styles.td}>
                      <span style={{ ...styles.badge, ...STATUS_COLORS[c.status] }}>{c.status}</span>
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      {editable && (
                        <>
                          <button onClick={() => setFormTarget(c)} style={styles.secondaryButton}>
                            Edit
                          </button>{" "}
                          <button onClick={() => cancelCampaign(c)} style={styles.secondaryButton}>
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
        <CampaignForm
          campaign={formTarget === "new" ? null : formTarget}
          branches={meta.branches}
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
    maxWidth: 1050,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16, marginBottom: 16 },
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
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff" },
  meta: { fontSize: 13, color: "#666" },
  empty: { fontSize: 14, color: "#888", padding: "24px 0" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 880, borderCollapse: "collapse", fontSize: 14 },
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
  campaignName: { fontWeight: 600 },
  strategy: { fontSize: 12, color: "#777", marginTop: 2, maxWidth: 280 },
  createdBy: { fontSize: 12, color: "#999", marginTop: 2 },
  badge: { fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" },
  secondaryButton: {
    padding: "5px 10px",
    fontSize: 12,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

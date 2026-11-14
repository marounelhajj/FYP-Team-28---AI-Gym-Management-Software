import { useEffect, useState } from "react";
import { fetchCampaignReport } from "../../api/marketing.js";

const BRANCHES = ["Hamra", "Achrafieh", "Jnah", "Zalka"];

const STATUS_COLORS = {
  Running: { background: "#e3f5e8", color: "#129638" },
  Scheduled: { background: "#eef1f8", color: "#124096" },
  Expired: { background: "#f0f0f3", color: "#777" },
  Cancelled: { background: "#fdeceb", color: "#b3261e" },
};

// A branch's spend against its budget, so a branch running over (or well
// under) what was approved is visible at a glance - same idea as
// finance/FinancialReport.jsx's CompareBar.
function SpendBar({ spent, budget }) {
  const ratio = Number(budget) === 0 ? 0 : Number(spent) / Number(budget);
  const width = Math.max(2, Math.min(100, Math.round(ratio * 100)));
  const color = ratio > 1 ? "#b3261e" : ratio > 0.85 ? "#e8a400" : "#129638";
  return (
    <div style={styles.barTrack}>
      <div style={{ ...styles.barFill, width: `${width}%`, background: color }} />
    </div>
  );
}

function CampaignRow({ campaign }) {
  return (
    <div style={styles.campaignRow}>
      <div style={styles.campaignHead}>
        <span style={styles.campaignName}>{campaign.name}</span>
        <span style={{ ...styles.badge, ...STATUS_COLORS[campaign.status] }}>{campaign.status}</span>
      </div>
      {campaign.strategy && <p style={styles.strategy}>{campaign.strategy}</p>}
      <div style={styles.campaignMeta}>
        <span>
          ${campaign.amountSpent} spent of ${campaign.budget}
        </span>
        <span>
          {campaign.startDate} → {campaign.endDate}
        </span>
      </div>
      <SpendBar spent={campaign.amountSpent} budget={campaign.budget} />
    </div>
  );
}

function BranchCard({ branch }) {
  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h2 style={styles.branchName}>{branch.branch}</h2>
        <div style={styles.cardTotals}>
          ${branch.spent} spent of ${branch.budget}
          <span style={styles.campaignCount}>
            {branch.campaignCount} campaign{branch.campaignCount === 1 ? "" : "s"}
          </span>
        </div>
      </div>
      {branch.campaigns.length === 0 ? (
        <p style={styles.noCampaigns}>No campaigns at this branch.</p>
      ) : (
        <div style={styles.campaignList}>
          {branch.campaigns.map((c) => (
            <CampaignRow key={c.id} campaign={c} />
          ))}
        </div>
      )}
    </div>
  );
}

// General Manager's cross-branch read of what Marketing Staff is running
// where (marketing.models.MarketingCampaign, via marketing.views.campaign_report) -
// each branch's campaigns with their strategy and budget vs. spend, so a
// branch's direction (or overspend) doesn't hide in an org-wide number.
//
// User story: "As a general manager, I want to view the marketing
// campaigns and strategies being run at each branch, so that I can assess
// alignment with overall brand direction and spending."
export default function CampaignsByBranch() {
  const [branch, setBranch] = useState("");
  const [data, setData] = useState({ branches: [], totals: { budget: "0.00", spent: "0.00" } });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchCampaignReport(branch || undefined)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [branch]);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>Marketing Campaigns by Branch</h1>
        <p style={styles.subtitle}>
          What's running at each branch, its strategy, and its budget vs. spending so far - to check alignment with
          brand direction without chasing Marketing Staff branch by branch.
        </p>
      </div>

      <div style={styles.filters}>
        <label style={styles.field}>
          <span style={styles.fieldLabel}>Branch</span>
          <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.input}>
            <option value="">All branches</option>
            {BRANCHES.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
        {!loading && !error && (
          <div style={styles.totals}>
            ${data.totals.spent} spent of ${data.totals.budget} total budget
          </div>
        )}
      </div>

      {error && <div style={styles.errorBox}>Couldn't load the report: {error}</div>}
      {loading && <div style={styles.empty}>Loading...</div>}

      {!loading && !error && (
        <div style={styles.cards}>
          {data.branches.map((b) => (
            <BranchCard key={b.branch} branch={b} />
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1100,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4, maxWidth: 760, lineHeight: 1.5 },
  filters: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: 14,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 16,
  },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "0 1 220px", minWidth: 0 },
  fieldLabel: { fontSize: 12, fontWeight: 600, color: "#444" },
  input: {
    padding: "8px 10px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    width: "100%",
    boxSizing: "border-box",
  },
  totals: { fontSize: 14, fontWeight: 600, color: "#444" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  cards: { display: "flex", flexDirection: "column", gap: 16 },
  card: { border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", padding: 16 },
  cardHeader: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 12,
  },
  branchName: { fontSize: 17, fontWeight: 700, margin: 0 },
  cardTotals: { display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#555" },
  campaignCount: { color: "#999" },
  noCampaigns: { fontSize: 13, color: "#999", margin: 0 },
  campaignList: { display: "flex", flexDirection: "column", gap: 12 },
  campaignRow: { padding: "10px 12px", border: "1px solid #eee", borderRadius: 8, background: "#fafafb" },
  campaignHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 },
  campaignName: { fontWeight: 600, fontSize: 14 },
  strategy: { fontSize: 13, color: "#555", margin: "6px 0 0", lineHeight: 1.4 },
  campaignMeta: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 12,
    color: "#777",
    marginTop: 8,
    marginBottom: 4,
  },
  barTrack: { height: 6, borderRadius: 999, background: "#eef1f8", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999 },
  badge: { fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, whiteSpace: "nowrap" },
};

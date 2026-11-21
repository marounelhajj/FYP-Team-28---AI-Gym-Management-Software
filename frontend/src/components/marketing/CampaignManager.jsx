import { useEffect, useState } from "react";
import { fetchCampaigns, fetchMarketingMeta, updateCampaign } from "../../api/marketing.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import CampaignForm from "./CampaignForm.jsx";
import CampaignResults from "./CampaignResults.jsx";

const STATUS_COLORS = {
  Running: { background: "#e3f5e8", color: "#129638" },
  Scheduled: { background: "#eef1f8", color: "#124096" },
  Expired: { background: "#f0f0f3", color: "#777" },
  Cancelled: { background: "#fdeceb", color: "#b3261e" },
};
const USE_SHORT = { Membership: "renewals", Shop: "shop", Both: "renewals & shop" };

function formatDay(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

// Marketing Staff's own screen for running campaigns branch by branch.
// Gated on manage_marketing_campaigns. A General Manager doesn't manage
// campaigns here - they compare them across branches on the separate
// "Campaigns by Branch" report (see CampaignsByBranch.jsx).
//
// User story: "As a marketing staff member, I want to create and schedule
// promotional campaigns with a target segment and offer code, so that I can
// launch promotions without needing developer help." Each row shows the
// offer, who it's for, whether it's gone out, and how it's doing.
export default function CampaignManager() {
  const [campaigns, setCampaigns] = useState([]);
  const [meta, setMeta] = useState(null);
  const [branch, setBranch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or a campaign object
  const [cancelTarget, setCancelTarget] = useState(null);
  const [resultsId, setResultsId] = useState(null);

  function load() {
    setLoading(true);
    setError(null);
    fetchCampaigns({ branch })
      .then((data) => setCampaigns(data.results))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchMarketingMeta().then(setMeta).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [branch]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 8000);
    return () => clearTimeout(t);
  }, [notice]);

  function handleSaved(saved, wasEditing) {
    setFormTarget(null);
    if (wasEditing) setNotice(`${saved.name} saved.`);
    else if (!saved.offerCode) setNotice(`${saved.name} added.`);
    else {
      const who = saved.audience ? `${saved.audience.reachable} member${saved.audience.reachable === 1 ? "" : "s"}` : "its audience";
      const when = saved.status === "Running" ? `today from ${meta.sendFrom}` : `on ${formatDay(saved.startDate)} at ${meta.sendFrom}`;
      setNotice(
        saved.notifyAudience
          ? `${saved.name} is set: ${saved.offerCode} goes out to ${who} ${when}, and works at the desk until ${formatDay(saved.endDate)}.`
          : `${saved.name} is set: ${saved.offerCode} works for ${who} from ${formatDay(saved.startDate)} to ${formatDay(saved.endDate)} (nothing is sent).`,
      );
    }
    load();
  }

  async function confirmCancel() {
    const campaign = cancelTarget;
    setActionError(null);
    try {
      const saved = await updateCampaign(campaign.id, { isActive: false });
      setCancelTarget(null);
      setNotice(
        saved.withdrawnNotices
          ? `${campaign.name} cancelled. ${saved.withdrawnNotices} member${saved.withdrawnNotices === 1 ? " was" : "s were"} told ${campaign.offerCode} no longer works.`
          : `${campaign.name} cancelled.`,
      );
      load();
    } catch (err) {
      setCancelTarget(null);
      setActionError(err.message);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Marketing Campaigns</h1>
          <p style={styles.subtitle}>
            Plan a campaign, give it an offer code and pick who it&apos;s for. On the start date the code is sent to them and starts working at
            the front desk and the shop - and it stops by itself after the end date.
          </p>
        </div>
        <button onClick={() => setFormTarget("new")} style={styles.newButton} disabled={!meta}>
          + New Campaign
        </button>
      </div>

      <div style={styles.filterRow}>
        <label style={styles.filterLabel}>
          Branch
          <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.select}>
            <option value="">All branches</option>
            {(meta?.branches || []).map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && <div style={styles.noticeBox} role="status">{notice}</div>}
      {loading && <div style={styles.meta}>Loading campaigns...</div>}
      {error && <div style={styles.errorBox}>Couldn&apos;t load campaigns: {error}</div>}
      {actionError && <div style={styles.errorBox}>{actionError}</div>}

      {!loading && !error && campaigns.length === 0 && <div style={styles.empty}>No campaigns{branch ? ` at ${branch}` : ""} yet.</div>}

      {!loading && !error && campaigns.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Campaign</th>
                <th style={styles.th}>Offer</th>
                <th style={styles.th}>Who it&apos;s for</th>
                <th style={styles.th}>Dates</th>
                <th style={styles.th}>Budget</th>
                <th style={styles.th}>Results</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => {
                const editable = c.status === "Running" || c.status === "Scheduled";
                const overBudget = Number(c.amountSpent) > Number(c.budget);
                const r = c.results;
                return (
                  <tr key={c.id}>
                    <td style={styles.td}>
                      <div style={styles.campaignName}>{c.name}</div>
                      <div style={styles.small}>{c.branch}</div>
                      {c.strategy && <div style={styles.strategy}>{c.strategy}</div>}
                      {c.createdBy && <div style={styles.createdBy}>by {c.createdBy}</div>}
                    </td>
                    <td style={styles.td}>
                      {c.offerCode ? (
                        <>
                          <span style={styles.code}>{c.offerCode}</span>
                          <div style={styles.small}>
                            {c.discountLabel} {USE_SHORT[c.appliesTo]}
                          </div>
                          {c.maxRedemptions && <div style={styles.small}>first {c.maxRedemptions} uses</div>}
                        </>
                      ) : (
                        <span style={styles.none}>No offer</span>
                      )}
                    </td>
                    <td style={{ ...styles.td, maxWidth: 220 }}>
                      {c.offerCode ? (
                        <>
                          <div style={styles.small}>{c.segment.description}</div>
                          <div style={styles.sendLine}>{sendLine(c)}</div>
                        </>
                      ) : (
                        <span style={styles.none}>—</span>
                      )}
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      {formatDay(c.startDate)} → {formatDay(c.endDate)}
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      ${c.budget}
                      <div style={{ ...styles.small, color: overBudget ? "#b3261e" : undefined, fontWeight: overBudget ? 700 : 400 }}>
                        ${c.amountSpent} spent
                      </div>
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      {c.offerCode ? (
                        <>
                          <div>
                            <strong>{r.redeemed}</strong> used{r.sent ? ` of ${r.sent} sent` : ""}
                          </div>
                          <div style={styles.small}>
                            ${r.discountGiven} off · ${r.revenue} taken
                          </div>
                        </>
                      ) : (
                        <span style={styles.none}>—</span>
                      )}
                    </td>
                    <td style={styles.td}>
                      <span style={{ ...styles.badge, ...STATUS_COLORS[c.status] }}>{c.status}</span>
                    </td>
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      <div style={styles.actionsCell}>
                        {c.offerCode && (
                          <button onClick={() => setResultsId(c.id)} style={styles.secondaryButton}>
                            Results
                          </button>
                        )}
                        {editable && (
                          <>
                            <button onClick={() => setFormTarget(c)} style={styles.secondaryButton}>
                              Edit
                            </button>
                            <button onClick={() => setCancelTarget(c)} style={styles.secondaryButton}>
                              Cancel
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {formTarget && meta && (
        <CampaignForm
          campaign={formTarget === "new" ? null : formTarget}
          meta={meta}
          defaultBranch={branch}
          onClose={() => setFormTarget(null)}
          onSaved={handleSaved}
        />
      )}

      {cancelTarget && <CancelDialog campaign={cancelTarget} onBack={() => setCancelTarget(null)} onConfirm={confirmCancel} />}
      {resultsId && <CampaignResults campaignId={resultsId} onClose={() => setResultsId(null)} />}
    </div>
  );
}

function sendLine(c) {
  if (!c.notifyAudience) return "Not sent - shared by hand";
  if (c.results.sent) return `Sent to ${c.results.sent}${c.launchedAt ? ` · since ${formatDay(c.launchedAt.slice(0, 10))}` : ""}`;
  if (c.status === "Scheduled") return `Goes out ${formatDay(c.startDate)}`;
  if (c.status === "Running") return "Going out (nobody matched yet)";
  return "Nobody was sent it";
}

function CancelDialog({ campaign, onBack, onConfirm }) {
  const [busy, setBusy] = useState(false);
  const sent = campaign.results?.sent || 0;
  return (
    <div style={styles.overlay} onClick={onBack}>
      <div style={styles.dialog} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Cancel campaign">
        <h2 style={styles.dialogTitle}>Cancel {campaign.name}?</h2>
        <p style={styles.dialogText}>
          {campaign.offerCode
            ? `${campaign.offerCode} stops working at the desk and the shop straight away.${
                sent ? ` The members who were sent it and haven't used it yet are told it's been withdrawn.` : ""
              } A cancelled campaign can't be restarted.`
            : "It stays on the record (and in the General Manager's report) as cancelled. A cancelled campaign can't be restarted."}
        </p>
        <div style={styles.dialogActions}>
          <button type="button" onClick={onBack} style={styles.secondaryButtonLarge} disabled={busy}>
            Keep it
          </button>
          <button
            type="button"
            onClick={() => {
              setBusy(true);
              onConfirm();
            }}
            style={styles.dangerButton}
            disabled={busy}
          >
            {busy ? "Cancelling..." : "Cancel campaign"}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1200,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16, marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4, maxWidth: 720 },
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
  noticeBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 1050, borderCollapse: "collapse", fontSize: 14 },
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
  small: { fontSize: 12, color: "#666", marginTop: 2 },
  strategy: { fontSize: 12, color: "#777", marginTop: 2, maxWidth: 240 },
  createdBy: { fontSize: 12, color: "#999", marginTop: 2 },
  code: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontWeight: 800,
    fontSize: 13,
    letterSpacing: 0.5,
    background: "#eef2fa",
    color: "#124096",
    borderRadius: 4,
    padding: "2px 7px",
  },
  sendLine: { fontSize: 12, color: "#124096", fontWeight: 600, marginTop: 4 },
  none: { fontSize: 13, color: "#aaa" },
  badge: { fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" },
  actionsCell: { display: "flex", gap: 6 },
  secondaryButton: {
    padding: "5px 10px",
    fontSize: 12,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20, zIndex: 1000 },
  dialog: { background: "#fff", borderRadius: 12, padding: 22, width: "100%", maxWidth: 440, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif" },
  dialogTitle: { fontSize: 17, fontWeight: 700, margin: "0 0 8px" },
  dialogText: { fontSize: 14, color: "#444", lineHeight: 1.5, margin: 0 },
  dialogActions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 },
  secondaryButtonLarge: { padding: "9px 14px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#f5f5f7", cursor: "pointer" },
  dangerButton: { padding: "9px 14px", fontSize: 14, border: "none", borderRadius: 8, ...BUTTON_COLORS.red, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" },
};

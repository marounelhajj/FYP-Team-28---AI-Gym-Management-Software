import { useEffect, useState } from "react";
import { fetchCampaign } from "../../api/marketing.js";

const USE_WORDS = {
  Membership: "membership renewals",
  Shop: "shop purchases",
  Both: "membership renewals and shop purchases",
};

// How one campaign's offer is doing: who it went to, how many used it, what
// it took off and what those members paid - and the latest uses.
export default function CampaignResults({ campaignId, onClose }) {
  const [campaign, setCampaign] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCampaign(campaignId).then(setCampaign).catch((err) => setError(err.message));
  }, [campaignId]);

  const r = campaign?.results;
  const rate = r && r.sent ? Math.round((r.redeemed / r.sent) * 100) : null;

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Campaign results">
        <div style={styles.head}>
          <div>
            <h2 style={styles.title}>{campaign ? campaign.name : "Campaign"}</h2>
            {campaign && (
              <p style={styles.sub}>
                <span style={styles.code}>{campaign.offerCode}</span> {campaign.discountLabel} {USE_WORDS[campaign.appliesTo]} · {campaign.branch} ·{" "}
                {campaign.startDate} → {campaign.endDate} · {campaign.status}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={styles.close} aria-label="Close">
            &times;
          </button>
        </div>
        {error && <div style={styles.errorBox}>{error}</div>}
        {!campaign && !error && <p style={styles.muted}>Loading...</p>}

        {campaign && (
          <>
            <div style={styles.stats}>
              <Stat label="Sent to" value={campaign.notifyAudience ? r.sent : "—"} note={campaign.notifyAudience ? null : "shared by hand"} />
              <Stat label="Used" value={r.redeemed} note={campaign.maxRedemptions ? `of ${campaign.maxRedemptions} allowed` : rate !== null ? `${rate}% of those sent` : null} />
              <Stat label="Discount given" value={`$${r.discountGiven}`} />
              <Stat label="Paid by those members" value={`$${r.revenue}`} />
            </div>

            <div style={styles.box}>
              <div style={styles.boxTitle}>Audience</div>
              <div>{campaign.segment.description}</div>
              {campaign.audience && (
                <div style={styles.muted}>
                  {campaign.audience.count} match right now · {campaign.audience.reachable} can be sent offers
                  {campaign.audience.optedOut ? ` · ${campaign.audience.optedOut} turned offers off` : ""}
                </div>
              )}
              {campaign.launchedAt && <div style={styles.muted}>First sent {campaign.launchedAt}</div>}
              {campaign.offerMessage && <div style={styles.message}>&ldquo;{campaign.offerMessage}&rdquo;</div>}
            </div>

            <h3 style={styles.sectionTitle}>Latest uses</h3>
            {campaign.recentUses.length === 0 ? (
              <p style={styles.muted}>Nobody has used {campaign.offerCode} yet.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>When</th>
                      <th style={styles.th}>Member</th>
                      <th style={styles.th}>On</th>
                      <th style={styles.thRight}>Price</th>
                      <th style={styles.thRight}>Off</th>
                      <th style={styles.thRight}>Paid</th>
                      <th style={styles.th}>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {campaign.recentUses.map((u) => (
                      <tr key={u.id} style={u.voided ? { color: "#999", textDecoration: "line-through" } : null}>
                        <td style={styles.td}>{u.redeemedAt}</td>
                        <td style={styles.td}>
                          {u.member} <span style={styles.muted}>#{u.memberId}</span>
                        </td>
                        <td style={styles.td}>
                          {u.use === "Shop" ? `Shop${u.saleId ? ` (sale #${u.saleId})` : ""}` : "Renewal"}
                          {u.voided && " - voided"}
                        </td>
                        <td style={styles.tdRight}>${u.amountBefore}</td>
                        <td style={styles.tdRight}>-${u.discount}</td>
                        <td style={styles.tdRight}>${u.amountPaid}</td>
                        <td style={styles.td}>{u.redeemedBy || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, note }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statLabel}>{label}</div>
      <div style={styles.statValue}>{value}</div>
      {note && <div style={styles.statNote}>{note}</div>}
    </div>
  );
}

const styles = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20, zIndex: 1000 },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 22,
    width: "100%",
    maxWidth: 760,
    maxHeight: "92vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  head: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  sub: { fontSize: 13, color: "#555", margin: "6px 0 0", lineHeight: 1.6 },
  close: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  code: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontWeight: 800,
    background: "#eef2fa",
    color: "#124096",
    borderRadius: 4,
    padding: "2px 7px",
  },
  stats: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 },
  stat: { border: "1px solid #e4e4e8", borderRadius: 10, padding: "10px 12px" },
  statLabel: { fontSize: 11, fontWeight: 700, color: "#666", textTransform: "uppercase", letterSpacing: 0.3 },
  statValue: { fontSize: 22, fontWeight: 800, marginTop: 2 },
  statNote: { fontSize: 12, color: "#777" },
  box: { background: "#f7f9fd", border: "1px solid #dfe5f2", borderRadius: 10, padding: "10px 12px", fontSize: 14, display: "flex", flexDirection: "column", gap: 3 },
  boxTitle: { fontSize: 11, fontWeight: 700, color: "#124096", textTransform: "uppercase", letterSpacing: 0.3 },
  message: { fontSize: 13, color: "#444", fontStyle: "italic", marginTop: 4 },
  sectionTitle: { fontSize: 14, fontWeight: 800, margin: "4px 0 0" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "7px 8px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", whiteSpace: "nowrap" },
  thRight: { textAlign: "right", padding: "7px 8px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase" },
  td: { padding: "7px 8px", borderBottom: "1px solid #f0f0f2", whiteSpace: "nowrap" },
  tdRight: { padding: "7px 8px", borderBottom: "1px solid #f0f0f2", textAlign: "right", whiteSpace: "nowrap" },
};

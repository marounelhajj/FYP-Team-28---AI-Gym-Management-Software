import { useEffect, useState } from "react";
import { fetchMyLoyalty } from "../../api/memberAuth.js";

// User story: "As a member, I want to earn loyalty points for attending
// sessions and referring friends, so that my consistency is rewarded."
//
// This member's running points balance (attended classes/PT sessions +
// referrals that led to a friend joining - see backend/loyalty), their
// own referral code to hand out, and how each entry was earned. Shows the
// balance and code even at zero, so a brand new member always sees where
// to find their code; the history list is only shown once there's
// something in it.
export default function MyLoyalty() {
  const [data, setData] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchMyLoyalty()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) return null;

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(data.referralCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied/unavailable - the code is still
      // right there on screen to copy by hand.
    }
  }

  return (
    <section style={styles.wrap} aria-label="Your loyalty points">
      <h2 style={styles.title}>Loyalty points</h2>
      <div style={styles.summaryRow}>
        <div style={styles.balanceCard}>
          <div style={styles.balanceNumber}>{data.balance}</div>
          <div style={styles.balanceLabel}>points earned</div>
        </div>
        <div style={styles.referralCard}>
          <div style={styles.referralLabel}>Your referral code</div>
          <div style={styles.codeRow}>
            <span style={styles.code}>{data.referralCode}</span>
            <button type="button" onClick={copyCode} style={styles.copyButton}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p style={styles.hint}>
            Share it with a friend - they enter it when they join, and you earn points once they do.
          </p>
        </div>
      </div>

      {data.entries.length > 0 && (
        <div style={styles.history}>
          {data.entries.map((e) => (
            <div key={e.id} style={styles.entryRow}>
              <span style={styles.entryPoints}>+{e.points}</span>
              <span style={styles.entryDescription}>{e.description}</span>
              <span style={styles.entryDate}>{e.earnedAt.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const styles = {
  wrap: { margin: "24px 0 20px" },
  title: { fontSize: 18, fontWeight: 700, margin: "0 0 10px" },
  summaryRow: { display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12 },
  balanceCard: {
    flex: "0 1 160px",
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    padding: "14px 16px",
    background: "#fff",
    textAlign: "center",
  },
  balanceNumber: { fontSize: 30, fontWeight: 800, color: "#124096" },
  balanceLabel: { fontSize: 12, color: "#666", marginTop: 2 },
  referralCard: {
    flex: "1 1 260px",
    border: "1px dashed #124096",
    background: "#f4f7fd",
    borderRadius: 12,
    padding: "14px 16px",
  },
  referralLabel: { fontSize: 11, fontWeight: 700, color: "#666", textTransform: "uppercase", letterSpacing: 0.4 },
  codeRow: { display: "flex", alignItems: "center", gap: 8, marginTop: 4 },
  code: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 18,
    fontWeight: 800,
    letterSpacing: 2,
    background: "#fff",
    border: "1px solid #c9d4ec",
    borderRadius: 6,
    padding: "3px 10px",
  },
  copyButton: {
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #c9d4ec",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  hint: { fontSize: 12, color: "#666", margin: "8px 0 0" },
  history: { display: "flex", flexDirection: "column", gap: 6 },
  entryRow: {
    display: "flex",
    alignItems: "baseline",
    gap: 10,
    padding: "8px 12px",
    border: "1px solid #eee",
    borderRadius: 8,
    background: "#fafafb",
    fontSize: 13,
  },
  entryPoints: { fontWeight: 700, color: "#129638", flexShrink: 0 },
  entryDescription: { flex: 1, color: "#333" },
  entryDate: { color: "#999", fontSize: 12, flexShrink: 0 },
};

import { useEffect, useState } from "react";
import { fetchMyOffers } from "../../api/memberAuth.js";

// The marketing offers this member was sent and can still use, so they can
// show the code at the desk without digging out the email. Shows nothing at
// all when there are none.
export default function MyOffers() {
  const [offers, setOffers] = useState([]);

  useEffect(() => {
    fetchMyOffers()
      .then((data) => setOffers(data.results))
      .catch(() => setOffers([]));
  }, []);

  if (offers.length === 0) return null;

  return (
    <section style={styles.wrap} aria-label="Your offers">
      <h2 style={styles.title}>Your offers</h2>
      <div style={styles.list}>
        {offers.map((o) => (
          <div key={o.campaignId} style={styles.card}>
            <div style={styles.top}>
              <span style={styles.discount}>{o.discount}</span>
              <span style={styles.for}>{o.for}</span>
            </div>
            {o.message && <p style={styles.message}>{o.message}</p>}
            <div style={styles.codeRow}>
              <span style={styles.codeLabel}>Code</span>
              <span style={styles.code}>{o.code}</span>
            </div>
            <p style={styles.terms}>
              {o.fullyClaimed
                ? "All the uses of this offer have been claimed."
                : `Show this at the ${o.branch} front desk by ${formatDay(o.endsOn)}. One use per member.`}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatDay(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

const styles = {
  wrap: { margin: "24px 0 20px" },
  title: { fontSize: 18, fontWeight: 700, margin: "0 0 10px" },
  list: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 },
  card: {
    border: "1px dashed #124096",
    background: "#f4f7fd",
    borderRadius: 12,
    padding: "14px 16px",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  top: { display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" },
  discount: { fontSize: 22, fontWeight: 800, color: "#124096" },
  for: { fontSize: 13, color: "#444" },
  message: { fontSize: 13, color: "#333", margin: 0 },
  codeRow: { display: "flex", alignItems: "center", gap: 8 },
  codeLabel: { fontSize: 11, fontWeight: 700, color: "#666", textTransform: "uppercase", letterSpacing: 0.4 },
  code: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 16,
    fontWeight: 800,
    letterSpacing: 1,
    background: "#fff",
    border: "1px solid #c9d4ec",
    borderRadius: 6,
    padding: "3px 10px",
  },
  terms: { fontSize: 12, color: "#666", margin: 0 },
};

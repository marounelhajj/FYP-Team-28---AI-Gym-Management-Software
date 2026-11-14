import { useEffect, useState } from "react";
import { fetchRatingsByBranch } from "../../api/feedback.js";
import { Stars } from "./Stars.jsx";

const BRANCHES = ["Hamra", "Achrafieh", "Jnah", "Zalka"];

// A star-count histogram (5 down to 1) against the branch's busiest star,
// so a lopsided distribution (all 5s, or a cluster of 1s) is visible at a
// glance without a chart library - same idea as audit's RetentionReport
// bar, just one per star instead of one per branch.
function StarBar({ value, max }) {
  const width = max === 0 ? 0 : Math.max(4, Math.round((value / max) * 100));
  return (
    <div style={styles.barTrack}>
      <div style={{ ...styles.barFill, width: `${width}%` }} />
    </div>
  );
}

function BranchCard({ branch }) {
  const maxStar = Math.max(1, ...Object.values(branch.stars));
  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <h2 style={styles.branchName}>{branch.branch}</h2>
        {branch.count > 0 ? (
          <div style={styles.branchAverage}>
            <Stars value={branch.average} size={18} />
            <span style={styles.averageNumber}>{branch.average.toFixed(2)}</span>
            <span style={styles.ratingCount}>
              ({branch.count} rating{branch.count === 1 ? "" : "s"})
            </span>
          </div>
        ) : (
          <span style={styles.ratingCount}>No ratings yet</span>
        )}
      </div>

      {branch.count > 0 && (
        <div style={styles.histogram}>
          {[5, 4, 3, 2, 1].map((n) => (
            <div key={n} style={styles.histogramRow}>
              <span style={styles.histogramLabel}>{n}★</span>
              <StarBar value={branch.stars[String(n)]} max={maxStar} />
              <span style={styles.histogramCount}>{branch.stars[String(n)]}</span>
            </div>
          ))}
        </div>
      )}

      {branch.coaches.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Coach</th>
                <th style={styles.th}>Ratings</th>
                <th style={styles.th}>Average</th>
              </tr>
            </thead>
            <tbody>
              {branch.coaches.map((c) => (
                <tr key={c.id}>
                  <td style={{ ...styles.td, fontWeight: 600 }}>{c.name}</td>
                  <td style={styles.td}>{c.count}</td>
                  <td style={styles.td}>
                    <span style={styles.coachAverage}>
                      <Stars value={c.average} size={14} />
                      {c.average.toFixed(2)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// General Manager's cross-branch read of the ratings members leave for
// coaches (feedback.models.CoachFeedback, via feedback.views.ratings_by_branch) -
// branch by branch, each with its coaches ranked best-average first, so a
// branch problem (or a stand-out coach) doesn't hide in the org-wide number.
//
// User story: "As a general manager, I want to view personal trainer
// ratings by branch, so that I can inform staffing, coaching, and
// incentive decisions."
export default function PTRatingsReport() {
  const [branch, setBranch] = useState("");
  const [data, setData] = useState({ branches: [], totals: { count: 0, average: null } });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchRatingsByBranch(branch || undefined)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [branch]);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>Personal Trainer Ratings</h1>
        <p style={styles.subtitle}>
          How members rate their coaches, broken down by branch and by coach, to inform staffing, coaching, and
          incentive decisions.
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
            {data.totals.count === 0 ? (
              "No ratings yet"
            ) : (
              <>
                <Stars value={data.totals.average} size={16} />
                <span style={styles.averageNumber}>{data.totals.average.toFixed(2)}</span>
                <span style={styles.ratingCount}>
                  across {data.totals.count} rating{data.totals.count === 1 ? "" : "s"}
                </span>
              </>
            )}
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
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
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
  totals: { display: "flex", alignItems: "center", gap: 8, fontSize: 14 },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  cards: { display: "flex", flexDirection: "column", gap: 16 },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    padding: 16,
  },
  cardHeader: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 10,
  },
  branchName: { fontSize: 17, fontWeight: 700, margin: 0 },
  branchAverage: { display: "flex", alignItems: "center", gap: 8 },
  averageNumber: { fontSize: 15, fontWeight: 700 },
  ratingCount: { fontSize: 13, color: "#777" },
  histogram: { display: "flex", flexDirection: "column", gap: 4, marginBottom: 12, maxWidth: 420 },
  histogramRow: { display: "flex", alignItems: "center", gap: 8 },
  histogramLabel: { fontSize: 12, color: "#666", width: 24, flexShrink: 0 },
  histogramCount: { fontSize: 12, color: "#666", width: 24, textAlign: "right", flexShrink: 0 },
  barTrack: { flex: 1, height: 8, borderRadius: 999, background: "#eef1f8", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999, background: "#e8a400" },
  tableWrap: { overflowX: "auto" },
  table: { width: "100%", minWidth: 360, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    whiteSpace: "nowrap",
  },
  td: { padding: "8px 10px", borderBottom: "1px solid #f0f0f3", verticalAlign: "middle" },
  coachAverage: { display: "inline-flex", alignItems: "center", gap: 6 },
};

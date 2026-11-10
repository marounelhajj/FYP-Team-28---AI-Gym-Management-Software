import { useEffect, useState } from "react";
import { fetchMyRatings } from "../../api/feedback.js";
import { Stars } from "./Stars.jsx";

// User story (SCRUM-37): "As a coach, I want to view ratings and feedback left
// by my clients, so that I can improve my coaching approach."
//
// The coach's own ratings: the overall average and star breakdown, the
// average per class, and every rating with its comment, newest first. The
// server only ever returns ratings left for the signed-in coach.

const STAR_FILTERS = ["", "5", "4", "3", "2", "1"];

const formatAverage = (value) => (value == null ? "-" : value.toFixed(1));

export default function MyRatings() {
  const [rating, setRating] = useState("");
  const [withComments, setWithComments] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetchMyRatings({ rating, withComments }).then(setData).catch((e) => setError(e.message));
  }, [rating, withComments]);

  const summary = data?.summary;
  const maxStars = summary ? Math.max(1, ...Object.values(summary.stars)) : 1;

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>My Ratings</h1>
      <p style={styles.subtitle}>What members said after your classes and private sessions.</p>
      {error && <div style={styles.errorBox}>{error}</div>}
      {!data && !error && <p style={styles.muted}>Loading...</p>}

      {summary && summary.count === 0 && (
        <div style={styles.empty}>No ratings yet. Members can rate a session they attended for 14 days afterwards.</div>
      )}

      {summary && summary.count > 0 && (
        <>
          <div style={styles.summaryGrid}>
            <section style={styles.card} aria-label="Overall rating">
              <div style={styles.bigNumber}>{formatAverage(summary.average)}</div>
              <Stars value={summary.average} size={20} />
              <div style={styles.cardMeta}>{summary.count} rating{summary.count === 1 ? "" : "s"}</div>
              <div style={styles.cardMeta}>
                Last {summary.recent.days} days: {formatAverage(summary.recent.average)}
                {summary.recent.count ? ` from ${summary.recent.count}` : " (none)"}
              </div>
            </section>

            <section style={styles.card} aria-label="Star breakdown">
              {/* Listed explicitly: JS sorts number-like object keys ascending. */}
              {[5, 4, 3, 2, 1].map((stars) => {
                const count = summary.stars[stars] || 0;
                return (
                  <div key={stars} style={styles.barRow}>
                    <span style={styles.barLabel}>{stars} ★</span>
                    <div style={styles.barTrack}>
                      <div style={{ ...styles.barFill, width: `${(count / maxStars) * 100}%` }} />
                    </div>
                    <span style={styles.barCount}>{count}</span>
                  </div>
                );
              })}
            </section>

            <section style={styles.card} aria-label="Average by session">
              <h2 style={styles.cardTitle}>By session</h2>
              <ul style={styles.sessionList}>
                {data.bySession.map((s) => (
                  <li key={s.name} style={styles.sessionRow}>
                    <span style={styles.sessionName}>{s.name}</span>
                    <span style={styles.sessionValue}>{formatAverage(s.average)} ★ · {s.count}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div style={styles.filters}>
            <label style={styles.filter}>
              <span style={styles.label}>Stars</span>
              <select value={rating} onChange={(e) => setRating(e.target.value)} style={styles.select}>
                {STAR_FILTERS.map((v) => (
                  <option key={v} value={v}>{v ? `${v} star${v === "1" ? "" : "s"}` : "All ratings"}</option>
                ))}
              </select>
            </label>
            <label style={styles.checkbox}>
              <input type="checkbox" checked={withComments} onChange={(e) => setWithComments(e.target.checked)} />
              Only with comments
            </label>
            <span style={styles.count}>
              {data.matching} rating{data.matching === 1 ? "" : "s"}
              {data.matching > data.results.length ? ` (newest ${data.results.length} shown)` : ""}
            </span>
          </div>

          {data.results.length === 0 && <div style={styles.empty}>No ratings match these filters.</div>}
          <ul style={styles.list}>
            {data.results.map((r) => (
              <li key={r.id} style={styles.item}>
                <div style={styles.itemHeader}>
                  <Stars value={r.rating} />
                  <span style={styles.itemTitle}>{r.sessionName}</span>
                  <span style={styles.itemMeta}>{r.sessionAt} · {r.branch}</span>
                </div>
                {r.comment ? <p style={styles.comment}>“{r.comment}”</p> : <p style={styles.noComment}>No comment</p>}
                <div style={styles.itemMeta}>{r.memberName}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1000, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 16px" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  empty: { padding: 18, border: "1px dashed #d0d0d5", borderRadius: 12, fontSize: 14, color: "#888", textAlign: "center" },
  muted: { fontSize: 13, color: "#888" },
  summaryGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 16 },
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff", minWidth: 0 },
  cardTitle: { fontSize: 14, fontWeight: 800, margin: "0 0 8px" },
  bigNumber: { fontSize: 36, fontWeight: 800, lineHeight: 1.1 },
  cardMeta: { fontSize: 13, color: "#666", marginTop: 4 },
  barRow: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 },
  barLabel: { width: 34, fontSize: 13, fontWeight: 700, color: "#444", whiteSpace: "nowrap" },
  barTrack: { flex: 1, height: 10, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999, background: "#e8a400" },
  barCount: { width: 28, fontSize: 13, color: "#666", textAlign: "right" },
  sessionList: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  sessionRow: { display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13 },
  sessionName: { fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  sessionValue: { color: "#555", whiteSpace: "nowrap" },
  filters: { display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap", marginBottom: 12 },
  filter: { display: "flex", flexDirection: "column", gap: 4 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  select: { height: 36, padding: "0 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontWeight: 600 },
  checkbox: { display: "flex", alignItems: "center", gap: 6, height: 36, fontSize: 13, fontWeight: 600, color: "#444" },
  count: { fontSize: 13, color: "#666", height: 36, display: "flex", alignItems: "center" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  item: { padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  itemHeader: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  itemTitle: { fontSize: 14, fontWeight: 700 },
  itemMeta: { fontSize: 12, color: "#666" },
  comment: { fontSize: 14, color: "#333", margin: "6px 0 4px", overflowWrap: "anywhere" },
  noComment: { fontSize: 13, color: "#999", fontStyle: "italic", margin: "6px 0 4px" },
};

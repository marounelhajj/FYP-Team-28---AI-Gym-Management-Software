import { useEffect, useState } from "react";
import { fetchMemberCalls } from "../../api/churn.js";

// User story (SCRUM-68): "...log the outcome of a retention call on an
// at-risk member's record, so that the team knows who has been contacted..."
//
// The member's retention calls, newest first: when, who called, the outcome,
// the note and any follow-up date. Shown on the member record and from the
// at-risk list. Renders nothing for a role that can't see calls (403).

export const OUTCOME_COLORS = {
  reached: { background: "#e6edfa", color: "#124096" },
  no_answer: { background: "#ececf0", color: "#555" },
  saved: { background: "#e6f4ea", color: "#1e6b34" },
  cancelled_anyway: { background: "#fde7e6", color: "#b3261e" },
};

function when(iso) {
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function day(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function OutcomeBadge({ outcome, label }) {
  return <span style={{ ...styles.badge, ...(OUTCOME_COLORS[outcome] || OUTCOME_COLORS.no_answer) }}>{label}</span>;
}

export default function RetentionCallHistory({ memberId, title = "Retention calls", reloadKey = 0 }) {
  const [calls, setCalls] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchMemberCalls(memberId)
      .then((body) => !cancelled && setCalls(body.calls))
      .catch((e) => {
        if (cancelled) return;
        if (e.status === 403) setHidden(true);
        else setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [memberId, reloadKey]);

  if (hidden) return null;
  return (
    <section aria-label={title}>
      {title && <h3 style={styles.title}>{title}</h3>}
      {error && <div style={styles.error}>Couldn't load calls: {error}</div>}
      {!calls && !error && <div style={styles.muted}>Loading...</div>}
      {calls && calls.length === 0 && <div style={styles.empty}>No retention calls logged yet.</div>}
      {calls && calls.length > 0 && (
        <ol style={styles.list}>
          {calls.map((c) => (
            <li key={c.id} style={styles.item}>
              <div style={styles.top}>
                <OutcomeBadge outcome={c.outcome} label={c.outcomeLabel} />
                <span style={styles.when}>{when(c.calledAt)}</span>
                <span style={styles.who}>by {c.calledBy || "a former staff member"}</span>
              </div>
              {c.note && <div style={styles.note}>"{c.note}"</div>}
              {c.followUpOn && <div style={styles.follow}>Follow up on {day(c.followUpOn)}</div>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const styles = {
  title: { fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: "#555", margin: "20px 0 8px" },
  muted: { fontSize: 13, color: "#888" },
  error: { fontSize: 13, color: "#b3261e" },
  empty: { fontSize: 13, color: "#888", padding: "10px 14px", border: "1px dashed #d0d0d5", borderRadius: 10 },
  list: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 10, overflow: "hidden" },
  item: { padding: "10px 14px", borderBottom: "1px solid #f0f0f2", display: "flex", flexDirection: "column", gap: 4 },
  top: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, fontSize: 13 },
  badge: { fontSize: 12, fontWeight: 800, padding: "3px 10px", borderRadius: 999 },
  when: { fontWeight: 700 },
  who: { color: "#666" },
  note: { fontSize: 13, color: "#333", fontStyle: "italic" },
  follow: { fontSize: 12, fontWeight: 700, color: "#8a5a00" },
};

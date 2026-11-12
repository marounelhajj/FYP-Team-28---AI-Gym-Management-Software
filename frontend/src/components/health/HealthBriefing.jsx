import { useEffect, useState } from "react";
import { fetchClassHealthBriefing, fetchPtHealthBriefing } from "../../api/health.js";
import { MemberHealth, formatDay } from "./HealthViews.jsx";

// User story: "As a coach, I want to view a client's health restrictions and
// injuries before starting a session, so that I can adapt the workout safely."
//
// Opened from a class or private session on the coach's My Schedule. For a
// class: who has restrictions (most limiting first), who never filled in
// their health information, and who has nothing to declare. Read-only - the
// notes belong to the member. The server decides who may open it.
export default function HealthBriefing({ kind, id, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = kind === "class" ? fetchClassHealthBriefing : fetchPtHealthBriefing;
    load(id).then(setData).catch((err) => setError(err.message));
  }, [kind, id]);

  const session = data && (data.class || data.session);
  const title = data ? (data.class ? data.class.name : `Private training · ${data.member.name}`) : "";

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Health briefing">
        <div style={styles.header}>
          <div>
            <h2 style={styles.title}>Health briefing{title ? ` · ${title}` : ""}</h2>
            {session && (
              <p style={styles.subtitle}>
                {formatDay(session.date)} · {session.startTime}–{session.endTime} · {session.branch}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {error && <div style={styles.errorBox}>{error}</div>}
        {!data && !error && <p style={styles.muted}>Loading...</p>}

        {data && data.member && <MemberHealth member={data.member} />}

        {data && data.class && (
          <>
            <div style={styles.counts}>
              <Count label="Booked" value={data.booked} color="#1a1a1a" />
              <Count label="With restrictions" value={data.restricted.length} color="#b3261e" />
              <Count label="Not declared" value={data.undeclared.length} color="#8a5300" />
              <Count label="Nothing to declare" value={data.clear.length} color="#0f6e2b" />
            </div>

            {data.booked === 0 && <p style={styles.muted}>No one is booked into this class yet.</p>}

            {data.restricted.length > 0 && (
              <>
                <h3 style={styles.section}>Adapt the workout for</h3>
                {data.restricted.map((m) => (
                  <div key={m.memberId} style={styles.member}>
                    <div style={styles.memberName}>
                      {m.name} <span style={styles.memberId}>#{m.memberId}</span>
                    </div>
                    <MemberHealth member={m} />
                  </div>
                ))}
              </>
            )}

            {data.undeclared.length > 0 && (
              <>
                <h3 style={styles.section}>Ask before you start</h3>
                <div style={styles.askBox}>
                  {data.undeclared.map((m) => m.name).join(", ")}{" "}
                  {data.undeclared.length === 1 ? "hasn't" : "haven't"} filled in their health information.
                </div>
              </>
            )}

            {data.clear.length > 0 && (
              <>
                <h3 style={styles.section}>Nothing to declare</h3>
                <p style={styles.clearList}>
                  {data.clear.map((m) => `${m.name}${m.recentlyRecovered.length ? " (recently recovered)" : ""}${m.stale ? " (not confirmed recently)" : ""}`).join(", ")}
                </p>
                {data.clear.filter((m) => m.recentlyRecovered.length > 0).map((m) => (
                  <div key={m.memberId} style={styles.member}>
                    <div style={styles.memberName}>{m.name}</div>
                    <MemberHealth member={{ ...m, status: "recovered" }} />
                  </div>
                ))}
              </>
            )}
          </>
        )}

        {data && <p style={styles.footer}>Health notes are written by the member and are confidential. Opening this is recorded.</p>}
      </div>
    </div>
  );
}

function Count({ label, value, color }) {
  return (
    <div style={styles.count}>
      <span style={{ ...styles.countValue, color }}>{value}</span>
      <span style={styles.countLabel}>{label}</span>
    </div>
  );
}

const styles = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 50 },
  modal: {
    background: "#fff",
    borderRadius: 14,
    padding: 22,
    width: "100%",
    maxWidth: 560,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  muted: { fontSize: 13, color: "#777", margin: "6px 0 10px" },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  counts: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8, marginBottom: 6 },
  count: { display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", padding: "8px 4px", borderRadius: 10, background: "#f6f6f8" },
  countValue: { fontSize: 22, fontWeight: 800 },
  countLabel: { fontSize: 10, fontWeight: 700, color: "#666", textTransform: "uppercase", letterSpacing: 0.3 },
  section: { fontSize: 14, fontWeight: 800, margin: "14px 0 8px" },
  member: { marginBottom: 12 },
  memberName: { fontSize: 14, fontWeight: 700, marginBottom: 6 },
  memberId: { fontSize: 12, fontWeight: 500, color: "#777" },
  askBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 12px", borderRadius: 8, fontSize: 13, lineHeight: 1.45 },
  clearList: { fontSize: 13, color: "#444", margin: "0 0 8px", lineHeight: 1.5 },
  footer: { fontSize: 11, color: "#888", margin: "14px 0 0" },
};

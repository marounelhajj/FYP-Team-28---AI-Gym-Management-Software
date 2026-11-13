// A complaint's conversation, oldest first, shared by the member's view and
// the manager's. Internal notes (staff only) only ever reach the manager's.

export const STATUS_STYLES = {
  Open: { background: "#fff1d6", color: "#8a5300" },
  "In progress": { background: "#eef2fa", color: "#124096" },
  Resolved: { background: "#e3f5e8", color: "#0f6e2b" },
};

export function StatusTag({ status }) {
  return <span style={{ ...styles.tag, ...STATUS_STYLES[status] }}>{status}</span>;
}

export default function ComplaintThread({ complaint, viewer }) {
  return (
    <ol style={styles.thread}>
      <li style={{ ...styles.message, ...styles.fromMember }}>
        <div style={styles.meta}>
          {viewer === "member" ? "You" : complaint.member?.name || "Deleted member"} · {complaint.createdAt}
        </div>
        <div style={styles.subject}>{complaint.subject}</div>
        <div style={styles.body}>{complaint.description}</div>
      </li>
      {complaint.messages.map((m) => {
        const mine = (viewer === "member") === (m.role === "member");
        return (
          <li
            key={m.id}
            style={{ ...styles.message, ...(m.role === "member" ? styles.fromMember : styles.fromStaff), ...(m.internal ? styles.internal : null) }}
          >
            <div style={styles.meta}>
              {mine && viewer === "member" ? "You" : m.author}
              {m.role === "staff" && viewer === "member" ? ` · ${complaint.branch}` : ""} · {m.at}
              {m.internal && <span style={styles.internalTag}>Internal note</span>}
            </div>
            <div style={styles.body}>{m.body}</div>
          </li>
        );
      })}
    </ol>
  );
}

const styles = {
  tag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4 },
  thread: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  message: { padding: "8px 12px", borderRadius: 10, maxWidth: "88%" },
  fromMember: { background: "#f4f4f6", alignSelf: "flex-start" },
  fromStaff: { background: "#eef2fa", alignSelf: "flex-end" },
  internal: { background: "#f3ecfb", border: "1px dashed #b89ad9" },
  internalTag: { marginLeft: 6, fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#6a2fa0", color: "#fff" },
  meta: { fontSize: 11, color: "#777", marginBottom: 3 },
  subject: { fontSize: 14, fontWeight: 700, marginBottom: 2 },
  body: { fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap", overflowWrap: "anywhere" },
};

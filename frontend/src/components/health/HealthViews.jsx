// Shared read-only pieces for health notes: the severity tag, a list of
// notes, and the one-line badge a coach sees next to a session or client.

const SEVERITY_STYLES = {
  Severe: { background: "#fdeceb", color: "#b3261e" },
  Moderate: { background: "#fff1d6", color: "#8a5300" },
  Mild: { background: "#eef2fa", color: "#124096" },
};

const SEVERITY_HINTS = {
  Severe: "avoid loading it",
  Moderate: "adapt some exercises",
  Mild: "train normally, with care",
};

export function formatDay(iso) {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function SeverityTag({ severity }) {
  return <span style={{ ...styles.tag, ...SEVERITY_STYLES[severity] }}>{severity}</span>;
}

// One note as a coach (or the member) reads it.
export function HealthNoteItem({ note, children }) {
  const recovered = note.status === "Resolved";
  return (
    <li style={{ ...styles.note, ...(recovered ? styles.noteRecovered : null) }}>
      <div style={styles.noteHead}>
        <span style={styles.noteTitle}>{note.title}</span>
        {recovered ? <span style={styles.recoveredTag}>Recovered</span> : <SeverityTag severity={note.severity} />}
      </div>
      <span style={styles.noteMeta}>
        {note.kind} · {note.bodyArea}
        {!recovered && ` · ${SEVERITY_HINTS[note.severity]}`}
        {note.since && ` · since ${formatDay(note.since)}`}
        {recovered && note.resolvedOn && ` · recovered ${formatDay(note.resolvedOn)}`}
      </span>
      {note.details && <span style={styles.noteDetails}>{note.details}</span>}
      {children}
    </li>
  );
}

export function HealthNoteList({ notes }) {
  return (
    <ul style={styles.list}>
      {notes.map((n) => (
        <HealthNoteItem key={n.id} note={n} />
      ))}
    </ul>
  );
}

// What a coach is shown for one member (a private client, or one name in a class).
export function MemberHealth({ member }) {
  return (
    <div>
      {member.status === "undeclared" && (
        <div style={styles.askBox}>
          {member.name.split(" ")[0]} hasn&apos;t filled in their health information yet. Ask about injuries or
          conditions before you start.
        </div>
      )}
      {member.status === "clear" && (
        <div style={styles.clearBox}>
          No injuries or restrictions declared (confirmed {formatDay(member.reviewedOn)}).
        </div>
      )}
      {member.status === "restrictions" && <HealthNoteList notes={member.active} />}
      {member.stale && (
        <p style={styles.staleNote}>
          Last confirmed {formatDay(member.reviewedOn)} - more than six months ago. Check it&apos;s still current.
        </p>
      )}
      {member.recentlyRecovered.length > 0 && (
        <>
          <div style={styles.subheading}>Recently recovered</div>
          <HealthNoteList notes={member.recentlyRecovered} />
        </>
      )}
    </div>
  );
}

// The short label for a session row or a client in a list.
export function healthBadge(badge) {
  if (!badge) return null;
  if (badge.status === "restrictions") {
    const count = `${badge.activeCount} health note${badge.activeCount === 1 ? "" : "s"}`;
    return { text: badge.severity === "Severe" ? `${count} · severe` : count, tone: badge.severity === "Severe" ? "red" : "amber" };
  }
  if (badge.status === "undeclared") return { text: "Health not declared", tone: "grey" };
  return { text: badge.stale ? "No restrictions · old" : "No restrictions", tone: "green" };
}

export const BADGE_TONES = {
  red: { background: "#fdeceb", color: "#b3261e" },
  amber: { background: "#fff1d6", color: "#8a5300" },
  grey: { background: "#ececf0", color: "#555" },
  green: { background: "#e3f5e8", color: "#0f6e2b" },
};

const styles = {
  tag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4 },
  recoveredTag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  note: {
    display: "flex",
    flexDirection: "column",
    gap: 3,
    padding: "10px 12px",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  noteRecovered: { background: "#f7f7f9", color: "#66666e" },
  noteHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 },
  noteTitle: { fontSize: 14, fontWeight: 700, minWidth: 0, overflowWrap: "anywhere" },
  noteMeta: { fontSize: 12, color: "#666" },
  noteDetails: { fontSize: 13, lineHeight: 1.45, overflowWrap: "anywhere" },
  askBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 12px", borderRadius: 8, fontSize: 13 },
  clearBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 12px", borderRadius: 8, fontSize: 13 },
  staleNote: { fontSize: 12, color: "#8a5300", margin: "6px 0 0" },
  subheading: { fontSize: 12, fontWeight: 700, color: "#666", margin: "10px 0 6px", textTransform: "uppercase", letterSpacing: 0.3 },
};

// Shown instead of a screen the signed-in role has no permission for.
// `title`/`message` let callers say what was blocked; the backend rejects
// the underlying API calls too, so this is the friendly face of a 403 and
// never the only line of defense.
export default function AccessDenied({
  title = "Access restricted",
  message = "Your role doesn't include permission to view this page.",
  roleName,
}) {
  return (
    <div style={styles.wrap} role="alert">
      <div style={styles.card}>
        <div style={styles.lock} aria-hidden="true">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="11" width="16" height="10" rx="3" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
        </div>
        <h2 style={styles.title}>{title}</h2>
        <p style={styles.message}>{message}</p>
        {roleName && (
          <p style={styles.hint}>
            Signed in as <strong>{roleName}</strong>. Ask a System Administrator if you need access.
          </p>
        )}
      </div>
    </div>
  );
}

const styles = {
  wrap: {
    display: "flex",
    justifyContent: "center",
    padding: "64px 20px",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  card: {
    maxWidth: 460,
    width: "100%",
    textAlign: "center",
    background: "#fff",
    border: "1px solid #e4e4e8",
    borderRadius: 28,
    padding: "40px 32px",
    boxShadow: "0 2px 0 #d8d8de, 0 18px 40px rgba(20, 20, 50, 0.10)",
  },
  lock: {
    width: 72,
    height: 72,
    margin: "0 auto 18px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
    background: "#fdecec",
    color: "#de0b12",
    boxShadow: "inset 0 -3px 0 rgba(222, 11, 18, 0.18)",
  },
  title: { fontSize: 26, fontWeight: 800, margin: "0 0 8px", color: "#1a1a1a" },
  message: { fontSize: 15, color: "#555", margin: "0 0 12px", lineHeight: 1.5 },
  hint: { fontSize: 13, color: "#777", margin: 0 },
};

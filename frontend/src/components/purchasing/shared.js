// Small helpers and styles shared by the supply-order screens.

export function money(value) {
  return `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatDay(iso) {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso, days) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export const STATUS_STYLES = {
  "Pending approval": { background: "#fff1d6", color: "#8a5300" },
  Ordered: { background: "#eef2fa", color: "#124096" },
  "Partly received": { background: "#f3ecfb", color: "#6a2fa0" },
  Received: { background: "#e3f5e8", color: "#0f6e2b" },
  Rejected: { background: "#fdeceb", color: "#b3261e" },
  Cancelled: { background: "#ececf0", color: "#555" },
};

export const ui = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 50 },
  modal: { background: "#fff", borderRadius: 14, padding: 22, width: "100%", maxWidth: 760, maxHeight: "92vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: "#1a1a1a" },
  head: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  sub: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  close: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  hint: { fontSize: 12, color: "#777", margin: 0, lineHeight: 1.45 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  warnBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  infoBox: { background: "#eef2fa", color: "#1d2f5c", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  field: { display: "flex", flexDirection: "column", gap: 4, minWidth: 0 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  input: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", boxSizing: "border-box", width: "100%" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, flexWrap: "wrap" },
  primary: { whiteSpace: "nowrap", padding: "9px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, background: "#124096", color: "#fff", cursor: "pointer" },
  green: { whiteSpace: "nowrap", padding: "9px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, background: "#129638", color: "#fff", cursor: "pointer" },
  danger: { whiteSpace: "nowrap", padding: "9px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, background: "#de0b12", color: "#fff", cursor: "pointer" },
  secondary: { whiteSpace: "nowrap", padding: "9px 16px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  tag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, whiteSpace: "nowrap" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "7px 8px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3 },
  thRight: { textAlign: "right", padding: "7px 8px", background: "#fafafa", borderBottom: "1px solid #e4e4e8", fontSize: 11, fontWeight: 700, color: "#555", textTransform: "uppercase", letterSpacing: 0.3 },
  td: { padding: "7px 8px", borderBottom: "1px solid #f0f0f2", verticalAlign: "middle" },
  tdRight: { padding: "7px 8px", borderBottom: "1px solid #f0f0f2", verticalAlign: "middle", textAlign: "right", whiteSpace: "nowrap" },
};

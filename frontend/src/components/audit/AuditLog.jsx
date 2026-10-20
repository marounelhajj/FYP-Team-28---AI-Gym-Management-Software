import { Fragment, useEffect, useState } from "react";
import { downloadAuditLogCsv, fetchAuditLog, fetchAuditLogMeta } from "../../api/audit.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

const PAGE_SIZE = 50;
const EMPTY_FILTERS = { user: "", action: "", branch: "", dateFrom: "", dateTo: "" };
const ARROW = "→";
const DASH = "—";

const TARGET_TYPES = {
  member: "member",
  staffaccount: "staff account",
  role: "role",
  membershipplan: "plan",
  branchpromotion: "promotion",
};

// Red for things that went wrong or locked someone out, so they stand out
// when scanning for an incident.
const WARNING_ACTIONS = new Set(["staff.login_failed", "staff.2fa_locked", "staff.deactivated", "member.cancelled"]);

function formatWhen(iso) {
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
  };
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return DASH;
  if (Array.isArray(value)) return value.length ? value.join(", ") : DASH;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Field names come from the API in camelCase ("maxPromoDiscountPercent").
function humanize(key) {
  const words = key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function EntryDetails({ entry }) {
  const { changes, ...rest } = entry.details || {};
  return (
    <div style={styles.details}>
      {changes && Object.keys(changes).length > 0 && (
        <div style={styles.detailBlock}>
          <div style={styles.detailHeading}>Changes</div>
          {Object.entries(changes).map(([field, change]) => (
            <div key={field} style={styles.changeRow}>
              <span style={styles.detailKey}>{humanize(field)}</span>
              {Array.isArray(change) ? (
                <span>
                  <span style={styles.oldValue}>{formatValue(change[0])}</span> {ARROW}{" "}
                  <strong>{formatValue(change[1])}</strong>
                </span>
              ) : (
                <span>
                  {change.added?.length > 0 && <span style={styles.added}>+ {change.added.join(", ")} </span>}
                  {change.removed?.length > 0 && <span style={styles.removed}>{"−"} {change.removed.join(", ")}</span>}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <div style={styles.detailBlock}>
        {Object.entries(rest).map(([key, value]) => (
          <div key={key} style={styles.changeRow}>
            <span style={styles.detailKey}>{humanize(key)}</span>
            <span>{formatValue(value)}</span>
          </div>
        ))}
        {entry.targetLabel && (
          <div style={styles.changeRow}>
            <span style={styles.detailKey}>Affected</span>
            <span>
              {entry.targetLabel} <span style={styles.muted}>({TARGET_TYPES[entry.targetType] || entry.targetType} #{entry.targetId})</span>
            </span>
          </div>
        )}
        <div style={styles.changeRow}>
          <span style={styles.detailKey}>IP address</span>
          <span>{entry.ipAddress || DASH}</span>
        </div>
        <div style={styles.changeRow}>
          <span style={styles.detailKey}>Entry</span>
          <span>#{entry.id}</span>
        </div>
      </div>
    </div>
  );
}

// Audit log viewer for General Managers (and System Administrators, from
// the Admin Console). Read-only: entries are written by the server as
// actions happen (SCRUM-124) and can never be edited or deleted.
//
// User story (SCRUM-125): "As a general manager, I want to search and
// filter the audit log by user, action type, branch and date range, so
// that I can investigate a specific incident."
export default function AuditLog() {
  const [meta, setMeta] = useState({ actionGroups: [], branches: [], users: [] });
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  // The user box is typed into, so it's applied after a short pause rather
  // than on every keystroke.
  const [userInput, setUserInput] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ total: 0, results: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState(null); // { ok: bool, text }
  // Bumped after an export so the list shows the new "Audit log exported" entry.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    fetchAuditLogMeta()
      .then(setMeta)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setFilter("user", userInput.trim()), 300);
    return () => clearTimeout(t);
  }, [userInput]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchAuditLog(filters, { limit: PAGE_SIZE, offset })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filters, offset, reloadKey]);

  function setFilter(key, value) {
    setFilters((f) => (f[key] === value ? f : { ...f, [key]: value }));
    setOffset(0);
    setExpanded(null);
  }

  function clearFilters() {
    setUserInput("");
    setFilters(EMPTY_FILTERS);
    setOffset(0);
    setExpanded(null);
  }

  async function handleExport() {
    setExporting(true);
    setExportMessage(null);
    try {
      const rows = await downloadAuditLogCsv(filters);
      setExportMessage({
        ok: true,
        text: `Downloaded ${rows} ${rows === 1 ? "entry" : "entries"} as CSV. The export itself was added to the log.`,
      });
      setReloadKey((k) => k + 1);
    } catch (err) {
      setExportMessage({ ok: false, text: `Couldn't export: ${err.message}` });
    } finally {
      setExporting(false);
    }
  }

  const hasFilters = Object.values(filters).some(Boolean) || userInput;
  const from = data.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.total);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Audit Log</h1>
          <p style={styles.subtitle}>
            A permanent record of sensitive actions: who did what, when, and at which branch. Entries can't be edited
            or deleted.
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting || loading || data.total === 0}
          style={styles.exportButton}
          title="Download every entry matching the current filters"
        >
          {exporting ? "Exporting..." : "Export CSV"}
        </button>
      </div>

      {exportMessage && (
        <div style={exportMessage.ok ? styles.successBox : styles.errorBox}>{exportMessage.text}</div>
      )}

      <div style={styles.filters}>
        <label style={styles.field}>
          <span style={styles.fieldLabel}>User</span>
          <input
            type="search"
            list="audit-users"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Name or username"
            style={styles.input}
          />
          <datalist id="audit-users">
            {meta.users.map((u) => (
              <option key={u.username} value={u.username}>
                {u.name} ({u.role})
              </option>
            ))}
          </datalist>
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>Action type</span>
          <select value={filters.action} onChange={(e) => setFilter("action", e.target.value)} style={styles.input}>
            <option value="">All actions</option>
            {meta.actionGroups.map((group) => (
              <optgroup key={group.value} label={group.label}>
                {group.actions.length > 1 && <option value={group.value}>All: {group.label}</option>}
                {group.actions.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>Branch</span>
          <select value={filters.branch} onChange={(e) => setFilter("branch", e.target.value)} style={styles.input}>
            <option value="">All branches</option>
            {meta.branches.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>From</span>
          <input
            type="date"
            value={filters.dateFrom}
            max={filters.dateTo || undefined}
            onChange={(e) => setFilter("dateFrom", e.target.value)}
            style={styles.input}
          />
        </label>

        <label style={styles.field}>
          <span style={styles.fieldLabel}>To</span>
          <input
            type="date"
            value={filters.dateTo}
            min={filters.dateFrom || undefined}
            onChange={(e) => setFilter("dateTo", e.target.value)}
            style={styles.input}
          />
        </label>

        <button onClick={clearFilters} disabled={!hasFilters} style={styles.clearButton}>
          Clear filters
        </button>
      </div>

      <div style={styles.countRow}>
        {loading
          ? "Loading..."
          : data.total === 0
            ? "0 entries"
            : `${from}–${to} of ${data.total} ${data.total === 1 ? "entry" : "entries"}`}
      </div>

      {error && <div style={styles.errorBox}>Couldn't load the audit log: {error}</div>}

      {!loading && !error && data.results.length === 0 && (
        <div style={styles.empty}>No entries match these filters.</div>
      )}

      {!error && data.results.length > 0 && (
        <div style={{ ...styles.tableWrap, opacity: loading ? 0.6 : 1 }}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>When</th>
                <th style={styles.th}>User</th>
                <th style={styles.th}>Action</th>
                <th style={styles.th}>What happened</th>
                <th style={styles.th}>Branch</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((entry) => {
                const when = formatWhen(entry.createdAt);
                const open = expanded === entry.id;
                const warning = WARNING_ACTIONS.has(entry.action);
                return (
                  <Fragment key={entry.id}>
                    <tr
                      onClick={() => setExpanded(open ? null : entry.id)}
                      style={{ ...styles.row, ...(open ? styles.rowOpen : null) }}
                      title="Show details"
                    >
                      <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                        <div>{when.date}</div>
                        <div style={styles.muted}>{when.time}</div>
                      </td>
                      <td style={styles.td}>
                        {entry.actorType === "Anonymous" ? (
                          <>
                            <div>{entry.actorUsername || DASH}</div>
                            <div style={styles.muted}>Not signed in</div>
                          </>
                        ) : (
                          <>
                            <div style={styles.actorName}>{entry.actorName}</div>
                            <div style={styles.muted}>
                              {entry.actorUsername && `${entry.actorUsername} · `}
                              {entry.actorRole}
                            </div>
                          </>
                        )}
                      </td>
                      <td style={styles.td}>
                        <span style={{ ...styles.badge, ...(warning ? styles.badgeWarning : null) }}>
                          {entry.actionLabel}
                        </span>
                      </td>
                      <td style={styles.td}>
                        <span style={styles.chevron}>{open ? "▾" : "▸"}</span> {entry.summary}
                      </td>
                      <td style={styles.td}>{entry.branch || <span style={styles.muted}>All</span>}</td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={5} style={styles.detailCell}>
                          <EntryDetails entry={entry} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data.total > PAGE_SIZE && (
        <div style={styles.pager}>
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0 || loading}
            style={styles.pageButton}
          >
            {"←"} Newer
          </button>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={to >= data.total || loading}
            style={styles.pageButton}
          >
            Older {ARROW}
          </button>
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
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: 16,
    marginBottom: 16,
  },
  exportButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  successBox: {
    background: "#e3f5e8",
    color: "#0f6e2b",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  filters: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: 12,
    padding: 14,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    marginBottom: 12,
  },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: "1 1 150px", minWidth: 0 },
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
  clearButton: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    color: "#444",
    cursor: "pointer",
  },
  countRow: { fontSize: 13, color: "#666", marginBottom: 10 },
  empty: { fontSize: 14, color: "#888", padding: "24px 0" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  tableWrap: {
    overflowX: "auto",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
  },
  // Wide enough to stay readable; scrolls inside tableWrap on a phone.
  table: { width: "100%", minWidth: 760, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "top" },
  row: { cursor: "pointer" },
  rowOpen: { background: "#f6f8fc" },
  actorName: { fontWeight: 600 },
  muted: { fontSize: 12, color: "#888" },
  chevron: { color: "#999", fontSize: 12 },
  badge: {
    display: "inline-block",
    fontSize: 12,
    fontWeight: 600,
    padding: "3px 9px",
    borderRadius: 999,
    background: "#eef1f8",
    color: "#124096",
    whiteSpace: "nowrap",
  },
  badgeWarning: { background: "#fdeceb", color: "#b3261e" },
  detailCell: { padding: 0, borderBottom: "1px solid #e4e4e8", background: "#f6f8fc" },
  details: { display: "flex", flexWrap: "wrap", gap: 24, padding: "12px 16px 16px 40px", fontSize: 13 },
  detailBlock: { minWidth: 240 },
  detailHeading: { fontSize: 12, fontWeight: 700, color: "#444", marginBottom: 6 },
  changeRow: { display: "flex", gap: 10, padding: "2px 0" },
  detailKey: { color: "#666", minWidth: 130 },
  oldValue: { color: "#999", textDecoration: "line-through" },
  added: { color: "#129638", fontWeight: 600 },
  removed: { color: "#b3261e", fontWeight: 600 },
  pager: { display: "flex", justifyContent: "space-between", marginTop: 14 },
  pageButton: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
};

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchMembers, fetchMemberFilterOptions } from "../api/members.js";
import RegisterMemberForm from "./RegisterMemberForm.jsx";

const STATUS_STYLES = {
  Active: { bg: "#e6f4ea", fg: "#1e7a34" },
  Frozen: { bg: "#e8f0fe", fg: "#1a56c4" },
  Cancelled: { bg: "#fdeceb", fg: "#b3261e" },
};

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || { bg: "#eee", fg: "#333" };
  return (
    <span
      style={{
        background: style.bg,
        color: style.fg,
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {status}
    </span>
  );
}

export default function MemberDirectory() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [branch, setBranch] = useState("");

  const [filterOptions, setFilterOptions] = useState({ branches: [], statuses: [], plans: [] });
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);

  const debounceRef = useRef(null);

  // Load branch/status/plan options once, from the backend, so this
  // component never hardcodes a list that can drift out of sync with the data.
  useEffect(() => {
    fetchMemberFilterOptions()
      .then(setFilterOptions)
      .catch(() => {
        // Non-fatal: dropdowns just stay empty if this fails, search still works.
      });
  }, []);

  function runSearch() {
    setLoading(true);
    setError(null);
    fetchMembers({ q: query, status, branch, limit: 50 })
      .then((data) => {
        setResults(data.results);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  // Debounced fetch whenever the search text or filters change.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(runSearch, 250); // debounce so we're not hammering the API on every keystroke
    return () => clearTimeout(debounceRef.current);
  }, [query, status, branch]);

  // Auto-dismiss the "member registered" banner after a few seconds.
  useEffect(() => {
    if (!successMessage) return;
    const timer = setTimeout(() => setSuccessMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [successMessage]);

  const hasActiveFilters = useMemo(
    () => Boolean(query || status || branch),
    [query, status, branch]
  );

  function clearFilters() {
    setQuery("");
    setStatus("");
    setBranch("");
  }

  // After a successful walk-in registration: clear any active search/filters
  // so the new member is immediately visible, and refetch right away rather
  // than waiting on the debounce.
  function handleMemberRegistered(member) {
    setShowRegisterForm(false);
    setSuccessMessage(`${member.name} was registered successfully.`);
    clearFilters();
    runSearch();
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Member Directory</h1>
          <p style={styles.subtitle}>
            Search and filter members by name, status, or branch to quickly pull up a record.
          </p>
        </div>
        <button onClick={() => setShowRegisterForm(true)} style={styles.registerButton}>
          + Register New Member
        </button>
      </div>

      {successMessage && <div style={styles.successBox}>{successMessage}</div>}

      <div style={styles.toolbar}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name..."
          aria-label="Search members by name"
          style={styles.searchInput}
        />

        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Filter by membership status"
          style={styles.select}
        >
          <option value="">All statuses</option>
          {filterOptions.statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <select
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          aria-label="Filter by branch"
          style={styles.select}
        >
          <option value="">All branches</option>
          {filterOptions.branches.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>

        {hasActiveFilters && (
          <button onClick={clearFilters} style={styles.clearButton}>
            Clear filters
          </button>
        )}
      </div>

      <div style={styles.resultsMeta}>
        {loading ? "Searching..." : `${total} member${total === 1 ? "" : "s"} found`}
      </div>

      {error && <div style={styles.errorBox}>Couldn't load members: {error}</div>}

      {!error && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Branch</th>
                <th style={styles.th}>Plan</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Member Since</th>
              </tr>
            </thead>
            <tbody>
              {!loading && results.length === 0 && (
                <tr>
                  <td colSpan={6} style={styles.emptyCell}>
                    No members match your search.
                  </td>
                </tr>
              )}
              {results.map((m) => (
                <tr key={m.id} style={styles.row}>
                  <td style={styles.td}>
                    <span style={styles.nameCell}>{m.name}</span>
                  </td>
                  <td style={styles.td}>{m.email}</td>
                  <td style={styles.td}>{m.branch}</td>
                  <td style={styles.td}>{m.membershipPlan}</td>
                  <td style={styles.td}>
                    <StatusBadge status={m.status} />
                  </td>
                  <td style={styles.td}>{m.joinDate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showRegisterForm && (
        <RegisterMemberForm
          filterOptions={filterOptions}
          onClose={() => setShowRegisterForm(false)}
          onRegistered={handleMemberRegistered}
        />
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1000,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    marginBottom: 20,
  },
  title: { fontSize: 24, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  registerButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    background: "#1a56c4",
    color: "#fff",
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  successBox: {
    background: "#e6f4ea",
    color: "#1e7a34",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
    marginBottom: 14,
  },
  toolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 14,
  },
  searchInput: {
    flex: "1 1 240px",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
  },
  select: {
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    minWidth: 150,
  },
  clearButton: {
    padding: "10px 14px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  resultsMeta: { fontSize: 13, color: "#666", marginBottom: 10 },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
  },
  tableWrap: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "hidden",
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 14px",
    background: "#fafafa",
    borderBottom: "1px solid #e4e4e8",
    fontWeight: 600,
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: 0.3,
    color: "#555",
  },
  td: {
    padding: "10px 14px",
    borderBottom: "1px solid #f0f0f2",
  },
  row: {},
  nameCell: { fontWeight: 600 },
  emptyCell: {
    padding: "28px 14px",
    textAlign: "center",
    color: "#888",
  },
};

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchStaff, fetchRoles, updateStaffAccount } from "../../api/admin.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import StaffAccountForm from "./StaffAccountForm.jsx";

function ActiveBadge({ isActive }) {
  const style = isActive ? BUTTON_COLORS.green : BUTTON_COLORS.red;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        height: 22,
        width: 76,
        background: style.background,
        color: style.color,
        padding: "0 10px",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {isActive ? "Active" : "Inactive"}
    </span>
  );
}

// User story: "As a system administrator, I want to create, edit and
// deactivate staff login accounts, so that only current staff can sign in
// to the system."
export default function StaffAccounts() {
  const [query, setQuery] = useState("");
  const [roleId, setRoleId] = useState("");
  const [isActive, setIsActive] = useState("");

  const [roles, setRoles] = useState([]);
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or an account object
  const [pendingToggleId, setPendingToggleId] = useState(null);

  const debounceRef = useRef(null);

  useEffect(() => {
    fetchRoles()
      .then(setRoles)
      .catch(() => {});
  }, []);

  function runSearch() {
    setLoading(true);
    setError(null);
    fetchStaff({ q: query, roleId, isActive })
      .then((data) => {
        setResults(data.results);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(runSearch, 250);
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, roleId, isActive]);

  const hasActiveFilters = useMemo(
    () => Boolean(query || roleId || isActive),
    [query, roleId, isActive]
  );

  function clearFilters() {
    setQuery("");
    setRoleId("");
    setIsActive("");
  }

  function handleSaved() {
    setFormTarget(null);
    runSearch();
  }

  async function toggleActive(account) {
    setPendingToggleId(account.id);
    try {
      await updateStaffAccount(account.id, { isActive: !account.isActive });
      runSearch();
    } catch (err) {
      setError(err.message);
    } finally {
      setPendingToggleId(null);
    }
  }

  return (
    <div>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Staff Accounts</h2>
          <p style={styles.subtitle}>
            Create, edit, and deactivate the login accounts staff use to access the system.
          </p>
        </div>
        <button onClick={() => setFormTarget("new")} style={styles.newButton}>
          + New Staff Account
        </button>
      </div>

      <div style={styles.toolbar}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name..."
          aria-label="Search staff by name"
          style={styles.searchInput}
        />

        <select
          value={roleId}
          onChange={(e) => setRoleId(e.target.value)}
          aria-label="Filter by role"
          style={styles.select}
        >
          <option value="">All roles</option>
          {roles.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>

        <select
          value={isActive}
          onChange={(e) => setIsActive(e.target.value)}
          aria-label="Filter by status"
          style={styles.select}
        >
          <option value="">All statuses</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>

        {hasActiveFilters && (
          <button onClick={clearFilters} style={styles.clearButton}>
            Clear filters
          </button>
        )}
      </div>

      <div style={styles.resultsMeta}>
        {loading ? "Searching..." : `${total} account${total === 1 ? "" : "s"} found`}
      </div>

      {error && <div style={styles.errorBox}>Couldn't load staff accounts: {error}</div>}

      {!error && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Username</th>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Job Title</th>
                <th style={styles.th}>Role</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {!loading && results.length === 0 && (
                <tr>
                  <td colSpan={7} style={styles.emptyCell}>
                    No staff accounts match your search.
                  </td>
                </tr>
              )}
              {results.map((s) => (
                <tr key={s.id}>
                  <td style={styles.td}>{s.fullName}</td>
                  <td style={styles.td}>{s.username}</td>
                  <td style={styles.td}>{s.email}</td>
                  <td style={styles.td}>{s.jobTitle}</td>
                  <td style={styles.td}>{s.roleName}</td>
                  <td style={styles.td}>
                    <ActiveBadge isActive={s.isActive} />
                  </td>
                  <td style={{ ...styles.td, textAlign: "right", whiteSpace: "nowrap" }}>
                    <button onClick={() => setFormTarget(s)} style={styles.editButton}>
                      Edit
                    </button>
                    <button
                      onClick={() => toggleActive(s)}
                      disabled={pendingToggleId === s.id}
                      style={s.isActive ? styles.deactivateButton : styles.reactivateButton}
                    >
                      {pendingToggleId === s.id ? "..." : s.isActive ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {formTarget && (
        <StaffAccountForm
          account={formTarget === "new" ? null : formTarget}
          roles={roles}
          onClose={() => setFormTarget(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}

const styles = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    marginBottom: 20,
  },
  title: { fontSize: 20, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  newButton: {
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
  emptyCell: {
    padding: "28px 14px",
    textAlign: "center",
    color: "#888",
  },
  editButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
    marginRight: 8,
  },
  deactivateButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
  reactivateButton: {
    padding: "6px 12px",
    fontSize: 13,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.green,
    fontWeight: 600,
    cursor: "pointer",
  },
};

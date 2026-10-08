import { useEffect, useState } from "react";
import { fetchRoles, fetchPermissions } from "../../api/admin.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import RoleForm from "./RoleForm.jsx";

function PermissionChip({ label }) {
  return <span style={styles.chip}>{label}</span>;
}

// User story: "As a system administrator, I want to define roles with
// specific permission sets, so that access matches each job function."
export default function RoleManager() {
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [formTarget, setFormTarget] = useState(null); // null = closed, "new", or a role object

  const permissionLabel = (key) => permissions.find((p) => p.key === key)?.label || key;

  function loadRoles() {
    setLoading(true);
    setError(null);
    fetchRoles()
      .then(setRoles)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadRoles();
    fetchPermissions()
      .then(setPermissions)
      .catch(() => {});
  }, []);

  function handleSaved() {
    setFormTarget(null);
    loadRoles();
  }

  return (
    <div>
      <div style={styles.header}>
        <div>
          <h2 style={styles.title}>Roles & Permissions</h2>
          <p style={styles.subtitle}>
            Define what each role can access, so staff accounts only see what their job requires.
          </p>
        </div>
        <button onClick={() => setFormTarget("new")} style={styles.newButton}>
          + New Role
        </button>
      </div>

      {loading && <div style={styles.meta}>Loading roles...</div>}
      {error && <div style={styles.errorBox}>Couldn't load roles: {error}</div>}

      {!loading && !error && (
        <div style={styles.grid}>
          {roles.map((role) => (
            <div key={role.id} style={styles.card}>
              <div style={styles.cardHeader}>
                <h3 style={styles.cardTitle}>{role.name}</h3>
                <button onClick={() => setFormTarget(role)} style={styles.editButton}>
                  Edit
                </button>
              </div>
              {role.description && <p style={styles.cardDescription}>{role.description}</p>}
              <div style={styles.chipRow}>
                {role.permissions.length === 0 && <span style={styles.noPermissions}>No permissions granted</span>}
                {role.permissions.map((key) => (
                  <PermissionChip key={key} label={permissionLabel(key)} />
                ))}
              </div>
              <div style={styles.staffCount}>
                {role.staffCount} staff account{role.staffCount === 1 ? "" : "s"} assigned
              </div>
            </div>
          ))}
        </div>
      )}

      {formTarget && (
        <RoleForm
          role={formTarget === "new" ? null : formTarget}
          permissions={permissions}
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
  meta: { fontSize: 13, color: "#666" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 14,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 14,
  },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    padding: 16,
    background: "#fff",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  cardTitle: { fontSize: 16, fontWeight: 700, margin: 0 },
  cardDescription: { fontSize: 13, color: "#666", margin: "6px 0 12px" },
  editButton: {
    flexShrink: 0,
    padding: "5px 10px",
    fontSize: 12,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  chipRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 10,
    minHeight: 24,
  },
  chip: {
    fontSize: 12,
    fontWeight: 600,
    padding: "3px 9px",
    borderRadius: 999,
    background: "#eef1f8",
    color: "#124096",
  },
  noPermissions: { fontSize: 12, color: "#999", fontStyle: "italic" },
  staffCount: { fontSize: 12, color: "#888", marginTop: 14 },
};

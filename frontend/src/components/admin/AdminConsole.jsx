import { useState } from "react";
import StaffAccounts from "./StaffAccounts.jsx";
import RoleManager from "./RoleManager.jsx";
import AccessDenied from "../AccessDenied.jsx";

// Each tab needs its own permission, so a role that only has one of the two
// (e.g. manage_roles without manage_staff_accounts) sees just that tab.
const TABS = [
  { key: "staff", label: "Staff Accounts", permission: "manage_staff_accounts", render: () => <StaffAccounts /> },
  { key: "roles", label: "Roles & Permissions", permission: "manage_roles", render: () => <RoleManager /> },
];

// System Administrator persona shell. Deliberately styled very differently
// from the receptionist's Member Directory (dark banner vs. light page, a
// distinct "ADMIN" tag) so it's unmistakable which persona's screen is on
// screen - admin screens touch staff access, not member data.
export default function AdminConsole({ permissions = [] }) {
  const tabs = TABS.filter((t) => permissions.includes(t.permission));
  const [tabKey, setTabKey] = useState(null);
  const activeTab = tabs.find((t) => t.key === tabKey) || tabs[0];

  if (!activeTab) return <AccessDenied />;

  return (
    <div>
      <div style={styles.banner}>
        <span style={styles.adminTag}>ADMIN</span>
        <div>
          <h1 style={styles.bannerTitle}>System Administrator Console</h1>
          <p style={styles.bannerSubtitle}>Manage staff access: accounts, roles, and permissions.</p>
        </div>
      </div>

      <div style={styles.tabBar}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTabKey(t.key)}
            style={activeTab.key === t.key ? styles.tabActive : styles.tab}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={styles.body}>{activeTab.render()}</div>
    </div>
  );
}

const styles = {
  banner: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    background: "#1a1a2e",
    color: "#fff",
    padding: "20px 24px",
    borderRadius: 10,
    marginBottom: 20,
  },
  adminTag: {
    flexShrink: 0,
    background: "#de0b12",
    color: "#fff",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 1,
    padding: "4px 10px",
    borderRadius: 6,
  },
  bannerTitle: { fontSize: 20, fontWeight: 700, margin: 0 },
  bannerSubtitle: { fontSize: 13, color: "#c6c6d8", margin: "4px 0 0" },
  tabBar: {
    display: "flex",
    gap: 8,
    marginBottom: 20,
    borderBottom: "1px solid #e4e4e8",
  },
  tab: {
    padding: "10px 16px",
    fontSize: 14,
    fontWeight: 600,
    border: "none",
    borderBottom: "2px solid transparent",
    background: "transparent",
    color: "#666",
    cursor: "pointer",
  },
  tabActive: {
    padding: "10px 16px",
    fontSize: 14,
    fontWeight: 600,
    border: "none",
    borderBottom: "2px solid #124096",
    background: "transparent",
    color: "#124096",
    cursor: "pointer",
  },
  body: {},
};

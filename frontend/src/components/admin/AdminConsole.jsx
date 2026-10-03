import { useState } from "react";
import StaffAccounts from "./StaffAccounts.jsx";
import RoleManager from "./RoleManager.jsx";

const TABS = [
  { key: "staff", label: "Staff Accounts" },
  { key: "roles", label: "Roles & Permissions" },
];

// System Administrator persona shell. Deliberately styled very differently
// from the receptionist's Member Directory (dark banner vs. light page, a
// distinct "ADMIN" tag) so it's unmistakable which persona's screen is on
// screen - admin screens touch staff access, not member data.
export default function AdminConsole() {
  const [tab, setTab] = useState("staff");

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
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={tab === t.key ? styles.tabActive : styles.tab}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={styles.body}>{tab === "staff" ? <StaffAccounts /> : <RoleManager />}</div>
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

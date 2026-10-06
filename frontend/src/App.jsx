import { useEffect, useState } from "react";
import { fetchCurrentUser, logout } from "./api/auth.js";
import MemberDirectory from "./components/MemberDirectory.jsx";
import AdminConsole from "./components/admin/AdminConsole.jsx";
import PlanManager from "./components/plans/PlanManager.jsx";
import PromotionManager from "./components/plans/PromotionManager.jsx";
import LoginPage from "./components/LoginPage.jsx";
import Logo from "./components/Logo.jsx";

// Which screens a logged-in account can open are resolved from their actual
// permissions (set by a System Administrator via Admin Console -> Roles),
// not chosen by the user - see LoginPage.jsx and administration/auth_views.py
// for why.
function canAccessAdminConsole(account) {
  return account.permissions.includes("manage_staff_accounts") || account.permissions.includes("manage_roles");
}

// Everyone except system administrators gets one tab per screen their role
// allows (e.g. a General Manager sees Plans + Promotions, a Branch Manager
// sees Members + Promotions, a Receptionist just Members - no tab bar).
function availableScreens(account) {
  const has = (p) => account.permissions.includes(p);
  const screens = [];
  if (has("manage_membership_plans")) {
    screens.push({ key: "plans", label: "Plans & Pricing", render: () => <PlanManager /> });
  }
  if (has("manage_branch_promotions") || has("manage_membership_plans")) {
    screens.push({ key: "promotions", label: "Branch Promotions", render: () => <PromotionManager /> });
  }
  if (has("manage_members") || screens.length === 0) {
    screens.push({ key: "members", label: "Member Directory", render: () => <MemberDirectory /> });
  }
  return screens;
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [screenKey, setScreenKey] = useState(null);

  // Restore an existing session on page load/refresh, so logging in isn't
  // required every time the page reloads.
  useEffect(() => {
    fetchCurrentUser()
      .then(setAccount)
      .finally(() => setCheckingSession(false));
  }, []);

  async function handleLogout() {
    await logout();
    setAccount(null);
    setScreenKey(null);
  }

  if (checkingSession) {
    return <div style={styles.loadingScreen}>Loading...</div>;
  }

  if (!account) {
    return <LoginPage onLoggedIn={setAccount} />;
  }

  const isAdmin = canAccessAdminConsole(account);
  const screens = isAdmin ? [] : availableScreens(account);
  const activeScreen = screens.find((s) => s.key === screenKey) || screens[0];

  return (
    <div>
      <div style={styles.topBar}>
        <Logo size={34} />
        <div style={styles.userGroup}>
          <div style={styles.userInfo}>
            <div style={styles.userName}>{account.fullName}</div>
            <div style={styles.userRole}>{account.roleName}</div>
          </div>
          <button onClick={handleLogout} style={styles.logoutButton}>
            Log out
          </button>
        </div>
      </div>

      {screens.length > 1 && (
        <nav style={styles.navBar}>
          {screens.map((s) => (
            <button
              key={s.key}
              onClick={() => setScreenKey(s.key)}
              style={s.key === activeScreen.key ? styles.navTabActive : styles.navTab}
            >
              {s.label}
            </button>
          ))}
        </nav>
      )}

      {isAdmin ? <AdminConsole /> : activeScreen.render()}
    </div>
  );
}

const styles = {
  loadingScreen: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#666",
  },
  topBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "10px 20px",
    background: "#f0f0f3",
    borderBottom: "1px solid #e0e0e5",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  userGroup: {
    display: "flex",
    alignItems: "center",
    gap: 14,
  },
  userInfo: { textAlign: "right", lineHeight: 1.25 },
  userName: { fontSize: 13, fontWeight: 700, color: "#1a1a1a" },
  userRole: { fontSize: 12, color: "#666" },
  navBar: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    padding: "0 20px",
    background: "#fff",
    borderBottom: "1px solid #e4e4e8",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  navTab: {
    padding: "12px 14px",
    fontSize: 14,
    fontWeight: 600,
    border: "none",
    borderBottom: "2px solid transparent",
    background: "transparent",
    color: "#666",
    cursor: "pointer",
  },
  navTabActive: {
    padding: "12px 14px",
    fontSize: 14,
    fontWeight: 600,
    border: "none",
    borderBottom: "2px solid #124096",
    background: "transparent",
    color: "#124096",
    cursor: "pointer",
  },
  logoutButton: {
    padding: "6px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 999,
    background: "#fff",
    color: "#444",
    cursor: "pointer",
  },
};

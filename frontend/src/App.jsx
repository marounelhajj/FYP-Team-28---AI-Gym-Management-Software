import { useEffect, useState } from "react";
import { fetchCurrentUser, logout } from "./api/auth.js";
import MemberDirectory from "./components/MemberDirectory.jsx";
import AdminConsole from "./components/admin/AdminConsole.jsx";
import LoginPage from "./components/LoginPage.jsx";
import Logo from "./components/Logo.jsx";

// Which screen a logged-in account lands on is resolved from their actual
// permissions (set by a System Administrator via Admin Console -> Roles),
// not chosen by the user - see LoginPage.jsx and administration/auth_views.py
// for why.
function canAccessAdminConsole(account) {
  return account.permissions.includes("manage_staff_accounts") || account.permissions.includes("manage_roles");
}

export default function App() {
  const [account, setAccount] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

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
  }

  if (checkingSession) {
    return <div style={styles.loadingScreen}>Loading...</div>;
  }

  if (!account) {
    return <LoginPage onLoggedIn={setAccount} />;
  }

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

      {canAccessAdminConsole(account) ? <AdminConsole /> : <MemberDirectory />}
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

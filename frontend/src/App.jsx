import { useEffect, useState } from "react";
import { fetchCurrentUser, logout } from "./api/auth.js";
import { fetchCurrentMember, logoutMember } from "./api/memberAuth.js";
import MemberDirectory from "./components/MemberDirectory.jsx";
import AdminConsole from "./components/admin/AdminConsole.jsx";
import LoginPage from "./components/LoginPage.jsx";
import WelcomeScreen from "./components/WelcomeScreen.jsx";
import MemberLoginPage from "./components/member/MemberLoginPage.jsx";
import MemberSignupPage from "./components/member/MemberSignupPage.jsx";
import MemberDashboard from "./components/member/MemberDashboard.jsx";
import Logo from "./components/Logo.jsx";

// Which screen a logged-in STAFF account lands on is resolved from their
// actual permissions (set by a System Administrator via Admin Console ->
// Roles), not chosen by the user - see LoginPage.jsx and
// administration/auth_views.py for why. Members are a separate account
// type entirely (members/auth_views.py) with no roles/permissions - they
// always land on MemberDashboard.
function canAccessAdminConsole(account) {
  return account.permissions.includes("manage_staff_accounts") || account.permissions.includes("manage_roles");
}

function destinationLabel(account) {
  return canAccessAdminConsole(account) ? "the System Administrator Console" : "the Member Directory";
}

export default function App() {
  // session is null (logged out) or { type: "staff" | "member", data }.
  const [session, setSession] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  // Which logged-out screen to show. Staff sign-in is the default landing
  // screen; members get there via the "Gym member?" link.
  const [authScreen, setAuthScreen] = useState("staffLogin");
  // True only right after an explicit staff login action (not a restored
  // session on page refresh) - triggers the one-time welcome screen so it
  // never gets in the way on a normal reload. Members skip this screen:
  // MemberDashboard already opens with "Welcome, {name}", so there's no
  // role ambiguity left to clarify the way there was for staff.
  const [justLoggedIn, setJustLoggedIn] = useState(false);

  // Restore an existing session on page load/refresh, so logging in isn't
  // required every time the page reloads. Staff and member sessions use
  // separate cookies server-side, so check both.
  useEffect(() => {
    fetchCurrentUser()
      .then((account) => {
        if (account) {
          setSession({ type: "staff", data: account });
          return null;
        }
        return fetchCurrentMember();
      })
      .then((member) => {
        if (member) setSession({ type: "member", data: member });
      })
      .finally(() => setCheckingSession(false));
  }, []);

  function handleStaffLoggedIn(account) {
    setSession({ type: "staff", data: account });
    setJustLoggedIn(true);
  }

  function handleMemberLoggedIn(member) {
    setSession({ type: "member", data: member });
  }

  async function handleLogout() {
    if (session?.type === "staff") {
      await logout();
    } else if (session?.type === "member") {
      await logoutMember();
    }
    setSession(null);
    setAuthScreen("staffLogin");
  }

  if (checkingSession) {
    return <div style={styles.loadingScreen}>Loading...</div>;
  }

  if (!session) {
    if (authScreen === "memberLogin") {
      return (
        <MemberLoginPage
          onLoggedIn={handleMemberLoggedIn}
          onSwitchToSignup={() => setAuthScreen("memberSignup")}
          onSwitchToStaff={() => setAuthScreen("staffLogin")}
        />
      );
    }
    if (authScreen === "memberSignup") {
      return (
        <MemberSignupPage
          onSignedUp={handleMemberLoggedIn}
          onSwitchToLogin={() => setAuthScreen("memberLogin")}
          onSwitchToStaff={() => setAuthScreen("staffLogin")}
        />
      );
    }
    return <LoginPage onLoggedIn={handleStaffLoggedIn} onSwitchToMember={() => setAuthScreen("memberLogin")} />;
  }

  if (session.type === "staff" && justLoggedIn) {
    return (
      <WelcomeScreen
        account={session.data}
        destination={destinationLabel(session.data)}
        onContinue={() => setJustLoggedIn(false)}
      />
    );
  }

  const isStaff = session.type === "staff";

  return (
    <div>
      <div style={styles.topBar}>
        <Logo size={34} />
        <div style={styles.userGroup}>
          <div style={styles.userInfo}>
            <div style={styles.userName}>{session.data.fullName || session.data.name}</div>
            <div style={styles.userRole}>{isStaff ? session.data.roleName : "Member"}</div>
          </div>
          <button onClick={handleLogout} style={styles.logoutButton}>
            Log out
          </button>
        </div>
      </div>

      {isStaff ? (
        canAccessAdminConsole(session.data) ? <AdminConsole /> : <MemberDirectory />
      ) : (
        <MemberDashboard member={session.data} />
      )}
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

import { useEffect, useState } from "react";
import { fetchCurrentUser, logout } from "./api/auth.js";
import { fetchCurrentMember, logoutMember } from "./api/memberAuth.js";
import MemberDirectory from "./components/MemberDirectory.jsx";
import AdminConsole from "./components/admin/AdminConsole.jsx";
import CheckIn from "./components/CheckIn.jsx";
import PlanManager from "./components/plans/PlanManager.jsx";
import PromotionManager from "./components/plans/PromotionManager.jsx";
import AuditLog from "./components/audit/AuditLog.jsx";
import RetentionReport from "./components/audit/RetentionReport.jsx";
import HeadcountDashboard from "./components/headcount/HeadcountDashboard.jsx";
import LoginPage from "./components/LoginPage.jsx";
import WelcomeScreen from "./components/WelcomeScreen.jsx";
import MemberLoginPage from "./components/member/MemberLoginPage.jsx";
import MemberSignupPage from "./components/member/MemberSignupPage.jsx";
import MemberDashboard from "./components/member/MemberDashboard.jsx";
import PlanBrowser from "./components/member/PlanBrowser.jsx";
import Logo from "./components/Logo.jsx";
import AccessDenied from "./components/AccessDenied.jsx";

// Which screens a logged-in STAFF account can open are resolved from their
// actual permissions (set by a System Administrator via Admin Console ->
// Roles), not chosen by the user - see LoginPage.jsx and
// administration/auth_views.py for why. Members are a separate account
// type entirely (members/auth_views.py) with no roles/permissions - they
// always land on MemberDashboard.
function canAccessAdminConsole(account) {
  return account.permissions.includes("manage_staff_accounts") || account.permissions.includes("manage_roles");
}

// Every staff account except system administrators gets one tab per screen
// their role allows (e.g. a General Manager sees Plans + Promotions, a
// Branch Manager sees Members + Promotions + Check-In, a Receptionist sees
// Members + Check-In - both gated on manage_members since checking a
// member in/out is part of the same front-desk job as the directory).
function availableScreens(account) {
  const has = (p) => account.permissions.includes(p);
  const screens = [];
  if (has("manage_membership_plans")) {
    screens.push({ key: "plans", label: "Plans & Pricing", render: () => <PlanManager /> });
  }
  if (has("manage_branch_promotions") || has("manage_membership_plans")) {
    screens.push({ key: "promotions", label: "Branch Promotions", render: () => <PromotionManager /> });
  }
  if (has("manage_members")) {
    screens.push({ key: "members", label: "Member Directory", render: () => <MemberDirectory /> });
    screens.push({ key: "checkin", label: "Check-In", render: () => <CheckIn /> });
  }
  // SCRUM-127: Branch Managers see their own branch, General Managers any.
  if (has("view_branch_headcount")) {
    screens.push({ key: "headcount", label: "Live Headcount", render: () => <HeadcountDashboard /> });
  }
  if (has("view_audit_log")) {
    screens.push({ key: "audit", label: "Audit Log", render: () => <AuditLog /> });
  }
  if (has("view_audit_log")) {
    screens.push({ key: "retention", label: "Retention", render: () => <RetentionReport /> });
  }
  // A role allowed to manage staff accounts on top of its own screens -
  // e.g. a General Manager managing staff and trainer profiles per branch
  // (SCRUM-103) - keeps those screens and gets the staff console as one
  // more tab. Anyone who can define roles is a System Administrator and
  // lands on the full console instead (see isSystemAdmin).
  if (screens.length > 0 && has("manage_staff_accounts") && !has("manage_roles")) {
    screens.push({
      key: "staff",
      label: "Staff & Trainers",
      render: () => <AdminConsole permissions={account.permissions} embedded />,
    });
  }
  return screens;
}

function isSystemAdmin(account) {
  return (
    account.permissions.includes("manage_roles") ||
    (canAccessAdminConsole(account) && availableScreens(account).length === 0)
  );
}

function destinationLabel(account) {
  if (isSystemAdmin(account)) return "the System Administrator Console";
  const first = availableScreens(account)[0];
  if (!first) return "your account (no pages are assigned to your role yet)";
  return first.key === "members" ? "the Member Directory" : first.label;
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
  // Which staff tab is open (see availableScreens). null = the first one.
  const [screenKey, setScreenKey] = useState(null);
  // Plan + branch a prospective member picked on PlanBrowser, carried into
  // the signup form (and back, if they return to compare plans).
  const [signupSelection, setSignupSelection] = useState(null);

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

  // Any API call that comes back 401 (session expired, or the account was
  // deactivated while logged in) sends the user back to the login screen.
  useEffect(() => {
    function onAuthExpired() {
      setSession(null);
      setScreenKey(null);
      setAuthScreen("staffLogin");
    }
    window.addEventListener("auth:expired", onAuthExpired);
    return () => window.removeEventListener("auth:expired", onAuthExpired);
  }, []);

  function handleStaffLoggedIn(account) {
    setSession({ type: "staff", data: account });
    setJustLoggedIn(true);
  }

  function handleMemberLoggedIn(member) {
    setSession({ type: "member", data: member });
    setSignupSelection(null);
  }

  async function handleLogout() {
    if (session?.type === "staff") {
      await logout();
    } else if (session?.type === "member") {
      await logoutMember();
    }
    setSession(null);
    setScreenKey(null);
    setAuthScreen("staffLogin");
  }

  if (checkingSession) {
    return <div style={styles.loadingScreen}>Loading...</div>;
  }

  if (!session) {
    const browsePlans = () => setAuthScreen("browsePlans");

    if (authScreen === "browsePlans") {
      return (
        <PlanBrowser
          initialBranch={signupSelection?.branch}
          onChoosePlan={(selection) => {
            setSignupSelection(selection);
            setAuthScreen("memberSignup");
          }}
          onSwitchToLogin={() => setAuthScreen("memberLogin")}
          onSwitchToStaff={() => setAuthScreen("staffLogin")}
        />
      );
    }
    if (authScreen === "memberLogin") {
      return (
        <MemberLoginPage
          onLoggedIn={handleMemberLoggedIn}
          onSwitchToSignup={() => {
            setSignupSelection(null);
            setAuthScreen("memberSignup");
          }}
          onSwitchToStaff={() => setAuthScreen("staffLogin")}
          onBrowsePlans={browsePlans}
        />
      );
    }
    if (authScreen === "memberSignup") {
      return (
        <MemberSignupPage
          initialSelection={signupSelection}
          onSignedUp={handleMemberLoggedIn}
          onSwitchToLogin={() => setAuthScreen("memberLogin")}
          onSwitchToStaff={() => setAuthScreen("staffLogin")}
          onBrowsePlans={browsePlans}
        />
      );
    }
    return (
      <LoginPage
        onLoggedIn={handleStaffLoggedIn}
        onSwitchToMember={() => setAuthScreen("memberLogin")}
        onBrowsePlans={browsePlans}
      />
    );
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
  const isAdmin = isStaff && isSystemAdmin(session.data);
  const screens = isStaff && !isAdmin ? availableScreens(session.data) : [];
  const activeScreen = screens.find((s) => s.key === screenKey) || screens[0];

  let content;
  if (!isStaff) content = <MemberDashboard member={session.data} />;
  else if (isAdmin) content = <AdminConsole permissions={session.data.permissions} />;
  else if (activeScreen) content = activeScreen.render();
  else {
    content = (
      <AccessDenied
        title="No pages assigned"
        message="Your role doesn't have access to any screens yet."
        roleName={session.data.roleName}
      />
    );
  }

  return (
    <div>
      <div style={styles.topBar}>
        <Logo size={52} />
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

      {screens.length > 1 && (
        <nav style={styles.navBar}>
          {screens.map((s) => (
            <button
              key={s.key}
              onClick={() => setScreenKey(s.key)}
              style={s.key === activeScreen?.key ? styles.navTabActive : styles.navTab}
            >
              {s.label}
            </button>
          ))}
        </nav>
      )}

      {content}
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
    padding: "12px 20px",
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

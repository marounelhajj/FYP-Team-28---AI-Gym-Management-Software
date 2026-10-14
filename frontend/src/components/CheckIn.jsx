import { useEffect, useRef, useState } from "react";
import { checkIn, checkOut, fetchRecentCheckIns } from "../api/checkins.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";

const RESULT_DISPLAY_MS = 3000;

// User story: "As a receptionist, I want to check in members via QR code
// or membership ID, so that I can quickly verify membership status and
// control entry."
//
// Membership ID is just the member's existing id - there's no separate
// member-number field. "QR code" is typed/pasted entry for now (the same
// field works for a scanned code once a real scanner exists, since it
// would decode to this same ID before being submitted here) - see
// backend/checkins/views.py for why.
//
// Check-in and check-out share one open/closed session per member
// (backend/checkins/models.py CheckIn.checked_out_at): you can't check in
// while already checked in, can't check out without having checked in,
// and only an Active member can do either - all enforced server-side,
// this screen just surfaces whatever comes back.
export default function CheckIn() {
  const [membershipId, setMembershipId] = useState("");
  const [submittingAction, setSubmittingAction] = useState(null); // "checkin" | "checkout" | null
  const [result, setResult] = useState(null); // { action, ok, member?, checkIn?, error? }
  const [recent, setRecent] = useState([]);
  const inputRef = useRef(null);
  const dismissTimer = useRef(null);

  function loadRecent() {
    fetchRecentCheckIns()
      .then((data) => setRecent(data.results))
      .catch(() => {
        // Non-fatal: the recent-activity list just stays empty/stale.
      });
  }

  useEffect(() => {
    loadRecent();
    return () => clearTimeout(dismissTimer.current);
  }, []);

  function showResult(data) {
    setResult(data);
    clearTimeout(dismissTimer.current);
    dismissTimer.current = setTimeout(() => setResult(null), RESULT_DISPLAY_MS);
  }

  async function handleAction(action) {
    if (!membershipId) return;
    setSubmittingAction(action);

    try {
      const data = action === "checkin" ? await checkIn(membershipId) : await checkOut(membershipId);
      showResult({ action, ok: true, ...data });
    } catch (err) {
      showResult({ action, ok: false, error: err.message });
    } finally {
      setSubmittingAction(null);
      setMembershipId("");
      loadRecent();
      inputRef.current?.focus();
    }
  }

  const cardStyle = !result
    ? null
    : result.ok && (result.action === "checkin" ? result.checkIn.result === "Allowed" : true)
    ? styles.allowedCard
    : styles.deniedCard;

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Member Check-In</h1>
      <p style={styles.subtitle}>Enter a membership ID or scan a QR code to verify status and control entry.</p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleAction("checkin");
        }}
        style={styles.form}
      >
        <input
          ref={inputRef}
          type="text"
          inputMode="numeric"
          value={membershipId}
          onChange={(e) => setMembershipId(e.target.value)}
          placeholder="Membership ID or scan QR..."
          aria-label="Membership ID"
          style={styles.input}
          autoFocus
        />
        <button type="submit" disabled={Boolean(submittingAction) || !membershipId} style={styles.checkInButton}>
          {submittingAction === "checkin" ? "Checking in..." : "Check In"}
        </button>
        <button
          type="button"
          onClick={() => handleAction("checkout")}
          disabled={Boolean(submittingAction) || !membershipId}
          style={styles.checkOutButton}
        >
          {submittingAction === "checkout" ? "Checking out..." : "Check Out"}
        </button>
      </form>

      {result && (
        <div style={cardStyle}>
          {result.ok ? (
            result.action === "checkin" ? (
              result.checkIn.result === "Allowed" ? (
                <>
                  <div style={styles.resultHeadline}>Welcome, {result.member.name}!</div>
                  <div style={styles.resultDetail}>
                    {result.member.membershipPlan} plan &middot; {result.member.branch}
                  </div>
                </>
              ) : (
                <>
                  <div style={styles.resultHeadline}>Entry denied</div>
                  <div style={styles.resultDetail}>
                    {result.checkIn.reason === "Already checked in"
                      ? `${result.member.name} is already checked in.`
                      : `${result.member.name}'s membership is ${result.checkIn.reason}.`}
                  </div>
                </>
              )
            ) : (
              <>
                <div style={styles.resultHeadline}>Goodbye, {result.member.name}!</div>
                <div style={styles.resultDetail}>Stayed for {result.checkIn.duration}.</div>
              </>
            )
          ) : (
            <>
              <div style={styles.resultHeadline}>{result.action === "checkin" ? "Couldn't check in" : "Couldn't check out"}</div>
              <div style={styles.resultDetail}>{result.error}</div>
            </>
          )}
        </div>
      )}

      <h2 style={styles.recentTitle}>Recent Check-Ins</h2>
      {recent.length === 0 ? (
        <p style={styles.emptyText}>No check-ins yet.</p>
      ) : (
        <div style={styles.recentList}>
          {recent.map((c) => (
            <div key={c.id} style={styles.recentRow}>
              <span style={styles.recentName}>{c.memberName}</span>
              <span style={c.result === "Allowed" ? styles.badgeAllowed : styles.badgeDenied}>
                {c.result === "Allowed" ? (c.duration ? `Checked out (${c.duration})` : "Checked in") : `Denied (${c.reason})`}
              </span>
              <span style={styles.recentTime}>{c.checkedOutAt || c.checkedInAt}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 640,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  title: { fontSize: 24, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4, marginBottom: 24 },
  form: {
    display: "flex",
    gap: 10,
    marginBottom: 20,
  },
  input: {
    flex: 1,
    padding: "14px 16px",
    fontSize: 18,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
  },
  checkInButton: {
    padding: "14px 22px",
    fontSize: 16,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 700,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  checkOutButton: {
    padding: "14px 22px",
    fontSize: 16,
    border: "none",
    borderRadius: 8,
    background: "#c2b697",
    color: "#fff",
    fontWeight: 700,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  allowedCard: {
    ...BUTTON_COLORS.green,
    borderRadius: 10,
    padding: "20px 24px",
    marginBottom: 28,
  },
  deniedCard: {
    ...BUTTON_COLORS.red,
    borderRadius: 10,
    padding: "20px 24px",
    marginBottom: 28,
  },
  resultHeadline: { fontSize: 20, fontWeight: 800 },
  resultDetail: { fontSize: 14, marginTop: 4, opacity: 0.95 },
  recentTitle: { fontSize: 15, fontWeight: 700, margin: "0 0 10px" },
  emptyText: { fontSize: 13, color: "#888" },
  recentList: {
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    overflow: "hidden",
  },
  recentRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 14px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 13,
  },
  recentName: { fontWeight: 600, flex: 1 },
  recentTime: { color: "#888", whiteSpace: "nowrap" },
  badgeAllowed: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 999,
    whiteSpace: "nowrap",
    ...BUTTON_COLORS.green,
  },
  badgeDenied: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 999,
    whiteSpace: "nowrap",
    ...BUTTON_COLORS.red,
  },
};

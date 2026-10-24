import { useCallback, useEffect, useRef, useState } from "react";
import { checkIn, checkOut, fetchFlags, fetchRecentCheckIns } from "../api/checkins.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import AccessCardPanel from "./AccessCardPanel.jsx";
import FlagCheckInForm from "./FlagCheckInForm.jsx";
import FlaggedCheckIns from "./FlaggedCheckIns.jsx";
import QrScanner from "./QrScanner.jsx";

const RESULT_DISPLAY_MS = 3000;

// User story: "As a receptionist, I want to check in members via QR code
// or membership ID, so that I can quickly verify membership status and
// control entry."
//
// Membership ID is just the member's existing id - there's no separate
// member-number field. QR: every member has a signed check-in QR code on
// their dashboard (backend/members/qr.py). "Scan QR" reads it with the
// camera and checks them in straight away; a USB scanner that types the
// code into the field works too, since the field accepts either.
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
  const [scanning, setScanning] = useState(false);
  const [cardMemberId, setCardMemberId] = useState(null); // member whose access card panel is open
  const [cardHint, setCardHint] = useState(null);
  const [flagTarget, setFlagTarget] = useState(null); // check-in attempt being flagged
  const [tab, setTab] = useState("recent"); // "recent" | "flags"
  const [openFlags, setOpenFlags] = useState(0);
  const [flagsVersion, setFlagsVersion] = useState(0); // bumped to reload the flagged list
  const inputRef = useRef(null);
  const dismissTimer = useRef(null);

  function loadOpenFlags() {
    fetchFlags("Open")
      .then((data) => setOpenFlags(data.openCount))
      .catch(() => {});
  }

  function handleFlagged(flag) {
    setFlagTarget(null);
    setResult((r) => (r?.checkIn?.id === flag.checkIn.id ? { ...r, checkIn: flag.checkIn } : r));
    loadRecent();
    loadOpenFlags();
    setFlagsVersion((v) => v + 1);
  }

  function openAccessCard() {
    const id = membershipId.trim();
    if (!/^\d+$/.test(id)) {
      setCardHint("Type the member's membership ID first, then click Reissue card.");
      inputRef.current?.focus();
      return;
    }
    setCardHint(null);
    setCardMemberId(Number(id));
  }

  function loadRecent() {
    fetchRecentCheckIns()
      .then((data) => setRecent(data.results))
      .catch(() => {
        // Non-fatal: the recent-activity list just stays empty/stale.
      });
  }

  useEffect(() => {
    loadRecent();
    loadOpenFlags();
    return () => clearTimeout(dismissTimer.current);
  }, []);

  // A normal result disappears after 3 seconds. One that needs the desk's
  // attention (a flagged member, or a suspicious attempt) stays until dismissed.
  function showResult(data) {
    setResult(data);
    clearTimeout(dismissTimer.current);
    if (!data.flagWarning && !data.checkIn?.suspicion) {
      dismissTimer.current = setTimeout(() => setResult(null), RESULT_DISPLAY_MS);
    }
  }

  async function handleAction(action, code = membershipId) {
    if (!code) return;
    setSubmittingAction(action);

    try {
      const data = action === "checkin" ? await checkIn(code) : await checkOut(code);
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

  const handleScan = useCallback((code) => {
    setScanning(false);
    handleAction("checkin", code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
          value={membershipId}
          onChange={(e) => {
            setMembershipId(e.target.value);
            setCardHint(null);
          }}
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
        <button
          type="button"
          onClick={() => setScanning(true)}
          disabled={scanning || Boolean(submittingAction)}
          style={styles.scanButton}
        >
          Scan QR
        </button>
      </form>

      <div style={styles.lostCardRow}>
        <span>Member lost their card or QR code?</span>
        <button type="button" onClick={openAccessCard} style={styles.linkButton}>
          Reissue card
        </button>
      </div>
      {cardHint && <div style={styles.cardHint}>{cardHint}</div>}

      {scanning && <QrScanner onScan={handleScan} onClose={() => setScanning(false)} />}
      {cardMemberId && <AccessCardPanel memberId={cardMemberId} onClose={() => setCardMemberId(null)} />}
      {flagTarget && (
        <FlagCheckInForm checkIn={flagTarget} onClose={() => setFlagTarget(null)} onFlagged={handleFlagged} />
      )}

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
                      : result.checkIn.reason === "Replaced card"
                        ? `This is an old card for ${result.member.name} (#${result.member.id}). It was replaced and `
                          + "no longer works - ask for the new card, or reissue one."
                        : `${result.member.name}: ${result.access?.message || result.checkIn.reason}`}
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

          {result.ok && result.action === "checkin" && result.checkIn.suspicion && (
            <div style={styles.resultSuspicion}>{result.checkIn.suspicion}</div>
          )}
          {result.flagWarning && (
            <div style={styles.flagWarning}>
              <strong>Check photo ID.</strong> This membership has {result.flagWarning.count} flagged check-in
              {result.flagWarning.count === 1 ? "" : "s"}
              {result.flagWarning.confirmed > 0 && ` (${result.flagWarning.confirmed} confirmed)`} - latest:{" "}
              {result.flagWarning.latestReason.toLowerCase()} on {result.flagWarning.latestFlaggedAt}.
            </div>
          )}
          {(result.flagWarning || result.checkIn?.suspicion) && (
            <div style={styles.resultActions}>
              {result.action === "checkin" &&
                (result.checkIn.flag ? (
                  <span style={styles.resultFlagged}>Flagged: {result.checkIn.flag.reason}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setFlagTarget(result.checkIn)}
                    style={styles.resultButton}
                  >
                    Flag this attempt
                  </button>
                ))}
              <button type="button" onClick={() => setResult(null)} style={styles.resultButtonGhost}>
                Dismiss
              </button>
            </div>
          )}
        </div>
      )}

      <div style={styles.tabs} role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "recent"}
          onClick={() => setTab("recent")}
          style={tab === "recent" ? styles.tabActive : styles.tab}
        >
          Recent Check-Ins
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "flags"}
          onClick={() => setTab("flags")}
          style={tab === "flags" ? styles.tabActive : styles.tab}
        >
          Flagged Attempts
          {openFlags > 0 && <span style={styles.countBadge}>{openFlags}</span>}
        </button>
      </div>

      {tab === "flags" ? (
        <FlaggedCheckIns
          refreshKey={flagsVersion}
          onResolved={() => {
            loadOpenFlags();
            loadRecent();
          }}
        />
      ) : recent.length === 0 ? (
        <p style={styles.emptyText}>No check-ins yet.</p>
      ) : (
        <div style={styles.recentList}>
          {recent.map((c) => (
            <div key={c.id} style={c.suspicion && !c.flag ? { ...styles.recentRow, ...styles.recentRowReview } : styles.recentRow}>
              <div style={styles.recentMain}>
                <span style={styles.recentName}>{c.memberName}</span>
                {c.suspicion && !c.flag && (
                  <span style={styles.reviewChip} title={c.suspicion}>
                    Review
                  </span>
                )}
              </div>
              <span style={c.result === "Allowed" ? styles.badgeAllowed : styles.badgeDenied}>
                {c.result === "Allowed" ? (c.duration ? `Checked out (${c.duration})` : "Checked in") : `Denied (${c.reason})`}
              </span>
              <span style={styles.recentTime}>
                {c.checkedOutAt || c.checkedInAt}
                {c.door && <span style={styles.recentDoor}>{c.door}</span>}
              </span>
              {c.flag ? (
                <span style={styles.flaggedChip} title={c.flag.note || c.flag.reason}>
                  Flagged{c.flag.status !== "Open" ? ` · ${c.flag.status}` : ""}
                </span>
              ) : (
                <button type="button" onClick={() => setFlagTarget(c)} style={styles.flagButton}>
                  Flag
                </button>
              )}
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
    marginBottom: 10,
  },
  lostCardRow: { display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#666", marginBottom: 20 },
  linkButton: {
    border: "none",
    background: "none",
    padding: 0,
    color: "#124096",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
  },
  cardHint: { fontSize: 12, color: "#b3261e", marginTop: -14, marginBottom: 20 },
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
  scanButton: {
    padding: "14px 18px",
    fontSize: 16,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#1a1a1a",
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
  resultSuspicion: { fontSize: 13, fontWeight: 700, marginTop: 8 },
  flagWarning: {
    marginTop: 12,
    padding: "10px 12px",
    borderRadius: 8,
    background: "#fff4e0",
    color: "#8a5a00",
    fontSize: 13,
    lineHeight: 1.45,
  },
  resultActions: { display: "flex", alignItems: "center", gap: 8, marginTop: 12 },
  resultButton: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 8,
    background: "#fff",
    color: "#b3261e",
    cursor: "pointer",
  },
  resultButtonGhost: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "1px solid rgba(255,255,255,0.7)",
    borderRadius: 8,
    background: "transparent",
    color: "#fff",
    cursor: "pointer",
  },
  resultFlagged: { fontSize: 13, fontWeight: 700 },
  tabs: { display: "flex", gap: 4, borderBottom: "1px solid #e4e4e8", marginBottom: 12 },
  tab: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "8px 12px",
    fontSize: 14,
    fontWeight: 700,
    border: "none",
    borderBottom: "2px solid transparent",
    background: "transparent",
    color: "#666",
    cursor: "pointer",
  },
  tabActive: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "8px 12px",
    fontSize: 14,
    fontWeight: 700,
    border: "none",
    borderBottom: "2px solid #124096",
    background: "transparent",
    color: "#124096",
    cursor: "pointer",
  },
  countBadge: {
    minWidth: 18,
    height: 18,
    padding: "0 5px",
    borderRadius: 999,
    fontSize: 11,
    lineHeight: "18px",
    textAlign: "center",
    ...BUTTON_COLORS.red,
  },
  emptyText: { fontSize: 13, color: "#888" },
  recentMain: { display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 },
  recentRowReview: { background: "#fffaf0" },
  reviewChip: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 8px",
    borderRadius: 999,
    background: "#fff4e0",
    color: "#8a5a00",
    cursor: "help",
    whiteSpace: "nowrap",
  },
  flaggedChip: {
    minWidth: 64,
    boxSizing: "border-box",
    textAlign: "center",
    fontSize: 11,
    fontWeight: 700,
    padding: "3px 6px",
    borderRadius: 6,
    background: "#fdeceb",
    color: "#b3261e",
    whiteSpace: "nowrap",
  },
  flagButton: {
    width: 64,
    padding: "3px 0",
    fontSize: 12,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    color: "#444",
    cursor: "pointer",
  },
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
  recentName: { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  recentTime: { display: "flex", flexDirection: "column", alignItems: "flex-end", color: "#888", whiteSpace: "nowrap" },
  recentDoor: { fontSize: 11, color: "#124096", fontWeight: 600 },
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

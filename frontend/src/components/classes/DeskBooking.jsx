import { useCallback, useEffect, useState } from "react";
import { bookMemberAtDesk, searchMembersForClass } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import QrScanner from "../QrScanner.jsx";

// Booking a member into a class at the front desk: find them by name, ID,
// phone or card, see straight away whether they can take a spot and why not,
// and book. The server decides all of it and checks again when booking, so a
// spot taken in the app a moment ago is refused rather than overbooked.
//
// User story: "As a receptionist, I want to view the daily class schedule and
// open slots, so that I can answer member questions and book walk-ins into
// classes."

const SEARCH_DELAY_MS = 250;

export default function DeskBooking({ gymClass, onBooked }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [scanning, setScanning] = useState(false);
  const classId = gymClass.id;

  const search = useCallback(
    (text) => {
      return searchMembersForClass(classId, text)
        .then((body) => {
          setResults(body.results);
          setError(null);
        })
        .catch((err) => {
          setResults(null);
          setError(err.message);
        });
    },
    [classId],
  );

  // Searches as the receptionist types; a USB card reader types the whole
  // code at once, so it lands here too.
  useEffect(() => {
    const text = query.trim();
    if (!text) {
      setResults(null);
      setError(null);
      return undefined;
    }
    let stale = false;
    const timer = setTimeout(() => {
      if (!stale) search(text);
    }, SEARCH_DELAY_MS);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [query, search]);

  const handleScan = useCallback((code) => {
    setScanning(false);
    setQuery(code);
  }, []);

  async function book(member) {
    setBusyId(member.id);
    setError(null);
    setNotice(null);
    try {
      const result = await bookMemberAtDesk(classId, member.id);
      const left = result.class.spotsLeft;
      setNotice(`${member.name} is booked in. ${left} spot${left === 1 ? "" : "s"} left.`);
      setQuery("");
      setResults(null);
      onBooked();
    } catch (err) {
      // Someone may have taken the last spot: show why, and refresh both views.
      setError(err.message);
      onBooked();
      search(query.trim());
    } finally {
      setBusyId(null);
    }
  }

  const isCode = query.trim().startsWith("FFM1:");

  return (
    <section style={styles.panel} aria-label="Book a member">
      <h3 style={styles.title}>Book a member</h3>
      {notice && <div style={styles.successBox}>{notice}</div>}

      {gymClass.spotsLeft === 0 ? (
        <div style={styles.fullBox}>
          This class is full - nobody else can be booked in unless a spot opens up
          {gymClass.waitlistCount
            ? `, and then it goes to the ${gymClass.waitlistCount} member${gymClass.waitlistCount === 1 ? "" : "s"} on the waitlist first.`
            : "."}
        </div>
      ) : (
        <>
          <div style={styles.searchRow}>
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setNotice(null);
              }}
              placeholder="Name, membership ID, phone or scan a card"
              aria-label="Find a member"
              style={styles.input}
              autoFocus
            />
            <button type="button" onClick={() => setScanning((s) => !s)} style={styles.scanButton}>
              {scanning ? "Close camera" : "Scan card"}
            </button>
          </div>
          {scanning && <QrScanner onScan={handleScan} onClose={() => setScanning(false)} />}
          {error && <div style={styles.errorBox}>{error}</div>}

          {results && results.length === 0 && (
            <div style={styles.none}>
              No member matches {isCode ? "that card" : `"${query.trim()}"`}. Someone who isn&apos;t a member yet has to be registered
              first: Member Directory → + Register New Member.
            </div>
          )}
          {results && results.length > 0 && (
            <ul style={styles.results}>
              {results.map((m) => (
                <li key={m.id} style={styles.result}>
                  <div style={styles.resultBody}>
                    <span style={styles.resultName}>
                      {m.name}
                      {m.status !== "Active" && <span style={styles.statusTag}>{m.status}</span>}
                      {m.visiting && <span style={styles.visitingTag}>Visiting from {m.branch}</span>}
                    </span>
                    <span style={styles.resultMeta}>
                      ID {m.id}
                      {m.phone && ` · ${m.phone}`}
                    </span>
                    {m.flagged && <span style={styles.warn}>Flagged check-in on file - check photo ID.</span>}
                    {!m.waiverOnFile && <span style={styles.warn}>No waiver on file - have them sign one.</span>}
                    {m.reason && <span style={styles.reason}>{m.reason}</span>}
                  </div>
                  <button
                    type="button"
                    onClick={() => book(m)}
                    disabled={!m.canBook || busyId !== null}
                    style={m.canBook ? styles.bookButton : styles.disabledButton}
                    aria-label={`Book ${m.name}`}
                  >
                    {busyId === m.id ? "Booking..." : "Book"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

const styles = {
  panel: { marginTop: 16, padding: 14, border: "1px solid #dfe5f2", borderRadius: 10, background: "#f7f9fd" },
  title: { fontSize: 15, fontWeight: 700, margin: "0 0 10px" },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "8px 12px", borderRadius: 8, fontSize: 14, marginBottom: 10 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 14, marginTop: 10 },
  fullBox: { background: "#fff1d6", color: "#8a5300", padding: "8px 12px", borderRadius: 8, fontSize: 14 },
  searchRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  input: {
    flex: "1 1 220px",
    minWidth: 0,
    padding: "9px 11px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  scanButton: {
    padding: "9px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#333",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  none: { fontSize: 13, color: "#666", marginTop: 10, lineHeight: 1.5 },
  results: { listStyle: "none", margin: "10px 0 0", padding: 0, border: "1px solid #e4e4e8", borderRadius: 8, background: "#fff" },
  result: { display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", borderBottom: "1px solid #f0f0f3" },
  resultBody: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  resultName: { fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  resultMeta: { fontSize: 12, color: "#666" },
  statusTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#ececf0", color: "#555" },
  visitingTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#eef2fa", color: "#124096" },
  warn: { fontSize: 12, color: "#a15c00" },
  reason: { fontSize: 12, color: "#b3261e" },
  bookButton: {
    flexShrink: 0,
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.green,
    cursor: "pointer",
  },
  disabledButton: {
    flexShrink: 0,
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 700,
    border: "none",
    borderRadius: 6,
    background: "#c9cdd3",
    color: "#fff",
    cursor: "not-allowed",
  },
};

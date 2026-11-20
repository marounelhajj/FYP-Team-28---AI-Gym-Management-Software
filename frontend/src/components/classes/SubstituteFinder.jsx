import { useEffect, useState } from "react";
import { assignSubstitute, fetchSubstitutes } from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import { formatLongDay } from "./dates.js";

// User story: "As a branch manager, I want to reassign a class to a
// substitute coach when the original coach cancels last minute, so that the
// session isn't lost."
//
// Every coach who can teach at the branch: free ones first, then the ones who
// know this class best; busy ones are shown (with why) but can't be picked.
// The server checks again when assigning, so a coach who just got booked
// elsewhere is refused rather than double-booked.
export default function SubstituteFinder({ classId, onClose, onAssigned }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [chosen, setChosen] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState(null);

  function load() {
    return fetchSubstitutes(classId)
      .then((body) => {
        setData(body);
        setReason((current) => current || body.coverRequest?.reason || "");
      })
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId]);

  async function assign() {
    setBusy(true);
    setError(null);
    setFieldError(null);
    try {
      const result = await assignSubstitute(classId, chosen.id, reason);
      onAssigned(
        `${chosen.name} is now teaching ${data.name} (${data.startTime}) instead of ${data.currentCoach.name}.` +
          (result.membersNotified ? " Booked members have been told." : ""),
      );
    } catch (err) {
      const f = err.fieldErrors;
      if (f?.reason) setFieldError(f.reason[0]);
      else setError(f?.coachId?.[0] || err.message);
      setChosen(null);
      load(); // someone's status may have changed
    } finally {
      setBusy(false);
    }
  }

  const free = data?.candidates.filter((c) => c.available) || [];
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Find a substitute">
        <div style={styles.head}>
          <div>
            <h2 style={styles.title}>Find a substitute</h2>
            {data && (
              <p style={styles.sub}>
                {data.name} · {formatLongDay(data.date)} · {data.startTime}–{data.endTime}
                {data.room ? ` · ${data.room}` : ""}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        {error && <div style={styles.errorBox}>{error}</div>}
        {!data && !error && <p style={styles.muted}>Loading...</p>}
        {data && (
          <>
            <div style={styles.current}>
              Now: <strong>{data.currentCoach.name}</strong>
              {!data.currentCoach.active && " (account deactivated)"}
              {data.coverRequest && (
                <span style={styles.requestNote}>
                  {" "}asked for cover {data.coverRequest.createdAt.slice(5)}: &ldquo;{data.coverRequest.reason}&rdquo;
                </span>
              )}
            </div>
            {data.started && !data.problem && (
              <div style={styles.warnBox}>This class has already started - the substitute takes over from now. Members in the room aren&apos;t messaged.</div>
            )}
            {data.problem ? (
              <div style={styles.errorBox}>{data.problem}</div>
            ) : (
              <>
                <p style={styles.muted}>
                  {free.length} of {data.candidates.length} coach{data.candidates.length === 1 ? " is" : "es are"} free at that time.
                </p>
                {data.candidates.length === 0 ? (
                  <div style={styles.empty}>No other coach can teach at this branch. Cancel the class instead to tell members.</div>
                ) : (
                  <ul style={styles.list} role="radiogroup" aria-label="Substitute coach">
                    {data.candidates.map((c) => {
                      const selected = chosen?.id === c.id;
                      return (
                        <li key={c.id}>
                          <button
                            type="button"
                            role="radio"
                            aria-checked={selected}
                            disabled={!c.available}
                            onClick={() => setChosen(c)}
                            style={{ ...styles.row, ...(selected ? styles.rowSelected : null), ...(c.available ? null : styles.rowBusy) }}
                          >
                            <span style={styles.rowMain}>
                              <span style={styles.name}>
                                {c.name}
                                {!c.branch && <span style={styles.chip}>All branches</span>}
                              </span>
                              <span style={styles.meta}>
                                {c.taughtThisType
                                  ? `Taught ${data.name} ${c.taughtThisType} time${c.taughtThisType === 1 ? "" : "s"}`
                                  : `Hasn't taught ${data.name} here yet`}
                                {c.classesThatDay ? ` · ${c.classesThatDay} other class${c.classesThatDay === 1 ? "" : "es"} that day` : ""}
                              </span>
                              {!c.available && <span style={styles.busy}>{c.busyReason}</span>}
                            </span>
                            <span style={c.available ? styles.freeTag : styles.busyTag}>{c.available ? "Free" : "Busy"}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <label style={styles.field}>
                  <span style={styles.label}>Why the change{data.coverRequest ? " (from the coach's request)" : ""}</span>
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    maxLength={200}
                    placeholder='e.g. "Called in sick"'
                    style={styles.input}
                  />
                  {fieldError && <span style={styles.fieldError}>{fieldError}</span>}
                </label>
                <p style={styles.hint}>
                  Only this session changes. The substitute and {data.currentCoach.name} are notified, and the class&apos;s pay,
                  attendance and health briefing go to the substitute.
                </p>
                <div style={styles.actions}>
                  <button type="button" onClick={onClose} style={styles.secondaryButton} disabled={busy}>
                    Cancel
                  </button>
                  <button type="button" onClick={assign} style={chosen ? styles.primaryButton : styles.disabledButton} disabled={!chosen || busy}>
                    {busy ? "Assigning..." : chosen ? `Assign ${chosen.name}` : "Pick a coach"}
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const styles = {
  overlay: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16, zIndex: 60 },
  modal: { background: "#fff", borderRadius: 14, padding: 22, width: "100%", maxWidth: 580, maxHeight: "90vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", color: "#1a1a1a" },
  head: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  title: { fontSize: 19, fontWeight: 800, margin: 0 },
  sub: { fontSize: 13, color: "#666", margin: "4px 0 0" },
  closeButton: { border: "none", background: "none", fontSize: 24, lineHeight: 1, cursor: "pointer", color: "#666" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  hint: { fontSize: 12, color: "#777", margin: 0, lineHeight: 1.45 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  warnBox: { background: "#fff1d6", color: "#8a5300", padding: "10px 14px", borderRadius: 8, fontSize: 13 },
  empty: { padding: 14, border: "1px dashed #d0d0d5", borderRadius: 10, fontSize: 13, color: "#888", textAlign: "center" },
  current: { fontSize: 14, padding: "10px 12px", background: "#f6f6f8", borderRadius: 8 },
  requestNote: { color: "#b3261e" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  row: { width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  rowSelected: { borderColor: "#124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  rowBusy: { background: "#f7f7f9", color: "#888", cursor: "not-allowed" },
  rowMain: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  name: { fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 },
  chip: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#eef2fa", color: "#124096" },
  meta: { fontSize: 12, color: "#666" },
  busy: { fontSize: 12, color: "#b3261e" },
  freeTag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#e3f5e8", color: "#0f6e2b" },
  busyTag: { flexShrink: 0, fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4, background: "#ececf0", color: "#666" },
  field: { display: "flex", flexDirection: "column", gap: 4 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  input: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8 },
  primaryButton: { padding: "9px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  disabledButton: { padding: "9px 16px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  secondaryButton: { padding: "9px 16px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
};

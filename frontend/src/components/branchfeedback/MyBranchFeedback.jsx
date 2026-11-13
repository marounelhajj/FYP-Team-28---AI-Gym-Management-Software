import { useEffect, useState } from "react";
import { fetchMyBranchFeedback, replyToMyComplaint, submitComplaint, submitSurvey } from "../../api/branchFeedback.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import ComplaintThread, { StatusTag } from "./ComplaintThread.jsx";

// The member's side of: "As a branch manager, I want to view member feedback
// and complaints specific to my branch, so that I can address local service
// issues directly rather than waiting on a company wide report."
//
// On the member dashboard: a short survey for a branch they've visited
// (how likely they'd recommend it, 0-10; five areas rated 1-5; a comment;
// optionally anonymous), and "Report a problem" - a complaint the branch's
// managers answer, followed here as a conversation.

const AREA_SCALE = ["Very poor", "Poor", "OK", "Good", "Excellent"];

function emptySurvey(branch) {
  return { branch, nps: null, cleanliness: null, equipment: null, staff: null, classes: null, atmosphere: null, comment: "", anonymous: false };
}

export default function MyBranchFeedback() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [survey, setSurvey] = useState(null);
  const [complaint, setComplaint] = useState(null);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [reply, setReply] = useState("");

  useEffect(() => {
    fetchMyBranchFeedback().then(setData).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  async function run(action, message, after) {
    setBusy(true);
    setErrors({});
    setError(null);
    try {
      setData(await action());
      setNotice(message);
      after?.();
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return <div style={styles.card}>{error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>}</div>;
  }

  const rateable = data.surveys.filter((s) => s.canSurvey);
  const waiting = data.surveys.filter((s) => !s.canSurvey);
  const unresolved = data.complaints.filter((c) => c.status !== "Resolved").length;
  const fieldError = (f) => errors[f] && <span style={styles.fieldError}>{errors[f][0]}</span>;

  return (
    <section style={styles.card} aria-label="Feedback and complaints">
      {notice && <div style={styles.successBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <h3 style={styles.heading}>Rate your gym</h3>
      {survey ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => submitSurvey(survey), "Thank you - the branch team will see your feedback.", () => setSurvey(null));
          }}
          style={styles.form}
          aria-label="Branch survey"
        >
          {rateable.length > 1 && (
            <label style={styles.field}>
              <span style={styles.label}>Branch</span>
              <select value={survey.branch} onChange={(e) => setSurvey({ ...survey, branch: e.target.value })} style={styles.input}>
                {rateable.map((s) => (
                  <option key={s.branch} value={s.branch}>{s.branch}</option>
                ))}
              </select>
            </label>
          )}
          <fieldset style={styles.fieldset}>
            <legend style={styles.label}>How likely are you to recommend {survey.branch} to a friend?</legend>
            <div style={styles.npsRow} role="radiogroup" aria-label="How likely to recommend, 0 to 10">
              {Array.from({ length: 11 }, (_, n) => (
                <button
                  key={n}
                  type="button"
                  role="radio"
                  aria-checked={survey.nps === n}
                  onClick={() => setSurvey({ ...survey, nps: n })}
                  style={{ ...styles.npsButton, ...(survey.nps === n ? styles.npsActive : null) }}
                >
                  {n}
                </button>
              ))}
            </div>
            <div style={styles.npsLegend}>
              <span>Not at all likely</span>
              <span>Extremely likely</span>
            </div>
            {fieldError("nps")}
          </fieldset>

          <div style={styles.label}>How is the branch doing? (skip any that don&apos;t apply)</div>
          {data.areas.map((area) => (
            <div key={area.key} style={styles.areaRow}>
              <span style={styles.areaLabel}>{area.label}</span>
              <div role="radiogroup" aria-label={area.label} style={styles.areaScale}>
                {AREA_SCALE.map((word, i) => {
                  const value = i + 1;
                  const selected = survey[area.key] === value;
                  return (
                    <button
                      key={word}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      title={word}
                      aria-label={`${area.label}: ${word}`}
                      onClick={() => setSurvey({ ...survey, [area.key]: selected ? null : value })}
                      style={{ ...styles.areaButton, ...(selected ? styles.areaActive : null) }}
                    >
                      {value}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          <p style={styles.hint}>1 = very poor, 5 = excellent. Tap again to clear.</p>

          <label style={styles.field}>
            <span style={styles.label}>What&apos;s one thing we should improve? (optional)</span>
            <textarea
              value={survey.comment}
              onChange={(e) => setSurvey({ ...survey, comment: e.target.value })}
              maxLength={1000}
              rows={3}
              style={styles.textarea}
            />
            {fieldError("comment")}
          </label>
          <label style={styles.check}>
            <input type="checkbox" checked={survey.anonymous} onChange={(e) => setSurvey({ ...survey, anonymous: e.target.checked })} />
            Send anonymously - the branch sees your answers but not your name
          </label>
          {fieldError("non_field_errors")}
          <div style={styles.actions}>
            <button type="button" onClick={() => setSurvey(null)} style={styles.secondaryButton} disabled={busy}>Cancel</button>
            <button type="submit" style={styles.primaryButton} disabled={busy || survey.nps === null}>
              {busy ? "Sending..." : "Send feedback"}
            </button>
          </div>
        </form>
      ) : (
        <>
          {rateable.length > 0 && (
            <button type="button" onClick={() => setSurvey(emptySurvey(rateable[0].branch))} style={styles.primaryButton}>
              Rate {rateable.length === 1 ? rateable[0].branch : "a branch"}
            </button>
          )}
          {waiting.map((s) => (
            <p key={s.branch} style={styles.muted}>
              Thanks for rating {s.branch} on {s.lastOn}. You can rate it again from {s.nextOn}.
            </p>
          ))}
          {data.surveys.length === 0 && (
            <p style={styles.muted}>You can rate a branch once you&apos;ve visited it - check in with your card or QR code.</p>
          )}
        </>
      )}

      <h3 style={styles.heading}>Problems &amp; complaints</h3>
      {complaint ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => submitComplaint(complaint), `Sent - ${complaint.branch} aims to answer within ${data.responseHours} hours.`, () => setComplaint(null));
          }}
          style={styles.form}
          aria-label="Report a problem"
        >
          <div style={styles.formRow}>
            <label style={styles.field}>
              <span style={styles.label}>Branch</span>
              <select value={complaint.branch} onChange={(e) => setComplaint({ ...complaint, branch: e.target.value })} style={styles.input}>
                {data.complaintBranches.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
              {fieldError("branch")}
            </label>
            <label style={styles.field}>
              <span style={styles.label}>What&apos;s it about?</span>
              <select value={complaint.category} onChange={(e) => setComplaint({ ...complaint, category: e.target.value })} style={styles.input}>
                {data.categories.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </label>
          </div>
          {complaint.category === "Safety" && (
            <p style={styles.urgentHint}>Safety problems are marked urgent. If someone is hurt, tell the front desk right away.</p>
          )}
          <label style={styles.field}>
            <span style={styles.label}>In a few words</span>
            <input value={complaint.subject} onChange={(e) => setComplaint({ ...complaint, subject: e.target.value })} maxLength={120} placeholder="e.g. Treadmill 3 is broken" style={styles.input} />
            {fieldError("subject")}
          </label>
          <label style={styles.field}>
            <span style={styles.label}>What happened?</span>
            <textarea
              value={complaint.description}
              onChange={(e) => setComplaint({ ...complaint, description: e.target.value })}
              maxLength={2000}
              rows={4}
              placeholder="Where, when, and anything that would help the team fix it."
              style={styles.textarea}
            />
            {fieldError("description")}
          </label>
          <div style={styles.actions}>
            <button type="button" onClick={() => setComplaint(null)} style={styles.secondaryButton} disabled={busy}>Cancel</button>
            <button type="submit" style={styles.dangerButton} disabled={busy}>{busy ? "Sending..." : "Send"}</button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setComplaint({ branch: data.homeBranch, category: data.categories[0].value, subject: "", description: "" })}
          style={unresolved >= data.maxUnresolved ? styles.disabledButton : styles.secondaryButton}
          disabled={unresolved >= data.maxUnresolved}
          title={unresolved >= data.maxUnresolved ? `You have ${unresolved} complaints still open.` : undefined}
        >
          Report a problem
        </button>
      )}

      {data.complaints.length > 0 && (
        <ul style={styles.list}>
          {data.complaints.map((c) => (
            <li key={c.id} style={styles.item}>
              <button type="button" onClick={() => setOpenId(openId === c.id ? null : c.id)} style={styles.itemHead} aria-expanded={openId === c.id}>
                <span style={styles.itemTitle}>{c.subject}</span>
                <span style={styles.itemMeta}>{c.branch} · {c.createdAt.slice(0, 10)}</span>
                <StatusTag status={c.status} />
              </button>
              {openId === c.id && (
                <div style={styles.itemBody}>
                  <ComplaintThread complaint={c} viewer="member" />
                  {c.status !== "Resolved" && !c.messages.some((m) => m.role === "staff") && (
                    <p style={styles.hint}>The {c.branch} team aims to answer within {data.responseHours} hours.</p>
                  )}
                  {c.canReply && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        run(() => replyToMyComplaint(c.id, reply), c.status === "Resolved" ? "Reopened - the team will look again." : "Sent.", () => setReply(""));
                      }}
                      style={styles.replyRow}
                    >
                      <input value={reply} onChange={(e) => setReply(e.target.value)} maxLength={1000} placeholder={c.status === "Resolved" ? "Not sorted? Reply to reopen it" : "Add more details"} aria-label="Reply" style={{ ...styles.input, flex: 1 }} />
                      <button type="submit" style={styles.primaryButton} disabled={busy || !reply.trim()}>Send</button>
                    </form>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start" },
  heading: { fontSize: 14, fontWeight: 800, margin: "4px 0 0" },
  muted: { fontSize: 13, color: "#777", margin: 0, lineHeight: 1.45 },
  hint: { fontSize: 12, color: "#777", margin: 0 },
  urgentHint: { fontSize: 12, color: "#b3261e", margin: 0, fontWeight: 600 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 13, alignSelf: "stretch" },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "8px 12px", borderRadius: 8, fontSize: 13, alignSelf: "stretch" },
  form: { display: "flex", flexDirection: "column", gap: 10, padding: 12, border: "1px solid #dfe5f2", borderRadius: 10, background: "#f7f9fd", alignSelf: "stretch" },
  formRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  fieldset: { border: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  field: { display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 140 },
  label: { fontSize: 12, fontWeight: 700, color: "#444", padding: 0 },
  input: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", boxSizing: "border-box" },
  textarea: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, fontFamily: "inherit", resize: "vertical", boxSizing: "border-box", width: "100%" },
  check: { display: "flex", alignItems: "center", gap: 8, fontSize: 13 },
  npsRow: { display: "grid", gridTemplateColumns: "repeat(11, minmax(0, 1fr))", gap: 3 },
  npsButton: { padding: "7px 0", fontSize: 13, fontWeight: 700, border: "1px solid #d0d0d5", borderRadius: 6, background: "#fff", cursor: "pointer" },
  npsActive: { background: "#124096", borderColor: "#124096", color: "#fff" },
  npsLegend: { display: "flex", justifyContent: "space-between", fontSize: 11, color: "#777" },
  areaRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 },
  areaLabel: { fontSize: 13 },
  areaScale: { display: "flex", gap: 3 },
  areaButton: { width: 32, height: 30, fontSize: 13, fontWeight: 700, border: "1px solid #d0d0d5", borderRadius: 6, background: "#fff", cursor: "pointer" },
  areaActive: { background: "#124096", borderColor: "#124096", color: "#fff" },
  fieldError: { fontSize: 12, color: "#b3261e" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 8 },
  primaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.blue, cursor: "pointer" },
  dangerButton: { padding: "8px 14px", fontSize: 13, fontWeight: 700, border: "none", borderRadius: 8, ...BUTTON_COLORS.red, cursor: "pointer" },
  secondaryButton: { padding: "8px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", cursor: "pointer" },
  disabledButton: { padding: "8px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #e4e4e8", borderRadius: 8, background: "#f4f4f6", color: "#999", cursor: "not-allowed" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6, alignSelf: "stretch" },
  item: { border: "1px solid #e4e4e8", borderRadius: 10, overflow: "hidden" },
  itemHead: { width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", border: "none", background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  itemTitle: { flex: 1, fontSize: 13, fontWeight: 700, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  itemMeta: { fontSize: 11, color: "#777", flexShrink: 0 },
  itemBody: { padding: "4px 12px 12px", display: "flex", flexDirection: "column", gap: 8 },
  replyRow: { display: "flex", gap: 6 },
};

import { useCallback, useEffect, useState } from "react";
import { fetchMyFeedback, rateSession, updateFeedback } from "../../api/feedback.js";
import { StarInput, Stars } from "./Stars.jsx";

// User story (SCRUM-40): "As a member, I want to rate and leave feedback for
// my coach after a session, so that I can help improve service quality."
//
// On the member dashboard: the classes and private sessions they attended in
// the last couple of weeks that they haven't rated yet, and the ratings
// they've left (editable until the window closes). The server decides what
// can be rated - this only shows what it returns.

const COMMENT_LIMIT = 500;

export default function RateMyCoaches() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  // The open form: { key, feedbackId?, kind, sessionId, rating, comment }.
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(() => {
    fetchMyFeedback().then(setData).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(t);
  }, [notice]);

  function openNew(session) {
    setError(null);
    setForm({ key: `${session.kind}-${session.sessionId}`, kind: session.kind, sessionId: session.sessionId, rating: 0, comment: "" });
  }

  function openEdit(given) {
    setError(null);
    setForm({ key: `edit-${given.id}`, feedbackId: given.id, rating: given.rating, comment: given.comment });
  }

  async function submit(e) {
    e.preventDefault();
    if (!form.rating) {
      setError("Choose a rating from 1 to 5 stars.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (form.feedbackId) {
        await updateFeedback(form.feedbackId, { rating: form.rating, comment: form.comment });
        setNotice("Rating updated.");
      } else {
        await rateSession({ kind: form.kind, sessionId: form.sessionId, rating: form.rating, comment: form.comment });
        setNotice("Thanks - your coach will see your rating.");
      }
      setForm(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (!data) {
    return <div style={styles.card}>{error ? <div style={styles.errorBox}>{error}</div> : <p style={styles.muted}>Loading...</p>}</div>;
  }

  const given = showAll ? data.given : data.given.slice(0, 5);

  const formFor = (key) => form && form.key === key && (
    <form onSubmit={submit} style={styles.form}>
      <StarInput value={form.rating} onChange={(rating) => setForm({ ...form, rating })} disabled={saving} />
      <label style={styles.field}>
        <span style={styles.label}>Comment (optional)</span>
        <textarea
          value={form.comment}
          maxLength={COMMENT_LIMIT}
          rows={3}
          placeholder="What went well? What could be better?"
          onChange={(e) => setForm({ ...form, comment: e.target.value })}
          style={styles.textarea}
        />
        <span style={styles.hint}>{form.comment.length}/{COMMENT_LIMIT} · Your coach sees your name, rating and comment.</span>
      </label>
      <div style={styles.actions}>
        <button type="button" onClick={() => setForm(null)} style={styles.secondaryButton} disabled={saving}>Cancel</button>
        <button type="submit" style={styles.primaryButton} disabled={saving}>
          {saving ? "Saving..." : form.feedbackId ? "Save changes" : "Submit rating"}
        </button>
      </div>
    </form>
  );

  return (
    <div style={styles.card}>
      {notice && <div style={styles.successBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <h3 style={styles.heading}>Waiting for your rating</h3>
      {data.toRate.length === 0 && (
        <p style={styles.muted}>
          Nothing to rate. Classes and private sessions you attend show up here for {data.windowDays} days.
        </p>
      )}
      <ul style={styles.list}>
        {data.toRate.map((s) => {
          const key = `${s.kind}-${s.sessionId}`;
          return (
            <li key={key} style={styles.item}>
              <div style={styles.itemRow}>
                <div style={styles.itemText}>
                  <span style={styles.itemTitle}>{s.name} with {s.coach.name}</span>
                  <span style={styles.itemMeta}>{s.startsAt} · rate by {s.rateBy.slice(0, 10)}</span>
                </div>
                {form?.key !== key && (
                  <button type="button" onClick={() => openNew(s)} style={styles.smallButton}>Rate</button>
                )}
              </div>
              {formFor(key)}
            </li>
          );
        })}
      </ul>

      {data.given.length > 0 && (
        <>
          <h3 style={styles.heading}>Your ratings</h3>
          <ul style={styles.list}>
            {given.map((g) => {
              const key = `edit-${g.id}`;
              return (
                <li key={g.id} style={styles.item}>
                  <div style={styles.itemRow}>
                    <div style={styles.itemText}>
                      <span style={styles.itemTitle}>{g.name} with {g.coachName}</span>
                      <span style={styles.itemMeta}>{g.sessionAt}</span>
                    </div>
                    <Stars value={g.rating} />
                    {g.editable && form?.key !== key && (
                      <button type="button" onClick={() => openEdit(g)} style={styles.smallButton}>Edit</button>
                    )}
                  </div>
                  {g.comment && form?.key !== key && <p style={styles.comment}>“{g.comment}”</p>}
                  {formFor(key)}
                </li>
              );
            })}
          </ul>
          {data.given.length > 5 && (
            <button type="button" onClick={() => setShowAll(!showAll)} style={styles.linkButton}>
              {showAll ? "Show fewer" : `Show all ${data.given.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}

const styles = {
  card: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 14, background: "#fff" },
  heading: { fontSize: 14, fontWeight: 800, margin: "0 0 8px" },
  list: { listStyle: "none", margin: "0 0 14px", padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  item: { padding: "10px 12px", border: "1px solid #ececf0", borderRadius: 10 },
  itemRow: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  itemText: { display: "flex", flexDirection: "column", gap: 2, flex: "1 1 180px", minWidth: 0 },
  itemTitle: { fontSize: 14, fontWeight: 700 },
  itemMeta: { fontSize: 12, color: "#666" },
  comment: { fontSize: 13, color: "#444", margin: "6px 0 0", overflowWrap: "anywhere" },
  form: { display: "flex", flexDirection: "column", gap: 10, padding: 12, borderRadius: 12, background: "#f6f6f8", marginTop: 10 },
  field: { display: "flex", flexDirection: "column", gap: 4 },
  label: { fontSize: 12, fontWeight: 700, color: "#444" },
  textarea: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit", resize: "vertical" },
  hint: { fontSize: 12, color: "#888" },
  actions: { display: "flex", gap: 8, justifyContent: "flex-end" },
  primaryButton: { height: 38, padding: "0 16px", border: "none", borderRadius: 8, background: "#124096", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  secondaryButton: { height: 38, padding: "0 14px", border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  smallButton: { padding: "5px 12px", fontSize: 12, fontWeight: 700, border: "1px solid #d0d0d5", borderRadius: 6, background: "#f5f5f7", cursor: "pointer" },
  linkButton: { padding: 0, border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  successBox: { background: "#e6f4ea", color: "#1e7a34", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "8px 12px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  muted: { fontSize: 13, color: "#888", margin: "0 0 14px" },
};

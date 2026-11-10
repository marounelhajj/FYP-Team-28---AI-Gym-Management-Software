import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { fetchAtRisk, logRetentionCall, refreshAtRisk, saveCallCapacity } from "../../api/churn.js";
import AccuracyPanel from "./AccuracyPanel.jsx";
import RetentionCallHistory, { OutcomeBadge } from "./RetentionCallHistory.jsx";
import AccessDenied from "../AccessDenied.jsx";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// User story (SCRUM-118): "As a branch manager, I want to view a ranked list
// of members at risk of leaving, so that I know who to contact first."
//
// This week's list for one branch, highest risk first. The list is made by
// a weekly job (churn/jobs.py); "Refresh now" re-scores on demand. A Branch
// Manager only ever gets their own branch (the server enforces it); a
// General Manager gets a branch picker.

const LEVELS = ["High", "Medium", "Low"];
const LEVEL_STYLES = {
  High: { background: "#fde7e6", color: "#b3261e", border: "#f3b9b5" },
  Medium: { background: "#fff3d6", color: "#8a5a00", border: "#f1d48f" },
  Low: { background: "#e8f3ea", color: "#1e6b34", border: "#bcdcc4" },
};

function formatDate(iso) {
  if (!iso) return "-";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function formatDateTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function daysFromToday(iso) {
  if (!iso) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Math.round((d - today) / 86400000);
}

function RiskBadge({ level, score }) {
  const s = LEVEL_STYLES[level] || LEVEL_STYLES.Low;
  return (
    <span style={{ ...styles.badge, background: s.background, color: s.color, borderColor: s.border }}>
      <span style={styles.badgeLevel}>{level}</span>
      <span style={styles.badgeScore}>{score}</span>
    </span>
  );
}

// SCRUM-119: the two or three reasons in plain language, each with a short
// line staff can use on the call.
function Reasons({ reasons, talkingPoints }) {
  if (!reasons.length) return <span style={styles.noReasons}>No warning signs</span>;
  return (
    <ul style={styles.reasonList}>
      {reasons.map((r) => (
        <li key={r.text} style={styles.reason}>
          <span style={styles.reasonText}>{r.text}</span>
          {talkingPoints && <span style={styles.talkingPoint} className="ar-say">Say: {r.talkingPoint}</span>}
        </li>
      ))}
    </ul>
  );
}

function MethodChip({ run }) {
  if (!run) return null;
  if (run.method === "model" && run.model) {
    const auc = run.model.auc != null ? ` · validated AUC ${run.model.auc.toFixed(2)}` : "";
    return <span style={{ ...styles.chip, ...styles.chipModel }} title={run.model.version}>Learned model{auc}</span>;
  }
  return <span style={styles.chip} title={run.methodNote}>Rule-based score</span>;
}

export default function AtRiskMembers() {
  const [branch, setBranch] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // "risk" = High and Medium. The call list is already capped to the
  // branch's capacity (SCRUM-120), so it opens on everyone in it.
  const [level, setLevel] = useState("all");
  const [query, setQuery] = useState("");
  // SCRUM-119: a suggested line for the call under each reason.
  const [showTalkingPoints, setShowTalkingPoints] = useState(true);
  // SCRUM-68: the member whose call is being logged, and the last result.
  const [openCall, setOpenCall] = useState(null);
  const [notice, setNotice] = useState(null);
  const [showContacted, setShowContacted] = useState(false);
  // SCRUM-120: members ranked below the week's call capacity.
  const [showBelowCap, setShowBelowCap] = useState(false);

  const load = useCallback((which) => {
    setLoading(true);
    setError(null);
    return fetchAtRisk(which)
      .then((body) => {
        setData(body);
        if (!which) setBranch(body.branch);
      })
      .catch((e) => (e.status === 403 && !which ? setForbidden(true) : setError(e.message)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(branch);
    // Only re-run when the chosen branch changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branch]);

  function refreshNow() {
    setRefreshing(true);
    setError(null);
    refreshAtRisk(data.branch)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setRefreshing(false));
  }

  function callLogged(member, call) {
    setOpenCall(null);
    setNotice(
      call.outcome === "no_answer"
        ? `No answer logged for ${member.name}. They stay on this week's list so you can try again.`
        : `Logged "${call.outcomeLabel}" for ${member.name}. They're off this week's call list.`,
    );
    load(data.branch);
  }

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  function capacitySaved(body) {
    setData(body);
    setNotice(`Call capacity set to ${body.capacity.weekly} a week. The list now shows the top ${body.capacity.weekly}.`);
  }

  const members = data?.members || [];
  const belowCap = data?.belowCap || [];
  const contactedList = data?.contacted || [];
  const counts = useMemo(() => {
    const c = { all: 0, High: 0, Medium: 0, Low: 0 };
    [...members, ...belowCap].forEach((m) => { c[m.level] += 1; c.all += 1; });
    c.risk = c.High + c.Medium;
    return c;
  }, [members, belowCap]);
  const matches = (m) =>
    (level === "all" || m.level === level || (level === "risk" && m.level !== "Low")) &&
    (!query || m.name.toLowerCase().includes(query.trim().toLowerCase()));
  const shown = members.filter(matches);
  const shownBelow = belowCap.filter(matches);
  const week = data?.accuracy?.thisWeek;

  if (forbidden) return <AccessDenied message="Your role doesn't include the at-risk members list." />;

  return (
    <div style={styles.page}>
      <style>{CSS}</style>
      <header style={styles.header}>
        <h1 style={styles.title}>At-Risk Members</h1>
        <p style={styles.subtitle}>
          Members most likely to leave, ranked so the team knows who to call first. Made every Monday.
        </p>
      </header>

      {error && <div style={styles.errorBox} role="alert">{error}</div>}
      {notice && <div style={styles.notice} role="status" className="ar-notice">{notice}</div>}
      {!data && loading && <p style={styles.muted}>Loading...</p>}

      {data && (
        <section style={styles.card} aria-label={`At-risk members at ${data.branch}`}>
          <div style={styles.cardHeader}>
            <div style={styles.headline}>
              <span style={styles.count} key={`${data.branch}-${members.length}`} className="ar-pop">{members.length}</span>
              <span style={styles.countLabelStrong}>{members.length === 1 ? "call" : "calls"} to make</span>
              <span style={styles.countLabel}>
                at {data.branch} this week
                {week ? ` · ${week.contacted} of ${week.capacity} done` : ""} · {counts.risk} at risk
              </span>
            </div>
            <div style={styles.controls}>
              <CapacityControl key={`${data.branch}-${data.capacity.weekly}`} data={data} onSaved={capacitySaved} />
              {data.canChooseBranch && (
                <label style={styles.inline}>
                  <span style={styles.srOnly}>Branch</span>
                  <select
                    className="ar-select"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    style={styles.select}
                    aria-label="Branch"
                  >
                    {data.branches.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </label>
              )}
              {data.canRefresh && (
                <button type="button" className="ar-press" onClick={refreshNow} disabled={refreshing} style={styles.primary}>
                  {refreshing ? "Refreshing..." : "Refresh now"}
                </button>
              )}
            </div>
          </div>

          <div style={styles.metaRow}>
            <MethodChip run={data.run} />
            <span style={styles.meta}>
              Updated {formatDateTime(data.run.ranAt)} · {data.run.triggerLabel.toLowerCase()}
              {data.run.triggeredBy ? ` by ${data.run.triggeredBy}` : ""} · {data.run.membersScored} members scored
            </span>
            {data.run.method === "rules" && data.run.methodNote && (
              <span style={styles.metaNote}>{data.run.methodNote}</span>
            )}
          </div>

          <div style={styles.toolRow}>
            <div style={styles.tray} role="tablist" aria-label="Risk level">
              {[["risk", "At risk"], ...LEVELS.map((l) => [l, l]), ["all", "All"]].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={level === key}
                  className="ar-tab"
                  onClick={() => setLevel(key)}
                  style={level === key ? { ...styles.tab, ...styles.tabSelected } : styles.tab}
                >
                  {label} <span style={styles.tabCount}>{counts[key]}</span>
                </button>
              ))}
            </div>
            <div style={styles.toolRight}>
            <label style={styles.toggle} className="ar-press">
              <input
                type="checkbox"
                checked={showTalkingPoints}
                onChange={(e) => setShowTalkingPoints(e.target.checked)}
                style={styles.toggleBox}
              />
              Talking points
            </label>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name"
              aria-label="Search members by name"
              style={styles.search}
              className="ar-input"
            />
            </div>
          </div>

          <div style={styles.scroll} className="ar-body" data-loading={loading || refreshing}>
            {shown.length === 0 ? (
              <div style={styles.empty}>{!members.length && !belowCap.length && !contactedList.length ? "No members to score at this branch yet."
                : !members.length ? "Every call on this week's list is done." : "No members on the call list match."}</div>
            ) : (
              <MemberTable
                members={shown}
                talkingPoints={showTalkingPoints}
                canLogCalls={data.canLogCalls}
                outcomes={data.outcomes}
                openCall={openCall}
                setOpenCall={setOpenCall}
                onLogged={callLogged}
              />
            )}
          </div>

          {/* SCRUM-120: ranked below the week's call capacity - collapsed, never hidden. */}
          {belowCap.length > 0 && (
            <div style={styles.subSection}>
              <button
                type="button"
                className="ar-press"
                style={styles.disclosure}
                aria-expanded={showBelowCap}
                onClick={() => setShowBelowCap((v) => !v)}
              >
                <span style={styles.chevron} className={showBelowCap ? "ar-open" : ""} aria-hidden="true">›</span>
                Below the cap <span style={styles.tabCount}>{belowCap.length}</span>
                <span style={styles.disclosureHint}>ranked after the top {data.capacity.weekly}</span>
              </button>
              {showBelowCap && (
                <div style={{ ...styles.scroll, marginTop: 10 }} className="ar-say">
                  {shownBelow.length === 0 ? (
                    <div style={styles.empty}>No members below the cap match.</div>
                  ) : (
                    <MemberTable
                      members={shownBelow}
                      talkingPoints={showTalkingPoints}
                      canLogCalls={data.canLogCalls}
                      outcomes={data.outcomes}
                      openCall={openCall}
                      setOpenCall={setOpenCall}
                      onLogged={callLogged}
                    />
                  )}
                </div>
              )}
            </div>
          )}

          {/* SCRUM-68: contacted this week - off the active list, kept visible. */}
          {contactedList.length > 0 && (
            <div style={styles.subSection}>
              <button
                type="button"
                className="ar-press"
                style={styles.disclosure}
                aria-expanded={showContacted}
                onClick={() => setShowContacted((v) => !v)}
              >
                <span style={styles.chevron} className={showContacted ? "ar-open" : ""} aria-hidden="true">›</span>
                Contacted this week <span style={styles.tabCount}>{contactedList.length}</span>
              </button>
              {showContacted && (
                <ul style={styles.contactedList} className="ar-say">
                  {contactedList.map((m) => {
                    const last = m.callsThisWeek.find((c) => c.outcome !== "no_answer") || m.callsThisWeek[0];
                    return (
                      <li key={m.memberId} style={styles.contactedItem}>
                        <span style={styles.contactedName}>{m.name}</span>
                        <OutcomeBadge outcome={last.outcome} label={last.outcomeLabel} />
                        <span style={styles.meta}>{formatDateTime(last.calledAt)} by {last.calledBy}</span>
                        {last.note && <span style={styles.contactedNote}>"{last.note}"</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      {data && <AccuracyPanel accuracy={data.accuracy} branch={data.branch} />}
    </div>
  );
}

// SCRUM-120: how many calls the branch's staff can make per week.
function CapacityControl({ data, onSaved }) {
  const [value, setValue] = useState(String(data.capacity.weekly));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  if (!data.capacity.canEdit) {
    return <span style={styles.capacityRead}>Capacity <strong>{data.capacity.weekly}</strong> calls a week</span>;
  }
  const changed = value !== String(data.capacity.weekly);

  function save(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    saveCallCapacity(data.branch, Number(value))
      .then(onSaved)
      .catch((err) => setError(err.fieldErrors?.weeklyCapacity || err.message))
      .finally(() => setSaving(false));
  }

  return (
    <form onSubmit={save} style={styles.capacityForm} aria-label="Weekly call capacity">
      <label htmlFor="call-capacity" style={styles.capacityLabel}>Calls a week</label>
      <input
        id="call-capacity"
        type="number"
        min={1}
        max={data.capacity.max}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={styles.capacityInput}
        className="ar-input"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? "call-capacity-error" : undefined}
      />
      <button type="submit" className="ar-press" style={changed ? styles.capacitySave : styles.capacitySaveIdle} disabled={saving || !changed}>
        {saving ? "Saving..." : "Set"}
      </button>
      {error && <span id="call-capacity-error" style={styles.capacityError} role="alert">{error}</span>}
    </form>
  );
}

function MemberTable({ members, talkingPoints, canLogCalls, outcomes, openCall, setOpenCall, onLogged }) {
  const columns = canLogCalls ? 7 : 6;
  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th style={styles.th}>#</th>
          <th style={styles.th}>Member</th>
          <th style={styles.th}>Risk</th>
          <th style={styles.th}>Why they're on the list</th>
          <th style={styles.th}>Last visit</th>
          <th style={styles.th}>Membership ends</th>
          {canLogCalls && <th style={styles.th}><span style={styles.srOnly}>Call</span></th>}
        </tr>
      </thead>
      <tbody>
        {members.map((m) => {
          const ends = daysFromToday(m.membershipEndsAt);
          const open = openCall === m.memberId;
          const tries = m.callsThisWeek.filter((c) => c.outcome === "no_answer");
          return (
            <Fragment key={m.memberId}>
              <tr className="ar-row" style={open ? styles.openRow : null}>
                <td style={styles.rank}>{m.rank}</td>
                <td style={styles.tdName}>
                  {m.name}
                  {m.status !== "Active" && <span style={styles.status}>{m.status}</span>}
                  {tries.length > 0 && (
                    <div style={styles.tried}>
                      No answer{tries.length > 1 ? ` ${tries.length} times` : ""} · {formatDateTime(tries[0].calledAt)}
                    </div>
                  )}
                </td>
                <td style={styles.td}><RiskBadge level={m.level} score={m.score} /></td>
                <td style={styles.tdReasons}><Reasons reasons={m.reasons} talkingPoints={talkingPoints} /></td>
                <td style={styles.td}>{m.lastVisit ? formatDate(m.lastVisit) : "Never"}</td>
                <td style={styles.td}>
                  {formatDate(m.membershipEndsAt)}
                  {ends != null && ends >= 0 && ends <= 30 && <span style={styles.soon}> · in {ends} day{ends === 1 ? "" : "s"}</span>}
                  {ends != null && ends < 0 && <span style={styles.lapsed}> · lapsed</span>}
                </td>
                {canLogCalls && (
                  <td style={styles.td}>
                    <button
                      type="button"
                      className="ar-press"
                      style={open ? styles.callButtonOpen : styles.callButton}
                      aria-expanded={open}
                      onClick={() => setOpenCall(open ? null : m.memberId)}
                    >
                      {open ? "Close" : tries.length ? "Try again" : "Log call"}
                    </button>
                  </td>
                )}
              </tr>
              {open && (
                <tr>
                  <td colSpan={columns} style={styles.formCell}>
                    <CallForm member={m} outcomes={outcomes} onCancel={() => setOpenCall(null)} onLogged={onLogged} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

// SCRUM-68: outcome, an optional note and an optional follow-up date.
function CallForm({ member, outcomes, onCancel, onLogged }) {
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [followUpOn, setFollowUpOn] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);

  function submit(e) {
    e.preventDefault();
    if (!outcome) {
      setErrors({ outcome: "Pick how the call went." });
      return;
    }
    setSaving(true);
    setErrors({});
    setError(null);
    logRetentionCall({ memberId: member.memberId, outcome, note, followUpOn })
      .then((call) => onLogged(member, call))
      .catch((err) => {
        if (err.fieldErrors) setErrors(err.fieldErrors);
        else setError(err.message);
      })
      .finally(() => setSaving(false));
  }

  return (
    <form onSubmit={submit} style={styles.form} className="ar-say" aria-label={`Log a call to ${member.name}`}>
      <div style={styles.formGrid}>
        <div style={styles.formMain}>
          <div style={styles.fieldLabel} id={`outcome-${member.memberId}`}>How did the call go?</div>
          <div style={styles.tray} role="radiogroup" aria-labelledby={`outcome-${member.memberId}`}>
            {outcomes.map((o) => (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={outcome === o.value}
                className="ar-tab"
                onClick={() => setOutcome(o.value)}
                style={outcome === o.value ? { ...styles.tab, ...styles.tabSelected } : styles.tab}
              >
                {o.label}
              </button>
            ))}
          </div>
          {errors.outcome && <div style={styles.fieldError}>{errors.outcome}</div>}
          {outcome === "no_answer" && <div style={styles.hint}>They'll stay on this week's list so you can try again.</div>}
          <label style={styles.fieldLabel} htmlFor={`note-${member.memberId}`}>Note (optional)</label>
          <textarea
            id={`note-${member.memberId}`}
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What did they say?"
            style={styles.textarea}
            className="ar-input"
          />
          {errors.note && <div style={styles.fieldError}>{errors.note}</div>}
        </div>
        <div style={styles.formSide}>
          <label style={styles.fieldLabel} htmlFor={`follow-${member.memberId}`}>Follow up on (optional)</label>
          <input
            id={`follow-${member.memberId}`}
            type="date"
            value={followUpOn}
            onChange={(e) => setFollowUpOn(e.target.value)}
            style={styles.dateInput}
            className="ar-input"
          />
          {errors.followUpOn && <div style={styles.fieldError}>{errors.followUpOn}</div>}
          <RetentionCallHistory memberId={member.memberId} title="Earlier calls" />
        </div>
      </div>
      {error && <div style={styles.errorBox} role="alert">{error}</div>}
      <div style={styles.formActions}>
        <button type="button" className="ar-press" style={styles.secondary} onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="submit" className="ar-press" style={styles.primary} disabled={saving}>
          {saving ? "Saving..." : "Save call"}
        </button>
      </div>
    </form>
  );
}

const BLUE = "#124096";

const CSS = `
.ar-tab { transition: background 160ms ease, box-shadow 160ms ease, color 160ms ease, transform 120ms ease; }
.ar-tab:hover { color: ${BLUE}; }
.ar-tab:active, .ar-press:active:not(:disabled) { transform: scale(0.96); }
.ar-press { transition: transform 120ms ease, filter 120ms ease; }
.ar-press:hover:not(:disabled) { filter: brightness(1.08); }
.ar-press:disabled { opacity: 0.6; cursor: progress; }
.ar-body { transition: opacity 180ms ease; }
.ar-body[data-loading="true"] { opacity: 0.55; }
.ar-open { transform: rotate(90deg); }
.ap-grow { animation: ap-grow 520ms cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes ap-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.ar-notice { animation: ar-toast 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
@keyframes ar-toast { from { opacity: 0; transform: translate(-50%, 12px); } to { opacity: 1; transform: translate(-50%, 0); } }
.ar-say { animation: ar-in 220ms ease-out both; }
.ar-row { animation: ar-in 260ms ease-out both; }
.ar-row:hover td { background: #f6f8fd; }
.ar-pop { display: inline-block; animation: ar-pop 360ms cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.ar-select { appearance: none; -webkit-appearance: none; cursor: pointer; padding-right: 40px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23124096' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat; background-position: right 14px center; }
.ar-select option { font-weight: 600; color: #1a1a1a; background: #fff; }
.ar-select:focus-visible, .ar-tab:focus-visible, .ar-press:focus-visible, .ar-input:focus-visible { outline: 3px solid ${BLUE}; outline-offset: 2px; }
@keyframes ar-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes ar-pop { from { transform: scale(0.85); opacity: 0.4; } to { transform: none; opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .ar-tab, .ar-press, .ar-body { transition: none; }
  .ar-row, .ar-pop, .ar-say, .ar-notice, .ap-grow { animation: none; }
  .ar-tab:active, .ar-press:active:not(:disabled) { transform: none; }
}
`;

export const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1240, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  header: { marginBottom: 16 },
  title: { fontSize: 24, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 12, fontSize: 14, marginBottom: 12, fontWeight: 600 },
  muted: { fontSize: 13, color: "#888" },
  card: { border: "1px solid #e4e4e8", borderRadius: 20, background: "#fff", padding: 20, marginBottom: 16, boxShadow: "0 2px 0 #e2e2e8" },
  cardHeader: { display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 14, marginBottom: 10 },
  headline: { display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" },
  count: { fontSize: 36, fontWeight: 900, letterSpacing: -0.5, color: "#b3261e" },
  countLabelStrong: { fontSize: 18, fontWeight: 800 },
  countLabel: { fontSize: 14, fontWeight: 600, color: "#666" },
  controls: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 },
  inline: { display: "inline-flex" },
  srOnly: { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" },
  select: { height: 48, padding: "0 14px", fontSize: 15, fontWeight: 800, border: "1px solid #d0d0d5", borderRadius: 14, background: "#fff", color: "#1a1a1a", fontFamily: "inherit" },
  primary: { height: 48, padding: "0 20px", fontSize: 15, fontWeight: 800, border: "none", borderRadius: 14, ...BUTTON_COLORS.blue, cursor: "pointer", boxShadow: "0 3px 0 #0b2a66", fontFamily: "inherit" },
  metaRow: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 14 },
  chip: { fontSize: 12, fontWeight: 800, padding: "5px 10px", borderRadius: 999, background: "#ececf0", color: "#444", textTransform: "uppercase", letterSpacing: 0.4 },
  chipModel: { background: "#e6edfa", color: BLUE },
  meta: { fontSize: 13, color: "#666", fontWeight: 600 },
  metaNote: { fontSize: 12, color: "#888", flexBasis: "100%" },
  toolRow: { display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 12 },
  tray: { display: "inline-flex", gap: 4, padding: 5, borderRadius: 16, background: "#e9e9ee", boxShadow: "inset 0 2px 4px rgba(0,0,0,0.12)", flexWrap: "wrap" },
  tab: { height: 38, padding: "0 16px", border: "none", borderRadius: 12, background: "transparent", fontSize: 14, fontWeight: 800, color: "#555", cursor: "pointer", whiteSpace: "nowrap", fontFamily: "inherit" },
  tabSelected: { background: "#fff", color: BLUE, boxShadow: "0 3px 8px rgba(18,64,150,0.22), 0 1px 0 rgba(255,255,255,0.9) inset" },
  tabCount: { fontWeight: 900, marginLeft: 4 },
  search: { height: 48, minWidth: 0, flex: "0 1 260px", padding: "0 14px", fontSize: 15, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 14, background: "#fff", fontFamily: "inherit" },
  scroll: { overflowX: "auto" },
  empty: { padding: 22, border: "1px dashed #d0d0d5", borderRadius: 14, fontSize: 14, color: "#888", textAlign: "center" },
  toolRight: { display: "flex", alignItems: "center", gap: 10, flex: "1 1 340px", justifyContent: "flex-end", minWidth: 0 },
  toggle: { flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 8, height: 48, padding: "0 14px", border: "1px solid #d0d0d5", borderRadius: 14, fontSize: 14, fontWeight: 800, color: "#333", cursor: "pointer", background: "#fff", userSelect: "none" },
  toggleBox: { width: 18, height: 18, accentColor: BLUE, margin: 0 },
  tdReasons: { padding: "12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "top", minWidth: 260, whiteSpace: "normal" },
  reasonList: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 },
  reason: { display: "flex", flexDirection: "column", gap: 2, paddingLeft: 12, borderLeft: "3px solid #f1c27a" },
  reasonText: { fontWeight: 700, fontSize: 14 },
  talkingPoint: { fontSize: 13, color: BLUE, fontWeight: 600 },
  noReasons: { fontSize: 13, color: "#888" },
  notice: {
    position: "fixed", left: "50%", bottom: "calc(24px + env(safe-area-inset-bottom, 0px))", transform: "translateX(-50%)", zIndex: 50,
    maxWidth: "min(560px, calc(100vw - 32px))", background: "#1e6b34", color: "#fff", padding: "14px 20px", borderRadius: 16,
    fontSize: 15, fontWeight: 800, boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
  },
  tried: { fontSize: 12, fontWeight: 700, color: "#8a5a00", marginTop: 4 },
  openRow: { background: "#f6f8fd" },
  callButton: { height: 40, padding: "0 16px", fontSize: 14, fontWeight: 800, border: "none", borderRadius: 12, ...BUTTON_COLORS.blue, cursor: "pointer", boxShadow: "0 2px 0 #0b2a66", fontFamily: "inherit", whiteSpace: "nowrap" },
  callButtonOpen: { height: 40, padding: "0 16px", fontSize: 14, fontWeight: 800, border: "1px solid #d0d0d5", borderRadius: 12, background: "#fff", color: "#333", cursor: "pointer", fontFamily: "inherit" },
  formCell: { padding: "0 12px 16px", background: "#f6f8fd", borderBottom: "1px solid #e4e4e8" },
  form: { background: "#fff", border: "1px solid #dfe5f3", borderRadius: 16, padding: 16, boxShadow: "0 6px 18px rgba(18,64,150,0.08)", whiteSpace: "normal" },
  formGrid: { display: "flex", flexWrap: "wrap", gap: 20 },
  formMain: { flex: "2 1 360px", display: "flex", flexDirection: "column", gap: 8, minWidth: 0 },
  formSide: { flex: "1 1 240px", display: "flex", flexDirection: "column", gap: 8, minWidth: 0 },
  fieldLabel: { fontSize: 12, fontWeight: 800, color: "#444", textTransform: "uppercase", letterSpacing: 0.4, marginTop: 4 },
  fieldError: { fontSize: 13, color: "#b3261e", fontWeight: 700 },
  hint: { fontSize: 13, color: "#8a5a00", fontWeight: 700 },
  textarea: { minHeight: 80, padding: 12, fontSize: 15, border: "1px solid #d0d0d5", borderRadius: 14, fontFamily: "inherit", resize: "vertical" },
  dateInput: { height: 48, padding: "0 14px", fontSize: 15, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 14, fontFamily: "inherit", background: "#fff" },
  formActions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 12 },
  secondary: { height: 48, padding: "0 20px", fontSize: 15, fontWeight: 800, border: "1px solid #d0d0d5", borderRadius: 14, background: "#fff", color: "#333", cursor: "pointer", fontFamily: "inherit" },
  subSection: { marginTop: 16, borderTop: "2px solid #ececf0", paddingTop: 12 },
  disclosure: { display: "inline-flex", alignItems: "center", gap: 10, height: 48, padding: "0 16px", border: "none", borderRadius: 14, background: "#f1f1f5", fontSize: 15, fontWeight: 800, color: "#333", cursor: "pointer", fontFamily: "inherit" },
  chevron: { display: "inline-block", fontSize: 20, lineHeight: 1, transition: "transform 160ms ease" },
  contactedList: { listStyle: "none", margin: "10px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  contactedItem: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, padding: "10px 12px", border: "1px solid #ececf0", borderRadius: 12 },
  contactedName: { fontWeight: 800 },
  contactedNote: { fontSize: 13, color: "#555", fontStyle: "italic" },
  capacityRead: { fontSize: 14, fontWeight: 700, color: "#444", padding: "0 6px" },
  capacityForm: { display: "flex", alignItems: "center", gap: 8, padding: 5, borderRadius: 16, background: "#e9e9ee", boxShadow: "inset 0 2px 4px rgba(0,0,0,0.12)", flexWrap: "wrap" },
  capacityLabel: { fontSize: 13, fontWeight: 800, color: "#444", padding: "0 6px 0 10px", whiteSpace: "nowrap" },
  capacityInput: { width: 76, height: 38, padding: "0 10px", fontSize: 16, fontWeight: 900, border: "none", borderRadius: 12, background: "#fff", boxShadow: "0 3px 8px rgba(18,64,150,0.18)", fontFamily: "inherit", fontVariantNumeric: "tabular-nums", textAlign: "center" },
  capacitySave: { height: 38, padding: "0 16px", fontSize: 14, fontWeight: 800, border: "none", borderRadius: 12, ...BUTTON_COLORS.blue, cursor: "pointer", fontFamily: "inherit" },
  capacitySaveIdle: { height: 38, padding: "0 16px", fontSize: 14, fontWeight: 800, border: "none", borderRadius: 12, background: "transparent", color: "#888", cursor: "default", fontFamily: "inherit" },
  capacityError: { flexBasis: "100%", fontSize: 13, fontWeight: 700, color: "#b3261e", padding: "0 10px 4px" },
  disclosureHint: { fontSize: 13, fontWeight: 600, color: "#777" },
  table: { width: "100%", minWidth: 860, borderCollapse: "collapse", fontSize: 14 },
  th: { textAlign: "left", padding: "10px 12px", fontSize: 12, fontWeight: 800, color: "#666", borderBottom: "2px solid #ececf0", whiteSpace: "nowrap", textTransform: "uppercase", letterSpacing: 0.4 },
  td: { padding: "12px", borderBottom: "1px solid #f0f0f3", whiteSpace: "nowrap", verticalAlign: "top" },
  tdName: { padding: "12px", borderBottom: "1px solid #f0f0f3", fontWeight: 800, verticalAlign: "top", whiteSpace: "nowrap" },
  rank: { padding: "12px", borderBottom: "1px solid #f0f0f3", fontWeight: 900, fontSize: 16, color: "#999", fontVariantNumeric: "tabular-nums", width: 40, verticalAlign: "top" },
  status: { marginLeft: 8, fontSize: 11, fontWeight: 800, padding: "2px 8px", borderRadius: 999, background: "#e6edfa", color: BLUE },
  badge: { display: "inline-flex", alignItems: "center", gap: 8, padding: "4px 10px", borderRadius: 999, border: "1px solid", fontSize: 13 },
  badgeLevel: { fontWeight: 900 },
  badgeScore: { fontWeight: 800, fontVariantNumeric: "tabular-nums", opacity: 0.8 },
  soon: { color: "#8a5a00", fontWeight: 700 },
  lapsed: { color: "#b3261e", fontWeight: 700 },
};

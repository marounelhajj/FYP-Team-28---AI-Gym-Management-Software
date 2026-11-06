import { useCallback, useEffect, useState } from "react";
import { fetchMyReminders, saveMyReminders } from "../../api/notifications.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// User story: "As a member, I want to receive notifications before an
// upcoming class or when my membership is about to renew, so that I don't
// miss sessions or get charged unexpectedly."
//
// The member picks when they're reminded; every change saves straight away.
// Reminders arrive under the bell (and as a desktop pop-up if allowed) and by
// email unless that's switched off. "Coming up" shows the next few reminders
// the server has lined up, so the settings can be seen at work.

const REFRESH_MS = 60000;
const KIND_LABELS = { class: "Class", pt: "Private training", renewal: "Membership" };
const canAlert = typeof window !== "undefined" && "Notification" in window;

function minutesLabel(minutes) {
  if (!minutes) return "Off";
  if (minutes < 60) return `${minutes} minutes before`;
  return `${minutes / 60} hour${minutes === 60 ? "" : "s"} before`;
}

function daysLabel(days) {
  if (!days) return "Off";
  return days === 1 ? "The day before" : `${days} days before`;
}

function formatSendAt(sendAt) {
  const day = new Date(`${sendAt.slice(0, 10)}T12:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return `${day} · ${sendAt.slice(11)}`;
}

export default function ReminderSettings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [permission, setPermission] = useState(canAlert ? Notification.permission : "unsupported");

  const load = useCallback(() => {
    return fetchMyReminders()
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!saved) return undefined;
    const timer = setTimeout(() => setSaved(false), 2500);
    return () => clearTimeout(timer);
  }, [saved]);

  async function change(field, value) {
    const previous = data;
    setData({ ...data, settings: { ...data.settings, [field]: value } });
    setSaving(true);
    setSaved(false);
    try {
      setData(await saveMyReminders({ [field]: value }));
      setError(null);
      setSaved(true);
    } catch (err) {
      setData(previous);
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function allowDesktop() {
    setPermission(await Notification.requestPermission());
  }

  if (!data) {
    return error ? (
      <div style={styles.errorBox}>Couldn&apos;t load your reminders: {error}</div>
    ) : (
      <p style={styles.muted}>Loading reminders...</p>
    );
  }

  const { settings, choices } = data;
  const renewalDays = settings.renewalDaysBefore;

  return (
    <section style={styles.card} aria-label="Reminders">
      <div style={styles.status} aria-live="polite">
        {saving ? "Saving..." : saved ? "Saved" : ""}
      </div>
      {error && <div style={styles.errorBox}>{error}</div>}

      <div style={styles.group}>
        <div style={styles.groupTitle}>Classes &amp; private training</div>
        <label style={styles.check}>
          <input
            type="checkbox"
            checked={settings.classDayBefore}
            onChange={(e) => change("classDayBefore", e.target.checked)}
          />
          The day before (24 hours ahead)
        </label>
        <label style={styles.field}>
          <span>Shortly before</span>
          <select
            value={settings.classMinutesBefore}
            onChange={(e) => change("classMinutesBefore", Number(e.target.value))}
            style={styles.select}
            aria-label="Remind me shortly before a class"
          >
            {choices.classMinutesBefore.map((m) => (
              <option key={m} value={m}>
                {minutesLabel(m)}
              </option>
            ))}
          </select>
        </label>
        {!settings.classDayBefore && !settings.classMinutesBefore && (
          <p style={styles.warn}>You won&apos;t be reminded about classes or sessions you book.</p>
        )}
      </div>

      <div style={styles.group}>
        <div style={styles.groupTitle}>Membership renewal</div>
        <label style={styles.field}>
          <span>Remind me</span>
          <select
            value={renewalDays}
            onChange={(e) => change("renewalDaysBefore", Number(e.target.value))}
            style={styles.select}
            aria-label="Remind me before my renewal date"
          >
            {choices.renewalDaysBefore.map((d) => (
              <option key={d} value={d}>
                {daysLabel(d)}
              </option>
            ))}
          </select>
        </label>
        <p style={styles.hint}>
          {renewalDays === 0
            ? "You won't be reminded - your renewal date is shown at the top of this page."
            : `At ${data.renewalHour}, ${
                renewalDays === 1 ? "the day before" : `${renewalDays} days before and again the day before`
              } your renewal date, with what renewing will cost.`}{" "}
          Nothing is ever charged automatically - you renew at the front desk.
        </p>
      </div>

      <div style={styles.group}>
        <div style={styles.groupTitle}>How you&apos;re told</div>
        <p style={styles.hint}>Always under the bell at the top of the app.</p>
        <label style={styles.check}>
          <input type="checkbox" checked={settings.email} onChange={(e) => change("email", e.target.checked)} />
          Also email me{data.emailAddress ? ` at ${data.emailAddress}` : ""}
        </label>
        <div style={styles.desktopRow}>
          {permission === "granted" && <span style={styles.ok}>Desktop pop-ups are on in this browser.</span>}
          {permission === "default" && (
            <>
              <span style={styles.hint}>Desktop pop-ups are off in this browser.</span>
              <button type="button" onClick={allowDesktop} style={styles.blueButton}>
                Turn on pop-ups
              </button>
            </>
          )}
          {permission === "denied" && (
            <span style={styles.hint}>Desktop pop-ups are blocked - allow notifications for this site in the browser settings.</span>
          )}
          {permission === "unsupported" && <span style={styles.hint}>This browser can&apos;t show desktop pop-ups.</span>}
        </div>
      </div>

      <div style={styles.group}>
        <div style={styles.groupTitle}>Coming up</div>
        {data.upcoming.length === 0 ? (
          <p style={styles.hint}>No reminders lined up. Book a class and its reminders show here.</p>
        ) : (
          <ul style={styles.list}>
            {data.upcoming.slice(0, 5).map((u) => (
              <li key={`${u.kind}-${u.about}-${u.sendAt}`} style={styles.item}>
                <span style={{ ...styles.kindTag, ...(u.kind === "renewal" ? styles.renewalTag : null) }}>
                  {KIND_LABELS[u.kind]}
                </span>
                <span style={styles.about}>{u.about}</span>
                <span style={styles.sendAt}>{formatSendAt(u.sendAt)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

const styles = {
  card: {
    position: "relative",
    padding: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  status: { position: "absolute", top: 12, right: 16, fontSize: 12, color: "#1e7a34", fontWeight: 600 },
  group: { display: "flex", flexDirection: "column", gap: 8 },
  groupTitle: { fontSize: 14, fontWeight: 700 },
  check: { display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" },
  field: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, fontSize: 13 },
  select: {
    padding: "6px 8px",
    fontSize: 13,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    fontFamily: "inherit",
  },
  hint: { fontSize: 12, color: "#666", margin: 0, lineHeight: 1.5 },
  warn: { fontSize: 12, color: "#a15c00", margin: 0 },
  ok: { fontSize: 12, color: "#1e7a34" },
  muted: { fontSize: 13, color: "#888" },
  desktopRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" },
  blueButton: {
    padding: "6px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.blue,
    cursor: "pointer",
  },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  item: { display: "flex", alignItems: "center", gap: 8, fontSize: 13 },
  kindTag: {
    flexShrink: 0,
    fontSize: 10,
    fontWeight: 700,
    padding: "2px 6px",
    borderRadius: 4,
    background: "#eef2fa",
    color: "#124096",
  },
  renewalTag: { background: "#fff1d6", color: "#8a5300" },
  about: { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  sendAt: { flexShrink: 0, fontSize: 12, color: "#666" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "8px 12px",
    borderRadius: 8,
    fontSize: 13,
  },
};

import { useCallback, useEffect, useRef, useState } from "react";
import { staffNotificationsApi } from "../api/notifications.js";

const POLL_MS = 20000;
const canAlert = typeof window !== "undefined" && "Notification" in window;

// The top bar's bell: the signed-in person's own notifications, newest first.
// Staff see theirs (SCRUM-128 capacity alerts); a member passes
// api={memberNotificationsApi} for theirs (waitlist spots, cancelled classes).
// Polls, since the app has no push channel.
//
// desktopAlerts: also pop up an operating-system notification - the
// browser's built-in Notification API, no outside service - for each new
// unread one, once the person allows it. Works while the app is open in a tab.
export default function NotificationBell({ api = staffNotificationsApi, desktopAlerts = false }) {
  const [data, setData] = useState({ unread: 0, results: [] });
  const [open, setOpen] = useState(false);
  const [permission, setPermission] = useState(canAlert ? Notification.permission : "unsupported");
  const wrap = useRef(null);
  const known = useRef(null); // ids already seen, so only new ones pop up

  const load = useCallback(
    () =>
      api
        .fetch()
        .then((body) => {
          setData(body);
          if (!desktopAlerts) return;
          const before = known.current;
          known.current = new Set(body.results.map((n) => n.id));
          if (!before || !canAlert || Notification.permission !== "granted") return;
          body.results
            .filter((n) => !n.read && !before.has(n.id))
            .forEach((n) => {
              try {
                new Notification(n.title, { body: n.message, tag: `ff-notification-${n.id}`, icon: "/logo-badge.png" });
              } catch {
                // Some browsers only allow notifications from a service worker; the bell still shows it.
              }
            });
        })
        .catch(() => {}),
    [api, desktopAlerts],
  );

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!open) return undefined;
    function onClick(e) {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function readOne(n) {
    if (!n.read) await api.markRead(n.id).catch(() => {});
    load();
  }

  async function readAll() {
    await api.markAllRead().catch(() => {});
    load();
  }

  async function allowAlerts() {
    setPermission(await Notification.requestPermission());
  }

  return (
    <div ref={wrap} style={styles.wrap}>
      <style>{CSS}</style>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${data.unread ? `, ${data.unread} unread` : ""}`}
        aria-expanded={open}
        className="nb-press"
        style={styles.bell}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path
            d="M12 3a6 6 0 0 0-6 6v3.6L4.3 16a1 1 0 0 0 .9 1.5h13.6a1 1 0 0 0 .9-1.5L18 12.6V9a6 6 0 0 0-6-6zm-2.5 16a2.5 2.5 0 0 0 5 0z"
            fill="currentColor"
          />
        </svg>
        {data.unread > 0 && <span style={styles.badge}>{data.unread > 9 ? "9+" : data.unread}</span>}
      </button>

      {open && (
        <div role="dialog" aria-label="Notifications" className="nb-pop" style={styles.popover}>
          <div style={styles.popHeader}>
            <span style={styles.popTitle}>
              Notifications <b style={styles.popCount}>{data.unread}</b>
            </span>
            {data.unread > 0 && (
              <button type="button" onClick={readAll} style={styles.linkButton}>
                Mark all read
              </button>
            )}
          </div>
          {desktopAlerts && permission === "default" && (
            <div style={styles.alertsRow}>
              <span>Get a pop-up on this computer too?</span>
              <button type="button" onClick={allowAlerts} style={styles.linkButton}>
                Turn on desktop alerts
              </button>
            </div>
          )}
          {desktopAlerts && permission === "denied" && (
            <div style={styles.alertsRow}>Desktop alerts are blocked in this browser&apos;s site settings.</div>
          )}
          {data.results.length === 0 ? (
            <div style={styles.empty}>Nothing yet.</div>
          ) : (
            <ul style={styles.list}>
              {data.results.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => readOne(n)} style={{ ...styles.item, ...(n.read ? null : styles.unread) }}>
                    <span style={styles.itemTitle}>
                      {!n.read && <span style={styles.dot} aria-label="Unread" />}
                      {n.title}
                    </span>
                    <span style={styles.itemText}>{n.message}</span>
                    <span style={styles.itemTime}>{n.createdAt}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const CSS = `
.nb-press { transition: transform 120ms ease, background 160ms ease; }
.nb-press:active { transform: scale(0.94); }
.nb-press:focus-visible { outline: 2px solid #124096; outline-offset: 2px; }
.nb-pop { animation: nb-in 160ms ease-out; transform-origin: top right; }
@keyframes nb-in { from { opacity: 0; transform: translateY(-4px) scale(0.98); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .nb-press, .nb-pop { transition: none; animation: none; } }
`;

const styles = {
  wrap: { position: "relative" },
  bell: {
    position: "relative", width: 40, height: 40, borderRadius: 12, border: "1px solid #d0d0d5",
    background: "#fff", color: "#1a1a1a", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
  },
  badge: {
    position: "absolute", top: -6, right: -6, minWidth: 20, height: 20, padding: "0 5px", borderRadius: 10,
    background: "#b3261e", color: "#fff", fontSize: 11, fontWeight: 800, display: "flex", alignItems: "center",
    justifyContent: "center", boxShadow: "0 0 0 2px #f0f0f3",
  },
  popover: {
    position: "absolute", right: 0, top: 48, width: 340, maxWidth: "calc(100vw - 32px)", maxHeight: 420,
    overflowY: "auto", background: "#fff", border: "1px solid #e0e0e5", borderRadius: 16,
    boxShadow: "0 12px 32px rgba(0,0,0,0.18)", zIndex: 60, textAlign: "left",
  },
  popHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", borderBottom: "1px solid #f0f0f2" },
  popTitle: { fontSize: 15, fontWeight: 800 },
  popCount: { marginLeft: 4 },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 700, cursor: "pointer" },
  alertsRow: {
    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap",
    padding: "8px 14px", fontSize: 12, color: "#555", background: "#fafafb", borderBottom: "1px solid #f0f0f2",
  },
  empty: { padding: 18, fontSize: 13, color: "#888", textAlign: "center" },
  list: { listStyle: "none", margin: 0, padding: 0 },
  item: {
    display: "flex", flexDirection: "column", gap: 3, width: "100%", padding: "12px 14px", border: "none",
    borderBottom: "1px solid #f0f0f2", background: "#fff", textAlign: "left", cursor: "pointer", fontFamily: "inherit",
  },
  unread: { background: "#f3f6fd" },
  itemTitle: { display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 800, color: "#1a1a1a" },
  dot: { width: 8, height: 8, borderRadius: 4, background: "#b3261e", flexShrink: 0 },
  itemText: { fontSize: 13, color: "#444", lineHeight: 1.4 },
  itemTime: { fontSize: 11, color: "#888" },
};

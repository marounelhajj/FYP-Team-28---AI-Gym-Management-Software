import { useEffect, useState } from "react";
import { fetchLiveHeadcount } from "../../api/headcount.js";

// While the feed is down, retry this often (the normal refresh rate comes
// from the server's refreshSeconds).
const RETRY_MS = 5000;

// Polls /api/headcount/live so the count updates without a manual refresh
// (SCRUM-127). There's no WebSocket or server-sent events setup in this
// project, so polling is the simplest thing that works on the Django dev
// server and anywhere it's deployed.
//
// status:
//   "loading"      - first request for this branch hasn't come back yet
//   "live"         - the last poll succeeded
//   "reconnecting" - the last poll failed; `data` still holds the last
//                    known count and `lastUpdated` says when it was fetched
//   "denied"       - the server refused (wrong branch, no branch assigned,
//                    permission removed); retrying won't help
//
// Also refreshes straight away when the tab becomes visible again or the
// browser comes back online, instead of waiting for the next tick.
export function useLiveHeadcount(branch) {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    // A different branch's count must never show under this branch's name.
    setData(null);
    setLastUpdated(null);
    setStatus("loading");
    setError(null);

    async function poll() {
      clearTimeout(timer);
      try {
        const body = await fetchLiveHeadcount(branch);
        if (cancelled) return;
        setData(body);
        setLastUpdated(new Date());
        setStatus("live");
        setError(null);
        timer = setTimeout(poll, (body.refreshSeconds || 15) * 1000);
      } catch (err) {
        if (cancelled) return;
        setError(err.message);
        if (err.status === 400 || err.status === 401 || err.status === 403) {
          setStatus("denied");
          return;
        }
        setStatus("reconnecting");
        timer = setTimeout(poll, RETRY_MS);
      }
    }

    function onVisible() {
      if (document.visibilityState === "visible") poll();
    }

    poll();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", poll);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", poll);
    };
  }, [branch]);

  return { data, status, error, lastUpdated };
}

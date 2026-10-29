import { useEffect, useState } from "react";

// A clock that shows the gym's time (Beirut), not the browser's: it starts
// from the server's "now" (nowIso, with its UTC offset) and keeps ticking from
// there, so it's right even on a laptop set to another time zone or with a
// clock that's a few minutes off.
export default function useServerClock(nowIso, timeZone) {
  const [skew, setSkew] = useState(0);
  const [tick, setTick] = useState(() => Date.now());

  useEffect(() => {
    if (nowIso) setSkew(Date.parse(nowIso) - Date.now());
  }, [nowIso]);

  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), 15000);
    return () => clearInterval(timer);
  }, []);

  const now = new Date(tick + skew);
  const zone = timeZone || undefined;
  return {
    time: new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(now),
    day: new Intl.DateTimeFormat("en-GB", { timeZone: zone, weekday: "short", day: "numeric", month: "short" }).format(now),
  };
}

// "UTC+2" from "+02:00".
export function offsetLabel(utcOffset) {
  if (!utcOffset) return "";
  const [hours, minutes] = utcOffset.slice(1).split(":").map(Number);
  return `UTC${utcOffset[0]}${hours}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""}`;
}

import { useEffect, useRef, useState } from "react";
import { fetchHourlyHeadcount } from "../../api/headcount.js";

// User story (SCRUM-129): "As a branch manager, I want to view headcount by
// hour for the current day, so that I can see when my peaks actually fall."
//
// Bars: today, hour by hour (how many different members were inside during
// that hour). Line: the average for the same weekday over the last few
// weeks. The API returns counts only - nobody is identifiable here.

const REFRESH_MS = 60000;
const HEIGHT = 220;
const MARGIN = { top: 14, right: 8, bottom: 28, left: 34 };

const COLORS = {
  today: "#2a78d6",
  average: "#eb6834",
  text: "#1a1a1a",
  secondary: "#555",
  axis: "#6b6b72",
  grid: "#e9e9ee",
  baseline: "#c3c2b7",
  highlight: "#f1f4fa",
};

function hourLabel(hour) {
  return new Date(2000, 0, 1, hour).toLocaleTimeString([], { hour: "numeric" });
}

function niceStep(max) {
  const raw = max / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw);
  return Math.max(1, step);
}

// The hours come from the server's clock. Say which one when it isn't the
// viewer's, so "Now" next to a 9 AM "updated" time doesn't look wrong.
function timeZoneNote(serverZone) {
  let viewerZone = "";
  try {
    viewerZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "";
  }
  const offset = (zone) => {
    try {
      return new Date().toLocaleString("en-US", { timeZone: zone });
    } catch {
      return null;
    }
  };
  if (!serverZone || offset(serverZone) === offset(viewerZone)) return "";
  return `Hours are in ${serverZone === "UTC" ? "UTC" : serverZone.replace("_", " ")}.`;
}

function formatAverage(value) {
  return value === null ? "–" : Number.isInteger(value) ? String(value) : value.toFixed(1);
}

// Opening hours vary, so show 6 AM-10 PM and stretch to any hour with data.
function visibleHours(hours) {
  const active = hours.filter((h) => h.today > 0 || h.weekdayAverage > 0).map((h) => h.hour);
  const lo = Math.min(6, ...active);
  const hi = Math.max(22, ...active);
  return hours.filter((h) => h.hour >= lo && h.hour <= hi);
}

// Bar with a 4px-rounded top, anchored flat on the baseline.
function barPath(x, y, width, height) {
  if (height <= 0) return "";
  const r = Math.min(4, width / 2, height);
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

function useHourly(branch) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    setData(null);
    setFailed(false);

    async function poll() {
      clearTimeout(timer);
      try {
        const body = await fetchHourlyHeadcount(branch);
        if (cancelled) return;
        setData(body);
        setFailed(false);
      } catch (err) {
        if (cancelled) return;
        // Keep the last chart on screen; the live count above already shows
        // the connection state.
        setFailed(true);
        if (err.status === 400 || err.status === 401 || err.status === 403) return;
      }
      timer = setTimeout(poll, REFRESH_MS);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [branch]);

  return { data, failed };
}

function Summary({ data }) {
  const sofar = data.hours.filter((h) => h.today !== null);
  const peak = sofar.reduce((best, h) => (h.today > (best?.today ?? 0) ? h : best), null);
  const usual = data.weeksCompared
    ? data.hours.reduce((best, h) => (h.weekdayAverage > (best?.weekdayAverage ?? 0) ? h : best), null)
    : null;

  return (
    <p style={styles.summary}>
      {peak ? (
        <>
          Busiest so far: <strong>{hourLabel(peak.hour)}</strong> with <strong>{peak.today}</strong>{" "}
          {peak.today === 1 ? "member" : "members"}.
        </>
      ) : (
        "Nobody has checked in yet today."
      )}{" "}
      {usual && (
        <>
          {data.weekday}s usually peak at <strong>{hourLabel(usual.hour)}</strong> (
          {formatAverage(usual.weekdayAverage)} on average).
        </>
      )}
    </p>
  );
}

export default function HourlyChart({ branch }) {
  const { data } = useHourly(branch);
  const wrapRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const hasAverage = data?.weeksCompared > 0;
  const hours = data ? visibleHours(data.hours) : [];
  const yMaxRaw = Math.max(4, ...hours.map((h) => Math.max(h.today ?? 0, h.weekdayAverage ?? 0)));
  const step = niceStep(yMaxRaw);
  const yMax = Math.ceil(yMaxRaw / step) * step;
  const ticks = Array.from({ length: yMax / step + 1 }, (_, i) => i * step);

  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const band = hours.length ? innerW / hours.length : 0;
  const barW = Math.max(2, Math.min(28, band - 4));
  const x = (i) => MARGIN.left + i * band;
  const y = (v) => MARGIN.top + innerH - (v / yMax) * innerH;
  const labelEvery = band < 22 ? 3 : band < 34 ? 2 : 1;

  const avgPoints = hasAverage
    ? hours.map((h, i) => `${x(i) + band / 2},${y(h.weekdayAverage)}`).join(" ")
    : "";
  const nowIndex = data ? hours.findIndex((h) => h.hour === data.currentHour) : -1;
  // Every labelEvery-th hour gets a label, plus "Now" - minus any label
  // that would collide with "Now".
  const showLabel = (i) =>
    i === nowIndex || (i % labelEvery === 0 && (nowIndex < 0 || Math.abs(i - nowIndex) >= labelEvery));
  const activeIndex = hours.findIndex((h) => h.hour === active);
  const activeHour = activeIndex >= 0 ? hours[activeIndex] : null;

  function onKeyDown(event) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step || !hours.length) return;
    event.preventDefault();
    const current = activeIndex >= 0 ? activeIndex : hours.findIndex((h) => h.hour === data.currentHour);
    const next = Math.min(hours.length - 1, Math.max(0, (current < 0 ? 0 : current) + step));
    setActive(hours[next].hour);
  }

  const ariaLabel = data
    ? `Headcount by hour today at ${data.branch}` +
      (hasAverage ? `, compared with the average ${data.weekday} over the last ${data.weeksCompared} weeks` : "") +
      ". Use the left and right arrow keys to read each hour."
    : "Headcount by hour";

  return (
    <div style={styles.wrap}>
      <div style={styles.head}>
        <h3 style={styles.title}>Today by hour</h3>
        {data && (
          <div style={styles.legend}>
            <span style={styles.legendItem}>
              <span style={{ ...styles.swatch, background: COLORS.today }} aria-hidden="true" />
              Today
            </span>
            {hasAverage ? (
              <span style={styles.legendItem}>
                <svg width="22" height="10" aria-hidden="true">
                  <line x1="0" y1="5" x2="22" y2="5" stroke={COLORS.average} strokeWidth="2" />
                  <circle cx="11" cy="5" r="4" fill={COLORS.average} stroke="#fff" strokeWidth="2" />
                </svg>
                Usual {data.weekday} (avg. of last {data.weeksCompared} {data.weeksCompared === 1 ? "week" : "weeks"})
              </span>
            ) : (
              <span style={styles.legendNote}>No past {data.weekday}s to compare with yet</span>
            )}
          </div>
        )}
      </div>

      {data && <Summary data={data} />}
      {data && timeZoneNote(data.timeZone) && <p style={styles.tzNote}>{timeZoneNote(data.timeZone)}</p>}

      <div ref={wrapRef} style={styles.chartBox} onMouseLeave={() => setActive(null)}>
        {data && width > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={ariaLabel}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onBlur={() => setActive(null)}
            className="hc-focus"
            style={styles.svg}
          >
            {activeHour && (
              <rect x={x(activeIndex)} y={MARGIN.top} width={band} height={innerH} fill={COLORS.highlight} rx="6" />
            )}
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={MARGIN.left}
                  x2={width - MARGIN.right}
                  y1={y(t)}
                  y2={y(t)}
                  stroke={t === 0 ? COLORS.baseline : COLORS.grid}
                  strokeWidth="1"
                />
                <text x={MARGIN.left - 8} y={y(t)} dy="0.32em" textAnchor="end" style={styles.axisText}>
                  {t}
                </text>
              </g>
            ))}
            <g className="hc-grow">
              {hours.map((h, i) =>
                h.today ? (
                  <path
                    key={h.hour}
                    d={barPath(x(i) + (band - barW) / 2, y(h.today), barW, y(0) - y(h.today))}
                    fill={COLORS.today}
                    opacity={h.hour === data.currentHour ? 0.65 : 1}
                  />
                ) : null,
              )}
            </g>
            {hasAverage && (
              <g>
                <polyline points={avgPoints} fill="none" stroke={COLORS.average} strokeWidth="2" strokeLinejoin="round" />
                {hours.map((h, i) => (
                  <circle
                    key={h.hour}
                    cx={x(i) + band / 2}
                    cy={y(h.weekdayAverage)}
                    r={h.hour === active ? 5 : 4}
                    fill={COLORS.average}
                    stroke="#fff"
                    strokeWidth="2"
                  />
                ))}
              </g>
            )}
            {hours.map((h, i) =>
              showLabel(i) ? (
                <text
                  key={h.hour}
                  x={x(i) + band / 2}
                  y={HEIGHT - 8}
                  textAnchor="middle"
                  style={h.hour === data.currentHour ? styles.axisNow : styles.axisText}
                >
                  {h.hour === data.currentHour ? "Now" : hourLabel(h.hour)}
                </text>
              ) : null,
            )}
            {hours.map((h, i) => (
              <rect
                key={h.hour}
                x={x(i)}
                y={MARGIN.top}
                width={band}
                height={innerH + MARGIN.bottom}
                fill="transparent"
                onMouseEnter={() => setActive(h.hour)}
              />
            ))}
          </svg>
        )}
        {activeHour && (
          <div
            role="status"
            style={{
              ...styles.tooltip,
              // Beside the hovered hour, flipping to its left past the middle.
              ...(x(activeIndex) + band / 2 < width / 2
                ? { left: x(activeIndex) + band + 8 }
                : { right: width - x(activeIndex) + 8 }),
            }}
          >
            <div style={styles.tooltipTitle}>
              {hourLabel(activeHour.hour)} – {hourLabel((activeHour.hour + 1) % 24)}
              {activeHour.hour === data.currentHour && " (so far)"}
            </div>
            <div style={styles.tooltipRow}>
              <span style={{ ...styles.swatch, background: COLORS.today }} aria-hidden="true" />
              Today <strong style={styles.tooltipValue}>{activeHour.today ?? "–"}</strong>
            </div>
            {hasAverage && (
              <div style={styles.tooltipRow}>
                <span style={{ ...styles.swatch, background: COLORS.average, borderRadius: "50%" }} aria-hidden="true" />
                Usual {data.weekday}
                <strong style={styles.tooltipValue}>{formatAverage(activeHour.weekdayAverage)}</strong>
              </div>
            )}
          </div>
        )}
        {!data && <div style={styles.placeholder}>Loading today's hours…</div>}
      </div>

      {data && (
        <details style={styles.details}>
          <summary style={styles.detailsSummary} className="hc-focus">
            Show as a table
          </summary>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Hour</th>
                <th style={styles.thNum}>Today</th>
                {hasAverage && <th style={styles.thNum}>Usual {data.weekday}</th>}
              </tr>
            </thead>
            <tbody>
              {hours.map((h) => (
                <tr key={h.hour}>
                  <td style={styles.td}>{hourLabel(h.hour)}</td>
                  <td style={styles.tdNum}>{h.today ?? "–"}</td>
                  {hasAverage && <td style={styles.tdNum}>{formatAverage(h.weekdayAverage)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

const styles = {
  wrap: { borderTop: "1px solid #eceef3", paddingTop: 20, paddingBottom: 24 },
  head: { display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 },
  title: { margin: 0, fontSize: 18, fontWeight: 800 },
  legend: { display: "flex", flexWrap: "wrap", gap: 16, fontSize: 13, fontWeight: 700, color: COLORS.secondary },
  legendItem: { display: "inline-flex", alignItems: "center", gap: 6 },
  legendNote: { fontWeight: 600, color: COLORS.axis },
  swatch: { display: "inline-block", width: 10, height: 10, borderRadius: 3 },
  summary: { margin: "8px 0 4px", fontSize: 14, color: COLORS.secondary, lineHeight: 1.5 },
  tzNote: { margin: "0 0 4px", fontSize: 12, color: COLORS.axis },
  chartBox: { position: "relative", minHeight: HEIGHT, marginTop: 8 },
  svg: { display: "block", overflow: "visible", borderRadius: 8 },
  axisText: { fontSize: 11, fill: COLORS.axis, fontVariantNumeric: "tabular-nums" },
  axisNow: { fontSize: 11, fontWeight: 800, fill: COLORS.text },
  placeholder: { height: HEIGHT, display: "flex", alignItems: "center", justifyContent: "center", color: "#888", fontSize: 14 },
  tooltip: {
    position: "absolute",
    top: MARGIN.top,
    minWidth: 150,
    padding: "10px 12px",
    borderRadius: 12,
    background: "#fff",
    border: "1px solid #e4e4e8",
    boxShadow: "0 6px 20px rgba(20, 30, 60, 0.16)",
    fontSize: 13,
    color: COLORS.secondary,
    pointerEvents: "none",
    whiteSpace: "nowrap",
  },
  tooltipTitle: { fontWeight: 800, color: COLORS.text, marginBottom: 6 },
  tooltipRow: { display: "flex", alignItems: "center", gap: 6, lineHeight: 1.7 },
  tooltipValue: { marginLeft: "auto", paddingLeft: 12, color: COLORS.text, fontVariantNumeric: "tabular-nums" },
  details: { marginTop: 12, fontSize: 13 },
  detailsSummary: { cursor: "pointer", fontWeight: 700, color: "#124096", width: "fit-content", borderRadius: 4 },
  table: { marginTop: 8, borderCollapse: "collapse", minWidth: 260 },
  th: { textAlign: "left", padding: "6px 12px 6px 0", borderBottom: "1px solid #e4e4e8", color: COLORS.secondary },
  thNum: { textAlign: "right", padding: "6px 0 6px 12px", borderBottom: "1px solid #e4e4e8", color: COLORS.secondary },
  td: { padding: "4px 12px 4px 0", borderBottom: "1px solid #f0f0f3" },
  tdNum: { textAlign: "right", padding: "4px 0 4px 12px", borderBottom: "1px solid #f0f0f3", fontVariantNumeric: "tabular-nums" },
};

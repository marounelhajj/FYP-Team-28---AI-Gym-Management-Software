import { useEffect, useRef, useState } from "react";

// SCRUM-112: SVG Line chart for attendance trends comparing up to 3 segments against all members.

const HEIGHT = 280;
const MARGIN = { top: 24, right: 24, bottom: 36, left: 48 };

const SERIES_COLORS = [
  "#71717a", // All members: neutral grey
  "#124096", // Segment 1: primary blue
  "#eb6834", // Segment 2: vibrant orange
  "#129638", // Segment 3: green
];

export { SERIES_COLORS };

function niceStep(max, targetTicks = 5) {
  if (max <= 0) return 1;
  const raw = max / targetTicks;
  const power = 10 ** Math.floor(Math.log10(raw));
  const mult = raw / power;
  let stepMultiplier = 1;
  if (mult > 5) stepMultiplier = 10;
  else if (mult > 2) stepMultiplier = 5;
  else if (mult > 1) stepMultiplier = 2;
  return Math.max(0.1, stepMultiplier * power);
}

export default function TrendChart({ periods = [], series = [], metric = "visitsPerMember" }) {
  const containerRef = useRef(null);
  const [width, setWidth] = useState(0);
  const [activeIdx, setActiveIdx] = useState(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const metricKey = metric === "visitsPerMember" ? "visitsPerMember" : "visits";
  const isDecimal = metric === "visitsPerMember";
  // No members in the segment yet in that period: a gap, not a zero.
  const valueOf = (pt) => (!pt || !pt.activeMembers || pt[metricKey] == null ? null : pt[metricKey]);

  // Calculate Y domain
  let maxVal = 0;
  for (const s of series) {
    for (const pt of s.points || []) {
      const v = valueOf(pt) || 0;
      if (v > maxVal) maxVal = v;
    }
  }
  if (maxVal === 0) maxVal = isDecimal ? 2.0 : 10;

  const step = isDecimal ? (maxVal > 5 ? 1 : 0.5) : niceStep(maxVal, 4);
  const yMax = Math.ceil(maxVal / step) * step;
  const numTicks = Math.round(yMax / step);
  const ticks = Array.from({ length: numTicks + 1 }, (_, i) => +(i * step).toFixed(2));

  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const n = periods.length;

  const x = (i) => MARGIN.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const y = (v) => MARGIN.top + innerH - (yMax > 0 ? (v / yMax) * innerH : 0);

  // Label density
  const labelEvery = width < 480 ? (n > 8 ? 3 : 2) : width < 720 ? (n > 10 ? 2 : 1) : 1;

  function handleKeyDown(e) {
    if (n === 0) return;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      setActiveIdx((prev) => (prev === null ? 0 : Math.min(n - 1, prev + 1)));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      setActiveIdx((prev) => (prev === null ? n - 1 : Math.max(0, prev - 1)));
    }
  }

  const activePeriod = activeIdx !== null && activeIdx >= 0 && activeIdx < n ? periods[activeIdx] : null;

  return (
    <div style={styles.chartWrap}>
      <style>{CHART_CSS}</style>

      {/* Legend */}
      <div style={styles.legend}>
        {series.map((s, idx) => {
          const color = SERIES_COLORS[idx % SERIES_COLORS.length];
          const isAll = s.key === "all";
          return (
            <div key={s.key ?? idx} style={styles.legendItem}>
              <span
                style={{
                  ...styles.legendSwatch,
                  background: isAll ? "#71717a" : color,
                  border: isAll ? "2px dashed #71717a" : "none",
                }}
                aria-hidden="true"
              />
              <span style={styles.legendLabel}>
                {s.name} <strong style={styles.legendSize}>({s.size})</strong>
              </span>
            </div>
          );
        })}
      </div>

      {/* SVG Canvas */}
      <div
        ref={containerRef}
        style={styles.svgContainer}
        onMouseLeave={() => setActiveIdx(null)}
      >
        {width > 0 && n > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`Attendance trend chart: ${metric === "visitsPerMember" ? "Visits per member" : "Total visits"} over ${n} periods.`}
            tabIndex={0}
            onKeyDown={handleKeyDown}
            onBlur={() => setActiveIdx(null)}
            style={styles.svg}
          >
            {/* Grid & Y Axis */}
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={MARGIN.left}
                  x2={width - MARGIN.right}
                  y1={y(t)}
                  y2={y(t)}
                  stroke={t === 0 ? "#b0b0b8" : "#e9e9ee"}
                  strokeWidth="1"
                />
                <text
                  x={MARGIN.left - 8}
                  y={y(t)}
                  dy="0.32em"
                  textAnchor="end"
                  style={styles.axisText}
                >
                  {isDecimal ? t.toFixed(1) : t}
                </text>
              </g>
            ))}

            {/* Active Period Highlight Guide */}
            {activeIdx !== null && (
              <line
                x1={x(activeIdx)}
                x2={x(activeIdx)}
                y1={MARGIN.top}
                y2={MARGIN.top + innerH}
                stroke="#124096"
                strokeWidth="1.5"
                strokeDasharray="4 3"
                opacity="0.75"
              />
            )}

            {/* Series Lines */}
            {series.map((s, idx) => {
              const color = SERIES_COLORS[idx % SERIES_COLORS.length];
              const isAll = s.key === "all";
              const pts = s.points || [];
              // One polyline per unbroken run of values, so gaps stay gaps.
              const runs = [];
              pts.forEach((pt, i) => {
                const v = valueOf(pt);
                if (v == null) {
                  runs.push(null);
                  return;
                }
                const last = runs[runs.length - 1];
                if (!last) runs.push([`${x(i)},${y(v)}`]);
                else last.push(`${x(i)},${y(v)}`);
              });

              return (
                <g key={s.key ?? idx}>
                  {runs.filter(Boolean).map((run, r) => (
                    <polyline
                      key={r}
                      points={run.join(" ")}
                      fill="none"
                      stroke={color}
                      strokeWidth={isAll ? 2.5 : 3}
                      strokeDasharray={isAll ? "5 4" : "none"}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      style={{ transition: "stroke 200ms ease" }}
                    />
                  ))}
                  {pts.map((pt, i) => {
                    if (valueOf(pt) == null) return null;
                    const cx = x(i);
                    const cy = y(valueOf(pt));
                    const isHovered = activeIdx === i;

                    return (
                      <circle
                        key={i}
                        cx={cx}
                        cy={cy}
                        r={isHovered ? 6 : isAll ? 3.5 : 4.5}
                        fill={color}
                        stroke="#fff"
                        strokeWidth="2"
                        style={{ transition: "r 120ms ease" }}
                      />
                    );
                  })}
                </g>
              );
            })}

            {/* X Axis Labels */}
            {periods.map((p, i) => {
              const show = i % labelEvery === 0 || i === n - 1;
              if (!show) return null;
              return (
                <text
                  key={p.start}
                  x={x(i)}
                  y={HEIGHT - 10}
                  textAnchor="middle"
                  style={activeIdx === i ? styles.axisActiveText : styles.axisText}
                >
                  {p.label}
                </text>
              );
            })}

            {/* Transparent Touch/Click Targets for Hover */}
            {periods.map((p, i) => {
              const colW = innerW / n;
              return (
                <rect
                  key={p.start}
                  x={x(i) - colW / 2}
                  y={MARGIN.top}
                  width={colW}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setActiveIdx(i)}
                  style={{ cursor: "pointer" }}
                />
              );
            })}
          </svg>
        )}

        {/* Hover / Focus Tooltip */}
        {activePeriod && activeIdx !== null && (
          <div
            style={{
              ...styles.tooltip,
              left: Math.min(
                Math.max(10, x(activeIdx) - 100),
                (width || 400) - 210
              ),
              top: MARGIN.top + 6,
            }}
            role="tooltip"
          >
            <div style={styles.tooltipHeader}>
              <strong>{activePeriod.label}</strong>
              <span style={styles.tooltipDates}>
                {activePeriod.start} → {activePeriod.end}
              </span>
            </div>
            <div style={styles.tooltipRows}>
              {series.map((s, idx) => {
                const color = SERIES_COLORS[idx % SERIES_COLORS.length];
                const pt = s.points?.[activeIdx];
                if (!pt) return null;
                return (
                  <div key={s.key ?? idx} style={styles.tooltipRow}>
                    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ ...styles.tooltipDot, background: color }} />
                      <span style={styles.tooltipSeriesName}>{s.name}</span>
                    </span>
                    <strong style={styles.tooltipVal}>
                      {valueOf(pt) == null
                        ? "No members yet"
                        : metric === "visitsPerMember"
                          ? `${pt.visitsPerMember.toFixed(2)} / member`
                          : `${pt.visits.toLocaleString()} visits`}
                    </strong>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const CHART_CSS = `
.trend-focus:focus-visible {
  outline: 3px solid #124096;
  outline-offset: 2px;
}
`;

const styles = {
  chartWrap: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  legend: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
    alignItems: "center",
    padding: "4px 0",
  },
  legendItem: {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    fontSize: 13,
  },
  legendSwatch: {
    width: 14,
    height: 14,
    borderRadius: 4,
    flexShrink: 0,
  },
  legendLabel: {
    color: "#333",
    fontWeight: 600,
  },
  legendSize: {
    color: "#777",
    fontWeight: 700,
  },
  svgContainer: {
    position: "relative",
    width: "100%",
    height: HEIGHT,
    outline: "none",
  },
  svg: {
    display: "block",
    overflow: "visible",
  },
  axisText: {
    fontSize: 11,
    fill: "#6b6b72",
    fontWeight: 600,
    fontFamily: "inherit",
  },
  axisActiveText: {
    fontSize: 12,
    fill: "#124096",
    fontWeight: 800,
    fontFamily: "inherit",
  },
  tooltip: {
    position: "absolute",
    pointerEvents: "none",
    background: "rgba(255, 255, 255, 0.96)",
    border: "1px solid #d0d0d8",
    borderRadius: 10,
    padding: "10px 12px",
    boxShadow: "0 6px 20px rgba(0, 0, 0, 0.12)",
    zIndex: 10,
    minWidth: 190,
    backdropFilter: "blur(4px)",
  },
  tooltipHeader: {
    display: "flex",
    flexDirection: "column",
    borderBottom: "1px solid #e8e8ed",
    paddingBottom: 6,
    marginBottom: 6,
    fontSize: 12,
  },
  tooltipDates: {
    fontSize: 11,
    color: "#666",
    marginTop: 2,
  },
  tooltipRows: {
    display: "flex",
    flexDirection: "column",
    gap: 5,
  },
  tooltipRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    fontSize: 12,
    gap: 10,
  },
  tooltipDot: {
    width: 8,
    height: 8,
    borderRadius: 2,
    flexShrink: 0,
  },
  tooltipSeriesName: {
    color: "#333",
    fontWeight: 600,
  },
  tooltipVal: {
    color: "#1a1a1a",
    fontWeight: 800,
    whiteSpace: "nowrap",
  },
};

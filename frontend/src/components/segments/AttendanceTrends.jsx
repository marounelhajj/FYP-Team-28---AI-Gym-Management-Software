import { useCallback, useEffect, useState } from "react";
import { fetchSegments, fetchSegmentsMeta, fetchTrends } from "../../api/segments.js";
import SegmentedControl from "../SegmentedControl.jsx";
import TrendChart, { SERIES_COLORS } from "./TrendChart.jsx";

// SCRUM-112: Attendance trends over time by branch and member segment.
// User story: "As a marketing staff member, I want to view attendance trends
// over time by branch and member segment, so that I can see where engagement
// is growing or falling."

export default function AttendanceTrends() {
  const [meta, setMeta] = useState(null);
  const [availableSegments, setAvailableSegments] = useState([]);
  const [selectedSegments, setSelectedSegments] = useState([]);
  const [branch, setBranch] = useState("");
  const [period, setPeriod] = useState("week"); // "week" | "month"
  const [metric, setMetric] = useState("visitsPerMember"); // "visitsPerMember" | "visits"

  const [trendData, setTrendData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exportError, setExportError] = useState(null);

  // Load initial meta & segments
  useEffect(() => {
    Promise.all([fetchSegmentsMeta(), fetchSegments()])
      .then(([m, segs]) => {
        setMeta(m);
        const list = segs.segments || [];
        setAvailableSegments(list);
        // Default select up to 1-2 segments if available
        if (list.length > 0) {
          setSelectedSegments([list[0].id]);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load segment metadata.");
      });
  }, []);

  const loadTrends = useCallback(() => {
    setLoading(true);
    setError(null);
    return fetchTrends({
      segments: selectedSegments,
      branch: branch || undefined,
      period,
    })
      .then((data) => {
        setTrendData(data);
      })
      .catch((err) => {
        setError(err.message || "Could not load attendance trends.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedSegments, branch, period]);

  useEffect(() => {
    loadTrends();
  }, [loadTrends]);

  function toggleSegment(segmentId) {
    if (selectedSegments.includes(segmentId)) {
      setSelectedSegments((prev) => prev.filter((id) => id !== segmentId));
    } else {
      if (selectedSegments.length < (meta?.maxCompare || 3)) {
        setSelectedSegments((prev) => [...prev, segmentId]);
      }
    }
  }

  const branches = meta?.branches || [];
  const maxReached = selectedSegments.length >= (meta?.maxCompare || 3);
  const metricKey = metric === "visitsPerMember" ? "visitsPerMember" : "visits";

  return (
    <div style={styles.page}>
      <style>{TRENDS_CSS}</style>

      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Attendance Trends</h1>
        <p style={styles.subtitle}>
          Compare weekly or monthly member visits per active member and raw visits across segments.
          Lines show how each segment's engagement changes over time relative to the overall gym population.
        </p>
      </header>

      {error && <div style={styles.errorBox} role="alert">{error}</div>}
      {exportError && <div style={styles.errorBox} role="alert">{exportError}</div>}

      {/* Main Trends Card with controls in the card header */}
      <section style={styles.card} aria-label="Attendance trends comparison">
        <div style={styles.cardHeader}>
          {/* Headline with Segment Count */}
          <div style={styles.headline}>
            <span style={styles.bigCount} className="seg-pop">
              {selectedSegments.length}
            </span>
            <span style={styles.countLabelStrong}>
              {selectedSegments.length === 1 ? "segment" : "segments"} compared
            </span>
            <span style={styles.countLabel}>
              against <strong>All members</strong>
            </span>
          </div>

          {/* Header Controls: Granularity, Branch, Metric, Export */}
          <div style={styles.controls}>
            {/* Week / Month Toggle */}
            <div style={styles.controlItem}>
              <SegmentedControl
                ariaLabel="Time period granularity"
                value={period}
                onChange={setPeriod}
                options={[
                  { value: "week", label: "Weekly" },
                  { value: "month", label: "Monthly" },
                ]}
              />
            </div>

            {/* Metric Toggle */}
            <div style={styles.controlItem}>
              <SegmentedControl
                ariaLabel="Attendance metric"
                value={metric}
                onChange={setMetric}
                options={[
                  { value: "visitsPerMember", label: "Visits / member" },
                  { value: "visits", label: "Total visits" },
                ]}
              />
            </div>

            {/* Branch select if > 1 branch */}
            {branches.length > 1 && (
              <label style={styles.inlineLabel}>
                <span style={styles.srOnly}>Branch</span>
                <select
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  style={styles.select}
                  className="seg-select"
                  aria-label="Filter by branch"
                >
                  <option value="">All branches</option>
                  {branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </label>
            )}

          </div>
        </div>

        {/* Segment comparison chips */}
        <div style={styles.chipRow}>
          <span style={styles.chipRowLabel}>
            Compare segments <strong style={{ color: "#124096" }}>({selectedSegments.length}/3)</strong>:
          </span>
          <div style={styles.chipsWrap} role="group" aria-label="Select up to 3 segments to compare">
            {availableSegments.length === 0 ? (
              <span style={styles.mutedText}>No segments available yet.</span>
            ) : (
              availableSegments.map((s) => {
                const isSelected = selectedSegments.includes(s.id);
                const disabled = !isSelected && maxReached;
                const colorIdx = isSelected
                  ? selectedSegments.indexOf(s.id) + 1
                  : 0;
                const dotColor = SERIES_COLORS[colorIdx % SERIES_COLORS.length];

                return (
                  <button
                    key={s.id}
                    type="button"
                    aria-pressed={isSelected}
                    disabled={disabled}
                    onClick={() => toggleSegment(s.id)}
                    style={{
                      ...styles.chip,
                      ...(isSelected ? styles.chipSelected : {}),
                      ...(disabled ? styles.chipDisabled : {}),
                    }}
                    className="seg-chip"
                    title={disabled ? "Maximum 3 segments can be compared at once" : s.name}
                  >
                    {isSelected && (
                      <span
                        style={{ ...styles.chipDot, background: dotColor }}
                        aria-hidden="true"
                      />
                    )}
                    <span>{s.name}</span>
                    <strong style={styles.chipSize}>({s.count})</strong>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Loading state */}
        {loading && <div style={styles.metaLoading}>Loading attendance trends...</div>}

        {/* Chart View */}
        {!loading && trendData && (
          <div style={styles.chartArea}>
            <TrendChart
              periods={trendData.periods || []}
              series={trendData.series || []}
              metric={metric}
            />
          </div>
        )}

        {/* Series Summary Table underneath the chart */}
        {!loading && trendData?.series && (
          <div style={styles.summarySection}>
            <h3 style={styles.summaryHeading}>Performance Summary (latest period)</h3>
            <div style={styles.tableWrap}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Series</th>
                    <th style={styles.th}>Audience Size</th>
                    <th style={styles.th}>
                      Latest Value ({metric === "visitsPerMember" ? "visits/member" : "visits"})
                    </th>
                    <th style={styles.th}>Change vs Prev Period</th>
                  </tr>
                </thead>
                <tbody>
                  {trendData.series.map((s, idx) => {
                    const color = SERIES_COLORS[idx % SERIES_COLORS.length];
                    const pts = s.points || [];
                    const latest = pts.length > 0 ? pts[pts.length - 1] : null;
                    const pctChange = s.change?.[metricKey];

                    return (
                      <tr key={s.key ?? idx} style={styles.tr} className="seg-row">
                        <td style={styles.td}>
                          <div style={styles.seriesNameCell}>
                            <span
                              style={{
                                ...styles.tableSwatch,
                                background: color,
                                border: s.key === "all" ? "2px dashed #71717a" : "none",
                              }}
                              aria-hidden="true"
                            />
                            <strong>{s.name}</strong>
                          </div>
                        </td>

                        <td style={styles.td}>
                          <strong style={styles.sizeText}>{s.size.toLocaleString()}</strong> members
                        </td>

                        <td style={styles.td}>
                          {latest ? (
                            <strong style={styles.latestValue}>
                              {metric === "visitsPerMember"
                                ? latest.visitsPerMember == null ? "—" : `${latest.visitsPerMember.toFixed(2)}`
                                : latest.visits.toLocaleString()}
                            </strong>
                          ) : (
                            "—"
                          )}
                        </td>

                        <td style={styles.td}>
                          {pctChange != null ? (
                            pctChange > 0 ? (
                              <span style={styles.changeUp}>▲ +{pctChange.toFixed(1)}%</span>
                            ) : pctChange < 0 ? (
                              <span style={styles.changeDown}>▼ {pctChange.toFixed(1)}%</span>
                            ) : (
                              <span style={styles.changeFlat}>0.0%</span>
                            )
                          ) : (
                            <span style={styles.changeNone}>—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

const BLUE = "#124096";

const TRENDS_CSS = `
.seg-chip {
  transition: background 140ms ease, border-color 140ms ease, color 140ms ease, transform 120ms ease;
}
.seg-chip:hover:not(:disabled) {
  border-color: ${BLUE};
}
.seg-chip:active:not(:disabled) {
  transform: scale(0.97);
}
.seg-select {
  appearance: none;
  -webkit-appearance: none;
  cursor: pointer;
  padding-right: 36px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23124096' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
}
.seg-select:focus-visible, .seg-chip:focus-visible {
  outline: 3px solid ${BLUE};
  outline-offset: 2px;
}
.seg-row:hover td {
  background: #f6f8fd;
}
.seg-pop {
  display: inline-block;
  animation: seg-pop 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
@keyframes seg-pop {
  from { transform: scale(0.9); opacity: 0.4; }
  to { transform: none; opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .seg-chip { transition: none; }
  .seg-pop { animation: none; }
  .seg-chip:active:not(:disabled) { transform: none; }
}
`;

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1240,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: {
    marginBottom: 20,
  },
  title: {
    fontSize: 26,
    fontWeight: 800,
    margin: 0,
    color: "#1a1a1a",
  },
  subtitle: {
    fontSize: 14,
    color: "#666",
    marginTop: 6,
    maxWidth: 820,
    lineHeight: 1.45,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "12px 16px",
    borderRadius: 12,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 16,
  },
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 20,
    background: "#fff",
    padding: 20,
    marginBottom: 24,
    boxShadow: "0 2px 0 #e2e2e8",
  },
  cardHeader: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 14,
    marginBottom: 16,
    borderBottom: "1px solid #f0f0f4",
    paddingBottom: 16,
  },
  headline: {
    display: "flex",
    alignItems: "baseline",
    gap: 10,
    flexWrap: "wrap",
  },
  bigCount: {
    fontSize: 36,
    fontWeight: 900,
    letterSpacing: -0.5,
    color: "#124096",
  },
  countLabelStrong: {
    fontSize: 18,
    fontWeight: 800,
  },
  countLabel: {
    fontSize: 14,
    fontWeight: 600,
    color: "#666",
  },
  controls: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 10,
  },
  controlItem: {
    display: "inline-flex",
  },
  inlineLabel: {
    display: "inline-flex",
  },
  srOnly: {
    position: "absolute",
    width: 1,
    height: 1,
    overflow: "hidden",
    clip: "rect(0 0 0 0)",
  },
  select: {
    height: 40,
    padding: "0 14px",
    fontSize: 14,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#fff",
    color: "#1a1a1a",
    fontFamily: "inherit",
    outline: "none",
  },
  chipRow: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 10,
    marginBottom: 20,
    padding: "8px 12px",
    background: "#f7f7fa",
    borderRadius: 14,
  },
  chipRowLabel: {
    fontSize: 13,
    fontWeight: 700,
    color: "#444",
  },
  chipsWrap: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    padding: "6px 14px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 20,
    border: "1px solid #d0d0d5",
    background: "#fff",
    color: "#444",
    cursor: "pointer",
    fontFamily: "inherit",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  },
  chipSelected: {
    border: `1.5px solid ${BLUE}`,
    background: "#eef2fa",
    color: BLUE,
    fontWeight: 700,
  },
  chipDisabled: {
    opacity: 0.45,
    cursor: "not-allowed",
    background: "#f3f3f5",
  },
  chipDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    flexShrink: 0,
  },
  chipSize: {
    fontSize: 12,
    color: "#777",
  },
  mutedText: {
    fontSize: 13,
    color: "#888",
  },
  metaLoading: {
    fontSize: 14,
    fontWeight: 600,
    color: "#888",
    padding: "40px 0",
    textAlign: "center",
  },
  chartArea: {
    marginBottom: 24,
  },
  summarySection: {
    borderTop: "1px solid #f0f0f4",
    paddingTop: 18,
  },
  summaryHeading: {
    fontSize: 15,
    fontWeight: 800,
    margin: "0 0 12px 0",
    color: "#1a1a1a",
  },
  tableWrap: {
    overflowX: "auto",
    borderRadius: 12,
    border: "1px solid #eef0f4",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    textAlign: "left",
  },
  th: {
    padding: "10px 14px",
    fontSize: 12,
    fontWeight: 800,
    color: "#666",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafc",
  },
  tr: {
    borderBottom: "1px solid #f0f0f4",
    transition: "background 120ms ease",
  },
  td: {
    padding: "12px 14px",
    fontSize: 14,
    verticalAlign: "middle",
  },
  seriesNameCell: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 14,
  },
  tableSwatch: {
    width: 12,
    height: 12,
    borderRadius: 3,
    flexShrink: 0,
  },
  sizeText: {
    fontSize: 15,
    fontWeight: 800,
    color: "#124096",
  },
  latestValue: {
    fontSize: 15,
    fontWeight: 800,
    color: "#1a1a1a",
  },
  changeUp: {
    fontSize: 14,
    fontWeight: 800,
    color: "#129638",
  },
  changeDown: {
    fontSize: 14,
    fontWeight: 800,
    color: "#b3261e",
  },
  changeFlat: {
    fontSize: 14,
    fontWeight: 700,
    color: "#666",
  },
  changeNone: {
    fontSize: 14,
    color: "#888",
  },
};

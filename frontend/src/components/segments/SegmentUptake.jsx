import { useCallback, useEffect, useState } from "react";
import { fetchSegments, fetchSegmentsMeta, fetchUptake } from "../../api/segments.js";
import ExportButton from "./ExportButton.jsx";

// SCRUM-113: Class and service uptake per segment.
// User story: "As a marketing staff member, I want to view class and service
// uptake per segment, so that I can see which offerings each group actually
// uses."

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 30);
  const toIso = (d) => {
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  };
  return { from: toIso(start), to: toIso(end) };
}

const KIND_LABELS = {
  class: "Classes",
  pt: "Personal Training",
  shop: "Shop Purchases",
};

export default function SegmentUptake() {
  const [meta, setMeta] = useState(null);
  const [availableSegments, setAvailableSegments] = useState([]);
  const [selectedSegments, setSelectedSegments] = useState([]);
  const [branch, setBranch] = useState("");
  const [{ from, to }, setDates] = useState(defaultDates);

  const [uptakeData, setUptakeData] = useState(null);
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
        if (list.length > 0) {
          setSelectedSegments([list[0].id]);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load segment metadata.");
      });
  }, []);

  const loadUptake = useCallback(() => {
    setLoading(true);
    setError(null);
    return fetchUptake({
      segments: selectedSegments,
      branch: branch || undefined,
      from,
      to,
    })
      .then((data) => {
        setUptakeData(data);
      })
      .catch((err) => {
        setError(err.message || "Could not load segment uptake.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [selectedSegments, branch, from, to]);

  useEffect(() => {
    loadUptake();
  }, [loadUptake]);

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
  const offerings = uptakeData?.offerings || [];
  const series = uptakeData?.series || [];

  // Group offerings by kind: class, pt, shop
  const groupedOfferings = offerings.reduce((acc, off) => {
    const k = off.kind || "class";
    if (!acc[k]) acc[k] = [];
    acc[k].push(off);
    return acc;
  }, {});

  return (
    <div style={styles.page}>
      <style>{UPTAKE_CSS}</style>

      {/* Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Segment Uptake</h1>
        <p style={styles.subtitle}>
          Examine which gym offerings (fitness classes, private personal training, and shop items)
          each member segment actively utilizes. Heatmap cells highlight segments that participate
          well above or below the overall gym average.
        </p>
      </header>

      {error && <div style={styles.errorBox} role="alert">{error}</div>}
      {exportError && <div style={styles.errorBox} role="alert">{exportError}</div>}

      {/* Main Card with controls in the card header */}
      <section style={styles.card} aria-label="Segment service uptake heatmap">
        <div style={styles.cardHeader}>
          {/* Headline */}
          <div style={styles.headline}>
            <span style={styles.bigCount} className="seg-pop">
              {offerings.length}
            </span>
            <span style={styles.countLabelStrong}>
              {offerings.length === 1 ? "offering" : "offerings"} tracked
            </span>
            <span style={styles.countLabel}>
              across <strong>{selectedSegments.length}</strong> compared {selectedSegments.length === 1 ? "segment" : "segments"}
            </span>
          </div>

          {/* Controls: Date range, Branch, Export */}
          <div style={styles.controls}>
            {/* Date Inputs */}
            <div style={styles.dateGroup}>
              <label style={styles.dateLabel}>
                From
                <input
                  type="date"
                  value={from}
                  onChange={(e) => setDates((prev) => ({ ...prev, from: e.target.value }))}
                  style={styles.dateInput}
                  className="seg-input"
                  aria-label="Start date"
                />
              </label>
              <label style={styles.dateLabel}>
                To
                <input
                  type="date"
                  value={to}
                  min={from}
                  onChange={(e) => setDates((prev) => ({ ...prev, to: e.target.value }))}
                  style={styles.dateInput}
                  className="seg-input"
                  aria-label="End date"
                />
              </label>
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

            {/* Export button */}
            <ExportButton
              params={{
                type: "aggregate",
                segments: selectedSegments,
                branch,
                from,
                to,
              }}
              label="Export CSV"
              onError={setExportError}
            />
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
                    <span>{s.name}</span>
                    <strong style={styles.chipSize}>({s.count})</strong>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Loading state */}
        {loading && <div style={styles.metaLoading}>Loading uptake data...</div>}

        {/* Empty state */}
        {!loading && offerings.length === 0 && (
          <div style={styles.empty}>
            <div style={styles.emptyTitle}>No service or class activity recorded in this period.</div>
            <div style={styles.emptySubtitle}>
              Try expanding the date range or selecting a different branch.
            </div>
          </div>
        )}

        {/* Heatmap Table */}
        {!loading && offerings.length > 0 && series.length > 0 && (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.thOffering}>Offering</th>
                  {series.map((s) => (
                    <th key={s.key} style={styles.thSeries}>
                      <div style={styles.seriesThName}>{s.name}</div>
                      <div style={styles.seriesThSize}>
                        <strong>{s.size}</strong> members
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {["class", "pt", "shop"].map((kindKey) => {
                  const items = groupedOfferings[kindKey] || [];
                  if (items.length === 0) return null;

                  return (
                    <tr key={`group-${kindKey}`} style={styles.trGroup}>
                      <td colSpan={series.length + 1} style={styles.tdGroupHeader}>
                        <span style={styles.groupHeaderLabel}>{KIND_LABELS[kindKey]}</span>
                      </td>
                    </tr>
                  ).type === "tr" ? (
                    [
                      <tr key={`header-${kindKey}`} style={styles.trGroup}>
                        <td colSpan={series.length + 1} style={styles.tdGroupHeader}>
                          <span style={styles.groupHeaderLabel}>{KIND_LABELS[kindKey]}</span>
                        </td>
                      </tr>,
                      ...items.map((off) => {
                        const displayName = off.name.startsWith("Shop: ")
                          ? off.name.replace("Shop: ", "")
                          : off.name;

                        return (
                          <tr key={off.name} style={styles.tr} className="seg-row">
                            <td style={styles.tdOffering}>
                              <div style={styles.offeringName}>{displayName}</div>
                            </td>

                            {series.map((s) => {
                              const cell = s.cells?.[offeringKey(off.name)] || s.cells?.[off.name];
                              if (!cell) {
                                return (
                                  <td key={s.key} style={styles.tdCell}>
                                    <span style={{ color: "#aaa" }}>—</span>
                                  </td>
                                );
                              }

                              const pct = cell.uptakePct || 0;
                              // Heatmap shade opacity: max 0.35 for high text readability
                              const shadeOpacity = pct > 0 ? Math.min(0.35, 0.04 + (pct / 100) * 0.35) : 0;
                              const cellBg = pct > 0 ? `rgba(18, 64, 150, ${shadeOpacity})` : "#fff";

                              const isAbove = cell.highlight === "above";
                              const isBelow = cell.highlight === "below";

                              return (
                                <td
                                  key={s.key}
                                  style={{
                                    ...styles.tdCell,
                                    background: cellBg,
                                    ...(isAbove ? styles.cellAbove : isBelow ? styles.cellBelow : {}),
                                  }}
                                  title={`${displayName} - ${s.name}: ${pct}% uptake (${cell.users} users, ${cell.usesPerMember} uses/member)`}
                                >
                                  <div style={styles.cellContent}>
                                    <div style={styles.cellPctRow}>
                                      <strong style={styles.cellPct}>{pct.toFixed(1)}%</strong>
                                      {isAbove && (
                                        <span style={styles.badgeAbove} title="Well above gym average">
                                          ▲
                                        </span>
                                      )}
                                      {isBelow && (
                                        <span style={styles.badgeBelow} title="Well below gym average">
                                          ▼
                                        </span>
                                      )}
                                    </div>
                                    <div style={styles.cellUses}>
                                      {cell.usesPerMember.toFixed(1)} uses/mbr
                                    </div>
                                  </div>
                                </td>
                              );
                            })}
                          </tr>
                        );
                      }),
                    ]
                  ) : null;
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Legend */}
        {!loading && offerings.length > 0 && (
          <div style={styles.legendBox}>
            <h4 style={styles.legendHeading}>Heatmap Legend</h4>
            <div style={styles.legendItems}>
              <div style={styles.legendItem}>
                <span style={styles.legendSwatchSample} aria-hidden="true" />
                <span>
                  <strong>Shading:</strong> Darker blue shading indicates higher uptake percentage.
                </span>
              </div>
              <div style={styles.legendItem}>
                <span style={{ ...styles.legendBadgeSample, ...styles.cellAboveSample }}>
                  <span style={{ color: "#129638", fontWeight: 900 }}>▲</span>
                </span>
                <span>
                  <strong>Green outline (▲):</strong> Well <em>above</em> the all-members average (at least 1.5× and +10 percentage points).
                </span>
              </div>
              <div style={styles.legendItem}>
                <span style={{ ...styles.legendBadgeSample, ...styles.cellBelowSample }}>
                  <span style={{ color: "#b3261e", fontWeight: 900 }}>▼</span>
                </span>
                <span>
                  <strong>Red outline (▼):</strong> Well <em>below</em> the all-members average (at most ⅔ and −10 percentage points).
                </span>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function offeringKey(name) {
  return name;
}

const BLUE = "#124096";

const UPTAKE_CSS = `
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
.seg-select:focus-visible, .seg-chip:focus-visible, .seg-input:focus-visible {
  outline: 3px solid ${BLUE};
  outline-offset: 2px;
}
.seg-row:hover td {
  filter: brightness(0.98);
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
    gap: 12,
  },
  dateGroup: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  dateLabel: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 13,
    fontWeight: 700,
    color: "#444",
  },
  dateInput: {
    height: 40,
    padding: "0 10px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#fff",
    color: "#1a1a1a",
    fontFamily: "inherit",
    outline: "none",
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
  empty: {
    padding: "48px 20px",
    textAlign: "center",
    background: "#fafafc",
    borderRadius: 14,
    border: "1px dashed #d8d8de",
  },
  emptyTitle: {
    fontSize: 16,
    fontWeight: 700,
    color: "#444",
    marginBottom: 6,
  },
  emptySubtitle: {
    fontSize: 13,
    color: "#777",
  },
  tableWrap: {
    overflowX: "auto",
    borderRadius: 14,
    border: "1px solid #e0e0e6",
    marginBottom: 20,
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    textAlign: "left",
  },
  thOffering: {
    padding: "12px 16px",
    fontSize: 13,
    fontWeight: 800,
    color: "#444",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    borderBottom: "2px solid #dcdce2",
    background: "#f4f4f7",
    width: "28%",
  },
  thSeries: {
    padding: "12px 14px",
    fontSize: 13,
    fontWeight: 800,
    color: "#1a1a1a",
    borderBottom: "2px solid #dcdce2",
    background: "#f4f4f7",
    textAlign: "center",
  },
  seriesThName: {
    fontSize: 14,
    fontWeight: 800,
    color: "#124096",
  },
  seriesThSize: {
    fontSize: 12,
    fontWeight: 500,
    color: "#666",
    marginTop: 2,
  },
  trGroup: {
    background: "#f9f9fb",
  },
  tdGroupHeader: {
    padding: "10px 16px",
    borderBottom: "1px solid #e8e8ed",
    borderTop: "1px solid #e8e8ed",
  },
  groupHeaderLabel: {
    fontSize: 12,
    fontWeight: 900,
    textTransform: "uppercase",
    letterSpacing: 0.7,
    color: "#555",
  },
  tr: {
    borderBottom: "1px solid #ebebef",
  },
  tdOffering: {
    padding: "12px 16px",
    fontSize: 14,
    verticalAlign: "middle",
    background: "#fff",
  },
  offeringName: {
    fontWeight: 700,
    color: "#1a1a1a",
  },
  tdCell: {
    padding: "10px 12px",
    textAlign: "center",
    verticalAlign: "middle",
    borderLeft: "1px solid #ededf2",
    transition: "background 150ms ease",
    boxSizing: "border-box",
  },
  cellContent: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 2,
  },
  cellPctRow: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
  },
  cellPct: {
    fontSize: 15,
    fontWeight: 800,
    color: "#1a1a1a",
  },
  cellUses: {
    fontSize: 11,
    color: "#555",
    fontWeight: 500,
  },
  badgeAbove: {
    fontSize: 12,
    color: "#129638",
    fontWeight: 900,
  },
  badgeBelow: {
    fontSize: 12,
    color: "#b3261e",
    fontWeight: 900,
  },
  cellAbove: {
    boxShadow: "inset 0 0 0 2px #129638",
    borderRadius: 4,
  },
  cellBelow: {
    boxShadow: "inset 0 0 0 2px #b3261e",
    borderRadius: 4,
  },
  legendBox: {
    padding: "14px 16px",
    background: "#fafafc",
    borderRadius: 12,
    border: "1px solid #e8e8ed",
  },
  legendHeading: {
    fontSize: 13,
    fontWeight: 800,
    margin: "0 0 8px 0",
    color: "#333",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  legendItems: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    fontSize: 13,
    color: "#444",
  },
  legendItem: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  legendSwatchSample: {
    width: 20,
    height: 14,
    borderRadius: 3,
    background: "rgba(18, 64, 150, 0.28)",
    border: "1px solid rgba(18, 64, 150, 0.4)",
    flexShrink: 0,
  },
  legendBadgeSample: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 20,
    height: 18,
    borderRadius: 4,
    fontSize: 12,
    flexShrink: 0,
  },
  cellAboveSample: {
    border: "2px solid #129638",
    background: "#f0fdf4",
  },
  cellBelowSample: {
    border: "2px solid #b3261e",
    background: "#fef2f2",
  },
};

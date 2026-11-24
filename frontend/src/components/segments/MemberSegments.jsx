import { useCallback, useEffect, useState } from "react";
import { deleteSegment, fetchClusters, fetchSegments, fetchSegmentsMeta } from "../../api/segments.js";
import SegmentFilterBuilder from "./SegmentFilterBuilder.jsx";
import SuggestedSegments from "./SuggestedSegments.jsx";
import ExportButton from "./ExportButton.jsx";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// SCRUM-43: Member Segments list and management.
// User story: "As a marketing staff member or manager, I want to define and
// view member segments based on attendance, tenure, and demographics, so that
// we can tailor communications and offers."

export default function MemberSegments() {
  const [segments, setSegments] = useState([]);
  const [meta, setMeta] = useState(null);
  const [clusters, setClusters] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Form modal state: null = closed, "new" = create, or a segment object = edit
  const [formTarget, setFormTarget] = useState(null);

  // Inline delete confirm state: segment ID or null
  const [deletingId, setDeletingId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    return Promise.all([fetchSegmentsMeta(), fetchSegments(), fetchClusters()])
      .then(([m, segs, clus]) => {
        setMeta(m);
        setSegments(segs.segments || []);
        setClusters(clus);
      })
      .catch((err) => {
        setError(err.message || "Could not load member segments.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Notice timeout
  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 7000);
    return () => clearTimeout(t);
  }, [notice]);

  function handleFormSaved(saved, isEditing) {
    setFormTarget(null);
    setNotice(isEditing ? `Segment "${saved.name}" updated.` : `Segment "${saved.name}" created.`);
    loadData();
  }

  function handleSuggestedSaved(saved) {
    setNotice(`Suggested segment "${saved.name}" saved as a segment.`);
    loadData();
  }

  async function handleDelete(segmentId) {
    const target = segments.find((s) => s.id === segmentId);
    setDeleteBusy(true);
    try {
      await deleteSegment(segmentId);
      setDeletingId(null);
      setNotice(`Segment "${target ? target.name : segmentId}" deleted.`);
      loadData();
    } catch (err) {
      setError(err.message || "Failed to delete segment.");
    } finally {
      setDeleteBusy(false);
    }
  }

  const canManage = Boolean(meta?.canManage);
  const canExport = Boolean(meta?.canExportMembers);
  const orgWide = meta?.orgWide !== false;

  return (
    <div style={styles.page}>
      <style>{PAGE_CSS}</style>

      {/* Page Header */}
      <header style={styles.header}>
        <h1 style={styles.title}>Member Segments</h1>
        <p style={styles.subtitle}>
          Group members by behavior, demographics, and churn risk to target marketing campaigns,
          understand attendance trends, and personalize communications.
        </p>
      </header>

      {notice && <div style={styles.noticeBox} role="status">{notice}</div>}
      {error && <div style={styles.errorBox} role="alert">{error}</div>}

      {/* Main Segments Card */}
      <section style={styles.card} aria-label="Defined member segments">
        <div style={styles.cardHeader}>
          <div style={styles.headline}>
            <span style={styles.bigCount} className="seg-pop">
              {segments.length}
            </span>
            <span style={styles.countLabelStrong}>
              {segments.length === 1 ? "segment" : "segments"}
            </span>
            <span style={styles.countLabel}>
              {orgWide ? "across all branches" : `for ${meta?.branches?.[0] || "your branch"}`}
            </span>
          </div>

          <div style={styles.controls}>
            {canManage && (
              <button
                type="button"
                onClick={() => setFormTarget("new")}
                style={styles.newButton}
                className="seg-press"
              >
                + New segment
              </button>
            )}
          </div>
        </div>

        {/* Loading state */}
        {loading && <div style={styles.metaLoading}>Loading segments...</div>}

        {/* Empty state */}
        {!loading && segments.length === 0 && (
          <div style={styles.empty}>
            <div style={styles.emptyTitle}>No member segments defined yet.</div>
            <div style={styles.emptySubtitle}>
              {canManage
                ? "Click '+ New segment' above to create rule-based cohorts, or explore suggested segments below."
                : "Segments created by marketing staff or general managers will appear here."}
            </div>
          </div>
        )}

        {/* Segments Table */}
        {!loading && segments.length > 0 && (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Segment</th>
                  <th style={styles.th}>Summary</th>
                  <th style={styles.th}>Audience Count</th>
                  <th style={styles.th}>Targetable / Opted Out</th>
                  <th style={styles.th}>Source</th>
                  <th style={styles.th}></th>
                </tr>
              </thead>
              <tbody>
                {segments.map((s) => {
                  const isDeleting = deletingId === s.id;
                  const isCluster = s.source === "cluster";

                  return (
                    <tr key={s.id} style={styles.tr} className="seg-row">
                      <td style={styles.td}>
                        <div style={styles.segmentName}>{s.name}</div>
                        {s.description && <div style={styles.segmentDesc}>{s.description}</div>}
                        {s.createdBy && <div style={styles.createdBy}>by {s.createdBy}</div>}
                      </td>

                      <td style={styles.td}>
                        <div style={styles.summaryText}>{s.summary || "All members"}</div>
                      </td>

                      <td style={styles.td}>
                        <div style={styles.countCell}>
                          <strong style={styles.boldCount}>{s.count}</strong> members
                        </div>
                      </td>

                      <td style={styles.td}>
                        <div style={styles.optCell}>
                          <span style={styles.targetableBadge}>
                            <strong>{s.targetable}</strong> targetable
                          </span>
                          <span style={styles.optedOutBadge}>
                            <strong>{s.optedOut}</strong> opted out
                          </span>
                        </div>
                      </td>

                      <td style={styles.td}>
                        <span
                          style={{
                            ...styles.badge,
                            ...(isCluster ? styles.badgeCluster : styles.badgeRules),
                          }}
                        >
                          {isCluster ? "Suggested" : "Rules"}
                        </span>
                      </td>

                      <td style={styles.tdActions}>
                        {isDeleting ? (
                          <div style={styles.confirmRow} role="group" aria-label="Confirm deletion">
                            <span style={styles.confirmPrompt}>Delete?</span>
                            <button
                              type="button"
                              onClick={() => handleDelete(s.id)}
                              disabled={deleteBusy}
                              style={styles.confirmYes}
                              className="seg-press"
                            >
                              {deleteBusy ? "..." : "Yes"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setDeletingId(null)}
                              disabled={deleteBusy}
                              style={styles.confirmNo}
                              className="seg-press"
                            >
                              No
                            </button>
                          </div>
                        ) : (
                          <div style={styles.actionButtons}>
                            {canExport && (
                              <ExportButton
                                params={{ type: "members", segment: s.id }}
                                label="Export members"
                                style={styles.actionExportBtn}
                              />
                            )}
                            {canManage && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => setFormTarget(s)}
                                  style={styles.actionButton}
                                  className="seg-press"
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setDeletingId(s.id)}
                                  style={styles.actionDeleteButton}
                                  className="seg-press"
                                >
                                  Delete
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Suggested Segments Section */}
      <SuggestedSegments
        clusters={clusters}
        meta={meta}
        onSegmentSaved={handleSuggestedSaved}
        onClustersUpdated={(newClusters) => setClusters(newClusters)}
      />

      {/* Filter Builder Modal */}
      {formTarget && meta && (
        <SegmentFilterBuilder
          segment={formTarget === "new" ? null : formTarget}
          meta={meta}
          onClose={() => setFormTarget(null)}
          onSaved={handleFormSaved}
        />
      )}
    </div>
  );
}

const BLUE = "#124096";

const PAGE_CSS = `
.seg-row:hover td {
  background: #f6f8fd;
}
.seg-press {
  transition: transform 120ms ease, filter 120ms ease;
}
.seg-press:hover:not(:disabled) {
  filter: brightness(1.08);
}
.seg-press:active:not(:disabled) {
  transform: scale(0.97);
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
  .seg-press { transition: none; }
  .seg-pop { animation: none; }
  .seg-press:active:not(:disabled) { transform: none; }
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
  noticeBox: {
    background: "#e8f5e9",
    color: "#1e7a34",
    padding: "12px 16px",
    borderRadius: 12,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 16,
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
  newButton: {
    height: 44,
    padding: "0 20px",
    fontSize: 14,
    fontWeight: 800,
    border: "none",
    borderRadius: 12,
    ...BUTTON_COLORS.blue,
    cursor: "pointer",
    fontFamily: "inherit",
    boxShadow: "0 3px 0 #0b2a66",
  },
  metaLoading: {
    fontSize: 14,
    fontWeight: 600,
    color: "#888",
    padding: "24px 0",
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
    fontSize: 17,
    fontWeight: 700,
    color: "#333",
    marginBottom: 6,
  },
  emptySubtitle: {
    fontSize: 14,
    color: "#666",
    maxWidth: 540,
    margin: "0 auto",
  },
  tableWrap: {
    overflowX: "auto",
    borderRadius: 12,
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    textAlign: "left",
  },
  th: {
    padding: "12px 14px",
    fontSize: 12,
    fontWeight: 800,
    color: "#666",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafc",
  },
  tr: {
    borderBottom: "1px solid #f0f0f3",
    transition: "background 120ms ease",
  },
  td: {
    padding: "14px",
    fontSize: 14,
    verticalAlign: "middle",
  },
  tdActions: {
    padding: "14px",
    fontSize: 14,
    verticalAlign: "middle",
    textAlign: "right",
    whiteSpace: "nowrap",
  },
  segmentName: {
    fontSize: 15,
    fontWeight: 700,
    color: "#1a1a1a",
  },
  segmentDesc: {
    fontSize: 12,
    color: "#666",
    marginTop: 2,
    maxWidth: 240,
    lineHeight: 1.35,
  },
  createdBy: {
    fontSize: 11,
    color: "#888",
    marginTop: 3,
  },
  summaryText: {
    fontSize: 13,
    color: "#333",
    maxWidth: 320,
    lineHeight: 1.4,
  },
  countCell: {
    fontSize: 14,
  },
  boldCount: {
    fontSize: 17,
    fontWeight: 800,
    color: "#124096",
  },
  optCell: {
    display: "flex",
    flexDirection: "column",
    gap: 3,
  },
  targetableBadge: {
    fontSize: 12,
    color: "#1e7a34",
    fontWeight: 600,
  },
  optedOutBadge: {
    fontSize: 12,
    color: "#777",
    fontWeight: 500,
  },
  badge: {
    display: "inline-block",
    padding: "3px 8px",
    borderRadius: 6,
    fontSize: 11,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  badgeCluster: {
    background: "#f0ebfa",
    color: "#5b21b6",
    border: "1px solid #d8ccf2",
  },
  badgeRules: {
    background: "#e8effc",
    color: "#124096",
    border: "1px solid #c8d8f7",
  },
  actionButtons: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
  },
  actionButton: {
    height: 36,
    padding: "0 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#1a1a1a",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  actionDeleteButton: {
    height: 36,
    padding: "0 12px",
    fontSize: 13,
    fontWeight: 700,
    border: "1px solid #f1c7c5",
    borderRadius: 8,
    background: "#fff5f5",
    color: "#b3261e",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  actionExportBtn: {
    height: 36,
    fontSize: 13,
  },
  confirmRow: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    background: "#fff1f0",
    padding: "4px 8px",
    borderRadius: 8,
    border: "1px solid #f8c8c5",
  },
  confirmPrompt: {
    fontSize: 13,
    fontWeight: 700,
    color: "#b3261e",
    marginRight: 2,
  },
  confirmYes: {
    padding: "4px 10px",
    fontSize: 12,
    fontWeight: 800,
    borderRadius: 6,
    border: "none",
    ...BUTTON_COLORS.red,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  confirmNo: {
    padding: "4px 10px",
    fontSize: 12,
    fontWeight: 700,
    borderRadius: 6,
    border: "1px solid #d0d0d5",
    background: "#fff",
    color: "#444",
    cursor: "pointer",
    fontFamily: "inherit",
  },
};

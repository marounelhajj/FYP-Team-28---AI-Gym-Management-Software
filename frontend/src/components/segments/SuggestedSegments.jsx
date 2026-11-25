import { useState } from "react";
import { runClusters, saveClusterGroup } from "../../api/segments.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// SCRUM-43: Machine-learned suggested member segments from k-means clustering.

function formatDateTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatTypicalHour(hour) {
  if (hour === undefined || hour === null) return "—";
  const h = Math.round(hour) % 24;
  const suffix = h < 12 ? "am" : "pm";
  const display = (h % 12) || 12;
  return `${display}${suffix}`;
}

export default function SuggestedSegments({ clusters, meta, onSegmentSaved, onClustersUpdated }) {
  const [recalculating, setRecalculating] = useState(false);
  const [recalcError, setRecalcError] = useState(null);
  const [savingGroupId, setSavingGroupId] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [notice, setNotice] = useState(null);

  const run = clusters?.run;
  const canManage = Boolean(meta?.canManage);
  const orgWide = meta?.orgWide !== false;

  async function handleRecalculate() {
    if (recalculating) return;
    setRecalculating(true);
    setRecalcError(null);
    setNotice(null);
    try {
      const data = await runClusters();
      if (onClustersUpdated) onClustersUpdated(data);
      setNotice("Suggested segments recalculated successfully.");
    } catch (err) {
      setRecalcError(err.message || "Failed to recalculate suggested segments.");
    } finally {
      setRecalculating(false);
    }
  }

  async function handleSaveGroup(group) {
    if (savingGroupId) return;
    setSavingGroupId(group.id);
    setSaveError(null);
    try {
      const saved = await saveClusterGroup(group.id, group.name);
      if (onSegmentSaved) onSegmentSaved(saved);
      setNotice(`Saved suggested segment "${saved.name}".`);
    } catch (err) {
      setSaveError(err.message || "Could not save suggested segment.");
    } finally {
      setSavingGroupId(null);
    }
  }

  return (
    <section style={styles.card} aria-label="Suggested Segments">
      <div style={styles.cardHeader}>
        <div style={styles.headline}>
          <h2 style={styles.sectionTitle}>Suggested Segments</h2>
          {run && !run.note && (
            <span style={styles.metaBadge}>
              <strong style={styles.boldCount}>{run.groups?.length || 0}</strong> clusters discovered
            </span>
          )}
        </div>
        {canManage && (
          <button
            type="button"
            onClick={handleRecalculate}
            disabled={recalculating}
            style={styles.recalcButton}
            className="seg-press"
          >
            {recalculating ? "Recalculating..." : "Recalculate now"}
          </button>
        )}
      </div>

      {notice && <div style={styles.noticeBox} role="status">{notice}</div>}
      {recalcError && <div style={styles.errorBox} role="alert">{recalcError}</div>}
      {saveError && <div style={styles.errorBox} role="alert">{saveError}</div>}

      {/* Run metadata summary */}
      {run && !run.note && (
        <div style={styles.runMetaRow}>
          <span style={styles.metaItem}>
            Last run: <strong>{formatDateTime(run.ranAt)}</strong>
          </span>
          <span style={styles.metaDot}>·</span>
          <span style={styles.metaItem}>
            Model: <strong>{run.modelVersion || "kmeans"}</strong>
          </span>
          <span style={styles.metaDot}>·</span>
          <span style={styles.metaItem}>
            k = <strong>{run.k}</strong>
          </span>
          <span style={styles.metaDot}>·</span>
          <span style={styles.metaItem}>
            Silhouette: <strong>{run.silhouette != null ? Number(run.silhouette).toFixed(2) : "—"}</strong>
          </span>
          <span style={styles.metaDot}>·</span>
          <span style={styles.metaItem}>
            Members clustered: <strong>{run.membersClustered}</strong>
          </span>
        </div>
      )}

      {/* Empty states */}
      {(!run || run.note || !run.groups || run.groups.length === 0) ? (
        <div style={styles.emptyState}>
          <div style={styles.emptyTitle}>
            {run?.note ? run.note : "No suggested segments available."}
          </div>
          <div style={styles.emptySubtitle}>
            {canManage
              ? "Cluster analysis identifies natural groupings among active members based on attendance patterns, spending, and activity mix."
              : "Check back once enough member data is recorded."}
          </div>
          {canManage && !run?.note && (
            <button
              type="button"
              onClick={handleRecalculate}
              disabled={recalculating}
              style={{ ...styles.recalcButton, marginTop: 12 }}
              className="seg-press"
            >
              {recalculating ? "Calculating..." : "Run clustering now"}
            </button>
          )}
        </div>
      ) : (
        /* Cluster group cards */
        <div style={styles.groupGrid}>
          {run.groups.map((group) => {
            const centroid = group.centroid || {};
            const classPct = Math.round((centroid.classShare || 0) * 100);
            const ptPct = Math.round((centroid.ptShare || 0) * 100);
            const gymPct = Math.max(0, 100 - classPct - ptPct);
            const isSaved = group.savedAs && group.savedAs.length > 0;
            const savingThis = savingGroupId === group.id;

            return (
              <div key={group.id} style={styles.groupCard}>
                <div style={styles.groupCardTop}>
                  <div>
                    <h3 style={styles.groupName}>{group.name}</h3>
                    <div style={styles.groupSize}>
                      <strong style={styles.sizeNumber}>{group.size}</strong> members
                      {!orgWide && group.sizeInScope != null && (
                        <span style={styles.scopeNote}>
                          {" "}(<strong>{group.sizeInScope}</strong> in this branch)
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Saved status / Save as segment button */}
                  <div>
                    {isSaved ? (
                      <span style={styles.savedBadge} title="Already saved as a segment">
                        ✓ Saved as {group.savedAs.map((s) => s.name).join(", ")}
                      </span>
                    ) : canManage ? (
                      <button
                        type="button"
                        onClick={() => handleSaveGroup(group)}
                        disabled={savingThis}
                        style={styles.saveBtn}
                        className="seg-press"
                        aria-label={`Save ${group.name} as segment`}
                      >
                        {savingThis ? "Saving..." : "Save as segment"}
                      </button>
                    ) : null}
                  </div>
                </div>

                <p style={styles.groupDesc}>{group.description}</p>

                {/* Centroid summary */}
                <div style={styles.centroidBox}>
                  <div style={styles.centroidMetrics}>
                    <div style={styles.centroidMetric}>
                      <span style={styles.centroidLabel}>Visits / week</span>
                      <strong style={styles.centroidValue}>
                        {centroid.visitsPerWeek != null ? centroid.visitsPerWeek.toFixed(1) : "—"}
                      </strong>
                    </div>
                    <div style={styles.centroidMetric}>
                      <span style={styles.centroidLabel}>Typical hour</span>
                      <strong style={styles.centroidValue}>
                        {formatTypicalHour(centroid.meanHour)}
                      </strong>
                    </div>
                    <div style={styles.centroidMetric}>
                      <span style={styles.centroidLabel}>Avg tenure</span>
                      <strong style={styles.centroidValue}>
                        {centroid.tenureMonths != null ? `${Math.round(centroid.tenureMonths)} mo` : "—"}
                      </strong>
                    </div>
                  </div>

                  {/* Activity mix segmented bar */}
                  <div style={styles.mixBarWrap}>
                    <div style={styles.mixBarLabelRow}>
                      <span style={styles.mixTitle}>Activity mix</span>
                      <span style={styles.mixLegend}>
                        <span style={{ color: "#124096", fontWeight: 700 }}>Classes {classPct}%</span>
                        {" · "}
                        <span style={{ color: "#eb6834", fontWeight: 700 }}>PT {ptPct}%</span>
                        {" · "}
                        <span style={{ color: "#129638", fontWeight: 700 }}>Gym floor {gymPct}%</span>
                      </span>
                    </div>
                    <div style={styles.mixBar} role="progressbar" aria-label="Activity mix distribution">
                      {classPct > 0 && (
                        <div
                          style={{
                            ...styles.mixSegment,
                            width: `${classPct}%`,
                            background: "#124096",
                          }}
                          title={`Classes: ${classPct}%`}
                        />
                      )}
                      {ptPct > 0 && (
                        <div
                          style={{
                            ...styles.mixSegment,
                            width: `${ptPct}%`,
                            background: "#eb6834",
                          }}
                          title={`Personal Training: ${ptPct}%`}
                        />
                      )}
                      {gymPct > 0 && (
                        <div
                          style={{
                            ...styles.mixSegment,
                            width: `${gymPct}%`,
                            background: "#129638",
                          }}
                          title={`Gym floor: ${gymPct}%`}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

const styles = {
  card: {
    border: "1px solid #e4e4e8",
    borderRadius: 20,
    background: "#fff",
    padding: 20,
    marginBottom: 20,
    boxShadow: "0 2px 0 #e2e2e8",
  },
  cardHeader: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 14,
    marginBottom: 12,
  },
  headline: {
    display: "flex",
    alignItems: "baseline",
    gap: 12,
    flexWrap: "wrap",
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 800,
    margin: 0,
    color: "#1a1a1a",
  },
  metaBadge: {
    fontSize: 14,
    fontWeight: 600,
    color: "#555",
  },
  boldCount: {
    fontSize: 18,
    fontWeight: 900,
    color: "#124096",
  },
  recalcButton: {
    height: 40,
    padding: "0 16px",
    fontSize: 14,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#fff",
    color: "#124096",
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    fontFamily: "inherit",
    boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  },
  noticeBox: {
    background: "#e8f5e9",
    color: "#1e7a34",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 12,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 12,
  },
  runMetaRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    fontSize: 13,
    color: "#666",
    padding: "8px 12px",
    background: "#f7f7fa",
    borderRadius: 10,
    marginBottom: 16,
  },
  metaItem: {
    color: "#444",
  },
  metaDot: {
    color: "#aaa",
  },
  emptyState: {
    padding: "36px 20px",
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
    maxWidth: 500,
    margin: "0 auto",
  },
  groupGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
    gap: 16,
  },
  groupCard: {
    border: "1px solid #e0e0e6",
    borderRadius: 16,
    background: "#fafafc",
    padding: 16,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    boxShadow: "0 1px 3px rgba(0,0,0,0.03)",
  },
  groupCardTop: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
    marginBottom: 10,
  },
  groupName: {
    fontSize: 16,
    fontWeight: 800,
    margin: "0 0 4px 0",
    color: "#1a1a1a",
  },
  groupSize: {
    fontSize: 13,
    color: "#555",
  },
  sizeNumber: {
    fontSize: 15,
    fontWeight: 900,
    color: "#124096",
  },
  scopeNote: {
    color: "#777",
    fontSize: 12,
  },
  groupDesc: {
    fontSize: 13,
    lineHeight: 1.45,
    color: "#444",
    margin: "0 0 14px 0",
    flexGrow: 1,
  },
  savedBadge: {
    fontSize: 12,
    fontWeight: 700,
    color: "#1e7a34",
    background: "#e8f5e9",
    border: "1px solid #b7dfbe",
    padding: "5px 10px",
    borderRadius: 8,
    whiteSpace: "nowrap",
    display: "inline-block",
  },
  saveBtn: {
    height: 34,
    padding: "0 12px",
    fontSize: 12,
    fontWeight: 700,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  centroidBox: {
    background: "#fff",
    border: "1px solid #ebebf0",
    borderRadius: 12,
    padding: 12,
  },
  centroidMetrics: {
    display: "flex",
    justifyContent: "space-between",
    gap: 8,
    marginBottom: 10,
  },
  centroidMetric: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  centroidLabel: {
    fontSize: 11,
    color: "#666",
    fontWeight: 600,
    textTransform: "uppercase",
  },
  centroidValue: {
    fontSize: 14,
    fontWeight: 800,
    color: "#1a1a1a",
    marginTop: 2,
  },
  mixBarWrap: {
    display: "flex",
    flexDirection: "column",
    gap: 5,
  },
  mixBarLabelRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    fontSize: 11,
  },
  mixTitle: {
    fontWeight: 700,
    color: "#555",
    textTransform: "uppercase",
  },
  mixLegend: {
    fontSize: 11,
  },
  mixBar: {
    height: 10,
    borderRadius: 5,
    overflow: "hidden",
    display: "flex",
    background: "#e5e5ea",
  },
  mixSegment: {
    height: "100%",
    transition: "width 200ms ease",
  },
};

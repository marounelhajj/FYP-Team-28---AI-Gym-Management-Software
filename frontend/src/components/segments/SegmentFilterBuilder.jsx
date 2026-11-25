import { useEffect, useMemo, useRef, useState } from "react";
import { createSegment, previewSegmentFilters, updateSegment } from "../../api/segments.js";
import SegmentedControl from "../SegmentedControl.jsx";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

// SCRUM-43: Filter builder for creating or editing a member segment.
// Evaluates rules on the backend and displays a sticky live count debounced ~300ms.

function cleanFormFilters(form) {
  const filters = {};

  if (form.branches.length > 0) filters.branches = form.branches;
  if (form.statuses.length > 0) filters.statuses = form.statuses;
  if (form.plans.length > 0) filters.plans = form.plans;
  if (form.classTypes.length > 0) filters.classTypes = form.classTypes;
  if (form.riskLevels.length > 0) filters.riskLevels = form.riskLevels;

  const num = (v, isFloat = false) => {
    if (v === "" || v === null || v === undefined) return undefined;
    const n = isFloat ? parseFloat(v) : parseInt(v, 10);
    return Number.isNaN(n) ? undefined : n;
  };

  const ranges = [
    ["ageMin", false],
    ["ageMax", false],
    ["tenureMonthsMin", false],
    ["tenureMonthsMax", false],
    ["visitsPerWeekMin", true],
    ["visitsPerWeekMax", true],
    ["daysSinceLastVisitMin", false],
    ["daysSinceLastVisitMax", false],
    ["renewalInDaysMin", false],
    ["renewalInDaysMax", false],
  ];

  for (const [key, isFloat] of ranges) {
    const val = num(form[key], isFloat);
    if (val !== undefined) filters[key] = val;
  }

  if (form.ptClient === "yes") filters.ptClient = true;
  else if (form.ptClient === "no") filters.ptClient = false;

  if (form.clusterGroup !== undefined && form.clusterGroup !== null) {
    filters.clusterGroup = form.clusterGroup;
  }

  return filters;
}

function initForm(segment, meta) {
  const f = segment?.filters || {};
  return {
    name: segment?.name || "",
    description: segment?.description || "",
    branches: f.branches ? [...f.branches] : [],
    statuses: f.statuses ? [...f.statuses] : (meta?.defaultStatuses || ["Active", "Frozen"]),
    plans: f.plans ? [...f.plans] : [],
    classTypes: f.classTypes ? [...f.classTypes] : [],
    riskLevels: f.riskLevels ? [...f.riskLevels] : [],
    ageMin: f.ageMin !== undefined ? String(f.ageMin) : "",
    ageMax: f.ageMax !== undefined ? String(f.ageMax) : "",
    tenureMonthsMin: f.tenureMonthsMin !== undefined ? String(f.tenureMonthsMin) : "",
    tenureMonthsMax: f.tenureMonthsMax !== undefined ? String(f.tenureMonthsMax) : "",
    visitsPerWeekMin: f.visitsPerWeekMin !== undefined ? String(f.visitsPerWeekMin) : "",
    visitsPerWeekMax: f.visitsPerWeekMax !== undefined ? String(f.visitsPerWeekMax) : "",
    daysSinceLastVisitMin: f.daysSinceLastVisitMin !== undefined ? String(f.daysSinceLastVisitMin) : "",
    daysSinceLastVisitMax: f.daysSinceLastVisitMax !== undefined ? String(f.daysSinceLastVisitMax) : "",
    renewalInDaysMin: f.renewalInDaysMin !== undefined ? String(f.renewalInDaysMin) : "",
    renewalInDaysMax: f.renewalInDaysMax !== undefined ? String(f.renewalInDaysMax) : "",
    ptClient: f.ptClient === true ? "yes" : f.ptClient === false ? "no" : "any",
    clusterGroup: f.clusterGroup,
  };
}

export default function SegmentFilterBuilder({ segment, meta, onClose, onSaved }) {
  const isEditing = Boolean(segment);
  const [form, setForm] = useState(() => initForm(segment, meta));
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Live preview state
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState(null);
  const [countKey, setCountKey] = useState(0);

  const cleanFilters = useMemo(() => cleanFormFilters(form), [form]);

  // Debounced live preview call (~300ms)
  const timerRef = useRef(null);
  useEffect(() => {
    setPreviewLoading(true);
    setPreviewError(null);
    clearTimeout(timerRef.current);

    timerRef.current = setTimeout(() => {
      previewSegmentFilters(cleanFilters)
        .then((res) => {
          setPreview(res);
          setCountKey((k) => k + 1);
          setPreviewError(null);
        })
        .catch((err) => {
          setPreviewError(err.message || "Could not preview filters");
        })
        .finally(() => {
          setPreviewLoading(false);
        });
    }, 300);

    return () => clearTimeout(timerRef.current);
  }, [cleanFilters]);

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFieldErrors((prev) => ({ ...prev, [key]: undefined, filters: undefined }));
  }

  function toggleChip(field, item) {
    const current = form[field];
    const next = current.includes(item) ? current.filter((x) => x !== item) : [...current, item];
    updateField(field, next);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});

    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      filters: cleanFilters,
    };

    try {
      const res = isEditing
        ? await updateSegment(segment.id, payload)
        : await createSegment(payload);
      onSaved(res, isEditing);
    } catch (err) {
      if (err.fieldErrors) {
        setFieldErrors(err.fieldErrors);
      } else {
        setSubmitError(err.message || "Failed to save segment.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose} role="dialog" aria-modal="true" aria-label={isEditing ? "Edit Segment" : "New Segment"}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <style>{BUILDER_CSS}</style>

        {/* Modal Header */}
        <div style={styles.modalHeader}>
          <div>
            <h2 style={styles.modalTitle}>{isEditing ? "Edit Segment" : "New Member Segment"}</h2>
            <p style={styles.modalSubtitle}>
              Define custom rules based on attendance, tenure, membership plans, and churn risk.
            </p>
          </div>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close dialog">
            &times;
          </button>
        </div>

        {/* Sticky Live Count Bar */}
        <div style={styles.stickyBar}>
          <div style={styles.stickyContent}>
            <div style={styles.liveCountRow}>
              <span style={styles.liveLabel}>Live audience:</span>
              {preview ? (
                <span key={countKey} className="seg-pop" style={styles.liveNumbers}>
                  <strong style={styles.boldCount}>{preview.count}</strong> members
                  <span style={styles.liveSub}> · <strong>{preview.targetable}</strong> can be targeted · {preview.optedOut} opted out</span>
                </span>
              ) : previewLoading ? (
                <span style={styles.liveLoading}>Calculating...</span>
              ) : (
                <span style={styles.liveLoading}>—</span>
              )}
            </div>
            {preview?.summary && (
              <div style={styles.liveSummary} title="Evaluated filter summary">
                {preview.summary}
              </div>
            )}
            {previewError && <div style={styles.liveError}>{previewError}</div>}
          </div>
        </div>

        {submitError && <div style={styles.errorBox} role="alert">{submitError}</div>}
        {fieldErrors.filters && (
          <div style={styles.errorBox} role="alert">
            {Array.isArray(fieldErrors.filters) ? fieldErrors.filters[0] : fieldErrors.filters}
          </div>
        )}

        <form onSubmit={handleSubmit} style={styles.form}>
          {/* General info */}
          <div style={styles.section}>
            <div style={styles.field}>
              <label style={styles.label} htmlFor="seg-name">
                Segment name <span style={styles.required}>*</span>
              </label>
              <input
                id="seg-name"
                type="text"
                value={form.name}
                maxLength={60}
                required
                placeholder="e.g. Regular Morning Warriors"
                onChange={(e) => updateField("name", e.target.value)}
                style={{
                  ...styles.input,
                  ...(fieldErrors.name ? styles.inputError : {}),
                }}
                className="seg-input"
                autoFocus
              />
              {fieldErrors.name && (
                <div style={styles.fieldError}>
                  {Array.isArray(fieldErrors.name) ? fieldErrors.name[0] : fieldErrors.name}
                </div>
              )}
            </div>

            <div style={styles.field}>
              <label style={styles.label} htmlFor="seg-desc">
                Description (optional)
              </label>
              <textarea
                id="seg-desc"
                value={form.description}
                maxLength={300}
                rows={2}
                placeholder="Brief summary of who this group targets and why..."
                onChange={(e) => updateField("description", e.target.value)}
                style={styles.textarea}
                className="seg-input"
              />
              {fieldErrors.description && (
                <div style={styles.fieldError}>
                  {Array.isArray(fieldErrors.description) ? fieldErrors.description[0] : fieldErrors.description}
                </div>
              )}
            </div>
          </div>

          {/* Filter Rules */}
          <div style={styles.filterSection}>
            <h3 style={styles.sectionHeading}>Filter Rules (all conditions must match)</h3>

            {/* Branches */}
            {meta?.branches && meta.branches.length > 0 && (
              <div style={styles.field}>
                <span style={styles.label}>Branches (any selected)</span>
                <div style={styles.chipGrid} role="group" aria-label="Filter branches">
                  {meta.branches.map((b) => {
                    const sel = form.branches.includes(b);
                    return (
                      <button
                        key={b}
                        type="button"
                        aria-pressed={sel}
                        onClick={() => toggleChip("branches", b)}
                        style={sel ? { ...styles.chip, ...styles.chipSelected } : styles.chip}
                        className="seg-chip"
                      >
                        {b}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Statuses */}
            {meta?.statuses && meta.statuses.length > 0 && (
              <div style={styles.field}>
                <span style={styles.label}>Member status (any selected)</span>
                <div style={styles.chipGrid} role="group" aria-label="Filter statuses">
                  {meta.statuses.map((s) => {
                    const sel = form.statuses.includes(s);
                    return (
                      <button
                        key={s}
                        type="button"
                        aria-pressed={sel}
                        onClick={() => toggleChip("statuses", s)}
                        style={sel ? { ...styles.chip, ...styles.chipSelected } : styles.chip}
                        className="seg-chip"
                      >
                        {s}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Membership plans */}
            {meta?.plans && meta.plans.length > 0 && (
              <div style={styles.field}>
                <span style={styles.label}>Plans (any selected)</span>
                <div style={styles.chipGrid} role="group" aria-label="Filter plans">
                  {meta.plans.map((p) => {
                    const sel = form.plans.includes(p);
                    return (
                      <button
                        key={p}
                        type="button"
                        aria-pressed={sel}
                        onClick={() => toggleChip("plans", p)}
                        style={sel ? { ...styles.chip, ...styles.chipSelected } : styles.chip}
                        className="seg-chip"
                      >
                        {p}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Class Types */}
            {meta?.classTypes && meta.classTypes.length > 0 && (
              <div style={styles.field}>
                <span style={styles.label}>Class types attended (last 90 days)</span>
                <div style={styles.chipGrid} role="group" aria-label="Filter class types">
                  {meta.classTypes.map((ct) => {
                    const sel = form.classTypes.includes(ct);
                    return (
                      <button
                        key={ct}
                        type="button"
                        aria-pressed={sel}
                        onClick={() => toggleChip("classTypes", ct)}
                        style={sel ? { ...styles.chip, ...styles.chipSelected } : styles.chip}
                        className="seg-chip"
                      >
                        {ct}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Churn Risk Levels */}
            {meta?.riskLevels && meta.riskLevels.length > 0 && (
              <div style={styles.field}>
                <span style={styles.label}>Churn risk level</span>
                <div style={styles.chipGrid} role="group" aria-label="Filter risk levels">
                  {meta.riskLevels.map((lvl) => {
                    const sel = form.riskLevels.includes(lvl);
                    return (
                      <button
                        key={lvl}
                        type="button"
                        aria-pressed={sel}
                        onClick={() => toggleChip("riskLevels", lvl)}
                        style={sel ? { ...styles.chip, ...styles.chipSelected } : styles.chip}
                        className="seg-chip"
                      >
                        {lvl} Risk
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Personal Training Client (3-way SegmentedControl) */}
            <div style={styles.field}>
              <span style={styles.label}>Personal training client (last 90 days)</span>
              <div style={{ maxWidth: 300 }}>
                <SegmentedControl
                  ariaLabel="Personal training client filter"
                  value={form.ptClient}
                  onChange={(val) => updateField("ptClient", val)}
                  options={[
                    { value: "any", label: "Any" },
                    { value: "yes", label: "Yes" },
                    { value: "no", label: "No" },
                  ]}
                />
              </div>
            </div>

            {/* Min-Max Numeric Pairs */}
            <h4 style={styles.subHeading}>Numeric Ranges</h4>
            <div style={styles.rangeGrid}>
              {/* Age */}
              <div style={styles.rangeField}>
                <span style={styles.rangeLabel}>Age (years)</span>
                <div style={styles.minMaxRow}>
                  <input
                    type="number"
                    min="0"
                    max="120"
                    placeholder="Min"
                    value={form.ageMin}
                    onChange={(e) => updateField("ageMin", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Minimum age"
                  />
                  <span style={styles.rangeDash}>–</span>
                  <input
                    type="number"
                    min="0"
                    max="120"
                    placeholder="Max"
                    value={form.ageMax}
                    onChange={(e) => updateField("ageMax", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Maximum age"
                  />
                </div>
              </div>

              {/* Tenure in months */}
              <div style={styles.rangeField}>
                <span style={styles.rangeLabel}>Tenure (months)</span>
                <div style={styles.minMaxRow}>
                  <input
                    type="number"
                    min="0"
                    max="600"
                    placeholder="Min"
                    value={form.tenureMonthsMin}
                    onChange={(e) => updateField("tenureMonthsMin", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Minimum tenure in months"
                  />
                  <span style={styles.rangeDash}>–</span>
                  <input
                    type="number"
                    min="0"
                    max="600"
                    placeholder="Max"
                    value={form.tenureMonthsMax}
                    onChange={(e) => updateField("tenureMonthsMax", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Maximum tenure in months"
                  />
                </div>
              </div>

              {/* Visits per week (last 4 weeks) */}
              <div style={styles.rangeField}>
                <span style={styles.rangeLabel}>Visits per week (avg last 4 wks)</span>
                <div style={styles.minMaxRow}>
                  <input
                    type="number"
                    min="0"
                    max="14"
                    step="0.1"
                    placeholder="Min"
                    value={form.visitsPerWeekMin}
                    onChange={(e) => updateField("visitsPerWeekMin", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Minimum visits per week"
                  />
                  <span style={styles.rangeDash}>–</span>
                  <input
                    type="number"
                    min="0"
                    max="14"
                    step="0.1"
                    placeholder="Max"
                    value={form.visitsPerWeekMax}
                    onChange={(e) => updateField("visitsPerWeekMax", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Maximum visits per week"
                  />
                </div>
              </div>

              {/* Days since last visit */}
              <div style={styles.rangeField}>
                <span style={styles.rangeLabel}>Days since last visit</span>
                <div style={styles.minMaxRow}>
                  <input
                    type="number"
                    min="0"
                    max="3650"
                    placeholder="Min"
                    value={form.daysSinceLastVisitMin}
                    onChange={(e) => updateField("daysSinceLastVisitMin", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Minimum days since last visit"
                  />
                  <span style={styles.rangeDash}>–</span>
                  <input
                    type="number"
                    min="0"
                    max="3650"
                    placeholder="Max"
                    value={form.daysSinceLastVisitMax}
                    onChange={(e) => updateField("daysSinceLastVisitMax", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Maximum days since last visit"
                  />
                </div>
              </div>

              {/* Renewal in days */}
              <div style={styles.rangeField}>
                <span style={styles.rangeLabel}>Renewal in days (negative = lapsed)</span>
                <div style={styles.minMaxRow}>
                  <input
                    type="number"
                    min="-3650"
                    max="3650"
                    placeholder="Min"
                    value={form.renewalInDaysMin}
                    onChange={(e) => updateField("renewalInDaysMin", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Minimum renewal days"
                  />
                  <span style={styles.rangeDash}>–</span>
                  <input
                    type="number"
                    min="-3650"
                    max="3650"
                    placeholder="Max"
                    value={form.renewalInDaysMax}
                    onChange={(e) => updateField("renewalInDaysMax", e.target.value)}
                    style={styles.rangeInput}
                    className="seg-input"
                    aria-label="Maximum renewal days"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Form Actions */}
          <div style={styles.actions}>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              style={styles.cancelBtn}
              className="seg-press"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={styles.submitBtn}
              className="seg-press"
            >
              {submitting ? "Saving..." : isEditing ? "Save changes" : "Create segment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const BLUE = "#124096";

const BUILDER_CSS = `
.seg-chip {
  transition: background 150ms ease, color 150ms ease, border-color 150ms ease, transform 120ms ease;
}
.seg-chip:hover {
  border-color: ${BLUE};
}
.seg-chip:active {
  transform: scale(0.97);
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
  from { transform: scale(0.92); opacity: 0.5; }
  to { transform: none; opacity: 1; }
}
.seg-input:focus-visible, .seg-chip:focus-visible, .seg-press:focus-visible {
  outline: 3px solid ${BLUE};
  outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  .seg-chip, .seg-press { transition: none; }
  .seg-pop { animation: none; }
  .seg-chip:active, .seg-press:active:not(:disabled) { transform: none; }
}
`;

const styles = {
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0, 0, 0, 0.45)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 1000,
    backdropFilter: "blur(2px)",
  },
  modal: {
    background: "#fff",
    borderRadius: 20,
    padding: 24,
    width: "100%",
    maxWidth: 720,
    maxHeight: "92vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 12px 48px rgba(0, 0, 0, 0.22)",
    display: "flex",
    flexDirection: "column",
  },
  modalHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 16,
    gap: 16,
  },
  modalTitle: {
    fontSize: 22,
    fontWeight: 800,
    margin: 0,
    color: "#1a1a1a",
  },
  modalSubtitle: {
    fontSize: 13,
    color: "#666",
    marginTop: 4,
    marginBottom: 0,
  },
  closeButton: {
    border: "none",
    background: "transparent",
    fontSize: 26,
    lineHeight: 1,
    cursor: "pointer",
    color: "#888",
    padding: "0 4px",
  },
  stickyBar: {
    position: "sticky",
    top: -24,
    zIndex: 20,
    background: "#f0f4fc",
    border: "1px solid #c7d8f5",
    borderRadius: 14,
    padding: "12px 16px",
    marginBottom: 20,
    boxShadow: "0 2px 8px rgba(18, 64, 150, 0.08)",
  },
  stickyContent: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  liveCountRow: {
    display: "flex",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: 8,
  },
  liveLabel: {
    fontSize: 13,
    fontWeight: 700,
    color: "#124096",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  liveNumbers: {
    fontSize: 16,
    color: "#1a1a1a",
    fontWeight: 500,
  },
  boldCount: {
    fontSize: 20,
    fontWeight: 900,
    color: "#124096",
  },
  liveSub: {
    fontSize: 13,
    color: "#555",
    fontWeight: 500,
  },
  liveSummary: {
    fontSize: 12,
    color: "#4a5568",
    fontStyle: "italic",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  liveLoading: {
    fontSize: 14,
    fontWeight: 600,
    color: "#777",
  },
  liveError: {
    fontSize: 12,
    color: "#b3261e",
    fontWeight: 600,
  },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 16,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  filterSection: {
    borderTop: "1px solid #ebebf0",
    paddingTop: 16,
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  sectionHeading: {
    fontSize: 15,
    fontWeight: 800,
    margin: "0 0 6px 0",
    color: "#1a1a1a",
  },
  subHeading: {
    fontSize: 14,
    fontWeight: 700,
    margin: "8px 0 2px 0",
    color: "#444",
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  label: {
    fontSize: 13,
    fontWeight: 700,
    color: "#333",
  },
  required: {
    color: "#b3261e",
  },
  input: {
    height: 42,
    padding: "0 12px",
    fontSize: 14,
    fontWeight: 500,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    outline: "none",
    background: "#fff",
    color: "#1a1a1a",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  inputError: {
    borderColor: "#b3261e",
  },
  textarea: {
    padding: "10px 12px",
    fontSize: 14,
    fontWeight: 500,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    outline: "none",
    background: "#fff",
    color: "#1a1a1a",
    boxSizing: "border-box",
    fontFamily: "inherit",
    resize: "vertical",
  },
  fieldError: {
    color: "#b3261e",
    fontSize: 12,
    fontWeight: 600,
  },
  chipGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    padding: "7px 14px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 20,
    border: "1px solid #d0d0d5",
    background: "#f7f7f9",
    color: "#444",
    cursor: "pointer",
    fontFamily: "inherit",
    display: "inline-flex",
    alignItems: "center",
  },
  chipSelected: {
    border: `1.5px solid ${BLUE}`,
    background: "#eef2fa",
    color: BLUE,
    fontWeight: 700,
  },
  rangeGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 14,
  },
  rangeField: {
    display: "flex",
    flexDirection: "column",
    gap: 5,
  },
  rangeLabel: {
    fontSize: 12,
    fontWeight: 700,
    color: "#555",
  },
  minMaxRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  rangeInput: {
    flex: 1,
    height: 38,
    padding: "0 10px",
    fontSize: 14,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    color: "#1a1a1a",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  rangeDash: {
    color: "#888",
    fontWeight: 700,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 10,
    marginTop: 20,
    borderTop: "1px solid #ebebf0",
    paddingTop: 16,
  },
  cancelBtn: {
    padding: "10px 18px",
    fontSize: 14,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#f5f5f7",
    color: "#333",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  submitBtn: {
    padding: "10px 22px",
    fontSize: 14,
    fontWeight: 700,
    border: "none",
    borderRadius: 10,
    ...BUTTON_COLORS.blue,
    cursor: "pointer",
    fontFamily: "inherit",
  },
};

import { useState } from "react";
import { downloadExport } from "../../api/segments.js";

// SCRUM-114: Export engagement data or member lists as CSV attachments.
// Used on Attendance Trends, Segment Uptake, and Member Segments pages.
export default function ExportButton({
  params,
  label = "Export CSV",
  disabled = false,
  onSuccess,
  onError,
  style = {},
  className = "seg-press",
}) {
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState(null);

  async function handleExport() {
    if (busy || disabled) return;
    setBusy(true);
    setLocalError(null);
    try {
      const filename = await downloadExport(params);
      if (onSuccess) onSuccess(filename);
    } catch (err) {
      const msg = err.message || "Export failed.";
      if (onError) onError(msg);
      else setLocalError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={styles.wrap}>
      <button
        type="button"
        onClick={handleExport}
        disabled={disabled || busy}
        style={{
          ...styles.button,
          ...style,
          ...(disabled || busy ? styles.disabled : {}),
        }}
        className={className}
        aria-label={label}
        title={label}
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        <span>{busy ? "Exporting..." : label}</span>
      </button>
      {localError && <div style={styles.errorText} role="alert">{localError}</div>}
    </div>
  );
}

const styles = {
  wrap: {
    display: "inline-flex",
    flexDirection: "column",
    alignItems: "flex-end",
  },
  button: {
    height: 40,
    padding: "0 14px",
    fontSize: 14,
    fontWeight: 700,
    border: "1px solid #d0d0d5",
    borderRadius: 10,
    background: "#fff",
    color: "#1a1a1a",
    cursor: "pointer",
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    fontFamily: "inherit",
    whiteSpace: "nowrap",
    transition: "background 140ms ease, border-color 140ms ease, transform 120ms ease",
  },
  disabled: {
    opacity: 0.6,
    cursor: "not-allowed",
  },
  errorText: {
    fontSize: 12,
    color: "#b3261e",
    fontWeight: 600,
    marginTop: 4,
  },
};

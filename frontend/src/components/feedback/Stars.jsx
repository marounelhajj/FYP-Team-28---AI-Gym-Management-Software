// Star ratings, shared by the member's rating form (SCRUM-40) and the
// coach's ratings page.

const LABELS = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];

export function StarInput({ value, onChange, disabled = false }) {
  return (
    <div role="radiogroup" aria-label="Rating" style={styles.row}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} star${n === 1 ? "" : "s"} - ${LABELS[n]}`}
          disabled={disabled}
          onClick={() => onChange(n)}
          style={{ ...styles.starButton, color: n <= (value || 0) ? "#e8a400" : "#c8c8cf" }}
        >
          ★
        </button>
      ))}
      <span style={styles.label}>{value ? LABELS[value] : "Tap to rate"}</span>
    </div>
  );
}

export function Stars({ value, size = 15 }) {
  return (
    <span aria-label={`${value} out of 5 stars`} style={{ fontSize: size, letterSpacing: 1, whiteSpace: "nowrap" }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} aria-hidden="true" style={{ color: n <= Math.round(value) ? "#e8a400" : "#d4d4da" }}>★</span>
      ))}
    </span>
  );
}

const styles = {
  row: { display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" },
  starButton: {
    width: 36, height: 36, padding: 0, border: "none", background: "transparent", fontSize: 28, lineHeight: 1,
    cursor: "pointer",
  },
  label: { fontSize: 13, fontWeight: 700, color: "#555", marginLeft: 6 },
};

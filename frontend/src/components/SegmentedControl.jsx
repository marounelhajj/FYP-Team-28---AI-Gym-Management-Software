// options: [{ value, label, tag? }] - a row of mutually exclusive choices.
export default function SegmentedControl({ options, value, onChange, ariaLabel }) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} style={styles.group}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            style={selected ? { ...styles.option, ...styles.selected } : styles.option}
          >
            {option.label}
            {option.tag && <span style={styles.tag}>{option.tag}</span>}
          </button>
        );
      })}
    </div>
  );
}

const styles = {
  group: { display: "flex", gap: 8 },
  option: {
    flex: 1,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 40,
    padding: "0 10px",
    fontSize: 14,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#444",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  selected: {
    border: "1px solid #124096",
    background: "#eef2fa",
    color: "#124096",
    boxShadow: "inset 0 0 0 1px #124096",
  },
  tag: {
    fontSize: 11,
    fontWeight: 700,
    padding: "2px 6px",
    borderRadius: 4,
    background: "#e6f4ea",
    color: "#1e7a34",
  },
};

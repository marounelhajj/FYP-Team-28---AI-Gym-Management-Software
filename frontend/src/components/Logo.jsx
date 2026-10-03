// App logo: a barbell (gym) fused with a sparkle accent (AI), in the
// established brand blue. Used as both the in-app header mark and the
// source for public/favicon.svg (keep the two in sync if this changes).
export default function Logo({ size = 40, showWordmark = true }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Fitness Factory logo"
        style={{ flexShrink: 0 }}
      >
        <rect width="100" height="100" rx="24" fill="#124096" />
        <rect x="14" y="38" width="10" height="32" rx="3" fill="#ffffff" />
        <rect x="24" y="46" width="6" height="16" rx="2" fill="#ffffff" />
        <rect x="30" y="50" width="40" height="8" rx="4" fill="#ffffff" />
        <rect x="70" y="46" width="6" height="16" rx="2" fill="#ffffff" />
        <rect x="76" y="38" width="10" height="32" rx="3" fill="#ffffff" />
        <path
          d="M78,13 L80.83,21.17 L89,24 L80.83,26.83 L78,35 L75.17,26.83 L67,24 L75.17,21.17 Z"
          fill="#ffffff"
        />
      </svg>
      {showWordmark && (
        <div style={{ lineHeight: 1.15 }}>
          <div
            style={{
              fontSize: Math.round(size * 0.42),
              fontWeight: 800,
              color: "#1a1a1a",
              fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
            }}
          >
            Fitness Factory
          </div>
          <div
            style={{
              fontSize: Math.round(size * 0.2),
              fontWeight: 600,
              letterSpacing: 0.6,
              color: "#888",
              textTransform: "uppercase",
              fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
            }}
          >
            AI Gym Management
          </div>
        </div>
      )}
    </div>
  );
}

// App logo: the Fitness Factory badge (public/logo-badge.png - also the
// favicon, see index.html). Used as the in-app header mark.
export default function Logo({ size = 40, showWordmark = true }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <img
        src="/logo-badge.png"
        width={size}
        height={size}
        alt="Fitness Factory logo"
        style={{ flexShrink: 0, borderRadius: "50%" }}
      />
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

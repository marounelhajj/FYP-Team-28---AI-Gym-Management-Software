import { useEffect, useState } from "react";
import { fetchBranchComparison } from "../../api/finance.js";

// User story (SCRUM-105): "As a general manager, I want to compare branch
// revenue performance in a single view, so that I can identify branches
// underperforming financially."
//
// Every branch over one period, ranked by revenue: its share of the company,
// growth on the period before, expenses, net and margin, revenue per active
// member, and - for a branch that's flagged - the reasons why, in plain words.
// Below, six months of revenue per branch on one chart. The thresholds are
// the server's (finance/compare.py); this page only shows them.

const PERIODS = [
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["this_quarter", "This quarter"],
  ["last_quarter", "Last quarter"],
  ["this_year", "This year"],
  ["custom", "Custom"],
];
const LINE_COLORS = ["#124096", "#129638", "#c45a00", "#8b3fb8", "#0f8a8a", "#b3261e"];
const RED = "#b3261e";
const GREEN = "#0f6e2b";

function money(value) {
  const n = Number(value);
  const text = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `-$${text}` : `$${text}`;
}

// A round top for the chart: 1, 2 or 5 times a power of ten.
function niceCeiling(max) {
  if (max <= 0) return 100;
  const power = 10 ** Math.floor(Math.log10(max));
  return [1, 2, 5, 10].map((m) => m * power).find((v) => v >= max);
}

function shortMoney(value) {
  const n = Number(value);
  return n >= 1000 ? `$${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `$${Math.round(n)}`;
}

function growth(percent) {
  if (percent === null) return { text: "no earlier revenue", color: "#777" };
  if (percent === 0) return { text: "no change", color: "#777" };
  return { text: `${percent > 0 ? "▲" : "▼"} ${Math.abs(percent).toFixed(1)}%`, color: percent > 0 ? GREEN : RED };
}

function range(from, to) {
  const fmt = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return `${fmt(from)} – ${fmt(to)}`;
}

export default function BranchComparison() {
  const [filters, setFilters] = useState({ period: "this_month", dateFrom: "", dateTo: "" });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (filters.period === "custom" && (!filters.dateFrom || !filters.dateTo)) return;
    setLoading(true);
    fetchBranchComparison(filters)
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filters]);

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Branch Comparison</h1>
      <p style={styles.subtitle}>Revenue performance of every branch side by side, and which ones are falling behind.</p>

      <div style={styles.toolbar}>
        <label style={styles.toolField}>
          <span style={styles.toolLabel}>Period</span>
          <select value={filters.period} onChange={set("period")} style={styles.input} aria-label="Period">
            {PERIODS.map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </label>
        {filters.period === "custom" && (
          <>
            <label style={styles.toolField}>
              <span style={styles.toolLabel}>From</span>
              <input type="date" value={filters.dateFrom} onChange={set("dateFrom")} style={styles.input} aria-label="From" />
            </label>
            <label style={styles.toolField}>
              <span style={styles.toolLabel}>To</span>
              <input type="date" value={filters.dateTo} onChange={set("dateTo")} style={styles.input} aria-label="To" />
            </label>
          </>
        )}
        {data && (
          <p style={styles.rangeNote}>
            {range(data.dateFrom, data.dateTo)}, compared with {range(data.previous.dateFrom, data.previous.dateTo)}
            {loading ? " · updating..." : ""}
          </p>
        )}
      </div>

      {error && <div style={styles.errorBox}>{error}</div>}
      {!data && !error && <p style={styles.muted}>{filters.period === "custom" ? "Pick both dates." : "Loading..."}</p>}
      {data && <Comparison data={data} />}
    </div>
  );
}

function Comparison({ data }) {
  const { totals, rules } = data;
  const totalGrowth = growth(totals.growthPercent);
  const top = Math.max(...data.branches.map((b) => Number(b.revenue)), 0);
  return (
    <>
      <div style={styles.tiles}>
        <Tile label="Company revenue" value={money(totals.revenue)} sub={`${totalGrowth.text} vs ${money(totals.previousRevenue)} before`} subColor={totalGrowth.color} strong />
        <Tile
          label="Net (revenue - expenses)"
          value={money(totals.net)}
          sub={totals.marginPercent === null ? "No revenue" : `${totals.marginPercent}% margin · ${money(totals.expenses)} spent`}
          valueColor={Number(totals.net) < 0 ? RED : null}
        />
        <Tile
          label="Revenue per active member"
          value={totals.revenuePerMember === null ? "—" : money(totals.revenuePerMember)}
          sub={`${totals.activeMembers} active members company-wide`}
        />
        <Tile
          label="Underperforming"
          value={`${data.underperformingCount} of ${data.branches.length}`}
          sub={data.underperformingCount ? "Branches with at least one warning below" : "Every branch is on track"}
          valueColor={data.underperformingCount ? RED : GREEN}
        />
      </div>

      <section style={styles.panel} aria-label="Branches ranked by revenue">
        <h2 style={styles.panelTitle}>Ranked by revenue</h2>
        <p style={styles.panelHint}>
          A branch is flagged for a loss, revenue below {rules.lowSharePercent}% of the branch average ({money(totals.averageRevenue)}),
          revenue down {rules.declinePercent}% or more on the period before, or revenue per active member below{" "}
          {rules.lowSharePercent}% of the company figure.
        </p>
        <ol style={styles.cards}>
          {data.branches.map((b) => (
            <BranchCard key={b.branch} branch={b} top={top} />
          ))}
        </ol>
      </section>

      <section style={styles.panel} aria-label="Revenue over six months">
        <h2 style={styles.panelTitle}>Revenue by month</h2>
        <p style={styles.panelHint}>Memberships and retail, the six months up to the end of the period.</p>
        <TrendChart trend={data.trend} />
      </section>
    </>
  );
}

function BranchCard({ branch: b, top }) {
  const change = growth(b.growthPercent);
  const width = top === 0 ? 0 : Math.max(2, Math.round((Number(b.revenue) / top) * 100));
  return (
    <li style={{ ...styles.card, ...(b.underperforming ? styles.cardFlagged : null) }}>
      <div style={styles.cardHead}>
        <span style={styles.rank}>#{b.rank}</span>
        <span style={styles.branchName}>{b.branch}</span>
        {b.underperforming ? <span style={styles.flagTag}>Underperforming</span> : <span style={styles.okTag}>On track</span>}
      </div>
      <div style={styles.revenue}>{money(b.revenue)}</div>
      <div style={styles.barTrack} role="img" aria-label={`${b.branch}: ${b.sharePercent ?? 0}% of company revenue`}>
        <div style={{ ...styles.barFill, width: `${width}%`, background: b.underperforming ? "#de0b12" : "#124096" }} />
      </div>
      <div style={styles.cardSub}>
        {b.sharePercent === null ? "No company revenue yet" : `${b.sharePercent}% of company revenue`} ·{" "}
        <span style={{ color: change.color, fontWeight: 700 }}>{change.text}</span>
      </div>
      <dl style={styles.stats}>
        <Stat label="Memberships" value={money(b.revenueBySource.memberships)} />
        <Stat label="Retail" value={money(b.revenueBySource.retail)} />
        <Stat label="Expenses" value={money(b.expenses)} />
        <Stat label="Net" value={money(b.net)} color={Number(b.net) < 0 ? RED : null} />
        <Stat label="Margin" value={b.marginPercent === null ? "—" : `${b.marginPercent}%`} />
        <Stat label="Per member" value={b.revenuePerMember === null ? "—" : money(b.revenuePerMember)} hint={`${b.activeMembers} active`} />
      </dl>
      {b.flags.length > 0 && (
        <ul style={styles.flags}>
          {b.flags.map((f) => (
            <li key={f.code} style={styles.flag}>{f.text}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Stat({ label, value, color, hint }) {
  return (
    <div style={styles.stat}>
      <dt style={styles.statLabel}>{label}{hint ? ` (${hint})` : ""}</dt>
      <dd style={{ ...styles.statValue, ...(color ? { color } : null) }}>{value}</dd>
    </div>
  );
}

function TrendChart({ trend }) {
  const W = 1000;
  const H = 300;
  const pad = { l: 56, r: 16, t: 14, b: 30 };
  const values = trend.series.flatMap((s) => s.revenue.map(Number));
  const max = Math.max(...values, 0);
  const ceiling = niceCeiling(max);
  const x = (i) => pad.l + (i * (W - pad.l - pad.r)) / Math.max(trend.months.length - 1, 1);
  const y = (v) => pad.t + (1 - v / ceiling) * (H - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ceiling * f);
  const monthLabel = (key) => {
    const [yr, m] = key.split("-").map(Number);
    return new Date(yr, m - 1, 1).toLocaleDateString("en-GB", { month: "short" });
  };
  const description = trend.series
    .map((s) => `${s.branch}: ${s.revenue.map((v, i) => `${monthLabel(trend.months[i])} ${shortMoney(v)}`).join(", ")}`)
    .join("; ");
  return (
    <div>
      <div style={styles.chartScroll}>
        <svg viewBox={`0 0 ${W} ${H}`} style={styles.chart} role="img" aria-label={`Revenue by month per branch. ${description}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="#ececf0" />
              <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="#777">{shortMoney(t)}</text>
            </g>
          ))}
          {trend.months.map((m, i) => (
            <text key={m} x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="#777">{monthLabel(m)}</text>
          ))}
          {trend.series.map((s, si) => {
            const color = LINE_COLORS[si % LINE_COLORS.length];
            const points = s.revenue.map((v, i) => `${x(i)},${y(Number(v))}`).join(" ");
            return (
              <g key={s.branch}>
                <polyline points={points} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />
                {s.revenue.map((v, i) => (
                  <circle key={i} cx={x(i)} cy={y(Number(v))} r="3.5" fill={color}>
                    <title>{`${s.branch}, ${monthLabel(trend.months[i])}: ${money(v)}`}</title>
                  </circle>
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div style={styles.legend}>
        {trend.series.map((s, si) => (
          <span key={s.branch} style={styles.legendItem}>
            <span style={{ ...styles.legendDot, background: LINE_COLORS[si % LINE_COLORS.length] }} />
            {s.branch}
          </span>
        ))}
      </div>
    </div>
  );
}

function Tile({ label, value, sub, subColor, valueColor, strong }) {
  return (
    <div style={{ ...styles.tile, ...(strong ? styles.tileStrong : null) }}>
      <span style={styles.tileLabel}>{label}</span>
      <span style={{ ...styles.tileValue, ...(valueColor ? { color: valueColor } : null) }}>{value}</span>
      {sub && <span style={{ ...styles.tileSub, ...(subColor ? { color: subColor } : null) }}>{sub}</span>}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 14px" },
  muted: { fontSize: 13, color: "#777", margin: 0 },
  errorBox: { background: "#fdeceb", color: RED, padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  toolbar: { display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap", alignItems: "flex-end" },
  toolField: { display: "flex", flexDirection: "column", gap: 4 },
  toolLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  input: { padding: "7px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff", fontFamily: "inherit" },
  rangeNote: { fontSize: 12, color: "#666", margin: "0 0 8px" },
  tiles: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 12 },
  tile: { display: "flex", flexDirection: "column", gap: 4, padding: "12px 14px", border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  tileStrong: { border: "1px solid #124096", boxShadow: "inset 0 0 0 1px #124096", background: "#eef2fa" },
  tileLabel: { fontSize: 12, fontWeight: 600, color: "#555" },
  tileValue: { fontSize: 24, fontWeight: 800 },
  tileSub: { fontSize: 12, color: "#666" },
  panel: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff", marginBottom: 12 },
  panelTitle: { fontSize: 15, fontWeight: 800, margin: "0 0 4px" },
  panelHint: { fontSize: 12, color: "#777", margin: "4px 0 12px", lineHeight: 1.45 },
  cards: { listStyle: "none", margin: 0, padding: 0, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 },
  card: { display: "flex", flexDirection: "column", gap: 6, padding: 14, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff" },
  cardFlagged: { border: "1px solid #f1b0ad", background: "#fff8f7" },
  cardHead: { display: "flex", alignItems: "center", gap: 8 },
  rank: { fontSize: 13, fontWeight: 800, color: "#777" },
  branchName: { fontSize: 16, fontWeight: 800, flex: 1 },
  flagTag: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: "#fdeceb", color: RED },
  okTag: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: "#e3f5e8", color: GREEN },
  revenue: { fontSize: 24, fontWeight: 800 },
  barTrack: { height: 8, borderRadius: 999, background: "#ececf0", overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999 },
  cardSub: { fontSize: 12, color: "#666" },
  stats: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 10px", margin: "4px 0 0" },
  stat: { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 },
  statLabel: { fontSize: 11, color: "#777" },
  statValue: { fontSize: 13, fontWeight: 700, margin: 0 },
  flags: { margin: "4px 0 0", padding: "8px 10px 8px 24px", borderRadius: 8, background: "#fdeceb", color: RED, fontSize: 12, display: "flex", flexDirection: "column", gap: 3 },
  flag: { lineHeight: 1.4 },
  chartScroll: { overflowX: "auto" },
  chart: { width: "100%", minWidth: 560, height: "auto", display: "block" },
  legend: { display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, color: "#555", marginTop: 6 },
  legendItem: { display: "flex", alignItems: "center", gap: 5 },
  legendDot: { width: 10, height: 10, borderRadius: 999, display: "inline-block" },
};

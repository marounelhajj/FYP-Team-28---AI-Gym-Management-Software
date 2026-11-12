import { useEffect, useState } from "react";
import { fetchMyPay } from "../../api/payroll.js";
import PayStatement from "./PayStatement.jsx";

// User story: "As a coach, I want to view my completed session count and
// earnings for the current pay period, so that I can verify my pay is
// correct."
//
// The coach's own statement: this month by default, or any of the last
// eleven. Read-only - rates are set by the branch manager.
export default function MyPay() {
  const [period, setPeriod] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    fetchMyPay(period)
      .then((body) => {
        if (!stale) {
          setData(body);
          setError(null);
        }
      })
      .catch((err) => !stale && setError(err.message))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [period]);

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>My Pay</h1>
      <p style={styles.subtitle}>
        The classes and private sessions you've taught, what each one pays, and your total for the pay period. If something
        looks wrong, show this to your branch manager.
      </p>
      {error && <div style={styles.errorBox}>{error}</div>}
      {!data && !error && <p style={styles.muted}>Loading...</p>}
      {data && <PayStatement data={data} period={period} onPeriod={setPeriod} loading={loading} />}
    </div>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1000, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 16px", lineHeight: 1.45 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 10 },
  muted: { fontSize: 13, color: "#888" },
};

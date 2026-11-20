import { useCallback, useEffect, useState } from "react";
import { fetchApprovals, fetchOrders, fetchPurchasingMeta } from "../../api/purchasing.js";
import SegmentedControl from "../SegmentedControl.jsx";
import PurchaseOrderDetail from "./PurchaseOrderDetail.jsx";
import PurchaseOrderForm from "./PurchaseOrderForm.jsx";
import { SourcingList, SupplierList } from "./SupplierManager.jsx";
import { STATUS_STYLES, formatDay, money, ui } from "./shared.js";

// User story: "As a branch manager, I want to submit supply reorder requests
// through the system, so that restocking doesn't depend on manual phone calls
// to vendors."
//
// What's running low at the branch (grouped by supplier, one click to order
// it), the branch's orders and where each stands, and - for head office -
// the orders waiting for approval, the supplier list and product sourcing.
// The server holds a Branch Manager to their own branch.

const FILTERS = [
  ["open", "Open"],
  ["pending", "Waiting approval"],
  ["closed", "Closed"],
  ["all", "All"],
];

export default function SupplyOrders() {
  const [branch, setBranch] = useState(null);
  const [meta, setMeta] = useState(null);
  const [orders, setOrders] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [filter, setFilter] = useState("open");
  const [tab, setTab] = useState("orders");
  const [creating, setCreating] = useState(null); // null | {} | { supplierId, products }
  const [openId, setOpenId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);

  const loadMeta = useCallback(() => {
    return fetchPurchasingMeta(branch)
      .then((body) => {
        setMeta(body);
        setError(null);
        if (body.canApprove) fetchApprovals().then((a) => setApprovals(a.results)).catch(() => setApprovals([]));
      })
      .catch((e) => setError(e.message));
  }, [branch]);

  const loadOrders = useCallback(() => {
    return fetchOrders(branch, filter)
      .then((body) => setOrders(body.results))
      .catch((e) => setError(e.message));
  }, [branch, filter]);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);
  useEffect(() => {
    loadOrders();
  }, [loadOrders]);
  useEffect(() => {
    if (!notice) return undefined;
    const t = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(t);
  }, [notice]);

  function refresh(message) {
    if (message) setNotice(message);
    loadMeta();
    loadOrders();
  }

  if (!meta) return <div style={styles.page}>{error ? <div style={ui.errorBox}>{error}</div> : <p style={ui.muted}>Loading...</p>}</div>;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Supply Orders · {meta.branch}</h1>
          <p style={styles.subtitle}>
            Order stock and supplies from suppliers by email. Orders under {money(meta.approvalLimit)} go straight out; bigger ones are approved by
            the General Manager first.
          </p>
        </div>
        <div style={styles.headerSide}>
          {meta.branches.length > 1 && (
            <select value={meta.branch} onChange={(e) => setBranch(e.target.value)} style={ui.input} aria-label="Branch">
              {meta.branches.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          )}
          {meta.canOrder && (
            <button type="button" onClick={() => setCreating({})} style={ui.primary}>
              + New order
            </button>
          )}
        </div>
      </div>
      {notice && <div style={{ ...ui.successBox, marginBottom: 12 }} role="status">{notice}</div>}
      {error && <div style={{ ...ui.errorBox, marginBottom: 12 }}>{error}</div>}

      {meta.canApprove && (
        <div style={{ marginBottom: 12 }}>
          <SegmentedControl
            ariaLabel="Section"
            options={[
              { value: "orders", label: "Orders" },
              { value: "suppliers", label: "Suppliers" },
              { value: "products", label: "Products & reorder levels" },
            ]}
            value={tab}
            onChange={setTab}
          />
        </div>
      )}

      {tab === "suppliers" && <SupplierList suppliers={meta.suppliers} onChanged={refresh} />}
      {tab === "products" && <SourcingList products={meta.products} suppliers={meta.suppliers} onChanged={refresh} />}

      {tab === "orders" && (
        <>
          {approvals.length > 0 && (
            <section style={{ ...styles.panel, ...styles.approvalPanel }} aria-label="Waiting for your approval">
              <h2 style={styles.panelTitle}>Waiting for your approval ({approvals.length})</h2>
              <ul style={styles.list}>
                {approvals.map((o) => (
                  <OrderRow key={o.id} order={o} showBranch onOpen={() => setOpenId(o.id)} />
                ))}
              </ul>
            </section>
          )}

          {meta.canOrder && meta.lowStock.length > 0 && (
            <section style={styles.panel} aria-label="Running low">
              <h2 style={styles.panelTitle}>Running low at {meta.branch}</h2>
              <p style={ui.hint}>At or below the reorder level, counting what&apos;s already on order. Suggested amounts bring it back to twice that level.</p>
              {meta.lowStock.map((group) => (
                <div key={group.supplierId ?? "none"} style={styles.lowGroup}>
                  <div style={styles.lowHead}>
                    <strong>{group.supplierName || "No usual supplier set"}</strong>
                    {group.supplierId && (
                      <button type="button" onClick={() => setCreating({ supplierId: group.supplierId, products: group.products })} style={ui.primary}>
                        Order from {group.supplierName}
                      </button>
                    )}
                  </div>
                  <ul style={styles.lowList}>
                    {group.products.map((p) => (
                      <li key={p.id}>
                        {p.name}: <strong style={{ color: "#b3261e" }}>{p.inStock} left</strong> (reorder at {p.reorderLevel}
                        {p.onOrder ? `, ${p.onOrder} on order` : ""}) - suggest {p.suggested}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          )}

          <section style={styles.panel} aria-label="Orders">
            <div style={styles.panelHead}>
              <h2 style={styles.panelTitle}>{meta.branch}&apos;s orders</h2>
              <div style={styles.filters}>
                {FILTERS.map(([key, label]) => (
                  <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)} style={{ ...styles.filter, ...(filter === key ? styles.filterOn : null) }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {!orders ? (
              <p style={ui.muted}>Loading...</p>
            ) : orders.length === 0 ? (
              <p style={ui.muted}>No orders here{filter === "open" && meta.canOrder ? " - use + New order to restock." : "."}</p>
            ) : (
              <ul style={styles.list}>
                {orders.map((o) => (
                  <OrderRow key={o.id} order={o} onOpen={() => setOpenId(o.id)} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {creating && (
        <PurchaseOrderForm
          meta={meta}
          start={creating}
          onClose={() => setCreating(null)}
          onPlaced={(order) => {
            setCreating(null);
            refresh(
              order.status === "Ordered"
                ? `${order.number} placed and emailed to ${order.supplier.name}.`
                : `${order.number} sent to the General Manager for approval.`,
            );
          }}
        />
      )}
      {openId && <PurchaseOrderDetail orderId={openId} onClose={() => setOpenId(null)} onChanged={() => refresh()} />}
    </div>
  );
}

function OrderRow({ order: o, showBranch, onOpen }) {
  const received = o.lines.reduce((n, l) => n + l.received, 0);
  const ordered = o.lines.reduce((n, l) => n + l.quantity, 0);
  return (
    <li>
      <button type="button" onClick={onOpen} style={styles.row} aria-label={`Open ${o.number}`}>
        <span style={styles.rowMain}>
          <span style={styles.rowTitle}>
            {o.number} · {o.supplier.name}
            {o.rush && !["Received", "Cancelled", "Rejected"].includes(o.status) && <span style={styles.urgent}>Urgent</span>}
            {o.sendError && <span style={styles.urgent}>Email failed</span>}
          </span>
          <span style={styles.rowMeta}>
            {showBranch && `${o.branch} · `}
            {o.lines.length} item{o.lines.length === 1 ? "" : "s"} · {o.requestedBy} · {o.createdAt.slice(0, 10)}
            {o.neededBy ? ` · needed ${formatDay(o.neededBy)}` : ""}
            {o.status === "Partly received" ? ` · ${received} of ${ordered} received` : ""}
          </span>
        </span>
        <span style={styles.rowTotal}>{money(o.total)}</span>
        <span style={{ ...ui.tag, ...STATUS_STYLES[o.status] }}>{o.status}</span>
      </button>
    </li>
  );
}

const styles = {
  page: { fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", maxWidth: 1100, margin: "0 auto", padding: "32px 20px", color: "#1a1a1a" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 14 },
  headerSide: { display: "flex", gap: 8, alignItems: "center" },
  title: { fontSize: 22, fontWeight: 800, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", margin: "4px 0 0", maxWidth: 680 },
  panel: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff", marginBottom: 12, display: "flex", flexDirection: "column", gap: 8 },
  approvalPanel: { borderColor: "#f3d9a4", background: "#fffaf0" },
  panelHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" },
  panelTitle: { fontSize: 15, fontWeight: 800, margin: 0 },
  filters: { display: "flex", gap: 6 },
  filter: { padding: "6px 12px", fontSize: 13, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 999, background: "#fff", cursor: "pointer" },
  filterOn: { background: "#124096", borderColor: "#124096", color: "#fff" },
  list: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  row: { width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff", cursor: "pointer", textAlign: "left", fontFamily: "inherit" },
  rowMain: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 },
  rowTitle: { fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" },
  rowMeta: { fontSize: 12, color: "#777" },
  rowTotal: { fontSize: 14, fontWeight: 800, whiteSpace: "nowrap" },
  urgent: { fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: "#de0b12", color: "#fff" },
  lowGroup: { border: "1px solid #f1d0ce", borderRadius: 10, padding: "10px 12px", background: "#fff8f7" },
  lowHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" },
  lowList: { margin: "6px 0 0", paddingLeft: 18, fontSize: 13, lineHeight: 1.6 },
};

import { useEffect, useState } from "react";
import { approveOrder, cancelOrder, closeOrder, fetchOrder, receiveOrder, rejectOrder, resendOrder } from "../../api/purchasing.js";
import { STATUS_STYLES, formatDay, money, ui } from "./shared.js";

// One order: what's on it, where it stands (approved, emailed to the
// supplier, delivered...), and what this person can do next. Each button is
// shown only when the server says it's allowed (canApprove, canReceive...).
export default function PurchaseOrderDetail({ orderId, onClose, onChanged }) {
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState(null); // "receive" | "reject" | "cancel" | "close"
  const [counts, setCounts] = useState({});
  const [text, setText] = useState("");

  useEffect(() => {
    fetchOrder(orderId).then(setOrder).catch((e) => setError(e.message));
  }, [orderId]);

  function startReceiving() {
    setCounts(Object.fromEntries(order.lines.filter((l) => l.outstanding).map((l) => [l.id, String(l.outstanding)])));
    setText("");
    setMode("receive");
  }

  async function run(action, message) {
    setBusy(true);
    setError(null);
    try {
      setOrder(await action());
      setNotice(message);
      setMode(null);
      setText("");
      onChanged();
    } catch (err) {
      const f = err.fieldErrors;
      setError((f && (f.items?.[0] || f.reason?.[0])) || err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={ui.overlay} onClick={onClose}>
      <div style={ui.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Supply order">
        <div style={ui.head}>
          <div>
            <h2 style={{ ...ui.title, display: "flex", alignItems: "center", gap: 8 }}>
              {order ? order.number : "Order"}
              {order && <span style={{ ...ui.tag, ...STATUS_STYLES[order.status] }}>{order.status}</span>}
              {order?.rush && order.status !== "Received" && <span style={{ ...ui.tag, background: "#de0b12", color: "#fff" }}>Urgent</span>}
            </h2>
            {order && (
              <p style={ui.sub}>
                {order.branch} · {order.supplier.name} ({order.supplier.email}{order.supplier.phone ? `, ${order.supplier.phone}` : ""})
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} style={ui.close} aria-label="Close">&times;</button>
        </div>
        {error && <div style={ui.errorBox}>{error}</div>}
        {notice && <div style={ui.successBox} role="status">{notice}</div>}
        {!order && !error && <p style={ui.muted}>Loading...</p>}

        {order && (
          <>
            <ol style={styles.timeline}>
              <Step done>Requested by {order.requestedBy} · {order.createdAt}{order.neededBy ? ` · needed by ${formatDay(order.neededBy)}` : ""}</Step>
              {order.status === "Pending approval" && <Step waiting>Waiting for the General Manager (orders of this size need approval)</Step>}
              {order.autoApproved && <Step done>Approved automatically (under the approval limit)</Step>}
              {order.approvedBy && <Step done>Approved by {order.approvedBy} · {order.approvedAt}</Step>}
              {order.status === "Rejected" && <Step bad>Rejected by {order.rejectedBy}: {order.rejectionReason}</Step>}
              {order.sentAt && <Step done>Emailed to {order.supplier.name} · {order.sentAt}</Step>}
              {order.sendError && (
                <Step bad>
                  Couldn&apos;t email the supplier ({order.sendError}).{" "}
                  {order.canResend && (
                    <button type="button" onClick={() => run(() => resendOrder(order.id), "Sent again.")} style={styles.link} disabled={busy}>
                      Try again
                    </button>
                  )}
                </Step>
              )}
              {order.receipts.map((r, i) => (
                <Step key={i} done>
                  Delivery received by {r.receivedBy} · {r.receivedAt}: {r.items.map((it) => `${it.quantity} × ${it.description}`).join(", ")} ({money(r.amount)})
                  {r.note ? ` - ${r.note}` : ""}
                </Step>
              ))}
              {order.status === "Cancelled" && <Step bad>Cancelled by {order.cancelledBy}: {order.cancelReason}</Step>}
              {order.closedShort && <Step bad>Closed with items missing ({order.cancelledBy}): {order.cancelReason}</Step>}
            </ol>

            <table style={ui.table}>
              <thead>
                <tr>
                  <th style={ui.th}>Item</th>
                  <th style={ui.thRight}>Ordered</th>
                  <th style={ui.thRight}>Received</th>
                  <th style={ui.thRight}>Cost each</th>
                  <th style={ui.thRight}>Total</th>
                  {mode === "receive" && <th style={ui.thRight}>Arrived now</th>}
                </tr>
              </thead>
              <tbody>
                {order.lines.map((l) => (
                  <tr key={l.id}>
                    <td style={ui.td}>
                      {l.description}
                      {!l.productId && <span style={styles.supplyTag}>supply</span>}
                    </td>
                    <td style={ui.tdRight}>{l.quantity}</td>
                    <td style={{ ...ui.tdRight, color: l.outstanding ? "#8a5300" : "#0f6e2b" }}>{l.received}</td>
                    <td style={ui.tdRight}>{money(l.unitCost)}</td>
                    <td style={ui.tdRight}>{money(l.lineTotal)}</td>
                    {mode === "receive" && (
                      <td style={ui.tdRight}>
                        {l.outstanding ? (
                          <input
                            type="number"
                            min="0"
                            max={l.outstanding}
                            value={counts[l.id] ?? ""}
                            onChange={(e) => setCounts({ ...counts, [l.id]: e.target.value })}
                            style={{ ...ui.input, width: 80 }}
                            aria-label={`${l.description} arrived now`}
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td style={ui.td} colSpan={4}><strong>Total</strong></td>
                  <td style={{ ...ui.tdRight, fontWeight: 800 }}>{money(order.total)}</td>
                  {mode === "receive" && <td style={ui.td} />}
                </tr>
              </tfoot>
            </table>
            {order.note && <p style={ui.hint}>Note to the supplier: {order.note}</p>}

            {mode === "receive" && (
              <>
                <input value={text} onChange={(e) => setText(e.target.value)} maxLength={300} placeholder="Delivery note (optional), e.g. 2 boxes damaged" style={ui.input} aria-label="Delivery note" />
                <p style={ui.hint}>Products go onto {order.branch}&apos;s shelf, and what arrived is recorded as a branch expense (Supplies &amp; stock).</p>
                <div style={ui.actions}>
                  <button type="button" onClick={() => setMode(null)} style={ui.secondary} disabled={busy}>Back</button>
                  <button
                    type="button"
                    onClick={() =>
                      run(
                        () => receiveOrder(order.id, Object.entries(counts).map(([lineId, q]) => ({ lineId: Number(lineId), quantity: Number(q) || 0 })), text),
                        "Delivery recorded - stock and expenses updated.",
                      )
                    }
                    style={ui.green}
                    disabled={busy}
                  >
                    Confirm delivery
                  </button>
                </div>
              </>
            )}

            {(mode === "reject" || mode === "cancel" || mode === "close") && (
              <>
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={300}
                  placeholder={mode === "reject" ? "Why (the branch manager sees this)" : mode === "close" ? "Why the rest won't come" : "Why cancel"}
                  aria-label="Reason"
                  style={ui.input}
                  autoFocus
                />
                {mode === "cancel" && order.status === "Ordered" && <p style={ui.hint}>{order.supplier.name} is emailed that the order is cancelled.</p>}
                <div style={ui.actions}>
                  <button type="button" onClick={() => setMode(null)} style={ui.secondary} disabled={busy}>Back</button>
                  <button
                    type="button"
                    disabled={busy || !text.trim()}
                    style={ui.danger}
                    onClick={() =>
                      run(
                        () => (mode === "reject" ? rejectOrder(order.id, text) : mode === "close" ? closeOrder(order.id, text) : cancelOrder(order.id, text)),
                        mode === "reject" ? "Rejected - the branch was told." : mode === "close" ? "Order closed." : "Order cancelled.",
                      )
                    }
                  >
                    {mode === "reject" ? "Reject order" : mode === "close" ? "Close order" : "Cancel order"}
                  </button>
                </div>
              </>
            )}

            {!mode && (
              <div style={ui.actions}>
                {order.canCancel && <button type="button" onClick={() => setMode("cancel")} style={ui.secondary}>Cancel order</button>}
                {order.canClose && <button type="button" onClick={() => setMode("close")} style={ui.secondary}>Close - rest won&apos;t come</button>}
                {order.canResend && order.sentAt && (
                  <button type="button" onClick={() => run(() => resendOrder(order.id), "Sent to the supplier again.")} style={ui.secondary} disabled={busy}>
                    Email again
                  </button>
                )}
                {order.canApprove && (
                  <>
                    <button type="button" onClick={() => setMode("reject")} style={ui.danger}>Reject</button>
                    <button type="button" onClick={() => run(() => approveOrder(order.id), "Approved and sent to the supplier.")} style={ui.green} disabled={busy}>
                      Approve {money(order.total)}
                    </button>
                  </>
                )}
                {order.canReceive && <button type="button" onClick={startReceiving} style={ui.green}>Record a delivery</button>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Step({ done, waiting, bad, children }) {
  const color = bad ? "#b3261e" : waiting ? "#8a5300" : done ? "#0f6e2b" : "#777";
  return (
    <li style={styles.step}>
      <span style={{ ...styles.dot, background: color }} />
      <span style={{ color: bad ? "#b3261e" : "#333" }}>{children}</span>
    </li>
  );
}

const styles = {
  timeline: { listStyle: "none", margin: 0, padding: "10px 12px", background: "#fafafb", borderRadius: 10, display: "flex", flexDirection: "column", gap: 6 },
  step: { display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, lineHeight: 1.4 },
  dot: { flexShrink: 0, width: 8, height: 8, borderRadius: 999, marginTop: 5 },
  link: { border: "none", background: "none", color: "#124096", fontWeight: 700, cursor: "pointer", padding: 0, fontSize: 13 },
  supplyTag: { marginLeft: 6, fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "#ececf0", color: "#555" },
};

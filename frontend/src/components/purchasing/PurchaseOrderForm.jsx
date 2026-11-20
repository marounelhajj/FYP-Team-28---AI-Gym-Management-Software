import { useState } from "react";
import { placeOrder } from "../../api/purchasing.js";
import { addDays, formatDay, localToday, money, ui } from "./shared.js";

// A new order to one supplier: catalog products (their cost comes from the
// product's sourcing and can be changed) and/or other supplies typed in.
// Shows as you go whether it goes straight to the supplier or to the General
// Manager first; the server decides for real.

const OTHER = "other";

function lineFrom(product) {
  return { productId: String(product.id), description: "", quantity: String(product.suggested || 1), unitCost: product.unitCost || "" };
}

export default function PurchaseOrderForm({ meta, start, onClose, onPlaced }) {
  const active = meta.suppliers.filter((s) => s.active);
  const [supplierId, setSupplierId] = useState(String(start?.supplierId || active[0]?.id || ""));
  const [lines, setLines] = useState(start?.products?.length ? start.products.map(lineFrom) : [{ productId: OTHER, description: "", quantity: "1", unitCost: "" }]);
  const [neededBy, setNeededBy] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const supplier = active.find((s) => String(s.id) === supplierId);
  const products = meta.products;
  const theirs = products.filter((p) => String(p.supplierId) === supplierId);
  const others = products.filter((p) => String(p.supplierId) !== supplierId);
  const total = lines.reduce((sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unitCost) || 0), 0);
  const needsApproval = total >= Number(meta.approvalLimit);
  const rush = supplier && neededBy && neededBy < addDays(localToday(), supplier.leadTimeDays);

  function setLine(i, field, value) {
    setLines((current) =>
      current.map((line, j) => {
        if (j !== i) return line;
        const next = { ...line, [field]: value };
        if (field === "productId" && value !== OTHER) {
          const product = products.find((p) => String(p.id) === value);
          next.unitCost = product?.unitCost || "";
          next.description = "";
        }
        return next;
      }),
    );
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    try {
      const order = await placeOrder({
        branch: meta.branch,
        supplierId: Number(supplierId),
        neededBy: neededBy || null,
        note,
        lines: lines.map((l) => ({
          productId: l.productId === OTHER ? null : Number(l.productId),
          description: l.productId === OTHER ? l.description : "",
          quantity: Number(l.quantity),
          unitCost: l.unitCost === "" ? null : l.unitCost,
        })),
      });
      onPlaced(order);
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const lineErrors = errors.lines && !Array.isArray(errors.lines) ? errors.lines : {};
  const listError = Array.isArray(errors.lines) ? errors.lines[0] : null;
  const rowError = (i) => {
    const e = lineErrors[i] || lineErrors[String(i)];
    return e ? Object.values(e)[0]?.[0] : null;
  };

  return (
    <div style={ui.overlay} onClick={onClose}>
      <form style={ui.modal} onClick={(e) => e.stopPropagation()} onSubmit={submit} role="dialog" aria-label="New supply order">
        <div style={ui.head}>
          <div>
            <h2 style={ui.title}>New supply order · {meta.branch}</h2>
            <p style={ui.sub}>One order goes to one supplier. Prices are what the gym pays, not the shelf price.</p>
          </div>
          <button type="button" onClick={onClose} style={ui.close} aria-label="Close">&times;</button>
        </div>
        {error && <div style={ui.errorBox}>{error}</div>}

        <label style={ui.field}>
          <span style={ui.label}>Supplier</span>
          <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} style={ui.input} aria-label="Supplier">
            {active.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}{s.supplies ? ` - ${s.supplies}` : ""}
              </option>
            ))}
          </select>
          {supplier && (
            <span style={ui.hint}>
              Orders go to {supplier.email}
              {supplier.phone ? ` · ${supplier.phone}` : ""} · usually delivers in {supplier.leadTimeDays} day{supplier.leadTimeDays === 1 ? "" : "s"}
            </span>
          )}
          {errors.supplierId && <span style={ui.fieldError}>{errors.supplierId[0]}</span>}
        </label>

        <div style={ui.label}>Items</div>
        <table style={ui.table}>
          <thead>
            <tr>
              <th style={ui.th}>Item</th>
              <th style={{ ...ui.th, width: 80 }}>Qty</th>
              <th style={{ ...ui.th, width: 110 }}>Cost each ($)</th>
              <th style={{ ...ui.thRight, width: 90 }}>Total</th>
              <th style={{ ...ui.th, width: 28 }} />
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => (
              <tr key={i}>
                <td style={ui.td}>
                  <select value={line.productId} onChange={(e) => setLine(i, "productId", e.target.value)} style={ui.input} aria-label={`Item ${i + 1}`}>
                    {theirs.length > 0 && (
                      <optgroup label={`From ${supplier?.name}`}>
                        {theirs.map((p) => (
                          <option key={p.id} value={p.id}>{p.name} ({p.inStock} in stock{p.low ? ", low" : ""})</option>
                        ))}
                      </optgroup>
                    )}
                    <optgroup label="Other catalog products">
                      {others.map((p) => (
                        <option key={p.id} value={p.id}>{p.name} ({p.inStock} in stock)</option>
                      ))}
                    </optgroup>
                    <option value={OTHER}>Something not sold (type it)...</option>
                  </select>
                  {line.productId === OTHER && (
                    <input
                      value={line.description}
                      onChange={(e) => setLine(i, "description", e.target.value)}
                      maxLength={120}
                      placeholder="e.g. Disinfectant spray 5 L"
                      aria-label={`Description of item ${i + 1}`}
                      style={{ ...ui.input, marginTop: 4 }}
                    />
                  )}
                  {rowError(i) && <div style={ui.fieldError}>{rowError(i)}</div>}
                </td>
                <td style={ui.td}>
                  <input type="number" min="1" value={line.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} style={ui.input} aria-label={`Quantity of item ${i + 1}`} />
                </td>
                <td style={ui.td}>
                  <input type="number" min="0" step="0.01" value={line.unitCost} onChange={(e) => setLine(i, "unitCost", e.target.value)} style={ui.input} aria-label={`Cost of item ${i + 1}`} />
                </td>
                <td style={ui.tdRight}>{money((Number(line.quantity) || 0) * (Number(line.unitCost) || 0))}</td>
                <td style={ui.td}>
                  {lines.length > 1 && (
                    <button type="button" onClick={() => setLines(lines.filter((_, j) => j !== i))} style={ui.close} aria-label={`Remove item ${i + 1}`}>
                      &times;
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td style={ui.td}>
                <button type="button" onClick={() => setLines([...lines, { productId: OTHER, description: "", quantity: "1", unitCost: "" }])} style={ui.secondary}>
                  + Add item
                </button>
              </td>
              <td style={ui.td} colSpan={2}><strong>Order total</strong></td>
              <td style={{ ...ui.tdRight, fontWeight: 800, fontSize: 15 }}>{money(total)}</td>
              <td style={ui.td} />
            </tr>
          </tfoot>
        </table>
        {listError && <div style={ui.errorBox}>{listError}</div>}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <label style={{ ...ui.field, flex: "0 0 180px" }}>
            <span style={ui.label}>Needed by (optional)</span>
            <input type="date" min={localToday()} value={neededBy} onChange={(e) => setNeededBy(e.target.value)} style={ui.input} />
            {errors.neededBy && <span style={ui.fieldError}>{errors.neededBy[0]}</span>}
          </label>
          <label style={{ ...ui.field, flex: 1 }}>
            <span style={ui.label}>Note for the supplier (optional)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="e.g. Deliver before 10 am" style={ui.input} />
          </label>
        </div>
        {rush && (
          <div style={ui.warnBox}>
            {supplier.name} usually needs {supplier.leadTimeDays} day{supplier.leadTimeDays === 1 ? "" : "s"} - {formatDay(neededBy)} may be too soon. The order will be marked urgent.
          </div>
        )}
        {needsApproval ? (
          <div style={ui.warnBox}>
            {money(total)} is {money(meta.approvalLimit)} or more, so the General Manager approves it first. You&apos;ll be notified, and it goes to the supplier once approved.
          </div>
        ) : (
          <div style={ui.infoBox}>Under {money(meta.approvalLimit)}: it&apos;s emailed to {supplier?.name || "the supplier"} as soon as you place it.</div>
        )}
        <div style={ui.actions}>
          <button type="button" onClick={onClose} style={ui.secondary} disabled={busy}>Cancel</button>
          <button type="submit" style={ui.primary} disabled={busy || !supplierId}>
            {busy ? "Placing..." : needsApproval ? "Send for approval" : "Place order"}
          </button>
        </div>
      </form>
    </div>
  );
}

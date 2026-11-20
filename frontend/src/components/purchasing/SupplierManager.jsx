import { useState } from "react";
import { addSupplier, updateSourcing, updateSupplier } from "../../api/purchasing.js";
import { money, ui } from "./shared.js";

// Head office's side: the supplier list (companies the gym buys from - they
// don't log in, they receive purchase orders by email) and, for each product
// the front desk sells, who it's bought from, what it costs, and when a
// branch should reorder it.

const EMPTY = { name: "", contactName: "", email: "", phone: "", supplies: "", leadTimeDays: "3" };

export function SupplierList({ suppliers, onChanged }) {
  const [form, setForm] = useState(null); // { id?, ...fields }
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setError(null);
    const { id, ...fields } = form;
    try {
      const body = { ...fields, leadTimeDays: Number(fields.leadTimeDays) || 0 };
      await (id ? updateSupplier(id, body) : addSupplier(body));
      setForm(null);
      onChanged(id ? "Supplier saved." : "Supplier added.");
    } catch (err) {
      if (err.fieldErrors) setErrors(err.fieldErrors);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggle(s) {
    try {
      await updateSupplier(s.id, { active: !s.active });
      onChanged(s.active ? `${s.name} won't be offered for new orders.` : `${s.name} is back in use.`);
    } catch (err) {
      setError(err.message);
    }
  }

  const set = (f) => (e) => setForm({ ...form, [f]: e.target.value });
  const fieldError = (f) => errors[f] && <span style={ui.fieldError}>{errors[f][0]}</span>;
  return (
    <div style={styles.panel}>
      <div style={styles.panelHead}>
        <h2 style={styles.panelTitle}>Suppliers</h2>
        {!form && <button type="button" onClick={() => setForm({ ...EMPTY })} style={ui.primary}>+ Add supplier</button>}
      </div>
      <p style={ui.hint}>Suppliers don&apos;t use the app: purchase orders are emailed to them, and branch managers record deliveries.</p>
      {error && <div style={ui.errorBox}>{error}</div>}
      {form && (
        <form onSubmit={save} style={styles.form} aria-label="Supplier">
          <div style={styles.grid}>
            <label style={ui.field}><span style={ui.label}>Company</span><input value={form.name} onChange={set("name")} maxLength={120} style={ui.input} />{fieldError("name")}</label>
            <label style={ui.field}><span style={ui.label}>Contact person</span><input value={form.contactName} onChange={set("contactName")} maxLength={120} style={ui.input} /></label>
            <label style={ui.field}><span style={ui.label}>Email for orders</span><input type="email" value={form.email} onChange={set("email")} style={ui.input} />{fieldError("email")}</label>
            <label style={ui.field}><span style={ui.label}>Phone</span><input value={form.phone} onChange={set("phone")} maxLength={40} style={ui.input} /></label>
            <label style={ui.field}><span style={ui.label}>What they supply</span><input value={form.supplies} onChange={set("supplies")} maxLength={300} placeholder="e.g. Cleaning products, towels" style={ui.input} /></label>
            <label style={ui.field}><span style={ui.label}>Usual delivery (days)</span><input type="number" min="0" max="90" value={form.leadTimeDays} onChange={set("leadTimeDays")} style={ui.input} />{fieldError("leadTimeDays")}</label>
          </div>
          <div style={ui.actions}>
            <button type="button" onClick={() => setForm(null)} style={ui.secondary} disabled={busy}>Cancel</button>
            <button type="submit" style={ui.primary} disabled={busy}>{busy ? "Saving..." : "Save supplier"}</button>
          </div>
        </form>
      )}
      <table style={ui.table}>
        <thead>
          <tr>
            <th style={ui.th}>Company</th>
            <th style={ui.th}>Contact</th>
            <th style={ui.th}>Supplies</th>
            <th style={ui.thRight}>Delivery</th>
            <th style={ui.th} />
          </tr>
        </thead>
        <tbody>
          {suppliers.map((s) => (
            <tr key={s.id} style={s.active ? null : { color: "#999" }}>
              <td style={ui.td}><strong>{s.name}</strong>{!s.active && " (not in use)"}</td>
              <td style={ui.td}>{s.contactName && `${s.contactName} · `}{s.email}{s.phone && ` · ${s.phone}`}</td>
              <td style={ui.td}>{s.supplies}</td>
              <td style={ui.tdRight}>{s.leadTimeDays} d</td>
              <td style={ui.tdRight}>
                <button type="button" onClick={() => setForm({ ...s, leadTimeDays: String(s.leadTimeDays) })} style={styles.small}>Edit</button>{" "}
                <button type="button" onClick={() => toggle(s)} style={styles.small}>{s.active ? "Stop using" : "Use again"}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SourcingList({ products, suppliers, onChanged }) {
  const [drafts, setDrafts] = useState({});
  const [error, setError] = useState(null);
  const active = suppliers.filter((s) => s.active);

  function draft(p) {
    return drafts[p.id] || { supplierId: p.supplierId ? String(p.supplierId) : "", unitCost: p.unitCost || "", reorderLevel: String(p.reorderLevel) };
  }

  async function save(p) {
    const d = draft(p);
    setError(null);
    try {
      await updateSourcing(p.id, {
        supplierId: d.supplierId ? Number(d.supplierId) : null,
        unitCost: d.unitCost === "" ? null : d.unitCost,
        reorderLevel: Number(d.reorderLevel) || 0,
      });
      setDrafts((all) => {
        const next = { ...all };
        delete next[p.id];
        return next;
      });
      onChanged(`${p.name} saved.`);
    } catch (err) {
      setError(err.fieldErrors ? Object.values(err.fieldErrors)[0][0] : err.message);
    }
  }

  return (
    <div style={styles.panel}>
      <h2 style={styles.panelTitle}>Products &amp; reorder levels</h2>
      <p style={ui.hint}>
        The usual supplier and cost fill in a new order. A branch with this many or fewer on the shelf (counting what&apos;s already on order) is
        told to reorder; 0 = never.
      </p>
      {error && <div style={ui.errorBox}>{error}</div>}
      <table style={ui.table}>
        <thead>
          <tr>
            <th style={ui.th}>Product</th>
            <th style={ui.th}>Usual supplier</th>
            <th style={ui.th}>Cost each ($)</th>
            <th style={ui.th}>Reorder at</th>
            <th style={ui.th} />
          </tr>
        </thead>
        <tbody>
          {products.map((p) => {
            const d = draft(p);
            const set = (f) => (e) => setDrafts({ ...drafts, [p.id]: { ...d, [f]: e.target.value } });
            return (
              <tr key={p.id}>
                <td style={ui.td}>
                  <strong>{p.name}</strong>
                  <div style={ui.hint}>Sells for {money(p.price)}</div>
                </td>
                <td style={ui.td}>
                  <select value={d.supplierId} onChange={set("supplierId")} style={ui.input} aria-label={`Supplier for ${p.name}`}>
                    <option value="">—</option>
                    {active.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </td>
                <td style={ui.td}><input type="number" min="0" step="0.01" value={d.unitCost} onChange={set("unitCost")} style={{ ...ui.input, width: 100 }} aria-label={`Cost of ${p.name}`} /></td>
                <td style={ui.td}><input type="number" min="0" value={d.reorderLevel} onChange={set("reorderLevel")} style={{ ...ui.input, width: 80 }} aria-label={`Reorder level of ${p.name}`} /></td>
                <td style={ui.tdRight}>
                  {drafts[p.id] && <button type="button" onClick={() => save(p)} style={styles.small}>Save</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const styles = {
  panel: { padding: 16, border: "1px solid #e4e4e8", borderRadius: 12, background: "#fff", display: "flex", flexDirection: "column", gap: 10 },
  panelHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 },
  panelTitle: { fontSize: 16, fontWeight: 800, margin: 0 },
  form: { display: "flex", flexDirection: "column", gap: 10, padding: 12, border: "1px solid #dfe5f2", borderRadius: 10, background: "#f7f9fd" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 },
  small: { padding: "5px 10px", fontSize: 12, fontWeight: 600, border: "1px solid #d0d0d5", borderRadius: 6, background: "#f5f5f7", cursor: "pointer" },
};

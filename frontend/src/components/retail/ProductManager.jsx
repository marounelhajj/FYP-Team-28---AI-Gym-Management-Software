import { useCallback, useEffect, useState } from "react";
import { adjustStock, createProduct, fetchProducts, fetchRetailMeta, updateProduct } from "../../api/retail.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import SegmentedControl from "../SegmentedControl.jsx";

const LOW_STOCK = 3;

// The shop catalog behind the Shop till (PointOfSale.jsx): what's for sale,
// at what price, and how many are on each branch's shelf. Gated on
// manage_retail_products. A General Manager handles every branch; a Branch
// Manager only receives or corrects stock at their own (the server enforces
// the same rule - see backend/retail/views.py).
//
// User story: "As a receptionist, I want to process point-of-sale purchases
// for retail items (protein, water bottles, merchandise), so that I can
// handle in-person retail sales." (the catalog the till sells from)
export default function ProductManager() {
  const [meta, setMeta] = useState(null);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState(null); // {} for a new product, or the product
  const [stockTarget, setStockTarget] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    setError(null);
    return fetchProducts({ includeArchived: true })
      .then((data) => setProducts(data.results))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchRetailMeta()
      .then(setMeta)
      .catch((err) => setError(err.message));
    load();
  }, [load]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  async function toggleArchived(product) {
    try {
      await updateProduct(product.id, { isActive: !product.isActive });
      setNotice(product.isActive ? `${product.name} archived - it's off the till.` : `${product.name} is back on the till.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (!meta) {
    return <div style={styles.page}>{error ? <div style={styles.errorBox}>{error}</div> : "Loading..."}</div>;
  }

  const branches = meta.branches;
  const visible = products.filter(
    (p) => (showArchived || p.isActive) && p.name.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const lowStock = products.filter(
    (p) => p.isActive && meta.manageableBranches.some((b) => (p.stock[b] ?? 0) <= LOW_STOCK),
  ).length;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Retail Products</h1>
          <p style={styles.subtitle}>
            What the front desk sells, its price, and the stock on each branch's shelf.
            {meta.manageableBranches.length < branches.length &&
              ` You can change stock at ${meta.manageableBranches.join(", ")}.`}
          </p>
        </div>
        <button type="button" onClick={() => setEditing({})} style={styles.addButton}>
          Add product
        </button>
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}
      {lowStock > 0 && (
        <div style={styles.warnBox}>
          {lowStock} product{lowStock === 1 ? " is" : "s are"} running low ({LOW_STOCK} or fewer) at your branch
          {meta.manageableBranches.length === 1 ? "" : "es"}.
        </div>
      )}

      <div style={styles.filters}>
        <input
          type="search"
          placeholder="Search products"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ ...styles.input, maxWidth: 280 }}
          aria-label="Search products"
        />
        <label style={styles.checkbox}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Show archived
        </label>
      </div>

      {!loading && visible.length === 0 && <div style={styles.empty}>No products yet.</div>}

      {visible.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Product</th>
                <th style={styles.th}>Category</th>
                <th style={styles.th}>Price</th>
                {branches.map((b) => (
                  <th key={b} style={{ ...styles.th, textAlign: "center" }}>
                    {b}
                  </th>
                ))}
                <th style={styles.th} />
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id} style={p.isActive ? null : styles.archivedRow}>
                  <td style={{ ...styles.td, fontWeight: 600 }}>
                    {p.name}
                    {!p.isActive && <span style={styles.archivedTag}>Archived</span>}
                  </td>
                  <td style={styles.td}>{p.category}</td>
                  <td style={{ ...styles.td, fontWeight: 600 }}>${p.price}</td>
                  {branches.map((b) => {
                    const qty = p.stock[b] ?? 0;
                    const tone = !p.isActive ? null : qty === 0 ? styles.out : qty <= LOW_STOCK ? styles.low : null;
                    return (
                      <td key={b} style={{ ...styles.td, textAlign: "center", ...tone }}>
                        {qty}
                      </td>
                    );
                  })}
                  <td style={{ ...styles.td, whiteSpace: "nowrap", textAlign: "right" }}>
                    <button type="button" onClick={() => setStockTarget(p)} style={styles.rowButton}>
                      Stock
                    </button>
                    <button type="button" onClick={() => setEditing(p)} style={styles.rowButton}>
                      Edit
                    </button>
                    <button type="button" onClick={() => toggleArchived(p)} style={styles.rowButton}>
                      {p.isActive ? "Archive" : "Restore"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <ProductForm
          product={editing.id ? editing : null}
          categories={meta.categories}
          onClose={() => setEditing(null)}
          onSaved={(product, isNew) => {
            setEditing(null);
            setNotice(isNew ? `${product.name} added - receive its first delivery with "Stock".` : `${product.name} saved.`);
            load();
          }}
        />
      )}
      {stockTarget && (
        <StockForm
          product={stockTarget}
          branches={meta.manageableBranches}
          onClose={() => setStockTarget(null)}
          onSaved={(product, branch) => {
            setStockTarget(null);
            setNotice(`${product.name}: ${product.stock[branch]} now on the shelf at ${branch}.`);
            load();
          }}
        />
      )}
    </div>
  );
}

function ProductForm({ product, categories, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: product?.name || "",
    category: product?.category || "",
    price: product?.price || "",
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFieldErrors({});
    setError(null);
    try {
      const saved = product ? await updateProduct(product.id, form) : await createProduct(form);
      onSaved(saved, !product);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
      setSaving(false);
    }
  }

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  return (
    <Modal title={product ? `Edit ${product.name}` : "Add Product"} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Name" error={fieldErrors.name}>
          <input value={form.name} onChange={(e) => update("name", e.target.value)} style={styles.input} autoFocus />
        </Field>
        <Field label="Category" error={fieldErrors.category}>
          <select value={form.category} onChange={(e) => update("category", e.target.value)} style={styles.input}>
            <option value="">Choose a category</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Price ($)" error={fieldErrors.price}>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={form.price}
            onChange={(e) => update("price", e.target.value)}
            style={styles.input}
          />
        </Field>
        {product && <p style={styles.hint}>A new price applies to sales from now on - past receipts keep the old one.</p>}
        {error && <div style={styles.errorBox}>{error}</div>}
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.cancelButton}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || !form.name.trim() || !form.category || !form.price}
            style={styles.submitButton}
          >
            {saving ? "Saving..." : product ? "Save changes" : "Add product"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function StockForm({ product, branches, onClose, onSaved }) {
  const [branch, setBranch] = useState(branches[0] || "");
  const [mode, setMode] = useState("receive");
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const current = product.stock[branch] ?? 0;
  const amount = parseInt(quantity, 10) || 0;
  const after = mode === "receive" ? current + amount : current - amount;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFieldErrors({});
    setError(null);
    try {
      const saved = await adjustStock(product.id, { branch, change: mode === "receive" ? amount : -amount, note });
      onSaved(saved, branch);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
      setSaving(false);
    }
  }

  return (
    <Modal title={`Stock: ${product.name}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Branch" error={fieldErrors.branch}>
          <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.input}>
            {branches.map((b) => (
              <option key={b} value={b}>
                {b} ({product.stock[b] ?? 0} on the shelf)
              </option>
            ))}
          </select>
        </Field>
        <div style={styles.field}>
          <SegmentedControl
            ariaLabel="Stock change"
            options={[
              { value: "receive", label: "Receive delivery" },
              { value: "remove", label: "Remove" },
            ]}
            value={mode}
            onChange={setMode}
          />
        </div>
        <Field label={mode === "receive" ? "Units received" : "Units to remove (damaged, expired, miscounted)"} error={fieldErrors.change}>
          <input
            type="number"
            min="1"
            max="999"
            step="1"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            style={styles.input}
            autoFocus
          />
        </Field>
        <Field label="Note (optional)" error={fieldErrors.note}>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={mode === "receive" ? "e.g. Supplier invoice #1042" : "e.g. 2 tubs damaged"}
            style={styles.input}
          />
        </Field>
        {amount > 0 && (
          <p style={after < 0 ? { ...styles.hint, color: "#b3261e" } : styles.hint}>
            {after < 0 ? `Only ${current} on the shelf at ${branch}.` : `${current} → ${after} on the shelf at ${branch}.`}
          </p>
        )}
        {error && <div style={styles.errorBox}>{error}</div>}
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.cancelButton}>
            Cancel
          </button>
          <button type="submit" disabled={saving || amount < 1 || after < 0 || !branch} style={styles.submitButton}>
            {saving ? "Saving..." : mode === "receive" ? "Add to stock" : "Remove from stock"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{title}</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.label}>{label}</label>
      {children}
      {message && <div style={styles.fieldError}>{message}</div>}
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1100,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  addButton: {
    flexShrink: 0,
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  warnBox: { background: "#fff7e0", color: "#7a5600", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  filters: { display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 14 },
  checkbox: { display: "flex", alignItems: "center", gap: 6, fontSize: 14, color: "#444" },
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 820, borderCollapse: "collapse", fontSize: 14 },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: "#666",
    borderBottom: "1px solid #e4e4e8",
    background: "#fafafb",
    whiteSpace: "nowrap",
  },
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "middle" },
  low: { color: "#a15c00", fontWeight: 700, background: "#fff7e0" },
  out: { color: "#b3261e", fontWeight: 700, background: "#fdeceb" },
  archivedRow: { color: "#999", background: "#fafafa" },
  archivedTag: {
    marginLeft: 8,
    padding: "2px 6px",
    borderRadius: 4,
    background: "#ececf0",
    color: "#666",
    fontSize: 11,
    fontWeight: 700,
  },
  rowButton: {
    padding: "5px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    color: "#333",
    cursor: "pointer",
    marginLeft: 6,
  },
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 440,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  field: { marginBottom: 14 },
  label: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
  input: {
    width: "100%",
    padding: "10px 12px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
  },
  hint: { fontSize: 13, color: "#555", margin: "0 0 10px" },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 },
  cancelButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  submitButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
};

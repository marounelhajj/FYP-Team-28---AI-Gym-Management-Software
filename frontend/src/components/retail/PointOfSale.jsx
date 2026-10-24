import { useCallback, useEffect, useMemo, useState } from "react";
import { createSale, fetchProducts, fetchRetailMeta, fetchSales, lookupMember, voidSale } from "../../api/retail.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import QrScanner from "../QrScanner.jsx";
import SegmentedControl from "../SegmentedControl.jsx";

const MAX_PER_PRODUCT = 99;
const BRANCH_KEY = "fitnessFactory.posBranch";

// User story: "As a receptionist, I want to process point-of-sale purchases
// for retail items (protein, water bottles, merchandise), so that I can
// handle in-person retail sales."
//
// The till only ever sends product IDs and quantities - the server prices
// the basket from the catalog and takes the stock off the branch's shelf
// (see backend/retail/views.py). The total shown here goes along as
// expectedTotal, so if a manager re-priced something while the basket was
// open the sale is refused instead of charging a different amount.

const toCents = (amount) => Math.round(Number(amount) * 100);
const money = (cents) => `$${(cents / 100).toFixed(2)}`;
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function savedBranch() {
  try {
    return localStorage.getItem(BRANCH_KEY) || "";
  } catch {
    return "";
  }
}

// Round-number notes a customer is likely to hand over, above the total.
function cashSuggestions(totalCents) {
  const steps = [500, 1000, 2000, 5000, 10000];
  const values = new Set(steps.map((s) => Math.ceil(totalCents / s) * s).filter((v) => v > totalCents));
  return [...values].sort((a, b) => a - b).slice(0, 3);
}

export default function PointOfSale() {
  const [meta, setMeta] = useState(null);
  const [branch, setBranch] = useState("");
  const [products, setProducts] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");

  // { productId: quantity }, in the order items were added.
  const [basket, setBasket] = useState({});
  const [member, setMember] = useState(null);
  const [memberCode, setMemberCode] = useState("");
  const [memberError, setMemberError] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [method, setMethod] = useState("Cash");
  const [tendered, setTendered] = useState("");
  const [charging, setCharging] = useState(false);
  const [saleError, setSaleError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [receipt, setReceipt] = useState(null);

  const [day, setDay] = useState(today());
  const [sales, setSales] = useState(null);
  const [salesError, setSalesError] = useState(null);
  const [voidTarget, setVoidTarget] = useState(null);

  useEffect(() => {
    fetchRetailMeta()
      .then((m) => {
        setMeta(m);
        const remembered = savedBranch();
        setBranch(m.fixedBranch || (m.branches.includes(remembered) ? remembered : ""));
      })
      .catch((err) => setLoadError(err.message));
  }, []);

  const loadProducts = useCallback(() => {
    return fetchProducts()
      .then((data) => {
        setProducts(data.results);
        return data.results;
      })
      .catch((err) => {
        setLoadError(err.message);
        return null;
      });
  }, []);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const loadSales = useCallback(() => {
    if (!meta) return;
    setSalesError(null);
    fetchSales({ date: day, branch: branch || undefined })
      .then(setSales)
      .catch((err) => setSalesError(err.message));
  }, [meta, day, branch]);

  useEffect(() => {
    loadSales();
  }, [loadSales]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  function chooseBranch(value) {
    setBranch(value);
    setSaleError(null);
    try {
      localStorage.setItem(BRANCH_KEY, value);
    } catch {
      // Remembering the branch is only a convenience.
    }
  }

  const byId = useMemo(() => Object.fromEntries(products.map((p) => [p.id, p])), [products]);
  const inStock = (product) => (branch ? product.stock[branch] ?? 0 : 0);

  const lines = Object.entries(basket)
    .map(([id, quantity]) => ({ product: byId[id], quantity }))
    .filter((line) => line.product);
  const totalCents = lines.reduce((sum, l) => sum + toCents(l.product.price) * l.quantity, 0);
  const itemCount = lines.reduce((sum, l) => sum + l.quantity, 0);
  const tenderedCents = tendered === "" ? null : toCents(tendered);
  const changeCents = tenderedCents === null ? null : tenderedCents - totalCents;
  const cashShort = method === "Cash" && (tenderedCents === null || changeCents < 0);

  const visible = products.filter(
    (p) =>
      (category === "All" || p.category === category) &&
      p.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  function setQuantity(productId, quantity) {
    setSaleError(null);
    setBasket((b) => {
      const next = { ...b };
      if (quantity <= 0) delete next[productId];
      else next[productId] = quantity;
      return next;
    });
  }

  function add(product) {
    const current = basket[product.id] || 0;
    if (current >= Math.min(inStock(product), MAX_PER_PRODUCT)) return;
    setQuantity(product.id, current + 1);
  }

  function clearSale() {
    setBasket({});
    setMember(null);
    setMemberCode("");
    setMemberError(null);
    setTendered("");
    setMethod("Cash");
    setSaleError(null);
  }

  async function findMember(code) {
    const value = (code ?? memberCode).trim();
    if (!value) return;
    setMemberError(null);
    try {
      setMember(await lookupMember(value));
      setMemberCode("");
    } catch (err) {
      setMemberError(err.message);
    }
  }

  const handleScan = useCallback((code) => {
    setScanning(false);
    findMember(code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function charge() {
    setCharging(true);
    setSaleError(null);
    try {
      const sale = await createSale({
        branch: meta.fixedBranch ? undefined : branch,
        items: lines.map((l) => ({ productId: l.product.id, quantity: l.quantity })),
        paymentMethod: method,
        amountTendered: method === "Cash" ? (tenderedCents / 100).toFixed(2) : undefined,
        memberId: member?.id,
        expectedTotal: (totalCents / 100).toFixed(2),
      });
      setReceipt(sale);
      clearSale();
      loadProducts();
      if (day === today()) loadSales();
      else setDay(today());
    } catch (err) {
      if (err.conflict) {
        // A price changed: show the new prices and let the receptionist charge again.
        const fresh = await loadProducts();
        if (fresh) {
          const stillSold = new Set(fresh.map((p) => String(p.id)));
          setBasket((b) => Object.fromEntries(Object.entries(b).filter(([id]) => stillSold.has(id))));
        }
        setSaleError(err.message);
      } else if (err.fieldErrors) {
        setSaleError(Object.values(err.fieldErrors).flat().join(" "));
        loadProducts();
      } else {
        setSaleError(err.message);
      }
    } finally {
      setCharging(false);
    }
  }

  if (loadError && !meta) {
    return (
      <div style={styles.page}>
        <div style={styles.errorBox}>Couldn't open the till: {loadError}</div>
      </div>
    );
  }
  if (!meta) return <div style={styles.page}>Loading...</div>;

  const canCharge = branch && lines.length > 0 && !cashShort && !charging;
  const isToday = day === today();

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Shop</h1>
          <p style={styles.subtitle}>Ring up protein, drinks and merchandise for walk-in customers and members.</p>
        </div>
        {meta.fixedBranch ? (
          <span style={styles.branchChip}>Selling at {meta.fixedBranch}</span>
        ) : (
          <label style={styles.branchPicker}>
            <span style={styles.branchLabel}>Selling at</span>
            <select value={branch} onChange={(e) => chooseBranch(e.target.value)} style={styles.select}>
              <option value="">Choose a branch</option>
              {meta.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {loadError && <div style={styles.errorBox}>Couldn't load products: {loadError}</div>}

      <div style={styles.layout}>
        {/* ---- Products ---- */}
        <section style={styles.catalog}>
          <div style={styles.filters}>
            <input
              type="search"
              placeholder="Search products"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ ...styles.input, flex: "1 1 200px" }}
              aria-label="Search products"
            />
            <div style={styles.pills}>
              {["All", ...meta.categories].map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCategory(c)}
                  style={c === category ? { ...styles.pill, ...styles.pillActive } : styles.pill}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {!branch && <div style={styles.hintBox}>Choose the branch you're selling at to see what's on the shelf.</div>}
          {products.length === 0 && <div style={styles.empty}>No products yet - a manager adds them under Retail Products.</div>}
          {products.length > 0 && visible.length === 0 && <div style={styles.empty}>No products match.</div>}

          <div style={styles.grid}>
            {visible.map((p) => {
              const stock = inStock(p);
              const inBasket = basket[p.id] || 0;
              const soldOut = stock === 0;
              const maxed = inBasket >= Math.min(stock, MAX_PER_PRODUCT);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => add(p)}
                  disabled={!branch || maxed}
                  style={{ ...styles.tile, ...(soldOut || !branch ? styles.tileDisabled : null) }}
                  aria-label={`Add ${p.name}`}
                >
                  <span style={styles.tileCategory}>{p.category}</span>
                  <span style={styles.tileName}>{p.name}</span>
                  <span style={styles.tileFooter}>
                    <span style={styles.tilePrice}>${p.price}</span>
                    {branch && (
                      <span style={soldOut ? styles.soldOut : stock <= 3 ? styles.lowStock : styles.stock}>
                        {soldOut ? "Out of stock" : `${stock - inBasket} left`}
                      </span>
                    )}
                  </span>
                  {inBasket > 0 && <span style={styles.badge}>{inBasket}</span>}
                </button>
              );
            })}
          </div>
        </section>

        {/* ---- Basket ---- */}
        <aside style={styles.basket}>
          <div style={styles.basketHeader}>
            <h2 style={styles.basketTitle}>Current sale</h2>
            {(lines.length > 0 || member) && (
              <button type="button" onClick={clearSale} style={styles.linkButton}>
                Clear
              </button>
            )}
          </div>

          {lines.length === 0 ? (
            <div style={styles.emptyBasket}>Tap a product to add it.</div>
          ) : (
            <ul style={styles.lines}>
              {lines.map(({ product, quantity }) => {
                const max = Math.min(inStock(product), MAX_PER_PRODUCT);
                return (
                  <li key={product.id} style={styles.line}>
                    <div style={styles.lineInfo}>
                      <span style={styles.lineName}>{product.name}</span>
                      <span style={styles.lineUnit}>${product.price} each</span>
                    </div>
                    <div style={styles.stepper}>
                      <button
                        type="button"
                        onClick={() => setQuantity(product.id, quantity - 1)}
                        style={styles.stepButton}
                        aria-label={`One fewer ${product.name}`}
                      >
                        −
                      </button>
                      <span style={styles.qty}>{quantity}</span>
                      <button
                        type="button"
                        onClick={() => setQuantity(product.id, quantity + 1)}
                        disabled={quantity >= max}
                        style={styles.stepButton}
                        aria-label={`One more ${product.name}`}
                      >
                        +
                      </button>
                    </div>
                    <span style={styles.lineTotal}>{money(toCents(product.price) * quantity)}</span>
                  </li>
                );
              })}
            </ul>
          )}

          <div style={styles.totalRow}>
            <span>
              Total{itemCount > 0 && <span style={styles.muted}> · {itemCount} item{itemCount === 1 ? "" : "s"}</span>}
            </span>
            <span style={styles.total}>{money(totalCents)}</span>
          </div>

          <div style={styles.section}>
            <div style={styles.sectionLabel}>Customer (optional)</div>
            {member ? (
              <div style={styles.memberChip}>
                <span>
                  <strong>{member.name}</strong>
                  <span style={styles.muted}>
                    {" "}
                    · ID {member.id} · {member.branch}
                    {member.status !== "Active" && ` · ${member.status}`}
                  </span>
                </span>
                <button type="button" onClick={() => setMember(null)} style={styles.chipRemove} aria-label="Remove member">
                  &times;
                </button>
              </div>
            ) : (
              <>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    findMember();
                  }}
                  style={styles.memberRow}
                >
                  <input
                    value={memberCode}
                    onChange={(e) => setMemberCode(e.target.value)}
                    placeholder="Membership ID"
                    style={{ ...styles.input, flex: 1, minWidth: 0 }}
                    aria-label="Membership ID"
                  />
                  <button type="submit" disabled={!memberCode.trim()} style={styles.smallButton}>
                    Find
                  </button>
                  <button type="button" onClick={() => setScanning(true)} style={styles.smallButton}>
                    Scan card
                  </button>
                </form>
                {memberError && <div style={styles.fieldError}>{memberError}</div>}
                {!memberError && <div style={styles.muted}>Leave empty for a walk-in customer.</div>}
              </>
            )}
            {scanning && <QrScanner onScan={handleScan} onClose={() => setScanning(false)} />}
          </div>

          <div style={styles.section}>
            <div style={styles.sectionLabel}>Payment</div>
            <SegmentedControl
              ariaLabel="Payment method"
              options={[
                { value: "Cash", label: "Cash" },
                { value: "Card", label: "Card" },
              ]}
              value={method}
              onChange={(m) => {
                setMethod(m);
                setSaleError(null);
              }}
            />
            {method === "Cash" && (
              <div style={{ marginTop: 10 }}>
                <label style={styles.cashLabel}>
                  Cash received
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    inputMode="decimal"
                    value={tendered}
                    onChange={(e) => setTendered(e.target.value)}
                    style={styles.input}
                    placeholder="0.00"
                  />
                </label>
                {totalCents > 0 && (
                  <div style={styles.quickCash}>
                    <button type="button" onClick={() => setTendered((totalCents / 100).toFixed(2))} style={styles.quickButton}>
                      Exact
                    </button>
                    {cashSuggestions(totalCents).map((c) => (
                      <button key={c} type="button" onClick={() => setTendered((c / 100).toFixed(2))} style={styles.quickButton}>
                        {money(c)}
                      </button>
                    ))}
                  </div>
                )}
                {changeCents !== null && totalCents > 0 && (
                  <div style={changeCents < 0 ? styles.short : styles.change}>
                    {changeCents < 0 ? `${money(-changeCents)} short` : `Change due: ${money(changeCents)}`}
                  </div>
                )}
              </div>
            )}
            {method === "Card" && <div style={styles.muted}>Take the payment on the card terminal, then charge.</div>}
          </div>

          {saleError && <div style={styles.errorBox}>{saleError}</div>}

          <button type="button" onClick={charge} disabled={!canCharge} style={canCharge ? styles.chargeButton : styles.chargeDisabled}>
            {charging ? "Charging..." : `Charge ${money(totalCents)}`}
          </button>
        </aside>
      </div>

      {/* ---- The day's sales ---- */}
      <section style={{ marginTop: 32 }}>
        <div style={styles.salesHeader}>
          <h2 style={styles.basketTitle}>{isToday ? "Today's sales" : `Sales on ${day}`}</h2>
          <input
            type="date"
            value={day}
            max={today()}
            onChange={(e) => setDay(e.target.value || today())}
            style={{ ...styles.input, width: "auto" }}
            aria-label="Sales date"
          />
        </div>

        {salesError && <div style={styles.errorBox}>Couldn't load sales: {salesError}</div>}
        {sales && (
          <>
            <div style={styles.summary}>
              <Stat label="Sales" value={sales.summary.sales} />
              <Stat label="Takings" value={`$${sales.summary.total}`} strong />
              <Stat label="Cash" value={`$${sales.summary.cash}`} />
              <Stat label="Card" value={`$${sales.summary.card}`} />
              <Stat label="Voided" value={sales.summary.voided} />
            </div>

            {sales.results.length === 0 ? (
              <div style={styles.empty}>No sales {isToday ? "yet today" : "on this day"}.</div>
            ) : (
              <div style={styles.tableWrap}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      {["Time", "Sale", "Items", "Customer", "Paid", "Total", "Cashier", ""].map((h) => (
                        <th key={h} style={styles.th}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sales.results.map((s) => (
                      <tr key={s.id} style={s.voided ? styles.voidedRow : null}>
                        <td style={styles.td}>{s.soldAt.slice(11)}</td>
                        <td style={styles.td}>
                          #{s.id}
                          {!meta.fixedBranch && !branch && <div style={styles.muted}>{s.branch}</div>}
                        </td>
                        <td style={styles.td}>
                          {s.items.map((i) => `${i.quantity} × ${i.productName}`).join(", ")}
                          {s.voided && (
                            <div style={styles.voidNote}>
                              Voided by {s.voidedBy}: {s.voidReason}
                            </div>
                          )}
                        </td>
                        <td style={styles.td}>{s.memberName ? `${s.memberName} (ID ${s.memberId})` : "Walk-in"}</td>
                        <td style={styles.td}>{s.paymentMethod}</td>
                        <td style={{ ...styles.td, fontWeight: 600, textDecoration: s.voided ? "line-through" : "none" }}>
                          ${s.total}
                        </td>
                        <td style={styles.td}>{s.soldBy}</td>
                        <td style={{ ...styles.td, whiteSpace: "nowrap", textAlign: "right" }}>
                          <button type="button" onClick={() => setReceipt(s)} style={styles.rowButton}>
                            Receipt
                          </button>
                          {!s.voided && (isToday || meta.canManage) && (
                            <button type="button" onClick={() => setVoidTarget(s)} style={styles.voidButton}>
                              Void
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {receipt && <Receipt sale={receipt} onClose={() => setReceipt(null)} />}
      {voidTarget && (
        <VoidSaleDialog
          sale={voidTarget}
          onClose={() => setVoidTarget(null)}
          onVoided={(sale) => {
            setVoidTarget(null);
            setNotice(`Sale #${sale.id} voided - ${sale.items.reduce((n, i) => n + i.quantity, 0)} item(s) back on the shelf.`);
            loadProducts();
            loadSales();
          }}
        />
      )}
    </div>
  );
}

function Stat({ label, value, strong }) {
  return (
    <div style={styles.stat}>
      <div style={styles.statLabel}>{label}</div>
      <div style={{ ...styles.statValue, color: strong ? "#129638" : "#1a1a1a" }}>{value}</div>
    </div>
  );
}

// Only the receipt shows up when it's printed.
const PRINT_CSS = `@media print {
  body * { visibility: hidden !important; }
  #pos-receipt, #pos-receipt * { visibility: visible !important; }
  #pos-receipt { position: absolute; left: 0; top: 0; width: 80mm; box-shadow: none !important; }
  .pos-receipt-actions { display: none !important; }
}`;

function Receipt({ sale, onClose }) {
  return (
    <div style={styles.overlay} onClick={onClose}>
      <style>{PRINT_CSS}</style>
      <div id="pos-receipt" style={styles.receipt} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Receipt">
        <div style={styles.receiptBrand}>Fitness Factory</div>
        <div style={styles.receiptMeta}>
          {sale.branch} · Sale #{sale.id}
          <br />
          {sale.soldAt} · {sale.soldBy}
          {sale.memberName && (
            <>
              <br />
              Member: {sale.memberName} (ID {sale.memberId})
            </>
          )}
        </div>
        {sale.voided && <div style={styles.receiptVoid}>VOIDED - {sale.voidReason}</div>}
        <table style={styles.receiptTable}>
          <tbody>
            {sale.items.map((i) => (
              <tr key={i.productId}>
                <td style={styles.receiptCell}>
                  {i.quantity} × {i.productName}
                  <div style={styles.muted}>@ ${i.unitPrice}</div>
                </td>
                <td style={{ ...styles.receiptCell, textAlign: "right" }}>${i.lineTotal}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={styles.receiptTotal}>
          <span>Total</span>
          <span>${sale.total}</span>
        </div>
        <div style={styles.receiptLine}>
          <span>Paid by {sale.paymentMethod.toLowerCase()}</span>
          <span>{sale.amountTendered ? `$${sale.amountTendered}` : `$${sale.total}`}</span>
        </div>
        {sale.changeDue && (
          <div style={{ ...styles.receiptLine, fontWeight: 700 }}>
            <span>Change</span>
            <span>${sale.changeDue}</span>
          </div>
        )}
        <div style={styles.receiptThanks}>Thank you!</div>
        <div className="pos-receipt-actions" style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.cancelButton}>
            Close
          </button>
          <button type="button" onClick={() => window.print()} style={styles.submitButton}>
            Print
          </button>
        </div>
      </div>
    </div>
  );
}

function VoidSaleDialog({ sale, onClose, onVoided }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onVoided(await voidSale(sale.id, reason));
    } catch (err) {
      setError(err.fieldErrors?.reason?.[0] || err.message);
      setSaving(false);
    }
  }

  return (
    <div style={styles.overlay} onClick={onClose}>
      <form style={styles.modal} onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2 style={styles.modalTitle}>Void sale #{sale.id}?</h2>
        <p style={styles.modalText}>
          ${sale.total} ({sale.items.map((i) => `${i.quantity} × ${i.productName}`).join(", ")}). The items go back on the
          shelf and the sale stops counting toward the takings. It stays on record as voided.
        </p>
        <label style={styles.cashLabel}>
          Reason
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Rang up the wrong item"
            style={styles.input}
            autoFocus
          />
        </label>
        {error && <div style={styles.errorBox}>{error}</div>}
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.cancelButton}>
            Keep sale
          </button>
          <button type="submit" disabled={saving || !reason.trim()} style={styles.dangerButton}>
            {saving ? "Voiding..." : "Void sale"}
          </button>
        </div>
      </form>
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1180,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  branchChip: {
    padding: "8px 14px",
    borderRadius: 999,
    background: "#eef2fa",
    color: "#124096",
    fontSize: 14,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  branchPicker: { display: "flex", alignItems: "center", gap: 8 },
  branchLabel: { fontSize: 13, fontWeight: 600, color: "#444" },
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff" },
  layout: { display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" },
  catalog: { flex: "1 1 520px", minWidth: 0 },
  filters: { display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 },
  pills: { display: "flex", gap: 6, flexWrap: "wrap" },
  pill: {
    padding: "7px 12px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 999,
    border: "1px solid #d0d0d5",
    background: "#fff",
    color: "#444",
    cursor: "pointer",
  },
  pillActive: { borderColor: "#124096", background: "#124096", color: "#fff" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 },
  tile: {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 6,
    minHeight: 112,
    padding: 12,
    textAlign: "left",
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fff",
    cursor: "pointer",
    fontFamily: "inherit",
    color: "inherit",
  },
  tileDisabled: { background: "#f6f6f8", color: "#999", cursor: "not-allowed" },
  tileCategory: { fontSize: 11, fontWeight: 700, color: "#888", textTransform: "uppercase", letterSpacing: 0.4 },
  tileName: { fontSize: 14, fontWeight: 600, lineHeight: 1.3, flex: 1 },
  tileFooter: { display: "flex", justifyContent: "space-between", alignItems: "baseline", width: "100%", gap: 6 },
  tilePrice: { fontSize: 15, fontWeight: 700 },
  stock: { fontSize: 12, color: "#666" },
  lowStock: { fontSize: 12, color: "#a15c00", fontWeight: 600 },
  soldOut: { fontSize: 12, color: "#b3261e", fontWeight: 700 },
  badge: {
    position: "absolute",
    top: 8,
    right: 8,
    minWidth: 22,
    height: 22,
    padding: "0 6px",
    borderRadius: 11,
    background: "#124096",
    color: "#fff",
    fontSize: 12,
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxSizing: "border-box",
  },
  basket: {
    flex: "1 1 320px",
    maxWidth: 420,
    border: "1px solid #e4e4e8",
    borderRadius: 12,
    background: "#fff",
    padding: 16,
    boxSizing: "border-box",
  },
  basketHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  basketTitle: { fontSize: 17, fontWeight: 700, margin: 0 },
  linkButton: { border: "none", background: "none", color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer" },
  emptyBasket: { fontSize: 14, color: "#888", padding: "18px 0", textAlign: "center" },
  lines: { listStyle: "none", margin: 0, padding: 0 },
  line: { display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid #f0f0f3" },
  lineInfo: { flex: 1, minWidth: 0, display: "flex", flexDirection: "column" },
  lineName: { fontSize: 14, fontWeight: 600 },
  lineUnit: { fontSize: 12, color: "#888" },
  stepper: { display: "flex", alignItems: "center", gap: 4 },
  stepButton: {
    width: 28,
    height: 28,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#fff",
    fontSize: 16,
    lineHeight: 1,
    cursor: "pointer",
  },
  qty: { minWidth: 22, textAlign: "center", fontWeight: 700, fontSize: 14 },
  lineTotal: { width: 64, textAlign: "right", fontWeight: 600, fontSize: 14 },
  totalRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    padding: "12px 0",
    fontSize: 15,
    fontWeight: 600,
  },
  total: { fontSize: 24, fontWeight: 800 },
  muted: { fontSize: 12, color: "#888", fontWeight: 400 },
  section: { borderTop: "1px solid #f0f0f3", paddingTop: 12, marginBottom: 12 },
  sectionLabel: { fontSize: 13, fontWeight: 700, color: "#444", marginBottom: 8 },
  memberRow: { display: "flex", gap: 6, marginBottom: 4 },
  memberChip: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
    padding: "8px 10px",
    borderRadius: 8,
    background: "#eef2fa",
    fontSize: 14,
  },
  chipRemove: { border: "none", background: "none", fontSize: 18, lineHeight: 1, color: "#666", cursor: "pointer" },
  smallButton: {
    padding: "8px 10px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    color: "#333",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  cashLabel: { display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600, color: "#444" },
  quickCash: { display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 },
  quickButton: {
    padding: "6px 10px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 6,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  change: { marginTop: 10, fontSize: 16, fontWeight: 700, color: "#0f6e2b" },
  short: { marginTop: 10, fontSize: 14, fontWeight: 700, color: "#b3261e" },
  chargeButton: {
    width: "100%",
    height: 48,
    border: "none",
    borderRadius: 10,
    ...BUTTON_COLORS.green,
    fontSize: 17,
    fontWeight: 700,
    cursor: "pointer",
  },
  chargeDisabled: {
    width: "100%",
    height: 48,
    border: "none",
    borderRadius: 10,
    background: "#c9cdd3",
    color: "#fff",
    fontSize: 17,
    fontWeight: 700,
    cursor: "not-allowed",
  },
  input: {
    width: "100%",
    padding: "9px 11px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
  },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 14 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  hintBox: { background: "#fff7e0", color: "#7a5600", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  empty: { fontSize: 14, color: "#888", padding: "16px 0" },
  salesHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 },
  summary: { display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 },
  stat: { flex: "1 1 110px", border: "1px solid #e4e4e8", borderRadius: 10, padding: "10px 12px", background: "#fff" },
  statLabel: { fontSize: 12, color: "#666", fontWeight: 600 },
  statValue: { fontSize: 20, fontWeight: 800, marginTop: 2 },
  tableWrap: { overflowX: "auto", border: "1px solid #e4e4e8", borderRadius: 10, background: "#fff" },
  table: { width: "100%", minWidth: 760, borderCollapse: "collapse", fontSize: 14 },
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
  td: { padding: "10px 12px", borderBottom: "1px solid #f0f0f3", verticalAlign: "top" },
  voidedRow: { color: "#999", background: "#fafafa" },
  voidNote: { fontSize: 12, color: "#b3261e", marginTop: 4 },
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
  voidButton: {
    padding: "5px 10px",
    fontSize: 12,
    fontWeight: 600,
    border: "none",
    borderRadius: 6,
    ...BUTTON_COLORS.red,
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
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: "0 0 8px" },
  modalText: { fontSize: 14, color: "#555", lineHeight: 1.5, margin: "0 0 14px" },
  receipt: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 360,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
    fontSize: 13,
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  receiptBrand: { fontSize: 18, fontWeight: 800, textAlign: "center", marginBottom: 6 },
  receiptMeta: { fontSize: 12, color: "#555", textAlign: "center", lineHeight: 1.5, marginBottom: 12 },
  receiptVoid: { textAlign: "center", color: "#b3261e", fontWeight: 700, marginBottom: 10 },
  receiptTable: { width: "100%", borderCollapse: "collapse", borderTop: "1px dashed #bbb", borderBottom: "1px dashed #bbb" },
  receiptCell: { padding: "6px 0", verticalAlign: "top" },
  receiptTotal: { display: "flex", justifyContent: "space-between", fontSize: 16, fontWeight: 800, padding: "10px 0 4px" },
  receiptLine: { display: "flex", justifyContent: "space-between", padding: "2px 0" },
  receiptThanks: { textAlign: "center", marginTop: 14, color: "#555" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18 },
  cancelButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  submitButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  },
  dangerButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
};

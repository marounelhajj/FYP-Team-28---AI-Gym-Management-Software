import { useEffect, useState } from "react";
import { fetchAccessCard, reissueAccessCard } from "../api/members.js";
import { BUTTON_COLORS } from "../styles/buttonColors.js";
import SegmentedControl from "./SegmentedControl.jsx";

const STATUS_STYLES = { Active: BUTTON_COLORS.green, Frozen: BUTTON_COLORS.blue, Cancelled: BUTTON_COLORS.red };
const REASON_OPTIONS = ["Lost", "Stolen", "Damaged", "Other"].map((r) => ({ value: r, label: r }));
const EMPTY_FORM = { reason: "", note: "", identityConfirmed: false };

const PRINT_CSS = `
  @page { margin: 12mm; }
  body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .card { box-sizing: border-box; width: 85.6mm; height: 54mm; border-radius: 3.5mm; padding: 4mm;
    display: flex; align-items: center; gap: 4mm; background: #124096; color: #fff;
    -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .qr { width: 32mm; height: 32mm; padding: 1mm; border-radius: 2mm; background: #fff; flex-shrink: 0; }
  .brand { display: flex; align-items: center; gap: 2mm; font-size: 7pt; font-weight: 800; letter-spacing: 0.4pt;
    white-space: nowrap; }
  .logo { width: 8mm; height: 8mm; border-radius: 50%; background: #fff; }
  .name { margin-top: 4mm; font-size: 12pt; font-weight: 700; line-height: 1.15; }
  .meta { margin-top: 1.2mm; font-size: 8pt; opacity: 0.9; }
`;

// Opens the card, at real ID-card size, in a print window. Built with DOM
// nodes and textContent so nothing typed into a member's profile is ever
// interpreted as HTML. Returns false if the browser blocked the pop-up.
function printCard(member, card) {
  const win = window.open("", "_blank", "width=480,height=380");
  if (!win) return false;
  const doc = win.document;
  doc.title = `Access card - ${member.name}`;

  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const style = el("style");
  style.textContent = PRINT_CSS;
  doc.head.appendChild(style);

  const qr = el("img", "qr");
  qr.src = card.qrCode;
  qr.alt = "";
  const logo = el("img", "logo");
  logo.src = `${window.location.origin}/logo-badge.png`;
  logo.alt = "";
  const brand = el("div", "brand");
  brand.append(logo, el("span", null, "FITNESS FACTORY"));
  const info = el("div");
  info.append(
    brand,
    el("div", "name", member.name),
    el("div", "meta", `Membership ID #${member.id}`),
    el("div", "meta", `Card ${card.number} · issued ${card.issuedOn}`),
  );
  const cardEl = el("div", "card");
  cardEl.append(qr, info);
  doc.body.appendChild(cardEl);

  win.addEventListener("afterprint", () => win.close());
  Promise.allSettled([qr.decode(), logo.decode()]).then(() => {
    win.focus();
    win.print();
  });
  return true;
}

// A member's access card - the QR code they show to check in - and where a
// receptionist reissues it when it's lost, stolen or damaged. Reissuing makes
// every earlier card stop working at once (backend/members/qr.py).
export default function AccessCardPanel({ memberId, onClose }) {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [issued, setIssued] = useState(null); // { number, previous } right after a reissue
  const [printBlocked, setPrintBlocked] = useState(false);

  useEffect(() => {
    fetchAccessCard(memberId)
      .then(setData)
      .catch((err) => setLoadError(err.message));
  }, [memberId]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    setFieldErrors((errs) => ({ ...errs, [field]: undefined }));
  }

  async function handleReissue(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    try {
      const previous = data.card.number;
      const updated = await reissueAccessCard(memberId, form);
      setData(updated);
      setIssued({ number: updated.card.number, previous });
      setForm(EMPTY_FORM);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handlePrint() {
    setPrintBlocked(!printCard(data.member, data.card));
  }

  const member = data?.member;
  const card = data?.card;
  const noteRequired = form.reason === "Other";
  const canReissue = Boolean(form.reason && form.identityConfirmed && (!noteRequired || form.note.trim()) && !submitting);

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>Access Card</h2>
          <button onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        {!data && !loadError && <div style={styles.muted}>Loading...</div>}
        {loadError && <div style={styles.errorBox}>{loadError}</div>}

        {data && (
          <>
            <div style={styles.memberStrip}>
              <div>
                <div style={styles.memberName}>{member.name}</div>
                <div style={styles.memberMeta}>
                  #{member.id} &middot; {member.branch}
                </div>
              </div>
              <span style={{ ...styles.statusBadge, ...(STATUS_STYLES[member.status] || BUTTON_COLORS.blue) }}>
                {member.status}
              </span>
            </div>

            {issued && (
              <div style={styles.successBox}>
                Card {issued.number} issued. Card {issued.previous} no longer works. Print the new card, or the member
                can open the new code in their member app.
              </div>
            )}

            <div style={styles.cardPreview} aria-label={`Access card ${card.number} for ${member.name}`}>
              <img src={card.qrCode} alt="Check-in QR code" style={styles.cardQr} />
              <div style={styles.cardInfo}>
                <div style={styles.cardBrand}>
                  <img src="/logo-badge.png" alt="" style={styles.cardLogo} />
                  FITNESS FACTORY
                </div>
                <div style={styles.cardName}>{member.name}</div>
                <div style={styles.cardMeta}>Membership ID #{member.id}</div>
                <div style={styles.cardMeta}>
                  Card {card.number} &middot; issued {card.issuedOn}
                </div>
              </div>
            </div>

            <div style={styles.previewFooter}>
              <span style={styles.muted}>
                Only this card works.{" "}
                {!member.doorAccess.granted ? (
                  <span style={{ color: "#b3261e", fontWeight: 600 }}>
                    Won't open the doors: {member.doorAccess.message}
                  </span>
                ) : data.doorDeskOnly ? (
                  <span style={{ color: "#8a5a00", fontWeight: 600 }}>
                    Doors send them to the front desk (flagged check-in).
                  </span>
                ) : (
                  <span style={{ color: "#1d5e2f", fontWeight: 600 }}>
                    Opens the doors - {member.doorAccess.message.toLowerCase()}
                  </span>
                )}
              </span>
              <button type="button" onClick={handlePrint} style={styles.secondaryButton}>
                Print card
              </button>
            </div>
            {printBlocked && (
              <div style={styles.errorBox}>The browser blocked the print window. Allow pop-ups for this site and try again.</div>
            )}

            <h3 style={styles.sectionTitle}>Reissue card</h3>
            <form onSubmit={handleReissue} style={styles.reissueBox}>
              <Field label="Why does the member need a new card?" error={fieldErrors.reason}>
                <SegmentedControl
                  options={REASON_OPTIONS}
                  value={form.reason}
                  onChange={(r) => update("reason", r)}
                  ariaLabel="Reason for reissuing"
                />
              </Field>

              <Field label={`Note ${noteRequired ? "(required)" : "(optional)"}`} error={fieldErrors.note}>
                <input
                  type="text"
                  value={form.note}
                  onChange={(e) => update("note", e.target.value)}
                  maxLength={200}
                  aria-label="Note"
                  placeholder={noteRequired ? "What happened?" : "e.g. lost at the pool"}
                  style={styles.input}
                />
              </Field>

              <label style={styles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={form.identityConfirmed}
                  onChange={(e) => update("identityConfirmed", e.target.checked)}
                />
                I checked the member's photo ID
              </label>
              {fieldErrors.identityConfirmed && <div style={styles.fieldError}>{fieldErrors.identityConfirmed[0]}</div>}

              <div style={styles.warning}>
                Card {card.number} stops working as soon as the new card is issued.
              </div>

              {submitError && <div style={styles.errorBox}>{submitError}</div>}

              <div style={styles.reissueActions}>
                <button
                  type="submit"
                  disabled={!canReissue}
                  style={canReissue ? styles.reissueButton : { ...styles.reissueButton, ...styles.disabled }}
                >
                  {submitting ? "Issuing..." : `Issue card ${card.number + 1}`}
                </button>
              </div>
            </form>

            <h3 style={styles.sectionTitle}>Card history</h3>
            <div style={styles.history}>
              {data.history.map((h) => (
                <div key={h.cardNumber} style={styles.historyRow}>
                  <div style={styles.historyMain}>
                    <strong>Card {h.cardNumber}</strong>
                    <span style={styles.reasonTag}>{h.reason}</span>
                    {h.note && <span style={styles.historyNote}>{h.note}</span>}
                  </div>
                  <div style={styles.historyMeta}>
                    {h.reissuedAt}
                    {h.reissuedBy ? ` · ${h.reissuedBy}` : ""}
                  </div>
                </div>
              ))}
              <div style={styles.historyRow}>
                <div style={styles.historyMain}>
                  <strong>Card 1</strong>
                  <span style={styles.reasonTag}>Original</span>
                </div>
                <div style={styles.historyMeta}>Issued at sign-up, {member.joinDate}</div>
              </div>
            </div>
          </>
        )}

        <div style={styles.footer}>
          <button type="button" onClick={onClose} style={styles.closeAction}>
            Close
          </button>
        </div>
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
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    // Opens on top of the subscription details panel too.
    zIndex: 1100,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 500,
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  memberStrip: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "12px 14px",
    marginBottom: 16,
    border: "1px solid #e4e4e8",
    borderRadius: 10,
    background: "#fafafa",
  },
  memberName: { fontSize: 15, fontWeight: 700 },
  memberMeta: { fontSize: 12, color: "#666", marginTop: 2 },
  statusBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 22,
    width: 76,
    flexShrink: 0,
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 600,
  },
  successBox: {
    background: "#e6f4ea",
    color: "#1e7a34",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    lineHeight: 1.45,
    marginBottom: 14,
  },
  cardPreview: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    padding: 16,
    borderRadius: 14,
    background: "linear-gradient(135deg, #124096 0%, #0b2a66 100%)",
    color: "#fff",
    boxShadow: "0 6px 18px rgba(18,64,150,0.25)",
  },
  cardQr: { width: 132, height: 132, padding: 4, borderRadius: 8, background: "#fff", flexShrink: 0 },
  cardInfo: { minWidth: 0 },
  cardBrand: { display: "flex", alignItems: "center", gap: 8, fontSize: 11, fontWeight: 800, letterSpacing: 0.8 },
  cardLogo: { width: 26, height: 26, borderRadius: "50%", background: "#fff" },
  cardName: { fontSize: 18, fontWeight: 700, marginTop: 14, lineHeight: 1.2, overflowWrap: "anywhere" },
  cardMeta: { fontSize: 12, opacity: 0.9, marginTop: 4 },
  previewFooter: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 10 },
  muted: { fontSize: 12, color: "#777" },
  secondaryButton: {
    flexShrink: 0,
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.4,
    color: "#555",
    margin: "22px 0 8px",
  },
  reissueBox: { padding: "14px", border: "1px solid #e4e4e8", borderRadius: 10 },
  field: { marginBottom: 12 },
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
  checkboxRow: { display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "#333", cursor: "pointer" },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  warning: {
    marginTop: 12,
    padding: "8px 10px",
    borderRadius: 8,
    background: "#fff4e0",
    color: "#8a5a00",
    fontSize: 12,
  },
  reissueActions: { display: "flex", justifyContent: "flex-end", marginTop: 12 },
  reissueButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
  disabled: { opacity: 0.5, cursor: "not-allowed" },
  history: { border: "1px solid #e4e4e8", borderRadius: 10, overflow: "hidden" },
  historyRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    gap: 12,
    padding: "9px 12px",
    borderBottom: "1px solid #f0f0f2",
    fontSize: 13,
  },
  historyMain: { display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 8, minWidth: 0 },
  reasonTag: {
    fontSize: 11,
    fontWeight: 700,
    padding: "1px 7px",
    borderRadius: 6,
    background: "#f0f0f3",
    color: "#555",
  },
  historyNote: { fontSize: 12, color: "#666" },
  historyMeta: { fontSize: 12, color: "#888", whiteSpace: "nowrap" },
  errorBox: {
    background: "#fdeceb",
    color: "#b3261e",
    padding: "10px 14px",
    borderRadius: 8,
    fontSize: 13,
    marginTop: 10,
  },
  footer: { display: "flex", justifyContent: "flex-end", marginTop: 18 },
  closeAction: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
};

import { useEffect, useMemo, useState } from "react";
import { createCampaign, previewAudience, updateCampaign } from "../../api/marketing.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";

function todayIso() {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function addDays(iso, days) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function formatDay(iso) {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

const DEFAULT_STATUSES = ["Active"];
// Inputs that can't change (a started campaign's offer) look it - the inline
// styles set a white background, so this needs !important.
const FIXED_CSS =
  ".campaign-form input:disabled, .campaign-form select:disabled, .campaign-form textarea:disabled" +
  " { background: #f3f3f6 !important; color: #666 !important; cursor: not-allowed; }";
const USE_WORDS = {
  Membership: "membership renewals",
  Shop: "shop purchases",
  Both: "membership renewals and shop purchases",
};

// A code from the campaign name and discount, e.g. "Summer Push" + 20% -> SUMMER20.
function suggestCode(name, value) {
  const word = (name.match(/[A-Za-z]+/) || ["PROMO"])[0].toUpperCase().slice(0, 10);
  const number = String(value || "").replace(/\.0+$/, "").replace(/[^0-9]/g, "").slice(0, 4);
  const code = `${word}${number}`;
  return code.length >= 3 ? code : `${code}OFF`;
}

function errorText(error) {
  if (!error) return null;
  if (Array.isArray(error)) return error[0];
  if (typeof error === "string") return error;
  return Object.values(error).flat()[0];
}

function initialForm(campaign, defaultBranch, branches) {
  if (campaign) {
    const s = campaign.segment || {};
    return {
      branch: campaign.branch,
      name: campaign.name,
      strategy: campaign.strategy,
      budget: campaign.budget,
      amountSpent: campaign.amountSpent,
      startDate: campaign.startDate,
      endDate: campaign.endDate,
      hasOffer: Boolean(campaign.offerCode),
      offerCode: campaign.offerCode || "",
      discountType: campaign.discountType || "Percent",
      discountValue: campaign.discountValue ? String(Number(campaign.discountValue)) : "",
      appliesTo: campaign.appliesTo || "Both",
      maxRedemptions: campaign.maxRedemptions ? String(campaign.maxRedemptions) : "",
      offerMessage: campaign.offerMessage || "",
      notifyAudience: campaign.offerCode ? campaign.notifyAudience : true,
      statuses: s.statuses?.length ? s.statuses : DEFAULT_STATUSES,
      plans: s.plans || [],
      renewalWithinDays: s.renewalWithinDays ? String(s.renewalWithinDays) : null,
      inactiveDays: s.inactiveDays ? String(s.inactiveDays) : null,
      joinedWithinDays: s.joinedWithinDays ? String(s.joinedWithinDays) : null,
    };
  }
  const today = todayIso();
  return {
    branch: defaultBranch || branches[0] || "",
    name: "",
    strategy: "",
    budget: "",
    amountSpent: "0",
    startDate: today,
    endDate: addDays(today, 14),
    hasOffer: true,
    offerCode: "",
    discountType: "Percent",
    discountValue: "",
    appliesTo: "Both",
    maxRedemptions: "",
    offerMessage: "",
    notifyAudience: true,
    statuses: DEFAULT_STATUSES,
    plans: [],
    // null = rule off; a string (maybe still being typed) = on.
    renewalWithinDays: null,
    inactiveDays: null,
    joinedWithinDays: null,
  };
}

function segmentOf(form) {
  const days = (v) => (v === null || v === "" ? null : Number(v));
  return {
    statuses: form.statuses,
    plans: form.plans,
    renewalWithinDays: days(form.renewalWithinDays),
    inactiveDays: days(form.inactiveDays),
    joinedWithinDays: days(form.joinedWithinDays),
  };
}

// User story: "As a marketing staff member, I want to create and schedule
// promotional campaigns with a target segment and offer code, so that I can
// launch promotions without needing developer help."
//
// New campaign or edit - `campaign` is null for a new one. Besides the plan
// and budget, a campaign can carry an offer code and a target segment: the
// form shows live how many members the segment reaches, and on the start date
// the server sends them the code and starts accepting it at the desk and the
// till by itself. Once a campaign has started its offer and audience are
// fixed (members may already have the code), so they're shown read-only.
export default function CampaignForm({ campaign, meta, defaultBranch, onClose, onSaved }) {
  const isEditing = Boolean(campaign);
  const branches = meta.branches;
  const [form, setForm] = useState(() => initialForm(campaign, defaultBranch, branches));
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [audience, setAudience] = useState(null);
  const [audienceError, setAudienceError] = useState(null);

  const started = isEditing && campaign.offerLocked;
  const offerFixed = started && Boolean(campaign.offerCode);
  const today = todayIso();
  const segment = useMemo(() => segmentOf(form), [form.statuses, form.plans, form.renewalWithinDays, form.inactiveDays, form.joinedWithinDays]);
  const activePlans = meta.plans.filter((p) => p.active || form.plans.includes(p.name));

  useEffect(() => {
    if (!form.hasOffer || !form.branch) {
      setAudience(null);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      previewAudience(form.branch, segment)
        .then((data) => {
          if (!cancelled) {
            setAudience(data);
            setAudienceError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) setAudienceError(errorText(err.fieldErrors?.segment) || err.message);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [form.hasOffer, form.branch, segment]);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
    setFieldErrors((errs) => {
      const key = ["statuses", "plans", "renewalWithinDays", "inactiveDays", "joinedWithinDays"].includes(field) ? "segment" : field;
      return { ...errs, [key]: undefined };
    });
  }

  function toggleIn(field, value) {
    const list = form[field];
    update(field, list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setFieldErrors({});
    const payload = {
      branch: form.branch,
      name: form.name,
      strategy: form.strategy,
      budget: form.budget,
      amountSpent: form.amountSpent,
      startDate: form.startDate,
      endDate: form.endDate,
      offerCode: form.hasOffer ? form.offerCode : "",
    };
    if (form.hasOffer) {
      Object.assign(payload, {
        discountType: form.discountType,
        discountValue: form.discountValue === "" ? null : form.discountValue,
        appliesTo: form.appliesTo,
        maxRedemptions: form.maxRedemptions === "" ? null : Number(form.maxRedemptions),
        offerMessage: form.offerMessage,
        notifyAudience: form.notifyAudience,
        segment,
      });
    }
    try {
      const saved = isEditing ? await updateCampaign(campaign.id, payload) : await createCampaign(payload);
      onSaved(saved, isEditing);
    } catch (err) {
      if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const capHint = form.appliesTo !== "Shop" && meta.plans.some((p) => p.active)
    ? `Membership discounts are capped per plan by the General Manager: ${meta.plans
        .filter((p) => p.active)
        .map((p) => `${p.name} ${Number(p.maxDiscountPercent)}%`)
        .join(", ")}. A branch promotion that's already cheaper wins instead.`
    : null;

  const discountWords = form.discountValue
    ? form.discountType === "Percent"
      ? `${Number(form.discountValue)}% off`
      : `$${Number(form.discountValue).toFixed(2)} off`
    : "";
  const startsToday = form.startDate <= today;

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={isEditing ? "Edit campaign" : "New campaign"}>
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{isEditing ? "Edit Campaign" : "New Marketing Campaign"}</h2>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>

        <style>{FIXED_CSS}</style>
        <form onSubmit={handleSubmit} className="campaign-form">
          <Section title="Campaign">
            <Field label="Campaign name" error={fieldErrors.name}>
              <input
                type="text"
                value={form.name}
                onChange={(e) => update("name", e.target.value)}
                style={styles.input}
                placeholder="e.g. Summer Membership Push"
                maxLength={80}
                autoFocus
              />
            </Field>

            <div style={styles.row}>
              <Field label="Branch" error={fieldErrors.branch}>
                <select value={form.branch} onChange={(e) => update("branch", e.target.value)} style={styles.input} disabled={isEditing}>
                  {branches.map((b) => (
                    <option key={b} value={b}>
                      {b}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Starts" error={fieldErrors.startDate}>
                <input
                  type="date"
                  value={form.startDate}
                  min={form.hasOffer && !started ? today : undefined}
                  onChange={(e) => update("startDate", e.target.value)}
                  style={styles.input}
                  disabled={offerFixed}
                />
              </Field>
              <Field label="Ends" error={fieldErrors.endDate}>
                <input
                  type="date"
                  value={form.endDate}
                  min={form.startDate}
                  onChange={(e) => update("endDate", e.target.value)}
                  style={styles.input}
                />
              </Field>
            </div>

            <Field label="Strategy (what it is, and why)" error={fieldErrors.strategy}>
              <textarea
                value={form.strategy}
                onChange={(e) => update("strategy", e.target.value)}
                style={{ ...styles.input, minHeight: 64, resize: "vertical", fontFamily: "inherit" }}
                placeholder="e.g. Win back members who stopped coming, ahead of the summer."
              />
            </Field>

            <div style={styles.row}>
              <Field label="Budget ($)" error={fieldErrors.budget}>
                <input type="number" min="0.01" step="0.01" value={form.budget} onChange={(e) => update("budget", e.target.value)} style={styles.input} />
              </Field>
              <Field label="Spent so far ($)" error={fieldErrors.amountSpent}>
                <input type="number" min="0" step="0.01" value={form.amountSpent} onChange={(e) => update("amountSpent", e.target.value)} style={styles.input} />
              </Field>
            </div>
          </Section>

          <Section
            title="Offer code"
            aside={
              <label style={{ ...styles.check, ...(started ? styles.disabledText : null) }}>
                <input type="checkbox" checked={form.hasOffer} disabled={started} onChange={(e) => update("hasOffer", e.target.checked)} />
                This campaign has an offer
              </label>
            }
          >
            {started && !campaign.offerCode && <p style={styles.hint}>An offer can only be added before a campaign starts - start a new campaign for one.</p>}
            {offerFixed && (
              <div style={styles.lockedBox}>
                This campaign has {campaign.status === "Running" ? "started" : campaign.status === "Expired" ? "ended" : "been cancelled"}, so its code,
                discount and audience are fixed - members may already have them. You can still change its name, plan, budget, spend, end date and use limit.
              </div>
            )}
            {errorText(fieldErrors.offerCode) && offerFixed && <div style={styles.errorBox}>{errorText(fieldErrors.offerCode)}</div>}

            {form.hasOffer && (
              <>
                <div style={styles.row}>
                  <Field label="Code" error={fieldErrors.offerCode}>
                    <div style={styles.inline}>
                      <input
                        type="text"
                        value={form.offerCode}
                        onChange={(e) => update("offerCode", e.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, ""))}
                        style={{ ...styles.input, ...styles.codeInput }}
                        placeholder="SUMMER20"
                        maxLength={20}
                        disabled={offerFixed}
                        aria-label="Offer code"
                      />
                      {!offerFixed && (
                        <button type="button" onClick={() => update("offerCode", suggestCode(form.name, form.discountValue))} style={styles.smallButton}>
                          Suggest
                        </button>
                      )}
                    </div>
                  </Field>
                  <Field label="Discount" error={fieldErrors.discountValue || fieldErrors.discountType}>
                    <div style={styles.inline}>
                      <select
                        value={form.discountType}
                        onChange={(e) => update("discountType", e.target.value)}
                        style={{ ...styles.input, width: 110, flexShrink: 0 }}
                        disabled={offerFixed}
                        aria-label="Discount type"
                      >
                        <option value="Percent">% off</option>
                        <option value="Fixed">$ off</option>
                      </select>
                      <input
                        type="number"
                        min="0.01"
                        max={form.discountType === "Percent" ? 100 : 1000}
                        step="0.01"
                        value={form.discountValue}
                        onChange={(e) => update("discountValue", e.target.value)}
                        style={styles.input}
                        disabled={offerFixed}
                        aria-label="Discount amount"
                        placeholder={form.discountType === "Percent" ? "20" : "10.00"}
                      />
                    </div>
                  </Field>
                </div>

                <div style={styles.row}>
                  <Field label="Can be used on" error={fieldErrors.appliesTo}>
                    <select value={form.appliesTo} onChange={(e) => update("appliesTo", e.target.value)} style={styles.input} disabled={offerFixed}>
                      {meta.appliesTo.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Limit on uses (optional)" error={fieldErrors.maxRedemptions}>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={form.maxRedemptions}
                      onChange={(e) => update("maxRedemptions", e.target.value)}
                      style={styles.input}
                      placeholder="No limit"
                    />
                  </Field>
                </div>
                {capHint && <p style={styles.hint}>{capHint} Each member can use a code once.</p>}

                <Field label="Message to members (optional)" error={fieldErrors.offerMessage}>
                  <textarea
                    value={form.offerMessage}
                    onChange={(e) => update("offerMessage", e.target.value)}
                    style={{ ...styles.input, minHeight: 56, resize: "vertical", fontFamily: "inherit" }}
                    maxLength={400}
                    disabled={offerFixed}
                    placeholder="e.g. We miss you! Come back this month and save on your next renewal."
                  />
                  <div style={styles.counter}>{form.offerMessage.length}/400 · the code, discount and end date are added for you</div>
                </Field>
              </>
            )}
          </Section>

          {form.hasOffer && (
            <Section title="Who it's for">
              {errorText(fieldErrors.segment) && <div style={styles.errorBox}>{errorText(fieldErrors.segment)}</div>}
              <p style={styles.hint}>
                {form.branch} members who match everything you tick. The code only works for them (and anyone it was sent to).
              </p>
              <div style={styles.groupLabel}>Membership</div>
              <div style={styles.chips}>
                {meta.statuses.map((s) => (
                  <label key={s.value} style={styles.check}>
                    <input
                      type="checkbox"
                      checked={form.statuses.includes(s.value)}
                      disabled={offerFixed || (form.statuses.length === 1 && form.statuses.includes(s.value))}
                      onChange={() => toggleIn("statuses", s.value)}
                    />
                    {s.label}
                  </label>
                ))}
              </div>
              <div style={styles.groupLabel}>Plan {form.plans.length === 0 && <span style={styles.muted}>(any plan)</span>}</div>
              <div style={styles.chips}>
                {activePlans.map((p) => (
                  <label key={p.name} style={styles.check}>
                    <input type="checkbox" checked={form.plans.includes(p.name)} disabled={offerFixed} onChange={() => toggleIn("plans", p.name)} />
                    {p.name}
                    {!p.active && " (no longer sold)"}
                  </label>
                ))}
              </div>
              <div style={styles.groupLabel}>And also</div>
              <DaysRule
                label="Membership renews in the next"
                value={form.renewalWithinDays}
                onChange={(v) => update("renewalWithinDays", v)}
                min={1}
                max={90}
                suggested="14"
                disabled={offerFixed || !form.statuses.includes("Active")}
                note={!form.statuses.includes("Active") ? "Only for active members" : null}
              />
              <DaysRule
                label="Hasn't been in for at least"
                value={form.inactiveDays}
                onChange={(v) => update("inactiveDays", v)}
                min={7}
                max={365}
                suggested="30"
                disabled={offerFixed}
              />
              <DaysRule
                label="Joined in the last"
                value={form.joinedWithinDays}
                onChange={(v) => update("joinedWithinDays", v)}
                min={1}
                max={365}
                suggested="30"
                disabled={offerFixed}
              />

              <div style={styles.audienceBox} aria-live="polite">
                {audienceError ? (
                  <span style={{ color: "#b3261e" }}>{audienceError}</span>
                ) : !audience ? (
                  <span style={styles.muted}>Counting members...</span>
                ) : (
                  <>
                    <div style={styles.audienceCount}>
                      {audience.count} member{audience.count === 1 ? "" : "s"}{" "}
                      {offerFixed ? "in this audience now" : audience.count === 1 ? "matches right now" : "match right now"}
                    </div>
                    <div style={styles.audienceDetail}>{audience.description}</div>
                    {audience.count > 0 && (
                      <div style={styles.audienceDetail}>
                        {audience.reachable} would get it: {audience.byEmail} by email and in the app, {audience.reachable - audience.byEmail} in the app only
                        {audience.optedOut > 0 && ` · ${audience.optedOut} turned offers off`}
                      </div>
                    )}
                    {audience.count === 0 && <div style={styles.audienceWarn}>Nobody matches yet - widen the audience, or members who join it later will get it.</div>}
                  </>
                )}
              </div>

              <label style={{ ...styles.check, marginTop: 10, ...(offerFixed ? styles.disabledText : null) }}>
                <input type="checkbox" checked={form.notifyAudience} disabled={offerFixed} onChange={(e) => update("notifyAudience", e.target.checked)} />
                Send them the code when the campaign starts (in the app, and by email if they get emails)
              </label>
              <p style={styles.hint}>
                {form.notifyAudience
                  ? `Goes out ${startsToday ? `today from ${meta.sendFrom} (within a minute if it's already later)` : `on ${formatDay(form.startDate)} at ${meta.sendFrom}`}. Members who join the audience while it runs get it then. Nobody is messaged at night or twice.`
                  : "Nothing is sent - share the code yourself (flyers, social media). It still only works for this audience."}
              </p>
            </Section>
          )}

          {form.hasOffer && form.offerCode && discountWords && !offerFixed && (
            <div style={styles.summary}>
              <strong>{form.offerCode}</strong> gives {discountWords} {USE_WORDS[form.appliesTo]} at {form.branch}, from {formatDay(form.startDate)} to{" "}
              {formatDay(form.endDate)}
              {form.maxRedemptions ? `, for the first ${form.maxRedemptions} uses` : ""}.{" "}
              {audience && form.notifyAudience ? `${audience.reachable} member${audience.reachable === 1 ? "" : "s"} will be sent it.` : ""}
            </div>
          )}

          {submitError && <div style={styles.errorBox}>{submitError}</div>}

          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelButton}>
              Cancel
            </button>
            <button type="submit" disabled={submitting} style={styles.submitButton}>
              {submitting ? "Saving..." : isEditing ? "Save changes" : startsToday && form.hasOffer ? "Launch campaign" : "Schedule campaign"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DaysRule({ label, value, onChange, min, max, suggested, disabled, note }) {
  const on = value !== null;
  return (
    <div style={{ ...styles.daysRule, ...(disabled && !on ? styles.disabledText : null) }}>
      <label style={styles.check}>
        <input type="checkbox" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked ? suggested : null)} />
        {label}
      </label>
      {on && (
        <span style={styles.inline}>
          <input
            type="number"
            min={min}
            max={max}
            value={value}
            onChange={(e) => onChange(e.target.value.replace(/[^0-9]/g, ""))}
            style={{ ...styles.input, width: 80 }}
            disabled={disabled}
            aria-label={`${label} (days)`}
          />
          days
        </span>
      )}
      {note && <span style={styles.muted}>{note}</span>}
    </div>
  );
}

function Section({ title, aside, children }) {
  return (
    <section style={styles.section}>
      <div style={styles.sectionHead}>
        <h3 style={styles.sectionTitle}>{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Field({ label, error, children }) {
  const message = errorText(error);
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
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxWidth: 680,
    maxHeight: "92vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  section: { borderTop: "1px solid #ececf0", paddingTop: 14, marginTop: 6, marginBottom: 6 },
  sectionHead: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 },
  sectionTitle: { fontSize: 14, fontWeight: 800, margin: 0, textTransform: "uppercase", letterSpacing: 0.4, color: "#124096" },
  row: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12 },
  field: { marginBottom: 12, minWidth: 0 },
  label: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
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
  codeInput: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontWeight: 700, letterSpacing: 1 },
  inline: { display: "flex", alignItems: "center", gap: 8 },
  smallButton: {
    flexShrink: 0,
    whiteSpace: "nowrap",
    padding: "8px 12px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  check: { display: "inline-flex", alignItems: "center", gap: 7, fontSize: 14, cursor: "pointer" },
  chips: { display: "flex", flexWrap: "wrap", gap: "8px 18px", marginBottom: 12 },
  groupLabel: { fontSize: 12, fontWeight: 700, color: "#555", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.3 },
  daysRule: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", minHeight: 38, marginBottom: 4 },
  disabledText: { color: "#999" },
  muted: { fontSize: 12, color: "#888", fontWeight: 400, textTransform: "none", letterSpacing: 0 },
  hint: { fontSize: 12, color: "#666", margin: "0 0 10px", lineHeight: 1.45 },
  counter: { fontSize: 11, color: "#888", marginTop: 4 },
  lockedBox: { background: "#eef2fa", color: "#1d2f5c", padding: "10px 12px", borderRadius: 8, fontSize: 13, marginBottom: 12, lineHeight: 1.45 },
  audienceBox: { background: "#f7f9fd", border: "1px solid #dfe5f2", borderRadius: 10, padding: "10px 12px", marginTop: 8 },
  audienceCount: { fontSize: 16, fontWeight: 800, color: "#124096" },
  audienceDetail: { fontSize: 13, color: "#444", marginTop: 2 },
  audienceWarn: { fontSize: 13, color: "#8a5300", marginTop: 4 },
  summary: { background: "#e3f5e8", color: "#0f4f22", padding: "10px 12px", borderRadius: 8, fontSize: 13, marginTop: 10, lineHeight: 1.45 },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12, marginTop: 8 },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 },
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
    whiteSpace: "nowrap",
  },
};

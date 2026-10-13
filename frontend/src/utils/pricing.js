// Reads pricing straight from GET /api/members/meta (planPrices,
// yearlyPrices) - the formula itself lives only in the backend
// (backend/billing/models.py price_for()), never duplicated here, so the
// preview shown in a form can't drift from what's actually charged.
//
// Returns { amount, originalAmount, hasPromo } or null if prices haven't
// loaded yet. For "1 Month" there's no promo, just the plan's monthly
// price. For "1 Year", originalAmount (12x monthly, undiscounted) is
// shown struck through next to amount (the real, discounted price).
export function getPriceInfo(meta, plan, duration) {
  if (!plan || !duration || !meta) return null;

  if (duration === "1 Year") {
    const yearly = meta.yearlyPrices?.[plan];
    if (!yearly) return null;
    return { amount: yearly.discounted, originalAmount: yearly.original, hasPromo: true };
  }

  const monthly = meta.planPrices?.[plan];
  if (monthly === undefined) return null;
  return { amount: monthly, originalAmount: null, hasPromo: false };
}

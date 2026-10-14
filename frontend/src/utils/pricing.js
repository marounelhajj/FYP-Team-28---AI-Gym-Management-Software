// Turns a plan's live monthly price (from GET /api/plans/pricing, i.e.
// fetchBranchPricing - already branch-promotion-aware) into what a
// receptionist/member should see for the chosen duration. The formula
// itself still lives only in the backend (backend/billing/models.py
// price_for()), never duplicated here - this is a preview only, so it
// can't drift from what's actually charged, but it also can't be trusted
// as the source of truth.
//
// Returns { amount, originalAmount, hasPromo } or null if the monthly
// price hasn't loaded yet. For "1 Month" there's no promo, just the
// monthly price. For "1 Year", originalAmount (12x monthly, undiscounted)
// is shown struck through next to amount (12x monthly minus the $20
// annual-prepay promo).
const YEARLY_MULTIPLIER = 12;
const YEARLY_PROMO_DISCOUNT = 20;

export function getPriceInfo(monthlyPrice, duration) {
  if (!duration || monthlyPrice === null || monthlyPrice === undefined) return null;
  const monthly = Number(monthlyPrice);
  if (Number.isNaN(monthly)) return null;

  if (duration === "1 Year") {
    const original = monthly * YEARLY_MULTIPLIER;
    return { amount: original - YEARLY_PROMO_DISCOUNT, originalAmount: original, hasPromo: true };
  }

  return { amount: monthly, originalAmount: null, hasPromo: false };
}

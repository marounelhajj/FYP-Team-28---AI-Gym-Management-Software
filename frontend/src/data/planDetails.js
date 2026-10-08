// Marketing copy for the public "browse plans" page. Plan NAMES must match
// Member.Plan on the backend exactly (fetched live from /api/members/meta
// so they never drift) - price and features here are illustrative
// placeholder content for this FYP demo, not real, finalized pricing.
export const PLAN_DETAILS = {
  Basic: {
    price: "$29",
    period: "/month",
    tagline: "Everything you need to get moving.",
    features: ["Full gym floor & equipment access", "Locker room access", "Access to your home branch"],
  },
  Standard: {
    price: "$49",
    period: "/month",
    tagline: "Our most popular plan.",
    features: [
      "Everything in Basic",
      "Unlimited group fitness classes",
      "1 guest pass per month",
    ],
  },
  Premium: {
    price: "$79",
    period: "/month",
    tagline: "For members who want it all.",
    features: [
      "Everything in Standard",
      "1 personal training session per month",
      "Access to all branches",
      "Priority class booking",
    ],
  },
};

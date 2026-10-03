// Mock member data.
// This stands in for the real database table until the team wires up
// Postgres (or whatever DB we land on). Swap getAllMembers() in
// members.repository.js for a real query and nothing else needs to change.

const BRANCHES = ["Hamra", "Achrafieh", "Jnah", "Zalka"];
const STATUSES = ["Active", "Frozen", "Cancelled"];
const PLANS = ["Basic", "Standard", "Premium"];

const FIRST_NAMES = [
  "Ali", "Maroun", "Ahmad", "Omar", "Layla", "Nour", "Rami", "Dana",
  "Karim", "Sara", "Hassan", "Mira", "Jad", "Yara", "Tarek", "Lina",
  "Ziad", "Nadine", "Fadi", "Rana",
];
const LAST_NAMES = [
  "Salloum", "El Hajj", "Yateem", "Doughan", "Khoury", "Haddad", "Saad",
  "Nassar", "Chami", "Aoun", "Sleiman", "Fakih", "Mansour", "Rizk",
];

function seededMembers() {
  const members = [];
  let id = 1;
  for (let i = 0; i < 48; i++) {
    const first = FIRST_NAMES[i % FIRST_NAMES.length];
    const last = LAST_NAMES[(i * 3 + 1) % LAST_NAMES.length];
    const branch = BRANCHES[i % BRANCHES.length];
    const status = STATUSES[i % STATUSES.length === 0 && i % 5 === 0 ? 1 : i % 7 === 0 ? 2 : 0];
    const plan = PLANS[i % PLANS.length];
    const joinDate = new Date(2024, i % 12, (i % 27) + 1).toISOString().slice(0, 10);

    members.push({
      id: id++,
      name: `${first} ${last}`,
      email: `${first}.${last}`.toLowerCase().replace(/\s+/g, "") + "@email.com",
      phone: `+961 7${(100000 + i * 37).toString().slice(0, 6)}`,
      status,
      branch,
      membershipPlan: plan,
      joinDate,
    });
  }
  return members;
}

const members = seededMembers();

module.exports = { members, BRANCHES, STATUSES, PLANS };

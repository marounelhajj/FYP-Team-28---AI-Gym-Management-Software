const express = require("express");
const { members, BRANCHES, STATUSES, PLANS } = require("../data/members");

const router = express.Router();

// GET /api/members
// Query params (all optional, all combinable):
//   q        - case-insensitive substring match on member name
//   status   - exact match: Active | Frozen | Cancelled
//   branch   - exact match: Hamra | Achrafieh | Jnah | Zalka
//   limit    - max results to return (default 25, max 100)
//   offset   - pagination offset (default 0)
//
// User story: "As a receptionist, I want to search and filter the member
// directory by name, membership status, or branch, so that I can quickly
// find a member's record."
router.get("/", (req, res) => {
  const { q, status, branch } = req.query;

  let limit = parseInt(req.query.limit, 10);
  if (!Number.isFinite(limit) || limit <= 0) limit = 25;
  limit = Math.min(limit, 100);

  let offset = parseInt(req.query.offset, 10);
  if (!Number.isFinite(offset) || offset < 0) offset = 0;

  if (status && !STATUSES.includes(status)) {
    return res.status(400).json({
      error: `Invalid status "${status}". Must be one of: ${STATUSES.join(", ")}`,
    });
  }
  if (branch && !BRANCHES.includes(branch)) {
    return res.status(400).json({
      error: `Invalid branch "${branch}". Must be one of: ${BRANCHES.join(", ")}`,
    });
  }

  let results = members;

  if (q && q.trim()) {
    const needle = q.trim().toLowerCase();
    results = results.filter((m) => m.name.toLowerCase().includes(needle));
  }
  if (status) {
    results = results.filter((m) => m.status === status);
  }
  if (branch) {
    results = results.filter((m) => m.branch === branch);
  }

  const total = results.length;
  const page = results.slice(offset, offset + limit);

  res.json({
    total,
    limit,
    offset,
    results: page,
  });
});

// GET /api/members/meta
// Returns the filter option lists so the frontend never hardcodes them.
router.get("/meta", (req, res) => {
  res.json({ branches: BRANCHES, statuses: STATUSES, plans: PLANS });
});

// GET /api/members/:id
router.get("/:id", (req, res) => {
  const id = parseInt(req.params.id, 10);
  const member = members.find((m) => m.id === id);
  if (!member) {
    return res.status(404).json({ error: `Member ${req.params.id} not found` });
  }
  res.json(member);
});

module.exports = router;

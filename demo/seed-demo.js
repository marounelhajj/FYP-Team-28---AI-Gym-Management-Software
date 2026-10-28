/*
 * One command: a clean, realistic demo database.
 *
 *   npm run demo:seed
 *
 * Creates demo/.data/demo.sqlite3 from scratch (migrate + seed_demo) and writes
 * the generated logins to demo/.data/credentials.json. Both are git-ignored,
 * and the demo database is separate from backend/db.sqlite3, so your own dev
 * data is never touched. Needs backend/.venv (see SETUP.md).
 */
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const DATA = path.join(__dirname, ".data");
const DB = path.join(DATA, "demo.sqlite3");
const CREDENTIALS = path.join(DATA, "credentials.json");

function python() {
  const venv = process.platform === "win32"
    ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
    : path.join(BACKEND, ".venv", "bin", "python");
  return process.env.PYTHON || (fs.existsSync(venv) ? venv : "python");
}

function manage(args) {
  const result = spawnSync(python(), ["manage.py", ...args], {
    cwd: BACKEND,
    env: { ...process.env, GYM_DB_PATH: DB },
    stdio: "inherit",
  });
  if (result.status !== 0) {
    console.error(`manage.py ${args[0]} failed`);
    process.exit(result.status || 1);
  }
}

fs.mkdirSync(DATA, { recursive: true });
fs.rmSync(DB, { force: true });
console.log("[demo] Creating a fresh demo database at", path.relative(ROOT, DB));
manage(["migrate", "-v", "0"]);
manage(["seed_demo", "--credentials", CREDENTIALS]);
console.log("[demo] Done. Next: npm run demo:record");

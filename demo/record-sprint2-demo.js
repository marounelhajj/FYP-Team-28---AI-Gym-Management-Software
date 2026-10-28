/*
 * Records the Sprint 2 demo video of Fitness Zone (FYP Group 28), silent.
 *
 *   npm run demo:seed       once: a clean, realistic demo database + logins
 *   npm run demo:record     records every story, role by role
 *   npm run demo:record -- --headed     watch the browser while it records
 *
 * Output (git-ignored): demo/sprint2-demo.webm (raw) and demo/sprint2-demo.mp4
 * (H.264, no audio), plus demo/.data/recording-report.json (chapters, skipped
 * stories). The story order, logins and click paths are in
 * docs/sprint2-demo-script.md; keep the two in step.
 *
 * Needs: backend/.venv, frontend/node_modules, Google Chrome, ffmpeg on PATH,
 * and Playwright (`npm install` at the repo root, or PLAYWRIGHT_PATH). Ports
 * 4000 (Django) and 5173 (Vite) must be free. The app runs against the demo
 * database only (GYM_DB_PATH), never your dev data.
 *
 * Honest by design: a step that cannot be done fails; the story is then
 * skipped (and named in the report and on the summary card) instead of
 * showing something that did not happen.
 */
const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");

const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const FRONTEND = path.join(ROOT, "frontend");
const DATA = path.join(__dirname, ".data");
const DB = path.join(DATA, "demo.sqlite3");
const CREDENTIALS = path.join(DATA, "credentials.json");
const VIDEO_DIR = path.join(DATA, "video");
const WEBM = path.join(__dirname, "sprint2-demo.webm");
const MP4 = path.join(__dirname, "sprint2-demo.mp4");
const REPORT = path.join(DATA, "recording-report.json");
const APP = "http://localhost:5173";
const HEADED = process.argv.includes("--headed");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const log = (message) => console.log(`[demo] ${message}`);
// Every caption sentence stays on screen at least this long (the brief asks for 3 seconds).
const CAPTION_MS = 3200;
const BEAT = 700;

function python() {
  const venv = process.platform === "win32"
    ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
    : path.join(BACKEND, ".venv", "bin", "python");
  return process.env.PYTHON || (fs.existsSync(venv) ? venv : "python");
}

// ---------------------------------------------------------------------------
// Servers
// ---------------------------------------------------------------------------

function portIsFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer().once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => server.close(() => resolve(true)));
  });
}

async function waitFor(url, label) {
  for (let i = 0; i < 240; i++) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch {
      // not up yet
    }
    await sleep(500);
  }
  throw new Error(`${label} did not start`);
}

async function startServers() {
  for (const port of [4000, 5173]) {
    if (!(await portIsFree(port))) throw new Error(`Port ${port} is in use. Stop your dev servers first.`);
  }
  log("Starting Django (4000) on the demo database and Vite (5173)");
  const django = spawn(python(), ["manage.py", "runserver", "4000", "--noreload"], {
    cwd: BACKEND,
    env: { ...process.env, GYM_DB_PATH: DB },
    stdio: "ignore",
  });
  const vite = spawn(process.execPath, [path.join(FRONTEND, "node_modules", "vite", "bin", "vite.js"), "--port", "5173", "--strictPort"], {
    cwd: FRONTEND,
    stdio: "ignore",
  });
  await waitFor("http://localhost:4000/api/health", "Django");
  await waitFor(APP, "Vite");
  return () => {
    for (const child of [django, vite]) {
      if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      else child.kill();
    }
  };
}

// ---------------------------------------------------------------------------
// Authenticator codes (RFC 6238, same as backend/administration/totp.py)
// ---------------------------------------------------------------------------

const usedSteps = {};

function codeFor(username, secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.replace(/[\s=]/g, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  let step = Math.floor(Date.now() / 30000);
  if (usedSteps[username] !== undefined && step <= usedSteps[username]) step = usedSteps[username] + 1;
  usedSteps[username] = step;
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = crypto.createHmac("sha1", key).update(msg).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, "0");
}

// ---------------------------------------------------------------------------
// On-screen overlay: caption bar, title/summary cards and a visible cursor.
// Injected into every page; state lives in sessionStorage so it survives the
// full page loads in the script.
// ---------------------------------------------------------------------------

function installOverlay() {
  const STYLE = `
    #demo-caption{position:fixed;left:0;right:0;bottom:0;z-index:2147483646;padding:12px 28px 14px;background:rgba(10,14,24,.93);
      color:#fff;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;border-top:3px solid #4d8bff;display:none;pointer-events:none}
    #demo-caption .meta{font-size:13px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;color:#9db8ff;display:flex;gap:10px;align-items:center}
    #demo-caption .key{background:#4d8bff;color:#06122e;border-radius:6px;padding:2px 8px}
    #demo-caption .title{font-size:19px;font-weight:800;margin-top:3px}
    #demo-caption .sentence{font-size:17px;font-weight:500;margin-top:3px;color:#e8eefc}
    #demo-card{position:fixed;inset:0;z-index:2147483647;display:none;flex-direction:column;align-items:center;justify-content:center;
      background:radial-gradient(circle at 30% 20%,#17306b,#070b16 70%);color:#fff;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;text-align:center;padding:40px;pointer-events:none}
    #demo-card h1{font-size:54px;margin:0 0 14px;font-weight:900;letter-spacing:-1px}
    #demo-card h2{font-size:26px;margin:0 0 6px;font-weight:600;color:#b9cbff}
    #demo-card p{font-size:20px;margin:6px 0;color:#d6e0fa}
    #demo-card ul{list-style:none;padding:0;margin:14px 0 0;columns:2;column-gap:46px;text-align:left;font-size:17px;line-height:1.55}
    #demo-card li b{color:#8fb0ff;margin-right:8px}
    #demo-card li.skipped{color:#ff9b9b}
    #demo-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
      transition:transform .45s cubic-bezier(.22,.8,.3,1);transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))}
    #demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
      border:3px solid #ff3b5c;opacity:0}
    #demo-ripple.go{animation:demo-ripple .55s ease-out}
    @keyframes demo-ripple{0%{opacity:.95;transform:scale(.6)}100%{opacity:0;transform:scale(3.6)}}
  `;
  const read = (key) => {
    try {
      return JSON.parse(sessionStorage.getItem(key) || "null");
    } catch {
      return null;
    }
  };
  const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function mount() {
    if (document.getElementById("demo-caption")) return;
    const style = document.createElement("style");
    style.textContent = STYLE;
    const caption = Object.assign(document.createElement("div"), { id: "demo-caption" });
    const card = Object.assign(document.createElement("div"), { id: "demo-card" });
    const ripple = Object.assign(document.createElement("div"), { id: "demo-ripple" });
    const cursor = Object.assign(document.createElement("div"), { id: "demo-cursor" });
    cursor.innerHTML =
      '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.6L21 10.8z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.append(style, caption, card, ripple, cursor);

    const move = (x, y) => {
      cursor.style.transform = `translate(${x - 4}px, ${y - 2}px)`;
      sessionStorage.setItem("demoCursor", JSON.stringify([x, y]));
    };
    const saved = read("demoCursor");
    if (saved) {
      cursor.style.transition = "none";
      move(saved[0], saved[1]);
      requestAnimationFrame(() => requestAnimationFrame(() => (cursor.style.transition = "")));
    }
    window.addEventListener("mousemove", (e) => move(e.clientX, e.clientY), true);
    window.addEventListener(
      "mousedown",
      (e) => {
        ripple.style.left = `${e.clientX}px`;
        ripple.style.top = `${e.clientY}px`;
        ripple.classList.remove("go");
        void ripple.offsetWidth;
        ripple.classList.add("go");
      },
      true
    );

    window.__demoRender = () => {
      const c = read("demoCaption");
      caption.style.display = c ? "block" : "none";
      if (c) {
        caption.innerHTML =
          `<div class="meta"><span class="key">${esc(c.key)}</span><span>${esc(c.role)}</span></div>` +
          `<div class="title">${esc(c.title)}</div><div class="sentence">${esc(c.sentence)}</div>`;
      }
      const k = read("demoCard");
      card.style.display = k ? "flex" : "none";
      if (k) card.innerHTML = k.html;
    };
    window.__demoRender();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
}

// ---------------------------------------------------------------------------
// Recorder helpers
// ---------------------------------------------------------------------------

class Demo {
  constructor(page, creds) {
    this.page = page;
    this.creds = creds;
    this.chapters = [];
    this.skipped = [];
    this.shown = [];
    this.t0 = Date.now();
    this.current = null;
  }

  now() {
    return (Date.now() - this.t0) / 1000;
  }

  async store(key, value) {
    await this.page.evaluate(
      ([k, v]) => {
        if (v === null) sessionStorage.removeItem(k);
        else sessionStorage.setItem(k, JSON.stringify(v));
        if (window.__demoRender) window.__demoRender();
      },
      [key, value]
    );
  }

  async card(html, ms) {
    await this.store("demoCaption", null);
    await this.store("demoCard", { html });
    await sleep(ms);
    await this.store("demoCard", null);
    await sleep(250);
  }

  // One story: caption with the Jira key, title, role and a sentence that stays >= 3s.
  async story(def, steps) {
    this.current = def;
    const startedAt = this.now();
    log(`${def.key} ${def.title} (${def.role})`);
    try {
      await this.store("demoCaption", { key: def.key, role: def.role, title: def.title, sentence: def.sentence });
      await sleep(CAPTION_MS);
      await steps();
      this.chapters.push({ key: def.key, title: def.title, role: def.role, start: startedAt, end: this.now() });
      if (!this.shown.includes(def.key)) this.shown.push(def.key);
    } catch (error) {
      log(`  SKIPPED ${def.key}: ${error.message.split("\n")[0]}`);
      this.skipped.push({ key: def.key, title: def.title, reason: error.message.split("\n")[0] });
      await this.page.screenshot({ path: path.join(DATA, `failed-${def.key}.png`), timeout: 8000 }).catch(() => {});
      await this.page.goto(APP, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
    }
    await this.store("demoCaption", null).catch(() => {});
  }

  // Updates the sentence under the same caption and holds it for 3 seconds.
  async say(sentence, ms = CAPTION_MS) {
    const d = this.current;
    await this.store("demoCaption", { key: d.key, role: d.role, title: d.title, sentence });
    await sleep(ms);
  }

  async see(locator, timeout = 20000) {
    await locator.first().waitFor({ state: "visible", timeout });
  }

  async moveTo(locator) {
    const el = locator.first();
    await el.waitFor({ state: "visible", timeout: 20000 });
    await el.evaluate((node) => node.scrollIntoView({ block: "center", inline: "nearest" }));
    const box = await el.boundingBox();
    if (box) {
      await this.page.mouse.move(box.x + Math.min(box.width / 2, 70), box.y + box.height / 2, { steps: 6 });
      await sleep(380);
    }
    return el;
  }

  async click(locator, hold = 450) {
    const el = await this.moveTo(locator);
    await el.click();
    await sleep(hold);
  }

  async type(locator, text, delay = 40) {
    const el = await this.moveTo(locator);
    await el.click();
    await el.fill("");
    await el.pressSequentially(String(text), { delay });
    await sleep(250);
  }

  async choose(locator, option) {
    const el = await this.moveTo(locator);
    await el.selectOption(option);
    await sleep(600);
  }

  // Starts waiting for the browser download before the click that causes it, and never leaves a
  // rejected promise behind if the click fails.
  async download(action) {
    const pending = this.page.waitForEvent("download", { timeout: 30000 });
    pending.catch(() => {});
    await action();
    return pending;
  }

  async reveal(locator, hold = 1500) {
    await this.moveTo(locator);
    await sleep(hold);
  }

  async goto(pathname) {
    await this.page.goto(`${APP}${pathname}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await sleep(900);
  }

  // Form fields whose <label> is a sibling of the input rather than linked to it.
  field(label) {
    return this.page.locator(
      `xpath=//label[contains(normalize-space(), "${label}")]/following-sibling::*[self::input or self::select or self::textarea][1]`
    );
  }

  button(name, exact = true) {
    return this.page.getByRole("button", { name, exact });
  }

  radio(name) {
    return this.page.getByRole("radio", { name, exact: true });
  }

  // ---- sessions ----
  async staffLogin(username) {
    const c = this.creds.staff[username];
    await this.goto("/");
    await this.see(this.page.getByRole("heading", { name: "Staff Login" }));
    await this.type(this.page.locator('input[autocomplete="username"]'), username);
    await this.type(this.page.locator('input[type="password"]'), c.password, 25);
    await this.click(this.button("Login"));
    await this.see(this.page.getByRole("heading", { name: "Two-Factor Sign-In" }));
    await this.type(this.page.locator('input[autocomplete="one-time-code"]'), codeFor(username, c.totpSecret), 70);
    await this.click(this.button("Verify"));
    await this.see(this.page.getByText("Logged in successfully", { exact: false }));
    await sleep(1000);
    await this.click(this.button("Continue"), 900);
  }

  async memberLogin(key, { expectOk = true } = {}) {
    const c = this.creds.members[key];
    await this.goto("/");
    await this.click(this.button("Login or sign up here"), 700);
    await this.see(this.page.getByRole("heading", { name: "Member Login" }));
    await this.type(this.field("Username"), c.username);
    await this.type(this.field("Password"), c.password, 25);
    await this.click(this.button("Login"));
    if (expectOk) await this.see(this.page.getByRole("heading", { name: /^Welcome,/ }));
  }

  async logout() {
    await this.click(this.button("Log out"), 900);
  }
}

// ---------------------------------------------------------------------------
// The stories (keep in step with docs/sprint2-demo-script.md)
// ---------------------------------------------------------------------------

const ADMIN = "System Administrator";
const GM = "General Manager";
const BM = "Branch Manager";
const REC = "Receptionist";
const MEMBER = "Member";
const ONLY = (process.argv.find((a) => a.startsWith("--only=")) || "").slice(7).split(",").filter(Boolean);
const want = (persona) => ONLY.length === 0 || ONLY.includes(persona);

async function recordStories(d) {
  const { page, creds } = d;
  const named = creds.named;

  // =========================== System Administrator ==========================
  if (want("admin")) {
  await d.staffLogin("mfakhoury");

  await d.story({
    key: "SCRUM-124", role: ADMIN, title: "Sensitive actions are written to a permanent audit log",
    sentence: "Every sign-in, edit, payment and cancellation is recorded automatically: who did it, what, when and where.",
  }, async () => {
    await d.click(d.button("Audit Log"), 900);
    await d.see(page.getByRole("heading", { name: "Audit Log", exact: true }));
    await d.reveal(page.locator("table tbody tr").first(), 1500);
    await d.click(page.locator("table tbody tr").first(), 1500);
    await d.say("Open an entry to see exactly what changed. Entries can't be edited or deleted afterwards.");
  });

  await d.story({
    key: "SCRUM-125", role: ADMIN, title: "Search and filter the audit log",
    sentence: "To investigate an incident, filter by action type, branch, user and date range.",
  }, async () => {
    await d.click(d.button("Audit Log"), 700);
    await d.choose(page.locator("select").filter({ hasText: "All actions" }), { label: "Membership cancelled" });
    await d.choose(page.locator("select").filter({ hasText: "All branches" }), "Hamra");
    await d.reveal(page.locator("table tbody tr").first(), 1800);
    await d.say("Only Hamra's membership cancellations remain. Add a name to narrow it further.");
    await d.click(d.button("Clear filters"), 900);
    await d.type(page.getByPlaceholder("Name or username"), "Dana");
    await sleep(1800);
    await d.click(d.button("Clear filters"), 700);
  });

  await d.story({
    key: "SCRUM-126", role: ADMIN, title: "Export a filtered audit log as CSV",
    sentence: "The filtered view can be exported as a CSV file to share as evidence in a dispute or review.",
  }, async () => {
    await d.click(d.button("Audit Log"), 700);
    await d.choose(page.locator("select").filter({ hasText: "All branches" }), "Jnah");
    await sleep(1000);
    const file = await d.download(() => d.click(d.button("Export CSV"), 600));
    log(`  downloaded ${file.suggestedFilename()}`);
    await d.see(page.getByText("Downloaded", { exact: false }));
    await d.reveal(page.getByText("Downloaded", { exact: false }), 1800);
    await d.say("The export itself is written to the log, so there is a record of who took a copy.");
    await d.click(d.button("Clear filters"), 700);
  });

  await d.story({
    key: "SCRUM-73", role: ADMIN, title: "Check-ins and cancellations logged as AI training data",
    sentence: "From the first release, every check-in and cancellation is stored as a training event for the future AI models.",
  }, async () => {
    await d.goto("/api/training-events?format=json&limit=6");
    await d.see(page.getByText("results", { exact: false }));
    await sleep(2500);
    await d.say("Each event has a type, time, branch and member id. No names, emails or phone numbers.");
    await d.goto("/");
  });

  await d.logout();
  }

  // ============================== General Manager ============================
  if (want("gm")) {
  await d.staffLogin("rhaddad");

  await d.story({
    key: "SCRUM-17", role: GM, title: "Revenue and expenses for each branch",
    sentence: "The general manager compares every branch's revenue, expenses and net side by side.",
  }, async () => {
    await d.click(d.button("Financial Report"), 900);
    await d.see(page.getByRole("heading", { name: "Financial Report", exact: true }));
    await d.reveal(page.locator("table").first(), 2200);
    await d.choose(page.locator("select").first(), "Hamra");
    await d.say("Filter to one branch or a date range to see where the money comes from.");
    await d.click(d.button("Clear filters"), 700);
  });

  await d.story({
    key: "SCRUM-96", role: GM, title: "History of membership freezes and cancellations by branch",
    sentence: "Freezes and cancellations are counted per branch, so retention problems stand out.",
  }, async () => {
    await d.click(d.button("Retention"), 900);
    await d.see(page.getByRole("heading", { name: /Retention/ }));
    await d.reveal(page.locator("table").first(), 2200);
    await d.reveal(page.getByRole("heading", { name: "History" }), 1800);
    await d.choose(page.locator("select").first(), "Jnah");
    await d.say("Narrow it to one branch to read the individual events behind the numbers.");
  });

  await d.story({
    key: "SCRUM-26", role: GM, title: "Branch Finances: a general manager can open any branch",
    sentence: "The same Branch Finances page that branch managers use lets a general manager switch to any branch.",
  }, async () => {
    await d.click(d.button("Branch Finances"), 900);
    await d.see(page.getByText("Revenue by source"));
    await d.choose(page.locator("select.bf-select").first(), "Jnah");
    await d.reveal(page.getByText("Revenue by source"), 2200);
  });

  await d.logout();
  }

  // ============================== Branch Manager =============================
  if (want("bm")) {
  await d.staffLogin("kabboud");

  await d.story({
    key: "SCRUM-127", role: BM, title: "Live headcount for my branch",
    sentence: "The branch manager sees how many members are inside right now, updating live.",
  }, async () => {
    await d.click(d.button("Live Headcount"), 900);
    await d.see(page.getByText("members inside now", { exact: false }));
    await d.reveal(page.getByText("members inside now", { exact: false }), 2400);
    await d.say("Members who forget to check out are closed automatically after four hours.");
  });

  await d.story({
    key: "SCRUM-129", role: BM, title: "Headcount by hour, today vs. the usual weekday",
    sentence: "Today's hour-by-hour headcount is drawn against the average of the same weekday over past weeks.",
  }, async () => {
    await d.reveal(page.getByRole("heading", { name: "Today by hour" }), 2800);
    await d.click(page.getByText("Show as a table"), 900);
    await d.reveal(page.locator("details table").first(), 2200);
    await d.say("That shows when the peaks really fall, so staffing can follow them.");
  });

  await d.story({
    key: "SCRUM-26", role: BM, title: "Branch Finances: my branch's revenue and expenses",
    sentence: "The branch manager sees only their own branch: revenue by source, expenses by category and the net for the period.",
  }, async () => {
    await d.click(d.button("Branch Finances"), 900);
    await d.see(page.getByText("Revenue by source"));
    await d.reveal(page.locator("figure").first(), 2400);
    await d.click(d.radio("Last month"), 1800);
    await d.click(d.radio("Custom"), 1500);
    await d.click(d.radio("This month"), 1200);
    await d.say("Expenses are kept by the branch manager: add one, correct it, delete it.");
    await d.click(d.button("Add expense").first(), 700);
    await d.choose(page.locator("select.bf-select").first(), "Utilities");
    await d.type(page.getByLabel("Amount ($)"), "85");
    await d.type(page.getByLabel("Note"), "Generator fuel");
    await d.click(d.button("Add expense").last(), 1500);
    await d.see(page.getByText("Expense added."));
    await d.click(page.getByRole("button", { name: /^Edit Utilities expense of \$85\.00/ }), 700);
    await d.type(page.getByLabel("Amount ($)"), "92.50");
    await d.click(d.button("Save changes"), 1500);
    await d.see(page.getByText("Expense updated."));
    await d.click(page.getByRole("button", { name: /^Delete Utilities expense of \$92\.50/ }), 700);
    await d.click(d.button("Delete"), 1200);
    await d.see(page.getByText("Expense deleted."));
    await d.say("The server enforces the branch: asking for Jnah's finances is refused.");
    await d.goto("/api/finance/branch?branch=Jnah&format=json");
    await d.see(page.getByText("only see finances for your own branch", { exact: false }));
    await sleep(2500);
    await d.goto("/");
  });

  await d.logout();
  }

  // ================================ Receptionist =============================
  if (want("rec")) {
  await d.staffLogin("dsarkis");
  const sami = named.renewal;
  const nour = named.flag;
  const dana = named.card;

  await d.story({
    key: "SCRUM-74", role: REC, title: "Door access follows membership status automatically",
    sentence: `${sami.name}'s subscription lapsed, so entry is refused with the reason. No manual card handling.`,
  }, async () => {
    await d.click(d.button("Check-In"), 900);
    await d.type(page.getByLabel("Membership ID"), String(sami.id));
    await d.click(d.button("Check In"), 900);
    await d.see(page.getByText("Entry denied"));
    await d.reveal(page.getByText("Entry denied"), 2500);
  });

  await d.story({
    key: "SCRUM-55", role: REC, title: "Renew a membership and update the payment method",
    sentence: `At the desk, ${sami.name} renews in person, and the receptionist updates ${nour.name}'s card on file.`,
  }, async () => {
    await d.click(d.button("Member Directory"), 900);
    await d.type(page.getByLabel("Search members by name"), sami.name);
    await d.see(page.getByRole("cell", { name: sami.name }));
    await d.click(d.button("Subscribe"), 900);
    await d.see(page.getByRole("heading", { name: "Subscribe", exact: true }));
    await d.choose(page.locator("select").filter({ hasText: "Select a plan" }), "Basic");
    await d.click(d.radio("1 Month"), 600);
    await d.click(d.radio("Cash"), 900);
    await d.click(page.getByRole("button", { name: /^Subscribe & charge/ }), 1200);
    await d.see(page.getByText("Subscription processed for", { exact: false }));
    await d.reveal(page.getByText("Subscription processed for", { exact: false }), 2200);
    await d.type(page.getByLabel("Search members by name"), nour.name);
    await d.see(page.getByRole("cell", { name: nour.name }));
    await d.click(d.button("See Subscription Details"), 900);
    await d.see(page.getByRole("heading", { name: "Subscription Details" }));
    await d.click(page.getByRole("button", { name: /^(Update|Add payment method)$/ }), 800);
    await d.click(d.radio("Card"), 500);
    await d.type(d.field("Name on card"), nour.name);
    await d.type(d.field("Card number"), "1881");
    await d.choose(page.locator("select").filter({ hasText: "MM" }), "9");
    await d.choose(page.locator("select").filter({ hasText: "YYYY" }), String(new Date().getFullYear() + 3));
    await d.click(d.button("Save payment method"), 1000);
    await d.see(page.getByText("Payment method updated."));
    await d.reveal(page.getByText("Payment method updated."), 1800);
    await d.click(d.button("Close"), 700);
  });

  await d.story({
    key: "SCRUM-74", role: REC, title: "Door access follows membership status automatically (after payment)",
    sentence: `Once ${sami.name} has paid, the same check-in lets them in.`,
  }, async () => {
    await d.click(d.button("Check-In"), 900);
    await d.type(page.getByLabel("Membership ID"), String(sami.id));
    await d.click(d.button("Check In"), 900);
    await d.see(page.getByText(`Welcome, ${sami.name}`, { exact: false }));
    await d.reveal(page.getByText(`Welcome, ${sami.name}`, { exact: false }), 2200);
  });

  await d.story({
    key: "SCRUM-56", role: REC, title: "Flag a suspicious or duplicate check-in",
    sentence: `${nour.name} checks in, and the receptionist flags the attempt as suspected membership sharing.`,
  }, async () => {
    await d.type(page.getByLabel("Membership ID"), String(nour.id));
    await d.click(d.button("Check In"), 900);
    await d.see(page.getByText(`Welcome, ${nour.name}`, { exact: false }));
    await d.click(page.getByRole("tab", { name: /Recent Check-Ins/ }), 900);
    await d.click(d.button("Flag").first(), 900);
    await d.see(page.getByRole("heading", { name: "Flag Check-In Attempt" }));
    await d.click(d.radio("Membership sharing"), 600);
    await d.type(page.getByLabel("Note (optional)"), "Different person at the desk than on the card photo");
    await d.click(d.button("Flag attempt"), 1200);
    await d.click(page.getByRole("tab", { name: /Flagged Attempts/ }), 900);
    await d.reveal(page.getByText(nour.name).first(), 2200);
    await d.say("Until the flag is resolved, the desk is told to check photo ID and door readers send them to the desk.");
  });

  await d.story({
    key: "SCRUM-32", role: REC, title: "Reissue a lost access card or QR code",
    sentence: `${dana.name} lost their card: the receptionist issues a new one, and the old code stops working at once.`,
  }, async () => {
    await d.click(d.button("Check-In"), 700);
    await d.type(page.getByLabel("Membership ID"), String(dana.id));
    await d.click(d.button("Reissue card"), 900);
    await d.see(page.getByRole("heading", { name: "Access Card" }));
    await d.click(d.radio("Lost"), 700);
    await d.click(page.getByRole("checkbox"), 700);
    await d.click(page.getByRole("button", { name: /^Issue card/ }), 1200);
    await d.see(page.getByText("no longer works", { exact: false }));
    await d.reveal(page.getByText("no longer works", { exact: false }), 2200);
    await d.click(d.button("Close"), 700);
  });

  await d.story({
    key: "SCRUM-31", role: REC, title: "Point-of-sale purchases for retail items",
    sentence: "At the front desk, the receptionist rings up protein and water, takes cash and prints a receipt.",
  }, async () => {
    await d.click(d.button("Shop"), 900);
    await d.see(page.getByRole("heading", { name: "Shop", exact: true }));
    await d.click(page.getByRole("button", { name: "Add Whey Protein 1kg (Chocolate)" }), 700);
    await d.click(page.getByRole("button", { name: "Add Water Bottle 500ml" }), 700);
    await d.click(d.radio("Cash"), 600);
    await d.click(d.button("Exact"), 700);
    await d.click(page.getByRole("button", { name: /^Charge \$/ }), 1200);
    await d.see(page.getByRole("dialog", { name: "Receipt" }));
    await d.reveal(page.getByRole("dialog", { name: "Receipt" }), 2600);
    await d.click(d.button("Close"), 700);
  });

  await d.logout();
  }

  // ================================== Member =================================
  if (want("member")) {
  await d.memberLogin("memberLogin");

  await d.story({
    key: "SCRUM-39", role: MEMBER, title: "Membership details and billing history",
    sentence: "A member sees their plan, renewal date and every payment they've made.",
  }, async () => {
    await d.reveal(page.getByText("Renewal date"), 1800);
    await d.reveal(page.getByRole("heading", { name: "Billing history" }), 3000);
  });

  await d.story({
    key: "SCRUM-88", role: MEMBER, title: "Update my profile and payment method myself",
    sentence: "Routine changes no longer need a front-desk visit: contact details and the card on file.",
  }, async () => {
    await d.click(d.button("Edit profile"), 900);
    await d.see(page.getByRole("heading", { name: "Edit Your Profile" }));
    await d.type(d.field("Phone"), "+961 71 555 019");
    await d.click(d.button("Save changes"), 1000);
    await d.see(page.getByText("Your profile was updated."));
    await d.reveal(page.getByText("Your profile was updated."), 1500);
    await d.click(d.button("Update"), 900);
    await d.type(d.field("Name on card"), "Lea Haddad");
    await d.type(page.getByLabel("Last 4 digits of the card"), "9921");
    await d.choose(page.getByLabel("Expiry month"), "6");
    await d.choose(page.getByLabel("Expiry year"), String(new Date().getFullYear() + 3));
    await d.click(d.button("Save payment method"), 1000);
    await d.see(page.getByText("Your payment method was updated."));
    await d.reveal(page.getByText("Your payment method was updated."), 1800);
  });

  await d.story({
    key: "SCRUM-41", role: MEMBER, title: "Freeze or cancel my membership in the app",
    sentence: "Members control their own subscription: freeze it, resume it, or cancel with a confirmation step.",
  }, async () => {
    await d.click(d.button("Freeze membership"), 1000);
    await d.see(page.getByText("Your membership is frozen", { exact: false }));
    await d.reveal(page.getByText("Your membership is frozen", { exact: false }), 2000);
    await d.click(d.button("Resume membership"), 1000);
    await d.see(page.getByText("Your membership is active again.", { exact: false }));
    await d.click(d.button("Cancel membership"), 900);
    await d.reveal(page.getByText("Cancel your membership?", { exact: false }), 2200);
    await d.click(d.button("Never mind"), 900);
  });

  await d.logout();
  }

  if (want("delete")) {
  await d.memberLogin("deleteLogin");
  await d.story({
    key: "SCRUM-62", role: MEMBER, title: "Export or delete my personal data",
    sentence: "A member can download everything held about them, or ask for their personal data to be deleted.",
  }, async () => {
    await d.reveal(page.getByRole("heading", { name: /Your data/ }), 1200);
    const file = await d.download(() => d.click(d.button("Download my data"), 800));
    log(`  downloaded ${file.suggestedFilename()}`);
    await d.reveal(page.getByText("Downloaded fitness-zone-my-data", { exact: false }), 2200);
    await d.say("Deleting needs the password and the word DELETE. Payments and waivers stay on file, anonymized.");
    await d.click(d.button("Delete my data"), 800);
    await d.type(page.getByLabel("Your password"), creds.members.deleteLogin.password, 25);
    await d.type(page.getByLabel("Type DELETE to confirm"), "DELETE");
    await d.click(d.button("Permanently delete my data"), 1500);
    await d.see(page.getByRole("heading", { name: "Member Login" }));
    await d.say("They're signed out, and the deleted account can no longer log in.");
    await d.type(d.field("Username"), creds.members.deleteLogin.username);
    await d.type(d.field("Password"), creds.members.deleteLogin.password, 25);
    await d.click(d.button("Login"), 900);
    await d.see(page.getByText("Invalid username or password."));
    await d.reveal(page.getByText("Invalid username or password."), 2200);
  });
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const TITLE_CARD = `
  <h1>Fitness Zone</h1><h2>Sprint 2 Demo</h2><p>FYP Group 28 &middot; AUB EECE 501</p>
  <p style="margin-top:26px;color:#8fb0ff">AI gym management software &middot; recorded 28 October 2026</p>`;

function summaryCard(d, order) {
  const rows = order.map((s) => {
    const skipped = d.skipped.find((x) => x.key === s.key);
    return skipped
      ? `<li class="skipped"><b>${s.key}</b>${s.title} (not shown)</li>`
      : `<li><b>${s.key}</b>${s.title}</li>`;
  });
  return `<h1 style="font-size:40px">Sprint 2: what we built</h1>
    <h2 style="font-size:20px">${d.shown.length} stories shown &middot; Fitness Zone, FYP Group 28</h2><ul>${rows.join("")}</ul>`;
}

function encode() {
  const files = fs.readdirSync(VIDEO_DIR).filter((f) => f.endsWith(".webm"));
  if (files.length !== 1) throw new Error(`Expected one recorded video, found ${files.length}`);
  fs.copyFileSync(path.join(VIDEO_DIR, files[0]), WEBM);
  const result = spawnSync(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-i", WEBM, "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart", MP4],
    { encoding: "utf8" }
  );
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.stderr}`);
}

function duration(file) {
  const probe = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", file], { encoding: "utf8" });
  return Number(probe.stdout.trim());
}

(async () => {
  if (!fs.existsSync(CREDENTIALS) || !fs.existsSync(DB)) {
    throw new Error("No demo data yet. Run `npm run demo:seed` first.");
  }
  const creds = JSON.parse(fs.readFileSync(CREDENTIALS, "utf8"));
  fs.rmSync(VIDEO_DIR, { recursive: true, force: true });
  fs.mkdirSync(VIDEO_DIR, { recursive: true });

  const stop = await startServers();
  process.on("exit", stop);
  let browser;
  let demo;
  try {
    browser = await chromium.launch({ channel: "chrome", headless: !HEADED, slowMo: 400 });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
      recordVideo: { dir: VIDEO_DIR, size: { width: 1280, height: 720 } },
      acceptDownloads: true,
    });
    await context.addInitScript(installOverlay);
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    page.on("pageerror", (e) => log(`  page error: ${e.message}`));
    demo = new Demo(page, creds);

    await page.goto(APP, { waitUntil: "domcontentloaded", timeout: 120000 });
    await sleep(1500);
    await demo.card(TITLE_CARD, 4500);
    await recordStories(demo);

    const order = [
      ["SCRUM-124", "Audit log"], ["SCRUM-125", "Audit search and filter"], ["SCRUM-126", "Audit CSV export"],
      ["SCRUM-73", "AI training event log"], ["SCRUM-17", "Revenue and expenses by branch"],
      ["SCRUM-96", "Freeze and cancel history"], ["SCRUM-127", "Live headcount"], ["SCRUM-129", "Headcount by hour"],
      ["SCRUM-26", "Branch Finances"], ["SCRUM-74", "Door access from membership status"],
      ["SCRUM-55", "Renewals and payment methods"], ["SCRUM-56", "Flag suspicious check-ins"],
      ["SCRUM-32", "Reissue access cards"], ["SCRUM-31", "Retail point of sale"],
      ["SCRUM-39", "Billing history"], ["SCRUM-88", "Update profile and payment method"],
      ["SCRUM-41", "Freeze or cancel in the app"], ["SCRUM-62", "Data export and deletion"],
    ].map(([key, title]) => ({ key, title }));
    await demo.card(summaryCard(demo, order), 7000);
    await context.close();
  } finally {
    await browser?.close().catch(() => {});
    stop();
  }

  encode();
  const seconds = duration(MP4);
  const sizeMb = fs.statSync(MP4).size / 1e6;
  fs.writeFileSync(REPORT, JSON.stringify({
    mp4: MP4, webm: WEBM, seconds, sizeMb, shown: demo.shown, skipped: demo.skipped, chapters: demo.chapters,
  }, null, 2));
  log(`Video: ${MP4}`);
  log(`Length ${(seconds / 60).toFixed(1)} min, ${sizeMb.toFixed(1)} MB, ${demo.shown.length} stories shown`);
  if (demo.skipped.length) {
    log(`SKIPPED: ${demo.skipped.map((s) => `${s.key} (${s.reason})`).join("; ")}`);
    process.exitCode = 1;
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

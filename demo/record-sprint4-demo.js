/*
 * Records the Sprint 4 demo video of Fitness Zone (FYP Group 28), silent.
 *
 *   npm run demo:seed       once: a clean, realistic demo database + logins
 *   npm run demo:record     records every story, role by role
 *   npm run demo:record -- --headed     watch the browser while it records
 *
 * Output (git-ignored): demo/sprint4-demo.webm (raw) and demo/sprint4-demo.mp4
 * (H.264, no audio), plus demo/.data/recording-report.json (chapters, skipped
 * stories). The story order, logins and click paths are in
 * docs/sprint4-demo-script.md; keep the two in step.
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
const WEBM = path.join(__dirname, "sprint4-demo.webm");
const MP4 = path.join(__dirname, "sprint4-demo.mp4");
const REPORT = path.join(DATA, "recording-report.json");
const APP = "http://localhost:5173";
const HEADED = process.argv.includes("--headed");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const log = (message) => console.log(`[demo] ${message}`);
// Every caption sentence stays on screen at least this long (the brief asks for 3 seconds).
const CAPTION_MS = 3000;
const BEAT = 700;
// Holds after clicks and on results, scaled down to keep the video short.
const PACE = 0.7;

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
    #demo-card ul{list-style:none;padding:0;margin:14px 0 0;columns:1;text-align:left;font-size:17px;line-height:1.55}
    #demo-card li b{color:#8fb0ff;margin-right:8px}
    #demo-card li.skipped{color:#ff9b9b}
    #demo-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
      transition:transform .45s cubic-bezier(.22,.8,.3,1);transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.55))}
    #demo-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;
      border:3px solid #ff3b5c;opacity:0}
    #demo-ripple.go{animation:demo-ripple .55s ease-out}
    body::after{content:"";display:block;height:130px}
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
    await sleep(hold * PACE);
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
    await sleep(hold * PACE);
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
// The stories (keep in step with docs/sprint4-demo-script.md)
// ---------------------------------------------------------------------------

const BM = "Branch Manager";
const GM = "General Manager";
const REC = "Receptionist";
const ONLY = (process.argv.find((a) => a.startsWith("--only=")) || "").slice(7).split(",").filter(Boolean);
const want = (part) => ONLY.length === 0 || ONLY.includes(part);

function isoDay(offset) {
  const d = new Date(Date.now() + offset * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// The visible rows of the main call list (not "Below the cap").
async function callListNames(page) {
  const table = page.locator("table").first();
  const names = await table.locator("tbody tr td:nth-child(2)").allInnerTexts();
  return names.map((n) => n.split("\n")[0].replace(/\s*(Frozen|Active|Cancelled)\s*$/, "").trim()).filter(Boolean);
}

function row(page, name) {
  return page.locator("table").first().locator("tbody tr").filter({ hasText: name }).first();
}

async function recordStories(d) {
  const { page } = d;
  const state = {};

  // ============================== Branch Manager =============================
  if (want("bm")) {
    await d.staffLogin("kabboud");

    await d.story({
      key: "SCRUM-118", role: BM, title: "A ranked list of members at risk of leaving",
      sentence: "Every Monday each member of Hamra is scored; the branch manager sees who to call first, highest risk at the top.",
    }, async () => {
      await d.click(d.button("At-Risk Members"), 1500);
      await d.see(page.getByText("Why they're on the list"));
      await d.reveal(page.getByText(/calls? to make/), 1800);
      await d.say("Hamra has months of history, so its list comes from a learned model, validated on held-out weeks.");
      await d.reveal(page.getByText(/Learned model/), 2200);
      await d.reveal(page.locator("table").first().locator("tbody tr").first(), 2000);
      await d.say("Refresh now re-scores the branch on demand; otherwise the weekly job does it.");
      await d.click(d.button("Refresh now"), 600);
      await d.see(page.getByText(/refresh now by Karim Abboud/));
      await d.reveal(page.getByText(/refresh now by Karim Abboud/), 2200);
    });

    await d.story({
      key: "SCRUM-119", role: BM, title: "The reasons behind each member's ranking",
      sentence: "Each member shows two or three reasons in plain language, with the member's real numbers, not raw scores.",
    }, async () => {
      const first = page.locator("table").first().locator("tbody tr").first();
      await d.reveal(first.locator("li").first(), 2600);
      await d.say("Under each reason is a short talking point for the person making the call.");
      await d.reveal(first.getByText(/^Say:/).first(), 2600);
      const second = page.locator("table").first().locator("tbody tr").nth(1);
      await d.reveal(second.locator("li").first(), 2200);
      await d.say("Talking points can be hidden for a compact list.");
      await d.click(page.getByText("Talking points", { exact: true }), 1400);
      await d.reveal(first, 1600);
      await d.click(page.getByText("Talking points", { exact: true }), 1200);
    });

    await d.story({
      key: "SCRUM-120", role: BM, title: "Cap the list to the calls staff can make this week",
      sentence: "The team can make 5 calls this week, so the branch manager sets the weekly capacity from 8 to 5.",
    }, async () => {
      await d.reveal(page.locator("#call-capacity"), 1200);
      await d.type(page.locator("#call-capacity"), "5", 120);
      await d.click(d.button("Set"), 900);
      await d.see(page.getByText("Call capacity set to 5"));
      await sleep(1200);
      await d.say("The call list now holds the top 5; everyone else stays visible, collapsed, below the cap.");
      await d.see(page.getByText(/calls? to make/));
      await d.reveal(page.getByText(/0 of 5 done/), 1800);
      await d.click(page.getByRole("button", { name: /Below the cap/ }), 1500);
      const below = page.locator("table").nth(1).locator("tbody tr").first();
      await d.reveal(below, 2200);
      await d.click(page.getByRole("button", { name: /Below the cap/ }), 900);
      state.callList = await callListNames(page);
      if (state.callList.length < 3) throw new Error(`Expected at least 3 members on the call list, found ${state.callList.length}`);
    });
    await d.logout();
  }

  // ============================== General Manager ============================
  if (want("gm")) {
    await d.staffLogin("rhaddad");
    await d.story({
      key: "SCRUM-118", role: GM, title: "A new branch falls back to the rule-based score",
      sentence: "The general manager can open any branch. Zalka opened seven weeks ago and has no cancellation history yet.",
    }, async () => {
      await d.click(d.button("At-Risk Members"), 1500);
      await d.see(page.getByText("Why they're on the list"));
      await d.choose(page.getByLabel("Branch"), "Zalka");
      await d.see(page.getByText(/at Zalka this week/));
      await d.say("With too little history for a model, Zalka is scored by the weighted rules, and the page says why.");
      await d.reveal(page.getByText("Rule-based score"), 1800);
      await d.reveal(page.getByText(/not enough history yet/), 2600);
      await d.reveal(page.locator("table").first().locator("tbody tr").first(), 2400);
    });
    await d.logout();
  }

  // =============================== Receptionist ==============================
  if (want("rec")) {
    await d.staffLogin("dsarkis");
    const names = state.callList || [];
    await d.story({
      key: "SCRUM-68", role: REC, title: "Log the outcome of each retention call",
      sentence: "The receptionist works through the call list and logs each call: reached, no answer, saved or cancelled anyway.",
    }, async () => {
      await d.click(d.button("At-Risk Members"), 1500);
      await d.see(page.getByText("Why they're on the list"));
      const list = names.length >= 3 ? names : await callListNames(page);
      const [saved, noAnswer, reached] = list;
      state.saved = saved;

      await d.click(row(page, saved).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("Saved"), 500);
      await d.type(page.getByPlaceholder("What did they say?"), "Busy with exams. Renewing on Friday.", 35);
      await d.moveTo(page.locator('input[type="date"]'));
      await page.locator('input[type="date"]').fill(isoDay(3));
      await sleep(500);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`for ${saved}`));
      await d.say(`${saved} was saved, so they drop off this week's call list.`);

      await d.click(row(page, noAnswer).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("No answer"), 900);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`No answer logged for ${noAnswer}`));
      await d.say("No answer keeps them on the list until the end of the week, so the call can be tried again.");
      await d.reveal(row(page, noAnswer).getByRole("button", { name: "Try again" }), 2200);

      await d.click(row(page, reached).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("Reached"), 500);
      await d.type(page.getByPlaceholder("What did they say?"), "Travelling for work, back in two weeks.", 35);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`for ${reached}`));
      await d.say("Contacted members move to \"Contacted this week\", with the outcome, time and who called.");
      await d.click(page.getByRole("button", { name: /Contacted this week/ }), 1200);
      await d.reveal(page.getByText("Busy with exams. Renewing on Friday."), 2600);
    });
    await d.logout();
  }

  // ========================== Branch Manager, again ==========================
  if (want("bm2")) {
    await d.staffLogin("kabboud");
    await d.story({
      key: "SCRUM-68", role: BM, title: "Calls are visible on the member's record",
      sentence: "Back as branch manager: the member's record now shows the call history with date, staff member and outcome.",
    }, async () => {
      const name = state.saved || d.creds.named.atRisk.noShows.name;
      await d.click(d.button("Member Directory"), 1200);
      await d.type(page.getByPlaceholder("Search by name..."), name, 45);
      await sleep(1500);
      await d.click(page.getByRole("row", { name: new RegExp(name) }).getByRole("button", { name: "See Subscription Details" }).first(), 1500);
      const calls = page.getByText("Retention calls", { exact: true });
      await d.see(calls);
      await d.reveal(calls, 800);
      await d.reveal(page.getByText("Busy with exams. Renewing on Friday."), 3000);
      await d.click(d.button("Close"), 900);
    });

    await d.story({
      key: "SCRUM-120", role: BM, title: "Accuracy tracked against completed calls",
      sentence: "The accuracy panel counts this week's calls against the capacity, and what happened on earlier weeks' lists.",
    }, async () => {
      await d.click(d.button("At-Risk Members"), 1500);
      await d.see(page.getByText("How the calls are working"));
      await d.reveal(page.getByText(/calls? to make/), 1600);
      await d.reveal(page.getByText("How the calls are working"), 1400);
      await d.reveal(page.getByText("Calls done"), 2600);
      await d.say("Of members on past call lists, many more cancelled within 30 days than everyone else: the list picks the right people.");
      await d.reveal(page.getByText("Did the list pick the right people?"), 1200);
      await d.reveal(page.getByText(/as often/), 3200);
    });
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const TITLE_CARD = `
  <h1>Fitness Zone, Sprint 4 Demo</h1><h2>FYP Group 28</h2><p>AUB EECE 501 &middot; Sprint 4, 11 to 25 November 2026</p>
  <p style="margin-top:26px;color:#8fb0ff">At-risk members: a weekly, ranked, explained, capped call list, and the calls that follow</p>`;

function summaryCard(d, order) {
  const rows = order.map((s) => {
    const skipped = d.skipped.find((x) => x.key === s.key);
    return skipped
      ? `<li class="skipped"><b>${s.key}</b>${s.title} (not shown)</li>`
      : `<li><b>${s.key}</b>${s.title}</li>`;
  });
  return `<h1 style="font-size:40px">Sprint 4: what we built</h1>
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
    await demo.card(TITLE_CARD, 4000);
    await recordStories(demo);

    const order = [
      ["SCRUM-118", "Ranked list of members at risk, refreshed weekly"],
      ["SCRUM-119", "Plain-language reasons and talking points"],
      ["SCRUM-120", "Weekly call capacity and accuracy"],
      ["SCRUM-68", "Retention call outcomes on the member record"],
    ].map(([key, title]) => ({ key, title }));
    await demo.card(summaryCard(demo, order), 6000);
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

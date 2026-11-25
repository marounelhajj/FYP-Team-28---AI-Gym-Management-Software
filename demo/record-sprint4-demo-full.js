/*
 * Records the full Sprint 4 demo video of Fitness Zone (FYP Group 28), silent:
 * every Sprint 4 story, grouped by role.
 *
 *   npm run demo:seed:full      a clean demo database with data for every story
 *   npm run demo:record:full    records it right away (the live class and the
 *                               substitute-coach class are timed from the seed)
 *   npm run demo:record:full -- --headed     watch the browser while it records
 *
 * Output (git-ignored): demo/sprint4-demo-full.webm (raw) and demo/sprint4-demo-full.mp4
 * (H.264, no audio), plus demo/.data/recording-report-full.json (chapters, skipped
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
const WEBM = path.join(__dirname, "sprint4-demo-full.webm");
const MP4 = path.join(__dirname, "sprint4-demo-full.mp4");
const REPORT = path.join(DATA, "recording-report-full.json");
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
// The stories (keep in step with docs/sprint4-demo-script.md), grouped by role
// to keep logins few: Coach, Receptionist, Member, Branch Manager, Marketing,
// General Manager. (The receptionist comes before the member because the
// friend who earns the member referral points is registered at the desk.)
// ---------------------------------------------------------------------------

const BM = "Branch Manager";
const GM = "General Manager";
const REC = "Receptionist";
const COACH = "Coach";
const MEMBER = "Member";
const MKT = "Marketing Staff";
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

// A tab in the staff nav (some roles have only one screen and no nav).
async function openTab(d, name) {
  const tab = d.page.getByRole("navigation").getByRole("button", { name, exact: true });
  if (await tab.count()) await d.click(tab, 1500);
}

async function recordStories(d) {
  const { page } = d;
  const state = {};

  // ================================== Coach ==================================
  if (want("coach")) {
    await d.staffLogin("hnasser");

    await d.story({
      key: "SCRUM-85", role: COACH, title: "Check a client's injuries before the session",
      sentence: "Before a private session, the coach sees what the client has declared: injuries and conditions, most limiting first.",
    }, async () => {
      await openTab(d, "My Schedule");
      await d.see(page.getByText(/Private training · Dana Aoun/));
      await d.reveal(page.getByText(/health notes · severe/).first(), 1800);
      await d.click(d.button("Health briefing for Dana Aoun"), 1200);
      await d.see(page.getByRole("heading", { name: /Health briefing · Private training · Dana Aoun/ }));
      await d.reveal(page.getByText("Rotator cuff tear, right shoulder"), 2600);
      await d.reveal(page.getByText(/No overhead pressing/), 2000);
      await d.reveal(page.getByText("Exercise-induced asthma"), 1600);
      await d.say("Only the coach of this session can open it, and every view is recorded.");
      await d.reveal(page.getByText(/Opening this is recorded/), 1200);
      await d.click(d.button("Close"), 800);
      await d.say("For a group class, the coach sees who in the room needs the workout adapted.");
      await d.click(d.button("Health briefing for Spinning").first(), 1200);
      await d.see(page.getByRole("heading", { name: /Health briefing · Spinning/ }));
      await d.reveal(page.getByText("Adapt the workout for"), 2200);
      await d.reveal(page.getByText("Ask before you start"), 1600);
      await d.click(d.button("Close"), 800);
    });

    await d.story({
      key: "SCRUM-35", role: COACH, title: "Log a client's session and progress notes",
      sentence: "After a private session, the coach logs the exercises and a progress note, picking up from last session's plan.",
    }, async () => {
      await d.click(d.button("Log session for Lea Haddad").first(), 1200);
      await d.see(page.getByRole("heading", { name: /Session log · Lea Haddad/ }));
      await d.reveal(page.getByText("Last plan"), 2400);
      await d.click(d.button("Repeat last session"), 1200);
      await d.say("Last session's exercises are copied in; the coach raises the squat to 75 kg and writes the notes.");
      await d.type(page.locator('label:has-text("kg") input[type="number"]').first(), "75", 120);
      await d.type(page.getByPlaceholder("Sleep, energy, soreness, pain, what they told you."), "Slept well. Right knee fine on the warm-up.", 25);
      await d.type(page.getByPlaceholder("Form, range of motion, test results, anything you observed."), "Box squat to parallel, 4x8 at 75 kg, no knee pain.", 25);
      await d.type(page.getByPlaceholder("Is it working? Ready to progress? Anything to watch?"), "Ready to progress. Knee tolerating load.", 25);
      await d.type(page.getByPlaceholder("Shown to you (and the client) when the next session is logged."), "Next: squat 77.5 kg, add lunges 3x10.", 25);
      await d.click(d.button("Save log"), 1200);
      await d.see(d.button("Save changes"));
      await d.click(d.button("Done"), 1000);
      await d.say("Every logged session builds the client's history: goals, strength over time and all the notes.");
      await openTab(d, "My Clients");
      await d.click(page.getByRole("list", { name: "Clients" }).getByRole("button", { name: /Lea Haddad/ }), 1500);
      await d.reveal(page.getByText("Squat 100 kg (estimated 1-rep max)"), 2200);
      await d.reveal(page.getByRole("heading", { name: "Strength" }), 2000);
      await d.reveal(page.getByText("Next: squat 77.5 kg, add lunges 3x10.").first(), 2400);
    });

    await d.story({
      key: "SCRUM-79", role: COACH, title: "Check this month's sessions and earnings",
      sentence: "The coach opens My Pay to check every session taught this month, the rate it was paid at, and the total so far.",
    }, async () => {
      await openTab(d, "My Pay");
      await d.see(page.getByRole("heading", { name: "My Pay" }));
      await d.reveal(page.getByText("Completed sessions", { exact: true }), 1800);
      await d.reveal(page.getByText("Earned so far", { exact: true }), 2400);
      await d.say("Each session is paid at the rate in effect on its date, so a mid-month raise is applied exactly.");
      await d.reveal(page.getByText("Rates for this period"), 1600);
      const done = page.locator("table").first().locator("tbody tr");
      await d.reveal(done.filter({ hasText: "Lea Haddad" }).last(), 2200);
    });
    await d.logout();
  }

  // =============================== Receptionist ==============================
  if (want("rec")) {
    await d.staffLogin("dsarkis");
    await d.story({
      key: "SCRUM-68", role: REC, title: "Log the outcome of each retention call",
      sentence: "The receptionist works through Hamra's call list and logs each call: reached, no answer, saved or cancelled anyway.",
    }, async () => {
      await openTab(d, "At-Risk Members");
      await d.see(page.getByText("Why they're on the list"));
      await d.say("The front desk can't change the list or its weekly capacity, but logs every call.");
      await d.reveal(page.getByText(/calls a week/).first(), 1600);
      const [saved, noAnswer, reached] = await callListNames(page);
      state.saved = saved;
      await d.click(row(page, saved).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("Saved"), 500);
      await d.type(page.getByPlaceholder("What did they say?"), "Busy with exams. Renewing on Friday.", 30);
      await d.moveTo(page.locator('input[type="date"]'));
      await page.locator('input[type="date"]').fill(isoDay(3));
      await sleep(400);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`for ${saved}`));
      await d.say(`${saved} was saved, so they drop off this week's call list.`);
      await d.click(row(page, noAnswer).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("No answer"), 700);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`No answer logged for ${noAnswer}`));
      await d.say("No answer keeps them on the list, so the call can be tried again this week.");
      await d.reveal(row(page, noAnswer).getByRole("button", { name: "Try again" }), 1800);
      await d.click(row(page, reached).getByRole("button", { name: "Log call" }), 900);
      await d.click(d.radio("Reached"), 500);
      await d.type(page.getByPlaceholder("What did they say?"), "Travelling for work, back in two weeks.", 30);
      await d.click(d.button("Save call"), 900);
      await d.see(page.getByText(`for ${reached}`));
      await d.click(page.getByRole("button", { name: /Contacted this week/ }), 1200);
      await d.reveal(page.getByText("Busy with exams. Renewing on Friday."), 2400);
    });

    const friend = "Tala Mouawad";
    await d.story({
      key: "SCRUM-130", role: REC, title: "Referring a friend earns loyalty points",
      sentence: "Lea's friend joins at the front desk with Lea's referral code, so Lea earns 50 points once the friend has paid.",
    }, async () => {
      await openTab(d, "Member Directory");
      await d.click(d.button("+ Register New Member"), 900);
      await d.see(page.getByRole("heading", { name: "Register New Member" }));
      await d.type(d.field("Full name"), friend);
      await d.type(d.field("Email"), "tala.mouawad@example.com", 20);
      await d.type(d.field("Phone"), "+961 70 555 214", 20);
      await d.choose(d.field("Branch"), "Hamra");
      await d.choose(d.field("Membership plan"), "Standard");
      await d.choose(d.field("Payment method"), "Card");
      await d.choose(d.field("Subscription duration"), "1 Month");
      await d.type(d.field("Referral code"), d.creds.named.loyalty.referralCode, 100);
      await d.click(page.getByLabel("I have read and agree to the liability waiver."), 300);
      await d.click(page.getByLabel("I confirm the health disclaimer applies to me."), 300);
      await d.type(page.locator("#waiver-signature"), friend, 25);
      await d.click(d.button("Register & charge payment"), 1200);
      await d.see(page.getByText(`${friend} was registered successfully`, { exact: false }));
      await d.reveal(page.getByText(`${friend} was registered successfully`, { exact: false }), 2000);
    });
    await d.logout();
  }

  // ================================== Member =================================
  if (want("member")) {
    await d.memberLogin("memberLogin");
    await d.story({
      key: "SCRUM-130", role: MEMBER, title: "Points for showing up, and for the referral",
      sentence: "Lea earns 10 points for every class or private session she checks in for, and 50 for the friend who just joined.",
    }, async () => {
      await d.reveal(page.getByRole("heading", { name: /^Book at / }), 600);
      await d.goto("/");
      await d.see(page.getByRole("heading", { name: "Loyalty points" }));
      await d.reveal(page.getByRole("heading", { name: "Loyalty points" }), 900);
      await d.reveal(page.getByText(/Referred Tala Mouawad/), 2600);
      await d.say("Classes count only when her check-in shows she was in the branch during the class.");
      await d.reveal(page.getByText(/^Attended /).first(), 2000);
    });
    await d.story({
      key: "SCRUM-131", role: MEMBER, title: "Points balance and where it came from",
      sentence: "Lea sees her balance and every entry behind it: what earned the points and on which day.",
    }, async () => {
      const card = page.locator('section[aria-label="Your loyalty points"]');
      await d.reveal(card.getByText("points earned"), 2400);
      const rows = card.locator("span").filter({ hasText: /^\+\d+$/ });
      await d.reveal(rows.first(), 1400);
      await d.reveal(rows.last(), 1600);
      await d.say("Her own referral code sits next to the balance, ready to give to a friend.");
      await d.reveal(card.getByText("Your referral code"), 1800);
    });
    await d.logout();
  }

  // ============================== Branch Manager =============================
  if (want("bm")) {
    await d.staffLogin("kabboud");

    await d.story({
      key: "SCRUM-89", role: BM, title: "Reassign a class when the coach calls in sick",
      sentence: "Omar Saleh just called in sick for tonight's HIIT class. The branch manager finds a free substitute in a few clicks.",
    }, async () => {
      await openTab(d, "Class Schedule");
      await d.see(page.getByText(/needs? a substitute coach/));
      await d.reveal(page.getByRole("region", { name: "Classes needing a substitute" }), 2200);
      await d.click(d.button("Find a substitute"), 1200);
      await d.see(page.getByRole("heading", { name: "Find a substitute" }));
      await d.say("Busy coaches are shown with the reason; the free ones come first, by who knows the class best.");
      await d.click(page.getByRole("radio", { name: /Rita Aoun/ }), 900);
      await d.click(d.button("Assign Rita Aoun"), 1200);
      await d.see(page.getByText(/Rita Aoun is now teaching HIIT/));
      await d.reveal(page.getByText(/Rita Aoun is now teaching HIIT/), 2400);
    });

    await d.story({
      key: "SCRUM-54", role: BM, title: "Member feedback and complaints for my branch",
      sentence: "The Hamra branch manager sees what Hamra's members say this month: their score, service areas, comments and complaints.",
    }, async () => {
      await openTab(d, "Member Feedback");
      await d.see(page.getByRole("heading", { name: /Member Feedback/ }));
      await d.reveal(page.getByText("Net Promoter Score", { exact: true }), 2000);
      await d.reveal(page.getByText("Needs attention").first(), 2000);
      await d.say("Complaints wait in a queue: urgent ones first, and anything unanswered for 48 hours is marked overdue.");
      await d.reveal(page.getByRole("heading", { name: "Complaints", exact: true }), 1000);
      await d.reveal(page.getByText("Overdue", { exact: true }).first(), 2000);
    });

    await d.story({
      key: "SCRUM-94", role: BM, title: "Escalate a complaint to the general manager",
      sentence: "Two treadmills have been broken for weeks and the repair is over the branch budget, so it goes to head office.",
    }, async () => {
      const esc = d.creds.named.feedback.escalate.subject;
      await d.click(page.getByRole("button", { name: `Open complaint: ${esc}` }), 1500);
      await d.see(page.getByRole("dialog", { name: "Complaint" }));
      await d.click(d.button("Escalate to general manager"), 900);
      await d.type(page.locator("#escalate-reason"), "Third report this month. Replacing both belts is over the branch budget.", 25);
      await d.click(d.button("Escalate"), 1200);
      await d.see(page.getByText("Escalated to the general manager", { exact: true }));
      await d.say("The reason is a staff-only note. The member is told it was passed up, but never sees the reason.");
      await d.reveal(page.getByText("Internal note").last(), 1800);
      await d.click(d.button("Close"), 800);
    });

    await d.story({
      key: "SCRUM-53", role: BM, title: "Send supply reorder requests through the system",
      sentence: "The branch manager sees what is running low and orders it from the usual supplier in a few clicks, no phone calls.",
    }, async () => {
      await openTab(d, "Supply Orders");
      const low = page.getByRole("region", { name: "Running low" });
      await d.reveal(low.getByText("Running low at Hamra"), 1500);
      await d.click(low.getByRole("button", { name: /^Order from NutriPro/ }).first(), 1200);
      const form = page.getByRole("dialog", { name: "New supply order" });
      await d.reveal(form.getByText("Order total"), 1500);
      await d.reveal(form.getByText(/General Manager approves it first/), 2000);
      await d.click(form.getByRole("button", { name: "Send for approval" }), 1200);
      await d.reveal(page.getByText(/sent to the General Manager for approval\./), 2200);
    });

    await d.story({
      key: "SCRUM-118", role: BM, title: "A ranked list of members at risk of leaving",
      sentence: "Every Monday each Hamra member is scored; the branch manager sees who to call first, highest risk at the top.",
    }, async () => {
      await openTab(d, "At-Risk Members");
      await d.see(page.getByText("Why they're on the list"));
      await d.say("Hamra has months of history, so its list comes from a learned model, validated on held-out weeks.");
      await d.reveal(page.getByText(/Learned model/).first(), 2000);
      await d.reveal(page.locator("table").first().locator("tbody tr").first(), 2000);
    });

    await d.story({
      key: "SCRUM-119", role: BM, title: "The reasons behind each member's ranking",
      sentence: "Each member shows two or three reasons in plain language, with their real numbers and a talking point for the call.",
    }, async () => {
      const first = page.locator("table").first().locator("tbody tr").first();
      await d.reveal(first.locator("li").first(), 2400);
      await d.reveal(first.getByText(/^Say:/).first(), 2400);
    });

    await d.story({
      key: "SCRUM-120", role: BM, title: "Cap the list to the calls staff can make this week",
      sentence: "The team can make 5 calls this week, so the branch manager lowers the weekly capacity from 8 to 5.",
    }, async () => {
      await d.type(page.locator("#call-capacity"), "5", 120);
      await d.click(d.button("Set"), 900);
      await d.see(page.getByText("Call capacity set to 5"));
      await d.say("The list now holds the top 5; everyone else stays visible below the cap. Calls logged count against it.");
      await d.reveal(page.getByText(/calls? to make/), 1600);
      await d.reveal(page.getByText("How the calls are working"), 1200);
      await d.reveal(page.getByText(/as often/), 2600);
    });

    await d.story({
      key: "SCRUM-68", role: BM, title: "Calls are visible on the member's record",
      sentence: "The member's record now shows the call the receptionist logged, with the date, staff member and outcome.",
    }, async () => {
      const name = state.saved;
      if (!name) throw new Error("No call was logged earlier in the recording");
      await openTab(d, "Member Directory");
      await d.type(page.getByPlaceholder("Search by name..."), name, 40);
      await sleep(1500);
      await d.click(page.getByRole("row", { name: new RegExp(name) }).getByRole("button", { name: "See Subscription Details" }).first(), 1500);
      await d.see(page.getByText("Retention calls", { exact: true }));
      await d.reveal(page.getByText("Busy with exams. Renewing on Friday."), 2600);
      await d.click(d.button("Close"), 900);
    });
    await d.logout();
  }

  // ============================== Marketing Staff ============================
  if (want("mkt")) {
    await d.staffLogin("nkhalil");

    await d.story({
      key: "SCRUM-43", role: MKT, title: "Segment members by behaviour or demographics",
      sentence: "Marketing builds a segment from filters that all apply together, and sees the live member count as the filters change.",
    }, async () => {
      await openTab(d, "Member Segments");
      await d.see(page.getByRole("heading", { name: "Member Segments" }));
      await d.click(d.button("+ New segment"), 1000);
      const dialog = page.getByRole("dialog");
      await d.reveal(dialog.getByText(/live audience/i), 1400);
      await d.click(dialog.getByRole("button", { name: "Hamra", exact: true }), 900);
      await d.click(dialog.getByRole("button", { name: "High Risk", exact: true }), 900);
      await d.click(dialog.getByRole("button", { name: "Medium Risk", exact: true }), 1200);
      await d.reveal(dialog.getByText(/live audience/i), 2200);
      await d.type(dialog.getByPlaceholder("e.g. Regular Morning Warriors"), "Hamra members at risk", 30);
      await d.click(dialog.getByRole("button", { name: "Create segment" }), 1500);
      await d.see(page.getByText(/Hamra members at risk/).first());
      await d.say("Members who turned off offers are still counted, but can't be targeted.");
      await d.reveal(page.locator("table tbody tr").filter({ hasText: "Hamra members at risk" }), 2200);
      await d.say("Suggested segments: a weekly k-means job groups active members by when, how often and how they train.");
      await d.reveal(page.getByText(/Silhouette/), 2600);
      await d.reveal(page.locator("button", { hasText: "Save as segment" }).first(), 2200);
      await d.click(page.locator("button", { hasText: "Save as segment" }).first(), 1500);
      await d.reveal(page.locator("table tbody tr").first(), 2000);
    });

    await d.story({
      key: "SCRUM-112", role: MKT, title: "Attendance trends by branch and segment",
      sentence: "Visits per active member, week by week, for chosen segments against all members, so growth or decline is easy to spot.",
    }, async () => {
      await openTab(d, "Attendance Trends");
      await d.see(page.getByText(/segments? compared/));
      const chips = page.locator("button", { hasText: "Hamra members at risk" });
      if (await chips.count()) await d.click(chips.first(), 1200);
      await sleep(1500);
      await d.reveal(page.locator("svg[role=img]").first(), 2600);
      await d.reveal(page.getByText(/Change vs prev period/i), 2400);
      const toggle = (name) => page.getByRole("radio", { name, exact: true }).or(d.button(name)).first();
      await d.click(toggle("Monthly"), 1800);
      await d.reveal(page.locator("svg[role=img]").first(), 2200);
      await d.click(toggle("Total visits"), 1800);
      await d.click(toggle("Visits / member"), 1000);
      await d.click(toggle("Weekly"), 1200);
    });

    await d.story({
      key: "SCRUM-113", role: MKT, title: "Class and service uptake per segment",
      sentence: "For a date range, the share of each segment that used each class, personal training and shop category.",
    }, async () => {
      await openTab(d, "Segment Uptake");
      await d.see(page.getByText(/offerings tracked/));
      const chips = page.locator("button", { hasText: "Hamra members at risk" });
      if (await chips.count()) await d.click(chips.first(), 1500);
      await sleep(1500);
      await d.reveal(page.locator("table").first(), 2400);
      await d.say("Green outlines mark offerings a segment uses well above average; red, well below.");
      await d.reveal(page.getByText(/Heatmap legend/i), 2400);
    });

    await d.story({
      key: "SCRUM-114", role: MKT, title: "Export a segment's engagement data",
      sentence: "Export the numbers on screen as CSV, or a segment's member list, without anyone who opted out. Every export is audited.",
    }, async () => {
      const agg = await d.download(() => d.click(page.locator("button", { hasText: "Export CSV" }).first(), 1200));
      state.aggregateCsv = agg.suggestedFilename();
      await d.say(`Downloaded ${state.aggregateCsv}: the uptake and trend numbers for these filters.`);
      await openTab(d, "Member Segments");
      const segRow = page.locator("table tbody tr").filter({ hasText: "Hamra members at risk" });
      const list = await d.download(() => d.click(segRow.locator("button", { hasText: "Export members" }), 1200));
      state.memberCsv = list.suggestedFilename();
      await d.say(`Downloaded ${state.memberCsv}: id, first name, email, plan, visits, last visit and risk level.`);
    });

    await d.story({
      key: "SCRUM-78", role: MKT, title: "Create and schedule a campaign with a target segment and offer code",
      sentence: "Marketing sets up a promotion: an offer code, who it is for, and when it starts.",
    }, async () => {
      await openTab(d, "Marketing Campaigns");
      await d.see(page.getByRole("heading", { name: "Marketing Campaigns" }));
      await d.click(d.button("+ New Campaign"), 900);
      const form = page.getByRole("dialog", { name: "New campaign" });
      await d.type(form.getByPlaceholder("e.g. Summer Membership Push"), "Win-Back Spring");
      await d.choose(d.field("Branch"), "Hamra");
      await d.field("Starts").first().fill(isoDay(1));
      await d.field("Ends").first().fill(isoDay(15));
      await d.type(form.getByPlaceholder("e.g. Win back members who stopped coming, ahead of the summer."),
        "Bring back members who haven't trained in a month.", 20);
      await d.type(d.field("Budget ($)"), "400");
      await d.type(form.getByLabel("Offer code"), "COMEBACK15", 60);
      await d.choose(form.getByLabel("Discount type"), "Percent");
      await d.type(form.getByLabel("Discount amount"), "15");
      await d.choose(d.field("Can be used on"), "Membership");
      await d.say("The target: Hamra members who haven't been in for 30 days. The count updates as you tick.");
      await d.click(form.getByRole("checkbox", { name: "Frozen or lapsed" }), 600);
      await d.click(form.getByRole("checkbox", { name: "Hasn't been in for at least" }), 900);
      await d.reveal(form.getByText(/members? match(es)? right now/), 2200);
      await d.click(form.getByRole("button", { name: "Schedule campaign" }), 1200);
      await d.see(page.getByText(/Win-Back Spring is set/));
      await d.reveal(page.locator("tbody tr").filter({ hasText: "Win-Back Spring" }), 2000);
    });

    await d.story({
      key: "SCRUM-63", role: MKT, title: "Sign-ups and redemptions per campaign",
      sentence: "Each campaign counts new members who joined with its code apart from existing members who used it, next to budget and spend.",
    }, async () => {
      await d.choose(page.getByLabel("Branch"), "Zalka");
      const opening = page.locator("tbody tr").filter({ hasText: "Zalka Grand Opening" });
      await d.reveal(opening.getByText(/sign-ups?/), 2200);
      await d.click(opening.getByRole("button", { name: "Results" }), 1500);
      const results = page.getByRole("dialog", { name: "Campaign results" });
      await d.reveal(results.getByText("Sign-ups", { exact: true }), 2200);
      await d.reveal(results.getByText("Revenue", { exact: true }), 2200);
      await d.click(results.getByRole("button", { name: "Close" }), 800);
      await d.choose(page.getByLabel("Branch"), "");
    });
    await d.logout();
  }

  // ============================= General Manager =============================
  if (want("gm")) {
    await d.staffLogin("rhaddad");

    await d.story({
      key: "SCRUM-94", role: GM, title: "Escalations land with the general manager",
      sentence: "The general manager is notified straight away and has one queue of escalations from every branch.",
    }, async () => {
      await openTab(d, "Member Feedback");
      await d.click(d.button("Escalated"), 1500);
      const esc = d.creds.named.feedback.escalate.subject;
      await d.reveal(page.getByRole("button", { name: `Open complaint: ${esc}` }), 2400);
    });

    await d.story({
      key: "SCRUM-23", role: GM, title: "Feedback from every branch, side by side",
      sentence: "The general manager compares what members say about every branch this month, to spot issues that keep coming up.",
    }, async () => {
      await openTab(d, "Feedback Overview");
      await d.see(page.getByRole("heading", { name: "Feedback Overview" }));
      await d.reveal(page.getByText("Company NPS"), 1600);
      await d.reveal(page.getByRole("heading", { name: "Branches side by side" }), 2000);
      await d.reveal(page.getByText("Recurring", { exact: true }).first(), 2200);
      await d.reveal(page.getByRole("heading", { name: "What members wrote" }), 1800);
    });

    await d.story({
      key: "SCRUM-24", role: GM, title: "Personal trainer ratings by branch",
      sentence: "Members rate their coach after each session; the general manager sees those ratings by branch, best first.",
    }, async () => {
      await openTab(d, "PT Ratings");
      await d.see(page.getByRole("heading", { name: "Personal Trainer Ratings" }));
      await d.reveal(page.getByRole("heading", { name: "Hamra", exact: true }), 1800);
      await d.reveal(page.locator("table").first(), 2200);
    });

    await d.story({
      key: "SCRUM-51", role: GM, title: "Compare branch retention rates in one view",
      sentence: "Every branch's retention rate side by side, so a branch losing members stands out.",
    }, async () => {
      await openTab(d, "Retention");
      await d.see(page.getByRole("heading", { name: /Retention/ }));
      const summary = page.locator("table").first();
      for (const b of ["Hamra", "Achrafieh", "Jnah", "Zalka"]) {
        await d.reveal(summary.locator("tbody tr").filter({ hasText: b }).first(), 1100);
      }
    });

    await d.story({
      key: "SCRUM-105", role: GM, title: "Compare branch revenue performance in one view",
      sentence: "Every branch's revenue, costs and margin in one ranked view; branches falling behind are flagged with the reason.",
    }, async () => {
      await openTab(d, "Branch Comparison");
      await d.see(page.getByRole("heading", { name: "Branch Comparison", exact: true }));
      await d.reveal(page.getByText("Company revenue"), 1500);
      await d.reveal(page.getByText("Underperforming", { exact: true }).first(), 2200);
      await d.reveal(page.getByRole("region", { name: "Revenue over six months" }), 2200);
    });

    await d.story({
      key: "SCRUM-21", role: GM, title: "Stock levels at every branch, to catch shortages",
      sentence: "One grid shows every product's stock at every branch; empty and nearly empty shelves are highlighted.",
    }, async () => {
      await openTab(d, "Retail Products");
      await d.see(page.getByRole("heading", { name: "Retail Products" }));
      await d.reveal(page.getByText(/running low/).first(), 2000);
      await d.reveal(page.locator("table").first(), 2000);
      await d.say("The branch manager's reorder from earlier waits here for the general manager's approval.");
      await openTab(d, "Supply Orders");
      const approvals = page.getByRole("region", { name: "Waiting for your approval" });
      await d.reveal(approvals, 2000);
      const hamra = approvals.getByRole("listitem").filter({ hasText: "Hamra" });
      const pending = (await hamra.count()) ? hamra.first() : approvals.getByRole("listitem").first();
      await d.click(pending.getByRole("button").first(), 1200);
      await d.click(page.getByRole("button", { name: /^Approve \$/ }), 1200);
      await d.reveal(page.getByText("Approved and sent to the supplier."), 2000);
      await d.click(page.getByRole("dialog", { name: "Supply order" }).getByRole("button", { name: "Close" }), 800);
    });

    await d.story({
      key: "SCRUM-44", role: GM, title: "Marketing campaigns and strategies at each branch",
      sentence: "What marketing runs at every branch, why, and how spending compares with each budget, including today's new campaign.",
    }, async () => {
      await openTab(d, "Campaigns by Branch");
      await d.see(page.getByRole("heading", { name: "Marketing Campaigns by Branch" }));
      await d.reveal(page.getByText(/total budget/).first(), 2000);
      await d.reveal(page.getByRole("heading", { name: "Hamra", exact: true }), 1400);
      await d.reveal(page.getByText("Win-Back Spring").first(), 2000);
    });
    await d.logout();
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const TITLE_CARD = `
  <h1>Fitness Zone, Sprint 4 Demo</h1><h2>FYP Group 28</h2><p>AUB EECE 501 &middot; Sprint 4, 11 to 25 November 2026</p>
  <p style="margin-top:26px;color:#8fb0ff">25 stories, role by role: coach, receptionist, member, branch manager, marketing, general manager</p>`;

function summaryCard(d, order) {
  const rows = order.map((s) => {
    const skipped = d.skipped.find((x) => x.key === s.key);
    return skipped
      ? `<li class="skipped"><b>${s.key}</b>${s.title} (not shown)</li>`
      : `<li><b>${s.key}</b>${s.title}</li>`;
  });
  return `<h1 style="font-size:40px">Sprint 4: what we built</h1>
    <h2 style="font-size:18px">${d.shown.length} stories shown &middot; Fitness Zone, FYP Group 28</h2><ul style="columns:2;column-gap:36px;font-size:14px;line-height:1.5;margin-top:10px">${rows.join("")}</ul>`;
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
      ["SCRUM-85", "Client health restrictions before a session"],
      ["SCRUM-35", "Session logs and progress notes"],
      ["SCRUM-79", "Coach sessions and earnings this period"],
      ["SCRUM-68", "Retention call outcomes"],
      ["SCRUM-130", "Loyalty points for sessions and referrals"],
      ["SCRUM-131", "Points balance and history"],
      ["SCRUM-89", "Substitute coach for a cancelled class"],
      ["SCRUM-54", "Branch feedback and complaints"],
      ["SCRUM-94", "Escalate a complaint to the GM"],
      ["SCRUM-53", "Supply reorder requests"],
      ["SCRUM-118", "Ranked at-risk members, weekly"],
      ["SCRUM-119", "Reasons behind each ranking"],
      ["SCRUM-120", "Weekly call capacity"],
      ["SCRUM-43", "Member segments and suggested clusters"],
      ["SCRUM-112", "Attendance trends by segment"],
      ["SCRUM-113", "Class and service uptake by segment"],
      ["SCRUM-114", "Export segment engagement data"],
      ["SCRUM-78", "Campaigns with a segment and offer code"],
      ["SCRUM-63", "Campaign sign-ups and redemptions"],
      ["SCRUM-23", "Feedback across branches"],
      ["SCRUM-24", "Trainer ratings by branch"],
      ["SCRUM-51", "Branch retention comparison"],
      ["SCRUM-105", "Branch revenue comparison"],
      ["SCRUM-21", "Inventory levels per branch"],
      ["SCRUM-44", "Campaigns per branch"],
    ].map(([key, title]) => ({ key, title }));
    await demo.card(summaryCard(demo, order), 9000);
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

/*
 * Records the Sprint 3 demo video of Fitness Zone (FYP Group 28), silent.
 *
 *   npm run demo:seed       once: a clean, realistic demo database + logins
 *   npm run demo:record     records every story, role by role
 *   npm run demo:record -- --headed     watch the browser while it records
 *
 * Output (git-ignored): demo/sprint3-demo.webm (raw) and demo/sprint3-demo.mp4
 * (H.264, no audio), plus demo/.data/recording-report.json (chapters, skipped
 * stories). The story order, logins and click paths are in
 * docs/sprint3-demo-script.md; keep the two in step.
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
const WEBM = path.join(__dirname, "sprint3-demo.webm");
const MP4 = path.join(__dirname, "sprint3-demo.mp4");
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
// The stories (keep in step with docs/sprint3-demo-script.md)
// ---------------------------------------------------------------------------

const BM = "Branch Manager";
const REC = "Receptionist";
const COACH = "Coach";
const MEMBER = "Member";
const ONLY = (process.argv.find((a) => a.startsWith("--only=")) || "").slice(7).split(",").filter(Boolean);
const want = (persona) => ONLY.length === 0 || ONLY.includes(persona);

function isoDay(offset) {
  const d = new Date(Date.now() + offset * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function longDay(offset) {
  const d = new Date(Date.now() + offset * 86400000);
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

// The capacity whose 90% alert level is exactly `target` people.
function capacityFor(target) {
  for (let cap = target; cap < target * 2 + 5; cap++) if (Math.ceil(cap * 0.9) === target) return cap;
  return target;
}

async function recordStories(d) {
  const { page, creds } = d;
  const named = creds.named;
  const dialog = () => page.getByRole("dialog").last();
  let inside = null;

  // ============================== Branch Manager =============================
  if (want("bm")) {
  await d.staffLogin("kabboud");

  await d.story({
    key: "SCRUM-81", role: BM, title: "Maximum capacity per class type",
    sentence: "Each class type has a safe maximum, so no class of that type can be overbooked.",
  }, async () => {
    await d.click(d.button("Class Schedule"), 900);
    await d.click(d.radio("Class types"), 900);
    const row = page.getByRole("row", { name: /Spinning/ }).first();
    await d.reveal(row, 1200);
    await d.click(row.getByRole("button", { name: "Edit" }), 700);
    await d.type(d.field("Maximum capacity"), "18");
    await d.click(d.button("Save changes"), 1000);
    await d.see(page.getByText("Spinning saved", { exact: false }));
    await d.reveal(page.getByText("Spinning saved", { exact: false }), 1500);
  });

  await d.story({
    key: "SCRUM-52", role: BM, title: "Build the weekly class calendar",
    sentence: "The branch manager adds a class on tomorrow's calendar and assigns a coach to the slot.",
  }, async () => {
    await d.click(d.radio("Weekly calendar"), 900);
    await d.click(page.getByRole("region", { name: longDay(1) }).getByRole("button", { name: "+ Add class" }), 900);
    const form = dialog();
    await d.choose(form.locator("select").filter({ hasText: "Choose a class type" }), { label: "Pilates (max 15)" });
    await d.choose(form.getByLabel("Start hour"), "20");
    await d.choose(form.locator("select").filter({ hasText: "Choose a coach" }), { label: "Rita Aoun" });
    await d.click(form.getByRole("button", { name: "Add class" }), 1200);
    await d.see(page.getByText("scheduled on", { exact: false }));
    await d.reveal(page.getByText("scheduled on", { exact: false }), 1500);
  });

  await d.story({
    key: "SCRUM-128", role: BM, title: "Set the branch capacity and alert level",
    sentence: "On Live Headcount the branch manager sets how many people the floor can hold and when to alert.",
  }, async () => {
    await d.click(d.button("Live Headcount"), 1200);
    await d.see(page.getByText("inside now", { exact: false }));
    inside = Number((await page.locator(".hc-bump").first().innerText()).trim());
    const cap = capacityFor(inside + 2);
    log(`  ${inside} inside, capacity ${cap} -> alert at ${inside + 2}`);
    await d.click(page.getByRole("button", { name: /capacity$/ }), 700);
    await d.type(page.getByLabel("Maximum people on the floor"), String(cap));
    await d.type(page.getByLabel("Alert when it reaches (%)"), "90");
    await d.click(d.button("Save capacity"), 1200);
    await d.reveal(page.getByText(`of ${cap} people`, { exact: false }), 2000);
  });

  await d.logout();
  }

  // ================================== Member =================================
  if (want("member")) {
  await d.memberLogin("memberLogin");

  await d.story({
    key: "SCRUM-77", role: MEMBER, title: "How busy is my branch, now and at typical hours",
    sentence: "Members see a busy level, never a headcount, plus the typical day hour by hour.",
  }, async () => {
    const card = page.getByText("How busy is it?");
    await d.reveal(card, 1500);
    await d.click(page.getByRole("radio", { name: "Saturday" }), 1500);
    await d.choose(page.getByLabel("Branch"), "Jnah");
    await sleep(1200);
    await d.choose(page.getByLabel("Branch"), "Hamra");
  });

  await d.story({
    key: "SCRUM-59", role: MEMBER, title: "Book a class or a private session in the app",
    sentence: "Lea reserves a spot in tomorrow's class and books private training with her coach.",
  }, async () => {
    await d.reveal(page.getByRole("heading", { name: /^Book at/ }), 600);
    await d.click(page.getByRole("tab").filter({ hasText: new RegExp(`^${new Date(Date.now() + 86400000).toLocaleDateString("en-GB", { weekday: "short" })}`) }).first(), 800);
    await d.click(d.button("Reserve").first(), 1200);
    await d.see(page.getByText("You're booked into", { exact: false }));
    await d.reveal(page.getByText("You're booked into", { exact: false }), 1400);
    await d.click(d.radio("Coaches & PT"), 900);
    const card = page.locator("div").filter({ has: page.getByText("Hadi Nasser", { exact: true }) }).filter({ has: d.button("See times") }).last();
    await d.click(card.getByRole("button", { name: "See times" }), 900);
    for (let i = 0; i < 3; i++) {
      const freeDay = page.getByRole("tab").filter({ hasText: /free/ }).first();
      if (await freeDay.count()) break;
      await d.click(page.getByRole("button", { name: "Next week" }), 900);
    }
    await d.click(page.getByRole("tab").filter({ hasText: /free/ }).first(), 700);
    await d.click(page.getByRole("button", { name: /: Free$/ }).first(), 700);
    await d.type(page.getByLabel("Note for the coach"), "Deadlift technique");
    await d.click(d.button("Book session"), 1200);
    await d.see(page.getByText("Booked: private training", { exact: false }));
    await d.reveal(page.getByText("Booked: private training", { exact: false }), 1600);
  });

  await d.story({
    key: "SCRUM-60", role: MEMBER, title: "Log my own workouts and body metrics",
    sentence: "Between sessions Lea logs her workouts and weight, for her coach and the AI to use.",
  }, async () => {
    await d.click(d.button("Log a workout"), 700);
    await d.choose(page.locator("#tl-exercise"), "Bench press");
    await d.type(page.locator("#tl-sets"), "4");
    await d.type(page.locator("#tl-reps"), "8");
    await d.type(page.locator("#tl-weight"), "45");
    await d.click(d.button("Save"), 1000);
    await d.see(page.getByText("Workout logged."));
    await d.click(page.getByRole("tab", { name: /^Body metrics/ }), 900);
    await d.reveal(page.locator("figure").last(), 2200);
  });

  await d.logout();
  }

  // =================================== Coach =================================
  if (want("coach")) {
  await d.staffLogin("hnasser");

  await d.story({
    key: "SCRUM-34", role: COACH, title: "My daily and weekly schedule",
    sentence: "Hadi sees his classes and private sessions for each day of the week.",
  }, async () => {
    await d.see(page.getByRole("tablist", { name: "Days" }));
    await d.reveal(page.getByRole("tab", { name: /^Today/ }), 1200);
    await d.click(page.getByRole("tab").nth(4), 1400);
    await d.click(page.getByRole("tab", { name: /^Today/ }), 900);
  });

  await d.story({
    key: "SCRUM-36", role: COACH, title: "Mark attendance for my classes",
    sentence: "During his class Hadi marks who came, who didn't, and adds a walk-in.",
  }, async () => {
    await d.click(d.button("Attendance").first(), 900);
    const sheet = page.getByRole("dialog", { name: "Attendance" });
    await d.see(sheet);
    const lea = creds.members.memberLogin.name;
    await d.click(sheet.getByRole("radiogroup", { name: `Attendance for ${lea}` }).getByRole("radio", { name: "Attended" }), 700);
    const others = sheet.getByRole("radiogroup", { name: new RegExp(`^Attendance for (?!${lea})`) });
    await d.click(others.nth(0).getByRole("radio", { name: "Attended" }), 500);
    await d.click(others.nth(1).getByRole("radio", { name: "No-show" }), 500);
    await d.type(sheet.getByPlaceholder("Membership ID"), String(named.walkIn.id));
    await d.click(sheet.getByRole("button", { name: "Add walk-in" }), 1200);
    await d.see(sheet.getByText("added as attended", { exact: false }));
    await d.reveal(sheet.getByText("Walk-ins", { exact: true }), 1800);
    await d.click(sheet.getByRole("button", { name: "Close" }), 600);
  });

  await d.story({
    key: "SCRUM-57", role: COACH, title: "Set my own PT availability",
    sentence: "Hadi publishes his own private training hours, which members can book straight away.",
  }, async () => {
    await d.click(d.button("My Availability"), 900);
    await d.choose(page.getByLabel("Every"), "Friday");
    await d.choose(page.getByLabel("From hour"), "14");
    await d.choose(page.getByLabel("To hour"), "17");
    await d.click(d.button("Add hours"), 1200);
    await d.see(page.getByText("members can book it now", { exact: false }));
    await d.reveal(page.getByText("members can book it now", { exact: false }), 1400);
  });

  await d.story({
    key: "SCRUM-100", role: COACH, title: "Block off time I'm unavailable",
    sentence: "He blocks off an afternoon, so members can't book him then.",
  }, async () => {
    await d.click(d.button("My Time Off"), 900);
    await d.moveTo(page.getByLabel("From"));
    await page.getByLabel("From").fill(`${isoDay(3)}T13:00`);
    await d.moveTo(page.getByLabel("To"));
    await page.getByLabel("To").fill(`${isoDay(3)}T17:00`);
    await d.type(page.getByLabel("Reason (optional)"), "Coaching course");
    await d.click(d.button("Block time off"), 1200);
    await d.see(page.getByText("members can't book you then", { exact: false }));
    await d.reveal(page.getByText("members can't book you then", { exact: false }), 1400);
  });

  await d.story({
    key: "SCRUM-60", role: COACH, title: "Coach views a client's training log (read-only)",
    sentence: "Her coach sees the workouts and weight Lea logged, read-only, to plan the next session.",
  }, async () => {
    await d.click(d.button("My Clients"), 1200);
    await d.see(page.getByText("Read-only"));
    await d.reveal(page.locator("figure").first(), 1800);
    await d.reveal(page.getByRole("heading", { name: "Recent workouts" }), 1500);
  });

  await d.logout();
  }

  // ================================ Receptionist =============================
  if (want("rec")) {
  await d.staffLogin("dsarkis");

  await d.story({
    key: "SCRUM-30", role: REC, title: "Today's class schedule and booking walk-ins",
    sentence: "The front desk sees today's classes with open slots and books a walk-in member into one.",
  }, async () => {
    await d.click(d.button("Class Schedule"), 1000);
    await d.reveal(page.getByText("Open spots", { exact: false }).first(), 1200);
    let book = page.getByRole("button", { name: /^Book a member into/ }).first();
    if (!(await book.count())) {
      await d.click(page.getByRole("button", { name: "Next day" }), 900);
      book = page.getByRole("button", { name: /^Book a member into/ }).first();
    }
    await d.click(book, 900);
    // The desk refuses a member who is already in another class then, so take the first one who can go.
    let booked = false;
    for (const m of [...named.checkInPool].reverse()) {
      await d.type(page.getByLabel("Find a member"), m.name);
      const btn = page.getByRole("button", { name: `Book ${m.name}` });
      await btn.first().waitFor({ timeout: 8000 }).catch(() => {});
      if ((await btn.count()) && (await btn.first().isEnabled())) {
        await d.click(btn, 1200);
        booked = true;
        break;
      }
    }
    if (!booked) throw new Error("Nobody in the seeded pool could be booked into that class");
    await d.see(page.getByText("is booked in", { exact: false }));
    await d.reveal(page.getByText("is booked in", { exact: false }), 1500);
    await d.click(dialog().getByRole("button", { name: "Close" }).first(), 600);
  });

  await d.story({
    key: "SCRUM-128", role: REC, title: "The capacity alert fires",
    sentence: "As members check in, the floor reaches its alert level and staff on site are notified.",
  }, async () => {
    await d.click(d.button("Check-In"), 900);
    let added = 0;
    for (const m of named.checkInPool.slice(1)) {
      if (added >= 2) break;
      await d.type(page.getByLabel("Membership ID"), String(m.id));
      await d.click(d.button("Check In"), 900);
      if (await page.getByText(`Welcome, ${m.name}`, { exact: false }).count()) added += 1;
    }
    await page.reload({ waitUntil: "domcontentloaded" });
    await sleep(1500);
    await d.click(page.getByRole("button", { name: /^Notifications/ }), 900);
    await d.see(page.getByText("is near capacity", { exact: false }));
    await d.reveal(page.getByText("is near capacity", { exact: false }), 2200);
    await page.keyboard.press("Escape");
  });

  await d.logout();
  }

  // ========================== Branch Manager, again ==========================
  if (want("bm2")) {
  await d.staffLogin("kabboud");
  await d.story({
    key: "SCRUM-128", role: BM, title: "The alert on the Live Headcount dashboard",
    sentence: "The branch manager sees the alert banner; it clears once headcount drops back under the level.",
  }, async () => {
    await d.click(d.button("Live Headcount"), 1200);
    await d.see(page.getByRole("alert").filter({ hasText: "Near capacity" }));
    await d.reveal(page.getByRole("alert").filter({ hasText: "Near capacity" }), 2600);
  });
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const TITLE_CARD = `
  <h1>Fitness Zone</h1><h2>Sprint 3 Demo</h2><p>FYP Group 28 &middot; AUB EECE 501</p>
  <p style="margin-top:26px;color:#8fb0ff">AI gym management software &middot; classes, coaching and capacity</p>`;

function summaryCard(d, order) {
  const rows = order.map((s) => {
    const skipped = d.skipped.find((x) => x.key === s.key);
    return skipped
      ? `<li class="skipped"><b>${s.key}</b>${s.title} (not shown)</li>`
      : `<li><b>${s.key}</b>${s.title}</li>`;
  });
  return `<h1 style="font-size:40px">Sprint 3: what we built</h1>
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
      ["SCRUM-81", "Class capacity per class type"], ["SCRUM-52", "Weekly class calendar"],
      ["SCRUM-128", "Branch capacity alert"], ["SCRUM-77", "Busy level for members"],
      ["SCRUM-59", "Book classes and private training"], ["SCRUM-60", "Member workout and metrics log"],
      ["SCRUM-34", "Coach daily and weekly schedule"], ["SCRUM-36", "Class attendance"],
      ["SCRUM-57", "Coach PT availability"], ["SCRUM-100", "Coach time off"],
      ["SCRUM-30", "Daily schedule and walk-in booking"],
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

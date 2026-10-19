// Polite headless render of official JS-heavy pages. Honest by design:
// robots.txt is obeyed (disallow -> skipped), bot challenges are treated as
// blocked (never bypassed), one page at a time, >=3s between pages.
// Usage: node render_pages.mjs [--targets f] [--out dir] [--max N] [--only id,id] [--delay s]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf("--" + name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const TARGETS = arg("targets", path.join(here, "../data/operations/rendered_pages.json"));
const OUT = arg("out", path.join(here, "../data/operations/rendered_cache"));
const MAX_PAGES = Number(arg("max", "60"));
const DELAY_MS = Math.max(3, Number(arg("delay", "3"))) * 1000;
const ONLY = arg("only", "") ? arg("only", "").split(",") : null;
const NAV_TIMEOUT = 30000;
const CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const UA = CHROME + " (compatible; XlakeBot/1.0; +https://xlake.site/about)";
const MAX_TEXT = 200000;
const MAX_HTML = 300000;
const MAX_LINKS = 300;

const CHALLENGE = /(just a moment|checking your browser|verify you are (a )?human|are you a robot|captcha|attention required|access denied|request blocked|enable javascript and cookies|pardon our interruption)/i;

// ---- robots.txt (RFC 9309 subset: longest match wins, allow beats disallow on tie) ----
function parseRobots(body) {
  const groups = [];
  let cur = null;
  let lastWasAgent = false;
  for (const raw of body.split(/\r?\n/)) {
    const line = raw.replace(/#.*/, "").trim();
    const m = line.match(/^([A-Za-z-]+)\s*:\s*(.*)$/);
    if (!m) continue;
    const k = m[1].toLowerCase();
    const v = m[2].trim();
    if (k === "user-agent") {
      if (!cur || !lastWasAgent) {
        cur = { agents: [], rules: [] };
        groups.push(cur);
      }
      cur.agents.push(v.toLowerCase());
      lastWasAgent = true;
    } else if ((k === "allow" || k === "disallow") && cur) {
      lastWasAgent = false;
      if (v) cur.rules.push({ allow: k === "allow", pat: v });
      else if (k === "allow") cur.rules.push({ allow: true, pat: "/" });
    } else {
      lastWasAgent = false;
    }
  }
  const pick = (name) => groups.filter((g) => g.agents.some((a) => a !== "*" && name.includes(a)));
  let sel = pick("xlake");
  if (!sel.length) sel = groups.filter((g) => g.agents.includes("*"));
  return sel.flatMap((g) => g.rules);
}
function patToRe(pat) {
  const esc = pat.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp("^" + esc.replace(/\\\$$/, "$"));
}
export function robotsAllows(rules, p) {
  let best = null;
  for (const r of rules) {
    if (!patToRe(r.pat).test(p)) continue;
    if (!best || r.pat.length > best.pat.length || (r.pat.length === best.pat.length && r.allow)) best = r;
  }
  return !best || best.allow;
}
const robotsCache = new Map();
async function robotsFor(origin) {
  if (robotsCache.has(origin)) return robotsCache.get(origin);
  let rules = [];
  let blanket = false;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 10000);
    const res = await fetch(origin + "/robots.txt", { headers: { "User-Agent": UA }, signal: ctl.signal });
    clearTimeout(t);
    if (res.ok) rules = parseRobots((await res.text()).slice(0, 1000000));
    else if (res.status >= 500) blanket = false; // unreachable: treated as allow, like the Python engine
  } catch {
    blanket = false;
  }
  const v = { rules, blanket };
  robotsCache.set(origin, v);
  return v;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function renderOne(browser, t) {
  const rec = {
    id: t.id, category: t.category || null, url: t.url, final_url: t.url,
    fetched_at: new Date().toISOString(), status: "ok", http_status: null,
    title: "", text: "", html: "", links: [],
  };
  const u = new URL(t.url);
  const rb = await robotsFor(u.origin);
  if (!robotsAllows(rb.rules, u.pathname + u.search)) {
    rec.status = "robots_disallowed";
    return rec;
  }
  const ctx = await browser.newContext({ userAgent: UA, locale: "en-US", viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.route("**/*", (route) => {
    const rt = route.request().resourceType();
    return rt === "image" || rt === "font" || rt === "media" ? route.abort() : route.continue();
  });
  try {
    const resp = await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT });
    rec.http_status = resp ? resp.status() : null;
    if (t.wait_for) {
      await page.waitForSelector(t.wait_for, { timeout: 10000 }).catch(() => {});
    } else {
      await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    }
    await page.waitForTimeout(1500);
    rec.final_url = page.url();
    // Redirect off-host to a place robots has not been checked for: re-check.
    const fu = new URL(rec.final_url);
    if (fu.origin !== u.origin) {
      const rb2 = await robotsFor(fu.origin);
      if (!robotsAllows(rb2.rules, fu.pathname + fu.search)) {
        rec.status = "robots_disallowed";
        return rec;
      }
    }
    rec.title = (await page.title()).slice(0, 300);
    rec.text = (await page.evaluate(() => document.body ? document.body.innerText : "")).slice(0, MAX_TEXT);
    rec.html = (await page.evaluate(() => {
      const el = document.querySelector("main") || document.querySelector("article") || document.body;
      el.querySelectorAll("script,style,noscript,svg,iframe").forEach((n) => n.remove());
      return el ? el.innerHTML : "";
    })).slice(0, MAX_HTML);
    rec.links = (await page.evaluate((cap) => Array.from(document.querySelectorAll("a[href]"))
      .map((a) => ({ href: a.href, text: (a.innerText || a.getAttribute("aria-label") || "").trim().slice(0, 160) }))
      .filter((l) => /^https?:/.test(l.href)).slice(0, cap), MAX_LINKS)) || [];
    const probe = rec.title + " " + rec.text.slice(0, 600);
    if (CHALLENGE.test(probe) && rec.text.length < 3000) rec.status = "challenge";
    else if (rec.http_status === 404 || rec.http_status === 410) rec.status = "not_found";
    else if (rec.http_status === 403 || rec.http_status === 429) rec.status = "blocked";
    else if (rec.http_status && rec.http_status >= 400) rec.status = "blocked";
    else if (rec.text.trim().length < 200) rec.status = "empty";
  } catch (e) {
    rec.status = /timeout/i.test(String(e)) ? "timeout" : "error";
    rec.error = String(e).slice(0, 200);
  } finally {
    await ctx.close();
  }
  if (rec.status !== "ok") { rec.text = rec.status === "empty" ? rec.text : ""; rec.html = ""; rec.links = []; }
  return rec;
}

async function main() {
  let targets = JSON.parse(fs.readFileSync(TARGETS, "utf8"));
  if (ONLY) targets = targets.filter((t) => ONLY.includes(t.id));
  targets = targets.slice(0, MAX_PAGES);
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const counts = {};
  let lastHost = null;
  let lastAt = 0;
  for (const t of targets) {
    // Strictly sequential, so one page at a time per host; delay >= 3s always.
    const wait = lastAt + DELAY_MS - Date.now();
    if (wait > 0 && lastAt) await sleep(wait);
    const rec = await renderOne(browser, t);
    lastAt = Date.now();
    lastHost = new URL(t.url).host;
    fs.writeFileSync(path.join(OUT, t.id + ".json"), JSON.stringify(rec, null, 1) + "\n");
    counts[rec.status] = (counts[rec.status] || 0) + 1;
    console.log(`${rec.status.padEnd(17)} ${t.id} ${rec.http_status || "-"} chars=${rec.text.length}`);
  }
  await browser.close();
  console.log("SUMMARY " + JSON.stringify(counts) + " host_last=" + lastHost);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

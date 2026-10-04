"use strict";

const $ = (id) => document.getElementById(id);

// Blocked site data (a browser setting, some in-app webviews) makes merely
// touching window.localStorage throw — at the first top-level read below, that
// aborted this whole script and the page never hydrated. This binding shadows
// the global for every read and write in the file: the real store when it
// works, else a per-page memory map (the app runs; nothing persists, as asked).
const localStorage = (() => {
  try { const s = window.localStorage; s.getItem("wg"); return s; } catch (e) {}
  const m = new Map();
  return {
    getItem: (k) => (m.has(String(k)) ? m.get(String(k)) : null),
    setItem: (k, v) => { m.set(String(k), String(v)); },
    removeItem: (k) => { m.delete(String(k)); },
    clear: () => m.clear(),
  };
})();

// This script's own deploy stamp (server.py rewrites /app.js to /app.js?v=<mtime>).
// Must be read at top level: document.currentScript is only set while the script
// is first executing, not later inside a function.
const ASSET_V = (() => {
  const m = ((document.currentScript && document.currentScript.src) || "").match(/[?&]v=([^&]+)/);
  return m ? m[1] : "";
})();
const stamped = (path) => (ASSET_V ? path + "?v=" + ASSET_V : path);
let lastRates = null;   // always USD-based — feeds the Top Picks scoring
let dataRates = null;   // whatever the Explore-the-Data currency view shows

// The one currency the whole site reasons in. Top Picks' "In" and the Data tab's
// "My currency" used to be separate state (fx_homecur vs fx_database), so setting
// one left the other disagreeing — the same question answered twice. Both selects
// are now views onto this, the way valueOrigin/flightOrigin already share fx_origin.
// Read from storage here rather than in initHomeCur so the first rates fetch asks
// for the right base instead of loading USD and correcting itself.
let homeBase = /^[A-Z]{3}$/.test(localStorage.getItem("fx_homecur") || "")
  ? localStorage.getItem("fx_homecur") : "USD";
// The dollar had a word ("the dollar") and every other home currency a bare
// code in the same sentence ("Where EUR is strong"). The common ones get their
// word; the rest read as "your money" — never a code where a word belongs.
const CUR_WORD = { USD: "the dollar", EUR: "the euro", GBP: "the pound", JPY: "the yen", CHF: "the franc",
                   INR: "the rupee", CAD: "the Canadian dollar", AUD: "the Australian dollar",
                   NZD: "the New Zealand dollar", SGD: "the Singapore dollar", HKD: "the Hong Kong dollar",
                   MXN: "the peso", BRL: "the real", KRW: "the won", CNY: "the yuan", ZAR: "the rand",
                   SEK: "the krona", NOK: "the krone", DKK: "the krone", PLN: "the złoty", TRY: "the lira" };
const baseWord = (b) => CUR_WORD[b] || "your money";

// Escape any externally-sourced string before it goes into innerHTML.
// (Currency names, advisory titles, flight city names, etc. come from
// third-party APIs and must never be trusted as HTML.)
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Read a theme color from CSS custom properties (so SVG charts follow dark mode).
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

// ---- light / dark theme -----------------------------------------------------
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("fx_theme", t);
  const btn = $("themeBtn");
  if (btn) btn.textContent = t === "dark" ? "☀️" : "🌙";
  if (lastIndexData) renderIndex(lastIndexData);   // redraw charts in new palette
  if (plHist) renderCol();
  if ($("fbmChart") && $("fbmChart")._redraw) renderFbm();
}
function initTheme() {
  // Default follows the browser/OS color scheme; a manual toggle overrides and
  // is remembered. Until then, live OS changes are tracked too.
  const mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  const sys = () => (mq && mq.matches ? "dark" : "light");
  const stored = localStorage.getItem("fx_theme");
  const t = stored || sys();
  document.documentElement.dataset.theme = t;
  const btn = $("themeBtn");
  if (btn) {
    btn.textContent = t === "dark" ? "☀️" : "🌙";
    btn.onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  }
  if (mq && mq.addEventListener) {
    mq.addEventListener("change", () => {
      if (!localStorage.getItem("fx_theme")) {   // no manual override yet
        document.documentElement.dataset.theme = sys();
        if (btn) btn.textContent = sys() === "dark" ? "☀️" : "🌙";
        if (lastIndexData) renderIndex(lastIndexData);
        if (plHist) renderCol();
        if ($("fbmChart") && $("fbmChart")._redraw) renderFbm();
      }
    });
  }
}
let lastIndexData = null;

// Transient by default: a "fares folded into the score" note was sitting at
// the top of the page across tab switches until something happened to
// overwrite it (the owner asked why). Non-sticky messages fade after a few
// seconds and die on tab switch; sticky ones (the shared-view warnings, which
// describe an ongoing state) stay until replaced.
let _statusTimer = null;
// #status and #acctnote are polite live regions. A screen reader only reads a
// change to a region that is already showing: text that arrives in the same
// frame that un-hides the box is never announced. So un-hide it empty, and put
// the words in a frame later. Two requestAnimationFrames, not one: a single
// rAF callback still runs before that frame's accessibility update, so the
// region would appear with its text in one step, exactly as before. The empty
// frame is transparent (opacity keeps it in the accessibility tree, where
// hidden/visibility would not), so the toast doesn't flash an empty pill.
// The text is prepended, not assigned: a caller may append its own controls
// right after (the Clear-all Undo), and assigning textContent later would
// wipe them. `quiet` keeps the old synchronous path, for page-load chatter
// nobody needs read out.
const _liveRaf = new WeakMap();
function _liveSet(el, msg, quiet) {
  cancelAnimationFrame(_liveRaf.get(el));
  el.style.opacity = "";
  el.textContent = quiet ? msg : "";
  el.hidden = !msg;
  if (!msg || quiet) return;
  el.style.opacity = "0";
  _liveRaf.set(el, requestAnimationFrame(() => _liveRaf.set(el, requestAnimationFrame(() => {
    el.prepend(msg);
    el.style.opacity = "";
  }))));
}
function status(msg, kind, sticky, quiet) {
  const el = $("status");
  clearTimeout(_statusTimer);
  _liveSet(el, msg, quiet);
  el.className = "status " + (kind || "");
  el.dataset.sticky = sticky ? "1" : "";
  if (msg && !sticky) _statusTimer = setTimeout(() => { el.hidden = true; }, 6000);
}
function clearTransientStatus() {
  const el = $("status");
  if (el && !el.dataset.sticky) { clearTimeout(_statusTimer); el.hidden = true; }
}

async function getJSON(url) {
  const r = await fetch(url);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

function fmt(n) {
  // Decimals scale with magnitude, so every rate reads to about four significant
  // figures and none of them are longer than they need to be. A flat one decimal
  // would round the euro to 0.9 and the dinar to 0.3 — precision that matters at
  // that scale — while 336.2501 was four digits of noise eating the column next
  // to it. Yields 18,067 · 336.3 · 47.03 · 0.8612.
  const a = Math.abs(n);
  const dp = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : 4;
  return n.toLocaleString(undefined, { maximumFractionDigits: dp });
}

function rangeMarker(r) {
  // Where today's rate sits between the window low and high. A rate near its
  // 1-year high means your currency buys more than usual → dot to the right,
  // on the green (strong) end of the track. Left/grey = weak.
  const span = r.high - r.low;
  const pct = span > 0 ? ((r.rate_now - r.low) / span) * 100 : 50;
  const clamped = Math.max(0, Math.min(100, pct));
  // Nominal rate: says where the rate sits, not what money buys — in a
  // high-inflation country prices can outrun a currency that looks strong.
  const meaning = clamped >= 66 ? "near its 1-year high — a stronger rate than most of the past year"
                : clamped <= 34 ? "near its 1-year low — a weaker rate than most of the past year"
                : "mid-range for the past year";
  const tip = `Today sits ${Math.round(clamped)}% up its 1-year range `
            + `(low ${fmt(r.low)} · high ${fmt(r.high)}) — ${meaning}. Further right = your currency is stronger`
            + ` (nominal rate, before inflation).`;
  return `<div class="range" title="${esc(tip)}"><span style="left:${clamped}%"></span></div>`;
}

const DAY_LABEL = { 30: "1 month", 90: "3 months", 180: "6 months", 365: "1 year" };
// The FX free tier only reaches ~366 days back, so rates.py caps history at 364 —
// which meant asking for a year got 364 days, missed this map's exact 365 key, and
// printed a raw "364d" at people. Nobody is served by that pedantry: snap to the
// named window when we're within a week of it. The subtitle prints the exact dates
// either way, so precision isn't lost, only the noise.
function dayLabel(days) {
  for (const d of Object.keys(DAY_LABEL)) if (Math.abs(days - d) <= 7) return DAY_LABEL[d];
  return days + "d";
}

// The strength chart reads like a stock chart: one index with a fixed base
// (Jan 1999 = 100 on the ECB history), so the level is the same on every
// range and only the change over the range moves.
const RANGE_SPAN = { "1m": "past month", "3m": "past 3 months", "6m": "past 6 months", ytd: "this year",
                     "1y": "past year", "2y": "past 2 years", "5y": "past 5 years", "10y": "past 10 years" };
const fmtIdx = (v) => (Math.abs(v) >= 10 ? v.toFixed(1) : v.toPrecision(3));
const fmtPct = (p) => (p >= 0 ? "+" : "−") + Math.abs(p).toFixed(Math.abs(p) >= 10 ? 1 : 2) + "%";
// A signed percentage as the Cost table prints it: a true minus (U+2212) —
// toFixed's "-0.6%" is a hyphen, shorter and higher than the "+" beside it in
// the Currency table — and no sign on a figure that rounds to nothing (never
// "−0.0%" or "+0.0%"). `dp` decimals, by toFixed as the callers always
// printed them; a caller that printed Math.round(x) passes that (toFixed(0)
// rounds -2.5 to -3, Math.round to -2).
function signedPct(p, dp) {
  const s = Number(p).toFixed(dp || 0);
  if (/^-?[0.]+$/.test(s)) return s.replace("-", "") + "%";
  return (s[0] === "-" ? "−" + s.slice(1) : "+" + s) + "%";
}
// The same minus for a figure that only sometimes goes below zero (an
// inflation rate in deflation: "−1% in 2024", not "-1%").
const trueMinus = (v) => String(v).replace(/^-/, "−");
// "2026-09-25" -> "25 Sep 2026" (day-month-year reads the same to everyone;
// month-first was the one US-only habit left in the copy); "Jan 1999" for
// the base
function fmtDay(iso) {
  const p = iso.split("-");
  return (+p[2]) + " " + MON_ABBR[+p[1] - 1] + " " + p[0];
}
// "2026-05-21" -> "21 May": when an advisory last moved, everywhere it is
// shown (the Safety tab's list and arrows, the guide's safety line, Top
// Picks' mark). They used to print it three ways — "21 May", "May 21" and
// "21 May 2026" — for one date. Day first like fmtDay; the year only once
// it isn't this one.
function fmtDayShort(iso) {
  const p = String(iso || "").slice(0, 10).split("-");
  if (p.length < 3 || !MON_ABBR[+p[1] - 1]) return String(iso || "");
  return (+p[2]) + " " + MON_ABBR[+p[1] - 1] + (+p[0] === new Date().getFullYear() ? "" : " " + p[0]);
}
// Money in any currency, the browser's way: "$601", "€481", "₹8,000". "USD 295"
// beside "$100" was two looks for the same idea, and the sign was the dollar's
// alone. Whole units — cached averages and annual indexes, not receipts. A
// code Intl doesn't know (GGP) falls back to "GGP 100".
function fmtCur(code, v) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code,
      minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(v);
  } catch (e) { return code + " " + Math.round(v).toLocaleString(); }
}
const CORE_NAME = { USD: "dollar", EUR: "euro", JPY: "yen", GBP: "pound", CHF: "Swiss franc" };
const fmtMonYear = (iso) => MON_ABBR[+iso.slice(5, 7) - 1] + " " + iso.slice(0, 4);
// A round step for ~n ticks across span: 1, 2, 2.5 or 5 x 10^k.
function niceStep(span, n) {
  const raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * mag) return m * mag;
  return 10 * mag;
}
// Calendar ticks, like a stock chart's: weeks on a month, months up to two
// years (every 2nd on a year, every 3rd on two), then years. -> [{i, label,
// year}], year = a year boundary, which is placed first when space is short.
function indexTicks(pts) {
  const first = new Date(pts[0].date + "T00:00:00Z"), last = new Date(pts[pts.length - 1].date + "T00:00:00Z");
  const span = (last - first) / 86400000;
  const out = [];
  let prevKey = null;
  pts.forEach((p, i) => {
    const d = new Date(p.date + "T00:00:00Z");
    let key, label;
    if (span <= 45) {
      // The first fixing of each week (Monday, or later after a holiday).
      const wk = Math.floor((d - Date.UTC(1970, 0, 5)) / (7 * 86400000));
      key = wk; label = MON_ABBR[d.getUTCMonth()] + " " + d.getUTCDate();
    } else if (span <= 800) {
      const m = d.getUTCMonth(), step = span <= 200 ? 1 : span <= 400 ? 2 : 3;
      key = d.getUTCFullYear() * 12 + m;
      if (m % step) { prevKey = key; return; }
      label = m === 0 ? String(d.getUTCFullYear()) : MON_ABBR[m];
      if (m === 0) { if (i > 0 && key !== prevKey) out.push({ i, label, year: true }); prevKey = key; return; }
    } else {
      const y = d.getUTCFullYear(), yrs = span / 365.25;
      const step = yrs <= 6 ? 1 : yrs <= 12 ? 2 : 5;
      key = y;
      if (y % step) { prevKey = key; return; }
      label = String(y);
      if (i > 0 && key !== prevKey) out.push({ i, label, year: true });
      prevKey = key;
      return;
    }
    if (i > 0 && key !== prevKey) out.push({ i, label });
    prevKey = key;
  });
  return out;
}

function renderIndex(data) {
  const pts = data.index || [];
  const rng = data.range || "1y";
  const chg = Number(data.change_pct != null ? data.change_pct : data.index_change_pct) || 0;
  const up = chg >= 0;
  const span = rng === "all" ? "since " + (pts.length ? pts[0].date.slice(0, 4) : "") : RANGE_SPAN[rng] || "";
  const nowEl = $("indexnow"), chgEl = $("indexchg");
  const showHead = (value, text, pos) => {
    nowEl.textContent = value;
    chgEl.textContent = text;
    chgEl.className = pos ? "pos" : "neg";
  };
  // The arrow is the sign: "▼ −2.31%" said it twice.
  const restHead = () => showHead(pts.length ? fmtIdx(pts[pts.length - 1].value) : "—",
                                  (up ? "▲ " : "▼ ") + fmtPct(chg).slice(1) + " " + span, up);
  restHead();
  $("chartsub").textContent = `Equal-weighted across ${data.index_count} currencies`
    + (pts.length ? ` · ${fmtDay(pts[0].date)} → ${fmtDay(data.as_of)}` : "");
  // Nominal, and over decades that matters: high-inflation currencies drift
  // down against everything, which reads as the dollar "up 31% since 1999"
  // while against the euro, yen, pound and franc it is ~2%. The ⓘ says so,
  // with that core figure for the same range.
  const core = data.core_change_pct;
  const coreNames = ["USD", "EUR", "JPY", "GBP", "CHF"].filter((c) => (data.core || []).includes(c))
    .map((c) => CORE_NAME[c]);
  // The history is the ECB's, not fxratesapi's (rates.py): the longest-horizon
  // number on the site names its source here, and the footer credits it.
  const tip = "Exchange rates before inflation: a currency with high inflation slides against the rest "
    + "over the years, so long ranges can run well ahead of what prices abroad feel like."
    + (core != null && coreNames.length
      ? ` Against the ${coreNames.slice(0, -1).join(", ")} and ${coreNames[coreNames.length - 1]} alone: ${fmtPct(core)} ${span}.`
      : "")
    // Credit the history's source here: the footer names today's rate feed,
    // and this line ends on the ECB's last fixing, not today.
    + (data.source === "ecb" ? " Built on ECB euro reference rates (daily fixings, back to 1999)." : "");
  $("chartnote").innerHTML = esc(`Index: ${data.base_date ? fmtMonYear(data.base_date) : "start"} = 100. Higher = `
    + `${baseWord(data.base || "USD")} buys more of ${data.index_count} other currencies (before inflation).`)
    + ` <span class="muted" data-tip="${esc(tip)}" title="">ⓘ</span>`;

  const host = $("chart");
  if (pts.length < 2) { host.innerHTML = "<p class='hint'>Not enough data.</p>"; host._redraw = null; return; }
  stockChart(host, pts, {
    color: up ? cssVar("--green", "#0a7d28") : cssVar("--red", "#b00020"),
    aria: `${data.base || "USD"} strength index ${fmtIdx(pts[pts.length - 1].value)}, ${fmtPct(chg)} ${span}`,
    // Scrub: that day in the headline — its level, date and change since the
    // range began.
    onScrub: (i) => {
      const c = (pts[i].value / pts[0].value - 1) * 100;
      showHead(fmtIdx(pts[i].value), fmtDay(pts[i].date) + " · " + (c >= 0 ? "▲ " : "▼ ") + fmtPct(c), c >= 0);
    },
    onLeave: restHead,
  });
}

// A stock-style line chart into `host`: drawn at the host's own pixel width
// (and redrawn when that changes, so axis text is 12px on a phone too — a
// fixed 800-wide viewBox shrank it to ~6px there), price axis on the right,
// calendar ticks, gradient fill, a dotted line where the range started, and a
// hover / finger scrub. pts: [{date: "YYYY-MM-DD", value}], at least two.
// o: color, aria, onScrub(i), onLeave(), byDate (x by date, not by point —
// for yearly points followed by a "today" one), ref: {value, label} (a
// dotted reference level, drawn only inside the range), noStart (no start line).
function stockChart(host, pts, o) {
  const W = Math.round(host.clientWidth) || 800;
  // In a card row the box is sized by the layout (as tall as its neighbour
  // card leaves room for) and the chart fills it; elsewhere it takes a shape.
  const fill = !!host.closest(".toprow");
  const H = fill && host.clientHeight >= 150 ? Math.round(host.clientHeight)
    : Math.max(190, Math.min(300, Math.round(W * 0.4)));
  const vals = pts.map((p) => p.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.01 || 1;
  lo -= pad; hi += pad;
  // Price levels on round values, at least three: four steps sometimes left two.
  let step = niceStep(hi - lo, 4);
  for (const n of [5, 6, 8]) {
    if (Math.floor(hi / step) - Math.ceil(lo / step) + 1 >= 3) break;
    step = niceStep(hi - lo, n);
  }
  const dec = (String(+step.toPrecision(2)).split(".")[1] || "").length;   // 2.5 -> 1, 0.05 -> 2
  const levels = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) levels.push(v);
  // The axis is as wide as its widest label ("126.75" clipped at a fixed 46).
  const padL = 2, padT = 12, padB = 26;
  const padR = Math.max(46, Math.ceil(7 * Math.max(...levels.map((v) => v.toFixed(dec).length))) + 12);
  const plotW = W - padL - padR, plotH = H - padT - padB, right = W - padR;
  const t0 = Date.parse(pts[0].date), tN = Date.parse(pts[pts.length - 1].date);
  const frac = o.byDate && tN > t0 ? pts.map((p) => (Date.parse(p.date) - t0) / (tN - t0))
                                   : pts.map((p, i) => i / (pts.length - 1));
  const x = (i) => padL + frac[i] * plotW;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  const color = o.color;
  const gridCol = cssVar("--chartgrid", "#eee");
  const labCol = cssVar("--gray", "#999");

  // Price gridlines, labelled at the right edge.
  let grid = "";
  for (const v of levels) {
    const gy = y(v).toFixed(1);
    grid += `<line x1="${padL}" y1="${gy}" x2="${right}" y2="${gy}" stroke="${gridCol}" stroke-width="1"/>`
      + `<text x="${right + 8}" y="${(+gy + 4).toFixed(1)}" font-size="12" fill="${labCol}">${v.toFixed(dec)}</text>`;
  }
  // Date gridlines at calendar boundaries; a label that would run past the
  // plot is dropped rather than squeezed.
  // Years go down first, so a narrow card keeps "2025 … 2026" rather than
  // "Oct Apr Oct Apr"; months and weeks fill in where they fit.
  const lw = (t) => 7.5 * t.label.length + 12;
  const placed = [];
  const ticks = indexTicks(pts);
  for (const t of ticks.filter((t) => t.year).concat(ticks.filter((t) => !t.year))) {
    const tx = x(t.i);
    if (tx > right - lw(t) + 8) continue;
    if (placed.some((p) => (tx >= p.x ? tx - p.x < lw(p) : p.x - tx < lw(t)))) continue;
    placed.push({ x: tx, label: t.label, i: t.i });
  }
  let xlab = "";
  for (const t of placed.sort((a, b) => a.x - b.x)) {
    const tx = t.x;
    xlab += `<line x1="${tx.toFixed(1)}" y1="${padT}" x2="${tx.toFixed(1)}" y2="${H - padB}" stroke="${gridCol}" stroke-width="1"/>`
      + `<text x="${(tx + 4).toFixed(1)}" y="${H - 7}" font-size="12" fill="${labCol}">${t.label}</text>`;
  }
  // Where the range started, dotted: above it = up over the range.
  const sy = y(pts[0].value).toFixed(1);
  const startLine = o.noStart ? ""
    : `<line x1="${padL}" y1="${sy}" x2="${right}" y2="${sy}" stroke="${labCol}" stroke-width="1" stroke-dasharray="2 4" opacity=".7"/>`;
  let refLine = "";
  if (o.ref && o.ref.value > lo && o.ref.value < hi) {
    const ry = y(o.ref.value).toFixed(1);
    refLine = `<line x1="${padL}" y1="${ry}" x2="${right}" y2="${ry}" stroke="${labCol}" stroke-width="1.2" stroke-dasharray="5 4"/>`
      + (o.ref.label ? `<text x="${padL + 4}" y="${(+ry - 5).toFixed(1)}" font-size="11" fill="${labCol}">${esc(o.ref.label)}</text>` : "");
  }

  const line = pts.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.value).toFixed(1)).join(" ");
  const area = line + ` L${x(pts.length - 1).toFixed(1)} ${H - padB} L${x(0).toFixed(1)} ${H - padB} Z`;
  const lastX = x(pts.length - 1), lastY = y(pts[pts.length - 1].value);
  const gid = "fill-" + host.id;

  host.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.aria || "")}">`
    + `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">`
    + `<stop offset="0" stop-color="${color}" stop-opacity=".32"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`
    + grid + xlab + startLine + refLine
    + `<path d="${area}" fill="url(#${gid})"/>`
    + `<path d="${line}" fill="none" stroke="${color}" stroke-width="2.2" stroke-linejoin="round"/>`
    + `<circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3.5" fill="${color}"/>`
    + `<g class="scrub" visibility="hidden"><line y1="${padT}" y2="${H - padB}" stroke="${labCol}" stroke-width="1"/>`
    + `<circle r="4.5" fill="${color}" stroke="${cssVar("--card", "#fff")}" stroke-width="2"/></g>`
    + `</svg>`;

  // Scrub: hovering (or dragging a finger along) the chart hands the nearest
  // point to o.onScrub, and o.onLeave when it ends.
  const svg = host.querySelector("svg"), scrub = svg.querySelector(".scrub");
  const sl = scrub.querySelector("line"), sc = scrub.querySelector("circle");
  const at = (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    let i = 0;
    for (let j = 1; j < pts.length; j++) if (Math.abs(x(j) - vx) < Math.abs(x(i) - vx)) i = j;
    const px = x(i).toFixed(1), py = y(pts[i].value).toFixed(1);
    sl.setAttribute("x1", px); sl.setAttribute("x2", px);
    sc.setAttribute("cx", px); sc.setAttribute("cy", py);
    scrub.setAttribute("visibility", "visible");
    if (o.onScrub) o.onScrub(i);
  };
  const off = () => { scrub.setAttribute("visibility", "hidden"); if (o.onLeave) o.onLeave(); };
  svg.addEventListener("pointermove", at);
  svg.addEventListener("pointerdown", at);
  svg.addEventListener("pointerleave", off);
  svg.addEventListener("pointercancel", off);
  svg.addEventListener("pointerup", (e) => { if (e.pointerType !== "mouse") off(); });
  // Redraw whenever the host's width differs from the width last DRAWN — a
  // render while its tab was hidden drew at the 800 fallback, and comparing
  // with the previous observed width left it there (5px text on a phone).
  // Next frame, not inside the callback: the redraw changes the host's height,
  // which inside it is a "ResizeObserver loop" error in Firefox and Safari.
  host._w = W; host._h = H;
  host._redraw = () => stockChart(host, pts, o);
  if (!host._ro && window.ResizeObserver) {
    host._ro = new ResizeObserver(() => requestAnimationFrame(() => refitChart(host)));
    host._ro.observe(host);
  }
}
function refitChart(host) {
  if (!host || !host._redraw || !host.clientWidth) return;
  const fill = !!host.closest(".toprow") && host.clientHeight >= 150;
  if (Math.abs(host.clientWidth - (host._w || 0)) > 4
      || (fill && Math.abs(host.clientHeight - (host._h || 0)) > 4)) host._redraw();
}

// Client-side sort for the currency table. Default matches the server order
// (vs-avg, strongest-first); clicking a header re-sorts, clicking again flips.
const CUR_SORT_GET = {
  code:  (r) => r.code,
  rate:  (r) => r.rate_now,
  vsavg: (r) => r.strength_pct,
  price: (r) => { const sp = currencySpread(r.code); return sp ? sp.mid : null; },   // null sorts last
  range: (r) => { const s = r.high - r.low; return s > 0 ? (r.rate_now - r.low) / s : 0.5; },
};
const CUR_SORT_DEFAULT_ASC = { code: true, rate: false, vsavg: false, price: true, range: false };
const curSort = { key: "vsavg", asc: false };

function sortedRates(rows) {
  const get = CUR_SORT_GET[curSort.key] || CUR_SORT_GET.vsavg;
  const dir = curSort.asc ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = get(a), vb = get(b);
    if (typeof va === "string") return dir * va.localeCompare(vb);
    // Missing/non-finite values (e.g. no price level) always sort to the bottom.
    const na = va == null || !isFinite(va), nb = vb == null || !isFinite(vb);
    if (na || nb) return na - nb;
    return dir * (va - vb);
  });
}

// Show a ▲/▼ marker (and aria-sort) on the active sort header.
function updateCurSortIndicators() { markSort("#rates", curSort); }
// Clicking a header sorts by that column (each column has a sensible first
// direction); clicking the active column again reverses it. Same wiring as
// every other table, so the keyboard path and aria-sort come with it.
wireSort("#rates", curSort, CUR_SORT_DEFAULT_ASC, () => { if (dataRates) renderRates(dataRates); });

// ---- generic click-to-sort for the other data tables (same UX as currency) --
// Headers carry class="sortable" data-sk="col" (label in a button.sortbtn);
// each table has a getters map, a sort-state object, a first-click direction
// map (default asc unless false), and a re-render callback.
// nameOf (optional) breaks ties A-Z whichever way the column runs: the Safety
// table's default Level sort had "Vatican City" between Guam and Hungary.
// The Top Picks tables don't pass it (their order is the ranking's).
function sortRows(rows, state, getters, nameOf) {
  const get = getters[state.key];
  if (!get) return rows.slice();
  const dir = state.asc ? 1 : -1;
  const tie = (a, b) => (nameOf ? String(nameOf(a)).localeCompare(String(nameOf(b))) : 0);
  return rows.slice().sort((a, b) => {
    const va = get(a), vb = get(b);
    if (typeof va === "string" || typeof vb === "string")
      return dir * String(va).localeCompare(String(vb)) || tie(a, b);
    const na = va == null || !isFinite(va), nb = vb == null || !isFinite(vb);
    if (na || nb) return na - nb || tie(a, b);   // blanks/unknowns always last
    return dir * (va - vb) || tie(a, b);
  });
}
// WAI-ARIA APG sortable table: the th keeps its columnheader role (a role on
// the th itself would hide aria-sort and break header/cell association) and
// a real <button> inside it is the control, so Enter/Space and focus come
// free. Labels live in the markup's .sortbtn; any header whose text was
// rewritten without one gets it back here, so it can't silently drop out of
// the tab order.
function markSort(theadSel, state) {
  document.querySelectorAll(theadSel + " th.sortable").forEach((th) => {
    if (!th.querySelector(".sortbtn")) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "sortbtn";
      while (th.firstChild) b.appendChild(th.firstChild);
      th.appendChild(b);
    }
    const cur = th.dataset.sk === state.key;
    th.dataset.sortdir = cur ? (state.asc ? "asc" : "desc") : "";
    th.setAttribute("aria-sort", cur ? (state.asc ? "ascending" : "descending") : "none");
  });
}
function wireSort(theadSel, state, firstAsc, rerender) {
  const act = (th) => {
    const sk = th.dataset.sk;
    if (state.key === sk) state.asc = !state.asc;
    else { state.key = sk; state.asc = firstAsc[sk] !== false; }
    const hadFocus = th.contains(document.activeElement);
    markSort(theadSel, state);   // static theads never re-render
    rerender();
    // The grade tables rebuild their thead, taking the focused button with
    // it; put focus back on the same column's new button.
    const nb = hadFocus && document.querySelector(theadSel + ' th.sortable[data-sk="' + sk + '"] .sortbtn');
    if (nb && nb !== document.activeElement) nb.focus();
  };
  // A native button fires click for Enter and Space too, so this one listener
  // is the mouse, touch and keyboard path.
  document.addEventListener("click", (e) => {
    const th = e.target.closest(theadSel + " th.sortable");
    if (th) act(th);
  });
}
// aria-sort for a header the grade tables emit as a string; markSort adds
// the button after the table lands.
function sortableThAttrs(state, sk) {
  const cur = state.key === sk;
  return ' aria-sort="' + (cur ? (state.asc ? "ascending" : "descending") : "none") + '"';
}

// Cost of living: cheapest-first by default; "$100 buys" is the inverse of the
// price level, so it opens descending (most goods first).
// name sorts by what the row actually shows, or "Laos" would file under L-a-o
// PDR while the eye looks for it under Laos.
const AFF_GET = { name: (r) => countryName(r.iso), cur: (r) => r.cur, pl: (r) => r.pl,
                  buys: (r) => 100 / r.pl, vs: (r) => (r.tr ? r.tr.pct : null),
                  range: (r) => (r.tr ? r.tr.pos : null) };
const affSort = { key: "pl", asc: true };
wireSort("#affTable", affSort, { buys: false, range: false }, () => { if (typeof ppp !== "undefined" && ppp) renderAfford(); });

// Safety: safest (Level 1) first by default. Risks sorts by how many
// reasons a row names, most first, ties by level — with every "do not
// travel" above the rest, however few reasons it names (Ukraine's one, "the
// Russia-Ukraine war", sat at #99 below France's two). Health sorts by how
// many diseases, ties by level. A country Canada's health advice doesn't
// cover sorts last (null).
const advLvl = (it) => parseInt(it.level, 10) || 0;
const ADV_GET = { country: (it) => advName(it), level: advLvl,
                  risks: (it) => (advLvl(it) >= 4 ? 1000 : 0) + (it._rk ? it._rk.length : 0) * 10 + advLvl(it),
                  health: (it) => (it._hz || it._wn ? ((it._hz ? it._hz.h.length + (it._hz.n ? it._hz.n.length / 2 : 0) : 0)
                    + (it._wn ? 1 : 0)) * 10 + advLvl(it) : null) };
const advSort = { key: "level", asc: true };
wireSort("#advTable", advSort, { risks: false, health: false }, () => { if (advisories) renderAdvisories(); });

// c.min is the cheapest of the recently cached rows; the month curve is a
// separate sample, so "Cheapest" could sit above the month's own fare in the
// same row (Ecuador: 315 beside an October 295). The column means the cheapest
// fare seen on the route, any month: the lower of the two.
function cheapestFare(c) {
  const curve = (c._fv && c._fv.c && c._fv.c.curve) || {};
  const vals = [Number(c.min), ...Object.values(curve).map((x) => x[0])].filter((x) => x > 0);
  return vals.length ? Math.min(...vals) : null;
}
// Flights: ranked by the chosen month's fare vs the route's own typical year
// (renderFlights stamps each row's _fv), most below typical first. Band first,
// then the %: the band is judged against each route's own middle-half range
// and the % against its median, so sorted by % alone a "Low −8%" landed under
// a "Typical −9%" and read as a contradiction. Rows with no range sort last.
const FV_ORDER = { low: -100, typical: 0, high: 100 };
const FLIGHT_GET = { dest: (c) => countryName(c.iso),
                     vs: (c) => (c._fv && c._fv.dev != null ? FV_ORDER[c._fv.band] + c._fv.dev : null),
                     mfare: (c) => c._fv && c._fv.price, avg: (c) => c.avg, min: (c) => cheapestFare(c),
                     dur: (c) => c.dur, stops: (c) => c.stops };
const flightSort = { key: "vs", asc: true };
wireSort("#flightTable", flightSort, {}, () => { if (flightsData) renderFlights(); });

// Top Picks report card: default overall-value order. Sorting a column
// reorders AND renumbers the same top-N set (rank = row position). Grade
// columns open best-first; Safety opens safest-first (advisory level 1);
// Destination A→Z. Flights with no fare sort last.
const PICK_GET = { dest: (s) => s.name, afford: (s) => s.afford, safety: (s) => s.advLvl,
                   weather: (s) => (s.wx == null ? null : s.wx), flights: (s) => (s.fly == null ? null : s.fly),
                   overall: (s) => s.value };
const pickSort = { key: "overall", asc: false };
wireSort("#topCards", pickSort, { afford: false, weather: false, flights: false, overall: false },
         () => { if (lastPicks && lastPicks.length) renderGradeTable($("topCards"), lastPicks, lastPicksMonth, false, true); });

// Hidden gems: same report-card columns, independent sort state.
const gemSort = { key: "overall", asc: false };
wireSort("#gemRows", gemSort, { afford: false, weather: false, flights: false, overall: false },
         () => { if (lastGems && lastGems.length) renderGradeTable($("gemRows"), lastGems, lastPicksMonth, true, true, gemSort); });

// "Full ranking & the math": every column sorts; numbers open best-first.
// Sorted over the WHOLE ranked list before the top-40 slice, so sorting by
// e.g. affordability shows the 40 most affordable, not a reshuffled top 40.
const FULL_GET = { country: (s) => s.name, value: (s) => s.value, afford: (s) => s.afford,
                   safety: (s) => s.safe, weather: (s) => (s.wx == null ? null : s.wx),
                   flight: (s) => (s.fly == null ? null : s.fly) };
const fullSort = { key: "value", asc: false };
wireSort("#valueTable", fullSort, { value: false, afford: false, safety: false, weather: false, flight: false },
         () => renderValue());

function renderRates(data) {
  const base = data.base || "USD";
  // The USD feed lists USD itself (1 USD = 1, +0.0%): a duplicate in both
  // currency pickers, a self-row in the table, and "USD +0%" on dollarised
  // countries' cards. Other bases already come without their own row.
  if (data.rows) data.rows = data.rows.filter((r) => r.code !== base);
  dataRates = data;
  if (base === "USD") lastRates = data;   // scoring only ever uses USD data
  renderMapSafe();
  buildBaseSelect();
  const w = baseWord(base);
  $("mapH2").innerHTML = `Where ${esc(w)} is strong <span class="muted">vs each currency's 1-year average</span>`;
  // "Overall euro strength"; a currency without a word of its own gets
  // "Overall strength of your money" rather than "Overall your money strength".
  $("chartH2").innerHTML = (w.startsWith("the ") ? `Overall ${esc(w.slice(4))} strength` : `Overall strength of ${esc(w)}`)
    + ` <span class="muted">vs rest of world</span>`;
  // Into the sort button, not the th: textContent on the th would wipe it.
  const rch = $("rateColHead");
  (rch.querySelector(".sortbtn") || rch).textContent = `1 ${base} =`;
  // Says "fixed at a year" on purpose: the chart's window toggle sits directly
  // above this column and looks like it drives it. It must not — this figure is
  // 30% of every Affordability grade, so a zoom control cannot be allowed to
  // re-grade the site, and a one-month average is noise anyway.
  $("vsAvgHead").title =
    `vs its own 1-year average — positive = ${w} is stronger than usual. `
    + `Nominal exchange rate: in high-inflation countries local prices can rise faster `
    + `than the currency falls, so the Affordability grade uses this net of inflation. `
    + `Fixed at a year (the chart's window above doesn't change it): a shorter `
    + `average is mostly noise.`;
  $("asof").textContent = "As of " + fmtDay(data.as_of);
  // A pegged currency (XOF, BAM, GGP...) moves exactly with its anchor (the
  // server derives it at the official rate), so it is listed inside the
  // anchor's row, and counted once, rather than as a separate "deal".
  const listed = new Set(data.rows.map((r) => r.code));
  const folded = {};
  const tableRows = data.rows.filter((r) => {
    if (!r.pegged_to || !listed.has(r.pegged_to)) return true;
    (folded[r.pegged_to] = folded[r.pegged_to] || []).push(r.code);
    return false;
  });
  // A "favorable" row is one the money has really gained on: the nominal move
  // net of the inflation gap (realFxPct), the figure the list under the map
  // ranks by. By the nominal rate alone the lira read as a +9% win, tinted
  // green, while prices there rose faster than it fell (−4.5% real) — and it
  // was missing from the "after inflation" list directly below.
  const realGain = (r) => {
    const c = currencyCountry(r.code);
    const real = c ? realFxPct(c, r.strength_pct) : null;
    return r.favorable && r.watched && real != null && real > 0;
  };
  const fav = tableRows.filter(realGain);
  // "364-day avg" was the history cap leaking into the copy; the column header one
  // line over already calls the same number a 1-year average, so say that here too.
  // Hyphenate as a compound modifier: "1 year" -> "1-year avg", "6 months" -> "6-month".
  const avgSpan = dayLabel(data.baseline_days).replace(/^(\d+) (\w+?)s?$/, "$1-$2");
  $("summary").innerHTML = esc(`${tableRows.length} currencies · ${fav.length} stronger than usual after inflation`)
    + ` <span class="muted" data-tip="${esc(`≥ +${data.threshold_pct}% vs its ${avgSpan} average, net of the inflation gap `
      + "between the two countries (a nominal rise that local inflation eats isn't counted; a low-inflation "
      + "country with no current figure keeps its nominal move, a high-inflation one isn't counted). "
      + "These rows are tinted green.")}" title="">ⓘ</span>`;
  // The same rule, said where the green is: on the column whose number drives
  // it. The only explanation used to be the summary line a screen above the
  // table. Inside the sort button, but a click on the ⓘ shows its tip and does
  // not sort (the tip engine's capture handler stops it).
  const fi = $("favInfo");
  if (fi) fi.dataset.tip = `Green rows: ${w} is at least ${data.threshold_pct}% above its ${avgSpan} average there, `
    + "and still ahead after that country's inflation, so your money really goes further. "
    + "A big % that isn't green was eaten by local price rises (prices there climbed faster than "
    + "the currency fell), or the country has high inflation and no current figure to check it against.";

  // The price level is measured against the traveller's From country, like the
  // Cost of living tab (plAnchor): "cheap" to a German is cheaper than
  // Germany. Every level is stored vs the US, so divide by the anchor's own.
  const A = plAnchor(originIso());
  const rel = (pl) => pl / A.pl;
  const plHead = document.querySelector('#rates th[data-sk="price"]');
  if (plHead) plHead.title = `local prices vs ${A.name}; below 1.00 = cheaper than ${A.home ? "home" : "the US"}. `
    + "A currency several countries share shows the range across them.";

  // A reader who leaves out Level 3-4 (the default) gets the rows once the
  // advisories say which those are, 4s at most: drawn before them, Iran's
  // rial (1,742,060, a Level 4 row) widened the rate column from 71px to 90
  // (more than any header share can hold), and the redraw the advisories
  // bring set it back, moving the header — sticky, so on screen for a reader
  // already in the table — twice (CLS 0.056 at 768). The placeholder row
  // keeps the table's room meanwhile.
  if (!showRisky && !advisories && !_ratesRiskWait) {
    _ratesRiskWait = true;
    const go = () => { if (dataRates === data) renderRates(data); };
    Promise.race([ensureAdvisories(), new Promise((r) => setTimeout(r, 2000))]).then(go, go);
    return;
  }
  const adv = advisoryByIso();
  const tbody = $("rows");
  tbody.innerHTML = "";
  updateCurSortIndicators();
  for (const r of sortedRates(tableRows)) {
    const tr = document.createElement("tr");
    if (realGain(r)) tr.className = "favorable";
    // Green only where the row is: a nominal rise that local inflation ate
    // (TRY +9.3%), or one under the threshold, is plain ink — the favInfo ⓘ
    // says a big % that isn't green was eaten by price rises, and 68 rows
    // used to show a green % with no tint. Display only; the sort is nominal.
    const sign = realGain(r) ? "pos" : r.strength_pct < 0 ? "neg" : "";
    const star = r.watched ? "" : ' <span title="not on watchlist" style="opacity:.4">·</span>';
    const sp = currencySpread(r.code);
    // Advisory level of the currency's representative country, for the
    // hide-higher-risk filter (so the Iranian rial isn't row one).
    const ctry = currencyCountry(r.code);
    tr.dataset.adv = String((ctry && adv[ctry]) || 0);
    // Every region a currency is used in: the euro row shows under Europe, the
    // West African franc under Africa (regionRowOk).
    tr.dataset.regions = [...new Set(currencyCountries(r.code).map(regionOf).filter(Boolean))].join(" ");
    // Row links to the representative country's Travel Guide (shared currencies
    // point at a primary country, e.g. EUR→Germany; XCD has none, so no link).
    // Only where a guide exists: Tonga's row must not open a near-empty page.
    if (ctry && (CUR_BY_ISO[ctry] || (ISO2SLUG && ISO2SLUG[ctry]))) {
      tr.dataset.iso = ctry; tr.title = "See the " + countryName(ctry) + " travel guide →";
    }
    // The filter matches row text, which names currencies, not places:
    // "mexico" found nothing. Every country that uses the currency, or one
    // pegged into this row, rides along as searchable text.
    tr.dataset.q = [...currencyCountries(r.code), ...(folded[r.code] || []).flatMap(currencyCountries)]
      .map(countryName).join(" ").toLowerCase();
    // On a phone the full list stood the EUR and GBP rows up at 136px; there
    // it is a count, and the list lives in the tip (a tap shows it).
    const peg = folded[r.code]
      ? `<div class="pegnote" data-tip="${esc("Fixed to the " + r.code + " at official rates, so they move with it by exactly the same %: " + folded[r.code].join(", ") + ".")}" title="">`
        + `<span class="peglong">+ ${esc(folded[r.code].join(" · "))} (pegged)</span><span class="pegshort">+${folded[r.code].length} pegged</span></div>` : "";
    // The code and name are a link to the guide the row opens (keyboard path;
    // a modifier-click opens a tab). Block, so the phone name ellipsis holds.
    const ident = `<span class="code">${esc(r.code)}</span>${star}<div class="name">${esc(r.name)}</div>`;
    const identCell = tr.dataset.iso
      ? `<a class="destlink" href="${esc(guidePath(ctry))}" aria-label="${esc(r.code + ": " + countryName(ctry) + " travel guide")}">${ident}</a>`
      : ident;
    const plCell = !sp ? `<span class="muted" data-tip="${esc(currencyCountries(r.code).length
        ? "No World Bank price data for " + currencyCountries(r.code).map(countryName).join(", ") + "."
        : "Not matched to a country.")}" title="">—</span>`
      : sp.n === 1 ? rel(sp.lo.pl).toFixed(2) + " " + plTag(rel(sp.lo.pl))
      : `<span data-tip="${esc(countryName(sp.lo.iso) + " " + rel(sp.lo.pl).toFixed(2) + " to " + countryName(sp.hi.iso) + " "
          + rel(sp.hi.pl).toFixed(2) + " · " + sp.n + " places use the " + r.code + " (median " + rel(sp.mid).toFixed(2) + ")")}" title="">`
        + `${rel(sp.lo.pl).toFixed(2)}–${rel(sp.hi.pl).toFixed(2)}</span>`;
    const flag = currencyFlag(r.code, ctry);
    tr.innerHTML = `
      <td><div class="curcell"><span class="curflag">${flag}</span><div>${identCell}${peg}</div></div></td>
      <td class="num">${fmt(r.rate_now)}</td>
      <td class="num ${sign}">${signedPct(r.strength_pct, 1)}</td>
      <td class="num">${plCell}</td>
      <td class="num">${rangeMarker(r)}</td>`;
    tbody.appendChild(tr);
  }
  applyCurrencyFilter();
}

// Newest request wins: a first fetch for a base is uncached server-side and
// slow, so after a quick currency switch an earlier response could land last
// and repaint the table in the old currency under the new picker.
let _ratesSeq = 0, _ratesRiskWait = false;
async function loadRates() {
  // Quiet: a polite live region would otherwise read this out on every load.
  status("Fetching rates…", "", false, true);
  const base = homeBase, seq = ++_ratesSeq;
  try {
    // Top Picks scoring always needs the USD dataset, even when the data tab
    // is viewing the world through another home currency.
    if (base !== "USD" && !lastRates) lastRates = await getJSON("/api/rates");
    const data = await getJSON("/api/rates" + (base !== "USD" ? "?base=" + base : ""));
    if (base === "USD") lastRates = data;   // scoring needs it even if stale here
    if (seq !== _ratesSeq) return;
    // The currency moved without a newer request (setHomeCur skips its refetch
    // until the first rates land): fetch again for the current one.
    if (base !== homeBase) return loadRates();
    renderRates(data);
    status("");
  } catch (e) {
    if (seq === _ratesSeq) { status("Could not load rates: " + e.message, "err"); dropLoadingRow("rows"); }
  }
}

// A Data table's "Loading…" row holds two screens of room for the rows on
// their way (tr.loadingrow, styles.css). When they never come — a failed
// fetch — it lets go, so the page doesn't keep a blank two screens under a
// row that still says Loading…, exactly as it read before the reservation.
// The same view's map list goes too if it is still the invisible stand-in
// (index.html): with no data it would stay a blank two or three lines. So
// does the room a phone holds for the Safety view's government list
// (#govScroll, 336px), which renderGov never reaches without advisories.
const LOADING_MAP = { rows: "map", affRows: "affMap", advRows: "advMap", flightRows: "flightMap" };
function dropLoadingRow(tbodyId) {
  const tr = document.querySelector("#" + tbodyId + " > tr.loadingrow");
  if (tr) tr.classList.remove("loadingrow");
  const sk = document.querySelector('.mappicksrow.skel[data-for="' + LOADING_MAP[tbodyId] + '"]');
  if (sk) sk.remove();
  const gov = tbodyId === "advRows" && $("govScroll");
  if (gov && !gov.firstChild) gov.setAttribute("data-failed", "");
}

// "AED" and "ANG" mean nothing to most people, so the pickers spell the
// currency out the way the rates table below them already does. The name comes
// from the same rows the table renders, so the two can never disagree. It also
// makes the searchable select match on words — typing "turkish" finds TRY.
// The dollar is the rate feed's base, so it has no row of its own to take a
// name from — and read as a bare "USD" at the top of every list of named
// currencies. Named like the rest, and sorted with them.
const BASE_CUR_NAME = { USD: "US Dollar" };
function curLabel(code) {
  const row = lastRates && lastRates.rows.find((r) => r.code === code);
  const name = (row && row.name) || BASE_CUR_NAME[code];
  return name && name !== code ? code + " (" + name + ")" : code;
}
// Every currency the pickers offer, A-Z (the dollar in its place, not first).
function pickerCurrencies() {
  return [...new Set(["USD", ...lastRates.rows.map((r) => r.code)])].sort();
}

// Populate the "My currency" picker once real data exists.
function buildBaseSelect() {
  const sel = $("dataBase");
  if (!sel || sel.options.length > 1 || !lastRates) return;
  const codes = pickerCurrencies();
  sel.innerHTML = codes.map((c) =>
    `<option value="${esc(c)}"${c === homeBase ? " selected" : ""}>${esc(curLabel(c))}</option>`).join("");
  // Writes through the same setter as Top Picks' "In" picker, so the two can't
  // drift apart. manual=true: touching this select is an explicit choice and
  // should stop the currency following the From country.
  sel.onchange = () => setHomeCur(sel.value, true);
  enhanceSelect(sel);
}

function buildWatchlist(allCodes, selected) {
  const sel = new Set(selected || []);
  const box = $("watchlist");
  box.innerHTML = "";
  for (const c of allCodes) {
    const id = "w_" + c;
    const lbl = document.createElement("label");
    lbl.innerHTML = `<input type="checkbox" id="${id}" value="${c}" ${sel.has(c) ? "checked" : ""}> ${c}`;
    box.appendChild(lbl);
  }
}

function selectedWatch() {
  return Array.from(document.querySelectorAll("#watchlist input:checked")).map((i) => i.value);
}

async function loadConfig() {
  const cfg = await getJSON("/api/config");
  $("baseline_days").value = cfg.baseline_days;
  $("threshold_pct").value = cfg.threshold_pct;
  $("alert_cooldown_hours").value = cfg.alert_cooldown_hours;
  const e = cfg.email || {};
  $("email_enabled").checked = !!e.enabled;
  $("smtp_host").value = e.smtp_host || "";
  $("smtp_port").value = e.smtp_port || 587;
  $("username").value = e.username || "";
  $("password").value = ""; // never echo stored secret
  $("password").placeholder = e.password ? "•••••• (stored — leave blank to keep)" : "(set here or via FX_SMTP_PASSWORD)";
  $("from_addr").value = e.from_addr || "";
  $("to_addr").value = e.to_addr || "";

  // Watchlist needs the full currency universe; pull from current rates.
  const codes = (lastRates ? lastRates.rows.map((r) => r.code) : []).sort();
  buildWatchlist(codes, cfg.watch);
}

async function saveConfig() {
  const email = {
    enabled: $("email_enabled").checked,
    smtp_host: $("smtp_host").value.trim(),
    smtp_port: parseInt($("smtp_port").value, 10) || 587,
    username: $("username").value.trim(),
    from_addr: $("from_addr").value.trim(),
    to_addr: $("to_addr").value.trim(),
  };
  const pw = $("password").value;
  if (pw) email.password = pw; // only send if user typed a new one

  const body = {
    watch: selectedWatch(),
    baseline_days: parseInt($("baseline_days").value, 10),
    threshold_pct: parseFloat($("threshold_pct").value),
    alert_cooldown_hours: parseInt($("alert_cooldown_hours").value, 10),
    email,
  };
  status("Saving…");
  try {
    await postJSON("/api/config", body);
    status("Settings saved. Reloading rates…", "ok");
    await loadRates();
    status("Settings saved.", "ok");
  } catch (e) {
    status("Save failed: " + e.message, "err");
  }
}

async function checkNow() {
  status("Checking and emailing…");
  try {
    const res = await postJSON("/api/check", {});
    const n = res.favorable.length;
    if (!n) {
      status(`No favorable currencies right now (as of ${res.as_of}).`, "ok");
    } else if (res.email_sent) {
      status(`${n} favorable — alert emailed.`, "ok");
    } else if (!res.email_configured) {
      status(`${n} favorable, but email isn't configured (see Settings).`, "err");
    } else {
      status(`${n} favorable, but send failed: ${res.error}`, "err");
    }
  } catch (e) {
    status("Check failed: " + e.message, "err");
  }
}

// ---- index chart range toggle --------------------------------------------
const INDEX_RANGES = ["1m", "3m", "6m", "ytd", "1y", "2y", "5y", "10y", "all"];
let activeRange = "1y";
// ?win= carries a range; a link from before ranges existed carries days.
function rangeFromParam(v) {
  v = String(v || "").toLowerCase();
  if (INDEX_RANGES.includes(v)) return v;
  const d = parseInt(v, 10);
  return !d ? "1y" : d <= 30 ? "1m" : d <= 90 ? "3m" : d <= 180 ? "6m" : "1y";
}
// A home currency the ECB doesn't quote has a year of history (and the
// Icelandic króna starts in 2018), so the ranges it can't reach are off.
function markRange(active, data) {
  for (const b of document.querySelectorAll("#windowtoggle button")) {
    const r = b.dataset.range, on = r === active;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
    if (data && data.ranges) {
      b.disabled = !data.ranges.includes(r);
      b.title = !b.disabled ? ""
        : data.source === "market" ? "Only a year of history for " + data.base
        : data.base + " history starts " + fmtMonYear(data.base_date || "");
    }
  }
}

// A render while the chart was hidden (a home-currency change on another tab)
// drew at the 800 fallback. The ResizeObserver catches the chart reappearing;
// showing the Currency view checks too, for browsers that hold observers back.
function refitIndex() { refitChart($("chart")); }

let _indexSeq = 0;
async function loadIndex(range) {
  activeRange = INDEX_RANGES.includes(range) ? range : "1y";
  markRange(activeRange);
  const base = homeBase, seq = ++_indexSeq;
  try {
    const data = await getJSON("/api/index?range=" + activeRange +
      (base !== "USD" ? "&base=" + base : ""));
    // Same newest-wins rule as loadRates: a slow earlier range or currency
    // must not repaint the chart under the button now active.
    if (seq !== _indexSeq) return;
    if (base !== homeBase) return loadIndex(activeRange);
    // A range this currency's history can't reach comes back as 1Y.
    if (data.range && INDEX_RANGES.includes(data.range)) activeRange = data.range;
    markRange(activeRange, data);
    lastIndexData = data;
    renderIndex(lastIndexData);
    syncURL();
  } catch (e) {
    if (seq === _indexSeq) $("chartsub").textContent = "Could not load chart: " + e.message;
  }
}

for (const b of document.querySelectorAll("#windowtoggle button")) {
  b.addEventListener("click", () => loadIndex(b.dataset.range));
}

// ---- world heatmap ---------------------------------------------------------
// Country (ISO-3166 alpha-2) -> currency code. Provider covers ~180 currencies,
// so nearly every country gets real data. Unmapped/absent -> "no data" (gray).
// Bulgaria joined 2026-01-01; the provider's BGN quote has been frozen since.
const EUROZONE = ["AT","BE","CY","EE","FI","FR","DE","GR","IE","IT","LV","LT",
  "LU","MT","NL","PT","SK","SI","ES","HR","AD","MC","SM","VA","ME","XK","BG"];
// Countries that use the US dollar itself (shown as flat for a US traveler).
const USD_USING = ["US","EC","SV","PA","TL","ZW","MH","FM","PW","TC","VG","BQ","PR","GU"];
const CUR_BY_ISO = (() => {
  const m = {
    // Americas
    CA:"CAD", MX:"MXN", GT:"GTQ", BZ:"BZD", HN:"HNL", NI:"NIO", CR:"CRC",
    CU:"CUP", DO:"DOP", HT:"HTG", JM:"JMD", TT:"TTD", BS:"BSD", BB:"BBD",
    // Curaçao's Caribbean guilder (XCG) replaced the ANG 1:1 on the same USD
    // peg in 2025; the FX feed still quotes ANG, which prices identically.
    AW:"AWG", CW:"ANG",
    CO:"COP", VE:"VES", GY:"GYD", SR:"SRD", PE:"PEN", BR:"BRL", BO:"BOB",
    PY:"PYG", CL:"CLP", AR:"ARS", UY:"UYU",
    // Europe (non-euro)
    GB:"GBP", IM:"GBP", JE:"GBP", GG:"GBP", CH:"CHF", LI:"CHF", NO:"NOK",
    SJ:"NOK", SE:"SEK", DK:"DKK", GL:"DKK", FO:"DKK", IS:"ISK", CZ:"CZK",
    PL:"PLN", HU:"HUF", RO:"RON", RS:"RSD", BA:"BAM", MK:"MKD",
    AL:"ALL", MD:"MDL", UA:"UAH", BY:"BYN", RU:"RUB", TR:"TRY",
    // Middle East
    IL:"ILS", PS:"ILS", SA:"SAR", AE:"AED", QA:"QAR", KW:"KWD", BH:"BHD",
    OM:"OMR", JO:"JOD", LB:"LBP", SY:"SYP", IQ:"IQD", IR:"IRR", YE:"YER",
    // Asia
    CN:"CNY", JP:"JPY", KR:"KRW", IN:"INR", PK:"PKR", BD:"BDT", LK:"LKR",
    NP:"NPR", AF:"AFN", MM:"MMK", TH:"THB", VN:"VND", KH:"KHR", LA:"LAK",
    MY:"MYR", SG:"SGD", ID:"IDR", PH:"PHP", BN:"BND", HK:"HKD", MO:"MOP",
    TW:"TWD", MN:"MNT", KZ:"KZT", UZ:"UZS", TM:"TMT", KG:"KGS", TJ:"TJS",
    AZ:"AZN", AM:"AMD", GE:"GEL", BT:"BTN", KP:"KPW",
    // Oceania
    AU:"AUD", NZ:"NZD", FJ:"FJD", PG:"PGK", SB:"SBD", VU:"VUV",
    // Africa
    EG:"EGP", MA:"MAD", DZ:"DZD", TN:"TND", LY:"LYD", ZA:"ZAR", NG:"NGN",
    KE:"KES", GH:"GHS", ET:"ETB", TZ:"TZS", UG:"UGX", RW:"RWF", BI:"BIF",
    SD:"SDG", SO:"SOS", DJ:"DJF", AO:"AOA", MZ:"MZN", ZM:"ZMW", BW:"BWP",
    NA:"NAD", SZ:"SZL", LS:"LSL", MW:"MWK", MG:"MGA", MU:"MUR", GM:"GMD",
    GN:"GNF", LR:"LRD", CD:"CDF", CV:"CVE", KM:"KMF", MR:"MRU", SC:"SCR", ER:"ERN",
    // The provider only quotes the old leone (SLL = SLE × 1000); see PPP_UNIT.
    SL:"SLL",
    // CFA franc zones (real data via XOF / XAF)
    SN:"XOF", CI:"XOF", ML:"XOF", BF:"XOF", NE:"XOF", BJ:"XOF", TG:"XOF", GW:"XOF",
    CM:"XAF", TD:"XAF", CF:"XAF", CG:"XAF", GA:"XAF", GQ:"XAF",
  };
  for (const iso of EUROZONE) m[iso] = "EUR";
  for (const iso of USD_USING) m[iso] = "USD";
  return m;
})();
// A home currency seeded from Bulgaria before the switch would keep measuring
// everything against the dead lev series.
if (homeBase === "BGN") {
  homeBase = "EUR";
  try { localStorage.setItem("fx_homecur", "EUR"); } catch (e) {}
}
const USDLINK = "#bcd0e6"; // pale blue: uses the US dollar (flat for your dollar)

let worldGeo = null;

async function ensureWorld() {
  if (worldGeo) return worldGeo;
  // ?v= busts the day-long HTTP cache when the geometry changes (bump manually)
  worldGeo = await (await fetch("/world.geojson?v=8")).json();
  return worldGeo;
}

function hexToRgb(h) { return [1,3,5].map((i) => parseInt(h.slice(i, i + 2), 16)); }
function mix(a, b, t) {
  const A = hexToRgb(a), B = hexToRgb(b);
  return "rgb(" + A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",") + ")";
}
function strengthColor(pct) {
  // Diverging: red (USD weaker) -> light -> green (USD stronger). Clamp at ±8%.
  const t = Math.max(-1, Math.min(1, pct / 8));
  return t >= 0 ? mix("#eef0f1", "#0a7d28", t) : mix("#eef0f1", "#b00020", -t);
}

// Mid-slate, deliberately NOT a near-white grey. Every scale on this site ends
// at a pale neutral for its middle value — "price level about the same as home",
// "currency flat against its average" — so a near-white no-data read as data. On
// the cost-of-living map that put Australia, Canada and the US in the same tone
// as Sudan, Iran and Venezuela, and 53 territories that have no World Bank entry
// at all were silently rendering as if they did. A mid tone is the one choice
// that separates from both a near-black ocean and a near-white one, so it holds
// in either theme without branching. Shared by all four maps.
const NODATA = "#6b7681";
// Level 4 "Do Not Travel" on the value map. Deliberately softer than the #b00020
// used for grade pills and diverging scales: at pill size that red is a small
// accent, but as a map fill it becomes whole continents of alarm sitting beside
// pale greens, which reads as danger-first rather than "excluded from ranking".
// Same hue, mixed 55% toward the neutral, so it still says stop without shouting.
const DNT_FILL = mix("#eef0f1", "#b00020", 0.55);
const HOME = "#bcd0e6";

// Flat lon/lat projection, cropped at -56 — Antarctica is deliberately off
// the map. Shown, it stretched into a dominating band (and switching to an
// equal-area projection changed the map's whole familiar look), so it stays
// markable via search/bulk-add and counts toward the 7-continent badge,
// just unpainted.
function projectRing(ring, W, H, latTop, latBot) {
  let d = "";
  for (let i = 0; i < ring.length; i++) {
    const lon = ring[i][0], lat = ring[i][1];
    const x = ((lon + 180) / 360) * W;
    const y = ((latTop - lat) / (latTop - latBot)) * H;
    d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
  }
  return d + "Z";
}

// Generic choropleth: colorFn(feature) -> {fill, title}. Reused by every map tab.
function drawMap(hostId, colorFn, ariaLabel) {
  const host = $(hostId);
  if (!worldGeo) { host.textContent = "Map data unavailable."; return; }
  // The region filter (setRegion): places outside it are drawn as "outside"
  // whatever their own colour would be.
  if (REGION_MAPS.has(hostId) && regionSel !== "all") {
    const own = colorFn, rn = REGIONS[regionSel];
    colorFn = (f) => (inRegion(f.properties.iso) ? own(f)
      : { fill: NODATA, cls: "out", title: f.properties.name + " — outside " + rn });
  }
  const W = 1000, latTop = 83, latBot = -56;
  const H = Math.round((W * (latTop - latBot)) / 360);
  let paths = "";
  // UK home nations (sub:"GB") replace the single UK outline on the travel
  // map, where England/Scotland/Wales are markable in their own right;
  // everywhere else the plain UK feature draws and the subdivisions skip.
  const hasSubs = worldGeo.features.some((x) => x.properties.sub);
  for (const f of worldGeo.features) {
    const isSub = !!f.properties.sub;
    if (hostId === "visitedMap" ? (f.properties.iso === "GB" && !isSub && hasSubs) : isSub) continue;
    const { fill, title, cls } = colorFn(f);
    const g = f.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    let d = "";
    for (const poly of polys)
      for (const ring of poly)
        if (ring.length >= 3) d += projectRing(ring, W, H, latTop, latBot);
    if (d) paths += `<path d="${d}" fill="${fill}"${cls ? ` class="${cls}"` : ""} data-iso="${esc(f.properties.iso)}"><title>${esc(title)}</title></path>`;
  }
  // Antarctica medallion: the continent can't sit on this flat map without
  // stretching into a band, so the travel map gets a small polar-view inset
  // in the empty southern-ocean corner instead — clickable and painted
  // exactly like any other place.
  if (hostId === "visitedMap") {
    const aq = worldGeo.features.find((x) => x.properties.iso === "AQ");
    if (aq) {
      const cx = 60, cy = H - 60, R = 42;
      const { fill, title, cls } = colorFn(aq);
      let d = "";
      for (const poly of aq.geometry.coordinates)
        for (const ring of poly) {
          ring.forEach((pt, i) => {
            const lam = pt[0] * Math.PI / 180;
            const rad = ((90 + pt[1]) / 30) * (R - 7);   // south-polar azimuthal
            d += (i ? "L" : "M") + (cx + rad * Math.sin(lam)).toFixed(1) + " "
               + (cy + rad * Math.cos(lam)).toFixed(1);
          });
          d += "Z";
        }
      const disc = `M ${cx - R},${cy} a ${R},${R} 0 1,0 ${2 * R},0 a ${R},${R} 0 1,0 ${-2 * R},0 Z`;
      paths += `<g class="aqmedal">`
        + `<path d="${disc}" fill="rgba(148,163,184,.10)" stroke="rgba(148,163,184,.55)" stroke-width="1.4" data-iso="AQ"><title>${esc(title)}</title></path>`
        + `<path d="${d}" fill="${fill}"${cls ? ` class="${cls}"` : ""} data-iso="AQ"><title>${esc(title)}</title></path>`
        + `</g>`;
    }
    // Dots for MARKED places whose paint is invisible at world scale
    // (Singapore, Barbados, Monaco...). Drawn as <path> circles so the map's
    // click-to-toggle and hover titles work on them like any country.
    const cen = countryCentroids();
    const spans = placeSpans();
    const dotFor = (f) => {
      const { fill, title, cls } = colorFn(f);
      // No dot for a country we have nothing to say about. Two distinct fills
      // mean that: NODATA on the data maps, and the pale "not marked yet" fill
      // on the Wander List map (they are deliberately different colours — one
      // is missing data, the other is an invitation to click). Checking only the
      // literal used to be enough, back when NODATA happened to be that same
      // pale grey; it no longer is, and dropping the NODATA case here would
      // speckle the data maps with dots for microstates we have no figures for.
      if (fill === "#e0e4e8" || fill === NODATA) return "";
      const c = cen[f.properties.iso];
      if (!c) return "";
      const x = ((c[0] + 180) / 360) * W, y = ((latTop - c[1]) / (latTop - latBot)) * H;
      if (y < 0 || y > H) return "";
      const r = 4;
      return `<path d="M ${(x - r).toFixed(1)},${y.toFixed(1)} a ${r},${r} 0 1,0 ${2 * r},0 a ${r},${r} 0 1,0 ${-2 * r},0 Z"`
        + ` fill="${fill}"${cls ? ` class="${cls}"` : ""} data-iso="${esc(f.properties.iso)}"><title>${esc(title)}</title></path>`;
    };
    for (const f of worldGeo.features)
      if ((spans[f.properties.iso] ?? 0) < 1.5 && !f.properties.sub) paths += dotFor(f);
    if (!(placeSpans().BQ >= 0))                      // geometry-less places
      paths += dotFor({ properties: { iso: "BQ", name: "Caribbean Netherlands" } });
  }
  // Clipped to the map's own rectangle: full screen can show more than it
  // (a tall phone's view reaches below -56°, where Antarctica's outline
  // would draw as a grey band).
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${ariaLabel}">`
    + `<defs><clipPath id="mapclip-${hostId}"><rect width="${W}" height="${H}"/></clipPath></defs>`
    + `<g clip-path="url(#mapclip-${hostId})">${paths}</g></svg>`;

  // Tap-for-detail on every map (the visited map keeps its toggle behavior).
  // Property assignment (not addEventListener) stays idempotent across re-renders,
  // and works on touch where hover tooltips don't.
  if (hostId !== "visitedMap") {
    host.onclick = (e) => {
      // A pan gesture ends with a click event; attachMapZoom sets this flag so
      // dragging the map doesn't open whatever country you happened to release
      // over. Same discrimination the Wander List map already relied on.
      if (host._dragJustHappened) { host._dragJustHappened = false; return; }
      const p = e.target.closest("path");
      const iso = p && p.getAttribute("data-iso");
      if (iso && iso !== "-99") {
        showCountryCard(iso, host);
        if (host._onPick) host._onPick(iso);
      }
    };
  }
  // Every map gets zoom, not just the Wander List one. Tiny countries are
  // unhittable at world scale, and the Top Picks map is where people are
  // actually trying to click through to a guide.
  attachMapZoom(host, W, H);
  // A new region glides the camera there (or back out); a re-render for any
  // other reason keeps whatever zoom the reader has.
  if (REGION_MAPS.has(hostId) && host._zoomTo && host._regionShown !== regionSel) {
    const first = host._regionShown === undefined;
    host._regionShown = regionSel;
    if (!(first && regionSel === "all"))
      host._zoomTo(regionSel === "all" ? { x: 0, y: 0, w: W, h: H } : regionZoomBox(regionSel), !first);
  }
}

// "Ctrl/⌘ + scroll to zoom" over a map, shown briefly when a plain wheel
// scrolls past it — at most every few seconds, so scrolling isn't nagged.
let _mapHintAt = 0;
function mapWheelHint(host) {
  const now = Date.now();
  if (now - _mapHintAt < 4000) return;
  _mapHintAt = now;
  let h = host.querySelector(".maphint");
  if (!h) {
    h = document.createElement("div");
    h.className = "maphint";
    h.setAttribute("aria-hidden", "true");
    h.textContent = (/Mac|iP(hone|ad|od)/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl")
      + " + scroll to zoom";
    host.appendChild(h);
  }
  h.classList.add("show");
  clearTimeout(h._t);
  h._t = setTimeout(() => h.classList.remove("show"), 1400);
}

// ---- map zoom / pan (Wander List map) ---------------------------------------
// Tiny countries are impossible to tap at world scale: ctrl/⌘+wheel (or pinch)
// zooms toward the cursor, dragging pans once zoomed, and +/−/⌂ buttons cover
// touch and plain mice.
// Zoom state lives on the host element so it survives the re-render that every
// country toggle triggers. Event handlers are property-assigned (idempotent).
function attachMapZoom(host, W, H) {
  const svg = host.querySelector("svg");
  if (!svg) return;
  const st = host._zoom || (host._zoom = { x: 0, y: 0, w: W, h: H });
  host.style.position = "relative";

  let animTimer = null;
  const setVB = (v) => svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  // apply(true) tweens the viewBox like a camera easing in/out; apply(false)
  // snaps (used for direct manipulation — wheel/drag/pinch — and re-render
  // restores, where a lag would feel wrong). The tween is clock-driven off a
  // setTimeout loop so it always completes (rAF is paused in background tabs).
  // The view's shape (height/width). On the page it is the map's own; full
  // screen sets the screen's (host._aspect), so zooming in on a tall phone
  // fills the whole screen instead of a 140px strip. The fully-out view fits
  // the world either way, and a side that is wider than the world stays
  // centred rather than pannable.
  const asp = () => host._aspect || H / W;
  const apply = (animate) => {
    if (animTimer) { clearTimeout(animTimer); animTimer = null; }
    st.w = Math.max(W / 8, Math.min(Math.max(W, H / asp()), st.w));
    st.h = st.w * asp();
    st.x = st.w >= W ? (W - st.w) / 2 : Math.max(0, Math.min(W - st.w, st.x));
    st.y = st.h >= H ? (H - st.h) / 2 : Math.max(0, Math.min(H - st.h, st.y));
    const zoomed = st.w < W - 0.5 || st.h < H - 0.5;
    // when zoomed, own the touch gestures (pan/pinch); at world view, let the
    // page scroll normally (full screen has no page to scroll)
    host.style.touchAction = zoomed || host._aspect ? "none" : "";
    host.classList.toggle("zoomed", zoomed);
    if (!animate || reducedMotion()) { setVB(st); return; }
    const cur = (svg.getAttribute("viewBox") || `0 0 ${W} ${H}`).split(" ").map(Number);
    const from = { x: cur[0], y: cur[1], w: cur[2], h: cur[3] };
    const to = { x: st.x, y: st.y, w: st.w, h: st.h };
    const t0 = performance.now(), dur = 520;
    const ease = (t) => 1 - Math.pow(1 - t, 3);   // ease-out cubic
    const frame = () => {
      const k = Math.min(1, (performance.now() - t0) / dur), e = ease(k);
      setVB({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e,
              w: from.w + (to.w - from.w) * e, h: from.h + (to.h - from.h) * e });
      animTimer = k < 1 ? setTimeout(frame, 16) : null;
    };
    frame();
  };
  const zoomAt = (fx, fy, factor, animate) => {   // fx, fy = fractions of the view
    const px = st.x + fx * st.w, py = st.y + fy * st.h;
    st.w /= factor;
    st.h = st.w * asp();
    st.x = px - fx * st.w;
    st.y = py - fy * st.h;
    apply(animate);
  };
  // programmatic camera move to an absolute viewBox (used by the continent
  // filter) — animated by default
  host._zoomTo = (t, animate = true) => {
    st.x = t.x; st.y = t.y; st.w = t.w; st.h = t.h;
    apply(animate);
  };
  // A new view shape (full screen in or out, a rotated phone), keeping the
  // same centre and zoom; null = the map's own shape.
  host._setAspect = (a) => {
    const cx = st.x + st.w / 2, cy = st.y + st.h / 2;
    const out = st.w >= Math.max(W, H / asp()) - 0.5;   // was the whole world in view
    host._aspect = a || null;
    // The whole world stays in view (a wide phone screen used to open on a
    // cropped, already-"zoomed" map); otherwise keep the zoom and centre.
    if (out) st.w = Math.max(W, H / asp());
    st.h = st.w * asp();
    st.x = cx - st.w / 2;
    st.y = cy - st.h / 2;
    apply(false);
  };

  // controls (re-created each render — innerHTML wiped the previous ones)
  if (!host.querySelector(".mapzoom")) {
    const ctr = document.createElement("div");
    ctr.className = "mapzoom";
    ctr.innerHTML = '<button type="button" data-z="fs"></button>'
      // Named like the full-screen button: a screen reader read the glyphs
      // ("full-width plus sign", "house").
      + '<button type="button" data-z="in" title="zoom in" aria-label="Zoom in">＋</button>'
      + '<button type="button" data-z="out" title="zoom out" aria-label="Zoom out">－</button>'
      + '<button type="button" data-z="reset" title="reset view" aria-label="Reset view">⌂</button>';
    ctr.onclick = (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      e.stopPropagation();                  // don't toggle a country underneath
      if (b.dataset.z === "fs") { if (host.closest(".mapfs")) closeMapFullscreen(); else openMapFullscreen(host); }
      else if (b.dataset.z === "in") zoomAt(0.5, 0.5, 1.6, true);
      else if (b.dataset.z === "out") zoomAt(0.5, 0.5, 1 / 1.6, true);
      else { st.x = 0; st.y = 0; st.w = Math.max(W, H / asp()); apply(true); }
    };
    host.appendChild(ctr);
    syncFsButton(host);
  }

  // Plain wheel scrolls the PAGE: every map is full-width, the landing one
  // included, so zooming on it trapped anyone scrolling past. Ctrl/⌘+wheel
  // zooms — Chrome, Edge and Firefox also report a trackpad pinch that way —
  // and a plain wheel just flashes the hint once in a while.
  host.onwheel = (e) => {
    if (!(e.ctrlKey || e.metaKey)) {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) mapWheelHint(host);
      return;
    }
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    // instant — wheel is already continuous; tweening each notch would lag
    zoomAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height,
           e.deltaY < 0 ? 1.25 : 0.8, false);
  };
  // Safari reports a trackpad pinch as gesture events, not a ctrl wheel.
  // Desktop only: on touch screens the pointer pinch below owns two fingers.
  // Listeners are added once and call through host._gesture, which each
  // render refreshes (the handlers close over this render's svg).
  if (!navigator.maxTouchPoints) {
    let g0 = null;
    host._gesture = {
      start: (e) => { e.preventDefault(); g0 = { w: st.w }; },
      change: (e) => {
        if (!g0 || !e.scale) return;
        e.preventDefault();
        const r = svg.getBoundingClientRect();
        zoomAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height,
               st.w / (g0.w / e.scale), false);
      },
      end: (e) => { e.preventDefault(); g0 = null; },
    };
    if (!host._gestureWired) {
      host._gestureWired = true;
      ["start", "change", "end"].forEach((t) =>
        host.addEventListener("gesture" + t, (e) => host._gesture[t](e)));
    }
  }

  // drag to pan (once zoomed) + two-finger pinch; a real drag suppresses the
  // click so it doesn't also toggle the country under the finger
  const ptrs = new Map();
  let pan = null, pinch = null, dragged = false;
  host.onpointerdown = (e) => {
    // Each press starts afresh: a flag left by the last drag or pinch ate the
    // next tap — on a zoom button (every control press ends in pointerup here
    // too) or on a country.
    host._dragJustHappened = false;
    if (e.target.closest(".mapzoom")) { dragged = false; return; }
    ptrs.set(e.pointerId, e);
    if (ptrs.size === 1) {
      pan = { cx: e.clientX, cy: e.clientY, x: st.x, y: st.y };
      dragged = false;
    } else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()];
      pinch = { d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), w: st.w };
      pan = null;
    }
  };
  host.onpointermove = (e) => {
    // A mouse released outside the map never sent pointerup here: with no
    // button down now, that drag is over (it used to follow the bare mouse).
    if (e.pointerType === "mouse" && e.buttons === 0 && ptrs.size) {
      ptrs.clear(); pan = null; pinch = null;
      return;
    }
    if (!ptrs.has(e.pointerId)) return;
    ptrs.set(e.pointerId, e);
    const r = svg.getBoundingClientRect();
    if (ptrs.size === 2 && pinch) {
      const [a, b] = [...ptrs.values()];
      const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (d > 0 && pinch.d > 0) {
        const fx = ((a.clientX + b.clientX) / 2 - r.left) / r.width;
        const fy = ((a.clientY + b.clientY) / 2 - r.top) / r.height;
        const targetW = pinch.w / (d / pinch.d);
        zoomAt(fx, fy, st.w / targetW, false);   // track the fingers directly
        dragged = true;
      }
    } else if (pan && (st.w < W - 0.5 || st.h < H - 0.5)) {
      const dx = e.clientX - pan.cx, dy = e.clientY - pan.cy;
      if (Math.abs(dx) + Math.abs(dy) > 6) dragged = true;
      if (dragged) {
        st.x = pan.x - dx * st.w / r.width;
        st.y = pan.y - dy * st.h / r.height;
        apply(false);
      }
    }
  };
  host.onpointerup = host.onpointercancel = (e) => {
    ptrs.delete(e.pointerId);
    if (ptrs.size < 2) pinch = null;
    if (ptrs.size === 0) {
      pan = null;
      if (dragged) host._dragJustHappened = true;
    }
  };
  if (!host._zoomClickGuard) {
    host._zoomClickGuard = true;
    host.addEventListener("click", (e) => {
      if (host._dragJustHappened) {
        host._dragJustHappened = false;
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
  }

  apply(false);                             // restore the pre-render zoom (snap)
}

// ---- full-screen map -------------------------------------------------------
// Every map opens full screen from the top button of its zoom stack: at card
// size the world is too small to steer (the owner's words). The map element
// itself moves into an overlay, with its ranked list and any open country
// card, so its handlers, zoom and by-id re-renders keep working; a comment
// marks where it goes back. The browser's own full screen is asked for too
// where the page may have it (not on iPhone: there the overlay fills the
// window). Esc, the ✕, the same button, or leaving the tab closes it.
const FS_ICON = {
  on: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  off: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};
let mapFs = null;   // { host, marker, overlay, prevFocus, real }
function syncFsButton(host) {
  const b = host.querySelector('.mapzoom [data-z="fs"]');
  if (!b) return;
  const on = !!host.closest(".mapfs");
  b.innerHTML = on ? FS_ICON.off : FS_ICON.on;
  b.title = on ? "exit full screen (Esc)" : "full screen";
  b.setAttribute("aria-label", b.title);
}
// The title and legend drawn above a map: the nearest earlier sibling (walking
// up the tree) that holds an h2.
function mapFsHeader(host) {
  for (let el = host; el && el !== document.body; el = el.parentElement) {
    for (let s = el.previousElementSibling; s; s = s.previousElementSibling) {
      const h = s.matches("h2, [data-h='2']") ? s : s.querySelector("h2, [data-h='2']");
      if (h) return { h2: h, legend: s.querySelector(".legend") };
    }
  }
  return { h2: null, legend: null };
}
function mapFsKey(e) {
  if (e.key === "Escape" && mapFs) { e.preventDefault(); closeMapFullscreen(); }
}
// Keep keyboard focus inside the overlay while it is open.
function mapFsFocus(e) {
  if (mapFs && !mapFs.overlay.contains(e.target)) mapFs.overlay.querySelector(".mapfs-close").focus();
}
function openMapFullscreen(host) {
  if (mapFs) return;
  const { h2, legend } = mapFsHeader(host);
  const overlay = document.createElement("div");
  overlay.className = "mapfs";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", (h2 ? h2.textContent.trim() : "Map") + " — full screen");
  overlay.innerHTML = '<div class="mapfs-head"><h2></h2><div class="legend"></div>'
    + '<button type="button" class="mapfs-close" title="exit full screen (Esc)" aria-label="exit full screen">✕</button></div>'
    + '<p class="mapfs-hint">Turn your phone sideways for a bigger map.</p>'
    + '<div class="mapfs-body"><div class="mapfs-stage"></div></div>';
  // Copies of the page's own markup (already escaped where it was built).
  if (h2) overlay.querySelector("h2").innerHTML = h2.innerHTML;
  if (legend) overlay.querySelector(".legend").innerHTML = legend.innerHTML;
  const body = overlay.querySelector(".mapfs-body"), stage = overlay.querySelector(".mapfs-stage");
  const parent = host.parentElement;
  // The ranked list may live in another card (Top Picks keeps it beside the
  // map, in the Tune card), so it is found by its data-for, anywhere.
  const rows = [...document.querySelectorAll('.mappicksrow[data-for="' + host.id + '"]')];
  const card = [...parent.children].find((c) => c.classList.contains("countrycard"));
  // Placeholders as tall as what leaves, so the page behind keeps its length
  // (a map near the end of a page shrank it, and the scroll position with it):
  // one for the map and its card, one per list row where it stood.
  const ph = (els) => {
    const top = Math.min(...els.map((el) => el.getBoundingClientRect().top));
    const bottom = Math.max(...els.map((el) => el.getBoundingClientRect().bottom));
    const m = document.createElement("div");
    m.className = "mapfs-ph";
    m.style.height = Math.max(0, bottom - top) + "px";
    return m;
  };
  const marker = ph([host, ...(card ? [card] : [])]);
  const rowMarks = rows.map((r) => { const m = ph([r]); r.before(m); return m; });
  host.before(marker);
  // The map and its card share a stage (the card floats over the map, not the
  // list); the ranked list sits below it.
  stage.append(host, ...(card ? [card] : []));
  body.append(...rows);
  // The Wander List's Been / Want to go switch decides what a tap marks: it
  // comes along, and goes back after.
  let mode = null;
  if (host.id === "visitedMap" && $("visitedMode")) {
    const r = $("visitedMode").getBoundingClientRect();
    mode = { el: $("visitedMode"), mark: document.createElement("span") };
    mode.mark.style.cssText = `display:inline-block;width:${r.width}px;height:${r.height}px`;
    mode.el.before(mode.mark);
    overlay.querySelector(".mapfs-head h2").after(mode.el);
  }
  // Everything else on the page is inert while this is open: Tab can't wander
  // behind the overlay (it used to scroll the page there).
  const inerted = [...document.body.children].filter((el) => !el.inert);
  inerted.forEach((el) => { el.inert = true; });
  document.body.appendChild(overlay);
  document.documentElement.classList.add("mapfs-open");
  mapFs = { host, marker, rowMarks, overlay, mode, inerted, prevFocus: document.activeElement, real: false,
            scroll: [window.scrollX, window.scrollY] };
  overlay.querySelector(".mapfs-close").onclick = closeMapFullscreen;
  document.addEventListener("keydown", mapFsKey);
  document.addEventListener("focusin", mapFsFocus);
  window.addEventListener("resize", mapFsFit);
  mapFsFit();
  syncFsButton(host);
  overlay.querySelector(".mapfs-close").focus();
  const de = document.documentElement;
  if (de.requestFullscreen && !document.fullscreenElement) {
    de.requestFullscreen({ navigationUI: "hide" })
      .then(() => { if (mapFs) mapFs.real = true; })
      .catch(() => {});                     // refused: the overlay alone is fine
  }
}
function closeMapFullscreen() {
  if (!mapFs) return;
  const { host, marker, rowMarks, overlay, mode, inerted, prevFocus, real, scroll } = mapFs;
  mapFs = null;
  document.removeEventListener("keydown", mapFsKey);
  document.removeEventListener("focusin", mapFsFocus);
  window.removeEventListener("resize", mapFsFit);
  inerted.forEach((el) => { el.inert = false; });
  const rows = [...overlay.querySelectorAll('.mappicksrow[data-for="' + host.id + '"]')];
  const card = overlay.querySelector(".countrycard");
  // The page's own order: the card right under the map (renderCountryCard
  // puts it there); each list row back where its placeholder stands.
  marker.replaceWith(host, ...(card ? [card] : []));
  rows.forEach((r, i) => { const m = rowMarks[i]; if (m && m.isConnected) m.replaceWith(r); else host.after(r); });
  if (mode) mode.mark.replaceWith(mode.el);
  overlay.remove();
  document.documentElement.classList.remove("mapfs-open");
  if (real && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  if (host._setAspect) host._setAspect(null);
  syncFsButton(host);
  // Back to the button that opened it (a mouse click in Safari never
  // focused it, so the page's last focus is no guide).
  const fb = host.querySelector('.mapzoom [data-z="fs"]');
  const to = prevFocus && prevFocus.isConnected && prevFocus !== document.body ? prevFocus : fb;
  if (to) to.focus({ preventScroll: true });
  window.scrollTo(scroll[0], scroll[1]);
}
// The view takes the shape of the space the map has on screen.
function mapFsFit() {
  if (!mapFs || !mapFs.host._setAspect) return;
  const r = mapFs.host.getBoundingClientRect();
  if (r.width > 0 && r.height > 0) mapFs.host._setAspect(r.height / r.width);
}
// Esc inside the browser's full screen only leaves full screen (the page
// never sees the key), so leaving it closes the overlay too.
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement && mapFs && mapFs.real) closeMapFullscreen();
});

// ---- tap-for-detail country card -------------------------------------------
let ccCurrent = null;   // { iso, host } of the open card

function showCountryCard(iso, host) {
  ccCurrent = { iso, host };
  renderCountryCard();
  // Pull in whatever context isn't loaded yet, then refresh the open card.
  Promise.all([ensureClimate().catch(() => {}), ensureAdvisories().catch(() => {}),
               ensureActivities().catch(() => {})])
    .then(() => { if (ccCurrent && ccCurrent.iso === iso) renderCountryCard(); });
}

function renderCountryCard() {
  if (!ccCurrent) return;
  const { iso, host } = ccCurrent;
  let card = host.nextElementSibling;
  if (!card || !card.classList.contains("countrycard")) {
    document.querySelectorAll(".countrycard").forEach((c) => c.remove());
    card = document.createElement("div");
    card.className = "countrycard";
    host.insertAdjacentElement("afterend", card);
  }
  const name = countryName(iso);
  const cur = CUR_BY_ISO[iso];
  // Same frame as the maps that open this card: FX in the home currency, price
  // level vs the From country (it used to read USD / US to every visitor).
  const fx = fxInfo(iso);
  const pl = priceLevel(iso);
  const anchor = plAnchor(guidePassport());
  const advLvl = advisoryByIso()[iso];
  const cl = climate && climate[iso];
  const act = activities && activities[iso];

  const facts = [];
  // One number, not two — the after-inflation one when a destination figure
  // was netted out (the one the table's mark uses), otherwise the exchange-
  // rate move, said plainly for what it is instead of "(nominal)". One
  // decimal, like the table: the raw figure printed "+10.34%" beside "+7.9%".
  const sgn = (p) => (p >= 0 ? "+" : "−") + Math.abs(p).toFixed(1) + "%";
  if (cur) facts.push(`💱 ${esc(cur)}` + (cur === homeBase ? " (your home currency)"
    : fx ? `: your ${esc(homeBase)} ${sgn(fx.adj ? fx.real : fx.nom)} vs 1-yr avg`
      + (fx.adj ? " after inflation" : " (exchange rate only — local inflation not netted out)")
    : ""));
  if (pl != null) facts.push(`💰 ${plPhrase(pl / anchor.pl, esc(anchor.name))}`);
  // 🛡️ for Levels 1–2, ⚠️ only where the advice is to reconsider: a warning
  // sign on "normal precautions" was alarmist. Whose advice it is, as the
  // table's pill already says.
  if (advLvl) facts.push(`${advLvl >= 3 ? "⚠️" : "🛡️"} ${esc(advLevelText(iso, advLvl) + advVia(iso))}`);
  if (cl && cl.best && cl.best.length) facts.push(`📅 best months: ${cl.best.map((m) => MON_ABBR[m - 1]).join(", ")}`);
  if (act && act.days) facts.push(`🧳 worth ${act.days[0]}–${act.days[1]} days`);

  const vis = isVisited(iso);
  card.innerHTML = `
    <button class="ccclose" title="close" aria-label="close">✕</button>
    <h3>${esc(name)} ${vis ? '<span class="visited-tag">✓ visited</span>' : ""}</h3>
    <div class="ccfacts">${facts.map((f) => `<span>${f}</span>`).join("") || "<span>Loading details…</span>"}</div>
    ${act ? `<p class="ccsummary">${esc(act.summary)}</p>` : ""}
    <div class="ccbtns">
      ${(act || cl) ? '<button data-cc="todo">Country guide →</button>' : ""}
      <button data-cc="visit">${vis ? "✓ Been (remove)" : "✓ Been"}</button>
      <button data-cc="wish">${loadWishlist().has(iso) ? "★ On wishlist (remove)" : "★ Want to go"}</button>
      <button data-cc="trip">${tripHas(iso) ? "🧳 On this trip (remove)" : "🧳 Add to trip"}</button>
    </div>`;
  card.querySelector(".ccclose").onclick = () => { card.remove(); ccCurrent = null; };
  const todo = card.querySelector('[data-cc="todo"]');
  if (todo) todo.onclick = () => openGuideFor(iso, true);
  const mark = (mode) => {
    const prev = visitMode; visitMode = mode; toggleMark(iso); visitMode = prev;
    renderCountryCard();
    if (loaded.value && !$("tab-value").hidden) renderValue();
    if (loaded.visited) renderVisited();
  };
  card.querySelector('[data-cc="visit"]').onclick = () => mark("visited");
  card.querySelector('[data-cc="wish"]').onclick = () => mark("wishlist");
  card.querySelector('[data-cc="trip"]').onclick = () => {
    tripToggle(iso);
    renderCountryCard();
    if (loaded.value && !$("tab-value").hidden) renderValue();
  };
}

function renderMap(rows, base) {
  base = base || "USD";
  const byCode = {};
  for (const r of rows) byCode[r.code] = r;
  // One decimal, like the table: the raw figure printed "+53.76%" beside "+53.8%".
  const sgn = (p) => (p >= 0 ? "+" : "−") + Math.abs(p).toFixed(1) + "%";

  let tracked = 0;
  drawMap("map", (f) => {
    const iso = f.properties.iso, cur = CUR_BY_ISO[iso] || TABLE_CUR[iso];
    const row = cur && cur !== base ? byCode[cur] : null;
    if (cur === base) {
      return { fill: USDLINK,
        title: `${f.properties.name} — uses ${base} (your home currency — flat by definition)` };
    }
    if (row) {
      tracked++;
      // The fill is the nominal rate and the hover says so, with the move
      // after inflation beside it where the country has a figure: the list
      // under the map ranks by that, and a lira "+9%" is a loss by it.
      const real = realFxPct(iso, row.strength_pct);
      return { fill: strengthColor(row.strength_pct),
        title: `${f.properties.name} — ${cur}: ${sgn(row.strength_pct)} vs 1-yr avg`
          + (real != null ? ` (before inflation; ${sgn(real)} after)` : "") };
    }
    return { fill: NODATA, title: f.properties.name + " — not tracked" };
  }, base + " strength world heatmap");
  // Ranked AFTER inflation — the figure each country card shows. By the
  // nominal rate alone the lira, the rial and the Syrian and Argentine pounds
  // read as "wins" while prices there rose faster than the currency fell
  // (Turkey: +9% nominal, -4% real). No inflation figure, no claimed gain.
  // Named by country (a currency union by its own name): "BOB" meant little.
  const gains = rows.filter((r) => !(r.pegged_to && byCode[r.pegged_to])
      && currencyCountries(r.code).some(inRegion))
    .map((r) => {
      const iso = currencyCountry(r.code);
      return { r, iso, real: iso ? realFxPct(iso, r.strength_pct) : null };
    })
    .filter((g) => g.real != null && g.real > 0 && fxInflBasis(g.iso).adj)
    .sort((a, b) => b.real - a.real).slice(0, 8);
  // "Your dollar's", "Your euro's", "Your money's" — never a bare code.
  renderDimPicks("map", baseWord(base).replace(/^(the|your) /, "Your ") + "'s biggest gains, after inflation",
    gains.map((g) => (g.r.code in PRIMARY_COUNTRY ? g.r.name : countryName(g.iso)) + " " + sgn(g.real)),
    gains.flatMap((g) => currencyCountries(g.r.code)));

  // One line: what green means and how many countries; the nominal caveat
  // (and that there is anything to hover) goes in the ⓘ.
  $("mapsub").innerHTML = esc(`Greener = ${baseWord(base)} above its 1-year average there · ${tracked} countries`)
    + ` <span class="muted" data-tip="Nominal exchange rate vs each currency's own 1-year average — in high-inflation countries local prices can rise faster than the currency falls, so a stronger rate isn't always more buying power. Hover a country for both figures. Top Picks and the guides net out inflation." title="">ⓘ</span>`;
  renderLegend(base);
}

function renderLegend(base) {
  $("legend").classList.remove("skel"); $("legend").removeAttribute("aria-hidden");   // index.html's stand-in
  $("legend").innerHTML =
    '<span>Weaker</span><span class="scale"></span><span>Stronger</span>' +
    `<span style="margin-left:8px"><span class="swatch" style="background:#bcd0e6"></span>${esc(base || "USD")}-linked</span>` +
    '<span style="margin-left:6px"><span class="swatch"></span>No data</span>';
}

function renderMapSafe() {
  const d = dataRates || lastRates;
  if (worldGeo && d) renderMap(d.rows, d.base || "USD");
}

// ---- PPP / affordability ---------------------------------------------------
let ppp = null;
async function ensurePPP() {
  // Stamped because ppp.json is browser-cached for a full day (server.py) while
  // app.js ships on a 5-minute cache. When the data gains a field the code depends
  // on — as it just did for the income cross-check — that skew leaves returning
  // visitors running new code against day-old data, with the guard silently inert.
  // The stamp makes the two bust together without giving up the day of caching.
  // An error body ({"error": "not found"} mid-deploy) is not the data: kept,
  // it read as "no figures for any country" all session and never retried.
  if (!ppp) {
    const r = await fetch(stamped("/ppp.json"));
    if (!r.ok) throw new Error("ppp.json " + r.status);
    ppp = await r.json();
  }
  return ppp;
}
// The base year most countries' PPP factor is from (2025 for 185 of 202), for
// crediting the source.
function pppYear() {
  const n = {};
  for (const k in ppp) { const y = ppp[k] && ppp[k].year; if (y) n[y] = (n[y] || 0) + 1; }
  return Object.keys(n).sort((a, b) => n[b] - n[a])[0] || "";
}
function rateForCurrency(code) {
  if (code === "USD") return 1;
  const r = lastRates && lastRates.rows.find((x) => x.code === code);
  return r ? r.rate_now : null;
}
// price level vs US for a country: PPP factor / market rate. <1 = cheaper than US.
// Countries whose World Bank PPP factor is quoted in a DIFFERENT unit from the
// currency travellers use: [unit it is quoted in, units of that code per unit].
// West Bank & Gaza and Liberia report GDP — and so PPP — in US dollars (the WB's
// NY.GDP.MKTP.CN equals .CD for both), so dividing by ILS/LRD put Palestine at a
// third of its real price level and pushed Liberia under the floor. Sierra
// Leone's factor is in new leones; the rates feed only carries the old leone.
// (Bulgaria's euro-restated factor needed this until BG moved into EUROZONE.)
// Only the price level reads this — FX views keep the circulating currency.
// Expect it to recur whenever a country redenominates or dollarises.
const PPP_UNIT = { PS: ["USD", 1], LR: ["USD", 1], SL: ["SLL", 1000] };
// England, Scotland and Wales have guides of their own but share the UK's
// economy and border: the guide borrows the UK's currency, price level and visa
// rules, labelled UK-wide. Guide-only — kept out of CUR_BY_ISO so they never
// enter scoring, the maps or allPlaces().
const GUIDE_PARENT = { "GB-ENG": "GB", "GB-SCT": "GB", "GB-WLS": "GB" };
const parentWide = (p) => (p === "GB" ? "UK" : countryName(p)) + "-wide";

// ---- inflation (World Bank CPI: ppp.json infl / infl_year) -------------------
// A PPP factor is one year's prices and the FX baseline is last year's rate, so
// both drift with inflation. A steadily depreciating currency always sits
// "above its 1-yr average" — Turkey read +9%, "goes further than usual", while
// local prices rose ~35% and buying power actually fell. Both are carried
// forward by the inflation gap. Same formulas as pricelevel.py / picks.py;
// entries without the fields behave exactly as before (no adjustment).
function nowYearFrac() {
  const d = new Date(), y = d.getUTCFullYear();
  const doy = Math.round((Date.UTC(y, d.getUTCMonth(), d.getUTCDate()) - Date.UTC(y, 0, 1)) / 864e5) + 1;
  return y + (doy - 1) / 365.25;
}
function inflRate(iso) {
  const e = ppp && ppp[iso];
  if (!e || typeof e.infl !== "number") return null;
  // A stale high-inflation reading (Argentina's 2024 = 220%) would overcorrect.
  if (e.infl_year < e.year && e.infl >= 10) return null;
  return Math.max(-0.05, Math.min(3, e.infl / 100));
}
function inflUS() { return inflRate("US") ?? 0.03; }
// High inflation with no current figure: no direction can be claimed.
function highInflUnknown(iso) {
  return inflRate(iso) == null && !!(ppp && ppp[iso] && ppp[iso].infl >= 10);
}
// Carry the PPP year's prices (measured mid-year) forward to today, ≤3 years.
function pplCarry(iso) {
  const e = ppp && ppp[iso], rL = inflRate(iso);
  if (!e || rL == null || !e.year) return 1;
  const t = Math.max(0, Math.min(3, nowYearFrac() - (e.year + 0.5)));
  return Math.pow((1 + rL) / (1 + inflUS()), t);
}
// Home side of the FX comparison: the From country when it uses the home
// currency, else that currency's own country (a pinned USD -> US, EUR -> DE).
function fxHomeIso() {
  const o = guidePassport();
  return CUR_BY_ISO[o] === homeBase ? o : (currencyCountry(homeBase) || o);
}
// The two inflation rates a real FX move rests on, and how honest each is.
// stale: an iso (either end) with high inflation and no current figure — no
// direction can be claimed, so the caller shows nominal and scores neutral.
// stand: the home has no figure, so the US rate stands in (and the copy says
// so — an Argentine home once read "Argentina ~3%/yr"). adj: the destination's
// own rate was used; without it real == nominal and "after inflation" is empty.
function fxInflBasis(iso, homeIso) {
  const hIso = homeIso || fxHomeIso();
  if (highInflUnknown(hIso)) return { hIso, stale: hIso };
  if (highInflUnknown(iso)) return { hIso, stale: iso };
  const rH = inflRate(hIso), rL = inflRate(iso);
  const rB = rH ?? inflUS();
  return { hIso, rB, rL: rL ?? rB, adj: rL != null, stand: rH == null && hIso !== "US" };
}
// Nominal strength_pct (now vs the 1-yr average) -> real: minus half a year of
// the inflation gap (0.5 = mean age of the samples in a 364-day average).
// Null = high inflation at either end with no current figure.
function realFxPct(iso, nomPct, homeIso) {
  if (typeof nomPct !== "number") return null;
  const b = fxInflBasis(iso, homeIso);
  if (b.stale) return null;
  return Math.round(((1 + nomPct / 100) * Math.pow((1 + b.rB) / (1 + b.rL), 0.5) - 1) * 10000) / 100;
}
// FX facts for a destination in the home-currency dataset, or null when there
// is no FX story (same currency, or not loaded yet).
function homeRatesNow() {
  return homeRates || (dataRates && (dataRates.base || "USD") === homeBase ? dataRates : null)
    || (homeBase === "USD" ? lastRates : null);
}
function fxInfo(iso) {
  const code = CUR_BY_ISO[iso];
  const hr = homeRatesNow(), rows = hr && hr.rows;
  if (!code || !rows || code === homeBase) return null;
  const row = rows.find((r) => r.code === code);
  if (!row || typeof row.strength_pct !== "number") return null;
  const homeIso = fxHomeIso();
  const real = realFxPct(iso, row.strength_pct, homeIso);
  return { code, nom: row.strength_pct, real, homeIso,
           adj: real != null && !!fxInflBasis(iso, homeIso).adj };
}
// "Türkiye ~35%/yr vs the US ~3%/yr" for the ⓘ copy ("" when the destination
// has no figure, i.e. nothing was adjusted). A home without a figure is shown
// as what was really used: the US rate, named as a stand-in.
function inflGapText(iso, homeIso) {
  const b = fxInflBasis(iso, homeIso);
  if (b.stale || !b.adj) return "";
  const nm = (i) => (i === "US" ? "the US" : countryName(i));
  const pc = (r) => "~" + trueMinus(Math.round(r * 100)) + "%/yr";
  return nm(iso) + " " + pc(b.rL) + " vs "
    + (b.stand ? "the US " + pc(b.rB) + ", used as a stand-in for " + countryName(b.hIso)
               : nm(b.hIso) + " " + pc(b.rB));
}

// Price level = a PPP factor measured in year Y, divided by TODAY's exchange
// rate. When a currency has collapsed since year Y, that arithmetic reports a
// country as far cheaper than it now is — local prices simply haven't caught up
// with the rate yet, and the World Bank won't restate until the next release.
// This was previously disclosed only as a footnote on one map, which meant the
// caveat never travelled with the number into the rankings, the guide pages or
// the budget filter.
// Threshold from the live distribution rather than taste: median one-year drift
// is 1.0% and the 90th percentile 4.4%, so 15% flags only genuine outliers.
// strength_pct is the dollar's move against that currency, so a positive number
// is exactly the case we care about. The price level is now carried forward by
// inflation where we know it, so only a fall FASTER than inflation — or one we
// can't adjust — still earns the caveat.
const PPP_DRIFT_WARN = 15;
function pppDrift(iso) {
  const code = CUR_BY_ISO[iso];
  if (!code || code === "USD" || !lastRates || !lastRates.rows) return null;
  const row = lastRates.rows.find((r) => r.code === code);
  const nom = row && row.strength_pct;
  if (typeof nom !== "number") return null;
  const real = realFxPct(iso, nom, "US");
  const pct = real == null ? nom : real;
  if (pct < PPP_DRIFT_WARN) return null;
  const year = ppp && ppp[iso] && ppp[iso].year;
  // "even after inflation" only when a local figure was netted out; without
  // one, real is just the nominal move under another name.
  return { pct, year, code, real: real != null && !!fxInflBasis(iso, "US").adj };
}
function pppDriftNote(iso) {
  const d = pppDrift(iso);
  if (d) {
    // d.pct is how much MORE a dollar buys (+43%); the currency's own fall is
    // 1 − 1/1.43 ≈ 30%, and it is measured against a 1-year average, not
    // over "the past year". The dollar is named: the price level is computed
    // from the USD rate whatever the reader's money, and "the dollar" is
    // ambiguous to a Canadian or an Australian.
    const fall = Math.round(100 * (1 - 1 / (1 + d.pct / 100)));
    return `⚠️ The ${d.code} is ~${fall}% weaker against the US Dollar than its 1-year average`
       + (d.real ? ", even after inflation" : "")
       + (d.year ? `, but the price level uses World Bank data from ${d.year}` : "")
       + ". Local prices may not have caught up yet, so this reads cheaper than it currently feels.";
  }
  // No current inflation figure: the price level couldn't be carried forward.
  if (highInflUnknown(iso)) {
    const e = ppp[iso];
    return `⚠️ ${countryName(iso)}'s latest inflation figure (${trueMinus(Math.round(e.infl))}% in ${e.infl_year}) `
      + `is older than its ${e.year} price data, so we can't bring prices up to date — `
      + "this likely reads cheaper than it currently feels.";
  }
  return "";
}
function priceLevelRaw(iso) {
  if (!ppp || !ppp[iso]) return null;
  const u = PPP_UNIT[iso];
  const cur = u ? u[0] : CUR_BY_ISO[iso];
  if (!cur) return null;
  const rate = rateForCurrency(cur);
  if (!rate) return null;
  const pl = ppp[iso].ppp * (u ? u[1] : 1) * pplCarry(iso) / rate;
  // Guard against broken World Bank values / unit mismatches (e.g. stale PPP for
  // a redenominated currency). Real price levels sit roughly in [0.1, 4].
  if (pl < 0.08 || pl > 6) return null;
  return pl;
}
// Those absolute bounds only catch the wild cases. The subtler failure is a
// country whose price level is merely *implausible*: Sudan came out at 1.95 —
// the most expensive country on the site, ahead of Iceland and Switzerland —
// because its official rate is pegged near 602 SDG/USD while the currency really
// trades far weaker. Dividing a PPP factor by a fictional rate gives a fictional
// price level, and 1.95 sits comfortably inside [0.08, 6].
//
// Price level tracks income log-linearly (the Penn effect: richer countries are
// genuinely pricier), so income is the cross-check. A country far off that line
// is nearly always a broken exchange rate — a managed peg, or a collapsed
// currency — rather than a real outlier. Those are treated as no-data, which
// every caller already handles, instead of being shown as a confident grade.
// This is deliberately complementary to pppDrift(), which watches currency
// strength and so cannot see a peg that never moves.
const PL_PLAUSIBLE_SD = 3;
let _plFitFor, _plFitVal;
function _computePlFit() {
  if (!ppp) return null;
  const pts = [];
  for (const iso in ppp) {
    const g = ppp[iso].gdppc, pl = priceLevelRaw(iso);
    if (g > 0 && pl) pts.push([Math.log(g), Math.log(pl)]);
  }
  const fit = (rows) => {
    const n = rows.length;
    if (n < 40) return null;              // too few to trust a band; skip the check
    const mx = rows.reduce((s, p) => s + p[0], 0) / n;
    const my = rows.reduce((s, p) => s + p[1], 0) / n;
    let sxy = 0, sxx = 0;
    for (const p of rows) { sxy += (p[0] - mx) * (p[1] - my); sxx += (p[0] - mx) * (p[0] - mx); }
    if (!sxx) return null;
    const b = sxy / sxx, a = my - b * mx;
    const sd = Math.sqrt(rows.reduce((s, p) => s + Math.pow(p[1] - (a + b * p[0]), 2), 0) / n);
    return sd > 0 ? { a, b, sd } : null;
  };
  const first = fit(pts);
  if (!first) return null;
  // Refit once without the extremes, so a single broken country can't widen the
  // band enough to hide itself inside it.
  const trimmed = pts.filter((p) => Math.abs(p[1] - (first.a + first.b * p[0])) <= 3 * first.sd);
  return fit(trimmed) || first;
}
function plFit() {
  // Recompute when rates change; the fit depends on every country's price level.
  if (_plFitFor !== lastRates) { _plFitFor = lastRates; _plFitVal = _computePlFit(); }
  return _plFitVal;
}
function plImplausible(iso) {
  const g = ppp && ppp[iso] && ppp[iso].gdppc;
  const pl = priceLevelRaw(iso);
  if (!(g > 0) || !pl) return false;
  const f = plFit();
  if (!f) return false;
  return Math.abs(Math.log(pl) - (f.a + f.b * Math.log(g))) > PL_PLAUSIBLE_SD * f.sd;
}
function priceLevel(iso) {
  return plImplausible(iso) ? null : priceLevelRaw(iso);
}
// Places the currency table and map can price but that aren't scored: no
// climate data or guide yet, so a ranked row would open a near-empty page.
// Tonga's pa'anga used to show a globe and "—" although the World Bank prices
// Tonga. Kept out of CUR_BY_ISO so they never reach the rankings, allPlaces()
// or the income fit (which the newsletter mirrors).
const TABLE_CUR = { TO: "TOP", WS: "WST", MV: "MVR", KY: "KYD", BM: "BMD",
  AG: "XCD", DM: "XCD", GD: "XCD", KN: "XCD", LC: "XCD", VC: "XCD",
  NC: "XPF", PF: "XPF", WF: "XPF" };
// Representative country for a currency (row flag, guide link, safety filter).
const PRIMARY_COUNTRY = { EUR: "DE", XOF: "SN", XAF: "CM", USD: "US", XCD: null };
function currencyCountries(code) {
  const out = [];
  for (const iso in CUR_BY_ISO) if (CUR_BY_ISO[iso] === code) out.push(iso);
  for (const iso in TABLE_CUR) if (TABLE_CUR[iso] === code && !out.includes(iso)) out.push(iso);
  return out;
}
function currencyCountry(code) {
  if (code in PRIMARY_COUNTRY) return PRIMARY_COUNTRY[code];
  return currencyCountries(code)[0] || null;
}
// Same arithmetic and plausibility test as priceLevel(), for a table-only
// place; it is tested against the fit but never feeds it.
function tablePriceLevel(iso) {
  if (CUR_BY_ISO[iso] || PPP_UNIT[iso]) return priceLevel(iso);
  const cur = TABLE_CUR[iso], e = ppp && ppp[iso];
  const rate = cur && e ? rateForCurrency(cur) : null;
  if (!rate) return null;
  const pl = e.ppp * pplCarry(iso) / rate;
  if (pl < 0.08 || pl > 6) return null;
  const f = plFit();
  if (f && e.gdppc > 0
      && Math.abs(Math.log(pl) - (f.a + f.b * Math.log(e.gdppc))) > PL_PLAUSIBLE_SD * f.sd) return null;
  return pl;
}
// A shared currency has no single price level: the euro row showed Germany's
// 0.80 while euro prices run from Kosovo (0.42) to Luxembourg (0.94). The table
// shows the range; sorting uses the median.
function currencySpread(code) {
  const pts = currencyCountries(code).map((iso) => ({ iso, pl: tablePriceLevel(iso) }))
    .filter((p) => p.pl != null).sort((a, b) => a.pl - b.pl);
  if (!pts.length) return null;
  const n = pts.length, mid = n % 2 ? pts[(n - 1) / 2].pl : (pts[n / 2 - 1].pl + pts[n / 2].pl) / 2;
  return { lo: pts[0], hi: pts[n - 1], mid, n, of: currencyCountries(code).length };
}
// Flag for a currency row: the euro uses the EU flag, multi-country basket/
// franc codes fall back to a globe, everything else uses its country flag.
const CUR_SUPRA_FLAG = { EUR: "🇪🇺", XOF: "🌍", XAF: "🌍", XPF: "🌍", XCD: "🌍", XDR: "🌍" };
function currencyFlag(code, iso) {
  return CUR_SUPRA_FLAG[code] || (iso ? flagEmoji(iso) : "🌍");
}
// "About the same as home" is one band everywhere: within ±10%. The cell word
// and its green/red ran on ±15% while plPhrase said ±10%, so Israel at 1.14
// read "about the same" in the table and "~14% pricier" in its guide, and
// Vanuatu at 0.87 likewise. −1 cheaper, 0 about the same, 1 pricier.
// Banded on the two decimals every cell shows: on raw values Vanuatu vs
// Germany (1.105) showed "1.10 pricey" and the Bahamas vs the US (0.904)
// "0.90 about the same", each on the wrong side of its own printed edge.
// plShown is toFixed(2) itself, the text the cells print: Math.round(rel *
// 100) / 100 differs from it on binary edges — 1.105 prints "1.10" but
// rounded to 1.11 and read "pricey" (likewise 0.605, 0.745, 0.815, 1.095).
const PL_SAME = 0.1;
const plShown = (rel) => +rel.toFixed(2);
function plBand(rel) { const r = plShown(rel); return r <= 1 - PL_SAME ? -1 : r <= 1 + PL_SAME ? 0 : 1; }
function plWord(pl) {
  const b = plBand(pl);
  return b < 0 ? (plShown(pl) < 0.55 ? "very cheap" : "cheap") : b > 0 ? "pricey" : "about the same";
}
// The price level in words, one way everywhere it is read (pill tip, row tip,
// map card, AI prompts, share images). 1 − pl is how much cheaper prices are;
// the "your money goes 1/pl further" framing overstated it (pl 0.58 read "73%
// further" for prices 42% lower), and "price level 0.47" is economist-speak.
// One fact used to appear as four different numbers across the hovers.
function plPhrase(rel, home) {
  const b = plBand(rel);
  return b < 0 ? `~${Math.round((1 - rel) * 100)}% cheaper than ${home}`
       : b > 0 ? `~${Math.round((rel - 1) * 100)}% pricier than ${home}`
       : `about the same as ${home}`;
}
// The colour that goes with plWord: green cheaper, red pricier, plain between.
function plCls(rel) { const b = plBand(rel); return b < 0 ? "pos" : b > 0 ? "neg" : ""; }
// The From country's price level — the yardstick "cheap" is measured against.
// Taiwan is a flight origin with no World Bank PPP row; it used to fall back to
// the US silently while every label said "vs Taiwan", so the fallback now says
// whose prices it really is.
function plAnchor(iso) {
  const pl = iso ? priceLevel(iso) : null;
  if (pl) return { iso, pl, name: iso === "US" ? "the US" : countryName(iso), cur: CUR_BY_ISO[iso] || "USD", home: true };
  return { iso: "US", pl: 1, name: "the US", cur: "USD", home: iso === "US" };
}
// "home" in the copy, unless the comparison had to fall back to the US.
function plHomeWord() { return plAnchor(guidePassport()).home ? "home" : "the US"; }
function plTag(pl) {
  const w = plWord(pl);
  const cls = plCls(pl);
  // nowrap (.pltag): "very cheap" is one phrase, and a narrow column split it
  // across two lines under the number, making the row three deep to say two
  // words. A class, not an inline style, so a 320px phone can let it wrap.
  return `<span class="pltag${cls ? " " + cls : ""}">${w}</span>`;
}
// Diverging around parity: 1.00 means $100 buys exactly $100 of what it buys at
// home. That threshold is the only one a traveler cares about, so it gets a hard
// visual break rather than being the pale middle of a smooth ramp.
// The red side starts at 45% saturation the moment a country crosses 1.00.
// Without that floor the handful of genuinely pricier countries (Switzerland at
// 1.13, Iceland 1.17) rendered as near-white and vanished into the map — the
// one group a US traveler most needs to spot.
function affordColor(pl) {
  if (pl <= 1) return mix("#eef0f1", "#0a7d28", Math.min(1, (1 - pl) / 0.8));
  return mix("#eef0f1", "#b00020", 0.45 + 0.55 * Math.min(1, (pl - 1) / 0.35));
}

// ---- wiring ---------------------------------------------------------------
$("check").addEventListener("click", checkNow);
$("save").addEventListener("click", saveConfig);
$("toggleSettings").addEventListener("click", async () => {
  const s = $("settings");
  s.hidden = !s.hidden;
  if (!s.hidden) await loadConfig();
});

// ===========================================================================
//  Region grouping (ISO -> region) for the travel tabs
// ===========================================================================
// index.html repeats these in the Data tab's four Region pickers (filled in
// the markup so they are their final width at first paint): keep in step.
const REGIONS = {
  AMER: "Americas", EUR: "Europe", MENA: "Middle East & N. Africa",
  ASIA: "Asia", AFRICA: "Africa (Sub-Saharan)", OCEANIA: "Oceania",
};
const ISO_REGION = (() => {
  const g = {
    AMER: "US CA MX GT BZ HN NI CR PA CU DO HT JM TT BS BB AW CW CO VE GY SR EC PE BR BO PY CL AR UY".split(" "),
    EUR: "GB GB-ENG GB-SCT GB-WLS IM JE GG CH LI NO SJ SE DK GL FO IS CZ PL HU RO BG RS BA MK AL MD UA BY RU TR AT BE CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES HR AD MC SM VA ME XK".split(" "),
    MENA: "IL PS SA AE QA KW BH OM JO LB SY IQ IR YE EG MA DZ TN LY".split(" "),
    ASIA: "CN JP KR IN PK BD LK NP AF MM TH VN KH LA MY SG ID PH BN HK MO TW MN KZ UZ TM KG TJ AZ AM GE BT".split(" "),
    AFRICA: "ZA NG KE GH ET TZ UG RW BI SD SS ER SO DJ AO MZ ZM BW NA SZ LS MW MG MU GM GN LR CD CV KM MR SC SN CI ML BF NE BJ TG GW CM TD CF CG GA GQ".split(" "),
    OCEANIA: "AU NZ FJ PG SB VU WS TO GU".split(" "),
  };
  const m = {};
  for (const r in g) for (const iso of g[r]) m[iso] = r;
  return m;
})();
// One region for the whole site, like the travel month and the From country:
// Top Picks' Region and the Data tab's share it (and the vr= link param). The
// maps it applies to zoom to it and shade everything outside it as "outside"
// — not grey "no data", and never a colour: under "Asia" the Do Not Travel
// fill used to light up Africa, Russia and Haiti.
const REGION_MAPS = new Set(["valueMap", "map", "affMap", "advMap", "flightMap"]);
let regionSel = (() => { const v = new URLSearchParams(location.search).get("vr") || ""; return REGIONS[v] ? v : "all"; })();
// Every place on the maps, not just the scored ones (Puerto Rico, the
// Caribbean islands, Pacific states come from the Wander List's continents).
function regionOf(iso) {
  if (ISO_REGION[iso]) return ISO_REGION[iso];
  if (iso === "EH") return "MENA";
  const c = continentOf(iso);
  return c ? ({ NA: "AMER", SA: "AMER", EU: "EUR", AS: "ASIA", AF: "AFRICA", OC: "OCEANIA" }[c] || null) : null;
}
const inRegion = (iso) => regionSel === "all" || regionOf(iso) === regionSel;
// A table row belongs if its country (or, for a currency, any country using
// it: data-regions) is in the region.
function regionRowOk(tr) {
  if (regionSel === "all") return true;
  if (tr.dataset.regions != null) return tr.dataset.regions.split(" ").includes(regionSel);
  return !!tr.dataset.iso && inRegion(tr.dataset.iso);
}
// lon1, lon2, lat1, lat2 each region is framed on.
const REGION_VIEW = {
  AMER: [-170, -30, -56, 72], EUR: [-25, 45, 34, 71], MENA: [-18, 63, 12, 42],
  ASIA: [34, 150, -11, 56], AFRICA: [-26, 52, -36, 22], OCEANIA: [110, 180, -48, 2],
};
function regionZoomBox(r) {
  const [lo1, lo2, la1, la2] = REGION_VIEW[r];
  const W = 1000, H = 386, latTop = 83, latBot = -56;
  const x1 = ((lo1 + 180) / 360) * W, x2 = ((lo2 + 180) / 360) * W;
  const y1 = ((latTop - la2) / (latTop - latBot)) * H, y2 = ((latTop - la1) / (latTop - latBot)) * H;
  const w = Math.max(x2 - x1, (y2 - y1) * W / H);
  return { x: (x1 + x2) / 2 - w / 2, y: (y1 + y2) / 2 - (w * H / W) / 2, w, h: w * H / W };
}
// One Region setting, one picker per Data table's filter bar (each tab shows
// its own, beside the search it narrows) plus Top Picks'.
const DATA_REGION_IDS = ["curRegion", "affRegion", "advRegion", "flightRegion"];
function setRegion(r) {
  regionSel = REGIONS[r] ? r : "all";
  for (const id of ["valueRegion", ...DATA_REGION_IDS]) {
    const sel = $(id);
    if (sel && sel.value !== regionSel) { sel.value = regionSel; if (sel._sync) sel._sync(); }
  }
  if (loaded.value) renderValue();
  if (dataRates) { renderRates(dataRates); renderMapSafe(); }
  if (loaded.afford) renderAfford();
  if (loaded.advisory && advisories) renderAdvisories();
  if (loaded.flights && flightsData && flightsData.configured) renderFlights();
  syncURL();
}
// Bound here, after REGIONS and regionSel exist; Top Picks fills its own
// select when that tab is built. The Data tab's four arrive filled from
// index.html (their width from first paint) — only an empty one is filled.
DATA_REGION_IDS.forEach((id) => fillRegionSelect($(id), "🌍 All regions"));
function fillRegionSelect(sel, allLabel) {
  if (!sel || sel._regionBound) return;
  sel._regionBound = true;
  if (!sel.options.length)
    sel.innerHTML = '<option value="all">' + (allLabel || "All regions") + '</option>'
      + Object.keys(REGIONS).map((r) => `<option value="${r}">${REGIONS[r]}</option>`).join("");
  sel.value = regionSel;
  sel.addEventListener("change", () => setRegion(sel.value));
}

const MONTHS = ["January","February","March","April","May","June","July",
  "August","September","October","November","December"];
const MON_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
// "a, b and c" — mirrors _join_and() in render_guide.py so the server and client
// copies of the best-months sentence read identically.
function joinAnd(items) {
  items = Array.from(items);
  if (items.length <= 1) return items[0] || "";
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}

function comfortColor(s) {
  if (s == null) return NODATA;
  return s >= 50 ? mix("#eef0f1", "#0a7d28", (s - 50) / 50)
                 : mix("#eef0f1", "#b00020", (50 - s) / 50);
}

// ===========================================================================
//  Climate data (best time to travel)
// ===========================================================================
let climate = null;
async function ensureClimate() {
  if (!climate) climate = await (await fetch("/climate.json")).json();
  return climate;
}

// Canada's travel health advice per country (build_health.py -> health.json):
// h = the diseases it calls a risk to travellers there, country-wide first;
// a = those among h it limits to some areas, seasons or itineraries; l = the
// ones it calls low or sporadic; n = those with a travel health notice. A
// failed load leaves `health` null and says so (healthFailed) rather than
// asking again on every redraw; the next page load tries again.
let health = null;
let healthFailed = false;
let _healthLoading = null;
function ensureHealth() {
  if (health) return Promise.resolve(health);
  return _healthLoading || (_healthLoading = getJSON("/health.json")
    .then((d) => { healthFailed = false; return (health = d && d.c ? d : { c: {} }); })
    .catch(() => { healthFailed = true; _healthLoading = null; return null; }));
}
// undefined while loading, null for a country the advice doesn't cover.
const healthOf = (iso) => (!health ? undefined : (iso && health.c[iso]) || null);
// West Nile virus: Canada's advice leaves it out (Italy, Greece and the US
// all report cases every summer), so build_health.py adds this season's
// reported transmission as `w`, from ECDC and/or CDC — each line says whose.
// Absent `w`, nothing changes. Countries missing from it are not "clear":
// ECDC watches the EU/EEA and seven neighbours (not Ukraine, Switzerland or
// the UK), CDC the US and its territories, and nobody here reports the rest.
const wnOf = (iso) => (health && health.w && health.w.c && iso && health.w.c[iso]) || null;
// A sentence closed with a full stop, unless it already ends one.
const fullStop = (s) => String(s || "").trim().replace(/([^.!?])$/, "$1.");
// Whose line it is. `w.source` names every agency in the build ("ECDC ·
// CDC"), so printing it credited ECDC with the US's count and CDC with
// Italy's; each entry's sentence opens with the one agency that made it
// ("ECDC: 590 …", "CDC: 987 …").
function wnAgency(iso) {
  const x = wnOf(iso), m = x && /^(ECDC|CDC):/.exec(x.t || "");
  return m ? m[1] : (health && health.w && health.w.source) || "ECDC";
}
// The agencies in the build, for the lines that speak of all of them:
// "ECDC · CDC" -> ["ECDC", "CDC"].
const wnAgencies = () => String((health && health.w && health.w.source) || "ECDC").split(/\s*·\s*/).filter(Boolean);
// Each agency's page, and the credit its data asks for. ECDC's is CC BY 4.0:
// its own credit line, the licence, and what we changed. `w.url` is ECDC's
// page, so a US line linked there sent readers looking for CDC's count to
// the wrong agency.
const WN_CC_URL = "https://creativecommons.org/licenses/by/4.0/";
const WN_ECDC_URL = "https://www.ecdc.europa.eu/en/west-nile-fever/surveillance-and-disease-data/disease-data-ecdc";
const WN_SRC = {
  ECDC: { credit: "Dataset provided by ECDC based on data provided by WHO and Ministries of Health from the affected "
            + "countries; adapted (per-country totals, top 10 areas)", licence: "CC BY 4.0",
          url: () => { const u = health && health.w && health.w.url; return /^https:\/\/[^/]*ecdc\.europa\.eu\//.test(u || "") ? u : WN_ECDC_URL; } },
  CDC: { credit: "Data: CDC ArboNET",
         url: () => "https://www.cdc.gov/west-nile-virus/data-maps/current-year-data.html" },
};
// The credit as a tip's sentence (a tip can't hold the licence's link; the
// notes row links it).
const wnCredit = (agency) => { const s = WN_SRC[agency]; return s ? fullStop(s.credit + (s.licence ? "; licence " + s.licence : "")) : ""; };
// "human cases reported in 2026", not "this season": ECDC's last report of
// a season stays up until the next one starts (December to June), when the
// entries read "in the 2025 season" under a label that said "this season".
// A country's own year comes from its own sentence ("in 2026 so far", "in
// the 2025 season"): w.season is the latest of the two agencies', so in
// winter, with CDC already on 2027, Italy's 2026 cases read "in 2027".
const wnYear = (iso) => {
  const m = /\b(?:in|the) (\d{4})\b/.exec(((wnOf(iso) || {}).t) || "");
  return m ? m[1] : (health && health.w && health.w.season) || "";
};
const wnIn = (iso) => { const y = iso ? wnYear(iso) : (health && health.w && health.w.season) || ""; return y ? " in " + y : ""; };
// "West Nile virus — human cases reported in 2026 (per ECDC)".
const wnLabel = (iso) => "West Nile virus — human cases reported" + wnIn(iso) + " (per " + wnAgency(iso) + ")";
// The areas, as many as the entry lists (10 at most) and how many it leaves
// out. " · ", not ", ": ECDC's names carry commas of their own ("Karditsa,
// Trikala" is one Greek area), so "Pella, Karditsa, Trikala" read as three.
// The count is the sentence's: "64 affected areas" (ECDC; older builds "in 64
// areas") or "from 42 states and DC" (CDC) — Italy listed 10 of 64 and read
// as complete.
function wnAreas(iso) {
  const x = wnOf(iso), a = (x && x.a) || [];
  if (!a.length) return "";
  const t = (x && x.t) || "";
  const m = /([\d,]+) (?:affected )?areas\b/.exec(t), s = /from ([\d,]+) states?( and DC)?\b/.exec(t);
  const n = m ? +m[1].replace(/,/g, "") : s ? +s[1].replace(/,/g, "") + (s[2] ? 1 : 0) : 0;
  return a.join(" · ") + (n > a.length ? " and " + (n - a.length) + " more" : "");
}
function wnText(iso) {
  const x = wnOf(iso);
  if (!x) return "";
  const areas = wnAreas(iso);
  return wnLabel(iso) + (areas ? ": " + areas : "") + "." + (x.t ? " " + fullStop(x.t) : "");
}
// The guide tip's closing caveat: without `w`, the sentence it always had;
// with it, where West Nile comes from instead (`here`: this country has a
// line). A country without one gets the build's coverage note too: "added
// where ECDC or CDC reported it" alone read as "no entry, no West Nile" in
// Russia or England, which neither agency covers.
function wnCaveat(here) {
  const w = health && health.w;
  if (!w) return "Not every risk is listed — West Nile virus, for one, isn't in Canada's advice.";
  return "Not every risk is listed" + (here ? "." : " — West Nile virus, which Canada's advice leaves out, is added where "
    + wnAgencies().join(" or ") + " reported human cases" + wnIn() + "." + (w.note ? " " + fullStop(w.note) : ""));
}
// The file is a snapshot (build_health.py, re-run by hand or on a schedule).
// A notice is only "current" while the snapshot is: past 45 days it's named
// as of its date and loses its warning colour.
const healthStale = () => !!(health && health.built && (Date.now() - Date.parse(health.built)) > 45 * 864e5);
const healthAsOf = () => (health && health.built ? fmtDay(health.built) : "");
// The chips' order: a notice first, then the build's (country-wide, then
// some-areas, each by how likely it is to change a trip).
// West Nile (`wn`, another agency's report) rides right after the notices:
// this season's cases are as current as a notice, and less settled than the
// standing list.
const WN_CHIP = "West Nile";
const healthNames = (hz, wn) => [...(hz.n || []), ...(wn ? [WN_CHIP] : []), ...hz.h.filter((x) => !(hz.n || []).includes(x))];
// What a country with none of the listed diseases shows: not "low risk" (our
// words, and untrue where Canada advises hepatitis A) but that only what
// Canada lists nearly everywhere applies.
const HEALTH_USUAL = "only the usual";
const HEALTH_USUAL_TIP = "None of the diseases Canada calls a risk to travellers here is one that sets a country apart. "
  + "Left out everywhere because Canada lists them for nearly every country: hepatitis A and B, routine vaccines, "
  + "travellers' diarrhea";
function healthGroups(hz) {
  const areas = hz.a || [], notice = hz.n || [];
  const wide = hz.h.filter((x) => !areas.includes(x) && !notice.includes(x));
  return [
    [healthStale() ? "Travel health notice as of " + healthAsOf() : "Current travel health notice", notice],
    ["A risk to travellers", wide],
    ["Only in some areas, seasons or itineraries", areas.filter((x) => !notice.includes(x))],
    ["Low or sporadic", hz.l || []],
  ].filter(([, list]) => list.length);
}
// `wn` = wnText(iso): West Nile, after Canada's credit — it is not Canada's.
function healthTip(hz, wn) {
  const parts = healthGroups(hz).map(([label, list]) => label + ": " + list.join(", "));
  if (!hz.h.length) parts.unshift(HEALTH_USUAL_TIP);
  return parts.join(". ") + ". Per the Government of Canada's travel health advice"
    + (hz.v ? " (its " + hz.v + " page)" : "")
    + (healthAsOf() ? " (as of " + healthAsOf() + ")" : "") + "."
    + (wn ? " " + wn : "");
}
// Chips. A notice leads with ⚠️ and a some-areas risk ends with ◐ — marks,
// not colour or a border alone, and each is spelled out for a screen reader.
// In a table cell (`fit`) every chip is written, with a hidden "+N" that
// fitChips() fills once it knows how many the cell has room for.
function chipHTML(n, kind) {
  if (kind === "notice") return `<span class="rkchip${healthStale() ? "" : " notice"}" data-n="${esc(n)}"><span class="rkwarn" aria-hidden="true">⚠️</span><span class="rkname">${esc(n)}</span>`
    + `<span class="vh"> (${healthStale() ? "travel health notice as of " + esc(healthAsOf()) : "current travel health notice"})</span></span>`;
  if (kind === "area") return `<span class="rkchip" data-n="${esc(n)}"><span class="rkname">${esc(n)}</span><span class="rkmark" aria-hidden="true"> ◐</span>`
    + `<span class="vh"> (only in some areas, seasons or itineraries)</span></span>`;
  // West Nile: `kind` is "wn:<agency>:<iso>" — the agency that reported this
  // country's cases (not every agency in the build), and the country, whose
  // own sentence gives the year.
  if (kind && kind.startsWith("wn:")) {
    const [, agency, wiso] = kind.split(":");
    return `<span class="rkchip" data-n="${esc(n)}"><span class="rkname">${esc(n)}</span>`
      + `<span class="vh"> (human cases reported${esc(wnIn(wiso))}, per ${esc(agency)})</span></span>`;
  }
  return `<span class="rkchip" data-n="${esc(n)}"><span class="rkname">${esc(n)}</span></span>`;
}
function chipsHTML(names, kindOf, fit) {
  return names.map((n) => chipHTML(n, kindOf ? kindOf(n) : "")).join("")
    + (fit ? '<span class="rkchip more" hidden></span>' : "");
}
// `wnBy`: the agency behind this country's West Nile line (wnAgency), or
// nothing when it has none.
function healthChipsHTML(hz, fit, wnBy, wnIso) {
  const notice = hz.n || [], areas = hz.a || [];
  return chipsHTML(healthNames(hz, wnBy), (n) => (notice.includes(n) ? "notice" : wnBy && n === WN_CHIP ? "wn:" + wnBy + ":" + (wnIso || "")
    : areas.includes(n) ? "area" : ""), fit);
}
// One line of chips a cell: as many as its width holds, the rest counted in
// the "+N" (named for a screen reader, and in the tip and the notes row).
// Measured, not guessed from the window — a fixed cap left Argentina using
// 235px of a 386px cell and still stood 21 rows up at 1100. One read pass,
// then one write pass.
function fitChips(root) {
  // Hidden (another tab, or a phone with the columns off): nothing to
  // measure yet. The table's ResizeObserver fits it once it has a width.
  if (!root || !root.offsetWidth) return;
  const wraps = [...root.querySelectorAll("td > .rkwrap, td > .hzwrap")].filter((w) => w.offsetWidth);
  for (const w of wraps) {
    w.querySelectorAll(".rkchip.cut, .rkchip.shrink").forEach((c) => c.classList.remove("cut", "shrink"));
    const more = w.querySelector(".rkchip.more");
    if (more) more.hidden = true;
  }
  const plan = wraps.map((w) => {
    const chips = [...w.children].filter((c) => !c.classList.contains("more") && !c.classList.contains("rkus"));
    const room = w.clientWidth;
    const right = chips.map((c) => c.offsetLeft + c.offsetWidth);
    if (!chips.length || right[right.length - 1] <= room) return null;
    // A lone chip too wide for its cell just shortens ("Tick-borne enc… ◐");
    // otherwise keep room for a "+12" chip and its gap.
    if (chips.length === 1) return { w, chips, k: 1 };
    const plus = 40;
    const k = right.filter((r) => r <= room - plus).length;
    return { w, chips, k: Math.max(1, k) };
  });
  for (const p of plan) {
    if (!p) continue;
    const rest = p.chips.slice(p.k);
    rest.forEach((c) => c.classList.add("cut"));
    if (p.k === 1) p.chips[0].classList.add("shrink");
    const more = p.w.querySelector(".rkchip.more");
    if (!more || !rest.length) continue;
    more.hidden = false;
    more.innerHTML = "+" + rest.length + '<span class="vh">: '
      + esc(rest.map((c) => c.dataset.n || c.textContent).join(", ")) + "</span>";
  }
}

// EKTA travel insurance via Travelpayouts — the client-side twin of the link
// render_guide.py puts in the server block. Both are needed: the server copy is
// what a crawler reads, and renderGuide() deletes it a few lines below, so the
// server copy alone would be a link no human ever sees. sub_id matches on both
// sides so a click counts once, against the right country.
//
// A plain <a>, never their widget: a third-party script is a failure mode this
// site does not need. EKTA has no per-country pages, so every link lands on the
// same quote form — which is why the text says "travel insurance" rather than
// naming the country. Promising a country-specific page we cannot deliver would
// buy a few more clicks with a small lie.
function insuranceHref(iso) {
  const slug = (typeof ISO2SLUG !== "undefined" && ISO2SLUG && ISO2SLUG[iso]) || iso.toLowerCase();
  return "https://tp.media/r?campaign_id=225&marker=738472&p=5869&sub_id=guide-"
       + encodeURIComponent(slug) + "&trs=541205&u=https%3A%2F%2Fektatraveling.com";
}
function renderGuideInsurance(iso) {
  const host = $("guideInsurance");
  if (!host) return;
  // No insurance, stays or tours under "Level 4 — do not travel": the grades
  // are the product, and a booking button beneath "do not travel for any
  // reason" makes the badge look like it is there to sell the booking. Held
  // back until the level is known, so it never flashes on a Level 4 page.
  // Empty until then it holds its usual height (styles.css #guideInsurance:
  // empty), so a Level 4 page hides it outright rather than keep a blank.
  // The server's stand-in for it (.gsizer) stays instead until then: emptied,
  // the note's bottom margin it carries went with it (12px at 1280).
  if (!host.querySelector('.gsizer[data-for="' + iso + '"]')) host.innerHTML = "";
  const show = () => {
    if (ccGuideIso !== iso) return;
    host.hidden = guideAdvLevel(iso) === 4;
    if (!host.hidden) fillGuideInsurance(host, iso);
  };
  ensureAdvisories().then(show, show);
}
// The grades the 📸 share card prints, on the page itself (an export must not
// show a figure its own page never shows): the same valueScores call, the
// travel month, the reader's Top Picks priorities. Static host (#guideGrades,
// height reserved in styles.css), so filling it moves nothing.
let _guideAskedFares = false, _guideFarePend = null, _guideFareLate = false;
async function renderGuideGrades(iso) {
  const host = $("guideGrades");
  if (!host) return;
  try { await Promise.all([ensureAdvisories(), ensurePPP()]); } catch (e) {}
  if (ccGuideIso !== iso) return;
  // The fares the ✈️ grade (and so the Overall) needs load with Top Picks; a
  // guide opened directly never asked for them, and graded flights as "—"
  // with an Overall the Top Picks table wouldn't show. Ask once; its arrival
  // re-renders this line (loadValueFlights), and so does its settling, once
  // more if it failed.
  if (!flightsData && !_guideAskedFares) {
    _guideAskedFares = true;
    _guideFarePend = loadValueFlights(true).finally(() => {
      _guideFarePend = null;
      if (ccGuideIso) renderGuideGrades(ccGuideIso);
    });
    // Fares still out after 2.5s: the line is drawn without them (below).
    setTimeout(() => { if (_guideFarePend) { _guideFareLate = true; if (ccGuideIso) renderGuideGrades(ccGuideIso); } }, 2500);
  }
  const month = parseInt(($("valueMonth") || {}).value, 10) || curMonth();
  let s = null;
  try { s = valueScores(iso, month, advisoryByIso(), buildFareContext(), plAnchor(originIso()).pl); } catch (e) {}
  // A graded line is drawn once, with its fares: drawn before them too, its
  // "—" for flights made it 445px against 438 after, and on an 810px iPad
  // the country picker beside the title wrapped under it and came back
  // (CLS 0.32-0.64). The empty line holds its width meanwhile (styles.css).
  // But fares 2.5s late left the line blank for seconds (7-10s with fares
  // 5s slow), so then it is drawn with the three grades that don't need
  // them, and the Overall, its number and ✈️ as grey pending boxes; the fares
  // fill them in place, each keeping at least its box's width (_ggHold,
  // below) so nothing beside it moves. The boxes are a one-letter grade's
  // pill (the narrowest a grade draws) and the number the scores give
  // without fares: sized by the grades these scores give without fares
  // ("B+ 84" for Thailand against "A 85" with them), the line was 7px
  // wider than its fares make it, and on an 810px iPad that wrapped the
  // country picker under the title (CLS 0.32).
  if (s && _guideFarePend && !_guideFareLate) return;
  const pending = !!(s && _guideFarePend);
  const act = activities && activities[iso];
  const days = act && act.days ? '<span class="ggdays" data-tip="' + esc("Worth " + act.days[0] + "–" + act.days[1]
    + " days on a first visit") + '" title="">🧳 ' + act.days[0] + "–" + act.days[1] + " days</span>" : "";
  const grey = (txt, tip) => '<span class="gr grx" data-tip="' + esc(tip) + '" title="">' + txt + "</span>";
  if (!s) {
    const lvl = guideAdvLevel(iso);
    const why = lvl === 4 ? "Level 4, do not travel: not graded"
      : !lvl ? "No advisory from the governments we follow, so it isn't graded" : "Not enough data to grade it";
    host.innerHTML = grey("—", why) + '<span class="vh"> ' + esc(why) + "</span>" + days;
    return;
  }
  const wait = (k, cls, txt) => '<span class="' + cls + ' skel ggpend" data-gg="' + k + '" data-tip="Waiting for fares…" title="">'
    + '<span class="ggph">' + txt + "</span></span>";
  const f = (emo, word, pill) => '<span class="ggf"><span aria-hidden="true">' + emo + '</span><span class="vh">' + word + " </span>" + pill + "</span>";
  const fly = pending ? wait("fly", "gr", "A")
    : s.fare == null ? grey("—", "No fare data")
    : (s.flyBasis !== "month" && s.fareEst) ? grey("~" + grade(s.fly), "Estimated — no cached fare yet, so flights count as a typical fare for the distance.")
    : gradePill(s.fly, s.flyBasis === "month" ? MONTHS[month - 1] + "'s fare vs this route's usual" : "Year-round fare vs the typical fare for this distance");
  host.innerHTML = (pending ? wait("ov", "gr big", "A") + wait("num", "ggnum", s.value)
      : gradePill(s.value, "Overall " + grade(s.value) + " · " + s.value + "/100 for " + MONTHS[month - 1], "big")
        .replace('class="', 'data-gg="ov" class="') + '<span class="ggnum" data-gg="num">' + s.value + "</span>")
    + f("💰", "Affordability", gradePill(s.afford, affordTitle(s).replace(" · click for cost-of-living detail", "")))
    + f("🛡️", "Safety", safetyPill(s.advLvl, iso))
    + f("🌤️", "Weather", s.wx == null ? grey("—", "No weather data") : gradePill(s.wx, s.wx + "/100 weather comfort in " + MONTHS[month - 1]))
    + f("✈️", "Flights", pending ? fly : fly.replace('class="', 'data-gg="fly" class="')) + days
    + '<span class="muted" data-tip="' + esc("Graded for " + MONTHS[month - 1] + " from " + originLabel()
      + ", weighted by your Top Picks priorities — the grades the Top Picks table and this page's 📸 share card show.") + '" title="">ⓘ</span>';
  // The pending boxes' widths, kept for this guide: every later draw of it
  // (the fares' own redraw, and their settling's) gives each grade at least
  // its box's width.
  if (pending) {
    const w = {};
    host.querySelectorAll(".ggpend").forEach((e) => { w[e.dataset.gg] = e.getBoundingClientRect().width; });
    _ggHold = { iso, w };
  } else if (_ggHold && _ggHold.iso === iso) {
    for (const k in _ggHold.w) { const e = host.querySelector('[data-gg="' + k + '"]'); if (e) e.style.minWidth = _ggHold.w[k] + "px"; }
  }
}
let _ggHold = null;
function fillGuideInsurance(host, iso) {
  // Named, and styled like the stay buttons it sits beside. It used to read
  // "Compare travel insurance" as a bare text link, which was wrong twice: it
  // compares nothing — it is one insurer's quote form — and an unfamiliar brand
  // in plain text under two styled buttons for names people know reads as an ad
  // somebody slipped in rather than a tool the site offers.
  host.innerHTML = '<div class="staybtns"><a class="staybtn" target="_blank" '
    + 'rel="sponsored nofollow noopener" href="' + insuranceHref(iso) + '">'
    + '🛡️ Travel insurance (EKTA) <span class="ext">↗</span></a></div>'
    // Worded to cover the whole booking section above it (stays + insurance),
    // not just this one link — the FTC wants the disclosure next to the links
    // it discloses, and the footer alone is too far away.
    + '<p class="affnote">Some links in this section are affiliate links — we may earn a commission, at no extra cost to you.</p>';
}

// -- Tab: country guide (best time + things to do, one picker) ---------------
function renderGuide(iso) {
  // Drop the server-rendered crawler block now that we're rendering the real,
  // interactive guide (prevents duplicate content). Its words go now; what is
  // left of its room after the activities above it fill (below) stays, blank,
  // until they have settled — their photos add 17-19px a row, the tours
  // button its line once the level is known. Removed outright, a guide whose
  // activities fill shorter than this block ended inside a 1280px screen
  // scrolled 700px down: the newsletter box rose into view, then the photos
  // pushed it back out, an 864px move that made Chrome score every 12px move
  // in that frame at full distance (CLS 0.044 on Iceland).
  const ssr = $("ssrGuide"), ssrH = ssr ? ssr.offsetHeight : 0;
  const actH0 = ssr ? $("actDetail").offsetHeight : 0;
  if (ssr) { ssr.innerHTML = ""; ssr.id = ""; ssr.setAttribute("aria-hidden", "true"); }
  // The advisory level, for styles.css's first-paint holds (the advisory
  // block, and on Level 4 the grades line, stays and insurance): the server
  // marks its own country (data-level); any other gets it from the advisories
  // once they are in, and none before (the holds for Level 2, the usual).
  const gtab = $("tab-guide");
  if (gtab) {
    const lvl = advisories ? guideAdvLevel(iso) : 0;
    if (lvl) gtab.setAttribute("data-level", lvl);
    else if (advisories || iso !== window.__WGGC__) gtab.removeAttribute("data-level");
    // Whether the fares strip will come, so its room is held only then
    // (data-fm, styles.css): the Flights data says, once it is in for this
    // origin (renderGuideFares draws from 3 months of the same curve); before
    // that the server's mark stands for its own guide whatever the origin
    // (UK, German and Canadian curves cover the same popular guides, and a
    // first visit learns its origin from location only after this runs),
    // and nothing is held for another guide (held and given back, the lines
    // under it jumped 154px). loadFlightValue settles it when the data lands.
    const fvC = flightValue && flightValue.origin === originIso() && flightValue.countries
      && flightValue.countries[iso];
    const fm = fvC && !fvC.pending ? (fvC.n_curve || 0) >= 3
      : iso === window.__WGGC__ ? null : false;
    if (fm) gtab.setAttribute("data-fm", "1");
    else if (fm === false) gtab.removeAttribute("data-fm");
    // The FX and local-prices lines likewise (data-fx, data-cost): none for
    // a currency the reader holds or a country without one, none on the
    // reader's own country; the server's marks stand for its own guide
    // otherwise (it also knows which have no price figure or FX chart).
    const fxIso = GUIDE_PARENT[iso] || iso, cur = CUR_BY_ISO[fxIso];
    if (!cur || cur === (homeBase || "USD")) gtab.setAttribute("data-fx", cur ? "home" : "0");
    else if (iso !== window.__WGGC__ || gtab.getAttribute("data-fx") === "home") gtab.removeAttribute("data-fx");
    if (fxIso === originIso()) gtab.setAttribute("data-cost", "home");
    else if (iso !== window.__WGGC__ || gtab.getAttribute("data-cost") === "home") gtab.removeAttribute("data-cost");
  }
  // The page's one h1. On /guide/<slug> the server already sent this exact
  // markup (render_guide.h1_html), so hydration writes nothing and nothing
  // swaps; other entries fill it and reveal it here.
  syncGuideH1(iso);
  const gh1 = $("guideH1");
  if (gh1) gh1.hidden = false;
  // Its topics come from guide-facts.json; fetched now, so a guide opened
  // in-app later already has them (and this one is corrected if it had to guess).
  if (!_guideFacts) ensureGuideFacts().then(() => { if (ccGuideIso === iso) syncGuideH1(iso); }).catch(() => {});
  renderGuideInsurance(iso);
  renderGuideGrades(iso);
  // Title and canonical here, not only in openGuideFor: the country picker and a
  // plain return to the guide tab both re-render without going through it, which
  // left the h1 naming one country while the title still said another (or the
  // site default). Every path that draws a guide now describes that guide.
  setGuideMeta(iso);
  renderGuideHero(iso);
  renderGuideVisa(iso);
  renderGuideSafety(iso);
  renderGuideAI(iso);
  renderCountryClimate(iso);
  const acts = renderActivity(iso);
  if (ssr) {
    // Only what the activities didn't take: held whole, the newsletter box
    // and the footer would drop by the activities' full height instead.
    ssr.style.height = Math.max(0, ssrH - ($("actDetail").offsetHeight - actH0)) + "px";
    Promise.race([Promise.allSettled([acts, ensureAdvisories()]), new Promise((r) => setTimeout(r, 8000))])
      .then(() => ssr.remove());
  }
  renderGuideStay(iso);
  // The fare column (fares by month, local prices, FX) fills in three
  // fetches, 0 -> 19 -> 96px at 768 and 250 with the fares: each block keeps
  // its place (.farecol.loading, styles.css) until all three have settled,
  // then the ones that didn't come go at once — released as each landed, the
  // column moved what is under it at every step.
  const fc = document.querySelector("#tab-guide .farecol");
  const fcSeq = ++_fareColSeq;
  if (fc) fc.classList.add("loading");
  Promise.allSettled([renderGuideFares(iso), renderGuideCost(iso), renderGuideFx(iso)])
    .then(() => { if (fc && fcSeq === _fareColSeq) fc.classList.remove("loading"); });
  syncURL();
}
let _fareColSeq = 0;

// ---- Fare-by-month strip ----------------------------------------------------
// The flights answer to "when should I go": /api/flight-months serves the
// cheapest cached fare per month up to a year forward for one route. Months
// nobody searched are absent and render as absence — a gap cell, never an
// invented number. Guide + Trip only for now; the Top Picks table waits until
// a few days of API behavior say the rate limits can carry 20 rows at once.
const _fareMonthsCache = {};
async function ensureFareMonths(iso) {
  // iso resolves to a destination city on the SERVER against its cached fares,
  // so this works on a direct guide load with no client fares bootstrap — the
  // first production version raced that bootstrap and stayed hidden forever.
  // The traveller's origin, not flightsData.origin: a stale or guide-first
  // fares payload (fetched for the US before the geo seed) must not win.
  const origin = originIso();
  const key = origin + ":" + iso;
  if (!_fareMonthsCache[key]) {
    // A FAILED fetch must not cache as permanent "no data" — one cold-start
    // 5xx would hide fare strips everywhere for the whole session. Evict on
    // failure so the next render retries; only genuine empties stay cached.
    _fareMonthsCache[key] = getJSON("/api/flight-months?origin=" + encodeURIComponent(origin)
      + "&iso=" + encodeURIComponent(iso)).then((r) => (r && r.months && Object.keys(r.months).length ? r : null))
      .catch(() => { delete _fareMonthsCache[key]; return null; });
  }
  return _fareMonthsCache[key];
}

// A cached fare in the reader's currency, the same look as the Flights tab:
// the code always, "≈" when converted at today's rate. A bare "$" read as
// local money to a Canadian or an Australian, and the strips carried it to
// every traveller — "$258" beside "EUR 1,500" budget copy.
function fareMoney(v, cur, conv) {
  return (cur === "USD" ? "" : "≈") + cur + " " + Math.round(v * (conv || 1)).toLocaleString();
}
// Strip options for the table and trip strips: the reader's flight currency
// (the guide and the Flights tab follow the same rule), or USD while no rate
// has loaded. Scoring and the budget filter stay in USD; this is display.
function fareStripOpts(month) {
  const c = flightDisplayCur();
  const r = c === "USD" ? 1 : rateForCurrency(c);
  return { highlightMonth: month, minMonths: 6, cur: r ? c : "USD", conv: r || 1 };
}

// The next 12 months as cells, coloured within THIS route's own range —
// cheapest month green, priciest red, missing grey. Returns null when there's
// too little to say (a one-month curve is a number, not a season).
function fareStripHTML(months, opts) {
  opts = opts || {};
  // Calendar Jan-Dec order, NOT next-12-months order: these strips sit beside
  // the season strips, which are calendar-ordered, and two same-looking strips
  // with different month axes in one row would be a quiet lie. Each month
  // shows its NEXT occurrence's fare.
  const now = new Date();
  const keys = [];
  for (let m = 1; m <= 12; m++) {
    const y = m > now.getMonth() ? now.getFullYear() : now.getFullYear() + 1;
    keys.push({ key: y + "-" + String(m).padStart(2, "0"), mon: m });
  }
  // Below minMonths the strip doesn't render at all: a 12-cell strip with
  // three filled cells reads as broken UI, not as sparse data. The compact
  // table/trip strips demand half a year of real months; the guide chart,
  // which labels and explains itself, tolerates fewer.
  const present = keys.filter((k) => months[k.key]);
  if (present.length < (opts.minMonths || 3)) return null;
  const vals = present.map((k) => months[k.key].price);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const conv = opts.conv || 1, cur = opts.cur || "USD";
  const fm = (v) => fareMoney(v, cur, conv);
  const cells = keys.map((k) => {
    const m = months[k.key];
    const nowCls = opts.highlightMonth === k.mon ? " now" : "";
    if (!m) return '<span class="fcell na' + nowCls + '" data-tip="'
      + esc(MONTHS[k.mon - 1] + " — no cached fares for this month") + '" title=""></span>';
    const t = hi > lo ? (m.price - lo) / (hi - lo) : 0.5;
    const fill = t <= 0.5 ? mix("#eef0f1", "#0a7d28", 1 - t * 1.3)
                          : mix("#eef0f1", "#b00020", (t - 0.5) * 1.3);
    return '<span class="fcell' + nowCls + '" style="background:' + fill + '" data-tip="'
      + esc(MONTHS[k.mon - 1] + ": from " + fm(m.price) + " round-trip"
        + (m.stops != null ? " · " + fmtStops(m.stops).replace(/<[^>]+>/g, "") : "")) + '" title=""></span>';
  }).join("");
  const cheap = present.reduce((a, b) => (months[a.key].price <= months[b.key].price ? a : b));
  const dear = present.reduce((a, b) => (months[a.key].price >= months[b.key].price ? a : b));
  return { cells, note: "cheapest " + MON_ABBR[cheap.mon - 1] + " " + fm(months[cheap.key].price)
      + " · priciest " + MON_ABBR[dear.mon - 1] + " " + fm(months[dear.key].price),
    cheapMon: cheap.mon, cheapPrice: months[cheap.key].price };
}

// A fare short enough for a phone's ~20px fare column: 818, 1.3K, 12K, 1.5M.
// Deliberately not Intl's compact notation in the reader's locale — de gives
// "12.000" and "1,5 Mio.", es "1,3 mil", all wider than the column. The digits
// still follow the reader's locale (toLocaleString); only the suffix is fixed.
function fareShort(n) {
  if (n < 1000) return n.toLocaleString();
  if (n < 1e6) return (n < 1e4 ? Math.round(n / 100) / 10 : Math.round(n / 1000)).toLocaleString() + "K";
  return (n < 1e7 ? Math.round(n / 1e5) / 10 : Math.round(n / 1e6)).toLocaleString() + "M";
}

async function renderGuideFares(iso) {
  const host = $("guideFares");
  if (!host) return;
  host.hidden = true;
  const fm = await ensureFareMonths(iso);
  if (ccGuideIso !== iso || !fm || !fm.months) return;
  const now2 = new Date();
  const prices = [];
  for (let m = 1; m <= 12; m++) {
    const y = m > now2.getMonth() ? now2.getFullYear() : now2.getFullYear() + 1;
    const rec = fm.months[y + "-" + String(m).padStart(2, "0")];
    prices.push(rec ? rec.price : null);
  }
  const known = prices.filter((p) => p != null);
  // Under three months there is no curve to read (the Trip strip's floor,
  // fareStripHTML minMonths): two bars would claim a season.
  if (known.length < 3) return;
  host.hidden = false;
  // Origin name from the strip's own payload — flightsData may be null on a
  // direct guide load (that null is what hid the first production version).
  const originName = countryName(fm.origin || travelOrigin() || "US");
  // The guide gets real bars, not chips: it sits beside the full-size
  // temperature chart and must speak that chart's language — 12 labeled
  // columns, the number on the bar, taller = cheaper (tall means "go", same
  // as the comfort bars; colour double-codes it so nobody misreads).
  // The Flights tab's formatter, so every currency gets the same treatment:
  // "USD 646" and "≈EUR 734" in the tips, the unit named once in the header,
  // bare numbers on the bars. The old "$646" vs "≈734" made the dollar the
  // one currency with a symbol and left the euro with no unit at all.
  const { F, money, approx, cur } = flightFmt();
  // Each month against the route's TYPICAL fare, not its own min and max —
  // min-max scaling drew a 6% spread as full green against full red. The
  // Flights tab's range (median + typical band, /api/flight-value) when it
  // has this route, so the two agree; else this curve's median with ±8%.
  const fvC = flightValue && flightValue.origin === (fm.origin || originIso())
    && flightValue.countries && flightValue.countries[iso];
  const typ = fvC && fvC.median != null ? fvC : null;
  const sorted = known.slice().sort((a, b) => a - b), mid = sorted.length >> 1;
  const med = typ ? typ.median : sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const bandOf = (p, dev) => (typ ? (p < typ.lo ? "low" : p > typ.hi ? "high" : "typical")
                                  : dev < -0.08 ? "low" : dev > 0.08 ? "high" : "typical");
  // The trip month is boxed like the temperature chart's (.selmonth), so the
  // fare for the month being planned is findable at a glance; planForMonth
  // redraws this panel when it changes.
  const selM = parseInt(($("valueMonth") || {}).value, 10) || curMonth();
  // The tip sits on the whole column, not the bar: on a phone a 9px-wide bar
  // (or an 8%-high empty stub) was the only tap target.
  const cols = prices.map((p, i) => {
    const colCls = "col" + (i + 1 === selM ? " selmonth" : "");
    if (p == null) return '<div class="' + colCls + '" data-tip="'
      + esc(MONTHS[i] + " — no cached fares") + '" title=""><div class="mscore">–</div>'
      + '<div class="fill na" style="height:8%"></div>'
      + '<div class="mlabel">' + MON_ABBR[i] + "</div></div>";
    const dev = p / med - 1;
    const band = bandOf(p, dev);
    const h = Math.max(30, Math.min(95, 62 - dev * 110));     // taller = cheaper
    // Typical months take the Flights tab's range-bar grey (styles .fill.typ)
    // rather than the map's pale fill, which vanished against the panel.
    const fill = band === "typical" ? "" : ";background:" + fareValueFill({ state: "ok", band, dev });
    // Two labels, CSS picks one: the full number where the column fits it,
    // the compact one on a phone (styles: .farebars .mscore .mfull/.mshort).
    return '<div class="' + colCls + '" data-tip="'
      + esc(MONTHS[i] + ": from " + money(p) + " round-trip · " + FV_WORD[band]
        + (band === "typical" ? "" : " (" + fmtDevPct(dev) + " vs typical)")) + '" title="">'
      + '<div class="mscore"><span class="mfull">' + F(p).toLocaleString() + '</span><span class="mshort">'
      + fareShort(F(p)) + "</span></div>"
      + '<div class="fill' + (band === "typical" ? " typ" : "") + '" style="height:' + h + "%" + fill + '"></div>'
      + '<div class="mlabel">' + MON_ABBR[i] + "</div></div>";
  }).join("");
  // One accessible name for the chart rather than 12 tab stops: every month's
  // number (or "no data") in the order the bars show them.
  const ariaFares = "Fares by month, " + approx + cur + ": " + prices.map((p, i) =>
    MON_ABBR[i] + " " + (p == null ? "no data" : F(p).toLocaleString())).join(", ");
  // Source, method and legend in the ⓘ; the header itself is one line. The
  // cheapest/priciest note it carried repeated what the bars already label.
  const tip = "Cheapest cached round-trip Aviasales has seen for each departure month"
    + (approx ? ", converted at today's rate" : "") + " — indicative, not live. Taller = cheaper. "
    + "Colour = the month against the route's typical fare: green low, pale typical, red high"
    + (typ ? " (the Flights tab's range)." : ".");
  host.innerHTML = '<span class="fareshead">✈️ Fares by month'
    + '<span class="legendinfo" data-tip="' + esc(tip) + '" title="">ⓘ</span>'
    + ' <span class="muted">' + esc(originName + " → " + countryName(iso) + " · round-trip, " + approx + cur)
    + "</span></span>"
    + '<div class="bars farebars" role="img" aria-label="' + esc(ariaFares) + '">' + cols + "</div>";
}

// ---- FX trailing trend ------------------------------------------------------
// A LINE, deliberately not bars: bars on this page mean "pick a month" (fares,
// temperature). FX has no forecastable seasonality, so this chart answers only
// "is your money going further than usual right now" — backward-looking
// monthly averages, the same 1-yr-average anchor the affordability score's FX
// component already uses. Never a month-picker. Plotted in today's prices
// (inflation gap removed, see realFxPct), so the headline matches the table's
// FX mark and a steady depreciation no longer reads as a bargain.
const _fxTrendCache = {};
async function renderGuideFx(iso) {
  const host = $("guideFx");
  if (!host) return;
  host.hidden = true;
  host.innerHTML = "";
  // Home nations borrow the UK's pound and inflation figure (GUIDE_PARENT).
  const fxIso = GUIDE_PARENT[iso] || iso;
  const dest = CUR_BY_ISO[fxIso];
  const base = homeBase || "USD";
  // Same currency both ends (an American in Ecuador) = no FX story to tell.
  if (!dest || dest === base) return;
  const key = base + ":" + dest;
  let t;
  try {
    t = await (_fxTrendCache[key] ||
      (_fxTrendCache[key] = getJSON("/api/fx-trend?cur=" + dest + "&base=" + base)));
  } catch (e) { delete _fxTrendCache[key]; return; }
  // The inflation figures ride in ppp.json (cached; usually already loaded).
  await ensurePPP().catch(() => {});
  // Guard BOTH coordinates that can shift during the await: the open guide
  // (ccGuideIso) and the home currency — a stale in-flight fetch for the
  // previous base must not paint over the fresh chart.
  if (ccGuideIso !== iso || homeBase !== base
      || !t || !t.months || t.months.length < 6) return;
  // The 364-day window starts mid-month, so its first calendar bucket can be a
  // few days wide — it was plotted as a full month ("Sep to Sep", 13 points).
  let months = t.months;
  const asOf = Date.parse((t.as_of || "") + "T12:00:00Z") || Date.now();
  if (months.length > 12) {
    const start = new Date(asOf - 364 * 864e5);
    const dim = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)).getUTCDate();
    if (months[0].m === start.toISOString().slice(0, 7) && dim - start.getUTCDate() + 1 < 15)
      months = months.slice(1);
  }
  const homeIso = fxHomeIso();
  // ppp.json failed to load: no inflation figures for ANY country, which is not
  // the same as this country's being out of date — plain move, no verdict.
  const noInfl = !ppp;
  const b = noInfl ? null : fxInflBasis(fxIso, homeIso);
  const real = noInfl ? null : realFxPct(fxIso, t.pct, homeIso);
  const nominal = real == null;              // high inflation, no current figure
  const g = nominal ? 1 : (1 + b.rL) / (1 + b.rB);
  // Each month in today's prices: v * g^(age in years of the month's midpoint).
  const age = (m) => Math.max(0, (asOf - Date.UTC(+m.slice(0, 4), +m.slice(5, 7) - 1, 15)) / (365.25 * 864e5));
  const pts = months.map((m) => m.v * Math.pow(g, age(m.m)));
  const avg = t.avg * Math.pow(g, 0.5);      // same 0.5-year mean age realFxPct uses
  const pct = Math.round((nominal ? t.pct : real) * 10) / 10;
  const lo = Math.min(...pts, avg), hi = Math.max(...pts, avg);
  const W = 240, H = 46, P = 4;
  const x = (i) => P + (i * (W - 2 * P)) / (pts.length - 1);
  const y = (v) => (hi > lo ? P + (H - 2 * P) * (1 - (v - lo) / (hi - lo)) : H / 2);
  const path = pts.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ");
  // Same thresholds as the Currency tab's strong/typical/weak labels.
  const col = nominal ? "#8891a0" : pct >= 2 ? "#2f9e44" : pct <= -2 ? "#d9480f" : "#8891a0";
  const verdict = pct >= 2 ? "goes further than usual" : pct <= -2 ? "goes less far than usual" : "about typical";
  const mLabel = (m) => MON_ABBR[parseInt(m.slice(5), 10) - 1] + " '" + m.slice(2, 4);
  const cn = countryName(iso);
  const gap = inflGapText(fxIso, homeIso);
  const tip = (fxIso !== iso ? `${cn} uses ${dest}, so these are ${parentWide(fxIso)} figures. ` : "") + (noInfl
      ? "Inflation figures didn't load, so this is the plain exchange-rate move — in high-inflation"
        + " countries prices can rise faster than the currency falls. "
      : nominal
      ? `Nominal — ${countryName(b.stale)}'s inflation data isn't current, so we can't say whether your money goes further. `
      : gap ? `After inflation: the exchange-rate move minus the inflation gap (${gap}, World Bank)`
          + (Math.abs(t.pct - pct) >= 0.1 ? `; the plain rate moved ${signedPct(Number(t.pct), 1)}` : "") + ". "
        : `No current inflation figure for ${countryName(fxIso)}, so this is the plain exchange-rate move. `)
    + `Monthly averages of the daily ${base}→${dest} rate, ${mLabel(months[0].m)} to ${mLabel(months[months.length - 1].m)}`
    + (nominal || !gap ? "" : ", in today's prices")
    // "buys more" is a claim about prices, so only the inflation-adjusted line makes it.
    + (nominal || noInfl || !gap ? ". Higher = a stronger rate for you" : ". Higher = your money buys more")
    + ". Backward-looking on purpose: exchange rates aren't seasonal, "
    + "so this says whether now is favourable — not which month to pick.";
  // "past 12 months: +0.1% vs its 1-yr average" read as a year's move and
  // named the period twice; the number is today's rate against the 12-month
  // average. "after inflation" is said on the line, as Top Picks says it —
  // it was only in the ⓘ. One decimal everywhere (-1.0%, not "-1%" beside
  // "+4.8%"). No verdict on a nominal line: that is a claim about prices.
  const basis = noInfl ? " (exchange rate only)"
    : nominal ? " (nominal — inflation data isn't current)"
    : gap ? ", after inflation" : " (exchange rate only)";
  host.innerHTML = `<span class="fxhead">💱 <b>Your ${esc(base)} in ${esc(cn)}</b>: `
    + `<b style="color:${col}">${signedPct(pct, 1)}</b> vs its 12-month average${basis}`
    + (noInfl || nominal || !gap ? "" : ` <span class="muted">— ${verdict}</span>`)
    + `<span class="fxinfo" data-tip="${esc(tip)}" title="">ⓘ</span></span>`
    + `<svg class="fxspark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">`
    + `<line x1="${P}" y1="${y(avg).toFixed(1)}" x2="${W - P}" y2="${y(avg).toFixed(1)}" class="fxavg"/>`
    + `<path d="${path}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>`
    + `<circle cx="${x(pts.length - 1).toFixed(1)}" cy="${y(pts[pts.length - 1]).toFixed(1)}" r="3" fill="${col}"/></svg>`;
  host.hidden = false;
}

// ---- Local price level -------------------------------------------------------
// The one number the share card and the AI prompt both assert, said on the
// page in the same words — a decision engine must not export a figure its own
// page never shows. Against the traveller's home; the US only as a fallback,
// and then the line says so.
function localPricesText(iso) {
  const A = plAnchor(originIso());
  const plIso = GUIDE_PARENT[iso] || iso;       // England etc: the UK's figure
  const pl = priceLevel(plIso);
  if (!pl) return null;
  return "≈ " + Math.round(100 * pl / A.pl) + "% of " + A.name
    + (A.home ? "" : " (no figure for " + countryName(originIso()) + ")")
    + (plIso !== iso ? " (" + parentWide(plIso) + " figure)" : "");
}
async function renderGuideCost(iso) {
  const host = $("guideCost");
  if (!host) return;
  host.hidden = true;
  await ensurePPP().catch(() => {});
  if (ccGuideIso !== iso) return;
  // The reader's own country: "≈ 100% of the US" tells them nothing.
  if ((GUIDE_PARENT[iso] || iso) === originIso()) return;
  const line = localPricesText(iso);
  if (!line) {
    // Live rates or ppp.json didn't load: the dated snapshot the title and
    // snippet were written from (render_guide's SSR line, word for word), so
    // the page still shows what its description claims. Never when live data
    // loaded and found no honest figure.
    if (ppp && lastRates) return;
    const f = await ensureGuideFacts().then((d) => d[iso]).catch(() => null);
    if (ccGuideIso !== iso || !f || f.pct == null || !guideFactsFresh()) return;
    const when = guideFactsMonth();
    host.innerHTML = `💰 <b>Local prices ≈ ${f.pct}% of the US (${esc(
      f.plof ? parentWide(f.plof) + " figure, " + when : when)})</b><span class="fxinfo" data-tip="${esc(
      "World Bank price level for residents, carried to the " + when + " exchange rate (live rates"
      + " didn't load) — what a local basket costs here against the same basket in the US. National"
      + " averages: tourist areas and foreigner rent run well above this.")}" title="">ⓘ</span>`;
    host.hidden = false;
    return;
  }
  host.innerHTML = `💰 <b>Local prices ${esc(line)}</b><span class="fxinfo" data-tip="${esc(
    "World Bank price level for residents, carried to today's exchange rate — what a local basket"
    + " costs here against the same basket at home. National averages: tourist areas and"
    + " foreigner rent run well above this.")}" title="">ⓘ</span>`;
  host.hidden = false;
}

// ---- Travel Guide: "Where to stay" Stay22 map -------------------------------
// A live hotel/hostel/rental price map anchored at the country's top attraction
// (coordinates pulled from each curated gallery's #1 sight, in stay-coords.json),
// pre-set to the reader's chosen travel month so prices are real. aid=wandergrade
// routes any booking to our Stay22 account. FTC disclosure shown below the map
// and in the footer.
const STAY22_AID = "wandergrade";
let _stayCoords = null;
function ensureStayCoords() {
  if (_stayCoords) return Promise.resolve(_stayCoords);
  return getJSON("/stay-coords.json").then((c) => (_stayCoords = c));
}
// Concrete check-in window from the selected travel month: the 15th of that
// month (this year if still ahead, else next year) for a 3-night stay.
function stayDates() {
  const vm = parseInt(($("valueMonth") || {}).value, 10);
  const month = (vm >= 1 && vm <= 12) ? vm : (lastPicksMonth || curMonth());
  const now = new Date();
  let y = now.getFullYear();
  if (month < now.getMonth() + 1) y++;
  let ci = new Date(y, month - 1, 15);
  // The current month's 15th may already be behind us (mid-month, this built
  // Booking/Stay22 deep links with a check-in in the past — a dead search).
  // Floor at three days out; the soonest realistic booking.
  const floor = new Date(now); floor.setDate(floor.getDate() + 3);
  if (ci < floor) ci = floor;
  const co = new Date(ci); co.setDate(co.getDate() + 3);
  const f = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
                   "-" + String(d.getDate()).padStart(2, "0");
  return { checkin: f(ci), checkout: f(co) };
}
// Hostelworld country listings, /hostels/<continent>/<slug>/. Their search route
// (/search?search_keywords=) 404s for every query, and the stay spots are
// landmarks ("Mount Fuji"), not Hostelworld cities, so link the country. Slugs
// from Hostelworld's sitemap, sample-checked 200 in 2026-09 (England stands in
// for the UK; DR Congo, Congo, Falklands and South Sudan have no page). The
// newer guides' slugs were each checked 200 with a desktop UA: England,
// Scotland and Wales have their own pages, and Hostelworld files Guernsey,
// Jersey and the Isle of Man under England.
// Anything unlisted gets the homepage rather than a guessed URL.
const HW_COUNTRY = (() => {
  const m = {};
  const add = (cont, list) => list.split(" ").forEach((p) => {
    const [iso, slug] = p.split(":");
    m[iso] = cont + "/" + slug;
  });
  add("europe", "AD:andorra AL:albania AM:armenia AT:austria BA:bosnia-and-herzegovina BE:belgium " +
    "BG:bulgaria BY:belarus CH:switzerland CY:cyprus CZ:czech-republic DE:germany " +
    "DK:denmark EE:estonia ES:spain FI:finland FR:france GB:england GE:georgia " +
    "GI:gibraltar GL:greenland GR:greece HR:croatia HU:hungary IE:ireland IS:iceland " +
    "IT:italy LI:liechtenstein LT:lithuania LU:luxembourg LV:latvia MD:moldova " +
    "ME:montenegro MK:north-macedonia MT:malta NL:netherlands NO:norway PL:poland " +
    "PT:portugal RO:romania RS:serbia RU:russia SE:sweden SI:slovenia SK:slovakia " +
    "TR:turkey UA:ukraine XK:kosovo GB-ENG:england GB-SCT:scotland GB-WLS:wales " +
    "FO:faroe-islands GG:england/guernsey JE:england/jersey IM:england/isle-of-man");
  add("asia", "AE:united-arab-emirates AF:afghanistan AZ:azerbaijan BD:bangladesh BN:brunei " +
    "BT:bhutan CN:china HK:hong-kong-china ID:indonesia IL:israel IN:india IQ:iraq " +
    "IR:iran JO:jordan JP:japan KG:kyrgyzstan KH:cambodia KP:north-korea KR:south-korea " +
    "KW:kuwait KZ:kazakhstan LA:laos LB:lebanon LK:sri-lanka MM:myanmar MN:mongolia " +
    "MV:maldives MY:malaysia NP:nepal OM:oman PH:philippines PK:pakistan PS:palestine " +
    "QA:qatar SA:saudi-arabia SG:singapore SY:syria TH:thailand TJ:tajikistan " +
    "TM:turkmenistan TW:taiwan-china UZ:uzbekistan VN:vietnam YE:yemen BH:bahrain");
  add("africa", "AO:angola BF:burkina-faso BI:burundi BJ:benin BW:botswana " +
    "CF:central-african-republic CI:cote-d-ivoire CM:cameroon CV:cape-verde DJ:djibouti " +
    "DZ:algeria EG:egypt EH:western-sahara ER:eritrea ET:ethiopia GA:gabon GH:ghana " +
    "GM:gambia GN:guinea GQ:equatorial-guinea GW:guinea-bissau KE:kenya LR:liberia " +
    "LS:lesotho LY:libyan-arab-jamahiriya MA:morocco MG:madagascar ML:mali MR:mauritania " +
    "MU:mauritius MW:malawi MZ:mozambique NA:namibia NE:niger NG:nigeria RE:reunion " +
    "RW:rwanda SD:sudan SL:sierra-leone SN:senegal SO:somalia ST:sao-tome-and-principe " +
    "SZ:swaziland TD:chad TG:togo TN:tunisia TZ:tanzania UG:uganda ZA:south-africa " +
    "ZM:zambia ZW:zimbabwe");
  add("north-america", "BB:barbados BS:bahamas BZ:belize CA:canada CR:costa-rica CU:cuba " +
    "DO:dominican-republic GP:guadeloupe GT:guatemala HN:honduras HT:haiti JM:jamaica " +
    "MX:mexico NI:nicaragua PA:panama SV:el-salvador TT:trinidad-and-tobago US:usa " +
    "VI:us-virgin-islands");
  add("south-america", "AR:argentina AW:aruba BO:bolivia BR:brazil CL:chile CO:colombia " +
    "EC:ecuador GY:guyana MQ:martinique PE:peru PR:puerto-rico PY:paraguay SR:suriname " +
    "UY:uruguay VE:venezuela CW:netherlands-antilles/curacao");
  add("oceania", "AU:australia CK:cook-islands FJ:fiji NC:new-caledonia NZ:new-zealand " +
    "PF:french-polynesia PG:papua-new-guinea SB:solomon-islands TL:east-timor VU:vanuatu " +
    "WS:samoa GU:guam");
  return m;
})();
function hostelworldURL(iso) {
  return HW_COUNTRY[iso] ? "https://www.hostelworld.com/hostels/" + HW_COUNTRY[iso] + "/"
                         : "https://www.hostelworld.com/";
}
let _staySpotIdx = 0, _staySpotIso = null;   // chip selection, reset per country
function renderGuideStay(iso) {
  const host = $("guideStay");
  if (!host) return;
  // Emptied, not hidden, until the spots load (the visa line's rule): empty
  // it keeps its held height (styles.css). Hidden, the stays column beside
  // the advisory collapsed to the insurance line and the weather chart under
  // both rode up 135px and back down when the stays came (1280).
  holdSizer(host, iso);
  host.innerHTML = ""; host.hidden = false;
  const none = () => { if (ccGuideIso === iso) { host.hidden = true; host.style.minHeight = ""; } };
  Promise.all([ensureStayCoords(), ensureAdvisories().catch(() => null)]).then(([cc]) => {
    if (ccGuideIso !== iso) return;                    // user switched country
    if (guideAdvLevel(iso) === 4) return none();       // no bookings under "do not travel"
    // Spots = the country's top places (from the curated gallery), each a
    // stay-search anchor. Tolerate the old single-anchor shape from cache.
    let spots = cc[iso];
    if (!spots) return none();
    if (!Array.isArray(spots)) spots = [{ n: spots.near, ll: spots.ll }];
    spots = spots.filter((s) => s && s.ll && s.n);
    if (!spots.length) return none();
    if (_staySpotIso !== iso) { _staySpotIso = iso; _staySpotIdx = 0; }
    if (_staySpotIdx >= spots.length) _staySpotIdx = 0;
    const sp = spots[_staySpotIdx];
    const { checkin, checkout } = stayDates();
    // Allez deep links land users in Booking's own UI at the chosen spot with
    // the traveler's month — earning through aid=wandergrade. Hostelworld is a
    // plain link until the Partnerize camref arrives. Footer disclosure covers
    // the affiliate relationship.
    const q = "aid=" + STAY22_AID + "&lat=" + sp.ll[0] + "&lng=" + sp.ll[1] +
              "&checkin=" + checkin + "&checkout=" + checkout;
    const hw = hostelworldURL(iso);
    const btn = (href, label, sponsored) =>
      '<a class="staybtn" target="_blank" rel="' + (sponsored ? "sponsored nofollow noopener" : "nofollow noopener") +
      '" href="' + href + '">' + label + ' <span class="ext">↗</span></a>';
    const chips = spots.length > 1
      ? '<div class="staychips">' + spots.map((s, i) =>
          '<button type="button" class="staychip' + (i === _staySpotIdx ? " active" : "") +
          '" aria-pressed="' + (i === _staySpotIdx) + '" data-si="' + i + '">📍 ' + esc(s.n) + "</button>").join("") + "</div>"
      : "";
    host.innerHTML =
      '<h3 class="staytitle">🏨 Where to stay <span class="staynear">near ' + esc(sp.n) + "</span></h3>" +
      chips +
      '<div class="staybtns">' +
        btn("https://www.stay22.com/allez/booking?" + q, "🏨 Booking.com", true) +
        btn(hw, "🎒 Hostelworld", false) +
      "</div>";
    host.querySelectorAll(".staychip").forEach((b) => b.addEventListener("click", () => {
      _staySpotIdx = parseInt(b.dataset.si, 10) || 0;
      renderGuideStay(iso);
    }));
    host.hidden = false; host.style.minHeight = "";
  }).catch(() => { if (!host.firstChild) none(); });
}

// Passport used for visa info = the traveller's home ("From") country.
function guidePassport() { return originIso(); }

// The passport as an adjective — "German passport", not "Germany passport".
// Every origin the From picker offers, plus common others; anything else
// reads "passport of <country>", clumsy but never wrong. "US" stays: "American passport" is not what its holders
// say on a form.
const DEMONYM = { US: "US", GB: "British", DE: "German", FR: "French", CA: "Canadian",
  AU: "Australian", NZ: "New Zealand", IN: "Indian", IT: "Italian", ES: "Spanish", PT: "Portuguese",
  NL: "Dutch", BE: "Belgian", CH: "Swiss", AT: "Austrian", IE: "Irish", SE: "Swedish", NO: "Norwegian",
  DK: "Danish", FI: "Finnish", PL: "Polish", CZ: "Czech", GR: "Greek", TR: "Turkish", IL: "Israeli",
  JP: "Japanese", KR: "South Korean", CN: "Chinese", TW: "Taiwanese", HK: "Hong Kong", SG: "Singaporean",
  MY: "Malaysian", TH: "Thai", PH: "Filipino", ID: "Indonesian", VN: "Vietnamese", AE: "Emirati",
  SA: "Saudi", ZA: "South African", NG: "Nigerian", KE: "Kenyan", EG: "Egyptian", MA: "Moroccan",
  BR: "Brazilian", AR: "Argentine", CL: "Chilean", CO: "Colombian", PE: "Peruvian", MX: "Mexican",
  RU: "Russian", UA: "Ukrainian", RO: "Romanian", HU: "Hungarian", PK: "Pakistani", BD: "Bangladeshi",
  IS: "Icelandic", LK: "Sri Lankan", KH: "Cambodian", CR: "Costa Rican", DO: "Dominican", PA: "Panamanian",
  GH: "Ghanaian", QA: "Qatari" };
function passportLabel(passport) {
  return DEMONYM[passport] ? DEMONYM[passport] + " passport" : "passport of " + countryName(passport);
}

// Visa FYI for this country — informational only, not part of any score.
// US passports link to the official State Dept page; other passports use the
// Passport Index matrix (loaded lazily on first use). German and Canadian
// passports link their own government's destination page — the advisory
// feeds carry it per country, and it covers entry rules.
function renderGuideVisa(iso) {
  const host = $("guideVisa");
  if (!host) return;
  const passport = guidePassport();
  if (passport !== "US" && !visaMatrix) {       // need the matrix; load then redraw
    // Empty, not hidden, while it loads: empty it keeps the height styles.css
    // holds for it (or the served stand-in's, holdSizer), where hiding it
    // collapsed the line and the guide under it jumped twice. Hidden only if
    // the matrix never comes.
    holdSizer(host, iso);
    host.innerHTML = ""; host.hidden = false;
    ensureVisaMatrix().then(() => { if (ccGuideIso === iso) renderGuideVisa(iso); })
      .catch(() => { if (ccGuideIso === iso && !host.firstChild) { host.hidden = true; host.style.minHeight = ""; } });
    return;
  }
  host.style.minHeight = "";
  const info = visaInfo(iso, passport);
  if (info && info.home) {
    host.hidden = false;
    host.innerHTML = `<span class="visa vfree">🛂 Home</span>
      <span class="guidevisa-txt">Your home country — no visa needed.</span>`;
    return;
  }
  if (!info) { host.hidden = true; return; }
  host.hidden = false;
  const detail = info.meta.long + (info.note ? " · " + info.note : "");
  let href = /^https:\/\/travel\.state\.gov\//.test(info.link) ? info.link : "";
  if (!href && (passport === "DE" || passport === "CA")) {
    const src = passport.toLowerCase();
    const viso = GUIDE_PARENT[iso] || ADV_PARENT[iso] || iso;
    const it = ((_advBySource[src] || {}).items || []).find((x) => x.iso === viso && !x.via);
    if (it && /^https:\/\/(www\.)?(auswaertiges-amt\.de|travel\.gc\.ca)\//.test(it.link || "")) href = it.link;
    // Not loaded yet (the safety row fetches the CHOSEN source, which need not
    // be this passport's): fetch it once and redraw, like the matrix above.
    else if (!_advBySource[src]) fetchAdv(src).then(() => {
      if (ccGuideIso === iso) renderGuideVisa(iso);
    }).catch(() => {});
  }
  const link = href ? ` <a href="${esc(href)}" target="_blank" rel="noopener">official details ↗</a>` : "";
  const checked = visaVerified(passport);
  // Non-US passports read the Passport Index matrix; the US table is checked
  // against the State Dept pages it links. Credit the source either way.
  const via = passport === "US" ? "" : " (Passport Index)";
  const asOf = checked ? ` Checked ${esc(checked)}${via}; verify before booking — rules change.`
                       : ` Verify before booking${via} — rules change.`;
  host.innerHTML = `<span class="visa ${info.meta.cls}">🛂 ${esc(info.meta.label)}</span>
    <span class="guidevisa-txt"><b>Visa · ${esc(passportLabel(passport))}:</b> ${esc(detail)}.${link}
    ${asOf}</span>`;
}

// Safety advisory for this country, from the traveler's home-country source
// (US State Dept by default, German Foreign Office for German travelers). Named
// so readers know whose guidance it is — advisories are politically colored.
// Each government's own words for its four levels. Canada's Level 3 is
// "avoid non-essential travel", not the US's "reconsider travel" — yet with
// Canada picked the level filter, the ⓘ, the legend and this badge all spoke
// US (the filter's "L3 — Reconsider travel" listed 17 of Canada's "Avoid
// non-essential travel"). Germany doesn't grade: its words are DE_LVL_LABEL.
const ADV_LVL_WORDS = {
  us: ["Normal precautions", "Increased caution", "Reconsider travel", "Do not travel"],
  ca: ["Normal security precautions", "High degree of caution", "Avoid non-essential travel", "Avoid all travel"],
};
// Whose call an item is: a gap-fill's is the government it came from.
const advSrcOf = (it) => (it && it.via) || (advisories && advisories.source) || "us";
// An item's level in the words of the government that set it.
function advLvlWords(it) {
  const s = advSrcOf(it), l = advLvl(it);
  return s === "de" ? DE_LVL_LABEL[l] || "" : (ADV_LVL_WORDS[s] || ADV_LVL_WORDS.us)[l - 1] || "";
}
// A level inside a sentence: "Level 3", or Germany's own call, quoted.
const advLvlName = (it) => (advSrcOf(it) === "de" ? "“" + advLvlWords(it) + "”" : "Level " + advLvl(it));
// The date of an advisory's latest move: when WanderGrade's own record first
// saw the current level (`changed`, the server's), else the feed's date. The
// feeds' "updated" moves with every reissue — and only the US's says which
// way the level went — so Canada's and Germany's moves only show at all
// because the server keeps that record.
const advChangedOn = (it) => (it && (it.changed || it.updated)) || "";
// England, Scotland, Wales and the Crown Dependencies have guides of their own,
// but every government we follow rates the United Kingdom as a whole (and the
// Faroes under Denmark). The guide shows the parent's level and says so;
// scoring never sees these ISOs, so nothing is ranked on it.
const ADV_PARENT = { ...GUIDE_PARENT, GG: "GB", IM: "GB", JE: "GB", FO: "DK" };
// The level the reader's chosen source gives a guide's country (a territory
// reads its parent's, as the badge does); 0 unrated, null while loading.
function guideAdvLevel(iso) {
  if (!advisories) return null;
  const meta = advisoryMetaByIso();
  const parent = !meta[iso] && ADV_PARENT[iso] && meta[ADV_PARENT[iso]] ? ADV_PARENT[iso] : null;
  const it = meta[iso] || (parent && meta[parent]);
  return it ? it.level : 0;
}
// A guide block about to be emptied and refilled for the country it already
// shows — the server's invisible stand-in for it (.gsizer, fxtracker/
// guide_sizers.py: the block as it will read, wrapped by the browser at this
// width), or its own content drawn before (a new From, a new source) — keeps
// that height as its min-height until the caller has filled it and lets go.
// Another country's block starts from the stylesheet's per-level height.
function holdSizer(host, iso) {
  const sz = host.querySelector(".gsizer");
  const mine = sz ? sz.dataset.for === iso : host.dataset.for === iso;
  host.style.minHeight = mine && host.offsetHeight ? host.offsetHeight + "px" : "";
  host.dataset.for = iso;
}
function renderGuideSafety(iso) {
  const host = $("guideSafety");
  if (!host) return;
  // Emptied, not hidden, while the advisories load (the visa line's rule):
  // empty it keeps its held height, and the line only goes when there is
  // nothing to say. The block then fills in three steps — the level and its
  // sentence, then Canada's safety notes and the health line, each its own
  // fetch — so .filling keeps that height until the last has landed: the
  // first step alone is ~70px, and the guide under it rode up 100px and back
  // down a frame later (768 and phones).
  holdSizer(host, iso);
  host.innerHTML = ""; host.hidden = false; host.classList.add("filling");
  const done = () => { if (ccGuideIso === iso) { host.classList.remove("filling"); host.style.minHeight = ""; } };
  ensureAdvisories().then(() => {
    if (ccGuideIso !== iso) return;
    const meta = advisoryMetaByIso();
    const parent = !meta[iso] && ADV_PARENT[iso] && meta[ADV_PARENT[iso]] ? ADV_PARENT[iso] : null;
    const it = meta[iso] || (parent && meta[parent]);
    if (!it) { host.hidden = true; done(); return; }
    const lvl = it.level;
    const src = (it.via_name || advSrcName()) + (parent ? " (" + countryName(parent) + " advisory)" : "");
    const url = it.link || advisories.source_url || "#";
    // The government's own sentences on WHY, when the feed carries them — a
    // level number is black and white; "some areas have increased risk" is the
    // nuance that actually shapes an itinerary. Quoted, never paraphrased:
    // this site does not author safety claims.
    const why = it.summary
      ? ` <span class="advwhy">“${esc(it.summary)}”</span>` : "";
    // The same moved-recently signal the Safety tab shows, on the one page
    // where a single country's trajectory matters. Sources publish only the
    // CURRENT advisory, so the latest move is all the history that exists.
    let moved = "";
    const on = advChangedOn(it);
    if (it.change && on && on >= advMoveCutoff()) {
      const when = fmtDayShort(on);
      moved = ` <span class="advmoved ${it.change === "up" ? "chup" : "chdown"}" data-tip="${
        esc(src + (it.change === "up" ? " raised" : " lowered")
        + " this advisory to " + advLvlName(it) + " on " + when
        + " — recently " + (it.change === "up" ? "riskier" : "safer") + " in their judgement.")}" title="">${
        it.change === "up" ? "▲ raised" : "▼ lowered"} ${esc(when)}</span>`;
    }
    // The level in its own government's words; Germany's calls are words
    // alone, and its "No warning" is neutral, not the green of a grade (as on
    // the Safety map).
    const deCall = advSrcOf(it) === "de";
    const badge = (deCall ? "" : "Level " + lvl + " · ") + (advLvlWords(it) || "");
    const badgeCls = deCall && lvl === 1 ? "nowarn" : "advlvl" + lvl;
    host.hidden = false;
    host.innerHTML = `<span class="advbadge ${badgeCls}">🛡️ ${esc(badge.replace(/ · $/, ""))}</span>${moved}
      <span class="guidevisa-txt"><b>Safety · per ${esc(src)}:</b>${why}
      <span class="advlinks"><a href="${esc(url)}" target="_blank" rel="noopener">full advisory ↗</a> · <button type="button" class="linkbtn advsrcjump">switch source (US · CA · DE) → Safety tab</button></span>
      <span id="guideWatchouts"></span></span>`;
    const jump = host.querySelector(".advsrcjump");
    if (jump) jump.onclick = async (e) => {
      e.preventDefault();
      await activateTab("data", true);
      setDataMode("advisory");
    };
    // The health line goes under the notes, so it waits for them: painted
    // first, it was pushed down 48-84px when they arrived.
    Promise.resolve(renderWatchouts(iso)).then(() => renderGuideHealth(iso)).catch(() => {}).then(done);
  }, () => renderGuideSafetySnapshot(iso).then(() => { if (ccGuideIso === iso && !host.firstChild) host.hidden = true; done(); }))
    .catch(() => { if (ccGuideIso === iso && !host.firstChild) host.hidden = true; done(); });
}
// Advisories didn't load: the dated badge the snippet and SSR state (the US
// State Dept's level, or whoever filled its gap), attributed and dated, so
// the page never silently drops what its description claims.
function renderGuideSafetySnapshot(iso) {
  // The snapshot is the US State Dept's view (gaps filled as its feed fills
  // them); a reader who picked Canada or Germany asked for another government.
  // Settles either way (renderGuideSafety then releases the block's held
  // height, or hides it when nothing was drawn).
  if (advisorySource() !== "us") return Promise.resolve();
  return ensureGuideFacts().then((d) => {
    const host = $("guideSafety"), f = d[iso];
    if (ccGuideIso !== iso || !host || !f || !f.adv || !guideFactsFresh()) return;
    const de = f.src === "de";
    const words = de ? DE_LVL_LABEL[f.adv] || "" : (ADV_LVL_WORDS[f.src] || ADV_LVL_WORDS.us)[f.adv - 1] || "";
    const badge = de ? words : "Level " + f.adv + " · " + words;
    const when = guideFactsMonth();
    host.innerHTML = `<span class="advbadge ${de && f.adv === 1 ? "nowarn" : "advlvl" + f.adv}">🛡️ ${esc(badge)}</span>
      <span class="guidevisa-txt"><b>Safety · per ${esc(ADV_SRC_SHORT[f.src] || ADV_SRC_SHORT.us)} (${esc(
        f.advof ? countryName(f.advof) + " advisory, " + when : when)})</b></span>`;
    host.hidden = false;
  }).catch(() => {});
}
// Under the advisory: the diseases Canada's travel health advice calls a risk
// there (the Safety table's Health column), the rest in the tip. Only a
// country's own entry, or for England, Scotland and Wales the UK's (the
// advisory above is the UK's too) — never a territory's parent, whose
// climate can be another world (French Guiana is not France).
function renderGuideHealth(iso) {
  return ensureHealth().then(() => {
    const host = $("guideSafety");
    if (ccGuideIso !== iso || !host || host.hidden) return;
    const parent = !healthOf(iso) && GUIDE_PARENT[iso] ? GUIDE_PARENT[iso] : null;
    const hz = healthOf(parent || iso);
    const wn = wnText(parent || iso);
    let el = host.querySelector(".guidehealth");
    if (!hz) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement("div"); el.className = "guidehealth"; host.appendChild(el); }
    const link = hz.s ? ` <a href="https://travel.gc.ca/destinations/${encodeURIComponent(hz.s)}#health" target="_blank" rel="noopener">health advice ↗</a>` : "";
    const tip = healthTip(hz) + " " + wnCaveat(!!wn);
    // West Nile after Canada's part, with its own credit: this line is
    // headed "per the Government of Canada", and the virus isn't in its
    // advice (the table's cell is headed "Health" alone, so it rides there
    // with the rest). The credit is the one agency's that reported it, linked
    // to its own page, and the ⓘ carries the credit its data asks for.
    const wby = wn ? wnAgency(parent || iso) : "", ws = WN_SRC[wby];
    const wnPart = !wn ? "" : ` <span class="hzwrap">${chipHTML(WN_CHIP)}</span> `
      + (ws ? `<a href="${esc(ws.url())}" target="_blank" rel="noopener">per ${esc(wby)}${wnYear(parent || iso) ? ", " + esc(wnYear(parent || iso)) : ""} ↗</a>` : `per ${esc(wby)}`)
      + ` <span class="muted" data-tip="${esc(wn + (ws ? " " + wnCredit(wby) : ""))}" title="">ⓘ</span>`;
    el.innerHTML = `<b><span aria-hidden="true">💉 </span>Health · per the Government of Canada${parent ? " (" + esc(countryName(parent)) + ")" : ""}:</b> `
      + (hz.h.length ? `<span class="hzwrap">${healthChipsHTML(hz)}</span> <span class="muted" data-tip="${esc(tip)}" title="">ⓘ</span>`
        : `<span class="muted" data-tip="${esc(tip)}" title="">${HEALTH_USUAL} ⓘ</span>`)
      + link + wnPart;
  });
}

// Specific watchouts, lifted verbatim from Global Affairs Canada's structured
// advisory pages (topic heading + their first sentence — hover a chip to read
// it). Canada is the one government that publishes this text as data; the
// LEVEL above still follows the traveler's own government, and both are named
// so nobody mistakes whose words are whose. Nothing here is paraphrased.
const _watchoutCache = {};
// One builder for the full watchouts block (chips + regional lines) so the
// guide and the safety table can't drift apart in how they render the same data.
function watchoutsBlockHTML(w) {
  const chips = w.watchouts.map((x) =>
    '<span class="wochip"' + (x.d ? ' data-tip="' + esc(x.d) + '" title=""' : "") + ">"
    + esc(x.t) + "</span>").join("");
  const reg = (w.regional || []).map((r) => {
    const head = (r.t || "").split(" - ").pop();
    const list = r.regions && r.regions.length
      ? ": " + r.regions.slice(0, 10).join(", ")
        + (r.regions.length > 10 ? " +" + (r.regions.length - 10) + " more" : "")
      : (r.lead ? ": " + r.lead : "");
    const starred = r.regions && r.regions.some((x) => /\*$/.test(x));
    return '<span class="woreg">📍 <b>' + esc(head) + "</b>" + esc(list)
      + (starred ? ' <span class="muted">(* parts excepted — see details)</span>' : "")
      + "</span>";
  }).join("");
  return { chips: '<span class="wochips">' + chips + "</span>", reg };
}
function renderWatchouts(iso) {
  const paint = (w) => {
    const host = $("guideWatchouts");
    if (!host || ccGuideIso !== iso) return;
    if (!w || (!w.watchouts.length && !w.regional.length)) return;
    // Proportionate display (the owner's call, and right): eight topic chips
    // under a Level 1 country read as a warning wall — Japan looked dangerous
    // because Canada writes thorough pages about safe places. At L1/L2 the
    // chips live in a collapsed fold; the loud treatment is reserved for
    // countries whose own government is loud (L3+), and regional
    // avoid-travel lines always show — they only exist when real.
    const lvl = (advisoryMetaByIso()[iso] || {}).level || 0;
    const calm = lvl > 0 && lvl <= 2;
    const built = watchoutsBlockHTML(w);
    const chips = built.chips;
    // Structured regional advisories: "Avoid all travel: Narathiwat, Pattani,
    // Yala..." — the named places a flat Level number hides. A star on a name
    // means the source lists exceptions for it; they live on the linked page.
    const reg = built.reg;
    const srcNote = '<span class="muted">(per ' + esc(w.source)
      + (w.link ? ' — <a href="' + esc(w.link) + '" target="_blank" rel="noopener">details ↗</a>' : "") + ")</span>";
    // A button, not <a href="#">: it performs a tab switch (button semantics),
    // and a dead-hash link scrolls to top if the handler ever fails to bind.
    const tabLink = ' <button type="button" class="linkbtn wotab">full picture → Safety tab</button>';
    // chips already arrives wrapped in .wochips — wrapping again indented the
    // chip row differently from every other line in the block.
    host.innerHTML = calm
      ? reg + '<details class="wofold"><summary>🧭 Safety notes ('
        + w.watchouts.length + ") — nothing unusual for a Level " + lvl
        + " country " + srcNote + "</summary>" + chips + "</details>"
      : '<span class="wohead">Safety notes ' + srcNote + "</span>"
        + chips + reg
        + '<span class="advsrcnote">' + tabLink.trim() + "</span>";
    const wt = host.querySelector(".wotab");
    if (wt) wt.onclick = async (e) => {
      e.preventDefault();
      await activateTab("data", true);
      setDataMode("advisory");
    };
  };
  if (_watchoutCache[iso]) { paint(_watchoutCache[iso]); return; }
  return getJSON("/api/watchouts?iso=" + encodeURIComponent(iso))   // settles when painted (renderGuideSafety waits)
    .then((w) => { _watchoutCache[iso] = w; paint(w); })
    .catch(() => {});
}

// A full-width photo carousel at the top of the guide: one scenic shot at a
// time with left/right arrows, to get the country's vibe before the data.
let heroUrls = [], heroIdx = 0, _heroTimer = null;
function renderGuideHero(iso) {
  const host = $("guideHero");
  if (!host) return;
  ccGuideIso = iso;
  host.className = "guidehero loading";
  host.innerHTML = "";
  // Debounce the Commons fetches: when the user clicks through countries fast,
  // only the one they settle on fires a request (avoids rate-limiting). Cached
  // countries still feel instant since the fetch resolves from cache.
  clearTimeout(_heroTimer);
  _heroTimer = setTimeout(() => { if (ccGuideIso === iso) loadHeroPhotos(iso); }, 220);
}
// Iconic photos for the guide hero. We resolve a few curated/derived landmark
// SUBJECTS to each subject's Wikipedia lead image, served crisp + landscape-
// cropped via the weserv proxy. This replaced a generic Commons text search
// that surfaced junk (e.g. Buenos Aires "Comuna" street-name signs) and low-res
// montage leads. A country can hand-pick its shots via activities[iso].gallery;
// otherwise subjects are the curated `photo` + the place in each activity label.
function photoSubjects(iso) {
  const a = activities && activities[iso];
  if (a && Array.isArray(a.gallery) && a.gallery.length) return a.gallery.slice(0, 6);
  const subs = [];
  if (a && a.photo) subs.push(a.photo);
  for (const x of (a && a.activities) || []) {
    const label = typeof x === "string" ? x : x.t;
    const m = label.match(/\(([^),]+)/);   // first place inside the parens
    subs.push(m ? m[1].trim() : label.replace(/\s*\([^)]*\)/g, "").trim());
  }
  return [...new Set(subs.filter(Boolean))].slice(0, 6);
}
async function wikiIconic(subject, minW, minH) {
  // Wikimedia's pageimages API renders a crisp thumbnail server-side and is
  // reliable (CORS-enabled, no proxy/rate-limit). thumbnail = the hero/carousel
  // size (CSS object-fit:cover crops it); original = full-res for the lightbox.
  // Two-tier quality gate. The hero renders as a wide strip, so WIDTH is the
  // binding constraint: default requires >=800px wide (or a genuinely tall
  // >=1000px portrait) — Angola's 620x594 Kissama shot was visibly soft.
  // 84px activity thumbs pass a lower bar (700x500, via actPhoto).
  if (minW === undefined) minW = 800;
  if (minH === undefined) minH = 1000;
  try {
    const api = "https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*" +
      "&prop=pageimages&piprop=thumbnail|original|name&pithumbsize=1600&redirects=1&titles=" +
      encodeURIComponent(subject);
    const r = await fetch(api);
    if (!r.ok) return null;
    const j = await r.json();
    const page = j.query && j.query.pages && Object.values(j.query.pages)[0];
    const t = page && page.thumbnail;
    const thumb = t && t.source;
    if (!thumb || PHOTO_BAD.test(thumb)) return null;
    // A small delivered thumb means the source itself is tiny (we asked for
    // 1600px). Reject unless at least one dimension clears its bar.
    if ((t.width || 0) < minW && (t.height || 0) < minH) return null;
    const orig = page.original && page.original.source;
    // file = the File: page name, for the author/licence credit.
    return { thumb, full: (orig && !PHOTO_BAD.test(orig)) ? orig : thumb, file: page.pageimage || "" };
  } catch (e) { return null; }
}

// ---- photo credits -----------------------------------------------------------
// Most of these files are CC BY / BY-SA, which require the author, the licence
// and a link to the source beside the photo; a footer naming the host doesn't
// do it. One imageinfo call per batch (en.wikipedia's API also resolves Commons
// files). _photoCredit[file]: undefined = never asked, null = asking,
// object = known. A failed call forgets its files so the next view retries.
const _photoCredit = {};
function _plainText(html) {
  const d = new DOMParser().parseFromString(String(html || ""), "text/html");
  const t = (d.body.textContent || "").replace(/\s+/g, " ").trim();
  return t.length > 60 ? t.slice(0, 58).trim() + "…" : t;
}
// file -> the in-flight batch asking for it. A caller wanting a file another
// call is already fetching waits on THAT batch: resolving at once left a
// lightbox opened mid-flight on the bare fallback credit until reopened.
const _photoCreditP = {};
function loadPhotoCredits(photos) {
  const files = [...new Set(photos.map((p) => p && p.file).filter(Boolean))];
  const want = files.filter((f) => _photoCredit[f] === undefined);
  const waits = files.filter((f) => _photoCredit[f] === null && _photoCreditP[f]).map((f) => _photoCreditP[f]);
  if (want.length) {
    want.forEach((f) => { _photoCredit[f] = null; });
    const batch = _fetchPhotoCredits(want).finally(() => want.forEach((f) => { delete _photoCreditP[f]; }));
    want.forEach((f) => { _photoCreditP[f] = batch; });
    waits.push(batch);
  }
  return Promise.all(waits).then(() => {});
}
async function _fetchPhotoCredits(want) {
  try {
    const titles = want.map((f) => "File:" + f.replace(/_/g, " "));
    const r = await fetch("https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*"
      + "&prop=imageinfo&iiprop=extmetadata|url&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl"
      + "&titles=" + encodeURIComponent(titles.join("|")));
    if (!r.ok) throw new Error("credits " + r.status);
    const q = (await r.json()).query || {};
    const back = {};
    titles.forEach((t, i) => { back[t] = want[i]; });
    for (const n of q.normalized || []) if (back[n.from]) back[n.to] = back[n.from];
    for (const pg of Object.values(q.pages || {})) {
      const f = back[pg.title], ii = (pg.imageinfo || [])[0];
      if (!f || !ii) continue;
      const md = ii.extmetadata || {}, val = (k) => (md[k] && md[k].value) || "";
      _photoCredit[f] = { artist: _plainText(val("Artist")), lic: _plainText(val("LicenseShortName")),
                          licUrl: val("LicenseUrl"), page: ii.descriptionurl || "" };
    }
  } catch (e) {
    want.forEach((f) => { if (_photoCredit[f] === null) delete _photoCredit[f]; });
  }
}
// "📷 Author · CC BY-SA 4.0": author links to the file page, licence to its
// deed. Before (or without) metadata it still links the file page.
function photoCreditHTML(p) {
  if (!p || !p.file) return "";
  const c = _photoCredit[p.file] || {};
  const safe = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
  const page = safe(c.page) || "https://en.wikipedia.org/wiki/File:" + encodeURIComponent(p.file.replace(/ /g, "_"));
  const lic = c.lic ? (safe(c.licUrl)
    ? ' · <a href="' + esc(c.licUrl) + '" target="_blank" rel="noopener license">' + esc(c.lic) + "</a>"
    : " · " + esc(c.lic)) : "";
  return '📷 <a href="' + esc(page) + '" target="_blank" rel="noopener">'
    + esc(c.artist || "Wikimedia Commons") + "</a>" + lic;
}
const _heroCache = {};
async function iconicPhotos(iso) {
  if (iso in _heroCache) return _heroCache[iso];
  // Arrow, not .map(wikiIconic): map's (index, array) args landed in minW/minH
  // and switched the size gate off.
  const settled = await Promise.all(photoSubjects(iso).map((s) => wikiIconic(s)));
  const out = [], seen = new Set();
  for (const p of settled) if (p && !seen.has(p.full)) { seen.add(p.full); out.push(p); }
  if (out.length) _heroCache[iso] = out;
  return out;
}
// Every activity is a {t: title, d: description} object — the bare-string form is
// legacy tolerance, nothing in activities.json uses it. Anything that prints one
// has to pull the title out: joining the raw objects is how both AI prompts came
// to say "Known for: [object Object]; [object Object]".
function actLabel(x) { return (typeof x === "string" ? x : (x && x.t)) || ""; }

// The photo subject an activity row will use (shared with renderActivity so
// the hero's de-dupe stays in lockstep with what the thumbnails show).
function activitySubject(x) {
  const label = actLabel(x);
  if (typeof x === "object" && x.p) return x.p;
  const pm = label.match(/\(([^),]+)/);
  const subj = (pm ? pm[1] : label.replace(/\s*\([^)]*\)/g, "")).trim();
  // Wikipedia titles spell these out ("Iona NP" -> "Iona National Park").
  return subj.replace(/\bNP\b/, "National Park").replace(/\bMt\b/, "Mount");
}
// File keys of every photo the activity thumbnails will display for this
// country — the hero excludes these so no image appears twice on the page.
async function activityPhotoKeys(iso) {
  const a = activities && activities[iso];
  const country = countryName(iso);
  const keys = new Set();
  await Promise.all(((a && a.activities) || []).map(async (x) => {
    const p = await actPhoto(activitySubject(x), country).catch(() => null);
    if (p && p.full) keys.add(fileKey(p.full));
  }));
  return keys;
}

function loadHeroPhotos(iso) {
  const host = $("guideHero");
  if (!host) return;
  Promise.all([iconicPhotos(iso), activityPhotoKeys(iso)]).then(([photos, used]) => {
    if (ccGuideIso !== iso) return;                 // user moved on
    // De-dupe against the activity thumbnails below; keep the full set if
    // filtering would leave the hero too thin to be worth a carousel.
    const kept = photos.filter((p) => !used.has(fileKey(p.full)));
    if (kept.length >= 2) photos = kept;
    heroUrls = photos.slice(0, 6); heroIdx = 0;
    host.classList.remove("loading");
    if (!heroUrls.length) { host.classList.add("empty"); return; }
    host.classList.add("loaded");
    heroUrls.forEach((p) => { const im = new Image(); im.src = p.thumb; });  // warm cache
    const multi = heroUrls.length > 1;
    host.innerHTML =
      `<img class="heroimg" alt="${esc(countryName(iso))}" title="click to enlarge">` +
      (multi ? '<button class="heronav prev" type="button" aria-label="previous photo">‹</button>' +
               '<button class="heronav next" type="button" aria-label="next photo">›</button>' +
               '<div class="herocount"></div>' : "") +
      '<div class="herocredit"></div>';
    const hero = host.querySelector(".heroimg");
    hero.addEventListener("click", openLightbox);
    // The hero is an interactive control (opens the photo viewer), so it
    // needs a keyboard path too — click-only left it mouse-exclusive.
    hero.tabIndex = 0; hero.setAttribute("role", "button");
    hero.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightbox(); }
    });
    if (multi) {
      host.querySelector(".heronav.prev").addEventListener("click", () => heroStep(-1));
      host.querySelector(".heronav.next").addEventListener("click", () => heroStep(1));
    }
    showHero();
    const shown = heroUrls;
    loadPhotoCredits(shown).then(() => { if (heroUrls === shown) { showHero(); syncLightboxCredit(); } });
  }).catch(() => {});
}
function heroStep(d) {
  if (!heroUrls.length) return;
  heroIdx = (heroIdx + d + heroUrls.length) % heroUrls.length;
  showHero();
  syncLightbox();
}
function showHero() {
  const host = $("guideHero");
  const img = host && host.querySelector(".heroimg");
  if (!img) return;
  img.src = heroUrls[heroIdx].thumb;
  const c = host.querySelector(".herocount");
  if (c) c.textContent = (heroIdx + 1) + " / " + heroUrls.length;
  const cr = host.querySelector(".herocredit");
  if (cr) cr.innerHTML = photoCreditHTML(heroUrls[heroIdx]);
}

// ---- lightbox: click a guide photo to view it full-screen ------------------
function ensureLightbox() {
  let lb = $("lightbox");
  if (lb) return lb;
  lb = document.createElement("div");
  lb.id = "lightbox"; lb.className = "lightbox"; lb.hidden = true;
  lb.setAttribute("role", "dialog");
  lb.setAttribute("aria-modal", "true");
  lb.setAttribute("aria-label", "Photo viewer");
  lb.innerHTML =
    '<button class="lbclose" type="button" aria-label="close">✕</button>' +
    '<button class="lbnav prev" type="button" aria-label="previous">‹</button>' +
    '<img class="lbimg" alt="">' +
    '<button class="lbnav next" type="button" aria-label="next">›</button>' +
    '<div class="lbcount"></div><div class="lbcredit"></div>';
  document.body.appendChild(lb);
  lb.addEventListener("click", (e) => {
    if (e.target === lb || e.target.classList.contains("lbclose")) closeLightbox();
  });
  lb.querySelector(".lbnav.prev").addEventListener("click", (e) => { e.stopPropagation(); heroStep(-1); });
  lb.querySelector(".lbnav.next").addEventListener("click", (e) => { e.stopPropagation(); heroStep(1); });
  return lb;
}
// The control that opened the viewer, so closing it puts keyboard users back
// where they were instead of at the top of the page.
let lbOpener = null;
function lbTakeFocus(lb) {
  const a = document.activeElement;
  if (a && a !== document.body && !lb.contains(a)) lbOpener = a;
  lb.querySelector(".lbclose").focus();   // dialog gets focus; Escape/✕ leave it
}
// The credit for whatever the viewer shows (a single photo or the carousel's).
function syncLightboxCredit() {
  const lb = $("lightbox");
  const cr = lb && !lb.hidden && lb.querySelector(".lbcredit");
  if (cr) cr.innerHTML = photoCreditHTML(lbSingle || heroUrls[heroIdx]);
}
function openLightbox() {
  if (!heroUrls.length) return;
  const lb = ensureLightbox();
  lb.hidden = false;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", lbKey);
  lbTakeFocus(lb);
  syncLightbox();
  // Preload every full-res image now (intent signalled), so clicking through
  // the carousel is instant instead of waiting on each load.
  heroUrls.forEach((p) => { if (p.full && p.full !== p.thumb) { const im = new Image(); im.src = p.full; } });
}
// One-off viewer for a single photo (activity thumbnails) — same lightbox,
// no carousel nav; lbSingle guards the arrow keys from stepping the hero.
let lbSingle = null;
function openLightboxSingle(photo) {
  lbSingle = photo;
  const lb = ensureLightbox();
  lb.hidden = false;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", lbKey);
  const img = lb.querySelector(".lbimg");
  img.src = photo.thumb;
  if (photo.full && photo.full !== photo.thumb) {
    const hi = new Image();
    hi.onload = () => { if (!lb.hidden && lbSingle === photo) img.src = photo.full; };
    hi.src = photo.full;
  }
  lb.querySelector(".lbcount").textContent = "";
  lb.querySelectorAll(".lbnav").forEach((b) => { b.style.display = "none"; });
  lbTakeFocus(lb);
  syncLightboxCredit();
  loadPhotoCredits([photo]).then(() => { if (lbSingle === photo) syncLightboxCredit(); });
}
function closeLightbox() {
  const lb = $("lightbox");
  const wasOpen = lb && !lb.hidden;
  if (lb) lb.hidden = true;
  lbSingle = null;
  document.body.style.overflow = "";
  document.removeEventListener("keydown", lbKey);
  if (wasOpen && lbOpener && lbOpener.isConnected) lbOpener.focus();
  lbOpener = null;
}
function syncLightbox() {
  const lb = $("lightbox");
  if (!lb || lb.hidden) return;
  const img = lb.querySelector(".lbimg");
  const idx = heroIdx, ph = heroUrls[idx];
  img.src = ph.thumb;                              // instant (already cached)
  if (ph.full && ph.full !== ph.thumb) {          // then upgrade to full-res
    const hi = new Image();
    hi.onload = () => { if (!lb.hidden && heroIdx === idx) img.src = ph.full; };
    hi.src = ph.full;
  }
  lb.querySelector(".lbcount").textContent = (idx + 1) + " / " + heroUrls.length;
  const multi = heroUrls.length > 1;
  lb.querySelectorAll(".lbnav").forEach((b) => { b.style.display = multi ? "" : "none"; });
  syncLightboxCredit();
}
function lbKey(e) {
  if (e.key === "Escape") closeLightbox();
  else if (lbSingle) return;                       // single-photo view: no carousel
  else if (e.key === "ArrowLeft") heroStep(-1);
  else if (e.key === "ArrowRight") heroStep(1);
}
let ccGuideIso = null;   // guards against a slow gallery landing after the user switched country

// Filename key for de-duping photos across the two image sources.
const fileKey = (u) => {
  const m = u && u.match(/\/thumb\/[^/]+\/[^/]+\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : u;
};
// Reject non-scenic files (flags, coats of arms, maps, diagrams) by filename.
const PHOTO_BAD = /map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram|\.svg|location|adm[_ ]|administrative|emblem|wikidata|collage|montage/i;
const INTERESTS = ["Beach & islands", "Nature", "City", "Culture", "Adventure", "Food", "Shopping"];
function buildBestPickers(initialIso) {
  const ctry = $("bestCountry");
  // Every country, always: the region/interest narrowing that used to live here
  // duplicated Top Picks' filters with its own state, and this list is a
  // type-to-search combo — the filters were saving a keystroke at the cost of two
  // controls that could disagree with the ones on the main tab.
  const list = Object.keys(climate)
    .map((iso) => ({ iso, name: climate[iso].name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  ctry.innerHTML = list.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("");
  const has = (iso) => !!iso && [...ctry.options].some((o) => o.value === iso);
  // Render ONE country: the one being opened, else Japan. Drawing Afghanistan
  // (first option) and Japan first fired their fare, FX and photo requests on
  // every guide landing, and each render's syncURL rewrote the history entry.
  ctry.value = has(initialIso) ? initialIso : has("JP") ? "JP" : ((ctry.options[0] || {}).value || "");
  ctry.onchange = () => renderGuide(ctry.value);
  enhanceSelect(ctry);
  if (ctry.value) renderGuide(ctry.value);
}

// Open the guide tab focused on a specific country (used by the map detail card).
let _guideTarget = null;   // the country an in-flight openGuideFor is opening
async function openGuideFor(iso, push) {
  const fresh = !loaded.guide;
  _guideTarget = iso;       // the first build renders it, and a push names it
  try { await activateTab("guide", push); }
  finally { if (_guideTarget === iso) _guideTarget = null; }
  const ctry = $("bestCountry");
  if ([...ctry.options].some((o) => o.value === iso)) ctry.value = iso;
  if (ctry._sync) ctry._sync();
  if (!(fresh && ccGuideIso === iso)) renderGuide(iso);   // the build just drew it
  setGuideMeta(iso);
}

// Classify each month into peak / shoulder / off by weather comfort alone,
// relative to the country's own range. No price or crowd data goes in, so no
// label may claim either: Swiss ski season and Brazil's Carnival land in "off".
function seasons(scores) {
  const valid = scores.filter((s) => s != null);
  if (!valid.length) return scores.map(() => "na");
  const mn = Math.min(...valid), mx = Math.max(...valid), rng = (mx - mn) || 1;
  return scores.map((s) => {
    if (s == null) return "na";
    const f = (s - mn) / rng;
    return f >= 0.66 ? "peak" : f <= 0.34 ? "off" : "shoulder";
  });
}
// What each class may say: weather, relative to the country's own year, nothing
// more. Relative matters — Fiji's "least comfy" months still score 80+, and a
// curated best month (Brazil's April) can sit there for non-weather reasons.
const SEASON_WX = { peak: "one of its comfiest months", shoulder: "a middling month",
                    off: "one of its least comfy months", na: "no data" };
// The two places the bare class contradicted the line beside it: a curated
// best month in the bottom third of its own year (Mexico's December scores
// 82/100) is not simply "least comfy", and a comfiest month with a hazard
// (Japan's September typhoons) is not simply "comfiest". Null = no caveat,
// the caller uses SEASON_WX.
function seasonCaveat(seas, isBest, hasHazard) {
  if (hasHazard && seas === "peak") return "comfortable temperatures, but note the heads-up";
  if (isBest && seas === "off") return "a curated best month, though not its comfiest weather";
  return null;
}

// ---- Temperature units ------------------------------------------------------
// Default to °C (what most of the world uses); only US-style home countries
// default to °F. Follows the chosen "traveling from" country unless the user
// pins a unit. Addresses feedback that the site felt US-centric.
const FAHRENHEIT_HOMES = new Set(["US", "BS", "BZ", "KY", "PW", "FM", "MH", "LR"]);
let tempUnitManual = localStorage.getItem("wg_tempunit");   // "C" | "F" | null
function homeUsesFahrenheit() {
  // Read the persistent origin (not the DOM select, which is empty on a direct
  // /guide/<slug> load before the Top Picks tab builds its dropdown).
  return FAHRENHEIT_HOMES.has(travelOrigin());
}
function tempUnit() { return tempUnitManual || (homeUsesFahrenheit() ? "F" : "C"); }
function fmtTemp(c) {
  if (c == null) return "—";
  return (tempUnit() === "F" ? Math.round(c * 9 / 5 + 32) : Math.round(c)) + "°";
}
function setTempUnit(u) {
  tempUnitManual = u;
  localStorage.setItem("wg_tempunit", u);
  if (ccGuideIso) renderCountryClimate(ccGuideIso);
}
// Bar color by temperature: blue = too cold, green = ideal (~18-26°C), then
// warming through amber to red (38°C+ fully red). The hot side goes via amber
// because a direct green->red blend passes through muddy brown.
function tempColor(c) {
  if (c == null) return NODATA;
  const BLUE = [43, 108, 176], GREEN = [10, 125, 40],
        AMBER = [223, 138, 16], RED = [190, 18, 24];
  const lerp = (a, b, f) => a.map((x, i) => Math.round(x + (b[i] - x) * f));
  const cl = (f) => Math.max(0, Math.min(1, f));
  let rgb;
  if (c < 18) rgb = lerp(BLUE, GREEN, cl(c / 18));
  else if (c <= 26) rgb = GREEN;
  else if (c <= 32) rgb = lerp(GREEN, AMBER, cl((c - 26) / 6));
  else rgb = lerp(AMBER, RED, cl((c - 32) / 6));
  return "rgb(" + rgb.join(",") + ")";
}

function renderCountryClimate(iso) {
  const c = climate[iso];
  $("bestDetail").classList.remove("loading");   // the first-paint height it held (styles.css)
  if (!c) { $("bestDetail").textContent = "No data."; return; }
  const bestSet = new Set(c.best);
  const seas = seasons(c.scores);

  // Curated month-level hazards (smoke season, monsoon, hurricanes…) — a blunt
  // peak/off-peak label hides these, so they get their own markers and lines.
  const hazards = (activities && activities[iso] && activities[iso].hazards) || [];
  const hzByMonth = {};
  for (const h of hazards) for (const m of h.months || []) hzByMonth[m] = h.note;

  // Spelled out, in a sentence, under a heading that repeats the question.
  // Every search that reaches these pages is some form of "best time to visit
  // <country>", and this block is what a reader — and a JS-rendering crawler —
  // actually sees: renderGuide() deletes the server-rendered copy on hydration,
  // so saying it only there says it to nobody. The sentence stands alone: a
  // month-chip row underneath repeated it verbatim and was cut for exactly
  // that reason — same fact twice in adjacent lines, and chips match nothing
  // anyone types.
  const bestFull = joinAnd(c.best.filter((m) => m >= 1 && m <= 12).map((m) => MONTHS[m - 1]));
  // country-names.json's name, as the server says it — climate.json carries
  // Natural Earth's abbreviations ("Bosnia and Herz."); "the Bahamas" mid-sentence.
  const cname = countryNameInText(iso);
  const bestLine = !bestFull
    ? (c.curated ? "📅 Curated best months:" : "📅 Best weather:")
    : c.curated
      ? `📅 The best months to visit ${esc(cname)} are <strong>${bestFull}</strong> — judged on weather and seasonality.`
      : `📅 The best weather in ${esc(cname)} is in <strong>${bestFull}</strong>.`;
  const temps = c.temps || [];
  const bars = c.scores.map((s, i) => {
    const h = s == null ? 0 : Math.round(s);
    const selM = parseInt(($("valueMonth") || {}).value, 10) || curMonth();
    const col = (bestSet.has(i + 1) ? "col best" : "col") + (i + 1 === selM ? " selmonth" : "");
    const hz = hzByMonth[i + 1];
    const t = temps[i];
    // Bar headline is the month's avg temperature; height + color still encode
    // weather comfort (score lives in the tooltip). Bars double as the month
    // picker — clicking one plans the trip for that month (planForMonth).
    const head = t != null ? fmtTemp(t) : (s == null ? "" : s);
    // The chart is the guide's month control, so it takes the keyboard too:
    // a focusable toggle per month (Enter/Space plans it, see the keydown
    // handler by planForMonth), named by the same text as its hover title.
    const what = `${MONTHS[i]}: ${t != null ? fmtTemp(t) + " avg · " : ""}comfort ${s == null ? "n/a" : s + "/100"} · ${seasonCaveat(seas[i], bestSet.has(i + 1), !!hz) || SEASON_WX[seas[i]]}${hz ? " · ⚠️ " + esc(hz) : ""} · click to plan for ${MONTHS[i]}`;
    return `<div class="${col}" data-mn="${i + 1}" title="${what}" tabindex="0" role="button" aria-pressed="${i + 1 === selM}" aria-label="${what}">
      <div class="mscore">${head}</div>
      <div class="fill" style="height:${h}%;background:${t != null ? tempColor(t) : comfortColor(s)}"></div>
      <div class="mlabel ${seas[i]}">${MON_ABBR[i]}${hz ? `<span class="hzmark" data-tip="⚠️ ${esc(hz)}" title="">⚠️</span>` : ""}</div></div>`;
  }).join("");
  const hasTemps = temps.some((t) => t != null);
  const unitToggle = hasTemps
    ? `<div class="tempunit" role="group" aria-label="temperature unit">
         <button type="button" data-u="C" class="${tempUnit() === "C" ? "active" : ""}" aria-pressed="${tempUnit() === "C"}">°C</button>
         <button type="button" data-u="F" class="${tempUnit() === "F" ? "active" : ""}" aria-pressed="${tempUnit() === "F"}">°F</button>
       </div>` : "";

  const hazardLines = hazards.map((h) =>
    `<div class="hazardline">⚠️ <b>${monthSpan(h.months)}:</b> ${esc(h.note)}</div>`).join("");

  // WHERE the temperatures are measured: one point stands for the country
  // (build_climate.py), named in climate.json ("at") where the point is a
  // city the build chose. No name = a geometric point; say that, never guess
  // a city. Peru's chart once read 25°C every month from the Amazon while
  // Cusco's dry season is 10-13°C, and nothing said so.
  const where = c.at
    ? `Temperatures are monthly averages for ${c.at}.`
    : "Monthly temperatures are for one representative point in the country.";
  const legend = "Each bar is a month — the number is its average temperature, taller = comfier"
    + " weather, and color = heat: blue cold, green ideal, amber warm, red hot. Month labels"
    + " underneath: green = its comfiest months, amber = in between, grey = its least comfy —"
    + " weather only, relative to its own year, not prices or crowds. Outlined bars = the"
    + (c.curated ? " curated best months" : " best-weather months")
    + "; the boxed, underlined bar = the month you're planning for (click any bar to change it). "
    + where;
  // The "Comfiest weather / Least comfy" line that sat here was cut: it named
  // curated best months as least comfy on the next line (the classes split the
  // country's own range into thirds), and the label colours already carry it.
  // regionOf, not ISO_REGION alone: 11 guides (North Korea, El Salvador…)
  // are missing from that table and headed "· —". Antarctica and the French
  // Southern Lands have no region at all, so no suffix.
  const rg = REGIONS[regionOf(iso)];
  $("bestDetail").innerHTML = `
    <div class="besthead">
      <h2><span aria-hidden="true">🌤️</span> Best time to visit ${esc(cname)}${rg ? ` <span class="muted">· ${rg}</span>` : ""}${
        hasTemps ? `<span class="legendinfo" data-tip="${esc(legend)}" title="">ⓘ</span>` : ""}</h2>
      ${unitToggle}
    </div>
    <div class="monthslabel">${bestLine}</div>
    ${hazardLines}
    <div class="bars">${bars}</div>`;
  for (const b of document.querySelectorAll("#bestDetail .tempunit button"))
    b.addEventListener("click", () => setTempUnit(b.dataset.u));
}

// (The standalone by-month map merged into "Where to go now" as a map mode.)

// ===========================================================================
//  Travel advisories
// ===========================================================================
// Which government's advisories to use: US, Canada or Germany, picked on the
// Data → Safety tab (see advisorySource). Government advisories reflect that
// country's foreign policy, so whose read it is gets named wherever it shows.
let advisories = null;
const _advBySource = {};
// One request per feed however many callers want it at once — the map, the
// table, the governments panel and a guide each asked separately, and the
// US and German feeds went out three times on a first load.
// A feed that just failed isn't asked again for a minute — every redraw
// (a sort, the governments panel) used to re-request a feed that was down.
const _advFetch = {}, _advFailAt = {};
function fetchAdv(src) {
  if (_advBySource[src]) return Promise.resolve(_advBySource[src]);
  if (_advFailAt[src] && Date.now() - _advFailAt[src] < 60000) return Promise.reject(new Error("feed unavailable"));
  return _advFetch[src] || (_advFetch[src] = getJSON("/api/advisories?source=" + src)
    .then((r) => { delete _advFailAt[src]; return (_advBySource[src] = r); })
    .catch((e) => { _advFailAt[src] = Date.now(); throw e; })
    .finally(() => { delete _advFetch[src]; }));
}
// Your own government first; the others fill its gaps (server-side, stamped `via`).
// Three governments, one explicit dropdown, no magic: the source used to
// follow the home country automatically, and the owner called it — with only
// three sources referenced, silent switching confused more than it helped.
// The pick persists and feeds the same global everything reads (map, table,
// guides, scoring); US is simply the default.
function advisorySource() {
  try {
    const o = localStorage.getItem("wg_advsrc");
    if (o === "us" || o === "ca" || o === "de") return o;
  } catch (e) {}
  return "us";
}
// Whose levels are in use, for every label that credits the safety data — a
// hard-coded "US State Dept" went stale once the source became a pick. The
// short form (the picker's own wording) is for image footers and headers,
// where "German Federal Foreign Office (Auswärtiges Amt)" would overflow.
const ADV_SRC_SHORT = { us: "US State Dept", ca: "Global Affairs Canada", de: "German Foreign Office" };
function advSrcName(short) {
  const src = (advisories && advisories.source) || advisorySource();
  if (short) return ADV_SRC_SHORT[src] || "US State Dept";
  return (advisories && advisories.source_name) || ADV_SRC_SHORT[src] || "U.S. State Department";
}
// A gap the chosen government leaves is filled by another (server stamps `via`).
function advViaShort(it) {
  return it && it.via ? ADV_SRC_SHORT[it.via] || it.via_name || "" : "";
}
// The site's own English name, not the feed's: the German feed says
// "Frankreich", and the Safety filter box matches row text.
function advName(it) {
  const n = it.iso ? countryName(it.iso) : "";
  return n && n !== it.iso ? n : it.country;
}
function advSafetyTitle() {
  return "travel-advisory level per " + advSrcName() + " — other governments fill its gaps";
}
// The key and the full-ranking Safety header are static HTML; name the
// current source on them whenever the ranking re-renders.
function labelSafetySource() {
  const k = $("safeKeySrc");
  if (k) k.textContent = advSrcName();
  const th = document.querySelector('#valueTable th[data-sk="safety"]');
  if (th) th.title = advSafetyTitle();
}
// The Full ranking's Overall header says what it is made of, from the
// weights actually in force (Count off = "off"). The weights are the core of
// "the math" and were shown nowhere.
function labelFullRanking(W) {
  const th = document.querySelector('#valueTable th[data-sk="value"]');
  if (!th) return;
  const tot = Object.values(W).reduce((a, b) => a + b, 0) || 1;
  th.title = "everything blended, weighted by your priorities — now "
    + WEIGHT_DEFS.map((w) => FACTOR_ICON[w.key] + " " + (W[w.key] ? Math.round(W[w.key] / tot * 100) + "%" : "off")).join(" · ")
    + "; a missing score is left out";
}
async function ensureAdvisories() {
  const src = advisorySource();
  await fetchAdv(src);
  // A slow fetch for a source the user has since switched away from must not
  // land last and flip every level back to it.
  if (advisorySource() === src || !advisories) advisories = _advBySource[src];
  return advisories;
}
// Re-fetch if the active advisory source changed since last load. The source
// used to follow the home country; it is an explicit dropdown now, so this is
// only a consistency check (returns true if a re-render is needed).
async function reloadAdvisoriesForOrigin() {
  const src = advisorySource();
  if (advisories && advisories.source === src) return false;
  await ensureAdvisories();
  return true;
}
const LVL_COLOR = { 1: "#0a7d28", 2: "#c9a200", 3: "#d4730a", 4: "#b00020" };
// Map fills: the pill colours above stay on pills, but the MAP samples the
// same red-neutral-green ramp every other map on the site is built from —
// switching Data sub-tabs used to jump from red/green worlds to a
// yellow/orange one, which read as a different product. Four discrete stops
// on one diverging ramp: rich green, pale green, pale rose, deep rose — and
// Level 4 is exactly DNT_FILL, so "do not travel" is one colour everywhere
// (value map, safety map, exported images). The legend draws from this same
// table so key and map cannot disagree.
const LVL_MAP_COLOR = {
  1: mix("#eef0f1", "#0a7d28", 0.62),
  2: mix("#eef0f1", "#0a7d28", 0.16),
  3: mix("#eef0f1", "#b00020", 0.30),
  4: mix("#eef0f1", "#b00020", 0.55),
};

// Germany grades nothing (see govGraded): a formal warning for the whole
// country (read as Level 4), one for some regions (Level 2), or none. Read as
// Level 1, its 150-odd "Keine Warnung" countries — North Korea among them —
// painted the map "safest" green. They get a neutral fill of their own, their
// own words in the pill, legend and level filter, and the German term in the
// tip. A gap another government fills (`via`) is a real level and keeps it.
const DE_NONE_FILL = "#e3e6e8";
const DE_LVL_LABEL = { 1: "No warning", 2: "Some regions", 4: "Travel warning" };
// The level filter. With Germany, its words match only its own calls: "No
// warning" also caught 26 other governments' Level 1 gap-fills, "Some
// regions" 6 country-wide Level 2s, and its "L3" option matched nothing —
// the gap-fills are their own option, "Rated by others" ("via").
function advLvlMatch(sel, lvl, via, de) {
  if (!sel || sel === "all") return true;
  if (sel === "via") return !!via;
  return String(lvl) === sel && !(de && via);
}
const _advWait = {};   // one redraw per load, however many renders asked
function renderAdvisories() {
  const byIso = {};
  for (const it of advisories.items) if (it.iso) byIso[it.iso] = it;
  const de = advisories.source === "de";
  const deOwn = (it) => de && !it.via && parseInt(it.level, 10) < 4;
  // "Keine Warnung (no warning)" -> ["Keine Warnung", "no warning"]
  const deSplit = (it) => { const m = /^(.*?) \((.*)\)$/.exec(it.level_text || ""); return m ? [m[1], m[2]] : [it.level_text, it.level_text]; };
  drawMap("advMap", (f) => {
    const it = byIso[f.properties.iso];
    if (!it) return { fill: NODATA, title: f.properties.name + " — no advisory data" };
    if (deOwn(it) && parseInt(it.level, 10) === 1)
      return { fill: DE_NONE_FILL, title: `${advName(it)} — no warning (${deSplit(it)[0]}; Germany warns, it doesn't grade)` };
    // Germany's own whole-country warning in its words too (deOwn leaves
    // out Level 4, so Russia read "Level 4: Reisewarnung" beside a "Travel
    // warning" pill, legend and filter).
    return { fill: LVL_MAP_COLOR[it.level],
      title: `${advName(it)} — ${de && !it.via && DE_LVL_LABEL[it.level] ? DE_LVL_LABEL[it.level] : "Level " + it.level}: ${it.level_text}`
        + (it.via ? ` (per ${advViaShort(it)})` : "") };
  }, (advisories.source_name || "Travel") + " advisory levels");
  // No "top" list — a hundred Level-1 ties can't be ranked. What CAN be said
  // is what MOVED: the feed's own "level was increased/decreased" statements,
  // dated. Under the map only (it used to repeat above the table, 100px on).
  const cutoff = advMoveCutoff();
  const changed = advisories.items
    .filter((it) => it.change && advChangedOn(it) >= cutoff && (!it.iso || inRegion(it.iso)))
    .sort((a, b) => (advChangedOn(a) < advChangedOn(b) ? 1 : -1)).slice(0, 8);
  // "New Caledonia ▼ L2 · 21 May": the arrow in its colour (a <b>, which the
  // share image reads as text, not as a pick of its own), named for a screen
  // reader; Germany's own calls in its words.
  const chLine = (it) => {
    const up = it.change === "up";
    return { html: esc(advName(it)) + ` <b class="${up ? "chup" : "chdown"}" role="img" aria-label="${up ? "raised to" : "lowered to"}">${up ? "▲" : "▼"}</b> `
      + esc(advSrcOf(it) === "de" ? advLvlWords(it) : "L" + advLvl(it)) + " · " + esc(fmtDayShort(advChangedOn(it))) };
  };
  renderDimPicks("advMap", "Recently changed", changed.map(chLine), changed.map((it) => it.iso));

  // The source is named once in the title; the picker beside it is the
  // control, and the sub-line counts instead of repeating it.
  const advH2 = $("advH2");
  if (advH2) advH2.innerHTML = `Travel advisories <span class="muted">per ${esc(advSrcName(true))}</span>`;
  // The level filter in the chosen government's words; an option no row of
  // its would match is hidden (and disabled, for Safari, which shows hidden
  // options), and "Rated by others" is Germany's alone.
  const words = ADV_LVL_WORDS[advisories.source] || ADV_LVL_WORDS.us;
  const lvlSel = $("advLevel");
  if (lvlSel) {
    for (const o of lvlSel.options) {
      if (o.value === "all") continue;
      const l = +o.value;
      o.textContent = o.value === "via" ? "Rated by others" : de ? DE_LVL_LABEL[l] || "L" + l : "L" + l + " — " + words[l - 1];
      const n = (o.value !== "via" || de) && advisories.items.some((it) => advLvlMatch(o.value, advLvl(it), it.via, de));
      o.hidden = o.disabled = !n;
    }
    if (lvlSel.selectedOptions[0] && lvlSel.selectedOptions[0].disabled) lvlSel.value = "all";
  }
  const srcSel = $("advSource");
  if (srcSel) {
    srcSel.value = advisories.source || advisorySource();
    srcSel.onchange = async () => {
      try { localStorage.setItem("wg_advsrc", srcSel.value); } catch (e) {}
      // Another government, another scale: a level picked under the last
      // one ("Some regions") could mean nothing under this one.
      if (lvlSel) lvlSel.value = "all";
      await ensureAdvisories();
      renderAdvisories();
      if (loaded.value) renderValue();   // safety grades follow the chosen source
      // …and so does everything else already painted with a level: an open
      // guide's safety block, and the Data tables' hide-higher-risk filters
      // (currency rows stamp their level when rendered, so re-render them).
      if (ccGuideIso) renderGuideSafety(ccGuideIso);
      if (dataRates) renderRates(dataRates);
      applyAffordFilter(); applyFlightFilter();
    };
  }
  // Gap-fills are counted apart: they are another government's call, and the
  // rows carrying one say whose. One line; the reading of the scale, and that
  // an advisory is one government's foreign policy, live in the ⓘ.
  const filled = advisories.filled || 0;
  const own = advisories.count - filled;
  const tip = (de
    ? "Germany issues a formal travel warning for a whole country (read here as Level 4), a warning for some "
      + "regions (Level 2), or none. \"No warning\" is not a safety grade — it advises against North Korea "
      + "without one — so those countries are left neutral rather than painted safest."
    : `Levels per ${advSrcName()}: ` + words.map((w, i) => (i + 1) + " " + w.toLowerCase()).join(", ") + ".")
    + (filled ? ` ${filled} ${filled === 1 ? "country" : "countries"} it doesn't cover carry another government's level — a dashed pill, whose tip says whose.` : "")
    + " Advisories reflect each government's own foreign policy — pick another under “Per” to compare.";
  $("advSub").innerHTML = esc(de ? `${own} countries · Germany warns, it doesn't grade` : `${own} countries rated`)
    + (filled ? esc(` · ${filled} filled in by others`) : "")
    // &nbsp;: the ⓘ goes down with the last word, not alone (Germany's line
    // wrapped at 1000 and left it on a line of its own).
    + `&nbsp;<span class="muted" data-tip="${esc(tip)}" title="">ⓘ</span>`;
  // Each level's words in its swatch's tip; the grey of a country no
  // government we follow rates (~10 on the map) is keyed like the Cost map's.
  // Germany's gap-fill note is "+32 others" (its tip says whose): with "No
  // data" added, "per others" broke the legend onto a third line at 1280.
  const sw = (c, l, tip) => `<span${tip ? ` data-tip="${esc(tip)}" title=""` : ""}><span class="swatch" style="background:${c}"></span>${l}</span>`;
  $("advLegend").innerHTML = (de
    ? [sw(DE_NONE_FILL, "No warning"), sw(LVL_MAP_COLOR[2], "Some regions"), sw(LVL_MAP_COLOR[4], "Travel warning")].join(" ")
      + (filled ? ` <span class="muted" data-tip="${esc(`${filled} countries Germany doesn't cover show another government's Level 1–4, green to red — each row says whose.`)}" title="">+${filled} others</span>` : "")
    : [1, 2, 3, 4].map((l) => sw(LVL_MAP_COLOR[l], "L" + l, `Level ${l} · ${words[l - 1]} (per ${advSrcName(true)})`)).join(" "))
    + ' <span><span class="swatch"></span>No data</span>';
  // Germany's words make a legend twice the US's or Canada's (392px to 196):
  // the CSS gives it a row of its own where squeezing it beside the picker
  // took three lines (styles.css, #advLegend.long).
  $("advLegend").classList.toggle("long", de);

  markSort("#advTable", advSort);
  // The two columns beside the level (usItem, healthOf): the reasons — the
  // US State Department's, or with Canada picked Canada's own (health.json
  // `r`, so it waits for that file too) — and Canada's disease risks. Each
  // loads once and redraws the table when it lands; one that fails says so
  // in its cells instead of asking again on every redraw.
  if (!health && !healthFailed && !_advWait.health) {
    _advWait.health = true;
    ensureHealth().then(() => { _advWait.health = false; if (advisories) renderAdvisories(); });
  }
  const usMine = advisories.source === "us";
  if (!usMine && !_advBySource.us && !_advWait.us && !_advWait.usFailed) {
    _advWait.us = true;
    ensureAllAdvisories().then(() => {
      _advWait.us = false;
      if (!_advBySource.us) _advWait.usFailed = true;
      if (advisories) renderAdvisories();
    });
  }
  const usOwn = {};
  for (const x of ((_advBySource.us || {}).items) || []) if (x.iso && !x.via) usOwn[x.iso] = x;
  const usLoaded = usMine || !!(_advBySource.us && _advBySource.us.items);
  // The US item whose reasons a row shows: its own when the US is the pick,
  // else the US's rating of the same country; null where the US rates none.
  const usItem = (it) => (usMine ? (it.via ? null : it) : (it.iso && usOwn[it.iso]) || null);
  // Canada's own reasons for its own level (never beside a gap-fill, which
  // is another government's level): health.json's `r` labels, `rq` the lead
  // sentence they come from.
  const caMine = advisories.source === "ca";
  // health.json is a snapshot and the feed is live: once Canada moves a
  // level after the build, the sentence quoted would contradict the pill
  // ("Exercise a high degree of caution" beside Level 3). Quoted only while
  // it says the row's level in Canada's words; else the US's, as for a row
  // Canada gives no reasons for. A gap-fill (`via`: Palestine on Canada's
  // list carries the US's or Germany's level) never shows Canada's.
  const caWhy = (it) => {
    const c = caMine && !it.via && it.iso && health && health.c[it.iso];
    const words = ADV_LVL_WORDS.ca[advLvl(it) - 1];
    return c && c.r && c.r.length && words && String(c.rq || "").toLowerCase().includes(words.toLowerCase()) ? c : null;
  };
  // _rk/_rkSrc: the reasons a row shows and whose — what the Risks sort and
  // the notes row read, so neither can disagree with the cell.
  for (const it of advisories.items) {
    const u = usItem(it), c = caWhy(it);
    it._rkSrc = c ? "ca" : u && u.risks && u.risks.length ? "us" : null;
    it._rk = c ? c.r : it._rkSrc ? u.risks : null;
    it._rq = c ? c.rq || "" : "";
    it._hz = healthOf(it.iso) || null;
    it._wn = wnOf(it.iso) ? wnAgency(it.iso) : "";
  }
  // With Germany picked, the reasons are the US's: the header says so, and
  // so does every phrase that stands in for them. With Canada, its own —
  // the US's, marked, only where Canada's page gives none. A health.json
  // built before it carried Canada's reasons has none at all: then the
  // column is the US's, and says so, as with Germany.
  const caOwn = caMine && (advisories.items.some((it) => it._rkSrc === "ca") || (!health && !healthFailed));
  const rkLabel = $("riskLabel");
  if (rkLabel) rkLabel.textContent = usMine || caOwn ? "Risks" : "Risks · US";
  const riskInfo = $("riskInfo");
  const usWhy = "the reasons the U.S. State Department gives for its level — its own “due to crime, terrorism…” line — "
    + "as short labels; “Other” is a reason no label fits (the tip quotes the sentence).";
  if (riskInfo) riskInfo.dataset.tip = usMine ? "T" + usWhy.slice(1)
    : caOwn ? "The reasons Global Affairs Canada gives for its level — its own lead sentence on each country's page — "
      + "as short labels; the tip quotes it. Where Canada's page names none, the U.S. State Department's, marked “US” "
      + "(its level can differ from Canada's)."
    : caMine ? "T" + usWhy.slice(1) + " Beside Canada's level, which can differ — they're the US's, marked “US”."
    : "Germany gives its reasons on each country's own page (in German). Shown here instead: " + usWhy
      + " Beside Germany's call, which can differ — they're the US's, marked “US”.";
  const healthInfo = $("healthInfo");
  if (healthInfo) healthInfo.dataset.tip = "Diseases the Government of Canada's travel health advice calls a risk to "
    + "travellers there — mosquito-borne ones like dengue, malaria and Zika, street-dog rabies, and more. ⚠️ = a travel "
    + "health notice" + (healthStale() ? " (as of " + healthAsOf() + ")" : "") + "; ◐ = only in some areas, seasons or "
    + "itineraries. Ones Canada calls low or sporadic are in each row's tip. “Only the usual” = none that sets the "
    + "country apart (hepatitis A, routine vaccines and the like are left out everywhere). Not every risk is listed — "
    + (health && health.w
      // Canada's date before West Nile's part, which has its own: "As of"
      // after the ECDC/CDC credits read as theirs.
      ? "Canada's advice says so." + (healthAsOf() ? " As of " + healthAsOf() + "." : "")
        + " West Nile virus, which Canada's advice leaves out, is added where " + wnAgencies().join(" or ")
        + " reported human cases" + wnIn() + "." + (health.w.note ? " " + fullStop(health.w.note) : "")
        + wnAgencies().map((a) => (WN_SRC[a] ? " " + wnCredit(a) : "")).join("")
      : "Canada's advice says so, and West Nile virus, for one, isn't in it." + (healthAsOf() ? " As of " + healthAsOf() + "." : ""));
  // Keep open notes rows open across a redraw (a late feed or a sort).
  const openIsos = [...document.querySelectorAll('#advRows .worow[aria-expanded="true"]')].map((b) => b.dataset.iso);
  $("advRows").innerHTML = sortRows(advisories.items, advSort, ADV_GET, ADV_GET.country).map((it) => {
    const lvl = advLvl(it);
    const safeLink = /^https:\/\//.test(it.link || "") ? it.link : "";
    const nm = advName(it);
    const guideAttr = it.iso ? ` data-iso="${esc(it.iso)}" title="See the ${esc(nm)} travel guide →"` : "";
    // Germany's own rows: the English in the pill, the government's own word
    // in its tip, led by the pill's words — "Reisewarnung · Avoid travel"
    // under a "Travel warning" pill never said the two were one call:
    // "Travel warning (Reisewarnung): avoid travel".
    const [term, eng] = de && !it.via ? deSplit(it) : [it.level_text, ""];
    const deLbl = de && !it.via ? DE_LVL_LABEL[lvl] || "" : "";
    const head = deLbl ? deLbl + " (" + term + ")" + (eng && eng.toLowerCase() !== deLbl.toLowerCase() ? ": " + eng : "")
      : term + (eng && eng !== term ? " · " + eng.charAt(0).toUpperCase() + eng.slice(1) : "");
    const tip = [it.summary, it.updated ? "updated " + fmtDay(it.updated) : ""].filter(Boolean).join(" · ");
    // The pill carries the level's words, whose call it is, the feed's
    // summary and date in its tip. Another government's level (a gap-fill)
    // is dashed, and says whose to a screen reader too.
    const pillTip = [head, it.via ? "per " + advViaShort(it) : "", tip].filter(Boolean).join(" · ");
    const pillAttr = ` data-tip="${esc(pillTip)}" title=""`;
    const viaCls = it.via ? " via" : "";
    const viaSr = it.via ? `<span class="vh"> (per ${esc(advViaShort(it))})</span>` : "";
    // Germany's own calls say its words, its whole-country warning too (it
    // read "Level 4" beside a "Travel warning" filter and legend).
    const pill = deOwn(it) ? `<span class="lvl ${lvl === 1 ? "none" : "lvl2"}${viaCls}"${pillAttr}>${DE_LVL_LABEL[lvl]}${viaSr}</span>`
      : de && !it.via && DE_LVL_LABEL[lvl] ? `<span class="lvl lvl${lvl}"${pillAttr}>${DE_LVL_LABEL[lvl]}</span>`
      : `<span class="lvl lvl${lvl}${viaCls}"${pillAttr}>Level ${lvl}${viaSr}</span>`;
    const src = it.via ? advViaShort(it) : advSrcName(true);
    const nameCell = it.iso ? `<span class="advflag" aria-hidden="true">${flagEmoji(it.iso)}</span><a class="destlink" href="${esc(guidePath(it.iso))}">${esc(nm)}</a>` : esc(nm);
    // The latest move the feed records (only the current advisory is
    // published, so this is all the history there is): an arrow after the
    // pill, dated in its tip and for a screen reader; a move in the last 180
    // days tints the row — red raised, green lowered.
    let moveCls = "", arrow = "";
    const on = advChangedOn(it);
    if (it.change && on) {
      const up = it.change === "up", when = fmtDayShort(on);
      arrow = `<span class="advmvp ${up ? "neg" : "pos"}" data-tip="${esc(src + (up ? " raised" : " lowered")
        + " it to " + advLvlName(it) + " on " + when)}" title=""><span aria-hidden="true">${up ? "▲" : "▼"}</span>`
        + `<span class="vh"> ${up ? "raised" : "lowered"} ${esc(when)}</span></span>`;
      if (on >= advMoveCutoff()) moveCls = up ? "advup" : "advdown";
    }
    // 🚨 Risks: the reasons as chips, the sentence they come from in the
    // tip — Canada's own beside Canada's level, else the US's. Without
    // reasons, one quiet phrase: "normal precautions" at Level 1 (the
    // advisory's full phrase repeated the pill down 83 rows), the level's own
    // words above it, or "no US advisory" where the US rates none. Beside
    // another government's pill, each says it's the US's.
    const u = usItem(it);
    const usPre = usMine ? "" : "US: ";
    const uTip = u && u.summary ? "Per the U.S. State Department: “" + u.summary + "”"
      : "Per the U.S. State Department: Level " + (u ? advLvl(u) : "") + ", no reasons given";
    const riskCell = it._rkSrc === "ca"
      ? `<span class="rkwrap" data-tip="${esc(it._rk.join(" · ") + " — per Global Affairs Canada"
          + (it._rq ? ": “" + it._rq + "”" : ""))}" title="">${chipsHTML(it._rk, null, true)}</span>`
      : caMine && !health && !healthFailed ? '<span class="muted">…</span>'
      : it._rk
      ? `<span class="rkwrap" data-tip="${esc(it._rk.join(" · ") + " — per the U.S. State Department"
          + (u && u.summary ? ": “" + u.summary + "”" : ""))}" title="">${usMine ? "" : '<span class="rkus">US</span>'}${chipsHTML(it._rk, null, true)}</span>`
      : !usLoaded && _advWait.usFailed ? `<span class="sftext" data-tip="The U.S. reasons couldn't be loaded — try again later." title="">—</span>`
      : !usLoaded ? '<span class="muted">…</span>'
      : !u ? `<span class="sftext">${usMine ? "no US advisory" : "US: no advisory"}</span>`
      : `<span class="sftext" data-tip="${esc(uTip)}" title="">${usPre}${advLvl(u) >= 2 ? esc(String(u.level_text || "").toLowerCase()) : "normal precautions"}</span>`;
    // 💉 Health: Canada's disease risks, the rest in the tip; West Nile
    // (another agency's, named in its tip) after any notices.
    const hz = it._hz, wn = it._wn ? wnText(it.iso) : "";
    const healthCell = !health && healthFailed ? `<span class="sftext" data-tip="Canada's health advice couldn't be loaded — try again later." title="">—</span>`
      : !health ? '<span class="muted">…</span>'
      : !it.iso ? '<span class="muted">—</span>'
      : !hz && !wn ? `<span class="sftext" data-tip="Not covered by Canada's travel health advice" title="">—</span>`
      : `<span class="hzwrap" data-tip="${esc(hz ? healthTip(hz, wn) : "Not covered by Canada's travel health advice. " + wn)}" title="">${
          (hz && hz.h.length) || wn ? healthChipsHTML(hz || { h: [] }, true, it._wn, it.iso) : `<span class="hzlow">${HEALTH_USUAL}</span>`}</span>`;
    // data-via: a gap another government fills — the level filter's "Rated
    // by others", and with Germany kept out of its own words' options.
    return `
    <tr data-lvl="${lvl}"${it.via ? ` data-via="${esc(it.via)}"` : ""}${guideAttr}${moveCls ? ` class="${moveCls}"` : ""}><td>${nameCell}</td>
      <td>${pill}${arrow}</td>
      <td class="rkcell">${riskCell}</td>
      <td class="hzcell">${healthCell}</td>
      <td class="advnotes">${it.iso ? `<button type="button" class="worow" data-iso="${esc(it.iso)}" aria-expanded="false" aria-label="${esc(nm)}: safety and health notes">▸ notes</button>` : ""}${safeLink ? `<a class="advlink farelink" href="${esc(safeLink)}" target="_blank" rel="noopener" aria-label="${esc(nm)} advisory on ${esc(src)} (opens in a new tab)"><span class="advlinkword">details</span>&nbsp;<span class="ext">↗</span></a>` : ""}</td>
    </tr>`;
  }).join("");
  fitChips($("advRows"));
  // …and again whenever the table's width changes: a window resized or a
  // tablet turned, or the table shown after being drawn while hidden.
  const tbl = $("advTable");
  if (tbl && !tbl._fitRO && window.ResizeObserver) {
    let lastW = 0, t = 0;
    tbl._fitRO = new ResizeObserver(() => {
      if (tbl.offsetWidth === lastW) return;
      lastW = tbl.offsetWidth;
      clearTimeout(t);
      t = setTimeout(() => fitChips($("advRows")), 120);
    });
    tbl._fitRO.observe(tbl);
  }
  for (const iso of openIsos) {
    const btn = document.querySelector(`#advRows .worow[data-iso="${iso}"]`);
    if (btn) btn.click();
  }
  applyAdvFilter();
  wireWatchoutRows();
  // A country clicked on the map shows all three governments' advice beside it.
  $("advMap")._onPick = (iso) => setGovCountry(iso);
  renderGov();
}

// ---- Safety: what each government says -------------------------------------
// Beside the map: by default the countries the US, Canada and Germany rate
// furthest apart; a country picked on the map (or in the list) shows all three
// advisories. Only each government's OWN ratings are compared — the gap-fills
// a feed borrows from another government (`via`) would compare a government
// with itself.
const GOV = [["us", "🇺🇸", "US"], ["ca", "🇨🇦", "Canada"], ["de", "🇩🇪", "Germany"]];
let govIso = (() => { const v = new URLSearchParams(location.search).get("sc") || ""; return /^[A-Z]{2}$/.test(v) ? v : null; })();
// On a phone the list sits in the page, eight rows until "Show all" (CSS
// gates both on width); this remembers the reader asked for all of them.
let govAll = false;
const GOV_SHORT = 8;
// Each feed on its own: one that fails leaves its column "unavailable"
// rather than blanking the panel.
async function ensureAllAdvisories() {
  await Promise.allSettled(GOV.map(([src]) => fetchAdv(src)));
}
function govOwn(src) {
  const out = {};
  for (const it of ((_advBySource[src] || {}).items) || [])
    if (it.iso && !it.via && parseInt(it.level, 10) >= 1) out[it.iso] = it;
  return out;
}
// Germany grades nothing: it issues a formal warning for a whole country (read
// as Level 4), a warning for some regions, or none. Neither of the last two is
// a level: "none" is not "normal precautions" (it advises against North Korea
// without a formal warning), and a regional warning can sit anywhere from
// "caution" to "avoid" for the rest of the country. Read as Level 1 and 2 they
// made up most of the "disagreements" — a scale mismatch, not a difference of
// view. Only Germany's full warning is compared.
const govGraded = (src, it) => !!it && (src !== "de" || parseInt(it.level, 10) === 4);
function setGovCountry(iso) {
  govIso = iso || null;
  renderGov(true);
  syncURL();
}
// Whether the list scrolls in its own box (beside the map, or stacked above
// 560px) rather than in the page.
const govInBox = (box) => getComputedStyle(box).overflowY !== "visible" && box.scrollHeight > box.clientHeight + 1;
async function renderGov(focus) {
  const box = $("govScroll");
  if (!box) return;
  await ensureAllAdvisories();
  const loadedSrc = GOV.filter(([src]) => _advBySource[src] && _advBySource[src].items);
  // data-failed lets go of the room a phone holds for the list while it
  // loads (styles.css #govScroll:empty): with nothing coming, it was 336px
  // of blank under this line.
  if (!loadedSrc.length) {
    $("govSub").textContent = "Couldn't load the governments' advisories — try again later.";
    box.innerHTML = ""; $("govNote").textContent = ""; $("govNote").hidden = true;
    box.setAttribute("data-failed", "");
    return;
  }
  box.removeAttribute("data-failed");
  const own = {};
  for (const [src] of GOV) own[src] = govOwn(src);
  const ok = (src) => !!(_advBySource[src] && _advBySource[src].items);
  // A code nobody rates (a bad sc= link) is no country to show.
  if (govIso && !GOV.some(([src]) => own[src][govIso])) govIso = null;
  const mine = (advisories && advisories.source) || advisorySource();
  const pill = (it, src) => (!ok(src) ? '<span class="none" title="this feed didn\'t load">unavailable</span>'
    : !it ? '<span class="none" title="no advisory of its own">—</span>'
    : src === "de" && !govGraded(src, it)
      ? `<span class="none" title="${esc(it.level_text || "")}">${parseInt(it.level, 10) === 2 ? "some regions" : "no warning"}</span>`
    : `<span class="lvl lvl${parseInt(it.level, 10)}"${src === "de" ? ` title="${esc(it.level_text || "")}"` : ""}>L${parseInt(it.level, 10)}</span>`);
  const tip = "Each government rates risk for its own citizens, and through its own foreign policy — the same country can be "
    + "'exercise caution' to one and 'avoid travel' to another. Canada grades 1–4 like the US. Germany only issues formal "
    + "warnings, for a whole country (shown as L4) or for some regions — so a regional warning, or none, isn't a level and "
    + "isn't compared. Only each government's own ratings count: gaps one fills from another are left out.";
  if (govIso) {
    const name = countryName(govIso);
    $("govH2").innerHTML = `${esc(name)} <span class="muted">what each government says</span>`;
    $("govSub").innerHTML = '<button type="button" class="govback">← Where governments disagree</button>';
    $("govNote").innerHTML = `<span class="muted" data-tip="${esc(tip)}" title="">How these compare ⓘ</span>`;
    box.classList.add("detail");
    box.innerHTML = GOV.map(([src, flag]) => {
      const it = own[src][govIso];
      const full = (_advBySource[src] || {}).source_name || ADV_SRC_SHORT[src];
      const link = it && /^https:\/\//.test(it.link || "") ? it.link : "";
      // Germany's page for the country is in German: say so.
      const linkText = src === "de" ? "Read the advice (in German) ↗" : "Read the advisory ↗";
      const meta = [it && it.updated ? "Updated " + fmtDay(String(it.updated).slice(0, 10)) : "",
                    link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${linkText}</a>` : ""].filter(Boolean);
      const line = !ok(src) ? '<div class="muted">This government\'s advisories didn\'t load.</div>'
        : !it ? `<div class="muted">No advisory of its own for ${esc(name)}</div>`
        : src === "de" && !govGraded(src, it)
          ? `<div>${parseInt(it.level, 10) === 2 ? "A formal warning for some regions only" : "No formal warning from Germany"}</div>`
        : `<div>${pill(it, src)} ${esc(it.level_text || "")}</div>`;
      // A long feed summary ends on its last full sentence, not mid-word.
      let sum = it && it.summary ? String(it.summary) : "";
      if (/\.\.\.$|…$/.test(sum)) { const k = sum.lastIndexOf(". ", sum.length - 4); if (k > 40) sum = sum.slice(0, k + 1); }
      return `<div class="govrow${src === mine ? " mine" : ""}"><div class="govname">${flag} ${esc(full)}</div>`
        + line
        + (meta.length ? `<div class="muted">${meta.map((m, i) => (i ? " · " : "") + m).join("")}</div>` : "")
        + (sum ? `<p class="govsum">${esc(sum)}</p>` : "")
        + "</div>";
    }).join("");
    if (focus) {
      box.scrollTop = 0;   // from deep in the list, the box kept its offset and hid the US's row
      const bk = document.querySelector("#govCard .govback");
      if (bk) bk.focus({ preventScroll: true });
      // Picked deep in a page-long phone list: the three advisories are
      // far shorter, and the page would be left showing what's below them.
      const card = $("govCard");
      if (card && card.getBoundingClientRect().top < 0) card.scrollIntoView({ block: "start" });
    }
  } else {
    const rows = [];
    const isos = new Set(GOV.flatMap(([src]) => Object.keys(own[src])));
    for (const iso of isos) {
      const lv = GOV.map(([src]) => (govGraded(src, own[src][iso]) ? own[src][iso] : null))
        .filter(Boolean).map((it) => parseInt(it.level, 10));
      if (lv.length < 2) continue;
      const spread = Math.max(...lv) - Math.min(...lv);
      if (spread >= 1 && countryName(iso) !== iso && inRegion(iso)) rows.push({ iso, spread, max: Math.max(...lv) });
    }
    rows.sort((a, b) => b.spread - a.spread || b.max - a.max || countryName(a.iso).localeCompare(countryName(b.iso)));
    const far = rows.filter((r) => r.spread >= 2).length;
    // The column heads name the three governments; the header keeps only a
    // region's name. One line of counts under it — how to use the list and
    // the key to its marks are in the ⓘ (they were two more lines).
    $("govH2").innerHTML = "Where governments disagree"
      + (regionSel === "all" ? "" : ` <span class="muted">${esc(REGIONS[regionSel])}</span>`);
    const how = (rows.length ? "Pick a country here or on the map to compare all three. " : "Pick one on the map to see all three. ")
      + "L1–L4 = each government's level; — = no advisory of its own. " + tip;
    $("govSub").innerHTML = esc(rows.length
      ? `${far} ${far === 1 ? "country" : "countries"} 2+ levels apart · ${rows.length - far} one level apart`
      : "They agree on every country here")
      + `&nbsp;<span class="muted" data-tip="${esc(how)}" title="">ⓘ</span>`;
    $("govNote").innerHTML = "";
    box.classList.remove("detail");
    // Back from a country further down than the phone's first rows: show
    // them all, or there is no row to come back to.
    const lastAt = box._lastIso ? rows.findIndex((r) => r.iso === box._lastIso) : -1;
    if (focus && lastAt >= GOV_SHORT) govAll = true;
    const more = rows.length > GOV_SHORT
      ? `<button type="button" class="showmore govmore" aria-expanded="${govAll}">${govAll ? "Show fewer ↑" : "Show all " + rows.length + " ↓"}</button>` : "";
    box.innerHTML = `<table class="govtable${govAll ? "" : " short"}"><thead><tr><th>Country</th>`
      // The flag in its own span: a phone under 375 drops it to keep the
      // three headers on one line each (styles.css, .govtable .thflag).
      + GOV.map(([src, flag, short]) => `<th class="${src === mine ? "mine" : ""}"><span class="thflag" aria-hidden="true">${flag} </span>${short}</th>`).join("")
      + `</tr></thead><tbody>`
      + rows.map((r) => `<tr data-iso="${esc(r.iso)}"><td><button type="button" class="govpick" data-iso="${esc(r.iso)}"`
        + ` title="All three advisories for ${esc(countryName(r.iso))}"><span class="govflag" aria-hidden="true">${flagEmoji(r.iso)}</span>`
        + `${esc(countryName(r.iso))}</button></td>`
        + GOV.map(([src]) => `<td class="${src === mine ? "mine" : ""}">${pill(own[src][r.iso], src)}</td>`).join("") + "</tr>").join("")
      + "</tbody></table>" + more;
    // Back from a country: its row in view (centred in the box, or in the
    // page where the list is part of it) and focused.
    if (focus) {
      const last = box._lastIso && box.querySelector(`.govpick[data-iso="${box._lastIso}"]`);
      if (last) {
        if (govInBox(box)) {
          const b = box.getBoundingClientRect(), r = last.getBoundingClientRect();
          box.scrollTop += r.top - b.top - (box.clientHeight - r.height) / 2;
        } else last.scrollIntoView({ block: "center" });
        last.focus({ preventScroll: true });
      }
    }
  }
  $("govNote").hidden = !$("govNote").innerHTML;
  box._lastIso = govIso || box._lastIso;
  if (!box._wired) {
    box._wired = true;
    $("govCard").addEventListener("click", (e) => {
      if (e.target.closest(".govback")) { setGovCountry(null); return; }
      const mb = e.target.closest(".govmore");
      if (mb) {
        govAll = !govAll;
        const t = $("govScroll").querySelector(".govtable");
        if (t) t.classList.toggle("short", !govAll);
        mb.textContent = govAll ? "Show fewer ↑" : "Show all " + (t ? t.tBodies[0].rows.length : "") + " ↓";
        mb.setAttribute("aria-expanded", String(govAll));
        // Folding 2,000px away from under the reader: keep the button in view.
        if (!govAll) mb.scrollIntoView({ block: "nearest" });
        return;
      }
      const tr = e.target.closest(".govtable tbody tr[data-iso]");
      if (tr) setGovCountry(tr.dataset.iso);
    });
  }
}

// The table is where safety research happens, so the full watchouts live here
// too (the owner moved them from the guide's front door). Lazy per country —
// one fetch on first open, shared cache with the guides — and the toggle stops
// propagation so it doesn't trip the row's open-the-guide handler.
// The notes row opens on every reason and disease in full — on a phone, whose
// table has no room for those columns, the only place they show — then
// Canada's watchouts.
function advDetailHead(iso) {
  const it = advisories && advisories.items.find((x) => x.iso === iso);
  const out = [];
  // Whose reasons these are: Canada's own beside its level, else the US's.
  if (it && it._rk) out.push(`<div class="advdl"><b><span aria-hidden="true">🚨 </span>Risks</b> <span class="muted">per ${
    it._rkSrc === "ca" ? "Global Affairs Canada" : "US State Dept"}</span> `
    + `<span class="rkwrap">${chipsHTML(it._rk)}</span></div>`);
  // The Health line in words, group by group — on a phone (no hover, no
  // column header) the ⚠️ and ◐ marks would otherwise go unexplained.
  // West Nile is a group of its own after Canada's link — spliced in among
  // Canada's groups it sat under "per Government of Canada", whose advice
  // leaves it out — credited to the agency that reported it, linked to that
  // agency's page, with the credit its data asks for (ECDC's licence too).
  const hz = healthOf(iso), wx = wnOf(iso);
  if (hz || wx) {
    const notice = (hz && hz.n) || [], areas = (hz && hz.a) || [];
    const kind = (n) => (notice.includes(n) ? "notice" : areas.includes(n) ? "area" : "");
    const hg = hz ? healthGroups(hz) : [];
    const groups = hg.map(([label, list], i) => `<span class="advgrp"><span class="muted">${esc(label)}:</span> `
      + (i === hg.length - 1 && label === "Low or sporadic"
        ? `<span class="muted">${esc(list.join(", "))}</span>`
        : `<span class="rkwrap">${chipsHTML(list, kind)}</span>`) + "</span>");
    const wby = wx ? wnAgency(iso) : "", ws = WN_SRC[wby], wa = wx ? wnAreas(iso) : "";
    const ext = (href, text) => `<a class="farelink" href="${esc(href)}" target="_blank" rel="noopener">${text}&nbsp;<span class="ext">↗</span></a>`;
    const wnGroup = !wx ? "" : ` <span class="advgrp wngrp"><span class="muted">${esc(wnLabel(iso))}${wa ? ":" : ""}</span> ${
      esc(wa && wx.t ? fullStop(wa) : wa)}${wx.t ? ` <span class="muted">${esc(fullStop(wx.t))}</span>` : ""}${ws
      ? ` <span class="muted">${esc(ws.credit)}${ws.licence ? "; licence</span> " + ext(WN_CC_URL, esc(ws.licence).replace(/ /g, "&nbsp;"))
          + ' <span class="muted">·</span>' : ".</span>"}`
        + " " + ext(ws.url(), esc(wby))
      : ""}</span>`;
    out.push(`<div class="advdl"><b><span aria-hidden="true">💉 </span>Health</b> <span class="muted">${hz
      ? "per Government of Canada" + (healthAsOf() ? ", as of " + esc(healthAsOf()) : "")
      : "not covered by Canada's travel health advice"}</span> `
      + (!hz || hz.h.length ? "" : `<span class="hzlow">${HEALTH_USUAL}</span> `)
      + groups.join(" ")
      + (hz && hz.s ? " " + ext(`https://travel.gc.ca/destinations/${encodeURIComponent(hz.s)}#health`, "health advice") : "")
      + wnGroup
      + "</div>");
  }
  return out.join("");
}
function wireWatchoutRows() {
  const host = $("advRows");
  if (!host || host._woWired) return;
  host._woWired = true;
  host.addEventListener("click", async (e) => {
    const btn = e.target.closest(".worow");
    if (!btn) return;
    e.stopPropagation();
    const tr = btn.closest("tr");
    const iso = btn.dataset.iso;
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("wodetail")) {
      next.remove();
      btn.textContent = "▸ notes";
      btn.setAttribute("aria-expanded", "false");
      return;
    }
    btn.textContent = "▾ notes";
    btn.setAttribute("aria-expanded", "true");
    const det = document.createElement("tr");
    det.className = "wodetail";
    const head = advDetailHead(iso);
    det.innerHTML = '<td colspan="5">' + head + '<span class="muted">Loading safety notes…</span></td>';
    tr.insertAdjacentElement("afterend", det);
    try {
      const w = _watchoutCache[iso]
        || (_watchoutCache[iso] = await getJSON("/api/watchouts?iso=" + encodeURIComponent(iso)));
      if (!det.isConnected) return;
      if (!w.watchouts.length && !w.regional.length) {
        det.innerHTML = '<td colspan="5">' + head + '<span class="muted">No structured watchouts published for this country.</span></td>';
        return;
      }
      const built = watchoutsBlockHTML(w);
      det.innerHTML = '<td colspan="5">' + head + built.reg + built.chips
        + '<span class="advsrcnote">Per ' + esc(w.source || "Global Affairs Canada")
        + (w.link ? ' — <a class="farelink" href="' + esc(w.link) + '" target="_blank" rel="noopener">details&nbsp;<span class="ext">↗</span></a>' : "") + "</span></td>";
    } catch (err) {
      if (det.isConnected) det.innerHTML = '<td colspan="5">' + head + '<span class="muted">Could not load watchouts.</span></td>';
    }
  });
}

// ===========================================================================
//  Cost of living (PPP) tab — its own map + ranked table
// ===========================================================================
// The cost tab's home selector is the SAME state as the From selector on Top
// Picks, mirrored (the homeCur/dataBase pattern): one home country, visible
// and changeable wherever the comparison is read. Changing it here changes it
// everywhere, fares and visas included.
function initAffAnchor() {
  const sel = $("affAnchor");
  if (!sel) return;
  // Straight into the shared origin (which repaints this map): mirroring into
  // #valueOrigin did nothing on a session that never built Top Picks.
  sel.onchange = () => setTravelOrigin(sel.value);
  const match = () => {
    const o = originIso();
    if (sel.value !== o && [...sel.options].some((x) => x.value === o)) {
      sel.value = o;
      if (sel._sync) sel._sync();
    }
  };
  if (sel.options.length <= 1) {
    // Fill from the same source as the From selector rather than cloning it:
    // on a direct Data-tab load, valueOrigin may not be populated yet.
    fillOriginSelect(sel).then(() => {
      match();
      renderAfford();          // repaint with the anchor the select now shows
    }).catch(() => {});
    return;
  }
  match();
}

// The price level against the country's own last ten years, both measured
// against the same home — the Cost tab's answer to Currency's "vs 1-yr avg".
// From the yearly World Bank history behind the Cost-over-time chart. null
// with under six of those years, or a history on another exchange-rate basis
// than today's figure (colJoins: Iran, Venezuela…). pos = where today sits in
// the decade's range, 100 = its cheapest (right, green, like Currency's bar).
function affTrend(iso, anchor, now) {
  if (!plHist) return null;
  const y0 = new Date().getFullYear() - 10;
  const pts = colSeries(iso, anchor).filter((p) => p.year != null && p.year >= y0);
  if (pts.length < 6 || !colJoins(iso, pts[pts.length - 1].value, now)) return null;
  const vals = pts.map((p) => p.value);
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  const lo = Math.min(...vals, now), hi = Math.max(...vals, now);
  return { pct: (now / avg - 1) * 100, from: pts[0].year, to: pts[pts.length - 1].year,
           pos: hi > lo ? ((hi - now) / (hi - lo)) * 100 : 50, lo, hi };
}
// "Cheaper than usual": at least this far under the 10-year average. 5% made
// 77 of 176 rows green for a US home (43%, against 23% on Currency), so green
// stopped picking anything out; 10%, tested on the printed whole percent
// (affPct), makes it 49 (28%). Every text that states the threshold reads
// this constant.
const AFF_CHEAP_PCT = 10;
// The "vs 10-yr avg" move as its cell prints it: a whole percent, rounded on
// the magnitude as the cell's toFixed(0) did, so −9.5 shows −10 (Math.round
// alone gives −9).
// Colour, row green and the sub-line count all test this, not the raw
// figure: on raw values a US home showed Togo, Botswana, Fiji, Panama and
// Sweden at "−10%" uncoloured and Romania and Estonia at "+10%", while the ⓘ
// says green means "at least 10% below".
const affPct = (t) => Math.sign(t.pct) * Math.round(Math.abs(t.pct));
// A price level built on World Bank data older than the year before most
// countries' (Eritrea 2021, British Virgin Islands 2017, against 2025):
// inflation carries it forward three years at most (pplCarry), and not at all
// without a current figure, so it is rougher than its neighbours. "" when the
// data is recent.
function pppAgeNote(iso) {
  const y = ppp && ppp[iso] && ppp[iso].year, most = Number(pppYear());
  if (!y || !most || y >= most - 1) return "";
  // "here", not the name: "for British Virgin Islands" lacked its "the".
  return `⚠️ The World Bank's latest price data here is from ${y} (${most} for most countries), `
    + "so this figure is rougher than most.";
}
// Every price-data caveat for a country, one per line, for a single ⚠️.
function pppNotes(iso) { return [pppDriftNote(iso), pppAgeNote(iso)].filter(Boolean).join("\n"); }
function renderAfford() {
  // The trend columns read the yearly history; its arrival re-renders.
  // (Not gated on loaded.afford: on a direct /?dm=afford load the history can
  // land before that flag is set, and the columns stayed "—".)
  if (!plHist) ensurePLHistory().then(() => { if (typeof ppp !== "undefined" && ppp) renderAfford(); }).catch(() => {});
  // The reference is the traveler's From country, not a hard-coded US — the
  // owner's question, and Top Picks already anchors this way (anchorPl). A
  // German comparing prices wants "vs Germany, in euros"; price levels are
  // all stored vs the US, so dividing by the anchor's own level rebases them.
  initAffAnchor();
  const anchorIso = originIso();
  const { pl: anchorPl, cur: anchorCur, name: anchorName } = plAnchor(anchorIso);
  // "$100", "€100", "₹100": the browser's own sign for every home currency,
  // not a "$" for the dollar and "EUR 100" for the rest.
  const money = (v) => fmtCur(anchorCur, v), hundred = money(100);
  drawMap("affMap", (f) => {
    const pl = priceLevel(f.properties.iso);
    if (pl == null) return { fill: NODATA, title: f.properties.name + " — no price data" };
    const rel = pl / anchorPl;
    const notes = pppNotes(f.properties.iso);
    return { fill: affordColor(rel),
      title: `${f.properties.name} — price level ${rel.toFixed(2)} (${plWord(rel)} vs ${anchorName})`
             + (notes ? " · " + notes.replace(/\n/g, " ") : "") };
  }, "Cost of living (price level vs " + anchorName + ")");
  // Mirrors the table under it, including its Level 3–4 filter. Only places
  // cheaper than home: ranked by the raw level alone, an Indian home listed
  // India itself at #2 and six places where the rupee goes less far.
  const adv = advisoryByIso();
  const cheap = Object.keys(CUR_BY_ISO)
    .map((iso) => ({ iso, pl: priceLevel(iso) }))
    .filter((x) => x.pl != null && x.iso !== anchorIso && x.pl < anchorPl
      && countryName(x.iso) !== x.iso && inRegion(x.iso)
      && (showRisky || (adv[x.iso] || 0) < 3))
    .sort((a, b) => a.pl - b.pl).slice(0, 8);
  // "Egypt $604": the title already says $100, and "$100≈$604" between two
  // amounts read like an exchange rate rather than what the $100 buys.
  // Each pick keeps its table row's ⚠️: Gambia sat at #7 for a US home on a
  // price level its own row warns reads cheaper than it feels, and the list
  // said nothing. The share image reads the names only (dimPicksFromDom).
  renderDimPicks("affMap", "Where " + hundred + " goes furthest",
    cheap.map((x) => countryName(x.iso) + " " + money(100 * anchorPl / x.pl)),
    cheap.map((x) => x.iso), "Few places are cheaper than " + anchorName + " on average — see the table",
    cheap.map((x) => pppNotes(x.iso)));

  // One line above the map; the source, its year and the national-average
  // caveat sit in the ⓘ. The "Vs home" picker beside it is the reference.

  $("affLegend2").innerHTML =
    '<span>Pricey</span><span class="scale"></span><span>Cheap</span>' +
    '<span style="margin-left:6px"><span class="swatch"></span>No data</span>';

  // Ranked cheapest-first table.
  const anchorObj = plAnchor(anchorIso);
  const rows = [];
  for (const iso in CUR_BY_ISO) {
    const pl = priceLevel(iso);
    if (pl == null) continue;
    const name = (ppp[iso] && ppp[iso].name) || (climate && climate[iso] && climate[iso].name) || iso;
    rows.push({ iso, name, cur: CUR_BY_ISO[iso], pl, tr: iso === anchorIso ? null : affTrend(iso, anchorObj, pl / anchorPl) });
  }
  // Both counts on the line are the table's rows as shown (its region and its
  // Level 3–4 filter). The country count used to be the map's — every price,
  // risky or not — so a US home read "176 countries · 32 cheaper than usual"
  // over 135 rows, and Americas "31 countries · 6 cheaper" over 25.
  const shown = rows.filter((r) => inRegion(r.iso) && (showRisky || (adv[r.iso] || 0) < 3));
  const cheaperNow = shown.filter((r) => r.tr && affPct(r.tr) <= -AFF_CHEAP_PCT).length;
  const ai = $("affInfo");
  if (ai) ai.dataset.tip = `Green rows: prices there, measured against ${anchorName}, are at least ${AFF_CHEAP_PCT}% below `
    + "their own average of the last ten years — cheaper than usual, whether from a weaker currency or slower price rises. "
    + "From the World Bank's yearly price levels behind the Cost over time chart. The bar shows where today sits in that "
    + "decade: further right = nearer its cheapest.";
  // After the rows: the count comes from them.
  // Until the history lands, an invisible stand-in for the count it adds
  // holds the line's length: without it the line was a line shorter on a
  // tablet or phone for that moment, and the map and table rode up and back.
  $("affSub").innerHTML = esc(`Below 1.00 = cheaper than ${anchorName} · ${shown.length} countries`
    + (plHist ? ` · ${cheaperNow} cheaper than usual` : ""))
    + ` <span class="muted" data-tip="${esc(`World Bank PPP (${pppYear()} for most countries), brought up to date by inflation, ÷ today's exchange rate. `
      + "National averages: neighbourhoods popular with visitors, and rent paid by foreigners, run well above them.")}" title="">ⓘ</span>`
    + (plHist ? "" : '<span class="skeltext" aria-hidden="true"> · 32 cheaper than usual</span>');
  markSort("#affTable", affSort);
  // The header carries the currency ("€100 buys"), so the cells needn't
  // repeat "of at-home goods" 176 times — the th title still says it.
  const bth = document.querySelector('#affTable th[data-sk="buys"] .sortbtn');
  if (bth) bth.textContent = hundred + " buys";
  // The Currency tab's grammar: flag + name (the currency code under it), the
  // price level with its word, a move column against the country's own norm,
  // green rows where that move favours the reader, and a range bar.
  $("affRows").innerHTML = sortRows(rows, affSort, AFF_GET, AFF_GET.name).map((r) => {
    const rel = r.pl / anchorPl;
    const cls = plCls(rel);
    // countryName(), not r.name: r.name is the World Bank's label ("Iran,
    // Islamic Rep.", "Lao PDR"), not what the rest of the site calls them.
    const cn = countryName(r.iso);
    // Top Picks' ⚠️ for a price level to doubt (Gambia's stale inflation,
    // Bolivia's slide, Eritrea's 2021 data). It lived only in the map's hover
    // title here, which touch never sees; .hzmark taps show the tip instead of
    // opening the guide. Sorting reads r.pl, so the mark never moves a row.
    const notes = pppNotes(r.iso);
    const warn = notes ? `<span class="hzmark" data-tip="${esc(notes)}" title="">⚠️</span>` : "";
    const t = r.tr;
    const p = t ? affPct(t) : 0;
    const cheapNow = t && p <= -AFF_CHEAP_PCT;
    const vsCls = !t ? "" : cheapNow ? "pos" : p >= AFF_CHEAP_PCT ? "neg" : "";
    // Sign and words from the rounded figure: on the raw one Austria (−0.3)
    // printed "−0%" and "0% below their average".
    const vsTip = !t ? "" : p === 0 ? `${cn}'s prices vs ${anchorName} are in line with their ${t.from}–${t.to} average`
      : `${cn}'s prices vs ${anchorName} are ${Math.abs(p)}% ${p < 0 ? "below" : "above"} their ${t.from}–${t.to} average`;
    const vs = t ? `<span data-tip="${esc(vsTip)}" title="">${p < 0 ? "−" : p > 0 ? "+" : ""}${Math.abs(p)}%</span>`
      : `<span class="muted" data-tip="${esc("Too little price history on today's exchange-rate basis to compare with")}" title="">—</span>`;
    const bar = t ? `<div class="range" data-tip="${esc(`Today sits ${Math.round(t.pos)}% of the way from its priciest to its cheapest level `
      + `of ${t.from}–${t.to} (vs ${anchorName}) — further right = cheaper than usual`)}" title=""><span style="left:${t.pos.toFixed(0)}%"></span></div>` : "";
    return `<tr data-iso="${esc(r.iso)}"${cheapNow ? ' class="favorable"' : ""} title="See the ${esc(cn)} travel guide →">`
      + `<td><div class="curcell"><span class="curflag" aria-hidden="true">${flagEmoji(r.iso)}</span><div>`
      + `<a class="destlink" href="${esc(guidePath(r.iso))}">${esc(cn)}</a><div class="affcur">${esc(r.cur)}</div></div></div></td>
      <td class="num"><span class="plnum"><span class="${cls}">${rel.toFixed(2)}</span>${warn}</span><span class="plw"> ${plTag(rel)}</span></td>
      <td class="num ${vsCls}">${vs}</td>
      <td class="num">${esc(money(100 * anchorPl / r.pl))}</td>
      <td class="num">${bar}</td></tr>`;
  }).join("");
  applyAffordFilter();
  // Clicking a country on this map also makes it the chart's line.
  $("affMap")._onPick = (iso) => setColCountry(iso);
  renderCol();
}

// ---- cost over time (Cost of living tab) -----------------------------------
// The map's price level per year since 1990 (World Bank; build_pl_history.py),
// then today's — the map's own number — as the last point. Against the Vs home
// country, like the map. "A typical country" is the geometric mean across
// every country with figures, chain-linked year to year so countries joining
// the data (Kosovo, 2008) don't move it.
let plHist = null, plHistP = null;
function ensurePLHistory() {
  if (!plHistP) {
    plHistP = fetch(stamped("/pl_history.json"))
      .then((r) => { if (!r.ok) throw new Error("pl_history.json " + r.status); return r.json(); })
      .then((d) => { if (!d || !d.years || !d.pl) throw new Error("no price history"); plHist = d; return d; })
      .catch((e) => { plHistP = null; throw e; });
  }
  return plHistP;
}
const COL_Q = new URLSearchParams(location.search);
let colIso = /^[A-Z]{2}$/.test(COL_Q.get("cc") || "") ? COL_Q.get("cc") : "world";
// Opens on 10Y, the window the table's "vs 10-yr avg" measures (as Currency's
// chart opens on 1Y beside its "vs 1-yr avg"); old cr=all links still work.
let colRange = ["10", "20", "all"].includes(COL_Q.get("cr")) ? COL_Q.get("cr") : "10";

// [{date, value, year}] for one country (or "world") vs the anchor, yearly
// points dated mid-year (they are annual averages), then today's.
function colSeries(iso, anchor) {
  const Y = plHist.years, P = plHist.pl;
  const home = anchor.iso === "US" ? null : P[anchor.iso];
  const rel = (c, i) => {
    const v = P[c] && P[c][i], h = home ? home[i] : 1;
    return v && h ? v / h : null;
  };
  const out = [];
  const asOf = ((dataRates || lastRates || {}).as_of) || new Date().toISOString().slice(0, 10);
  if (iso !== "world") {
    Y.forEach((y, i) => { const v = rel(iso, i); if (v != null) out.push({ date: y + "-07-01", value: v, year: y }); });
    // Today's figure joins only a recent series (Eritrea's stops in 2011: a
    // straight line to today would draw fifteen years nobody measured), on the
    // same exchange-rate basis (colJoins).
    const now = priceLevel(iso), lastY = out.length ? out[out.length - 1] : null;
    if (now != null && lastY && lastY.year >= Number(asOf.slice(0, 4)) - 3
        && colJoins(iso, lastY.value, now / anchor.pl))
      out.push({ date: asOf, value: now / anchor.pl, year: null });
    return out;
  }
  const isos = Object.keys(P).filter(inRegion);
  let level = null;
  Y.forEach((y, i) => {
    const logs = [];
    if (level == null) {
      for (const c of isos) { const v = rel(c, i); if (v) logs.push(Math.log(v)); }
      if (logs.length) level = Math.exp(logs.reduce((a, b) => a + b, 0) / logs.length);
    } else {
      for (const c of isos) { const a = rel(c, i - 1), b = rel(c, i); if (a && b) logs.push(Math.log(b / a)); }
      if (!logs.length) return;
      level *= Math.exp(logs.reduce((a, b) => a + b, 0) / logs.length);
    }
    if (level != null) out.push({ date: y + "-07-01", value: level, year: y });
  });
  // Today: the same countries' move from the line's last year to the map —
  // that year, not the data's (a UAE home has no 2025, and the line ended
  // there with "no figures since").
  const lastPt = out[out.length - 1], logs = [];
  const li = lastPt ? Y.indexOf(lastPt.year) : -1;
  for (const c of isos) {
    const a = li >= 0 ? rel(c, li) : null, now = priceLevel(c);
    if (a && now != null && colJoins(c, a, now / anchor.pl)) logs.push(Math.log(now / anchor.pl / a));
  }
  if (lastPt && lastPt.year >= Number(asOf.slice(0, 4)) - 3 && logs.length)
    out.push({ date: asOf, value: lastPt.value * Math.exp(logs.reduce((a, b) => a + b, 0) / logs.length), year: null });
  return out;
}

// Whether today's map figure can follow a country's yearly ones. Not where the
// World Bank converts that economy at another rate than the official one the
// map uses (plHist.alt: Burundi's yearly 0.19 beside today's 0.46), nor across
// a jump bigger than the data ever shows in a year and a bit (Turkmenistan).
function colJoins(iso, last, now) {
  if ((plHist.alt || []).includes(iso)) return false;
  const r = now / last;
  return r < 1.5 && r > 1 / 1.5;
}

// Rebuilt when the home country changes: home is left out (a country against
// itself is a flat 1.00 line), so the list depends on it.
function fillColPick() {
  const sel = $("colPick");
  const home = originIso();
  if (!sel || sel.dataset.home === home) return;
  sel.dataset.home = home;
  const isos = Object.keys(plHist.pl).filter((c) => c !== home && countryName(c) !== c)
    .sort((a, b) => countryName(a).localeCompare(countryName(b)));
  sel.innerHTML = '<option value="world">🌍 A typical country</option>'
    + isos.map((c) => `<option value="${esc(c)}">${esc(countryName(c))}</option>`).join("");
  sel.onchange = () => setColCountry(sel.value);
  enhanceSelect(sel);   // once; its observer resyncs the label on a rebuild
}
function setColCountry(iso) {
  if (iso === originIso()) iso = "world";   // home vs home: the typical line instead
  if (!plHist || (iso !== "world" && !plHist.pl[iso])) return;
  colIso = iso;
  renderCol();
  syncURL();
}
for (const b of document.querySelectorAll("#colRange button")) {
  b.addEventListener("click", () => { colRange = b.dataset.range; renderCol(); syncURL(); });
}

async function renderCol() {
  const host = $("colChart");
  if (!host) return;
  try { await ensurePLHistory(); } catch (e) {
    $("colSub").textContent = "Could not load the price history: " + e.message;
    return;
  }
  fillColPick();
  if (colIso !== "world" && (!plHist.pl[colIso] || colIso === originIso())) colIso = "world";
  const sel = $("colPick");
  if (sel.value !== colIso) { sel.value = colIso; if (sel._sync) sel._sync(); }
  const anchor = plAnchor(originIso());
  let pts = colSeries(colIso, anchor);
  if (colRange !== "all") {
    const from = new Date().getUTCFullYear() - Number(colRange);
    const cut = pts.filter((p) => p.year == null || p.year >= from);
    // A series that stopped before the window (Venezuela, 2011) shows all it
    // has rather than an empty box — the strength chart's rule too.
    if (cut.length >= 2 || pts.length < 2) pts = cut;
    else colRange = "all";
  }
  for (const b of document.querySelectorAll("#colRange button")) {
    const on = b.dataset.range === colRange;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }
  const name = colIso === "world" ? "A typical country" + (regionSel === "all" ? "" : " in " + REGIONS[regionSel])
    : countryName(colIso);
  $("colH2").innerHTML = `Cost over time <span class="muted">${esc(name)} vs ${esc(anchor.name)}</span>`;
  if (pts.length < 2) {
    host.innerHTML = "<p class='hint'>No price history for " + esc(name) + ".</p>";
    host._redraw = null;
    $("colNow").textContent = ""; $("colChg").textContent = "";
    $("colSub").textContent = ""; $("colNote").textContent = "";
    return;
  }
  const first = pts[0], lastP = pts[pts.length - 1];
  const when = (p) => (p.year == null ? "today" : String(p.year));
  const chgText = (p) => {
    const c = (p.value / first.value - 1) * 100;
    return { text: `${c < 0 ? "▼" : "▲"} ${Math.abs(c).toFixed(Math.abs(c) < 10 ? 1 : 0)}% ${c < 0 ? "cheaper" : "pricier"} than ${first.year}`, cheaper: c < 0 };
  };
  const showHead = (p, prefix) => {
    const c = chgText(p);
    $("colNow").textContent = p.value.toFixed(2);
    const el = $("colChg");
    el.textContent = (prefix ? prefix + " · " : "") + c.text;
    el.className = c.cheaper ? "pos" : "neg";   // cheaper is the good news here
  };
  // A country whose figures stop (Venezuela: 2011) says which year its
  // headline is, rather than passing an old number off as today's.
  const rest = () => showHead(lastP, lastP.year == null ? "" : "in " + lastP.year);
  rest();
  // The title names the home country; this line doesn't say it again.
  $("colSub").innerHTML = esc(`1.00 = ${anchor.home ? "home" : "US"} prices · `)
    + `<span style="white-space:nowrap">${esc(first.year + "–" + when(lastP))}</span>`
    + (lastP.year == null ? "" : " (no figures since)");
  $("colNote").innerHTML = esc("Lower = your money buys more there. Yearly averages from the World Bank"
    + (lastP.year == null ? ", then today's figure from the map." : "."))
    + ` <span class="muted" data-tip="${esc("A year's price level is the World Bank's purchasing-power-parity factor over that year's exchange rate — the same measure as the map, which brings the latest year up to date with inflation and today's rate. National averages: the places visitors go run above them."
      + (colIso === "world" ? " A typical country is the geometric mean across every country with figures, chained year to year so countries joining the data don't move it." : ""))}" title="">ⓘ</span>`;
  const cheaper = lastP.value < first.value;
  stockChart(host, pts, {
    byDate: true,
    color: cheaper ? cssVar("--green", "#0a7d28") : cssVar("--red", "#b00020"),
    ref: { value: 1, label: anchor.name === "the US" ? "US prices" : anchor.name + " prices" },
    aria: `${name}: price level ${lastP.value.toFixed(2)} vs ${anchor.name}, ${chgText(lastP).text}`,
    onScrub: (i) => (i ? showHead(pts[i], when(pts[i]))
      : ($("colNow").textContent = pts[0].value.toFixed(2),
         $("colChg").textContent = when(pts[0]) + " · start", $("colChg").className = "")),
    onLeave: rest,
  });
}

// ===========================================================================
//  Best value now (blend affordability + currency timing + safety + weather)
// ===========================================================================
const clamp100 = (x) => Math.max(0, Math.min(100, Math.round(x)));

// User-adjustable priorities: High / Medium / Low per factor (simpler than
// numeric sliders). "fly" only participates for countries with a fare loaded.
// "afford" blends cost-of-living (PPP price level) with current FX strength into
// one Affordability factor — users found "Dollar" vs "Prices" hard to tell apart.
const WEIGHT_DEFS = [
  { key: "afford", label: "Affordability", def: "high" },
  { key: "safe",   label: "Safety",        def: "med" },
  { key: "wx",     label: "Weather",       def: "med" },
  { key: "fly",    label: "Flights",       def: "med" },
];
const PRI_LEVELS = [["high", "High"], ["med", "Med"], ["low", "Low"]];
const PRI_W = { high: 3, med: 2, low: 1 };   // relative weights, normalized at score time
const FACTOR_ICON = { afford: "💰", safe: "🛡️", wx: "🌤️", fly: "✈️" };
let priorities = null;

// Which factors count toward the grade at all (toggle chips in the filter row).
// Distinct from priorities: a factor can be weighted low or excluded entirely.
let factors = null;
function loadFactors() {
  if (factors) return factors;
  try { factors = JSON.parse(localStorage.getItem("fx_factors2") || "null"); } catch (e) {}
  factors = Array.isArray(factors) ? factors.filter((k) => WEIGHT_DEFS.some((w) => w.key === k)) : null;
  if (!factors || !factors.length) factors = WEIGHT_DEFS.map((w) => w.key);
  return factors;
}
function saveFactors() { localStorage.setItem("fx_factors2", JSON.stringify(factors)); }

function buildFactorChips() {
  loadFactors();
  const host = $("factorChips");
  if (!host) return;
  const on = new Set(factors);
  host.innerHTML = '<span class="picklabel">Count</span>' + WEIGHT_DEFS.map((w) =>
    `<button type="button" class="factorchip ${on.has(w.key) ? "on" : ""}" data-f="${w.key}"
       aria-pressed="${on.has(w.key)}"
       title="${w.label} ${on.has(w.key) ? "counts toward" : "is excluded from"} the grade">${FACTOR_ICON[w.key]} ${w.label}</button>`).join("");
  host.onclick = (e) => {
    const btn = e.target.closest(".factorchip");
    if (!btn) return;
    const k = btn.dataset.f;
    const set = new Set(loadFactors());
    if (set.has(k)) {
      if (set.size === 1) return;          // at least one factor must count
      set.delete(k);
    } else set.add(k);
    factors = WEIGHT_DEFS.map((w) => w.key).filter((x) => set.has(x));
    saveFactors();
    buildFactorChips();
    renderValue();
  };
}

// ---- interest filter (Top Picks) --------------------------------------------
// Multi-select, per traveler feedback: "culture and nature and food — but for
// goodness sake don't suggest beaches". A country stays if it matches ANY
// selected interest; nothing selected = no filtering. Same profile tags the
// Travel Guide uses (activities.json).
let wgInterests = null;
function loadInterests() {
  if (wgInterests) return wgInterests;
  try { wgInterests = new Set(JSON.parse(localStorage.getItem("wg_interests") || "[]")); }
  catch (e) { wgInterests = new Set(); }
  return wgInterests;
}
function matchesInterests(iso) {
  const sel = loadInterests();
  if (!sel.size) return true;
  if (!activities) return true;               // tags not loaded yet — don't hide
  const prof = (activities[iso] && activities[iso].profile) || [];
  return prof.some((p) => sel.has(p));
}
function buildInterestChips() {
  const host = $("interestChips");
  if (!host) return;
  const sel = loadInterests();
  host.innerHTML = '<span class="picklabel">Into</span>' + INTERESTS.map((i) =>
    `<button type="button" class="factorchip ${sel.has(i) ? "on" : ""}" data-i="${esc(i)}"
       title="${sel.has(i) ? "only countries matching a selected interest are suggested — tap to drop" : "tap to add"}">${PROFILE_EMOJI[i] || ""} ${esc(i)}</button>`).join("");
  host.onclick = (e) => {
    const btn = e.target.closest(".factorchip");
    if (!btn) return;
    const s = loadInterests();
    if (s.has(btn.dataset.i)) s.delete(btn.dataset.i); else s.add(btn.dataset.i);
    localStorage.setItem("wg_interests", JSON.stringify([...s]));
    buildInterestChips();
    // profile tags live in activities.json — lazily fetched, then re-rank
    ensureActivities().catch(() => {}).then(() => renderValue());
  };
  // saved interests from a previous visit need the tags before first render
  if (sel.size && !activities)
    ensureActivities().catch(() => {}).then(() => renderValue());
}

function loadPriorities() {
  if (priorities) return priorities;
  try { priorities = JSON.parse(localStorage.getItem("fx_priorities2") || "null"); } catch (e) {}
  if (!priorities) priorities = {};
  for (const w of WEIGHT_DEFS) if (!PRI_W[priorities[w.key]]) priorities[w.key] = w.def;
  return priorities;
}
function savePriorities() { localStorage.setItem("fx_priorities2", JSON.stringify(priorities)); }

// Numeric weights for the scorer, derived from the chosen priority levels.
// Factors toggled off in the filter row get weight 0 (excluded entirely).
function loadWeights() {
  const p = loadPriorities();
  const on = new Set(loadFactors());
  return Object.fromEntries(WEIGHT_DEFS.map((w) =>
    [w.key, on.has(w.key) ? PRI_W[p[w.key]] : 0]));
}

function buildWeightSliders() {
  loadPriorities();
  // The factor's emoji, as the table headers and the Count chips carry it, so
  // "🛡️ Safety: Med" here reads straight across to the 🛡️ column. Each group
  // is named by its label and says which level is pressed: the buttons used
  // to announce only "High"/"Med"/"Low", with the choice a class.
  $("weightRows").innerHTML = WEIGHT_DEFS.map((w) => `
    <div class="prirow" data-w="${w.key}"><span class="prilabel" id="pri-${w.key}"><span class="pico" aria-hidden="true">${FACTOR_ICON[w.key]}</span>${w.label}</span>
      <span class="prigroup" role="group" aria-labelledby="pri-${w.key}" data-w="${w.key}">${PRI_LEVELS.map(([v, t]) =>
        `<button type="button" data-v="${v}" class="${priorities[w.key] === v ? "active" : ""}" aria-pressed="${priorities[w.key] === v}">${t}</button>`).join("")}</span>
    </div>`).join("");
  $("weightRows").onclick = (e) => {
    const btn = e.target.closest("button");
    const grp = e.target.closest(".prigroup");
    if (!btn || !grp) return;
    priorities[grp.dataset.w] = btn.dataset.v;
    savePriorities();
    grp.querySelectorAll("button").forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-pressed", String(b === btn));
    });
    renderValue();
  };
}

function advisoryByIso() {
  const m = {};
  if (advisories) for (const it of advisories.items) if (it.iso) m[it.iso] = it.level;
  return m;
}
// The whole item, for the few places that need to name whose advisory it is —
// the server stamps `via` on any level the other government filled in.
function advisoryMetaByIso() {
  const m = {};
  if (advisories) for (const it of advisories.items) if (it.iso) m[it.iso] = it;
  return m;
}

// ---- home currency for Top Picks --------------------------------------------
// "From" picks the country (flights + what "cheap" is measured against);
// "In" picks the money (FX column + the currency prices are shown in). It
// follows the From country automatically until the user overrides it — an
// American expat hopping countries can pin USD and it stays pinned.
// homeBase itself is declared at the top of the file — the Data tab's rates fetch
// runs long before this point and needs it.
let homeRates = null;        // /api/rates dataset for that base (= lastRates for USD)
let homeManual = localStorage.getItem("fx_homecur_manual") === "1";
const _baseRatesCache = {};

function homeCurAuto() { return CUR_BY_ISO[originIso()] || "USD"; }

// ---- single "traveling from" origin, shared across the whole site ----------
// One source of truth: Top Picks "From", Explore-the-Data flights "From", the
// Travel Guide passport (visa), and the AI prompts all read it — so changing it
// in any tab carries everywhere. Persisted so it sticks across tabs and reloads.
function travelOrigin() { return localStorage.getItem("fx_origin") || "US"; }

// The home country every "from" question reads (fares, price anchor, currency,
// passport, AI prompts): the Top Picks select once built, else the persisted
// origin. That select is empty on a guide-first session, and reading it there
// with a "US" fallback quietly answered the US for a German visitor.
function originIso() {
  const sel = $("valueOrigin");
  return (sel && /^[A-Z]{2}$/.test(sel.value)) ? sel.value : travelOrigin();
}
function originLabel() { const o = originIso(); return o === "US" ? "the US" : countryName(o); }

function setTravelOrigin(iso) {
  if (!iso || !/^[A-Z]{2}$/.test(iso)) return;
  localStorage.setItem("fx_origin", iso);
  // Mirror into both origin selects (each only if it carries that option) and
  // refresh their comboboxes — programmatic, so this doesn't re-fire change.
  for (const id of ["valueOrigin", "flightOrigin", "affAnchor"]) {
    const sel = $(id);
    if (sel && [...sel.options].some((o) => o.value === iso)) {
      if (sel.value !== iso) sel.value = iso;
      if (sel._sync) sel._sync();
    }
  }
  if (!homeManual) setHomeCur(homeCurAuto(), false);   // currency follows unless pinned
  loadValueFlights(false);                             // Top Picks fares (re-renders)
  if (loaded.value) renderValue();                     // immediate: new affordability anchor
  if (loaded.afford) renderAfford();                   // cost-of-living anchor
  if (dataRates) renderRates(dataRates);               // its Price level column is vs From too
  if (ccCurrent) renderCountryCard();                  // its price level is vs From
  if (loaded.flights) loadFlights();                   // Explore-the-Data fares
  // The advisory source is an explicit dropdown (no longer tied to the home
  // country); this is a consistency re-check and normally a no-op.
  reloadAdvisoriesForOrigin().then((changed) => {
    if (!changed) return;
    if (loaded.value) renderValue();
    if (advisories && document.getElementById("advMap")) renderAdvisories();
    if (ccGuideIso) renderGuideSafety(ccGuideIso);
  }).catch(() => {});
  // guide visa + AI + temperature units (default unit follows the home country)
  if (ccGuideIso) { renderGuideVisa(ccGuideIso); renderGuideAI(ccGuideIso); renderCountryClimate(ccGuideIso); renderGuideSafety(ccGuideIso); renderGuideCost(ccGuideIso); }
  syncURL();
}

async function loadHomeRates() {
  const base = homeBase;   // homeBase can change during the await
  if (base === "USD") { homeRates = lastRates; return; }
  if (_baseRatesCache[base]) { homeRates = _baseRatesCache[base]; return; }
  homeRates = null;   // FX column shows neutral until the dataset lands
  const data = await getJSON("/api/rates?base=" + base);
  // Cache under the base REQUESTED — keyed by homeBase after the await, a
  // late response filed one currency's rates under another's name.
  if (data && data.base === base) _baseRatesCache[base] = data;
  if (homeBase === base && data && data.base === base) homeRates = data;   // ignore stale responses
}

function setHomeCur(code, manual) {
  const changed = homeBase !== code;
  homeBase = code;
  homeManual = manual;
  localStorage.setItem("fx_homecur", code);
  localStorage.setItem("fx_homecur_manual", manual ? "1" : "0");
  // Mirror into both pickers — Top Picks' "In" and the Data tab's "My currency"
  // are two views of one value, so neither may be left showing the other's.
  // Programmatic assignment doesn't re-fire change, so this can't loop.
  for (const id of ["homeCur", "dataBase"]) {
    const sel = $(id);
    if (!sel || !sel.options.length) continue;
    if ([...sel.options].some((o) => o.value === code) && sel.value !== code) sel.value = code;
    if (sel._sync) sel._sync();
  }
  loadHomeRates().catch(() => {}).then(() => {
    if (loaded.value) renderValue();
    if (ccCurrent) renderCountryCard();      // an open card reasons in this currency
  });
  // The Data tab reasons in this currency too, so refetch it in the new base.
  // Guarded on lastRates, not a loaded.* flag: the rates table isn't lazy — it
  // loads at boot — so there is no flag for it, and there was never one to check.
  if (changed && lastRates) { loadRates(); loadIndex(activeRange); }
  // The guide's FX trend AND fare chart are anchored to the home currency —
  // an open guide must not keep showing the previous one (the fare chart's
  // display currency falls back to homeBase when unpinned; its fetch is
  // cached, so this only re-runs the conversion).
  if (changed && ccGuideIso) { renderGuideFx(ccGuideIso); renderGuideFares(ccGuideIso); }
  syncSubCur();   // newsletter currency pickers the reader hasn't touched follow it
}

function initHomeCur() {
  const sel = $("homeCur");
  if (!sel || sel.options.length > 1 || !lastRates) return;
  const codes = pickerCurrencies();
  sel.innerHTML = codes.map((c) => `<option value="${esc(c)}">${esc(curLabel(c))}</option>`).join("");
  const stored = localStorage.getItem("fx_homecur");
  const start = homeManual && codes.includes(stored) ? stored : homeCurAuto();
  sel.value = start;
  sel.onchange = () => setHomeCur(sel.value, sel.value !== homeCurAuto());
  setHomeCur(start, homeManual);
  enhanceSelect(sel);
}


function valueScores(iso, month, advMap, fares, anchorPl) {
  const plUS = priceLevel(iso);
  if (plUS == null) return null;                     // need affordability to rank
  // Affordability is measured against the traveler's HOME country, not the US:
  // for a US traveler anchorPl is 1 and nothing changes.
  const pl = plUS / (anchorPl || 1);
  const advLvl = advMap[iso];
  if (advLvl === 4) return null;                     // Do Not Travel: excluded outright
  // Unrated means unrated. This used to read as Level 2 and grade B, which put
  // Palestine — Level 4 by Germany's read, and unpublished by America's — into the
  // picks. Two governments now fill each other's gaps (see advisories.py); if
  // NEITHER rates a place we decline to recommend it rather than invent a level.
  // Costs Puerto Rico and a few uninhabited territories from the picks; that is
  // the price of not making safety claims we can't source.
  if (!advLvl) return null;
  // FX timing, judged in the chosen home currency's dataset and net of the
  // inflation gap (realFxPct). Neutral while that dataset loads, and when a
  // high-inflation country has no current figure to net it against.
  const fxi = fxInfo(iso);
  const fxReal = fxi ? fxi.real : null;
  const cl = climate && climate[iso];
  const wxKnown = !!(cl && cl.scores && cl.scores[month - 1] != null);

  const w = loadWeights();
  // Sub-scores (kept for tooltips/detail): cheapness maxes once prices are ~1/3
  // of home prices; FX maxes at +8% vs the 1-year average.
  const aff = clamp100(((1.3 - pl) / 0.95) * 100);
  const fx = fxReal != null ? clamp100(50 + fxReal * 6.25) : 50;
  const comps = {
    // Affordability = mostly structural cost of living, nudged by FX timing.
    afford: clamp100(aff * 0.7 + fx * 0.3),
    safe: advLvl ? { 1: 100, 2: 70, 3: 35 }[advLvl] : 70,
  };
  // No climate entry = no weather measure. It used to be a made-up 50 (a D pill)
  // averaged in, while the 3/4 mark said weather was left out.
  if (wxKnown) comps.wx = cl.scores[month - 1];
  // s.fare is the fare the traveller would pay — the cached average, or the
  // distance estimate (fareEst). The deal grade alone uses the version shrunk
  // toward the distance fit (dealPrices), so a one-route sample can't swing it.
  let fare = null, fareEst = false, fareBase = null, fareMin = null, dealRatio = null, flyBasis = null;
  // Flights, month first: the chosen month's fare against the route's own
  // typical range (the Flights tab's Low/Typical/High), where a route has
  // one — at the median 70 (B), 30% under 100, 30% over 40, the same slope
  // the distance measure uses. Poland read an "A" beside a strip showing
  // September its priciest month, because the grade was the all-months
  // average against a distance-typical fare. That measure stays the
  // fallback for routes with too few cached months (and says so).
  // Mirrors picks.py month_fare + _score.
  const mv = fares && flightValue && flightValue.origin === originIso() ? fareValue(iso, flightMonthKey(month)) : null;
  if (mv && mv.state === "ok") {
    fare = mv.price;
    comps.fly = clamp100(70 - mv.dev * 100);
    flyBasis = "month";
  } else if (fares && fares.prices[iso] != null) {
    flyBasis = "distance";
    fare = fares.prices[iso];
    fareEst = !!(fares.est && fares.est.has(iso));
    fareMin = fareEst ? null : (fares.mins && fares.mins[iso]) || null;
    fareBase = fares.expected ? fares.expected(iso) : null;
    const deal = fares.dealPrices ? fares.dealPrices[iso] : fare;
    if (fareBase) dealRatio = deal / fareBase;
    // Deal vs the typical fare for that distance: at baseline = 70 (B),
    // ~20% below = A, ~30% below = A+, ~20% above = D, ~40%+ above = F.
    // An estimate IS the baseline, so it scores a neutral 70 (flagged in the
    // coverage mark). It used to be graded like a real fare, and the
    // estimate's clamp to 1.4x the dearest known fare then read as a deal:
    // from Beijing (10 cached fares) Argentina, Chile and El Salvador showed
    // "~A+". Falls back to min-max cheapness with no fitted baseline.
    // Mirrors picks.py _score.
    comps.fly = fareEst ? 70
      : fareBase ? clamp100(70 + (1 - dealRatio) * 100)
      : fares.max > fares.min
        ? clamp100(((fares.max - deal) / (fares.max - fares.min)) * 100) : 50;
  }
  // Weighted mean over the components this country actually has.
  let num = 0, den = 0;
  for (const k in comps) { num += (w[k] || 0) * comps[k]; den += (w[k] || 0); }
  const value = den ? clamp100(num / den) : 0;
  return { iso, name: (cl && cl.name) || (ppp[iso] && ppp[iso].name) || iso,
           afford: comps.afford, safe: comps.safe, wx: wxKnown ? comps.wx : null,
           fly: comps.fly, fare, fareEst, fareMin, fareBase, dealRatio, flyBasis, advLvl, value,
           // Which dimensions this score is actually built on. A country with
           // no measure for something is averaged over the rest, so those carry
           // full weight and it can float above a country measured on four —
           // which is how three microstates outranked a country with a JFK
           // nonstop. The average was right; the row just never said it was
           // standing on less.
           wxMissing: !wxKnown,
           flyMissing: comps.fly == null && !!fares,
           pl, fx: fxReal, fxAdj: !!(fxi && fxi.adj) };
}

let valueMapMode = "score";
// Rank by follows the map mode into the tables: in weather mode the picks and
// gems sort on the Weather column. The list was ranked by comfort, then the
// tables quietly re-sorted it by Overall, so #1 was not the best-weather pick.
function syncRankSort() {
  const wx = valueMapMode === "weather";
  pickSort.key = gemSort.key = wx ? "weather" : "overall";
  // The Full ranking follows too: it used to stay sorted by value in Best
  // weather while bolding the Weather column. Only called on the toggle and a
  // shared link, so a column the reader sorts by hand is left alone.
  fullSort.key = wx ? "weather" : "value";
  pickSort.asc = gemSort.asc = fullSort.asc = false;
}
// The Rank-by toggle's look and its pressed state, from valueMapMode.
function markRankBy() {
  document.querySelectorAll("#valueMapMode button").forEach((b) => {
    const on = b.dataset.vm === valueMapMode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
}

// ---- fare estimation for countries the cached-fare API doesn't cover -------
// Travelpayouts only knows prices for recently-searched routes, so roughly half
// the world would show "—". We fit fare ~ distance on the known fares and fill
// the gaps with clearly-marked estimates.
let _centroids = null;
function countryCentroids() {
  if (_centroids || !worldGeo) return _centroids || {};
  _centroids = {};
  const inRing = (pt, ring) => {
    let inn = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > pt[1]) !== (yj > pt[1]) &&
          pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) inn = !inn;
    }
    return inn;
  };
  for (const f of worldGeo.features) {
    // The Northern Ireland subdivision carries iso "GB" (clicking it toggles
    // the whole-UK mark) — don't let it overwrite the real UK centroid.
    if (f.properties.sub && f.properties.iso === f.properties.sub) continue;
    // Area centroid of the LARGEST ring (the mainland). A plain vertex
    // average gets dragged toward vertex-dense coastlines — the US pin used
    // to land near Alaska and Canada's in the Arctic archipelago.
    let best = null, bestA = -1;
    const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
    for (const poly of polys) {
      const ring = poly[0];
      let a = 0;
      for (let i = 0; i < ring.length - 1; i++)
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
      a = Math.abs(a) / 2;
      if (a > bestA) { bestA = a; best = ring; }
    }
    if (!best) continue;
    let a2 = 0, cx = 0, cy = 0;                       // shoelace centroid
    for (let i = 0; i < best.length - 1; i++) {
      const cr = best[i][0] * best[i + 1][1] - best[i + 1][0] * best[i][1];
      a2 += cr;
      cx += (best[i][0] + best[i + 1][0]) * cr;
      cy += (best[i][1] + best[i + 1][1]) * cr;
    }
    if (!a2) continue;
    let c = [cx / (3 * a2), cy / (3 * a2)];
    // Concave shapes (Norway's fjord crescent, Croatia's banana, Vietnam's S)
    // can put the true centroid outside the land — nudge to the interior grid
    // point nearest the centroid so the pin always sits on the country.
    if (!inRing(c, best)) {
      let mnX = 999, mxX = -999, mnY = 999, mxY = -999;
      for (const pt of best) {
        if (pt[0] < mnX) mnX = pt[0];
        if (pt[0] > mxX) mxX = pt[0];
        if (pt[1] < mnY) mnY = pt[1];
        if (pt[1] > mxY) mxY = pt[1];
      }
      let bestPt = null, bestD = Infinity;
      const N = 16;
      for (let gy = 1; gy < N; gy++) for (let gx = 1; gx < N; gx++) {
        const p = [mnX + (mxX - mnX) * gx / N, mnY + (mxY - mnY) * gy / N];
        if (!inRing(p, best)) continue;
        const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2;
        if (d < bestD) { bestD = d; bestPt = p; }
      }
      if (bestPt) c = bestPt;
    }
    _centroids[f.properties.iso] = c;
  }
  // markable places with no map geometry still get a share-card pin
  if (!_centroids.BQ) _centroids.BQ = [-68.26, 12.18];   // Caribbean Netherlands (Bonaire)
  return _centroids;
}

// Max bounding-box span (degrees) per place — the "is its paint even visible
// at world scale?" test behind the pin/dot markers. No geometry -> no entry.
let _placeSpans = null;
function placeSpans() {
  if (_placeSpans || !worldGeo) return _placeSpans || {};
  _placeSpans = {};
  for (const f of worldGeo.features) {
    let mnX = 999, mxX = -999, mnY = 999, mxY = -999;
    const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
    for (const poly of polys) for (const ring of poly) for (const pt of ring) {
      if (pt[0] < mnX) mnX = pt[0];
      if (pt[0] > mxX) mxX = pt[0];
      if (pt[1] < mnY) mnY = pt[1];
      if (pt[1] > mxY) mxY = pt[1];
    }
    _placeSpans[f.properties.iso] = Math.max(mxX - mnX, mxY - mnY);
  }
  return _placeSpans;
}

function distKm(a, b) {
  const R = 6371, toR = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toR, dLon = (b[0] - a[0]) * toR;
  const s = Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * toR) * Math.cos(b[1] * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

// Returns { prices, dealPrices, mins, est:Set, min, max, expected } — known
// fares plus distance-based estimates for every mappable country, or null when
// no fare data is loaded. `prices` is what a traveller would pay (the cached
// average, or the estimate) — the budget, prompts and share cards read it.
// `dealPrices` is shrunk toward the fit and feeds only the deal grade. `mins`
// holds the cheapest cached fare per country. expected(iso) is the fitted
// "typical fare for that distance" — the baseline a real fare is judged
// against (deal vs ripoff).
function buildFareContext() {
  if (!(flightsData && flightsData.configured && flightsData.by_country)) return null;
  const prices = { ...flightsData.by_country };
  const dealPrices = { ...prices };
  const mins = {};
  for (const r of flightsData.countries || []) if (Number(r.min) > 0) mins[r.iso] = Number(r.min);
  const est = new Set();
  let expected = null;
  const C = countryCentroids();
  const o = C[flightsData.origin];
  const pts = Object.entries(prices)
    .filter(([iso]) => o && C[iso])
    .map(([iso, p]) => [distKm(o, C[iso]), p]);
  if (o && pts.length >= 8) {
    // least-squares fit: fare = a + b * distance
    const n = pts.length;
    const mx = pts.reduce((s, p) => s + p[0], 0) / n;
    const my = pts.reduce((s, p) => s + p[1], 0) / n;
    let num = 0, den = 0;
    for (const [x, y] of pts) { num += (x - mx) * (y - my); den += (x - mx) ** 2; }
    const b = den ? num / den : 0, a = my - b * mx;
    expected = (iso) => (C[iso] ? Math.max(50, a + b * distKm(o, C[iso])) : null);
    const known = Object.values(prices);
    const lo = Math.min(...known), hi = Math.max(...known) * 1.4;
    // Shrink thin evidence toward the distance baseline — for the DEAL grade
    // only. Half the covered countries stand on fewer than 5 sampled routes,
    // and an "average" of one route is just that itinerary — Croatia's only
    // sample is a 4-stop fare. Weight n/(n+3): one route keeps a quarter of its
    // own price, ten routes keep ~77%, a well-sampled country is untouched in
    // practice. The fit itself is over all ~114 points, so one outlier barely
    // bends the line it is being pulled toward. It never touches `prices`: a
    // shrunk $904 for a route cached at $542 once put Cameroon "out of reach"
    // of an $800 budget.
    const nBy = {};
    for (const r of flightsData.countries || []) nBy[r.iso] = r.n;
    for (const iso in dealPrices) {
      const e = C[iso] ? a + b * distKm(o, C[iso]) : null;
      if (e == null) continue;
      const wN = (nBy[iso] || 1) / ((nBy[iso] || 1) + 3);
      dealPrices[iso] = Math.round(wN * dealPrices[iso] + (1 - wN) * Math.max(50, e));
    }
    for (const iso in CUR_BY_ISO) {
      if (prices[iso] != null || !C[iso] || iso === flightsData.origin) continue;
      const e = a + b * distKm(o, C[iso]);
      prices[iso] = dealPrices[iso] = Math.round(Math.max(lo, Math.min(hi, e)));
      est.add(iso);
    }
  }
  const vals = Object.values(dealPrices);
  if (!vals.length) return null;
  return { prices, dealPrices, mins, est, min: Math.min(...vals), max: Math.max(...vals), expected };
}

let _vfSeq = 0;
async function loadValueFlights(silent) {
  const origin = originIso();
  const seq = ++_vfSeq;
  // The toasts talk about the Top Picks score — noise on a guide-first session.
  const say = !silent && loaded.value;
  try {
    const data = await getJSON("/api/flights?origin=" + encodeURIComponent(origin));
    // A slower response for an earlier origin (cold origins take longer) must
    // not land last and overwrite the current origin's fares.
    if (seq !== _vfSeq) return;
    if (!data.configured) {
      if (say) status("Flight prices need TRAVELPAYOUTS_TOKEN on the server — see the Flights tab.", "err");
    } else {
      flightsData = data;
      if (say) status(`Fares from ${data.origin_name || origin} folded into the score.`, "ok");
      // The month curves the grade prefers: the same payload the Flights tab
      // polls, fetched once here (no polling — a country still filling just
      // grades on the distance measure until the next render).
      if (!(flightValue && flightValue.origin === origin)) {
        getJSON("/api/flight-value?origin=" + encodeURIComponent(origin)).then((fv) => {
          if (seq !== _vfSeq || !fv || fv.configured === false || fv.origin !== origin) return;
          flightValue = fv;
          if (loaded.value) renderValue();
        }).catch(() => {});
      }
      // A guide opened before fares arrived rendered its fare strip against
      // nothing and stayed hidden — give it its data now.
      if (ccGuideIso) { renderGuideFares(ccGuideIso); renderGuideGrades(ccGuideIso); }
    }
  } catch (e) {
    if (seq !== _vfSeq) return;
    if (say) status("Could not load flights: " + e.message, "err");
  }
  // renderValue redraws the trip list too; a Trip-only session has no Top
  // Picks to render, but its rows' Flights links come from these fares.
  if (loaded.value) renderValue();
  else if (loaded.trip) renderTripBar();
}

// ---- searchable dropdowns (custom combobox over a native <select>) ---------
// Non-invasive: the native select stays the source of truth (existing .value /
// change logic is untouched); we overlay a type-to-filter input + list.
let _comboN = 0;   // unique list ids, for aria-controls / aria-activedescendant
function enhanceSelect(sel) {
  if (!sel || sel.dataset.combo || sel.options.length < 10) return;
  sel.dataset.combo = "1";
  const wrap = document.createElement("span");
  wrap.className = "combo";
  const input = document.createElement("input");
  input.type = "text"; input.className = "combo-input"; input.autocomplete = "off";
  input.setAttribute("role", "combobox"); input.placeholder = "Type to search…";
  input.setAttribute("aria-expanded", "false");
  // Accessible name: without one, every enhanced control announced only the
  // shared placeholder — nine identical "Type to search…" comboboxes. The
  // group's own label text (or the select's title/id) names each.
  // Only the long label variant: textContent of both responsive spans ran
  // together ("I'm going inWhen", "✈️ From✈️"), and emoji read as words.
  const pickLbl = sel.closest(".pickgroup") && sel.closest(".pickgroup").querySelector(".picklabel");
  const lblSrc = pickLbl && (pickLbl.querySelector(".lbl-lg") || pickLbl);
  const lblTxt = lblSrc ? lblSrc.textContent.replace(/[\p{Extended_Pictographic}\uFE0F]/gu, "").trim() : "";
  input.setAttribute("aria-label",
    lblTxt || sel.title || sel.getAttribute("aria-label") || sel.id || "search");
  const list = document.createElement("ul");
  list.className = "combo-list"; list.hidden = true;
  // A scrollable list is a Tab stop in Chrome: Tab from the input landed on
  // it, the input's blur then hid it, and focus fell to <body>. -1 keeps it
  // out of the Tab order, so Tab goes on to the next control. Options are
  // announced through aria-activedescendant while focus stays in the input.
  list.tabIndex = -1;
  list.id = "cl" + (++_comboN);
  list.setAttribute("role", "listbox");
  input.setAttribute("aria-controls", list.id);
  const setOpen = (open) => {
    list.hidden = !open; input.setAttribute("aria-expanded", String(open));
    if (!open) input.removeAttribute("aria-activedescendant");
  };
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(input); wrap.appendChild(list); wrap.appendChild(sel);
  sel.style.display = "none";
  let active = -1;
  const labelFor = () => { const o = sel.selectedOptions[0]; return o && o.value !== "" ? o.textContent.trim() : ""; };
  const sync = () => { if (document.activeElement !== input) input.value = labelFor(); };
  sel._sync = sync;
  const render = (q) => {
    q = (q || "").trim().toLowerCase();
    const opts = [...sel.options].filter((o) => o.value !== "" && o.textContent.toLowerCase().includes(q));
    list.innerHTML = opts.length
      ? opts.map((o, i) => `<li class="combo-opt" role="option" id="${list.id}-${i}" data-val="${esc(o.value)}">${esc(o.textContent.trim())}</li>`).join("")
      : '<li class="combo-opt muted" role="option" aria-disabled="true">No matches</li>';
    active = -1;
    // The ids were just reissued, so an old one would now name a different option.
    input.removeAttribute("aria-activedescendant");
  };
  // "change" only when the value moved (listeners re-render); "pick" on
  // every choice, for controls where re-picking the shown value means
  // something (the Flights month shows next month until one is chosen).
  const choose = (val) => {
    if (sel.value !== val) { sel.value = val; sel.dispatchEvent(new Event("change", { bubbles: true })); }
    sel.dispatchEvent(new Event("pick"));
    input.value = labelFor(); setOpen(false);
  };
  input.addEventListener("focus", () => { input.value = ""; render(""); setOpen(true); });
  input.addEventListener("input", () => { render(input.value); setOpen(true); });
  input.addEventListener("blur", () => setTimeout(() => { setOpen(false); input.value = labelFor(); }, 150));
  input.addEventListener("keydown", (e) => {
    const items = [...list.querySelectorAll(".combo-opt[data-val]")];
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, items.length - 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); }
    else if (e.key === "Enter") { e.preventDefault(); const pick = items[active] || (items.length === 1 ? items[0] : null); if (pick) choose(pick.dataset.val); return; }
    else if (e.key === "Escape") { setOpen(false); input.value = labelFor(); input.blur(); return; }
    else return;
    items.forEach((it, i) => it.classList.toggle("active", i === active));
    if (items[active]) {
      input.setAttribute("aria-activedescendant", items[active].id);
      items[active].scrollIntoView({ block: "nearest" });
    }
  });
  list.addEventListener("mousedown", (e) => {   // mousedown beats the input blur
    const li = e.target.closest(".combo-opt[data-val]");
    if (li) { e.preventDefault(); choose(li.dataset.val); }
  });
  new MutationObserver(sync).observe(sel, { childList: true });  // options rebuilt -> resync label
  // Programmatic picks that announce themselves (the guided picker's month)
  // left the box showing the old value while the page ranked for the new one.
  sel.addEventListener("change", sync);
  sync();
}
function resyncCombos() {
  document.querySelectorAll("select[data-combo]").forEach((s) => s._sync && s._sync());
}

function buildValueTab() {
  const reg = $("valueRegion"), mon = ensureMonthOptions();
  fillRegionSelect(reg);
  mon.onchange = renderValue;
  enhanceSelect(mon);
  // Fares auto-load for the home country (defaults to United States) and
  // reload whenever the user picks a different one — no button needed.
  fillOriginSelect($("valueOrigin"))
    .then(() => { enhanceSelect($("valueOrigin")); initHomeCur(); loadValueFlights(true); })
    .catch(() => {});
  $("valueOrigin").addEventListener("change", () => setTravelOrigin($("valueOrigin").value));
  $("pickCount").value = String(parseInt(localStorage.getItem("fx_pickcount") || "5", 10) || 5);
  $("pickCount").addEventListener("change", () => {
    localStorage.setItem("fx_pickcount", $("pickCount").value);
    renderValue();
  });
  // Budget + days. Persisted like the other filters, and re-rendered on `input`
  // rather than `change` so typing a figure updates the picks as you go.
  for (const [id, key] of [["budgetTotal", "wg_budget"], ["budgetDays", "wg_budgetdays"]]) {
    const el = $(id);
    if (!el) continue;
    const saved = localStorage.getItem(key);
    if (saved) el.value = saved;
    el.addEventListener("input", () => {
      localStorage.setItem(key, el.value);
      renderValue();
    });
  }
  const sf = localStorage.getItem("fx_safefloor");
  if (sf && ["a", "b", "any"].includes(sf)) $("safeFloor").value = sf;
  $("safeFloor").addEventListener("change", () => {
    localStorage.setItem("fx_safefloor", $("safeFloor").value);
    renderValue();
  });
  buildFactorChips();
  buildInterestChips();
  if ($("beenFilter")) {
    $("beenFilter").value = localStorage.getItem("wg_showvisited") === "1" ? "show" : "hide";
    $("beenFilter").addEventListener("change", () => {
      localStorage.setItem("wg_showvisited", $("beenFilter").value === "show" ? "1" : "0");
      renderValue();
    });
  }
  for (const b of document.querySelectorAll("#valueMapMode button")) {
    b.addEventListener("click", () => {
      valueMapMode = b.dataset.vm;
      markRankBy();
      syncRankSort();
      renderValue();
    });
  }
  buildWeightSliders();
  renderValue();
  // Data-backed popularity (tourist arrivals) loads in the background, then the
  // top/gems split re-renders with it — the fallback set covers the meantime.
  ensurePopularity().then(() => renderValue()).catch(() => {});
}

// ---- export shortlist as an AI prompt --------------------------------------
// Bridges the exploratory phase (this tool) to planning (the user's LLM):
// copies their preferences + shortlist as a ready-to-paste prompt.
let lastPicks = [], lastPicksMonth = null;
// The month Top Picks ranked by, else the travel month itself: a Trip landing
// never builds Top Picks, and /?tab=trip&vmn=3 showed October weather without
// this (#valueMonth already holds the link's vmn= by then).
function picksMonth() { return lastPicksMonth || parseInt(($("valueMonth") || {}).value, 10) || curMonth(); }
let lastGems = [];   // current hidden-gems list, for the 💎 surprise button

// ---- Trip builder -----------------------------------------------------------
// A working set for ONE trip, deliberately separate from the ★ wishlist. The
// wishlist is a lifetime list and can run to dozens of countries; feeding that
// into "plan my two weeks" produces mush. This is the three-to-eight you are
// actually choosing between. Persisted, because planning happens over weeks.
//
// Grouping is left to the AI on purpose. Which countries make one trip is not a
// geometry problem — it turns on flight connections, land borders, visas and
// season — and a distance-based clustering would produce tidy, travel-naive
// answers (splitting the Baltics from Poland on centroids, routing a Balkans
// loop through an awkward crossing). We hand over coordinates and let it judge.
let _trip = null;
let sharedTripView = null;   // {td, tm} while viewing a shared trip link
function loadTrip() {
  if (!_trip) {
    try { _trip = new Set(JSON.parse(localStorage.getItem("fx_trip") || "[]")); }
    catch (e) { _trip = new Set(); }
  }
  return _trip;
}
function saveTrip() {
  try { localStorage.setItem("fx_trip", JSON.stringify([...loadTrip()])); } catch (e) {}
}
function tripHas(iso) { return loadTrip().has(iso); }
function tripToggle(iso) {
  const t = loadTrip();
  if (t.has(iso)) t.delete(iso); else t.add(iso);
  saveTrip();
  renderTripBar();
  return t.has(iso);
}
function tripDays() {
  const el = $("tripDays");
  const n = el ? parseInt(el.value, 10) : NaN;
  return (n >= 1 && n <= 180) ? n : null;
}

// When you travel changes the answer more than where you start from, so the
// trip carries its own month rather than silently inheriting whichever month
// the Top Picks slider happens to sit on. Three states: unset follows the
// global month (the old behaviour, and right for someone who set the slider
// deliberately), 0 means flexible, 1-12 is an explicit pick. Flexible is the
// interesting one — it turns "is August any good for these" into "when should
// I go", which is the question most people with a shortlist actually have.
function tripMonth() {
  const el = $("tripMonth");
  const raw = el ? el.value : (localStorage.getItem("fx_tripmonth") || "");
  if (raw === "0") return { month: null, flexible: true };
  const n = parseInt(raw, 10);
  if (n >= 1 && n <= 12) return { month: n, flexible: false };
  return { month: picksMonth(), flexible: false };
}

// The cart badge and the Top Picks pointer. The basket itself lives in its own
// tab; these two just say it exists and has something in it, which is the part
// you need while browsing.
function renderTripBadge() {
  const t = loadTrip();
  const label = $("tripTabLabel");
  if (label) {
    label.innerHTML = "Trip" + (t.size ? '<span class="tripcount">' + t.size + "</span>" : "");
  }
  const peek = $("tripPeek");
  if (peek) {
    peek.hidden = !t.size;
    if (t.size) {
      peek.innerHTML = "🧳 <strong>" + t.size + "</strong> "
        + (t.size === 1 ? "country" : "countries") + " in your trip"
        + '<button type="button" id="tripPeekGo">View trip →</button>';
      const go = $("tripPeekGo");
      if (go) go.onclick = () => activateTab("trip", true);
    }
  }
}

function renderTripBar() {
  renderTripBadge();
  const host = $("tripBar");
  if (!host) return;
  const t = loadTrip();
  loadWishlist();
  const seedable = wishlist && wishlist.size && [...wishlist].some((i) => !t.has(i));
  const savedM = (sharedTripView && sharedTripView.tm != null ? sharedTripView.tm : localStorage.getItem("fx_tripmonth")) || "";
  if (!t.size) {
    // Empty state gets doors, not just directions: the owner read the text-only
    // version and still asked where to start. Two buttons jump straight to the
    // places countries actually live.
    host.innerHTML = '<span class="triphint">🧳 <strong>Your trip is empty.</strong> '
      + "Find a country and hit “Add to my trip” — every country you add gets booking "
      + "links for flights, stays and things to do.</span>"
      + '<div class="tripstart">'
      + '<button type="button" class="tripgo" id="tripGoPicks">🧭 Browse Top Picks</button>'
      + '<button type="button" class="tripgo" id="tripGoGuide">📅 Open the Travel Guide</button>'
      + (seedable ? '<button type="button" class="tripseed" id="tripSeed">★ Use my wishlist</button>' : "")
      + "</div>";
    const goP = $("tripGoPicks"), goG = $("tripGoGuide");
    if (goP) goP.onclick = () => activateTab("value", true);
    if (goG) goG.onclick = () => activateTab("guide", true);
  } else {
    // One line: "for [14] days in [October]". The count, the wishlist seed and
    // Clear moved to the list's header row (renderTripBook), and the chips
    // went: every country was listed twice, and the chips were the only way
    // to remove one. Each row now carries its own ×.
    host.innerHTML = '<div class="triphead">'
      + '<label class="tripdays">for <input id="tripDays" type="number" min="1" max="180" aria-label="Trip length in days" '
      // One trip length: a budget's "for N days" on Top Picks seeds this until
      // the trip has its own.
      + 'value="' + esc((sharedTripView && sharedTripView.td) || localStorage.getItem("fx_tripdays")
        || ($("budgetDays") || {}).value || localStorage.getItem("wg_budgetdays") || 14) + '" inputmode="numeric"> days</label>'
      + '<label class="tripmonth">in <select id="tripMonth" aria-label="Trip month">'
      + '<option value="0"' + (savedM === "0" ? " selected" : "") + ">I'm flexible</option>"
      + MONTHS.map((m, i) => '<option value="' + (i + 1) + '"'
        + ((savedM === "0" ? false : (parseInt(savedM, 10) || picksMonth()) === i + 1)
          ? " selected" : "") + ">" + m + "</option>").join("")
      + "</select></label></div>"
      + '<div class="tripbook" id="tripBook"></div>';
    renderTripBook([...t]);
  }
  bindTripActions();
  const days = $("tripDays");
  if (days) days.onchange = () => {
    sharedTripView = null;             // an edit makes the trip the recipient's own
    try { localStorage.setItem("fx_tripdays", String(tripDays() || 14)); } catch (e) {}
    refreshTripPrompt();
  };
  const mon = $("tripMonth");
  if (mon) mon.onchange = () => {
    sharedTripView = null;
    try { localStorage.setItem("fx_tripmonth", mon.value); } catch (e) {}
    refreshTripPrompt();
    renderTripBook([...loadTrip()]);   // stay links carry month-derived dates
  };
}
// The wishlist seed and Clear live in the list's header, which a month change
// re-renders on its own (renderTripBook), so they are bound from both.
function bindTripActions() {
  const seed = $("tripSeed");
  if (seed) seed.onclick = () => {
    loadWishlist().forEach((i) => loadTrip().add(i));
    // Top Picks only once it exists: a Trip landing never builds it.
    saveTrip(); renderTripBar(); if (loaded.value) renderValue();
  };
  const clr = $("tripClear");
  if (clr) clr.onclick = () => { loadTrip().clear(); saveTrip(); renderTripBar(); if (loaded.value) renderValue(); };
}
// A month's next occurrence as "YYYY-MM" — fareStripHTML's rule, so the price
// on a row is the cell its strip ticks.
function nextMonthKey(m) {
  const now = new Date();
  return (m > now.getMonth() ? now.getFullYear() : now.getFullYear() + 1) + "-" + String(m).padStart(2, "0");
}

// Booking links for the trip itself. The Trip tab is the one surface where
// the visitor has already told us where, how long, and when — which is the
// moment flights, stays and insurance actually get bought. Same partners and
// helpers as the guide pages (Aviasales marker, Stay22 Allez, Viator, EKTA);
// this only changes where they appear, not what they are. Dates come from the
// trip's own month, not the Top Picks slider.
function tripStayDates() {
  const month = tripMonth().month || picksMonth();
  const now = new Date();
  let y = now.getFullYear();
  if (month < now.getMonth() + 1) y++;
  let ci = new Date(y, month - 1, 15);
  // Same floor as stayDates: mid-month, the 15th is already in the past.
  const floor = new Date(now); floor.setDate(floor.getDate() + 3);
  if (ci < floor) ci = floor;
  const co = new Date(ci); co.setDate(co.getDate() + 3);
  const f = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
                   "-" + String(d.getDate()).padStart(2, "0");
  return { checkin: f(ci), checkout: f(co) };
}
function renderTripBook(isos) {
  const host = $("tripBook");
  if (!host) return;
  // Booking links name their country for screen readers ("Flights, Morocco
  // (new tab)"): a links list read four identical "Flights". The emoji and
  // the arrow are decoration.
  const A = (href, emo, label, whose) => '<a class="triplink" target="_blank" '
    + 'rel="sponsored nofollow noopener" href="' + href + '">'
    + (emo ? '<span aria-hidden="true">' + emo + "</span> " : "") + label
    + '<span class="vh">, ' + esc(whose) + " (new tab)</span>"
    + ' <span class="ext" aria-hidden="true">↗</span></a>';
  const tm = tripMonth();
  const m = tm.flexible ? null : tm.month;
  const key = m ? nextMonthKey(m) : null;
  const adv = advisoryByIso();
  loadWishlist();
  const seedable = wishlist && wishlist.size && [...wishlist].some((i) => !isos.includes(i));
  // The trip month's weather, as the other tables grade it (climate comfort
  // for that month), so the month select shows what it changes. Nothing in
  // flexible mode: there is no month to grade.
  const wxPill = (iso) => {
    if (!m || !climate) return "";
    const cl = climate[iso];
    const sc = cl && cl.scores ? cl.scores[m - 1] : null;
    if (sc == null) return '<span class="gr grx" data-tip="No weather data" title="">—</span>';
    const seas = seasons(cl.scores)[m - 1];
    const tip = MONTHS[m - 1] + " weather: comfort " + sc + "/100 · "
      + (seasonCaveat(seas, !!(cl.best && cl.best.includes(m)), hazardsFor(iso, m).length > 0) || SEASON_WX[seas]);
    return '<span class="gr ' + gradeCls(grade(sc)) + '" role="img" aria-label="' + esc(MONTHS[m - 1] + " weather " + grade(sc))
      + '" data-tip="' + esc(tip) + '" title="">' + grade(sc) + "</span>";
  };
  const hdr = '<div class="tbrow tbhdr">'
    + '<span class="tbn">' + isos.length + " " + (isos.length === 1 ? "country" : "countries") + "</span>"
    + '<span class="tbwx">' + (m ? '<span aria-hidden="true">🌤️</span><span class="vh">' + MONTHS[m - 1] + " weather</span>" : "") + "</span>"
    + '<span class="tbfare"><span aria-hidden="true">✈️</span><span class="thw"> Fares by month</span>'
    + '<span class="muted" data-tip="' + esc("Cheapest cached round trip from " + originLabel() + " each month, January to December"
      + (m ? "; " + MONTHS[m - 1] + " is ticked and priced" : "") + ". Cached searches (Aviasales), not live prices.")
    + '" title=""> ⓘ</span></span>'
    + '<span class="tbacts">' + (seedable ? '<button type="button" class="tripseed" id="tripSeed">+ my ★ wishlist</button>' : "")
    + '<button type="button" class="tripseed" id="tripClear">Clear</button></span></div>';
  const rows = isos.map((iso) => {
    const name = countryName(iso);
    const fr = flightsData && flightsData.countries
      ? flightsData.countries.find((r) => r.iso === iso) : null;
    // The trip month's search, not the default ~60 days out: the row now
    // says "Oct USD 608", and its Flights link has to mean October.
    const lvl = adv[iso] || (ADV_PARENT[iso] && adv[ADV_PARENT[iso]]) || 0;
    // No booking links for a "Level 4 — do not travel" country (the guide's
    // rule); its ⚠️ still says why.
    const fu = lvl < 4 && fr && fr.dest ? flightSearchURL(fr.dest, key) : null;
    const links = [];
    if (fu) links.push(A(fu, "✈️", "Flights", name).replace('class="triplink"', 'class="triplink tbfly"'));
    // Stay link needs coordinates that load async; the span keeps the row's
    // shape until the fill swaps it for the real anchor.
    if (lvl < 4) {
      links.push('<span class="tbstay" data-iso="' + iso + '"></span>');
      links.push(A(viatorURL(name), "🎟️", "Things to do", name));
    }
    // Level 3-4: the table's ⚠️ exception mark.
    const warn = lvl >= 3 ? ' <span class="hzmark" data-tip="' + esc(advLevelText(iso, lvl) + advVia(iso)) + '" title="">⚠️</span>' : "";
    return '<div class="tbrow" data-iso="' + iso + '">'
      + '<span class="tbn"><a class="tbdest" href="' + esc(guidePath(iso)) + '"><span aria-hidden="true">' + flagEmoji(iso)
      + "</span> " + esc(name) + "</a>" + warn + "</span>"
      + '<span class="tbwx">' + wxPill(iso) + "</span>"
      + '<span class="tbfare" data-iso="' + iso + '"><span class="farestrip empty" aria-hidden="true"></span></span>'
      + '<span class="tblinks">' + links.join("") + "</span>"
      + '<button type="button" class="tbx" data-iso="' + iso + '" aria-label="' + esc("Remove " + name + " from the trip")
      + '" title="' + esc("Remove " + name) + '">×</button></div>';
  }).join("");
  // 🧳, not 🛡️: 🛡️ means Safety everywhere else on the site.
  host.innerHTML = hdr + rows
    + '<div class="tbrow tbins"><span class="tbn">🧳 The whole trip</span>'
    + '<span class="tblinks">' + A(insuranceHref(isos[0] || "US"), "", "Travel insurance (EKTA)", "whole trip") + "</span></div>"
    + '<p class="affnote">These earn us a commission at no extra cost to you — it’s what keeps the site free.</p>';
  bindTripActions();
  host.querySelectorAll(".tbx").forEach((b) => b.addEventListener("click", () => {
    const all = [...host.querySelectorAll(".tbx")];
    const at = all.indexOf(b);
    tripToggle(b.dataset.iso);
    if (loaded.value) renderValue();
    // Focus goes to the next row's ×, not to <body>.
    const next = [...document.querySelectorAll("#tripBook .tbx")];
    const f = next[Math.min(at, next.length - 1)] || $("tripDays") || $("tripGoPicks");
    if (f) f.focus();
  }));
  // Each row's fare cell: the trip month's own price first ("Oct USD 608"),
  // then the strip with that month ticked, and the cheapest month only when
  // it is another one. A route too sparse for a strip still gets its month's
  // price. Currency is the reader's (fareStripOpts).
  const o = fareStripOpts(m);
  isos.forEach(async (iso2) => {
    const fm = await ensureFareMonths(iso2);
    const slot = host.querySelector('.tbfare[data-iso="' + iso2 + '"]');
    if (!fm || !fm.months || !slot || !slot.isConnected) return;
    const strip = fareStripHTML(fm.months, o);
    const rec = key ? fm.months[key] : null;
    const bits = [];
    if (rec) bits.push('<b>' + MON_ABBR[m - 1] + "</b> " + fareMoney(rec.price, o.cur, o.conv));
    if (strip && strip.cheapMon !== m) bits.push('<span class="tblow">' + (rec ? " · " : "") + "low "
      + MON_ABBR[strip.cheapMon - 1] + " " + fareMoney(strip.cheapPrice, o.cur, o.conv) + "</span>");
    slot.innerHTML = (strip
      ? '<span class="farestrip" role="img" aria-label="' + esc("Round-trip fares from " + originLabel() + " by month — " + strip.note) + '">' + strip.cells + "</span>"
      : '<span class="farestrip empty" aria-hidden="true"></span>')
      + (bits.length ? '<span class="tbfarenote">' + bits.join("") + "</span>" : "");
    // The month's fare may be to another airport (Morocco: CMN in October,
    // RAK in November); the Flights link searches the one that has the price.
    if (rec && rec.dest) {
      const fl = slot.closest(".tbrow").querySelector("a.tbfly");
      const u = flightSearchURL(rec.dest, key);
      if (fl && u) fl.href = u;
    }
  });
  ensureStayCoords().then((cc) => {
    const { checkin, checkout } = tripStayDates();
    host.querySelectorAll(".tbstay").forEach((el) => {
      let spots = cc[el.dataset.iso];
      if (spots && !Array.isArray(spots)) spots = [{ n: spots.near, ll: spots.ll }];
      const sp = spots && spots.filter((s) => s && s.ll)[0];
      if (!sp) { el.remove(); return; }
      el.outerHTML = A("https://www.stay22.com/allez/booking?aid=" + STAY22_AID
        + "&lat=" + sp.ll[0] + "&lng=" + sp.ll[1]
        + "&checkin=" + checkin + "&checkout=" + checkout, "🏨", "Stays", countryName(el.dataset.iso));
    });
  }).catch(() => {});
}

// Days and month both sit above the prompt box, so once the box is open you
// can see it not changing. Rebuild it in place — but only if it is already
// open, since generating it is what the plan button is for.
function refreshTripPrompt() {
  const p = $("tripPanel");
  if (p && !p.hidden && p.innerHTML) renderAIPanel(p, buildTripAIPrompt());
}

// The trip prompt. Everything the model cannot look up goes in: coordinates so
// it can reason about routing, the season fit for the chosen month, the local
// price level, and the visa position for this passport.
function buildTripAIPrompt() {
  const t = [...loadTrip()];
  const tm = tripMonth();
  const flexible = tm.flexible;
  const month = tm.month || picksMonth();
  const monthName = MONTHS[month - 1];
  const days = tripDays() || 14;
  const originName = originLabel();
  const passport = guidePassport();
  const cen = countryCentroids();
  const A = plAnchor(originIso()), anchorPl = A.pl;   // US fallback when home has no price level

  const lines = [];
  lines.push("I have " + days + " days"
    + (flexible ? " and I'm flexible on when to go — help me pick the month"
                : " in " + monthName)
    + ", travelling from " + originName
    + ", and a shortlist of countries I'm interested in. I used a travel-value tool (WanderGrade) "
    + "for the underlying data — use what's below, don't re-derive it.");
  // The currency every figure below is in, and the budget if one was set on
  // Top Picks: the model was asked for a daily budget with no currency named.
  const bud = budgetOf();
  lines.push("MY MONEY: " + bud.cur + (bud.entered
    ? "; budget " + bud.cur + " " + Math.round(bud.entered).toLocaleString() + " all-in for the whole trip" : ""));
  lines.push("");
  lines.push("MY SHORTLIST (" + t.length + (t.length === 1 ? " country, " : " countries, ") + days + " days total):");
  t.forEach((iso) => {
    const bits = [];
    const c = cen[iso];
    // Round first, then pick the hemisphere: -0.3 is 0°N, not "-0°S".
    if (c) {
      const lat = Math.round(c[1]), lon = Math.round(c[0]);
      bits.push("approx " + Math.abs(lat) + "°" + (lat >= 0 ? "N" : "S")
        + ", " + Math.abs(lon) + "°" + (lon >= 0 ? "E" : "W"));
    }
    const reg = REGIONS[ISO_REGION[iso]];
    if (reg) bits.push(reg);
    const cl = climate && climate[iso];
    if (cl) {
      // Fixed month: how this country scores in it. Flexible: the whole shape
      // of the year, since the model is choosing the month rather than judging
      // one — worst months matter as much as best when it has to find overlap.
      if (!flexible) {
        const s = seasons(cl.scores)[month - 1];
        bits.push(monthName + ": " + SEASON_WX[s] + " for weather");
      } else {
        const ss = seasons(cl.scores);
        const off = ss.map((s, i) => (s === "off" ? i + 1 : 0)).filter(Boolean);
        if (off.length) bits.push("least comfy weather " + monthSpan(off));
      }
      if (cl.best && cl.best.length) bits.push("best months " + cl.best.map((m) => MON_ABBR[m - 1]).join("/"));
    }
    const plIso = GUIDE_PARENT[iso] || iso;       // England etc: the UK's figure
    const pl = priceLevel(plIso);
    // Same framing as the table's pill, and the yardstick named: "your 100 ≈
    // 134 there" said neither what 100 nor 134 was, and a model can read it
    // as an exchange rate.
    if (pl) bits.push("prices " + plPhrase(pl / anchorPl, A.name)
      + (plIso !== iso ? " (" + parentWide(plIso) + ")" : ""));
    // The cached average round trip from home, in the budget's money — the
    // level the daily budget has to be worked out from; the trip list shows
    // the reader the month curve.
    const fare = flightsData && flightsData.by_country && flightsData.by_country[iso];
    if (fare > 0) bits.push("return flights avg ~" + fmtBC(fare));
    const vi = visaInfo(iso, passport);
    if (vi && vi.meta) bits.push("visa: " + vi.meta.long);
    // Curated first-visit range. This is what lets the model refuse a cramped
    // plan with numbers instead of vibes — "your five countries want 23 days
    // minimum and you have 10" beats a polite paragraph about pacing.
    const dm = activities && activities[iso] && activities[iso].days;
    if (dm) bits.push("worth " + dm[0] + "-" + dm[1] + " days on a first visit");
    // Fixed month: only what bites in that month. Flexible: every seasonal
    // hazard with the months it covers, so the model can route around cyclone
    // or monsoon season instead of being told about it after the fact.
    const hz = flexible
      ? ((activities && activities[iso] && activities[iso].hazards) || [])
          .map((h) => h.note + (h.months && h.months.length < 12 ? " (" + monthSpan(h.months) + ")" : ""))
      : hazardsFor(iso, month).map((h) => h.note);
    if (hz.length) bits.push("heads-up: " + hz.join("; "));
    lines.push("- " + countryName(iso) + " — " + bits.join(" · "));
  });
  const beenOwn = ownVisited();   // not a shared map that happens to be open
  if (beenOwn.size) {
    lines.push("");
    lines.push("ALREADY BEEN (fine to route through, don't build days around): "
      + [...beenOwn].map(countryName).join(", "));
  }
  lines.push("");
  lines.push("PLEASE:");
  lines.push("- Group these into realistic trips using the coordinates above — countries that genuinely combine into one route, not just ones that are near each other. Consider flight connections, land borders and border crossings, and whether the visas work together.");
  lines.push("- Name each trip the way a traveller would (\"Balkans loop\", \"Benelux + Rhine\", \"Northern Vietnam & Laos\").");
  // The honest-failure instruction. Without it the model will cheerfully cram
  // every country in and hand back an itinerary that reads fine and would be
  // miserable to actually travel.
  // The sum the model should be doing anyway, done for it — and for the user,
  // who sees the arithmetic of an overstuffed shortlist before any AI does.
  const mins = t.map((iso) => activities && activities[iso] && activities[iso].days)
    .filter(Boolean).reduce((s2, d) => s2 + d[0], 0);
  lines.push("- BE HONEST ABOUT WHAT DOESN'T FIT. If " + days + " days can't cover this shortlist well, say so plainly: tell me which countries make the best single trip, which should wait for another one, and what the minimum sensible number of days would be for the rest. I would much rather drop countries than rush them."
    + (mins ? " (The first-visit minimums above already sum to " + mins + " days against my " + days + ".)" : ""));
  lines.push("- For the trip you recommend first: a day-by-day outline, rough travel times between places, and where to fly into and out of.");
  lines.push("- Give a daily budget range (budget / mid-range / comfortable) using the price figures above rather than generic assumptions.");
  if (flexible) {
    // The whole point of the flexible mode: make the model commit to a window
    // rather than hedge across the year. It has best months, off months and
    // dated hazards for every country above, so it can.
    lines.push("- TELL ME WHEN TO GO. For each trip you propose, name the specific month — or a two-week window — that works best across the countries in it, and say why using the best months and least-comfy months above. Give a second-choice window too.");
    lines.push("- If no single month suits the whole group, say so and split it: which countries belong in a trip at one time of year and which in another. Don't average the year into a compromise month that is mediocre everywhere.");
    lines.push("- Flag anything where timing is the deciding factor — a hazard season, a short comfy-weather window, or prices that swing hard between seasons.");
  } else {
    lines.push("- Use the " + monthName + " season notes: if it's one of a country's least comfy months or has a heads-up, say whether to reorder, swap it out, or accept the trade.");
  }
  lines.push("");
  lines.push("Then end with the 2-3 questions that would most change this plan, so I can refine it with you.");
  lines.push("");
  lines.push("Source: WanderGrade — " + SITE_ORIGIN + "/");
  return lines.join("\n");
}

// UNREFERENCED as of 2026-08-13. This built a prompt from the algorithmic top
// ten, behind a "Plan these with AI" button in Top Picks. Removed because it
// wore the same label as the Trip tab's plan button while doing a different
// job, so the two read as one feature duplicated — and nobody travels to a
// top-ten list. The ranked table answers "which of these" better than a prompt.
// Kept rather than deleted because it is a working exploratory prompt if that
// idea ever comes back with its own name; delete it freely if it never does.
function buildAIPrompt() {
  const month = lastPicksMonth || curMonth();
  const originName = originLabel();
  const region = regionSel;
  // What they care about = the counted factors weighted High.
  const p = loadPriorities();
  const careMap = { afford: "affordability (low prices & strong currency)", safe: "safety",
                    wx: "good weather", fly: "cheap flights" };
  const cares = WEIGHT_DEFS.filter((w) => p[w.key] === "high" && loadFactors().includes(w.key))
    .map((w) => careMap[w.key]);
  const monthName = MONTHS[month - 1];
  const passport = guidePassport();
  const lines = [];
  lines.push("I'm in the early, exploratory phase of planning a trip and used a travel-value tool to shortlist destinations. Below is everything it already gave me — use it (don't re-derive it) to help me turn this into a plan.");
  lines.push("");
  lines.push("WHEN: " + monthName);
  lines.push("FROM: " + originName + (homeBase !== "USD" ? " (budgeting in " + homeBase + ")" : ""));
  if (region !== "all") lines.push("REGION: " + (REGIONS[region] || region));
  if (cares.length) lines.push("I CARE MOST ABOUT: " + cares.join(", "));
  loadWishlist();
  if (wishlist.size) lines.push("ON MY WISHLIST: " + [...wishlist].map(countryName).join(", "));
  const beenOwn = ownVisited();
  if (beenOwn.size) lines.push("ALREADY BEEN (skip): " + [...beenOwn].map(countryName).join(", "));
  lines.push("");
  lines.push("SHORTLIST (best value first; grades are A+ to F):");
  lastPicks.forEach((s, i) => {
    const cl = climate && climate[s.iso];
    const seas = cl ? seasons(cl.scores)[month - 1] : null;
    const best = cl && cl.best && cl.best.length ? cl.best.map((m) => MON_ABBR[m - 1]).join(", ") : null;
    const hz = hazardsFor(s.iso, month).map((h) => h.note);
    const acts = (activities && activities[s.iso] && activities[s.iso].activities) || [];
    const vi = visaInfo(s.iso, passport);
    // Affordability in plain words.
    let aff = "";
    if (s.pl != null) aff = "prices " + plPhrase(s.pl, plHomeWord());
    if (s.fx != null && Math.abs(s.fx) >= 2)
      aff += ` (${homeBase} ${signedPct(Math.round(s.fx))} vs its 1-yr avg${s.fxAdj ? ", after inflation" : ""})`;
    // The same basis as the Flights pill, so the words can't disagree with it:
    // the month's fare vs the route's usual, or the year-round fare for the
    // distance where a route has too few cached months.
    const fl = s.flyBasis === "month"
      ? (s.fly >= 80 ? "cheaper than this route's usual for " : s.fly <= 60 ? "pricier than this route's usual for "
         : "about this route's usual for ") + MONTHS[month - 1]
      : (s.dealRatio != null && !s.fareEst)
      ? (s.dealRatio <= 0.95 ? "cheaper than usual for the distance"
         : s.dealRatio >= 1.05 ? "pricier than usual for the distance" : "about average for the distance")
      : null;
    lines.push(`${i + 1}. ${s.name} — overall ${grade(s.value)}`);
    if (aff) lines.push(`   - Affordability ${grade(s.afford)}: ${aff}`);
    // Whose words they are, too: "“No warning”" alone doesn't say it's Germany's.
    lines.push(`   - Safety: ${s.advLvl ? advLevelText(s.iso, s.advLvl) + advVia(s.iso) : "no current advisory"}`);
    // visaInfo returns {home: true} with no meta for the passport's own
    // country (the US in Top Picks for a US reader): it crashed the prompt.
    if (vi && vi.meta) lines.push(`   - Visa (${passport === "US" ? "US" : countryName(passport)} passport): ${vi.meta.long}${vi.note ? " — " + vi.note : ""}`);
    if (best) lines.push(`   - Best months: ${best}; ${monthName}: ${SEASON_WX[seas] || "no data"} for weather`);
    if (hz.length) lines.push(`   - ${monthName} heads-up: ${hz.join("; ")}`);
    if (acts.length) lines.push(`   - Known for: ${acts.map(actLabel).filter(Boolean).join("; ")}`);
    if (fl) lines.push(`   - Flights: ${fl}`);
  });
  lines.push("");
  lines.push("USING THE ABOVE, please:");
  lines.push("- Narrow to the 2–3 that best fit what I care about, and say why");
  lines.push("- For each, recommend specific cities/regions and how many days");
  lines.push("- Estimate a rough daily budget and total trip cost from " + originName);
  lines.push("- Draft a day-by-day itinerary for your top pick");
  lines.push("- Tell me when to book flights and where to stay");
  lines.push("");
  lines.push("These grades are from WanderGrade: " + SITE_ORIGIN + "/?vmn=" + month);
  return lines.join("\n");
}
// Shared AI panel: shows the prompt with Copy / Open in ChatGPT / Open in
// Claude. Used by both the Top Picks shortlist export and the Travel Guide
// per-country button so they behave identically.
function renderAIPanel(host, prompt) {
  if (!host) return;
  const cg = "https://chatgpt.com/?q=" + encodeURIComponent(prompt);
  const cla = "https://claude.ai/new?q=" + encodeURIComponent(prompt);
  const px = "https://www.perplexity.ai/search?q=" + encodeURIComponent(prompt);
  // Grok verified 2026-08-15: grok.com/?q= prefills the composer even logged
  // out. The others were checked and rejected: Copilot ignores ?q=, Gemini has
  // no public prefill URL at all, Mistral has none documented. A button that
  // opens an empty chat is worse than no button — those stay on the paste path.
  const gk = "https://grok.com/?q=" + encodeURIComponent(prompt);
  host.hidden = false;
  host.innerHTML =
    '<div class="airow">'
    + '<button type="button" class="aiact" data-act="copy">📋 Copy prompt</button>'
    + '<a class="aiact" href="' + cg + '" target="_blank" rel="noopener">Open in ChatGPT ↗</a>'
    + '<a class="aiact" href="' + cla + '" target="_blank" rel="noopener">Open in Claude ↗</a>'
    + '<a class="aiact" href="' + gk + '" target="_blank" rel="noopener">Open in Grok ↗</a>'
    + '<a class="aiact" href="' + px + '" target="_blank" rel="noopener">Open in Perplexity ↗</a>'
    + '</div>'
    + '<textarea class="aitext" readonly rows="9">' + esc(prompt) + '</textarea>'
    + '<p class="hint">“Copy prompt” grabs the full version — paste into ChatGPT, Claude, Grok, Perplexity, or any AI. The buttons open a new chat with it pre-filled.</p>';
  host.querySelector('[data-act="copy"]').onclick = () => copyText(prompt);
  // Also copy when opening an AI, so the full prompt is ready to paste if the
  // pre-fill link is truncated by length limits.
  host.querySelectorAll("a.aiact").forEach((el) =>
    el.addEventListener("click", () => copyText(prompt, true)));
  host.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "nearest" });
}


// Shared clipboard helper (secure-context API + execCommand fallback).
async function copyText(text, quiet) {
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch (e) {}
  if (!ok) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      ok = document.execCommand("copy"); document.body.removeChild(ta);
    } catch (e) {}
  }
  if (!quiet) status(ok ? "Copied! Paste into any AI to plan your trip. 🤖"
                        : "Couldn't copy — select the text and ⌘C.", ok ? "ok" : "err");
  return ok;
}

// ---- Travel Guide: per-country "Plan with AI" -------------------------------
// A guide-native rich prompt (seasonality, visa, activities, hazards) the reader
// can copy or fire straight into ChatGPT/Claude. The monthly email links here
// (?tab=guide&gc=ISO&ai=1) so the AI hand-off keeps people on the site.
function buildCountryAIPrompt(iso) {
  // Prefer the chosen travel month (set by ?vmn= from the email link or the
  // Top Picks selector), else the last picks month, else the current month.
  const vm = parseInt(($("valueMonth") || {}).value, 10);
  const month = (vm >= 1 && vm <= 12) ? vm : (lastPicksMonth || curMonth());
  const monthName = MONTHS[month - 1];
  const passport = guidePassport();
  const name = countryName(iso);
  const cl = climate && climate[iso];
  const seas = cl ? seasons(cl.scores)[month - 1] : null;
  const best = cl && cl.best && cl.best.length ? cl.best.map((m) => MON_ABBR[m - 1]).join(", ") : null;
  const hz = hazardsFor(iso, month).map((h) => h.note);
  const a = activities && activities[iso];
  const acts = (a && a.activities) || [];
  const prof = (a && a.profile) || [];
  const vi = visaInfo(iso, passport);
  const originName = originLabel();

  const lines = [];
  lines.push("I'm planning a trip to " + name + " and used a travel-value tool (WanderGrade) for the basics. Use the info below (don't re-derive it) to help me build a plan.");
  lines.push("");
  lines.push("DESTINATION: " + name);
  lines.push("WHEN: " + monthName);
  lines.push("FROM: " + originName + (homeBase !== "USD" ? " (budgeting in " + homeBase + ")" : ""));
  if (prof.length) lines.push("KNOWN FOR: " + prof.join(", "));
  if (vi && vi.meta) lines.push("VISA (" + passportLabel(passport) + "): " + vi.meta.long + (vi.note ? " — " + vi.note : ""));
  if (best) lines.push("BEST MONTHS: " + best + "; " + monthName + ": "
    + (seasonCaveat(seas, cl.best.includes(month), hz.length > 0) || (SEASON_WX[seas] || "no data") + " for weather"));
  if (hz.length) lines.push(monthName + " HEADS-UP: " + hz.join("; "));
  if (acts.length) lines.push("HIGHLIGHTS: " + acts.map(actLabel).filter(Boolean).join("; "));
  // The cost line is the whole reason this prompt beats asking an AI cold: it
  // is the one number here the model cannot look up and would otherwise guess.
  // The same sentence the guide page and the share card show (localPricesText):
  // against the traveller's own home prices, the US only as a named fallback.
  const lp = localPricesText(iso);
  if (lp) lines.push("LOCAL PRICES: " + lp
    + ". National averages for residents; tourist areas and foreigner rent run well above this.");
  try {
    const fc = buildFareContext();
    const f = fc && fc.prices && fc.prices[iso];
    if (f != null) {
      // In the currency the FROM line says the reader budgets in; fares are
      // cached in dollars, so a rate must have loaded — US$ only when none has.
      const k = homeBase === "USD" ? 1 : rateForCurrency(homeBase);
      const amt = k ? "about " + Math.round(f * k).toLocaleString("en-US") + " " + homeBase
                    : "about US$" + Math.round(f).toLocaleString("en-US");
      lines.push("TYPICAL ROUND-TRIP FLIGHT: " + amt + " from " + originName
        + (fc.est && fc.est.has && fc.est.has(iso) ? " (distance-based estimate)" : " (recently seen fares)"));
    }
  } catch (e) { /* fares are a bonus; never block the prompt on them */ }

  lines.push("");
  lines.push("USING THE ABOVE, please:");
  lines.push("- Recommend specific cities/regions and how many days in each, with rough travel times between them");
  lines.push("- Draft a day-by-day itinerary. Assume about 7 days unless I say otherwise — and tell me if this country really wants more or less");
  lines.push("- Base the budget on the LOCAL PRICES figure above rather than generic assumptions, and give me a daily range for budget / mid-range / comfortable");
  lines.push("- Tell me when to book flights and which neighbourhoods to stay in, and why those ones");
  lines.push("- Work the " + monthName + " season notes above (weather, any heads-up) into the timing and pacing");
  lines.push("- Flag anything that needs booking well ahead, or any permit/reservation I could miss");
  // A confident plan built on guessed preferences is worth less than a decent
  // plan plus the questions that would fix it. This is a starting point.
  lines.push("");
  lines.push("Then end with the 2-3 questions that would most change this plan — budget, pace, who I'm travelling with, what I actually care about — so I can refine it with you.");
  lines.push("");
  lines.push("Source: WanderGrade — " + SITE_ORIGIN + guidePath(iso));
  return lines.join("\n");
}

function renderGuideAI(iso) {
  const host = $("guideAI");
  if (!host) return;
  const name = countryName(iso);
  // The button alone reads as "an AI writes your trip", which is not what this
  // does and oversells it. It writes the *prompt* — with the month, the visa
  // rules for your passport, the season, and the local price level already
  // filled in — and hands it to whichever AI you use. Saying so is both more
  // honest and more appealing than the vague version.
  // The trip toggle lives here rather than in the ranked row. A row already
  // navigates to this page, and two document-level handlers open the guide from
  // a row click — a button inside one fights both of them and still loses. Here
  // the flow reads straight through: row -> guide -> add it, no interception.
  host.innerHTML = '<button id="guideTripBtn" type="button" class="tripbtn'
    + (tripHas(iso) ? " on" : "") + '" title="'
    + (tripHas(iso) ? "Remove " + esc(name) + " from your trip"
                    : "Add " + esc(name) + " to the trip you're building") + '">'
    + (tripHas(iso) ? "🧳 On your trip — remove" : "🧳 Add " + esc(name) + " to my trip")
    + "</button>"
    + '<button id="guideAIBtn" type="button" class="aibtn"'
    + ' title="Writes the prompt for you — ' + esc(name)
    + '\'s season, visa rules and local prices already filled in.'
    + ' Copy it, or open it in ChatGPT, Claude, Grok or Perplexity.">'
    + '✨ Plan ' + esc(name) + ' with AI →</button>'
    + '<div id="guideAIPanel" class="aipanel" hidden></div>';
  $("guideAIBtn").onclick = () => openGuideAI(iso);
  $("guideTripBtn").onclick = () => {
    tripToggle(iso);
    renderGuideAI(iso);                       // relabel in place
    if (loaded.value) renderValue();          // keep the Top Picks trip bar in step
    status(tripHas(iso) ? "Added to your trip 🧳 — open the Trip tab to plan it."
                        : "Removed from your trip.", "ok");
  };
}

async function openGuideAI(iso) {
  // Non-US passports need the visa matrix for the visa line — load it first.
  if (guidePassport() !== "US") await ensureVisaMatrix().catch(() => {});
  renderAIPanel($("guideAIPanel"), buildCountryAIPrompt(iso));
}

// ---- top picks: report-card grade table -------------------------------------
// ---- markable places beyond ISO countries ------------------------------------
// House rule (traveler feedback): if it has a flag emoji, it gets its own mark.
// Kosovo, Antarctica, the Caribbean territories, and the UK home nations are
// all markable on the Wander List. Most don't participate in scoring (no
// price data); the ones with climate data also have a full guide page.
const EXTRA_PLACES = {
  "XK": "Kosovo", "AQ": "Antarctica", "PR": "Puerto Rico", "GU": "Guam",
  "VI": "U.S. Virgin Islands", "AW": "Aruba", "CW": "Curaçao",
  "SX": "Sint Maarten", "GB-ENG": "England", "GB-SCT": "Scotland",
  "GB-WLS": "Wales", "GS": "South Georgia", "FK": "Falkland Islands",
};
// UN members + popular flag territories that sit outside the scored currency
// dataset (mostly small island nations): markable on the Wander List. Names
// resolve through Intl.DisplayNames; continents from the map below.
const MORE_PLACES = ("AG DM GD KN LC VC KY TC BM VG AI MV SL SS ST " +
  "KI NR WS TO TV PF NC CK").split(" ");
// continent buckets for the extras (AN unlocks the 7-continent achievement)
const EXTRA_CONTINENT = {
  "XK": "EU", "AQ": "AN", "PR": "NA", "GU": "OC", "VI": "NA", "AW": "NA",
  "CW": "NA", "SX": "NA", "GB-ENG": "EU", "GB-SCT": "EU", "GB-WLS": "EU",
  "AG": "NA", "DM": "NA", "GD": "NA", "KN": "NA", "LC": "NA", "VC": "NA",
  "KY": "NA", "TC": "NA", "BM": "NA", "VG": "NA", "AI": "NA",
  "MV": "AS", "SL": "AF", "SS": "AF", "ST": "AF",
  "KI": "OC", "NR": "OC", "WS": "OC", "TO": "OC", "TV": "OC",
  "PF": "OC", "NC": "OC", "CK": "OC",
  // markable countries missing from the scored region data
  "SV": "NA", "KP": "AS", "MH": "OC", "FM": "OC", "PW": "OC",
  "TL": "AS", "ZW": "AF",
  // South Atlantic territories (grouped with South America, not Antarctica —
  // the 7-continent badge should mean the actual continent)
  "GS": "SA", "FK": "SA",
};
let _allPlaces = null;
function allPlaces() {
  if (!_allPlaces)
    _allPlaces = [...new Set([...Object.keys(CUR_BY_ISO), ...Object.keys(EXTRA_PLACES), ...MORE_PLACES])];
  return _allPlaces;
}

// England/Scotland/Wales use Unicode tag-sequence flags, not letter pairs.
const _SUBDIV_FLAG = (s) => "🏴" + [...s].map((c) =>
  String.fromCodePoint(0xe0000 + c.charCodeAt(0))).join("") + "\u{E007F}";
const SPECIAL_FLAGS = {
  "GB-ENG": _SUBDIV_FLAG("gbeng"),
  "GB-SCT": _SUBDIV_FLAG("gbsct"),
  "GB-WLS": _SUBDIV_FLAG("gbwls"),
};
function flagEmoji(iso) {
  if (SPECIAL_FLAGS[iso]) return SPECIAL_FLAGS[iso];
  if (!/^[A-Z]{2}$/.test(iso)) return "🌍";
  return String.fromCodePoint(...[...iso].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

// 0-100 score -> letter grade. Calibrated against the score curves: a realistic
// best case (~95) reads A+, a middling 50-60 reads C.
function grade(score) {
  if (score == null) return "—";
  return score >= 93 ? "A+" : score >= 85 ? "A" : score >= 78 ? "B+" : score >= 68 ? "B"
       : score >= 55 ? "C" : score >= 42 ? "D" : "F";
}
const gradeCls = (g) => "gr" + g.replace("+", "p").replace("—", "x");
function gradePill(score, title, extra) {
  const g = grade(score);
  return `<span class="gr ${gradeCls(g)}${extra ? " " + extra : ""}" title="${esc(title)}">${g}</span>`;
}
// Safety grades come from the advisory level, not the score curve, so the
// letter matches the State Dept tier exactly.
// 4 has no caller today — valueScores drops Do Not Travel before anything can ask
// for its pill — but leaving the hole meant safetyPill(4) crashed on an undefined
// grade. F, so the map is total and the next caller can't fall through it.
const SAFE_GRADE = { 1: "A", 2: "B", 3: "D", 4: "F" };
// A level in its own government's words, for the Top Picks pills and tips:
// "Level 2: high degree of caution" (Canada), "“No warning”" (Germany's own
// call, which isn't a grade). Its one table of words (US's) printed "Level 2:
// increased caution — per Global Affairs Canada" and "Level 1: normal
// precautions — per German Foreign Office", the defect the Safety tab's
// filter, legend and ⓘ had. A gap-fill speaks its filler's words (advSrcOf);
// ADV_TEXT is for a level with no item behind it.
const ADV_TEXT = { 1: "Level 1: normal precautions", 2: "Level 2: increased caution",
                   3: "Level 3: reconsider travel", 4: "Level 4: do not travel" };
function advLevelText(iso, l) {
  const it = iso ? advisoryMetaByIso()[iso] : null;
  if (!it || !l) return ADV_TEXT[l] || "";
  const s = advSrcOf(it);
  if (s === "de" && DE_LVL_LABEL[l]) return "“" + DE_LVL_LABEL[l] + "”";
  const w = (ADV_LVL_WORDS[s] || ADV_LVL_WORDS.us)[l - 1];
  return w ? "Level " + l + ": " + w.toLowerCase() : ADV_TEXT[l] || "";
}
// " — per <source>", or which government filled the gap ("" without an iso).
function advVia(iso) {
  const meta = iso ? advisoryMetaByIso()[iso] : null;
  return !meta ? ""
    : meta.via ? ` — ${advSrcName(true)} publishes no advisory here; level per ${advViaShort(meta)}`
    : ` — per ${advSrcName(true)}`;
}
// iso is optional: with it, a level filled in by the other government says so.
function safetyPill(advLvl, iso) {
  // Unrated is its own answer, not a quiet B. Saying "treated as Level 2" in a
  // tooltip while showing a B is still showing a B — and B is recommendable.
  if (!advLvl) {
    return `<span class="gr grx" title="${esc("Not rated — none of the three governments we follow (US, Canada, Germany) publishes an advisory for this destination, so it isn't graded or ranked.")}">—</span>`;
  }
  return `<span class="gr ${gradeCls(SAFE_GRADE[advLvl])}" title="${esc(advLevelText(iso, advLvl) + advVia(iso))}">${SAFE_GRADE[advLvl]}</span>`;
}

// ---- month-level hazards (curated in activities.json) -----------------------
function hazardsFor(iso, month) {
  const a = activities && activities[iso];
  if (!a || !a.hazards) return [];
  return a.hazards.filter((h) => h.months && h.months.includes(month));
}
// [11,12,1,2] -> "Nov–Feb"; [6,7,8] -> "Jun–Aug"; non-contiguous -> "Apr, Oct"
function monthSpan(ms) {
  if (!ms || !ms.length) return "";
  const s = [...ms].sort((a, b) => a - b);
  if (s.length === 1) return MON_ABBR[s[0] - 1];
  const contig = (arr) => arr.every((m, i) => !i || m === arr[i - 1] + 1);
  if (contig(s)) return MON_ABBR[s[0] - 1] + "–" + MON_ABBR[s[s.length - 1] - 1];
  const set = new Set(s);
  const missing = [];
  for (let m = 1; m <= 12; m++) if (!set.has(m)) missing.push(m);
  if (missing.length && contig(missing))   // wraps around New Year, e.g. Nov–Apr
    return MON_ABBR[missing[missing.length - 1] % 12] + "–" + MON_ABBR[(missing[0] + 10) % 12];
  return s.map((m) => MON_ABBR[m - 1]).join(", ");
}

// ---- polish: seasonal doodles, count-up, parallax ---------------------------
const reducedMotion = () =>
  window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

// Seasonal accent layer follows the chosen travel month (N-hemisphere seasons —
// the audience is US travelers).
let _season = null;
function setSeason(month) {
  const s = month === 12 || month <= 2 ? "winter" : month <= 5 ? "spring"
          : month <= 8 ? "summer" : "autumn";
  if (s === _season) return;
  _season = s;
  const el = document.querySelector(".bgseason");
  if (el) el.style.backgroundImage = `url("/bg-${s}.svg")`;
}

// Tick a number element from 0 to its target (used on the Overall scores).
function countUp(el) {
  const target = parseInt(el.textContent, 10);
  if (!target) return;
  const t0 = performance.now(), dur = 650;
  const tick = (t) => {
    const f = Math.min(1, (t - t0) / dur);
    el.textContent = Math.round(target * (1 - Math.pow(1 - f, 3)));   // ease-out
    if (f < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// Background drifts a touch slower than the page scroll for a hint of depth.
(function initParallax() {
  if (reducedMotion()) return;
  const doo = document.querySelector(".bgdoodle");
  if (!doo) return;
  let raf = null;
  addEventListener("scroll", () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      doo.style.transform = "translateY(" + (-scrollY * 0.06).toFixed(1) + "px)";
      raf = null;
    });
  }, { passive: true });
})();

// ---- safety floor filter -----------------------------------------------------
function safetyFloor() {
  const sel = $("safeFloor");
  const v = (sel && sel.value) || localStorage.getItem("fx_safefloor") || "b";
  return ["a", "b", "any"].includes(v) ? v : "b";
}
// ---- budget ---------------------------------------------------------------
// "I have $2000 and 10 days — where can I actually go?"
//
// The obvious way to answer that needs a daily-cost number per country, and we
// don't have one: the PPP feed gives a price LEVEL (how local prices compare to
// home), not dollars. Turning that into "$47/day in Vietnam" needs an anchor —
// "a day of travel at home costs $X" — and no government publishes it. Inventing
// one and then eliminating countries on the strength of it would be the site's
// worst habit: a confident number nobody can check.
//
// So this doesn't invent the anchor, it removes the need for one. Two answers,
// both from data we actually hold:
//   1. The flight is real money (cached Travelpayouts fares). If even the
//      cheapest cached fare exceeds the budget, the trip is impossible — no
//      assumptions required. Where nothing is cached the fare is a distance
//      estimate: those drops are counted separately and say so.
//   2. What's left, per day, converted into home-money terms by the price level.
//      "$110/day, which buys what $260/day buys at home." The traveler knows
//      whether that's comfortable; we don't.
// Whole dollars: cents on a $260/day estimate would imply a precision that isn't
// there — the fare is a cached average and the price level is an annual index.
// The code, not "$": the Flights tab spells every currency the same way, and
// a bare $ reads as local money to a Canadian or an Australian.
function fmtMoney(n) {
  return "USD " + Math.round(n).toLocaleString();
}

// The budget's own currency — an Argentine thinks in pesos, and a number box
// that silently means US dollars turns their budget into nonsense (the owner
// watched it happen: a leftover $1,000 from a US test read as an impossible
// budget from Buenos Aires). Entered amount converts to USD internally, since
// the cached fares are USD; every display of it uses the entered currency.
function budgetCur() {
  try {
    const c = localStorage.getItem("wg_budgetcur");
    if (c && /^[A-Z]{3}$/.test(c)) return c;
  } catch (e) {}
  return /^[A-Z]{3}$/.test(homeBase || "") ? homeBase : "USD";
}
function budgetRate() {   // units of budget currency per USD
  const c = budgetCur();
  return c === "USD" ? 1 : (rateForCurrency(c) || null);
}
// Format a USD-space number in the budget currency, for every budget-adjacent
// display — one arithmetic, one look.
function fmtBC(usd) {
  const c = budgetCur(), r = budgetRate();
  if (c === "USD" || !r) return fmtMoney(usd);
  return c + " " + Math.round(usd * r).toLocaleString();
}
function initBudgetCur() {
  const sel = $("budgetCur");
  if (!sel || !lastRates) return;
  if (!sel.options.length) {
    // A-Z with the dollar in its place, like every other currency picker. A
    // compact inline control: the name rides on the option's title, since
    // spelling it out would widen the native select.
    sel.innerHTML = pickerCurrencies().map((c) => `<option value="${esc(c)}" title="${esc(curLabel(c))}">${esc(c)}</option>`).join("");
    sel.onchange = () => {
      try { localStorage.setItem("wg_budgetcur", sel.value); } catch (e) {}
      renderValue();
    };
  }
  // Unpinned budget currency follows "My currency" — switching home to
  // Germany should carry the budget to EUR unless the visitor explicitly
  // chose otherwise (an explicit pick persists and wins).
  const want = budgetCur();
  if (sel.value !== want && [...sel.options].some((o) => o.value === want)) sel.value = want;
}

function budgetOf() {
  // The boxes are filled from storage when Top Picks builds; a Trip or guide
  // landing never builds it, and its AI prompt then dropped the budget the
  // reader had set. Storage holds what the boxes would (a cleared box is "").
  const saved = (id, key) => {
    const v = ($(id) || {}).value;
    if (v || loaded.value) return v;
    try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
  };
  const t = parseFloat(saved("budgetTotal", "wg_budget"));
  const d = parseInt(saved("budgetDays", "wg_budgetdays"), 10);
  const r = budgetRate();
  // No conversion rate yet (rates still loading) -> treat as unset rather than
  // filter every country on a wrong number.
  const usd = t > 0 && r ? t / r : null;
  return { total: usd, days: d > 0 ? d : 10, entered: t > 0 ? t : null, cur: budgetCur() };
}

// Null when there's no budget set or no fare to reason from — callers treat that
// as "no opinion", never as "affordable". Plans on the average cached fare;
// when that alone eats the budget but a cheaper fare has been seen, plans on
// the cheapest (fareIsMin). Only real fares make a country `impossible`; an
// estimate over budget is `estOut` — dropped too, but counted and said apart.
function budgetFit(s) {
  const { total, days } = budgetOf();
  if (!total || s.fare == null) return null;
  const cheapest = !s.fareEst && s.fareMin > 0 ? Math.min(s.fareMin, s.fare) : s.fare;
  const fare = s.fare < total ? s.fare : cheapest;
  const left = total - fare;
  const perDay = left / days;
  // s.pl is already relative to the traveler's home country, so dividing by it
  // converts local spending power back into home money.
  const homeEquiv = s.pl > 0 ? perDay / s.pl : null;
  return { total, days, fare, fareEst: s.fareEst, fareIsMin: fare !== s.fare, left,
           perDay, homeEquiv, impossible: !s.fareEst && left <= 0, estOut: !!s.fareEst && left <= 0 };
}

function passesBudget(s) {
  const f = budgetFit(s);
  return !f || !(f.impossible || f.estOut);
}

function passesFloor(s, floor) {
  return floor === "any" || (floor === "a" ? s.advLvl === 1 : s.advLvl !== 3);
}

// What the flight leaves per day, in words: the row title and the line under
// the name say the same thing. Admits when the fare is a distance estimate
// rather than a seen one.
function budgetWords(s, bf) {
  const home = plHomeWord();
  const atHome = home === "home" ? "at home" : "in " + home;
  return `${fmtBC(bf.fare)} ${bf.fareIsMin ? "cheapest " : ""}flight${bf.fareEst ? " (est.)" : ""} leaves `
    + `${fmtBC(bf.perDay)}/day`
    + (bf.homeEquiv && s.pl < 0.95 ? ` — like ${fmtBC(bf.homeEquiv)}/day ${atHome}` : "");
}
// With a budget set, the per-day figure under the destination's name, where
// the answer is read. It used to live only in the row's title, which touch
// never shows and the pills' own titles mask on desktop.
function budLine(s) {
  const bf = budgetFit(s);
  if (!bf || bf.impossible || bf.estOut) return "";
  return `<span class="budline" data-tip="${esc(budgetWords(s, bf))}" title="">💵 ${fmtBC(bf.perDay)}/day left</span>`;
}

// Compose a human sentence from the score ingredients — answers, not numbers.
function whyLine(s, month) {
  const money = "your " + homeBase;            // the code for everyone, USD included
  const home = plHomeWord();                   // "the US" when From has no price level
  const bits = [];
  // One framing for the price level everywhere (plPhrase): this row title, the
  // pill, the map card and the prompts used to give four numbers for one fact.
  if (s.pl != null) bits.push("prices " + plPhrase(s.pl, home));
  // Same gate as the table's FX mark: below it the mark stays silent, and a
  // sentence calling +2% "unusual" contradicted the table's own silence.
  if (s.fx != null && s.fx >= FX_MARK_PCT) bits.push(`${money} is unusually strong there right now`);
  // Only when a budget is set.
  const bf = budgetFit(s);
  if (bf && !bf.impossible && !bf.estOut) bits.push(budgetWords(s, bf));
  if (s.wx >= 75) bits.push(`great weather in ${MONTHS[month - 1]}`);
  else if (s.wx >= 55) bits.push(`decent weather in ${MONTHS[month - 1]}`);
  if (s.advLvl === 1) bits.push("safest travel rating");
  else if (s.advLvl === 3) bits.push("⚠️ has a reconsider-travel advisory");
  // The deal grade's own (shrunk) ratio, so this never contradicts the pill;
  // a month grade has no ratio and speaks for the month instead.
  if (s.flyBasis === "month" || (s.dealRatio != null && !s.fareEst)) {
    const r = s.dealRatio;
    // "for the distance", always: "cheaper than usual" read as cheaper than
    // this route's own year, which the month strip beside it can contradict
    // (the grade is the year-round average fare against a distance-typical one).
    bits.push(s.flyBasis === "month"
      ? (s.fly >= 80 ? "flights cheap for " : s.fly <= 60 ? "flights pricey for " : "flights typical for ") + MONTHS[month - 1]
      : r <= 0.95 ? "flights cheap for the distance"
      : r >= 1.05 ? "flights pricey for the distance" : "flights typical for the distance");
  }
  return bits.slice(0, 4).join(" · ");
}

// How many answer cards to show (persisted per browser; default 5 so the map
// stays visible below the fold).
function pickCount() {
  const sel = $("pickCount");
  const v = parseInt((sel && sel.value) || localStorage.getItem("fx_pickcount") || "5", 10);
  return [5, 10, 20].includes(v) ? v : 5;
}

// Render a ranked list as a compact report-card table. gem=true marks the
// hidden-gems list, which ranks #1..#N just like the popular table (the 💎
// lives in the section title). The why-sentence moves to the row tooltip so
// the table itself stays scannable.
// ---- "why now" ---------------------------------------------------------------
// The ranking answers "how good is this place" but never "why this month". The
// seasonal data to answer it already existed — 282 entries across all 176
// countries, each with months, a short name and a description — but it only
// appeared on the guide page, one click PAST the decision. Surfacing the ones
// that match the selected month turns a weather grade into a reason: "August is
// pleasant in Japan" becomes "Autumn leaves". Idea borrowed from a friend's
// weekend-trips site, which does this better than we did.
function seasonalNow(iso, month) {
  const a = activities && activities[iso];
  if (!a || !a.seasonal) return [];
  return a.seasonal.filter((x) => (x.months || []).includes(month));
}
// Grey on the value map is three different situations wearing one colour, and
// "not scored" told the reader none of them. Filling the gaps is not the fix —
// two of the three are grey on purpose — so the fix is saying which it is.
function notScoredReason(iso) {
  if (!iso || iso === "-99") return "not a tracked country";
  const hasPl = priceLevel(iso) != null;
  const hasAdv = advisoryByIso()[iso] != null;
  // Deliberate suppression: the exchange rate is a peg or otherwise so far out
  // of line with income that a price level would be fiction. See plImplausible.
  if (!hasPl && typeof plImplausible === "function" && plImplausible(iso)) {
    return "no reliable price data — its exchange rate is pegged or distorted, "
         + "so any figure here would be fictional";
  }
  if (!hasPl && !hasAdv) return "no price or safety data";
  if (!hasPl) {
    // Most gaps are not a missing PPP figure — say which link actually broke.
    const u = PPP_UNIT[iso], cur = u ? u[0] : CUR_BY_ISO[iso];
    if (!ppp || !ppp[iso]) return "no price data — no World Bank PPP figure for this country";
    if (!cur) return "no price data — we can't match its currency to an exchange rate";
    if (!rateForCurrency(cur)) return "no price data — no live exchange rate for the " + cur;
    return "no reliable price data — the World Bank figure and today's exchange rate "
         + "are in different currency units (redenominated or dollarised)";
  }
  if (!hasAdv) return "no safety rating — none of the three governments we follow publishes one";
  return "not scored this month";
}

// Applies the top-picks treatment — pulse plus the named list — to any map.
// The Data tab maps each show one dimension; marking where the overall picks
// land gives them a common reference point, and makes every one of them
// shareable with the takeaway already in the picture.
// Each Data map annotates with ITS OWN dimension's leaders. The overall value
// ranking already lives on the Top Picks map; repeating it under a currency or
// fares map mislabeled what the colours were showing (the owner caught it).
// The list also moved BELOW the map — as an overlay it covered a continent on
// narrow layouts. Safety gets no list at all: ~100 countries tie at Level 1,
// and ranking a tie is invention.
// `empty`: a line to show instead when there are no items (else the row goes).
// `hold`: with no items, keep the row's room instead (it turns back into an
// invisible stand-in, .skel) — for a list that is only waiting on its data.
// `marks`: an optional ⚠️ tip per item ("" for none), the same caveat its row
// carries in the table under the map.
// An item is text, or { html } for trusted markup the caller built and
// escaped (Safety's coloured ▲/▼ — escaped, it printed as grey text).
// dimPicksFromDom reads only the row's direct <span>s, so markup nested in
// an item never becomes a pick of its own in the share image.
function renderDimPicks(hostId, title, items, isos, empty, marks, hold) {
  const host = $(hostId);
  if (!host) return;
  // Anywhere in the page: in full screen the map and its list sit apart.
  let row = document.querySelector('.mappicksrow[data-for="' + hostId + '"]');
  if ((!items || !items.length) && !empty) {
    if (row && hold) { row.classList.add("skel"); row.setAttribute("aria-hidden", "true"); }
    else if (row) row.remove();
    return;
  }
  if (!row) {
    row = document.createElement("div");
    row.className = "mappicksrow";
    row.dataset.for = hostId;
    // Top Picks keeps the list at the foot of the Tune card beside the map (a
    // slot says where); every other map has it directly underneath.
    const slot = document.querySelector('[data-picks-slot="' + hostId + '"]');
    if (slot) slot.appendChild(row); else host.insertAdjacentElement("afterend", row);
  }
  // The markup's invisible stand-in (index.html) holds the space until now.
  row.classList.remove("skel");
  row.removeAttribute("aria-hidden");
  // The note is a <strong>, not a <span>: dimPicksFromDom reads the spans as
  // picks, and the share image must not list "Nothing below…" as #1.
  if (!items || !items.length) { row.innerHTML = "<strong>" + esc(empty) + "</strong>"; return; }
  row.innerHTML = "<strong>" + esc(title) + "</strong>"
    + items.slice(0, 8).map((t, i) => "<span>" + (i + 1) + ". " + (t && t.html != null ? t.html : esc(t))
      + (marks && marks[i] ? '<span class="hzmark" data-tip="' + esc(marks[i]) + '" title="">⚠️</span>' : "")
      + "</span>").join("");
  if (isos && isos.length && !reducedMotion()) {
    const set = new Set(isos);
    let i = 0;
    for (const p of host.querySelectorAll("path")) {
      if (set.has(p.getAttribute("data-iso"))) {
        p.classList.add("toppick");
        p.style.animationDelay = (i++ * 0.25) + "s";
      }
    }
  }
}
// The share images read whatever list is on screen, so map and export can't
// disagree about what the map claims.
// Direct child spans only, with any ⚠️ left out: an item's nested .hzmark is
// a span too, so the cost share image would have listed a ninth pick, "⚠️",
// and Gambia as "Gambia $420⚠️".
function dimPicksFromDom(hostId) {
  const row = document.querySelector('.mappicksrow[data-for="' + hostId + '"]');
  if (!row || row.classList.contains("skel")) return { picks: null, title: null };
  const pickText = (x) => [...x.childNodes].filter((c) => !(c.classList && c.classList.contains("hzmark")))
    .map((c) => c.textContent).join("").replace(/^\d+\.\s*/, "").trim();
  return { picks: [...row.querySelectorAll(":scope > span")].map(pickText),
           title: (row.querySelector("strong") || {}).textContent || null };
}

function renderMapPicksOverlay(picks, month, hostId) {
  // Below the map, not on it — the same call the Data maps made when their
  // overlays covered continents on narrow layouts. The EXPORTED image keeps
  // its on-map list (an image needs the answer inside itself); the live map
  // stays unobstructed.
  const show = valueMapMode !== "weather" && picks && picks.length;
  renderDimPicks(hostId || "valueMap",
    "Best value in " + MONTHS[month - 1],
    show ? picks.slice(0, 8).map((s) => s.name) : null);
}

// ---- coverage: what the overall score is actually standing on ---------------
// The weighted mean excludes dimensions we have no data for — no climate entry
// means no weather term in the numerator or the denominator. That is the
// correct arithmetic, and it produces a wrong-looking table: a country scored
// on three dimensions has those three carrying full weight, so it can float
// above a country measured on four.
//
// Flights are different: every country with map geometry gets a fare — the
// cached one, or a distance estimate scored as a neutral 70 (a typical fare for
// the distance). Only the origin itself has none. So an estimate is flagged as
// "estimated" rather than "missing" — it IS averaged in. It used to read
// "3+1" here; the estimate is now said once, where it is: the Flights cell's
// grey "~B" pill (the Full ranking's grey "~70"), so this mark is only for a
// measure the country has no data for.
//
// The fix is not to change the average. It is to stop the row implying it knows
// four things when it knows fewer.
function coverageMark(s) {
  const missing = [];
  if (s.flyMissing) missing.push("flight prices");
  if (s.wxMissing) missing.push("weather");
  if (!missing.length) return "";
  const est = !s.flyMissing && s.fareEst;
  const n = 4 - missing.length;
  const tip = "Graded on " + n + " of 4 measures — no " + missing.join(" or ") + " data for this country"
    + (est ? ", and flights are an estimate (no cached fare, counted as a typical fare for the distance)" : "")
    + ". The score is the average of the " + n + " it has, so it is not directly comparable with a fully-measured country.";
  return `<span class="covmark" data-tip="${esc(tip)}" title="">${n}/4</span>`;
}

// ---- 12-month season strip --------------------------------------------------
// The weather column was a single letter for the chosen month, which cannot say
// the thing that actually decides trips: how WIDE a country's good window is.
// The Baltics are usable roughly June to mid-September and unusable otherwise;
// the Balkans have two windows; Benelux is a shoulder destination year-round.
// A "B in August" reads identically for all three.
//
// The twelve monthly comfort scores have been sitting in climate.json the whole
// time — the guide page already draws them as bars. This is the same data at
// glance size, next to the grade it explains. Presentation only: no score, no
// ordering and no grade changes, so it cannot silently reshuffle the ranking.
function seasonStrip(iso, month) {
  const cl = climate && climate[iso];
  if (!cl || !cl.scores || cl.scores.length !== 12) return "";
  const seas = seasons(cl.scores);
  const good = seas.filter((s) => s === "peak").length;
  const cells = seas.map((s, i) => {
    const cur = (i + 1) === month ? " now" : "";
    return `<i class="sc ${s}${cur}" data-m="${i + 1}"></i>`;
  }).join("");
  // Scarcity is the point: a country good three months a year, in one of them,
  // is a different proposition from one that is pleasant all year.
  const scarce = good > 0 && good <= 4;
  // Names the months the guide sentence and the "🗓️ Best in" tag name
  // (climate.best: hand-curated for 35 countries, top weather months for the
  // rest). The bright cells are weather alone; a "Best: May–Aug" beside a
  // curated "Best in Apr, May, Sep, Oct" read as the site contradicting itself.
  const bestM = (cl.best || []).filter((m) => m >= 1 && m <= 12);
  const best = bestM.map((m) => MON_ABBR[m - 1]);
  // The scarcity count is the bright (peak) cells. When those aren't the best
  // months just listed (Brazil: best Apr/May/Sep/Oct, comfiest May–Aug), name
  // them, or the reader takes the listed months for the comfy ones.
  const peakM = seas.map((x, i) => (x === "peak" ? i + 1 : 0)).filter(Boolean);
  const same = peakM.length === bestM.length && peakM.every((m) => bestM.includes(m));
  const tip = (best.length ? (cl.curated ? "Best months: " : "Best weather: ") + best.join(", ") + ". " : "")
    + (!scarce ? ""
      : best.length && same ? "Only " + good + (good === 1 ? " comfy month" : " comfy months") + " a year — a narrow window. "
      : "Comfiest weather only " + monthSpan(peakM) + " (" + good + (good === 1 ? " month" : " months")
        + " a year) — a narrow window. ")
    + "Each block is a month, January to December; brighter is more comfortable weather.";
  // role=img + aria-label: the cells are color-only; the tip text is the
  // strip's meaning, so screen readers get the same sentence hover gets.
  return `<span class="seasonstrip${scarce ? " scarce" : ""}" role="img" aria-label="${esc(tip)}" data-tip="${esc(tip)}" title="">${cells}</span>`;
}

function seasonalTags(iso, month, max) {
  const hits = seasonalNow(iso, month);
  // Nothing in season is itself the answer, and a blank cell doesn't say it.
  // Egypt in August has two seasonal windows, neither covering August, because
  // August is genuinely its dead month — but next to Bulgaria's "Beach season"
  // the empty cell read as "we have nothing on this country" rather than "this
  // is the wrong month". Say the true thing, sourced from the hazard note or
  // the off-peak classification, never invented.
  if (!hits.length) {
    const hz = hazardsFor(iso, month).map((h) => h.note).filter(Boolean);
    const cl = climate && climate[iso];
    const seas = cl && cl.scores ? seasons(cl.scores)[month - 1] : null;
    if (hz.length) {
      // Short label, full text in the tooltip — these notes are written as
      // sentences ("Intense desert heat — Luxor and Aswan regularly exceed
      // 105F / 40C") and would blow the column apart at full length.
      const short = hz[0].split(/[—.(]/)[0].trim();
      return `<span class="seastag seasoff" data-tip="${esc(hz.join(" · "))}" title="">`
           + `⚠️ ${esc(short.length > 30 ? short.slice(0, 29).trimEnd() + "…" : short)}</span>`;
    }
    // Otherwise point at when this country IS at its best. That answers the
    // question the blank cell raises ("is there nothing here?") with the most
    // useful thing we know, and it comes straight from climate.best.
    const best = (cl && cl.best) || [];
    if (best.length) {
      const span = best.map((m) => MON_ABBR[m - 1]).join(", ");
      return `<span class="seastag seasoff" data-tip="${esc("Nothing peaks in "
        + MONTHS[month - 1] + ". This country is at its best in " + span + ".")}" title="">`
        + `🗓️ Best in ${esc(span)}</span>`;
    }
    return "";
  }
  const shown = hits.slice(0, max || 2).map((x) =>
    `<span class="seastag" data-tip="${esc(x.what + (x.d ? " — " + x.d : ""))}" title="">`
    + `${activityEmoji(x.what)} ${esc(x.what)}</span>`).join("");
  const more = hits.length > (max || 2)
    ? `<span class="seastag seasmore" data-tip="${esc(hits.slice(max || 2).map((x) => x.what).join(" · "))}" title="">+${hits.length - (max || 2)}</span>`
    : "";
  return shown + more;
}

// Fare strips for the picks table, filled after render: one cached call per
// row via /api/flight-months (12h server cache per route). The slot is a flex
// box the strip's own height (styles .rowfares), so its async arrival adds the
// same 4 + 9px the weather cell's season strip already sets — no CLS. It was
// a block around an inline strip, a 20px line box that grew rows after paint.
// The chosen month gets the season strip's tick, dimmed at rest like it.
function fillRowFareStrips(hostSel, month) {
  const slots = document.querySelectorAll(hostSel + " .rowfares");
  slots.forEach(async (slot) => {
    const iso = slot.dataset.iso;
    const fm = await ensureFareMonths(iso);
    if (!fm || !fm.months || !slot.isConnected) return;
    const strip = fareStripHTML(fm.months, fareStripOpts(month));
    if (strip) slot.innerHTML = '<span class="farestrip" role="img" aria-label="'
      + esc("Fares by month — " + strip.note) + '">' + strip.cells + "</span>";
  });
}

// Table-sized versions of the guide's two trend signals, compressed to the
// table's own grammar: pill + rare marker, never a chart. The full sparkline
// and dated move live on the guide, where there is room to be honest about
// what they mean.
// FX: gated at ±5% of REAL movement (after the inflation gap, realFxPct) —
// rarer than the Currency tab's ±2% "strong" label on purpose. A scan table
// earns a mark only when it might change a decision; the ⚠️ drift warning
// already covers the extreme (±15%) case. The nominal move marked every
// steadily depreciating high-inflation currency as a bargain.
const FX_MARK_PCT = 5;
function fxMark(iso) {
  const f = fxInfo(iso);
  const pct = f && f.real;
  if (typeof pct !== "number" || Math.abs(pct) < FX_MARK_PCT) return "";
  const up = pct > 0;
  const cn = countryName(iso);
  // Without a destination inflation figure nothing was netted out: state the
  // exchange-rate move and say so, never "after inflation" / "goes further".
  const tip = f.adj
    ? "After inflation, your " + homeBase + " buys " + Math.abs(Math.round(pct)) + "% " + (up ? "more" : "less")
      + " in " + cn + " than its 1-yr average — your money goes " + (up ? "further" : "less far")
      + " there than usual right now. Exchange-rate move " + signedPct(Math.round(f.nom))
      + "; inflation " + inflGapText(iso, f.homeIso) + " (World Bank)."
    : "Your " + homeBase + " is " + Math.abs(Math.round(pct)) + "% " + (up ? "stronger" : "weaker")
      + " in " + cn + " than its 1-yr average. Exchange rate only — no inflation figure for " + cn
      + ", so rising local prices aren't netted out.";
  return `<span class="fxmark ${up ? "fxup" : "fxdn"}" data-tip="${esc(tip)}" title="">${
    up ? "+" : "−"}${Math.abs(Math.round(pct))}%</span>`;
}
// How long a level change counts as recent: the Safety list and table, the
// guide's safety line and Top Picks' mark all read this one window.
const ADV_MOVE_DAYS = 180;
const advMoveCutoff = () => new Date(Date.now() - ADV_MOVE_DAYS * 864e5).toISOString().slice(0, 10);
// Safety: the advisory's latest move (180-day window) — an event mark, only a
// handful of countries carry one at a time.
function advMovedMark(iso) {
  const it = advisoryMetaByIso()[iso];
  const on = advChangedOn(it);
  if (!it || !it.change || !on) return "";
  if (on < advMoveCutoff()) return "";
  const when = fmtDayShort(on);
  const up = it.change === "up";
  return `<span class="advmv ${up ? "chup" : "chdown"}" data-tip="${esc("Advisory "
    + (up ? "raised" : "lowered") + " to " + advLvlName(it) + " on " + when
    + " — recently " + (up ? "riskier" : "safer") + " in the source's judgement.")}" title="">${
    up ? "▲" : "▼"}</span>`;
}

function renderGradeTable(host, list, month, gem, sortable, state = pickSort) {
  if (!host) return;
  if (!list.length) { host.innerHTML = "<p class='hint'>No destinations match these filters.</p>"; return; }
  // Sortable tables reorder the same set by the chosen column; rank (#i+1)
  // renumbers to match. Each table gets its own sort state (picks vs gems).
  if (sortable) list = sortRows(list, state, PICK_GET);
  const sa = (sk) => sortable
    ? ` data-sk="${sk}" data-sortdir="${state.key === sk ? (state.asc ? "asc" : "desc") : ""}"${sortableThAttrs(state, sk)}` : "";
  const sc = sortable ? " sortable" : "";
  const been = ownVisited();
  const rows = list.map((s, i) => {
    const hz = hazardsFor(s.iso, month);
    const wxTitle = (s.wx == null ? "no weather data" : `${s.wx}/100 weather comfort in ${MONTHS[month - 1]}`) +
      (hz.length ? " — ⚠️ " + hz.map((h) => h.note).join("; ") : "");
    const iso = esc(s.iso);
    // Same ⚠️ affordance the weather column uses for seasonal hazards, with
    // every price-data caveat the Cost table's ⚠️ carries (pppNotes): on the
    // drift note alone, San Marino, Greenland, the British Virgin Islands and
    // Eritrea were flagged in the Cost table for old World Bank data but bare
    // here, on the same price level.
    const priceNotes = pppNotes(s.iso);
    // The name is a real link to the guide: rows open it on a click, but
    // nothing in the row could take keyboard focus, so a keyboard user could
    // sort the table and never open a country. The delegate below keeps a
    // plain click in the app; cmd/middle-click opens a new tab. No title on
    // the link, so the row's why-line still shows on hover.
    const seen = been.has(s.iso);
    return `<tr data-iso="${iso}"${seen ? ' class="visited"' : ""} title="${esc(whyLine(s, month))}" style="--i:${i}">
      <td class="rank">#${i + 1}</td>
      <td class="dest"><a class="destlink" href="${esc(guidePath(s.iso))}"><span aria-hidden="true">${flagEmoji(s.iso)}</span> ${esc(s.name)}</a>${seen ? ' <span class="visited-tag">✓<span class="vtword"> visited</span></span>' : ""}${seasonalTags(s.iso, month)}${budLine(s)}</td>
      <td class="scell" data-go="afford" data-iso="${iso}"><span class="pillwrap">${gradePill(s.afford, affordTitle(s))}${priceNotes ? `<span class="hzmark" data-tip="${esc(priceNotes)}" title="">⚠️</span>` : ""}${fxMark(s.iso)}</span></td>
      <td class="scell" data-go="advisory" data-iso="${iso}"><span class="pillwrap">${safetyPill(s.advLvl, iso)}${advMovedMark(s.iso)}</span></td>
      <td class="scell" data-go="weather" data-iso="${iso}"><span class="pillwrap">${s.wx == null ? `<span class="gr grx" data-tip="${esc(wxTitle)}" title="">—</span>` : gradePill(s.wx, wxTitle + " · click for the month-by-month guide")}${hz.length ? `<span class="hzmark" data-tip="${esc(hz.map((h) => "⚠️ " + monthSpan(h.months) + ": " + h.note).join("\n"))}" title="">⚠️</span>` : ""}</span>${seasonStrip(s.iso, month)}</td>
      <td class="scell" data-go="flights" data-iso="${iso}"><span class="pillwrap">${s.fare == null ? '<span class="gr grx" data-tip="No fare data" title="">—</span>'
            // An estimate is a grey pill with its letter (it always scores
            // 70, a B): the same test and the same grey as the Full ranking's
            // "~70", where a bare "~" and a title touch never shows used to be.
            : (s.flyBasis !== "month" && s.fareEst) ? `<span class="gr grx" role="img" aria-label="estimated ${grade(s.fly)}" data-tip="Estimated — no cached fare yet, so flights count as a typical fare for the distance, averaged in with the rest. Click for the Flights tab." title="">~${grade(s.fly)}</span>`
            : gradePill(s.fly, (s.flyBasis === "month"
                ? MONTHS[month - 1] + "'s fare vs this route's usual · click for exact prices"
                : "Year-round fare vs the typical fare for this distance (too few cached months for a month grade) · click for exact prices"))}</span><span class="rowfares" data-iso="${iso}"></span></td>
      <td class="overall">${gradePill(s.value, `Overall value score ${s.value}/100`, "big")}<span class="ovnums"><span class="grnum" title="value score out of 100">${s.value}</span>${coverageMark(s)}</span></td>
    </tr>`;
  }).join("");
  host.innerHTML = `<table class="gradetable">
    <thead><tr><th><span class="vh">Rank</span></th><th class="dest${sc}"${sa("dest")}>Destination</th>
      <th class="${sc.trim()}"${sa("afford")} title="how far your money goes — daily prices vs home, plus how strong your currency is right now"><span aria-hidden="true">💰</span> <span class="thword">Affordability</span></th>
      <th class="${sc.trim()}"${sa("safety")} title="${esc(advSafetyTitle())}"><span aria-hidden="true">🛡️</span> <span class="thword">Safety</span></th>
      <th class="${sc.trim()}"${sa("weather")} title="weather comfort for your chosen month"><span aria-hidden="true">🌤️</span> <span class="thword">Weather</span></th>
      <th class="${sc.trim()}"${sa("flights")} title="this month's fare vs the route's usual where we have cached months; otherwise the year-round fare vs a typical fare for the distance (the strip shows each month)"><span aria-hidden="true">✈️</span> <span class="thword">Flights</span></th>
      <th class="ovh ${sc.trim()}"${sa("overall")} title="everything blended, weighted by your priorities">Overall</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  if (sortable) markSort("#" + host.id, state);   // sort buttons + aria-sort
  if (!reducedMotion()) host.querySelectorAll(".grnum").forEach(countUp);
  fillRowFareStrips("#" + host.id, month);
}
// Tooltip for the merged Affordability cell: explains both the price level and
// the FX timing, both measured against the traveler's home country/currency.
function affordTitle(s) {
  const parts = [];
  const home = plHomeWord();
  // plPhrase, not a copy of its band: the copy tested raw values while the
  // table bands on the two decimals it prints, so at the edges the Bahamas vs
  // the US (0.904) read "about the same" here but "0.90 cheap" in the table
  // and "~10% cheaper" in its guide (Vanuatu vs Germany, 1.1048, the reverse).
  if (s.pl != null) parts.push("daily prices " + plPhrase(s.pl, home));
  // "after inflation" only when a destination figure was actually netted out.
  // Whole percentages: two decimals on a cached 1-yr average claimed a
  // precision the figure doesn't have.
  if (s.fx != null && Math.abs(s.fx) >= 1)
    parts.push(`your ${homeBase} is ${signedPct(Math.round(s.fx))} vs its 1-yr average${s.fxAdj ? ", after inflation" : ""}`);
  // Repeatedly the sharpest critique this gets: PPP is a national consumption
  // basket, so it under-weights the one cost a visitor most feels — rent in the
  // few neighbourhoods foreigners actually stay in. Say so where the number is
  // read rather than burying it in a methodology note.
  return (parts.join(" · ") || "affordability")
    + " · national average — tourist areas and foreigner rents run higher"
    + " · click for cost-of-living detail";
}

// One delegated click for the grade table:
//  - a factor cell jumps to that factor's detail for the country
//  - the rest of the row opens the country's travel guide
document.addEventListener("click", (e) => {
  const dl = e.target.closest(".gradetable a.destlink, #tripBook a.tbdest, #tab-data a.destlink");
  if (dl) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;   // new tab/window: the browser's
    e.preventDefault();
    openGuideFor(dl.closest("[data-iso]").dataset.iso, true);
    return;
  }
  if (e.target.closest("a")) return;
  const cell = e.target.closest(".gradetable td.scell[data-go]");
  if (cell && cell.dataset.iso) { goToDetail(cell.dataset.go, cell.dataset.iso); return; }
  const t = e.target.closest(".pickcard, .gradetable tr[data-iso]");
  if (t && t.dataset.iso) openGuideFor(t.dataset.iso, true);
});

// Data-tab tables (currency, cost of living, safety, flights): a row click opens
// that country's Travel Guide, so a traveler can go straight from "this looks
// cheap / safe / close" to planning the trip. In-row links (advisory "details",
// the fare ↗) keep working via the closest("a") guard above.
document.addEventListener("click", (e) => {
  if (e.target.closest("a")) return;
  const tr = e.target.closest("#rows tr[data-iso], #affRows tr[data-iso], #advRows tr[data-iso], #flightRows tr[data-iso]");
  if (tr && tr.dataset.iso) openGuideFor(tr.dataset.iso, true);
});

// Jump from a Top Picks score to the matching detail view, filtered to the
// country. Weather lives in the Travel Guide; the rest in Explore the Data.
async function goToDetail(go, iso) {
  if (go === "weather") { openGuideFor(iso, true); return; }
  await activateTab("data", true);
  await setDataMode(go);
  const code = CUR_BY_ISO[iso];
  const scrollTo = (sel) => { const el = document.querySelector(sel); if (el) el.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "center" }); };
  // Use the table's OWN displayed name for the country (data files disagree on
  // some names, e.g. Turkey vs Türkiye), so the text filter always matches.
  const rowName = (tbodyId) => {
    const r = document.querySelector(`#${tbodyId} tr[data-iso="${iso}"]`);
    // The name link's text: the cell also carries a flag and (Cost) a
    // currency code, which would make the filter match nothing.
    const a = r && r.children[0].querySelector("a.destlink");
    return a ? a.textContent.trim() : r ? r.children[0].textContent.trim() : countryName(iso);
  };
  // Jumping to a specific country must never land on an empty table, so reveal
  // Level 3–4 if that's what's being asked for. Not persisted: this is one look
  // at one country, not a standing preference. Applies to every risk-filtered
  // sub-tab now, not just currency.
  if ((advisoryByIso()[iso] || 0) >= 3 && !showRisky) setShowRisky(true, false);
  // Pin the jump to the iso (see jumpActive) — the name alone matched "Romania"
  // for Oman and "Nigeria" for Niger.
  const jump = (box, name) => { $(box).value = name; _jump = { box, q: name.trim().toLowerCase(), iso }; };
  if (go === "currency") {
    $("curFilter").value = code || countryName(iso); applyCurrencyFilter(); scrollTo("#dataSubCurrency .tablewrap");
  } else if (go === "afford") {
    jump("affFilter", rowName("affRows")); applyAffordFilter(); scrollTo("#affTable");
  } else if (go === "advisory") {
    jump("advFilter", rowName("advRows")); $("advLevel").value = "all"; applyAdvFilter(); scrollTo("#advTable");
  } else if (go === "flights") {
    jump("flightFilter", rowName("flightRows")); applyFlightFilter(); scrollTo("#flightTable");
  }
}

// "Popular" = the most-visited countries by international tourist arrivals
// (UN Tourism via World Bank, /api/popularity), refreshed server-side. These
// lead "above the fold"; the rest (high value but off the beaten path) become
// Hidden Gems. The curated set below is only a fallback if the data won't load.
const POPULAR_N = 60;
let popularSet = new Set((
  "FR ES IT GB DE GR PT NL AT CH IE HR CZ IS NO SE DK PL HU BE TR " +
  "US MX CA BR AR PE CO CR CU DO JM CL " +
  "JP TH CN IN VN ID PH KR SG MY KH LK NP AE IL JO TW " +
  "EG MA ZA KE TZ AU NZ").split(" "));
let popularDataBacked = false;
let _arrivals = null;
async function ensurePopularity() {
  if (_arrivals) return;
  const d = await getJSON("/api/popularity");
  if (d && d.arrivals && Object.keys(d.arrivals).length > 20) {
    _arrivals = d.arrivals;
    const ranked = Object.keys(CUR_BY_ISO)
      .filter((iso) => _arrivals[iso] != null)
      .sort((a, b) => _arrivals[b] - _arrivals[a]);
    popularSet = new Set(ranked.slice(0, POPULAR_N));
    popularDataBacked = true;
  }
}

function renderValue() {
  const region = regionSel;
  const month = parseInt($("valueMonth").value, 10);
  setSeason(month);
  renderTripBar();
  const advMap = advisoryByIso();
  labelSafetySource();

  // Fare context: known fares per country + distance-based estimates for the rest.
  const fares = buildFareContext();
  // "Cheap" is relative to the From country's own price level (US anchor = 1).
  const A = plAnchor(originIso()), anchorPl = A.pl;   // US fallback when home has no price level

  const scored = {};
  for (const iso in CUR_BY_ISO) {
    if (region !== "all" && ISO_REGION[iso] !== region) continue;
    const s = valueScores(iso, month, advMap, fares, anchorPl);
    if (s) scored[iso] = s;
  }
  // Title, ⓘ and key follow whichever map is showing. The sub line is an ⓘ
  // (one header line, per the owner), so its sentence goes in the tip.
  const vTitle = $("valueMapTitle"), vSub = $("valueMapSub"), vLeg = $("valueLegend");
  if (vTitle) vTitle.textContent = valueMapMode === "weather"
    ? "Weather comfort in " + MONTHS[month - 1]
    : "Best value destinations in " + MONTHS[month - 1];
  if (vSub) vSub.dataset.tip = valueMapMode === "weather"
    ? "Greener = more comfortable weather that month."
    : "Greener = better overall value — affordability, safety, weather and flights combined.";
  // Short labels ("Lower"/"Higher", as the share image has them; the title
  // says of what): the key then fits one row under the title in a half-width
  // card, where "Lower value … your top picks" wrapped to two.
  // The markup's invisible copy of this key (index.html) held its room until now.
  if (vLeg) { vLeg.classList.remove("skel"); vLeg.removeAttribute("aria-hidden"); }
  if (vLeg) vLeg.innerHTML = valueMapMode === "weather"
    ? '<span>Harsh</span><span class="scale"></span><span>Comfortable</span>'
      + '<span><span class="swatch"></span>No data</span>'
    : '<span>Lower</span><span class="scale"></span><span>Higher</span>'
      // Only claimed when the pulse actually runs — reducedMotion() suppresses
      // it, and a key describing an animation nobody sees is worse than none.
      + (reducedMotion() ? ""
         : '<span><span class="swatch pulsekey"></span>Pulsing = top picks</span>')
      + '<span><span class="swatch"></span>No data</span>'
      + '<span><span class="swatch" style="background:' + DNT_FILL + '"></span>Do Not Travel</span>';

  if (valueMapMode === "weather" && climate) {
    // Weather-only view (absorbed the old "best places by month" tab).
    drawMap("valueMap", (f) => {
      const c = climate[f.properties.iso];
      const s = c ? c.scores[month - 1] : null;
      return { fill: comfortColor(s),
        title: c ? `${c.name}: ${s == null ? "n/a" : s + "/100"} weather comfort in ${MONTHS[month - 1]}`
                 : f.properties.name + " — no data" };
    }, "Weather comfort by month");
  } else {
    drawMap("valueMap", (f) => {
      const s = scored[f.properties.iso];
      if (s) return { fill: comfortColor(s.value),
        title: `${s.name}: value ${s.value}/100 (afford ${s.afford}, safe ${s.safe}${s.wx != null ? ", wx " + s.wx : ""}${s.fly != null ? ", fly " + s.fly + (s.fareEst ? " est." : "") : ""})` };
      if (advMap[f.properties.iso] === 4)
        return { fill: DNT_FILL, title: f.properties.name + " — Level 4: Do Not Travel (excluded)" };
      return { fill: NODATA, title: f.properties.name + " — " + notScoredReason(f.properties.iso) };
    }, "Best value destinations");
  }

  // The viewer's OWN been-list: while a shared map is open, `visited` holds the
  // sharer's countries, and Top Picks was hiding those as "you've been".
  const been = ownVisited();
  // In weather mode the TABLES follow the map: ranked by weather comfort for the
  // chosen month (value as tiebreak; syncRankSort sets the column), and the
  // picks note says so where it is read — the old note sat in the closed fold.
  const weatherMode = valueMapMode === "weather";
  // Filled in below, once the filters have run and we know what they removed.
  const note = $("rankNote");
  const rankedAll = Object.values(scored)
    .sort(weatherMode ? ((a, b) => ((b.wx ?? -1) - (a.wx ?? -1)) || (b.value - a.value))
                      : ((a, b) => b.value - a.value));
  // Above the fold = recognizable destinations; Hidden Gems = high-value but
  // off-the-beaten-path. Both come from the safety-filtered, unvisited pool.
  const floor = safetyFloor();
  // "Somewhere new" (default) keeps your ✓ been countries out of the picks;
  // interests narrow to countries matching any selected tag.
  const showVisited = localStorage.getItem("wg_showvisited") === "1";
  const preBudget = rankedAll.filter((s) =>
    (showVisited || !been.has(s.iso)) && passesFloor(s, floor) && matchesInterests(s.iso));
  const eligible = preBudget.filter(passesBudget);
  // Counted so the note can say the filter did something. At a roomy budget it
  // drops nothing, and a control that silently changes nothing reads as broken.
  // Drops on a real cached fare and on a distance estimate are told apart, and
  // nothing is called "reachable" that had no fare to judge.
  let outOfReach = 0, outOfReachEst = 0, judged = 0, unjudged = 0;
  const fromIso = flightsData && flightsData.origin;   // home needs no flight
  for (const s of preBudget) {
    const f = budgetFit(s);
    if (!f) { if (s.iso !== fromIso) unjudged++; continue; }
    judged++;
    if (f.impossible) outOfReach++;
    else if (f.estOut) outOfReachEst++;
  }
  // The "Somewhere new" filter is on by default and works, but it lives inside
  // a collapsed Filters fold — so a reader with 34 countries marked sees them
  // silently missing from the ranking and has no idea why. Say it out loud.
  const hiddenVisited = showVisited ? 0 : rankedAll.filter((s) => been.has(s.iso)).length;
  if (note) {
    const bits = [];
    if (hiddenVisited) bits.push(`Hiding ${hiddenVisited} `
      + (hiddenVisited === 1 ? "country" : "countries")
      + " you've marked ✓ been — change that under ⚙️ Filters → Been-to.");
    note.hidden = !bits.length;
    note.textContent = bits.join(" · ");
  }
  const popular = eligible.filter((s) => popularSet.has(s.iso));
  const offbeat = eligible.filter((s) => !popularSet.has(s.iso));
  // Fall back to the full list if no popular destinations match the filters.
  const picks = (popular.length ? popular : eligible).slice(0, pickCount());
  const picksNote = $("picksNote");
  initBudgetCur();
  const bud = budgetOf();
  const nOut = outOfReach + outOfReachEst;
  const budNote = bud.total
    ? ` 💵 <b>${bud.cur} ${Math.round(bud.entered).toLocaleString()} for ${bud.days} ${bud.days === 1 ? "day" : "days"}</b>`
      + (!judged ? " — no fare data yet, so nothing was filtered."
         : nOut ? ` — ${nOut} ${nOut === 1 ? "country is" : "countries are"} out of reach on the flight alone`
           + (outOfReachEst ? ` (${outOfReachEst === nOut ? "all" : outOfReachEst} on estimated fares)` : "") + "."
         : unjudged ? " — every pick with a fare is reachable."
         : " — every pick below is reachable.")
      + (judged && unjudged ? ` ${unjudged} had no fare to judge.` : "")
      + ` <span class="muted" data-tip="Flights are the cached fares Aviasales has seen (the cheapest one decides what's out of reach); where none is cached, a distance-based estimate, marked est. What's left is your budget minus the fare, spread over your days — and &quot;at home&quot; converts that by the local price level (World Bank PPP), so you can judge whether it's liveable. We don't guess a daily cost for you.">ⓘ</span>`
    : "";
  const rankedBy = weatherMode ? `weather comfort in ${MONTHS[month - 1]}` : "value";
  if (picksNote) picksNote.innerHTML = (popular.length
    ? `${weatherMode ? "🌤️" : "🌍"} Popular destinations, ranked by ${rankedBy}${popularDataBacked ? ' <span class="muted" data-tip="popularity = international tourism spend (UN Tourism / World Bank)">ⓘ</span>' : ""} — more finds under 💎 Hidden gems.`
    : `Ranked by ${weatherMode ? rankedBy : "overall value"} — no mainstream destinations match these filters, so showing everything.`) + budNote;
  lastPicks = picks; lastPicksMonth = month;   // for the AI export + re-sort
  renderGradeTable($("topCards"), picks, month, false, true);
  // "Show more" reveals 10 then 20; hides when maxed out or nothing left.
  const sm = $("showMore");
  if (sm) {
    const cap = pickCount();
    sm.hidden = cap >= 20 || picks.length < cap;
    sm.textContent = cap === 5 ? "Show top 10 ↓" : "Show top 20 ↓";
  }
  // Pulse the picked countries on the map so table and map visibly agree.
  if (!reducedMotion()) {
    const pickSet = new Set(picks.map((s) => s.iso));
    let pi = 0;
    for (const p of $("valueMap").querySelectorAll("path")) {
      if (pickSet.has(p.getAttribute("data-iso"))) {
        p.classList.add("toppick");
        p.style.animationDelay = (pi++ * 0.25) + "s";
      }
    }
  }
  // The same ranked list the exported PNG carries, on the live map — so what
  // you see is what you would be sharing. It also does the pulse's job for
  // anyone with reduced motion on, where nothing pulses at all.
  renderMapPicksOverlay(picks, month);
  // Gems mirror the popular list's count (5 → 10 → 20 via "Show more") so the
  // two sections always feel like one consistent ranking.
  const gems = (popular.length ? offbeat : []).slice(0, pickCount());
  lastGems = gems;
  const gemsBox = $("gemsBox");
  if (gemsBox) {
    gemsBox.hidden = !gems.length;
    if (gems.length) renderGradeTable($("gemRows"), gems, month, true, true, gemSort);
  }
  const ranked = sortRows(rankedAll, fullSort, FULL_GET).slice(0, 40);
  markSort("#valueTable", fullSort);
  // Same vocabulary as the popular table (rank, flag, the four factor emoji,
  // Overall last on its band), but the raw 0–100 numbers stay: this is "the
  // math". Each number is tinted by its grade so a deal-breaker (weather 32,
  // flights 55) shows without reading every cell; Safety is tinted by the
  // advisory level (SAFE_GRADE), never grade(35) = F, which would contradict
  // the popular table's D. The sorted column is the bold one, by hand or by
  // Rank by, so the emphasis can't sit on a column the rows aren't ordered by.
  const W = loadWeights();
  labelFullRanking(W);
  const hot = fullSort.key;
  const chip = (v, g, title) => `<span class="vchip" data-g="${g}"${title ? ` title="${esc(title)}"` : ""}>${v}</span>`;
  const td = (sk, html) => `<td class="num${sk === hot ? " sorted" : ""}">${html}</td>`;
  $("valueRows").innerHTML = ranked.map((s, i) => {
    const seen = been.has(s.iso);
    const vis = seen ? ' <span class="visited-tag">✓<span class="vtword"> visited</span></span>' : "";
    // The level in its own government's words + whose it is (advLevelText):
    // the State Dept's phrases ("Exercise Increased Caution") credited US
    // wording to Canada's or Germany's.
    const safe = chip(s.safe, SAFE_GRADE[s.advLvl] || "x", advLevelText(s.iso, s.advLvl) + advVia(s.iso))
      + `<span class="vh"> · level ${s.advLvl}</span>`;
    const wx = s.wx == null ? '<span class="muted" title="no weather data">—</span>'
      : chip(s.wx, grade(s.wx), `${s.wx}/100 weather comfort in ${MONTHS[month - 1]}`);
    // An estimated fare is the distance baseline, so its 70 stays grey and
    // says so rather than passing for a measured deal.
    const fly = s.fly == null ? '<span class="muted" title="no fare data">—</span>'
      : s.flyBasis !== "month" && s.fareEst
        ? chip("~" + s.fly, "x", "estimated — no cached fare, scored as a typical fare for the distance")
        : chip(s.fly, grade(s.fly), s.flyBasis === "month"
          ? `${MONTHS[month - 1]}'s fare vs this route's usual`
          : "year-round fare vs a typical fare for the distance");
    return `<tr${seen ? ' class="visited"' : ""}>
      <td class="rank">#${i + 1}</td>
      <td class="dest" title="${esc(s.name)}"><span aria-hidden="true">${flagEmoji(s.iso)}</span> ${esc(s.name)}${vis}</td>
      ${td("afford", chip(s.afford, grade(s.afford), affordTitle(s).replace(" · click for cost-of-living detail", "")))}
      ${td("safety", safe)}${td("weather", wx)}${td("flight", fly)}
      <td class="num ovcell${hot === "value" ? " sorted" : ""}"><span class="gr ${gradeCls(grade(s.value))}" title="${esc(`Overall ${grade(s.value)} · ${s.value}/100`)}">${s.value}</span></td></tr>`;
  }).join("") || '<tr><td colspan="7">No data for this region.</td></tr>';
  // A factor Count leaves out weighs nothing; its row says so instead of
  // showing a level the scorer isn't using.
  document.querySelectorAll("#weightRows .prirow").forEach((r) => {
    const off = !W[r.dataset.w];
    r.classList.toggle("off", off);
    r.title = off ? "Not counted — turn it back on under Count" : "";
  });
  syncURL();
}

// ===========================================================================
//  Flight prices (Travelpayouts)
// ===========================================================================
let flightsData = null;
let flightOrigins = null;

// Travelpayouts affiliate marker (public ID for Aviasales links — distinct from
// the server-side TRAVELPAYOUTS_TOKEN). Bookings made within the cookie window
// after clicking these links earn commission. See FTC disclosure in the footer.
const TP_MARKER = "738472";

// Deep-link an Aviasales search from the current origin hub to a destination
// city. Aviasales' search path is ORIGIN+DDMM (outbound) + DEST+DDMM (return) +
// passengers; we default to ~2 months out for 10 nights, 1 traveler — a sane
// starting point the user can adjust on Aviasales. With a departure month
// ("2026-10") it searches the middle of that month instead (tomorrow, if the
// 15th has passed), so a month's fare links to that month. Returns null if we
// lack the hub or a destination city (older cached fares have no `dest`).
function flightSearchURL(dest, monthKey) {
  if (!dest || !flightsData || !flightsData.hub) return null;
  let dep = new Date(); dep.setDate(dep.getDate() + 60);
  if (/^\d{4}-\d{2}$/.test(monthKey || "")) {
    dep = new Date(+monthKey.slice(0, 4), +monthKey.slice(5) - 1, 15);
    const soon = new Date(); soon.setDate(soon.getDate() + 1);
    if (dep < soon) dep = soon;
  }
  const ret = new Date(dep); ret.setDate(ret.getDate() + 10);
  const p = (n) => String(n).padStart(2, "0");
  const seg = (d) => p(d.getDate()) + p(d.getMonth() + 1);
  const path = flightsData.hub + seg(dep) + dest + seg(ret) + "1";
  return "https://www.aviasales.com/search/" + encodeURIComponent(path) +
         "?marker=" + TP_MARKER;
}

async function ensureOrigins() {
  if (!flightOrigins) flightOrigins = (await getJSON("/api/flight-origins")).origins;
  return flightOrigins;
}

// Populate an origin-country <select>, defaulting to the US.
async function fillOriginSelect(sel) {
  if (sel.options.length > 1) return;
  const list = await ensureOrigins();
  const cur = travelOrigin();   // default to the shared "traveling from", not always US
  sel.innerHTML = list.map((o) =>
    `<option value="${esc(o.iso)}"${o.iso === cur ? " selected" : ""}>${esc(o.name)}</option>`).join("");
  enhanceSelect(sel);
}

// The last selector living outside the one-home-country model: flights kept
// its own origin, so From=Germany on Top Picks still showed US fares here.
// Mirrored both ways now, same pattern as the cost tab's anchor.
function syncFlightOrigin() {
  const fo = $("flightOrigin"), vo = $("valueOrigin");
  if (!fo || fo._synced) return;
  fo._synced = true;
  fo.addEventListener("change", () => {
    if (vo && vo.options.length && vo.value !== fo.value) {
      vo.value = fo.value;
      vo.dispatchEvent(new Event("change"));
    }
  });
}

let _flSeq = 0;
async function loadFlights() {
  syncFlightOrigin();
  const vo = $("valueOrigin");
  if (vo && vo.options.length && $("flightOrigin").options.length
      && $("flightOrigin").value !== vo.value) {
    $("flightOrigin").value = vo.value;
    resyncCombos();
  }
  const origin = $("flightOrigin").value || originIso();
  const seq = ++_flSeq;
  initFlightMonth();    // the picker shows the month while fares load
  clearTimeout(_fvTimer);
  flightValue = null;   // another origin's ranges must never band these fares
  _fvFailed = false; _fvMissed = false;
  resetFbm($("flightOrigin").selectedOptions[0] ? $("flightOrigin").selectedOptions[0].textContent : origin);
  // With the invisible rest of the line renderFlights writes, so the box is
  // already the height that line wraps to (index.html, the same padding).
  $("flightSub").innerHTML = esc("Loading fares from " +
    ($("flightOrigin").selectedOptions[0] ? $("flightOrigin").selectedOptions[0].textContent : origin) + "…")
    + '<span class="skeltext" aria-hidden="true"> vs each route\'s typical <span class="muted">ⓘ</span> · cached by Aviasales, not live</span>';
  let data;
  try {
    data = await getJSON("/api/flights?origin=" + encodeURIComponent(origin));
  } catch (e) {
    if (seq === _flSeq) { $("flightSub").textContent = "Could not load flights: " + e.message; dropLoadingRow("flightRows"); }
    return;
  }
  if (seq !== _flSeq) return;   // an earlier origin's slow reply must not win
  flightsData = data;
  if (!flightsData.configured) {
    $("flightSub").innerHTML = "Flight prices need a free Travelpayouts token. Set <code>TRAVELPAYOUTS_TOKEN</code> on the server (Render → Environment), then redeploy.";
    $("flightMap").textContent = "Not configured.";
    $("flightRows").innerHTML = '<tr><td colspan="7">Add TRAVELPAYOUTS_TOKEN to enable.</td></tr>';
    dropLoadingRow("flightRows");
    syncURL();
    return;
  }
  renderFlights();
  syncURL();
  loadFlightValue(origin, seq, 0);
}

// ---- Flights: the month's fare vs the route's own typical year --------------
// Google Flights' "prices are low / typical / high", across DEPARTURE MONTHS
// rather than booking dates: /api/flight-value sends every destination's
// monthly curve (the guide chart's, number for number) plus its typical range,
// and the month picked here is banded on the spot. The server fills cold
// curves in the background; while it does, re-ask for a bounded while.
let flightValue = null;
let _fvTimer = null;
let _fvPollEnd = 0;
// Polling ended without one usable answer (every request failed): the cells
// say so instead of "Loading…" forever.
let _fvFailed = false;
// The first ask came back with nothing: the room held for what the ranges
// fill (the "Below typical" list, the month chart's note) is let go rather
// than kept blank through up to 15 minutes of retries; a later answer
// draws them as it arrives.
let _fvMissed = false;
// A cold fill of the default origin is at most 174 routes x 3 s of pacing
// ≈ 8.7 min, plus 20 s after a boot and the fares fetch. Waiting 15, 30,
// 45 s between asks, then 60 s, for up to 15 min covers it with room to
// spare; if the server is still filling after that, the note says reload
// instead of promising updates that won't come.
const FV_POLL_MS = 15 * 60 * 1000;
async function loadFlightValue(origin, seq, attempt) {
  if (!attempt) { _fvPollEnd = Date.now() + FV_POLL_MS; _fvFailed = false; _fvMissed = false; }
  let data = null;
  try {
    data = await getJSON("/api/flight-value?origin=" + encodeURIComponent(origin));
  } catch (e) { /* keep what's shown; the next poll may do better */ }
  if (seq !== _flSeq) return;   // origin changed while this was in flight
  const more = (!data || !!data.filling) && Date.now() < _fvPollEnd;
  if (data && data.configured !== false && data.origin === origin) flightValue = data;
  // A guide whose fares strip is still loading: the room held for it
  // (data-fm) now follows this origin's own curve.
  if (flightValue && flightValue.origin === originIso() && ccGuideIso) {
    const gtab = $("tab-guide"), c = flightValue.countries && flightValue.countries[ccGuideIso];
    if (gtab && c && !c.pending && gtab.querySelector(".farecol.loading")) {
      if ((c.n_curve || 0) >= 3) gtab.setAttribute("data-fm", "1"); else gtab.removeAttribute("data-fm");
    }
  }
  if (flightValue) flightValue.gaveUp = !more && !!flightValue.filling;
  _fvFailed = !more && !flightValue;
  const missed = !flightValue && !attempt;
  if (missed) _fvMissed = true;
  if ((flightValue || _fvFailed || missed) && flightsData && flightsData.configured) renderFlights();
  if (more)
    _fvTimer = setTimeout(() => loadFlightValue(origin, seq, attempt + 1),
                          Math.min(60, 15 * (attempt + 1)) * 1000);
}

// The travel month counts as CHOSEN once the reader picks one (Top Picks,
// the guide's month bars, "Departing in") or a link carries ?vmn=. Until
// then it is just "now" — and late in a month "now" is mostly last-minute
// fares and dates already flown, so the Flights tab shows next month instead.
let travelMonthChosen = false;
// The departure month the Flights tab bands: the travel month (#valueMonth,
// the one every tab reads), except an unchosen default after the 15th, which
// shows next month. Display only — nothing is written back (Top Picks keeps
// ranking the travel month) until the reader picks here.
function flightMonthNum(now) {
  const vm = parseInt((ensureMonthOptions() || {}).value, 10) || curMonth();
  if (travelMonthChosen || (now || new Date()).getDate() <= 15) return vm;
  return vm % 12 + 1;
}
// A month number as a departure month key: its NEXT occurrence, the guide
// chart's rule. The server's own 12-month window wins when present, so a
// browser a timezone ahead can't ask for a month the server hasn't reached.
function flightMonthKey(m) {
  const mm = String(m).padStart(2, "0");
  const hit = flightValue && (flightValue.months || []).find((k) => k.slice(5) === mm);
  if (hit) return hit;
  const now = new Date();
  return (m > now.getMonth() ? now.getFullYear() : now.getFullYear() + 1) + "-" + mm;
}

// One country's standing for a departure month. state: ok (banded) | few
// (under min_months of fares — a price, no range) | nomonth (a range, no fare
// that month) | pending (no curve on the server yet) | none | loading |
// failed (polling ended without a single answer).
function fareValue(iso, key) {
  const fv = flightValue;
  if (!fv || !fv.countries) return { state: _fvFailed ? "failed" : "loading" };
  const c = fv.countries[iso];
  if (!c) return { state: "none" };
  if (c.pending) return { state: "pending" };
  const rec = c.curve && c.curve[key];
  const price = rec ? rec[0] : null, city = rec ? rec[1] : null;
  if (c.median == null) return { state: "few", n: c.n_months || 0, c, price, city };
  if (price == null) return { state: "nomonth", c };
  return { state: "ok", price, city, c, dev: price / c.median - 1,
           band: price < c.lo ? "low" : price > c.hi ? "high" : "typical" };
}
const FV_WORD = { low: "Low", typical: "Typical", high: "High" };
// Signed whole percent with a real minus sign: "−24%", "+8%", "0%".
function fmtDevPct(d) {
  const p = Math.round(d * 100);
  return p === 0 ? "0%" : (p < 0 ? "−" : "+") + Math.abs(p) + "%";
}
// Map fill: pale neutral for typical (the site's mid-scale tone), green/red
// deepening with the distance from the median, grey when there's no range.
function fareValueFill(v) {
  if (v.state !== "ok") return NODATA;
  if (v.band === "typical") return "#eef0f1";
  const t = 0.45 + 0.55 * Math.min(1, Math.abs(v.dev) / 0.3);
  return mix("#eef0f1", v.band === "low" ? "#0a7d28" : "#b00020", t);
}
// Mini range bar: the route's cheapest..priciest month, the typical band
// shaded, a dot for this month's fare. Decoration — the numbers are in the tip.
function fareValueBar(v) {
  const c = v.c, vals = Object.values(c.curve).map((x) => x[0]);
  const lo = Math.min(c.lo, ...vals), hi = Math.max(c.hi, ...vals);
  const at = (x) => (hi > lo ? ((x - lo) / (hi - lo)) * 100 : 50).toFixed(1);
  return '<span class="fvbar" aria-hidden="true"><span class="fvtyp" style="left:' + at(c.lo)
    + "%;width:" + (at(c.hi) - at(c.lo)).toFixed(1) + '%"></span><span class="fvdot ' + v.band
    + '" style="left:' + at(v.price) + '%"></span></span>';
}
// Why a row has no pill — said in the tooltip, never guessed at. "Pending"
// only promises an update while one is coming: this page still polling, a
// reload once it has stopped, "later" when the server isn't filling at all
// (a failed lookup waiting out its retry).
function fareValueWhy(v, monthName, money, range) {
  const fv = flightValue, min = (fv && fv.min_months) || 6;
  if (v.state === "loading") return "Loading typical fares…";
  if (v.state === "failed") return "Couldn't load typical fares — reload to retry";
  if (v.state === "pending")
    return !fv.filling ? "This route's monthly fares aren't in yet — try again later"
      : fv.gaveUp ? "Still gathering this route's monthly fares — reload in a few minutes"
      : "Still gathering this route's monthly fares — they'll show here in a few minutes";
  // Counted from the curve, not n_months: a curve with fares is never "none".
  const nc = v.c && v.c.curve ? Object.keys(v.c.curve).length : 0;
  if (v.state === "none" || (v.state === "few" && !nc)) return "No monthly fares cached for this route yet";
  if (v.state === "few") {
    const n = v.n || nc;
    return "Only " + n + " month" + (n === 1 ? "" : "s") + " of cached fares on this route"
      + fvPartialNote(v.c) + " — too few for a typical range (needs " + min + ")";
  }
  return "No cached " + monthName + " fare yet · typical is " + range(v.c.lo, v.c.hi)
    + " across " + v.c.n_months + " months of cached fares" + fvPartialNote(v.c);
}
// Late in a month the server leaves this month's remaining (last-minute)
// fares out of a country's range when 6+ other months remain
// (flightvalue.stats_prices). The curve still shows that fare, so wherever a
// month count is shown, say why it is one short. n_curve > n_months only then.
function fvPartialNote(c, isThatMonth) {
  const fv = flightValue;
  if (!fv || !fv.partial || !c || !c.curve || !c.curve[fv.partial] || !(c.n_curve > c.n_months)) return "";
  return " (the last days of " + MONTHS[+fv.partial.slice(5) - 1]
    + (isThatMonth ? " are last-minute fares, so they don't count toward the range)" : " don't count toward the range)");
}
// Low-pill countries for a departure month, most below typical first: the
// map's pick list. Same Level 3-4 filter as the rows.
function flightLows(countries, key, adv) {
  return countries
    .map((r) => ({ iso: r.iso, v: fareValue(r.iso, key) }))
    .filter((x) => x.v.state === "ok" && x.v.band === "low" && countryName(x.iso) !== x.iso
      && inRegion(x.iso) && (showRisky || (adv[x.iso] || 0) < 3))
    .sort((a, b) => a.v.dev - b.v.dev);
}

// The fare CACHE is USD; the fare DISPLAY is the reader's choice — a German
// flying home from the US wants EUR numbers. Conversion is today's rate over
// the cached fares, display-only (scoring and the budget filter stay in USD),
// which also makes switching currencies instant. Defaults to "My currency".
function flightDisplayCur() {
  try {
    const saved = localStorage.getItem("wg_flightcur");
    if (saved && /^[A-Z]{3}$/.test(saved)) return saved;
  } catch (e) {}
  return /^[A-Z]{3}$/.test(homeBase || "") ? homeBase : "USD";
}
function initFlightCur() {
  const sel = $("flightCur");
  if (!sel || !lastRates) return;
  if (!sel.options.length) {
    // Named and A-Z like "My currency" (buildBaseSelect): the two pickers on
    // this tab used to disagree, this one listing a bare "USD" first.
    sel.innerHTML = pickerCurrencies().map((c) => `<option value="${esc(c)}">${esc(curLabel(c))}</option>`).join("");
    sel.onchange = () => {
      try { localStorage.setItem("wg_flightcur", sel.value); } catch (e) {}
      renderFlights();
    };
    enhanceSelect(sel);
  }
  // Unpinned display currency follows "My currency", same rule as the budget:
  // an explicit pick persists and wins; the default tracks the home switch.
  const want = flightDisplayCur();
  if (sel.value !== want && [...sel.options].some((o) => o.value === want)) sel.value = want;
  if (sel._sync) sel._sync();
}

// Fares are cached in the feed's currency (USD) and shown in the reader's
// pick, converted at today's rate — "≈" marks a conversion.
function flightFmt() {
  const dispCur = ($("flightCur") || {}).value || flightDisplayCur();
  const feedCur = ((flightsData && flightsData.currency) || "usd").toUpperCase();
  const conv = dispCur === feedCur ? 1 : (rateForCurrency(dispCur) || null);
  // Fall back to the feed currency rather than show unconverted numbers under
  // the wrong label.
  const cur = conv ? dispCur : feedCur;
  const F = (v) => (conv ? Math.round(v * conv) : Math.round(v));
  const approx = cur !== feedCur ? "≈" : "";
  // "$295" / "≈€481", the browser's own sign (fmtCur). Plain text: esc() it into HTML.
  const money = (v) => approx + fmtCur(cur, F(v));
  const range = (a, b) => approx + fmtCur(cur, F(a)) + "–" + fmtCur(cur, F(b));
  return { cur, feedCur, F, approx, money, range };
}

function renderFlights() {
  const countries = flightsData.countries || [];
  initFlightCur();
  initFlightMonth();
  const { cur, feedCur, F, approx, money, range } = flightFmt();
  const m = flightMonthNum(), key = flightMonthKey(m), monthName = MONTHS[m - 1];
  const byIso = {};
  for (const c of countries) { c._fv = fareValue(c.iso, key); byIso[c.iso] = c; }

  // One measure on this tab: the month's fare vs the route's typical. (The
  // distance-fit "typical for the distance" lives on only inside the Top
  // Picks Flights grade — two different typicals on one tab read as one.)
  drawMap("flightMap", (f) => {
    const c = byIso[f.properties.iso], v = c ? c._fv : null;
    if (!v) return { fill: NODATA, title: f.properties.name + " — no fares cached" };
    if (v.state !== "ok")
      return { fill: NODATA, title: f.properties.name + " — " + fareValueWhy(v, monthName, money, range) };
    return { fill: fareValueFill(v),
             title: `${f.properties.name} — ${monthName} ${money(v.price)}: ${FV_WORD[v.band]}, `
               + `${fmtDevPct(v.dev)} vs typical ${range(v.c.lo, v.c.hi)}` };
  }, monthName + " flight prices vs each route's typical fare");
  // The list is the table's own ranking cut to the Low pills — a route 13%
  // under its median can still sit inside its own typical range (Mexico's
  // year swings wide), and a "below typical" list must not contradict the
  // pill beside it. An empty list still says so (and where to look next)
  // once any country has a range for the month to be below, or once the fill
  // is done — a far month or a thin origin can have none banded at all. Only
  // while loading or filling with nothing banded does the row go.
  const fv = flightValue;
  const adv = advisoryByIso();
  const best = flightLows(countries, key, adv).slice(0, 8);
  let empty = null;
  const anyBanded = countries.some((c) => c._fv.state === "ok");
  if (!best.length && fv && (anyBanded || !fv.filling)) {
    const later = (fv.months || []).filter((k) => k > key)
      .find((k) => flightLows(countries, k, adv).length);
    empty = (anyBanded ? "Nothing below typical for " + monthName + (fv.filling ? " yet" : "")
                       : "Not enough fares to judge " + monthName + " yet")
      + (later ? " — try " + MONTHS[+later.slice(5) - 1] : "");
  }
  // While the ranges are still on their way (or filling with nothing banded
  // yet) the list is held, not dropped: dropped, the map card lost 91-115px
  // for the moment between the fares and their ranges, and the table under
  // it rode up and back down (768, phones). If they never come, it goes.
  renderDimPicks("flightMap", "Below typical for " + monthName,
    best.map((d) => countryName(d.iso) + " " + fmtDevPct(d.v.dev)), best.map((d) => d.iso), empty,
    null, fv ? fv.filling : !_fvFailed && !_fvMissed);

  const gathering = fv && fv.filling ? fv.total - fv.ready : 0;
  const tip = "Like Google Flights' price insight, but across departure months: a route's typical range is "
    + "the middle half of its cheapest cached fare for each of the next 12 months (never narrower than ±5% "
    + "of the median; in this month's last 9 days its last-minute fares leave the range where 6 other months remain). "
    + "Low = under that range, High = over it; the % is vs the median. Needs "
    + ((fv && fv.min_months) || 6) + "+ months of fares — grey has fewer. Round-trips from "
    + (flightsData.hub || "the main hub") + " that Aviasales has seen in real searches: indicative, not live."
    + (cur !== feedCur ? ` Fares are cached in ${feedCur}; shown ≈${cur} at today's rate.` : "");
  // One line: the affiliate disclosure sits beside the table's fare links
  // (index.html), and the conversion note is in the ⓘ with the rest.
  $("flightSub").innerHTML =
    `${esc(monthName)} fares from ${esc(flightsData.origin_name || flightsData.origin)} vs each route's typical`
    + ` <span class="muted" data-tip="${esc(tip)}" title="">ⓘ</span>`
    + ` · cached by <a href="https://www.aviasales.com" target="_blank" rel="noopener">Aviasales</a>, not live`
    // " · still gathering…", the right-hand card's own wording: joined with a
    // bare space it read "not live Still gathering fares".
    + (gathering > 0 ? ` <span class="muted fvfill">· still gathering fares for ${gathering} ${gathering === 1 ? "country" : "countries"}`
      + (fv.gaveUp ? " — reload in a few minutes to see them." : "…") + "</span>" : "");
  // Legend names the month and the comparison — green isn't "cheap", it's
  // "cheaper than this route usually is".
  $("flightLegend").classList.remove("skel"); $("flightLegend").removeAttribute("aria-hidden");
  $("flightLegend").innerHTML =
    `<span>${esc(MON_ABBR[m - 1])} vs typical:</span><span>Low</span>`
    + '<span class="scale" style="background:linear-gradient(90deg,#0a7d28,#eef0f1 35%,#eef0f1 65%,#b00020)"></span><span>High</span>'
    // Grey is most of this map: a range needs half a year of cached months,
    // and Aviasales only caches routes somebody searched.
    + '<span style="margin-left:6px"><span class="swatch"></span>Not enough fare data</span>';

  markSort("#flightTable", flightSort);
  const mth = document.querySelector('#flightTable th[data-sk="mfare"] .sortbtn');
  if (mth) mth.textContent = MON_ABBR[m - 1] + " fare";
  $("flightRows").innerHTML = sortRows(countries, flightSort, FLIGHT_GET, FLIGHT_GET.dest).map((c) => {
    const v = c._fv;
    const fare = Number(c.avg) ? esc(money(Number(c.avg))) : `${esc(cur)} ?`;
    const cheapest = cheapestFare(c);   // the lower of the cached rows and the month curve
    const url = flightSearchURL(c.dest);
    // revisit: Kiwi — decided Aviasales-only here (2026-07). A Kiwi booking CTA
    // would be price-less (no Kiwi data w/o Tequila) beside this priced,
    // route-specific handoff. Reconsider a SECONDARY "compare on Kiwi" link on
    // the guide (not this table) at the Oct traffic review, A/B-tested. See the
    // affiliate-setup memory note for the full rationale.
    const seen = fmtSeen(c.seen);
    const seenTip = seen ? ` · cheapest fare seen ${seen}` : "";
    const fareCell = url
      ? `<a class="farelink" href="${url}" target="_blank" rel="sponsored nofollow noopener"
            title="Cached fare${seenTip} — click to search ${esc(countryName(c.iso))} live on Aviasales"><b>${fare}</b>&nbsp;<span class="ext">↗</span></a>`
      : `<b>${fare}</b>`;
    // The month's own fare links to that month, on the city that has the
    // price — on a phone it is the one fare link left standing.
    const murl = v.price != null ? flightSearchURL(v.city || c.dest, key) : null;
    const mfare = v.price == null ? '<span class="muted">—</span>'
      : murl ? `<a class="farelink" href="${murl}" target="_blank" rel="sponsored nofollow noopener"
            title="Cheapest cached ${esc(monthName)} round-trip — click to search it live on Aviasales"><b>${esc(money(v.price))}</b>&nbsp;<span class="ext">↗</span></a>`
      : `<b>${esc(money(v.price))}</b>`;
    // Late in a month its own fare can be banded against the other months.
    const partial = v.state === "ok" ? fvPartialNote(v.c, fv && key === fv.partial) : "";
    const vs = v.state === "ok"
      ? `<span class="fv" data-tip="${esc(money(v.price) + " in " + monthName + " vs a typical " + range(v.c.lo, v.c.hi)
          + " (median " + money(v.c.median) + ") across " + v.c.n_months + " months of cached fares" + partial)}" title="">`
        + `<span class="fvband ${v.band}">${FV_WORD[v.band]}</span><span class="fvpct ${v.band}">${fmtDevPct(v.dev)}</span>`
        + fareValueBar(v) + "</span>"
      : `<span class="fv na" data-tip="${esc(fareValueWhy(v, monthName, money, range))}" title="">${v.state === "loading" || (v.state === "pending" && fv.filling) ? "…" : "—"}</span>`;
    return `<tr data-iso="${esc(c.iso)}" title="See the ${esc(countryName(c.iso))} travel guide →"><td><a class="destlink" href="${esc(guidePath(c.iso))}">${esc(countryName(c.iso))}</a></td>
      <td>${vs}</td>
      <td class="num">${mfare}</td>
      <td class="num">${fareCell}</td>
      <td class="num">${cheapest ? esc(money(cheapest)) : `${esc(cur)} ?`}</td>
      <td class="num"${c.dur && c.dur_city ? ` title="to ${esc(c.dur_city)}, one way — the most direct cached flight"` : ""}>${fmtDuration(c.dur)}</td>
      <td class="num">${fmtStops(c.stops)}</td></tr>`;
  }).join("")
    || '<tr><td colspan="7">No fares found from this country.</td></tr>';
  applyFlightFilter();
  $("flightMap")._onPick = (iso) => setFbmCountry(iso);
  renderFbm();
}

// ---- Flights: fares by month -----------------------------------------------
// Beside the map, Google Flights' price graph by departure month: the picked
// destination's cheapest cached round-trip for each of the next 12 months,
// its typical range shaded and each bar coloured Low / Typical / High the way
// the map is. With no destination picked, every destination at once: each
// month's median fare vs each route's own typical — "when is it cheap to fly
// anywhere from here". A month bar sets the travel month for the whole site.
let fbmIso = (() => { const v = new URLSearchParams(location.search).get("fc") || ""; return /^[A-Z]{2}$/.test(v) ? v : "all"; })();
function setFbmCountry(iso) {
  // The origin itself is no destination (domestic flights aren't listed).
  fbmIso = iso && !(flightsData && iso === flightsData.origin) ? iso : "all";
  renderFbm();
  syncURL();
}
const median = (a) => { const b = a.slice().sort((x, y) => x - y), n = b.length;
  return n ? (n % 2 ? b[(n - 1) / 2] : (b[n / 2 - 1] + b[n / 2]) / 2) : null; };
// The note renderFbm writes under the month bars, invisibly, while they
// load (index.html has the same): it wraps where the real one will — two
// lines in a narrow column (768, phones), where a held single line grew to
// two when it came (17 -> 35px).
const FBM_NOTE_SKEL = '<span class="skeltext" aria-hidden="true">Best month: Feb (−12% vs typical). Tap a month to plan for it. <span class="muted">ⓘ</span></span>';
// A new From: nothing of the old origin's chart may stay up while its fares load.
function resetFbm(originName) {
  const host = $("fbmChart");
  if (!host) return;
  host.innerHTML = "<p class='hint'>" + esc("Loading fares" + (originName ? " from " + originName : "") + "…") + "</p>";
  host._redraw = null;
  for (const id of ["fbmNow", "fbmChg"]) $(id).textContent = "";
  $("fbmNote").innerHTML = FBM_NOTE_SKEL;
  $("fbmChg").className = "";
}

function renderFbm() {
  const host = $("fbmChart");
  if (!host || !flightsData || !flightsData.configured) return;
  const fv = flightValue;
  const { money, range, F, cur, approx } = flightFmt();
  const m = flightMonthNum(), key = flightMonthKey(m);
  const origin = flightsData.origin_name || flightsData.origin || "here";
  if (fbmIso !== "all" && (fbmIso === flightsData.origin || countryName(fbmIso) === fbmIso)) fbmIso = "all";
  // Destinations with any cached month, A-Z (the list grows while the server
  // is still filling). The picked one is always listed, fares or not, so the
  // control never names another destination than the chart.
  const sel = $("fbmPick");
  const withFares = fv && fv.countries ? Object.keys(fv.countries)
    .filter((iso) => { const c = fv.countries[iso]; return c && !c.pending && c.curve && Object.keys(c.curve).length
      && countryName(iso) !== iso && inRegion(iso); })
    .sort((a, b) => countryName(a).localeCompare(countryName(b))) : [];
  const extra = fbmIso !== "all" && !withFares.includes(fbmIso) ? fbmIso : null;
  const sig = withFares.join(",") + "|" + (extra || "");
  if (sel && sel._sig !== sig) {
    sel._sig = sig;
    sel.innerHTML = '<option value="all">🌍 All destinations</option>'
      + (extra ? `<option value="${esc(extra)}">${esc(countryName(extra))} (no fares yet)</option>` : "")
      + withFares.map((iso) => `<option value="${esc(iso)}">${esc(countryName(iso))}</option>`).join("");
    if (!sel._fbmWired) { sel._fbmWired = true; sel.addEventListener("change", () => setFbmCountry(sel.value)); }
    enhanceSelect(sel);
  }
  if (sel && sel.value !== fbmIso) { sel.value = fbmIso; if (sel._sync) sel._sync(); }
  const months = (fv && fv.months) || [];
  // `holding`: the bars are still on their way, so the note keeps its room,
  // and so does the number box (styles.css, unless data-nofig: with no
  // figure coming it would be a blank 306px beside the title).
  const clear = (msg, holding) => {
    host.innerHTML = "<p class='hint'>" + esc(msg) + "</p>";
    host._redraw = null;
    for (const id of ["fbmNow", "fbmChg"]) $(id).textContent = "";
    $("fbmNote").innerHTML = holding ? FBM_NOTE_SKEL : "";
    $("fbmChg").className = "";
    $("fbmCard").toggleAttribute("data-nofig", !holding);
  };
  const monthWord = (k) => MONTHS[+k.slice(5) - 1] + " " + k.slice(0, 4);
  // This month, late in it: what's left is last-minute fares (the tab bands it
  // apart the same way) — drawn faded, and never "the cheapest month".
  const partial = fv && fv.partial;
  const filling = fv && fv.filling ? ` · still gathering fares (${fv.ready} of ${fv.total} routes)` : "";
  $("fbmCard").removeAttribute("data-nofig");
  if (!months.length) {
    // Invisible tails of the full title and sub-line (index.html's): this
    // is the loading state, and the header keeps the size it will have —
    // only while the ranges may still come, or it is blank space for good.
    const holding = !_fvFailed && !_fvMissed;
    $("fbmH2").innerHTML = 'Fares by month' + (holding ? ' <span class="muted skeltext" aria-hidden="true">all destinations</span>' : "");
    $("fbmSub").innerHTML = esc("From " + origin) + (holding
      ? '<span class="skeltext" aria-hidden="true"> · each month vs each route\'s typical fare (median of up to 45 routes)</span>' : "");
    clear(_fvFailed ? "Couldn't load the fare ranges — try again later." : "Loading fares…", holding);
    return;
  }
  let items, band = null, mode;
  if (fbmIso === "all") {
    mode = "dev";
    items = months.map((k) => {
      const devs = [];
      for (const iso in fv.countries) {
        const c = fv.countries[iso];
        if (!c || c.pending || c.median == null || !c.curve || !c.curve[k] || !inRegion(iso)) continue;
        devs.push(c.curve[k][0] / c.median - 1);
      }
      return { key: k, value: devs.length >= 5 ? median(devs) : null, n: devs.length };
    });
    const ns = items.map((i) => i.n);
    $("fbmH2").innerHTML = 'Fares by month <span class="muted">all destinations'
      + (regionSel === "all" ? "" : " in " + esc(REGIONS[regionSel])) + "</span>";
    $("fbmSub").textContent = `From ${origin} · each month vs each route's typical fare (median of up to ${Math.max(...ns)} routes)` + filling;
  } else {
    mode = "price";
    const c = fv.countries[fbmIso];
    const name = countryName(fbmIso);
    $("fbmH2").innerHTML = `Fares by month <span class="muted">${esc(name)}</span>`;
    if (!c || c.pending) {
      $("fbmSub").textContent = `From ${origin} to ${name}`;
      clear(c && c.pending && fv.filling ? `Still gathering fares to ${name}…` : `No cached fares to ${name} from ${origin} — pick another destination, or All destinations.`,
            !!(c && c.pending && fv.filling));
      return;
    }
    // Charted in the display currency, so the axis steps are round in it
    // (USD steps converted read "EUR 176, 351, 527").
    items = months.map((k) => { const r = c.curve && c.curve[k]; return { key: k, value: r ? F(r[0]) : null, city: r ? r[1] : null }; });
    if (c.median != null) band = { lo: F(c.lo), hi: F(c.hi), median: F(c.median) };
    $("fbmSub").textContent = `From ${origin} · cheapest cached round-trip per departure month`
      + (band ? ` · typical ${range(c.lo, c.hi)}` : "") + filling;
  }
  for (const it of items) it.partial = it.key === partial;
  if (items.filter((i) => i.value != null).length < 2) {
    clear(fbmIso === "all" ? "Not enough fares yet to compare months." : "Too few cached months to chart — pick another destination, or All destinations.");
    return;
  }
  const show = (v) => approx + cur + " " + Math.round(v).toLocaleString();
  const bandOf = (it) => (it.value == null ? null
    : mode === "dev" ? (it.value < -0.05 ? "low" : it.value > 0.05 ? "high" : "typical")
    : band ? (it.value < band.lo ? "low" : it.value > band.hi ? "high" : "typical") : null);
  const head = (it) => {
    const now = $("fbmNow"), chg = $("fbmChg"), b = bandOf(it);
    const when = monthWord(it.key) + (it.partial ? " (last days — last-minute fares)" : "");
    chg.className = "";
    if (it.value == null) {
      now.textContent = "—";
      chg.textContent = when + " · " + (mode === "dev" ? `too few routes to compare (${it.n})` : "no fares cached");
      return;
    }
    if (mode === "dev") {
      now.textContent = fmtDevPct(it.value);
      chg.textContent = when + " · " + (b === "low" ? "cheaper than usual" : b === "high" ? "pricier than usual" : "about usual")
        + ` · ${it.n} routes`;
    } else {
      now.textContent = show(it.value);
      chg.textContent = when + (b ? " · " + FV_WORD[b] + (band && b !== "typical" ? ", " + fmtDevPct(it.value / band.median - 1) + " vs its median" : "") : "");
    }
    chg.className = b === "low" ? "pos" : b === "high" ? "neg" : "";
  };
  const selIt = items.find((i) => i.key === key) || items.find((i) => i.value != null);
  head(selIt);
  const ranked = items.filter((i) => i.value != null && !i.partial);
  const cheapest = ranked.length ? ranked.reduce((a, b) => (b.value < a.value ? b : a)) : null;
  $("fbmNote").innerHTML = esc((cheapest ? `Best month: ${MON_ABBR[+cheapest.key.slice(5) - 1]} (${mode === "dev" ? fmtDevPct(cheapest.value) + " vs typical" : show(cheapest.value)}). ` : "")
    + "Tap a month to plan for it.")
    + ` <span class="muted" data-tip="${esc(mode === "dev"
      ? "For each destination with 6+ months of fares, a month's cheapest cached round-trip is compared with that route's own median; the bar is the median of those comparisons (5+ routes). Green/red = more than 5% below/above usual. Far-off months have fewer cached searches, so fewer routes."
      : "The cheapest cached round-trip per departure month (Aviasales, real searches, not live). Shaded = the route's typical range — the middle half of its months, never narrower than ±5% of the median; green bars fall below it, red above. A faded bar is this month's last days (last-minute fares)." + (band ? "" : " This route has too few months of fares for a typical range, so its bars aren't coloured."))}" title="">ⓘ</span>`;
  const typ = cssVar("--fvtyp", "#b7bec6");
  monthBars(host, items, {
    mode, band, sel: key,
    fmt: (v) => (mode === "dev" ? fmtDevPct(v) : cur + " " + Math.round(v).toLocaleString()),
    colorOf: (it) => { const b = bandOf(it);
      return b === "low" ? cssVar("--green", "#0a7d28") : b === "high" ? cssVar("--red", "#b00020") : b === "typical" ? typ : null; },
    aria: (fbmIso === "all" ? "Fares by month, all destinations" : "Fares by month to " + countryName(fbmIso))
      + (cheapest ? ", best month " + monthWord(cheapest.key) : "") + ". Use the arrow keys to read each month, Enter to plan for it.",
    onScrub: (i) => head(items[i]),
    onLeave: () => head(selIt),
    onPick: (i) => { if (items[i].value != null) planForMonth(+items[i].key.slice(5), true); },
  });
}

// Twelve month bars, stock-chart style: axis on the right, drawn at the box's
// own size (a card row's box is sized by the layout — see stockChart). mode
// "price" bars rise from zero with the typical band shaded and its median
// dashed; mode "dev" bars go up or down from a "typical" zero line. The
// travel month is outlined; hovering scrubs, a tap picks; the chart takes
// focus, arrow keys scrub and Enter picks. colorOf null = an outlined bar
// (no range to judge it against); it.partial = faded.
function monthBars(host, items, o) {
  const W = Math.round(host.clientWidth) || 800;
  const fillBox = !!host.closest(".toprow");
  const H = fillBox && host.clientHeight >= 150 ? Math.round(host.clientHeight)
    : Math.max(190, Math.min(300, Math.round(W * 0.4)));
  const vals = items.map((i) => i.value).filter((v) => v != null);
  let lo, hi;
  if (o.mode === "dev") {
    lo = Math.min(0, ...vals); hi = Math.max(0, ...vals);
    const pad = (hi - lo) * 0.12 || 0.05; lo -= pad; hi += pad;
  } else {
    lo = 0; hi = Math.max(...vals, o.band ? o.band.hi : 0) * 1.12;
  }
  let step = niceStep(hi - lo, 4);
  for (const n of [5, 6, 8]) {
    if (Math.floor(hi / step) - Math.ceil(lo / step) + 1 >= 3) break;
    step = niceStep(hi - lo, n);
  }
  const levels = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) levels.push(Math.abs(v) < 1e-9 ? 0 : v);
  const lab = (v) => o.fmt(v);
  const padL = 2, padT = 12, padB = 26;
  // "typical" names its own line in the axis column, where the other values
  // are read: the dev chart's zero ("0%" said nothing a reader could use) and
  // the price chart's dashed median. It used to float over the last bar.
  const typAt = o.mode === "dev" ? 0 : o.mode === "price" && o.band ? o.band.median : null;
  const padR = Math.max(46, Math.ceil(7 * Math.max(typAt != null ? 7 : 0, ...levels.map((v) => lab(v).length))) + 12);
  const plotW = W - padL - padR, plotH = H - padT - padB, right = W - padR;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  const n = items.length, slot = plotW / n, bw = Math.max(6, Math.min(34, slot * 0.64));
  const xs = (i) => padL + i * slot + (slot - bw) / 2;
  const gridCol = cssVar("--chartgrid", "#eee"), labCol = cssVar("--gray", "#999"), ink = cssVar("--ink", "#111");
  const card = cssVar("--card", "#fff");
  let g = "", marks = "";
  const typY = typAt != null ? y(typAt) : null;
  for (const v of levels) {
    const gy = y(v).toFixed(1);
    g += `<line x1="${padL}" y1="${gy}" x2="${right}" y2="${gy}" stroke="${gridCol}" stroke-width="1"/>`;
    // A value label that would sit on the "typical" one gives way to it (the
    // dev chart's own zero, or a price tick within a line's height of the median).
    if (typY == null || Math.abs(+gy - typY) >= 14)
      g += `<text x="${right + 8}" y="${(+gy + 4).toFixed(1)}" font-size="12" fill="${labCol}">${esc(lab(v))}</text>`;
  }
  if (typY != null)
    marks += `<text x="${right + 8}" y="${(typY + 4).toFixed(1)}" font-size="12" font-weight="600" fill="${ink}">typical</text>`;
  if (o.mode === "price" && o.band) {
    const ty = y(o.band.hi), by = y(o.band.lo), my = y(o.band.median).toFixed(1);
    g += `<rect x="${padL}" y="${ty.toFixed(1)}" width="${plotW.toFixed(1)}" height="${Math.max(1, by - ty).toFixed(1)}" fill="${labCol}" opacity=".13"/>`
      + `<line x1="${padL}" y1="${my}" x2="${right}" y2="${my}" stroke="${labCol}" stroke-width="1" stroke-dasharray="4 4"/>`;
  }
  const zeroY = y(o.mode === "dev" ? 0 : lo);
  if (o.mode === "dev") {
    g += `<line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${right}" y2="${zeroY.toFixed(1)}" stroke="${labCol}" stroke-width="1.2" stroke-dasharray="4 4"/>`;
  }
  let bars = "", xl = "";
  // Every month labelled where it fits; otherwise every other one, counted
  // from the travel month so its own label never crowds a neighbour's.
  const labEvery = slot < 26 ? 2 : 1;
  const selIdx = Math.max(0, items.findIndex((it) => it.key === o.sel));
  items.forEach((it, i) => {
    const x = xs(i), mo = +it.key.slice(5), isSel = i === selIdx && it.key === o.sel;
    if (it.value != null) {
      const top = Math.min(y(it.value), zeroY), h = Math.max(1.5, Math.abs(zeroY - y(it.value)));
      const col = o.colorOf(it);
      const op = it.partial ? 0.35 : isSel ? 1 : 0.8;
      bars += `<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3"`
        + (col ? ` fill="${col}"` : ` fill="none" stroke="${labCol}" stroke-width="1.5"`)
        + ` opacity="${op}"${isSel ? ` stroke="${ink}" stroke-width="2"` : ""}/>`;
    } else {
      bars += `<line x1="${x.toFixed(1)}" y1="${(zeroY - 1).toFixed(1)}" x2="${(x + bw).toFixed(1)}" y2="${(zeroY - 1).toFixed(1)}" stroke="${labCol}" stroke-width="2" stroke-dasharray="2 3"/>`;
    }
    if ((i - selIdx) % labEvery === 0)
      xl += `<text x="${(padL + i * slot + slot / 2).toFixed(1)}" y="${H - 7}" font-size="12" text-anchor="middle"`
        + ` fill="${isSel ? ink : labCol}"${isSel ? ' font-weight="700"' : ""}>${MON_ABBR[mo - 1]}${it.partial ? "*" : ""}</text>`;
  });
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="${esc(o.aria || "")}">${g}${bars}${marks}${xl}`
    + `<rect class="scrub" y="${padT}" height="${plotH}" width="${slot.toFixed(1)}" fill="${labCol}" opacity="0" pointer-events="none"/></svg>`;
  const svg = host.querySelector("svg"), sc = svg.querySelector(".scrub");
  const at = (e) => {
    const r = svg.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    return Math.max(0, Math.min(n - 1, Math.floor((vx - padL) / slot)));
  };
  const mark = (i) => { sc.setAttribute("x", (padL + i * slot).toFixed(1)); sc.setAttribute("opacity", ".08"); if (o.onScrub) o.onScrub(i); };
  let down = null, kbd = selIdx;
  svg.addEventListener("pointermove", (e) => mark(at(e)));
  svg.addEventListener("pointerdown", (e) => { down = { x: e.clientX, i: at(e) }; });
  svg.addEventListener("pointerup", (e) => {
    const tap = down && Math.abs(e.clientX - down.x) < 8 && o.onPick;
    down = null;
    // A finger lifting ends the scrub BEFORE the pick: the pick redraws with
    // the new month's headline, which a late onLeave would overwrite.
    if (e.pointerType !== "mouse") { sc.setAttribute("opacity", "0"); if (o.onLeave) o.onLeave(); }
    if (tap) o.onPick(at(e));
  });
  const off = () => { down = null; sc.setAttribute("opacity", "0"); if (o.onLeave) o.onLeave(); };
  svg.addEventListener("pointerleave", off);
  svg.addEventListener("pointercancel", off);
  // Keyboard: the same scrub and pick, month by month.
  svg.addEventListener("focus", () => mark(kbd));
  svg.addEventListener("blur", off);
  svg.addEventListener("keydown", (e) => {
    const k = e.key;
    if (k === "ArrowRight" || k === "ArrowLeft" || k === "Home" || k === "End") {
      e.preventDefault();
      kbd = k === "Home" ? 0 : k === "End" ? n - 1 : Math.max(0, Math.min(n - 1, kbd + (k === "ArrowRight" ? 1 : -1)));
      mark(kbd);
    } else if ((k === "Enter" || k === " ") && o.onPick) {
      e.preventDefault();
      o.onPick(kbd);
      const again = host.querySelector("svg");
      if (again) again.focus();
    }
  });
  host._w = W; host._h = H;
  host._redraw = () => monthBars(host, items, o);
  if (!host._ro && window.ResizeObserver) {
    host._ro = new ResizeObserver(() => requestAnimationFrame(() => refitChart(host)));
    host._ro.observe(host);
  }
}

// "Departing in" IS the travel month (#valueMonth), mirrored the way From is:
// October here ranks Top Picks for October too, and the other way round. It
// shows the month the tab bands (flightMonthNum), which late in a month is
// next month until one is chosen — so re-picking the month on screen is
// still a pick: "pick", not "change", which only fires when the value moves.
function initFlightMonth() {
  const sel = $("flightMonth");
  if (!sel || !ensureMonthOptions()) return;
  if (!sel.options.length) {
    sel.innerHTML = MONTHS.map((mn, i) => `<option value="${i + 1}">${mn}</option>`).join("");
    sel.addEventListener("pick", () => planForMonth(parseInt(sel.value, 10), true));
    enhanceSelect(sel);
  }
  const want = String(flightMonthNum());
  if (sel.value !== want) { sel.value = want; if (sel._sync) sel._sync(); }
}
// Top Picks' own month picker (and the guided picker, which fires change on
// it only when the reader changed the month there). Re-picking the month
// already shown is a choice too: "pick" fires on every combo choice.
function markTravelMonthChosen() {
  travelMonthChosen = true;
  if (loaded.flights && flightsData && flightsData.configured) renderFlights();
}
$("valueMonth").addEventListener("change", markTravelMonthChosen);
// A changed pick already ran the above via "change"; an unchanged one only
// changes whether the month counts, so the address bar gains its vmn too.
$("valueMonth").addEventListener("pick", () => { if (!travelMonthChosen) { markTravelMonthChosen(); syncURL(); } });

// Relative freshness of a cached fare from its found_at timestamp: "today",
// "3 days ago", "2 weeks ago", "4 months ago". Empty string if unknown.
function fmtSeen(ts) {
  if (!ts) return "";
  const t = Date.parse(ts);
  if (isNaN(t)) return "";
  const days = Math.floor((Date.now() - t) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return days + " days ago";
  if (days < 60) return Math.round(days / 7) + " weeks ago";
  return Math.round(days / 30) + " months ago";
}

// Minutes -> "13h 25m"; null when the provider didn't return a duration.
function fmtDuration(mins) {
  const m = Number(mins);
  if (!m || m <= 0) return "—";
  const h = Math.floor(m / 60), r = m % 60;
  return (h ? h + "h" : "") + (r ? " " + r + "m" : (h ? "" : r + "m")) || "—";
}
// Layovers each way: the table's are the most direct cached flight's, the
// month strips' the cheapest fare's.
function fmtStops(stops) {
  if (stops == null) return "—";
  const n = Number(stops);
  return n === 0 ? '<span class="pos">nonstop</span>' : n + (n === 1 ? " stop" : " stops");
}

// Changing the flights "From" updates the one shared origin (so Top Picks, the
// guide visa, and the AI prompts follow too), then reloads fares.
$("flightOrigin").addEventListener("change", () => setTravelOrigin($("flightOrigin").value));

// ---- Explore-the-Data table filters ----------------------------------------
// Generic row filter: hide rows whose text doesn't match, skipping the
// placeholder/empty rows (which have a single cell).
// A filter that hid every row left a bare header with no word of why, so one
// "No matches" row stands in (one cell, so the next pass skips it too). Its
// own class: applyFlightFilter clears .jumpempty rows right after this.
function filterRows(tbodyId, predicate) {
  const tb = $(tbodyId);
  if (!tb) return;
  tb.querySelectorAll("tr.filterempty").forEach((r) => r.remove());
  let rows = 0, shown = 0;
  for (const tr of tb.querySelectorAll("tr")) {
    if (tr.children.length < 2) continue;
    const ok = predicate(tr);
    tr.style.display = ok ? "" : "none";
    rows++; if (ok) shown++;
  }
  if (rows && !shown) {
    const table = tb.closest("table");
    const n = (table && table.querySelectorAll("thead th").length) || 1;
    tb.insertAdjacentHTML("beforeend", `<tr class="filterempty"><td colspan="${n}">No matches</td></tr>`);
  }
}
const _q = (id) => (($(id) && $(id).value) || "").trim().toLowerCase();
// One-shot "exactly this country" from a Top Picks jump: matches on the row's
// iso while the filter box still holds the name the jump put there, and lapses
// the moment the visitor edits it.
let _jump = null;   // { box, q, iso }
function jumpActive(box) {
  return _jump && _jump.box === box && _q(box) === _jump.q ? _jump.iso : null;
}
function rowMatches(tr, box, q) {
  const iso = jumpActive(box);
  if (iso) return tr.dataset.iso === iso;
  return !q || tr.textContent.toLowerCase().includes(q);
}

// "Include higher-risk (L3–4)" is one answer for the Data tab, not one per table.
// Currency hid Level 3–4 by default; Cost of living and Flights had no such filter
// at all, so Iran and Afghanistan (both Do Not Travel) sat at the top of Cost of
// living while the same countries were hidden one sub-tab over. Three checkboxes,
// one state — mirrored, the way the currency pickers are.
const RISKY_KEY = "wg_showrisky";
let showRisky = localStorage.getItem(RISKY_KEY) === "1";
const RISKY_BOXES = ["curRisky", "affRisky", "flightRisky"];

function riskyOf(tr) {
  // Currency rows carry data-adv; the others carry the iso, so look it up.
  const d = parseInt(tr.dataset.adv || "0", 10);
  if (d) return d >= 3;
  const lvl = tr.dataset.iso ? advisoryByIso()[tr.dataset.iso] : 0;
  return (lvl || 0) >= 3;
}

function setShowRisky(on, persist) {
  showRisky = !!on;
  if (persist) localStorage.setItem(RISKY_KEY, showRisky ? "1" : "0");
  for (const id of RISKY_BOXES) {
    const el = $(id);
    if (el && el.checked !== showRisky) el.checked = showRisky;
  }
  applyCurrencyFilter(); applyAffordFilter(); applyFlightFilter();
  // The "cheapest" lists under the maps mirror their tables' risk filter.
  if (loaded.afford && ppp) renderAfford();
  if (loaded.flights && flightsData && flightsData.configured) renderFlights();
}

function applyCurrencyFilter() {
  const q = _q("curFilter");
  filterRows("rows", (tr) => {
    if (!showRisky && riskyOf(tr)) return false;
    if (!regionRowOk(tr)) return false;
    // Row text names currencies; dataset.q adds the countries that use them.
    return !q || (tr.textContent + " " + (tr.dataset.q || "")).toLowerCase().includes(q);
  });
}
function applyAffordFilter() {
  const q = _q("affFilter");
  filterRows("affRows", (tr) => {
    if (!showRisky && riskyOf(tr)) return false;
    if (!regionRowOk(tr)) return false;
    return rowMatches(tr, "affFilter", q);
  });
}
function applyAdvFilter() {
  const q = _q("advFilter");
  const lvl = ($("advLevel") && $("advLevel").value) || "all";
  // The name only: the rows now carry disease and reason chips, and "congo"
  // matched 26 countries (Crimean-Congo fever), "den" 93.
  const jumpIso = jumpActive("advFilter");
  const de = !!(advisories && advisories.source === "de");
  filterRows("advRows", (tr) =>
    advLvlMatch(lvl, tr.dataset.lvl, tr.dataset.via, de) && regionRowOk(tr)
    && (jumpIso ? tr.dataset.iso === jumpIso : !q || (tr.cells[0] ? tr.cells[0].textContent : "").toLowerCase().includes(q)));
  // An open notes row follows its country: hidden with it, back with it.
  for (const d of $("advRows").querySelectorAll("tr.wodetail")) {
    const p = d.previousElementSibling;
    d.style.display = p && p.style.display === "none" ? "none" : "";
  }
}
function applyFlightFilter() {
  const q = _q("flightFilter");
  filterRows("flightRows", (tr) => {
    if (!showRisky && riskyOf(tr)) return false;
    if (!regionRowOk(tr)) return false;
    return rowMatches(tr, "flightFilter", q);
  });
  // The "~" on Top Picks promises the Flights tab; a country with no cached
  // fare used to land on an empty table with no word of why. One-cell row, so
  // filterRows leaves it alone; rebuilt on every filter pass.
  const tb = $("flightRows");
  if (!tb) return;
  tb.querySelectorAll("tr.jumpempty").forEach((r) => r.remove());
  const iso = jumpActive("flightFilter");
  if (iso && flightsData && tb.querySelector("tr[data-iso]") && !tb.querySelector(`tr[data-iso="${iso}"]`)) {
    tb.querySelectorAll("tr.filterempty").forEach((r) => r.remove());   // this says why; not both
    tb.insertAdjacentHTML("afterbegin", `<tr class="jumpempty"><td colspan="7">No cached fares from `
      + `${esc(flightsData.origin_name || countryName(flightsData.origin))} to ${esc(countryName(iso))} yet — `
      + "the grey “~” grade on Top Picks is a distance-based estimate.</td></tr>");
  }
}
// Wire filter controls once (elements are static in the markup).
// The Safety sub-tab is deliberately absent: listing advisories is its whole job,
// and it has its own level select. Hiding Level 4 there would hide the point.
[["curFilter", applyCurrencyFilter],
 ["affFilter", applyAffordFilter], ["advFilter", applyAdvFilter],
 ["advLevel", applyAdvFilter], ["flightFilter", applyFlightFilter]
].forEach(([id, fn]) => {
  const el = $(id);
  if (el) el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", fn);
});
// All three risk checkboxes drive the one shared answer.
RISKY_BOXES.forEach((id) => {
  const el = $(id);
  if (el) { el.checked = showRisky; el.addEventListener("change", () => setShowRisky(el.checked, true)); }
});

// ===========================================================================
//  Things to do (curated activities + what's in season now)
// ===========================================================================
let activities = null;
function curMonth() { return new Date().getMonth() + 1; }   // 1-12, real browser clock

async function ensureActivities() {
  if (!activities) activities = await (await fetch("/activities.json")).json();
  return activities;
}

// ---- visa requirements ------------------------------------------------------
// US passports use the curated visa.json (notes + official State Dept links).
// Every other "From" country uses a passport×destination matrix derived from
// the MIT-licensed Passport Index dataset, loaded lazily.
let visa = null;
async function ensureVisa() {
  if (!visa) visa = await (await fetch("/visa.json")).json();
  return visa;
}
let visaMatrix = null;
async function ensureVisaMatrix() {
  if (!visaMatrix) visaMatrix = await (await fetch("/visa-passport.json")).json();
  return visaMatrix;
}
const MX_STATUS = { f: "free", t: "eta", v: "voa", e: "evisa", r: "required", x: "special" };
const VISA_META = {
  free:     { label: "Visa-free",   cls: "vfree",  long: "Visa-free entry" },
  eta:      { label: "eTA",         cls: "veasy",  long: "Electronic travel authorization (apply online)" },
  voa:      { label: "On arrival",  cls: "veasy",  long: "Visa on arrival" },
  evisa:    { label: "eVisa",       cls: "vmid",   long: "eVisa — apply online before you go" },
  required: { label: "Visa req'd",  cls: "vhard",  long: "Visa required in advance (embassy/consulate)" },
  special:  { label: "Restricted",  cls: "vhard",  long: "Special restrictions apply" },
  check:    { label: "Check",       cls: "vchk",   long: "Requirements vary — verify before booking" },
};
// When the visa data was last checked by hand. There is no reliable free visa
// API, so these tables are curated and can only be as fresh as the last review
// — saying so beats implying a freshness we can't guarantee, especially on data
// where being wrong costs someone a trip. Read from the files themselves so the
// date can never drift from what shipped.
function visaVerified(passport) {
  const src = passport === "US" ? visa : visaMatrix;
  const raw = src && src._verified;
  if (!raw) return "";
  const [y, m] = raw.split("-");
  const MON = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"];
  return m ? MON[+m - 1] + " " + y : y;
}
function visaInfo(iso, passport) {
  passport = /^[A-Z]{2}$/.test(passport) ? passport : "US";
  // England etc. are entered on UK rules, and are home to a UK passport.
  const viso = GUIDE_PARENT[iso] || iso;
  // Guernsey, Jersey and the Isle of Man admit visitors on UK rules (Common
  // Travel Area). Not the Faroes: Denmark's Schengen rules don't reach them.
  const cta = { GG: "GB", JE: "GB", IM: "GB" }[iso];
  if (passport === viso) return { home: true, passport };   // their own country
  if (passport === "US") {
    const v = visa && (visa[iso] || visa[viso]);
    if (!v || !v.status) return null;
    const meta = VISA_META[v.status] || VISA_META.check;
    return { status: v.status, note: v.note || "", meta, link: v.link || "", passport };
  }
  const code = visaMatrix && visaMatrix[passport]
    && (visaMatrix[passport][viso] || (cta && visaMatrix[passport][cta]));
  if (!code) return null;
  let status, note = "";
  if (/^\d+$/.test(code)) { status = "free"; note = code + " days"; }
  else { status = MX_STATUS[code] || "check"; }
  return { status, note, meta: VISA_META[status] || VISA_META.check, link: "", passport };
}

// Emoji for the (small, fixed) set of profile tags, and a keyword matcher that
// gives each activity / seasonal line a leading icon so the guide scans fast.
const PROFILE_EMOJI = {
  "Nature": "🌿", "Culture": "🏛️", "Beach & islands": "🏖️", "Adventure": "🥾",
  "City": "🏙️", "Food": "🍴", "Shopping": "🛍️",
};
const ACT_EMOJI = [
  [/aurora|northern lights|white nights/, "🌌"], [/whale|dolphin/, "🐋"],
  [/cherry blossom|sakura|blossom/, "🌸"], [/autumn leaves|foliage|fall colou?r|autumn colou?r/, "🍁"],
  [/migration/, "🦓"], [/garden|tulip|flower|keukenhof/, "🌷"],
  [/railway|train|trans-?siberian|metro|tram/, "🚆"], [/\bice\b|frozen|glacier/, "🧊"],
  [/opera|ballet|theat/, "🎭"], [/hermitage|museum|galler|\bart\b/, "🖼️"], [/red square/, "🏛️"],
  [/cheese/, "🧀"], [/rice terrace|paddy/, "🌾"], [/tulip/, "🌷"],
  [/beer|oktoberfest|brewery|pub/, "🍺"], [/flamenco|tango|salsa|dance/, "💃"],
  [/tapas|hawker|food|cuisine|street\s?food|culinary|dining/, "🍜"],
  [/architecture|skyline|gardens?/, "🏛️"], [/reef|snorkel|manta|coral|marine|lagoon|\bray/, "🐠"],
  [/turtle/, "🐢"], [/penguin/, "🐧"], [/bird|flamingo/, "🦤"], [/outback|savanna/, "🐪"],
  [/resort/, "🏝️"], [/cathedral|basilica/, "⛪"], [/canal/, "🛶"], [/lighthouse/, "🗼"],
  [/petra|nabataean|pyramid|ruins|ancient|archaeolog/, "🏺"], [/dead sea|salt flat|salar|uyuni/, "🧂"],
  [/crater|caldera/, "🌋"], [/canyon|gorge/, "🏜️"], [/baobab/, "🌳"], [/gorilla|chimp|lemur|monkey/, "🐒"],
  [/moai|easter island|statue/, "🗿"], [/gobi|kalahari|atacama|sahara|desert|dune/, "🏜️"],
  [/whale shark|diving|scuba|snorkel/, "🤿"], [/festival|naadam|carnival/, "🎉"],
  [/geothermal|hot spring|onsen|thermal|spa/, "♨️"], [/zip-?lin|bungee|adventure sport/, "🪂"],
  [/fjord/, "🏔️"], [/wine|vineyard|port wine/, "🍷"],
  [/div(e|ing)|snorkel|scuba/, "🤿"], [/surf/, "🏄"], [/ski|snowboard|\bsnow\b/, "🎿"],
  [/balloon/, "🎈"], [/shrine|pagoda/, "⛩️"], [/temple/, "🛕"], [/mosque/, "🕌"],
  [/church|cathedral|basilica|monaster/, "⛪"], [/ruins|ancient|archaeolog/, "🏺"],
  [/castle|palace|kremlin|\bfort\b|citadel/, "🏰"], [/safari|wildlife|gorilla|big five|game drive/, "🦁"],
  [/hik|trek|trail/, "🥾"], [/volcano/, "🌋"], [/mountain|peak|everest|kilimanjaro|alps|valley/, "⛰️"],
  [/desert|dune|sahara/, "🏜️"], [/waterfall|falls/, "💦"], [/lake/, "🏞️"],
  [/cruise|boat|sail|kayak|raft|river/, "⛵"], [/rainforest|jungle|forest/, "🌴"],
  [/wine|vineyard/, "🍷"], [/coffee|\btea\b/, "☕"],
  [/food|cuisine|cooking|culinary|dining|street\s?food/, "🍜"],
  [/market|bazaar|souk/, "🛍️"], [/museum|galler|\bart\b/, "🖼️"],
  [/festival|carnival|songkran|christmas/, "🎉"], [/nightlife|\bbar\b|\bclub\b|party/, "🍸"],
  [/spa|onsen|hot spring|thermal|wellness/, "♨️"], [/beach|coast|island/, "🏖️"],
  [/village/, "🏘️"], [/cit(y|ies)|town|skyline|metropolis/, "🏙️"], [/square|plaza|registan/, "🏛️"],
  [/steppe|nomad/, "🐪"], [/space|cosmodrome|baikonur/, "🚀"], [/histor|heritage/, "🏛️"],
  [/road trip|\broad\b/, "🚗"], [/bike|cycl/, "🚲"],
];
function activityEmoji(text) {
  const t = String(text || "").toLowerCase();
  for (const [re, em] of ACT_EMOJI) if (re.test(t)) return em;
  return "📍";
}

// Viator affiliate (tours & activities): country-level search deep-link tracked
// with our partner ID (8% commission, 30-day cookie). The search URL works for
// every country without needing Viator's per-destination ID taxonomy. FTC
// disclosure lives in the footer.
const VIATOR_PID = "P00308640", VIATOR_MCID = "42383";
function viatorURL(q) {
  return "https://www.viator.com/searchResults/all?text=" + encodeURIComponent(q) +
         "&pid=" + VIATOR_PID + "&mcid=" + VIATOR_MCID + "&medium=link";
}

function renderActivity(iso) {
  const a = activities[iso];
  const name = countryName(iso), nameT = countryNameInText(iso);   // nameT: "in the Bahamas"
  if (!a) { $("actDetail").innerHTML = `<div class="besthead"><h2>Things to do in ${esc(nameT)}</h2></div><p class="hint">No curated activity profile yet.</p>`; return; }
  // The travel month the rest of the page plans for (?vmn=, a month-bar
  // click), not the calendar month: stays and the AI prompt already followed
  // it, and this list was the one block still saying "now".
  const m = parseInt(($("valueMonth") || {}).value, 10) || curMonth();
  const tags = a.profile.map((p) =>
    `<span class="chip2">${PROFILE_EMOJI[p] ? PROFILE_EMOJI[p] + " " : ""}${esc(p)}</span>`).join("");
  // Each activity is either a plain label or { t: label, d: one-line insight }.
  const acts = a.activities.map((x) => {
    const label = actLabel(x);
    const desc = (typeof x === "object" && x.d) ? x.d : "";
    // Photo subject via activitySubject() — the hero carousel de-dupes against
    // the same derivation, so each image appears exactly once on the page.
    // Thumb loads async; rows without a clean photo just stay text-only.
    const subj = activitySubject(x);
    return `<li><span class="actemoji">${activityEmoji(label)}</span><span class="actmain">`
      + `<span class="actlabel">${esc(label)}</span>`
      + (desc ? `<span class="actdesc">${esc(desc)}</span>` : "")
      + `</span><span class="actthumbslot" data-subj="${esc(subj)}"></span></li>`;
  }).join("");
  const seas = (a.seasonal || []).map((s) => {
    const on = s.months.includes(m);
    // "not in <month>", never "off season": that reads as the tourist low
    // season, which this list (what nature and the calendar are doing) does
    // not measure and must not claim.
    return `<div class="seasrow">
      <span class="what"><span class="actemoji">${activityEmoji(s.what)}</span>${esc(s.what)}</span>
      <span class="months">${s.months.map((x) => MON_ABBR[x - 1]).join(", ")}</span>
      <span class="${on ? "inseason" : "offseason"}">${on ? "in season" : "not in " + MON_ABBR[m - 1]}</span>
      ${s.d ? `<span class="seasdesc">${esc(s.d)}</span>` : ""}
    </div>`;
  }).join("");
  const vis = isVisited(iso) ? '<span class="visited-tag">✓ visited</span>' : "";
  // The one-line summary is BACK (it was dropped as restating the bullets):
  // the SSR body and the meta description are built from it, and hydration
  // deleting it meant the rendered DOM Google indexes no longer contained the
  // sentence the snippet promises. One muted line is the honest price.
  const summary = (a.summary || "").trim();
  // The tours button waits for the advisory level like the stays do: none
  // under "Level 4 — do not travel" (guideAdvLevel), hidden until it is known.
  const lv = guideAdvLevel(iso);
  const tours = lv === 4 ? "" : `<div class="guidetours"${lv == null ? " hidden" : ""}>
    <a class="viatorbtn" href="${viatorURL(name)}" target="_blank" rel="sponsored nofollow noopener"
       title="Browse bookable tours & experiences in ${esc(nameT)} on Viator">🎟️ Book tours &amp; activities in ${esc(nameT)} <span class="muted">on Viator</span> <span class="ext">↗</span></a>
    <p class="affnote">Affiliate link — we may earn a commission, at no extra cost to you.</p></div>`;
  // h3 under the h2 (an h4 skipped a level); 1em keeps the h4's size.
  const todo = `<h3 style="font-size:1em;margin:.6em 0 .2em">🎒 Top things to do</h3>
    <ul class="actlist">${acts}</ul>${tours}`;
  // Things to do beside what's in season on a desktop (.actgrid, styles.css);
  // the season rows were each a card-wide line with the months a thousand
  // pixels from their label. Phones stack them as before.
  const seasHead = m === curMonth() ? "🗓️ What's in season now" : `🗓️ What's in season in ${MONTHS[m - 1]}`;
  // No "· Asia" on this heading: the weather heading just above already says it.
  $("actDetail").innerHTML = `
    <div class="besthead"><h2>Things to do in ${esc(nameT)} ${vis}</h2></div>
    ${summary ? `<p class="actsummary muted">${esc(summary)}</p>` : ""}
    <div class="chips">${tags}</div>
    ${seas ? `<div class="actgrid"><div>${todo}</div><div><h3 style="font-size:1em;margin:.6em 0 .2em">${seasHead}</h3>${seas}</div></div>` : todo}`;
  if (lv == null) {
    const settle = () => {
      const t = $("actDetail").querySelector(".guidetours");
      if (!t || ccGuideIso !== iso) return;
      if (guideAdvLevel(iso) === 4) t.remove(); else t.hidden = false;
    };
    ensureAdvisories().then(settle, settle);
  }
  return loadActivityThumbs(iso);   // settles once every row's photo is in or known missing
}

// ---- per-activity photo thumbnails ------------------------------------------
// Each "top things to do" row gets a small photo of its place (same Wikipedia
// pageimages source as the hero carousel), clickable to a full-screen view —
// visualize on-page instead of clicking out. Rows whose subject doesn't
// resolve to a clean photo silently stay text-only.
const _actPhotoCache = {};
async function actPhoto(subject, country) {
  const key = subject + "|" + country;
  if (!(key in _actPhotoCache)) {
    // Bare place names often land on disambiguation pages ("Ella", "Yala") —
    // no photo there, so retry with the country attached, in both Wikipedia
    // title styles: "Ella, Sri Lanka" (comma) and "Golden Circle (Iceland)"
    // (parenthetical).
    // Lower quality bar than the hero: these render as 84px thumbs.
    let p = await wikiIconic(subject, 700, 500).catch(() => null);
    if (!p && country) p = await wikiIconic(subject + ", " + country, 700, 500).catch(() => null);
    if (!p && country) p = await wikiIconic(subject + " (" + country + ")", 700, 500).catch(() => null);
    _actPhotoCache[key] = p;
  }
  return _actPhotoCache[key];
}
function loadActivityThumbs(iso) {
  const country = countryName(iso);
  const used = new Set();   // two rows resolving to the same image: first one wins
  const shown = [];         // [img, photo] — credited in one batch once all land
  const rows = Promise.all([...document.querySelectorAll("#actDetail .actthumbslot[data-subj]")].map(async (slot) => {
    const p = await actPhoto(slot.dataset.subj, country);
    if (!p || ccGuideIso !== iso || slot.childElementCount) return;
    const k = fileKey(p.full);
    if (used.has(k)) return;
    used.add(k);
    // Derive a lightweight thumb from the API's 1600px URL (standard MediaWiki
    // size-in-path); fall back to the big one if that variant doesn't exist.
    const small = p.thumb.replace(/\/(\d+)px-/, "/320px-");
    const img = document.createElement("img");
    // An interactive control, so it is neither alt="" (invisible to SRs) nor
    // mouse-only: named, focusable, Enter/Space opens the same viewer.
    img.className = "actthumb"; img.loading = "lazy";
    img.alt = "Photo — open viewer";
    img.title = "view photo";
    img.tabIndex = 0; img.setAttribute("role", "button");
    img.onerror = () => { img.onerror = null; img.src = p.thumb; };
    img.src = small;
    img.addEventListener("click", () => openLightboxSingle(p));
    img.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightboxSingle(p); }
    });
    slot.appendChild(img);
    shown.push([img, p]);
  }));
  rows.then(() => loadPhotoCredits(shown.map((x) => x[1]))).then(() => {
    // Too small for a caption: the credit rides the tooltip (and the viewer).
    for (const [img, p] of shown) {
      const c = _photoCredit[p.file];
      if (c && (c.artist || c.lic)) img.title = "view photo · 📷 " + [c.artist, c.lic].filter(Boolean).join(" · ");
    }
  }).catch(() => {});
  return rows;
}

// ===========================================================================
//  Your travel map: visited (been) + wishlist (want to go) — both in localStorage
// ===========================================================================
let visited = null, wishlist = null;
let visitMode = "visited";   // which list the map/dropdown edits
// True while a shared ?v= map is on screen: `visited` then holds the SHARER's
// countries, in memory only. Storage and the account keep the viewer's own list
// until they edit — which adopts the shared map, as the on-screen warning says.
let sharedVisitedView = false;
function loadVisited() {
  if (visited) return visited;
  try { visited = new Set(JSON.parse(localStorage.getItem("fx_visited") || "[]")); }
  catch (e) { visited = new Set(); }
  return visited;
}
function loadWishlist() {
  if (wishlist) return wishlist;
  try { wishlist = new Set(JSON.parse(localStorage.getItem("fx_wishlist") || "[]")); }
  catch (e) { wishlist = new Set(); }
  return wishlist;
}
// The viewer's own been-list, whatever map is on screen.
function ownVisited() {
  if (!sharedVisitedView) return loadVisited();
  try { return new Set(JSON.parse(localStorage.getItem("fx_visited") || "[]")); }
  catch (e) { return new Set(); }
}
// localStorage stays the source of truth for everyone (accounts are optional);
// when signed in, every change also pushes to the cloud copy.
function saveVisited() {
  sharedVisitedView = false;   // an edit adopts the shared map (see above)
  localStorage.setItem("fx_visited", JSON.stringify([...visited]));
  acctQueueSync();
}
function saveWishlist() {
  localStorage.setItem("fx_wishlist", JSON.stringify([...wishlist]));
  acctQueueSync();
}
function isVisited(iso) { return loadVisited().has(iso); }
// Toggle a country in the active list only. Been and Want-to-go can overlap —
// "I've been to Japan AND want to go back" is a real state (traveler
// feedback: exclusivity silently stripped been-marks when pasting a bucket
// list). Overlap paints green with a blue ring.
function toggleMark(iso) {
  loadVisited(); loadWishlist();
  const on = visitMode === "visited" ? visited : wishlist;
  if (on.has(iso)) on.delete(iso); else on.add(iso);
  // Save only the list that changed: saving both made a want-to-go tap adopt
  // a shared been-map the viewer never touched.
  if (on === visited) saveVisited(); else saveWishlist();
}

let _displayNames = null;
// The map data carries Natural Earth's names, which abbreviate ("Dominican
// Rep.", "S. Sudan") and give one country its long official name ("United
// States of America" beside "United Kingdom" and "Russia"). These match
// public/country-names.json, which the guide pages and the From picker use,
// so a country is called the same thing everywhere on the site.
const NAME_FIX = { US: "United States", BA: "Bosnia and Herzegovina", CD: "DR Congo",
  CG: "Republic of the Congo", CF: "Central African Republic", DO: "Dominican Republic",
  GQ: "Equatorial Guinea", SS: "South Sudan", SB: "Solomon Islands",
  EH: "Western Sahara", TF: "French Southern Territories" };
function countryName(iso) {
  if (EXTRA_PLACES[iso]) return EXTRA_PLACES[iso];   // flag-emoji places
  if (NAME_FIX[iso]) return NAME_FIX[iso];
  const n = (climate && climate[iso] && climate[iso].name) ||
            (ppp && ppp[iso] && ppp[iso].name);
  if (n) return n;
  // Micro-states and small islands (Andorra, Singapore, Bahrain…) aren't in the
  // map-derived data files; the browser's own region names cover them.
  try {
    _displayNames = _displayNames || new Intl.DisplayNames(["en"], { type: "region" });
    return _displayNames.of(iso) || iso;
  } catch (e) {
    return iso;
  }
}
// The name inside a sentence or heading: "Things to do in the Bahamas". The
// same set as render_guide.THE (scripts/test_guide_meta.py holds them equal);
// labels and the h1 keep the bare name.
const NAME_THE = new Set(["BS", "PH", "NL", "AE", "GB", "US", "DO", "GM", "SB", "FO", "FK", "CF", "CG", "IM", "TF"]);
function countryNameInText(iso) { return (NAME_THE.has(iso) ? "the " : "") + countryName(iso); }

// ---- paste-a-list importer ---------------------------------------------------
// Travelers keep their history in Google Docs / Keep / random notes, mixing
// countries with cities and parks ("Kyoto", "Machu Picchu"). Parsed entirely
// client-side: canonical names, aliases, ISO codes, and a famous-places map.
// Unrecognized lines are reported, never guessed.
const COUNTRY_ALIASES = {
  "usa": "US", "u s": "US", "u s a": "US", "america": "US", "united states": "US",
  "united states of america": "US", "uk": "GB", "great britain": "GB", "britain": "GB",
  "england": "GB-ENG", "scotland": "GB-SCT", "wales": "GB-WLS", "northern ireland": "GB",
  "st maarten": "SX", "saint maarten": "SX", "virgin islands": "VI",
  "us virgin islands": "VI", "the antarctic": "AQ", "antigua": "AG",
  "st kitts": "KN", "saint kitts": "KN", "st vincent": "VC",
  "saint vincent": "VC", "bvi": "VG", "tahiti": "PF", "bora bora": "PF",
  "saudi": "SA", "falklands": "FK",
  // regions travelers list as destinations of their own
  "tibet": "CN", "lhasa": "CN", "ladakh": "IN", "socotra": "YE",
  "kurdistan": "IQ", "iraqi kurdistan": "IQ", "mulu": "MY",
  "peninsular malaysia": "MY", "bornean malaysia": "MY", "zanzibar": "TZ",
  "uae": "AE", "emirates": "AE", "south korea": "KR", "korea": "KR", "north korea": "KP",
  "czechia": "CZ", "czech republic": "CZ", "ivory coast": "CI", "cote d'ivoire": "CI",
  "myanmar": "MM", "burma": "MM", "holland": "NL", "bosnia": "BA", "bosnia and herz": "BA",
  "congo": "CG",   // its display name is now "Republic of the Congo"; a bare "Congo" still imports
  "macedonia": "MK", "turkiye": "TR", "viet nam": "VN", "drc": "CD", "swaziland": "SZ",
  "cape verde": "CV", "east timor": "TL", "timor leste": "TL", "vatican": "VA",
  "vatican city": "VA", "the gambia": "GM", "the bahamas": "BS", "st lucia": "LC",
  "saint lucia": "LC", "kyrgyzstan": "KG", "faroe islands": "FO", "palestine": "PS",
};
const PLACE_TO_ISO = {
  // Europe
  "paris": "FR", "nice": "FR", "lyon": "FR", "london": "GB", "edinburgh": "GB",
  "rome": "IT", "venice": "IT", "florence": "IT", "milan": "IT", "sicily": "IT",
  "amalfi": "IT", "barcelona": "ES", "madrid": "ES", "seville": "ES", "ibiza": "ES",
  "mallorca": "ES", "lisbon": "PT", "porto": "PT", "madeira": "PT", "azores": "PT",
  "athens": "GR", "santorini": "GR", "mykonos": "GR", "crete": "GR",
  "amsterdam": "NL", "brussels": "BE", "bruges": "BE", "berlin": "DE", "munich": "DE",
  "vienna": "AT", "salzburg": "AT", "prague": "CZ", "budapest": "HU", "krakow": "PL",
  "warsaw": "PL", "zurich": "CH", "geneva": "CH", "interlaken": "CH", "zermatt": "CH",
  "oslo": "NO", "bergen": "NO", "lofoten": "NO", "stockholm": "SE", "copenhagen": "DK",
  "helsinki": "FI", "reykjavik": "IS", "dublin": "IE", "moscow": "RU", "dubrovnik": "HR",
  "split": "HR", "kotor": "ME", "istanbul": "TR", "cappadocia": "TR",
  // Asia
  "tokyo": "JP", "kyoto": "JP", "osaka": "JP", "okinawa": "JP", "seoul": "KR",
  "busan": "KR", "beijing": "CN", "shanghai": "CN", "taipei": "TW", "hong kong": "HK",
  "macau": "MO", "hanoi": "VN", "saigon": "VN", "ho chi minh": "VN", "ha long": "VN",
  "bangkok": "TH", "phuket": "TH", "chiang mai": "TH", "krabi": "TH", "bali": "ID",
  "jakarta": "ID", "kuala lumpur": "MY", "penang": "MY", "manila": "PH", "palawan": "PH",
  "siem reap": "KH", "angkor": "KH", "angkor wat": "KH", "phnom penh": "KH",
  "luang prabang": "LA", "yangon": "MM", "bagan": "MM", "kathmandu": "NP",
  "everest": "NP", "delhi": "IN", "mumbai": "IN", "jaipur": "IN", "agra": "IN",
  "taj mahal": "IN", "goa": "IN", "kerala": "IN", "colombo": "LK", "male": "MV",
  "maldives islands": "MV", "dubai": "AE", "abu dhabi": "AE", "doha": "QA",
  "petra": "JO", "amman": "JO", "jerusalem": "IL", "tel aviv": "IL", "tbilisi": "GE",
  "yerevan": "AM", "baku": "AZ", "samarkand": "UZ", "tashkent": "UZ",
  // Africa & Middle East
  "cairo": "EG", "luxor": "EG", "giza": "EG", "marrakech": "MA", "marrakesh": "MA",
  "casablanca": "MA", "fez": "MA", "chefchaouen": "MA", "cape town": "ZA",
  "johannesburg": "ZA", "kruger": "ZA", "nairobi": "KE", "masai mara": "KE",
  "zanzibar": "TZ", "serengeti": "TZ", "kilimanjaro": "TZ", "victoria falls": "ZM",
  "okavango": "BW", "addis ababa": "ET", "tunis": "TN", "accra": "GH", "lagos": "NG",
  // Americas
  "new york": "US", "nyc": "US", "los angeles": "US", "san francisco": "US",
  "las vegas": "US", "miami": "US", "chicago": "US", "hawaii": "US", "maui": "US",
  "alaska": "US", "yellowstone": "US", "yosemite": "US", "grand canyon": "US",
  "zion": "US", "toronto": "CA", "vancouver": "CA", "montreal": "CA", "banff": "CA",
  "quebec": "CA", "mexico city": "MX", "cancun": "MX", "tulum": "MX", "oaxaca": "MX",
  "cabo": "MX", "havana": "CU", "san juan": "PR", "panama city": "PA", "antigua guatemala": "GT",
  "lima": "PE", "cusco": "PE", "machu picchu": "PE", "bogota": "CO", "cartagena": "CO",
  "medellin": "CO", "quito": "EC", "galapagos": "EC", "la paz": "BO", "uyuni": "BO",
  "rio": "BR", "rio de janeiro": "BR", "sao paulo": "BR", "iguazu": "BR",
  "buenos aires": "AR", "patagonia": "AR", "mendoza": "AR", "santiago": "CL",
  "atacama": "CL", "easter island": "CL", "montevideo": "UY",
  // Oceania
  "sydney": "AU", "melbourne": "AU", "great barrier reef": "AU", "uluru": "AU",
  "auckland": "NZ", "queenstown": "NZ", "fiji islands": "FJ", "bora bora": "PF",
  "tahiti": "PF",
};

function parsePlaceList(text) {
  const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z\s'&-]/g, " ").replace(/\s+/g, " ").trim();
  const nameToIso = {};
  for (const iso of allPlaces()) nameToIso[norm(countryName(iso))] = iso;
  Object.assign(nameToIso, COUNTRY_ALIASES, PLACE_TO_ISO);
  const isoSet = new Set(allPlaces().filter((p) => p.length === 2));
  // organizational headers in real bucket lists ("Asia:", "Middle East:") —
  // not matches, but not worth reporting as unrecognized either
  const HEADER_NOISE = new Set(["asia", "europe", "africa", "oceania", "americas",
    "america", "middle east", "north america", "south america", "central america",
    "caribbean", "pacific", "polar", "travel bucket list", "bucket list", "been",
    "want to go", "wishlist", "maybe"]);
  const found = new Set(), missed = [];
  for (const raw of text.split(/[\n,;:•·|\/]+/)) {
    const t = norm(raw);
    if (!t || t.length < 2) continue;
    const up = raw.trim().toUpperCase();
    if (up.length === 2 && isoSet.has(up)) { found.add(up); continue; }
    if (nameToIso[t]) { found.add(nameToIso[t]); continue; }
    // messy lines ("2019 — Japan (Kyoto!!)"): find the longest known name inside
    let hit = null;
    const padded = " " + t + " ";
    for (const name in nameToIso) {
      if (name.length >= 4 && padded.includes(" " + name + " ") &&
          (!hit || name.length > hit.length)) hit = name;
    }
    if (hit) found.add(nameToIso[hit]);
    else if (!HEADER_NOISE.has(t)) missed.push(raw.trim().slice(0, 30));
  }
  return { found: [...found], missed };
}

// Bulk add: seasoned travelers shouldn't have to add 40 countries one search
// at a time. Every country as a tap-to-toggle chip with a filter box; applies
// to whichever list (Been / Want to go) is active. Map re-renders on close.
function openBulkAdd() {
  if (document.querySelector(".bulkmodal")) return;
  loadVisited(); loadWishlist();
  const on = visitMode === "visited" ? visited : wishlist;
  const all = allPlaces()
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const m = document.createElement("div");
  m.className = "submodal bulkmodal";
  const label = visitMode === "visited" ? "✓ Been" : "★ Want to go";
  m.innerHTML = '<div class="submodal-card bulkcard"><button class="submodal-x" aria-label="Close">✕</button>'
    + `<span class="sublabel">Tap every country for your <b>${label}</b> list</span>`
    + '<input type="search" class="bulksearch" placeholder="Filter countries…">'
    + '<button type="button" class="bulkpaste-toggle">📋 Or paste your list from a doc / notes / spreadsheet</button>'
    + '<div class="bulkpaste" hidden>'
    + '<textarea class="bulkpastebox" rows="4" placeholder="Paste anything — one place per line or comma-separated. Cities and famous parks count (“Kyoto” → Japan, “Machu Picchu” → Peru)."></textarea>'
    + '<div class="bulkpaste-actions"><button type="button" class="bulkmatch">Match my list</button>'
    + '<span class="bulkmatch-out"></span></div></div>'
    + '<div class="bulkchips">' + all.map((c) =>
        `<button type="button" class="bulkchip${on.has(c.iso) ? " on" : ""}" aria-pressed="${on.has(c.iso)}" data-iso="${esc(c.iso)}">${flagEmoji(c.iso)} ${esc(c.name)}</button>`
      ).join("") + "</div>"
    + `<div class="bulkfoot"><span class="bulkcount">${on.size} selected</span>`
    + '<button type="button" class="bulkdone">Done</button></div></div>';
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add("show"));
  // close() drops the Escape listener itself, whichever way the modal closes
  // (X, Done, backdrop, Escape) — a stale one re-ran renderVisited on every
  // later Escape anywhere on the page.
  const close = () => {
    document.removeEventListener("keydown", onKey);
    m.classList.remove("show");
    setTimeout(() => m.remove(), 220);
    renderVisited();                        // one redraw for the whole batch
  };
  m.querySelector(".submodal-x").onclick = close;
  m.querySelector(".bulkdone").onclick = close;
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  m.querySelector(".bulkchips").addEventListener("click", (e) => {
    const chip = e.target.closest(".bulkchip");
    if (!chip) return;
    toggleMark(chip.dataset.iso);
    chip.classList.toggle("on", on.has(chip.dataset.iso));
    chip.setAttribute("aria-pressed", String(on.has(chip.dataset.iso)));
    m.querySelector(".bulkcount").textContent = on.size + " selected";
  });
  const search = m.querySelector(".bulksearch");
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    for (const chip of m.querySelectorAll(".bulkchip"))
      chip.hidden = !!q && !chip.textContent.toLowerCase().includes(q);
  });
  // paste-a-list: parse free text and switch every match ON (never off)
  const paste = m.querySelector(".bulkpaste");
  m.querySelector(".bulkpaste-toggle").onclick = () => {
    paste.hidden = !paste.hidden;
    if (!paste.hidden) paste.querySelector("textarea").focus();
  };
  m.querySelector(".bulkmatch").onclick = () => {
    const { found, missed } = parsePlaceList(paste.querySelector("textarea").value);
    for (const iso of found) {
      if (!on.has(iso)) toggleMark(iso);
      const chip = m.querySelector(`.bulkchip[data-iso="${iso}"]`);
      if (chip) { chip.classList.add("on"); chip.setAttribute("aria-pressed", "true"); }
    }
    m.querySelector(".bulkcount").textContent = on.size + " selected";
    m.querySelector(".bulkmatch-out").textContent = found.length
      ? `✓ Matched ${found.length} ${found.length === 1 ? "country" : "countries"}`
        + (missed.length ? ` · didn't recognize: ${missed.slice(0, 5).join(", ")}${missed.length > 5 ? "…" : ""}` : "")
      : (missed.length ? "Nothing recognized — try country or major-city names" : "Paste something first");
  };
  search.focus();
}

function buildVisited() {
  loadVisited(); loadWishlist();
  const pick = $("visitedPick");
  // dropdown of every markable place by name (countries + flag-emoji places)
  const all = allPlaces()
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  pick.innerHTML = '<option value="">+ add a country…</option>' +
    all.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("");
  enhanceSelect(pick);
  pick.onchange = () => { if (pick.value) { toggleMark(pick.value); pick.value = ""; if (pick._sync) pick._sync(); renderVisited(); } };
  if ($("visitedBulk")) $("visitedBulk").onclick = openBulkAdd;
  $("visitedClear").onclick = clearActiveList;
  for (const b of document.querySelectorAll("#visitedMode button")) {
    b.addEventListener("click", () => {
      visitMode = b.dataset.vm;
      for (const x of document.querySelectorAll("#visitedMode button")) {
        x.classList.toggle("active", x === b);
        x.setAttribute("aria-pressed", String(x === b));   // the state, not just the colour
      }
      renderVisited();
    });
  }
  // One delegated listener each on the (stable) containers — survives innerHTML
  // re-renders and avoids re-binding 176 path handlers every toggle.
  $("visitedMap").addEventListener("click", (e) => {
    const p = e.target.closest("path");
    const iso = p && p.getAttribute("data-iso");
    if (iso && iso !== "-99") { toggleMark(iso); renderVisited(); }
  });
  $("visitedChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".rm");
    if (chip) {   // remove from whichever list it's in
      loadVisited(); loadWishlist();
      const dv = visited.delete(chip.dataset.iso), dw = wishlist.delete(chip.dataset.iso);
      if (dv) saveVisited();
      if (dw) saveWishlist();
      renderVisited();
    }
  });
  renderVisited();
}

// "Clear all" sat one mis-tap from Share image and wiped the list — and, when
// signed in, the account copy — with no way back. Confirm with the count, then
// offer Undo; the account push waits out the undo window.
const CLEAR_UNDO_MS = 8000;
function clearActiveList() {
  const isV = visitMode === "visited";
  const set = isV ? loadVisited() : loadWishlist();
  const label = isV ? "been-to" : "want-to-go";
  const n = set.size;
  if (!n) { status("Your " + label + " list is already empty.", "ok"); return; }
  const ask = isV && sharedVisitedView
    ? `Clear this shared map of ${n} ${n === 1 ? "country" : "countries"}? It replaces your own saved ${label} list.`
    : `Clear all ${n} ${n === 1 ? "country" : "countries"} from your ${label} list?`;
  if (!window.confirm(ask)) return;
  const prev = [...set];
  // On a shared map `set` is the SHARER's list; the viewer's own saved list is
  // what the clear overwrites. Snapshot it, so Undo returns exactly to before
  // the click (own list intact, shared map on screen) instead of adopting the
  // sharer's countries as the viewer's own.
  const wasShared = isV && sharedVisitedView;
  const prevOwn = wasShared ? [...ownVisited()] : null;
  const save = () => (isV ? saveVisited() : saveWishlist());
  acctHoldSync(CLEAR_UNDO_MS);
  set.clear();
  save();
  renderVisited();
  status(`Cleared ${n} ${n === 1 ? "country" : "countries"} from your ${label} list.`, "ok");
  const undo = document.createElement("button");
  undo.type = "button"; undo.className = "linkbtn"; undo.textContent = "Undo";
  undo.onclick = () => {
    // The status() below replaces the toast, Undo included: a keyboard user
    // on it would drop to <body>. Clear all is where they came from.
    if (document.activeElement === undo) $("visitedClear").focus();
    if (wasShared) {
      set.clear(); prev.forEach((iso) => set.add(iso));
      sharedVisitedView = true;
      try { localStorage.setItem("fx_visited", JSON.stringify(prevOwn)); } catch (e) {}
      acctQueueSync();   // merges the restored own list: a no-op against the cloud
      renderVisited();
      status("Restored the shared map — your own " + label + " list is unchanged.", "ok");
      return;
    }
    prev.forEach((iso) => set.add(iso));
    save();
    renderVisited();
    status("Restored your " + label + " list.", "ok");
  };
  $("status").append(" ", undo);
  // The toast floats at the foot of the screen, ~30 Tabs from the button that
  // raised it, and it lives 8 seconds: a keyboard user could never reach Undo
  // in time. Put them on it; when the toast goes, give focus back to Clear all
  // rather than letting it drop to <body> with the hidden button.
  if (_kbdNav) undo.focus();
  clearTimeout(_statusTimer);   // the Undo stays exactly as long as the hold
  _statusTimer = setTimeout(() => {
    $("status").hidden = true;
    if (document.activeElement === undo) $("visitedClear").focus();
  }, CLEAR_UNDO_MS);
}

const VISITED_COLOR = "#0a7d28", WISH_COLOR = "#2b6cb0";
function renderVisited() {
  // Exporting an empty map would render a blank "0 countries" card — keep the
  // share buttons off until at least one country is marked.
  const canShare = visited.size > 0;
  const shareBtn = $("visitedImage");
  if (shareBtn) {
    shareBtn.disabled = !canShare;
    shareBtn.title = canShare ? "" : "Mark at least one country first ✓";
  }
  drawMap("visitedMap", (f) => {
    const iso = f.properties.iso, par = f.properties.sub;
    // UK home nations paint with their own mark OR the whole-UK mark
    const been = visited.has(iso) || (par && visited.has(par));
    const want = wishlist.has(iso) || (par && wishlist.has(par));
    if (been && want)
      return { fill: VISITED_COLOR, cls: "been both",
               title: f.properties.name + " — been ✓ and want to go again ★" };
    if (been) return { fill: VISITED_COLOR, cls: "been", title: f.properties.name + " — been ✓ (click to remove)" };
    if (want) return { fill: WISH_COLOR, cls: "want", title: f.properties.name + " — want to go ★ (click to remove)" };
    return { fill: "#e0e4e8",
      title: f.properties.name + " — click to mark " + (visitMode === "visited" ? "been" : "want to go") };
  }, "Your travel map");
  // an active continent filter (click a % chip) narrows the country chips too
  const inFilter = (iso) => !contFilter || continentOf(iso) === contFilter;
  // flag + name, like the bulk-add chips: this list is the one place each
  // country appears (the stats used to repeat every one as a bare flag).
  const chipsFor = (set, cls) => [...set].filter(inFilter)
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name))
    // Real buttons, so Tab reaches them and a screen reader hears what one does.
    .map((c) => `<button type="button" class="chip2 rm ${cls}" data-iso="${esc(c.iso)}" aria-label="Remove ${esc(c.name)}" title="remove">${flagEmoji(c.iso)} ${esc(c.name)} ✕</button>`).join("");
  renderVisitedStats();
  const sections = [];
  const beenChips = chipsFor(visited, "v"), wantChips = chipsFor(wishlist, "w");
  if (beenChips) sections.push('<div class="chiprow"><span class="chiplabel">✓ Been</span>' + beenChips + '</div>');
  if (wantChips) sections.push('<div class="chiprow"><span class="chiplabel">★ Want to go</span>' + wantChips + '</div>');
  // With nothing marked at all the stats column carries the hint (it sits
  // beside the map); this only speaks for a continent filter that finds nothing.
  $("visitedChips").innerHTML = sections.join("") ||
    (contFilter ? '<span class="hint">Nothing marked on this continent yet.</span>' : "");
  syncURL();
}

// On-page version of the shareable card's stats: flags, an award tag (with a
// hover tooltip explaining how it's earned), and the continents / % of world text.
// Continent filter (traveler feedback): clicking a % chip narrows the flag
// strip and the country chip lists to that continent, and zooms the map to
// it — "all my places, but also a South America view". Click again to clear.
let contFilter = null;
// lon1, lon2, lat1, lat2 per continent — traced to the real extent of the
// countries we actually file under each one (Russia and Greenland are EUR
// here, so Asia stops at ~146E/55N and must NOT reach Siberia: empty span
// gets aspect-padded into a wide view showing the neighbours). Hand-tuned
// rather than computed, because Europe and Oceania straddle the dateline and
// a naive bounding box spans the globe.
const CONT_VIEW = {
  NA: [-170, -52, 7, 83], SA: [-82, -34, -56, 13], EU: [-25, 45, 34, 72],
  AS: [30, 150, -11, 56], AF: [-26, 60, -36, 38], OC: [110, 180, -50, 16],
};
function continentZoomBox(c) {
  const [lo1, lo2, la1, la2] = CONT_VIEW[c];
  const W = 1000, H = 386, latTop = 83, latBot = -56;
  const x1 = ((lo1 + 180) / 360) * W, x2 = ((lo2 + 180) / 360) * W;
  const y1 = ((latTop - la2) / (latTop - latBot)) * H, y2 = ((latTop - la1) / (latTop - latBot)) * H;
  const w = Math.max(x2 - x1, (y2 - y1) * W / H);      // keep aspect, contain box
  return { x: (x1 + x2) / 2 - w / 2, y: (y1 + y2) / 2 - (w * H / W) / 2, w, h: w * H / W };
}
function setContFilter(c) {
  contFilter = contFilter === c ? null : c;
  // Re-render the filtered content FIRST (at the current zoom, so the map
  // doesn't jump), then glide the camera to the continent — or back out.
  renderVisited();
  const map = $("visitedMap");
  if (map && map._zoomTo)
    map._zoomTo(contFilter ? continentZoomBox(contFilter) : { x: 0, y: 0, w: 1000, h: 386 }, true);
}

// "% of the world" is UN members out of UN_MEMBERS, the same basis as the
// continent chips and the badge ladder beside it. Out of every place on the
// map (226, territories included) the line read "~12%" next to chips that
// said 15%, and someone with all 193 would have read "~85%". The headline
// count still includes territories: marking Hong Kong or Puerto Rico is real.
function worldPct(set) {
  const unN = [...set].filter((i) => UN_MEMBERS.has(i)).length;
  return Math.max(1, Math.round((unN / UN_MEMBERS.size) * 100));
}
const WORLD_PCT_TIP = "Share of the 193 UN member states plus Vatican City and Palestine. "
  + "Territories and Antarctica count in your total but not in this %.";

function renderVisitedStats() {
  const host = $("visitedStats");
  if (!host) return;
  const n = visited.size, m = wishlist.size;
  // The empty state lives here, beside the map, so the layout is the same
  // before and after the first mark (the map doesn't jump under the cursor).
  // The first rung of the badge ladder sits with it: the column then holds a
  // goal rather than one line of grey text beside an empty map.
  if (!n && !m) {
    const [t, label] = MILESTONE_TIERS[0];
    host.innerHTML = '<div class="vstats-line"><span class="hint">Nothing marked yet</span>'
      + `<span class="awardtag locked" data-tip="${esc(`Visit ${t} countries to earn ${label}`)}" title="">🔒 ${t} to ${esc(label)}</span></div>`;
    return;
  }
  const cont = visitedContinents();
  const bits = [];
  if (n) bits.push(`<b>${n}</b> ${n === 1 ? "country" : "countries"}`);
  if (cont) bits.push(`🌍 ${cont} continent${cont === 1 ? "" : "s"}`);
  if (n) bits.push(`<span data-tip="${WORLD_PCT_TIP}" title="">~${worldPct(visited)}% of the world ⓘ</span>`);
  if (m) bits.push(`${m} want to go`);
  const mi = milestoneInfo(n);
  let award = "";
  // All seven continents (Antarctica included) outranks any count tier.
  if (cont === 7)
    award += '<span class="awardtag seven" data-tip="Every continent on Earth — Antarctica included. The rarest badge there is." title="">🌐 All 7 Continents</span>';
  if (mi.earned) {
    const q = `Earned by visiting ${mi.earned.t}+ countries`
      + (mi.next ? ` — ${mi.next.t - n} more for ${mi.next.label}` : " — top tier!");
    award += `<span class="awardtag" data-tip="${esc(q)}" title="">${esc(mi.earned.label)}</span>`;
  } else if (mi.next && n) {
    award += `<span class="awardtag locked" data-tip="${esc(`Visit ${mi.next.t} countries to earn ${mi.next.label} — ${mi.next.t - n} to go`)}" title="">🔒 ${mi.next.t - n} to ${esc(mi.next.label)}</span>`;
  }
  // continent progress chips — click to filter to that continent, gold at 100%
  const prog = continentProgress().filter((p) => p.n > 0 && p.total > 0);
  const contRow = prog.length
    ? '<div class="contbar">' + prog.map((p) =>
        `<button type="button" class="contchip${p.pct === 100 ? " done" : ""}${p.c === contFilter ? " active" : ""}" data-cont="${p.c}" aria-pressed="${p.c === contFilter}"`
        + ` data-tip="${p.n} of ${p.total} countries in ${esc(p.name)} (UN members) — ${p.c === contFilter ? "tap to show everything again" : "tap to filter to this continent"}" title="">`
        + `${p.pct === 100 ? "🏅 " : ""}${esc(p.name)} ${p.pct}%</button>`).join("")
      + (contFilter ? `<button type="button" class="contchip clear" data-cont="${contFilter}" data-tip="show all continents" title="">✕ clear</button>` : "")
      + "</div>"
    : "";
  // One <span> per line of text: .vstats-line is a flex row (for the award
  // pill), and a bare <b> would become its own flex item — the gap property
  // then splits the number from its own sentence.
  // Save prompt lives HERE, not only in the header. The header button reads
  // "Save map" on all four tabs, three of which contain no map — and it asks
  // for the save before the reader has anything worth saving. Motivation peaks
  // at exactly this point: they have just marked N countries and can see what
  // they'd lose. Only shown once there is something to lose, and never to
  // someone already signed in. The why is a ⓘ, and it counts been and want
  // to go apart: added together, a country on both lists was counted twice
  // and the note disagreed with the stats line right above it.
  const saveCta = (ACCT_ON && !acctSignedIn() && (n || m))
    ? `<div class="vsave"><button type="button" id="visitedSave">👤 Save this map</button>`
      + `<span class="muted" data-tip="${esc(`Saved in this browser only. Sign in to keep your `
        + (n ? `${n} been` : "") + (n && m ? " + " : "") + (m ? `${m} want to go` : "")
        + ` on every device.`)}" title="">ⓘ</span></div>`
    : "";
  host.innerHTML = `<div class="vstats-line"><span>${bits.join(" · ")}</span>${award}</div>`
    + contRow + saveCta;
  const sb = $("visitedSave");
  if (sb) sb.onclick = () => openSignIn();
  // idempotent across re-renders (property assignment, not addEventListener)
  host.onclick = (e) => {
    const chip = e.target.closest(".contchip");
    if (chip) setContFilter(chip.dataset.cont);
  };
}

// ===========================================================================
//  Tab switching (lazy-load each tab's data on first open)
// ===========================================================================
const loaded = {};
// First builds in flight, per tab. A second activateTab for a tab still
// awaiting its data used to run the builder twice, doubling every
// addEventListener — two Wander List map listeners toggled each click twice,
// so marking a country did nothing. Later calls now await the same build.
const _building = {};
function buildTabOnce(name, build) {
  if (!_building[name]) {
    _building[name] = build().catch((e) => { delete _building[name]; throw e; });
  }
  return _building[name];
}
// /guide/<slug> HTML carries the other tabs' 16 h2/h3 as <div data-h="2|3">
// (server.py _guide_template) so they don't tell a crawler the page is about
// dollar strength and fares. Restored, attributes and children intact, before
// a reader can see any of them: the same CSS then applies, so nothing moves.
// A no-op on every other page.
function promoteShellHeadings() {
  for (const el of document.querySelectorAll("[data-h]")) {
    const h = document.createElement("h" + el.dataset.h);
    for (const a of el.attributes) if (a.name !== "data-h") h.setAttribute(a.name, a.value);
    h.append(...el.childNodes);
    el.replaceWith(h);
  }
  // The header's headline too: a guide page serves it as <p class="sitetitle">
  // (the country's h1 is that page's one), so Top Picks reached in-app from a
  // guide had no h1 at all. h1 and .sitetitle share one rule (styles.css), so
  // the swap moves nothing; back on a guide the CSS hides it again.
  const st = document.querySelector("header p.sitetitle");
  if (st) {
    const h1 = document.createElement("h1");
    for (const a of st.attributes) h1.setAttribute(a.name, a.value);
    h1.append(...st.childNodes);
    st.replaceWith(h1);
  }
}
async function activateTab(name, push) {
  // A /guide/ page serves the other tabs' headings as <div data-h> (server.py
  // _guide_template); they become h2/h3 again before their tab is revealed.
  if (name !== "guide") promoteShellHeadings();
  clearTransientStatus();   // a note about the old tab shouldn't outlive it
  closeMapFullscreen();     // "Country guide →" from a full-screen map
  document.documentElement.setAttribute("data-tab", name);  // keep pre-paint CSS in sync
  if (name === "trip") renderTripBar();
  // Meta follows the tab in BOTH directions. Leaving the guide restores the
  // homepage title/canonical; returning to an already-rendered guide has to put
  // the country's back, because nothing re-renders it — which otherwise left the
  // h1 naming a country under the homepage title.
  if (name !== "guide") {
    setDocMeta(_DEFAULT_META, _DEFAULT_URL);
  } else {
    const iso = _guideTarget || ($("bestCountry") || {}).value;
    if (iso) setGuideMeta(iso);
  }
  for (const b of document.querySelectorAll("#tabs button")) {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }
  for (const s of document.querySelectorAll(".tab"))
    s.hidden = s.id !== "tab-" + name;
  // Push the new history entry BEFORE anything renders. Every render ends in
  // a replacing syncURL(); run first, they overwrote the entry of the page
  // being left, so Back skipped it (or opened a guide nobody chose).
  if (push) syncURL(true);

  // Refresh visited marks when returning to the recommendation tab.
  if (name === "value" && loaded.value) renderValue();

  try {
    if (name === "value" && !loaded.value) {
      await buildTabOnce("value", async () => {
        await Promise.all([ensureWorld(), ensurePPP(), ensureClimate(), ensureAdvisories(),
                           ensureActivities().catch(() => {}),     // hazards + photos
                           ensureVisa().catch(() => {})]);         // visa column
        buildValueTab(); loaded.value = true;
      });
    } else if (name === "guide" && !loaded.guide) {
      await buildTabOnce("guide", async () => {
        // Prices are one line of a guide: without ppp.json it still renders
        // (its FX line says the inflation figures didn't load).
        await Promise.all([ensurePPP().catch(() => {}), ensureClimate(), ensureActivities(),
                           ensureVisa().catch(() => {})]);
        buildBestPickers(_guideTarget); loaded.guide = true;
      });
    } else if (name === "visited" && !loaded.visited) {
      await buildTabOnce("visited", async () => {
        // The Wander List never reads PPP; a ppp.json blip must not fail the tab.
        await Promise.all([ensureWorld(), ensurePPP().catch(() => {}), ensureClimate()]);
        buildVisited(); loaded.visited = true;
      });
    } else if (name === "trip" && !loaded.trip) {
      await buildTabOnce("trip", async () => {
        // What the rows read, without building Top Picks: the month's
        // weather pill (climate, its tip's hazards from activities), the
        // Level 3-4 marks and no booking links at Level 4 (advisories), and
        // each row's Flights link (the origin's fares: not awaited — a cold
        // origin can take seconds; loadValueFlights redraws the list when
        // they land). A Top Picks session has all four (its own fares
        // request may still be out: a second would only be discarded).
        await Promise.all([ensureClimate(), ensureAdvisories().catch(() => {}),
                           ensureActivities().catch(() => {})]);
        if (!flightsData && !loaded.value) loadValueFlights(true);
        loaded.trip = true;
        renderTripBar();
      });
    } else if (name === "data") {
      setDataMode(dataMode);   // initialize the active sub-view (incl. currency)
    }
  } catch (e) {
    status("Could not load " + name + ": " + e.message, "err");
  }
  syncURL();
}
for (const b of document.querySelectorAll("#tabs button"))
  b.addEventListener("click", () => activateTab(b.dataset.tab, true));
// The whole masthead (logo + title + tagline) -> home (Top Picks) as an SPA
// switch; the href="/" fallback still works for open-in-new-tab / no-JS.
document.querySelector(".homelink").addEventListener("click", (e) => {
  // let cmd/ctrl/shift-clicks open a real new tab via the href
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  activateTab("value", true);
  window.scrollTo(0, 0);
});

// #valueMonth is the one travel month every tab reads (guide bars, stay dates,
// AI prompts, share links). Filled at boot, not only when Top Picks builds: a
// /guide/<slug> landing never builds Top Picks, and a select with no options
// silently ignored every month picked on the guide. Keeps a chosen value.
function ensureMonthOptions() {
  const sel = $("valueMonth");
  if (sel && !sel.options.length) {
    sel.innerHTML = MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("");
    sel.value = String(curMonth());   // "I'm going in" defaults to the month it is now
  }
  return sel;
}

// Clicking a month bar in the guide makes the chart the control: sets the one
// global travel month (the same one Top Picks ranks by), re-prices the stay
// map, and rebuilds the AI prompt for that month.
function planForMonth(m, quiet) {
  const sel = ensureMonthOptions();
  if (!sel || !(m >= 1 && m <= 12)) return;
  travelMonthChosen = true;   // even an unchanged value: the Flights tab stops showing next month
  const changed = sel.value !== String(m);
  sel.value = String(m);
  if (sel.value !== String(m)) return;   // never report a change that didn't happen
  if (sel._sync) sel._sync();
  if (loaded.value) renderValue();
  if (ccGuideIso) { renderCountryClimate(ccGuideIso); renderGuideStay(ccGuideIso); renderGuideAI(ccGuideIso); renderActivity(ccGuideIso); renderGuideFares(ccGuideIso); renderGuideGrades(ccGuideIso); }
  if (loaded.flights && flightsData && flightsData.configured) renderFlights();
  if (changed && !quiet) status("Planning for " + MONTHS[m - 1] + " ✓ — picks, stay prices & AI prompt updated", "ok");
  syncURL();
}
$("bestDetail").addEventListener("click", (e) => {
  const bar = e.target.closest("#bestDetail .bars .col[data-mn]");
  if (!bar) return;
  if (e.target.closest(".hzmark")) return;   // ⚠️ taps show the hazard, not switch months
  planForMonth(parseInt(bar.dataset.mn, 10));
});
// The keyboard half of the same control (the columns are role="button").
// planForMonth rebuilds the chart, so focus goes back to the new column.
$("bestDetail").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const bar = e.target.closest("#bestDetail .bars .col[data-mn]");
  if (!bar || e.target.closest(".hzmark")) return;
  e.preventDefault();   // Space would scroll the page
  const m = parseInt(bar.dataset.mn, 10);
  planForMonth(m);
  const again = document.querySelector('#bestDetail .col[data-mn="' + m + '"]');
  if (again) again.focus();
});

// Guide jump chips: smooth-scroll to a section (buttons, not #hash links, so
// the clean /guide/<slug> URLs stay untouched).
document.querySelector(".guidejump").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-go]");
  if (!b) return;
  let el = $(b.dataset.go);
  if (el && el.hidden) el = $("subscribe") || el;   // stay map can be hidden
  if (el) el.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
});

// "Show more" under the Top Picks table: 5 -> 10 -> 20 without a pre-decision
// dropdown (the Show select still lives in Filters for direct control).
$("showMore").addEventListener("click", () => {
  const next = pickCount() === 5 ? "10" : "20";
  $("pickCount").value = next;
  localStorage.setItem("fx_pickcount", next);
  renderValue();
});

// Explore-the-Data sub-views: currency / cost of living / safety / flights.
let dataMode = "currency";
const DATA_SUBS = { currency: "dataSubCurrency", afford: "dataSubAfford",
                    advisory: "dataSubAdvisory", flights: "dataSubFlights" };

async function setDataMode(mode) {
  if (!DATA_SUBS[mode]) mode = "currency";
  closeMapFullscreen();
  dataMode = mode;
  // Keep the head script's pre-paint flag in step (CSS shows the sub-view
  // html[data-dm] names, so a stale one would override the [hidden] below).
  document.documentElement.setAttribute("data-dm", mode);
  for (const x of document.querySelectorAll("#dataMode button"))
    x.classList.toggle("active", x.dataset.dm === mode);
  for (const m in DATA_SUBS) $(DATA_SUBS[m]).hidden = m !== mode;
  try {
    // Every risk-filtered view needs the advisories to know what to hide — this
    // used to be loaded for the currency table alone, which is half of why Cost
    // of living showed Iran: no filter, and nothing to filter with.
    if (mode !== "advisory" && !loaded.risk) {
      await ensureAdvisories().catch(() => {});
      loaded.risk = true;
    }
    if (mode === "currency") {
      if (!lastIndexData) loadIndex(activeRange);   // deferred from init
      else refitIndex();
      // Re-render the (already-populated) rates table so rows carry their level.
      if (!loaded.curRisk) {
        loaded.curRisk = true;
        if (dataRates) renderRates(dataRates);
      }
      applyCurrencyFilter();
    } else if (mode === "afford" && !loaded.afford) {
      await Promise.all([ensureWorld(), ensurePPP()]);
      renderAfford(); loaded.afford = true;
    } else if (mode === "afford") {
      refitChart($("colChart"));   // drawn while hidden: at the 800 fallback
    } else if (mode === "flights" && loaded.flights) {
      refitChart($("fbmChart"));
    } else if (mode === "advisory" && !loaded.advisory) {
      await Promise.all([ensureWorld(), ensureAdvisories()]);
      renderAdvisories(); loaded.advisory = true;
    } else if (mode === "flights" && !loaded.flights) {
      await Promise.all([ensureWorld(), fillOriginSelect($("flightOrigin"))]);
      loadFlights(); loaded.flights = true;
    }
  } catch (e) {
    status("Could not load " + mode + ": " + e.message, "err");
    dropLoadingRow({ currency: "rows", afford: "affRows", advisory: "advRows", flights: "flightRows" }[mode]);
  }
  syncURL();
}
for (const b of document.querySelectorAll("#dataMode button"))
  b.addEventListener("click", () => setDataMode(b.dataset.dm));

// ---- newsletter signup (Buttondown embed) ---------------------------------
// Set this to your public Buttondown newsletter username to enable signups.
const BUTTONDOWN_USER = "wandergrade";

// The digest's home-currency editions a reader can pick (server.py fills
// window.__WGDIGEST__ from fxtracker/digest_variants.ROLLOUT). Just USD means
// no picker anywhere, and the forms are exactly what they were. The choice
// travels as a Buttondown tag (currency-eur, ...). Function declarations, not
// consts: setHomeCur() calls syncSubCur() and can run before this line has.
function digestCurs() {
  const w = window.__WGDIGEST__;
  const c = Array.isArray(w) ? w.filter((x) => /^[A-Z]{3}$/.test(x)) : [];
  return c.length ? c : ["USD"];
}
function subCurDefault() { return digestCurs().includes(homeBase) ? homeBase : "USD"; }
function subCurTag(code) { return "currency-" + code.toLowerCase(); }
// <option>s for a picker: tag values for the embed form, codes for accounts.
// blank adds a leading "—" (nothing chosen yet), selected when sel is empty.
function subCurOptions(sel, asTag, blank) {
  return (blank ? `<option value=""${sel ? "" : " selected"}>—</option>` : "")
    + digestCurs().map((c) => `<option value="${asTag ? subCurTag(c) : c}"`
    + `${c === sel ? " selected" : ""}>${c}</option>`).join("");
}
// The default follows the home currency until the reader picks one: the geo
// seed lands after the footer box is drawn. Fixed width, so no shift.
function syncSubCur() {
  for (const s of document.querySelectorAll("select.subcur")) {
    if (s.dataset.touched) continue;
    const c = subCurDefault();
    s.value = s.name === "tag" ? subCurTag(c) : c;
  }
}
function touchSubCur(s) { if (s) s.addEventListener("change", () => { s.dataset.touched = "1"; }); }

// ---- feedback form ----------------------------------------------------------
// Google Form ("WanderGrade — Feedback", anonymous-friendly). Drives the line
// under the newsletter box; set "" to hide it. (A second "Feedback" link in the
// footer, 70px below the same form, was dropped as a duplicate.)
const FEEDBACK_URL = "https://forms.gle/gzG1Bmg7kKRKubri7";

function renderFeedback() {
  if (!FEEDBACK_URL) return;
  const sub = $("subscribe");
  if (sub) sub.insertAdjacentHTML("beforeend",
    `<a class="feedbacklink" href="${FEEDBACK_URL}" target="_blank" rel="noopener">💬 Spotted something off, or missing a feature? Tell me — it takes 30 seconds →</a>`);
}

function subscribeFormHTML() {
  const base = "https://buttondown.com/" + BUTTONDOWN_USER;
  if (!BUTTONDOWN_USER)
    return '<span class="hint">📬 Newsletter signup not configured yet — set BUTTONDOWN_USER in app.js.</span>';
  // embed-subscribe, with a HYPHEN. It was embed/subscribe — a slash — which
  // Buttondown 404s, so every visitor who ever tried to subscribe landed on
  // "Not found" and no one was ever added to the list. The endpoint is otherwise
  // unchanged; nothing here was ever going to reveal it, because the form posts
  // to a popup and the site never sees the response.
  // The hidden embed=1 is what Buttondown's own embed docs specify.
  if (digestCurs().length > 1) {
    // The currency rides as Buttondown's `tag` field. No "written in US
    // dollars" line: the reader picks the edition written for them.
    // Subscribing again through this form ADDS a tag (Buttondown never swaps
    // it), so the tip says how switching really works: the account panel
    // re-tags an existing subscriber even when the account itself isn't
    // opted in (accounts._sync_newsletter), and a reply always reaches us.
    const tip = "Each issue is graded for someone paying in this currency: prices compared with home,"
      + " and how far your money goes right now. Subscribing again here adds a currency rather"
      + " than switching. To switch, "
      + (window.__WGACCT__ === true ? "sign in (👤) with the address you subscribed with and change it"
        + " in your account, or reply to any issue." : "reply to any issue.");
    // subform-cur: only the picker form changes shape on a phone (styles.css).
    return `<span class="sublabel">📬 Once a month: the best-value places to travel, straight to your inbox.</span>
    <form action="https://buttondown.com/api/emails/embed-subscribe/${BUTTONDOWN_USER}"
          method="post" target="popupwindow"
          onsubmit="window.open('${base}','popupwindow')" class="subform subform-cur">
      <input type="email" name="email" placeholder="you@email.com" required>
      <span class="subcurwrap"><select name="tag" class="subcur" aria-label="Newsletter currency">${subCurOptions(subCurDefault(), true)}</select><span class="muted subcurtip" data-tip="${esc(tip)}" title="">ⓘ</span></span>
      <input type="hidden" name="embed" value="1">
      <button type="submit">Subscribe</button>
    </form>`;
  }
  // One honest line under the pitch: the digest is written in US dollars from
  // a US point of view (newsletter.py), and a visitor from anywhere else
  // should know that before they type an email — so it is text, not a ⓘ.
  return `<span class="sublabel">📬 Once a month: the best-value places to travel, straight to your inbox.</span>
    <form action="https://buttondown.com/api/emails/embed-subscribe/${BUTTONDOWN_USER}"
          method="post" target="popupwindow"
          onsubmit="window.open('${base}','popupwindow')" class="subform">
      <input type="email" name="email" placeholder="you@email.com" required>
      <input type="hidden" name="embed" value="1">
      <button type="submit">Subscribe</button>
    </form>
    <span class="subnote">Written in US dollars, from a US traveler's point of view.</span>`;
}

function renderSubscribe() {
  // Quiet catch box at the page bottom; the primary CTA is the small header
  // "📬 Subscribe" button (openSubscribeModal) so the tool — not an email gate —
  // is what greets people up top.
  const sub = $("subscribe");
  if (sub) { sub.innerHTML = subscribeFormHTML(); wireSubForm(sub); }
}

// Newsletter modal — opened by the header "📬 Subscribe" button, or auto-shown
// after the visitor has engaged (see armSubscribeAutoPrompt below). Two states
// govern the auto-invite: submitting a subscribe form marks the visitor as
// subscribed (never auto-invite again); closing without subscribing records a
// dismissal that re-arms the invite after 30 days.
const SUB_DONE_KEY = "wg_sub_done";          // "1" once they submit a signup form
const SUB_DISMISS_KEY = "wg_sub_dismissed";  // ms timestamp of last dismissal
const SUB_REARM_MS = 30 * 24 * 60 * 60 * 1000;

function subDone() {
  try { return localStorage.getItem(SUB_DONE_KEY) === "1"; } catch (e) { return false; }
}
function markSubscribed() {
  try { localStorage.setItem(SUB_DONE_KEY, "1"); } catch (e) {}
}
function markDismissed() {
  try { localStorage.setItem(SUB_DISMISS_KEY, String(Date.now())); } catch (e) {}
}
function shouldAutoPrompt() {
  if (subDone()) return false;
  try {
    const ts = parseInt(localStorage.getItem(SUB_DISMISS_KEY) || "0", 10);
    if (ts && (Date.now() - ts) < SUB_REARM_MS) return false;   // dismissed < 30 days ago
  } catch (e) {}
  return true;
}
// Submitting any subscribe form (modal or footer) = subscribed → stop inviting.
function wireSubForm(root) {
  const f = root && root.querySelector("form.subform");
  if (f) f.addEventListener("submit", markSubscribed);
  if (f) touchSubCur(f.querySelector("select.subcur"));
}

function openSubscribeModal(opts) {
  opts = opts || {};
  if (document.querySelector(".submodal")) return;
  const m = document.createElement("div");
  m.className = "submodal";
  if (opts.auto) m.dataset.nofocus = "1";   // see the modal observer
  m.innerHTML = '<div class="submodal-card"><button class="submodal-x" aria-label="Close">✕</button>'
    + subscribeFormHTML() + "</div>";
  document.body.appendChild(m);
  wireSubForm(m);
  requestAnimationFrame(() => m.classList.add("show"));
  const close = () => {
    document.removeEventListener("keydown", onKey);   // however it closes
    // Closed without subscribing → count as a dismissal (re-arm in 30 days).
    if (!subDone()) markDismissed();
    m.classList.remove("show");
    setTimeout(() => m.remove(), 220);
  };
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  m.querySelector(".submodal-x").onclick = close;
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  // Focus the field only for a deliberate click — auto-popping the mobile
  // keyboard on an unrequested modal is jarring.
  if (!opts.auto) { const inp = m.querySelector('input[type="email"]'); if (inp) inp.focus(); }
}
if ($("subscribeBtn")) $("subscribeBtn").addEventListener("click", () => openSubscribeModal());

// Auto-invite: surface the newsletter after the visitor has shown interest —
// whichever comes first of ~50% scroll depth or 45s dwell. Never interrupts
// another overlay. Suppressed permanently once they subscribe, and for 30 days
// after a dismissal, so a not-yet-convinced visitor gets a second chance later.
// Geo-seeded defaults: first-time visitors start on their own country instead
// of the US — home country, currency, budget and fare display all follow.
// Strictly a SEED: any stored choice wins, and nothing is written until the
// seed applies so a later explicit pick behaves exactly as before. The country
// comes from Cloudflare's per-request header via /api/geo (no-store; the HTML
// is edge-cached and must never carry one visitor's country to the next).
(async function seedGeoDefaults() {
  try {
    if (localStorage.getItem("fx_origin")) return;      // they've already chosen
    const g = await getJSON("/api/geo");
    const iso = (g.country || "").toUpperCase();
    if (!/^[A-Z]{2}$/.test(iso) || iso === "US") return;
    const list = await ensureOrigins();
    if (!list.some((o) => o.iso === iso)) return;       // not a supported origin
    // ONE path, not two: the select's own change listener calls
    // setTravelOrigin, so calling it directly AND dispatching change ran the
    // whole fares/advisories/render pipeline twice on every seeded first
    // visit. Dispatch when the select is ready; call directly only when not.
    const vo = $("valueOrigin");
    if (vo && [...vo.options].some((o) => o.value === iso)) {
      vo.value = iso;
      vo.dispatchEvent(new Event("change"));
    } else {
      setTravelOrigin(iso);
    }
    if (!homeManual && CUR_BY_ISO[iso]) setHomeCur(CUR_BY_ISO[iso], false);
  } catch (e) { /* geo is a nicety; silence is the right failure mode */ }
})();

(function armSubscribeAutoPrompt() {
  // First visit is for the product. The auto-invite waits for a RETURN visit:
  // interrupting someone mid-scroll on the pageview where they are deciding
  // whether the site is any good was the most user-hostile moment we had.
  // Visits are counted once per browser session; the header Subscribe button
  // and the footer form work on visit one as always.
  try {
    if (!sessionStorage.getItem("wg_sess")) {
      sessionStorage.setItem("wg_sess", "1");
      localStorage.setItem("wg_visits",
        String((parseInt(localStorage.getItem("wg_visits") || "0", 10) || 0) + 1));
    }
    if ((parseInt(localStorage.getItem("wg_visits") || "0", 10) || 0) < 2) return;
  } catch (e) {
    // Site data blocked: visits can't be counted and a dismissal can't stick,
    // so falling through armed the invite on the first visit and every page
    // view after it. No auto-invite then; the Subscribe button still works.
    return;
  }
  if (!shouldAutoPrompt()) return;
  let done = false, retry = null;
  function cleanup() {
    clearTimeout(timer);
    clearTimeout(retry);
    window.removeEventListener("scroll", onScroll);
  }
  function fire() {
    if (done || !shouldAutoPrompt()) { cleanup(); return; }
    // Don't stack on top of a guide lightbox, the spin-globe, or an open modal —
    // wait until the visitor's attention is free, then try again. The lightbox
    // stays in the DOM once opened (hidden), so only a VISIBLE one counts; one
    // pending retry at a time, however many scroll events land meanwhile.
    if (document.querySelector(".submodal, .lightbox:not([hidden]), .spinover")) {
      if (!retry) retry = setTimeout(() => { retry = null; fire(); }, 3000);
      return;
    }
    done = true;
    cleanup();
    openSubscribeModal({ auto: true });
  }
  function onScroll() {
    const de = document.documentElement;
    const max = de.scrollHeight - de.clientHeight;
    if (max <= 0) return;
    const y = de.scrollTop || document.body.scrollTop || 0;
    if (y / max >= 0.5) fire();
  }
  const timer = setTimeout(fire, 45000);
  window.addEventListener("scroll", onScroll, { passive: true });
})();

// ===========================================================================
//  Share: encode the current tab + settings into a URL anyone can open
// ===========================================================================
function currentTab() {
  const b = document.querySelector("#tabs button.active");
  return b ? b.dataset.tab : "value";
}

// ---- Clean per-country guide URLs (/guide/<slug>) for SEO -------------------
// The server renders each country at /guide/<slug>; the SPA mirrors that in the
// address bar and can open a country from such a URL. slugs.json is the shared
// slug<->ISO map (also used server-side).
// A failed load leaves empty maps (callers fall back to the query form, which
// always opens) and lets the next call try again.
let SLUG2ISO = null, ISO2SLUG = null, _slugsOk = false;
function ensureSlugs() {
  if (_slugsOk) return Promise.resolve();
  return fetch("/slugs.json").then((r) => {
    if (!r.ok) throw new Error("slugs " + r.status);
    return r.json();
  }).then((m) => {
    SLUG2ISO = m; ISO2SLUG = {};
    for (const s in m) ISO2SLUG[m[s]] = s;
    _slugsOk = true;
  }).catch(() => { if (!_slugsOk) { SLUG2ISO = SLUG2ISO || {}; ISO2SLUG = ISO2SLUG || {}; } });
}
// iso -> "/guide/japan". A country without a slug (or before slugs load) gets
// the query form, which the SPA always opens — never a guessed /guide/ path.
function guidePath(iso) {
  const slug = ISO2SLUG && ISO2SLUG[iso];
  return slug ? "/guide/" + slug : "/?tab=guide&gc=" + encodeURIComponent(iso);
}
// If the address is /guide/<slug>, the ISO it maps to (else null).
function pathGuideIso() {
  const m = location.pathname.match(/^\/guide\/([a-z0-9-]+)\/?$/);
  return (m && SLUG2ISO) ? (SLUG2ISO[m[1]] || null) : null;
}
// Keep <title>/canonical/og:url correct on client-side navigation too, so they
// match what the server rendered (and update as the user browses countries).
const SITE_ORIGIN = "https://wandergrade.com";
// server.py _HTML_DEFAULTS TITLE / DESC / OGTITLE — change them together.
const _DEFAULT_META = {
  title: "WanderGrade — Where Should I Travel to Next?",
  desc: "Decide where — and when — to go. Every country graded A+ to F on "
      + "prices, weather, safety, and flights. Free, no sign-up.",
  og: "Where Should I Travel to Next?",
};
const _DEFAULT_URL = SITE_ORIGIN + "/";
// The head the server sent with a /guide/<slug> page, read before anything
// rewrites it: the boot country keeps exactly what the crawler saw.
const _bootMeta = (() => {
  const d = document.querySelector('meta[name="description"]');
  return { iso: window.__WGGC__ || null, title: document.title, desc: d ? d.getAttribute("content") : "" };
})();
function setDocMeta(m, absURL) {
  document.title = m.title;
  const set = (sel, v) => { const e = document.querySelector(sel); if (e) e.setAttribute("content", v); };
  set('meta[name="description"]', m.desc);
  set('meta[property="og:description"]', m.desc);
  set('meta[name="twitter:description"]', m.desc);
  set('meta[property="og:title"]', m.og || m.title);
  set('meta[name="twitter:title"]', m.og || m.title);
  const c = document.querySelector('link[rel="canonical"]'); if (c) c.setAttribute("href", absURL);
  set('meta[property="og:url"]', absURL);
}
// The guide's h1, byte for byte render_guide.h1_html(): no figures, so it never
// contradicts one. Its topics are render_guide.h1_topics(): "cost" only where
// guide-facts.json has a price figure, "safety" only where it has an advisory.
// Until the file is in, every topic (the boot guide keeps the server's h1).
function guideH1Text(iso) {
  const f = _guideFacts && _guideFacts[iso];
  const t = [...(!f || f.pct != null ? ["cost"] : []), ...(!f || f.adv ? ["safety"] : []), "when to go"];
  return countryName(iso) + " travel: " + (t.length === 1 ? t[0] : t.slice(0, -1).join(", ") + " & " + t[t.length - 1]);
}
function guideH1Html(iso) {
  const n = countryName(iso);
  return '<span aria-hidden="true">' + flagEmoji(iso) + '</span> <span class="gname">' + esc(n) + "</span>"
    + esc(guideH1Text(iso).slice(n.length));
}
function syncGuideH1(iso) {
  const gh1 = $("guideH1");
  if (!gh1 || (!_guideFacts && iso === _bootMeta.iso)) return;   // the server's own h1
  if (gh1.textContent !== flagEmoji(iso) + " " + guideH1Text(iso)) gh1.innerHTML = guideH1Html(iso);
}
// ---- guide-facts.json: the dated snapshot behind every guide's title/snippet --
// Built by scripts/build_guide_facts.py from render_guide.meta(), so a guide
// opened in-app gets the server's exact title and description. The client
// never composes them from live data: a live band crossing would flip "Cheap"
// to "Expensive" in the DOM a crawler renders.
let _guideFacts = null, _guideFactsP = null;
function ensureGuideFacts() {
  if (_guideFacts) return Promise.resolve(_guideFacts);
  if (!_guideFactsP) _guideFactsP = getJSON("/guide-facts.json").then((d) => (_guideFacts = d))
    .catch((e) => { _guideFactsP = null; throw e; });
  return _guideFactsP;
}
// Past 90 days (render_guide.STALE_DAYS) the server drops every figure; so does this.
function guideFactsFresh() {
  const a = _guideFacts && _guideFacts._asof;
  return !!a && (Date.now() - Date.parse(a + "T00:00:00Z")) / 864e5 <= 90;
}
// "Sep 2026", the snapshot's month.
function guideFactsMonth() {
  const a = (_guideFacts && _guideFacts._asof) || "";
  return MON_ABBR[+a.slice(5, 7) - 1] ? MON_ABBR[+a.slice(5, 7) - 1] + " " + a.slice(0, 4) : "";
}
function guideMeta(iso) {
  if (iso === _bootMeta.iso) return { title: _bootMeta.title, desc: _bootMeta.desc };
  const f = _guideFacts && _guideFacts[iso];
  if (f) return { title: f.t, desc: (!guideFactsFresh() && f.dn) || f.d };
  // Not loaded yet: render_guide's number-free "Travel Guide" title ladder and
  // its last-resort description (render_guide.generic_desc) — never the
  // homepage's, which describes another page.
  const n = countryName(iso);
  const title = [n + " Travel Guide: Best Time to Visit & Things to Do", n + " Travel Guide: Best Time to Visit",
                 n + " Travel Guide"].find((t) => t.length <= 60) || n + " Travel Guide";
  return { title, desc: "What to do in " + countryNameInText(iso)
    + ", when to go, and what's in season — graded on prices, weather, safety and flights." };
}
function setGuideMeta(iso) {
  setDocMeta(guideMeta(iso), SITE_ORIGIN + guidePath(iso));
  if (!_guideFacts && iso !== _bootMeta.iso) ensureGuideFacts().then(() => {
    if (currentTab() === "guide" && ccGuideIso === iso) setDocMeta(guideMeta(iso), SITE_ORIGIN + guidePath(iso));
  }).catch(() => {});
}

function buildShareURL(forShare) {
  if (forShare === undefined) forShare = true;
  const q = new URLSearchParams();
  const tab = currentTab();
  q.set("tab", tab);
  if (tab === "value") {
    // Read before Top Picks builds too (activateTab pushes first): an empty
    // region select is "all", not vr=.
    if (regionSel !== "all") q.set("vr", regionSel);
    // A shared link pins the month; the address bar only once it's chosen, so
    // a reload doesn't turn the untouched default into a pick (see flightMonthNum).
    if ($("valueMonth").value && (forShare || travelMonthChosen)) q.set("vmn", $("valueMonth").value);
    if (pickCount() !== 5) q.set("pc", String(pickCount()));
    if (safetyFloor() !== "b") q.set("sf", safetyFloor());
    const fac = loadFactors();
    if (fac.length !== WEIGHT_DEFS.length) q.set("fac", fac.join("."));
    if (originIso() !== "US") q.set("vo", originIso());
    if (homeManual && homeBase !== homeCurAuto()) q.set("hc", homeBase);
    if (valueMapMode === "weather") q.set("vmm", "weather");
    const p = loadPriorities();
    const compact = WEIGHT_DEFS.map((w) => p[w.key][0]).join(".");   // e.g. h.m.m.m.m
    if (compact !== WEIGHT_DEFS.map((w) => w.def[0]).join(".")) q.set("pri", compact);
  } else if (tab === "data") {
    if (dataMode !== "currency") q.set("dm", dataMode);
    if (regionSel !== "all") q.set("vr", regionSel);
    // The Flights tab bands fares for a month, so its link keeps the one on
    // screen — same rule as Top Picks for the address bar.
    if (dataMode === "flights" && (forShare || travelMonthChosen)) q.set("vmn", String(flightMonthNum()));
    if (dataMode === "currency" && activeRange !== "1y") q.set("win", activeRange);
    if (dataMode === "currency" && homeBase !== "USD") q.set("db", homeBase);
    if (dataMode === "flights" && $("flightOrigin").value) q.set("fo", $("flightOrigin").value);
    if (dataMode === "afford" && colIso !== "world") q.set("cc", colIso);
    if (dataMode === "advisory" && govIso) q.set("sc", govIso);
    if (dataMode === "flights" && fbmIso !== "all") q.set("fc", fbmIso);
    if (dataMode === "afford" && colRange !== "10") q.set("cr", colRange);
    // Clean path: /guide/<slug>, plus ?vmn= once a trip month is chosen (or
    // for an explicit Share) — the Top Picks rule above. The month is what the
    // bars, stay dates and AI prompt are drawn for; dropping it made a shared
    // guide or a reload open on the calendar month. The canonical stays the
    // bare path (setDocMeta), so the query adds no duplicate for search.
    // Same-origin so history.pushState in syncURL accepts it.
  } else if (tab === "guide") {
    const u = location.origin + guidePath(_guideTarget || $("bestCountry").value || "JP");
    const vm = $("valueMonth").value;
    return vm && (forShare || travelMonthChosen) ? u + "?vmn=" + vm : u;
  } else if (tab === "visited") {
    loadVisited();
    // The visited list persists in localStorage already; only embed it for an
    // explicit Share (embedding it on every refresh would wrongly trip the
    // "viewing a shared map" warning against the user's own list).
    if (visited.size && forShare) q.set("v", [...visited].join(","));
  } else if (tab === "trip") {
    // Same deal as the visited map: the trip lives in localStorage, so without
    // embedding it a shared Trip link opens empty for the recipient — the one
    // tab where "share this" silently shared nothing.
    const t = loadTrip();
    if (t.size && forShare) {
      q.set("tp", [...t].join(","));
      const d = tripDays();
      if (d) q.set("td", String(d));
      const m = localStorage.getItem("fx_tripmonth");
      if (m) q.set("tm", m);
    }
  }
  // Non-guide tabs all live at the root path (guide returns early above); using
  // "/" avoids leaving a stale /guide/<slug> path when switching tabs.
  return location.origin + "/?" + q.toString();
}

// Keep the address bar in sync with the current tab + selections, so a refresh
// (or bookmark) lands the user right back where they were. Gated until init
// finishes restoring state, so it never clobbers the params being read.
let appReady = false;
let restoringHistory = false;   // true while applying a popstate (don't re-write the entry)
// push=true adds a history entry (real navigation: tab / country / detail) so the
// browser Back button returns to it; otherwise we replace (minor filter tweaks
// shouldn't pile up history). Only pushes when the URL actually changed.
function syncURL(push) {
  if (!appReady || restoringHistory) return;
  try {
    const url = buildShareURL(false);
    // Absolute vs absolute: comparing with pathname+search never matched, so
    // every push added an entry, even for a click on the tab already open.
    const cur = location.origin + location.pathname + location.search;
    if (push && url !== cur) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
  } catch (e) {}
}

// Back/forward: re-apply the tab + key state from the URL. Guarded so the
// restore doesn't itself push or overwrite the entry we're navigating to.
window.addEventListener("popstate", async () => {
  if (!appReady) return;
  restoringHistory = true;
  try {
    const q = new URLSearchParams(location.search);
    // The month first: a guide URL carries it too (/guide/<slug>?vmn=), and
    // the guide returns early below — Back between two months of one guide
    // left the bars on the month being left.
    const vmn = q.get("vmn"), vmSel = $("valueMonth");
    if (vmn && vmSel && [...vmSel.options].some((o) => o.value === vmn)) { vmSel.value = vmn; travelMonthChosen = true; }
    // Clean guide URL (/guide/<slug>) takes precedence over the other params.
    const pIso = pathGuideIso();
    if (pIso) { resyncCombos(); await openGuideFor(pIso, false); return; }
    const tab = q.get("tab") || "value";
    // setDataMode only loads Flights the first time, so without this Back
    // left the table on the month it was leaving while the URL said another.
    if (loaded.flights && flightsData && flightsData.configured) renderFlights();
    resyncCombos();   // restored values show in the search boxes too
    await activateTab(tab, false);
    if (tab === "guide" && GC_RE.test(q.get("gc") || "")) await openGuideFor(q.get("gc"), false);
    // Currency is the default and writes no dm, so a missing dm means currency
    // — not whichever sub-tab happened to be open last.
    else if (tab === "data") await setDataMode(q.get("dm") || "currency");
  } catch (e) {
    /* best-effort restore */
  } finally {
    restoringHistory = false;
  }
});

async function shareCurrent() {
  const url = buildShareURL();
  if (navigator.share) {
    try { await navigator.share({ title: "Where Should I Travel to Next?", url }); return; }
    // Cancelled: nothing. A real failure (no permission, unsupported) falls
    // through to the clipboard.
    catch (e) { if (e && e.name === "AbortError") return; }
  }
  try {
    await navigator.clipboard.writeText(url);
    status("Share link copied to clipboard 🔗", "ok");
  } catch (e) {
    status("Share link: " + url, "ok");
  }
}

// Restore state from a shared URL. Pre-phase runs before the first tab builds
// (priorities + visited list); post-phase sets controls after tabs exist.
const sharedQ = new URLSearchParams(location.search);
const GC_RE = /^[A-Z]{2}(-[A-Z]{3})?$/;   // guide codes: JP, and GB-SCT-style home nations

function preApplyShared() {
  if (![...sharedQ.keys()].length) return;
  const pri = sharedQ.get("pri");
  if (pri) {
    const lv = { h: "high", m: "med", l: "low" };
    const parts = pri.split(".");
    loadPriorities();
    WEIGHT_DEFS.forEach((w, i) => { if (lv[parts[i]]) priorities[w.key] = lv[parts[i]]; });
    savePriorities();
  }
  const v = sharedQ.get("v");
  if (v) {
    // On screen only (sharedVisitedView): storage and the account keep the
    // viewer's own list — a signed-in viewer's sync used to merge this one in.
    // GC_RE, not two letters: England/Scotland/Wales (GB-ENG…) are markable and
    // trip-able, and a two-letter filter dropped them from every shared link.
    visited = new Set(v.split(",").map((s) => s.trim().toUpperCase()).filter((s) => GC_RE.test(s)));
    sharedVisitedView = true;
  }
  // Shared trip: in-memory only, like the visited list above — nothing touches
  // the recipient's saved trip unless they edit, and the warning in
  // postApplyShared says so before they do.
  const tp = sharedQ.get("tp");
  if (tp) {
    _trip = new Set(tp.split(",").map((s) => s.trim().toUpperCase()).filter((s) => GC_RE.test(s)));
    // Days/month from the link override the recipient's saved ones for this
    // view only — renderTripBar reads this instead of localStorage until the
    // recipient edits either control, which dissolves the shared view into
    // their own (and only then persists).
    // Validated here AND escaped where drawn: td went into innerHTML raw, so a
    // crafted link could run script on the site (reflected XSS).
    const td = parseInt(sharedQ.get("td"), 10), tm = sharedQ.get("tm");
    sharedTripView = {
      td: td >= 1 && td <= 180 ? td : null,
      tm: /^(0|[1-9]|1[0-2])$/.test(tm || "") ? tm : null,
    };
  }
}

// The tab (and Data sub-view) a landing URL names. Read by init, which opens
// it directly, and by postApplyShared; the <head> script applies the same
// mapping before first paint (html[data-tab], html[data-dm]).
function sharedTab() {
  let tab = sharedQ.get("tab");
  if (tab && !/^[a-z]+$/.test(tab)) tab = null;   // goes into a CSS selector below
  let dm = sharedQ.get("dm");
  // Old share links used standalone money/advisory/flights tabs — map them
  // into the consolidated Explore-the-Data tab.
  const legacyTabs = { money: "currency", advisory: "advisory", flights: "flights" };
  if (legacyTabs[tab]) {
    dm = dm || (sharedQ.get("mmode") === "afford" ? "afford" : legacyTabs[tab]);
    tab = "data";
  }
  if (tab && !document.querySelector(`#tabs button[data-tab="${tab}"]`)) tab = null;
  const gc = sharedQ.get("gc");
  const gcOk = !!gc && GC_RE.test(gc);   // a code, never markup: it reaches the guide's renderers
  return { tab, dm, gc, gcOk };
}
let _bootTab = null;   // the tab init opened (postApplyShared doesn't reopen it)

async function postApplyShared() {
  if (![...sharedQ.keys()].length) return;
  const { tab, dm, gc, gcOk } = sharedTab();
  // A guide link opens its own country below (after the month is applied);
  // opening the tab bare first drew a default country for nothing.
  if (tab && tab !== "value" && tab !== _bootTab && !(tab === "guide" && gcOk)) {
    await activateTab(tab);
  }
  // init already opened this sub-view when it opened the tab.
  if (tab === "data" && dm && dm !== dataMode) await setDataMode(dm);
  let rerender = false;
  if (sharedQ.get("vr") && [...$("valueRegion").options].some((o) => o.value === sharedQ.get("vr"))) {
    $("valueRegion").value = sharedQ.get("vr"); rerender = true;
  }
  const vmn = sharedQ.get("vmn"), vmSel = ensureMonthOptions();
  if (vmn && vmSel && [...vmSel.options].some((o) => o.value === vmn)) {
    // A /guide/<slug>?vmn= page (the newsletter's link) has already drawn its
    // guide for the calendar month: go through planForMonth so the chart, the
    // stays, the season list and the AI prompt all move to the link's month.
    // A ?gc= link opens its guide below, after the value is set, and the
    // guide then draws for it directly.
    if (ccGuideIso) planForMonth(+vmn, true);
    else {
      vmSel.value = vmn; travelMonthChosen = true; rerender = true;
      if (loaded.flights && flightsData && flightsData.configured) renderFlights();
    }
  }
  if (sharedQ.get("pc")) { $("pickCount").value = sharedQ.get("pc"); rerender = true; }
  if (["a", "b", "any"].includes(sharedQ.get("sf"))) { $("safeFloor").value = sharedQ.get("sf"); rerender = true; }
  if (sharedQ.get("fac")) {
    const keys = sharedQ.get("fac").split(".").filter((k) => WEIGHT_DEFS.some((w) => w.key === k));
    if (keys.length) { factors = keys; saveFactors(); buildFactorChips(); rerender = true; }
  }
  if (sharedQ.get("vmm") === "weather") {
    valueMapMode = "weather"; rerender = true;
    syncRankSort();
    markRankBy();
  }
  // Shared origin: vo is canonical; fall back to a legacy fo-only link. Either
  // way it drives the one global "traveling from".
  const sharedOrigin = sharedQ.get("vo") || sharedQ.get("fo");
  if (sharedOrigin && /^[A-Z]{2}$/.test(sharedOrigin)) {
    ensureOrigins().then(() => setTravelOrigin(sharedOrigin)).catch(() => {});
  }
  const hc = sharedQ.get("hc");
  if (hc && /^[A-Z]{3}$/.test(hc)) setHomeCur(hc, true);
  if (rerender && loaded.value) renderValue();
  if (gcOk) {
    await openGuideFor(gc);
    if (sharedQ.get("ai")) openGuideAI(gc);   // email "Plan with AI" deep link
  }
  if (sharedQ.get("win")) loadIndex(rangeFromParam(sharedQ.get("win")));
  const db = sharedQ.get("db");
  // A currency carried on a shared link is an explicit choice: pin it, and let
  // setHomeCur mirror both pickers and refresh whatever has loaded.
  if (db && /^[A-Z]{3}$/.test(db) && db !== homeBase) setHomeCur(db, true);
  if (sharedQ.get("v") && tab === "visited") {
    renderVisited();
    status(`Viewing a shared map of ${visited.size} ${visited.size === 1 ? "country" : "countries"} — editing it will overwrite your own saved list.`, "ok", true);
  }
  if (sharedQ.get("tp") && tab === "trip") {
    renderTripBar();
    // renderTripBar reads sharedTripView, so the link's days/month are already
    // in the controls; nothing here touches localStorage.
    status(`Viewing a shared trip of ${loadTrip().size} ${loadTrip().size === 1 ? "country" : "countries"} — changing it will overwrite your own.`, "ok", true);
  }
  resyncCombos();   // reflect restored values in the search inputs
}

// ===========================================================================
//  Visited tab: social-media share image (SVG -> canvas -> PNG)
// ===========================================================================
const SHARE_W = 1200, SHARE_H = 630, STORY_W = 1080, STORY_H = 1920;
const SHARE_SCALE = 4;   // render at 4x (4800px landscape) for max crispness on hi-DPI / 4K
// Pins were once disabled for looking busy — that's fixed: they now mark ONLY
// visited places too small for their paint to show (Singapore, Barbados...).
const SHARE_PINS = true;

// Refine the app's 6 regions into true continents for the "N continents" flex.
const _SOUTH_AMERICA = new Set("CO VE GY SR EC PE BR BO PY CL AR UY GF FK".split(" "));
const _MENA_AFRICA = new Set("EG MA DZ TN LY".split(" "));
function continentOf(iso) {
  if (EXTRA_CONTINENT[iso]) return EXTRA_CONTINENT[iso];
  const r = ISO_REGION[iso];
  if (!r) return null;
  if (r === "AMER") return _SOUTH_AMERICA.has(iso) ? "SA" : "NA";
  if (r === "MENA") return _MENA_AFRICA.has(iso) ? "AF" : "AS";
  return { EUR: "EU", ASIA: "AS", AFRICA: "AF", OCEANIA: "OC" }[r] || null;
}
function visitedContinents() {
  const s = new Set();
  for (const iso of visited) { const c = continentOf(iso); if (c) s.add(c); }
  return s.size;
}
// ---- per-continent progress -------------------------------------------------
// "% of each continent" chips under the stats line, gold at 100%. Progress
// counts UN members only — completing Europe shouldn't require Guernsey,
// Svalbard and all three UK home nations (territories still count toward the
// headline total, but not the "% of the world", which shares this basis).
// Antarctica is one place; its trophies are the map medallion and the
// 7-continents badge, so it sits out of this row.
const UN_MEMBERS = new Set(("AF AL DZ AD AO AG AR AM AU AT AZ BS BH BD BB BY BE BZ BJ BT BO BA BW BR BN BG BF BI " +
  "CV KH CM CA CF TD CL CN CO KM CG CD CR CI HR CU CY CZ DK DJ DM DO EC EG SV GQ ER EE SZ ET " +
  "FJ FI FR GA GM GE DE GH GR GD GT GN GW GY HT HN HU IS IN ID IR IQ IE IL IT JM JP JO KZ KE " +
  "KI KP KR KW KG LA LV LB LS LR LY LI LT LU MG MW MY MV ML MT MH MR MU MX FM MD MC MN ME MA " +
  "MZ MM NA NR NP NL NZ NI NE NG MK NO OM PK PW PA PG PY PE PH PL PT QA RO RU RW KN LC VC WS " +
  "SM ST SA SN RS SC SL SG SK SI SB SO ZA SS ES LK SD SR SE CH SY TJ TZ TH TL TG TO TT TN TR " +
  "TM TV UG UA AE GB US UY UZ VU VE VN YE ZM ZW VA PS").split(" "));
const CONTINENT_NAMES = { NA: "North America", SA: "South America", EU: "Europe",
                          AS: "Asia", AF: "Africa", OC: "Oceania" };
function continentProgress() {
  const totals = {}, got = {};
  for (const iso of allPlaces()) {
    if (!UN_MEMBERS.has(iso)) continue;
    const c = continentOf(iso);
    if (!c || c === "AN") continue;
    totals[c] = (totals[c] || 0) + 1;
    if (visited.has(iso)) got[c] = (got[c] || 0) + 1;
  }
  return Object.keys(CONTINENT_NAMES).map((c) => ({
    c, name: CONTINENT_NAMES[c], total: totals[c] || 0, n: got[c] || 0,
    pct: totals[c] ? Math.round(((got[c] || 0) / totals[c]) * 100) : 0,
  }));
}

// Honest, count-based milestone tiers (counts are how travelers actually
// talk — nobody brags in percentages). The ladder has a rule, not vibes:
// each tier is roughly double the last, then the summit tiers close in on
// 193 (every UN member). 100 nods to the Travelers' Century Club.
const MILESTONE_TIERS = [
  [5, "🧭 Explorer"], [10, "🌍 Globetrotter"], [25, "🌟 Seasoned Traveler"],
  [50, "⭐ Globe Master"], [100, "💯 Century Club"], [150, "🏆 World Elite"],
  [193, "👑 Every Country Club"],
];
function travelMilestone(n) {
  let label = null;
  for (const [t, l] of MILESTONE_TIERS) if (n >= t) label = l;
  return label;
}
// Highest earned tier + the next one to chase, for the on-page award tag tooltip.
function milestoneInfo(n) {
  let earned = null, next = null;
  for (const [t, l] of MILESTONE_TIERS) {
    if (n >= t) earned = { t, label: l };
    else { next = { t, label: l }; break; }
  }
  return { earned, next };
}

// orientation: "landscape" (1200x630, for X/LinkedIn/FB) or "story" (1080x1920,
// for Instagram/TikTok Stories). Returns { svg, W, H, flag } — flags are drawn
// on the canvas afterward (SVG can't render emoji).
function buildVisitedShareSVG(orientation, withPins) {
  const story = orientation === "story";
  const W = story ? STORY_W : SHARE_W, H = story ? STORY_H : SHARE_H;
  const n = visited.size, m = wishlist.size;
  const pct = worldPct(visited);
  const cont = visitedContinents();
  // the 7-continent badge (Antarctica included) outranks any count tier
  const badge = cont === 7 ? "🌐 All 7 Continents" : travelMilestone(n);
  const host = esc(location.host || "wandergrade.com");
  const font = "-apple-system,'Segoe UI',Arial,sans-serif";

  const mapW = story ? 1040 : 960, latTop = 80, latBot = -56;
  const mapH = Math.round((mapW * (latTop - latBot)) / 360);
  let paths = "";
  // same home-nation rules as the live map: the subdivisions replace the UK
  // outline (when present) and paint with their own mark or the whole-UK mark
  const hasSubs = worldGeo.features.some((x) => x.properties.sub);
  for (const f of worldGeo.features) {
    const iso = f.properties.iso, par = f.properties.sub;
    if (!par && iso === "GB" && hasSubs) continue;
    // Antarctica projects BELOW the map crop, and unlike the live map there's
    // no viewBox here to clip it — flat-drawn it smears across the card as a
    // full-width band. It gets the polar medallion below instead.
    if (iso === "AQ") continue;
    const marked = visited.has(iso) || (par && visited.has(par));
    const wished = wishlist.has(iso) || (par && wishlist.has(par));
    const fill = marked ? "#34d27b" : wished ? "#4f9bf0" : "#243449";
    // been + want-to-go-again reads as green with a blue ring, like the live map
    const stroke = marked && wished ? 'stroke="#4f9bf0" stroke-width="2.4"' : 'stroke="#0c1422" stroke-width="0.9"';
    const g = f.geometry, polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    let d = "";
    for (const poly of polys) for (const ring of poly)
      if (ring.length >= 3) d += projectRing(ring, mapW, mapH, latTop, latBot);
    if (d) paths += `<path d="${d}" fill="${fill}" ${stroke}/>`;
  }
  // Antarctica medallion — same polar-view inset as the live travel map,
  // bottom-left of the map band, colored by its mark.
  let medal = "";
  const aqF = worldGeo.features.find((x) => x.properties.iso === "AQ");
  if (aqF) {
    const mcx = 64, mcy = mapH - 58, mR = 46;
    const aqBeen = visited.has("AQ"), aqWant = wishlist.has("AQ");
    const mFill = aqBeen ? "#34d27b" : aqWant ? "#4f9bf0" : "#243449";
    const mStroke = aqBeen && aqWant ? ' stroke="#4f9bf0" stroke-width="2.4"' : ' stroke="#0c1422" stroke-width="0.9"';
    let d = "";
    for (const poly of aqF.geometry.coordinates)
      for (const ring of poly) {
        ring.forEach((pt, i) => {
          const lam = pt[0] * Math.PI / 180;
          const rad = ((90 + pt[1]) / 30) * (mR - 7);
          d += (i ? "L" : "M") + (mcx + rad * Math.sin(lam)).toFixed(1) + " "
             + (mcy + rad * Math.cos(lam)).toFixed(1);
        });
        d += "Z";
      }
    medal = `<circle cx="${mcx}" cy="${mcy}" r="${mR}" fill="rgba(148,163,184,.10)" stroke="rgba(148,163,184,.5)" stroke-width="1.4"/>`
      + `<path d="${d}" fill="${mFill}"${mStroke}/>`;
  }

  // A red pushpin on EVERY visited place — the stuck-a-pin-in-the-map
  // scrapbook metaphor (pins sit at centroids, not cities), and they're what
  // makes micro places like Singapore visible on the card at all.
  let pins = "";
  if (withPins) {
    const cen = countryCentroids();
    for (const iso of visited) {
      const c = cen[iso];
      if (!c) continue;
      const px = ((c[0] + 180) / 360) * mapW, py = ((latTop - c[1]) / (latTop - latBot)) * mapH;
      if (px < 0 || px > mapW || py < 0 || py > mapH) continue;
      pins += `<g transform="translate(${px.toFixed(1)},${py.toFixed(1)})">`
        + `<path d="M0,0 C-1.5,-3 -6.5,-7.5 -6.5,-12 A6.5,6.5 0 1 1 6.5,-12 C6.5,-7.5 1.5,-3 0,0 Z" fill="#ff4d57" stroke="#0a0c10" stroke-width="0.8"/>`
        + `<circle cy="-12" r="2.6" fill="#fff"/></g>`;
    }
  }

  const stat = [];
  if (cont) stat.push(`🌍 ${cont} continent${cont === 1 ? "" : "s"}`);
  if (n) stat.push(`~${pct}% of the world`);
  const statLine = stat.join("   ·   ");
  const listLine = m ? `${m} more on my list` : "";

  // milestone pill (anchor: "middle" centers on cx; "end" right-aligns to cx)
  const pill = (cx, cy, text, anchor) => {
    if (!text) return "";
    const w = text.length * 11 + 52, x = anchor === "middle" ? cx - w / 2 : cx - w;
    return `<rect x="${x}" y="${cy - 25}" width="${w}" height="38" rx="19" fill="#12331e" stroke="#34d27b" stroke-width="1.5"/>`
      + `<text x="${x + w / 2}" y="${cy + 1}" text-anchor="middle" font-family="${font}" font-size="18" font-weight="700" fill="#7fd99a">${esc(text)}</text>`;
  };

  const grad = `<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">`
    + `<stop offset="0" stop-color="#0a0c12"/><stop offset="1" stop-color="#030407"/></linearGradient></defs>`
    + `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;

  let inner, flag;
  if (story) {
    const cx = W / 2, big = String(n || m || 0);
    // per-continent progress, matching the site's chips — up to 3 per line so
    // even all six continents fit the gap between the stats and the map
    const CONT_SHORT = { NA: "N. America", SA: "S. America", EU: "Europe",
                         AS: "Asia", AF: "Africa", OC: "Oceania" };
    const prog = continentProgress().filter((p) => p.n > 0 && p.total > 0);
    let contLines = "";
    for (let i = 0; i < prog.length; i += 3) {
      const parts = prog.slice(i, i + 3).map((p) => p.pct === 100
        ? `<tspan fill="#e8c34f">🏅 ${CONT_SHORT[p.c]} 100%</tspan>`
        : `<tspan>${CONT_SHORT[p.c]} ${p.pct}%</tspan>`
      ).join(`<tspan fill="#4a5a70">   ·   </tspan>`);
      contLines += `<text x="${cx}" y="${772 + (i / 3) * 46}" text-anchor="middle" font-family="${font}" font-size="30" fill="#9fb3cd">${parts}</text>`;
    }
    inner = `
      <text x="${cx}" y="160" text-anchor="middle" font-family="${font}" font-size="30" font-weight="800" letter-spacing="6" fill="#7fd99a">🗺️ WANDER LIST</text>
      <text x="${cx}" y="440" text-anchor="middle" font-family="${font}" font-size="260" font-weight="800" fill="#34d27b">${big}</text>
      <text x="${cx}" y="520" text-anchor="middle" font-family="${font}" font-size="48" font-weight="700" fill="#ffffff">${n ? (n === 1 ? "country visited" : "countries visited") : "on my wishlist"}</text>
      ${badge ? pill(cx, 610, badge, "middle") : ""}
      ${statLine ? `<text x="${cx}" y="${badge ? 700 : 660}" text-anchor="middle" font-family="${font}" font-size="36" fill="#9fb3cd">${esc(statLine)}</text>` : ""}
      ${contLines}
      <g transform="translate(${(W - mapW) / 2},900)">${paths}${pins}${medal}</g>
      ${listLine ? `<text x="${cx}" y="1580" text-anchor="middle" font-family="${font}" font-size="34" fill="#9fb3cd">✦ ${esc(listLine)}</text>` : ""}
      <circle cx="${cx - 168}" cy="1660" r="9" fill="#34d27b"/><text x="${cx - 150}" y="1669" font-family="${font}" font-size="28" font-weight="600" fill="#9fb3cd">been</text>
      <circle cx="${cx + 14}" cy="1660" r="9" fill="#4f9bf0"/><text x="${cx + 32}" y="1669" font-family="${font}" font-size="28" font-weight="600" fill="#9fb3cd">want to go</text>
      <text x="${cx}" y="1772" text-anchor="middle" font-family="${font}" font-size="32" fill="#8fa3bd">Make your own map →</text>
      <text x="${cx}" y="1822" text-anchor="middle" font-family="${font}" font-size="42" font-weight="800" fill="#7fd99a">${host}</text>`;
    // flags fill the band between the map (~1315) and the wishlist line (1580)
    flag = { x: cx, y: 1352, size: 46, align: "center", maxH: 195 };
  } else {
    const headline = n
      ? `I've been to <tspan font-size="58" fill="#34d27b">${n}</tspan> ${n === 1 ? "country" : "countries"}`
      : `My travel <tspan fill="#34d27b">Wander List</tspan>`;
    const subParts = [statLine, listLine].filter(Boolean).join("   ·   ");
    inner = `
      <text x="60" y="52" font-family="${font}" font-size="20" font-weight="800" letter-spacing="3" fill="#7fd99a">🗺️ WANDER LIST</text>
      ${badge ? pill(W - 50, 50, badge, "end") : ""}
      <text x="60" y="116" font-family="${font}" font-size="42" font-weight="800" fill="#ffffff">${headline}</text>
      ${subParts ? `<text x="60" y="150" font-family="${font}" font-size="21" fill="#9fb3cd">${esc(subParts)}</text>` : ""}
      <g transform="translate(${(W - mapW) / 2},168)">${paths}${pins}${medal}</g>
      <rect x="0" y="${H - 48}" width="${W}" height="48" fill="#000000"/>
      <rect x="0" y="${H - 49}" width="${W}" height="1.5" fill="#1c2940"/>
      <circle cx="68" cy="${H - 24}" r="7" fill="#34d27b"/><text x="83" y="${H - 18}" font-family="${font}" font-size="19" font-weight="600" fill="#9fb3cd">been</text>
      <circle cx="152" cy="${H - 24}" r="7" fill="#4f9bf0"/><text x="167" y="${H - 18}" font-family="${font}" font-size="19" font-weight="600" fill="#9fb3cd">want to go</text>
      <text x="${W - 60}" y="${H - 18}" text-anchor="end" font-family="${font}" font-size="19" font-weight="700" fill="#7fd99a">Make your own map → ${host}</text>`;
    flag = { x: 60, y: H - 64, size: 30, align: "left", maxH: 36 };
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W * SHARE_SCALE}" height="${H * SHARE_SCALE}" viewBox="0 0 ${W} ${H}">${grad}${inner}</svg>`;
  return { svg, W, H, flag };
}

// Wrap flag emojis into rows at the largest size (starting at startSize,
// floor 14px) whose wrapped block fits maxW × maxH. Returns { size, rows }.
function fitFlagRows(ctx, flags, maxW, maxH, startSize) {
  let size = startSize, rows = [];
  for (;;) {
    // must match the drawing font exactly — measure and paint as one
    ctx.font = size + "px -apple-system,system-ui,'Segoe UI',Arial,sans-serif";
    rows = [];
    let row = "";
    for (const f of flags) {
      const next = row ? row + " " + f : f;
      if (row && ctx.measureText(next).width > maxW) { rows.push(row); row = f; }
      else row = next;
    }
    if (row) rows.push(row);
    if (rows.length * Math.round(size * 1.35) <= maxH || size <= 14) return { size, rows };
    size -= 2;
  }
}

// ---- shareable data-map images ---------------------------------------------
// The Wander List share card worked because it is a *finding about you*. The
// data maps have the same property — "what $100 buys" travelled on Reddit —
// but had no way to leave the site except a screenshot. This wraps whichever
// map is on screen in a title, key and caveat and exports a PNG.
//
// The caveat is baked into the image on purpose: these get reposted without
// their captions, and a purchasing-power map read as a travel budget is the
// misreading that actually costs us credibility.
function buildMapShareSVG(hostId, o) {
  const src = $(hostId) && $(hostId).querySelector("svg");
  if (!src) throw new Error("map not ready");
  const HEAD = 88, FOOT = 22, W = 1000, MAPH = 386, H = MAPH + HEAD + FOOT;
  const BG = "#101316", FG = "#f2f5f7", MUTE = "#9aa4ad", DIM = "#7d868f";
  const F = "Helvetica Neue, Helvetica, Arial, sans-serif";
  const esc2 = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  let leg = "";
  const sw = o.swatches || [];
  if (o.gradient) {
    leg += '<defs><linearGradient id="lg" x1="0" x2="1">'
      + '<stop offset="0" stop-color="' + o.gradient[0] + '"/>'
         + '<stop offset="0.5" stop-color="' + o.gradient[1] + '"/>'
         + '<stop offset="1" stop-color="' + o.gradient[2] + '"/></linearGradient></defs>'
      + '<text x="16" y="68" font-family="' + F + '" font-size="9" fill="' + MUTE + '">' + esc2(o.leftLabel) + "</text>"
      + '<rect x="' + (20 + o.leftLabel.length * 5) + '" y="59" width="150" height="9" rx="2" fill="url(#lg)"/>'
      + '<text x="' + (178 + o.leftLabel.length * 5) + '" y="68" font-family="' + F + '" font-size="9" fill="' + MUTE + '">' + esc2(o.rightLabel) + "</text>";
  }
  let x = (o.gradient ? 250 + o.leftLabel.length * 5 : 16);
  sw.forEach((s) => {
    leg += '<rect x="' + x + '" y="59" width="9" height="9" rx="2" fill="' + s.c + '"/>'
         + '<text x="' + (x + 13) + '" y="68" font-family="' + F + '" font-size="9" fill="' + MUTE + '">' + esc2(s.label) + "</text>";
    x += 22 + s.label.length * 5;
  });

  // The pulse that marks top picks on screen cannot survive a PNG, and a
  // shared image with no answer in it is just a green map. List them instead,
  // bottom-left over the empty Pacific — the reader gets the takeaway without
  // decoding colours, which is what made the Reddit maps travel.
  let picksOverlay = "";
  if (o.picks && o.picks.length) {
    const rows = o.picks.slice(0, 8);
    const lh = 13, padY = 9, boxH = rows.length * lh + padY * 2 + 12;
    const boxW = 168, x = 16, y = HEAD + MAPH - boxH - 10;
    picksOverlay = '<rect x="' + x + '" y="' + y + '" width="' + boxW + '" height="' + boxH
      + '" rx="6" fill="#101316" fill-opacity="0.82"/>'
      + '<text x="' + (x + 11) + '" y="' + (y + padY + 10) + '" font-family="' + F
      + '" font-size="9.5" font-weight="700" fill="' + FG + '">' + esc2(o.picksTitle || "Top picks") + "</text>"
      + rows.map((n2, i) =>
          '<text x="' + (x + 11) + '" y="' + (y + padY + 10 + 14 + i * lh) + '" font-family="' + F
          + '" font-size="9" fill="' + MUTE + '">' + esc2((i + 1) + ". " + n2) + "</text>").join("");
  }

  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H
    + '" viewBox="0 0 ' + W + " " + H + '">'
    + '<rect width="' + W + '" height="' + H + '" fill="' + BG + '"/>'
    + '<text x="16" y="27" font-family="' + F + '" font-size="19" font-weight="700" fill="' + FG + '">' + esc2(o.title) + "</text>"
    + '<text x="16" y="45" font-family="' + F + '" font-size="9.5" fill="' + MUTE + '">' + esc2(o.sub) + "</text>"
    + leg
    // The HTML serializer writes U+00A0 as &nbsp;, which XML doesn't define —
    // one locale-formatted fare ("1 234" in sv/ru/pl…) in a <title> made the
    // whole image fail to load. Every other entity it emits is XML-safe.
    + '<g transform="translate(0,' + HEAD + ')">' + src.innerHTML.replace(/&nbsp;/g, "&#160;") + "</g>"
    + picksOverlay
    + '<text x="16" y="' + (HEAD + MAPH + 15) + '" font-family="' + F + '" font-size="8" fill="' + DIM + '">' + esc2(o.footer) + "</text>"
    + "</svg>";
  return { svg, W, H };
}

async function downloadMapImage(hostId, o) {
  try {
    const { svg, W, H } = buildMapShareSVG(hostId, o);
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
    const c = document.createElement("canvas");
    c.width = W * SHARE_SCALE; c.height = H * SHARE_SCALE;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#101316"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    URL.revokeObjectURL(url);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const file = new File([blob], o.filename, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: o.title }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }   // cancelled: nothing; a real failure downloads
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = o.filename;
    a.click();
    status("Map image downloaded — post it anywhere 🌍", "ok");
  } catch (e) {
    // img.onerror rejects with an Event, which has no .message.
    status("Could not build map image: " + ((e && e.message) || "the image failed to render"), "err");
  }
}

// The ranked list itself as an image — the product's actual answer, which the
// map exports only gesture at. Portrait, because rankings get shared from
// phones. Emoji flags can't ride inside the SVG (SVG-in-<img> has no emoji
// font); we return their positions and the canvas pass draws them with
// fillText, the same split buildVisitedShareSVG settled on.
const RANK_GRADE_FILL = { "A+": "#067a23", "A": "#2f9e44", "B+": "#74b816",
                          "B": "#c9a200", "C": "#e8590c", "D": "#d9480f", "F": "#b00020" };
// White on the mid-tone fills failed contrast (B 2.4:1); mirrors styles.css .gr*.
const RANK_GRADE_INK = (g) => (g === "A+" || g === "F" || !RANK_GRADE_FILL[g]) ? "#fff" : "#000";
// Money on an exported image, which travels without the page around it: a bare
// "$" reads as local money to an Australian or a Canadian. Converted from the
// USD cache into the "In" currency at today's rate; USD is spelled US$.
function shareMoney(usd) {
  const cur = /^[A-Z]{3}$/.test(homeBase || "") ? homeBase : "USD";
  const r = cur === "USD" ? 1 : rateForCurrency(cur);
  if (!r) return "US$" + Math.round(usd).toLocaleString("en");
  return (cur === "USD" ? "US$" : cur + " ") + Math.round(usd * r).toLocaleString("en");
}
function buildRankShareSVG() {
  if (!lastPicks || !lastPicks.length) throw new Error("ranking not ready");
  const picks = lastPicks.slice(0, 10);
  const month = MONTHS[(lastPicksMonth || curMonth()) - 1];
  const originName = originLabel();
  const A = plAnchor(originIso());   // US fallback when home has no price level
  const W = 640, HEAD = 118, ROWH = 62, FOOT = 54;
  const H = HEAD + picks.length * ROWH + FOOT;
  const BG = "#101316", FG = "#f2f5f7", MUTE = "#9aa4ad", DIM = "#7d868f", LINE = "#242a30";
  const F = "Helvetica Neue, Helvetica, Arial, sans-serif";
  const esc2 = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  let body = "";
  const flags = [];
  picks.forEach((s, i) => {
    const y = HEAD + i * ROWH;
    const g = grade(s.value);
    const gw = g.length > 1 ? 46 : 38;
    if (i) body += '<line x1="24" x2="' + (W - 24) + '" y1="' + y + '" y2="' + y
      + '" stroke="' + LINE + '" stroke-width="1"/>';
    body += '<text x="30" y="' + (y + 38) + '" font-family="' + F
      + '" font-size="17" font-weight="800" fill="' + DIM + '">' + (i + 1) + "</text>";
    flags.push({ iso: s.iso, x: 62, y: y + 39 });
    body += '<text x="102" y="' + (y + 30) + '" font-family="' + F
      + '" font-size="17" font-weight="700" fill="' + FG + '">' + esc2(s.name) + "</text>";
    const bits = [];
    // s.fare is the cached AVERAGE round trip (or a distance estimate), never
    // a minimum — so not "from". The price line is the pill's own framing with
    // the yardstick named (an image travels; "home" means nothing to its reader).
    if (s.fare != null) bits.push("avg flight ~" + shareMoney(s.fare) + (s.fareEst ? " (est.)" : ""));
    // s.pl comes from valueScores, already divided by the home anchor — dividing
    // by it again squared the anchor (DE→BG read 136, the guide card said 170).
    if (s.pl) bits.push("prices " + plPhrase(s.pl, A.name));
    body += '<text x="102" y="' + (y + 48) + '" font-family="' + F
      + '" font-size="11" fill="' + MUTE + '">' + esc2(bits.join("  ·  ")) + "</text>";
    body += '<rect x="' + (W - 30 - gw) + '" y="' + (y + 17) + '" width="' + gw
      + '" height="28" rx="8" fill="' + (RANK_GRADE_FILL[g] || "#55606b") + '"/>'
      + '<text x="' + (W - 30 - gw / 2) + '" y="' + (y + 37) + '" text-anchor="middle" font-family="' + F
      + '" font-size="16" font-weight="800" fill="' + RANK_GRADE_INK(g) + '">' + g + "</text>";
  });

  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H
    + '" viewBox="0 0 ' + W + " " + H + '">'
    + '<rect width="' + W + '" height="' + H + '" fill="' + BG + '"/>'
    + '<text x="24" y="44" font-family="' + F + '" font-size="26" font-weight="800" fill="' + FG
    + '">' + esc2("Where to travel in " + month) + "</text>"
    + '<text x="24" y="70" font-family="' + F + '" font-size="12.5" fill="' + MUTE
    + '">' + esc2("Top " + picks.length + " by value from " + originName
      + " — affordability, safety, weather and flights, graded A+ to F") + "</text>"
    + '<line x1="24" x2="' + (W - 24) + '" y1="' + (HEAD - 10) + '" y2="' + (HEAD - 10)
    + '" stroke="' + LINE + '" stroke-width="1"/>'
    + body
    + '<text x="24" y="' + (H - 22) + '" font-family="' + F + '" font-size="10.5" fill="' + DIM
    + '">' + esc2("wandergrade.com — free, no sign-up. World Bank PPP + live FX; safety per "
      + advSrcName(true) + "; cached fares.") + "</text>"
    + "</svg>";
  return { svg, W, H, flags };
}

async function downloadRankImage() {
  try {
    const { svg, W, H, flags } = buildRankShareSVG();
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
    const c = document.createElement("canvas");
    c.width = W * SHARE_SCALE; c.height = H * SHARE_SCALE;
    const ctx = c.getContext("2d");
    ctx.scale(SHARE_SCALE, SHARE_SCALE);
    ctx.fillStyle = "#101316"; ctx.fillRect(0, 0, W, H);
    ctx.drawImage(img, 0, 0, W, H);
    URL.revokeObjectURL(url);
    ctx.font = "24px -apple-system,system-ui,'Segoe UI',Arial,sans-serif";
    ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
    for (const f of flags) ctx.fillText(flagEmoji(f.iso), f.x, f.y);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const name = "wandergrade-top" + flags.length + ".png";
    const file = new File([blob], name, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: "Where to travel next" }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }   // cancelled: nothing; a real failure downloads
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    status("Ranking image downloaded — post it anywhere 🌍", "ok");
  } catch (e) {
    status("Could not build the image: " + e.message, "err");
  }
}

// The country card: every other surface exports, the guide didn't — and a
// guide is the natural "look where I'm going" share. Typographic on purpose:
// the hero photos are remote and would taint the canvas; the data IS the brand.
function buildGuideCardSVG(iso) {
  const name = countryName(iso);
  const W = 640, H = 356;
  const BG = "#101316", FG = "#f2f5f7", MUTE = "#9aa4ad", DIM = "#7d868f", LINE = "#242a30";
  const F = "Helvetica Neue, Helvetica, Arial, sans-serif";
  const esc2 = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const month = (parseInt(($("valueMonth") || {}).value, 10)) || curMonth();
  const A = plAnchor(originIso()), anchorPl = A.pl;   // US fallback when home has no price level

  let s = null;
  try { s = valueScores(iso, month, advisoryByIso(), buildFareContext(), anchorPl); } catch (e) {}
  const g = s ? grade(s.value) : null;

  const facts = [];
  const cl = climate && climate[iso];
  // Only 35 countries have hand-curated best months; the rest are the top
  // weather months, and the card says so, as the guide page does.
  if (cl && cl.best && cl.best.length)
    facts.push((cl.curated ? "📅  Best months: " : "📅  Best weather: ")
      + cl.best.map((m) => MON_ABBR[m - 1]).join(", "));
  // The price sentence the guide page shows, word for word (localPricesText):
  // "Your 100 ≈ 130 there" left open which 100 and which 130. Home nations
  // carry the UK's figure, and they, the Crown Dependencies and the Faroes
  // their parent's advisory, as the guide page does — each saying whose it
  // is ("for Denmark" keeps the longest source on the card).
  const plIso = GUIDE_PARENT[iso] || iso;
  const lp = localPricesText(plIso);
  if (lp) facts.push("💰  Local prices " + lp + (plIso !== iso ? " (" + parentWide(plIso) + ")" : ""));
  const meta = advisoryMetaByIso();
  const advPar = !meta[iso] && ADV_PARENT[iso] && meta[ADV_PARENT[iso]] ? ADV_PARENT[iso] : null;
  const adv = meta[iso] || (advPar && meta[advPar]);
  if (adv) facts.push("🛡️  " + (advSrcOf(adv) === "de" ? "" : "Level " + adv.level + " · ") + advLvlWords(adv)
    + "  (per " + (advViaShort(adv) || advSrcName(true))
    + (advPar ? ", for " + (advPar === "GB" ? "the UK" : countryName(advPar)) : "") + ")");
  const act = activities && activities[iso];
  if (act && act.days) facts.push("🧳  Worth " + act.days[0] + "–" + act.days[1] + " days on a first visit");

  const gw = g && g.length > 1 ? 64 : 54;
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H
    + '" viewBox="0 0 ' + W + " " + H + '">'
    + '<rect width="' + W + '" height="' + H + '" fill="' + BG + '"/>'
    + '<text x="96" y="72" font-family="' + F + '" font-size="34" font-weight="800" fill="' + FG + '">' + esc2(name) + "</text>"
    + '<text x="96" y="98" font-family="' + F + '" font-size="13" fill="' + MUTE + '">' + esc2(MONTHS[month - 1] + " · WanderGrade report card") + "</text>"
    + (g ? '<rect x="' + (W - 36 - gw) + '" y="34" width="' + gw + '" height="46" rx="10" fill="'
        + (RANK_GRADE_FILL[g] || "#55606b") + '"/>'
        + '<text x="' + (W - 36 - gw / 2) + '" y="66" text-anchor="middle" font-family="' + F
        + '" font-size="26" font-weight="800" fill="' + RANK_GRADE_INK(g) + '">' + g + "</text>" : "")
    + '<line x1="36" x2="' + (W - 36) + '" y1="122" y2="122" stroke="' + LINE + '"/>'
    + facts.map((t, i) => '<text x="36" y="' + (162 + i * 38) + '" font-family="' + F
        + '" font-size="16.5" fill="' + FG + '">' + esc2(t) + "</text>").join("")
    + '<text x="36" y="' + (H - 24) + '" font-family="' + F + '" font-size="11" fill="' + DIM
    // Only a real /guide/<slug> is printed: an ISO fallback (/guide/hk) 404s,
    // and the image outlives any fix. No slug = the bare domain.
    + '">' + esc2("wandergrade.com" + (ISO2SLUG && ISO2SLUG[iso] ? "/guide/" + ISO2SLUG[iso] : "")
    + " — sourced data, graded A+ to F, free") + "</text>"
    + "</svg>";
  return { svg, W, H, flags: [{ iso, x: 36, y: 76 }] };
}

async function downloadGuideCard(iso) {
  try {
    await Promise.all([ensureAdvisories().catch(() => {}), ensureSlugs()]);
    const { svg, W, H, flags } = buildGuideCardSVG(iso);
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
    const c = document.createElement("canvas");
    c.width = W * SHARE_SCALE; c.height = H * SHARE_SCALE;
    const ctx = c.getContext("2d");
    ctx.scale(SHARE_SCALE, SHARE_SCALE);
    ctx.fillStyle = "#101316"; ctx.fillRect(0, 0, W, H);
    ctx.drawImage(img, 0, 0, W, H);
    URL.revokeObjectURL(url);
    ctx.font = "44px -apple-system,system-ui,'Segoe UI',Arial,sans-serif";
    for (const f of flags) ctx.fillText(flagEmoji(f.iso), f.x, f.y);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const nameSlug = countryName(iso).toLowerCase().replace(/[^a-z]+/g, "-");
    const file = new File([blob], "wandergrade-" + nameSlug + ".png", { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: countryName(iso) }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }   // cancelled: nothing; a real failure downloads
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = file.name;
    a.click();
    status("Country card downloaded — post it anywhere 🌍", "ok");
  } catch (e) {
    status("Could not build the card: " + ((e && e.message) || "the image failed to render"), "err");
  }
}

async function downloadVisitedImage(orientation) {
  try {
    await ensureWorld();
    loadVisited(); loadWishlist();
    const { svg, W, H, flag } = buildVisitedShareSVG(orientation, SHARE_PINS);
    const blobUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = blobUrl; });
    const canvas = document.createElement("canvas");
    canvas.width = W * SHARE_SCALE; canvas.height = H * SHARE_SCALE;
    const ctx = canvas.getContext("2d");
    ctx.scale(SHARE_SCALE, SHARE_SCALE);
    ctx.drawImage(img, 0, 0, W, H);
    URL.revokeObjectURL(blobUrl);
    // Flag emojis of EVERY country you've been to (canvas fillText renders
    // emoji where the SVG path can't), alphabetical. The size shrinks until
    // all of them fit the reserved band — no more "+62" truncation.
    const flags = [...visited]
      .sort((a, b) => countryName(a).localeCompare(countryName(b)))
      .map((iso) => flagEmoji(iso));
    if (flags.length && flag) {
      ctx.textBaseline = "alphabetic";
      ctx.textAlign = "left";
      const { size, rows } = fitFlagRows(ctx, flags, W - 120, flag.maxH || 150, flag.size);
      ctx.font = size + "px -apple-system,system-ui,'Segoe UI',Arial,sans-serif";
      const rowH = Math.round(size * 1.35);
      // centering is done by hand (measure + offset): iOS Safari canvas has
      // been seen ignoring textAlign="center" here, anchoring rows at the
      // midpoint and clipping half the flags off the right edge
      rows.forEach((r, i) => {
        const x = flag.align === "center" ? flag.x - ctx.measureText(r).width / 2 : flag.x;
        ctx.fillText(r, x, flag.y + i * rowH);
      });
    }
    const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
    const name = orientation === "story" ? "wandergrade-wander-list-story.png" : "wandergrade-wander-list-map.png";
    const file = new File([blob], name, { type: "image/png" });
    // Native share sheet on phones (posts straight to socials); download elsewhere.
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: "My Wander List" }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }   // cancelled: nothing; a real failure downloads
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    status("Share image downloaded — post it anywhere 🌍", "ok");
  } catch (e) {
    status("Could not build share image: " + e.message, "err");
  }
}

$("shareBtn").addEventListener("click", shareCurrent);

// "Surprise me" — for visitors with no destination in mind, open a random
// well-known destination's guide. Leans into the decide-where-to-go angle.
const SURPRISE_POOL = ("JP TH IT FR ES GR PT VN ID IN MX PE EG IS KE AR MA TR ZA CR " +
  "NP LK KH JO GE CO PH MY TZ HR CZ NO CH NZ AU BR CL").split(" ");
// ---- guided picker ----------------------------------------------------------
// A tester opened the site and didn't know where to start: the filter row asks
// you to configure a query, which only works if you already know your criteria,
// while the promise is "decide for me". This asks three questions instead and
// sets the existing filters from the answers — the instant ranking underneath is
// untouched, so nobody who prefers filters loses anything. One screen rather
// than a multi-step wizard: fewer clicks, and it can't strand you halfway.
const GUIDE_PRIORITY = {
  money: { afford: "high", safe: "med",  wx: "low",  fly: "med"  },
  warm:  { afford: "med",  safe: "med",  wx: "high", fly: "low"  },
  safe:  { afford: "med",  safe: "high", wx: "med",  fly: "low"  },
  near:  { afford: "med",  safe: "med",  wx: "low",  fly: "high" },
};
const GUIDE_PRIORITY_LABEL = [
  ["money", "💰", "My money going furthest"],
  ["warm",  "🌤️", "Great weather"],
  ["safe",  "🛡️", "Feeling safe"],
  // The fly factor is fare vs the typical fare for the distance — a bargain
  // long-haul scores high — so the label promises a deal, not a short hop.
  ["near",  "✈️", "A good flight deal"],
];

function openGuidedPicker() {
  const monthSel = ensureMonthOptions();
  // No priority pre-picked ("Skip any of them" has to hold here too: a default
  // overwrote custom weights on every submit). A preset the current weights
  // already match shows as chosen, so the picker reflects state.
  const curPri = loadPriorities();
  let want = GUIDE_PRIORITY_LABEL.map(([k]) => k).find((k) =>
    Object.entries(GUIDE_PRIORITY[k]).every(([f, v]) => curPri[f] === v)) || null;
  const months = monthSel ? [...monthSel.options].map((o) => `<option value="${esc(o.value)}">${esc(o.textContent)}</option>`).join("") : "";
  const m = acctModal(`
    <h3 class="gqh">Let's narrow it down</h3>
    <p class="gqsub">Three questions. Skip any of them.</p>
    <div class="gqrow">
      <label class="gqlabel" for="gqMonth">When are you going?</label>
      <select id="gqMonth" class="gqinput">${months}</select>
    </div>
    <div class="gqrow">
      <label class="gqlabel" for="gqBudget">What's your total budget?</label>
      <span class="gqbudget">
        <input id="gqBudget" class="gqinput numin" type="number" min="0" step="100" placeholder="any" inputmode="numeric">
        <span class="gqfor">for</span>
        <input id="gqDays" class="gqinput numin" type="number" min="1" max="365" step="1" placeholder="10" inputmode="numeric">
        <span class="gqfor">days</span>
      </span>
    </div>
    <div class="gqrow">
      <span class="gqlabel">What matters most?</span>
      <div class="gqpick" id="gqPick">${GUIDE_PRIORITY_LABEL.map(([k, ic, lab]) =>
        `<button type="button" data-k="${k}" class="${k === want ? "active" : ""}" aria-pressed="${k === want}">${ic} ${esc(lab)}</button>`).join("")}</div>
    </div>
    <button id="gqGo" class="gqgo" type="button">Show me where to go →</button>
  `);
  if (!m) return;
  // Seed from whatever's already set, so this reflects rather than resets state.
  if (monthSel) m.querySelector("#gqMonth").value = monthSel.value;
  // Only a month the reader set here counts as chosen: the prefilled one is
  // the untouched default, and "Skip any of them" has to hold for it too.
  let monthTouched = false;
  m.querySelector("#gqMonth").addEventListener("change", () => { monthTouched = true; });
  const bt = $("budgetTotal"), bd = $("budgetDays");
  if (bt && bt.value) m.querySelector("#gqBudget").value = bt.value;
  if (bd && bd.value) m.querySelector("#gqDays").value = bd.value;

  m.querySelector("#gqPick").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    want = want === b.dataset.k ? null : b.dataset.k;   // tap again to skip
    m.querySelectorAll("#gqPick button").forEach((x) => {
      x.classList.toggle("active", x.dataset.k === want);
      x.setAttribute("aria-pressed", String(x.dataset.k === want));
    });
  });

  m.querySelector("#gqGo").onclick = () => {
    const mo = m.querySelector("#gqMonth").value;
    if (monthSel && mo && monthTouched) { monthSel.value = mo; monthSel.dispatchEvent(new Event("change", { bubbles: true })); }
    const budget = m.querySelector("#gqBudget").value.trim();
    const days = m.querySelector("#gqDays").value.trim();
    // Persisted under the budget inputs' own keys: setting .value fires no
    // input event, so a picker budget was lost on reload (and a cleared one
    // came back from the old saved value).
    for (const [el, key, v] of [[bt, "wg_budget", budget], [bd, "wg_budgetdays", days]]) {
      if (el) el.value = v;
      localStorage.setItem(key, v);
    }
    if (want && GUIDE_PRIORITY[want]) {
      loadPriorities();
      Object.assign(priorities, GUIDE_PRIORITY[want]);
      savePriorities();
      if (typeof buildWeightSliders === "function") buildWeightSliders();
    }
    m.close();
    if (loaded.value) renderValue();
    // Land the user on the answer, not back at the top of the page.
    // The picks, not #valueRows: that always exists, inside the closed fold.
    const rows = $("topCards");
    if (rows) rows.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "center" });
  };
}
if ($("guideMeBtn")) $("guideMeBtn").addEventListener("click", openGuidedPicker);

function surpriseMe() {
  ensureSlugs().then(() => {
    const pool = SURPRISE_POOL.filter((iso) => !climate || climate[iso]);
    const list = pool.length ? pool : SURPRISE_POOL;
    const winner = list[Math.floor(Math.random() * list.length)];
    if (reducedMotion()) { openGuideFor(winner, true); return; }
    spinGlobe(list, winner, () => openGuideFor(winner, true));
  });
}

// Same roulette, but across the CURRENT hidden-gems list (top offbeat value
// under the active filters) instead of the famous-destinations pool.
function surpriseGem() {
  const pool = lastGems.map((s) => s.iso);
  if (!pool.length) return;
  ensureSlugs().then(() => {
    const winner = pool[Math.floor(Math.random() * pool.length)];
    if (reducedMotion()) { openGuideFor(winner, true); return; }
    spinGlobe(pool, winner, () => openGuideFor(winner, true));
  });
}

// Real spinning Earth: orthographic projection of actual coastlines, drawn on
// a <canvas>. Land outlines are Natural Earth 110m (public domain), simplified
// to integer degrees and packed below as "lon,lat,lon,lat,..." rings joined
// by ";" (~8.5KB — regenerate with scripts/make_land_data.py).
const WORLD_LAND_ENC = "107,77,114,76,109,74,123,73,123,74,127,74,131,71,132,72,140,71,139,72,140,73,150,72,153,71,159,71,161,69,168,70,170,69,171,69,170,70,176,70,180,69,180,65,177,65,179,62,174,62,170,60,169,61,164,60,162,58,163,58,162,55,160,54,160,53,159,53,157,51,155,55,156,57,164,61,164,63,160,61,159,62,157,61,154,60,155,59,151,59,151,60,150,60,142,59,135,55,138,54,140,54,141,52,140,48,138,46,135,43,132,43,128,40,129,37,129,35,126,34,126,37,127,37,125,38,125,40,121,39,122,40,122,41,118,39,119,37,122,37,119,35,122,32,121,31,122,30,122,28,119,25,116,23,111,21,110,20,109,22,106,20,109,13,109,12,105,9,105,10,100,13,99,9,103,6,104,1,101,3,100,6,99,8,98,8,99,11,97,17,95,16,94,16,94,18,91,23,90,23,90,22,87,21,86,20,80,16,80,10,78,8,74,16,73,21,70,21,66,25,57,26,56,27,55,26,52,28,50,30,48,30,51,25,51,26,52,26,52,24,54,24,56,26,57,24,60,22,58,20,58,19,55,17,49,14,43,13,43,17,39,21,38,24,35,28,35,30,34,28,32,30,36,23,37,22,37,19,43,12,45,10,51,12,51,11,48,4,40,-3,39,-5,39,-6,40,-11,41,-15,39,-17,35,-20,36,-24,33,-26,32,-29,28,-33,26,-34,20,-35,18,-34,18,-32,15,-27,14,-22,12,-18,12,-16,14,-11,12,-5,9,-1,9,4,9,5,6,4,4,6,-2,5,-9,5,-12,7,-17,12,-18,15,-16,18,-17,22,-14,26,-10,30,-9,33,-6,36,-2,35,1,37,10,37,11,37,10,34,19,30,20,32,22,33,29,31,31,32,34,31,36,35,36,37,28,37,26,39,29,41,34,42,38,41,42,42,37,45,39,47,35,46,36,45,34,44,32,45,33,46,31,47,28,43,29,41,26,40,25,41,24,41,24,40,23,40,24,38,23,38,23,36,22,36,19,40,20,42,13,46,12,45,13,44,18,40,17,40,17,39,16,38,15,40,9,44,7,43,3,43,3,42,1,41,0,39,-2,37,-5,36,-7,37,-9,37,-9,43,-1,44,-1,46,-5,49,-2,49,-2,50,1,50,5,53,8,54,9,54,8,56,9,57,11,58,11,56,10,55,11,54,20,54,21,55,22,57,24,57,24,58,23,59,29,60,23,60,21,61,22,63,25,65,24,66,22,66,21,64,18,63,17,61,19,60,17,59,16,56,13,55,10,59,8,58,6,59,5,62,11,64,15,68,25,71,28,71,31,70,30,70,31,70,37,69,41,67,38,66,33,67,35,66,35,64,37,64,37,65,40,65,42,66,44,66,45,67,43,69,46,68,47,68,46,67,54,69,53,68,59,69,60,68,61,69,60,70,61,70,69,68,69,69,67,69,67,71,69,73,73,73,72,71,73,70,73,69,74,68,71,66,72,66,75,68,75,69,74,70,74,71,73,71,75,72,75,73,76,72,75,71,76,71,76,72,78,72,82,72,81,74,87,74,86,74,87,75,101,76,104,78,107,77;-59,-64,-62,-65,-63,-65,-62,-66,-66,-68,-62,-71,-61,-74,-71,-77,-77,-77,-74,-78,-78,-78,-78,-79,-58,-83,-50,-82,-43,-82,-29,-80,-30,-79,-36,-79,-36,-78,-18,-75,-16,-74,-15,-73,-10,-71,-7,-72,-7,-71,0,-72,8,-70,11,-71,13,-70,27,-70,32,-70,34,-69,39,-70,55,-66,61,-68,69,-68,70,-69,68,-70,69,-71,68,-72,70,-72,74,-70,78,-69,83,-67,87,-67,88,-66,90,-67,96,-67,100,-67,103,-66,106,-67,114,-66,120,-67,135,-66,135,-65,137,-67,145,-67,149,-68,154,-69,162,-71,171,-72,169,-74,166,-74,164,-76,165,-78,167,-79,162,-79,160,-81,169,-84,180,-85,180,-90,-180,-90,-180,-85,-179,-84,-170,-84,-158,-85,-143,-85,-154,-84,-153,-82,-157,-81,-151,-81,-146,-80,-155,-79,-158,-78,-158,-77,-151,-77,-146,-76,-146,-75,-135,-74,-121,-75,-114,-74,-112,-75,-108,-75,-100,-75,-103,-74,-104,-73,-96,-74,-90,-73,-89,-73,-81,-74,-80,-73,-75,-74,-67,-72,-69,-70,-67,-68,-68,-67,-63,-65,-57,-64,-59,-64;-91,69,-91,68,-89,69,-87,67,-86,69,-86,70,-83,70,-81,69,-82,68,-81,68,-83,66,-86,67,-87,65,-93,62,-95,59,-93,59,-92,57,-82,55,-82,53,-80,51,-79,53,-80,55,-77,57,-79,59,-77,60,-78,62,-74,62,-70,61,-69,59,-68,58,-65,60,-61,57,-62,56,-57,55,-56,53,-56,52,-60,50,-66,50,-71,47,-65,49,-64,49,-65,48,-64,46,-62,46,-61,47,-60,46,-65,44,-66,44,-64,45,-67,45,-71,43,-70,42,-74,41,-72,41,-74,41,-75,39,-76,39,-75,38,-76,37,-76,39,-76,38,-77,38,-76,36,-81,31,-80,27,-80,25,-82,26,-84,30,-89,30,-89,29,-90,29,-94,30,-97,28,-97,27,-98,22,-96,19,-94,18,-92,19,-91,19,-90,21,-87,22,-89,16,-83,15,-84,11,-81,9,-80,10,-77,9,-75,11,-72,12,-71,12,-72,11,-72,9,-71,11,-70,12,-68,11,-65,10,-62,11,-62,10,-57,6,-54,6,-51,4,-50,2,-50,0,-49,0,-49,-1,-48,-1,-45,-2,-45,-3,-40,-3,-36,-5,-35,-7,-35,-9,-39,-13,-39,-18,-41,-22,-48,-25,-49,-29,-54,-34,-56,-35,-58,-34,-57,-37,-59,-39,-62,-39,-63,-41,-65,-41,-65,-42,-63,-43,-65,-43,-66,-45,-67,-46,-68,-46,-66,-47,-66,-48,-69,-51,-68,-52,-71,-53,-71,-54,-75,-52,-76,-49,-74,-47,-76,-47,-74,-44,-73,-44,-73,-42,-74,-43,-73,-39,-74,-37,-71,-32,-70,-20,-71,-17,-76,-15,-80,-7,-81,-6,-81,-5,-80,-3,-81,-2,-81,-1,-77,4,-78,8,-80,9,-81,7,-86,10,-87,13,-91,14,-95,16,-97,16,-104,18,-105,20,-106,23,-112,29,-113,31,-115,32,-115,30,-109,23,-110,23,-112,25,-112,26,-115,28,-114,29,-117,33,-121,35,-124,40,-124,46,-125,48,-123,48,-123,47,-123,49,-127,51,-128,52,-129,53,-134,58,-147,61,-152,59,-151,61,-154,59,-153,59,-154,58,-158,56,-165,54,-158,58,-157,59,-162,59,-162,60,-164,60,-166,62,-165,63,-161,64,-162,64,-161,65,-165,64,-168,66,-164,67,-162,66,-167,68,-157,71,-137,69,-128,70,-126,69,-124,70,-124,69,-121,70,-114,68,-115,68,-109,67,-108,68,-109,68,-108,69,-106,69,-101,68,-98,68,-98,69,-96,68,-96,67,-94,69,-96,70,-96,71,-95,72,-92,70,-91,69;144,-14,145,-15,146,-19,149,-20,153,-26,153,-32,150,-37,146,-39,145,-38,144,-39,141,-38,140,-36,138,-36,138,-34,137,-35,138,-33,136,-35,134,-33,131,-31,126,-32,124,-34,120,-34,118,-35,115,-34,116,-32,113,-26,114,-26,113,-24,114,-22,114,-23,117,-21,121,-20,123,-16,124,-17,126,-14,127,-14,130,-15,131,-13,133,-12,132,-11,135,-12,136,-12,137,-12,136,-15,140,-18,141,-16,143,-11,144,-14;-27,84,-21,83,-32,82,-22,82,-23,81,-16,82,-12,81,-20,80,-18,80,-20,79,-20,78,-18,77,-22,77,-20,76,-20,75,-21,75,-19,74,-24,73,-22,72,-25,72,-22,71,-26,71,-25,71,-26,70,-22,70,-40,65,-43,63,-42,62,-43,60,-48,61,-52,64,-54,67,-51,70,-55,70,-54,71,-51,71,-56,72,-55,73,-59,76,-69,76,-71,77,-67,77,-73,78,-66,79,-68,80,-62,81,-63,82,-50,82,-45,82,-47,83,-39,84,-27,84;-87,73,-86,73,-82,74,-81,73,-81,72,-78,73,-74,71,-72,72,-67,69,-69,69,-62,67,-64,65,-68,66,-65,63,-69,64,-66,62,-75,65,-78,64,-79,65,-78,65,-74,65,-73,68,-79,70,-85,70,-90,71,-89,73,-86,74,-87,73;-68,83,-62,83,-68,82,-65,82,-71,80,-77,79,-75,79,-80,77,-78,77,-81,76,-89,76,-88,77,-88,78,-85,78,-88,78,-85,79,-87,80,-82,80,-88,81,-92,82,-79,83,-68,83;134,-1,134,-3,135,-3,138,-2,145,-4,148,-6,147,-7,151,-11,148,-10,145,-8,143,-9,139,-8,138,-8,139,-7,138,-5,134,-4,133,-4,132,-3,134,-2,131,-1,132,0,134,-1;118,2,119,1,118,1,116,-4,110,-3,109,0,110,2,111,2,111,3,113,3,117,7,119,5,117,3,118,2;50,-14,50,-16,47,-25,45,-26,44,-25,43,-22,44,-20,44,-16,48,-15,49,-12,50,-14;-114,73,-115,73,-110,73,-108,72,-108,73,-107,73,-104,71,-101,70,-103,70,-102,69,-113,69,-117,70,-112,70,-118,71,-116,71,-119,72,-118,73,-114,73;-3,59,-4,58,-2,58,-3,56,2,53,1,51,-5,50,-6,50,-3,51,-5,52,-4,52,-5,53,-3,54,-5,55,-5,56,-6,55,-6,57,-5,59,-3,59;106,-6,103,-4,95,5,97,5,104,0,103,-1,106,-3,106,-6;141,37,140,35,137,35,136,33,135,35,131,34,132,33,131,31,130,31,130,32,129,33,133,35,136,36,137,37,139,38,140,41,141,41,142,39,141,37;-175,67,-172,67,-170,66,-173,65,-173,64,-178,65,-179,66,-180,66,-180,65,-180,69,-175,67;58,71,54,71,51,72,56,75,61,76,69,77,58,74,55,72,58,71;-45,-78,-44,-78,-43,-80,-50,-81,-54,-81,-49,-78,-45,-78;-15,66,-14,65,-19,63,-23,64,-22,64,-24,65,-22,65,-24,66,-22,66,-21,66,-15,66;18,80,22,79,16,77,10,80,18,80;-87,80,-86,79,-91,78,-97,80,-92,81,-87,80;125,1,124,0,120,0,121,-1,123,-1,122,-2,123,-5,122,-5,123,-4,121,-5,121,-3,120,-3,120,-6,119,-5,119,-3,120,1,121,1,125,1;173,-41,174,-41,173,-44,171,-44,169,-47,167,-46,167,-45,173,-41;-120,71,-123,71,-126,72,-124,74,-125,74,-116,73,-119,73,-120,71;-95,77,-89,76,-81,76,-80,75,-90,75,-97,77,-95,77;-68,-71,-69,-72,-71,-73,-75,-72,-72,-71,-72,-70,-70,-69,-68,-71;175,-36,177,-38,179,-38,175,-42,175,-40,174,-40,175,-37,173,-35,175,-36;-56,51,-57,50,-53,49,-54,49,-53,49,-53,48,-53,47,-54,47,-54,48,-55,47,-56,48,-59,48,-57,51,-55,52,-56,51;100,79,95,79,91,80,96,81,100,80,100,79;144,51,145,49,143,49,143,48,144,46,143,47,142,46,142,52,142,54,144,51;-108,76,-106,75,-112,74,-114,75,-112,75,-118,75,-115,76,-109,75,-110,76,-108,76;121,19,122,18,123,17,122,14,124,14,124,13,121,14,121,15,120,15,120,16,121,19;144,44,145,44,146,43,143,42,142,43,141,42,140,42,140,43,141,43,142,46,144,44;-100,74,-97,74,-98,73,-97,73,-97,72,-99,71,-102,73,-100,73,-102,73,-100,74;109,-7,111,-6,116,-8,105,-7,106,-6,109,-7;126,8,127,7,126,6,126,7,125,7,125,6,124,6,124,8,122,7,123,9,125,9,125,10,126,8;-7,52,-10,52,-9,53,-10,54,-7,55,-6,55,-7,52;-85,66,-80,64,-87,64,-86,66,-85,66;145,-41,148,-41,148,-43,146,-44,145,-41;145,76,144,75,139,75,137,75,139,76,145,76;-68,-54,-65,-55,-69,-55,-75,-53,-71,-54,-69,-53,-68,-54;-73,20,-68,19,-71,18,-74,18,-72,19,-73,20;-80,23,-74,20,-78,20,-77,20,-79,22,-82,23,-85,22,-82,23,-80,23;-93,73,-95,72,-96,73,-95,74,-91,74,-93,73;-98,77,-98,76,-98,75,-103,76,-98,77;25,80,27,80,23,79,17,80,25,80;-116,78,-117,77,-123,76,-116,78";

// Flat equirectangular land mask, rasterized once from the packed rings.
// The sphere face samples this per pixel, so horizon clipping never happens
// in polygon space — any rotation is correct by construction.
const LM_W = 2048, LM_H = 1024;   // LM_W must stay a power of two (wrap via &)
let _landMask = null;
function landMask() {
  if (_landMask) return _landMask;
  const cv = document.createElement("canvas");
  cv.width = LM_W;
  cv.height = LM_H;
  const c = cv.getContext("2d", { willReadFrequently: true });
  c.fillStyle = "#fff";
  for (const s of WORLD_LAND_ENC.split(";")) {
    const v = s.split(",");
    c.beginPath();
    for (let i = 0; i < v.length; i += 2) {
      const X = (+v[i] + 180) / 360 * LM_W;
      const Y = (90 - +v[i + 1]) / 180 * LM_H;
      i ? c.lineTo(X, Y) : c.moveTo(X, Y);
    }
    c.closePath();
    c.fill();
  }
  const d = c.getImageData(0, 0, LM_W, LM_H).data;
  const m = new Uint8Array(LM_W * LM_H);
  for (let i = 0; i < m.length; i++) m[i] = d[i * 4 + 3] > 127 ? 1 : 0;
  _landMask = m;
  return m;
}

// Everything rotation-independent, precomputed once per device-pixel size:
// which pixels are on the disc, where each one lands in the mask (up to a
// longitude shift), and its pre-shaded land/ocean colors. Per frame each
// pixel is then just one add + one mask lookup.
let _sph = null;
function sphereCache(dev) {
  if (_sph && _sph.dev === dev) return _sph;
  const Cd = dev / 2, Rd = dev * 0.42;
  const tilt = 16 * Math.PI / 180;
  const st = Math.sin(tilt), ct = Math.cos(tilt);
  let lx = -0.42, ly = 0.55, lz = 0.72;              // light: upper-left, front
  const lm = Math.hypot(lx, ly, lz);
  lx /= lm; ly /= lm; lz /= lm;
  const pix = [], ixb = [], row = [], cols = [];
  const shade = (base, lum) => Math.min(255, Math.round(base * lum));
  for (let py = 0; py < dev; py++) {
    for (let px = 0; px < dev; px++) {
      const x = (px - Cd) / Rd, y = (Cd - py) / Rd;
      const r2 = x * x + y * y;
      if (r2 > 1) continue;
      const z = Math.sqrt(1 - r2);
      const sphi = ct * y + st * z;                  // undo the axial tilt
      const dl = Math.atan2(x, ct * z - st * y);     // longitude offset from rot
      const phi = Math.asin(Math.max(-1, Math.min(1, sphi)));
      const iy = Math.min(LM_H - 1, Math.max(0, Math.round((0.5 - phi / Math.PI) * LM_H)));
      const lum = 0.62 + 0.42 * Math.max(0, lx * x + ly * y + lz * z);
      pix.push(py * dev + px);
      ixb.push(Math.round((dl / (2 * Math.PI) + 0.5) * LM_W) & (LM_W - 1));
      row.push(iy * LM_W);
      cols.push(shade(96, lum), shade(212, lum), shade(138, lum),   // land
                shade(38, lum), shade(122, lum), shade(202, lum));  // ocean
    }
  }
  const cv = document.createElement("canvas");
  cv.width = cv.height = dev;
  const c = cv.getContext("2d");
  _sph = {
    dev,
    n: pix.length,
    pix: new Uint32Array(pix),
    ixb: new Uint16Array(ixb),
    row: new Uint32Array(row),
    cols: new Uint8Array(cols),
    cv, c,
    img: c.createImageData(dev, dev),
  };
  return _sph;
}

// One frame of the globe at rotation `rot` (radians of longitude). Ocean +
// atmosphere + graticule + sunlit landmasses + limb shading + gloss.
function drawGlobe(ctx, S, rot) {
  const C = S / 2, R = S * 0.42;
  const D = Math.PI / 180, tilt = 16 * D;             // slight northern tilt
  const st = Math.sin(tilt), ct = Math.cos(tilt);
  const TAU = Math.PI * 2;
  ctx.clearRect(0, 0, S, S);

  // Orthographic projection; returns [x, y, cosc] in unit-sphere coords.
  // cosc > 0 → point faces the viewer.
  const proj = (lam, sphi, cphi) => {
    const cdl = Math.cos(lam - rot), sdl = Math.sin(lam - rot);
    return [cphi * sdl, ct * sphi - st * cphi * cdl, st * sphi + ct * cphi * cdl];
  };

  // atmosphere halo
  let g = ctx.createRadialGradient(C, C, R * 0.9, C, C, R * 1.2);
  g.addColorStop(0, "rgba(120,190,255,.33)");
  g.addColorStop(1, "rgba(120,190,255,0)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(C, C, R * 1.2, 0, TAU); ctx.fill();

  // sphere face: per-pixel land/ocean from the equirect mask
  const dpr = ctx.canvas.width / S;
  const sc = sphereCache(Math.round(S * dpr));
  const mask = landMask();
  const d = sc.img.data;
  const rotPx = Math.round(((rot / TAU) % 1 + 1) * LM_W);
  for (let k = 0; k < sc.n; k++) {
    const ix = (sc.ixb[k] + rotPx) & (LM_W - 1);
    const o = sc.pix[k] * 4;
    const cb = k * 6 + (mask[sc.row[k] + ix] ? 0 : 3);
    d[o] = sc.cols[cb];
    d[o + 1] = sc.cols[cb + 1];
    d[o + 2] = sc.cols[cb + 2];
    d[o + 3] = 255;
  }
  sc.c.putImageData(sc.img, 0, 0);
  ctx.drawImage(sc.cv, 0, 0, S, S);

  ctx.save();
  ctx.beginPath(); ctx.arc(C, C, R, 0, TAU); ctx.clip();

  // graticule (30° grid), only the front hemisphere
  ctx.strokeStyle = "rgba(255,255,255,.14)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  const gseg = (lo, la, pen) => {
    const p = proj(lo * D, Math.sin(la * D), Math.cos(la * D));
    if (p[2] <= 0) return false;
    const px = C + p[0] * R, py = C - p[1] * R;
    pen ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    return true;
  };
  for (let lo = -180; lo < 180; lo += 30) {
    let pen = false;
    for (let la = -85; la <= 85; la += 5) pen = gseg(lo, la, pen);
  }
  for (let la = -60; la <= 60; la += 30) {
    let pen = false;
    for (let lo = -180; lo <= 180; lo += 5) pen = gseg(lo, la, pen);
  }
  ctx.stroke();

  // limb darkening (sphere falloff toward the edge)
  g = ctx.createRadialGradient(C, C, R * 0.55, C, C, R);
  g.addColorStop(0, "rgba(2,16,38,0)");
  g.addColorStop(0.8, "rgba(2,16,38,.06)");
  g.addColorStop(1, "rgba(2,16,38,.5)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(C, C, R, 0, TAU); ctx.fill();
  ctx.restore();

  // gloss + rim light
  ctx.beginPath();
  ctx.ellipse(C - R * 0.38, C - R * 0.48, R * 0.42, R * 0.2, -0.5, 0, TAU);
  ctx.fillStyle = "rgba(255,255,255,.15)";
  ctx.fill();
  ctx.beginPath(); ctx.arc(C, C, R, 0, TAU);
  ctx.strokeStyle = "rgba(195,228,255,.7)";
  ctx.lineWidth = 1.6;
  ctx.stroke();
}

// Mount the canvas inside `host` and spin: fast at first, exponentially easing
// to a slow drift (mirrors the flag reel's deceleration). Stops itself when the
// overlay leaves the DOM.
function startGlobe(host) {
  const S = 190;
  const canvas = document.createElement("canvas");
  canvas.className = "globecanvas";
  canvas.setAttribute("aria-hidden", "true");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = S * dpr;
  canvas.height = S * dpr;
  host.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  let rot = Math.random() * Math.PI * 2;
  let vel = 4.4;                                 // rad/s — a brisk ~0.7 rev/s
  let last = performance.now();
  (function frame(now) {
    if (!canvas.isConnected) return;             // overlay was removed
    const dt = Math.min(now - last, 50) / 1000;
    last = now;
    rot += vel * dt;
    vel = Math.max(vel * Math.pow(0.42, dt), 0.3);  // decelerate, keep drifting
    drawGlobe(ctx, S, rot);
    requestAnimationFrame(frame);
  })(last);
}

// ---- spin sound effects ------------------------------------------------------
// Synthesized with the Web Audio API — no audio files, so nothing to license,
// download, or get flagged. Prize-wheel grammar: a whoosh on launch, clicker
// ticks that drop in pitch as the reel slows, and a two-note chime on landing.
// The spin always starts from a user click, which satisfies autoplay policies.
let _sfx = null;
function sfxCtx() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!_sfx) _sfx = new AC();
  if (_sfx.state === "suspended") _sfx.resume();
  return _sfx;
}
// One reel click; t = 0..1 spin progress (pitch falls as the wheel slows).
function sfxTick(t) {
  const ac = sfxCtx();
  if (!ac) return;
  const o = ac.createOscillator(), g = ac.createGain();
  o.type = "triangle";
  o.frequency.value = 1500 - 650 * t;
  g.gain.setValueAtTime(0.05, ac.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.05);
  o.connect(g).connect(ac.destination);
  o.start();
  o.stop(ac.currentTime + 0.06);
}
// Launch whoosh: fading noise through a bandpass sweeping downward.
function sfxWhoosh(dur) {
  const ac = sfxCtx();
  if (!ac) return;
  const n = Math.floor(ac.sampleRate * dur);
  const buf = ac.createBuffer(1, n, ac.sampleRate);
  const d = buf.getChannelData(0);
  for (let k = 0; k < n; k++) d[k] = (Math.random() * 2 - 1) * (1 - k / n);
  const src = ac.createBufferSource();
  src.buffer = buf;
  const f = ac.createBiquadFilter();
  f.type = "bandpass";
  f.Q.value = 0.8;
  f.frequency.setValueAtTime(900, ac.currentTime);
  f.frequency.exponentialRampToValueAtTime(170, ac.currentTime + dur);
  const g = ac.createGain();
  g.gain.setValueAtTime(0.1, ac.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + dur);
  src.connect(f).connect(g).connect(ac.destination);
  src.start();
}
// Landing chime: E5 then B5, soft attack, long decay — "you've arrived".
function sfxLand() {
  const ac = sfxCtx();
  if (!ac) return;
  [[659.25, 0], [987.77, 0.09]].forEach(([hz, dt]) => {
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = "sine";
    o.frequency.value = hz;
    const t0 = ac.currentTime + dt;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(0.13, t0 + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.7);
    o.connect(g).connect(ac.destination);
    o.start(t0);
    o.stop(t0 + 0.75);
  });
}

// ---- soundtrack --------------------------------------------------------------
// "My Love" by SoundEden — melodic afro/deep house, from Pixabay (track 343626;
// Pixabay Content License: free for commercial use, no attribution required).
// Served from /music.mp3 (~6 MB, 3:20, loops); the file is only fetched when
// the music is actually turned on, so it never touches first paint. Strictly
// opt-in via the 🎵 header button; the choice persists in localStorage.
// Returning visitors with music on get it resumed on their first interaction
// (autoplay policy). This replaced a generative Web Audio engine — a real
// track sounds better than oscillators ever did.
const MUSIC_KEY = "wg_music";
const MUSIC_SRC = "/music.mp3";
// Volumes are set from measurement, not feel. The track's body sits at ~-10.5
// dBFS RMS (a loud modern master); listeners calibrate their system volume to
// "normal music" ≈ -14 LUFS (every streaming service normalizes there), and
// background music convention is 8-12 dB under that foreground anchor. Cruise
// at 0.26 (-11.7 dB) puts the body at ~-22 effective — clearly music, doesn't
// fight reading. The track's first ~20s (and its outro, = the loop seam) are
// ~7 dB quieter than the body, which at cruise volume would make the first
// click sound broken — so those stretches play at a higher volume and glide
// down as the song's own crescendo arrives.
// Doug's ear checks (2026-07-21): two "lower" passes from the measured
// baseline of 0.26/0.5 — each ~2.4 dB down, same intro/cruise ratio both times.
const MUSIC_VOL = 0.15;           // cruise: track body ≈ -27 dB effective
const MUSIC_VOL_INTRO = 0.29;     // first ~15s / loop seam: keeps the quiet intro audible
const MUSIC_INTRO_END = 15;       // seconds; the song reaches cruise loudness ~20s
let _music = null;                // HTMLAudioElement, created on first start
let _musicFade = null;
// iOS ignores .volume (it always reads 1), so every fade and the intro/cruise
// levels did nothing there. Where the element's volume won't stick, the audio
// runs through a Web Audio gain node instead; with neither, it plays at the
// device volume and the fades are skipped rather than spun forever.
let _musicAC = null, _musicGain = null, _musicVolOK = true;
function _musicVol() { return _musicGain ? _musicGain.gain.value : _music.volume; }
function _setMusicVol(v) {
  if (_musicGain) _musicGain.gain.value = v; else _music.volume = v;
}
function _musicRouteVolume() {
  _music.volume = 0.5;
  if (Math.abs(_music.volume - 0.5) < 0.01) return;
  _music.volume = 1;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error("no Web Audio");
    _musicAC = new AC();
    _musicGain = _musicAC.createGain();
    _musicGain.gain.value = 0;
    _musicAC.createMediaElementSource(_music).connect(_musicGain);
    _musicGain.connect(_musicAC.destination);
    // Web Audio defaults to iOS's ambient session, which the mute switch
    // silences; this was an explicit tap on 🎵, so play like media does.
    try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}
  } catch (e) {
    _musicAC = null; _musicGain = null; _musicVolOK = false;
  }
}

// Linear volume fade so starts/stops are a door opening, not a light switch.
function _fadeMusic(to, ms, done) {
  if (_musicFade) clearInterval(_musicFade);
  _musicFade = null;
  if (!_music) return;
  if (!_musicVolOK) { if (done) done(); return; }
  const from = _musicVol(), t0 = Date.now();
  _musicFade = setInterval(() => {
    const k = Math.min(1, (Date.now() - t0) / ms);
    _setMusicVol(from + (to - from) * k);
    if (k === 1) {
      clearInterval(_musicFade);
      _musicFade = null;
      if (done) done();
    }
  }, 40);
}

function musicOn() { return !!(_music && !_music.paused); }

// The right volume for wherever the playhead is: lifted through the quiet
// intro (which the loop seam replays every 3:20), cruise everywhere else.
function _musicWantVol() {
  return _music && _music.currentTime < MUSIC_INTRO_END ? MUSIC_VOL_INTRO : MUSIC_VOL;
}

function startMusic() {
  if (!_music) {
    _music = new Audio(MUSIC_SRC);
    _music.loop = true;
    _music.preload = "auto";
    // In the DOM (renders nothing without `controls`) so devtools can see it.
    _music.style.display = "none";
    document.body.appendChild(_music);
    // Loudness rider: when the playhead crosses the intro boundary — or wraps
    // back over it at the loop seam — glide to the new target over 6s. The
    // glide runs against the song's own crescendo/outro, so the perceived
    // level stays steady. Never fights an explicit start/stop fade (those own
    // _musicFade while active, and a paused element fires no timeupdate).
    _music.addEventListener("timeupdate", () => {
      if (_musicFade || !musicOn() || !_musicVolOK) return;
      const want = _musicWantVol();
      if (Math.abs(_musicVol() - want) > 0.01) _fadeMusic(want, 6000);
    });
    // A file that can't load or decode can't play: say so on the button
    // instead of showing "on" over silence.
    _music.addEventListener("error", () => {
      if (_musicFade) { clearInterval(_musicFade); _musicFade = null; }
      setMusicBtn(false);
    });
    _musicRouteVolume();
  }
  if (musicOn()) return;
  if (_musicAC && _musicAC.state !== "running") _musicAC.resume().catch(() => {});
  _setMusicVol(0);
  const p = _music.play();
  // An autoplay block (no user gesture yet) lands here and stays armed — the
  // first-interaction arm at the bottom retries. A real failure turns the
  // button off; AbortError is just a pause() racing this play().
  if (p && p.catch) p.catch((err) => {
    const n = err && err.name;
    if (n !== "NotAllowedError" && n !== "AbortError" && !musicOn()) setMusicBtn(false);
  });
  _fadeMusic(_musicWantVol(), 900);
}

function stopMusic() {
  if (!musicOn()) return;
  _fadeMusic(0, 700, () => { if (_music) _music.pause(); });
}

function setMusicBtn(on) {
  const b = $("musicBtn");
  if (!b) return;
  b.setAttribute("aria-pressed", on ? "true" : "false");
  b.classList.toggle("playing", on);
  b.title = on ? "Soundtrack — on (click to turn off)"
              : "Soundtrack — off (click to turn on)";
}
function toggleMusic(on) {
  try { localStorage.setItem(MUSIC_KEY, on ? "1" : "0"); } catch (e) {}
  setMusicBtn(on);
  if (on) startMusic(); else stopMusic();
}
if ($("musicBtn")) {
  // Toggle off the button's SHOWN state, not the engine's: with a saved "on"
  // preference the button can display on before audio has permission to start,
  // and keying off _music made the first click a no-op there.
  $("musicBtn").addEventListener("click", () => {
    const showingOn = $("musicBtn").getAttribute("aria-pressed") === "true";
    toggleMusic(!showingOn);
  });
  let saved = null;
  try { saved = localStorage.getItem(MUSIC_KEY); } catch (e) {}
  if (saved === "1") {
    setMusicBtn(true);
    // Browsers require a user gesture before audio: resume on the first one.
    // Skip when the gesture is the music button itself — its click handler
    // owns the decision; resuming here made that first click toggle straight
    // back off (pointerdown fires before click).
    // pointerup too: a touch pointerdown doesn't count as a gesture for audio
    // (iOS refused the play and the one-shot arm was spent). Stays armed until
    // the music is actually playing or the button takes over.
    const ARM = ["pointerdown", "pointerup", "keydown"];
    const disarm = () => ARM.forEach((t) => document.removeEventListener(t, arm));
    const arm = (e) => {
      if (e.target && e.target.closest && e.target.closest("#musicBtn")) { disarm(); return; }
      let want = false;
      try { want = localStorage.getItem(MUSIC_KEY) === "1"; } catch (err) {}
      // The button showing off means a load/decode error (or a real play()
      // failure) turned it off: stop retrying play() on every click and key.
      const shownOn = $("musicBtn").getAttribute("aria-pressed") === "true";
      if (musicOn() || !want || !shownOn) { disarm(); return; }
      startMusic();
    };
    ARM.forEach((t) => document.addEventListener(t, arm));
  }
  // First-visit nudge: visitors who have never touched the toggle get a soft
  // ring that breathes a few times on the 🎵 button — deliberate discovery,
  // since sound before a gesture is (rightly) impossible. One visit only, and
  // any press on the button ends it early.
  let hinted = null;
  try { hinted = localStorage.getItem(MUSIC_KEY + "_hint"); } catch (e) {}
  if (saved === null && !hinted) {
    $("musicBtn").classList.add("hint");
    try { localStorage.setItem(MUSIC_KEY + "_hint", "1"); } catch (e) {}
    $("musicBtn").addEventListener("pointerdown",
      () => $("musicBtn").classList.remove("hint"), { once: true });
  }
}

// "Surprise me" roulette: spinning globe + a flag/name reel that eases to a stop
// on `winner`, then runs done(). Click anywhere to skip to the result.
function spinGlobe(list, winner, done) {
  const overlay = document.createElement("div");
  overlay.className = "spinover";
  overlay.innerHTML = '<div class="spinbox"><div class="globe"></div>'
    + '<div class="spinflag">🌍</div><div class="spinname">Spinning the globe…</div>'
    + '<div class="spinhint">tap to skip</div></div>';
  document.body.appendChild(overlay);
  startGlobe(overlay.querySelector(".globe"));
  sfxWhoosh(2.8);
  requestAnimationFrame(() => overlay.classList.add("show"));
  const flagEl = overlay.querySelector(".spinflag");
  const nameEl = overlay.querySelector(".spinname");

  const reel = [];
  for (let k = 0; k < 20; k++) reel.push(list[Math.floor(Math.random() * list.length)]);
  reel.push(winner);

  let i = 0, timer = null, stopped = false;
  function finish() {
    if (stopped) return;
    stopped = true;
    clearTimeout(timer);
    sfxLand();
    flagEl.textContent = flagEmoji(winner);
    nameEl.innerHTML = "✨ You’re going to <b>" + esc(countryName(winner)) + "</b>";
    overlay.classList.add("landed");
    setTimeout(() => {
      overlay.classList.remove("show");
      setTimeout(() => { overlay.remove(); done(); }, 340);
    }, 900);
  }
  function tick() {
    if (stopped) return;
    const iso = reel[i];
    flagEl.textContent = flagEmoji(iso);
    nameEl.textContent = countryName(iso);
    if (++i >= reel.length) { finish(); return; }
    const t = i / reel.length;
    sfxTick(t);
    timer = setTimeout(tick, 45 + t * t * 340);   // ease-out deceleration
  }
  overlay.addEventListener("click", finish);
  tick();
}
if ($("surpriseBtn")) $("surpriseBtn").addEventListener("click", surpriseMe);
// Lives inside the <summary>: stop the click from also toggling the fold.
if ($("gemSurprise")) $("gemSurprise").addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  surpriseGem();
});
// One share format: vertical/story — these get shared from phones, where
// portrait is what Stories, TikTok, and messaging previews all want.
$("visitedImage").addEventListener("click", () => downloadVisitedImage("story"));
// The Trip tab's own plan button: always the basket, never the algorithmic
// shortlist. "Plan these with AI" in Top Picks still plans what is on screen
// there, which is the ranked list — two buttons, two clearly different subjects.
if ($("tripPlanBtn")) $("tripPlanBtn").addEventListener("click", async () => {
  if (!loadTrip().size) { status("Add a country to your trip first — open any country and hit “Add to my trip”.", "err"); return; }
  // Each country's visa line: a US passport reads visa.json, which Top Picks
  // and the guide load — a Trip landing has neither.
  if (guidePassport() !== "US") await ensureVisaMatrix().catch(() => {});
  else await ensureVisa().catch(() => {});
  // Centroids (world.geojson) and price levels (ppp.json) too: Top Picks loaded
  // both, and without them a Trip landing's prompt lost every country's
  // "approx 15°N, 101°E" and "prices ~71% cheaper" lines.
  await Promise.all([ensureWorld().catch(() => {}), ensurePPP().catch(() => {})]);
  renderAIPanel($("tripPanel"), buildTripAIPrompt());
});


// Share buttons for the data maps. Titles state the finding, not the product —
// "What US$100 actually buys" is what travelled on Reddit; "WanderGrade cost of
// living map" is not. The footer carries the caveat because these get reposted
// without their captions.
if ($("fxShare")) $("fxShare").addEventListener("click", () => {
  const base = homeBase || "USD";
  const dp = dimPicksFromDom("map");
  downloadMapImage("map", {
    picks: dp.picks, picksTitle: dp.title,
    title: "Where the " + (base === "USD" ? "dollar" : base) + " is strong right now",
    // Nominal, like the map it prints: in a high-inflation country a stronger
    // rate is not more buying power, so no "goes further" claim travels with it.
    sub: "Each currency vs its own 1-year average against " + base + ". Greener = "
       + (base === "USD" ? "dollar" : base) + " stronger than usual (nominal — in high-inflation"
       + " countries prices can rise faster than the currency falls).",
    gradient: ["#b00020", "#eef0f1", "#0a7d28"],
    leftLabel: "Weaker", rightLabel: "Stronger",
    swatches: [{ c: "#bcd0e6", label: base + "-linked" }, { c: NODATA, label: "no data" }],
    footer: "Exchange-rate strength only — not prices. Pair with the cost-of-living map for what money buys. wandergrade.com",
    filename: "wandergrade-currency-strength.png",
  });
});
// The cost map is coloured against the From country and its picks are in that
// country's money, so the headline is too — built at click time, from the same
// origin (and the same no-price-level fallback to the US) the map is drawn with.
if ($("affShare")) $("affShare").addEventListener("click", () => {
  const vo = $("valueOrigin");
  let iso = vo && /^[A-Z]{2}$/.test(vo.value) ? vo.value : travelOrigin();
  if (!priceLevel(iso)) iso = "US";
  const cur = CUR_BY_ISO[iso] || "USD";
  const sym = cur === "USD" ? "US$" : cur + " ";
  const where = iso === "US" ? "the US" : countryName(iso);
  downloadMapImage("affMap", {
    picks: dimPicksFromDom("affMap").picks, picksTitle: dimPicksFromDom("affMap").title,
    title: "What " + sym + "100 actually buys around the world",
    sub: "Local prices vs " + where + " — greener = your " + sym
       + "100 goes further. World Bank PPP divided by today's market exchange rate.",
    gradient: ["#b00020", "#eef0f1", "#0a7d28"],
    leftLabel: "Pricey", rightLabel: "Cheap",
    swatches: [{ c: NODATA, label: "no data" }],
    footer: "National averages for residents — tourist areas and rent paid by foreigners run well above these. wandergrade.com",
    filename: "wandergrade-cost-of-living.png",
  });
});
if ($("advShare")) $("advShare").addEventListener("click", () => downloadMapImage("advMap", {
  picks: dimPicksFromDom("advMap").picks, picksTitle: dimPicksFromDom("advMap").title,
  title: "Where governments say it's safe to travel",
  // Read at click time: the map shows whichever government the picker holds,
  // in its own words — Germany's three calls, not a 1–4 it doesn't give.
  sub: advisories && advisories.source === "de"
    ? advSrcName() + ": a travel warning, one for some regions, or none"
      + (advisories.filled ? "; gaps filled by other governments, 1–4." : ".")
    : advSrcName() + " advisory levels, 1 (" + (ADV_LVL_WORDS[(advisories && advisories.source) || "us"] || ADV_LVL_WORDS.us)[0].toLowerCase()
      + ") to 4 (" + (ADV_LVL_WORDS[(advisories && advisories.source) || "us"] || ADV_LVL_WORDS.us)[3].toLowerCase() + ")"
      + (advisories && advisories.filled ? "; gaps filled by other governments." : "."),
  swatches: (advisories && advisories.source === "de"
    ? [{ c: DE_NONE_FILL, label: "No warning" }, { c: LVL_MAP_COLOR[2], label: "Some regions" },
       { c: LVL_MAP_COLOR[4], label: "Travel warning" }]
    : [{ c: LVL_MAP_COLOR[1], label: "Level 1" }, { c: LVL_MAP_COLOR[2], label: "Level 2" },
       { c: LVL_MAP_COLOR[3], label: "Level 3" }, { c: LVL_MAP_COLOR[4], label: "Level 4" }])
    .concat([{ c: NODATA, label: "no data" }]),
  footer: "Advisories are one government's read and change often — check the current notice before booking. wandergrade.com",
  filename: "wandergrade-travel-advisories.png",
}));
// Month and measure are both in the image: it travels without the tab, and
// "green" means cheaper than that route usually is, not cheap. The legend
// runs the way the page's does (Low, green, on the left) and states the range
// the way the ⓘ does, ±5% floor included.
function flightShareOpts() {
  const mn = MONTHS[flightMonthNum() - 1];
  const from = (flightsData && (flightsData.origin_name || flightsData.origin)) || countryName(originIso());
  const dp = dimPicksFromDom("flightMap");
  return {
    picks: dp.picks, picksTitle: dp.title,
    title: mn + " flights: below or above the usual fare?",
    sub: "Cheapest cached " + mn + " round-trip from " + from + " vs each route's typical range"
       + " — the middle half of its monthly fares over the next 12 months, at least ±5%.",
    gradient: ["#0a7d28", "#eef0f1", "#b00020"],
    leftLabel: "Low", rightLabel: "High",
    swatches: [{ c: NODATA, label: "not enough fare data" }],
    footer: "Cached fares from real searches, not live prices — and they move. wandergrade.com",
    filename: "wandergrade-flights-" + mn.toLowerCase() + ".png",
  };
}
if ($("flightShare")) $("flightShare").addEventListener("click", () => downloadMapImage("flightMap", flightShareOpts()));
if ($("rankShare")) $("rankShare").addEventListener("click", downloadRankImage);
if ($("guideShare")) $("guideShare").addEventListener("click", () =>
  downloadGuideCard(($("bestCountry") || {}).value || ccGuideIso || "JP"));
if ($("valueShare")) $("valueShare").addEventListener("click", () => {
  const month = MONTHS[(parseInt(($("valueMonth") || {}).value, 10) || curMonth()) - 1];
  const weather = valueMapMode === "weather";
  downloadMapImage("valueMap", {
    title: weather ? "Where the weather is best in " + month
                   : "Best-value places to travel in " + month,
    sub: weather ? "Weather comfort by country, scored 0-100 for this month."
                 : "Affordability, safety, weather and flight cost, combined into one grade.",
    gradient: ["#b00020", "#eef0f1", "#0a7d28"],
    leftLabel: weather ? "Harsh" : "Lower", rightLabel: weather ? "Comfortable" : "Higher",
    swatches: weather ? [{ c: NODATA, label: "no data" }]
                      : [{ c: NODATA, label: "no data" }, { c: DNT_FILL, label: "do not travel" }],
    // Names the ranked countries in the image itself. On screen they pulse;
    // in a PNG they cannot, and a shared map with no answer in it is just
    // colours. lastPicks is whatever the table is currently showing.
    picks: weather ? null : (lastPicks || []).slice(0, 8).map((p2) => p2.name),
    picksTitle: weather ? null : "Best value in " + month,
    footer: "Graded free at wandergrade.com — no sign-up.",
    filename: "wandergrade-" + (weather ? "weather-" : "best-value-") + month.toLowerCase() + ".png",
  });
});
// ("Use on another device" was removed — the Share button already produces a
//  URL carrying your map across devices.)

// ---- Instant tooltip ([data-tip]) -------------------------------------------
// Native title tooltips need a ~1s hover and are easy to miss; anything with a
// data-tip gets an immediate, styled tooltip instead. Fixed-positioned so the
// scrollable table wrappers can't clip it. (title="" on the same element
// suppresses the ancestor row's native tooltip from doubling up.)
const _tipEl = document.createElement("div");
_tipEl.className = "wgtip";
_tipEl.id = "wgtip";
_tipEl.setAttribute("role", "tooltip");
_tipEl.hidden = true;
document.body.appendChild(_tipEl);
let _tipFor = null;   // the element the tooltip is currently displaying for

// While a tip shows, its element is described by it, so a screen reader that
// lands on an ⓘ reads the tip's words, not just "More info". Only our own
// link is removed — never an aria-describedby the markup set itself.
function _tipUnlink() {
  if (_tipFor && _tipFor.getAttribute("aria-describedby") === "wgtip") _tipFor.removeAttribute("aria-describedby");
}
function _hideTip() { _tipUnlink(); _tipEl.hidden = true; _tipFor = null; }

function _showTipFor(t) {
  if (!t || !t.dataset.tip) { _hideTip(); return; }
  // Already showing for this exact element — don't reposition, that just jitters.
  if (t === _tipFor && !_tipEl.hidden) return;
  _tipUnlink();
  _tipFor = t;
  if (!t.hasAttribute("aria-describedby")) t.setAttribute("aria-describedby", "wgtip");
  _tipEl.textContent = t.dataset.tip;
  _tipEl.hidden = false;
  const r = t.getBoundingClientRect();
  const w = _tipEl.offsetWidth, h = _tipEl.offsetHeight;
  // clientWidth, not innerWidth — the latter reads 0 in some headless/embedded contexts
  const vw = document.documentElement.clientWidth || window.innerWidth;
  _tipEl.style.left = Math.max(8, Math.min(vw - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  _tipEl.style.top = (r.top - h - 8 > 8 ? r.top - h - 8 : r.bottom + 8) + "px";
}

const _tipShowFor = (e) => _showTipFor(e.target.closest && e.target.closest("[data-tip]"));
document.addEventListener("mouseover", _tipShowFor);

// mouseover fires on ENTERING an element — which never happens when the cursor
// is stationary and the DOM changes underneath it. Two ways that bit people:
//   - the tables re-render on every filter/budget change, destroying the hovered
//     node; the replacement appears under the still cursor with no mouseover, so
//     the tip wouldn't show until you moved off and back.
//   - the scroll handler below hides the tip on any scroll (a trackpad twitch
//     counts), and it wouldn't return without re-entering.
// A mousemove fallback fixes both cheaply: it only does work while the tip is
// hidden, or when the element it was showing for has been replaced — so any tiny
// movement re-shows it, no need to leave and come back.
document.addEventListener("mousemove", (e) => {
  if (_tipEl.hidden || (_tipFor && !_tipFor.isConnected)) _tipShowFor(e);
}, { passive: true });

// Info-only markers (the ⓘ hints and the ⚠️ hazard mark) sit inside clickable
// rows/cells. A click on one used to bubble to the row's navigation handler and
// redirect you before you'd read anything — and those handlers run first, so the
// tip's own click couldn't stop them. Intercept in the CAPTURE phase, which runs
// before any bubble-phase handler: show the tip, and stop the click there so it
// never reaches navigation. Interactive tips (continent chips) aren't matched, so
// they still filter on click.
// The pointer behind the next click: click events don't carry pointerType in
// every browser (older Safari), so remember it from pointerdown.
let _lastPtrType = "";
document.addEventListener("pointerdown", (e) => { _lastPtrType = e.pointerType || ""; }, true);
document.addEventListener("click", (e) => {
  // Every info-only mark that lives inside a clickable row/cell belongs on
  // this list — anything missing navigates on tap and its tip is unreachable
  // on touch: the trend marks (±%, ▲/▼), the ⓘ hints, the per-month strip
  // cells and the Flights low/typical/high cell (the row still opens from
  // anywhere else in it).
  // The ⓘ/⚠️ glyphs are info for every pointer. The rest are wide (a strip
  // spans its whole cell, trend-mark halos overlap the pills), so a mouse —
  // which already got the tip on hover — clicks through them to the row.
  const t = e.target.closest ? e.target : null;
  const mouse = (e.pointerType || _lastPtrType) === "mouse";
  const info = t && (t.closest(".hzmark, .muted[data-tip], .legendinfo, .fxinfo, .covmark")
    || (!mouse && t.closest(".fxmark, .advmv, .advmoved, .farestrip .fcell, .seasonstrip[data-tip], .wochip, .fv, .gr.grx[data-tip], #advRows .lvl[data-tip], #rows .pegnote, #advRows .advmvp, #advRows .rkwrap[data-tip], #advRows .hzwrap[data-tip], #advRows .sftext[data-tip], #affRows td.num [data-tip], #affRows .range")));
  if (info) { _showTipFor(info.dataset && info.dataset.tip ? info : e.target.closest("[data-tip]")); e.stopPropagation(); return; }
  // Touch screens have no hover: a tap on any other tipped element shows it, a
  // tap elsewhere dismisses. (closest() miss hides.)
  _tipShowFor(e);
}, true);

// Keyboard path (WCAG 1.4.13): tips show on focus, hide on blur or Escape.
// The engine was mouse/touch-only — content that exists ONLY in tips was
// unreachable for keyboard and screen-reader users.
document.addEventListener("focusin", _tipShowFor);
document.addEventListener("focusout", () => _hideTip());
document.addEventListener("keydown", (e) => { if (e.key === "Escape") _hideTip(); });

// ...but a <span>ⓘ</span> can't take focus, so that path never fired for the
// marks it was written for. Every info mark becomes a Tab stop: the ⓘ hints
// and the ⚠️ caveats (by their glyph, which leaves out the per-row "—" cells
// and grade pills that share .muted[data-tip]), the award tags and the
// guide's watch-out chips. A ⚠️ (.hzmark: a month's hazard, a Level 3-4 pick,
// a price level's caveat) held its words only in a hover or tap tip, so Tab
// went from Gambia's link straight to Sri Lanka's past it.
// A mark that is only the glyph is named "More info" (a ⚠️ "Warning — more
// info"); one with words ("~7% of the world ⓘ", "How these compare ⓘ") keeps
// them. Marks inside a control are left alone — a button, a link, or a
// role="button" like the guide's month bars, whose ⚠️ the bar's own label
// already reads: a focusable inside a control is a nested control, which
// screen readers can't reach and axe fails. One subtree observer covers the
// static page and every later render (tables, guides).
const _TIPMARK_SEL = [".muted[data-tip]", ".legendinfo[data-tip]", ".fxinfo[data-tip]", ".awardtag[data-tip]",
  ".wochip[data-tip]", ".vstats-line [data-tip]", ".hzmark[data-tip]"].map((q) => q + ":not([tabindex])").join(", ");
const _tipMarkEls = new WeakSet();
function _tipMarks() {
  for (const el of document.querySelectorAll(_TIPMARK_SEL)) {
    const txt = el.textContent;
    if (!/[ⓘ⚠]/.test(txt) && !el.matches(".awardtag, .wochip")) continue;
    if (el.parentElement && el.parentElement.closest('button, a, [role="button"]')) continue;
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    const g = txt.trim();
    if (g === "ⓘ") el.setAttribute("aria-label", "More info");
    else if (g.replace(/\uFE0F/g, "") === "⚠") el.setAttribute("aria-label", "Warning — more info");
    _tipMarkEls.add(el);
  }
}
_tipMarks();
new MutationObserver((muts) => {
  // The tooltip's own text swaps on every hover; nothing to mark there.
  if (muts.every((m) => m.target === _tipEl)) return;
  _tipMarks();
}).observe(document.body, { childList: true, subtree: true });
// role=button answers Enter and Space: both (re)show the tip — after Escape,
// say — and Space must not scroll the page out from under it.
document.addEventListener("keydown", (e) => {
  if ((e.key === " " || e.key === "Enter") && _tipMarkEls.has(e.target)) {
    e.preventDefault();
    _showTipFor(e.target);
  }
});

// Every modal is a .submodal div appended to body and removed on close, so ONE
// observer gives all of them dialog semantics and focus management — focus
// moves into the dialog on open and returns to the opener on close. Without
// this, a keyboard/SR user who opened "Save map" or "Subscribe" stayed in the
// background page under an invisible overlay.
//
// The opener is the last element focused OUTSIDE any overlay, tracked here:
// this observer runs after the opener's own code, and modals that focus their
// own field (Subscribe, Bulk add) had already moved activeElement inside, so
// focus came back to nothing. Focus that falls to the page itself clears it.
let _focusOutside = null;
// Keyboard or pointer, last? Only a keyboard visit into the unrequested invite
// earns a focus restore when it closes (see the removal branch below).
let _kbdNav = false;
document.addEventListener("keydown", () => { _kbdNav = true; }, true);
document.addEventListener("pointerdown", () => { _kbdNav = false; }, true);
document.addEventListener("focusin", (e) => {
  const ov = e.target.closest && e.target.closest(".submodal, .lightbox");
  if (!ov) _focusOutside = e.target;
  else if (_kbdNav && ov.classList.contains("submodal")) ov._kbdIn = true;
});
document.addEventListener("focusout", (e) => { if (!e.relatedTarget) _focusOutside = null; });
new MutationObserver((muts) => {
  for (const mu of muts) {
    for (const n of mu.addedNodes) {
      if (!(n instanceof HTMLElement) || !n.classList || !n.classList.contains("submodal")) continue;
      const card = n.querySelector(".submodal-card") || n;
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-modal", "true");
      if (!card.hasAttribute("aria-label")) {
        const lbl = card.querySelector("h2, h3, .sublabel");
        card.setAttribute("aria-label", (lbl && lbl.textContent.trim().slice(0, 80)) || "Dialog");
      }
      n._opener = _focusOutside;
      // aria-modal alone does not stop Tab: without this, Tab from the last
      // control walked out into the page behind the overlay. Everything else on
      // body goes inert while the dialog is up (already-inert nodes are left
      // alone, so the restore below never un-inerts something it didn't set).
      // Not for the unrequested invite: inerting the page would blur the field
      // the visitor is typing in, and that modal never takes focus anyway.
      if (!n.dataset.nofocus) {
        n._inerted = [...document.body.children].filter((el) => el !== n && el !== _tipEl && !el.inert);
        n._inerted.forEach((el) => { el.inert = true; });
      }
      // An unrequested modal (the timed newsletter invite) never takes focus:
      // it would catch whatever the visitor was typing, and on phones pop the
      // keyboard; Escape still dismisses it from anywhere. Modals that focused
      // their own field already did the job.
      if (n.dataset.nofocus || card.contains(document.activeElement)) continue;
      const f = card.querySelector("input, select, textarea, button:not(.submodal-x)")
        || card.querySelector("button");
      if (f) f.focus();
    }
    for (const n of mu.removedNodes) {
      if (!(n instanceof HTMLElement) || !n.classList || !n.classList.contains("submodal")) continue;
      // Un-inert the page first: the opener can't take focus back while inert.
      (n._inerted || []).forEach((el) => { el.inert = false; });
      // The unrequested invite never took focus, so unless the keyboard went
      // into it there is nothing to give back: a mouse close (the X focuses,
      // then vanishes) or Escape from a combobox (which blurs itself) left
      // activeElement on body, and the restore re-opened that combobox's list
      // and, for the scroll-triggered invite, jumped the page back up.
      if (n.dataset.nofocus && !n._kbdIn) continue;
      // Only when focus went down with the modal — never yank it from
      // somewhere the visitor has since moved to.
      const a = document.activeElement;
      if (n._opener && n._opener.isConnected && (!a || a === document.body || n.contains(a)))
        n._opener.focus({ preventScroll: !!n.dataset.nofocus });
    }
  }
}).observe(document.body, { childList: true });

document.addEventListener("scroll", _hideTip, true);

(async function init() {
  initTheme();
  ensureMonthOptions();   // the travel month exists before any tab (guide-first too)
  renderSubscribe();
  renderFeedback();
  preApplyShared();
  // A Trip landing draws its list now, from this browser's storage (or the
  // link's tp=), not after the rates, map and climate below: until then the
  // tab was an empty card that grew 109px at 390 when the list arrived,
  // taking the newsletter box and footer with it. The rows' pills, marks
  // and booking links fill in once their data lands (activateTab).
  if (document.documentElement.getAttribute("data-tab") === "trip") renderTripBar();
  // Settings + manual email exist only off a public deployment: the group
  // ships hidden and is shown here when the server isn't read-only. Hiding it
  // on the answer instead (the public case) let the two buttons wrap the Data
  // bar to a second row on every phone until /api/config returned, then pulled
  // the whole Currency view up 46px (CLS 0.034 per phone load). And the group
  // as a whole, not just its buttons: an empty .actions still took a slot in
  // the bar's space-between row and parked the Region picker mid-page.
  getJSON("/api/config").then((c) => {
    if (!c.readonly) $("check").parentElement.hidden = false;
  }).catch(() => {});
  // Load the currency data (the "Where to go" score needs live rates + PPP),
  // render the currency tab in the background, then open the verdict tab.
  // climate.json too: it is where countryName gets the names people use
  // ("Iran", "Laos"), and without it the maps' lists fall back to ppp.json's
  // World Bank ones ("Iran, Islamic Rep.", "Lao PDR"). Every landing used to
  // load it with Top Picks; a Data landing no longer builds Top Picks (init
  // below), so it comes here, before the first list is drawn.
  await Promise.all([ensurePPP().catch(() => {}), ensureWorld().catch(() => {}), loadRates(),
                     ensureClimate().catch(() => {})]);
  renderMapSafe();
  // The 1-year index chart lives in the Explore-the-Data tab; it loads there
  // on first open (setDataMode) instead of costing every landing visit.
  // A /guide/<slug> page (server injects window.__WGGC__) opens that country
  // straight away — no Top Picks flash. Email ?tab=guide&gc= links fall through
  // to postApplyShared as before.
  await ensureSlugs();
  const bootIso = (window.__WGGC__ && /^[A-Z]{2}(-[A-Z]{3})?$/.test(window.__WGGC__))
    ? window.__WGGC__ : pathGuideIso();
  // Every other landing opens the tab its URL names, straight away. This used
  // to open Top Picks first and leave the switch to postApplyShared: a
  // ?tab=data link painted Data (the head script), then Top Picks, then Data
  // again — 2.8s / 3.4s / 4.1s on slow 4G, two 0.30 layout shifts at 1280 for
  // a reader already scrolling, and the whole Top Picks build (activities.json
  // and eleven fare fetches) paid for a tab nobody opened. A ?tab=guide&gc=
  // link is left to postApplyShared, which opens that country after the month.
  // Trip too now: it used to go through Top Picks for the climate and
  // advisories its rows read, so /?tab=trip painted Trip, Top Picks, Trip
  // (two shifts of 0.50 and 0.37 on a 4x-slowed 390 phone). activateTab loads
  // what Trip reads itself.
  const boot = sharedTab();
  if (bootIso) await openGuideFor(bootIso);
  else if (boot.tab === "guide" && boot.gcOk) _bootTab = null;
  else {
    _bootTab = boot.tab || "value";
    if (_bootTab === "data" && DATA_SUBS[boot.dm]) dataMode = boot.dm;
    await activateTab(_bootTab);
  }
  await postApplyShared().catch(() => {});
  appReady = true;          // from here on, user navigation is mirrored to the URL
  syncURL();
})();

// PWA: installable + offline shell. Registered ONLY on the real domain — a
// service worker on localhost would serve stale copies during development.
if ("serviceWorker" in navigator && location.hostname.endsWith("wandergrade.com"))
  navigator.serviceWorker.register("/sw.js").catch(() => {});

// ---- accounts: passwordless magic-link sign-in --------------------------------
// The Wander List lives in localStorage, which private-browsing tabs discard.
// Signing in copies the map to the cloud so it survives private tabs and
// follows you across devices. No passwords: a one-time emailed link is the
// whole credential. Everything here stays hidden unless the server reports
// accounts are configured (window.__WGACCT__).
const ACCT_ON = window.__WGACCT__ === true;
// The newsletter is monthly or nothing: one list, one monthly send. "Every 3
// months" was offered but never honoured, so it's gone; a stored "quarterly"
// shows as monthly.
const CADENCE_LABEL = { monthly: "Monthly", off: "No emails" };
let acctState = null;              // { email, user } once signed in

let acctKnown = false;              // the server has answered (or a 401 has)

function acctSignedIn() { return !!(acctState && acctState.email); }
// A 401 means the session is gone: show it, instead of silently dropping
// every later sync.
function acctSignedOut() { acctState = null; acctKnown = true; acctPaintButton(); }

async function acctLoad() {
  if (!ACCT_ON) return;
  try {
    const r = await fetch("/api/auth/me", { credentials: "same-origin" });
    const d = await r.json();
    acctState = d && d.email ? d : null;
    acctKnown = true;
  } catch (e) { acctState = null; }
  acctPaintButton();
  if (acctSignedIn() && acctState.user) await acctMergeDown(acctState.user);
}

// ---- map sync: a three-way merge ---------------------------------------------
// The server stores whatever list it is sent, so merging is the client's job.
// A plain union on every load could not express a deletion: a country removed
// on one device came back from any other. Each device keeps the last list it
// and the cloud agreed on (the base); against that, a country missing from
// either side was removed there and one new on either side was added. With no
// base yet (first sign-in on this device) it is the old union.
const SYNC_BASE_KEY = "wg_sync_base";
// Which account a base belongs to, without keeping the address itself around.
const acctTag = (email) => {
  let h = 5381;
  for (const ch of String(email)) h = ((h * 33) ^ ch.charCodeAt(0)) >>> 0;
  return h.toString(36);
};
function acctBase() {
  try {
    const b = JSON.parse(localStorage.getItem(SYNC_BASE_KEY) || "null");
    if (b && acctSignedIn() && b.acct === acctTag(acctState.email)) return b;
  } catch (e) {}
  return null;
}
function acctSetBase(u) {
  if (!acctSignedIn()) return;
  try {
    localStorage.setItem(SYNC_BASE_KEY, JSON.stringify({
      acct: acctTag(acctState.email), visited: u.visited || [], wishlist: u.wishlist || [] }));
  } catch (e) {}
}
function merge3(base, local, cloud) {
  const l = new Set(local), c = new Set(cloud || []);
  const out = new Set([...l, ...c]);
  for (const x of base || []) if (!l.has(x) || !c.has(x)) out.delete(x);
  return out;
}
const sameSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));

// Reconcile this device with the cloud copy `user` (fresh from /api/auth/me)
// and push the result if the cloud is behind. Runs on every load and before
// every push, so a stale tab can't overwrite another device's edits. Works on
// the viewer's OWN lists — never a shared map that happens to be on screen.
async function acctMergeDown(user) {
  const base = acctBase();
  const lv = ownVisited(), lw = loadWishlist();
  const mv = merge3(base && base.visited, lv, user.visited);
  const mw = merge3(base && base.wishlist, lw, user.wishlist);
  if (!sameSet(mv, lv) || !sameSet(mw, lw)) {
    localStorage.setItem("fx_visited", JSON.stringify([...mv]));
    localStorage.setItem("fx_wishlist", JSON.stringify([...mw]));
    // In place: open views (the bulk-add modal) hold these very Sets.
    if (!sharedVisitedView) { visited.clear(); mv.forEach((i) => visited.add(i)); }
    wishlist.clear(); mw.forEach((i) => wishlist.add(i));
    if (loaded.visited) renderVisited();
    if (loaded.value) renderValue();
  }
  const lists = { visited: [...mv], wishlist: [...mw] };
  if (sameSet(mv, new Set(user.visited || [])) && sameSet(mw, new Set(user.wishlist || []))) {
    acctSetBase(lists);
    return true;
  }
  // Backgrounded (phones suspend page fetches soon after): keepalive lets the
  // POST outlive that once the fresh GET has come back.
  return acctPost(lists, document.visibilityState === "hidden");
}

async function acctPost(lists, keepalive) {
  let r;
  try {
    r = await fetch("/api/auth/sync", {
      method: "POST", credentials: "same-origin", keepalive: !!keepalive,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lists),
    });
  } catch (e) { return false; }   // offline: localStorage holds it; the next merge pushes it
  if (r.status === 401) { acctSignedOut(); return false; }
  if (!r.ok) return false;
  try {
    const d = await r.json();
    if (d.user) { if (acctState) acctState.user = d.user; acctSetBase(d.user); }
  } catch (e) {}
  return true;
}

let _syncTimer = null, _syncHoldUntil = 0, _syncRun = null, _syncAgain = false;
function acctQueueSync() {
  if (!acctSignedIn()) return;
  clearTimeout(_syncTimer);        // coalesce bulk edits into one request
  _syncTimer = setTimeout(acctSync, Math.max(800, _syncHoldUntil - Date.now()));
}
// Keep queued pushes back for an undo window (Clear all), so an undone
// clear never reaches the account.
function acctHoldSync(ms) { _syncHoldUntil = Date.now() + ms; }
async function acctSync() {
  clearTimeout(_syncTimer); _syncTimer = null;
  if (!acctSignedIn()) return;
  if (_syncRun) { _syncAgain = true; return _syncRun; }   // one at a time, then rerun
  _syncRun = (async () => {
    do {
      _syncAgain = false;
      try {
        const r = await fetch("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
        if (!r.ok) break;
        const d = await r.json();
        if (!d || !d.email) { acctSignedOut(); break; }
        acctState = d;
        await acctMergeDown(d.user || {});
      } catch (e) { break; }   // offline: the next change or load retries
    } while (_syncAgain && acctSignedIn());
  })().finally(() => { _syncRun = null; });
  return _syncRun;
}
// A change made just before the tab closed used to die in the debounce, and
// the next load's merge brought it back. Push it on the way out (keepalive
// outlives the page), merged against the last cloud copy this tab saw.
// Never inside a Clear-all undo hold: the cloud keeps the pre-clear list, and
// the queued push (or this device's next load, which merges the clear from
// localStorage) sends it once Undo is no longer possible — nothing is lost.
// A sync still in flight counts as pending: closing a tab fires the
// visibilitychange below first, and its GET dies with the page.
function acctFlush() {
  if ((!_syncTimer && !_syncRun) || !acctSignedIn() || Date.now() < _syncHoldUntil) return;
  clearTimeout(_syncTimer); _syncTimer = null;
  const base = acctBase(), u = acctState.user || {};
  acctPost({
    visited: [...merge3(base && base.visited, ownVisited(), u.visited)],
    wishlist: [...merge3(base && base.wishlist, loadWishlist(), u.wishlist)],
  }, true);
}
window.addEventListener("pagehide", acctFlush);
// A tab switch isn't an unload: the page stays alive, so take the normal
// GET-then-merge path. The blind keepalive POST merged against this tab's last
// cloud copy and could resurrect a country another device had just removed.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && _syncTimer && Date.now() >= _syncHoldUntil) acctSync();
});

async function acctPrefs(prefs) {
  try {
    const r = await fetch("/api/auth/prefs", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
    if (r.status === 401) { acctSignedOut(); return; }
    const d = await r.json();
    if (d.user && acctState) acctState.user = d.user;
  } catch (e) {}
}

function acctPaintButton() {
  const b = $("acctBtn");
  if (!b) return;
  b.hidden = !ACCT_ON;
  b.innerHTML = acctSignedIn() ? "👤" : '👤 <span class="btxt">Save map</span>';
  b.title = acctSignedIn()
    ? "Your account — " + acctState.email
    : "Save your travel map to an account (works in private tabs)";
  // Remembered for the next page's <head> script, which hides the label
  // before first paint (html[data-acct]): a signed-in visitor's button
  // otherwise painted "👤 Save map" and shrank to "👤" when /api/auth/me
  // answered, re-wrapping the header twice. Only once the answer is in — at
  // parse time the state is still unknown, not signed out. With the session
  // cookie's own expiry (accounts.SESSION_TTL, 90 days, rolled forward by
  // this same answer): a flag outliving the session painted "👤" for a
  // signed-out visitor and re-wrapped the header when it widened (+62px at
  // 850).
  if (!acctKnown) return;
  const root = document.documentElement;
  try {
    if (acctSignedIn()) {
      root.setAttribute("data-acct", "in");
      localStorage.setItem("wg_acct", "in:" + (Date.now() + 90 * 864e5));
    } else { root.removeAttribute("data-acct"); localStorage.removeItem("wg_acct"); }
  } catch (e) {}
}

function acctModal(inner) {
  if (document.querySelector(".submodal")) return null;
  const m = document.createElement("div");
  m.className = "submodal";
  m.innerHTML = '<div class="submodal-card"><button class="submodal-x" aria-label="Close">✕</button>'
    + inner + "</div>";
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add("show"));
  // close() drops the Escape listener however the modal closes (X, backdrop,
  // Escape, or a caller's m.close()), so no stale one outlives it.
  const close = () => {
    document.removeEventListener("keydown", onKey);
    m.classList.remove("show"); setTimeout(() => m.remove(), 220);
  };
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  m.querySelector(".submodal-x").onclick = close;
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  m.close = close;
  return m;
}

function openSignIn() {
  const m = acctModal(
    '<span class="sublabel">👤 Save your travel map <span class="muted" data-tip="Private tabs wipe it. Sign in and it follows you — on every device. No password — just a one-time link." title="">ⓘ</span></span>'
    + '<form class="subform acctform"><input type="email" name="email" placeholder="you@email.com" required>'
    + '<button type="submit">Email me a link</button></form>'
    // Unticked by default: saving a map is not consent to a newsletter (a
    // pre-ticked box isn't valid consent under GDPR). Monthly is the only
    // cadence there is, so it's in the words rather than a one-option picker.
    + '<label class="acctcheck"><input type="checkbox" id="acctSub"> Also send me the monthly newsletter'
    + (digestCurs().length > 1 ? ' in <select id="acctCur" class="subcur" aria-label="Newsletter currency">'
      + subCurOptions(subCurDefault(), false) + "</select>" : "")
    + "</label>"
    );
  if (!m) return;
  const sub = m.querySelector("#acctSub"), curSel = m.querySelector("#acctCur");
  touchSubCur(curSel);
  m.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const email = m.querySelector('input[type="email"]').value.trim();
    if (!email) return;
    // Remember the newsletter choice so it can be applied once the link is
    // clicked (the click may land in a different tab). Opt-in only: an unticked
    // box on a re-sign-in (new device, expired session) must not unsubscribe an
    // existing subscriber — the account panel is the one place to opt out.
    try {
      if (sub.checked) {
        localStorage.setItem("wg_pending_prefs", JSON.stringify(Object.assign(
          { subscribed: true, cadence: "monthly" }, curSel ? { currency: curSel.value } : {})));
      } else {
        localStorage.removeItem("wg_pending_prefs");
      }
    } catch (err) {}
    const btn = m.querySelector('button[type="submit"]');
    btn.disabled = true; btn.textContent = "Sending…";
    try {
      await fetch("/api/auth/request", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
    } catch (err) {}
    m.querySelector(".submodal-card").innerHTML =
      '<button class="submodal-x" aria-label="Close">✕</button>'
      + '<span class="sublabel">📬 Check your inbox</span>'
      + `<p class="hint">If ${esc(email)} is a working address, a one-time sign-in link is on its way.`
      + ' It expires in 15 minutes.</p>';
    m.querySelector(".submodal-x").onclick = m.close;
  };
}

function openAccount() {
  const u = (acctState && acctState.user) || {};
  // Any live cadence (incl. a legacy "quarterly") is monthly; unsubscribed is off.
  const cad = u.subscribed && u.cadence !== "off" ? "monthly" : "off";
  // The currency select shows the account's choice. With none stored, a
  // subscriber gets the USD issue, so that is what it says; an account that
  // isn't opted in shows "—" (nothing chosen), so that ANY pick is a change:
  // a reader on the list through the public form switches editions here
  // (accounts._sync_newsletter re-tags them), and a pre-selected home
  // currency could never be picked. A stored choice that has since been
  // switched off (digest_variants.ROLLOUT) is kept for when it returns: the
  // select shows what they get meanwhile (USD) and only a real pick, never a
  // cadence toggle, replaces it.
  const curs = digestCurs();
  const stored = curs.includes(u.currency) ? u.currency : null;
  const keepOff = !!u.currency && !stored;
  const cur = stored || (cad !== "off" ? "USD" : "");
  const m = acctModal(
    '<span class="sublabel">👤 Your account</span>'
    + `<p class="hint"><b>${esc(acctState.email)}</b> — your map syncs automatically.</p>`
    + '<label class="acctcheck"><input type="checkbox" id="acctSub2"' + (cad !== "off" ? " checked" : "")
    + '> Newsletter <select id="acctCad2">'
    + ["monthly", "off"].map((c) =>
        `<option value="${c}"${c === cad ? " selected" : ""}>${CADENCE_LABEL[c]}</option>`).join("")
    + "</select>"
    + (curs.length > 1 ? ' in <select id="acctCur2" class="subcur" aria-label="Newsletter currency">'
      + subCurOptions(cur, false, !cur) + "</select>" : "")
    + "</label>"
    + (curs.length > 1 ? '<p class="hint" id="acctCurMsg" hidden></p>' : "")
    + '<div class="bulkfoot"><button type="button" class="bulkdone" id="acctOut">Sign out</button></div>');
  if (!m) return;
  const sub = m.querySelector("#acctSub2"), cadSel = m.querySelector("#acctCad2");
  const curSel = m.querySelector("#acctCur2");
  if (curSel) curSel.dataset.touched = "1";   // shows the account's choice: never re-defaulted
  const curPrefs = () => (curSel && curSel.value && (!keepOff || curSel.dataset.picked)
    ? { currency: curSel.value } : {});
  let curTimer = 0;
  // The select shows what the account kept: a pick that rode along with a
  // subscribe/cadence change and wasn't saved snaps back, as a pick on its
  // own does.
  const showKept = () => {
    const got = acctState && acctState.user ? acctState.user.currency : null;
    if (curSel && curs.includes(got) && curSel.value !== got) curSel.value = got;
  };
  const push = async () => {
    clearTimeout(curTimer);                   // a pending pick rides along with this call
    await acctPrefs(Object.assign({ subscribed: sub.checked, cadence: cadSel.value }, curPrefs()));
    showKept();
  };
  // A currency-only change re-tags the subscriber; nothing else is sent.
  // Debounced: arrowing through the closed select fires change per step,
  // and each call reads and rewrites the subscriber's Buttondown tags on its
  // own server thread — the last write won, which could leave the tag on a
  // currency the reader only passed over. Only the value they settle on is
  // sent. If the server didn't keep it (Buttondown unreachable: the account
  // reverts so it never disagrees with the list), the select snaps back.
  if (curSel) curSel.onchange = () => {
    curSel.dataset.picked = "1";
    clearTimeout(curTimer);
    curTimer = setTimeout(async () => {
      const want = curSel.value, msg = m.querySelector("#acctCurMsg");
      if (!want) return;
      await acctPrefs({ currency: want });
      const got = acctState && acctState.user ? acctState.user.currency : null;
      if (got === want || curSel.value !== want) { if (msg) msg.hidden = true; return; }
      curSel.value = curs.includes(got) ? got : cur;
      if (msg) {
        msg.textContent = "Couldn't switch the newsletter to " + want + " just now — try again in a minute.";
        msg.hidden = false;
      }
    }, 800);
  };
  // Opting in from "—": the home currency is the suggestion, now shown and sent.
  const optInCur = () => {
    if (sub.checked && curSel && !curSel.value) { curSel.value = subCurDefault(); curSel.dataset.picked = "1"; }
  };
  sub.onchange = () => {
    if (!sub.checked) cadSel.value = "off";
    else if (cadSel.value === "off") cadSel.value = "monthly";
    optInCur();
    push();
  };
  cadSel.onchange = () => { sub.checked = cadSel.value !== "off"; optInCur(); push(); };
  m.querySelector("#acctOut").onclick = async () => {
    // A currency picked under 800ms ago is still waiting on its debounce:
    // send it before the session ends, or signing out drops it.
    if (curTimer && curSel && curSel.value && curSel.dataset.picked) {
      clearTimeout(curTimer);
      curTimer = 0;
      await acctPrefs({ currency: curSel.value });
    }
    if (_syncTimer) await acctSync();   // a pending edit reaches the account first
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); } catch (e) {}
    acctSignedOut();
    m.close();
    status("Signed out — your map stays in this browser.", "ok");
  };
}

if ($("acctBtn")) {
  acctPaintButton();
  $("acctBtn").addEventListener("click", () => (acctSignedIn() ? openAccount() : openSignIn()));
}
// Read at parse time, not inside the .then(): syncURL() rebuilds the address bar
// from app state as soon as init finishes and drops every param it doesn't own,
// so ?signin= is often gone by the time acctLoad()'s round trip resolves. Reading
// it late made the whole sign-in result a coin flip on which finished first.
const SIGNIN_RESULT = new URLSearchParams(location.search).get("signin");

// Sign-in results get their own banner. #status is a transient line — loadRates()
// clears it a second or two after load — so a sign-in message posted there showed
// up and then vanished before it could be read.
function acctNote(msg, kind) {
  const el = $("acctnote");
  if (!el) return;
  _liveSet(el, msg);   // announced, like status()
  el.className = "status " + (kind || "");
}
if (ACCT_ON) {
  acctLoad().then(async () => {
    const q = SIGNIN_RESULT;
    if (!q) return;
    history.replaceState(null, "", location.pathname);   // don't leave ?signin= around
    if (q === "expired") { acctNote("That sign-in link expired — request a new one.", "err"); return; }
    if (acctSignedIn()) {
      let pending = null;
      try { pending = JSON.parse(localStorage.getItem("wg_pending_prefs") || "null"); } catch (e) {}
      if (pending) {
        localStorage.removeItem("wg_pending_prefs");
        // Opt-in only (see openSignIn): a {subscribed:false} left by an older
        // build must not unsubscribe anyone either.
        if (pending.subscribed === true) {
          await acctPrefs(Object.assign({ subscribed: true, cadence: "monthly" },
            /^[A-Z]{3}$/.test(pending.currency || "") ? { currency: pending.currency } : {}));
        }
      }
      await acctSync();               // seed the account with this device's map
      acctNote("Signed in — your travel map is saved to " + acctState.email + " ✓", "ok");
      return;
    }
    // The token verified but this browser has no session: the link was opened in
    // a mail app's in-app browser, which spent the single-use token and kept the
    // cookie in its own jar. Saying nothing here left the map looking unchanged
    // with no reason why — the one failure the sign-in path must not be silent
    // about, since a fresh link is the only way forward.
    acctNote("Sign-in didn't stick — your email app opened the link in its own browser."
             + " Request a new link and open it here.", "err");
  });
}

// ---- install-app affordance ---------------------------------------------------
// iOS never prompts for PWA install and Android only sometimes, so a small 📲
// header button appears when installation is possible but not done. On iOS it
// walks through Share → Add to Home Screen (no programmatic prompt exists);
// elsewhere it fires the browser's real install prompt, captured below.
(function installAffordance() {
  const btn = $("installBtn");
  if (!btn) return;
  if (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true)
    return;                                    // already running as the app
  let deferred = null;
  const bipMiss = (v) => { try { if (v == null) localStorage.removeItem("wg_bipmiss"); else localStorage.setItem("wg_bipmiss", v); } catch (e) {} };
  if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
    btn.hidden = false;
  } else {
    let offered = false, counted = false;
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferred = e;
      btn.hidden = false;
      offered = true;
      bipMiss(null);
    });
    // The head script reserves the button's slot only while the prompt may
    // still come here: a page view that ends without it counts once, and two
    // in a row (already installed, a browser that won't offer it) stop the
    // reservation, which was otherwise a taller header for good. An offer
    // resets the count — also when it comes late, after a count.
    const miss = () => {
      if (offered || counted || !("onbeforeinstallprompt" in window)) return;
      counted = true;
      let n = 0;
      try { n = +localStorage.getItem("wg_bipmiss") || 0; } catch (e) {}
      bipMiss(String(n + 1));
    };
    window.addEventListener("pagehide", miss);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") miss(); });
  }
  // Drop the head script's flag too: it shows (iOS) or reserves the button
  // over [hidden]. Installed, this browser won't be offered it again.
  window.addEventListener("appinstalled", () => {
    btn.hidden = true;
    document.documentElement.removeAttribute("data-inst");
    bipMiss("9");
  });
  btn.addEventListener("click", () => {
    if (deferred) {                            // Chrome/Android: the real prompt
      deferred.prompt();
      deferred = null;
      btn.hidden = true;
      return;
    }
    // iOS: show the ritual (the button only shows without `deferred` on iOS)
    if (document.querySelector(".submodal")) return;
    const m = document.createElement("div");
    m.className = "submodal";
    m.innerHTML = '<div class="submodal-card"><button class="submodal-x" aria-label="Close">✕</button>'
      + '<span class="sublabel">📲 Install WanderGrade</span>'
      + '<ol class="installsteps">'
      + '<li>Tap the <b>Share</b> button in Safari — the square with the up arrow <span class="sharemark">⬆</span></li>'
      + '<li>Scroll down and tap <b>“Add to Home Screen”</b></li>'
      + '<li>Tap <b>Add</b> — then launch WanderGrade from your home screen 🌍</li>'
      + '</ol>'
      + '<span class="hint">Full-screen, its own icon, works like an app — always up to date.</span>'
      + "</div>";
    document.body.appendChild(m);
    requestAnimationFrame(() => m.classList.add("show"));
    const close = () => {
      document.removeEventListener("keydown", onKey);   // however it closes
      m.classList.remove("show"); setTimeout(() => m.remove(), 220);
    };
    m.addEventListener("click", (e) => { if (e.target === m) close(); });
    m.querySelector(".submodal-x").onclick = close;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
  });
})();

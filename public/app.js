"use strict";

const $ = (id) => document.getElementById(id);
let lastRates = null;   // always USD-based — feeds the Top Picks scoring
let dataRates = null;   // whatever the Explore-the-Data currency view shows

// Home currency for the Explore-the-Data currency view (display only; Top
// Picks stays a USD-traveler tool). Persisted per browser, default USD.
let dataBase = /^[A-Z]{3}$/.test(localStorage.getItem("fx_database") || "")
  ? localStorage.getItem("fx_database") : "USD";
const baseWord = (b) => (b === "USD" ? "the dollar" : b);

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
  if (lastIndexData) renderIndex(lastIndexData);   // redraw chart in new palette
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
      }
    });
  }
}
let lastIndexData = null;

function status(msg, kind) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + (kind || "");
  el.hidden = !msg;
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
  // Compact but readable for both 0.85 and 18070.
  if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function rangeMarker(r) {
  // Where today's rate sits between the window low and high. A rate near its
  // 1-year high means your currency buys more than usual → dot to the right,
  // on the green (strong) end of the track. Left/grey = weak.
  const span = r.high - r.low;
  const pct = span > 0 ? ((r.rate_now - r.low) / span) * 100 : 50;
  const clamped = Math.max(0, Math.min(100, pct));
  const meaning = clamped >= 66 ? "near its 1-year high — your money buys more than most of the past year"
                : clamped <= 34 ? "near its 1-year low — your money buys less than most of the past year"
                : "mid-range for the past year";
  const tip = `Today sits ${Math.round(clamped)}% up its 1-year range `
            + `(low ${fmt(r.low)} · high ${fmt(r.high)}) — ${meaning}. Further right = your money goes further.`;
  return `<div class="range" title="${esc(tip)}"><span style="left:${clamped}%"></span></div>`;
}

function fmtMonth(iso) {
  // "2025-06-06" -> "Jun '25"
  const m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const p = iso.split("-");
  return m[parseInt(p[1], 10) - 1] + " '" + p[0].slice(2);
}

const DAY_LABEL = { 30: "1 month", 90: "3 months", 180: "6 months", 365: "1 year" };

function renderIndex(data) {
  const pts = data.index || [];
  const chg = data.index_change_pct || 0;
  const up = chg >= 0;
  const label = DAY_LABEL[data.days] || (data.days + "d");

  $("indexnow").textContent = pts.length ? pts[pts.length - 1].value.toFixed(1) : "—";
  const chgEl = $("indexchg");
  chgEl.textContent = (up ? "▲ +" : "▼ ") + chg + " over " + label;
  chgEl.className = up ? "pos" : "neg";
  $("chartsub").textContent =
    `Equal-weighted across ${data.index_count} currencies · ${pts.length ? pts[0].date : ""} → ${data.as_of}`;

  const host = $("chart");
  if (pts.length < 2) { host.innerHTML = "<p class='hint'>Not enough data.</p>"; return; }

  // Geometry (viewBox units; scales to container width via CSS).
  const W = 800, H = 260, padL = 44, padR = 16, padT = 14, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const vals = pts.map((p) => p.value);
  let lo = Math.min(100, ...vals), hi = Math.max(100, ...vals);
  const pad = (hi - lo) * 0.12 || 1;
  lo -= pad; hi += pad;

  const x = (i) => padL + (i / (pts.length - 1)) * plotW;
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;

  const color = up ? "#0a7d28" : "#b00020";
  const fill = up ? "rgba(10,125,40,0.08)" : "rgba(176,0,32,0.07)";

  // Theme-aware chart chrome (gridlines/labels follow light/dark mode).
  const gridCol = cssVar("--chartgrid", "#eee");
  const labCol = cssVar("--gray", "#999");

  // Y gridlines + labels (~4 ticks).
  let grid = "";
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = lo + (t / ticks) * (hi - lo);
    const gy = y(v);
    grid += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="${gridCol}" stroke-width="1"/>`;
    grid += `<text x="${padL - 6}" y="${gy + 3}" text-anchor="end" font-size="10" fill="${labCol}">${v.toFixed(1)}</text>`;
  }

  // Baseline at 100.
  const by = y(100);
  const baseline =
    `<line x1="${padL}" y1="${by}" x2="${W - padR}" y2="${by}" stroke="${labCol}" stroke-width="1" stroke-dasharray="4 3"/>` +
    `<text x="${W - padR}" y="${by - 4}" text-anchor="end" font-size="10" fill="${labCol}">100 (start)</text>`;

  // X date labels (~5 evenly spaced).
  let xlab = "";
  const xticks = 5;
  for (let t = 0; t <= xticks; t++) {
    const i = Math.round((t / xticks) * (pts.length - 1));
    xlab += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="${labCol}">${fmtMonth(pts[i].date)}</text>`;
  }

  // Line + area paths.
  const line = pts.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.value).toFixed(1)).join(" ");
  const area = `M${x(0).toFixed(1)} ${y(pts[0].value).toFixed(1)} ` +
    pts.map((p, i) => "L" + x(i).toFixed(1) + " " + y(p.value).toFixed(1)).join(" ") +
    ` L${x(pts.length - 1).toFixed(1)} ${by} L${x(0).toFixed(1)} ${by} Z`;

  const lastX = x(pts.length - 1), lastY = y(pts[pts.length - 1].value);

  host.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(data.base || "USD")} strength index over time">` +
    grid + baseline +
    `<path d="${area}" fill="${fill}"/>` +
    `<path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>` +
    `<circle cx="${lastX}" cy="${lastY}" r="3.5" fill="${color}"/>` +
    xlab +
    `</svg>`;
}

// Client-side sort for the currency table. Default matches the server order
// (vs-avg, strongest-first); clicking a header re-sorts, clicking again flips.
const CUR_SORT_GET = {
  code:  (r) => r.code,
  rate:  (r) => r.rate_now,
  vsavg: (r) => r.strength_pct,
  price: (r) => priceLevelForCurrency(r.code),   // may be null → sorts last
  range: (r) => { const s = r.high - r.low; return s > 0 ? (r.rate_now - r.low) / s : 0.5; },
};
const CUR_SORT_DEFAULT_ASC = { code: true, rate: false, vsavg: false, price: true, range: false };
let curSort = { key: "vsavg", asc: false };

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

// Show a ▲/▼ marker on the active sort header.
function updateCurSortIndicators() {
  document.querySelectorAll('#rates th.sortable').forEach((th) => {
    const active = th.dataset.sk === curSort.key;
    th.dataset.sortdir = active ? (curSort.asc ? "asc" : "desc") : "";
  });
}
// Clicking a header sorts by that column (each column has a sensible first
// direction); clicking the active column again reverses it.
document.addEventListener("click", (e) => {
  const th = e.target.closest("#rates th.sortable");
  if (!th) return;
  const k = th.dataset.sk;
  curSort = (curSort.key === k)
    ? { key: k, asc: !curSort.asc }
    : { key: k, asc: CUR_SORT_DEFAULT_ASC[k] };
  if (dataRates) renderRates(dataRates);
});

// ---- generic click-to-sort for the other data tables (same UX as currency) --
// Headers carry class="sortable" data-sk="col"; each table has a getters map, a
// sort-state object, a first-click direction map (default asc unless false),
// and a re-render callback.
function sortRows(rows, state, getters) {
  const get = getters[state.key];
  if (!get) return rows.slice();
  const dir = state.asc ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = get(a), vb = get(b);
    if (typeof va === "string" || typeof vb === "string")
      return dir * String(va).localeCompare(String(vb));
    const na = va == null || !isFinite(va), nb = vb == null || !isFinite(vb);
    if (na || nb) return na - nb;                 // blanks/unknowns always last
    return dir * (va - vb);
  });
}
function markSort(theadSel, state) {
  document.querySelectorAll(theadSel + " th.sortable").forEach((th) => {
    th.dataset.sortdir = th.dataset.sk === state.key ? (state.asc ? "asc" : "desc") : "";
  });
}
function wireSort(theadSel, state, firstAsc, rerender) {
  document.addEventListener("click", (e) => {
    const th = e.target.closest(theadSel + " th.sortable");
    if (!th) return;
    if (state.key === th.dataset.sk) state.asc = !state.asc;
    else { state.key = th.dataset.sk; state.asc = firstAsc[th.dataset.sk] !== false; }
    rerender();
  });
}

// Cost of living: cheapest-first by default; "$100 buys" is the inverse of the
// price level, so it opens descending (most goods first).
const AFF_GET = { name: (r) => r.name, cur: (r) => r.cur, pl: (r) => r.pl,
                  buys: (r) => 100 / r.pl, feels: (r) => r.pl };
const affSort = { key: "pl", asc: true };
wireSort("#affTable", affSort, { buys: false }, () => { if (typeof ppp !== "undefined" && ppp) renderAfford(); });

// Safety: safest (Level 1) first by default. The advisory text tracks the
// level, so that column sorts by severity too.
const ADV_GET = { country: (it) => it.country, level: (it) => parseInt(it.level, 10) || 0,
                  text: (it) => parseInt(it.level, 10) || 0 };
const advSort = { key: "level", asc: true };
wireSort("#advTable", advSort, {}, () => { if (advisories) renderAdvisories(); });

// Flights: cheapest average first; "routes sampled" opens descending.
const FLIGHT_GET = { dest: (c) => countryName(c.iso), avg: (c) => c.avg, min: (c) => c.min,
                     dur: (c) => c.dur, stops: (c) => c.stops, n: (c) => c.n };
const flightSort = { key: "avg", asc: true };
wireSort("#flightTable", flightSort, { n: false }, () => { if (flightsData) renderFlights(); });

// Top Picks report card: default overall-value order. Sorting a column
// reorders AND renumbers the same top-N set (rank = row position). Grade
// columns open best-first; Safety opens safest-first (advisory level 1);
// Destination A→Z. Flights with no fare sort last.
const PICK_GET = { dest: (s) => s.name, afford: (s) => s.afford, safety: (s) => s.advLvl,
                   weather: (s) => s.wx, flights: (s) => (s.fly == null ? null : s.fly),
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
                   safety: (s) => s.safe, weather: (s) => s.wx,
                   flight: (s) => (s.fly == null ? null : s.fly) };
const fullSort = { key: "value", asc: false };
wireSort("#valueTable", fullSort, { value: false, afford: false, safety: false, weather: false, flight: false },
         () => renderValue());

function renderRates(data) {
  dataRates = data;
  const base = data.base || "USD";
  if (base === "USD") lastRates = data;   // scoring only ever uses USD data
  renderMapSafe();
  buildBaseSelect();
  const w = baseWord(base);
  $("mapH2").innerHTML = `Where ${esc(w)} is strong <span class="muted">vs each currency's 1-year average</span>`;
  $("chartH2").innerHTML = `Overall ${esc(w === "the dollar" ? "dollar" : w)} strength <span class="muted">vs rest of world</span>`;
  $("rateColHead").textContent = `1 ${base} =`;
  $("vsAvgHead").title = `vs its own 1-year average — positive = ${w} is stronger than usual`;
  $("asof").textContent = "As of " + data.as_of;
  const fav = data.rows.filter((r) => r.favorable && r.watched);
  $("summary").textContent =
    `${data.rows.length} currencies · ${fav.length} favorable (≥ +${data.threshold_pct}% vs ${data.baseline_days}-day avg)`;

  const adv = advisoryByIso();
  const tbody = $("rows");
  tbody.innerHTML = "";
  updateCurSortIndicators();
  for (const r of sortedRates(data.rows)) {
    const tr = document.createElement("tr");
    if (r.favorable && r.watched) tr.className = "favorable";
    const sign = r.strength_pct >= 0 ? "pos" : "neg";
    const star = r.watched ? "" : ' <span title="not on watchlist" style="opacity:.4">·</span>';
    const pl = priceLevelForCurrency(r.code);
    // Advisory level of the currency's representative country, for the
    // hide-higher-risk filter (so the Iranian rial isn't row one).
    const ctry = currencyCountry(r.code);
    tr.dataset.adv = String((ctry && adv[ctry]) || 0);
    // Row links to the representative country's Travel Guide (shared currencies
    // point at a primary country, e.g. EUR→Germany; XCD has none, so no link).
    if (ctry) { tr.dataset.iso = ctry; tr.title = "See the " + countryName(ctry) + " travel guide →"; }
    const flag = currencyFlag(r.code, ctry);
    tr.innerHTML = `
      <td><div class="curcell"><span class="curflag">${flag}</span><div><span class="code">${esc(r.code)}</span>${star}<div class="name">${esc(r.name)}</div></div></div></td>
      <td class="num">${fmt(r.rate_now)}</td>
      <td class="num ${sign}">${r.strength_pct >= 0 ? "+" : ""}${r.strength_pct}%</td>
      <td class="num">${pl == null ? "—" : pl.toFixed(2) + " " + plTag(pl)}</td>
      <td class="num">${rangeMarker(r)}</td>`;
    tbody.appendChild(tr);
  }
  applyCurrencyFilter();
}

async function loadRates() {
  status("Fetching rates…");
  try {
    // Top Picks scoring always needs the USD dataset, even when the data tab
    // is viewing the world through another home currency.
    if (dataBase !== "USD" && !lastRates) lastRates = await getJSON("/api/rates");
    renderRates(await getJSON("/api/rates" + (dataBase !== "USD" ? "?base=" + dataBase : "")));
    status("");
  } catch (e) {
    status("Could not load rates: " + e.message, "err");
  }
}

// Populate the "My currency" picker once real data exists (USD first).
function buildBaseSelect() {
  const sel = $("dataBase");
  if (!sel || sel.options.length > 1 || !lastRates) return;
  const codes = ["USD", ...lastRates.rows.map((r) => r.code).sort()];
  sel.innerHTML = codes.map((c) =>
    `<option value="${esc(c)}"${c === dataBase ? " selected" : ""}>${esc(c)}</option>`).join("");
  sel.onchange = () => {
    dataBase = sel.value;
    localStorage.setItem("fx_database", dataBase);
    loadRates();
    loadIndex(activeDays);
  };
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

// ---- index chart window toggle --------------------------------------------
let activeDays = 365;

async function loadIndex(days) {
  activeDays = days;
  for (const b of document.querySelectorAll("#windowtoggle button")) {
    b.classList.toggle("active", parseInt(b.dataset.days, 10) === days);
  }
  try {
    lastIndexData = await getJSON("/api/index?days=" + days +
      (dataBase !== "USD" ? "&base=" + dataBase : ""));
    renderIndex(lastIndexData);
    syncURL();
  } catch (e) {
    $("chartsub").textContent = "Could not load chart: " + e.message;
  }
}

for (const b of document.querySelectorAll("#windowtoggle button")) {
  b.addEventListener("click", () => loadIndex(parseInt(b.dataset.days, 10)));
}

// ---- world heatmap ---------------------------------------------------------
// Country (ISO-3166 alpha-2) -> currency code. Provider covers ~180 currencies,
// so nearly every country gets real data. Unmapped/absent -> "no data" (gray).
const EUROZONE = ["AT","BE","CY","EE","FI","FR","DE","GR","IE","IT","LV","LT",
  "LU","MT","NL","PT","SK","SI","ES","HR","AD","MC","SM","VA","ME","XK"];
// Countries that use the US dollar itself (shown as flat for a US traveler).
const USD_USING = ["US","EC","SV","PA","TL","ZW","MH","FM","PW","TC","VG","BQ"];
const CUR_BY_ISO = (() => {
  const m = {
    // Americas
    CA:"CAD", MX:"MXN", GT:"GTQ", BZ:"BZD", HN:"HNL", NI:"NIO", CR:"CRC",
    CU:"CUP", DO:"DOP", HT:"HTG", JM:"JMD", TT:"TTD", BS:"BSD", BB:"BBD",
    CO:"COP", VE:"VES", GY:"GYD", SR:"SRD", PE:"PEN", BR:"BRL", BO:"BOB",
    PY:"PYG", CL:"CLP", AR:"ARS", UY:"UYU",
    // Europe (non-euro)
    GB:"GBP", IM:"GBP", JE:"GBP", GG:"GBP", CH:"CHF", LI:"CHF", NO:"NOK",
    SJ:"NOK", SE:"SEK", DK:"DKK", GL:"DKK", FO:"DKK", IS:"ISK", CZ:"CZK",
    PL:"PLN", HU:"HUF", RO:"RON", BG:"BGN", RS:"RSD", BA:"BAM", MK:"MKD",
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
    // CFA franc zones (real data via XOF / XAF)
    SN:"XOF", CI:"XOF", ML:"XOF", BF:"XOF", NE:"XOF", BJ:"XOF", TG:"XOF", GW:"XOF",
    CM:"XAF", TD:"XAF", CF:"XAF", CG:"XAF", GA:"XAF", GQ:"XAF",
  };
  for (const iso of EUROZONE) m[iso] = "EUR";
  for (const iso of USD_USING) m[iso] = "USD";
  return m;
})();
const USDLINK = "#bcd0e6"; // pale blue: uses the US dollar (flat for your dollar)

let worldGeo = null;

async function ensureWorld() {
  if (worldGeo) return worldGeo;
  // ?v= busts the day-long HTTP cache when the geometry changes (bump manually)
  worldGeo = await (await fetch("/world.geojson?v=7")).json();
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

const NODATA = "#e0e4e8";
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
      if (fill === "#e0e4e8") return "";              // unmarked — no dot
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
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${ariaLabel}">${paths}</svg>`;

  // Tap-for-detail on every map (the visited map keeps its toggle behavior).
  // Property assignment (not addEventListener) stays idempotent across re-renders,
  // and works on touch where hover tooltips don't.
  if (hostId !== "visitedMap") {
    host.onclick = (e) => {
      const p = e.target.closest("path");
      const iso = p && p.getAttribute("data-iso");
      if (iso && iso !== "-99") showCountryCard(iso, host);
    };
  } else {
    attachMapZoom(host, W, H);
  }
}

// ---- map zoom / pan (Wander List map) ---------------------------------------
// Tiny countries are impossible to tap at world scale: wheel (or pinch) zooms
// toward the cursor, dragging pans once zoomed, and +/−/⌂ buttons cover touch.
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
  const apply = (animate) => {
    if (animTimer) { clearTimeout(animTimer); animTimer = null; }
    st.w = Math.max(W / 8, Math.min(W, st.w));
    st.h = st.w * H / W;
    st.x = Math.max(0, Math.min(W - st.w, st.x));
    st.y = Math.max(0, Math.min(H - st.h, st.y));
    const zoomed = st.w < W - 0.5;
    // when zoomed, own the touch gestures (pan/pinch); at world view, let the
    // page scroll normally
    host.style.touchAction = zoomed ? "none" : "";
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
    st.h = st.w * H / W;
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

  // controls (re-created each render — innerHTML wiped the previous ones)
  if (!host.querySelector(".mapzoom")) {
    const ctr = document.createElement("div");
    ctr.className = "mapzoom";
    ctr.innerHTML = '<button type="button" data-z="in" title="zoom in">＋</button>'
      + '<button type="button" data-z="out" title="zoom out">－</button>'
      + '<button type="button" data-z="reset" title="reset view">⌂</button>';
    ctr.onclick = (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      e.stopPropagation();                  // don't toggle a country underneath
      if (b.dataset.z === "in") zoomAt(0.5, 0.5, 1.6, true);
      else if (b.dataset.z === "out") zoomAt(0.5, 0.5, 1 / 1.6, true);
      else { st.x = 0; st.y = 0; st.w = W; st.h = H; apply(true); }
    };
    host.appendChild(ctr);
  }

  host.onwheel = (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    // instant — wheel is already continuous; tweening each notch would lag
    zoomAt((e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height,
           e.deltaY < 0 ? 1.25 : 0.8, false);
  };

  // drag to pan (once zoomed) + two-finger pinch; a real drag suppresses the
  // click so it doesn't also toggle the country under the finger
  const ptrs = new Map();
  let pan = null, pinch = null, dragged = false;
  host.onpointerdown = (e) => {
    if (e.target.closest(".mapzoom")) return;
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
    } else if (pan && st.w < W - 0.5) {
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
  const row = cur && lastRates ? lastRates.rows.find((r) => r.code === cur) : null;
  const pl = priceLevel(iso);
  const advLvl = advisoryByIso()[iso];
  const cl = climate && climate[iso];
  const act = activities && activities[iso];

  const facts = [];
  if (cur) facts.push(`💱 ${esc(cur)}${row ? ` ${row.strength_pct >= 0 ? "+" : ""}${row.strength_pct}% vs avg` : (cur === "USD" ? " (US dollar)" : "")}`);
  if (pl != null) facts.push(`💰 price level ${pl.toFixed(2)} (${plWord(pl)})`);
  if (advLvl) facts.push(`⚠️ advisory Level ${advLvl}${advLvl === 4 ? " — Do Not Travel" : ""}`);
  if (cl && cl.best && cl.best.length) facts.push(`📅 best months: ${cl.best.map((m) => MON_ABBR[m - 1]).join(", ")}`);

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
}

function renderMap(rows, base) {
  base = base || "USD";
  const byCode = {};
  for (const r of rows) byCode[r.code] = r;
  const sgn = (p) => (p >= 0 ? "+" : "") + p + "%";

  let tracked = 0;
  drawMap("map", (f) => {
    const iso = f.properties.iso, cur = CUR_BY_ISO[iso];
    const row = cur && cur !== base ? byCode[cur] : null;
    if (cur === base) {
      return { fill: USDLINK,
        title: `${f.properties.name} — uses ${base} (your home currency — flat by definition)` };
    }
    if (row) {
      tracked++;
      return { fill: strengthColor(row.strength_pct),
        title: `${f.properties.name} — ${cur}: ${sgn(row.strength_pct)} vs 1yr avg` };
    }
    return { fill: NODATA, title: f.properties.name + " — not tracked" };
  }, base + " strength world heatmap");

  $("mapsub").textContent =
    `Greener = ${baseWord(base)} stronger vs that country's currency. Hover for detail · ${tracked} countries tracked.`;
  renderLegend(base);
}

function renderLegend(base) {
  $("legend").innerHTML =
    '<span>Weaker</span><span class="bar"></span><span>Stronger</span>' +
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
  if (!ppp) ppp = await (await fetch("/ppp.json")).json();
  return ppp;
}
function rateForCurrency(code) {
  if (code === "USD") return 1;
  const r = lastRates && lastRates.rows.find((x) => x.code === code);
  return r ? r.rate_now : null;
}
// price level vs US for a country: PPP factor / market rate. <1 = cheaper than US.
function priceLevel(iso) {
  if (!ppp || !ppp[iso]) return null;
  const cur = CUR_BY_ISO[iso];
  if (!cur) return null;
  const rate = rateForCurrency(cur);
  if (!rate) return null;
  const pl = ppp[iso].ppp / rate;
  // Guard against broken World Bank values / unit mismatches (e.g. stale PPP for
  // a redenominated currency). Real price levels sit roughly in [0.1, 4].
  if (pl < 0.08 || pl > 6) return null;
  return pl;
}
// Representative country for a currency (for the per-currency table column).
const PRIMARY_COUNTRY = { EUR: "DE", XOF: "SN", XAF: "CM", USD: "US", XCD: null };
function currencyCountry(code) {
  if (code in PRIMARY_COUNTRY) return PRIMARY_COUNTRY[code];
  for (const iso in CUR_BY_ISO) if (CUR_BY_ISO[iso] === code) return iso;
  return null;
}
// Flag for a currency row: the euro uses the EU flag, multi-country basket/
// franc codes fall back to a globe, everything else uses its country flag.
const CUR_SUPRA_FLAG = { EUR: "🇪🇺", XOF: "🌍", XAF: "🌍", XPF: "🌍", XCD: "🌍", XDR: "🌍" };
function currencyFlag(code, iso) {
  return CUR_SUPRA_FLAG[code] || (iso ? flagEmoji(iso) : "🌍");
}
function priceLevelForCurrency(code) {
  const iso = currencyCountry(code);
  return iso ? priceLevel(iso) : null;
}
function plWord(pl) { return pl < 0.55 ? "very cheap" : pl < 0.85 ? "cheap" : pl <= 1.15 ? "about the same" : "pricey"; }
function plTag(pl) {
  const w = plWord(pl);
  const cls = pl <= 0.85 ? "pos" : pl > 1.15 ? "neg" : "";
  return `<span class="${cls}" style="font-size:11px">${w}</span>`;
}
function affordColor(pl) {
  return pl <= 1 ? mix("#eef0f1", "#0a7d28", Math.min(1, (1 - pl) / 0.8))
                 : mix("#eef0f1", "#b00020", Math.min(1, (pl - 1) / 0.4));
}

// ---- wiring ---------------------------------------------------------------
$("refresh").addEventListener("click", () => { loadRates(); loadIndex(activeDays); });
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
const REGIONS = {
  AMER: "Americas", EUR: "Europe", MENA: "Middle East & N. Africa",
  ASIA: "Asia", AFRICA: "Africa (Sub-Saharan)", OCEANIA: "Oceania",
};
const ISO_REGION = (() => {
  const g = {
    AMER: "US CA MX GT BZ HN NI CR PA CU DO HT JM TT BS BB CO VE GY SR EC PE BR BO PY CL AR UY".split(" "),
    EUR: "GB IM JE GG CH LI NO SJ SE DK GL FO IS CZ PL HU RO BG RS BA MK AL MD UA BY RU TR AT BE CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES HR AD MC SM VA ME XK".split(" "),
    MENA: "IL PS SA AE QA KW BH OM JO LB SY IQ IR YE EG MA DZ TN LY".split(" "),
    ASIA: "CN JP KR IN PK BD LK NP AF MM TH VN KH LA MY SG ID PH BN HK MO TW MN KZ UZ TM KG TJ AZ AM GE BT".split(" "),
    AFRICA: "ZA NG KE GH ET TZ UG RW BI SD SS ER SO DJ AO MZ ZM BW NA SZ LS MW MG MU GM GN LR CD CV KM MR SC SN CI ML BF NE BJ TG GW CM TD CF CG GA GQ".split(" "),
    OCEANIA: "AU NZ FJ PG SB VU WS TO".split(" "),
  };
  const m = {};
  for (const r in g) for (const iso of g[r]) m[iso] = r;
  return m;
})();
const MONTHS = ["January","February","March","April","May","June","July",
  "August","September","October","November","December"];
const MON_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

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

// -- Tab: country guide (best time + things to do, one picker) ---------------
function renderGuide(iso) {
  // Drop the server-rendered crawler block now that we're rendering the real,
  // interactive guide (prevents duplicate content).
  const ssr = $("ssrGuide"); if (ssr) ssr.remove();
  // The country is the answer — put it in the page title, not just mid-page.
  const h2c = $("guideH2Country");
  if (h2c) h2c.innerHTML = " — " + flagEmoji(iso) + " " + esc(countryName(iso));
  renderGuideHero(iso);
  renderGuideVisa(iso);
  renderGuideSafety(iso);
  renderGuideAI(iso);
  renderCountryClimate(iso);
  renderActivity(iso);
  renderGuideStay(iso);
  syncURL();
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
  const ci = new Date(y, month - 1, 15);
  const co = new Date(ci); co.setDate(co.getDate() + 3);
  const f = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
                   "-" + String(d.getDate()).padStart(2, "0");
  return { checkin: f(ci), checkout: f(co) };
}
let _staySpotIdx = 0, _staySpotIso = null;   // chip selection, reset per country
function renderGuideStay(iso) {
  const host = $("guideStay");
  if (!host) return;
  host.hidden = true; host.innerHTML = "";
  ensureStayCoords().then((cc) => {
    if (ccGuideIso !== iso) return;                    // user switched country
    // Spots = the country's top places (from the curated gallery), each a
    // stay-search anchor. Tolerate the old single-anchor shape from cache.
    let spots = cc[iso];
    if (!spots) return;
    if (!Array.isArray(spots)) spots = [{ n: spots.near, ll: spots.ll }];
    spots = spots.filter((s) => s && s.ll && s.n);
    if (!spots.length) return;
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
    const hw = "https://www.hostelworld.com/search?search_keywords=" +
               encodeURIComponent(sp.n + ", " + countryName(iso));
    const btn = (href, label, sponsored) =>
      '<a class="staybtn" target="_blank" rel="' + (sponsored ? "sponsored nofollow noopener" : "nofollow noopener") +
      '" href="' + href + '">' + label + ' <span class="ext">↗</span></a>';
    const chips = spots.length > 1
      ? '<div class="staychips">' + spots.map((s, i) =>
          '<button type="button" class="staychip' + (i === _staySpotIdx ? " active" : "") +
          '" data-si="' + i + '">📍 ' + esc(s.n) + "</button>").join("") + "</div>"
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
    host.hidden = false;
  }).catch(() => {});
}

// Passport used for visa info = the "From" country chosen on Top Picks
// (your home country), defaulting to US.
function guidePassport() {
  const sel = $("valueOrigin");
  // Fall back to the persisted origin (not "US") so visa info follows the home
  // country even on a direct /guide/<slug> load, before Top Picks builds.
  return (sel && /^[A-Z]{2}$/.test(sel.value)) ? sel.value : travelOrigin();
}

// Visa FYI for this country — informational only, not part of any score.
// US passports link to the official State Dept page; other passports use the
// Passport Index matrix (loaded lazily on first use).
function renderGuideVisa(iso) {
  const host = $("guideVisa");
  if (!host) return;
  const passport = guidePassport();
  if (passport !== "US" && !visaMatrix) {       // need the matrix; load then redraw
    host.hidden = true;
    ensureVisaMatrix().then(() => { if (ccGuideIso === iso) renderGuideVisa(iso); }).catch(() => {});
    return;
  }
  const ppName = passport === "US" ? "US" : countryName(passport);
  const info = visaInfo(iso, passport);
  if (info && info.home) {
    host.hidden = false;
    host.innerHTML = `<span class="visa vfree">🛂 Home</span>
      <span class="guidevisa-txt">Your home country (${esc(ppName)} passport) — no visa needed.</span>`;
    return;
  }
  if (!info) { host.hidden = true; return; }
  host.hidden = false;
  const detail = info.meta.long + (info.note ? " · " + info.note : "");
  const link = /^https:\/\/travel\.state\.gov\//.test(info.link)
    ? ` <a href="${esc(info.link)}" target="_blank" rel="noopener">official details ↗</a>` : "";
  host.innerHTML = `<span class="visa ${info.meta.cls}">🛂 ${esc(info.meta.label)}</span>
    <span class="guidevisa-txt"><b>Visa · ${esc(ppName)} passport:</b> ${esc(detail)}.${link}
    Verify before booking — rules change.</span>`;
}

// Safety advisory for this country, from the traveler's home-country source
// (US State Dept by default, German Foreign Office for German travelers). Named
// so readers know whose guidance it is — advisories are politically colored.
const ADV_LABEL = { 1: "Level 1 · Normal precautions", 2: "Level 2 · Increased caution",
                    3: "Level 3 · Reconsider travel", 4: "Level 4 · Avoid travel" };
function renderGuideSafety(iso) {
  const host = $("guideSafety");
  if (!host) return;
  host.hidden = true;
  ensureAdvisories().then(() => {
    if (ccGuideIso !== iso) return;
    const lvl = advisoryByIso()[iso];
    if (!lvl) return;
    const src = advisories.source_name || "US State Dept";
    const url = advisories.source_url || "#";
    host.hidden = false;
    host.innerHTML = `<span class="advbadge advlvl${lvl}">🛡️ ${esc(ADV_LABEL[lvl] || "Level " + lvl)}</span>
      <span class="guidevisa-txt"><b>Safety · per ${esc(src)}:</b> follows your home country's official guidance
      (change it in the "From" selector). <a href="${esc(url)}" target="_blank" rel="noopener">official advisory ↗</a></span>`;
  }).catch(() => {});
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
      "&prop=pageimages&piprop=thumbnail|original&pithumbsize=1600&redirects=1&titles=" +
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
    return { thumb, full: (orig && !PHOTO_BAD.test(orig)) ? orig : thumb };
  } catch (e) { return null; }
}
const _heroCache = {};
async function iconicPhotos(iso) {
  if (iso in _heroCache) return _heroCache[iso];
  const settled = await Promise.all(photoSubjects(iso).map(wikiIconic));
  const out = [], seen = new Set();
  for (const p of settled) if (p && !seen.has(p.full)) { seen.add(p.full); out.push(p); }
  if (out.length) _heroCache[iso] = out;
  return out;
}
// The photo subject an activity row will use (shared with renderActivity so
// the hero's de-dupe stays in lockstep with what the thumbnails show).
function activitySubject(x) {
  const label = typeof x === "string" ? x : x.t;
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
               '<div class="herocount"></div>' : "");
    host.querySelector(".heroimg").addEventListener("click", openLightbox);
    if (multi) {
      host.querySelector(".heronav.prev").addEventListener("click", () => heroStep(-1));
      host.querySelector(".heronav.next").addEventListener("click", () => heroStep(1));
    }
    showHero();
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
}

// ---- lightbox: click a guide photo to view it full-screen ------------------
function ensureLightbox() {
  let lb = $("lightbox");
  if (lb) return lb;
  lb = document.createElement("div");
  lb.id = "lightbox"; lb.className = "lightbox"; lb.hidden = true;
  lb.innerHTML =
    '<button class="lbclose" type="button" aria-label="close">✕</button>' +
    '<button class="lbnav prev" type="button" aria-label="previous">‹</button>' +
    '<img class="lbimg" alt="">' +
    '<button class="lbnav next" type="button" aria-label="next">›</button>' +
    '<div class="lbcount"></div>';
  document.body.appendChild(lb);
  lb.addEventListener("click", (e) => {
    if (e.target === lb || e.target.classList.contains("lbclose")) closeLightbox();
  });
  lb.querySelector(".lbnav.prev").addEventListener("click", (e) => { e.stopPropagation(); heroStep(-1); });
  lb.querySelector(".lbnav.next").addEventListener("click", (e) => { e.stopPropagation(); heroStep(1); });
  return lb;
}
function openLightbox() {
  if (!heroUrls.length) return;
  const lb = ensureLightbox();
  lb.hidden = false;
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", lbKey);
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
}
function closeLightbox() {
  const lb = $("lightbox");
  if (lb) lb.hidden = true;
  lbSingle = null;
  document.body.style.overflow = "";
  document.removeEventListener("keydown", lbKey);
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
// Derive the original (full-resolution) file URL from a Commons thumb URL —
// strip "/thumb/" and the trailing "/NNNpx-Name" segment. Widened thumbs 400 on
// many files, but the original always exists.
const origFromThumb = (u) =>
  (u && u.indexOf("/thumb/") !== -1) ? u.replace("/thumb/", "/").replace(/\/[^/]+$/, "") : u;

// Several scenic photos for a country via Commons search of its curated query.
// Filters to landscape JPEG photos with a high-resolution ORIGINAL (so they
// stay crisp full-screen), dropping maps/flags/coats/diagrams/small/old scans.
// Returns [{thumb, full}] — carousel size + a larger size for the lightbox.
// One Commons search -> filtered [{thumb, full}]. Returns null on a failed/
// errored fetch (vs [] for "searched, nothing qualified") so callers can retry.
async function commonsSearch(query) {
  try {
    const api = "https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*" +
      "&generator=search&gsrnamespace=6&gsrlimit=24&gsrsearch=" + encodeURIComponent(query) +
      "&prop=imageinfo&iiprop=url|size|mime&iiurlwidth=1280";
    const r = await fetch(api);
    if (!r.ok) return null;
    const j = await r.json();
    const pages = Object.values((j.query || {}).pages || {}).sort((a, b) => (a.index || 0) - (b.index || 0));
    const out = [];
    for (const p of pages) {
      const ii = (p.imageinfo || [])[0];
      if (!ii || !ii.thumburl) continue;
      const ow = ii.width || 0, oh = ii.height || 0, ar = ow / (oh || 1);
      if (ii.mime === "image/jpeg" && !PHOTO_BAD.test(p.title) &&
          ow >= 1600 && oh >= 1000 && ar >= 1.2 && ar <= 2.4) {
        out.push({ thumb: ii.thumburl, full: ii.url });   // ii.url = full-res original
        if (out.length >= 8) break;
      }
    }
    return out;
  } catch (e) { return null; }
}
const _galleryCache = {};
async function photoGallery(iso) {
  if (iso in _galleryCache) return _galleryCache[iso];
  const skey = "fxgal_" + iso;
  try {
    const c = sessionStorage.getItem(skey);
    if (c) { const arr = JSON.parse(c); if (arr.length) return (_galleryCache[iso] = arr); }
  } catch (e) {}
  const q = (activities && activities[iso] && activities[iso].photo) || countryName(iso);
  let out = await commonsSearch(q);
  // Fall back to the country name if the landmark query came up short.
  const name = countryName(iso);
  if ((!out || out.length < 2) && name && name.toLowerCase() !== q.toLowerCase()) {
    const alt = await commonsSearch(name);
    if (alt && alt.length > (out ? out.length : 0)) out = alt;
  }
  out = out || [];
  // Only persist real results — caching an empty/failed fetch would leave the
  // country permanently photo-less for the session (the bug this fixes).
  if (out.length) {
    _galleryCache[iso] = out;
    try { sessionStorage.setItem(skey, JSON.stringify(out)); } catch (e) {}
  }
  return out;
}

const INTERESTS = ["Beach & islands", "Nature", "City", "Culture", "Adventure", "Food", "Shopping"];
function buildBestPickers() {
  const reg = $("bestRegion"), ctry = $("bestCountry"), intr = $("bestInterest");
  reg.innerHTML = '<option value="all">All regions</option>' +
    Object.keys(REGIONS).map((r) => `<option value="${r}">${REGIONS[r]}</option>`).join("");
  intr.innerHTML = '<option value="all">All interests</option>' +
    INTERESTS.map((i) => `<option value="${esc(i)}">${PROFILE_EMOJI[i] || ""} ${esc(i)}</option>`).join("");
  const fill = (keepCurrent) => {
    const region = reg.value, want = intr.value, prev = ctry.value;
    const list = Object.keys(climate)
      .filter((iso) => region === "all" || ISO_REGION[iso] === region)
      .filter((iso) => want === "all" ||
        ((activities[iso] && activities[iso].profile) || []).includes(want))
      .map((iso) => ({ iso, name: climate[iso].name }))
      .sort((a, b) => a.name.localeCompare(b.name));
    ctry.innerHTML = list.length
      ? list.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("")
      : '<option value="">No countries match — widen your filters</option>';
    if (!list.length) { $("guideHero").className = "guidehero empty"; $("bestDetail").innerHTML = ""; $("actDetail").innerHTML = ""; $("guideVisa").hidden = true; return; }
    // keep the same country if it still qualifies, else jump to the first match
    if (keepCurrent && list.some((c) => c.iso === prev)) ctry.value = prev;
    renderGuide(ctry.value);
  };
  reg.onchange = () => fill(true);
  intr.onchange = () => fill(true);
  ctry.onchange = () => renderGuide(ctry.value);
  fill(false);
  if ([...ctry.options].some((o) => o.value === "JP")) { ctry.value = "JP"; renderGuide("JP"); }
  enhanceSelect(ctry);
}

// Open the guide tab focused on a specific country (used by the map detail card).
async function openGuideFor(iso, push) {
  await activateTab("guide", push);
  const ctry = $("bestCountry");
  if ([...ctry.options].some((o) => o.value === iso)) ctry.value = iso;
  if (ctry._sync) ctry._sync();
  renderGuide(iso);
  setDocMeta(guideTitle(iso), SITE_ORIGIN + guidePath(iso));
}

// Classify each month into peak / shoulder / off season by weather, relative to
// the country's own range. Peak = best weather (busiest, priciest); off = worst
// (cheapest, fewest crowds).
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
const fmtMonths = (arr) => (arr.length ? arr.map((m) => MON_ABBR[m - 1]).join(", ") : "—");

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
  if (!c) { $("bestDetail").textContent = "No data."; return; }
  const bestSet = new Set(c.best);
  const seas = seasons(c.scores);
  const peakM = [], offM = [];
  seas.forEach((s, i) => { if (s === "peak") peakM.push(i + 1); else if (s === "off") offM.push(i + 1); });

  // Curated month-level hazards (smoke season, monsoon, hurricanes…) — a blunt
  // peak/off-peak label hides these, so they get their own markers and lines.
  const hazards = (activities && activities[iso] && activities[iso].hazards) || [];
  const hzByMonth = {};
  for (const h of hazards) for (const m of h.months || []) hzByMonth[m] = h.note;

  const chips = c.best.map((m) => `<span class="chip2">${MON_ABBR[m - 1]}</span>`).join("");
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
    return `<div class="${col}" data-mn="${i + 1}" title="${MONTHS[i]}: ${t != null ? fmtTemp(t) + " avg · " : ""}comfort ${s == null ? "n/a" : s + "/100"} · ${seas[i]} season${hz ? " · ⚠️ " + esc(hz) : ""} · click to plan for ${MONTHS[i]}">
      <div class="mscore">${head}</div>
      <div class="fill" style="height:${h}%;background:${t != null ? tempColor(t) : comfortColor(s)}"></div>
      <div class="mlabel ${seas[i]}">${MON_ABBR[i]}${hz ? `<span class="hzmark" data-tip="⚠️ ${esc(hz)}" title="">⚠️</span>` : ""}</div></div>`;
  }).join("");
  const hasTemps = temps.some((t) => t != null);
  const unitToggle = hasTemps
    ? `<div class="tempunit" role="group" aria-label="temperature unit">
         <button type="button" data-u="C" class="${tempUnit() === "C" ? "active" : ""}">°C</button>
         <button type="button" data-u="F" class="${tempUnit() === "F" ? "active" : ""}">°F</button>
       </div>` : "";

  const hazardLines = hazards.map((h) =>
    `<div class="hazardline">⚠️ <b>${monthSpan(h.months)}:</b> ${esc(h.note)}</div>`).join("");

  $("bestDetail").innerHTML = `
    <div class="besthead">
      <h3>${esc(c.name)} <span class="muted">· ${REGIONS[ISO_REGION[iso]] || "—"}</span></h3>
      ${unitToggle}
    </div>
    <div class="monthslabel">${c.curated ? "📅 Curated best months" : "📅 Best weather"}:</div>
    <div class="chips">${chips}</div>
    <div class="seasons">
      <span><b class="peak">☀️ Peak</b> (best weather, busiest &amp; priciest): ${fmtMonths(peakM)}</span>
      <span><b class="off">💸 Off-peak</b> (cheapest, fewest crowds): ${fmtMonths(offM)}</span>
    </div>
    ${hazardLines}
    ${hasTemps ? `<div class="monthslabel">🌡️ Avg temperature (${tempUnit() === "F" ? "°F" : "°C"}) · taller bar = comfier month · color = temp: <span style="color:#2b6cb0;font-weight:700">cold</span> → <span style="color:#0a7d28;font-weight:700">ideal</span> → <span style="color:#df8a10;font-weight:700">warm</span> → <span style="color:#be1218;font-weight:700">hot</span></div>
    <div class="monthslabel seaskey">Month labels: <span style="color:var(--green);font-weight:700">peak season</span> · <span style="color:var(--amber)">shoulder</span> · <span style="color:#aaa">off-season</span></div>` : ""}
    <div class="bars">${bars}</div>`;
  for (const b of document.querySelectorAll("#bestDetail .tempunit button"))
    b.addEventListener("click", () => setTempUnit(b.dataset.u));
}

// (The standalone by-month map merged into "Where to go now" as a map mode.)

// ===========================================================================
//  Travel advisories
// ===========================================================================
// Which government's advisories to use, driven by the home country (German
// travelers get the Auswärtiges Amt; everyone else the US State Dept for now).
// Government advisories reflect that country's foreign policy, so following the
// traveler's own government is more relevant + less US-skewed.
let advisories = null;
const _advBySource = {};
function advisorySource() { return travelOrigin() === "DE" ? "de" : "us"; }
async function ensureAdvisories() {
  const src = advisorySource();
  if (!_advBySource[src]) _advBySource[src] = await getJSON("/api/advisories?source=" + src);
  advisories = _advBySource[src];
  return advisories;
}
// Re-fetch when the home country moves to a different advisory source. Returns
// true if the active source changed (so callers can re-render).
async function reloadAdvisoriesForOrigin() {
  const src = advisorySource();
  if (advisories && advisories.source === src) return false;
  await ensureAdvisories();
  return true;
}
const LVL_COLOR = { 1: "#0a7d28", 2: "#c9a200", 3: "#d4730a", 4: "#b00020" };

function renderAdvisories() {
  const byIso = {};
  for (const it of advisories.items) if (it.iso) byIso[it.iso] = it;
  drawMap("advMap", (f) => {
    const it = byIso[f.properties.iso];
    return it
      ? { fill: LVL_COLOR[it.level], title: `${it.country} — Level ${it.level}: ${it.level_text}` }
      : { fill: NODATA, title: f.properties.name + " — no advisory data" };
  }, (advisories.source_name || "Travel") + " advisory levels");

  $("advSub").innerHTML =
    `${advisories.count} advisories from the <b>${esc(advisories.source_name || "US State Dept")}</b> ` +
    `(follows your home country). Green = safest (Level 1), red = avoid travel (Level 4). ` +
    `<span class="muted">Government advisories reflect each country's own foreign policy.</span>`;
  $("advLegend").innerHTML = [1, 2, 3, 4]
    .map((l) => `<span><span class="swatch" style="background:${LVL_COLOR[l]}"></span>L${l}</span>`).join(" ");

  markSort("#advTable", advSort);
  $("advRows").innerHTML = sortRows(advisories.items, advSort, ADV_GET).map((it) => {
    const lvl = parseInt(it.level, 10) || 0;
    const safeLink = /^https:\/\//.test(it.link || "") ? it.link : "";
    const guideAttr = it.iso ? ` data-iso="${esc(it.iso)}" title="See the ${esc(it.country)} travel guide →"` : "";
    return `
    <tr data-lvl="${lvl}"${guideAttr}><td>${esc(it.country)}</td>
      <td><span class="lvl lvl${lvl}">Level ${lvl}</span></td>
      <td>${esc(it.level_text)}${safeLink ? ` · <a href="${esc(safeLink)}" target="_blank" rel="noopener">details</a>` : ""}</td>
    </tr>`;
  }).join("");
  applyAdvFilter();
}

// ===========================================================================
//  Cost of living (PPP) tab — its own map + ranked table
// ===========================================================================
function renderAfford() {
  let n = 0;
  drawMap("affMap", (f) => {
    const pl = priceLevel(f.properties.iso);
    if (pl == null) return { fill: NODATA, title: f.properties.name + " — no price data" };
    n++;
    return { fill: affordColor(pl),
      title: `${f.properties.name} — price level ${pl.toFixed(2)} (${plWord(pl)} vs US)` };
  }, "Cost of living (price level vs US)");

  $("affSub").textContent =
    `Below 1.00 = cheaper than the US (a dollar buys more). World Bank PPP ÷ live rate · ${n} countries.`;
  $("affLegend2").innerHTML =
    '<span>Pricey</span><span class="bar"></span><span>Cheap</span>' +
    '<span style="margin-left:6px"><span class="swatch"></span>No data</span>';

  // Ranked cheapest-first table.
  const rows = [];
  for (const iso in CUR_BY_ISO) {
    const pl = priceLevel(iso);
    if (pl == null) continue;
    const name = (ppp[iso] && ppp[iso].name) || (climate && climate[iso] && climate[iso].name) || iso;
    rows.push({ iso, name, cur: CUR_BY_ISO[iso], pl });
  }
  markSort("#affTable", affSort);
  $("affRows").innerHTML = sortRows(rows, affSort, AFF_GET).map((r) => {
    const cls = r.pl <= 0.85 ? "pos" : r.pl > 1.15 ? "neg" : "";
    return `<tr data-iso="${esc(r.iso)}" title="See the ${esc(r.name)} travel guide →"><td>${esc(r.name)}</td><td>${esc(r.cur)}</td>
      <td class="num ${cls}">${r.pl.toFixed(2)}</td>
      <td class="num">$${Math.round(100 / r.pl)} of US goods</td>
      <td>${plWord(r.pl)}</td></tr>`;
  }).join("");
  applyAffordFilter();
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
  $("weightRows").innerHTML = WEIGHT_DEFS.map((w) => `
    <div class="prirow"><span class="prilabel">${w.label}</span>
      <span class="prigroup" data-w="${w.key}">${PRI_LEVELS.map(([v, t]) =>
        `<button type="button" data-v="${v}" class="${priorities[w.key] === v ? "active" : ""}">${t}</button>`).join("")}</span>
    </div>`).join("");
  $("weightRows").onclick = (e) => {
    const btn = e.target.closest("button");
    const grp = e.target.closest(".prigroup");
    if (!btn || !grp) return;
    priorities[grp.dataset.w] = btn.dataset.v;
    savePriorities();
    grp.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === btn));
    renderValue();
  };
}

function advisoryByIso() {
  const m = {};
  if (advisories) for (const it of advisories.items) if (it.iso) m[it.iso] = it.level;
  return m;
}

// ---- home currency for Top Picks --------------------------------------------
// "From" picks the country (flights + what "cheap" is measured against);
// "In" picks the money (FX column + the currency prices are shown in). It
// follows the From country automatically until the user overrides it — an
// American expat hopping countries can pin USD and it stays pinned.
let homeBase = "USD";        // currency code the main tab reasons in
let homeRates = null;        // /api/rates dataset for that base (= lastRates for USD)
let homeManual = localStorage.getItem("fx_homecur_manual") === "1";
const _baseRatesCache = {};

function homeCurAuto() { return CUR_BY_ISO[$("valueOrigin").value || "US"] || "USD"; }

// ---- single "traveling from" origin, shared across the whole site ----------
// One source of truth: Top Picks "From", Explore-the-Data flights "From", the
// Travel Guide passport (visa), and the AI prompts all read it — so changing it
// in any tab carries everywhere. Persisted so it sticks across tabs and reloads.
function travelOrigin() { return localStorage.getItem("fx_origin") || "US"; }

function setTravelOrigin(iso) {
  if (!iso || !/^[A-Z]{2}$/.test(iso)) return;
  localStorage.setItem("fx_origin", iso);
  // Mirror into both origin selects (each only if it carries that option) and
  // refresh their comboboxes — programmatic, so this doesn't re-fire change.
  for (const id of ["valueOrigin", "flightOrigin"]) {
    const sel = $(id);
    if (sel && [...sel.options].some((o) => o.value === iso)) {
      if (sel.value !== iso) sel.value = iso;
      if (sel._sync) sel._sync();
    }
  }
  if (!homeManual) setHomeCur(homeCurAuto(), false);   // currency follows unless pinned
  loadValueFlights(false);                             // Top Picks fares (re-renders)
  renderValue();                                       // immediate: new affordability anchor
  if (loaded.flights) loadFlights();                   // Explore-the-Data fares
  // Safety source follows the home country too (German travelers -> Auswärtiges
  // Amt). If it changed, re-score Top Picks and refresh the advisory map + guide.
  reloadAdvisoriesForOrigin().then((changed) => {
    if (!changed) return;
    if (loaded.value) renderValue();
    if (advisories && document.getElementById("advMap")) renderAdvisories();
    if (ccGuideIso) renderGuideSafety(ccGuideIso);
  }).catch(() => {});
  // guide visa + AI + temperature units (default unit follows the home country)
  if (ccGuideIso) { renderGuideVisa(ccGuideIso); renderGuideAI(ccGuideIso); renderCountryClimate(ccGuideIso); renderGuideSafety(ccGuideIso); }
  syncURL();
}

async function loadHomeRates() {
  if (homeBase === "USD") { homeRates = lastRates; return; }
  if (_baseRatesCache[homeBase]) { homeRates = _baseRatesCache[homeBase]; return; }
  homeRates = null;   // FX column shows neutral until the dataset lands
  const data = await getJSON("/api/rates?base=" + homeBase);
  _baseRatesCache[homeBase] = data;
  if (data.base === homeBase) homeRates = data;   // ignore stale responses
}

function setHomeCur(code, manual) {
  homeBase = code;
  homeManual = manual;
  localStorage.setItem("fx_homecur", code);
  localStorage.setItem("fx_homecur_manual", manual ? "1" : "0");
  const sel = $("homeCur");
  if (sel && sel.value !== code) sel.value = code;
  if (sel && sel._sync) sel._sync();
  loadHomeRates().catch(() => {}).then(() => { if (loaded.value) renderValue(); });
}

function initHomeCur() {
  const sel = $("homeCur");
  if (!sel || sel.options.length > 1 || !lastRates) return;
  const codes = ["USD", ...lastRates.rows.map((r) => r.code).sort()];
  sel.innerHTML = codes.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
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
  const cur = CUR_BY_ISO[iso];
  // FX strength is judged from the chosen home currency's dataset. While a
  // non-USD dataset is still loading, FX reads neutral rather than wrong.
  const row = cur && cur !== homeBase && homeRates
    ? homeRates.rows.find((r) => r.code === cur) : null;
  const cl = climate && climate[iso];

  const w = loadWeights();
  // Sub-scores (kept for tooltips/detail): cheapness maxes once prices are ~1/3
  // of home prices; FX maxes at +8% vs the 1-year average.
  const aff = clamp100(((1.3 - pl) / 0.95) * 100);
  const fx = row ? clamp100(50 + row.strength_pct * 6.25) : 50;
  const comps = {
    // Affordability = mostly structural cost of living, nudged by FX timing.
    afford: clamp100(aff * 0.7 + fx * 0.3),
    safe: advLvl ? { 1: 100, 2: 70, 3: 35 }[advLvl] : 70,
    wx: cl && cl.scores[month - 1] != null ? cl.scores[month - 1] : 50,
  };
  let fare = null, fareEst = false, fareBase = null;
  if (fares && fares.prices[iso] != null) {
    fare = fares.prices[iso];
    fareEst = fares.est && fares.est.has(iso);
    fareBase = fares.expected ? fares.expected(iso) : null;
    // Deal vs the typical fare for that distance: at baseline = 70 (B),
    // ~20% below = A, ~30% below = A+, ~20% above = D, ~40%+ above = F.
    // Falls back to min-max cheapness when there's no fitted baseline.
    comps.fly = fareBase ? clamp100(70 + (1 - fare / fareBase) * 100)
      : fares.max > fares.min
        ? clamp100(((fares.max - fare) / (fares.max - fares.min)) * 100) : 50;
  }
  // Weighted mean over the components this country actually has.
  let num = 0, den = 0;
  for (const k in comps) { num += (w[k] || 0) * comps[k]; den += (w[k] || 0); }
  const value = den ? clamp100(num / den) : 0;
  return { iso, name: (cl && cl.name) || (ppp[iso] && ppp[iso].name) || iso,
           afford: comps.afford, safe: comps.safe, wx: comps.wx,
           fly: comps.fly, fare, fareEst, fareBase, advLvl, value,
           pl, fx: row ? row.strength_pct : null };
}

let valueMapMode = "score";

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

// Returns { prices, est:Set, min, max, expected } — known fares plus
// distance-based estimates for every mappable country, or null when no fare
// data is loaded. expected(iso) is the fitted "typical fare for that distance"
// — the baseline a real fare is judged against (deal vs ripoff).
function buildFareContext() {
  if (!(flightsData && flightsData.configured && flightsData.by_country)) return null;
  const prices = { ...flightsData.by_country };
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
    for (const iso in CUR_BY_ISO) {
      if (prices[iso] != null || !C[iso] || iso === flightsData.origin) continue;
      const e = a + b * distKm(o, C[iso]);
      prices[iso] = Math.round(Math.max(lo, Math.min(hi, e)));
      est.add(iso);
    }
  }
  const vals = Object.values(prices);
  if (!vals.length) return null;
  return { prices, est, min: Math.min(...vals), max: Math.max(...vals), expected };
}

async function loadValueFlights(silent) {
  const origin = $("valueOrigin").value || "US";
  try {
    const data = await getJSON("/api/flights?origin=" + encodeURIComponent(origin));
    if (!data.configured) {
      if (!silent) status("Flight prices need TRAVELPAYOUTS_TOKEN on the server — see the Flights tab.", "err");
    } else {
      flightsData = data;
      if (!silent) status(`Average fares from ${data.origin_name || origin} folded into the score.`, "ok");
    }
  } catch (e) {
    if (!silent) status("Could not load flights: " + e.message, "err");
  }
  renderValue();
}

// ---- searchable dropdowns (custom combobox over a native <select>) ---------
// Non-invasive: the native select stays the source of truth (existing .value /
// change logic is untouched); we overlay a type-to-filter input + list.
function enhanceSelect(sel) {
  if (!sel || sel.dataset.combo || sel.options.length < 10) return;
  sel.dataset.combo = "1";
  const wrap = document.createElement("span");
  wrap.className = "combo";
  const input = document.createElement("input");
  input.type = "text"; input.className = "combo-input"; input.autocomplete = "off";
  input.setAttribute("role", "combobox"); input.placeholder = "Type to search…";
  input.setAttribute("aria-expanded", "false");
  const list = document.createElement("ul");
  list.className = "combo-list"; list.hidden = true;
  const setOpen = (open) => { list.hidden = !open; input.setAttribute("aria-expanded", String(open)); };
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
      ? opts.map((o) => `<li class="combo-opt" data-val="${esc(o.value)}">${esc(o.textContent.trim())}</li>`).join("")
      : '<li class="combo-opt muted">No matches</li>';
    active = -1;
  };
  const choose = (val) => {
    if (sel.value !== val) { sel.value = val; sel.dispatchEvent(new Event("change", { bubbles: true })); }
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
    if (items[active]) items[active].scrollIntoView({ block: "nearest" });
  });
  list.addEventListener("mousedown", (e) => {   // mousedown beats the input blur
    const li = e.target.closest(".combo-opt[data-val]");
    if (li) { e.preventDefault(); choose(li.dataset.val); }
  });
  new MutationObserver(sync).observe(sel, { childList: true });  // options rebuilt -> resync label
  sync();
}
function resyncCombos() {
  document.querySelectorAll("select[data-combo]").forEach((s) => s._sync && s._sync());
}

function buildValueTab() {
  const reg = $("valueRegion"), mon = $("valueMonth");
  reg.innerHTML = '<option value="all">All regions</option>' +
    Object.keys(REGIONS).map((r) => `<option value="${r}">${REGIONS[r]}</option>`).join("");
  mon.innerHTML = MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("");
  mon.value = String(curMonth());   // "I'm going in" defaults to the month it is now
  reg.onchange = renderValue;
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
      for (const x of document.querySelectorAll("#valueMapMode button"))
        x.classList.toggle("active", x === b);
      valueMapMode = b.dataset.vm;
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
let lastGems = [];   // current hidden-gems list, for the 💎 surprise button
function buildAIPrompt() {
  const month = lastPicksMonth || curMonth();
  const origin = $("valueOrigin");
  const originName = origin && origin.selectedOptions[0] ? origin.selectedOptions[0].textContent : "the US";
  const region = $("valueRegion").value;
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
  if (visited && visited.size) lines.push("ALREADY BEEN (skip): " + [...visited].map(countryName).join(", "));
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
    if (s.pl != null) {
      const ratio = 1 / s.pl;
      aff = ratio >= 1.12 ? `your money goes ~${ratio >= 1.75 ? (Math.round(ratio * 10) / 10) + "×" : Math.round((ratio - 1) * 100) + "%"} further than home`
          : s.pl <= 1.1 ? "prices about the same as home" : "pricier than home";
    }
    if (s.fx != null && Math.abs(s.fx) >= 2) aff += ` (${homeBase} ${s.fx >= 0 ? "+" : ""}${s.fx}% vs its 1-yr avg)`;
    const fl = (s.fare != null && !s.fareEst && s.fareBase != null)
      ? (s.fare / s.fareBase <= 0.95 ? "cheaper than usual for the distance"
         : s.fare / s.fareBase >= 1.05 ? "pricier than usual for the distance" : "about average for the distance")
      : null;
    lines.push(`${i + 1}. ${s.name} — overall ${grade(s.value)}`);
    if (aff) lines.push(`   - Affordability ${grade(s.afford)}: ${aff}`);
    lines.push(`   - Safety: ${ADV_TEXT[s.advLvl] || "no current advisory"}`);
    if (vi) lines.push(`   - Visa (${passport === "US" ? "US" : countryName(passport)} passport): ${vi.meta.long}${vi.note ? " — " + vi.note : ""}`);
    if (best) lines.push(`   - Best months: ${best}; ${monthName} is ${seas === "peak" ? "peak season" : seas === "off" ? "off-season" : "shoulder season"}`);
    if (hz.length) lines.push(`   - ${monthName} heads-up: ${hz.join("; ")}`);
    if (acts.length) lines.push(`   - Known for: ${acts.join("; ")}`);
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
  host.hidden = false;
  host.innerHTML =
    '<div class="airow">'
    + '<button type="button" class="aiact" data-act="copy">📋 Copy prompt</button>'
    + '<a class="aiact" href="' + cg + '" target="_blank" rel="noopener">Open in ChatGPT ↗</a>'
    + '<a class="aiact" href="' + cla + '" target="_blank" rel="noopener">Open in Claude ↗</a>'
    + '<a class="aiact" href="' + px + '" target="_blank" rel="noopener">Open in Perplexity ↗</a>'
    + '</div>'
    + '<textarea class="aitext" readonly rows="9">' + esc(prompt) + '</textarea>'
    + '<p class="hint">“Copy prompt” grabs the full version — paste into ChatGPT, Claude, Gemini, Grok, Perplexity, or any AI. The buttons open a new chat with it pre-filled.</p>';
  host.querySelector('[data-act="copy"]').onclick = () => copyText(prompt);
  // Also copy when opening an AI, so the full prompt is ready to paste if the
  // pre-fill link is truncated by length limits.
  host.querySelectorAll("a.aiact").forEach((el) =>
    el.addEventListener("click", () => copyText(prompt, true)));
  host.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function exportAIPrompt() {
  if (!lastPicks.length) { status("Load some picks first.", "err"); return; }
  // Make sure visa data for the chosen passport is loaded so the export can
  // embed it (US uses visa.json; other From countries need the matrix).
  if (guidePassport() !== "US") await ensureVisaMatrix().catch(() => {});
  renderAIPanel($("aiPanel"), buildAIPrompt());
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
  const origin = $("valueOrigin");
  const originName = origin && origin.selectedOptions[0] ? origin.selectedOptions[0].textContent : "the US";

  const lines = [];
  lines.push("I'm planning a trip to " + name + " and used a travel-value tool (WanderGrade) for the basics. Use the info below (don't re-derive it) to help me build a plan.");
  lines.push("");
  lines.push("DESTINATION: " + name);
  lines.push("WHEN: " + monthName);
  lines.push("FROM: " + originName + (homeBase !== "USD" ? " (budgeting in " + homeBase + ")" : ""));
  if (prof.length) lines.push("KNOWN FOR: " + prof.join(", "));
  if (vi) lines.push("VISA (" + (passport === "US" ? "US" : countryName(passport)) + " passport): " + vi.meta.long + (vi.note ? " — " + vi.note : ""));
  if (best) lines.push("BEST MONTHS: " + best + "; " + monthName + " is " + (seas === "peak" ? "peak season" : seas === "off" ? "off-season" : "shoulder season"));
  if (hz.length) lines.push(monthName + " HEADS-UP: " + hz.join("; "));
  if (acts.length) lines.push("HIGHLIGHTS: " + acts.join("; "));
  lines.push("");
  lines.push("USING THE ABOVE, please:");
  lines.push("- Recommend specific cities/regions and how many days in each");
  lines.push("- Draft a day-by-day itinerary for a ~5–7 day trip");
  lines.push("- Estimate a rough daily budget and total cost from " + originName);
  lines.push("- Tell me when to book flights and which neighborhoods to stay in");
  lines.push("- Work the " + monthName + " season notes above (peak/off, crowds, any heads-up) into the timing and pacing");
  lines.push("");
  lines.push("Source: WanderGrade — " + SITE_ORIGIN + guidePath(iso));
  return lines.join("\n");
}

function renderGuideAI(iso) {
  const host = $("guideAI");
  if (!host) return;
  const name = countryName(iso);
  host.innerHTML = '<button id="guideAIBtn" type="button" class="aibtn"'
    + ' title="Generate a ready-to-use AI planning prompt for ' + esc(name) + '">'
    + '✨ Plan ' + esc(name) + ' with AI →</button>'
    + '<div id="guideAIPanel" class="aipanel" hidden></div>';
  $("guideAIBtn").onclick = () => openGuideAI(iso);
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
// all markable on the Wander List. They don't participate in scoring/guides —
// no currency/climate data — just the map, chips, counts and share card.
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
const SAFE_GRADE = { 1: "A", 2: "B", 3: "D" };
const ADV_TEXT = { 1: "Level 1: Exercise Normal Precautions", 2: "Level 2: Exercise Increased Caution",
                   3: "Level 3: Reconsider Travel", 4: "Level 4: Do Not Travel" };
function safetyPill(advLvl) {
  const g = advLvl ? SAFE_GRADE[advLvl] : "B";
  return `<span class="gr ${gradeCls(g)}" title="${esc(advLvl ? ADV_TEXT[advLvl] : "No US advisory published — treated as Level 2")}">${g}</span>`;
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
function passesFloor(s, floor) {
  return floor === "any" || (floor === "a" ? s.advLvl === 1 : s.advLvl !== 3);
}

// Compose a human sentence from the score ingredients — answers, not numbers.
function whyLine(s, month) {
  const money = homeBase === "USD" ? "your dollar" : "your " + homeBase;
  const bits = [];
  if (s.pl != null) {
    const ratio = 1 / s.pl;
    if (ratio >= 1.75) bits.push(`${money} goes ~${(Math.round(ratio * 10) / 10).toFixed(1).replace(/\.0$/, "")}× further than at home`);
    else if (ratio >= 1.12) bits.push(`${money} goes ~${Math.round((ratio - 1) * 100)}% further than at home`);
    else if (s.pl <= 1.1) bits.push("prices about the same as home");
    else bits.push("pricier than home");
  }
  if (s.fx != null && s.fx >= 2) bits.push(`${money} is unusually strong there right now`);
  if (s.wx >= 75) bits.push(`great weather in ${MONTHS[month - 1]}`);
  else if (s.wx >= 55) bits.push(`decent weather in ${MONTHS[month - 1]}`);
  if (s.advLvl === 1) bits.push("safest travel rating");
  else if (s.advLvl === 3) bits.push("⚠️ has a reconsider-travel advisory");
  if (s.fare != null && !s.fareEst && s.fareBase != null) {
    const r = s.fare / s.fareBase;
    bits.push(r <= 0.95 ? "flights cheaper than usual"
            : r >= 1.05 ? "flights pricier than usual" : "flights about average");
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

// Color-differentiated arrow for a price vs a baseline: green ▼ below,
// red ▲ above, gray ≈ about. Used in the Flights data table.
function priceArrow(value, baseline, label) {
  if (value == null || !baseline) return "";
  const r = value / baseline;
  if (r <= 0.95) return `<span class="farearrow dn" title="below ${esc(label)}">▼</span>`;
  if (r >= 1.05) return `<span class="farearrow up" title="above ${esc(label)}">▲</span>`;
  return `<span class="farearrow flat" title="about ${esc(label)}">≈</span>`;
}

// Render a ranked list as a compact report-card table. gem=true marks the
// hidden-gems list, which ranks #1..#N just like the popular table (the 💎
// lives in the section title). The why-sentence moves to the row tooltip so
// the table itself stays scannable.
function renderGradeTable(host, list, month, gem, sortable, state = pickSort) {
  if (!host) return;
  if (!list.length) { host.innerHTML = "<p class='hint'>No destinations match these filters.</p>"; return; }
  // Sortable tables reorder the same set by the chosen column; rank (#i+1)
  // renumbers to match. Each table gets its own sort state (picks vs gems).
  if (sortable) list = sortRows(list, state, PICK_GET);
  const sa = (sk) => sortable
    ? ` data-sk="${sk}" data-sortdir="${state.key === sk ? (state.asc ? "asc" : "desc") : ""}"` : "";
  const sc = sortable ? " sortable" : "";
  const rows = list.map((s, i) => {
    const hz = hazardsFor(s.iso, month);
    const wxTitle = `${s.wx}/100 weather comfort in ${MONTHS[month - 1]}` +
      (hz.length ? " — ⚠️ " + hz.map((h) => h.note).join("; ") : "");
    const iso = esc(s.iso);
    return `<tr data-iso="${iso}" title="${esc(whyLine(s, month))}" style="--i:${i}">
      <td class="rank">#${i + 1}</td>
      <td class="dest">${flagEmoji(s.iso)} ${esc(s.name)}</td>
      <td class="scell" data-go="afford" data-iso="${iso}">${gradePill(s.afford, affordTitle(s))}</td>
      <td class="scell" data-go="advisory" data-iso="${iso}">${safetyPill(s.advLvl)}</td>
      <td class="scell" data-go="weather" data-iso="${iso}">${gradePill(s.wx, wxTitle + " · click for the month-by-month guide")}${hz.length ? `<span class="hzmark" data-tip="${esc(hz.map((h) => "⚠️ " + monthSpan(h.months) + ": " + h.note).join("\n"))}" title="">⚠️</span>` : ""}</td>
      <td class="scell" data-go="flights" data-iso="${iso}">${s.fare == null ? '<span class="muted">—</span>'
            : (s.fareEst || s.fareBase == null) ? '<span class="muted" title="estimated — no cached fare; click for the Flights tab">~</span>'
            : gradePill(s.fly, "Flight deal vs the typical fare for this distance · click for exact prices")}</td>
      <td class="overall">${gradePill(s.value, `Overall value score ${s.value}/100`, "big")}<span class="grnum" title="value score out of 100">${s.value}</span></td>
    </tr>`;
  }).join("");
  host.innerHTML = `<table class="gradetable">
    <thead><tr><th></th><th class="dest${sc}"${sa("dest")}>Destination</th>
      <th class="${sc.trim()}"${sa("afford")} title="how far your money goes — daily prices vs home, plus how strong your currency is right now">💰 Affordability</th>
      <th class="${sc.trim()}"${sa("safety")} title="US State Dept advisory level">🛡️ Safety</th>
      <th class="${sc.trim()}"${sa("weather")} title="weather comfort for your chosen month">🌤️ Weather</th>
      <th class="${sc.trim()}"${sa("flights")} title="flight deal: fare vs the typical price for this distance (exact prices in the Flights tab)">✈️ Flights</th>
      <th class="${sc.trim()}"${sa("overall")} title="everything blended, weighted by your priorities">Overall</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  if (!reducedMotion()) host.querySelectorAll(".grnum").forEach(countUp);
}
// Tooltip for the merged Affordability cell: explains both the price level and
// the FX timing, both measured against the traveler's home country/currency.
function affordTitle(s) {
  const parts = [];
  if (s.pl != null) {
    const ratio = 1 / s.pl;
    parts.push(ratio >= 1.1 ? `daily prices ~${Math.round((ratio - 1) * 100)}% cheaper than home`
             : s.pl <= 1.1 ? "daily prices about the same as home" : `pricier than home`);
  }
  if (s.fx != null && Math.abs(s.fx) >= 1)
    parts.push(`your ${homeBase} is ${s.fx >= 0 ? "+" : ""}${s.fx}% vs its 1-yr average`);
  return (parts.join(" · ") || "affordability") + " · click for cost-of-living detail";
}

// One delegated click for the grade table:
//  - a factor cell jumps to that factor's detail for the country
//  - the rest of the row opens the country's travel guide
document.addEventListener("click", (e) => {
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
  const scrollTo = (sel) => { const el = document.querySelector(sel); if (el) el.scrollIntoView({ behavior: "smooth", block: "center" }); };
  // Use the table's OWN displayed name for the country (data files disagree on
  // some names, e.g. Turkey vs Türkiye), so the text filter always matches.
  const rowName = (tbodyId) => {
    const r = document.querySelector(`#${tbodyId} tr[data-iso="${iso}"]`);
    return r ? r.children[0].textContent.trim() : countryName(iso);
  };
  if (go === "currency") {
    if (advisoryByIso()[iso] >= 3 && $("curRisky")) $("curRisky").checked = true;  // reveal if risk-hidden
    $("curFilter").value = code || countryName(iso); applyCurrencyFilter(); scrollTo("#dataSubCurrency .tablewrap");
  } else if (go === "afford") {
    $("affFilter").value = rowName("affRows"); applyAffordFilter(); scrollTo("#affTable");
  } else if (go === "advisory") {
    $("advFilter").value = rowName("advRows"); $("advLevel").value = "all"; applyAdvFilter(); scrollTo("#advTable");
  } else if (go === "flights") {
    $("flightFilter").value = rowName("flightRows"); applyFlightFilter(); scrollTo("#flightTable");
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
  const region = $("valueRegion").value;
  const month = parseInt($("valueMonth").value, 10);
  setSeason(month);
  const advMap = advisoryByIso();

  // Fare context: known fares per country + distance-based estimates for the rest.
  const fares = buildFareContext();
  // "Cheap" is relative to the From country's own price level (US anchor = 1).
  const anchorPl = priceLevel($("valueOrigin").value || "US") || 1;

  const scored = {};
  for (const iso in CUR_BY_ISO) {
    if (region !== "all" && ISO_REGION[iso] !== region) continue;
    const s = valueScores(iso, month, advMap, fares, anchorPl);
    if (s) scored[iso] = s;
  }
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
        title: `${s.name}: value ${s.value}/100 (afford ${s.afford}, safe ${s.safe}, wx ${s.wx}${s.fly != null ? ", fly " + s.fly : ""})` };
      if (advMap[f.properties.iso] === 4)
        return { fill: "#b00020", title: f.properties.name + " — Level 4: Do Not Travel (excluded)" };
      return { fill: NODATA, title: f.properties.name + " — not scored" };
    }, "Best value destinations");
  }

  loadVisited();
  // In weather mode the TABLE follows the map: ranked by weather comfort for the
  // chosen month (value as tiebreak), with a note explaining the sort.
  const weatherMode = valueMapMode === "weather";
  const note = $("rankNote");
  if (note) {
    note.hidden = !weatherMode;
    if (weatherMode) note.textContent =
      `Ranked by weather comfort in ${MONTHS[month - 1]} — switch back to “Value” for the blended score ranking.`;
  }
  const rankedAll = Object.values(scored)
    .sort(weatherMode ? ((a, b) => (b.wx - a.wx) || (b.value - a.value))
                      : ((a, b) => b.value - a.value));
  // Above the fold = recognizable destinations; Hidden Gems = high-value but
  // off-the-beaten-path. Both come from the safety-filtered, unvisited pool.
  const floor = safetyFloor();
  // "Somewhere new" (default) keeps your ✓ been countries out of the picks;
  // interests narrow to countries matching any selected tag.
  const showVisited = localStorage.getItem("wg_showvisited") === "1";
  const eligible = rankedAll.filter((s) =>
    (showVisited || !visited.has(s.iso)) && passesFloor(s, floor) && matchesInterests(s.iso));
  const popular = eligible.filter((s) => popularSet.has(s.iso));
  const offbeat = eligible.filter((s) => !popularSet.has(s.iso));
  // Fall back to the full list if no popular destinations match the filters.
  const picks = (popular.length ? popular : eligible).slice(0, pickCount());
  const picksNote = $("picksNote");
  if (picksNote) picksNote.innerHTML = popular.length
    ? `🌍 Popular destinations, ranked by value${popularDataBacked ? ' <span class="muted" data-tip="popularity = international tourism spend (UN Tourism / World Bank)">ⓘ</span>' : ""} — more finds under 💎 Hidden gems.`
    : "Ranked by overall value — no mainstream destinations match these filters, so showing everything.";
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
  $("valueRows").innerHTML = ranked.map((s) => {
    const vis = visited.has(s.iso) ? ' <span class="visited-tag">✓ visited</span>' : "";
    const adv = s.advLvl === 1 ? ' <span class="advtag a1" title="Level 1: Exercise Normal Precautions">L1</span>'
              : s.advLvl === 2 ? ' <span class="advtag a2" title="Level 2: Exercise Increased Caution">L2</span>'
              : s.advLvl === 3 ? ' <span class="advtag a3" title="Level 3: Reconsider Travel">L3</span>' : "";
    // "The math" table mirrors the other columns with the numeric flight deal
    // score (0-100); exact fares live in the Flights data tab.
    const flight = s.fly != null ? s.fly : "—";
    const valCell = weatherMode ? `${s.value}` : `<b>${s.value}</b>`;
    const wxCell = weatherMode ? `<b>${s.wx}</b>` : `${s.wx}`;
    return `<tr${visited.has(s.iso) ? ' style="opacity:.55"' : ""}><td>${esc(s.name)}${adv}${vis}</td>
      <td class="num">${valCell}</td>
      <td class="num">${s.afford}</td>
      <td class="num">${s.safe}</td><td class="num">${wxCell}</td>
      <td class="num">${flight}</td></tr>`;
  }).join("") || '<tr><td colspan="6">No data for this region.</td></tr>';
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
// starting point the user can adjust on Aviasales. Returns null if we lack the
// hub or a destination city (older cached fares have no `dest`).
function flightSearchURL(dest) {
  if (!dest || !flightsData || !flightsData.hub) return null;
  const dep = new Date(); dep.setDate(dep.getDate() + 60);
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

async function loadFlights() {
  const origin = $("flightOrigin").value || "US";
  $("flightSub").textContent = "Averaging international fares from " +
    ($("flightOrigin").selectedOptions[0] ? $("flightOrigin").selectedOptions[0].textContent : origin) + "…";
  try {
    flightsData = await getJSON("/api/flights?origin=" + encodeURIComponent(origin));
  } catch (e) {
    $("flightSub").textContent = "Could not load flights: " + e.message;
    return;
  }
  if (!flightsData.configured) {
    $("flightSub").innerHTML = "Flight prices need a free Travelpayouts token. Set <code>TRAVELPAYOUTS_TOKEN</code> on the server (Render → Environment), then redeploy.";
    $("flightMap").textContent = "Not configured.";
    $("flightRows").innerHTML = '<tr><td colspan="6">Add TRAVELPAYOUTS_TOKEN to enable.</td></tr>';
    syncURL();
    return;
  }
  renderFlights();
  syncURL();
}

function flightColor(price, min, max) {
  if (price == null) return NODATA;
  const t = max > min ? (price - min) / (max - min) : 0;        // 0 cheap -> 1 pricey
  return t <= 0.5 ? mix("#0a7d28", "#eef0f1", t * 2) : mix("#eef0f1", "#b00020", (t - 0.5) * 2);
}

function renderFlights() {
  const countries = flightsData.countries || [];
  const byC = flightsData.by_country || {};
  const prices = Object.values(byC);
  // Scale colors across the actual fare range (anchoring min at 0 would wash
  // out the green end — the cheapest real average should read as fully cheap).
  const min = prices.length ? Math.min(...prices) : 0;
  const max = prices.length ? Math.max(...prices) : 1;
  const cur = (flightsData.currency || "usd").toUpperCase();
  // Distance-fit baseline so the arrows flag a genuine deal (a long-haul fare
  // can be "below typical" even though it's a bigger number than a short hop).
  const fares = buildFareContext();
  const expected = fares && fares.expected;

  drawMap("flightMap", (f) => {
    const p = byC[f.properties.iso];
    return p == null
      ? { fill: NODATA, title: f.properties.name + " — no fares sampled" }
      : { fill: flightColor(p, min, max), title: `${f.properties.name} — avg ${cur} ${p} round-trip` };
  }, "Average flight prices by destination country");

  $("flightSub").innerHTML =
    `Cached lowest round-trip fares from ${esc(flightsData.origin_name || flightsData.origin)} (via ${esc(flightsData.hub)}), as seen by <a href="https://www.aviasales.com" target="_blank" rel="noopener">Aviasales</a> in the last ~90 days — indicative, not live · ${countries.length} destination countries · greener = cheaper · <span class="farearrow dn">▼</span> below / <span class="farearrow up">▲</span> above the typical fare for the distance · <b>click a fare ↗</b> to search that route live on Aviasales.`;
  $("flightLegend").innerHTML =
    '<span>Cheaper</span><span class="bar" style="background:linear-gradient(90deg,#0a7d28,#eef0f1,#b00020)"></span><span>Pricier</span>';

  markSort("#flightTable", flightSort);
  $("flightRows").innerHTML = sortRows(countries, flightSort, FLIGHT_GET).map((c) => {
    const exp = expected ? expected(c.iso) : null;
    const arrow = priceArrow(Number(c.avg) || null, exp, "the typical fare for this distance");
    const fare = `${esc(cur)} ${Number(c.avg) || "?"}`;
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
            title="Cached fare${seenTip} — click to search ${esc(countryName(c.iso))} live on Aviasales"><b>${fare}</b> <span class="ext">↗</span></a>`
      : `<b>${fare}</b>`;
    return `<tr data-iso="${esc(c.iso)}" title="See the ${esc(countryName(c.iso))} travel guide →"><td>${esc(countryName(c.iso))}</td>
      <td class="num">${fareCell} ${arrow}</td>
      <td class="num">${esc(cur)} ${Number(c.min) || "?"}</td>
      <td class="num">${fmtDuration(c.dur)}</td>
      <td class="num">${fmtStops(c.stops)}</td>
      <td class="num">${Number(c.n) || 0}</td></tr>`;
  }).join("")
    || '<tr><td colspan="6">No fares found from this country.</td></tr>';
  applyFlightFilter();
}

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
// Outbound layovers on the cheapest itinerary.
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
function filterRows(tbodyId, predicate) {
  const tb = $(tbodyId);
  if (!tb) return;
  for (const tr of tb.querySelectorAll("tr")) {
    if (tr.children.length < 2) continue;
    tr.style.display = predicate(tr) ? "" : "none";
  }
}
const _q = (id) => (($(id) && $(id).value) || "").trim().toLowerCase();

function applyCurrencyFilter() {
  const q = _q("curFilter");
  const showRisky = $("curRisky") && $("curRisky").checked;
  filterRows("rows", (tr) => {
    if (!showRisky && parseInt(tr.dataset.adv || "0", 10) >= 3) return false;
    return !q || tr.textContent.toLowerCase().includes(q);
  });
}
function applyAffordFilter() {
  const q = _q("affFilter");
  filterRows("affRows", (tr) => !q || tr.textContent.toLowerCase().includes(q));
}
function applyAdvFilter() {
  const q = _q("advFilter");
  const lvl = ($("advLevel") && $("advLevel").value) || "all";
  filterRows("advRows", (tr) =>
    (lvl === "all" || tr.dataset.lvl === lvl) &&
    (!q || tr.textContent.toLowerCase().includes(q)));
}
function applyFlightFilter() {
  const q = _q("flightFilter");
  filterRows("flightRows", (tr) => !q || tr.textContent.toLowerCase().includes(q));
}
// Wire filter controls once (elements are static in the markup).
[["curFilter", applyCurrencyFilter], ["curRisky", applyCurrencyFilter],
 ["affFilter", applyAffordFilter], ["advFilter", applyAdvFilter],
 ["advLevel", applyAdvFilter], ["flightFilter", applyFlightFilter]
].forEach(([id, fn]) => {
  const el = $(id);
  if (el) el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", fn);
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

// ---- destination photos (Wikipedia REST, keyless) --------------------------
// Each country has a curated landmark/city article in activities.json; we pull
// that page's lead thumbnail. Cached in memory + sessionStorage so it's fetched
// at most once per browser session (and never blocks the page).
const _photoCache = {};
// Pull a high-res lead image for the country's curated landmark via the
// pageimages API, which renders a thumbnail at the requested width (no upscale,
// never errors on size) — much sharper than the ~320px REST summary thumbnail.
async function photoURL(iso, size) {
  size = size || 1000;
  const ckey = iso + "@" + size;
  if (ckey in _photoCache) return _photoCache[ckey];
  const skey = "fxphoto_" + ckey;
  try {
    const cached = sessionStorage.getItem(skey);
    if (cached != null) return (_photoCache[ckey] = cached || null);
  } catch (e) {}
  const q = (activities && activities[iso] && activities[iso].photo) || countryName(iso);
  let url = null;
  try {
    const api = "https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*" +
      "&prop=pageimages&piprop=thumbnail&pithumbsize=" + size +
      "&redirects=1&titles=" + encodeURIComponent(q);
    const r = await fetch(api);
    if (r.ok) {
      const j = await r.json();
      const pages = j.query && j.query.pages;
      const page = pages && Object.values(pages)[0];
      url = (page && page.thumbnail && page.thumbnail.source) || null;
    }
  } catch (e) {}
  _photoCache[ckey] = url;
  try { sessionStorage.setItem(skey, url || ""); } catch (e) {}
  return url;
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
function visaInfo(iso, passport) {
  passport = /^[A-Z]{2}$/.test(passport) ? passport : "US";
  if (passport === iso) return { home: true, passport };   // their own country
  if (passport === "US") {
    const v = visa && visa[iso];
    if (!v || !v.status) return null;
    const meta = VISA_META[v.status] || VISA_META.check;
    return { status: v.status, note: v.note || "", meta, link: v.link || "", passport };
  }
  const code = visaMatrix && visaMatrix[passport] && visaMatrix[passport][iso];
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
  const name = (climate && climate[iso] && climate[iso].name) || (ppp[iso] && ppp[iso].name) || iso;
  if (!a) { $("actDetail").innerHTML = `<h3>${esc(name)}</h3><p class="hint">No curated activity profile yet.</p>`; return; }
  const m = curMonth();
  const tags = a.profile.map((p) =>
    `<span class="chip2">${PROFILE_EMOJI[p] ? PROFILE_EMOJI[p] + " " : ""}${esc(p)}</span>`).join("");
  // Each activity is either a plain label or { t: label, d: one-line insight }.
  const acts = a.activities.map((x) => {
    const label = typeof x === "string" ? x : x.t;
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
    return `<div class="seasrow">
      <span class="what"><span class="actemoji">${activityEmoji(s.what)}</span>${esc(s.what)}</span>
      <span class="months">${s.months.map((x) => MON_ABBR[x - 1]).join(", ")}</span>
      <span class="${on ? "inseason" : "offseason"}">${on ? "in season now" : "off season"}</span>
      ${s.d ? `<span class="seasdesc">${esc(s.d)}</span>` : ""}
    </div>`;
  }).join("");
  const vis = isVisited(iso) ? '<span class="visited-tag">✓ visited</span>' : "";
  // Summary line dropped — it just restated the "things to do" bullets below.
  $("actDetail").innerHTML = `
    <div class="besthead"><h3>${esc(name)} ${vis} <span class="muted">· ${REGIONS[ISO_REGION[iso]] || "—"}</span></h3></div>
    <div class="chips">${tags}</div>
    <h4 style="margin:.6em 0 .2em">🎒 Top things to do</h4>
    <ul class="actlist">${acts}</ul>
    <a class="viatorbtn" href="${viatorURL(name)}" target="_blank" rel="sponsored nofollow noopener"
       title="Browse bookable tours & experiences in ${esc(name)} on Viator">🎟️ Book tours &amp; activities in ${esc(name)} <span class="muted">on Viator</span> <span class="ext">↗</span></a>
    ${seas ? `<h4 style="margin:.6em 0 .2em">🗓️ What's in season <span class="muted">(now: ${MONTHS[m - 1]})</span></h4>${seas}` : ""}`;
  loadActivityThumbs(iso);
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
  document.querySelectorAll("#actDetail .actthumbslot[data-subj]").forEach(async (slot) => {
    const p = await actPhoto(slot.dataset.subj, country);
    if (!p || ccGuideIso !== iso || slot.childElementCount) return;
    const k = fileKey(p.full);
    if (used.has(k)) return;
    used.add(k);
    // Derive a lightweight thumb from the API's 1600px URL (standard MediaWiki
    // size-in-path); fall back to the big one if that variant doesn't exist.
    const small = p.thumb.replace(/\/(\d+)px-/, "/320px-");
    const img = document.createElement("img");
    img.className = "actthumb"; img.loading = "lazy"; img.alt = "";
    img.title = "view photo";
    img.onerror = () => { img.onerror = null; img.src = p.thumb; };
    img.src = small;
    img.addEventListener("click", () => openLightboxSingle(p));
    slot.appendChild(img);
  });
}

// ===========================================================================
//  Your travel map: visited (been) + wishlist (want to go) — both in localStorage
// ===========================================================================
let visited = null, wishlist = null;
let visitMode = "visited";   // which list the map/dropdown edits
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
// localStorage stays the source of truth for everyone (accounts are optional);
// when signed in, every change also pushes to the cloud copy.
function saveVisited() {
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
  saveVisited(); saveWishlist();
}

let _displayNames = null;
function countryName(iso) {
  if (EXTRA_PLACES[iso]) return EXTRA_PLACES[iso];   // flag-emoji places
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
        `<button type="button" class="bulkchip${on.has(c.iso) ? " on" : ""}" data-iso="${esc(c.iso)}">${flagEmoji(c.iso)} ${esc(c.name)}</button>`
      ).join("") + "</div>"
    + `<div class="bulkfoot"><span class="bulkcount">${on.size} selected</span>`
    + '<button type="button" class="bulkdone">Done</button></div></div>';
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add("show"));
  const close = () => {
    m.classList.remove("show");
    setTimeout(() => m.remove(), 220);
    renderVisited();                        // one redraw for the whole batch
  };
  m.querySelector(".submodal-x").onclick = close;
  m.querySelector(".bulkdone").onclick = close;
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  const onKey = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  m.querySelector(".bulkchips").addEventListener("click", (e) => {
    const chip = e.target.closest(".bulkchip");
    if (!chip) return;
    toggleMark(chip.dataset.iso);
    chip.classList.toggle("on", on.has(chip.dataset.iso));
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
      if (chip) chip.classList.add("on");
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
  $("visitedClear").onclick = () => {
    const label = visitMode === "visited" ? "been-to" : "wishlist";
    (visitMode === "visited" ? visited : wishlist).clear();
    saveVisited(); saveWishlist(); renderVisited();
    status("Cleared your " + label + " list.", "ok");
  };
  for (const b of document.querySelectorAll("#visitedMode button")) {
    b.addEventListener("click", () => {
      visitMode = b.dataset.vm;
      for (const x of document.querySelectorAll("#visitedMode button"))
        x.classList.toggle("active", x === b);
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
      visited.delete(chip.dataset.iso); wishlist.delete(chip.dataset.iso);
      saveVisited(); saveWishlist(); renderVisited();
    }
  });
  renderVisited();
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
  const chipsFor = (set, cls) => [...set].filter(inFilter)
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `<span class="chip2 rm ${cls}" data-iso="${esc(c.iso)}" title="remove">${esc(c.name)} ✕</span>`).join("");
  $("visitedSub").innerHTML =
    `<b class="subbeen">${visited.size} been</b> · ` +
    `<b class="subwant">${wishlist.size} want to go</b> — ` +
    `marking <b>${visitMode === "visited" ? "✓ been" : "★ want to go"}</b>. Click the map or pick a country.`;
  renderVisitedStats();
  const sections = [];
  const beenChips = chipsFor(visited, "v"), wantChips = chipsFor(wishlist, "w");
  if (beenChips) sections.push('<div class="chiprow"><span class="chiplabel">✓ Been</span>' + beenChips + '</div>');
  if (wantChips) sections.push('<div class="chiprow"><span class="chiplabel">★ Want to go</span>' + wantChips + '</div>');
  $("visitedChips").innerHTML = sections.join("") ||
    (contFilter ? '<span class="hint">Nothing marked on this continent yet.</span>'
                : '<span class="hint">Nothing yet — click countries on the map.</span>');
  syncURL();
}

// On-page version of the shareable card's stats: flags, an award tag (with a
// hover tooltip explaining how it's earned), and the continents / % of world text.
// Continent filter (traveler feedback): clicking a % chip narrows the flag
// strip and the country chip lists to that continent, and zooms the map to
// it — "all my places, but also a South America view". Click again to clear.
let contFilter = null;
const CONT_VIEW = {   // lon/lat boxes per continent for the map zoom
  NA: [-170, -50, 7, 83], SA: [-85, -32, -56, 13], EU: [-25, 45, 34, 72],
  AS: [25, 180, -12, 78], AF: [-20, 52, -36, 38], OC: [110, 180, -50, 0],
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

function renderVisitedStats() {
  const host = $("visitedStats");
  if (!host) return;
  const n = visited.size, m = wishlist.size;
  if (!n && !m) { host.innerHTML = ""; return; }
  const cont = visitedContinents();
  const pct = Math.max(1, Math.round((n / allPlaces().length) * 100));
  const bits = [];
  if (n) bits.push(`<b>${n}</b> ${n === 1 ? "country" : "countries"}`);
  if (cont) bits.push(`🌍 ${cont} continent${cont === 1 ? "" : "s"}`);
  if (n) bits.push(`~${pct}% of the world`);
  if (m) bits.push(`${m} on the wishlist`);
  const mi = milestoneInfo(n);
  let award = "";
  // All seven continents (Antarctica included) outranks any count tier.
  if (cont === 7)
    award += '<span class="awardtag seven" title="Every continent on Earth — Antarctica included. The rarest badge there is.">🌐 All 7 Continents</span>';
  if (mi.earned) {
    const q = `Earned by visiting ${mi.earned.t}+ countries`
      + (mi.next ? ` — ${mi.next.t - n} more for ${mi.next.label}` : " — top tier!");
    award += `<span class="awardtag" title="${esc(q)}">${esc(mi.earned.label)}</span>`;
  } else if (mi.next && n) {
    award += `<span class="awardtag locked" title="${esc(`Visit ${mi.next.t} countries to earn ${mi.next.label} — ${mi.next.t - n} to go`)}">🔒 ${mi.next.t - n} to ${esc(mi.next.label)}</span>`;
  }
  // every visited flag, alphabetical (narrowed by the continent filter when
  // one is active) — each names its place on hover/tap
  const flags = [...visited]
    .filter((iso) => !contFilter || continentOf(iso) === contFilter)
    .sort((a, b) => countryName(a).localeCompare(countryName(b)))
    .map((iso) => `<span data-tip="${esc(countryName(iso))}" title="">${flagEmoji(iso)}</span>`)
    .join(" ");
  // continent progress chips — click to filter to that continent, gold at 100%
  const prog = continentProgress().filter((p) => p.n > 0 && p.total > 0);
  const contRow = prog.length
    ? '<div class="contbar">' + prog.map((p) =>
        `<span class="contchip${p.pct === 100 ? " done" : ""}${p.c === contFilter ? " active" : ""}" data-cont="${p.c}"`
        + ` data-tip="${p.n} of ${p.total} countries in ${esc(p.name)} (UN members) — ${p.c === contFilter ? "tap to show everything again" : "tap to filter to this continent"}" title="">`
        + `${p.pct === 100 ? "🏅 " : ""}${esc(p.name)} ${p.pct}%</span>`).join("")
      + (contFilter ? `<span class="contchip clear" data-cont="${contFilter}" data-tip="show all continents" title="">✕ clear</span>` : "")
      + "</div>"
    : "";
  // One <span> per line of text: .vstats-line is a flex row (for the award
  // pill), and a bare <b> would become its own flex item — the gap property
  // then splits the number from its own sentence.
  host.innerHTML = `<div class="vstats-line"><span>${bits.join(" · ")}</span>${award}</div>`
    + (flags.trim() ? `<div class="vflags">${flags}</div>` : "")
    + contRow;
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
async function activateTab(name, push) {
  document.documentElement.setAttribute("data-tab", name);  // keep pre-paint CSS in sync
  // Leaving the guide -> restore the homepage title/canonical (openGuideFor sets
  // the country-specific ones when a guide opens).
  if (name !== "guide") setDocMeta(_DEFAULT_TITLE, _DEFAULT_URL);
  for (const b of document.querySelectorAll("#tabs button"))
    b.classList.toggle("active", b.dataset.tab === name);
  for (const s of document.querySelectorAll(".tab"))
    s.hidden = s.id !== "tab-" + name;

  // Refresh visited marks when returning to the recommendation tab.
  if (name === "value" && loaded.value) renderValue();

  try {
    if (name === "value" && !loaded.value) {
      await Promise.all([ensureWorld(), ensurePPP(), ensureClimate(), ensureAdvisories(),
                         ensureActivities().catch(() => {}),     // hazards + photos
                         ensureVisa().catch(() => {})]);         // visa column
      buildValueTab(); loaded.value = true;
    } else if (name === "guide" && !loaded.guide) {
      await Promise.all([ensurePPP(), ensureClimate(), ensureActivities(),
                         ensureVisa().catch(() => {})]);
      buildBestPickers(); loaded.guide = true;
    } else if (name === "visited" && !loaded.visited) {
      await Promise.all([ensureWorld(), ensurePPP(), ensureClimate()]);
      buildVisited(); loaded.visited = true;
    } else if (name === "data") {
      setDataMode(dataMode);   // initialize the active sub-view (incl. currency)
    }
  } catch (e) {
    status("Could not load " + name + ": " + e.message, "err");
  }
  syncURL(push);
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

// Clicking a month bar in the guide makes the chart the control: sets the one
// global travel month (the same one Top Picks ranks by), re-prices the stay
// map, and rebuilds the AI prompt for that month.
function planForMonth(m) {
  const sel = $("valueMonth");
  if (!sel || !(m >= 1 && m <= 12)) return;
  sel.value = String(m);
  if (sel._sync) sel._sync();
  if (loaded.value) renderValue();
  if (ccGuideIso) { renderCountryClimate(ccGuideIso); renderGuideStay(ccGuideIso); renderGuideAI(ccGuideIso); }
  status("Planning for " + MONTHS[m - 1] + " ✓ — picks, stay prices & AI prompt updated", "ok");
  syncURL();
}
$("bestDetail").addEventListener("click", (e) => {
  const bar = e.target.closest("#bestDetail .bars .col[data-mn]");
  if (!bar) return;
  if (e.target.closest(".hzmark")) return;   // ⚠️ taps show the hazard, not switch months
  planForMonth(parseInt(bar.dataset.mn, 10));
});

// Guide jump chips: smooth-scroll to a section (buttons, not #hash links, so
// the clean /guide/<slug> URLs stay untouched).
document.querySelector(".guidejump").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-go]");
  if (!b) return;
  let el = $(b.dataset.go);
  if (el && el.hidden) el = $("subscribe") || el;   // stay map can be hidden
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
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
  dataMode = mode;
  for (const x of document.querySelectorAll("#dataMode button"))
    x.classList.toggle("active", x.dataset.dm === mode);
  for (const m in DATA_SUBS) $(DATA_SUBS[m]).hidden = m !== mode;
  try {
    if (mode === "currency") {
      if (!lastIndexData) loadIndex(activeDays);   // deferred from init
      // Load advisories so the hide-higher-risk filter works, then re-render
      // the (already-populated) rates table to tag rows + apply the filter.
      if (!loaded.curRisk) {
        await ensureAdvisories().catch(() => {});
        loaded.curRisk = true;
        if (dataRates) renderRates(dataRates);
      }
      applyCurrencyFilter();
    } else if (mode === "afford" && !loaded.afford) {
      await Promise.all([ensureWorld(), ensurePPP()]);
      renderAfford(); loaded.afford = true;
    } else if (mode === "advisory" && !loaded.advisory) {
      $("advSub").textContent = "Loading advisories…";
      await Promise.all([ensureWorld(), ensureAdvisories()]);
      renderAdvisories(); loaded.advisory = true;
    } else if (mode === "flights" && !loaded.flights) {
      await Promise.all([ensureWorld(), fillOriginSelect($("flightOrigin"))]);
      loadFlights(); loaded.flights = true;
    }
  } catch (e) {
    status("Could not load " + mode + ": " + e.message, "err");
  }
  syncURL();
}
for (const b of document.querySelectorAll("#dataMode button"))
  b.addEventListener("click", () => setDataMode(b.dataset.dm));

// ---- newsletter signup (Buttondown embed) ---------------------------------
// Set this to your public Buttondown newsletter username to enable signups.
const BUTTONDOWN_USER = "wandergrade";

// ---- feedback form ----------------------------------------------------------
// Google Form ("WanderGrade — Feedback", anonymous-friendly). Drives the footer
// link + the line under the newsletter box; set "" to hide both.
const FEEDBACK_URL = "https://forms.gle/gzG1Bmg7kKRKubri7";

function renderFeedback() {
  if (!FEEDBACK_URL) return;
  const foot = $("feedbackFoot");
  if (foot) {
    foot.hidden = false;
    foot.querySelector("a").href = FEEDBACK_URL;
  }
  const sub = $("subscribe");
  if (sub) sub.insertAdjacentHTML("beforeend",
    `<a class="feedbacklink" href="${FEEDBACK_URL}" target="_blank" rel="noopener">💬 Spotted something off, or missing a feature? Tell me — it takes 30 seconds →</a>`);
}

function subscribeFormHTML() {
  const base = "https://buttondown.com/" + BUTTONDOWN_USER;
  if (!BUTTONDOWN_USER)
    return '<span class="hint">📬 Newsletter signup not configured yet — set BUTTONDOWN_USER in app.js.</span>';
  return `<span class="sublabel">📬 Once a month: the best-value places to travel, straight to your inbox.</span>
    <form action="https://buttondown.com/api/emails/embed/subscribe/${BUTTONDOWN_USER}"
          method="post" target="popupwindow"
          onsubmit="window.open('${base}','popupwindow')" class="subform">
      <input type="email" name="email" placeholder="you@email.com" required>
      <button type="submit">Subscribe</button>
    </form>`;
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
}

function openSubscribeModal(opts) {
  opts = opts || {};
  if (document.querySelector(".submodal")) return;
  const m = document.createElement("div");
  m.className = "submodal";
  m.innerHTML = '<div class="submodal-card"><button class="submodal-x" aria-label="Close">✕</button>'
    + subscribeFormHTML() + "</div>";
  document.body.appendChild(m);
  wireSubForm(m);
  requestAnimationFrame(() => m.classList.add("show"));
  const close = () => {
    // Closed without subscribing → count as a dismissal (re-arm in 30 days).
    if (!subDone()) markDismissed();
    m.classList.remove("show");
    setTimeout(() => m.remove(), 220);
  };
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  m.querySelector(".submodal-x").onclick = close;
  const onKey = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } };
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
(function armSubscribeAutoPrompt() {
  if (!shouldAutoPrompt()) return;
  let done = false;
  function cleanup() {
    clearTimeout(timer);
    window.removeEventListener("scroll", onScroll);
  }
  function fire() {
    if (done || !shouldAutoPrompt()) { cleanup(); return; }
    // Don't stack on top of a guide lightbox, the spin-globe, or an open modal —
    // wait until the visitor's attention is free, then try again.
    if (document.querySelector(".submodal, .lightbox, .spinover")) {
      setTimeout(fire, 3000);
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
let SLUG2ISO = null, ISO2SLUG = null;
function ensureSlugs() {
  if (SLUG2ISO) return Promise.resolve();
  return fetch("/slugs.json").then((r) => r.json()).then((m) => {
    SLUG2ISO = m; ISO2SLUG = {};
    for (const s in m) ISO2SLUG[m[s]] = s;
  }).catch(() => { SLUG2ISO = {}; ISO2SLUG = {}; });
}
// iso -> "/guide/japan"; falls back to the query form until slugs load.
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
const _DEFAULT_TITLE = "WanderGrade — Where Should I Travel to Next?";
const _DEFAULT_URL = SITE_ORIGIN + "/";
function setDocMeta(title, absURL) {
  document.title = title;
  const c = document.querySelector('link[rel="canonical"]'); if (c) c.setAttribute("href", absURL);
  const o = document.querySelector('meta[property="og:url"]'); if (o) o.setAttribute("content", absURL);
}
function guideTitle(iso) {
  return countryName(iso) + " Travel Guide — Best Time to Visit & What to Do | WanderGrade";
}

function buildShareURL(forShare) {
  if (forShare === undefined) forShare = true;
  const q = new URLSearchParams();
  const tab = currentTab();
  q.set("tab", tab);
  if (tab === "value") {
    if ($("valueRegion").value !== "all") q.set("vr", $("valueRegion").value);
    q.set("vmn", $("valueMonth").value);
    if (pickCount() !== 5) q.set("pc", String(pickCount()));
    if (safetyFloor() !== "b") q.set("sf", safetyFloor());
    const fac = loadFactors();
    if (fac.length !== WEIGHT_DEFS.length) q.set("fac", fac.join("."));
    if ($("valueOrigin").value && $("valueOrigin").value !== "US") q.set("vo", $("valueOrigin").value);
    if (homeManual && homeBase !== homeCurAuto()) q.set("hc", homeBase);
    if (valueMapMode === "weather") q.set("vmm", "weather");
    const p = loadPriorities();
    const compact = WEIGHT_DEFS.map((w) => p[w.key][0]).join(".");   // e.g. h.m.m.m.m
    if (compact !== WEIGHT_DEFS.map((w) => w.def[0]).join(".")) q.set("pri", compact);
  } else if (tab === "data") {
    if (dataMode !== "currency") q.set("dm", dataMode);
    if (dataMode === "currency" && activeDays !== 365) q.set("win", String(activeDays));
    if (dataMode === "currency" && dataBase !== "USD") q.set("db", dataBase);
    if (dataMode === "flights" && $("flightOrigin").value) q.set("fo", $("flightOrigin").value);
    // Clean, indexable URL: /guide/<slug> (no query string). Same-origin so
    // history.pushState in syncURL accepts it.
  } else if (tab === "guide") {
    return location.origin + guidePath($("bestCountry").value || "JP");
  } else if (tab === "visited") {
    loadVisited();
    // The visited list persists in localStorage already; only embed it for an
    // explicit Share (embedding it on every refresh would wrongly trip the
    // "viewing a shared map" warning against the user's own list).
    if (visited.size && forShare) q.set("v", [...visited].join(","));
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
    const cur = location.pathname + location.search;
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
    // Clean guide URL (/guide/<slug>) takes precedence over query params.
    const pIso = pathGuideIso();
    if (pIso) { await openGuideFor(pIso, false); return; }
    const q = new URLSearchParams(location.search);
    const tab = q.get("tab") || "value";
    const vmn = q.get("vmn"), vmSel = $("valueMonth");
    if (vmn && vmSel && [...vmSel.options].some((o) => o.value === vmn)) vmSel.value = vmn;
    await activateTab(tab, false);
    if (tab === "guide" && q.get("gc")) await openGuideFor(q.get("gc"), false);
    else if (tab === "data" && q.get("dm")) await setDataMode(q.get("dm"));
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
    catch (e) { /* user cancelled -> fall through to clipboard */ }
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
    loadVisited();
    visited = new Set(v.split(",").map((s) => s.trim().toUpperCase()).filter((s) => /^[A-Z]{2}$/.test(s)));
  }
}

async function postApplyShared() {
  if (![...sharedQ.keys()].length) return;
  let tab = sharedQ.get("tab");
  let dm = sharedQ.get("dm");
  // Old share links used standalone money/advisory/flights tabs — map them
  // into the consolidated Explore-the-Data tab.
  const legacyTabs = { money: "currency", advisory: "advisory", flights: "flights" };
  if (legacyTabs[tab]) {
    dm = dm || (sharedQ.get("mmode") === "afford" ? "afford" : legacyTabs[tab]);
    tab = "data";
  }
  if (tab && tab !== "value" && document.querySelector(`#tabs button[data-tab="${tab}"]`)) {
    await activateTab(tab);
  }
  if (tab === "data" && dm) await setDataMode(dm);
  let rerender = false;
  if (sharedQ.get("vr") && [...$("valueRegion").options].some((o) => o.value === sharedQ.get("vr"))) {
    $("valueRegion").value = sharedQ.get("vr"); rerender = true;
  }
  if (sharedQ.get("vmn")) { $("valueMonth").value = sharedQ.get("vmn"); rerender = true; }
  if (sharedQ.get("pc")) { $("pickCount").value = sharedQ.get("pc"); rerender = true; }
  if (["a", "b", "any"].includes(sharedQ.get("sf"))) { $("safeFloor").value = sharedQ.get("sf"); rerender = true; }
  if (sharedQ.get("fac")) {
    const keys = sharedQ.get("fac").split(".").filter((k) => WEIGHT_DEFS.some((w) => w.key === k));
    if (keys.length) { factors = keys; saveFactors(); buildFactorChips(); rerender = true; }
  }
  if (sharedQ.get("vmm") === "weather") {
    valueMapMode = "weather"; rerender = true;
    document.querySelectorAll("#valueMapMode button").forEach((b) =>
      b.classList.toggle("active", b.dataset.vm === "weather"));
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
  if (sharedQ.get("gc")) {
    await openGuideFor(sharedQ.get("gc"));
    if (sharedQ.get("ai")) openGuideAI(sharedQ.get("gc"));   // email "Plan with AI" deep link
  }
  if (sharedQ.get("win")) loadIndex(parseInt(sharedQ.get("win"), 10) || 365);
  const db = sharedQ.get("db");
  if (db && /^[A-Z]{3}$/.test(db) && db !== dataBase) {
    dataBase = db;
    const sel = $("dataBase");
    if (sel && [...sel.options].some((o) => o.value === db)) sel.value = db;
    loadRates();
    loadIndex(activeDays);
  }
  if (sharedQ.get("v") && tab === "visited") {
    renderVisited();
    status(`Viewing a shared map of ${visited.size} countries — editing it will overwrite your own saved list.`, "ok");
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
// total and % of world). Antarctica is one place; its trophies are the map
// medallion and the 7-continents badge, so it sits out of this row.
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
  const pct = Math.max(1, Math.round((n / allPlaces().length) * 100));
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
      <text x="${cx}" y="160" text-anchor="middle" font-family="${font}" font-size="30" font-weight="800" letter-spacing="6" fill="#7fd99a">🗺️ WANDERLIST</text>
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
      <text x="60" y="52" font-family="${font}" font-size="20" font-weight="800" letter-spacing="3" fill="#7fd99a">🗺️ WANDERLIST</text>
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
    const name = orientation === "story" ? "wanderlist-story.png" : "wanderlist-map.png";
    const file = new File([blob], name, { type: "image/png" });
    // Native share sheet on phones (posts straight to socials); download elsewhere.
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: "My Wander List" }); return; }
      catch (e) { /* cancelled -> download instead */ }
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

// ---- ambient soundtrack ------------------------------------------------------
// Generative ambience synthesized live (Web Audio) — slow stereo pad chords, a
// soft bass root, a breath of band-passed air, and a sparse kalimba-like
// melody that follows the chords, all sent through a synthesized reverb and a
// dub-style echo. No audio files: nothing to download and nothing to license,
// and it never loops exactly. Strictly opt-in via the 🎵 header button; the
// choice persists in localStorage. Returning visitors with music on get it
// resumed on their first interaction (autoplay policy).
const MUSIC_KEY = "wg_music";
let _music = null;

// Warm, floaty loop: Fmaj7 → Am(add9) → Cmaj9 → G6. Frequencies in Hz.
const MUSIC_CHORDS = [
  [174.61, 220.00, 261.63, 329.63],
  [220.00, 246.94, 261.63, 329.63],
  [130.81, 164.81, 196.00, 293.66],
  [196.00, 246.94, 293.66, 329.63],
];

// Synthesized reverb impulse: stereo exponentially-decaying noise. Cheap to
// build, and it's what turns bare oscillators into something that sounds
// produced — every voice gets space and distance from it.
function musicIR(ac, dur, decay) {
  const len = Math.floor(ac.sampleRate * dur);
  const ir = ac.createBuffer(2, len, ac.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = ir.getChannelData(ch);
    for (let i = 0; i < len; i++)
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
  }
  return ir;
}

function musicChord() {
  if (!_music) return;
  const ac = _sfx;
  const chord = MUSIC_CHORDS[_music.ci++ % MUSIC_CHORDS.length];
  _music.chord = chord;                            // the melody reads this
  const dur = 14 + Math.random() * 4;
  const t0 = ac.currentTime;
  chord.forEach((hz, vi) => {
    [[-5, -0.45], [4, 0.45]].forEach(([cents, panPos]) => {   // stereo spread
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = vi < 2 ? "sine" : "triangle";
      o.frequency.value = hz;
      o.detune.value = cents;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.011, t0 + 4);     // slow swell in
      g.gain.setValueAtTime(0.011, t0 + dur - 5);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);  // slow fade out
      let tail = o.connect(g);
      if (ac.createStereoPanner) {
        const pan = ac.createStereoPanner();
        pan.pan.value = panPos;
        tail = g.connect(pan);
      }
      tail.connect(_music.lp);
      o.start(t0);
      o.stop(t0 + dur + 0.1);
    });
  });
  // bass root an octave down — felt more than heard, anchors the chord
  const b = ac.createOscillator(), bg = ac.createGain();
  b.type = "sine";
  b.frequency.value = chord[0] / 2;
  bg.gain.setValueAtTime(0.0001, t0);
  bg.gain.exponentialRampToValueAtTime(0.02, t0 + 4);
  bg.gain.setValueAtTime(0.02, t0 + dur - 5);
  bg.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  b.connect(bg).connect(_music.dry);
  b.start(t0);
  b.stop(t0 + dur + 0.1);
  _music.timer = setTimeout(musicChord, (dur - 4.5) * 1000);  // overlap swells
}

// One kalimba-ish pluck: fast attack, long decay, a quiet octave partial for
// timbre, routed through the echo + reverb so it trails off into the distance.
function musicPluck(hz, t0, vel) {
  const ac = _sfx;
  const o = ac.createOscillator(), o2 = ac.createOscillator();
  const g = ac.createGain(), g2 = ac.createGain();
  o.type = "sine";
  o.frequency.value = hz;
  o2.type = "sine";
  o2.frequency.value = hz * 2;
  g2.gain.value = 0.35;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vel, t0 + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + 2.2);
  o.connect(g);
  o2.connect(g2).connect(g);
  let tail = g;
  if (ac.createStereoPanner) {
    const pan = ac.createStereoPanner();
    pan.pan.value = Math.random() * 1.2 - 0.6;
    tail = g.connect(pan);
  }
  tail.connect(_music.pluckBus);
  o.start(t0);  o.stop(t0 + 2.4);
  o2.start(t0); o2.stop(t0 + 2.4);
}

// Sparse generative phrases — 1–3 notes from the current chord, an octave or
// two up, with humanized spacing. Silence is part of the instrument.
function musicMelody() {
  if (!_music) return;
  const ac = _sfx;
  const chord = _music.chord || MUSIC_CHORDS[0];
  const pool = chord.map((f) => f * 2).concat(chord[0] * 4, chord[2] * 4);
  const nNotes = 1 + Math.floor(Math.random() * 3);
  let t = ac.currentTime + 0.05;
  for (let k = 0; k < nNotes; k++) {
    musicPluck(pool[Math.floor(Math.random() * pool.length)], t, 0.022 + Math.random() * 0.012);
    t += 0.22 + Math.random() * 0.28;
  }
  _music.melodyTimer = setTimeout(musicMelody, 3500 + Math.random() * 5500);
}

function startMusic() {
  const ac = sfxCtx();
  if (!ac || _music) return;
  const master = ac.createGain();
  master.gain.setValueAtTime(0.0001, ac.currentTime);
  // Deliberately quiet: ambience should sit under the room, not in it.
  // quick enough that a click gets an audible response, still a fade not a hit
  master.gain.exponentialRampToValueAtTime(0.55, ac.currentTime + 1.2);
  master.connect(ac.destination);
  // dry bus + reverb send
  const dry = ac.createGain();
  dry.connect(master);
  const conv = ac.createConvolver();
  conv.buffer = musicIR(ac, 3.5, 2.8);
  const wet = ac.createGain();
  wet.gain.value = 0.55;
  wet.connect(conv).connect(master);
  // pads: lowpass keeps them soft/hazy, then room + a generous reverb send
  const lp = ac.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 1100;
  lp.Q.value = 0.4;
  lp.connect(dry);
  lp.connect(wet);
  // plucks: dry + echo; the echo repeats feed the reverb, not the dry bus,
  // so each repeat drifts further away
  const pluckBus = ac.createGain();
  pluckBus.connect(dry);
  pluckBus.connect(wet);
  const dly = ac.createDelay(1.5);
  dly.delayTime.value = 0.44;
  const fb = ac.createGain();
  fb.gain.value = 0.34;
  dly.connect(fb).connect(dly);
  pluckBus.connect(dly);
  dly.connect(wet);
  // "air": looped noise through a slowly wandering bandpass, barely there
  const nb = ac.createBuffer(1, ac.sampleRate * 2, ac.sampleRate);
  const nd = nb.getChannelData(0);
  for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
  const air = ac.createBufferSource();
  air.buffer = nb;
  air.loop = true;
  const bp = ac.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 520;
  bp.Q.value = 2.5;
  const airG = ac.createGain();
  airG.gain.value = 0.009;
  const lfo = ac.createOscillator();
  lfo.frequency.value = 0.02;
  const lfoG = ac.createGain();
  lfoG.gain.value = 260;
  lfo.connect(lfoG).connect(bp.frequency);
  air.connect(bp).connect(airG).connect(dry);
  air.start();
  lfo.start();
  _music = { master, lp, dry, wet, pluckBus, timer: null, melodyTimer: null,
             nodes: [air, lfo], ci: 0, chord: null };
  musicChord();
  // greet the click right away: two soft chord-tone plucks, then the loop
  musicPluck(523.25, ac.currentTime + 0.05, 0.03);
  musicPluck(659.25, ac.currentTime + 0.32, 0.024);
  _music.melodyTimer = setTimeout(musicMelody, 1600);
}

function stopMusic() {
  if (!_music) return;
  const ac = _sfx, m = _music;
  _music = null;                                   // chord/melody loops stop
  clearTimeout(m.timer);
  clearTimeout(m.melodyTimer);
  m.master.gain.cancelScheduledValues(ac.currentTime);
  m.master.gain.setValueAtTime(Math.max(m.master.gain.value, 0.0001), ac.currentTime);
  m.master.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 1.2);
  setTimeout(() => {
    m.nodes.forEach((n) => { try { n.stop(); } catch (e) {} });
    m.master.disconnect();
  }, 1500);
}

function setMusicBtn(on) {
  const b = $("musicBtn");
  if (!b) return;
  b.setAttribute("aria-pressed", on ? "true" : "false");
  b.classList.toggle("playing", on);
  b.title = on ? "Ambient soundtrack — on (click to turn off)"
              : "Ambient soundtrack — off (click to turn on)";
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
    const arm = (e) => {
      if (e.target && e.target.closest && e.target.closest("#musicBtn")) return;
      if (!_music && localStorage.getItem(MUSIC_KEY) === "1") startMusic();
    };
    document.addEventListener("pointerdown", arm, { once: true });
    document.addEventListener("keydown", arm, { once: true });
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
if ($("aiExport")) $("aiExport").addEventListener("click", exportAIPrompt);
// ("Use on another device" was removed — the Share button already produces a
//  URL carrying your map across devices.)

// ---- Instant tooltip ([data-tip]) -------------------------------------------
// Native title tooltips need a ~1s hover and are easy to miss; anything with a
// data-tip gets an immediate, styled tooltip instead. Fixed-positioned so the
// scrollable table wrappers can't clip it. (title="" on the same element
// suppresses the ancestor row's native tooltip from doubling up.)
const _tipEl = document.createElement("div");
_tipEl.className = "wgtip";
_tipEl.hidden = true;
document.body.appendChild(_tipEl);
function _tipShowFor(e) {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (!t || !t.dataset.tip) { _tipEl.hidden = true; return; }
  _tipEl.textContent = t.dataset.tip;
  _tipEl.hidden = false;
  const r = t.getBoundingClientRect();
  const w = _tipEl.offsetWidth, h = _tipEl.offsetHeight;
  // clientWidth, not innerWidth — the latter reads 0 in some headless/embedded contexts
  const vw = document.documentElement.clientWidth || window.innerWidth;
  _tipEl.style.left = Math.max(8, Math.min(vw - w - 8, r.left + r.width / 2 - w / 2)) + "px";
  _tipEl.style.top = (r.top - h - 8 > 8 ? r.top - h - 8 : r.bottom + 8) + "px";
}
document.addEventListener("mouseover", _tipShowFor);
// Touch screens have no hover — a tap on the element shows the tooltip, a tap
// anywhere else dismisses it (the closest() miss hides in _tipShowFor).
document.addEventListener("click", _tipShowFor);
document.addEventListener("scroll", () => { _tipEl.hidden = true; }, true);

(async function init() {
  initTheme();
  renderSubscribe();
  renderFeedback();
  preApplyShared();
  // On a public deployment the server disables settings + manual email; hide them.
  getJSON("/api/config").then((c) => {
    if (c.readonly) { $("toggleSettings").hidden = true; $("check").hidden = true; }
  }).catch(() => {});
  // Load the currency data (the "Where to go" score needs live rates + PPP),
  // render the currency tab in the background, then open the verdict tab.
  await Promise.all([ensurePPP().catch(() => {}), ensureWorld().catch(() => {}), loadRates()]);
  renderMapSafe();
  // The 1-year index chart lives in the Explore-the-Data tab; it loads there
  // on first open (setDataMode) instead of costing every landing visit.
  // A /guide/<slug> page (server injects window.__WGGC__) opens that country
  // straight away — no Top Picks flash. Email ?tab=guide&gc= links fall through
  // to postApplyShared as before.
  await ensureSlugs();
  const bootIso = (window.__WGGC__ && /^[A-Z]{2}$/.test(window.__WGGC__))
    ? window.__WGGC__ : pathGuideIso();
  if (bootIso) await openGuideFor(bootIso);
  else await activateTab("value");
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
const CADENCE_LABEL = { monthly: "Monthly", quarterly: "Every 3 months", off: "No emails" };
let acctState = null;              // { email, user } once signed in

function acctSignedIn() { return !!(acctState && acctState.email); }

async function acctLoad() {
  if (!ACCT_ON) return;
  try {
    const r = await fetch("/api/auth/me", { credentials: "same-origin" });
    const d = await r.json();
    acctState = d && d.email ? d : null;
  } catch (e) { acctState = null; }
  if (acctSignedIn() && acctState.user) acctMergeDown(acctState.user);
  acctPaintButton();
}

// First sign-in on a device: union the cloud map with whatever is already
// marked locally. Union (not replace) because silently dropping either side
// would destroy real travel history.
function acctMergeDown(user) {
  loadVisited(); loadWishlist();
  const before = visited.size + wishlist.size;
  (user.visited || []).forEach((i) => visited.add(i));
  (user.wishlist || []).forEach((i) => wishlist.add(i));
  if (visited.size + wishlist.size !== before ||
      (user.visited || []).length !== visited.size ||
      (user.wishlist || []).length !== wishlist.size) {
    localStorage.setItem("fx_visited", JSON.stringify([...visited]));
    localStorage.setItem("fx_wishlist", JSON.stringify([...wishlist]));
    acctQueueSync();               // push the merged union back up
    if (loaded.visited) renderVisited();
  }
}

let _syncTimer = null;
function acctQueueSync() {
  if (!acctSignedIn()) return;
  clearTimeout(_syncTimer);        // coalesce bulk edits into one request
  _syncTimer = setTimeout(acctSync, 800);
}
async function acctSync() {
  if (!acctSignedIn()) return;
  try {
    loadVisited(); loadWishlist();
    await fetch("/api/auth/sync", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visited: [...visited], wishlist: [...wishlist] }),
    });
  } catch (e) { /* offline: localStorage still holds it; next change retries */ }
}

async function acctPrefs(prefs) {
  try {
    const r = await fetch("/api/auth/prefs", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
    const d = await r.json();
    if (d.user && acctState) acctState.user = d.user;
  } catch (e) {}
}

function acctPaintButton() {
  const b = $("acctBtn");
  if (!b) return;
  b.hidden = !ACCT_ON;
  b.textContent = acctSignedIn() ? "👤" : "👤 Sign in";
  b.title = acctSignedIn()
    ? "Your account — " + acctState.email
    : "Save your travel map to an account (works in private tabs)";
}

function acctModal(inner) {
  if (document.querySelector(".submodal")) return null;
  const m = document.createElement("div");
  m.className = "submodal";
  m.innerHTML = '<div class="submodal-card"><button class="submodal-x" aria-label="Close">✕</button>'
    + inner + "</div>";
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add("show"));
  const close = () => { m.classList.remove("show"); setTimeout(() => m.remove(), 220); };
  m.addEventListener("click", (e) => { if (e.target === m) close(); });
  m.querySelector(".submodal-x").onclick = close;
  const onKey = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  m.close = close;
  return m;
}

function openSignIn() {
  const m = acctModal(
    '<span class="sublabel">👤 Save your travel map</span>'
    + '<p class="hint">Your map is stored in this browser — private tabs throw it away.'
    + ' Sign in and it\'s saved to your account, on every device.</p>'
    + '<form class="subform acctform"><input type="email" name="email" placeholder="you@email.com" required>'
    + '<button type="submit">Email me a link</button></form>'
    + '<label class="acctcheck"><input type="checkbox" id="acctSub" checked>'
    + ' Also send me the monthly newsletter — the best-value places to travel</label>'
    + '<label class="acctcheck" id="acctCadWrap">How often:'
    + ' <select id="acctCad"><option value="monthly">Monthly</option>'
    + '<option value="quarterly">Every 3 months</option></select></label>'
    + '<span class="hint">No password — we email you a one-time link.</span>');
  if (!m) return;
  const sub = m.querySelector("#acctSub"), cadWrap = m.querySelector("#acctCadWrap");
  sub.onchange = () => { cadWrap.style.opacity = sub.checked ? "1" : ".4"; };
  m.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const email = m.querySelector('input[type="email"]').value.trim();
    if (!email) return;
    // Remember the newsletter choice so it can be applied once the link is
    // clicked (the click may land in a different tab).
    try {
      localStorage.setItem("wg_pending_prefs", JSON.stringify({
        subscribed: sub.checked,
        cadence: sub.checked ? m.querySelector("#acctCad").value : "off",
      }));
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
  const cad = u.cadence || "monthly";
  const m = acctModal(
    '<span class="sublabel">👤 Your account</span>'
    + `<p class="hint">Signed in as <b>${esc(acctState.email)}</b>. Your map syncs automatically.</p>`
    + '<label class="acctcheck"><input type="checkbox" id="acctSub2"' + (u.subscribed ? " checked" : "")
    + '> Monthly newsletter — the best-value places to travel</label>'
    + '<label class="acctcheck">How often: <select id="acctCad2">'
    + ["monthly", "quarterly", "off"].map((c) =>
        `<option value="${c}"${c === cad ? " selected" : ""}>${CADENCE_LABEL[c]}</option>`).join("")
    + "</select></label>"
    + '<div class="bulkfoot"><button type="button" class="bulkdone" id="acctOut">Sign out</button></div>');
  if (!m) return;
  const sub = m.querySelector("#acctSub2"), cadSel = m.querySelector("#acctCad2");
  const push = () => acctPrefs({ subscribed: sub.checked, cadence: cadSel.value });
  sub.onchange = () => {
    if (!sub.checked) cadSel.value = "off";
    else if (cadSel.value === "off") cadSel.value = "monthly";
    push();
  };
  cadSel.onchange = () => { sub.checked = cadSel.value !== "off"; push(); };
  m.querySelector("#acctOut").onclick = async () => {
    try { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); } catch (e) {}
    acctState = null;
    acctPaintButton();
    m.close();
    status("Signed out — your map stays in this browser.", "ok");
  };
}

if ($("acctBtn")) {
  acctPaintButton();
  $("acctBtn").addEventListener("click", () => (acctSignedIn() ? openAccount() : openSignIn()));
}
if (ACCT_ON) {
  acctLoad().then(async () => {
    const q = new URLSearchParams(location.search).get("signin");
    if (!q) return;
    history.replaceState(null, "", location.pathname);   // don't leave ?signin= around
    if (q === "expired") { status("That sign-in link expired — request a new one.", "err"); return; }
    if (acctSignedIn()) {
      let pending = null;
      try { pending = JSON.parse(localStorage.getItem("wg_pending_prefs") || "null"); } catch (e) {}
      if (pending) {
        localStorage.removeItem("wg_pending_prefs");
        await acctPrefs(pending);
      }
      await acctSync();               // seed the account with this device's map
      status("Signed in — your travel map is saved to " + acctState.email + " ✓", "ok");
    }
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
  if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
    btn.hidden = false;
  } else {
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferred = e;
      btn.hidden = false;
    });
  }
  window.addEventListener("appinstalled", () => { btn.hidden = true; });
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
    const close = () => { m.classList.remove("show"); setTimeout(() => m.remove(), 220); };
    m.addEventListener("click", (e) => { if (e.target === m) close(); });
    m.querySelector(".submodal-x").onclick = close;
    const onKey = (e) => { if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); } };
    document.addEventListener("keydown", onKey);
  });
})();

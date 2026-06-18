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
  // Where today's rate sits between the window low and high.
  const span = r.high - r.low;
  const pct = span > 0 ? ((r.rate_now - r.low) / span) * 100 : 50;
  const clamped = Math.max(0, Math.min(100, pct));
  return `<div class="range" title="low ${fmt(r.low)} · high ${fmt(r.high)}"><span style="left:${clamped}%"></span></div>`;
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
  for (const r of data.rows) {
    const tr = document.createElement("tr");
    if (r.favorable && r.watched) tr.className = "favorable";
    const sign = r.strength_pct >= 0 ? "pos" : "neg";
    const star = r.watched ? "" : ' <span title="not on watchlist" style="opacity:.4">·</span>';
    const pl = priceLevelForCurrency(r.code);
    // Advisory level of the currency's representative country, for the
    // hide-higher-risk filter (so the Iranian rial isn't row one).
    const ctry = currencyCountry(r.code);
    tr.dataset.adv = String((ctry && adv[ctry]) || 0);
    tr.innerHTML = `
      <td><span class="code">${esc(r.code)}</span>${star}<div class="name">${esc(r.name)}</div></td>
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
  worldGeo = await (await fetch("/world.geojson")).json();
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
  for (const f of worldGeo.features) {
    const { fill, title } = colorFn(f);
    const g = f.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    let d = "";
    for (const poly of polys)
      for (const ring of poly)
        if (ring.length >= 3) d += projectRing(ring, W, H, latTop, latBot);
    if (d) paths += `<path d="${d}" fill="${fill}" data-iso="${esc(f.properties.iso)}"><title>${esc(title)}</title></path>`;
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
  }
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
  renderGuideHero(iso);
  renderGuideVisa(iso);
  renderGuideAI(iso);
  renderCountryClimate(iso);
  renderActivity(iso);
  syncURL();
}

// Passport used for visa info = the "From" country chosen on Top Picks
// (your home country), defaulting to US.
function guidePassport() {
  const sel = $("valueOrigin");
  return (sel && /^[A-Z]{2}$/.test(sel.value)) ? sel.value : "US";
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
function loadHeroPhotos(iso) {
  const host = $("guideHero");
  if (!host) return;
  // Lead image (curated, reliably iconic) first, then more from Commons search.
  Promise.all([photoURL(iso, 1000).catch(() => null), photoGallery(iso).catch(() => [])])
    .then(([lead, more]) => {
      if (ccGuideIso !== iso) return;                 // user moved on
      const seen = new Set();
      heroUrls = []; heroIdx = 0;
      // Curated lead first (wrapped to {thumb, full}), then the Commons set.
      // Only keep the lead if it's a real /thumb/ URL — MediaWiki only returns
      // that when the original was large enough to scale, so it filters out the
      // small/low-res leads that look bad blown up.
      // Lead only if it's a real /thumb/ image AND not a flag/coat/map (some
      // country-name queries lead with the flag, which looked wrong cropped).
      const leadObj = (lead && lead.indexOf("/thumb/") !== -1 && !PHOTO_BAD.test(fileKey(lead)))
        ? { thumb: lead, full: origFromThumb(lead) } : null;
      for (const p of [leadObj].concat(more)) {
        if (!p || !p.thumb) continue;
        const k = fileKey(p.thumb);
        if (seen.has(k)) continue;
        seen.add(k); heroUrls.push(p);
        if (heroUrls.length >= 6) break;
      }
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
function closeLightbox() {
  const lb = $("lightbox");
  if (lb) lb.hidden = true;
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
const PHOTO_BAD = /map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram|\.svg|location|adm[_ ]|administrative|emblem|wikidata/i;
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
  const bars = c.scores.map((s, i) => {
    const h = s == null ? 0 : Math.round(s);
    const col = bestSet.has(i + 1) ? "col best" : "col";
    const hz = hzByMonth[i + 1];
    return `<div class="${col}" title="${MONTHS[i]}: ${s == null ? "n/a" : s + "/100"} · ${seas[i]} season${hz ? " · ⚠️ " + esc(hz) : ""}">
      <div class="mscore">${s == null ? "" : s}</div>
      <div class="fill" style="height:${h}%;background:${comfortColor(s)}"></div>
      <div class="mlabel ${seas[i]}">${MON_ABBR[i]}${hz ? "<span class='hzmark'>⚠️</span>" : ""}</div></div>`;
  }).join("");

  const hazardLines = hazards.map((h) =>
    `<div class="hazardline">⚠️ <b>${monthSpan(h.months)}:</b> ${esc(h.note)}</div>`).join("");

  $("bestDetail").innerHTML = `
    <div class="besthead">
      <h3>${esc(c.name)} <span class="muted">(${REGIONS[ISO_REGION[iso]] || "—"})</span></h3>
    </div>
    <div class="monthslabel">${c.curated ? "📅 Curated best months" : "📅 Best weather"}:</div>
    <div class="chips">${chips}</div>
    <div class="seasons">
      <span><b class="peak">☀️ Peak</b> (best weather, busiest &amp; priciest): ${fmtMonths(peakM)}</span>
      <span><b class="off">💸 Off-peak</b> (cheapest, fewest crowds): ${fmtMonths(offM)}</span>
    </div>
    ${hazardLines}
    <div class="bars">${bars}</div>`;
}

// (The standalone by-month map merged into "Where to go now" as a map mode.)

// ===========================================================================
//  Travel advisories
// ===========================================================================
let advisories = null;
async function ensureAdvisories() {
  if (!advisories) advisories = await getJSON("/api/advisories");
  return advisories;
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
  }, "US travel advisory levels");

  $("advSub").textContent =
    `${advisories.count} advisories from the US State Dept. Green = safest (Level 1), red = Do Not Travel (Level 4).`;
  $("advLegend").innerHTML = [1, 2, 3, 4]
    .map((l) => `<span><span class="swatch" style="background:${LVL_COLOR[l]}"></span>L${l}</span>`).join(" ");

  $("advRows").innerHTML = advisories.items.map((it) => {
    const lvl = parseInt(it.level, 10) || 0;
    const safeLink = /^https:\/\//.test(it.link || "") ? it.link : "";
    return `
    <tr data-lvl="${lvl}" data-iso="${esc(it.iso || "")}"><td>${esc(it.country)}</td>
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
  rows.sort((a, b) => a.pl - b.pl);
  $("affRows").innerHTML = rows.map((r) => {
    const cls = r.pl <= 0.85 ? "pos" : r.pl > 1.15 ? "neg" : "";
    return `<tr data-iso="${esc(r.iso)}"><td>${esc(r.name)}</td><td>${esc(r.cur)}</td>
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
  if (ccGuideIso) { renderGuideVisa(ccGuideIso); renderGuideAI(ccGuideIso); }  // guide visa + AI
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
  for (const f of worldGeo.features) {
    let sx = 0, sy = 0, n = 0;
    const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
    for (const poly of polys) for (const ring of poly) for (const pt of ring) { sx += pt[0]; sy += pt[1]; n++; }
    if (n) _centroids[f.properties.iso] = [sx / n, sy / n];
  }
  return _centroids;
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
  return lines.join("\n");
}
// Shared AI panel: shows the prompt with Copy / Open in ChatGPT / Open in
// Claude. Used by both the Top Picks shortlist export and the Travel Guide
// per-country button so they behave identically.
function renderAIPanel(host, prompt) {
  if (!host) return;
  const cg = "https://chatgpt.com/?q=" + encodeURIComponent(prompt);
  const cla = "https://claude.ai/new?q=" + encodeURIComponent(prompt);
  host.hidden = false;
  host.innerHTML =
    '<div class="airow">'
    + '<button type="button" class="aiact" data-act="copy">📋 Copy prompt</button>'
    + '<a class="aiact" href="' + cg + '" target="_blank" rel="noopener">Open in ChatGPT ↗</a>'
    + '<a class="aiact" href="' + cla + '" target="_blank" rel="noopener">Open in Claude ↗</a>'
    + '</div>'
    + '<textarea class="aitext" readonly rows="9">' + esc(prompt) + '</textarea>'
    + '<p class="hint">“Copy prompt” grabs the full version — paste into any AI. The buttons open a new chat with it pre-filled.</p>';
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
  lines.push("I'm planning a trip to " + name + " and used a travel-value tool (Wandergrade) for the basics. Use the info below (don't re-derive it) to help me build a plan.");
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
function flagEmoji(iso) {
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

// Render a ranked list as a compact report-card table. gem=true swaps the rank
// number for a 💎 (the hidden-gems list). The why-sentence moves to the row
// tooltip so the table itself stays scannable.
function renderGradeTable(host, list, month, gem) {
  if (!host) return;
  if (!list.length) { host.innerHTML = "<p class='hint'>No destinations match these filters.</p>"; return; }
  const rows = list.map((s, i) => {
    const hz = hazardsFor(s.iso, month);
    const wxTitle = `${s.wx}/100 weather comfort in ${MONTHS[month - 1]}` +
      (hz.length ? " — ⚠️ " + hz.map((h) => h.note).join("; ") : "");
    const iso = esc(s.iso);
    return `<tr data-iso="${iso}" title="${esc(whyLine(s, month))}" style="--i:${i}">
      <td class="rank">${gem ? "💎" : "#" + (i + 1)}</td>
      <td class="dest">${flagEmoji(s.iso)} ${esc(s.name)}</td>
      <td class="scell" data-go="afford" data-iso="${iso}">${gradePill(s.afford, affordTitle(s))}</td>
      <td class="scell" data-go="advisory" data-iso="${iso}">${safetyPill(s.advLvl)}</td>
      <td class="scell" data-go="weather" data-iso="${iso}">${gradePill(s.wx, wxTitle + " · click for the month-by-month guide")}${hz.length ? `<span class="hzmark" title="${esc(hz.map((h) => h.note).join("; "))}">⚠️</span>` : ""}</td>
      <td class="scell" data-go="flights" data-iso="${iso}">${s.fare == null ? '<span class="muted">—</span>'
            : (s.fareEst || s.fareBase == null) ? '<span class="muted" title="estimated — no cached fare; click for the Flights tab">~</span>'
            : gradePill(s.fly, "Flight deal vs the typical fare for this distance · click for exact prices")}</td>
      <td class="overall">${gradePill(s.value, `Overall value score ${s.value}/100`, "big")}<span class="grnum" title="value score out of 100">${s.value}</span></td>
    </tr>`;
  }).join("");
  host.innerHTML = `<table class="gradetable">
    <thead><tr><th></th><th class="dest">Destination</th>
      <th title="how far your money goes — daily prices vs home, plus how strong your currency is right now">💰 Affordability</th>
      <th title="US State Dept advisory level">🛡️ Safety</th>
      <th title="weather comfort for your chosen month">🌤️ Weather</th>
      <th title="flight deal: fare vs the typical price for this distance (exact prices in the Flights tab)">✈️ Flights</th>
      <th title="everything blended, weighted by your priorities">Overall</th></tr></thead>
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
  const eligible = rankedAll.filter((s) => !visited.has(s.iso) && passesFloor(s, floor));
  const popular = eligible.filter((s) => popularSet.has(s.iso));
  const offbeat = eligible.filter((s) => !popularSet.has(s.iso));
  // Fall back to the full list if no popular destinations match the filters.
  const picks = (popular.length ? popular : eligible).slice(0, pickCount());
  const picksNote = $("picksNote");
  if (picksNote) picksNote.innerHTML = popular.length
    ? `🌍 The most-popular destinations${popularDataBacked ? " (by international tourism spend)" : ""}, ranked by value — lesser-known high-value spots are in 💎 Hidden gems below.`
    : "Ranked by overall value — no mainstream destinations match these filters, so showing everything.";
  lastPicks = picks; lastPicksMonth = month;   // for the AI export
  renderGradeTable($("topCards"), picks, month, false);
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
  const gems = (popular.length ? offbeat : []).slice(0, 8);
  const gemsBox = $("gemsBox");
  if (gemsBox) {
    gemsBox.hidden = !gems.length;
    if (gems.length) renderGradeTable($("gemRows"), gems, month, true);
  }
  const ranked = rankedAll.slice(0, 40);
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
    `Average international round-trips from ${esc(flightsData.origin_name || flightsData.origin)} (via ${esc(flightsData.hub)}) · ${countries.length} destination countries · greener = cheaper · <span class="farearrow dn">▼</span> below / <span class="farearrow up">▲</span> above the typical fare for the distance.`;
  $("flightLegend").innerHTML =
    '<span>Cheaper</span><span class="bar" style="background:linear-gradient(90deg,#0a7d28,#eef0f1,#b00020)"></span><span>Pricier</span>';

  $("flightRows").innerHTML = countries.map((c) => {
    const exp = expected ? expected(c.iso) : null;
    const arrow = priceArrow(Number(c.avg) || null, exp, "the typical fare for this distance");
    return `<tr data-iso="${esc(c.iso)}"><td>${esc(countryName(c.iso))}</td>
      <td class="num"><b>${esc(cur)} ${Number(c.avg) || "?"}</b> ${arrow}</td>
      <td class="num">${esc(cur)} ${Number(c.min) || "?"}</td>
      <td class="num">${fmtDuration(c.dur)}</td>
      <td class="num">${fmtStops(c.stops)}</td>
      <td class="num">${Number(c.n) || 0}</td></tr>`;
  }).join("")
    || '<tr><td colspan="6">No fares found from this country.</td></tr>';
  applyFlightFilter();
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

function renderActivity(iso) {
  const a = activities[iso];
  const name = (climate && climate[iso] && climate[iso].name) || (ppp[iso] && ppp[iso].name) || iso;
  if (!a) { $("actDetail").innerHTML = `<h3>${esc(name)}</h3><p class="hint">No curated activity profile yet.</p>`; return; }
  const m = curMonth();
  const tags = a.profile.map((p) =>
    `<span class="chip2">${PROFILE_EMOJI[p] ? PROFILE_EMOJI[p] + " " : ""}${esc(p)}</span>`).join("");
  const acts = a.activities.map((x) =>
    `<li><span class="actemoji">${activityEmoji(x)}</span>${esc(x)}</li>`).join("");
  const seas = (a.seasonal || []).map((s) => {
    const on = s.months.includes(m);
    return `<div class="seasrow">
      <span class="what"><span class="actemoji">${activityEmoji(s.what)}</span>${esc(s.what)}</span>
      <span class="months">${s.months.map((x) => MON_ABBR[x - 1]).join(", ")}</span>
      <span class="${on ? "inseason" : "offseason"}">${on ? "in season now" : "off season"}</span>
    </div>`;
  }).join("");
  const vis = isVisited(iso) ? '<span class="visited-tag">✓ visited</span>' : "";
  // Summary line dropped — it just restated the "things to do" bullets below.
  $("actDetail").innerHTML = `
    <div class="besthead"><h3>${esc(name)} ${vis} <span class="muted">(${REGIONS[ISO_REGION[iso]] || "—"})</span></h3></div>
    <div class="chips">${tags}</div>
    <h4 style="margin:.6em 0 .2em">🎒 Top things to do</h4>
    <ul class="actlist">${acts}</ul>
    ${seas ? `<h4 style="margin:.6em 0 .2em">🗓️ What's in season <span class="muted">(now: ${MONTHS[m - 1]})</span></h4>${seas}` : ""}`;
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
function saveVisited() { localStorage.setItem("fx_visited", JSON.stringify([...visited])); }
function saveWishlist() { localStorage.setItem("fx_wishlist", JSON.stringify([...wishlist])); }
function isVisited(iso) { return loadVisited().has(iso); }
// Toggle a country in the active list; the two lists are mutually exclusive
// (you've either been or you want to go, not both).
function toggleMark(iso) {
  loadVisited(); loadWishlist();
  const on = visitMode === "visited" ? visited : wishlist;
  const other = visitMode === "visited" ? wishlist : visited;
  if (on.has(iso)) on.delete(iso); else { on.add(iso); other.delete(iso); }
  saveVisited(); saveWishlist();
}

let _displayNames = null;
function countryName(iso) {
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

function buildVisited() {
  loadVisited(); loadWishlist();
  const pick = $("visitedPick");
  // dropdown of all mappable countries by name
  const all = [...new Set(Object.keys(CUR_BY_ISO))]
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  pick.innerHTML = '<option value="">+ add a country…</option>' +
    all.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("");
  enhanceSelect(pick);
  pick.onchange = () => { if (pick.value) { toggleMark(pick.value); pick.value = ""; if (pick._sync) pick._sync(); renderVisited(); } };
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
  drawMap("visitedMap", (f) => {
    const iso = f.properties.iso;
    if (visited.has(iso)) return { fill: VISITED_COLOR, title: f.properties.name + " — been ✓ (click to remove)" };
    if (wishlist.has(iso)) return { fill: WISH_COLOR, title: f.properties.name + " — want to go ★ (click to remove)" };
    return { fill: "#e0e4e8",
      title: f.properties.name + " — click to mark " + (visitMode === "visited" ? "been" : "want to go") };
  }, "Your travel map");
  const chipsFor = (set, cls) => [...set].map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `<span class="chip2 rm ${cls}" data-iso="${esc(c.iso)}" title="remove">${esc(c.name)} ✕</span>`).join("");
  $("visitedSub").innerHTML =
    `<b style="color:${VISITED_COLOR}">${visited.size} been</b> · ` +
    `<b style="color:${WISH_COLOR}">${wishlist.size} want to go</b> — ` +
    `marking <b>${visitMode === "visited" ? "✓ been" : "★ want to go"}</b>. Click the map or pick a country.`;
  const sections = [];
  if (visited.size) sections.push('<div class="chiprow"><span class="chiplabel">✓ Been</span>' + chipsFor(visited, "v") + '</div>');
  if (wishlist.size) sections.push('<div class="chiprow"><span class="chiplabel">★ Want to go</span>' + chipsFor(wishlist, "w") + '</div>');
  $("visitedChips").innerHTML = sections.join("") ||
    '<span class="hint">Nothing yet — click countries on the map.</span>';
  syncURL();
}

// ===========================================================================
//  Tab switching (lazy-load each tab's data on first open)
// ===========================================================================
const loaded = {};
async function activateTab(name, push) {
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

function renderSubscribe() {
  const el = $("subscribe");
  if (!el) return;
  if (!BUTTONDOWN_USER) {
    el.innerHTML = '<span class="hint">📬 Newsletter signup not configured yet — set BUTTONDOWN_USER in app.js once you have a Buttondown account.</span>';
    return;
  }
  const base = "https://buttondown.com/" + BUTTONDOWN_USER;
  el.innerHTML = `
    <span class="sublabel">📬 Once a month: the best-value places to travel, straight to your inbox.</span>
    <form action="https://buttondown.com/api/emails/embed/subscribe/${BUTTONDOWN_USER}"
          method="post" target="popupwindow"
          onsubmit="window.open('${base}','popupwindow')" class="subform">
      <input type="email" name="email" placeholder="you@email.com" required>
      <button type="submit">Subscribe</button>
    </form>`;
}

// ===========================================================================
//  Share: encode the current tab + settings into a URL anyone can open
// ===========================================================================
function currentTab() {
  const b = document.querySelector("#tabs button.active");
  return b ? b.dataset.tab : "value";
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
  } else if (tab === "guide") {
    q.set("gc", $("bestCountry").value || "JP");
  } else if (tab === "visited") {
    loadVisited();
    // The visited list persists in localStorage already; only embed it for an
    // explicit Share (embedding it on every refresh would wrongly trip the
    // "viewing a shared map" warning against the user's own list).
    if (visited.size && forShare) q.set("v", [...visited].join(","));
  }
  return location.origin + location.pathname + "?" + q.toString();
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
const SHARE_SCALE = 3;   // render at 3x so it stays crisp even zoomed

// Refine the app's 6 regions into true continents for the "N continents" flex.
const _SOUTH_AMERICA = new Set("CO VE GY SR EC PE BR BO PY CL AR UY GF FK".split(" "));
const _MENA_AFRICA = new Set("EG MA DZ TN LY".split(" "));
function continentOf(iso) {
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
// Honest, count-based milestone tiers (not a fabricated "top X%" percentile).
function travelMilestone(n) {
  return n >= 100 ? "🏆 100+ Club" : n >= 50 ? "⭐ Globe Master"
       : n >= 25 ? "🌟 Seasoned Traveler" : n >= 15 ? "🌍 Globetrotter"
       : n >= 7 ? "🧭 Explorer" : null;
}

// orientation: "landscape" (1200x630, for X/LinkedIn/FB) or "story" (1080x1920,
// for Instagram/TikTok Stories). Returns { svg, W, H, flag } — flags are drawn
// on the canvas afterward (SVG can't render emoji).
function buildVisitedShareSVG(orientation) {
  const story = orientation === "story";
  const W = story ? STORY_W : SHARE_W, H = story ? STORY_H : SHARE_H;
  const n = visited.size, m = wishlist.size, pct = Math.max(1, Math.round((n / 195) * 100));
  const cont = visitedContinents(), badge = travelMilestone(n);
  const host = esc(location.host || "wandergrade.com");
  const font = "-apple-system,'Segoe UI',Arial,sans-serif";

  const mapW = story ? 1040 : 960, latTop = 80, latBot = -56;
  const mapH = Math.round((mapW * (latTop - latBot)) / 360);
  let paths = "";
  for (const f of worldGeo.features) {
    const iso = f.properties.iso;
    const fill = visited.has(iso) ? "#34d27b" : wishlist.has(iso) ? "#4f9bf0" : "#243449";
    const g = f.geometry, polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    let d = "";
    for (const poly of polys) for (const ring of poly)
      if (ring.length >= 3) d += projectRing(ring, mapW, mapH, latTop, latBot);
    if (d) paths += `<path d="${d}" fill="${fill}" stroke="#0c1422" stroke-width="0.6"/>`;
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
    + `<stop offset="0" stop-color="#10192e"/><stop offset="1" stop-color="#0a1220"/></linearGradient></defs>`
    + `<rect width="${W}" height="${H}" fill="url(#bg)"/>`;

  let inner, flag;
  if (story) {
    const cx = W / 2, big = String(n || m || 0);
    inner = `
      <text x="${cx}" y="160" text-anchor="middle" font-family="${font}" font-size="30" font-weight="800" letter-spacing="6" fill="#7fd99a">🗺️ WANDERLIST</text>
      <text x="${cx}" y="440" text-anchor="middle" font-family="${font}" font-size="260" font-weight="800" fill="#34d27b">${big}</text>
      <text x="${cx}" y="520" text-anchor="middle" font-family="${font}" font-size="48" font-weight="700" fill="#ffffff">${n ? (n === 1 ? "country visited" : "countries visited") : "on my wishlist"}</text>
      ${badge ? pill(cx, 610, badge, "middle") : ""}
      ${statLine ? `<text x="${cx}" y="${badge ? 700 : 660}" text-anchor="middle" font-family="${font}" font-size="36" fill="#9fb3cd">${esc(statLine)}</text>` : ""}
      <g transform="translate(${(W - mapW) / 2},900)">${paths}</g>
      ${listLine ? `<text x="${cx}" y="1480" text-anchor="middle" font-family="${font}" font-size="34" fill="#9fb3cd">✦ ${esc(listLine)}</text>` : ""}
      <circle cx="${cx - 168}" cy="1632" r="9" fill="#34d27b"/><text x="${cx - 150}" y="1641" font-family="${font}" font-size="28" font-weight="600" fill="#9fb3cd">been</text>
      <circle cx="${cx + 14}" cy="1632" r="9" fill="#4f9bf0"/><text x="${cx + 32}" y="1641" font-family="${font}" font-size="28" font-weight="600" fill="#9fb3cd">want to go</text>
      <text x="${cx}" y="1772" text-anchor="middle" font-family="${font}" font-size="32" fill="#8fa3bd">Make your own map →</text>
      <text x="${cx}" y="1822" text-anchor="middle" font-family="${font}" font-size="42" font-weight="800" fill="#7fd99a">${host}</text>`;
    flag = { x: cx, y: 1350, size: 46, align: "center" };
  } else {
    const headline = n
      ? `I've been to <tspan font-size="58" fill="#34d27b">${n}</tspan> ${n === 1 ? "country" : "countries"}`
      : `My travel <tspan fill="#34d27b">Wanderlist</tspan>`;
    const subParts = [statLine, listLine].filter(Boolean).join("   ·   ");
    inner = `
      <text x="60" y="52" font-family="${font}" font-size="20" font-weight="800" letter-spacing="3" fill="#7fd99a">🗺️ WANDERLIST</text>
      ${badge ? pill(W - 50, 50, badge, "end") : ""}
      <text x="60" y="116" font-family="${font}" font-size="42" font-weight="800" fill="#ffffff">${headline}</text>
      ${subParts ? `<text x="60" y="150" font-family="${font}" font-size="21" fill="#9fb3cd">${esc(subParts)}</text>` : ""}
      <g transform="translate(${(W - mapW) / 2},168)">${paths}</g>
      <rect x="0" y="${H - 48}" width="${W}" height="48" fill="#0a1220"/>
      <rect x="0" y="${H - 49}" width="${W}" height="1.5" fill="#1c2940"/>
      <circle cx="68" cy="${H - 24}" r="7" fill="#34d27b"/><text x="83" y="${H - 18}" font-family="${font}" font-size="19" font-weight="600" fill="#9fb3cd">been</text>
      <circle cx="152" cy="${H - 24}" r="7" fill="#4f9bf0"/><text x="167" y="${H - 18}" font-family="${font}" font-size="19" font-weight="600" fill="#9fb3cd">want to go</text>
      <text x="${W - 60}" y="${H - 18}" text-anchor="end" font-family="${font}" font-size="19" font-weight="700" fill="#7fd99a">Make your own → ${host}</text>`;
    flag = { x: 60, y: H - 64, size: 30, align: "left" };
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W * SHARE_SCALE}" height="${H * SHARE_SCALE}" viewBox="0 0 ${W} ${H}">${grad}${inner}</svg>`;
  return { svg, W, H, flag };
}

async function downloadVisitedImage(orientation) {
  try {
    await ensureWorld();
    loadVisited(); loadWishlist();
    const { svg, W, H, flag } = buildVisitedShareSVG(orientation);
    const blobUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = blobUrl; });
    const canvas = document.createElement("canvas");
    canvas.width = W * SHARE_SCALE; canvas.height = H * SHARE_SCALE;
    const ctx = canvas.getContext("2d");
    ctx.scale(SHARE_SCALE, SHARE_SCALE);
    ctx.drawImage(img, 0, 0, W, H);
    URL.revokeObjectURL(blobUrl);
    // Flag emojis of the countries you've been to (canvas fillText renders emoji
    // where the SVG path can't). Capped so a big list doesn't overflow.
    const flags = [...visited].slice(0, 26);
    if (flags.length && flag) {
      ctx.font = flag.size + "px -apple-system,'Segoe UI',Arial,sans-serif";
      ctx.textBaseline = "alphabetic";
      ctx.textAlign = flag.align === "center" ? "center" : "left";
      let line = flags.map((iso) => flagEmoji(iso)).join(" ");
      if (visited.size > flags.length) line += "  +" + (visited.size - flags.length);
      ctx.fillText(line, flag.x, flag.y, W - 120);
      ctx.textAlign = "left";
    }
    const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
    const name = orientation === "story" ? "wanderlist-story.png" : "wanderlist-map.png";
    const file = new File([blob], name, { type: "image/png" });
    // Native share sheet on phones (posts straight to socials); download elsewhere.
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: "My Wanderlist" }); return; }
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
$("visitedImage").addEventListener("click", () => downloadVisitedImage("landscape"));
if ($("visitedStory")) $("visitedStory").addEventListener("click", () => downloadVisitedImage("story"));
if ($("aiExport")) $("aiExport").addEventListener("click", exportAIPrompt);
// ("Use on another device" was removed — the Share button already produces a
//  URL carrying your map across devices.)

(async function init() {
  initTheme();
  renderSubscribe();
  preApplyShared();
  // On a public deployment the server disables settings + manual email; hide them.
  getJSON("/api/config").then((c) => {
    if (c.readonly) { $("toggleSettings").hidden = true; $("check").hidden = true; }
  }).catch(() => {});
  // Load the currency data (the "Where to go" score needs live rates + PPP),
  // render the currency tab in the background, then open the verdict tab.
  await Promise.all([ensurePPP().catch(() => {}), ensureWorld().catch(() => {}), loadRates()]);
  renderMapSafe();
  loadIndex(365);
  await activateTab("value");
  await postApplyShared().catch(() => {});
  appReady = true;          // from here on, user navigation is mirrored to the URL
  syncURL();
})();

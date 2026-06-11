"use strict";

const $ = (id) => document.getElementById(id);
let lastRates = null;

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
  const stored = localStorage.getItem("fx_theme");
  const t = stored || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = t;
  const btn = $("themeBtn");
  if (btn) {
    btn.textContent = t === "dark" ? "☀️" : "🌙";
    btn.onclick = () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
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
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="USD strength index over time">` +
    grid + baseline +
    `<path d="${area}" fill="${fill}"/>` +
    `<path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>` +
    `<circle cx="${lastX}" cy="${lastY}" r="3.5" fill="${color}"/>` +
    xlab +
    `</svg>`;
}

function renderRates(data) {
  lastRates = data;
  renderMapSafe();
  $("asof").textContent = "As of " + data.as_of;
  const fav = data.rows.filter((r) => r.favorable && r.watched);
  $("summary").textContent =
    `${data.rows.length} currencies · ${fav.length} favorable (≥ +${data.threshold_pct}% vs ${data.baseline_days}-day avg)`;

  const tbody = $("rows");
  tbody.innerHTML = "";
  for (const r of data.rows) {
    const tr = document.createElement("tr");
    if (r.favorable && r.watched) tr.className = "favorable";
    const sign = r.strength_pct >= 0 ? "pos" : "neg";
    const star = r.watched ? "" : ' <span title="not on watchlist" style="opacity:.4">·</span>';
    const pl = priceLevelForCurrency(r.code);
    tr.innerHTML = `
      <td><span class="code">${esc(r.code)}</span>${star}<div class="name">${esc(r.name)}</div></td>
      <td class="num">${fmt(r.rate_now)}</td>
      <td class="num ${sign}">${r.strength_pct >= 0 ? "+" : ""}${r.strength_pct}%</td>
      <td class="num">${pl == null ? "—" : pl.toFixed(2) + " " + plTag(pl)}</td>
      <td class="num">${rangeMarker(r)}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadRates() {
  status("Fetching rates…");
  try {
    renderRates(await getJSON("/api/rates"));
    status("");
  } catch (e) {
    status("Could not load rates: " + e.message, "err");
  }
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
    lastIndexData = await getJSON("/api/index?days=" + days);
    renderIndex(lastIndexData);
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
      <button data-cc="visit">${vis ? "Unmark visited" : "Mark visited"}</button>
    </div>`;
  card.querySelector(".ccclose").onclick = () => { card.remove(); ccCurrent = null; };
  const todo = card.querySelector('[data-cc="todo"]');
  if (todo) todo.onclick = () => openGuideFor(iso);
  card.querySelector('[data-cc="visit"]').onclick = () => {
    toggleVisited(iso);
    renderCountryCard();
    if (loaded.value && !$("tab-value").hidden) renderValue();
    if (loaded.visited) renderVisited();
  };
}

function renderMap(rows) {
  const byCode = {};
  for (const r of rows) byCode[r.code] = r;
  const sgn = (p) => (p >= 0 ? "+" : "") + p + "%";

  let tracked = 0;
  drawMap("map", (f) => {
    const iso = f.properties.iso, cur = CUR_BY_ISO[iso];
    const row = cur && cur !== "USD" ? byCode[cur] : null;
    if (cur === "USD") {
      return { fill: USDLINK, title: iso === "US"
        ? f.properties.name + " — USD (home currency)"
        : `${f.properties.name} — uses the US dollar (flat for your dollar)` };
    }
    if (row) {
      tracked++;
      return { fill: strengthColor(row.strength_pct),
        title: `${f.properties.name} — ${cur}: ${sgn(row.strength_pct)} vs 1yr avg` };
    }
    return { fill: NODATA, title: f.properties.name + " — not tracked" };
  }, "USD strength world heatmap");

  $("mapsub").textContent =
    `Greener = dollar stronger vs that country's currency. Hover for detail · ${tracked} countries tracked.`;
  renderLegend();
}

function renderLegend() {
  $("legend").innerHTML =
    '<span>Weaker</span><span class="bar"></span><span>Stronger</span>' +
    '<span style="margin-left:8px"><span class="swatch" style="background:#bcd0e6"></span>USD-linked</span>' +
    '<span style="margin-left:6px"><span class="swatch"></span>No data</span>';
}

function renderMapSafe() {
  if (worldGeo && lastRates) renderMap(lastRates.rows);
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
  renderCountryClimate(iso);
  renderActivity(iso);
}

function buildBestPickers() {
  const reg = $("bestRegion"), ctry = $("bestCountry");
  reg.innerHTML = '<option value="all">All regions</option>' +
    Object.keys(REGIONS).map((r) => `<option value="${r}">${REGIONS[r]}</option>`).join("");
  const fill = () => {
    const sel = reg.value;
    const list = Object.keys(climate)
      .filter((iso) => sel === "all" || ISO_REGION[iso] === sel)
      .map((iso) => ({ iso, name: climate[iso].name }))
      .sort((a, b) => a.name.localeCompare(b.name));
    ctry.innerHTML = list.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("");
    if (list.length) renderGuide(ctry.value);
  };
  reg.onchange = fill;
  ctry.onchange = () => renderGuide(ctry.value);
  fill();
  if ([...ctry.options].some((o) => o.value === "JP")) { ctry.value = "JP"; renderGuide("JP"); }
}

// Open the guide tab focused on a specific country (used by the map detail card).
async function openGuideFor(iso) {
  await activateTab("guide");
  const ctry = $("bestCountry");
  if ([...ctry.options].some((o) => o.value === iso)) ctry.value = iso;
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

  const chips = c.best.map((m) => `<span class="chip2">${MON_ABBR[m - 1]}</span>`).join("");
  const bars = c.scores.map((s, i) => {
    const h = s == null ? 0 : Math.round(s);
    const col = bestSet.has(i + 1) ? "col best" : "col";
    return `<div class="${col}" title="${MONTHS[i]}: ${s == null ? "n/a" : s + "/100"} · ${seas[i]} season">
      <div class="mscore">${s == null ? "" : s}</div>
      <div class="fill" style="height:${h}%;background:${comfortColor(s)}"></div>
      <div class="mlabel ${seas[i]}">${MON_ABBR[i]}</div></div>`;
  }).join("");

  $("bestDetail").innerHTML = `
    <div class="besthead">
      <h3>${esc(c.name)} <span class="muted">(${REGIONS[ISO_REGION[iso]] || "—"})</span></h3>
      <div>${c.curated ? "Curated best months" : "Best weather"}: </div>
    </div>
    <div class="chips">${chips}</div>
    <div class="seasons">
      <span><b class="peak">● Peak</b> (best weather, busiest &amp; priciest): ${fmtMonths(peakM)}</span>
      <span><b class="off">● Off-peak</b> (cheapest, fewest crowds): ${fmtMonths(offM)}</span>
    </div>
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
    <tr><td>${esc(it.country)}</td>
      <td><span class="lvl lvl${lvl}">Level ${lvl}</span></td>
      <td>${esc(it.level_text)}${safeLink ? ` · <a href="${esc(safeLink)}" target="_blank" rel="noopener">details</a>` : ""}</td>
    </tr>`;
  }).join("");
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
    `Below 1.00 = cheaper than the US (your dollar buys more). World Bank PPP ÷ live rate · ${n} countries.`;
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
    return `<tr><td>${esc(r.name)}</td><td>${esc(r.cur)}</td>
      <td class="num ${cls}">${r.pl.toFixed(2)}</td>
      <td class="num">$${Math.round(100 / r.pl)} of US goods</td>
      <td>${plWord(r.pl)}</td></tr>`;
  }).join("");
}

// ===========================================================================
//  Best value now (blend affordability + currency timing + safety + weather)
// ===========================================================================
const clamp100 = (x) => Math.max(0, Math.min(100, Math.round(x)));

// User-adjustable priorities: High / Medium / Low per factor (simpler than
// numeric sliders). "fly" only participates for countries with a fare loaded.
const WEIGHT_DEFS = [
  { key: "aff",  label: "Cheap",    def: "high" },
  { key: "cur",  label: "$ timing", def: "med" },
  { key: "safe", label: "Safety",   def: "med" },
  { key: "wx",   label: "Weather",  def: "med" },
  { key: "fly",  label: "Flights",  def: "med" },
];
const PRI_LEVELS = [["high", "High"], ["med", "Med"], ["low", "Low"]];
const PRI_W = { high: 3, med: 2, low: 1 };   // relative weights, normalized at score time
let priorities = null;

function loadPriorities() {
  if (priorities) return priorities;
  try { priorities = JSON.parse(localStorage.getItem("fx_priorities") || "null"); } catch (e) {}
  if (!priorities) priorities = {};
  for (const w of WEIGHT_DEFS) if (!PRI_W[priorities[w.key]]) priorities[w.key] = w.def;
  return priorities;
}
function savePriorities() { localStorage.setItem("fx_priorities", JSON.stringify(priorities)); }

// Numeric weights for the scorer, derived from the chosen priority levels.
function loadWeights() {
  const p = loadPriorities();
  return Object.fromEntries(WEIGHT_DEFS.map((w) => [w.key, PRI_W[p[w.key]]]));
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

function valueScores(iso, month, advMap, fares) {
  const pl = priceLevel(iso);
  if (pl == null) return null;                       // need affordability to rank
  const advLvl = advMap[iso];
  if (advLvl === 4) return null;                     // Do Not Travel: excluded outright
  const cur = CUR_BY_ISO[iso];
  const row = cur && cur !== "USD" ? lastRates.rows.find((r) => r.code === cur) : null;
  const cl = climate && climate[iso];

  const w = loadWeights();
  const comps = {
    aff: clamp100((1.3 - pl) / 1.1 * 100),
    cur: row ? clamp100(50 + row.strength_pct * 4) : 50,
    safe: advLvl ? { 1: 100, 2: 70, 3: 35 }[advLvl] : 70,
    wx: cl && cl.scores[month - 1] != null ? cl.scores[month - 1] : 50,
  };
  let fare = null;
  if (fares && fares.prices[iso] != null) {
    fare = fares.prices[iso];
    comps.fly = fares.max > fares.min
      ? clamp100(((fares.max - fare) / (fares.max - fares.min)) * 100) : 50;
  }
  // Weighted mean over the components this country actually has.
  let num = 0, den = 0;
  for (const k in comps) { num += (w[k] || 0) * comps[k]; den += (w[k] || 0); }
  const value = den ? clamp100(num / den) : 0;
  return { iso, name: (cl && cl.name) || (ppp[iso] && ppp[iso].name) || iso,
           aff: comps.aff, cur: comps.cur, safe: comps.safe, wx: comps.wx,
           fly: comps.fly, fare, advLvl, value };
}

let valueMapMode = "score";

async function loadValueFlights() {
  const origin = $("valueOrigin").value || "US";
  $("valueFlightsBtn").textContent = "loading…";
  try {
    const data = await getJSON("/api/flights?origin=" + encodeURIComponent(origin));
    if (!data.configured) {
      status("Flight prices need TRAVELPAYOUTS_TOKEN on the server — see the Flight prices tab.", "err");
    } else {
      flightsData = data;
      status(`Average fares from ${data.origin_name || origin} folded into the score.`, "ok");
    }
  } catch (e) {
    status("Could not load flights: " + e.message, "err");
  }
  $("valueFlightsBtn").textContent = "+ flights";
  renderValue();
}

function buildValueTab() {
  const reg = $("valueRegion"), mon = $("valueMonth");
  reg.innerHTML = '<option value="all">All regions</option>' +
    Object.keys(REGIONS).map((r) => `<option value="${r}">${REGIONS[r]}</option>`).join("");
  mon.innerHTML = MONTHS.map((m, i) => `<option value="${i + 1}">${m}</option>`).join("");
  reg.onchange = renderValue;
  mon.onchange = renderValue;
  $("valueFlightsBtn").onclick = loadValueFlights;
  fillOriginSelect($("valueOrigin")).catch(() => {});
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
}

function renderValue() {
  const region = $("valueRegion").value;
  const month = parseInt($("valueMonth").value, 10);
  const advMap = advisoryByIso();

  // Fare context: cheapest fare per country, min/max for normalization.
  let fares = null;
  if (flightsData && flightsData.configured && flightsData.by_country) {
    const prices = flightsData.by_country;
    const vals = Object.values(prices);
    if (vals.length) fares = { prices, min: Math.min(...vals), max: Math.max(...vals) };
  }

  const scored = {};
  for (const iso in CUR_BY_ISO) {
    if (region !== "all" && ISO_REGION[iso] !== region) continue;
    const s = valueScores(iso, month, advMap, fares);
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
        title: `${s.name}: value ${s.value}/100 (cheap ${s.aff}, $ ${s.cur}, safe ${s.safe}, wx ${s.wx}${s.fly != null ? ", fly " + s.fly : ""})` };
      if (advMap[f.properties.iso] === 4)
        return { fill: "#b00020", title: f.properties.name + " — Level 4: Do Not Travel (excluded)" };
      return { fill: NODATA, title: f.properties.name + " — not scored" };
    }, "Best value destinations");
  }

  loadVisited();
  const ranked = Object.values(scored).sort((a, b) => b.value - a.value).slice(0, 40);
  $("valueRows").innerHTML = ranked.map((s) => {
    const vis = visited.has(s.iso) ? ' <span class="visited-tag">✓ visited</span>' : "";
    const adv = s.advLvl === 2 ? ' <span class="advtag a2" title="Level 2: Exercise Increased Caution">L2</span>'
              : s.advLvl === 3 ? ' <span class="advtag a3" title="Level 3: Reconsider Travel">L3</span>' : "";
    const flight = s.fare != null ? `$${Math.round(s.fare)}` : "—";
    return `<tr${visited.has(s.iso) ? ' style="opacity:.55"' : ""}><td>${esc(s.name)}${adv}${vis}</td>
      <td class="num"><b>${s.value}</b></td>
      <td class="num">${s.aff}</td><td class="num">${s.cur}</td>
      <td class="num">${s.safe}</td><td class="num">${s.wx}</td>
      <td class="num">${flight}</td></tr>`;
  }).join("") || '<tr><td colspan="7">No data for this region.</td></tr>';
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
  sel.innerHTML = list.map((o) =>
    `<option value="${esc(o.iso)}"${o.iso === "US" ? " selected" : ""}>${esc(o.name)}</option>`).join("");
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
    $("flightRows").innerHTML = '<tr><td colspan="4">Add TRAVELPAYOUTS_TOKEN to enable.</td></tr>';
    return;
  }
  renderFlights();
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

  drawMap("flightMap", (f) => {
    const p = byC[f.properties.iso];
    return p == null
      ? { fill: NODATA, title: f.properties.name + " — no fares sampled" }
      : { fill: flightColor(p, min, max), title: `${f.properties.name} — avg ${cur} ${p} round-trip` };
  }, "Average flight prices by destination country");

  $("flightSub").textContent =
    `Average international round-trips from ${flightsData.origin_name || flightsData.origin} (via ${flightsData.hub}) · ${countries.length} destination countries · greener = cheaper.`;
  $("flightLegend").innerHTML =
    '<span>Cheaper</span><span class="bar" style="background:linear-gradient(90deg,#0a7d28,#eef0f1,#b00020)"></span><span>Pricier</span>';

  $("flightRows").innerHTML = countries.map((c) => `
    <tr><td>${esc(countryName(c.iso))}</td>
      <td class="num"><b>${esc(cur)} ${Number(c.avg) || "?"}</b></td>
      <td class="num">${esc(cur)} ${Number(c.min) || "?"}</td>
      <td class="num">${Number(c.n) || 0}</td></tr>`).join("")
    || '<tr><td colspan="4">No fares found from this country.</td></tr>';
}

$("flightGo").addEventListener("click", loadFlights);

// ===========================================================================
//  Things to do (curated activities + what's in season now)
// ===========================================================================
let activities = null;
function curMonth() { return new Date().getMonth() + 1; }   // 1-12, real browser clock

async function ensureActivities() {
  if (!activities) activities = await (await fetch("/activities.json")).json();
  return activities;
}

function renderActivity(iso) {
  const a = activities[iso];
  const name = (climate && climate[iso] && climate[iso].name) || (ppp[iso] && ppp[iso].name) || iso;
  if (!a) { $("actDetail").innerHTML = `<h3>${esc(name)}</h3><p class="hint">No curated activity profile yet.</p>`; return; }
  const m = curMonth();
  const tags = a.profile.map((p) => `<span class="chip2">${esc(p)}</span>`).join("");
  const acts = a.activities.map((x) => `<li>${esc(x)}</li>`).join("");
  const seas = (a.seasonal || []).map((s) => {
    const on = s.months.includes(m);
    return `<div class="seasrow">
      <span class="what">${esc(s.what)}</span>
      <span class="months">${s.months.map((x) => MON_ABBR[x - 1]).join(", ")}</span>
      <span class="${on ? "inseason" : "offseason"}">${on ? "in season now" : "off season"}</span>
    </div>`;
  }).join("");
  const vis = isVisited(iso) ? '<span class="visited-tag">✓ visited</span>' : "";
  $("actDetail").innerHTML = `
    <div class="besthead"><h3>${esc(name)} ${vis} <span class="muted">(${REGIONS[ISO_REGION[iso]] || "—"})</span></h3></div>
    <div class="chips">${tags}</div>
    <p>${esc(a.summary)}</p>
    <h4 style="margin:.6em 0 .2em">Top things to do</h4>
    <ul class="actlist">${acts}</ul>
    ${seas ? `<h4 style="margin:.6em 0 .2em">What's in season (now: ${MONTHS[m - 1]})</h4>${seas}` : ""}`;
}

// ===========================================================================
//  Countries visited (stored in this browser)
// ===========================================================================
let visited = null;
function loadVisited() {
  if (visited) return visited;
  try { visited = new Set(JSON.parse(localStorage.getItem("fx_visited") || "[]")); }
  catch (e) { visited = new Set(); }
  return visited;
}
function saveVisited() { localStorage.setItem("fx_visited", JSON.stringify([...visited])); }
function isVisited(iso) { return loadVisited().has(iso); }
function toggleVisited(iso) {
  loadVisited();
  if (visited.has(iso)) visited.delete(iso); else visited.add(iso);
  saveVisited();
}

function countryName(iso) {
  return (climate && climate[iso] && climate[iso].name) ||
         (ppp && ppp[iso] && ppp[iso].name) || iso;
}

function buildVisited() {
  loadVisited();
  const pick = $("visitedPick");
  // dropdown of all mappable countries by name
  const all = [...new Set(Object.keys(CUR_BY_ISO))]
    .map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  pick.innerHTML = '<option value="">+ add a country…</option>' +
    all.map((c) => `<option value="${esc(c.iso)}">${esc(c.name)}</option>`).join("");
  pick.onchange = () => { if (pick.value) { toggleVisited(pick.value); pick.value = ""; renderVisited(); } };
  $("visitedClear").onclick = () => { visited.clear(); saveVisited(); renderVisited(); };
  // One delegated listener each on the (stable) containers — survives innerHTML
  // re-renders and avoids re-binding 176 path handlers every toggle.
  $("visitedMap").addEventListener("click", (e) => {
    const p = e.target.closest("path");
    const iso = p && p.getAttribute("data-iso");
    if (iso && iso !== "-99") { toggleVisited(iso); renderVisited(); }
  });
  $("visitedChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".rm");
    if (chip) { toggleVisited(chip.dataset.iso); renderVisited(); }
  });
  renderVisited();
}

function renderVisited() {
  drawMap("visitedMap", (f) => {
    const v = visited.has(f.properties.iso);
    return { fill: v ? "#0a7d28" : "#e0e4e8",
      title: f.properties.name + (v ? " — visited ✓ (click to remove)" : " — click to mark visited") };
  }, "Countries visited");
  const list = [...visited].map((iso) => ({ iso, name: countryName(iso) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  $("visitedSub").textContent = `${visited.size} countries visited. Click the map or use the dropdown. Saved in this browser.`;
  $("visitedChips").innerHTML = list.length
    ? list.map((c) => `<span class="chip2 rm" data-iso="${esc(c.iso)}" title="remove">${esc(c.name)} ✕</span>`).join("")
    : '<span class="hint">None yet — click countries on the map.</span>';
}

// ===========================================================================
//  Tab switching (lazy-load each tab's data on first open)
// ===========================================================================
const loaded = {};
async function activateTab(name) {
  for (const b of document.querySelectorAll("#tabs button"))
    b.classList.toggle("active", b.dataset.tab === name);
  for (const s of document.querySelectorAll(".tab"))
    s.hidden = s.id !== "tab-" + name;

  // Refresh visited marks when returning to the recommendation tab.
  if (name === "value" && loaded.value) renderValue();

  try {
    if (name === "value" && !loaded.value) {
      await Promise.all([ensureWorld(), ensurePPP(), ensureClimate(), ensureAdvisories()]);
      buildValueTab(); loaded.value = true;
    } else if (name === "guide" && !loaded.guide) {
      await Promise.all([ensurePPP(), ensureClimate(), ensureActivities()]);
      buildBestPickers(); loaded.guide = true;
    } else if (name === "advisory" && !loaded.advisory) {
      $("advSub").textContent = "Loading advisories…";
      await Promise.all([ensureWorld(), ensureAdvisories()]); renderAdvisories(); loaded.advisory = true;
    } else if (name === "flights" && !loaded.flights) {
      await Promise.all([ensureWorld(), fillOriginSelect($("flightOrigin"))]);
      loadFlights(); loaded.flights = true;
    } else if (name === "visited" && !loaded.visited) {
      await Promise.all([ensureWorld(), ensurePPP(), ensureClimate()]);
      buildVisited(); loaded.visited = true;
    }
  } catch (e) {
    status("Could not load " + name + ": " + e.message, "err");
  }
}
for (const b of document.querySelectorAll("#tabs button"))
  b.addEventListener("click", () => activateTab(b.dataset.tab));

// Money tab sub-toggle: currency timing <-> cost of living.
for (const b of document.querySelectorAll("#moneyMode button")) {
  b.addEventListener("click", async () => {
    for (const x of document.querySelectorAll("#moneyMode button"))
      x.classList.toggle("active", x === b);
    const afford = b.dataset.mm === "afford";
    $("moneySubCurrency").hidden = afford;
    $("moneySubAfford").hidden = !afford;
    if (afford && !loaded.afford) {
      try {
        await Promise.all([ensureWorld(), ensurePPP()]);
        renderAfford(); loaded.afford = true;
      } catch (e) { status("Could not load cost of living: " + e.message, "err"); }
    }
  });
}

// ---- newsletter signup (Buttondown embed) ---------------------------------
// Set this to your public Buttondown newsletter username to enable signups.
const BUTTONDOWN_USER = "dougc97";

function renderSubscribe() {
  const el = $("subscribe");
  if (!el) return;
  if (!BUTTONDOWN_USER) {
    el.innerHTML = '<span class="hint">📬 Newsletter signup not configured yet — set BUTTONDOWN_USER in app.js once you have a Buttondown account.</span>';
    return;
  }
  const base = "https://buttondown.com/" + BUTTONDOWN_USER;
  el.innerHTML = `
    <span class="sublabel">📬 Get monthly “where the dollar goes furthest” alerts:</span>
    <form action="https://buttondown.com/api/emails/embed/subscribe/${BUTTONDOWN_USER}"
          method="post" target="popupwindow"
          onsubmit="window.open('${base}','popupwindow')" class="subform">
      <input type="email" name="email" placeholder="you@email.com" required>
      <button type="submit">Subscribe</button>
    </form>`;
}

(async function init() {
  initTheme();
  renderSubscribe();
  // Load the currency data (the "Where to go" score needs live rates + PPP),
  // render the currency tab in the background, then open the verdict tab.
  await Promise.all([ensurePPP().catch(() => {}), ensureWorld().catch(() => {}), loadRates()]);
  renderMapSafe();
  loadIndex(365);
  activateTab("value");
})();

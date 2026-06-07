"use strict";

const $ = (id) => document.getElementById(id);
let lastRates = null;

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

const DAY_LABEL = { 90: "3 months", 180: "6 months", 365: "1 year", 730: "2 years" };

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

  // Y gridlines + labels (~4 ticks).
  let grid = "";
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const v = lo + (t / ticks) * (hi - lo);
    const gy = y(v);
    grid += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="#eee" stroke-width="1"/>`;
    grid += `<text x="${padL - 6}" y="${gy + 3}" text-anchor="end" font-size="10" fill="#999">${v.toFixed(1)}</text>`;
  }

  // Baseline at 100.
  const by = y(100);
  const baseline =
    `<line x1="${padL}" y1="${by}" x2="${W - padR}" y2="${by}" stroke="#bbb" stroke-width="1" stroke-dasharray="4 3"/>` +
    `<text x="${W - padR}" y="${by - 4}" text-anchor="end" font-size="10" fill="#999">100 (start)</text>`;

  // X date labels (~5 evenly spaced).
  let xlab = "";
  const xticks = 5;
  for (let t = 0; t <= xticks; t++) {
    const i = Math.round((t / xticks) * (pts.length - 1));
    xlab += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="#999">${fmtMonth(pts[i].date)}</text>`;
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
    tr.innerHTML = `
      <td><span class="code">${r.code}</span>${star}<div class="name">${r.name}</div></td>
      <td class="num">${fmt(r.rate_now)}</td>
      <td class="num">${fmt(r.baseline_avg)}</td>
      <td class="num ${sign}">${r.strength_pct >= 0 ? "+" : ""}${r.strength_pct}%</td>
      <td class="num">${rangeMarker(r)}</td>
      <td><span class="pill ${r.label}">${r.label}</span></td>`;
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
    renderIndex(await getJSON("/api/index?days=" + days));
  } catch (e) {
    $("chartsub").textContent = "Could not load chart: " + e.message;
  }
}

for (const b of document.querySelectorAll("#windowtoggle button")) {
  b.addEventListener("click", () => loadIndex(parseInt(b.dataset.days, 10)));
}

// ---- world heatmap ---------------------------------------------------------
// Which tracked currency each country uses (ISO-3166 alpha-2 -> currency code).
const EUROZONE = ["AT","BE","CY","EE","FI","FR","DE","GR","IE","IT","LV","LT",
  "LU","MT","NL","PT","SK","SI","ES","AD","MC","SM","VA","ME","XK"];
const CUR_BY_ISO = (() => {
  const m = {
    AU:"AUD", BR:"BRL", CA:"CAD", CH:"CHF", LI:"CHF", CN:"CNY", CZ:"CZK",
    DK:"DKK", GL:"DKK", FO:"DKK", GB:"GBP", IM:"GBP", JE:"GBP", GG:"GBP",
    HK:"HKD", HU:"HUF", ID:"IDR", IL:"ILS", PS:"ILS", IN:"INR", IS:"ISK",
    JP:"JPY", KR:"KRW", MX:"MXN", MY:"MYR", NO:"NOK", SJ:"NOK", NZ:"NZD",
    PH:"PHP", PL:"PLN", RO:"RON", SE:"SEK", SG:"SGD", TH:"THB", TR:"TRY",
    ZA:"ZAR", US:"USD",
  };
  for (const iso of EUROZONE) m[iso] = "EUR";
  return m;
})();

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

function renderMap(rows) {
  const host = $("map");
  if (!worldGeo) { host.textContent = "Map data unavailable."; return; }

  const byCode = {};
  for (const r of rows) byCode[r.code] = r;
  let tracked = 0;

  const W = 1000, latTop = 83, latBot = -56;
  const H = Math.round((W * (latTop - latBot)) / 360);

  let paths = "";
  for (const f of worldGeo.features) {
    const iso = f.properties.iso;
    const cur = CUR_BY_ISO[iso];
    const row = cur && cur !== "USD" ? byCode[cur] : null;

    let fill, title;
    if (cur === "USD") {
      fill = HOME;
      title = f.properties.name + " — USD (home currency)";
    } else if (row) {
      fill = strengthColor(row.strength_pct);
      const sign = row.strength_pct >= 0 ? "+" : "";
      title = `${f.properties.name} — ${cur}: ${sign}${row.strength_pct}% vs 1yr avg`;
      tracked++;
    } else {
      fill = NODATA;
      title = f.properties.name + " — not tracked";
    }

    const g = f.geometry;
    const polys = g.type === "MultiPolygon" ? g.coordinates : [g.coordinates];
    let d = "";
    for (const poly of polys) {
      for (const ring of poly) {
        if (ring.length >= 3) d += projectRing(ring, W, H, latTop, latBot);
      }
    }
    if (d) paths += `<path d="${d}" fill="${fill}"><title>${title}</title></path>`;
  }

  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="USD strength world heatmap">${paths}</svg>`;
  $("mapsub").textContent =
    `Greener = dollar stronger vs that country's currency. Hover a country for detail · ${tracked} countries tracked.`;
  renderLegend();
}

function renderLegend() {
  $("legend").innerHTML =
    '<span>Weaker</span><span class="bar"></span><span>Stronger</span>' +
    '<span style="margin-left:8px"><span class="swatch"></span>No data</span>';
}

function renderMapSafe() {
  if (worldGeo && lastRates) renderMap(lastRates.rows);
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

(async function init() {
  await Promise.all([ensureWorld().catch(() => {}), loadRates()]);
  renderMapSafe();
  loadIndex(365);
})();

// ig_data.mjs — the data half of the Instagram story generators (ig_cheapest.mjs,
// ig_quiz.mjs): read-only GETs against the live site, parsers for its
// server-rendered pages and JSON, the stale-date refusal and the selection
// rules. Pure functions apart from liveGetter(), so test_ig_parsers.mjs runs
// them on the saved copies in fixtures/ig/ with an injected date.
//
// Every number a frame prints comes out of these parsers at render time;
// nothing here types one in. Nothing here posts anything anywhere.

export const SITE = process.env.SITE || 'https://wandergrade.com';
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December'];
export const MON3 = MONTHS.map((m) => m.slice(0, 3));
export const monthSlug = (m) => MONTHS[m - 1].toLowerCase();   // /cheapest/<slug>: fixed English names

// A refusal is the normal "not today" outcome (stale date, degraded page,
// blocked GET): the script prints why and renders nothing.
export class Refusal extends Error {}
const refuse = (msg) => { throw new Refusal(msg); };

// ---- dates (all UTC) -------------------------------------------------------------

// TODAY=YYYY-MM-DD injects the date (tests); otherwise today in UTC.
export function todayUTC(env = process.env) {
  if (env.TODAY) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(env.TODAY)) throw new Error('TODAY must be YYYY-MM-DD, got ' + env.TODAY);
    return env.TODAY;
  }
  return new Date().toISOString().slice(0, 10);
}
// "28 Oct 2026" -> "2026-10-28" (the site's RL._day format), null if it isn't one.
export function dayToIso(s) {
  const m = /^(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})$/.exec(String(s || '').trim());
  if (!m || MON3.indexOf(m[2]) < 0) return null;
  return `${m[3]}-${String(MON3.indexOf(m[2]) + 1).padStart(2, '0')}-${m[1].padStart(2, '0')}`;
}
// "2026-10-28" -> "28 Oct 2026"
export function isoToDay(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MON3[m - 1]} ${y}`;
}
// The stale-date refusal: the source's own "as of" must be today in UTC.
export function checkFresh(label, asOfIso, today) {
  if (!asOfIso) refuse(`${label}: no "as of" date found, so its figures can't be dated: refusing to render.`);
  if (asOfIso !== today) {
    refuse(`${label} is as of ${asOfIso}, not today (${today} UTC): refusing to render. The pages move when the `
      + `server next refreshes its rates and /guide-facts.json's _asof several hours after midnight UTC; `
      + `run again later in the day.`);
  }
}
// "2026-10-28" -> ISO week number (for rotating quiz sets without a state file).
export function isoWeek(iso) {
  const d = new Date(iso + 'T00:00:00Z');
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const y0 = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - y0) / 86400000 + 1) / 7);
}
export const nextMonth = (m, k = 1) => ((m - 1 + k) % 12) + 1;

// ---- GETs ----------------------------------------------------------------------

// liveGetter(): GET <SITE><path> with Node fetch. Anything but a 200 with the
// expected content type (a Cloudflare challenge is a 403/503 HTML page) stops
// the run: no retries, no spoofed User-Agent.
export function liveGetter(site = SITE) {
  return async (path, kind) => {
    const url = site + path;
    let r;
    try { r = await fetch(url); } catch (e) { refuse(`GET ${url} failed (${e.cause && e.cause.code || e.message}): stopping.`); }
    const body = await r.text();
    return { url, status: r.status, contentType: r.headers.get('content-type') || '',
             cacheControl: r.headers.get('cache-control') || '', body };
  };
}
// Checks a getter's reply and returns { body, json?, cacheControl }.
export async function getChecked(getter, path, kind) {
  const r = await getter(path, kind);
  const where = r.url || path;
  if (r.status !== 200) refuse(`GET ${where} returned ${r.status}, not 200 (a Cloudflare challenge or an outage?): stopping. Not retrying.`);
  if (kind === 'json') {
    if (!/application\/json/i.test(r.contentType)) refuse(`GET ${where} returned ${r.contentType || 'no content type'}, not JSON: stopping.`);
    let json;
    try { json = JSON.parse(r.body); } catch { refuse(`GET ${where} did not parse as JSON: stopping.`); }
    return { ...r, json };
  }
  if (!/text\/html/i.test(r.contentType) || !/<main class="shellmain">/.test(r.body)) {
    refuse(`GET ${where} is not the site's server-rendered page (${r.contentType || 'no content type'}): stopping.`);
  }
  return r;
}

// ---- HTML helpers (the pages are server-rendered and regular; no DOM in Node) -------

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
export const decode = (s) => String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => (e[0] === '#'
  ? String.fromCodePoint(e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : +e.slice(1))
  : (ENT[e] !== undefined ? ENT[e] : m)));
// textContent, whitespace collapsed.
export const text = (h) => decode(String(h).replace(/<[^>]*>/g, '')).replace(/\s+/g, ' ').trim();
// A signed figure as the pages print it: a true minus (U+2212), which
// parseFloat reads as NaN, and thousands commas.
export const num = (s) => parseFloat(String(s).replace(/−/g, '-').replace(/[,$%+]/g, ''));
const attr = (tag, name) => { const m = new RegExp(`\\s${name}="([^"]*)"`).exec(tag); return m ? decode(m[1]) : null; };
function rowsOf(tableHtml) {
  const tb = /<tbody>([\s\S]*?)<\/tbody>/.exec(tableHtml);
  return tb ? [...tb[1].matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map((m) => m[1]) : [];
}
// {data-l: inner html} for one row.
function cellsOf(tr) {
  const out = {};
  for (const m of tr.matchAll(/<td([^>]*)>([\s\S]*?)<\/td>/g)) out[attr(m[1], 'data-l')] = m[2];
  return out;
}
const headsOf = (tableHtml) => [...tableHtml.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map((m) => text(m[1]));
// The flag emoji in front of a name: whatever text precedes it, minus the rank.
const flagOf = (h) => text(h.replace(/<span class="rk">[\s\S]*?<\/span>/, ''));

// ---- /cheapest/<month> -------------------------------------------------------------

export const GRADES = ['A+', 'A', 'B+', 'B', 'C', 'D', 'F'];
// A full letter worse: the letter without its "+" gets worse (A->B+, A->B yes; A+->A, B+->B no).
export const LETTERS = 'ABCDF';
export const fullLetterDrop = (g1, g2) => LETTERS.indexOf(g2[0]) > LETTERS.indexOf(g1[0]);

// parseCheapest(html, cacheControl, month?) -> the page's lede, rule, rows and notes.
// Refuses a degraded page (no-store), an unavailable list and a missing table.
export function parseCheapest(html, cacheControl = '', month = null) {
  if (/no-store/i.test(cacheControl)) {
    refuse('/cheapest is degraded (Cache-Control: no-store: a feed is missing or fares are still loading): refusing to render.');
  }
  const h1 = text((/<h1>([\s\S]*?)<\/h1>/.exec(html) || [])[1] || '');
  const hm = /^Cheapest countries to visit in (\w+) (\d{4}), from the US$/.exec(h1);
  if (!hm) refuse(`/cheapest: unexpected heading "${h1}": refusing to render.`);
  if (month && hm[1] !== MONTHS[month - 1]) refuse(`/cheapest: page is for ${hm[1]}, not ${MONTHS[month - 1]}.`);
  const ledeHtml = (/<p class="lede">([\s\S]*?)<\/p>/.exec(html) || [])[1] || '';
  const lede = text(ledeHtml);
  if (/The list isn't available right now/.test(lede)) refuse(`/cheapest/${hm[1].toLowerCase()}: "${lede}": refusing to render.`);
  const table = (/<table class="listtable">([\s\S]*?)<\/table>/.exec(html) || [])[1];
  if (!table) refuse(`/cheapest/${hm[1].toLowerCase()} has no table: refusing to render.`);
  const lm = /^(The rule: (.+?)\.) (\d+) (countries qualify|country qualifies), ranked by (.+?), as of (\d{1,2} [A-Z][a-z]{2} \d{4})\.$/.exec(lede);
  if (!lm) refuse(`/cheapest: the lede no longer reads "The rule: … N countries qualify, … as of <date>.": "${lede}"`);
  const [, rule, ruleBody, nStr, , rankedBy, asOfDay] = lm;
  // One chip per clause, word for word; the regex rebuilds the sentence exactly.
  const cm = /^(.+?), (no .+?), (local .+?) and (a weather .+)$/.exec(ruleBody);
  if (!cm) refuse(`/cheapest: the rule sentence changed ("${ruleBody}"); update the chip split in ig_data.mjs.`);
  const heads = headsOf(table);
  for (const h of ['Country', 'Grade', 'Prices vs US', 'US State Dept', 'US round trip']) {
    if (!heads.includes(h)) refuse(`/cheapest: column "${h}" is missing (${heads.join(' | ')}).`);
  }
  const rows = rowsOf(table).map((tr, i) => {
    const c = cellsOf(tr);
    const name = c.Country || '';
    if (!/<a href="\/guide\//.test(name)) return null;   // the "No country meets the rule" row
    const am = /<a href="\/guide\/([^"]+)">([\s\S]*?)<\/a>/.exec(name);
    const gm = /<span class="(gr gr\w+)"[^>]*>([^<]+)<\/span>\s*(\d+)/.exec(c.Grade || '');
    const pt = text(c['Prices vs US'] || '');
    const wm = /<strong>(\d+)<\/strong> · ([−-]?\d+)°C \/ ([−-]?\d+)°F/.exec(c['Weather score'] || '');
    const sm = /<span class="lvl lvl(\d)"[^>]*>([^<]+)<\/span>/.exec(c['US State Dept'] || '');
    const ft = text(c['US round trip'] || '');
    let fare = null;
    if (ft !== '—*') {
      const fm = /^\$([\d,]+) (Low|Typical|High)$/.exec(ft);
      if (!fm) refuse(`/cheapest: fare cell "${ft}" is neither "$N Band" nor "—*".`);
      fare = { price: num(fm[1]), text: '$' + fm[1], band: fm[2] };
    }
    if (!gm || !sm || !/^\d+%†?$/.test(pt)) refuse(`/cheapest: row ${i + 1} (${text(name)}) didn't parse.`);
    const pill = decode(sm[2]);
    const lv = /^Level (\d)\b/.exec(pill);
    return {
      rank: i + 1, slug: am[1], name: text(am[2]), flag: flagOf(name.slice(0, am.index)),
      gradeCls: gm[1], grade: gm[2].trim(), score: +gm[3],
      pct: num(pt), dagger: pt.endsWith('†'),
      wx: wm ? +wm[1] : num(text(c['Weather score'] || '')),
      tempC: wm ? num(wm[2]) : null, tempF: wm ? num(wm[3]) : null,
      level: lv ? +lv[1] : null, levelPill: pill,
      fare,
    };
  }).filter(Boolean);
  const n = +nStr;
  if (rows.length !== n) refuse(`/cheapest: the lede says ${n} qualify but the table has ${rows.length} rows.`);
  const notes = [...html.matchAll(/<p class="note">([\s\S]*?)<\/p>/g)].map((m) => text(m[1]));
  return {
    month: MONTHS.indexOf(hm[1]) + 1, monthName: hm[1], year: +hm[2], h1, lede, rule, ruleBody,
    chips: cm.slice(1, 5), n, rankedBy, asOfDay, asOf: dayToIso(asOfDay), heads, rows,
    altNote: notes.find((t) => t.startsWith('†')) || null,
    fareNote: notes.find((t) => t.startsWith('*')) || null,
  };
}

// The flip pick: among m+1's top 10, the biggest score drop of a full letter
// or more into m+2; ties go to the higher m+1 rank. Only countries listed on
// both pages count (missing from m+2 means it didn't meet that month's rule:
// no m+2 grade, never inferred).
export function pickFlip(p1, p2, top = 10) {
  const by2 = new Map(p2.rows.map((r) => [r.slug, r]));
  const c = p1.rows.slice(0, top).map((r) => ({ a: r, b: by2.get(r.slug) }))
    .filter((x) => x.b && fullLetterDrop(x.a.grade, x.b.grade))
    .map((x) => ({ ...x, drop: x.a.score - x.b.score }));
  c.sort((x, y) => (y.drop - x.drop) || (x.a.rank - y.a.rank));
  return c[0] || null;
}

// /api/flight-value: the [price, city] of a country's month, keyed by the
// month's next occurrence ("YYYY-MM" from `months`). null when pending or missing.
export function fareCity(fv, iso, month) {
  const key = (fv.months || []).find((k) => +k.slice(5) === month);
  const c = fv.countries && fv.countries[iso];
  if (!key || !c || c.pending || !c.curve || !c.curve[key]) return null;
  return { key, price: c.curve[key][0], city: c.curve[key][1] };
}

// ---- /dollar-strength ---------------------------------------------------------------

export function parseDollar(html) {
  const table = (/<table class="listtable dstable">([\s\S]*?)<\/table>/.exec(html) || [])[1];
  if (!table) refuse('/dollar-strength has no table.dstable: refusing to render.');
  const heads = headsOf(table);
  for (const h of ['Currency', 'Used in', 'Before inflation', 'After inflation', 'Prices vs US']) {
    if (!heads.includes(h)) refuse(`/dollar-strength: column "${h}" is missing (${heads.join(' | ')}).`);
  }
  // The exchange-rate date, from the closing sources line (the lede's "as of"
  // is the ECB dollar index, a business day or more behind).
  const asm = /<p class="asof">Exchange rates: [^,<]+, as of (\d{1,2} [A-Z][a-z]{2} \d{4})/.exec(html);
  const rows = rowsOf(table).map((tr, i) => {
    const c = cellsOf(tr);
    const cur = c.Currency || '';
    const code = text((/<span class="dscode">([\s\S]*?)<\/span>/.exec(cur) || [])[1] || '');
    const ci = cur.indexOf('<span class="dscode">');
    const after = cur.slice(cur.indexOf('</span>', ci) + 7).replace(/<span class="dspegs"[\s\S]*?<\/span>/, '');
    const used = c['Used in'] || '';
    // The first place listed is the currency's main country (Germany for the euro).
    const fm = /^<span class="v"><a href="\/guide\/([^"]+)">([\s\S]*?)<\/a>/.exec(used.trim());
    const ai = c['After inflation'] || '';
    const sp = /<span class="(\w+)" title="([^"]*)">([^<]+)<\/span>/.exec(ai);
    const r = {
      rank: i + 1, code, flag: flagOf(cur.slice(0, ci)), currency: text(after),
      slug: fm ? fm[1] : null, place: fm ? text(fm[2]) : text(used).split(/,| and /)[0].trim(),
      beforeText: text(c['Before inflation'] || ''), before: num(text(c['Before inflation'] || '')),
      afterText: sp ? text(sp[3]) : text(ai), after: sp ? num(sp[3]) : NaN,
      afterTitle: sp ? decode(sp[2]) : '', afterDagger: /†/.test(ai),
      prices: text(c['Prices vs US'] || ''),
    };
    if (!code || Number.isNaN(r.before)) refuse(`/dollar-strength: row ${i + 1} didn't parse.`);
    return r;
  });
  const none = [...((/<ul class="dsnone">([\s\S]*?)<\/ul>/.exec(html) || [])[1] || '')
    .matchAll(/<span class="dscode">([A-Z]{3})<\/span>/g)].map((m) => m[1]);
  return { asOfDay: asm ? asm[1] : null, asOf: asm ? dayToIso(asm[1]) : null, heads, rows, noInflation: none };
}

// The inflation pair from the After-inflation figure's title:
// "After inflation: Turkey ~35%/yr vs the US ~3%/yr (World Bank)." -> "Turkey ~35%/yr vs the US ~3%/yr (World Bank)"
export const inflationPair = (title) => {
  const m = /^After inflation: (.+?)\.?$/.exec(title || '');
  return m ? m[1] : null;
};

// Sign-flip candidates, hand-kept: well-known destinations.
export const FLIP_ALLOW = ['TRY', 'EGP', 'ARS', 'GHS', 'ZAR', 'INR', 'MXN', 'BRL', 'COP', 'VND', 'IDR', 'THB', 'PHP'];
// Bolivia's jump comes from an official-rate change a frame can't explain:
// never on a frame (and never moved down, which would show the list out of order).
export const NEVER_ISO = ['BO'];
// The flip must read clearly, so "About the same" isn't arguably right:
// at least this far up before inflation and this far down after.
export const FLIP_MIN = 1.0;

// A US State Dept level 1-2 from /guide-facts.json: src "us" only (a "ca"/"de"
// gap-fill isn't the State Department's), and a missing entry is out, not "below 3".
export function usLevel(facts, iso) {
  const f = iso && facts[iso];
  if (!f || f.src !== 'us' || !(f.adv === 1 || f.adv === 2)) return null;
  return f.adv;
}

// Step 3 of KIND=dollar: rows that may appear on a frame at all.
export function dollarEligible(ds, facts, slugs) {
  return ds.rows.map((r) => ({ ...r, iso: r.slug ? slugs[r.slug] || null : null }))
    .filter((r) => r.iso && !NEVER_ISO.includes(r.iso) && usLevel(facts, r.iso)
      && !r.afterDagger && !ds.noInflation.includes(r.code) && !Number.isNaN(r.after))
    .map((r) => ({ ...r, level: usLevel(facts, r.iso) }));
}
// The sign flip: up before inflation, down after, from the allowlist; the
// biggest gap between the two wins (ties: allowlist order).
export function pickSignFlip(eligible) {
  const c = eligible.filter((r) => FLIP_ALLOW.includes(r.code) && r.before >= FLIP_MIN && r.after <= -FLIP_MIN);
  c.sort((a, b) => ((b.before - b.after) - (a.before - a.after)) || (FLIP_ALLOW.indexOf(a.code) - FLIP_ALLOW.indexOf(b.code)));
  return c[0] || null;
}
// F3: where it did go further after inflation, in the page's order.
export const wentFurther = (eligible, k = 4) => eligible.filter((r) => r.after > 0).slice(0, k);

// ---- /guide-facts.json and /slugs.json -------------------------------------------------

// The site's own name for a country: the start of its guide description
// ("Japan: local prices ≈ 62% of the US …").
export function factName(facts, iso) {
  const d = (facts[iso] || {}).d || '';
  const m = /^([^:]+): local prices/.exec(d);
  return m ? m[1] : null;
}
export const isoToSlug = (slugs, iso) => Object.keys(slugs).find((s) => slugs[s] === iso) || null;

// How many countries have a price figure, England/Scotland/Wales (plof "GB",
// the UK's own figure repeated) counted once.
export const priceCount = (facts) => Object.entries(facts)
  .filter(([k, v]) => k !== '_asof' && v && v.pct != null && !v.plof).length;

// KIND=price sets, rotated by ISO week. Each is checked at render time; a set
// that fails falls through to the next in rotation order.
export const PRICE_SETS = [
  ['JP', 'ES', 'IT', 'FR'],
  ['MX', 'CR', 'PT', 'KR'],
  ['VN', 'MY', 'MA', 'TR'],
  ['GB', 'DE', 'AT', 'NL'],
  ['AR', 'CL', 'BR', 'PE'],
  ['SG', 'CA', 'NZ', 'AU'],
  ['PL', 'HR', 'GR', 'CH'],
  ['EG', 'IN', 'TH', 'ZA'],
];
// SLIDER=1: one country a fortnight, same rules.
export const SLIDER_LIST = ['JP', 'PT', 'MX', 'GR', 'TH', 'KR', 'AR', 'ZA', 'MA', 'VN', 'ES', 'PE', 'CZ', 'IE'];
export const PRICE_GAP = 2;

// Why a set can't run today, or null when it can.
export function priceSetProblem(facts, set) {
  for (const iso of set) {
    if (!facts[iso] || facts[iso].pct == null) return `${iso} has no price figure`;
    if (!usLevel(facts, iso)) return `${iso} isn't US State Dept Level 1-2 (adv ${facts[iso].adv}, src ${facts[iso].src})`;
  }
  const p = set.map((i) => facts[i].pct).sort((a, b) => a - b);
  for (let i = 1; i < p.length; i++) if (p[i] - p[i - 1] < PRICE_GAP) return `prices ${p.join(', ')} are under ${PRICE_GAP} points apart`;
  return null;
}
// The week's set: start at isoWeek % n, take the first that passes.
export function pickPriceSet(facts, postIso, sets = PRICE_SETS) {
  const start = isoWeek(postIso) % sets.length, tried = [];
  for (let k = 0; k < sets.length; k++) {
    const set = sets[(start + k) % sets.length], why = priceSetProblem(facts, set);
    if (!why) return { set, tried };
    tried.push(`${set.join('/')}: ${why}`);
  }
  return { set: null, tried };
}
export function pickSlider(facts, postIso, list = SLIDER_LIST) {
  const start = isoWeek(postIso) % list.length, tried = [];
  for (let k = 0; k < list.length; k++) {
    const iso = list[(start + k) % list.length];
    const f = facts[iso];
    if (f && f.pct != null && usLevel(facts, iso) && factName(facts, iso)) return { iso, tried };
    tried.push(`${iso}: no price figure or not US State Dept Level 1-2`);
  }
  return { iso: null, tried };
}
// "Cheaper than X of the N": countries with a strictly higher figure (plof counted once).
export const pricierThan = (facts, pct) => Object.entries(facts)
  .filter(([k, v]) => k !== '_asof' && v && v.pct != null && !v.plof && v.pct > pct).length;

// ---- shared wording guards --------------------------------------------------------------

// The display name for a country (frames and sidecars). Quoted page text keeps the page's words.
const DISPLAY = { Turkey: 'Turkey (Türkiye)' };
export const displayName = (name) => DISPLAY[name] || name;
// ISO -> flag emoji (regional indicators).
export const flagEmoji = (iso) => String.fromCodePoint(...[...iso.slice(0, 2).toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)));

// The site never writes its own safety claims, and there's no Airbnb anywhere:
// any of these words on a frame or in a sidecar stops the run.
export function wordingProblems(s) {
  const out = [];
  if (/\bsafe(st|r)?\b/i.test(s)) out.push('the word "safe"/"safest"');
  if (/airbnb/i.test(s)) out.push('Airbnb');
  if (/last chance|deadline|hurry|before it'?s gone/i.test(s)) out.push('deadline wording');
  return out;
}

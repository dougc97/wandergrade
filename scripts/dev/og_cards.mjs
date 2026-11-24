// og_cards.mjs — the per-country share cards: public/og/<slug>.jpg, 1200x630 JPEG,
// one per guide, plus public/og/cards.json (the facts each card shows).
//
//   cd scripts/dev && CDP_TIMEOUT=55 node cdp.mjs ./og_cards.mjs
//   ONLY=thailand,japan   just these slugs        START=0 COUNT=80   a slice of the sorted slugs
//   CHECK=1               render nothing: list the slugs whose card is missing or stale, exit
//
// A guide's og:image / twitter:image is /og/<slug>.jpg while its card exists and
// cards.json's facts for it match the data (server.py _og_image), else /og.png. So a
// card can't go stale silently: scripts/test_og_cards.py fails, and the page falls back,
// until this is re-run for the slugs it names.
//
// Only facts that rarely change go on a card, so the files don't churn in git: the flag,
// the country's name (country-names.json), its best months (climate.json "best", worded
// "Best time to go" where curated, "Best weather" otherwise, as render_guide words them),
// and the wordmark. No grade, price, fare or advisory level: those move daily. Rendered
// offline in headless Chrome (the server can't run Pillow) from an inline page: the brand
// font as data: URLs from public/fonts, the flag from the system's emoji font. A card is
// written only when its bytes change. Limits held by test_og_cards.py: at most 70 KB a card,
// 12 MB in all; QUALITY steps down for a card over MAX_BYTES.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PUB = ROOT + '/public';
const OUT = PUB + '/og';
const MAX_BYTES = 70 * 1024;
const QUALITIES = [82, 74, 66, 58];
const W = 1200, H = 630;
const MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const readJSON = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));

// The facts a card shows, from the data: what cards.json records and the server compares.
export function facts(slug, iso, names, clim) {
  const c = clim[iso] || {};
  return { iso, name: names[iso] || slug, best: (c.best || []).filter((m) => m >= 1 && m <= 12), curated: !!c.curated };
}
// Months in season order (build_climate.season_order): a run across New Year starts after its gap.
function seasonOrder(ms) {
  const b = [...new Set(ms)].sort((x, y) => x - y), n = b.length;
  if (n < 2 || b[0] + 12 - b[n - 1] > 2) return b;
  let gi = 0, gap = -1;
  for (let i = 0; i < n; i++) { const g = (b[(i + 1) % n] - b[i] + 12) % 12; if (g > gap || (g === gap && i > gi)) { gap = g; gi = i; } }
  const s = (gi + 1) % n;
  return b.slice(s).concat(b.slice(0, s));
}
// "November – February", "March – April · October – November": runs of consecutive months.
export function monthsText(best) {
  const ms = seasonOrder(best), runs = [];
  for (const m of ms) {
    const r = runs[runs.length - 1];
    if (r && (r[r.length - 1] % 12) + 1 === m) r.push(m); else runs.push([m]);
  }
  return runs.map((r) => r.length === 1 ? MON[r[0] - 1] : MON[r[0] - 1] + ' – ' + MON[r[r.length - 1] - 1]).join(' · ');
}
// Regional-indicator flag; England, Scotland and Wales by their tag sequences.
export function flag(iso) {
  const sub = { 'GB-ENG': 'gbeng', 'GB-SCT': 'gbsct', 'GB-WLS': 'gbwls' }[iso];
  if (sub) return '\u{1F3F4}' + [...sub].map((ch) => String.fromCodePoint(0xE0000 + ch.charCodeAt(0))).join('') + '\u{E007F}';
  if (!/^[A-Z]{2}$/.test(iso)) return '';
  return String.fromCodePoint(...[...iso].map((ch) => 0x1F1E6 + ch.charCodeAt(0) - 65));
}

function pageHTML() {
  const face = (file, range) => `@font-face{font-family:J;font-style:normal;font-weight:200 800;font-display:block;`
    + `src:url(data:font/woff2;base64,${fs.readFileSync(PUB + '/fonts/' + file).toString('base64')}) format('woff2');unicode-range:${range};}`;
  // latin and latin-ext: every guide name is in them (Côte d'Ivoire, São Tomé, Curaçao).
  const css = face('LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yygg_vb.woff2', 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD')
    + face('LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko40yygg_vbd-E.woff2', 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF');
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:${W}px;height:${H}px;overflow:hidden;background:#0a1018}
#c{position:relative;width:${W}px;height:${H}px;padding:54px 72px;font-family:J,system-ui,sans-serif;color:#fff;
  background:radial-gradient(1100px 620px at 0% 0%,#132034 0%,rgba(19,32,52,0) 70%),linear-gradient(135deg,#0d1520 0%,#0a1018 55%,#060a10 100%)}
#brand{font-weight:800;font-size:38px;color:#34d27b;letter-spacing:-.01em;display:flex;align-items:center;gap:12px}
#brand .g{font-family:"Apple Color Emoji","Noto Color Emoji",sans-serif;font-size:36px}
#flag{font-family:"Apple Color Emoji","Noto Color Emoji",sans-serif;font-size:96px;line-height:1;margin:30px 0 14px}
#name{font-weight:800;font-size:92px;line-height:1;letter-spacing:-.02em;max-width:1056px}
#best{margin-top:20px;font-size:34px;font-weight:600;color:#9fb0bd}
#best b{color:#fff;font-weight:800}
#foot{position:absolute;left:72px;bottom:48px;font-size:28px;color:#9fb0bd;font-weight:600}
#foot b{color:#34d27b;font-weight:800}
</style></head><body><div id="c"><div id="brand"><span class="g">🌍</span>WanderGrade</div>
<div id="flag"></div><div id="name"></div><div id="best"></div>
<div id="foot"><b>wandergrade.com</b> · every country graded A+ to F</div></div></body></html>`;
}

export default async ({ send, evaluate, setSize, nav, sleep, errs }) => {
  const slugs = readJSON(PUB + '/slugs.json'), names = readJSON(PUB + '/country-names.json'), clim = readJSON(PUB + '/climate.json');
  const manifestPath = OUT + '/cards.json';
  const manifest = fs.existsSync(manifestPath) ? readJSON(manifestPath) : {};
  let list = Object.keys(slugs).sort();
  if (process.env.ONLY) { const want = new Set(process.env.ONLY.split(',')); list = list.filter((s) => want.has(s)); }
  const start = +process.env.START || 0, count = process.env.COUNT ? +process.env.COUNT : list.length;
  list = list.slice(start, start + count);
  const stale = (s) => { const f = facts(s, slugs[s], names, clim); return !fs.existsSync(`${OUT}/${s}.jpg`) || JSON.stringify(manifest[s]) !== JSON.stringify(f); };
  if (process.env.CHECK) {
    const bad = Object.keys(slugs).sort().filter(stale);
    console.log(bad.length ? 'missing or stale: ' + bad.join(',') : 'every card is current');
    return;
  }
  fs.mkdirSync(OUT, { recursive: true });
  const tmp = path.join(fs.mkdtempSync(path.join(process.env.TMPDIR || '/tmp', 'ogc-')), 'card.html');
  fs.writeFileSync(tmp, pageHTML());
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await nav('file://' + tmp, 300);
  await evaluate(`(async () => { await document.fonts.load('800 92px J'); await document.fonts.load('600 34px J'); await document.fonts.ready; return 1; })()`);
  let wrote = 0, same = 0, total = 0;
  for (const s of list) {
    const f = facts(s, slugs[s], names, clim);
    const lead = f.curated ? 'Best time to go' : 'Best weather';
    const months = f.best.length ? monthsText(f.best) : '';
    const fit = await evaluate(`(async () => {
      const el = (id) => document.getElementById(id);
      el('flag').textContent = ${JSON.stringify(flag(f.iso))};
      el('name').textContent = ${JSON.stringify(f.name)};
      el('best').innerHTML = ${JSON.stringify(months ? `${lead}: <b>${months}</b>` : '')};
      // The name at 92px, smaller until it fits two lines inside the card.
      let px = 92; el('name').style.fontSize = px + 'px';
      while (px > 52 && el('name').getBoundingClientRect().height > 2.2 * px) { px -= 4; el('name').style.fontSize = px + 'px'; }
      el('best').style.fontSize = '${months.length > 40 ? 30 : 34}px';
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const b = el('best').getBoundingClientRect(), ft = el('foot').getBoundingClientRect();
      return { px, overlap: b.bottom > ft.top - 12 };
    })()`);
    if (fit && fit.overlap) console.log('WARN ' + s + ': the months line reaches the footer');
    let buf;
    for (const q of QUALITIES) {
      const r = await send('Page.captureScreenshot', { format: 'jpeg', quality: q, clip: { x: 0, y: 0, width: W, height: H, scale: 1 } });
      buf = Buffer.from(r.result.data, 'base64');
      if (buf.length <= MAX_BYTES) break;
    }
    const file = `${OUT}/${s}.jpg`;
    if (fs.existsSync(file) && fs.readFileSync(file).equals(buf)) same++;
    else { fs.writeFileSync(file, buf); wrote++; }
    manifest[s] = f;
    total += buf.length;
  }
  const sorted = {};
  for (const k of Object.keys(manifest).sort()) if (slugs[k]) sorted[k] = manifest[k];
  fs.writeFileSync(manifestPath, JSON.stringify(sorted, null, 1) + '\n');
  fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
  console.log(`cards: ${list.length} rendered (${wrote} written, ${same} unchanged), ${(total / 1024).toFixed(0)} KB this run`);
};

// ig_frame.mjs — the shared 1080x1920 Instagram-story frame for ig_story.mjs,
// ig_cheapest.mjs and ig_quiz.mjs, so every series looks the same: a dark
// gradient, Plus Jakarta Sans 800, big rounded cards and the site's own .gr
// grade pills, drawn INSIDE a server-rendered page of the live site so its
// CSS variables, pills and self-hosted font apply.
//
// Safe areas: Instagram's own UI covers roughly the top 250px (progress bars,
// name) and the bottom 280px (reply bar): no text of ours goes there. Sticker
// spots (poll, quiz, slider, link) are empty .igband boxes inside the safe
// area; checkLayout() fails a frame whose text enters one, leaves the safe
// area or is clipped. Nothing is posted anywhere: the output is PNG files.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { wordingProblems } from './ig_data.mjs';

export const W = 1080, H = 1920, SAFE_TOP = 250, SAFE_BOTTOM = 280, SIDE = 72;

export const FRAME_CSS = `
  #igstory { position: fixed; inset: 0; width: ${W}px; height: ${H}px; z-index: 99999; box-sizing: border-box;
    padding: ${SAFE_TOP}px ${SIDE}px ${SAFE_BOTTOM}px; color: var(--ink, #e7eaed);
    background: linear-gradient(170deg, #1a242c 0%, var(--bg, #101316) 55%, #0b0e10 100%);
    font-family: "Plus Jakarta Sans", system-ui, sans-serif; display: flex; flex-direction: column; line-height: 1.3; }
  #igstory * { box-sizing: border-box; }
  #igstory .igbrand { font-weight: 800; font-size: 40px; color: #2bb24c; letter-spacing: -.01em; }
  #igstory .igkick { font-weight: 800; font-size: 30px; letter-spacing: .02em; text-transform: uppercase; opacity: .6; margin-top: 18px; }
  #igstory .igh1 { font-weight: 800; font-size: 82px; line-height: 1.02; letter-spacing: -.025em; margin: 22px 0 14px; }
  #igstory .igh1.m { font-size: 66px; line-height: 1.06; }
  #igstory .igh1.s { font-size: 56px; line-height: 1.08; }
  #igstory .igsub { font-size: 29px; line-height: 1.35; opacity: .72; margin-bottom: 36px; max-width: 900px; }
  #igstory .igc { display: flex; align-items: center; gap: 26px; background: var(--card); border: 1px solid var(--line, rgba(255,255,255,.08));
    border-radius: 26px; padding: 24px 30px; margin-bottom: 16px; }
  #igstory .igc.col { flex-direction: column; align-items: stretch; gap: 14px; }
  #igstory .igc.win { border: 3px solid #2bb24c; }
  #igstory .igrow { display: flex; align-items: center; gap: 26px; }
  #igstory .igrank { font-weight: 800; font-size: 34px; opacity: .45; width: 64px; }
  #igstory .igflag { font-size: 64px; line-height: 1; }
  #igstory .igmain { flex: 1; min-width: 0; }
  #igstory .igname { font-weight: 800; font-size: 46px; line-height: 1.1; letter-spacing: -.02em; }
  #igstory .igwhy { font-size: 25px; line-height: 1.3; opacity: .72; margin-top: 8px; }
  /* ig_story's one-line names and two-line why-lines: truncated on purpose (renderFrame's allowClip) */
  #igstory .igname.clip { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #igstory .igwhy.clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  #igstory .green { color: #2bb24c; }
  #igstory .igfacts { font-size: 27px; line-height: 1.4; }
  #igstory .igfacts div { opacity: .85; }
  #igstory .igfacts b { font-weight: 800; opacity: 1; }
  #igstory .igpill { display: flex; align-items: center; gap: 14px; }
  #igstory .igpill .gr { font-size: 40px; min-width: 100px; height: 80px; line-height: 80px; border-radius: 20px; padding: 0 16px; font-weight: 800; }
  #igstory .igpill.big .gr { font-size: 72px; min-width: 170px; height: 140px; line-height: 140px; border-radius: 32px; }
  #igstory .igscore { font-weight: 800; font-size: 34px; opacity: .6; min-width: 56px; text-align: right; }
  #igstory .igpill.big .igscore { font-size: 56px; }
  #igstory .igchips { display: flex; flex-wrap: wrap; gap: 14px; }
  #igstory .igchip { background: var(--card); border: 1px solid var(--line, rgba(255,255,255,.08)); border-radius: 999px;
    padding: 14px 28px; font-size: 30px; font-weight: 700; line-height: 1.25; }
  #igstory .igbig { font-weight: 800; font-size: 200px; line-height: 1; letter-spacing: -.04em; margin: 10px 0 18px; }
  #igstory .igbig.pos { color: #3fb95f; } #igstory .igbig.neg { color: #ff9f6b; }
  #igstory .igquote { font-size: 27px; line-height: 1.4; opacity: .8; }
  #igstory .iggrid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  #igstory .iggrid .igc { flex-direction: column; justify-content: center; gap: 10px; margin: 0; padding: 30px 20px; text-align: center; }
  #igstory .iggrid .igflag { font-size: 110px; }
  #igstory .iggrid .igname { font-size: 40px; }
  #igstory .igval { font-weight: 800; font-size: 54px; }
  #igstory .igband { flex-shrink: 0; }   /* a sticker's spot: kept clear on purpose */
  #igstory .igspace { margin-top: auto; }
  #igstory .igfoot { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; font-size: 26px; opacity: .72; }
  #igstory .igfoot b { font-weight: 800; opacity: 1; color: #2bb24c; font-size: 34px; }
  #igstory .igfoot small { font-size: 24px; }
  #igstory .igfoot > div:first-child { white-space: nowrap; flex-shrink: 0; }
  #igstory .igfoot .r { text-align: right; }
`;

export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// A clear sticker band. kind: poll | quiz | slider | link; h in px.
export const band = (kind, h) => `<div class="igband" data-band="${kind}" style="height:${h}px"></div>`;
export const brand = () => '<div class="igbrand">🌍 WanderGrade</div>';
// The footer every frame carries: the site on the left, "As of <date>" (and any caveat) on the right.
export const foot = (asOfLine, left = 'Tap the link · free, no sign-up') =>
  `<div class="igfoot"><div><b>wandergrade.com</b><br><small>${esc(left)}</small></div><div class="r"><small>${esc(asOfLine)}</small></div></div>`;
export const pill = (cls, grade, score, big = false) =>
  `<div class="igpill${big ? ' big' : ''}"><span class="${esc(cls)}">${esc(grade)}</span>${score != null ? `<span class="igscore">${esc(score)}</span>` : ''}</div>`;

// ---- the browser side -------------------------------------------------------------

// Before any page load of wandergrade.com: block the Cloudflare analytics
// beacon, so test loads don't count as real visitors. send() never throws.
export async function blockBeacon(send) {
  await send('Network.enable');
  const b = await send('Network.setBlockedURLs', { urls: ['*cloudflareinsights.com*'] });
  if (b.error) throw new Error('beacon block failed: ' + JSON.stringify(b.error));
}

const FONT = '800 80px "Plus Jakarta Sans"';
// Navigates to a server-rendered page to draw on, beacon blocked, and waits
// for Plus Jakarta Sans 800. The font is font-display: optional, so a load
// that misses its window stays on the fallback for that page's life: reload.
export async function openCanvas(t, url) {
  const { send, on, evaluate, nav } = t;
  await blockBeacon(send);
  const blocked = [];
  const off = on((d) => { if (d.method === 'Network.loadingFailed' && d.params.blockedReason) blocked.push(d.params.blockedReason); });
  for (let attempt = 1; attempt <= 3; attempt++) {
    await nav(url, 800);
    const f = await evaluate(`(async () => {
      await Promise.race([document.fonts.load(${JSON.stringify(FONT)}), new Promise((r) => setTimeout(r, 8000))]);
      // check() says the face is loaded; the width test says this page actually draws with it.
      const m = (fam) => { const s = document.createElement('span'); s.style.cssText = 'position:absolute;visibility:hidden;font:800 80px ' + fam; s.textContent = 'WanderGrade 0123'; document.body.appendChild(s); const w = s.getBoundingClientRect().width; s.remove(); return w; };
      return { check: document.fonts.check(${JSON.stringify(FONT)}), used: Math.abs(m('"Plus Jakarta Sans", monospace') - m('monospace')) > 1, title: document.title };
    })()`);
    if (f && f.check && f.used) { off(); console.log('canvas', url, '— font ready', blocked.length ? `(beacon blocked: ${blocked.join(',')})` : ''); return; }
    console.log(`font missed its window on attempt ${attempt} (${JSON.stringify(f)}): reloading`);
  }
  off();
  throw new Error('Plus Jakarta Sans 800 never loaded on ' + url);
}

// Is a flag drawn as a colour emoji (not two letters)? Draws it on a canvas
// and looks for coloured pixels: letters in black have none.
export async function flagCheck(evaluate, flag) {
  return evaluate(`(() => {
    const c = document.createElement('canvas'); c.width = 120; c.height = 120; const x = c.getContext('2d');
    x.fillStyle = '#000'; x.font = '96px "Plus Jakarta Sans", system-ui, sans-serif'; x.textBaseline = 'top';
    x.fillText(${JSON.stringify(flag)}, 4, 4);
    const d = x.getImageData(0, 0, 120, 120).data; let col = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]) > 40) col++;
    return { flag: ${JSON.stringify(flag)}, colouredPixels: col, emoji: col > 200 };
  })()`);
}

// Text inside the safe area and the side margins, never in a sticker band,
// never outside its card, never clipped; the panel itself never taller than 1920.
const CHECK = (allowClip) => `(() => {
  const s = document.getElementById('igstory'), P = [];
  const TOP = ${SAFE_TOP}, BOT = ${H - SAFE_BOTTOM}, L = ${SIDE - 24}, R = ${W - SIDE + 24};
  const bands = [...s.querySelectorAll('.igband')].map((b) => ({ k: b.dataset.band, r: b.getBoundingClientRect() }));
  const hit = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  const w = document.createTreeWalker(s, NodeFilter.SHOW_TEXT); let n, texts = 0;
  while ((n = w.nextNode())) {
    if (!n.textContent.trim() || n.parentElement.closest('style')) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    const card = n.parentElement.closest('.igc, .igchip');
    const cr = card && card.getBoundingClientRect();
    for (const r of rg.getClientRects()) {
      if (!r.width) continue; texts++;
      const t = n.textContent.trim().slice(0, 40);
      if (r.top < TOP - 0.5 || r.bottom > BOT + 0.5) P.push('outside the safe area (y ' + Math.round(r.top) + '-' + Math.round(r.bottom) + '): ' + t);
      if (r.left < L || r.right > R) P.push('outside the side margins (x ' + Math.round(r.left) + '-' + Math.round(r.right) + '): ' + t);
      for (const b of bands) if (hit(r, b.r)) P.push('in the ' + b.k + ' sticker band: ' + t);
      if (cr && (r.left < cr.left - 0.5 || r.right > cr.right + 0.5 || r.top < cr.top - 0.5 || r.bottom > cr.bottom + 0.5)) P.push('spills out of its card: ' + t);
    }
  }
  for (const el of s.querySelectorAll('*')) {
    if (el.tagName === 'STYLE' || ${JSON.stringify(allowClip || '')} && el.matches(${JSON.stringify(allowClip || '*:not(*)')})) continue;
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'visible') P.push('clipped horizontally: ' + el.className);
    if (el.scrollHeight > el.clientHeight + 1 && getComputedStyle(el).overflowY !== 'visible') P.push('clipped vertically: ' + el.className);
  }
  for (const b of bands) if (b.r.top < TOP - 0.5 || b.r.bottom > BOT + 0.5) P.push(b.k + ' band leaves the safe area');
  if (s.scrollHeight > ${H} + 1) P.push('panel overflows: ' + s.scrollHeight + 'px');
  const f = s.querySelector('.igfoot');
  return { problems: P, texts, bands: bands.map((b) => b.k + ' ' + Math.round(b.r.top) + '-' + Math.round(b.r.bottom)),
           footBottom: f ? Math.round(f.getBoundingClientRect().bottom) : null, text: s.innerText };
})()`;

// Draws one frame over the canvas page and writes a 1080x1920 PNG. A frame
// that breaks the layout rules or the wording rules is not written. `css`:
// a series' own additions after FRAME_CSS.
export async function renderFrame(t, { html, out, allowClip = null, css = '' }) {
  const { send, evaluate, setSize, sleep } = t;
  await setSize(W, H, false);
  await evaluate(`(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const old = document.getElementById('igstory'); if (old) old.remove();
    const d = document.createElement('div'); d.id = 'igstory';
    d.innerHTML = '<style>' + ${JSON.stringify(FRAME_CSS + css)} + '</style>' + ${JSON.stringify(html)};
    document.body.appendChild(d);
  })()`);
  await evaluate('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))');
  await sleep(400);
  // Before each screenshot: the face is still there (openCanvas reloaded until the page drew with it).
  const fontOk = await evaluate(`document.fonts.load(${JSON.stringify(FONT)}).then(() => document.fonts.check(${JSON.stringify(FONT)}))`);
  if (fontOk !== true) throw new Error(`Plus Jakarta Sans 800 not loaded before ${path.basename(out)}: ${JSON.stringify(fontOk)}`);
  const lay = await evaluate(CHECK(allowClip));
  if (!lay || lay.EXC) throw new Error('layout check failed to run: ' + JSON.stringify(lay));
  const words = wordingProblems(lay.text);
  const problems = lay.problems.concat(words.map((w) => 'wording: ' + w));
  console.log(`frame ${path.basename(out)}: ${lay.texts} text boxes, bands [${lay.bands.join(', ')}], footer ends y=${lay.footBottom}`
    + (problems.length ? '' : ' — layout OK'));
  if (problems.length && process.env.IG_DEBUG) console.log(await evaluate(`(() => [...document.querySelectorAll('#igstory > *')].map((e) => e.className + ' ' + Math.round(e.getBoundingClientRect().top) + '+' + Math.round(e.getBoundingClientRect().height)).join('\\n'))()`));
  if (problems.length) throw new Error(`frame ${path.basename(out)} not written:\n  ` + [...new Set(problems)].join('\n  '));
  const shot = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: W, height: H, scale: 1 }, captureBeyondViewport: true });
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
  const size = pngSize(out);
  if (size.w !== W || size.h !== H) throw new Error(`${out} is ${size.w}x${size.h}, not ${W}x${H}`);
  return out;
}

export function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

// ---- the sidecar ----------------------------------------------------------------------

// The text file Doug types stickers from: posting date, "as of" date, the
// exact link-sticker URL, the poll/quiz question with its options and answer,
// a one-line caption, and any notes. Same wording rules as the frames.
export function sidecarText({ series, posting, asOf, link, sticker, caption, frames = [], notes = [] }) {
  const L = [`WanderGrade story: ${series}`, `Posting date: ${posting}`, `As of: ${asOf}`, ''];
  if (frames.length) L.push('Frames, in order:', ...frames.map((f, i) => `  ${i + 1}. ${f}`), '');
  if (link) L.push('Link sticker URL (exact):', `  ${link}`, '');
  if (sticker) {
    L.push(`${sticker.kind} sticker${sticker.frame ? ` (frame ${sticker.frame})` : ''}:`, `  Question: ${sticker.question}`);
    (sticker.options || []).forEach((o, i) => L.push(`  Option ${i + 1}: ${o}`));
    if (sticker.answer != null) L.push(`  Correct answer: ${sticker.answer}`);
    L.push('');
  }
  if (caption) L.push('Caption:', `  ${caption}`, '');
  if (notes.length) L.push('Notes:', ...notes.map((n) => `  - ${n}`), '');
  L.push('Nothing here was posted or scheduled. Post by hand.');
  const s = L.join('\n') + '\n';
  const w = wordingProblems(s);
  if (w.length) throw new Error('sidecar wording: ' + w.join(', '));
  return s;
}
export function writeSidecar(file, fields) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, sidecarText(fields));
  return file;
}

// Where output goes: OUT_DIR, else scripts/dev/shots/ig/ (gitignored).
export const outDir = () => path.resolve(process.env.OUT_DIR || path.join(path.dirname(fileURLToPath(import.meta.url)), 'shots', 'ig'));

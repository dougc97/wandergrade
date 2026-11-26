// postcard_check.mjs — the Top Picks postcard (a country at a glance), headless, on a local server.
//   PC_BASE=http://127.0.0.1:8861 PC_CASE=rows PC_W=1280 node cdp.mjs ./postcard_check.mjs
// Env:
//   PC_BASE   the local server (never production)
//   PC_CASE   rows | keys | gems | served | filters | ratesdown | visa | photo | maps | layout | shots
//   PC_W, PC_H the viewport (below 700 wide: a phone, touch + a phone UA)
//   PC_SEED   localStorage to start from, JSON of strings ('{"fx_origin":"DE"}')
//   PC_FIX    recorded /api answers, <dir>/<sha1(path + query)>.json ({status, ct, body base64})
//   PC_PAR    scripts/parity/fixtures (non-USD rates, IN/GB/DE flights)
//   PC_SHOTS  where the shots case saves its PNGs (default: shots/ beside cdp.mjs); PC_PREFIX names them,
//             PC_ONLY=1 takes just the Top Picks one, PC_SCHEME=light|dark the colour scheme
// Production hosts are refused; Wikipedia and Wikimedia go through wikicache.mjs. Each case prints
// PASS/FAIL lines and "RESULT passed/total"; keep a case under ~50 s (one Chrome at a time).
import fs from 'node:fs'; import crypto from 'node:crypto'; import path from 'node:path';
import { enableWikiCache } from './wikicache.mjs';

const BASE = process.env.PC_BASE || 'http://127.0.0.1:8861';
const CASE = process.env.PC_CASE || 'rows';
const W = +process.env.PC_W || 1280, H = +process.env.PC_H || (W < 700 ? 844 : 900), PHONE = W < 700;
const FIX = process.env.PC_FIX ? process.env.PC_FIX.replace(/\/?$/, '/') : '';
const PAR = process.env.PC_PAR || '';
const CUR = { GB: 'GBP', IN: 'INR', DE: 'EUR' };
const key = (u) => crypto.createHash('sha1').update(u).digest('hex');
const results = [];
const ok = (c, m) => { results.push(!!c); console.log((c ? '  PASS  ' : '  FAIL  ') + m); return !!c; };

function parityAnswer(u) {
  if (!PAR) return null;
  const o = u.searchParams.get('origin'), base = u.searchParams.get('base');
  const f = (c, name) => { const p = `${PAR}/${c}/${name}.json`; return fs.existsSync(p) ? fs.readFileSync(p) : null; };
  if (u.pathname === '/api/rates' && base && base !== 'USD') return f(base, 'rates');
  if (u.pathname === '/api/flights' && o && CUR[o]) return f(CUR[o], 'flights');
  if (u.pathname === '/api/flight-value' && o && CUR[o]) return f(CUR[o], 'flight_value');
  return null;
}
// opt.rates: 'ok' | 'net' (every /api/rates fails); opt.slow: [{ re, ms }] holds matching requests back.
async function intercept({ send, on, sleep }, opt = {}) {
  let wiki = null;
  await enableWikiCache((m, p) => (m === 'Fetch.enable' ? Promise.resolve() : send(m, p)), (fn) => { wiki = fn; });
  const st = { fix: 0, refused: [], local: [], slowed: [], wiki: [], all: [] };
  const json = (id, body, code = 200) => send('Fetch.fulfillRequest', { requestId: id, responseCode: code,
    responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'Cache-Control', value: 'no-store' }],
    body: Buffer.from(body).toString('base64') });
  on(async (d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId, u = new URL(d.params.request.url);
    const slow = (opt.slow || []).find((s) => s.re.test(u.href));
    if (slow) { st.slowed.push(u.pathname); await sleep(slow.ms); }
    if (/(^|\.)wandergrade\.com$|onrender\.com$|cloudflareinsights|prf\.hn$|hostelworld|stay22|booking\.com|travelpayouts|aviasales/.test(u.hostname)) {
      st.refused.push(u.href); return send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' });
    }
    st.all.push(u.hostname + u.pathname);
    if (/wikipedia\.org$|wikimedia\.org$/.test(u.hostname)) { st.wiki.push(u.href); return wiki(d); }
    if (u.hostname !== '127.0.0.1') return send('Fetch.continueRequest', { requestId: id });
    if (u.pathname === '/api/rates' && opt.rates === 'net') return send('Fetch.failRequest', { requestId: id, errorReason: 'Failed' });
    if (u.pathname.startsWith('/api/advisories') && opt.adv === 'net') return send('Fetch.failRequest', { requestId: id, errorReason: 'Failed' });
    if (u.pathname === '/api/geo') return json(id, '{}');
    if (u.pathname.startsWith('/api/') && !u.pathname.startsWith('/api/advisories')) {
      const pb = parityAnswer(u);
      if (pb) return json(id, pb);
      const f = FIX && FIX + key(u.pathname + u.search) + '.json';
      if (f && fs.existsSync(f)) {
        const c = JSON.parse(fs.readFileSync(f, 'utf8')); st.fix++;
        return send('Fetch.fulfillRequest', { requestId: id, responseCode: c.status, responseHeaders: [{ name: 'Content-Type', value: c.ct }, { name: 'Cache-Control', value: 'no-store' }], body: c.body });
      }
      st.local.push(u.pathname + u.search);
    }
    return send('Fetch.continueRequest', { requestId: id });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  return st;
}

export default async (ctx) => {
  const { send, on, evaluate, setSize, nav, shot, sleep, errs } = ctx;
  const seed = process.env.PC_SEED || '';
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    window.__cls = 0; window.__shifts = [];
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) { window.__cls += e.value;
      window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(5), src: (e.sources || []).map((s) => s.node ? (s.node.id ? '#' + s.node.id : (s.node.className || s.node.nodeName || '?')) : '?').slice(0, 3) }); } })
      .observe({ type: 'layout-shift', buffered: true });
    ${seed ? `try { var s = ${seed}; for (var k in s) localStorage.setItem(k, s[k]); } catch (e) {}` : ''}` });
  const slow = [];
  if (CASE === 'visa') slow.push({ re: /\/visa-passport\.json/, ms: 2500 });
  if (CASE === 'photo') slow.push({ re: /(upload|thumb)\.wikimedia\.org|wikipedia\.org\/w\/api\.php/, ms: 2000 });
  const st = await intercept(ctx, { rates: CASE === 'ratesdown' ? 'net' : 'ok', adv: CASE === 'advdown' ? 'net' : 'ok', slow });
  await setSize(W, H, PHONE);
  if (process.env.PC_SCHEME) await ctx.scheme(process.env.PC_SCHEME === 'dark');   // light | dark (default: the browser's)

  const waitFor = async (expr, ms = 15000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { const v = await evaluate(expr); if (v && !v.EXC) return v; await sleep(150); }
    return evaluate(expr);
  };
  // A real pointer click at an element's centre (scrolled into view first).
  const click = async (sel, mods = 0) => {
    // The first point of the element's box that hit-tests to it (a chip can overlap a name's box).
    const r = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null;
      el.scrollIntoView({ block: 'center', behavior: 'instant' }); const b = el.getBoundingClientRect();
      for (const fy of [0.5, 0.3, 0.7]) for (const fx of [0.5, 0.15, 0.3, 0.7, 0.85]) {
        const x = b.left + b.width * fx, y = b.top + b.height * fy, hit = document.elementFromPoint(x, y);
        if (hit && el.contains(hit)) return { x, y }; }
      return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`);
    if (!r || r.EXC) return false;
    await sleep(60);
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased'])
      await send('Input.dispatchMouseEvent', { type, x: r.x, y: r.y, button: type === 'mouseMoved' ? 'none' : 'left', clickCount: 1, modifiers: mods });
    await sleep(250);
    return true;
  };
  const KEYS = { Enter: [13, '\r'], Escape: [27, ''], Tab: [9, ''] };
  const press = async (k, shift = false) => {
    const [code, text] = KEYS[k];
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code: k, windowsVirtualKeyCode: code, text, modifiers: shift ? 8 : 0 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code: k, windowsVirtualKeyCode: code, modifiers: shift ? 8 : 0 });
    await sleep(200);
  };
  // What the page shows about postcards right now.
  const state = (host = '#topCards') => evaluate(`(() => {
    const host = document.querySelector(${JSON.stringify(host)});
    const pcs = [...document.querySelectorAll('tr.pcrow')];
    const pc = pcs[0], prev = pc && pc.previousElementSibling;
    const a = document.activeElement;
    const card = pc && pc.querySelector('.postcard');
    return { n: pcs.length, iso: pc ? pc.getAttribute('data-pc-iso') : null, after: prev && prev.getAttribute('data-iso'),
      inHost: !!(pc && host && host.contains(pc)), url: location.pathname + location.search, tabValue: !document.getElementById('tab-value').hidden,
      expanded: [...document.querySelectorAll('.gradetable a.destlink[aria-expanded="true"]')].map((x) => x.closest('tr').dataset.iso),
      controls: (document.querySelector('.gradetable a.destlink[aria-expanded="true"]') || { getAttribute: () => null }).getAttribute('aria-controls'),
      pcId: pc ? pc.id : null,
      active: a ? (a.className || a.tagName) + (a.closest && a.closest('tr[data-iso]') ? '@' + a.closest('tr[data-iso]').dataset.iso : '') : null,
      h: card ? Math.round(card.getBoundingClientRect().height * 10) / 10 : null,
      text: card ? card.innerText.replace(/\\s+/g, ' ').trim() : null,
      trip: (document.querySelector('#tripTabLabel .tripcount') || {}).textContent || '0',
      sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
  })()`);
  const rows = (host = '#topCards') => evaluate(`[...document.querySelectorAll('${host} table.gradetable:not(.skeleton) tbody tr[data-iso]')].map((t) => t.dataset.iso)`);
  const ready = `(() => { const h = document.getElementById('topCards'); return typeof loaded !== 'undefined' && loaded.value && h && !h.hasAttribute('data-ssr')
    && h.querySelectorAll('table.gradetable:not(.skeleton) tbody tr[data-iso]').length >= 5 && typeof togglePostcard === 'function'; })()`;
  const tag = `${CASE}@${W}`;

  if (CASE === 'advdown') {
    // Advisories down: Top Picks can't rank (as before), the served rows stay, and a click on one
    // opens its postcard (it reads no advisory) without an error of its own.
    await nav(BASE + '/', 0);
    const live = await waitFor(`(() => { const h = document.getElementById('topCards'); return typeof togglePostcard === 'function' && h && h.querySelector('tr[data-iso]') ? [...h.querySelectorAll('tr[data-iso]')].map((t) => t.dataset.iso) : null; })()`, 8000);
    if (!ok(Array.isArray(live), `${tag}: rows on screen with app.js running (${JSON.stringify(live)})`)) return finish();
    await sleep(3000);
    const iso = live[1];
    await click(`#topCards tr[data-iso="${iso}"] td.rank`);
    await sleep(2500);
    const s1 = await state();
    ok(s1.n === 1 && s1.iso === iso && /Full guide →/.test(s1.text || ''), `${tag}: a row opens its postcard (${(s1.text || '').slice(0, 140)})`);
    ok(!/…/.test(s1.text || ''), `${tag}: nothing left waiting (${(s1.text || '').slice(0, 140)})`);
    return finish();
  }
  if (CASE === 'served') {
    // A click on the served rows before app.js redraws them: the postcard opens, and stays on that
    // country through the redraw (or closes if the redraw drops it). Never two.
    await nav(BASE + '/', 0);
    const live = await waitFor(`(() => { const h = document.getElementById('topCards'); return typeof renderValue === 'function' && h && h.hasAttribute('data-ssr') && h.querySelector('tr[data-iso]') ? [...h.querySelectorAll('tr[data-iso]')].map((t) => t.dataset.iso) : null; })()`, 8000);
    if (!ok(Array.isArray(live), `${tag}: served rows on screen with app.js running (${JSON.stringify(live)})`)) return finish();
    // In-page, in one go: a pointer click can land after the app's redraw has moved the rows (these
    // fixtures rank them differently from the server's own data).
    const iso = live[1];
    const was = await evaluate(`(() => { const h = document.getElementById('topCards'); const ssr = h.hasAttribute('data-ssr');
      h.querySelector('tr[data-iso="${iso}"] td.rank').click(); return ssr; })()`);
    await sleep(250);
    const s1 = await state();
    ok(s1.n === 1 && s1.iso === iso && s1.after === iso, `${tag}: a ${was ? 'served' : '(already redrawn)'} row opens its postcard (${JSON.stringify(s1).slice(0, 200)})`);
    await waitFor(ready, 20000);
    const s2 = await state(), listed = (await rows()).includes(iso);
    ok(listed ? s2.n === 1 && s2.iso === iso && s2.after === iso : s2.n === 0,
       `${tag}: after the app's redraw it is ${listed ? 'still open under ' + iso : 'closed (' + iso + ' left the list)'} (${JSON.stringify(s2)})`);
    return finish();
  }

  if (CASE === 'net') {
    // What a cold homepage load fetches (any tree, main too): Wikimedia, and every request, in order.
    await nav(BASE + '/', 12000);
    console.log('WIKI ' + st.wiki.length + ' ' + JSON.stringify(st.wiki.map((u) => u.slice(0, 150))));
    console.log('ALL ' + st.all.length + ' ' + JSON.stringify([...new Set(st.all)]));
    ok(true, `${tag}: ${st.wiki.length} Wikimedia requests, ${st.all.length} in all`);
    return finish();
  }
  if (CASE === 'cls') {
    // A cold homepage load, no postcard involved: the page's own layout shift (any tree, main too).
    await nav(BASE + '/', 12000);
    const r = await evaluate(`({ cls: +window.__cls.toFixed(5), shifts: window.__shifts })`);
    console.log('CLS ' + JSON.stringify(r));
    ok(r && typeof r.cls === 'number', `${tag}: cls ${r && r.cls}`);
    return finish();
  }
  if (CASE === 'ratesdown') {
    // Round 10's notice instead of the list (after the quiet retries): no postcard, no errors, and a
    // click where a row was opens nothing.
    await nav(BASE + '/', 500);
    const r = await waitFor(`(() => document.querySelector('#topCards .ratesdown') ? { btn: !!document.getElementById('ratesRetry'), pcs: document.querySelectorAll('tr.pcrow').length, rows: document.querySelectorAll('#topCards tr[data-iso]').length } : null)()`, 30000);
    ok(r && r.btn && r.pcs === 0 && r.rows === 0, `${tag}: rates down: the notice with Try again, no rows, no postcard (${JSON.stringify(r)})`);
    await click('#topCards .ratesdown p');
    const r2 = await evaluate(`document.querySelectorAll('tr.pcrow').length`);
    ok(r2 === 0, `${tag}: a click on the notice opens nothing`);
    return finish();
  }
  await nav(BASE + '/', 500);
  const r0 = await waitFor(ready, 25000);
  if (!ok(r0 === true, `${tag}: Top Picks drawn by the app`)) return finish();
  const list = await rows();

  if (CASE === 'rows') {
    const url0 = (await state()).url;
    const a = list[0], b = list[1], c = list[2];
    await click(`#topCards tr[data-iso="${a}"] td.rank`);
    let s = await state();
    ok(s.n === 1 && s.iso === a && s.after === a && s.inHost && s.url === url0 && s.tabValue,
       `${tag}: a click on row 1 opens one postcard right under it, URL and tab unchanged (${JSON.stringify({ n: s.n, iso: s.iso, after: s.after, url: s.url })})`);
    ok(/Full guide →/.test(s.text) && /Add to trip/.test(s.text), `${tag}: it reads "${(s.text || '').slice(0, 160)}"`);
    ok(s.expanded.join() === a && s.controls && s.controls === s.pcId, `${tag}: the name says expanded and what it controls (${s.expanded} ${s.controls} ${s.pcId})`);
    await click(`#topCards tr[data-iso="${a}"] td.rank`);
    s = await state();
    ok(s.n === 0 && !s.expanded.length, `${tag}: the same row again closes it`);
    await click(`#topCards tr[data-iso="${b}"] td.scell[data-go="afford"] .gr`);
    s = await state();
    ok(s.n === 1 && s.iso === b && s.after === b && s.url === url0 && s.tabValue, `${tag}: a grade badge opens its row's postcard, no jump (${JSON.stringify({ iso: s.iso, url: s.url })})`);
    await click(`#topCards tr[data-iso="${c}"] a.destlink`);
    s = await state();
    ok(s.n === 1 && s.iso === c && s.after === c && s.url === url0 && s.tabValue, `${tag}: the name opens it too and the first one moves (never two) (${JSON.stringify({ n: s.n, iso: s.iso, url: s.url })})`);
    // New tab / window: left to the browser (nothing prevented, no postcard). The window-level
    // listener runs after the page's own and cancels the navigation so this tab stays.
    const nt = await evaluate(`(() => { const out = {}; const a = document.querySelector('#topCards tr[data-iso="${a}"] a.destlink');
      document.querySelectorAll('tr.pcrow').forEach(() => {});
      for (const [k, init] of [['meta', { metaKey: true }], ['ctrl', { ctrlKey: true }], ['shift', { shiftKey: true }], ['middle', { button: 1 }]]) {
        let prevented = null; const rec = (e) => { prevented = e.defaultPrevented; e.preventDefault(); };
        const type = k === 'middle' ? 'auxclick' : 'click';
        window.addEventListener(type, rec, { once: true });
        a.dispatchEvent(new MouseEvent(type, Object.assign({ bubbles: true, cancelable: true, view: window }, init)));
        out[k] = { prevented, pc: document.querySelectorAll('tr.pcrow').length, open: (document.querySelector('tr.pcrow') || {}).getAttribute ? document.querySelector('tr.pcrow').getAttribute('data-pc-iso') : null };
      }
      out.href = a.getAttribute('href'); return out; })()`);
    ok(nt && ['meta', 'ctrl', 'shift', 'middle'].every((k) => nt[k] && nt[k].prevented === false && nt[k].open === c),
       `${tag}: cmd/ctrl/shift/middle-click on a name is the browser's (not prevented, no postcard for it) → ${nt && nt.href} (${JSON.stringify(nt)})`);
    ok(/^\/guide\/[a-z-]+$/.test(nt && nt.href), `${tag}: the name is still a real /guide/ link`);
    // Esc closes, focus to the name.
    await press('Escape');
    s = await state();
    ok(s.n === 0 && s.active === `destlink@${c}`, `${tag}: Esc closes it and the focus is on ${c}'s name (${s.active})`);
    // Add to trip flips in place.
    await click(`#topCards tr[data-iso="${b}"] td.rank`);
    const t0 = (await state()).trip;
    await click('tr.pcrow .pctrip');
    s = await state();
    ok(s.n === 1 && s.iso === b && /✓ On your trip/.test(s.text) && +s.trip === +t0 + 1,
       `${tag}: 🧳 Add to trip → ✓ On your trip, still open, Trip count ${t0} → ${s.trip}`);
    ok(s.active === 'pcbtn pctrip on@' + b || /pctrip/.test(s.active || ''), `${tag}: the focus stays on the trip button (${s.active})`);
    await click('tr.pcrow .pctrip');
    s = await state();
    ok(/🧳 Add to trip/.test(s.text) && +s.trip === +t0, `${tag}: and back (Trip count ${s.trip})`);
    // Full guide → on an "Any time" row: the guide on that row's month.
    const m = await evaluate(`(document.querySelector('#topCards tr[data-iso="${b}"]') || {}).dataset.m || ''`);
    await click('tr.pcrow .pcguide');
    await sleep(1500);
    const g = await evaluate(`(() => ({ guide: !document.getElementById('tab-guide').hidden, path: location.pathname, month: travelMonth(), box: document.getElementById('bestCountry').value }))()`);
    ok(g.guide && g.box === b && /^\/guide\//.test(g.path) && (!m || g.month === +m),
       `${tag}: Full guide → opens ${b}'s guide${m ? ' on its row month ' + m : ''} (${JSON.stringify(g)})`);
    return finish();
  }

  if (CASE === 'keys') {
    const a = list[1];
    await evaluate(`document.querySelector('#topCards tr[data-iso="${a}"] a.destlink').focus()`);
    await press('Enter');
    let s = await state();
    ok(s.n === 1 && s.iso === a && s.expanded.join() === a && s.active === `destlink@${a}`,
       `${tag}: Enter on a focused name opens its postcard, aria-expanded="true", focus stays on the name (${JSON.stringify({ n: s.n, exp: s.expanded, active: s.active })})`);
    const seen = [];
    for (let i = 0; i < 12; i++) { await press('Tab'); const x = (await state()).active || ''; seen.push(x); if (/pcclose/.test(x)) break; }
    ok(seen.some((x) => /pcguide/.test(x)) && seen.some((x) => /pctrip/.test(x)), `${tag}: Tab reaches Full guide → and Add to trip (${seen.join(' > ')})`);
    await press('Escape');
    s = await state();
    ok(s.n === 0 && s.active === `destlink@${a}` && !s.expanded.length, `${tag}: Esc from inside closes it, focus back on the name (${s.active})`);
    const ae = await evaluate(`document.querySelector('#topCards tr[data-iso="${a}"] a.destlink').getAttribute('aria-expanded')`);
    ok(ae === 'false', `${tag}: the name says collapsed again (${ae})`);
    await press('Enter');
    await press('Enter');
    s = await state();
    ok(s.n === 0, `${tag}: Enter twice: open, then closed`);
    // ✕ by keyboard: focus goes back to the name, not <body>.
    await press('Enter');
    await evaluate(`document.querySelector('tr.pcrow .pcclose').focus()`);
    await press('Enter');
    s = await state();
    ok(s.n === 0 && s.active === `destlink@${a}`, `${tag}: ✕ closes, focus on the name (${s.active})`);
    return finish();
  }

  if (CASE === 'filters') {
    // Sort, month, budget, region while a postcard is open: stays on the same country if it is still
    // listed, closes if not; never two.
    const a = list[2];
    await click(`#topCards tr[data-iso="${a}"] td.rank`);
    await click('#topCards th[data-sk="dest"] button');
    let s = await state(), l = await rows();
    ok(l.join() !== list.join() && s.n === 1 && s.iso === a && s.after === a, `${tag}: sorted A→Z, still open under ${a} (${l.join(' ')})`);
    await evaluate(`(() => { const s = document.getElementById('valueMonth'); s.value = '3'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await sleep(1500);
    s = await state(); l = await rows();
    ok(l.includes(a) ? s.n === 1 && s.iso === a && s.after === a : s.n === 0, `${tag}: March picked: ${l.includes(a) ? 'still open under ' + a : 'closed (' + a + ' left)'} (${JSON.stringify({ n: s.n, iso: s.iso, text: (s.text || '').slice(-60) })})`);
    if (s.n) ok(!/🧳 worth/.test(s.text) || /🗓️/.test(await evaluate(`document.querySelector('#topCards tr[data-iso="${a}"] td.dest').textContent`)),
                `${tag}: a month row without its own month tag shows 📅, not 🧳 days (${(s.text || '').slice(-50)})`);
    // A region without it.
    const reg = await evaluate(`(() => { const sel = document.getElementById('valueRegion'); return [...sel.options].map((o) => o.value).filter((v) => v && v !== 'all'); })()`);
    let closed = null;
    for (const r of reg || []) {
      await evaluate(`(() => { const s = document.getElementById('valueRegion'); s.value = ${JSON.stringify(r)}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
      await sleep(900);
      l = await rows(); s = await state();
      if (!l.includes(a)) { closed = { r, n: s.n, expanded: s.expanded }; break; }
    }
    ok(closed && closed.n === 0 && !closed.expanded.length, `${tag}: a region without ${a} closes it (${JSON.stringify(closed)})`);
    await evaluate(`(() => { const s = document.getElementById('valueRegion'); s.value = 'all'; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await sleep(900);
    l = await rows(); s = await state();
    ok(s.n === 0, `${tag}: and it stays closed when the region comes back (${s.n})`);
    // Budget: open the last row, then a budget that drops some countries.
    const z = l[l.length - 1];
    await click(`#topCards tr[data-iso="${z}"] td.rank`);
    await evaluate(`(() => { const i = document.getElementById('budgetTotal'); i.value = '900'; i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await sleep(1500);
    l = await rows(); s = await state();
    ok((l.includes(z) ? s.n === 1 && s.iso === z && s.after === z : s.n === 0) && s.n <= 1,
       `${tag}: a budget: ${l.includes(z) ? 'still open under ' + z : 'closed (' + z + ' dropped)'} (${l.join(' ')})`);
    return finish();
  }

  if (CASE === 'gems') {
    await evaluate(`(() => { const d = document.getElementById('gemsBox'); d.open = true; d.dispatchEvent(new Event('toggle')); })()`);
    await sleep(800);
    const gl = await rows('#gemRows');
    if (!ok(gl.length >= 3, `${tag}: Hidden gems rows (${gl.join(' ')})`)) return finish();
    await click(`#gemRows tr[data-iso="${gl[1]}"] td.rank`);
    const s = await state('#gemRows');
    ok(s.n === 1 && s.iso === gl[1] && s.after === gl[1] && s.inHost && s.tabValue, `${tag}: a gem row opens its postcard in the gems table (${JSON.stringify({ iso: s.iso, inHost: s.inHost })})`);
    await click(`#topCards tr[data-iso="${list[0]}"] td.rank`);
    const s2 = await state();
    ok(s2.n === 1 && s2.iso === list[0] && s2.inHost, `${tag}: opening one in Top Picks closes the gem's (never two)`);
    return finish();
  }

  if (CASE === 'maps' || CASE === 'maps2') {
    // Every map's country card is the postcard, plus the fact its map is about (Currency 💱, Safety
    // 🛡️/⚠️); the Wander List's ✓ Been / ★ Want to go still mark; ✕ closes; the full-screen overlay
    // gets the same card.
    const which = CASE === 'maps'
      ? [['value', null, 'valueMap', ''], ['data', 'currency', 'map', 'currency'], ['data', 'advisory', 'advMap', 'safety']]
      : [['data', 'afford', 'affMap', ''], ['data', 'flights', 'flightMap', ''], ['value', null, 'valueMap', '', 'fs']];
    const iso = process.env.PC_ISO || 'JP';
    for (const [tab, mode, id, fact, fs] of which) {
      await evaluate(`(async () => { await activateTab('${tab}', true); ${mode ? `await setDataMode('${mode}');` : ''} return 1; })()`);
      const drawn = await waitFor(`!!document.querySelector('#${id} svg path[data-iso="${iso}"]')`, 15000);
      if (!ok(drawn === true, `${tag}: #${id} drawn`)) continue;
      if (fs) { await evaluate(`openMapFullscreen(document.getElementById('${id}'))`); await sleep(500); }
      await evaluate(`document.querySelector('#${id} path[data-iso="${iso}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
      const c = await waitFor(`(() => { const c = document.querySelector('.countrycard'); if (!c || !c.querySelector('.postcard') || c.querySelector('.pcpend')) return null;
        const host = document.getElementById('${id}');
        return { after: host.nextElementSibling === c, fs: !!c.closest('.mapfs'), text: c.innerText.replace(/\s+/g, ' ').trim(),
          map: (c.querySelector('.pcfact[data-k="map"]') || {}).textContent || '', ks: [...c.querySelectorAll('.pcfact')].map((f) => f.dataset.k).join(),
          h: Math.round(c.getBoundingClientRect().height) }; })()`, 9000);
      if (!ok(c && c.text, `${tag}: #${id}${fs ? ' (full screen)' : ''}: ${iso}'s card is a postcard (${c && c.text.slice(0, 170)})`)) continue;
      ok(/Full guide →/.test(c.text) && /Add to trip/.test(c.text) && /✓ Been/.test(c.text) && /★ Want to go/.test(c.text),
         `${tag}: #${id}: Full guide →, Add to trip, ✓ Been, ★ Want to go`);
      ok(fs ? c.fs : c.after, `${tag}: #${id}: ${fs ? 'floats in the full-screen overlay' : 'right under its map'}`);
      ok(fact === 'currency' ? /^💱 /.test(c.map) : fact === 'safety' ? /^(🛡️|⚠️) /.test(c.map) : !c.map,
         `${tag}: #${id}: the map's own fact: ${c.map || '(none)'} [${c.ks}]`);
      if (id === 'valueMap' && !fs) {
        for (const [cc, fn] of [['visit', 'isVisited'], ['wish', 'loadWishlist().has']]) {
          await evaluate(`document.querySelector('.countrycard [data-cc="${cc}"]').click()`); await sleep(500);
          const on = await evaluate(`(() => ({ p: (document.querySelector('.countrycard [data-cc="${cc}"]') || {}).getAttribute && document.querySelector('.countrycard [data-cc="${cc}"]').getAttribute('aria-pressed'), m: ${fn}('${iso}') }))()`);
          await evaluate(`document.querySelector('.countrycard [data-cc="${cc}"]').click()`); await sleep(500);
          const off = await evaluate(`(() => ({ p: document.querySelector('.countrycard [data-cc="${cc}"]').getAttribute('aria-pressed'), m: ${fn}('${iso}') }))()`);
          ok(on.p === 'true' && on.m === true && off.p === 'false' && off.m === false, `${tag}: ${cc === 'visit' ? '✓ Been' : '★ Want to go'} marks and unmarks the Wander List (${JSON.stringify([on, off])})`);
        }
        const ph = await waitFor(`(() => { const i = document.querySelector('.countrycard img.pcimg'); return i && i.complete && i.naturalWidth ? { w: i.naturalWidth, src: i.currentSrc } : null; })()`, 8000);
        ok(ph && /\/(330|500)px-/.test(ph.src), `${tag}: the card's photo, a Wikimedia thumbnail step (${ph && ph.src.slice(-60)})`);
        await evaluate(`document.querySelector('.countrycard .pctrip').click()`); await sleep(400);
        const tr = await evaluate(`(() => ({ t: document.querySelector('.countrycard .pctrip').textContent, has: tripHas('${iso}') }))()`);
        ok(/✓ On your trip/.test(tr.t) && tr.has, `${tag}: the card's 🧳 Add to trip flips to ✓ On your trip`);
        await evaluate(`document.querySelector('.countrycard .pctrip').click()`); await sleep(300);
        // Another country on the same map reuses the card: never the last one's photo.
        const other = process.env.PC_ISO2 || 'TH';
        await evaluate(`document.querySelector('#${id} path[data-iso="${other}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
        await sleep(80);
        const sw = await evaluate(`(() => { const c = document.querySelector('.countrycard .postcard'); const i = c && c.querySelector('img.pcimg');
          return { iso: c && c.getAttribute('data-iso'), src: i ? i.currentSrc || i.src : null, alt: i ? i.alt : null }; })()`);
        ok(sw.iso === other && (!sw.src || sw.src !== ph.src) && !/Japan/.test(sw.alt || ''), `${tag}: ${other} after ${iso}: not ${iso}'s photo (${JSON.stringify(sw).slice(0, 200)})`);
      }
      await evaluate(`document.querySelector('.countrycard .pcclose').click()`); await sleep(300);
      const gone = await evaluate(`!document.querySelector('.countrycard') && !ccCurrent`);
      ok(gone === true, `${tag}: #${id}: ✕ closes it`);
      if (fs) await evaluate(`closeMapFullscreen()`);
    }
    return finish();
  }

  if (CASE === 'visa' || CASE === 'photo') {
    // A late visa table (non-US reader) or a late photo: the card fills in place, its height and the
    // rows under it don't move, and no layout shift is recorded.
    const a = list[0], b = list[1];
    await click(`#topCards tr[data-iso="${a}"] td.rank`);
    const t0 = await evaluate('performance.now()');
    const m = (q) => evaluate(`(() => { const c = document.querySelector('tr.pcrow .postcard'); const nx = document.querySelector('#topCards tr[data-iso="${b}"]');
      const v = c && c.querySelector('.pcfact[data-k="visa"]'); const i = c && c.querySelector('img.pcimg');
      return { h: c ? Math.round(c.getBoundingClientRect().height * 100) / 100 : null, next: nx ? Math.round(nx.getBoundingClientRect().top * 100) / 100 : null,
        visa: v ? v.textContent : null, pend: c ? c.querySelectorAll('.pcpend').length : null, img: i ? (i.complete && i.naturalWidth > 0) + ':' + i.className : 'none',
        photoBox: c ? (() => { const r = c.querySelector('.pcphoto').getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })() : null }; })()`);
    const before = await m();
    await sleep(CASE === 'photo' ? 5500 : 3500);   // the lookup and then the image, each held 2 s
    const after = await m();
    const sh = await evaluate(`window.__shifts.filter((x) => x.t > ${t0} + 400)`);
    if (CASE === 'visa') ok(/…/.test(before.visa || '') && before.pend > 0 && after.visa && !/…/.test(after.visa) && after.pend === 0,
                            `${tag}: the visa fact waited ("${before.visa}") and filled in place ("${after.visa}")`);
    else ok(before.img === 'none' || /false/.test(before.img), `${tag}: the photo was still on its way at open (${before.img})`) &&
         ok(/^true:.*\bin\b/.test(after.img), `${tag}: and then shown (${after.img})`);
    ok(before.h === after.h && before.next === after.next && JSON.stringify(before.photoBox) === JSON.stringify(after.photoBox),
       `${tag}: the card's height ${before.h} → ${after.h}, the next row ${before.next} → ${after.next}, photo box ${before.photoBox} → ${after.photoBox}`);
    ok(!sh.length, `${tag}: no layout shift after the open (${JSON.stringify(sh)})`);
    return finish();
  }

  if (CASE === 'layout') {
    // Columns don't move when a postcard opens; phones stack it (photo strip on top), wider screens put
    // the photo on the left; no sideways scroll with it open.
    const cols = () => evaluate(`[...document.querySelectorAll('#topCards table.gradetable thead th')].map((t) => Math.round(t.getBoundingClientRect().width * 10) / 10)`);
    const c0 = await cols();
    const a = list[0];
    await click(`#topCards tr[data-iso="${a}"] td.rank`);
    await sleep(600);
    const c1 = await cols();
    ok(c0.join() === c1.join(), `${tag}: column widths the same open and closed (${c0.join(' ')} | ${c1.join(' ')})`);
    const g = await evaluate(`(() => { const c = document.querySelector('tr.pcrow .postcard'); const p = c.querySelector('.pcphoto').getBoundingClientRect(), b = c.querySelector('.pcbody').getBoundingClientRect();
      const t = document.querySelector('#topCards table.gradetable').getBoundingClientRect(), r = c.getBoundingClientRect();
      return { photo: [p.left, p.top, p.width, p.height].map(Math.round), body: [b.left, b.top, b.width, b.height].map(Math.round), card: [r.left, r.right].map(Math.round), table: [t.left, t.right].map(Math.round),
        sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; })()`);
    if (W < 600) ok(g.photo[1] + g.photo[3] <= g.body[1] + 1 && g.photo[2] >= g.body[2] - 2, `${tag}: stacked: the photo a strip on top (${JSON.stringify(g)})`);
    else ok(g.photo[0] + g.photo[2] <= g.body[0] + 1 && Math.abs(g.photo[1] - g.body[1]) < 40, `${tag}: the photo on the left (${JSON.stringify(g)})`);
    ok(g.card[0] >= g.table[0] - 1 && g.card[1] <= g.table[1] + 1, `${tag}: the card stays inside the table (${g.card} in ${g.table})`);
    ok(g.sw <= g.cw, `${tag}: no sideways scroll with it open (${g.sw} <= ${g.cw})`);
    return finish();
  }

  if (CASE === 'shots') {
    // Proof screenshots: an open postcard in Top Picks ("Any time": the 🧳 days fact), Hidden gems, a
    // map card on the Top Picks map and on the Currency map. PC_SHOTS/<prefix>_<what>_<W>.png
    const dir = process.env.PC_SHOTS || path.join(path.dirname(new URL(import.meta.url).pathname), 'shots');
    fs.mkdirSync(dir, { recursive: true });
    const pre = process.env.PC_PREFIX || 'us';
    const snap = async (name, sel) => {
      await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (el) el.scrollIntoView({ block: 'center', behavior: 'instant' }); })()`);
      await sleep(1800);
      const r = await send('Page.captureScreenshot', { format: 'png' });
      const p = `${dir}/${pre}_${name}_${W}.png`; fs.writeFileSync(p, Buffer.from(r.result.data, 'base64'));
      const t = await evaluate(`(() => { const c = document.querySelector(${JSON.stringify(sel)}); return c ? c.innerText.replace(/\s+/g, ' ').trim().slice(0, 200) : null; })()`);
      ok(!!t, `${tag}: ${name}: ${p} — "${t}"`);
    };
    await click(`#topCards tr[data-iso="${list[0]}"] td.rank`);
    await waitFor(`(() => { const i = document.querySelector('tr.pcrow img.pcimg'); return i && i.complete; })()`, 8000);
    await snap('toppicks', 'tr.pcrow');
    if (!process.env.PC_ONLY) {
      await evaluate(`(() => { const d = document.getElementById('gemsBox'); d.open = true; d.dispatchEvent(new Event('toggle')); })()`);
      await sleep(600);
      const gl = await rows('#gemRows');
      await click(`#gemRows tr[data-iso="${gl[0]}"] td.rank`);
      await waitFor(`(() => { const i = document.querySelector('tr.pcrow img.pcimg'); return i && i.complete; })()`, 8000);
      await snap('gems', 'tr.pcrow');
      await press('Escape');
      const iso = process.env.PC_ISO || 'JP';
      await evaluate(`document.querySelector('#valueMap path[data-iso="${iso}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
      await waitFor(`(() => { const i = document.querySelector('.countrycard img.pcimg'); return i && i.complete && !document.querySelector('.countrycard .pcpend'); })()`, 8000);
      await snap('map-toppicks', '.countrycard');
      await evaluate(`(async () => { await activateTab('data', true); await setDataMode('currency'); return 1; })()`);
      await waitFor(`!!document.querySelector('#map svg path[data-iso="${iso}"]')`, 15000);
      await evaluate(`document.querySelector('#map path[data-iso="${iso}"]').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
      await waitFor(`(() => { const i = document.querySelector('.countrycard img.pcimg'); return i && i.complete && !document.querySelector('.countrycard .pcpend'); })()`, 8000);
      await snap('map-currency', '.countrycard');
    }
    return finish();
  }

  ok(false, `unknown case ${CASE}`);
  return finish();

  function finish() {
    const real = errs.filter((e) => !/favicon|BlockedByClient|ERR_BLOCKED_BY_CLIENT|net::ERR_FAILED.*\/api\/rates|Failed to load resource/.test(e));
    ok(!real.length, `${tag}: no console errors (${real.slice(0, 3).join(' | ')})`);
    ok(!st.refused.length, `${tag}: no production requests (${st.refused.slice(0, 2).join(' ')})`);
    if (st.slowed.length) console.log('SLOWED ' + st.slowed.length + ' ' + [...new Set(st.slowed)].slice(0, 4).join(' '));
    console.log(`RESULT ${results.filter(Boolean).length}/${results.length} ${tag}`);
  }
};

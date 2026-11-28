// trip_route_check.mjs — the Trip tab's route (round 16): the order switch, drag/keyboard reordering, the
// legs between rows, the totals, share links, late or failing legs, context changes, and cold layout shift.
//   TR_BASE=http://127.0.0.1:11710 TR_CASE=modes TR_W=390 node cdp.mjs ./trip_route_check.mjs
// Env:
//   TR_BASE   the local server (never production)
//   TR_CASE   modes | drag | keys | share | fail | late | context | origin | one | empty | big | real | shots | cls
//   TR_W      viewport width (below 700: a phone, touch + a phone UA)
//   TR_FAIL   net | 503   (fail: how /api/trip-legs fails)
//   TR_N      cls: countries on the trip (0, 1, 3, 8); TR_NET=latency,kbps a slow link (cache off); TR_RUNS loads
//   TR_BASELINE=1  cls on a tree without the route (the base): only the layout shift is reported
//   TR_PAR    scripts/parity/fixtures: non-USD rates (/api/rates?base=EUR, GBP) answered from the repo's recordings
// /api/trip-legs is answered from a fixture (below) unless TR_CASE=real; production hosts are refused; Wikipedia
// and Wikimedia go through wikicache.mjs. Each case prints PASS/FAIL lines and "RESULT passed/total"; keep a case
// under ~50 s (one Chrome at a time).
import fs from 'node:fs';
import { enableWikiCache } from './wikicache.mjs';

const BASE = process.env.TR_BASE || 'http://127.0.0.1:11710';
const CASE = process.env.TR_CASE || 'modes';
const W = +process.env.TR_W || 1280, H = W < 700 ? 844 : 900, PHONE = W < 700;
const results = [];
const ok = (c, m) => { results.push(!!c); console.log((c ? '  PASS  ' : '  FAIL  ') + m); return !!c; };
const tag = `${CASE}@${W}`;

// The fixture: every leg between Thailand, Vietnam and Cambodia is fast and dear (USD 3,000 round trip, 1 h)
// except TH->VN and VN->KH, cheap and slow (USD 20, 10 h). So Cheapest is TH, VN, KH (Cambodia at an end,
// where distance alone puts it in the middle) and Quickest avoids both cheap legs.
const EXPENSIVE = { fare: 3000, dur: 60 }, CHEAP = { fare: 20, dur: 600 };
const SPECIAL = { 'TH>VN': CHEAP, 'VN>KH': CHEAP };
const SEA = ['TH', 'VN', 'KH'];
function legsFixture(u) {
  const isos = (u.searchParams.get('isos') || '').split(',').filter(Boolean), legs = {};
  for (const a of isos) for (const b of isos) {
    if (a === b || !SEA.includes(a) || !SEA.includes(b)) continue;
    const v = SPECIAL[a + '>' + b] || EXPENSIVE;
    (legs[a] = legs[a] || {})[b] = { fare: v.fare, basis: 'avg', dur: v.dur, stops: 0 };
  }
  return JSON.stringify({ configured: true, origin: u.searchParams.get('origin'), month: u.searchParams.get('month'),
    legs, fit: { a: 40, b: 0.06, n: 35 }, pending: [] });
}

async function intercept({ send, on, sleep }, opt = {}) {
  let wiki = null;
  await enableWikiCache((m, p) => (m === 'Fetch.enable' ? Promise.resolve() : send(m, p)), (fn) => { wiki = fn; });
  const st = { refused: [], legs: [], legsAnswered: 0, world: 0, third: [] };
  const json = (id, body, code = 200) => send('Fetch.fulfillRequest', { requestId: id, responseCode: code,
    responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'Cache-Control', value: 'no-store' }],
    body: Buffer.from(body).toString('base64') });
  on(async (d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId, u = new URL(d.params.request.url);
    if (/(^|\.)wandergrade\.com$|onrender\.com$|cloudflareinsights|prf\.hn$|hostelworld|stay22|booking\.com|travelpayouts|aviasales|tp\.media|gc\.ca$/.test(u.hostname)) {
      st.refused.push(u.href); return send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' });
    }
    if (/wikipedia\.org$|wikimedia\.org$/.test(u.hostname)) return wiki(d);
    if (u.hostname !== '127.0.0.1') { st.third.push(u.hostname); return send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' }); }
    if (u.pathname === '/world.geojson') st.world++;
    if (u.pathname === '/api/geo') return json(id, '{}');
    const base = u.searchParams.get('base');
    if (u.pathname === '/api/rates' && base && base !== 'USD' && process.env.TR_PAR) {
      const f = `${process.env.TR_PAR}/${base}/rates.json`;
      if (fs.existsSync(f)) return json(id, fs.readFileSync(f));
    }
    if (u.pathname === '/api/trip-legs') {
      st.legs.push(u.search);
      if (opt.legs === 'real') return send('Fetch.continueRequest', { requestId: id });
      if (opt.legs === 'net') return send('Fetch.failRequest', { requestId: id, errorReason: 'Failed' });
      if (opt.legs === '503') return json(id, '{"error":"busy"}', 503);
      if (opt.legsDelay) await sleep(opt.legsDelay);
      st.legsAnswered = Date.now();
      return json(id, legsFixture(u));
    }
    return send('Fetch.continueRequest', { requestId: id });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  return st;
}

export default async (ctx) => {
  const { send, evaluate, setSize, nav, sleep, errs } = ctx;
  // Seeds once per tab (sessionStorage survives a reload, so a reload keeps what the page saved).
  const seed = (o) => send('Page.addScriptToEvaluateOnNewDocument', { source: `
    window.__cls = 0; window.__shifts = [];
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) { window.__cls += e.value;
      window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(5), src: (e.sources || []).map((s) => s.node ? (s.node.id ? '#' + s.node.id : (s.node.className || s.node.nodeName || '?')) : '?').slice(0, 3) }); } })
      .observe({ type: 'layout-shift', buffered: true });
    try { if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1'); localStorage.clear();
      var s = ${JSON.stringify(o)}; for (var k in s) localStorage.setItem(k, s[k]); } } catch (e) {}` });
  const legsMode = CASE === 'real' ? 'real' : CASE === 'fail' ? (process.env.TR_FAIL || 'net') : null;
  const st = await intercept(ctx, { legs: legsMode, legsDelay: CASE === 'late' ? 4000 : 0 });
  await setSize(W, H, PHONE);

  const waitFor = async (expr, ms = 12000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { const v = await evaluate(expr); if (v && !v.EXC) return v; await sleep(120); }
    return evaluate(expr);
  };
  // What the Trip tab shows right now.
  const state = () => evaluate(`(() => {
    const host = document.getElementById('tripBook');
    if (!host) return { rows: [], legs: [], empty: !!document.querySelector('#tripBar > .triphint') };
    const rows = [...host.querySelectorAll('.tbrow[data-iso]')].map((r) => r.dataset.iso);
    const legs = [...host.querySelectorAll('.tbleg')].map((l) => ({ from: l.dataset.from, to: l.dataset.to, text: l.textContent.replace(/\\s+/g, ' ').trim() }));
    const pressed = [...host.querySelectorAll('.tripsort [data-ts][aria-pressed="true"]')].map((b) => b.dataset.ts);
    let ls = {}; try { ls = { trip: localStorage.getItem('fx_trip'), sort: localStorage.getItem('fx_tripsort'), last: localStorage.getItem('fx_tripsortlast') }; } catch (e) {}
    return { rows, legs, pressed, sortRow: !!host.querySelector('.tripsort'), mine: !!host.querySelector('.tsmine'),
      rec: !!host.querySelector('.tsrec'), handles: host.querySelectorAll('.tbdrag').length,
      total: (host.querySelector('.tbtotal') || { textContent: null }).textContent, ls,
      active: document.activeElement ? (document.activeElement.className || document.activeElement.tagName) + ':' + (document.activeElement.dataset.iso || document.activeElement.dataset.ts || '') : null,
      sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
  })()`);
  const filled = `(() => { const l = [...document.querySelectorAll('#tripBook .tbleg')]; return l.length && l.every((x) => !/…/.test(x.textContent)) && !/…/.test((document.querySelector('#tripBook .tbtotal') || {}).textContent || '…'); })()`;
  // The page's own answer for a mode over its current matrix (the jsc test checks the maths itself).
  const pageOrder = (mode) => evaluate(`(() => { if (!_tripM) return null; return tripBestOrder(_tripM.m, ${JSON.stringify(mode)}).map((i) => _tripM.nodes[i + 1]); })()`);
  const box = (sel) => evaluate(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null;
    el.scrollIntoView({ block: 'center', behavior: 'instant' }); const b = el.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2, top: b.top, bottom: b.bottom }; })()`);
  const click = async (sel) => {
    const r = await box(sel);
    if (!r || r.EXC) return false;
    await sleep(60);
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased'])
      await send('Input.dispatchMouseEvent', { type, x: r.x, y: r.y, button: type === 'mouseMoved' ? 'none' : 'left', clickCount: 1 });
    await sleep(250);
    return true;
  };
  // A pointer drag of iso's handle to just above (or below) another row.
  const drag = async (iso, toIso, below = false) => {
    const a = await box(`#tripBook .tbrow[data-iso="${iso}"] .tbdrag`);
    if (!a || a.EXC) return false;
    const b = await evaluate(`(() => { const r = document.querySelector('#tripBook .tbrow[data-iso="${toIso}"]'); if (!r) return null; const x = r.getBoundingClientRect(); return { top: x.top, bottom: x.bottom }; })()`);
    if (!b || b.EXC) return false;
    const y1 = below ? b.bottom - 3 : b.top + 3;
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: a.x, y: a.y, button: 'none' });
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: a.x, y: a.y, button: 'left', clickCount: 1 });
    for (let k = 1; k <= 8; k++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: a.x, y: a.y + (y1 - a.y) * k / 8, button: 'left', buttons: 1 }); await sleep(40); }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: a.x, y: y1, button: 'left', clickCount: 1 });
    await sleep(300);
    return true;
  };
  const KEYS = { ArrowUp: 38, ArrowDown: 40 };
  const press = async (k) => {
    await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: k, code: k, windowsVirtualKeyCode: KEYS[k] });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code: k, windowsVirtualKeyCode: KEYS[k] });
    await sleep(250);
  };
  const legsInOrder = (s) => {
    const want = [''].concat(s.rows, ['']);
    return s.legs.length === s.rows.length + 1 && s.legs.every((l, i) => l.from === want[i] && l.to === want[i + 1]);
  };
  const finish = () => {
    const bad = errs.filter((e) => !/trip-legs|ERR_BLOCKED_BY_CLIENT|status of 503/.test(e));
    if (CASE !== 'cls') ok(!bad.length, `${tag}: no console errors (${JSON.stringify(bad.slice(0, 3))})`);
    ok(!st.refused.length && !st.third.length, `${tag}: no production or third-party request (${JSON.stringify(st.refused.concat(st.third).slice(0, 3))})`);
    console.log(`RESULT ${results.filter(Boolean).length}/${results.length}`);
  };
  const US = { fx_origin: 'US', fx_homecur: 'USD', fx_homecur_manual: '0' };
  const trip = (isos, more = {}) => Object.assign({}, US, { fx_trip: JSON.stringify(isos), fx_tripmonth: '0' }, more);

  if (CASE === 'modes') {
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    const f = await waitFor(filled);
    let s = await state();
    ok(f === true, `${tag}: the legs and the totals fill in (${JSON.stringify(s.legs.map((l) => l.text))} / ${s.total})`);
    ok(s.sortRow && JSON.stringify(s.pressed) === '["best"]' && !s.mine, `${tag}: the switch shows Best overall selected (${s.pressed})`);
    ok(s.handles === 3 && legsInOrder(s) && s.legs.length === 4, `${tag}: a handle per row, a leg before, between and after the rows (${s.handles}, ${JSON.stringify(s.legs.map((l) => l.from + '>' + l.to))})`);
    const best = await pageOrder('best');
    ok(JSON.stringify(s.rows) === JSON.stringify(best), `${tag}: the rows are in the Best overall order (${s.rows} = ${best})`);
    ok(/USD/.test(s.total) && /flying/.test(s.total) && /✈️/.test(s.legs[1].text) && /USD/.test(s.legs[1].text),
       `${tag}: legs read "✈️ USD …" and the totals "USD … flying" (${s.legs[1].text} | ${s.total})`);
    ok(s.legs.slice(1, -1).every((l) => !/≈/.test(l.text.replace(/≈\s?\d+h|≈\d+m/g, ''))), `${tag}: the legs between trip countries are real (no ≈ fare) (${s.legs.slice(1, -1).map((l) => l.text)})`);
    await click('#tripBook .tripsort [data-ts="cheap"]');
    s = await state();
    ok(JSON.stringify(s.rows) === '["TH","VN","KH"]' && JSON.stringify(s.pressed) === '["cheap"]' && s.ls.sort === 'cheap',
       `${tag}: Cheapest: Thailand, Vietnam, Cambodia (the fixture's cheap legs) (${s.rows}, ${s.pressed}, ${s.ls.sort})`);
    ok(legsInOrder(s) && JSON.stringify(s.ls.trip) === JSON.stringify(JSON.stringify(s.rows)), `${tag}: the legs follow the rows, the saved trip is in the shown order (${s.ls.trip})`);
    const cheapLegs = JSON.stringify(s.legs);
    await click('#tripBook .tripsort [data-ts="quick"]');
    s = await state();
    const quick = await pageOrder('quick');
    ok(JSON.stringify(s.rows) === JSON.stringify(quick) && JSON.stringify(s.rows) !== '["TH","VN","KH"]' && JSON.stringify(s.pressed) === '["quick"]',
       `${tag}: Quickest reorders, away from both slow legs (${s.rows} = ${quick})`);
    ok(legsInOrder(s) && JSON.stringify(s.legs) !== cheapLegs, `${tag}: the leg lines change with the order`);
    ok(/tripsort/.test(s.active) || /quick/.test(s.active), `${tag}: focus stays on the switch (${s.active})`);
    await click('#tripBook .tripsort [data-ts="best"]');
    s = await state();
    ok(JSON.stringify(s.rows) === JSON.stringify(best) && JSON.stringify(s.pressed) === '["best"]', `${tag}: back to Best overall (${s.rows})`);
    ok(s.sw <= s.cw, `${tag}: no sideways scroll (${s.sw} <= ${s.cw})`);
    return finish();
  }

  if (CASE === 'drag') {
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await click('#tripBook .tripsort [data-ts="quick"]');
    let s = await state();
    const quick = s.rows.slice();
    const last = quick[quick.length - 1], first = quick[0];
    await drag(last, first);
    s = await state();
    const want = [last].concat(quick.slice(0, -1));
    ok(JSON.stringify(s.rows) === JSON.stringify(want), `${tag}: dragging ${last} above ${first} moves it to the top (${s.rows})`);
    ok(s.mine && s.rec && !s.pressed.length && s.ls.sort === 'mine' && s.ls.trip === JSON.stringify(want),
       `${tag}: "Your order" with ↺ Recommended, saved (fx_tripsort ${s.ls.sort}, fx_trip ${s.ls.trip})`);
    ok(legsInOrder(s), `${tag}: the legs follow the dragged order`);
    await sleep(500);
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await sleep(2500);
    s = await state();
    ok(JSON.stringify(s.rows) === JSON.stringify(want) && s.mine, `${tag}: after a reload, still the dragged order and "Your order" (${s.rows})`);
    await click('#tripBook .tripsort .tsrec');
    s = await state();
    ok(JSON.stringify(s.pressed) === '["quick"]' && JSON.stringify(s.rows) === JSON.stringify(quick) && s.ls.sort === 'quick' && !s.mine,
       `${tag}: ↺ Recommended goes back to the last mode, Quickest (${s.pressed}, ${s.rows})`);
    // a drop where it started changes nothing
    await drag(s.rows[1], s.rows[1]);
    const s2 = await state();
    ok(JSON.stringify(s2.rows) === JSON.stringify(s.rows) && s2.ls.sort === 'quick', `${tag}: a drop in place changes nothing (${s2.rows}, ${s2.ls.sort})`);
    // the rows below and the card around them stay put while dragging (a transform, not layout)
    return finish();
  }

  if (CASE === 'keys') {
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    let s = await state();
    const start = s.rows.slice(), iso = start[0];
    await evaluate(`(() => { document.querySelector('#tripBook .tbrow[data-iso="${iso}"] .tbdrag').focus(); return 1; })()`);
    await press('ArrowDown');
    s = await state();
    ok(JSON.stringify(s.rows) === JSON.stringify([start[1], iso, start[2]]) && s.mine && s.ls.sort === 'mine',
       `${tag}: ArrowDown on ${iso}'s handle moves it down one, "Your order" (${s.rows})`);
    ok(s.active === 'tbdrag:' + iso, `${tag}: focus stays on the moved row's handle (${s.active})`);
    await press('ArrowDown');
    await press('ArrowDown');   // already last: nothing
    s = await state();
    ok(JSON.stringify(s.rows) === JSON.stringify([start[1], start[2], iso]) && s.active === 'tbdrag:' + iso, `${tag}: and again to the end, no further (${s.rows})`);
    await press('ArrowUp');
    s = await state();
    ok(JSON.stringify(s.rows) === JSON.stringify([start[1], iso, start[2]]), `${tag}: ArrowUp moves it back up (${s.rows})`);
    const label = await evaluate(`document.querySelector('#tripBook .tbrow[data-iso="${iso}"] .tbdrag').getAttribute('aria-label')`);
    ok(/2 of 3/.test(label || '') && /arrow/i.test(label || ''), `${tag}: the handle names its place and the keys (${label})`);
    return finish();
  }

  if (CASE === 'share') {
    await seed(trip(['FR', 'IT']));
    await nav(BASE + '/?tab=trip&tp=KH,TH,VN', 0);
    await waitFor(filled);
    await sleep(2500);
    let s = await state();
    ok(JSON.stringify(s.rows) === '["KH","TH","VN"]' && s.mine && !s.pressed.length, `${tag}: a shared link opens in its own order as "Your order" (${s.rows})`);
    ok(s.ls.trip === '["FR","IT"]' && s.ls.sort == null, `${tag}: the reader's own trip and order are untouched (${s.ls.trip}, ${s.ls.sort})`);
    await click('#tripBook .tripsort [data-ts="cheap"]');
    s = await state();
    ok(JSON.stringify(s.rows) === '["TH","VN","KH"]' && s.ls.trip === '["FR","IT"]' && s.ls.sort == null,
       `${tag}: Cheapest reorders the shared trip on screen only (${s.rows}, ${s.ls.trip})`);
    const link = await evaluate(`(() => { try { return buildShareURL(true); } catch (e) { return 'ERR ' + e.message; } })()`);
    ok(/tp=TH(%2C|,)VN(%2C|,)KH/.test(link || ''), `${tag}: a Share link carries the order shown (${link})`);
    return finish();
  }

  if (CASE === 'fail') {
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    const f = await waitFor(filled, 9000);
    const s = await state();
    ok(f === true && st.legs.length >= 1, `${tag}: /api/trip-legs fails (${process.env.TR_FAIL || 'net'}) and the legs still fill in (${JSON.stringify(s.legs.map((l) => l.text))})`);
    ok(s.legs.slice(1, -1).every((l) => /≈/.test(l.text)) && /≈/.test(s.total || ''), `${tag}: the legs between trip countries are estimates (≈), the totals too (${s.total})`);
    const best = await pageOrder('best');
    ok(JSON.stringify(s.rows) === JSON.stringify(best) && s.rows.length === 3, `${tag}: still ordered (Best overall on estimates) (${s.rows})`);
    await click('#tripBook .tripsort [data-ts="quick"]');
    const s2 = await state();
    ok(JSON.stringify(s2.pressed) === '["quick"]' && legsInOrder(s2), `${tag}: the switch still works (${s2.rows})`);
    return finish();
  }

  if (CASE === 'late') {
    // the legs answer after 4 s: an order on estimates first, then the real one — unless the reader dragged
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    const t0 = Date.now();
    await waitFor(filled, 2900);
    let s = await state();
    const early = s.rows.slice(), answered0 = st.legsAnswered;
    ok(!answered0 && s.legs.slice(1, -1).every((l) => /≈/.test(l.text)), `${tag}: before the answer (${Date.now() - t0} ms): estimated legs, order ${early}`);
    await waitFor(`(() => !!document.querySelector('#tripBook .tbleg') && [...document.querySelectorAll('#tripBook .tbleg')].slice(1, -1).every((l) => !/≈\\s?(USD|EUR)/.test(l.textContent)))()`, 5000);
    s = await state();
    ok(st.legsAnswered && JSON.stringify(s.rows) === '["TH","VN","KH"]' && JSON.stringify(early) !== JSON.stringify(s.rows),
       `${tag}: once the real legs land the order changes to theirs (${early} -> ${s.rows})`);
    // again, dragging before the answer
    await evaluate(`(() => { sessionStorage.removeItem('__seeded'); return 1; })()`);
    st.legsAnswered = 0;
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled, 2900);
    await sleep(200);
    s = await state();
    const r0 = s.rows.slice();
    await drag(r0[2], r0[0]);
    s = await state();
    const dragged = s.rows.slice();
    ok(!st.legsAnswered && s.mine && JSON.stringify(dragged) === JSON.stringify([r0[2], r0[0], r0[1]]), `${tag}: dragged before the answer (${dragged})`);
    await waitFor(`(() => [...document.querySelectorAll('#tripBook .tbleg')].slice(1, -1).every((l) => !/≈\\s?(USD|EUR)/.test(l.textContent)))()`, 5000);
    await sleep(400);
    s = await state();
    ok(st.legsAnswered && JSON.stringify(s.rows) === JSON.stringify(dragged) && s.mine, `${tag}: the answer fills the legs and leaves the dragged order alone (${s.rows})`);
    return finish();
  }

  if (CASE === 'context') {
    await seed(trip(['KH', 'TH', 'VN'], { fx_tripmonth: '3' }));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    const n0 = st.legs.length;
    ok(st.legs.some((q) => /month=\d{4}-03/.test(q)), `${tag}: the legs are asked for the trip month (${st.legs})`);
    await evaluate(`(() => { const m = document.getElementById('tripMonth'); m.value = '5'; m.dispatchEvent(new Event('change')); return 1; })()`);
    await waitFor(filled);
    await sleep(600);
    ok(st.legs.length > n0 && /month=\d{4}-05/.test(st.legs[st.legs.length - 1]), `${tag}: a new month asks again (${st.legs.slice(n0)})`);
    let s = await state();
    ok(/USD/.test(s.total), `${tag}: totals in USD (${s.total})`);
    // the reader's currency, changed on Top Picks, then back to Trip
    await click('#tabs button[data-tab="value"]');
    await waitFor(`(() => typeof loaded !== 'undefined' && loaded.value && document.getElementById('homeCur').options.length > 3)()`, 20000);
    await evaluate(`(() => { const c = document.getElementById('homeCur'); c.value = 'EUR'; c.dispatchEvent(new Event('change')); return c.value; })()`);
    await sleep(800);
    await click('#tabs button[data-tab="trip"]');
    await waitFor(filled);
    s = await state();
    ok(/EUR/.test(s.total || '') && s.legs.every((l) => /EUR|—/.test(l.text)), `${tag}: the legs and totals follow the currency (${s.total} | ${s.legs[1] && s.legs[1].text})`);
    return finish();
  }

  if (CASE === 'origin') {
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    const n0 = st.legs.length;
    let s = await state();
    const firstLeg = s.legs[0].text;
    await click('#tabs button[data-tab="value"]');
    await waitFor(`(() => typeof loaded !== 'undefined' && loaded.value && [...document.getElementById('valueOrigin').options].some((o) => o.value === 'GB'))()`, 20000);
    await evaluate(`(() => { const c = document.getElementById('valueOrigin'); c.value = 'GB'; c.dispatchEvent(new Event('change')); return c.value; })()`);
    await sleep(1500);
    await click('#tabs button[data-tab="trip"]');
    await waitFor(`(() => { const l = document.querySelector('#tripBook .tbleg'); return l && /🇬🇧/.test(l.textContent) && !/…/.test(l.textContent); })()`, 9000);
    s = await state();
    ok(st.legs.slice(n0).some((q) => /origin=GB/.test(q)), `${tag}: a new From asks for the legs from there (${st.legs.slice(n0)})`);
    ok(/🇬🇧/.test(s.legs[0].text) && s.legs[0].text !== firstLeg && legsInOrder(s), `${tag}: the home legs now start in the UK (${s.legs[0].text})`);
    const best = await pageOrder('best');
    ok(JSON.stringify(s.rows) === JSON.stringify(best), `${tag}: reordered for the new From (${s.rows})`);
    return finish();
  }

  if (CASE === 'one') {
    await seed(trip(['TH']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    const s = await state();
    ok(!s.sortRow && s.handles === 0, `${tag}: one country: no switch, no handle (${s.sortRow}, ${s.handles})`);
    ok(s.legs.length === 2 && s.legs[0].from === '' && s.legs[0].to === 'TH' && s.legs[1].from === 'TH' && s.legs[1].to === '' && /flying/.test(s.total || ''),
       `${tag}: home -> Thailand -> home and the totals (${JSON.stringify(s.legs.map((l) => l.text))} | ${s.total})`);
    return finish();
  }

  if (CASE === 'empty') {
    await seed(trip([]));
    await nav(BASE + '/?tab=trip', 2500);
    const s = await evaluate(`(() => { const b = document.getElementById('tripBar'); return { hint: (b.querySelector('.triphint') || {}).textContent,
      btns: [...b.querySelectorAll('.tripstart button')].map((x) => x.id), extra: b.querySelectorAll('.tbleg, .tripsort, .tbtotal, .tbdrag').length }; })()`);
    ok(s && /^🧳 Your trip is empty\. Find a country and hit “Add to my trip”/.test(s.hint || '') && JSON.stringify(s.btns) === '["tripGoPicks","tripGoGuide"]' && s.extra === 0,
       `${tag}: an empty trip shows today's empty state (${JSON.stringify(s)})`);
    // (world.geojson loads on every landing, empty trip or not: init)
    ok(st.legs.length === 0 && st.world <= 1, `${tag}: and asks for no legs (${st.legs.length}; map ${st.world}, as every landing)`);
    return finish();
  }

  if (CASE === 'big') {
    const isos = ['TH', 'VN', 'KH', 'LA', 'MY', 'SG', 'ID', 'PH', 'JP', 'KR', 'TW', 'NP', 'LK'];
    await seed(trip(isos));
    await nav(BASE + '/?tab=trip', 0);
    await evaluate(`(() => { window.__long = 0; new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long = Math.max(window.__long, e.duration); }).observe({ type: 'longtask', buffered: true }); return 1; })()`);
    await waitFor(filled, 15000);
    const s = await state();
    ok(s.rows.length === 13 && new Set(s.rows).size === 13 && isos.every((i) => s.rows.includes(i)), `${tag}: 13 countries, every one still listed (${s.rows})`);
    ok(s.legs.length === 14 && legsInOrder(s), `${tag}: 14 legs in order`);
    const q = st.legs[0] ? new URLSearchParams(st.legs[0]).get('isos').split(',') : [];
    ok(st.legs.length >= 1 && q.length === 12, `${tag}: the legs request names 12 countries (${q})`);
    const best = await pageOrder('best');
    ok(JSON.stringify(s.rows) === JSON.stringify(best), `${tag}: in the Best overall order`);
    const t = await evaluate(`(() => { const t0 = performance.now(); for (const md of ['best', 'cheap', 'quick']) tripBestOrder(_tripM.m, md); return performance.now() - t0; })()`);
    ok(t < 50, `${tag}: ordering 13 stops in all three modes takes ${Math.round(t)} ms`);
    return finish();
  }

  if (CASE === 'real') {
    // /api/trip-legs through to the local server (recorded fares only)
    await seed(trip(['KH', 'TH', 'VN', 'GB']));
    await nav(BASE + '/?tab=trip', 0);
    const f = await waitFor(filled, 12000);
    const s = await state();
    const r = await evaluate(`fetch('/api/trip-legs?origin=US&isos=GB,KH,TH,VN').then(async (x) => ({ status: x.status, cc: x.headers.get('cache-control'), robots: x.headers.get('x-robots-tag'), body: await x.json() }))`);
    ok(f === true && legsInOrder(s), `${tag}: the legs fill in from the server's answer (${JSON.stringify(s.legs.map((l) => l.text))})`);
    ok(r && r.status === 200 && r.cc === 'no-store' && /noindex/.test(r.robots || '') && r.body && r.body.legs && r.body.fit,
       `${tag}: the server answers 200, no-store, noindex (${r && r.status}, ${r && r.cc}, fit ${JSON.stringify(r && r.body && r.body.fit)})`);
    return finish();
  }

  if (CASE === 'shots') {
    // the Trip card in Best overall, then after a drag (Your order); TR_SCHEME=light|dark, TR_PREFIX names the PNGs
    await seed(trip(['KH', 'TH', 'VN']));
    if (process.env.TR_SCHEME) await ctx.scheme(process.env.TR_SCHEME === 'dark');
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await sleep(800);
    const pre = (process.env.TR_PREFIX || 'trip') + '_' + W;
    await evaluate(`(() => { document.querySelector('#tab-trip .cardwide').scrollIntoView({ block: 'start', behavior: 'instant' }); return 1; })()`);
    await sleep(300);
    ok(!!(await ctx.shot(pre + '_best')), `${tag}: shot ${pre}_best`);
    let s = await state();
    await drag(s.rows[2], s.rows[0]);
    await evaluate(`(() => { document.querySelector('#tab-trip .cardwide').scrollIntoView({ block: 'start', behavior: 'instant' }); return 1; })()`);
    await sleep(300);
    s = await state();
    ok(s.mine && !!(await ctx.shot(pre + '_mine')), `${tag}: shot ${pre}_mine (${s.rows})`);
    return finish();
  }

  if (CASE === 'cls') {
    const n = +process.env.TR_N || 0, runs = +process.env.TR_RUNS || 2;
    const all = ['TH', 'VN', 'KH', 'JP', 'PT', 'MA', 'MX', 'PE'].slice(0, n);
    await seed(trip(all, { fx_tripmonth: '' }));
    // TR_DIAG=1: the trip card's height and its parts, every frame it changes (first 6 s)
    if (process.env.TR_DIAG) await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__hist = [];
      (function tick() { const b = document.getElementById('tripBar'); if (b) { const h = Math.round(b.getBoundingClientRect().height * 10) / 10;
        const l = window.__hist[window.__hist.length - 1];
        if (!l || l.h !== h) window.__hist.push({ t: Math.round(performance.now()), h, parts: [...b.querySelectorAll('.triphead, .tripsort, .tbrow, .tbleg, .tbtotal, .affnote')]
          .map((e) => e.className.split(' ').slice(0, 2).join('.') + ':' + Math.round(e.getBoundingClientRect().height)).join(' ') }); }
        if (performance.now() < 6000) requestAnimationFrame(tick); })();` });
    // cold: no HTTP cache, and the seed applied afresh on every load
    await send('Network.enable'); await send('Network.setCacheDisabled', { cacheDisabled: true });
    if (process.env.TR_NET) {
      const [lat, kbps] = process.env.TR_NET.split(',').map(Number);
      await send('Network.emulateNetworkConditions', { offline: false, latency: lat, downloadThroughput: kbps * 1000 / 8, uploadThroughput: kbps * 1000 / 8 });
    }
    const vals = [];
    for (let i = 0; i < runs; i++) {
      await nav(BASE + '/?tab=trip', +process.env.TR_SETTLE || 9000);
      const r = await evaluate(`(() => ({ cls: +window.__cls.toFixed(5), shifts: window.__shifts, legs: document.querySelectorAll('#tripBook .tbleg').length,
        filled: [...document.querySelectorAll('#tripBook .tbleg')].filter((l) => !/…/.test(l.textContent)).length,
        rows: [...document.querySelectorAll('#tripBook .tbrow[data-iso]')].map((r) => r.dataset.iso) }))()`);
      vals.push(r.cls);
      console.log('  run ' + i + ' ' + JSON.stringify(r));
      if (process.env.TR_DIAG) console.log('  hist ' + JSON.stringify(await evaluate('window.__hist')));
      if (!process.env.TR_BASELINE && n) ok(r.legs === n + 1 && r.filled === n + 1, `${tag}: n=${n} run ${i}: ${r.filled}/${n + 1} legs filled`);
      await evaluate(`(() => { try { sessionStorage.clear(); localStorage.clear(); } catch (e) {} return 1; })()`);
      await nav('about:blank', 200);
    }
    console.log(`CLS n=${n} net=${process.env.TR_NET || 'fast'} ${JSON.stringify(vals)} max ${Math.max(...vals)}`);
    return finish();
  }
  console.log('unknown case ' + CASE);
  finish();
};

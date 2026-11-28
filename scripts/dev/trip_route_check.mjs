// trip_route_check.mjs — the Trip tab's route (round 16): the order switch, drag/keyboard reordering, the
// legs between rows, the totals, share links, late or failing legs, context changes, and cold layout shift.
//   TR_BASE=http://127.0.0.1:11710 TR_CASE=modes TR_W=390 node cdp.mjs ./trip_route_check.mjs
// Env:
//   TR_BASE   the local server (never production)
//   TR_CASE   modes | drag | keys | share | fail | late | context | origin | one | empty | big | real | shots | cls
//             | globe | turn | motion   (the route's globe, Task 6)
//   TR_W      viewport width (below 700: a phone, touch + a phone UA)
//   TR_FAIL   net | 503   (fail: how /api/trip-legs fails)
//   TR_N      cls: countries on the trip (0, 1, 3, 8); TR_NET=latency,kbps a slow link (cache off); TR_RUNS loads
//   TR_BASELINE=1  cls on a tree without the route (the base): only the layout shift is reported
//   TR_PAR    scripts/parity/fixtures: non-USD rates (/api/rates?base=EUR, GBP) answered from the repo's recordings
//   TR_SHOTN  shots: countries on the trip (3: TH VN KH, the default; 8: eight across three continents); TR_SHOTS the
//             folder for the PNGs (default shots/ beside cdp.mjs)
//   TR_ISOS   shots / cls / rowfit: the trip itself (comma list), over TR_SHOTN / TR_N; TR_MONTH its month (fx_tripmonth:
//             '' unset = the picks month, 0 flexible, 1-12)
//   TR_LS     shots: more localStorage as JSON (a reader's From and currency)
//   rowfit    a trip of long names and ⚠️ countries with a month set: every name's ⚠️ beside it on its line, and
//             under 1200px every row one height
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
  const st = await intercept(ctx, { legs: legsMode, legsDelay: CASE === 'late' ? 4000 : CASE === 'motion' && !process.env.TR_RM ? 1500 : 0 });
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
  // The route's globe as drawn: its box, the canvas, the model it drew (_tg) and where each place lands.
  const globe = () => evaluate(`(() => {
    const el = document.querySelector('#tripBar .tripglobe'), book = document.getElementById('tripBook');
    if (!el || typeof _tg === 'undefined') return null;
    const cv = el.querySelector('canvas'), b = el.getBoundingClientRect(), bb = book ? book.getBoundingClientRect() : null;
    const view = tgView(el.clientWidth, el.clientHeight), r = _tg.route;
    const at1 = (X, Y) => { if (!cv || !cv.width || !el.clientWidth) return null; const k = cv.width / el.clientWidth,
      d = cv.getContext('2d').getImageData(Math.round(X * k), Math.round(Y * k), 1, 1).data; return [d[0], d[1], d[2], d[3]]; };
    // each marker as last placed (a stop may sit off its place, tied to it by a line): a pixel inside its disc
    const marks = (_tg.marks || []).map((m) => ({ home: !!m.home, label: m.label || '', x: m.x, y: m.y, rad: m.rad, half: m.half,
      off: Math.round(Math.hypot(m.x - m.x0, m.y - m.y0)), px: m.home ? at1(m.x - 6, m.y + 1) : at1(m.x, m.y - 5.3) }));
    let white = 0, green = 0, n = 0;
    if (cv && cv.width) { const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data; n = d.length / 4;
      for (let i = 0; i < d.length; i += 4) { if (d[i] > 245 && d[i + 1] > 245 && d[i + 2] > 245) white++; if (d[i] < 40 && d[i + 1] > 100 && d[i + 1] < 150 && d[i + 2] < 70) green++; } }
    const rows = [...document.querySelectorAll('#tripBook .tbrow[data-iso]')].map((x) => x.dataset.iso);
    const C = countryCentroids(), at = (iso) => C[iso] || C[GUIDE_PARENT[iso]] || null;
    return { drawn: el.getAttribute('data-drawn'), w: Math.round(b.width), h: Math.round(b.height), cw: cv && cv.width, ch: cv && cv.height,
      dpr: devicePixelRatio, top: Math.round(b.top), left: Math.round(b.left), bottom: Math.round(b.bottom),
      bookTop: bb && Math.round(bb.top), bookRight: bb && Math.round(bb.right), bookLeft: bb && Math.round(bb.left),
      aria: el.getAttribute('aria-label'), role: el.getAttribute('role'), touch: getComputedStyle(el).touchAction,
      ctr: _tg.ctr, t: _tg.t, done: _tg.drawn, frames: _tg.frames, raf: _tg.raf, white, green, n, rows,
      nums: [...document.querySelectorAll('#tripBook .tbrow[data-iso] .tbno')].map((x) => x.textContent),
      legs: r ? r.legs.map((L) => ({ a: L.a, b: L.b, dashed: L.dashed })) : null,
      stops: r ? r.stops.map((s) => ({ ll: s.ll, label: s.label, back: !globeProject(s.ll[0], s.ll[1], view)[2] })) : null, marks,
      home: _tg.home, want: { home: at(originIso()), rows: rows.map(at) },
      finite: !!r && r.legs.every((L) => L.a.concat(L.b).every(Number.isFinite)) && r.stops.every((s) => s.ll.every(Number.isFinite)) };
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
  // The totals line is the leg lines added up as shown (each leg rounded as its line shows it).
  const amt = (t) => { const m = /([A-Z]{3}) ([\d,]+)/.exec(t || ''); return m ? [m[1], +m[2].replace(/,/g, '')] : null; };
  const sums = (s) => { const L = s.legs.map((l) => (/✈️ —/.test(l.text) ? ['', 0] : amt(l.text))), T = amt(s.total);
    return { ok: !!T && L.every((x) => x && (x[0] === '' || x[0] === T[0])) && L.reduce((a, x) => a + x[1], 0) === T[1],
             legs: L.map((x) => x && x[1]), total: T && T[1] }; };
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
    const sm = sums(s);
    ok(sm.ok, `${tag}: the totals line is the leg lines added up (${sm.legs} = ${sm.total})`);
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
    const sm = sums(s);
    ok(sm.ok, `${tag}: the totals line is the leg lines added up (${sm.legs} = ${sm.total} | ${s.total})`);
    ok(r && r.status === 200 && r.cc === 'no-store' && /noindex/.test(r.robots || '') && r.body && r.body.legs && r.body.fit,
       `${tag}: the server answers 200, no-store, noindex (${r && r.status}, ${r && r.cc}, fit ${JSON.stringify(r && r.body && r.body.fit)})`);
    return finish();
  }

  if (CASE === 'shots') {
    // the Trip card in Best overall, then after a drag (Your order); TR_SCHEME=light|dark, TR_PREFIX names the PNGs
    const N8 = ['TH', 'VN', 'KH', 'JP', 'PT', 'MA', 'MX', 'PE'];
    // TR_LS: more localStorage (JSON), e.g. a UK reader in GBP: {"fx_origin":"GB","fx_homecur":"GBP"}
    const mo = Object.assign(process.env.TR_MONTH != null ? { fx_tripmonth: process.env.TR_MONTH } : {}, JSON.parse(process.env.TR_LS || '{}'));
    await seed(trip(process.env.TR_ISOS ? process.env.TR_ISOS.split(',') : +process.env.TR_SHOTN === 8 ? N8 : ['KH', 'TH', 'VN'], mo));
    if (process.env.TR_SCHEME) await ctx.scheme(process.env.TR_SCHEME === 'dark');
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await waitFor(`(() => { const g = document.querySelector('#tripBar .tripglobe'); return !g || (g.getAttribute('data-drawn') === 'route' && _tg.drawn); })()`, 6000);
    await sleep(800);
    const pre = (process.env.TR_PREFIX || 'trip') + '_' + W;
    const snap = async (name) => {
      if (!process.env.TR_SHOTS) return ctx.shot(name);
      const r = await send('Page.captureScreenshot', { format: 'png' }), f = process.env.TR_SHOTS + '/' + name + '.png';
      fs.mkdirSync(process.env.TR_SHOTS, { recursive: true }); fs.writeFileSync(f, Buffer.from(r.result.data, 'base64'));
      return f;
    };
    ctx.shot = snap;
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

  if (CASE === 'globe') {
    // The route's globe (Task 6): its box beside the list from 901px, above it under; home, the numbered stops and
    // an arc per leg in the list's order, dashed where the leg line says ≈; the rows carry the same numbers; a
    // reorder redraws the route and leaves the view where it was; the box is fixed (no layout shift as it draws).
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await waitFor(`(() => { const g = document.querySelector('#tripBar .tripglobe'); return g && g.getAttribute('data-drawn') === 'route' && _tg.drawn; })()`, 6000);
    let g = await globe(), s = await state();
    if (!ok(g && g.drawn === 'route' && g.done, `${tag}: the globe drew the route (${g && g.drawn}, drawn-in ${g && g.done}, ${g && g.frames} frames)`)) return finish();
    const wantH = W > 900 ? 280 : W > 560 ? 300 : 260;
    ok(g.h === wantH && g.cw === Math.round(g.w * Math.min(g.dpr, 2)) && g.ch === Math.round(g.h * Math.min(g.dpr, 2)),
       `${tag}: a ${g.w}x${g.h} box (want height ${wantH}), canvas ${g.cw}x${g.ch} at ${g.dpr}x (DPR capped at 2)`);
    ok(W > 900 ? g.left >= g.bookRight && Math.abs(g.top - g.bookTop) <= 1 : g.bottom <= g.bookTop,
       `${tag}: ${W > 900 ? 'beside the list' : 'above the list'} (globe ${g.left},${g.top}-${g.bottom}; list ${g.bookLeft}-${g.bookRight}, top ${g.bookTop})`);
    ok(g.role === 'img' && /from the US to /.test(g.aria || '') && g.touch === 'pan-y', `${tag}: named for screen readers, pan-y (${g.aria}; ${g.touch})`);
    const eq = (p, q) => !!p && !!q && Math.abs(p[0] - q[0]) < 1e-9 && Math.abs(p[1] - q[1]) < 1e-9;
    const seqWant = [g.want.home].concat(g.want.rows, [g.want.home]);
    ok(g.legs.length === 4 && g.legs.every((L, k) => eq(L.a, seqWant[k]) && eq(L.b, seqWant[k + 1])) && g.finite,
       `${tag}: one arc per leg, home -> ${s.rows} -> home, in the list's order (${g.legs.length})`);
    const est = s.legs.map((l) => /≈/.test(l.text));
    ok(JSON.stringify(g.legs.map((L) => L.dashed)) === JSON.stringify(est), `${tag}: dashed exactly where the leg line says ≈ (${g.legs.map((L) => L.dashed)} vs ${est})`);
    ok(JSON.stringify(g.stops.map((x) => x.label)) === '["1","2","3"]' && g.stops.every((x, k) => eq(x.ll, g.want.rows[k]))
       && JSON.stringify(g.nums) === '["1","2","3"]', `${tag}: numbered stops 1-3 at the rows' countries, the rows numbered the same (${g.nums})`);
    const isGreen = (p) => Array.isArray(p) && p[0] < 40 && p[1] > 100 && p[1] < 150 && p[2] < 70;
    const front = g.stops.filter((x) => !x.back).map((x) => x.label).sort();
    const sep = g.marks.every((a, i) => g.marks.every((b, j) => j <= i || Math.hypot(a.x - b.x, a.y - b.y) >= a.rad + b.rad - 0.5));
    ok(JSON.stringify(g.marks.filter((m) => !m.home).map((m) => m.label).sort()) === JSON.stringify(front) && g.marks.some((m) => m.home)
       && g.marks.every((m) => isGreen(m.px)) && sep,
       `${tag}: a marker per stop on this side of the globe (${front}) and home, drawn, none on another (${JSON.stringify(g.marks.map((m) => [m.label || 'home', m.off, m.px]))})`);
    ok(g.white > 200 && g.green > 200, `${tag}: arcs (${g.white} white px) and the trip's countries and markers (${g.green} green px)`);
    const ctr0 = JSON.stringify(g.ctr), cls0 = await evaluate('window.__cls');
    await click('#tripBook .tripsort [data-ts="cheap"]');
    await sleep(300);
    g = await globe(); s = await state();
    ok(JSON.stringify(s.rows) === '["TH","VN","KH"]' && g.stops.every((x, k) => eq(x.ll, g.want.rows[k])) && g.legs.every((L, k) => eq(L.a, [g.want.home].concat(g.want.rows)[k])),
       `${tag}: Cheapest reorders the arcs and numbers with the rows (${s.rows})`);
    ok(JSON.stringify(g.ctr) === ctr0, `${tag}: the view stays where it was (${ctr0})`);
    const cls1 = await evaluate('window.__cls');
    ok(cls1 === cls0, `${tag}: no layout shift from the reorder's redraw (${cls0} -> ${cls1})`);
    ok(s.sw <= s.cw, `${tag}: no sideways scroll (${s.sw} <= ${s.cw})`);
    return finish();
  }

  if (CASE === 'turn') {
    // Turning it: a sideways drag turns it (the longitude, kept within -180..180), a mouse's up/down tilts it once
    // the drag ends; on a phone a vertical swipe over it scrolls the page and turns nothing.
    await seed(trip(['KH', 'TH', 'VN']));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await waitFor(`(() => _tg.drawn && document.querySelector('#tripBar .tripglobe').getAttribute('data-drawn') === 'route')()`, 6000);
    await box('#tripBar .tripglobe');
    await sleep(300);
    const at = await evaluate(`(() => { const b = document.querySelector('#tripBar .tripglobe').getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2, sy: scrollY }; })()`);
    let g0 = await globe();
    if (!PHONE) {
      const mv = (type, x, y, btn = 'left', buttons = 1) => send('Input.dispatchMouseEvent', { type, x, y, button: btn, buttons, clickCount: 1 });
      await mv('mouseMoved', at.x, at.y, 'none', 0);
      await mv('mousePressed', at.x, at.y);
      for (let k = 1; k <= 8; k++) { await mv('mouseMoved', at.x - 10 * k, at.y - 5 * k); await sleep(30); }
      await sleep(100);
      const mid = await globe();
      await mv('mouseReleased', at.x - 80, at.y - 40);
      await sleep(200);
      const g1 = await globe(), sy1 = await evaluate('scrollY');
      const r = await evaluate(`tgView(document.querySelector('#tripBar .tripglobe').clientWidth, document.querySelector('#tripBar .tripglobe').clientHeight).r`);
      const dlon = ((g1.ctr.lon - g0.ctr.lon + 540) % 360) - 180, wantD = 80 / r * 180 / Math.PI;
      ok(Math.abs(dlon - wantD) < 0.5 && g1.ctr.lon >= -180 && g1.ctr.lon < 180, `${tag}: an 80px drag to the left turns it ${dlon.toFixed(1)} degrees east (want ${wantD.toFixed(1)}), longitude ${g1.ctr.lon.toFixed(1)}`);
      ok(mid.ctr.lat === g0.ctr.lat && g1.ctr.lat < g0.ctr.lat - 5, `${tag}: a drag upward tilts it south, once dropped (${mid.ctr.lat} during, ${g1.ctr.lat.toFixed(1)} after)`);
      ok(sy1 === at.sy && JSON.stringify(g1.rows) === JSON.stringify(g0.rows) && g1.drawn === 'route', `${tag}: the page didn't scroll, the list didn't change`);
      // keep turning: still within -180..180
      for (let i = 0; i < 3; i++) {
        await mv('mouseMoved', at.x + 120, at.y, 'none', 0); await mv('mousePressed', at.x + 120, at.y);
        for (let k = 1; k <= 6; k++) { await mv('mouseMoved', at.x + 120 - 40 * k, at.y); await sleep(20); }
        await mv('mouseReleased', at.x - 120, at.y); await sleep(100);
      }
      const g2 = await globe();
      ok(g2.ctr.lon >= -180 && g2.ctr.lon < 180, `${tag}: after turning on, the longitude is still within -180..180 (${g2.ctr.lon.toFixed(1)})`);
    } else {
      const touch = async (pts) => {
        await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: pts[0][0], y: pts[0][1] }] });
        for (const p of pts.slice(1)) { await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: p[0], y: p[1] }] }); await sleep(16); }
        await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        await sleep(500);
      };
      const vs = []; for (let k = 0; k <= 12; k++) vs.push([at.x, at.y + 60 - 10 * k]);
      await touch(vs);
      const g1 = await globe(), sy1 = await evaluate('scrollY');
      ok(sy1 > at.sy + 20, `${tag}: a vertical swipe over the globe scrolls the page (${at.sy} -> ${sy1})`);
      ok(JSON.stringify(g1.ctr) === JSON.stringify(g0.ctr), `${tag}: and turns nothing (${JSON.stringify(g1.ctr)})`);
      const at2 = await evaluate(`(() => { const b = document.querySelector('#tripBar .tripglobe').getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2, sy: scrollY }; })()`);
      const hs = []; for (let k = 0; k <= 10; k++) hs.push([at2.x + 60 - 12 * k, at2.y]);
      await touch(hs);
      const g2 = await globe(), sy2 = await evaluate('scrollY');
      ok(Math.abs(g2.ctr.lon - g1.ctr.lon) > 5 && g2.ctr.lat === g1.ctr.lat && Math.abs(sy2 - at2.sy) <= 1,
         `${tag}: a sideways swipe turns it (${g1.ctr.lon.toFixed(1)} -> ${g2.ctr.lon.toFixed(1)}), the page stays (${at2.sy} -> ${sy2})`);
    }
    return finish();
  }

  if (CASE === 'motion') {
    // motion_and_touch: TR_RM=1 (prefers-reduced-motion): the route is drawn whole at once, no animation frame
    // runs for it, and none at all while the page sits; else the draw-in waits while the page is hidden, stops
    // when it is hidden or the Trip tab goes offscreen, resumes, and runs once.
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__raf = 0; const __r = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (f) => { window.__raf++; return __r(f); };` });
    if (process.env.TR_RM) await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    await seed(trip(['KH', 'TH', 'VN']));
    const hide = (on) => evaluate(`(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => ${on} });
      document.dispatchEvent(new Event('visibilitychange')); return document.hidden; })()`);
    if (process.env.TR_RM) {
      await nav(BASE + '/?tab=trip', 0);
      await waitFor(filled);
      await waitFor(`(() => document.querySelector('#tripBar .tripglobe').getAttribute('data-drawn') === 'route')()`, 6000);
      const g = await globe();
      ok(g.drawn === 'route' && g.done && g.frames === 0 && g.t === 0 && g.white > 200,
         `${tag}: reduced motion: the route drawn whole at once, no draw-in frames (${g.frames}), arcs there (${g.white} white px)`);
      const r0 = await evaluate('window.__raf');
      await sleep(2000);
      const r1 = await evaluate('window.__raf'), g2 = await globe();
      ok(r1 === r0 && g2.frames === 0, `${tag}: nothing asks for an animation frame while the page sits (${r0} -> ${r1} in 2 s)`);
      return finish();
    }
    // the page hidden before the route is in: the draw-in waits
    await nav(BASE + '/?tab=trip', 0);
    await hide(true);
    await waitFor(filled);
    await waitFor(`(() => !!_tg.route)()`, 6000);
    await sleep(400);
    let g = await globe();
    ok(g.frames === 0 && !g.done && !g.raf && g.drawn === 'route', `${tag}: hidden: the route is in but nothing animates (${g.frames} frames)`);
    await hide(false);
    await waitFor(`(() => _tg.frames > 3)()`, 3000);
    await hide(true);
    await sleep(60);
    const f1 = (await globe()).frames;
    await sleep(600);
    g = await globe();
    ok(g.frames === f1 && !g.raf && !g.done && g.t > 0 && g.t < 1, `${tag}: hidden mid-way: it stops (${f1} -> ${g.frames} frames, at ${g.t.toFixed(2)})`);
    await hide(false);
    await waitFor(`(() => _tg.frames > ${f1} + 2)()`, 3000);
    // offscreen: another tab
    await evaluate(`(() => { activateTab('value', true); return 1; })()`);
    await sleep(300);
    const f2 = (await globe()).frames;
    await sleep(600);
    g = await globe();
    ok(g.frames === f2 && !g.raf && !g.done, `${tag}: on another tab it stops (${f2} -> ${g.frames} frames, at ${g.t.toFixed(2)})`);
    await evaluate(`(() => { activateTab('trip', true); return 1; })()`);
    await waitFor(`(() => _tg.drawn)()`, 4000);
    g = await globe();
    ok(g.done && g.t === 1 && g.drawn === 'route' && g.frames > f2, `${tag}: back on the Trip tab it finishes (${g.frames} frames)`);
    const f3 = g.frames, rows3 = JSON.stringify(g.rows);
    await click('#tripBook .tripsort [data-ts="quick"]');
    await sleep(400);
    g = await globe();
    ok(g.frames === f3 && g.t === 1 && g.done && g.drawn === 'route', `${tag}: a reorder after that redraws at once, no second draw-in (${rows3} -> ${JSON.stringify(g.rows)}, ${g.frames} frames)`);
    return finish();
  }

  if (CASE === 'rowfit') {
    // Long names and ⚠️ (Level 3) countries on a phone, a month set (the weather pill and the month's fare share the
    // first line): each name gives way to its ellipsis, its ⚠️ stays beside it, every row keeps one height.
    const isos = (process.env.TR_ISOS || 'BA,AE,DO,PG').split(',');
    await seed(trip(isos, { fx_tripmonth: process.env.TR_MONTH || '3' }));
    await nav(BASE + '/?tab=trip', 0);
    await waitFor(filled);
    await sleep(1500);
    const r = await evaluate(`(() => [...document.querySelectorAll('#tripBook .tbrow[data-iso]')].map((row) => {
      const n = row.querySelector('.tbdest'), w = row.querySelector('.tbn .hzmark'), h = row.querySelector('.tbdrag'), b = row.getBoundingClientRect();
      const nb = n.getBoundingClientRect(), wb = w && w.getBoundingClientRect(), hb = h && h.getBoundingClientRect();
      return { iso: row.dataset.iso, h: Math.round(b.height), name: Math.round(nb.width), full: n.scrollWidth, cut: n.scrollWidth > n.clientWidth + 1,
        warn: !!w, warnLine: w ? Math.abs((wb.top + wb.bottom) / 2 - (nb.top + nb.bottom) / 2) < 6 : null, warnRight: w ? Math.round(wb.left - nb.right) : null,
        inside: w ? wb.right <= row.querySelector('.tbn').getBoundingClientRect().right + 1 : null, handleLine: hb ? Math.abs((hb.top + hb.bottom) / 2 - (nb.top + nb.bottom) / 2) < 6 : null };
    }))()`);
    console.log('  rows ' + JSON.stringify(r));
    ok(Array.isArray(r) && r.length === isos.length, `${tag}: ${r && r.length} rows`);
    ok(r.every((x) => !x.warn || (x.warnLine && x.inside && x.warnRight >= 0 && x.warnRight < 8)),
       `${tag}: every ⚠️ beside its name, on its line (${JSON.stringify(r.map((x) => [x.iso, x.warnLine, x.warnRight]))})`);
    ok(r.every((x) => x.handleLine !== false), `${tag}: handle, number and name on one line`);
    // Under 1200px the links take a line of their own, so every row is one height; from 1200 they share the row's
    // line and a row with more of them may wrap (reported, not held).
    if (W < 1200) ok(new Set(r.map((x) => x.h)).size === 1, `${tag}: every row one height (${r.map((x) => x.h)})`);
    else console.log(`  rows' heights ${r.map((x) => x.h)} (one line shared with the links from 1200px)`);
    const s = await state();
    ok(s.sw <= s.cw, `${tag}: no sideways scroll (${s.sw} <= ${s.cw})`);
    return finish();
  }

  if (CASE === 'cls') {
    const all = process.env.TR_ISOS ? process.env.TR_ISOS.split(',') : ['TH', 'VN', 'KH', 'JP', 'PT', 'MA', 'MX', 'PE'].slice(0, +process.env.TR_N || 0);
    const n = all.length, runs = +process.env.TR_RUNS || 2;
    await seed(trip(all, { fx_tripmonth: process.env.TR_MONTH != null ? process.env.TR_MONTH : '' }));
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

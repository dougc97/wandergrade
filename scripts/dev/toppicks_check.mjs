// toppicks_check.mjs — the Top Picks fixes of the Nov 2026 review (r5) in a real browser.
//   T_BASE=http://127.0.0.1:8010 T_CASE=hold CDP_TIMEOUT=55 node cdp.mjs ./toppicks_check.mjs
// T_CASE (one per run, each well under the 60 s cap):
//   helpme  #2  Help me choose -> Go at 390x664: the page scrolls to the ranking and stays there,
//               focus lands on row #1's link (it used to snap back up to the button)
//   hold    #5  ?vmn=12&vo=US with popularity, fares and fare curves answering late: the skeleton
//               gives way to ONE order of rows (it used to reshuffle twice)
//   month   #14 the month picker on a touch phone: read-only, no keyboard, keeps its value, opens on
//               this month inside the screen, no group tip, a tap picks; desktop still searchable
//   fares   #25 row fare strips: none fetched on a phone load, the gems' only once the fold opens,
//               the rest when the screen widens past 640px
//   want    #18 Been-to "★ My want-to-go": the rows, the note's count, vb=want, the empty state
//   trip    #29 the Trip tab's AI bar hidden while the trip is empty, shown with a trip
// T_CACHE  a directory of recorded production API answers (files sha1(pathname+search).json holding
//          {url,status,ct,body base64}); hold and fares replay /api/flight*, /api/popularity from it.
//          Without it they use what the local server answers (no fares locally: weaker checks).
// T_RATES  a saved /api/rates answer to serve instead of the server's (a restarted local server
//          can be rate-limited upstream with 429s).
import fs from 'node:fs'; import crypto from 'node:crypto';
const BASE = process.env.T_BASE || 'http://127.0.0.1:8010', CASE = process.env.T_CASE || 'hold';
const CACHE = process.env.T_CACHE || '';
const RATES = process.env.T_RATES ? fs.readFileSync(process.env.T_RATES).toString('base64') : null;
const key = (u) => crypto.createHash('sha1').update(u).digest('hex');
const ok = (c, m) => console.log((c ? '  PASS  ' : '  FAIL  ') + m);

export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  const delays = { '/api/popularity': 300, '/api/flights': 400, '/api/flight-value': 500 };
  const fm = [];   // /api/flight-months isos asked for
  const pats = [];
  if (RATES) pats.push({ urlPattern: '*/api/rates', requestStage: 'Request' });
  if (CACHE) pats.push({ urlPattern: '*/api/flight*', requestStage: 'Request' }, { urlPattern: '*/api/popularity*', requestStage: 'Request' });
  else pats.push({ urlPattern: '*/api/flight-months*', requestStage: 'Request' });
  await send('Fetch.enable', { patterns: pats });
  on(async (d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId, u = new URL(d.params.request.url);
    const json = (b64, status = 200, ct = 'application/json') => send('Fetch.fulfillRequest', { requestId: id, responseCode: status, responseHeaders: [{ name: 'Content-Type', value: ct }], body: b64 });
    if (u.pathname === '/api/rates' && RATES) return json(RATES);
    if (u.pathname === '/api/flight-months') fm.push(u.searchParams.get('iso'));
    if (!CACHE) return send('Fetch.continueRequest', { requestId: id });
    if (CASE === 'hold' && delays[u.pathname]) await sleep(delays[u.pathname]);
    const f = CACHE + '/' + key(u.pathname + u.search) + '.json';
    if (fs.existsSync(f)) { const c = JSON.parse(fs.readFileSync(f, 'utf8')); return json(c.body, c.status, c.ct); }
    if (u.pathname === '/api/flight-months') return json(Buffer.from('{"months":{}}').toString('base64'));
    return send('Fetch.continueRequest', { requestId: id });
  });
  const tap = async (expr, touch) => {
    const c = await evaluate(`(function(){ const e = ${expr}; const b = e.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()`);
    if (touch) return send('Input.synthesizeTapGesture', { x: c[0], y: c[1], gestureSourceType: 'touch' });
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: c[0], y: c[1], button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: c[0], y: c[1], button: 'left', clickCount: 1 });
  };

  if (CASE === 'helpme') {
    await setSize(390, 664, true);
    await nav(BASE + '/?cb=' + Date.now(), 5000);
    await evaluate(`(function(){ window.scrollTo(0, 45); return 1; })()`);
    await sleep(300);
    await tap(`document.getElementById('guideMeBtn')`, true);
    await sleep(600);
    await evaluate(`(function(){ window.__ys = []; const t0 = performance.now(); const f = () => { window.__ys.push(Math.round(scrollY)); if (performance.now() - t0 < 1500) requestAnimationFrame(f); }; requestAnimationFrame(f); return 1; })()`);
    await tap(`document.getElementById('gqGo')`, true);
    await sleep(1800);
    const r = await evaluate(`(function(){ const ys = window.__ys; let drops = 0; for (let i = 1; i < ys.length; i++) if (ys[i] < ys[i - 1] - 20) drops++;
      const a = document.activeElement, row = document.querySelector('#topCards tbody tr'), b = row.getBoundingClientRect();
      return { max: Math.max(...ys), final: ys[ys.length - 1], drops, active: a.className, first: row.querySelector('a.destlink') === a, row1: [Math.round(b.top), Math.round(b.bottom)], vh: innerHeight }; })()`);
    ok(r.drops === 0 && r.final >= r.max - 5, 'the page scrolls to the ranking and stays (max ' + r.max + ', final ' + r.final + ')');
    ok(r.first, 'focus is on row #1\'s link (' + r.active + ')');
    ok(r.row1[0] >= 0 && r.row1[1] <= r.vh, 'row #1 is on screen ' + JSON.stringify(r.row1));
  }

  if (CASE === 'hold') {
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `(function(){ window.__orders = []; let last = ''; const t0 = performance.now();
      const look = () => { const h = document.getElementById('topCards'); if (h) { const skel = !!h.querySelector('table.skeleton:not([hidden])');
        const k = skel ? 'SKELETON' : [...h.querySelectorAll('tbody tr[data-iso]')].map((r) => r.dataset.iso).join(' ');
        if (k !== last) { window.__orders.push([Math.round(performance.now() - t0), k]); last = k; } }
        if (performance.now() - t0 < 7000) setTimeout(look, 25); };
      document.addEventListener('DOMContentLoaded', look); })();` });
    await setSize(390, 664, true);
    await nav(BASE + '/?vmn=12&vo=US&cb=' + Date.now(), 6000);
    const o = await evaluate(`(function(){ return window.__orders; })()`);
    o.forEach((x) => console.log('    ' + String(x[0]).padStart(5) + 'ms  ' + x[1]));
    const orders = o.filter((x) => x[1] !== 'SKELETON' && x[1]);
    ok(o.length && o[0][1] === 'SKELETON', 'the skeleton shows first');
    ok(orders.length === 1, 'one order of rows, no reshuffle (' + orders.length + ')' + (CACHE ? '' : ' [no T_CACHE: fares off]'));
  }

  if (CASE === 'month') {
    for (const touch of [true, false]) {
      await setSize(390, 664, touch);
      await nav(BASE + '/?cb=' + Date.now(), 4000);
      const inp = `document.querySelector('#valueMonth').parentNode.querySelector('.combo-input')`;
      const st = `(function(){ const inp = ${inp}, list = inp.parentNode.querySelector('.combo-list'), lb = list.getBoundingClientRect();
        const vis = [...list.querySelectorAll('.combo-opt')].filter((li) => { const b = li.getBoundingClientRect(); return b.top >= lb.top - 1 && b.bottom <= lb.bottom + 1; }).map((li) => li.textContent);
        const tip = document.getElementById('wgtip');
        return { ro: inp.readOnly, im: inp.getAttribute('inputmode'), value: inp.value, open: !list.hidden, vis, bottom: Math.round(lb.bottom), vh: innerHeight, tip: tip.hidden ? null : tip.textContent, sel: document.getElementById('valueMonth').value, url: location.search }; })()`;
      await tap(inp, touch);
      await sleep(400);
      const a = await evaluate(st);
      const now = ['January','February','March','April','May','June','July','August','September','October','November','December'][new Date().getMonth()];
      if (touch) {
        ok(a.ro && a.im === 'none', 'touch: read-only, inputmode=none (no keyboard)');
        ok(a.value === 'Any time' && a.open, 'touch: the box keeps "Any time" and the list opens');
        ok(a.vis.includes(now) && a.bottom <= a.vh, 'touch: this month (' + now + ') in view, the list inside the screen (' + a.vis.join(',') + ')');
        ok(a.tip === null, 'touch: no group tip over Help me choose');
        await tap(`[...document.querySelectorAll('.combo-list:not([hidden]) .combo-opt')].find((li) => li.textContent === ${JSON.stringify(now)})`, true);
        await sleep(600);
        const b = await evaluate(st);
        ok(b.value === now && !b.open && /vmn=\d+/.test(b.url), 'touch: a tap picks the month (' + b.url + ')');
      } else {
        ok(!a.ro && a.value === '' && a.open, 'desktop: still a search box (cleared to type, list open)');
      }
    }
  }

  if (CASE === 'fares') {
    await setSize(390, 844, true);
    await nav(BASE + '/?cb=' + Date.now(), 6000);
    const atLoad = fm.length;
    await evaluate(`(function(){ document.getElementById('gemsBox').open = true; return 1; })()`);
    await sleep(1200);
    const afterGems = fm.length;
    await setSize(1280, 900, false);
    await sleep(1500);
    const filled = await evaluate(`(function(){ return [...document.querySelectorAll('#topCards .rowfares, #gemRows .rowfares')].filter((s) => s.firstChild).length; })()`);
    ok(atLoad === 0, 'phone load: no fare strips fetched (' + atLoad + ')');
    ok(afterGems === 0, 'phone, gems open: still none (strips hidden under 640px) (' + afterGems + ')');
    ok(fm.length >= 10, 'wider than 640px: the top 5 and the open gems fetched (' + fm.length + ', ' + filled + ' filled)');
    fm.length = 0;
    await nav(BASE + '/?cb=' + Date.now(), 6000);
    const desk = fm.length, rows = await evaluate(`(function(){ return [...document.querySelectorAll('#gemRows tr[data-iso]')].length; })()`);
    await evaluate(`(function(){ document.getElementById('gemsBox').open = true; return 1; })()`);
    await sleep(1200);
    ok(desk <= 8 && fm.length - desk >= Math.min(rows, 1), 'desktop: the closed gems fold waits for its opening (' + desk + ' at load, ' + (fm.length - desk) + ' on opening)');
  }

  if (CASE === 'want') {
    await setSize(1280, 900, false);
    await nav(BASE + '/?cb=' + Date.now(), 1500);
    await evaluate(`(function(){ localStorage.setItem('fx_wishlist', JSON.stringify(['JP','GB-SCT','SY','FO','TH','IS','PT','MX'])); localStorage.setItem('fx_visited', JSON.stringify(['TH'])); return 1; })()`);
    await nav(BASE + '/?vb=want&cb=' + Date.now(), 5000);
    const st = `(function(){ const n = document.getElementById('picksNote'), m = n.querySelector('.wantmiss');
      return { rows: [...document.querySelectorAll('#topCards tr[data-iso]')].map((r) => r.dataset.iso), note: n.textContent, miss: m ? m.dataset.tip : '', tabbable: m ? m.tabIndex : null,
        sel: document.getElementById('beenFilter').value, saved: localStorage.getItem('wg_showvisited'), url: location.search, gems: document.getElementById('gemsBox').hidden,
        hint: (document.querySelector('#topCards .hint') || {}).textContent || '' }; })()`;
    const a = await evaluate(st);
    ok(a.sel === 'want' && a.saved === null, 'a link\'s vb=want opens the ★ list, not saved');
    ok(a.rows.length === 5 && a.rows.includes('TH') && a.rows.includes('GB') && !a.rows.includes('SY'), 'the rows are ★ countries (✓ TH in, Scotland as GB, no Level 4): ' + a.rows);
    ok(a.note.startsWith('★ Your want-to-go list') && /· 2 not ranked ⓘ/.test(a.note) && /Syria: Level 4/.test(a.miss) && a.tabbable === 0, 'the note counts the 2 it can\'t rank, reasons in a reachable tip');
    ok(a.gems && /vb=want/.test(a.url), 'no gems fold; the address bar keeps vb=want');
    await evaluate(`(function(){ localStorage.setItem('fx_wishlist', '[]'); const s = document.getElementById('beenFilter'); s.value = 'want'; s.dispatchEvent(new Event('change')); return 1; })()`);
    await nav(BASE + '/?cb=' + Date.now(), 4000);
    const b = await evaluate(st);
    ok(b.saved === 'want' && b.sel === 'want' && /empty/.test(b.hint), 'chosen in the select it is saved; an empty ★ list says so');
  }

  if (CASE === 'trip') {
    await setSize(390, 844, true);
    const st = `(function(){ return getComputedStyle(document.querySelector('#tab-trip .aibar')).display; })()`;
    await nav(BASE + '/?tab=trip&cb=' + Date.now(), 3500);
    const empty = await evaluate(st);
    await evaluate(`(function(){ localStorage.setItem('fx_trip', JSON.stringify(['PT'])); return 1; })()`);
    await nav(BASE + '/?tab=trip&cb=' + Date.now(), 3500);
    const one = await evaluate(st);
    await evaluate(`(function(){ document.querySelector('#tripBook .tbx').click(); return 1; })()`);
    await sleep(500);
    const gone = await evaluate(st);
    ok(empty === 'none' && one !== 'none' && gone === 'none', 'the AI bar: hidden empty (' + empty + '), shown with a trip (' + one + '), hidden again (' + gone + ')');
  }
  console.log('  errors: ' + errs.filter((e) => !/api\/rates/.test(e)).length);
};

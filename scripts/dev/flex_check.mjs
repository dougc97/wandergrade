// flex_check.mjs — Top Picks' "Any time" (flexible month) in headless Chrome.
//
//   cd scripts/dev && PORT=9351 STEP=toggle CDP_TIMEOUT=50 node cdp.mjs ./flex_check.mjs
//
// STEP picks one short run (each well under the driver's cap):
//   toggle  month mode, then Any time picked the way ig_story.mjs picks a month
//           (set the select, dispatch change): chips, months, titles, the URL,
//           row heights against month mode, renderValue's time
//   fares   Any time with production fares injected through the page's own
//           globals (flightsData, flightValue, the fare-months cache) — the
//           local server has no TRAVELPAYOUTS_TOKEN: which rows get the
//           cheapest-flight chip, and that none is on an unbanded route
//   landing the same fares arriving through the page's own fetches (request
//           interception), flight-value after the first render: the chips
//           appear on the render its arrival triggers
//   heights row heights, month mode vs Any time, per country, with fares in
//           and with a budget set (PC=20 for the top 20; BUDGET=0 skips it)
//   parity  hashes of month mode's tables and notes, to compare with main's
//           (flex_dump.mjs diffs them whole, on one server's data)
//   link    a fresh /?tab=value&vmf=1 opens in Any time; picking November
//           turns it off and writes vmn=11
//   tabs    with Any time on, the Flights tab's "Departing in" holds a real
//           month and a guide's month bar still sets the month
// W/H set the viewport (a width under 768 runs as a phone); SHOT names a
// screenshot in shots/. FV/FL are production /api/flight-value and
// /api/flights?origin=US JSON files (fetched with a User-Agent naming
// wandergrade: Cloudflare answers 403 to a default one).
import fs from 'node:fs';
const PORT = process.env.PORT || '9351';
const STEP = process.env.STEP || 'toggle';
const W = +(process.env.W || 1280), H = +(process.env.H || 900);
const SHOT = process.env.SHOT || '';
const BASE = `http://127.0.0.1:${PORT}`;

const rowsJS = `(() => {
  const trs = [...document.querySelectorAll('#topCards table.gradetable:not(.skeleton) tbody tr[data-iso]')];
  if (trs.length < 5) return null;
  const gems = [...document.querySelectorAll('#gemRows tbody tr[data-iso]')];
  const cell = (t) => ({ iso: t.dataset.iso,
    chips: [...t.querySelectorAll('td.dest .seastag')].map((c) => c.textContent.trim()),
    tick: (t.querySelector('.seasonstrip .sc.now') || {}).dataset ? (t.querySelector('.seasonstrip .sc.now') || { dataset: {} }).dataset.m : null,
    h: Math.round(t.getBoundingClientRect().height * 10) / 10 });
  const combo = document.getElementById('valueMonth').parentNode.querySelector('input.combo-input');
  return { value: document.getElementById('valueMonth').value, url: location.search,
    title: document.getElementById('valueMapTitle').textContent,
    tip: document.getElementById('valueMapSub').dataset.tip,
    note: document.getElementById('picksNote').textContent.trim(),
    overlay: (document.querySelector('.mappicksrow[data-for="valueMap"] strong') || {}).textContent,
    combo: combo ? { text: combo.value, w: combo.clientWidth, sw: combo.scrollWidth } : null,
    picks: trs.map(cell), gems: gems.map(cell),
    full: [...document.querySelectorAll('#valueRows tr')].slice(0, 5).map((t) => t.children[1] && t.children[1].textContent.trim()) };
})()`;

const waitRows = async (evaluate, sleep) => {
  let r = null;
  for (let i = 0; i < 30 && !r; i++) { r = await evaluate(rowsJS); if (!r) await sleep(500); }
  return r;
};
const pick = (v) => `(() => { const s = document.getElementById('valueMonth'); s.value = ${JSON.stringify(String(v))}; s.dispatchEvent(new Event('change', { bubbles: true })); return s.value; })()`;

export default async ({ send, on, evaluate, setSize, nav, sleep, shot }) => {
  await setSize(W, H, W < 768);
  if (STEP === 'toggle') {
    await nav(`${BASE}/?tab=value&cb=${Date.now()}`, 3500);
    const before = await waitRows(evaluate, sleep);
    console.log('MONTH', JSON.stringify({ value: before.value, url: before.url, picks: before.picks.map((p) => p.iso + ' ' + p.h), gems: before.gems.map((p) => p.iso) }));
    await evaluate(pick(0));
    await sleep(1500);
    const after = await evaluate(rowsJS);
    console.log('FLEX', JSON.stringify(after, null, 1));
    // renderValue's own time in Any time vs month mode, best of five each.
    const t = await evaluate(`(() => { const time = () => { let b = 1e9; for (let i = 0; i < 5; i++) { const t0 = performance.now(); renderValue(); b = Math.min(b, performance.now() - t0); } return Math.round(b * 10) / 10; };
      const flex = time(); const s = document.getElementById('valueMonth'); s.value = String(travelMonth()); const mon = time(); s.value = '0'; renderValue();
      return { flexMs: flex, monthMs: mon, win: flexWindow() }; })()`);
    console.log('TIMING', JSON.stringify(t));
    await sleep(2500);   // the rows' entrance animation, rerun by each render
    if (SHOT) console.log('shot', await shot(SHOT));
  } else if (STEP === 'fares') {
    const fv = fs.readFileSync(process.env.FV, 'utf8'), fl = fs.readFileSync(process.env.FL, 'utf8');
    await nav(`${BASE}/?tab=value&pc=20&cb=${Date.now()}`, 3500);
    await waitRows(evaluate, sleep);
    await evaluate(pick(0));
    await sleep(800);
    const r = await evaluate(`(() => {
      const fl = ${fl}, fv = ${fv};
      flightsData = fl; flightValue = fv;
      // The row fare strips' months, from the same curves (the page fetches
      // /api/flight-months per row; the local server has none).
      for (const iso in fv.countries) {
        const c = fv.countries[iso]; if (!c.curve) continue;
        const months = {}; for (const k in c.curve) months[k] = { price: c.curve[k][0] };
        _fareMonthsCache['US:' + iso] = Promise.resolve({ origin: 'US', months });
      }
      renderValue();
      const rows = [...lastPicks, ...lastGems];
      const banded = (iso) => !!(fv.countries[iso] && fv.countries[iso].median != null);
      const withFly = rows.filter((s) => s.cheapFly).map((s) => s.iso + ' best ' + s.month + ' cheapest ' + s.cheapFly.month + ' ' + s.cheapFly.price);
      const bad = rows.filter((s) => s.cheapFly && (!banded(s.iso) || s.cheapFly.month === s.month)).map((s) => s.iso);
      const domFly = [...document.querySelectorAll('.gradetable tr[data-iso]')].filter((t) => t.querySelector('.seasfly')).map((t) => t.dataset.iso);
      const domBad = domFly.filter((iso) => !banded(iso));
      const unbandedShown = rows.filter((s) => !banded(s.iso)).map((s) => s.iso);
      const tips = [...document.querySelectorAll('.gradetable .seasfly')].slice(0, 2).map((e) => e.dataset.tip);
      const best = [...document.querySelectorAll('#topCards .seasbest')].slice(0, 3).map((e) => e.textContent + ' :: ' + e.dataset.tip);
      return { origin: originIso(), withFly, bad, domFly, domBad, unbandedShown, tips, best,
        picks: lastPicks.map((s) => s.iso + '@' + s.month + ' ' + s.value) };
    })()`);
    console.log('FARES', JSON.stringify(r, null, 1));
    await sleep(1200);
    const ticks = await evaluate(`(() => [...document.querySelectorAll('#topCards tr[data-iso]')].slice(0, 6).map((t) => {
      const slot = t.querySelector('.rowfares'); const now = slot && slot.querySelector('.fcell.now');
      const cells = slot ? [...slot.querySelectorAll('.fcell')] : [];
      return t.dataset.iso + ' m=' + (slot && slot.dataset.m) + ' tick=' + (now ? cells.indexOf(now) + 1 : '-') + ' h=' + Math.round(t.getBoundingClientRect().height * 10) / 10 + ' chips=' + [...t.querySelectorAll('td.dest .seastag')].map((c) => c.textContent.trim()).join(' | ');
    }))()`);
    console.log('STRIPS', JSON.stringify(ticks, null, 1));
    await sleep(1500);
    if (SHOT) console.log('shot', await shot(SHOT));
  } else if (STEP === 'parity') {
    // Month mode must render exactly as main: the tables' and notes' HTML,
    // hashed, without fares and then with production fares injected.
    const fv = fs.readFileSync(process.env.FV, 'utf8'), fl = fs.readFileSync(process.env.FL, 'utf8');
    await nav(`${BASE}/?tab=value&pc=10&cb=${Date.now()}`, 3500);
    await waitRows(evaluate, sleep);
    const dump = `(() => { const h = (s) => { let x = 5381; for (let i = 0; i < s.length; i++) x = (x * 33 + s.charCodeAt(i)) >>> 0; return x.toString(16) + ':' + s.length; };
      const g = (id) => (document.getElementById(id) || {}).innerHTML || '';
      return { topCards: h(g('topCards')), gemRows: h(g('gemRows')), valueRows: h(g('valueRows')), picksNote: h(g('picksNote')),
        title: g('valueMapTitle'), tip: document.getElementById('valueMapSub').dataset.tip, overlay: h((document.querySelector('.mappicksrow[data-for="valueMap"]') || {}).innerHTML || ''),
        map: h([...document.querySelectorAll('#valueMap path')].map((p) => p.getAttribute('fill') + (p.querySelector('title') || {}).textContent).join('|')),
        picks: lastPicks.map((s) => s.iso + ' ' + s.value).join(','), gems: lastGems.map((s) => s.iso + ' ' + s.value).join(','), url: location.search }; })()`;
    await sleep(1500);
    console.log('NOFARES', JSON.stringify(await evaluate(dump)));
    await evaluate(`(() => { const fl = ${fl}, fv = ${fv}; flightsData = fl; flightValue = fv; renderValue(); return 1; })()`);
    await sleep(1500);
    console.log('FARES', JSON.stringify(await evaluate(dump)));
    await evaluate(`(() => { valueMapMode = 'weather'; markRankBy(); syncRankSort(); renderValue(); return 1; })()`);
    await sleep(1500);
    console.log('WEATHER', JSON.stringify(await evaluate(dump)));
  } else if (STEP === 'heights') {
    // Row heights, month mode vs Any time, with production fares in (the
    // Flights cell is then its tallest), and again with a budget set (the
    // name cell's budget line). BUDGET=0 skips the second pass.
    const fv = fs.readFileSync(process.env.FV, 'utf8'), fl = fs.readFileSync(process.env.FL, 'utf8');
    await nav(`${BASE}/?tab=value&pc=${process.env.PC || 5}&cb=${Date.now()}`, 3500);
    await waitRows(evaluate, sleep);
    await evaluate(`(() => { const fl = ${fl}, fv = ${fv}; flightsData = fl; flightValue = fv;
      for (const iso in fv.countries) { const c = fv.countries[iso]; if (!c.curve) continue;
        const months = {}; for (const k in c.curve) months[k] = { price: c.curve[k][0] };
        _fareMonthsCache['US:' + iso] = Promise.resolve({ origin: 'US', months }); }
      document.getElementById('gemsBox').open = true; renderValue(); return 1; })()`);
    const hs = `(() => { const m = (sel) => [...document.querySelectorAll(sel + ' table.gradetable:not(.skeleton) tbody tr[data-iso]')].map((t) => Math.round(t.getBoundingClientRect().height * 10) / 10);
      const byIso = {}; document.querySelectorAll('.gradetable:not(.skeleton) tbody tr[data-iso]').forEach((t) => { byIso[t.dataset.iso] = Math.round(t.getBoundingClientRect().height * 10) / 10; });
      window.__h = window.__h || []; window.__h.push(byIso);
      const t = m('#topCards'), g = m('#gemRows');
      const over = (id) => { const e = document.getElementById(id); return e.scrollWidth - e.clientWidth; };
      return { max: Math.max(...t, ...g), min: Math.min(...t, ...g), top: t.join(','), gems: g.join(','),
               overflow: [over('topCards'), over('gemRows'), document.documentElement.scrollWidth - innerWidth].join('/') }; })()`;
    for (const bud of process.env.BUDGET === '0' ? [''] : ['', '3000']) {
      await evaluate(`(() => { const b = document.getElementById('budgetTotal'); b.value = ${JSON.stringify(bud)}; b.dispatchEvent(new Event('input')); return 1; })()`);
      await evaluate(pick(10)); await sleep(1500);
      const mon = await evaluate(hs);
      await evaluate(pick(0)); await sleep(1500);
      const flex = await evaluate(hs);
      console.log('HEIGHTS', W, bud ? 'budget' : 'nobudget', JSON.stringify({ month: mon, flex }));
      // Per country: an Any time row against the same country's month-mode
      // row (the two lists hold different countries).
      const cmp = await evaluate(`(() => { const [a, b] = window.__h.slice(-2); const out = [];
        for (const iso in b) if (a[iso] != null && b[iso] > a[iso] + 0.05) out.push(iso + ' ' + a[iso] + '->' + b[iso]);
        const lone = Object.keys(b).filter((iso) => a[iso] == null);
        return { taller: out, shared: Object.keys(b).filter((iso) => a[iso] != null).length, flexOnly: lone.map((iso) => iso + ' ' + b[iso]).join(', ') }; })()`);
      console.log('PERISO', JSON.stringify(cmp));
    }
    await evaluate(`(() => { const b = document.getElementById('budgetTotal'); b.value = ''; b.dispatchEvent(new Event('input')); return 1; })()`);
    await sleep(1500);
    if (SHOT) console.log('shot', await shot(SHOT));
  } else if (STEP === 'landing') {
    // The fares arrive the way they do in production: the page's own
    // loadValueFlights fetches /api/flights, then /api/flight-value, and
    // renders again when each lands. Here those responses (and each row's
    // /api/flight-months) are production JSON served by request interception,
    // /api/flight-value held back 1.5 s so it lands after the first render.
    const FV = JSON.parse(fs.readFileSync(process.env.FV, 'utf8')), FL = fs.readFileSync(process.env.FL, 'utf8');
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/flights?*', requestStage: 'Request' },
      { urlPattern: '*/api/flight-value?*', requestStage: 'Request' }, { urlPattern: '*/api/flight-months?*', requestStage: 'Request' }] });
    const b64 = (x) => Buffer.from(x).toString('base64');
    const reply = (id, body) => send('Fetch.fulfillRequest', { requestId: id, responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: b64(body) });
    const seen = [];
    on((d) => {
      if (d.method !== 'Fetch.requestPaused') return;
      const u = new URL(d.params.request.url), id = d.params.requestId;
      seen.push(u.pathname + ' ' + Date.now());
      if (u.pathname === '/api/flights') reply(id, FL);
      else if (u.pathname === '/api/flight-value') setTimeout(() => reply(id, JSON.stringify(FV)), 1500);
      else {
        const c = FV.countries[u.searchParams.get('iso')], months = {};
        if (c && c.curve) for (const k in c.curve) months[k] = { price: c.curve[k][0] };
        reply(id, JSON.stringify({ origin: 'US', months }));
      }
    });
    await nav(`${BASE}/?tab=value&vmf=1&pc=20&cb=${Date.now()}`, 300);
    const snap = `(() => ({ fv: !!flightValue, fly: [...document.querySelectorAll('.gradetable .seasfly')].map((e) => e.closest('tr').dataset.iso),
      unbandedFly: [...document.querySelectorAll('.gradetable .seasfly')].map((e) => e.closest('tr').dataset.iso).filter((iso) => !(flightValue && flightValue.countries[iso] && flightValue.countries[iso].median != null)),
      rows: document.querySelectorAll('#topCards tr.flexrow').length }))()`;
    const marks = [];
    for (let i = 0; i < 12; i++) { await sleep(500); marks.push(JSON.stringify(await evaluate(snap))); }
    console.log('LANDING', marks.filter((m, i) => i === 0 || m !== marks[i - 1]).join('\n        '));
    console.log('REQUESTS', seen.filter((x) => !x.includes('flight-months')).join(', '), '+', seen.filter((x) => x.includes('flight-months')).length, 'flight-months');
  } else if (STEP === 'link') {
    await nav(`${BASE}/?tab=value&vmf=1&cb=${Date.now()}`, 3500);
    const a = await waitRows(evaluate, sleep);
    console.log('LANDED', JSON.stringify({ value: a.value, url: a.url, title: a.title, combo: a.combo, chips: a.picks.map((p) => p.chips.join(' | ')) }));
    await evaluate(pick(11));
    await sleep(1200);
    const b = await evaluate(rowsJS);
    console.log('NOV', JSON.stringify({ value: b.value, url: b.url, title: b.title, chips: b.picks.map((p) => p.chips.join(' | ')) }));
    // Back to Any time, then reload the address bar's own URL: still Any time.
    await evaluate(pick(0));
    await sleep(800);
    const url = await evaluate(`(() => location.href)()`);
    await nav(url, 3500);
    const c = await waitRows(evaluate, sleep);
    console.log('RELOAD', JSON.stringify({ url: c.url, value: c.value, title: c.title }));
  } else if (STEP === 'tabs') {
    await nav(`${BASE}/?tab=value&cb=${Date.now()}`, 3500);
    await waitRows(evaluate, sleep);
    await evaluate(pick(0));
    await sleep(800);
    const f = await evaluate(`(async () => { await activateTab('data', true); await setDataMode('flights'); await new Promise((r) => setTimeout(r, 1500));
      const fm = document.getElementById('flightMonth');
      return { flightMonth: fm && fm.value, combo: fm && fm.parentNode.querySelector('input.combo-input') && fm.parentNode.querySelector('input.combo-input').value,
               flightMonthNum: flightMonthNum(), travelMonth: travelMonth(), valueMonth: document.getElementById('valueMonth').value, url: location.search }; })()`);
    console.log('FLIGHTS', JSON.stringify(f));
    const g = await evaluate(`(async () => { await openGuideFor('JP', true); await new Promise((r) => setTimeout(r, 2000));
      const sel = document.querySelector('#bestDetail .bars .col.selmonth');
      const before = { selmonth: sel && sel.dataset.mn, valueMonth: document.getElementById('valueMonth').value, url: location.pathname + location.search };
      const bar = document.querySelector('#bestDetail .bars .col[data-mn="2"]');
      if (bar) bar.click();
      await new Promise((r) => setTimeout(r, 800));
      const sel2 = document.querySelector('#bestDetail .bars .col.selmonth');
      return { before, after: { selmonth: sel2 && sel2.dataset.mn, valueMonth: document.getElementById('valueMonth').value, url: location.pathname + location.search } }; })()`);
    console.log('GUIDE', JSON.stringify(g));
  }
};

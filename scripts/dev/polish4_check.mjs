// polish4_check.mjs — Top Picks "Any time" with a budget, the row's own month
// on the views a row opens, and shared pri=/fac= as a view, in headless Chrome.
//
//   cd scripts/dev && PORT=9411 FV=fv.json FL=fl.json STEP=budget CDP_TIMEOUT=50 node cdp.mjs ./polish4_check.mjs
//
// FV/FL are production /api/flight-value and /api/flights?origin=US JSON
// (fetched with a User-Agent naming wandergrade: Cloudflare answers 403 to a
// default one); the page's own fetches of them, and of each row's
// /api/flight-months, are answered from those files by request interception,
// so the Flights tab loads them too (the local server has no fare token).
// STEP picks one short run:
//   budget  Any time without and with a budget (BUDGET, default 700 USD for
//           10 days): the countries whose month the budget moved (month,
//           value and fare before and after), the ones no month of the window
//           saves, the "Best in" tip, and the note's count against one taken
//           independently from valueScores over the window
//   focus   a row whose month is not the window's first: its name link opens
//           the guide on that month (bars, stays), Top Picks keeps Any time,
//           the guide tab opened by hand shows the window's first; its
//           Flights cell opens the Flights tab on that month; a guide bar
//           picked clears it, and Any time picked again does not bring it back
//   focus2  the Weather cell, a hidden gem's row, a country on the value map
//           ("Country guide →") and Back from the guide (popstate)
//   prefs   ?pri=&fac= opened by a fresh visitor and by one with saved
//           priorities: on screen, not saved; a reload without them shows
//           the reader's own; a Count chip or priority changed while viewing
//           saves both; and what the other shared params leave in storage
//   shot    Top Picks for a screenshot (SHOT): month mode, or Any time with
//           ANY=1, with a budget with BUDGET; APPJS=main's for the same view
//           on main
// W/H set the viewport (a width under 768 runs as a phone); SHOT names a
// screenshot in shots/. APPJS serves another app.js (main's, say) in place of
// the server's, for the same run on another build.
import fs from 'node:fs';
const PORT = process.env.PORT || '9411';
const STEP = process.env.STEP || 'budget';
const W = +(process.env.W || 1280), H = +(process.env.H || 900);
const BASE = `http://127.0.0.1:${PORT}`;

const pick = (v) => `(() => { const s = document.getElementById('valueMonth'); s.value = ${JSON.stringify(String(v))}; s.dispatchEvent(new Event('change', { bubbles: true })); return s.value; })()`;

async function serveFares(send, on) {
  const FV = JSON.parse(fs.readFileSync(process.env.FV, 'utf8')), FL = fs.readFileSync(process.env.FL, 'utf8');
  const APP = process.env.APPJS ? fs.readFileSync(process.env.APPJS) : null;
  await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/flights?*', requestStage: 'Request' },
    { urlPattern: '*/api/flight-value?*', requestStage: 'Request' }, { urlPattern: '*/api/flight-months?*', requestStage: 'Request' },
    ...(APP ? [{ urlPattern: '*/app.js*', requestStage: 'Request' }] : [])] });
  const b64 = (x) => Buffer.from(x).toString('base64');
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const u = new URL(d.params.request.url);
    if (u.pathname.endsWith('/app.js')) {
      send('Fetch.fulfillRequest', { requestId: d.params.requestId, responseCode: 200,
        responseHeaders: [{ name: 'Content-Type', value: 'application/javascript; charset=utf-8' }], body: APP.toString('base64') });
      return;
    }
    let body;
    if (u.pathname === '/api/flights') body = FL;
    else if (u.pathname === '/api/flight-value') body = JSON.stringify(FV);
    else {
      const c = FV.countries[u.searchParams.get('iso')], months = {};
      if (c && c.curve) for (const k in c.curve) months[k] = { price: c.curve[k][0] };
      body = JSON.stringify({ origin: 'US', months });
    }
    send('Fetch.fulfillRequest', { requestId: d.params.requestId, responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: b64(body) });
  });
}

// Top Picks in Any time with the fares in (flightValue for the US), Top pc.
async function anyTime(evaluate, nav, sleep, pc = 20) {
  await nav(`${BASE}/?tab=value&pc=${pc}&cb=${Date.now()}`, 3000);
  for (let i = 0; i < 30; i++) {
    if (await evaluate(`(() => !!(flightValue && flightValue.countries && document.querySelectorAll('#topCards tr[data-iso]').length >= 5))()`)) break;
    await sleep(400);
  }
  await evaluate(pick(0));
  await sleep(1200);
}

// What the guide shows for its month: the boxed bar, the stay dates, the
// grades line, and the month the page reads.
const guideState = `(() => ({ tab: document.documentElement.getAttribute('data-tab'), iso: ccGuideIso,
  selmonth: +((document.querySelector('#bestDetail .bars .col.selmonth') || { dataset: {} }).dataset.mn || 0),
  fareSel: [...document.querySelectorAll('#guideFares .col')].findIndex((c) => c.classList.contains('selmonth')) + 1,
  stay: (() => { try { return stayDates().checkin || JSON.stringify(stayDates()); } catch (e) { return 'n/a'; } })(),
  grades: (([...document.querySelectorAll('#guideGrades [data-tip]')].find((e) => /^Graded for/.test(e.dataset.tip)) || { dataset: {} }).dataset.tip || '').slice(0, 40),
  travelMonth: travelMonth(), focus: flexFocusMonth, valueMonth: document.getElementById('valueMonth').value,
  win0: flexWindow()[0], url: location.pathname + location.search }))()`;
const flightsState = `(() => { const fm = document.getElementById('flightMonth');
  return { tab: document.documentElement.getAttribute('data-tab'), dm: dataMode, flightMonth: fm && +fm.value,
    combo: fm && (fm.parentNode.querySelector('input.combo-input') || {}).value, flightMonthNum: flightMonthNum(),
    focus: flexFocusMonth, valueMonth: document.getElementById('valueMonth').value, url: location.search,
    filter: (document.getElementById('flightFilter') || {}).value,
    mapLabel: (document.querySelector('#flightMap svg') || { getAttribute: () => '' }).getAttribute('aria-label') }; })()`;
const clickTab = (t) => `(() => { document.querySelector('#tabs button[data-tab="${t}"]').click(); return 1; })()`;

export default async ({ send, on, evaluate, setSize, nav, sleep, shot, errs }) => {
  await setSize(W, H, W < 768);
  if (STEP === 'budget') {
    await serveFares(send, on);
    await anyTime(evaluate, nav, sleep);
    const BUD = process.env.BUDGET || '700';
    const snap = `(() => {
      return { picks: lastPicks.map((s) => s.iso + '@' + s.month), gems: lastGems.map((s) => s.iso + '@' + s.month),
        note: document.getElementById('picksNote').textContent.trim() }; })()`;
    const before = await evaluate(snap);
    console.log('NOBUDGET', JSON.stringify(before));
    await evaluate(`(() => { const d = document.getElementById('budgetDays'); d.value = '10'; d.dispatchEvent(new Event('input'));
      const b = document.getElementById('budgetTotal'); b.value = ${JSON.stringify(BUD)}; b.dispatchEvent(new Event('input')); return 1; })()`);
    await sleep(1500);
    const r = await evaluate(`(() => {
      const win = flexWindow(), advMap = advisoryByIso(), fares = buildFareContext(), pl = plAnchor(originIso()).pl;
      const key = valueMapMode === 'weather' ? 'wx' : 'value', floor = safetyFloor(), been = ownVisited();
      const moved = [], saved = [], none = [];
      let outIndep = 0;
      for (const iso in CUR_BY_ISO) {
        const by = {}; for (const m of win) by[m] = valueScores(iso, m, advMap, fares, pl);
        const free = bestOfWindow(by, win, key), b = bestOfWindow(by, win, key, passesBudget);
        if (!free) continue;
        const pre = !been.has(iso) && passesFloor(free.s, floor) && matchesInterests(iso);
        const anyFits = win.some((m) => by[m] && passesBudget(by[m]));
        if (pre && !anyFits) { outIndep++; none.push(iso + ' ' + win.map((m) => by[m] && by[m].fare != null ? Math.round(by[m].fare) : '-').join('/')); }
        if (b.moved) {
          const row = iso + ' ' + MON_ABBR[free.month - 1] + ' v' + free.s.value + ' $' + Math.round(free.s.fare) + ' -> ' + MON_ABBR[b.month - 1] + ' v' + b.s.value + ' $' + Math.round(b.s.fare);
          moved.push(row);
          if (pre) saved.push(iso);
        }
      }
      const tr = (iso) => document.querySelector('.gradetable tr[data-iso="' + iso + '"]');
      const shown = saved.filter((iso) => tr(iso));
      const tips = shown.slice(0, 4).map((iso) => { const t = tr(iso); return iso + ' [' + t.dataset.m + '] ' + (t.querySelector('.seasbest') || {}).textContent + ' :: ' + (t.querySelector('.seasbest') || { dataset: {} }).dataset.tip
        + ' || ' + ((t.querySelector('.budline') || {}).textContent || '') + ' || full: ' + ([...document.querySelectorAll('#valueRows td.dest')].find((td) => td.textContent.includes(countryName(iso))) || {}).title; });
      const note = document.getElementById('picksNote').textContent.trim();
      const m = note.match(/(\\d+) countr(?:y is|ies are) out of reach/);
      return { budget: budgetOf(), win, moved, savedInRanking: saved, savedShownInTables: shown, tips,
        dropped: none, outIndependent: outIndep, noteOut: m ? +m[1] : 0, note,
        picks: lastPicks.map((s) => s.iso + '@' + s.month), gems: lastGems.map((s) => s.iso + '@' + s.month),
        droppedShown: none.map((x) => x.split(' ')[0]).filter((iso) => tr(iso)) };
    })()`);
    console.log('BUDGET', JSON.stringify(r, null, 1));
    if (process.env.SHOT) { await sleep(1500); console.log('shot', await shot(process.env.SHOT)); }
  } else if (STEP === 'focus') {
    await serveFares(send, on);
    await anyTime(evaluate, nav, sleep);
    const row = await evaluate(`(() => { const w0 = flexWindow()[0];
      const trs = [...document.querySelectorAll('#topCards tr[data-iso][data-m]')];
      const t = trs.find((t) => t.dataset.iso === '${process.env.ISO || 'TH'}' && +t.dataset.m !== w0) || trs.find((t) => +t.dataset.m !== w0);
      return t ? { iso: t.dataset.iso, m: +t.dataset.m, chip: (t.querySelector('.seasbest') || {}).textContent, win: flexWindow() } : null; })()`);
    console.log('ROW', JSON.stringify(row));
    if (!row) return;
    // 1. The name link: the guide on the row's month.
    await evaluate(`(() => { document.querySelector('#topCards tr[data-iso="${row.iso}"] a.destlink').click(); return 1; })()`);
    await sleep(3000);
    console.log('GUIDE_FROM_ROW', JSON.stringify(await evaluate(guideState)));
    // 2. Back to Top Picks by its tab: Any time still on, the focus gone.
    await evaluate(clickTab('value'));
    await sleep(1500);
    console.log('TOPPICKS', JSON.stringify(await evaluate(`(() => ({ valueMonth: document.getElementById('valueMonth').value,
      combo: (document.getElementById('valueMonth').parentNode.querySelector('input.combo-input') || {}).value, focus: flexFocusMonth,
      travelMonth: travelMonth(), url: location.search, chip: (document.querySelector('#topCards tr[data-iso="${row.iso}"] .seasbest') || {}).textContent }))()`)));
    // 3. The guide tab opened by hand: the window's first month.
    await evaluate(clickTab('guide'));
    await sleep(1500);
    console.log('GUIDE_BY_TAB', JSON.stringify(await evaluate(guideState)));
    // 4. The row's Flights cell: the Flights tab on the row's month.
    await evaluate(clickTab('value'));
    await sleep(1200);
    await evaluate(`(() => { document.querySelector('#topCards tr[data-iso="${row.iso}"] td.scell[data-go="flights"]').click(); return 1; })()`);
    await sleep(4000);
    console.log('FLIGHTS_FROM_CELL', JSON.stringify(await evaluate(flightsState)));
    // 5. The guide tab now (drawn while hidden): the focus month still.
    await evaluate(clickTab('guide'));
    await sleep(1500);
    console.log('GUIDE_WHILE_FOCUSED', JSON.stringify(await evaluate(guideState)));
    // 6. A guide bar picked: a month, Any time off, the focus gone.
    const pickM = row.win.find((m) => m !== row.m && m !== row.win[0]);
    await evaluate(`(() => { document.querySelector('#bestDetail .bars .col[data-mn="${pickM}"]').click(); return 1; })()`);
    await sleep(1200);
    console.log('BAR_PICKED', JSON.stringify(await evaluate(guideState)));
    // 7. Any time on again (Top Picks' picker): no leftover row month. (The
    // guide's own bars stay on the month picked above until something redraws
    // them: a month changed on Top Picks never redrew a guide, main included.)
    await evaluate(clickTab('value'));
    await sleep(1000);
    await evaluate(pick(0));
    await sleep(1000);
    await evaluate(clickTab('guide'));
    await sleep(1500);
    console.log('ANYTIME_AGAIN', JSON.stringify(await evaluate(guideState)));
    // 8. Flights tab by hand from here: the window's first month too.
    await evaluate(`(async () => { await activateTab('data', true); await setDataMode('flights'); return 1; })()`);
    await sleep(1500);
    console.log('FLIGHTS_BY_HAND', JSON.stringify(await evaluate(flightsState)));
  } else if (STEP === 'focus2') {
    await serveFares(send, on);
    await anyTime(evaluate, nav, sleep);
    const w0 = await evaluate(`(() => flexWindow()[0])()`);
    // The Weather cell of a row with a month of its own.
    const wrow = await evaluate(`(() => { const t = [...document.querySelectorAll('#topCards tr[data-iso][data-m]')].find((t) => +t.dataset.m !== flexWindow()[0]);
      return t && { iso: t.dataset.iso, m: +t.dataset.m }; })()`);
    await evaluate(`(() => { document.querySelector('#topCards tr[data-iso="${wrow.iso}"] td.scell[data-go="weather"]').click(); return 1; })()`);
    await sleep(3000);
    console.log('WEATHER_CELL', JSON.stringify(wrow), JSON.stringify(await evaluate(guideState)));
    // Back (popstate) to Top Picks: the focus is gone.
    await evaluate(`(() => { history.back(); return 1; })()`);
    await sleep(2000);
    console.log('BACK', JSON.stringify(await evaluate(`(() => ({ tab: document.documentElement.getAttribute('data-tab'), focus: flexFocusMonth, valueMonth: document.getElementById('valueMonth').value, url: location.search }))()`)));
    // A hidden gem's row (a click on its rank cell).
    const grow = await evaluate(`(() => { document.getElementById('gemsBox').open = true;
      const t = [...document.querySelectorAll('#gemRows tr[data-iso][data-m]')].find((t) => +t.dataset.m !== flexWindow()[0]) || document.querySelector('#gemRows tr[data-iso][data-m]');
      return t && { iso: t.dataset.iso, m: +t.dataset.m }; })()`);
    if (grow) {
      await evaluate(`(() => { document.querySelector('#gemRows tr[data-iso="${grow.iso}"] td.rank').click(); return 1; })()`);
      await sleep(3000);
      console.log('GEM_ROW', JSON.stringify(grow), JSON.stringify(await evaluate(guideState)));
      await evaluate(clickTab('value'));
      await sleep(1500);
    } else console.log('GEM_ROW none');
    // A country on the value map, through its card's "Country guide →".
    const mrow = await evaluate(`(() => { const e = Object.entries(valueMapMonths || {}).find(([iso, m]) => m !== flexWindow()[0] && document.querySelector('#valueMap path[data-iso="' + iso + '"]'));
      return e && { iso: e[0], m: e[1] }; })()`);
    await evaluate(`(() => { document.querySelector('#valueMap path[data-iso="${mrow.iso}"]').dispatchEvent(new MouseEvent('click', { bubbles: true })); return 1; })()`);
    await sleep(800);
    const card = await evaluate(`(() => { const b = document.querySelector('.countrycard [data-cc="todo"]'); if (b) b.click(); return !!b; })()`);
    await sleep(3000);
    console.log('MAP_CARD', JSON.stringify(mrow), 'card', card, JSON.stringify(await evaluate(guideState)), 'w0', w0);
    // The Flights tab already drawn for the window's first month, then a
    // row's Flights cell: drawn again for the row's (its second visit only
    // refits, so the focus draws it).
    await evaluate(clickTab('value'));
    await sleep(1000);
    await evaluate(`(async () => { await activateTab('data', true); await setDataMode('flights'); return 1; })()`);
    await sleep(2000);
    console.log('FLIGHTS_FIRST', JSON.stringify(await evaluate(flightsState)));
    await evaluate(clickTab('value'));
    await sleep(1000);
    const frow = await evaluate(`(() => { const t = [...document.querySelectorAll('#topCards tr[data-iso][data-m]')].find((t) => +t.dataset.m !== flexWindow()[0]);
      return t && { iso: t.dataset.iso, m: +t.dataset.m }; })()`);
    await evaluate(`(() => { document.querySelector('#topCards tr[data-iso="${frow.iso}"] td.scell[data-go="flights"]').click(); return 1; })()`);
    await sleep(2500);
    console.log('FLIGHTS_SECOND', JSON.stringify(frow), JSON.stringify(await evaluate(flightsState)));
  } else if (STEP === 'shot') {
    await serveFares(send, on);
    if (process.env.ANY) await anyTime(evaluate, nav, sleep, 10);
    else { await nav(`${BASE}/?tab=value&pc=10&cb=${Date.now()}`, 4000); }
    if (process.env.BUDGET) {
      await evaluate(`(() => { const d = document.getElementById('budgetDays'); d.value = '10'; d.dispatchEvent(new Event('input'));
        const b = document.getElementById('budgetTotal'); b.value = ${JSON.stringify(process.env.BUDGET)}; b.dispatchEvent(new Event('input')); return 1; })()`);
    }
    await sleep(3500);   // the rows' entrance animation
    const y = await evaluate(`(() => { const t = document.getElementById('topCards'); t.scrollIntoView({ block: 'start' }); return Math.round(scrollY); })()`);
    await sleep(800);
    console.log('scrollY', y, 'shot', await shot(process.env.SHOT || 'polish4'));
  } else if (STEP === 'prefs') {
    const ls = `(() => ({ pri: localStorage.getItem('fx_priorities2'), fac: localStorage.getItem('fx_factors2'),
      mem: { pri: JSON.stringify(priorities), fac: JSON.stringify(factors) }, view: sharedPrefsView,
      buttons: [...document.querySelectorAll('#weightRows .prigroup')].map((g) => g.dataset.w + ':' + ((g.querySelector('button.active') || {}).dataset || {}).v).join(' '),
      chips: [...document.querySelectorAll('#factorChips .factorchip.on')].map((b) => b.dataset.f).join(' '),
      top3: lastPicks.slice(0, 3).map((s) => s.iso + ' ' + s.value).join(', '), url: location.search }))()`;
    const LINK = `${BASE}/?tab=value&pri=h.l.l.l&fac=afford.safe`;
    // 1. A fresh visitor opens the link.
    await nav(LINK + `&cb=${Date.now()}`, 4500);
    console.log('FRESH_LINK', JSON.stringify(await evaluate(ls)));
    // 2. A visitor with their own saved priorities and factors opens it.
    await evaluate(`(() => { localStorage.setItem('fx_priorities2', JSON.stringify({ afford: 'low', safe: 'high', wx: 'high', fly: 'med' }));
      localStorage.setItem('fx_factors2', JSON.stringify(['afford', 'safe', 'wx', 'fly'])); return 1; })()`);
    await nav(LINK + `&cb=${Date.now()}`, 4500);
    console.log('OWN_THEN_LINK', JSON.stringify(await evaluate(ls)));
    // ...then reloads / without the params.
    await nav(`${BASE}/?tab=value&cb=${Date.now()}`, 4500);
    console.log('RELOAD_OWN', JSON.stringify(await evaluate(ls)));
    // 3. Opens the link again and turns Weather on under Count: both saved.
    await nav(LINK + `&cb=${Date.now()}`, 4500);
    await evaluate(`(() => { document.querySelector('#factorChips .factorchip[data-f="wx"]').click(); return 1; })()`);
    await sleep(800);
    console.log('CHIP_WHILE_VIEWING', JSON.stringify(await evaluate(ls)));
    await nav(`${BASE}/?tab=value&cb=${Date.now()}`, 4500);
    console.log('RELOAD_ADOPTED', JSON.stringify(await evaluate(ls)));
    // 4. A priority button while viewing another link saves both too.
    await nav(`${BASE}/?tab=value&pri=l.h.l.l&fac=safe.fly&cb=${Date.now()}`, 4500);
    await evaluate(`(() => { document.querySelector('#weightRows .prigroup[data-w="fly"] button[data-v="high"]').click(); return 1; })()`);
    await sleep(800);
    console.log('PRI_WHILE_VIEWING', JSON.stringify(await evaluate(ls)));
    // 5. The other shared params, opened by a fresh visitor: what they write.
    await evaluate(`(() => { localStorage.clear(); return 1; })()`);
    await nav(`${BASE}/?tab=value&vr=ASIA&vmf=1&pc=20&sf=a&vmm=weather&cb=${Date.now()}`, 4500);
    console.log('OTHER_PARAMS', JSON.stringify(await evaluate(`(() => ({ keys: Object.keys(localStorage).sort(),
      on: { region: regionSel, month: document.getElementById('valueMonth').value, pc: pickCount(), sf: safetyFloor(), vmm: valueMapMode } }))()`)));
  }
  console.log('ERRS', JSON.stringify(errs));
};

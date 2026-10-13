// ai_prompt_check.mjs — the two AI prompts (the Travel Guide's "Plan X with
// AI" and the Trip tab's "Plan this trip with AI") for the cases of the
// 2026-10-13 prompt review, generated in headless Chrome with production
// fares, printed beside what the page itself shows for the same case.
//
//   cd scripts/dev && PORT=9471 CASE=A CDP_TIMEOUT=50 node cdp.mjs ./ai_prompt_check.mjs
//
// CASE  A  Japan guide, October, from the US, opened with ai=1
//       B  Top Picks in Any time, the Thailand row's guide, then its AI panel
//       C  Trip from the UK in GBP: Portugal, Spain, Morocco, 12 days in
//          November, a GBP 2,000 budget
//       D  Trip from the US: Thailand, Vietnam, Cambodia, 14 days, flexible
//       E  Japan guide, October, from the UK, GBP 1,800 for 10 days set on
//          Top Picks
//       F  an 8-country flexible trip from the US (length)
//       G  Top Picks in Any time, then the Trip tab with no saved trip month
// The local server has no TRAVELPAYOUTS_TOKEN, so /api/flights,
// /api/flight-value and /api/flight-months are answered by request
// interception with production's own replies (GETs only, 15 s each), fetched
// here with a User-Agent naming wandergrade (Cloudflare answers 403 to a bare
// one): the page's own fetches, so its own waits run as they do live.
//   BASE   the server (default http://127.0.0.1:$PORT)
//   APPJS  another app.js swapped in (main's, on the same server's data)
//   LS     localStorage added to the case's: LS='{"fx_visited":"[\"JP\"]"}'
//   URL    the case's address replaced (a guide case keeps ai=1, a trip
//          case tab=trip)
//   DELAY  ms each /api/flight-months reply is held: past the panel's ~3 s
//          wait it is drawn without them, then again when they land
//          (VERSIONS lists each drawing's flights line)
//   PAGE=0 skips the page's facts; PANEL=1 lists the panel's buttons (label,
//          cap verdict, href length) and clicks each with its navigation
//          cancelled: the AI sites are never opened
//   W, H   the viewport (a width under 768 runs as a phone); SHOT names a
//          screenshot of the panel in shots/; OUT writes the prompt as JSON
//          ({case, prompt, chars, encoded})
import fs from 'node:fs';
const PORT = process.env.PORT || '9471';
const BASE = process.env.BASE || `http://127.0.0.1:${PORT}`;
const CASE = (process.env.CASE || 'A').toUpperCase();
const W = +(process.env.W || 1280), H = +(process.env.H || 900);
const PROD = 'https://wandergrade.com';
const UA = 'Mozilla/5.0 (wandergrade dev check; scripts/dev/ai_prompt_check.mjs)';
const DELAY = +(process.env.DELAY || 0);

const CASES = {
  A: { kind: 'guide', iso: 'JP', ls: { fx_origin: 'US' }, url: '/?tab=guide&gc=JP&vmn=10&ai=1' },
  B: { kind: 'guide', iso: 'TH', ls: { fx_origin: 'US' }, url: '/?tab=value&vmf=1&pc=20', row: 'TH' },
  C: { kind: 'trip', ls: { fx_origin: 'GB', fx_homecur: 'GBP', fx_trip: '["PT","ES","MA"]', fx_tripdays: '12', fx_tripmonth: '11',
       wg_budget: '2000', wg_budgetdays: '12' }, url: '/?tab=trip' },
  D: { kind: 'trip', ls: { fx_origin: 'US', fx_trip: '["TH","VN","KH"]', fx_tripdays: '14', fx_tripmonth: '0' }, url: '/?tab=trip' },
  E: { kind: 'guide', iso: 'JP', ls: { fx_origin: 'GB', fx_homecur: 'GBP', wg_budget: '1800', wg_budgetdays: '10' }, url: '/?tab=guide&gc=JP&vmn=10&ai=1' },
  F: { kind: 'trip', ls: { fx_origin: 'US', fx_trip: '["PT","ES","FR","IT","HR","GR","TR","MA"]', fx_tripdays: '21', fx_tripmonth: '0' },
       url: '/?tab=trip' },
  G: { kind: 'trip', ls: { fx_origin: 'US', fx_trip: '["TH","VN","KH"]', fx_tripdays: '14' }, url: '/?tab=value&vmf=1', viaPicks: true },
};

export default async ({ send, on, evaluate, setSize, nav, sleep, shot }) => {
  const C = CASES[CASE];
  if (!C) { console.log('unknown CASE', CASE); return; }
  await setSize(W, H, W < 768);
  const cache = {};
  const prod = (pathq) => (cache[pathq] = cache[pathq]
    || fetch(PROD + pathq, { headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(15000) })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error('HTTP ' + r.status))))
      .catch((e) => { delete cache[pathq]; throw e; }));
  const patterns = ['/api/flights?', '/api/flight-value?', '/api/flight-months?'].map((p) => ({ urlPattern: '*' + p + '*', requestStage: 'Request' }));
  const appjs = process.env.APPJS ? fs.readFileSync(process.env.APPJS).toString('base64') : null;
  if (appjs) patterns.push({ urlPattern: '*/app.js*', requestStage: 'Request' });
  await send('Fetch.enable', { patterns });
  const reply = (id, ctype, b64) => send('Fetch.fulfillRequest', { requestId: id, responseCode: 200,
    responseHeaders: [{ name: 'Content-Type', value: ctype }], body: b64 });
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const u = new URL(d.params.request.url), id = d.params.requestId;
    if (u.pathname.endsWith('/app.js')) return reply(id, 'application/javascript; charset=utf-8', appjs);
    if (d.params.request.method !== 'GET') return send('Fetch.failRequest', { requestId: id, errorReason: 'Failed' });
    const hold = u.pathname === '/api/flight-months' ? DELAY : 0;
    prod(u.pathname + u.search).then((t) => new Promise((r) => setTimeout(() => r(t), hold)))
      .then((t) => reply(id, 'application/json', Buffer.from(t).toString('base64')))
      .catch(() => send('Fetch.failRequest', { requestId: id, errorReason: 'Failed' }));
  });

  // A clean slate, then the case's own storage, set on the page's origin.
  await nav(`${BASE}/?tab=visited&cb=${Date.now()}`, 1200);
  const ls = Object.assign({}, C.ls, process.env.LS ? JSON.parse(process.env.LS) : {});
  await evaluate(`(() => { localStorage.clear(); const o = ${JSON.stringify(ls)}; for (const k in o) localStorage.setItem(k, o[k]); return 1; })()`);
  await nav(`${BASE}${process.env.URL || C.url}&cb=${Date.now()}`, 4000);

  if (C.row) {
    // The Any time row, clicked the way a reader does (its data-m sets the
    // guide's month), then the guide's own AI button.
    let ok = null;
    for (let i = 0; i < 20 && !ok; i++) {
      ok = await evaluate(`(() => { const tr = document.querySelector('.gradetable tr[data-iso="${C.row}"]');
        if (!tr || !flightValue) return null; const a = tr.querySelector('a.destlink') || tr.querySelector('td.dest') || tr;
        const chips = [...tr.querySelectorAll('td.dest .seastag')].map((c) => c.textContent.trim() + (c.dataset.tip ? ' [' + c.dataset.tip + ']' : ''));
        a.click(); return { m: tr.dataset.m, chips }; })()`);
      if (!ok) await sleep(500);
    }
    console.log('ROW', JSON.stringify(ok));
    await sleep(2500);
    await evaluate(`(() => { const b = document.getElementById('guideAIBtn'); if (b) b.click(); return !!b; })()`);
  }
  if (C.viaPicks) {
    for (let i = 0; i < 20; i++) { if (await evaluate(`(() => document.querySelectorAll('.gradetable tr[data-iso]').length > 4)()`)) break; await sleep(500); }
    await evaluate(`(() => { activateTab('trip', true); return 1; })()`);
    await sleep(1500);
  }
  if (C.kind === 'trip') await evaluate(`(() => { const b = document.getElementById('tripPlanBtn'); b.click(); return 1; })()`);

  // The panel is drawn once its data is in (or after its wait), and drawn
  // again if more lands: read it once it has stopped changing.
  const panelSel = C.kind === 'trip' ? '#tripPanel' : '#guideAIPanel';
  // Read once it has held still for 3 s, and no sooner than 5 s in (the
  // panel's own wait is ~3 s, and its data can land after it).
  let prompt = null, last = null, still = 0;
  const seen = [];
  for (let i = 1; i <= 40; i++) {
    await sleep(500);
    const p = await evaluate(`(() => { const t = document.querySelector('${panelSel} textarea'); return t ? t.value : null; })()`);
    if (p && !seen.includes(p)) seen.push(p);
    still = p && p === last ? still + 1 : 0;
    last = p;
    if (still >= 6 && i * 500 >= Math.max(5000, DELAY + 1500)) { prompt = p; break; }
  }
  prompt = prompt || last;
  if (!prompt) { console.log('NO PROMPT'); return; }
  // More than one version: the panel was drawn, then drawn again as data
  // landed (each version's FLIGHTS line shows which).
  if (seen.length > 1) console.log('VERSIONS ' + seen.length + '\n' + seen.map((v, i) => '  #' + (i + 1) + ' '
    + ((v.split('\n').find((l) => /^FLIGHTS|flights /.test(l)) || '(no flights line)').slice(0, 160))).join('\n'));
  const enc = encodeURIComponent(prompt).length;
  const fits = await evaluate(`(() => [...document.querySelectorAll('${panelSel} a.aiact')].map((a) => a.textContent.replace(/ ↗$/, '') + (a.dataset.fits === '0' ? ' (over cap)' : '')).join(', '))()`);
  const odd = [...new Set([...prompt].filter((c) => c.charCodeAt(0) > 127))].join('');
  console.log(`PROMPT ${CASE} chars=${prompt.length} encoded=${enc}${odd ? ' non-ASCII=' + odd : ''}${fits ? ' | ' + fits : ''}`);
  console.log(prompt);
  if (process.env.OUT) fs.writeFileSync(process.env.OUT, JSON.stringify({ case: CASE, prompt, chars: prompt.length, encoded: enc }));

  if (process.env.PAGE !== '0') {
    const facts = C.kind === 'guide' ? await evaluate(`(() => {
      const iso = '${C.iso}', tx = (id) => { const e = document.getElementById(id); return e && !e.hidden ? e.innerText.replace(/\\s+/g, ' ').trim() : null; };
      const fares = document.querySelector('#guideFares .farebars');
      let budget = null;
      try { const s = valueScores(iso, travelMonth(), advisoryByIso(), buildFareContext(), plAnchor(originIso()).pl);
            const bf = s && budgetFit(s); budget = bf ? (bf.impossible || bf.estOut ? 'over budget' : budgetWords(s, bf)) : null; } catch (e) { budget = 'ERR ' + e; }
      const fvc = flightValue && flightValue.countries && flightValue.countries[iso];
      return { travelMonth: travelMonth(), flex: picksFlex(), flexFocusMonth, window: flexWindow(),
        faresHead: tx('guideFares') && document.querySelector('#guideFares .fareshead').innerText.trim(),
        fares: fares && fares.getAttribute('aria-label'),
        selFareTip: (document.querySelector('#guideFares .col.selmonth') || { dataset: {} }).dataset.tip,
        typical: fvc && fvc.median != null ? [fvc.lo, fvc.median, fvc.hi] : null,
        cost: tx('guideCost'), fx: tx('guideFx'), visa: tx('guideVisa'), safety: tx('guideSafety'),
        grades: tx('guideGrades'), days: (document.querySelector('#guideGrades .ggdays') || {}).dataset ? (document.querySelector('#guideGrades .ggdays') || { dataset: {} }).dataset.tip : null,
        seasons: [...document.querySelectorAll('#actDetail .seasrow')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim().slice(0, 90)),
        budgetWords: budget, visited: isVisited(iso) };
    })()`) : await evaluate(`(() => ({
      tripMonth: (document.getElementById('tripMonth') || {}).value, tripDays: (document.getElementById('tripDays') || {}).value,
      flex: picksFlex(), window: flexWindow(),
      rows: [...document.querySelectorAll('#tripBook .tbrow[data-iso]')].map((r) => r.dataset.iso + ': '
        + ((r.querySelector('.tbfarenote') || {}).innerText || '-') + ' | strip ' + ((r.querySelector('.farestrip[aria-label]') || { getAttribute: () => '-' }).getAttribute('aria-label') || '-')
        + ' | wx ' + ((r.querySelector('.tbwx .gr') || { dataset: {} }).dataset.tip || '-')
        + ' | warn ' + ((r.querySelector('.hzmark') || { dataset: {} }).dataset.tip || '-')),
    }))()`);
    console.log('PAGE', JSON.stringify(facts, null, 1));
  }
  if (process.env.PANEL === '1') {
    const p = await evaluate(`(() => [...document.querySelectorAll('${panelSel} .airow > *')].map((e) => ({ text: e.textContent.trim(),
      fits: e.dataset.fits, href: e.href ? e.href.slice(0, 70) + (e.href.length > 70 ? '…' : '') : null, hrefLen: e.href ? e.href.length : null })))()`);
    console.log('PANEL', JSON.stringify(p, null, 1));
    const hint = await evaluate(`(() => { const h = document.querySelector('${panelSel} .hint'); return h ? { text: h.innerText.trim(), tip: (h.querySelector('[data-tip]') || { dataset: {} }).dataset.tip } : null; })()`);
    console.log('HINT', JSON.stringify(hint, null, 1));
    // Each link clicked with its navigation cancelled (a capturing listener
    // prevents the default; the AI sites are never opened) and the clipboard
    // stubbed: what was copied, and the status line it left (only a link
    // past its site's cap should speak).
    const clicks = await evaluate(`(async () => {
      const stop = (e) => { if (e.target.closest && e.target.closest('a.aiact')) e.preventDefault(); };
      document.addEventListener('click', stop, true);
      let got = null;
      Object.defineProperty(navigator.clipboard, 'writeText', { configurable: true, value: (t) => { got = t; return Promise.resolve(); } });
      const out = [], prompt = document.querySelector('${panelSel} textarea').value, st = document.getElementById('status');
      for (const a of document.querySelectorAll('${panelSel} a.aiact')) {
        got = null; status('');
        a.click(); await new Promise((r) => setTimeout(r, 200));
        out.push({ text: a.textContent.trim(), fits: a.dataset.fits, copiedWhole: got === prompt, status: st.hidden ? null : st.textContent });
      }
      document.removeEventListener('click', stop, true);
      return out; })()`);
    console.log('CLICKS', JSON.stringify(clicks, null, 1));
  }
  if (process.env.SHOT) {
    await evaluate(`(() => { document.querySelector('${panelSel}').scrollIntoView({ block: 'start' }); return 1; })()`);
    await sleep(400);
    console.log('shot', await shot(process.env.SHOT));
  }
};

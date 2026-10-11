// share_check.mjs — what opening a URL costs and what it leaves behind: every
// /api request counted by path+query (Network events), main-thread stalls and
// long tasks, and localStorage's home country/currency at the end. Written for
// the share-link work: a ?vo=GB link used to fetch /api/flight-origins twice,
// /api/rates?base=GBP twice, and rewrite a fresh visitor's fx_origin/fx_homecur.
// Usage (a cdp.mjs script; one JSON line on stdout):
//   URL='http://127.0.0.1:9201/?tab=value&vo=GB' CDP_TIMEOUT=50 node scripts/dev/cdp.mjs scripts/dev/share_check.mjs
//   SECS=20            poll window after the load event (a trivial evaluate every 500 ms;
//                      a poll over STALL_MS = 1000 ms is a stall: the main thread was busy)
//   SEED='{"fx_origin":"GB"}'  localStorage written on the origin before the page loads (a returning visitor)
//   GEO=DE             CF-IPCountry header on every request — what /api/geo answers (a non-US first visit)
//   ACT='<js>'         run after the poll window (the reader changing From by hand), then 3 s settle;
//                      `after` repeats ls + page and counts only the /api requests ACT caused
// Output: { url, loadMs, api: {"/api/flights?origin=GB": 1, ...}, polls, stalls, maxPollMs,
//           longtasks: [{start, dur}], ls: {fx_origin, fx_homecur, fx_homecur_manual},
//           page: {valueOrigin, homeCur, flightOrigin, homeBase, sharedOriginView, href}, errs, after }
const STALL_MS = 1000;
const LS = `(() => ({ fx_origin: localStorage.getItem('fx_origin'), fx_homecur: localStorage.getItem('fx_homecur'),
  fx_homecur_manual: localStorage.getItem('fx_homecur_manual') }))()`;
const PAGE = `(() => { const v = (id) => { const e = document.getElementById(id); return e ? e.value : null; };
  return { valueOrigin: v('valueOrigin'), homeCur: v('homeCur'), flightOrigin: v('flightOrigin'),
    homeBase: typeof homeBase === 'string' ? homeBase : null,
    sharedOriginView: typeof sharedOriginView === 'undefined' ? 'n/a' : sharedOriginView, href: location.href }; })()`;

export default async function ({ send, on, evaluate, nav, sleep, errs }) {
  const url = process.env.URL;
  if (!url) { console.log('URL= is required'); return; }
  const secs = +process.env.SECS || 20;
  let api = {};
  on((d) => {
    if (d.method !== 'Network.requestWillBeSent') return;
    const u = new URL(d.params.request.url);
    if (!u.pathname.startsWith('/api/')) return;
    const k = u.pathname + u.search;
    api[k] = (api[k] || 0) + 1;
  });
  let loadedAt = 0;
  on((d) => { if (d.method === 'Page.loadEventFired' && !loadedAt) loadedAt = Date.now(); });
  await send('Network.enable');
  if (process.env.GEO) await send('Network.setExtraHTTPHeaders', { headers: { 'CF-IPCountry': process.env.GEO } });
  // Long tasks are observed from before the page's own scripts run; `buffered`
  // alone would miss the ones before the observer existed.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__lt = []; try { new PerformanceObserver((l) => {
    for (const e of l.getEntries()) window.__lt.push({ start: Math.round(e.startTime), dur: Math.round(e.duration) });
  }).observe({ type: 'longtask', buffered: true }); } catch (e) {}` });
  if (process.env.SEED) {
    // Same origin, a page with no script: storage set here is what the real load reads.
    await nav(new URL(url).origin + '/robots.txt', 100);
    await evaluate(`(() => { const s = ${process.env.SEED}; for (const k in s) localStorage.setItem(k, s[k]); return Object.keys(s).length; })()`);
    api = {};
  }
  const t0 = Date.now();
  await nav(url, 0);
  const loadMs = (loadedAt || Date.now()) - t0;
  const polls = [];
  const until = Date.now() + secs * 1000;
  while (Date.now() < until) {
    const s = Date.now();
    await evaluate('1 + 1');
    polls.push(Date.now() - s);
    await sleep(500);
  }
  const out = {
    url, loadMs, api,
    polls: polls.length, stalls: polls.filter((p) => p > STALL_MS).length, maxPollMs: Math.max(...polls),
    longtasks: await evaluate('window.__lt || []'),
    ls: await evaluate(LS), page: await evaluate(PAGE), errs: errs.slice(), after: null,
  };
  if (process.env.ACT) {
    const before = { ...api };
    await evaluate(`(() => { ${process.env.ACT} })()`);
    await sleep(3000);
    const delta = {};
    for (const k in api) if (api[k] !== before[k]) delta[k] = api[k] - (before[k] || 0);
    out.after = { api: delta, ls: await evaluate(LS), page: await evaluate(PAGE), errs: errs.slice(out.errs.length) };
  }
  console.log(JSON.stringify(out));
}

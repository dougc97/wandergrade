// rates_down_check.mjs — Top Picks when the live exchange rates fail (r10, app.js loadRates /
// renderRatesDown), in a real browser against a LOCAL server (it fetches the rates itself).
//   R_BASE=http://127.0.0.1:9000 R_CASE=down CDP_TIMEOUT=55 node cdp.mjs ./rates_down_check.mjs
// R_CASE (one per run, each well under the 60 s cap):
//   down       every /api/rates fails: the first paint (served rows or skeleton) holds through the quiet
//              retries, then ONE line where the list goes in the same room, no rows anywhere in Top
//              Picks, the value map not drawn; Try again with the rates back draws the full list there
//   transient  the first /api/rates fails and the retry 2 s later answers: the full list, the notice
//              never shown, nothing moved
//   ok         the rates answer: the list, one /api/rates request, no retry
// R_SEED  localStorage items before the load, string values ('{"fx_origin":"DE"}': a reader from Germany)
// R_W     viewport width (390 default, a phone; 1280 a desktop)
// Wikipedia/Wikimedia answers come from wikicache.mjs; nothing goes to production.
import { enableWikiCache } from './wikicache.mjs';
const BASE = process.env.R_BASE || 'http://127.0.0.1:9000', CASE = process.env.R_CASE || 'down';
const W = +process.env.R_W || 390;
const ok = (c, m) => console.log((c ? '  PASS  ' : '  FAIL  ') + m);

export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  let wiki = null, failing = CASE === 'down', failLeft = CASE === 'transient' ? 1 : 0;
  const asked = [];
  await enableWikiCache((m, p) => (m === 'Fetch.enable' ? Promise.resolve() : send(m, p)), (fn) => { wiki = fn; });
  on(async (d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const u = new URL(d.params.request.url);
    if (/wikipedia\.org$|wikimedia\.org$/.test(u.hostname)) return wiki(d);
    if (/(^|\.)wandergrade\.com$|onrender\.com$|cloudflareinsights|prf\.hn$|hostelworld/.test(u.hostname))
      return send('Fetch.failRequest', { requestId: d.params.requestId, errorReason: 'BlockedByClient' });
    if (u.pathname === '/api/rates') {
      const fail = failing || failLeft-- > 0;
      asked.push((fail ? 'failed ' : 'answered ') + (u.search || '(USD)'));
      if (fail) return send('Fetch.failRequest', { requestId: d.params.requestId, errorReason: 'Failed' });
    }
    return send('Fetch.continueRequest', { requestId: d.params.requestId });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  if (process.env.R_SEED) await send('Page.addScriptToEvaluateOnNewDocument', { source: `try { var s = ${process.env.R_SEED}; for (var k in s) localStorage.setItem(k, s[k]); } catch(e){}` });
  // What #topCards shows, each time it changes, with its height; and layout shift.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(function(){ window.__seen = []; window.__cls = 0; var last = '';
    new PerformanceObserver(function (l) { l.getEntries().forEach(function (e) { if (!e.hadRecentInput) window.__cls += e.value; }); }).observe({ type: 'layout-shift', buffered: true });
    setInterval(function () { var h = document.getElementById('topCards'); if (!h) return;
      var k = h.hasAttribute('data-ssr') ? 'served' : h.querySelector('table.skeleton:not([hidden])') ? 'skeleton'
        : h.querySelector('.ratesdown') ? 'notice' : 'rows:' + h.querySelectorAll('table.gradetable tbody tr').length;
      if (k !== last) { last = k; window.__seen.push([Math.round(performance.now()), k, Math.round(h.getBoundingClientRect().height)]); } }, 50); })();` });
  await setSize(W, W < 768 ? 844 : 900, W < 768);
  await nav(BASE + '/?cb=' + Date.now(), CASE === 'down' ? 11000 : 6000);
  const look = `(function(){ var h = document.getElementById('topCards');
    return { seen: window.__seen, cls: +window.__cls.toFixed(4), rows: h.querySelectorAll('table.gradetable:not(.skeleton) tbody tr').length,
      text: h.innerText.trim().replace(/\\s+/g, ' ').slice(0, 80), gems: document.querySelectorAll('#gemRows tbody tr').length,
      full: document.querySelectorAll('#valueRows tr').length, map: !!document.querySelector('#valueMap svg'), lastRates: !!lastRates }; })()`;
  const a = await evaluate(look);
  a.seen.forEach((x) => console.log('    ' + String(x[0]).padStart(6) + 'ms  ' + x[1] + '  ' + x[2] + 'px'));
  const kinds = a.seen.map((x) => x[1]);
  if (CASE === 'down') {
    const first = a.seen[0], notice = a.seen.find((x) => x[1] === 'notice');
    ok(kinds.length === 2 && (first[1] === 'served' || first[1] === 'skeleton') && notice,
       'the first paint, then the notice; never a partial list (' + kinds.join(' → ') + ')');
    ok(notice && notice[0] > 7000, 'the notice only after the quiet retries (' + (notice && notice[0]) + 'ms)');
    ok(notice && notice[2] === first[2], 'in the room the first paint had (' + (notice && notice[2]) + ' vs ' + first[2] + 'px)');
    ok(a.rows === 0 && a.gems === 0 && a.full === 1 && !a.map && a.text.startsWith("Live exchange rates didn't load. Try again"),
       'no rows in the picks, gems or full ranking, no value map; "' + a.text + '"');
    ok(asked.length === 3 && asked.every((x) => x.startsWith('failed')), 'three requests, ~2 s and ~6 s apart: ' + asked.join(', '));
    failing = false;
    await evaluate(`(function(){ document.getElementById('ratesRetry').click(); return 1; })()`);
    await sleep(4000);
    const b = await evaluate(look);
    const last = b.seen[b.seen.length - 1];
    ok(b.lastRates && b.rows >= 5 && b.full > 1 && b.map, 'Try again: the full list (' + b.rows + ' rows, full ranking ' + b.full + ', map drawn)');
    ok(last[2] === notice[2], 'in the same room (' + last[2] + 'px)');
  } else {
    ok(a.lastRates && a.rows >= 5 && !kinds.includes('notice'), 'the full list, the notice never shown (' + kinds.join(' → ') + ')');
    ok(asked.length === (CASE === 'transient' ? 2 : 1) || asked.length === (CASE === 'transient' ? 3 : 2),
       (CASE === 'transient' ? 'one failure, then the retry answered: ' : 'answered at once: ') + asked.join(', '));
  }
  ok(a.cls === 0, 'no layout shift (' + a.cls + ')');
  const own = errs.filter((e) => !/Failed to load resource.*\/api\/rates/.test(e));
  ok(own.length === 0, 'no console errors beyond the failed requests themselves' + (own.length ? ' ' + JSON.stringify(own) : ''));
};

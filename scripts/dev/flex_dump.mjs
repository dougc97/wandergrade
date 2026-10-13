// flex_dump.mjs — month mode's rendered Top Picks HTML (tables, map paths),
// written whole so two builds can be diffed on the SAME server's data (live
// FX differs between two servers by the minute). APPJS swaps in another
// app.js (e.g. main's) through request interception; OUT is the JSON file.
// Q adds to the query; LS is a JSON object of localStorage entries set before
// the page loads (a budget: LS='{"wg_budget":"700","wg_budgetdays":"10"}').
//   PORT=9351 APPJS=/path/to/main/public/app.js OUT=main.json node cdp.mjs ./flex_dump.mjs
import fs from 'node:fs';
const PORT = process.env.PORT || '9351';
export default async ({ send, on, evaluate, nav, sleep }) => {
  if (process.env.APPJS) {
    const body = fs.readFileSync(process.env.APPJS).toString('base64');
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/app.js*', requestStage: 'Request' }] });
    on((d) => { if (d.method === 'Fetch.requestPaused') send('Fetch.fulfillRequest', { requestId: d.params.requestId, responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/javascript; charset=utf-8' }], body }); });
  }
  if (process.env.LS) {
    await nav(`http://127.0.0.1:${PORT}/?tab=visited&cb=${Date.now()}`, 1500);
    await evaluate(`(() => { const o = ${process.env.LS}; for (const k in o) localStorage.setItem(k, o[k]); return 1; })()`);
  }
  await nav(`http://127.0.0.1:${PORT}/?tab=value${process.env.Q || ''}&cb=${Date.now()}`, 5000);
  await sleep(2000);
  if (process.env.FV) {
    const fv = fs.readFileSync(process.env.FV, 'utf8'), fl = fs.readFileSync(process.env.FL, 'utf8');
    await evaluate(`(() => { flightsData = ${fl}; flightValue = ${fv}; renderValue(); return 1; })()`);
    await sleep(2000);
  }
  const r = await evaluate(`(() => ({
    topCards: document.getElementById('topCards').innerHTML,
    gemRows: document.getElementById('gemRows').innerHTML,
    valueRows: document.getElementById('valueRows').innerHTML,
    notes: document.getElementById('picksNote').innerHTML + '|' + document.getElementById('valueMapTitle').textContent + '|' + document.getElementById('valueMapSub').dataset.tip + '|' + ((document.querySelector('.mappicksrow[data-for="valueMap"]') || {}).innerHTML || ''),
    url: location.search, build: typeof flexWindow,
    map: [...document.querySelectorAll('#valueMap path')].map((p) => p.outerHTML).join('\\n') }))()`);
  fs.writeFileSync(process.env.OUT, JSON.stringify(r));
  console.log('wrote', process.env.OUT);
};

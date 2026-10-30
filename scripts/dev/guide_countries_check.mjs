// guide_countries_check.mjs — the guide's country box holds only the country
// on show until a reader goes to pick another (app.js fillGuideCountries).
//
//   cd scripts/dev && BASE=http://127.0.0.1:9022 W=390 CDP_TIMEOUT=60 node cdp.mjs ./guide_countries_check.mjs
//
// A /guide/japan landing has one option; the box's first focus fills all 190
// and lists them; typing "tha" finds Thailand, and picking it opens Thailand's
// guide (Back returns to Japan's); from Peru's guide, Top Picks' map card for
// Japan ("Country guide →") opens Japan's, the box on Japan; Malta, which has
// no guide (/?tab=guide&gc=MT), leaves the box empty. No JS error. Every
// third-party request is refused (photos, Wikipedia: Wikimedia asks for at
// most 2 a second). Prints a PASS/FAIL line per step and a summary. On a
// server from before the change, or on this one run with FX_GUIDE_TEXTOUT=0
// (the box is held only on a guide served with #shellText), only the first
// line fails (190 options): every step a reader takes behaves the same.
const BASE = process.env.BASE || 'http://127.0.0.1:9022';
const W = +process.env.W || 1280;
export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  await setSize(W, W < 768 ? 844 : 900, W < 768);
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId;
    if (/^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(d.params.request.url)) send('Fetch.continueRequest', { requestId: id });
    else send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' });
  });
  const results = [];
  const ok = (c, m) => { results.push(!!c); console.log((c ? '  PASS  ' : '  FAIL  ') + m); };
  const waitFor = async (expr, ms = 20000) => {
    for (let t = 0; t < ms; t += 250) { if (await evaluate(`(() => !!(${expr}))()`) === true) return true; await sleep(250); }
    return false;
  };
  const open = async (url) => { await nav('about:blank', 100); await nav(url, 300); };
  const BOX = `(() => { const s = document.getElementById('bestCountry'), i = s.closest('.combo') && s.closest('.combo').querySelector('.combo-input');
    return { opts: s.options.length, value: s.value, input: i ? i.value : null, listed: document.querySelectorAll('#' + (i && i.getAttribute('aria-controls')) + ' .combo-opt[data-val]').length,
             open: i ? i.getAttribute('aria-expanded') : null, path: location.pathname + location.search,
             h1: (document.getElementById('guideH1') || {}).textContent || '' }; })()`;
  const focusBox = `(() => { document.getElementById('bestCountry').closest('.combo').querySelector('.combo-input').focus(); return 1; })()`;
  const e0 = errs.length;

  await open(`${BASE}/guide/japan`);
  await waitFor(`!document.getElementById('ssrGuide')`);
  await sleep(800);
  let b = await evaluate(BOX);
  ok(b.opts === 1 && b.value === 'JP' && b.input === 'Japan', `landing: 1 option, Japan chosen and shown (${b.opts}, ${b.value}, "${b.input}")`);
  await evaluate(focusBox);
  await sleep(400);
  b = await evaluate(BOX);
  ok(b.opts === 190 && b.listed === 190 && b.open === 'true' && b.value === 'JP', `first focus: all ${b.opts} options, ${b.listed} listed, still on Japan`);
  await evaluate(`(() => { const i = document.getElementById('bestCountry').closest('.combo').querySelector('.combo-input');
    i.value = 'tha'; i.dispatchEvent(new Event('input')); return 1; })()`);
  await sleep(300);
  const hits = await evaluate(`[...document.querySelectorAll('.combo-list:not([hidden]) .combo-opt[data-val]')].map((l) => l.textContent)`);
  ok(hits.includes('Thailand'), `"tha" lists Thailand (${hits.join(', ')})`);
  await evaluate(`(() => { const li = [...document.querySelectorAll('.combo-list:not([hidden]) .combo-opt[data-val]')].find((l) => l.textContent === 'Thailand');
    li.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); return 1; })()`);
  await waitFor(`location.pathname === '/guide/thailand' && /Thailand/.test((document.getElementById('guideH1') || {}).textContent)`, 10000);
  await evaluate(`document.activeElement && document.activeElement.blur()`);
  await sleep(600);
  b = await evaluate(BOX);
  ok(b.path === '/guide/thailand' && /Thailand/.test(b.h1) && b.value === 'TH' && b.input === 'Thailand', `picking it opens Thailand's guide (${b.path}, "${b.h1.slice(0, 40)}", box "${b.input}")`);
  await evaluate('history.back()');
  await waitFor(`location.pathname === '/guide/japan' && /Japan/.test((document.getElementById('guideH1') || {}).textContent)`, 10000);
  await sleep(600);
  b = await evaluate(BOX);
  ok(b.path === '/guide/japan' && /Japan/.test(b.h1) && b.value === 'JP' && b.input === 'Japan', `Back: Japan's guide, box on Japan (${b.path}, "${b.input}")`);

  await open(`${BASE}/guide/peru`);
  await waitFor(`!document.getElementById('ssrGuide')`);
  await evaluate(`document.querySelector('#tabs button[data-tab="value"]').click()`);
  await waitFor(`document.querySelector('#valueMap path[data-iso="JP"]')`, 20000);
  await evaluate(`showCountryCard('JP', document.getElementById('valueMap'))`);
  await waitFor(`document.querySelector('.countrycard [data-cc="todo"]')`, 10000);
  await evaluate(`document.querySelector('.countrycard [data-cc="todo"]').click()`);
  await waitFor(`location.pathname === '/guide/japan' && /Japan/.test((document.getElementById('guideH1') || {}).textContent)`, 10000);
  await sleep(600);
  b = await evaluate(BOX);
  ok(b.path.startsWith('/guide/japan') && b.value === 'JP' && b.input === 'Japan' && b.opts === 190,
     `Peru's guide → Top Picks → map card "Country guide →" Japan: Japan's guide, box on Japan, list filled (${b.path}, "${b.input}", ${b.opts})`);

  await open(`${BASE}/?tab=guide&gc=MT`);
  await waitFor(`/Malta/.test((document.getElementById('guideH1') || {}).textContent)`, 20000);
  await sleep(800);
  b = await evaluate(BOX);
  ok(/Malta/.test(b.h1) && b.value === '' && b.input === '', `Malta (no guide): its page, the box empty ("${b.h1.slice(0, 30)}", value "${b.value}", box "${b.input}")`);

  const e = errs.slice(e0).filter((x) => !/ERR_BLOCKED_BY_CLIENT/.test(x));
  ok(!e.length, `no JS error ${e.slice(0, 2).join(' | ')}`);
  console.log(`SUMMARY W=${W}: ${results.filter(Boolean).length}/${results.length} passed`);
};

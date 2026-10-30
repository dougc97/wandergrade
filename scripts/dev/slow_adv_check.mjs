// slow_adv_check.mjs — Data opened from a guide while /api/advisories is slow
// shows the currency table and "My currency" picker as a server from before
// the text-out does.
//
//   cd scripts/dev && BASE=http://127.0.0.1:9085 TEST=http://127.0.0.1:9086 W=1280 \
//     SLUGS=japan DELAY=12000 CDP_TIMEOUT=200 node cdp.mjs ./slow_adv_check.mjs
//
// A guide landing holds the hidden Data tab's table and picker back
// (app.js dataTabDeferred) and opening Currency then waits for the advisories
// with no time limit; the held rows and picker must come with the tab, as
// they stood before. Every /api/advisories answer is held DELAY ms (the
// server's own cold or expired cache, fetching upstream), third-party
// requests refused. Data is opened twice per guide and server:
//   late   7 s after the landing, renderRates' 2 s risk wait long over
//   early  the moment the guide has hydrated (the boot opens the guide tab
//          after the rates: a click before that is undone), inside that
//          wait (the click's read has no summary line yet)
// and read in the click's own task (what the first paint shows), 2.6 s later
// and once the advisories have landed. Each read must equal BASE's. Read the
// SUMMARY line: the exit status is always 0.
const BASE = process.env.BASE, TEST = process.env.TEST;
const SLUGS = (process.env.SLUGS || 'japan').split(/[\s,]+/).filter(Boolean);
const W = +process.env.W || 1280, H = W < 768 ? 844 : 900, DELAY = +process.env.DELAY || 12000;

const SNAP = `(() => { const rows = document.querySelectorAll('#rows tr'), sel = document.getElementById('dataBase');
  const combo = sel.closest('.combo');
  return { tab: document.documentElement.getAttribute('data-tab') + '/' + document.documentElement.getAttribute('data-dm'),
    rows: rows.length, shownRows: [...rows].filter((r) => r.getClientRects().length).length,
    firstRow: rows[0] ? rows[0].innerText.replace(/\\s+/g, ' ').trim().slice(0, 40) : '',
    baseOpts: sel.options.length, baseValue: sel.value, combo: !!combo, nativeShown: !!sel.getClientRects().length,
    comboInput: combo ? combo.querySelector('input').value : null,
    head: document.querySelector('#rates thead').innerText.replace(/\\s+/g, ' ').trim(),
    summary: document.getElementById('summary').innerText }; })()`;

export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  await setSize(W, H, W < 768);
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId, u = d.params.request.url;
    if (!/^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(u)) return send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' });
    if (/\/api\/advisories/.test(u)) return setTimeout(() => send('Fetch.continueRequest', { requestId: id }), DELAY);
    send('Fetch.continueRequest', { requestId: id });
  });
  const run = async (base, slug, mode) => {
    const out = {}, e0 = errs.length;
    await nav('about:blank', 50);
    const t0 = Date.now();
    await nav(`${base}/guide/${slug}`, 0);
    if (mode === 'early') {
      for (let t = 0; t < 10000; t += 20) {
        if (await evaluate(`/As of/.test(document.getElementById('asof').textContent) && !document.getElementById('ssrGuide')`) === true) break;
        await sleep(20);
      }
    } else await sleep(Math.max(0, 7000 - (Date.now() - t0)));
    out.click = await evaluate(`(() => { document.querySelector('#tabs button[data-tab="data"]').click(); return ${SNAP}; })()`);
    await sleep(2600);
    out.later = await evaluate(SNAP);
    await sleep(Math.max(0, DELAY - (Date.now() - t0) + 2500));
    out.landed = await evaluate(SNAP);
    out.errs = errs.slice(e0).filter((e) => !/ERR_BLOCKED_BY_CLIENT|favicon/.test(e));
    await evaluate(`(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} return 1; })()`);
    return out;
  };
  let ok = 0, n = 0;
  for (const slug of SLUGS) for (const mode of ['late', 'early']) {
    const b = await run(BASE, slug, mode), t = await run(TEST, slug, mode);
    for (const k of ['click', 'later', 'landed']) {
      n++;
      const same = JSON.stringify(b[k]) === JSON.stringify(t[k]) && !t.errs.length;
      if (same) ok++;
      console.log(same ? 'SAME' : 'DIFF', slug, mode, k, same ? JSON.stringify(t[k]) : '\n  base ' + JSON.stringify(b[k]) + '\n  test ' + JSON.stringify(t[k]));
    }
    if (t.errs.length) console.log('  js errors', t.errs.slice(0, 5));
  }
  console.log(`SUMMARY ${ok}/${n} reads equal with /api/advisories held ${DELAY} ms (W=${W})`);
};

// acct_save_check.mjs — the Wander List's "👤 Save this map" button follows the sign-in state as it
// changes, not only at the next redraw of the tab: signing out (the account panel's Sign out) brings
// it back at once, and a sign-in that /api/auth/me reports after the tab was drawn takes it away.
// Needs a server with accounts ON against the mock store and a session in it whose stored lists
// equal the seeded ones (so the sign-in merge changes nothing and redraws nothing):
//   /usr/bin/python3 scripts/mock_upstash.py 8931 &
//   UPSTASH_REDIS_REST_URL=http://127.0.0.1:8931 UPSTASH_REDIS_REST_TOKEN=mock RESEND_API_KEY=mock \
//     /usr/bin/python3 server.py 8950 &
//   (a session: accounts.save_user(<placeholder address>, lists FR,DE,IT,JP,PE) and
//    accounts._kv_set("sess:" + <sid>, <placeholder address>, 3600) in that store)
//   S_BASE=http://127.0.0.1:8950 S_SID=<sid> S_CASE=signout CDP_TIMEOUT=50 node cdp.mjs ./acct_save_check.mjs
// S_CASE signout (the default): signed in, open the account panel, Sign out; the button must show
//        right after, before anything else redraws the tab. A sign-out ends the session: make a new
//        one per run.
//        signin: signed in, but /api/auth/me held back S_HOLD ms (2500) so the tab draws first, signed
//        out as far as it knows; once the answer lands the button must be gone.
// Wikipedia/Wikimedia requests are blocked (the Wander List needs none). Prints PASS/FAIL lines; the
// cdp.mjs errors list must be empty too, but for /api/rates 500s on a server with no live rates.
const LIST = ["FR", "DE", "IT", "JP", "PE"];
export default async ({ send, on, evaluate, setSize, nav, sleep }) => {
  const base = process.env.S_BASE || 'http://127.0.0.1:8950', kase = process.env.S_CASE || 'signout';
  const hold = +(process.env.S_HOLD || 2500);
  const ok = (c, m) => console.log((c ? '  PASS  ' : '  FAIL  ') + m);
  await setSize(1280, 900);
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  await send('Network.setBlockedURLs', { urls: ['*wikimedia.org*', '*wikipedia.org*'] });
  await send('Network.setCookie', { name: 'wg_sess', value: process.env.S_SID || '', url: base, path: '/' });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.clear();
    localStorage.setItem("fx_visited", ${JSON.stringify(JSON.stringify(LIST))});
    localStorage.setItem("wg_acct", "in:" + (Date.now() + 864e5)); } catch (e) {}` });
  const me = { asked: 0, at: null };
  if (kase === 'signin') {
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/api/auth/me*', requestStage: 'Request' }] });
    on((d) => {
      if (d.method !== 'Fetch.requestPaused') return;
      me.asked++;
      setTimeout(() => { me.at = Date.now(); send('Fetch.continueRequest', { requestId: d.params.requestId }); }, hold);
    });
  }
  const look = `(function(){ const b = document.getElementById('visitedSave'), row = document.getElementById('visitedSaveRow');
    return { btn: !!b, label: b ? b.textContent : null, row: row ? row.innerHTML.length : -1,
      tab: (document.querySelector('#tabs button.active') || {}).dataset ? document.querySelector('#tabs button.active').dataset.tab : null,
      acctBtn: (document.getElementById('acctBtn') || {}).textContent || null,
      marked: document.querySelectorAll('#visitedChips .chip2').length }; })()`;
  const t0 = Date.now();
  await nav(base + '/?tab=visited&cb=' + t0, kase === 'signin' ? 900 : 2500);
  if (kase === 'signin') {
    const before = await evaluate(look);
    const early = me.at === null;
    ok(early && before && before.tab === 'visited' && before.marked === LIST.length && before.btn,
       `/api/auth/me not answered yet (${early}): the tab is drawn (${before && before.marked} marked), signed out as far as it knows, button shown (${JSON.stringify(before)})`);
    for (let i = 0; i < 40 && me.at === null; i++) await sleep(100);
    await sleep(600);
    const after = await evaluate(look);
    ok(me.asked === 1 && me.at !== null && after && !after.btn && after.row === 0 && after.acctBtn === '👤',
       `/api/auth/me answered signed in ${me.at ? me.at - t0 : '-'} ms after load: header shows 👤 and the button is gone (${JSON.stringify(after)})`);
    return;
  }
  const signedIn = await evaluate(look);
  ok(signedIn && signedIn.tab === 'visited' && signedIn.marked === LIST.length && !signedIn.btn && signedIn.acctBtn === '👤',
     `signed in: the tab is drawn (${signedIn && signedIn.marked} marked), no button (${JSON.stringify(signedIn)})`);
  const opened = await evaluate(`(function(){ document.getElementById('acctBtn').click(); return true; })()`);
  await sleep(500);
  const hasOut = await evaluate(`(function(){ return !!document.getElementById('acctOut'); })()`);
  ok(opened === true && hasOut === true, `the account panel opened with its Sign out button (${hasOut})`);
  await evaluate(`(function(){ document.getElementById('acctOut').click(); return true; })()`);
  await sleep(700);
  const out = await evaluate(look);
  ok(out && out.btn && out.label === '👤 Save this map' && /Save map/.test(out.acctBtn || ''),
     `signed out: the header says Save map and the button is back at once (${JSON.stringify(out)})`);
};

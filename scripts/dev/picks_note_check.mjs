// picks_note_check.mjs — Top Picks' notes for what the picks leave out: the ✓ been
// clause on the picks note, "Show more" hidden when nothing is left (keeping its
// room), and pointing at the gems when the popular list runs out.
//   BASE=http://127.0.0.1:9401 VISITED='["US","MX"]' Q='vr=AMER&vmf=1' PC=20 W=1280 node cdp.mjs ./picks_note_check.mjs
const BASE = process.env.BASE || 'http://127.0.0.1:9401';
const W = +(process.env.W || 1280);
export default async ({ evaluate, setSize, nav, sleep, shot, errs }) => {
  await setSize(W, 900, W < 768);
  await nav(BASE + '/?cb=' + Date.now(), 2500);
  await evaluate(`(() => { localStorage.setItem('fx_visited', JSON.stringify(${process.env.VISITED || '[]'})); localStorage.setItem('fx_pickcount', ${JSON.stringify(process.env.PC || '5')}); })()`);
  await nav(`${BASE}/?tab=value&${process.env.Q || ''}&cb=${Date.now()}`, 4000);
  for (let i = 0; i < 30; i++) { if (await evaluate(`(() => lastPicks.length > 0)()`)) break; await sleep(500); }
  await sleep(1500);
  const state = () => evaluate(`(() => { const sm = document.getElementById('showMore'), g = document.getElementById('gemsBox');
    return { rows: document.querySelectorAll('#topCards tbody tr').length, gems: lastGems.length, note: document.getElementById('picksNote').textContent.trim(),
      showMore: { hidden: sm.hidden, vis: getComputedStyle(sm).visibility, display: getComputedStyle(sm).display, text: sm.textContent, go: sm.dataset.go, h: Math.round(sm.getBoundingClientRect().height) },
      gemsTop: Math.round(g.getBoundingClientRect().top + scrollY), gemsOpen: g.open, been: document.getElementById('beenFilter').value, scrollY: Math.round(scrollY) }; })()`);
  console.log('LOAD', JSON.stringify(await state()));
  if (process.env.SHOT) console.log('shot', await shot(process.env.SHOT));
  if (process.env.CLICK === 'more') {
    await evaluate(`(() => document.getElementById('showMore').click())()`); await sleep(1500);
    console.log('AFTER showMore', JSON.stringify(await state()));
  }
  if (process.env.CLICK === 'been') {
    await evaluate(`(() => { const b = document.getElementById('showBeen'); if (b) b.click(); })()`); await sleep(1500);
    console.log('AFTER show', JSON.stringify(await state()), 'stored', await evaluate(`(() => localStorage.getItem('wg_showvisited'))()`));
  }
  console.log('errors', errs.length, errs.slice(0, 2));
};

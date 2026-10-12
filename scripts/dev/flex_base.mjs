// flex_base.mjs — Top Picks in month mode (the default): the top picks, the
// hidden gems and the tbody row heights, so a branch can be compared with main.
//
//   cd scripts/dev && PORT=9351 W=1280 H=900 CDP_TIMEOUT=50 node cdp.mjs ./flex_base.mjs
//
// PORT is the local server; W/H the viewport (375x812 runs as a phone).
const PORT = process.env.PORT || '9351';
const W = +(process.env.W || 1280), H = +(process.env.H || 900);
const SHOT = process.env.SHOT || '';

export default async ({ evaluate, setSize, nav, sleep, shot }) => {
  await setSize(W, H, W < 768);
  await nav(`http://127.0.0.1:${PORT}/?tab=value&cb=${Date.now()}`, 3500);
  let r = null;
  for (let i = 0; i < 30 && !r; i++) {
    r = await evaluate(`(() => {
      const trs = [...document.querySelectorAll('#topCards table.gradetable:not(.skeleton) tbody tr[data-iso]')];
      if (trs.length < 5) return null;
      const gems = [...document.querySelectorAll('#gemRows tbody tr[data-iso]')].map((t) => t.dataset.iso);
      const hs = trs.map((t) => Math.round(t.getBoundingClientRect().height * 10) / 10);
      const combo = document.querySelector('#valueMonth') && document.querySelector('#valueMonth').parentNode.querySelector('input.combo-input');
      return { month: document.getElementById('valueMonth').value, picks: trs.map((t) => t.dataset.iso), gems,
               heights: hs, combo: combo ? { value: combo.value, w: combo.clientWidth, sw: combo.scrollWidth } : null,
               title: document.getElementById('valueMapTitle').textContent, url: location.search,
               chips: trs.map((t) => [...t.querySelectorAll('td.dest .seastag')].map((c) => c.textContent.trim()).join(' | ')) };
    })()`);
    if (!r) await sleep(500);
  }
  console.log(JSON.stringify(r, null, 1));
  if (SHOT) console.log('shot', await shot(SHOT));
};

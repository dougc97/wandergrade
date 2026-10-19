// stay_chips_check.mjs — the "Where to stay" chips a guide draws, and its errors.
//   BASE=http://127.0.0.1:8872 SLUGS="ethiopia,rwanda" node cdp.mjs ./stay_chips_check.mjs
const BASE = process.env.BASE || 'https://wandergrade.com';
const SLUGS = (process.env.SLUGS || 'ethiopia').split(',');
export default async (t) => {
  const { evaluate, setSize, nav, sleep, errs } = t;
  await setSize(1280, 900, false);
  for (const slug of SLUGS) {
    await nav(`${BASE}/guide/${slug}?cb=${Date.now()}`, 6000);
    let r = null;
    for (let i = 0; i < 12; i++) {
      r = await evaluate(`(() => { const chips = [...document.querySelectorAll('#tab-guide .staychip, #tab-guide [data-stay]')].map(x => x.textContent.trim()); return { chips, nostay: document.getElementById('tab-guide')?.hasAttribute('data-nostay') }; })()`);
      if (r && r.chips.length) break;
      await sleep(700);
    }
    console.log(slug, JSON.stringify(r));
  }
  console.log('console errors', errs.length, JSON.stringify(errs.slice(0, 3)));
};

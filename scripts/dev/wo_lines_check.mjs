// wo_lines_check.mjs — the guide's 📍 lines as drawn (server stand-in vs app.js),
// their height swap, and a screenshot of the advisory block.
//   BASE=http://127.0.0.1:8871 SLUGS="benin,pakistan" node cdp.mjs ./wo_lines_check.mjs   (shots/wo-<slug>-<width>.png)
const BASE = process.env.BASE || 'https://wandergrade.com';
const SLUGS = (process.env.SLUGS || 'benin').split(',');
export default async (t) => {
  const { evaluate, setSize, nav, sleep, shot, errs } = t;
  for (const [w, h] of [[1280, 900], [390, 844]]) {
    await setSize(w, h, w < 500);
    for (const slug of SLUGS) {
      await nav(`${BASE}/guide/${slug}?cb=${Date.now()}`, 6000);
      let r = null;
      for (let i = 0; i < 15; i++) {
        r = await evaluate(`(() => { const el = document.getElementById('guideWatchouts'); const regs = el ? [...el.querySelectorAll('.woreg')].map(x => x.textContent.trim()) : []; return { regs, h: el ? el.offsetHeight : -1 }; })()`);
        if (r && r.regs.length) break;
        await sleep(800);
      }
      console.log(w, slug, 'h=' + (r && r.h), JSON.stringify(r && r.regs));
      await evaluate(`(() => { const el = document.getElementById('guideWatchouts'); if (el) el.scrollIntoView({block: 'center'}); return 1; })()`);
      await sleep(400);
      await shot(`wo-${slug}-${w}`);
    }
  }
  console.log('console errors', errs.length, JSON.stringify(errs.slice(0, 3)));
};

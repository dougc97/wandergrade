// hero_check.mjs — which lead images a guide's hero actually shows, and that
// the skip list bites.  BASE=http://127.0.0.1:8861 SLUGS="sri-lanka,philippines" node cdp.mjs ./hero_check.mjs
const BASE = process.env.BASE || 'https://wandergrade.com';
const SLUGS = (process.env.SLUGS || 'sri-lanka,philippines').split(',');
export default async (t) => {
  const { evaluate, setSize, nav, sleep, errs } = t;
  await setSize(1280, 900, false);
  for (const slug of SLUGS) {
    await nav(`${BASE}/guide/${slug}?cb=${Date.now()}`, 5000);
    let r = null;
    for (let i = 0; i < 12 && !(r && r.n); i++) {
      r = await evaluate(`(() => ({ n: (typeof heroUrls !== 'undefined' && heroUrls) ? heroUrls.length : 0, files: (typeof heroUrls !== 'undefined' && heroUrls) ? heroUrls.map(p => p.file) : [], thumbs: document.querySelectorAll('.actphoto img, .actthumb img, [class*="act"] img').length, h: (document.getElementById('guideHero') || {}).offsetHeight }))()`);
      if (!(r && r.n)) await sleep(1000);
    }
    const skipped = await evaluate(`(async () => { const s = await photoSkip(); const files = (typeof heroUrls !== 'undefined' && heroUrls) ? heroUrls.map(p => p.file) : []; return { skipSize: s.size, onList: files.filter(f => s.has(f)), galle: await wikiIconic('Galle Fort') }; })()`);
    console.log(slug, JSON.stringify(r), JSON.stringify(skipped));
  }
  console.log('console errors', errs.length, errs.slice(0, 3));
};

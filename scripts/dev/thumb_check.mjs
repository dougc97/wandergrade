// thumb_check.mjs — do a guide's "Top things to do" thumbnails load, and does
// any Wikimedia image request fail? Wikimedia rejects (400) thumbnail widths
// off its standard steps (https://w.wiki/GHai), so every thumb URL's width is
// listed too. The service worker is bypassed so a cached app.js can't answer.
//   BASE=http://127.0.0.1:8861 SLUGS="japan,ethiopia,chad" node cdp.mjs ./thumb_check.mjs
const BASE = process.env.BASE || 'https://wandergrade.com';
const SLUGS = (process.env.SLUGS || 'japan,ethiopia,chad').split(',');
const STEPS = new Set([20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920, 3840]);
export default async (t) => {
  const { send, on, evaluate, setSize, nav, sleep } = t;
  await send('Network.enable');
  await send('Network.setBypassServiceWorker', { bypass: true });
  await setSize(1280, 900, false);
  let bad = [];       // wikimedia responses >= 400, or requests that failed outright
  const urls = new Map();   // requestId -> url (wikimedia only)
  on((d) => {
    if (d.method === 'Network.requestWillBeSent' && /wikimedia\.org/.test(d.params.request.url)) urls.set(d.params.requestId, d.params.request.url);
    if (d.method === 'Network.responseReceived' && urls.has(d.params.requestId) && d.params.response.status >= 400)
      bad.push(d.params.response.status + ' ' + urls.get(d.params.requestId));
    if (d.method === 'Network.loadingFailed' && urls.has(d.params.requestId) && !d.params.canceled)
      bad.push('failed ' + d.params.errorText + ' ' + urls.get(d.params.requestId));
  });
  let total = 0;
  for (const slug of SLUGS) {
    bad = []; urls.clear();
    await nav(`${BASE}/guide/${slug}?cb=${Date.now()}`, 3000);
    let r = null;
    // Lazy thumbs only load in view: scroll each slot into view, then wait for every img to settle.
    for (let i = 0; i < 20; i++) {
      r = await evaluate(`(() => {
        const slots = [...document.querySelectorAll('#actDetail .actthumbslot[data-subj]')];
        const imgs = slots.map((s) => s.querySelector('img.actthumb')).filter(Boolean);
        imgs.forEach((im) => { im.loading = 'eager'; });
        return { slots: slots.length, imgs: imgs.map((im) => ({ src: im.currentSrc || im.src, w: im.naturalWidth, done: im.complete })) };
      })()`);
      if (r && r.slots && r.imgs.length && r.imgs.every((x) => x.done)) break;
      await sleep(1000);
    }
    await sleep(1500);   // let any onerror fallback land
    const w = (u) => +((u.match(/\/(\d+)px-/) || [])[1] || 0);
    const offStep = [...urls.values()].filter((u) => /\/thumb\//.test(u) && w(u) && !STEPS.has(w(u)));
    const loaded = r ? r.imgs.filter((x) => x.w > 0).length : 0;
    console.log(`${slug}: slots ${r && r.slots} imgs ${r && r.imgs.length} loaded ${loaded} | wikimedia 4xx/failed ${bad.length} | off-step widths ${offStep.length}`);
    for (const x of (r && r.imgs) || []) console.log(`   ${x.w ? 'ok  ' : 'FAIL'} natural ${x.w}px  ${x.src.slice(0, 140)}`);
    bad.forEach((b) => console.log('   BAD', b.slice(0, 180)));
    offStep.forEach((u) => console.log('   OFF-STEP', u.slice(0, 160)));
    total += bad.length + offStep.length + (r ? r.imgs.length - loaded : 1);
  }
  console.log(total ? `RESULT: ${total} problem(s)` : 'RESULT: all thumbnails loaded, no Wikimedia 4xx, every width on a standard step');
};

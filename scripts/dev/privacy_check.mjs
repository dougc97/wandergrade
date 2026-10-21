// privacy_check.mjs — /privacy, the homepage footer link and the PH/LK Vrbo buttons in headless Chrome.
// Usage: P_BASE=http://127.0.0.1:8881 P_STEP=privacy|footer|vrbo CDP_TIMEOUT=58 node cdp.mjs ./privacy_check.mjs
//   privacy  /privacy at 1280 and 390, light and dark: screenshots (shots/privacy-<w>-<scheme>.png), no
//            sideways scroll, one h1, the text and background colours of each scheme, every third-party
//            request host the page made (none expected; the beacon only runs with a CF token)
//   footer   the homepage footer's Privacy link (visible, /privacy) at 1280 and 390
//   vrbo     /guide/philippines and /guide/sri-lanka: the stays buttons in order and the Vrbo link's
//            host, path and aid, at 1280 (screenshot shots/vrbo-<slug>.png)
// P_W=390 runs the footer step at one width only. Navigation waits for the load event at most 20 s
// (cdp.mjs); a slow Wikimedia photo can take that long.
export default async ({ send, on, evaluate, setSize, scheme, nav, shot, sleep }) => {
  const B = process.env.P_BASE || 'http://127.0.0.1:8881';
  const step = process.env.P_STEP || 'privacy';
  await send('Network.enable');
  const third = new Set();
  on((d) => {
    if (d.method !== 'Network.requestWillBeSent') return;
    const u = new URL(d.params.request.url);
    if (u.protocol.startsWith('http') && !/^(localhost|127\.0\.0\.1)$/.test(u.hostname)) third.add(u.hostname);
  });
  if (step === 'privacy') {
    for (const [w, h, mobile] of [[1280, 900, false], [390, 844, true]]) {
      for (const dark of [false, true]) {
        await setSize(w, h, mobile); await scheme(dark);
        await nav(B + '/privacy?cb=' + w + dark, 1200);
        const r = await evaluate(`(() => { const b = getComputedStyle(document.body), h1 = document.querySelector('h1');
          return { theme: document.documentElement.getAttribute('data-theme'), sideways: document.documentElement.scrollWidth - innerWidth,
                   h1s: document.querySelectorAll('h1').length, h1: h1 && h1.textContent, h1weight: h1 && getComputedStyle(h1).fontWeight,
                   font: getComputedStyle(h1).fontFamily.split(',')[0], bg: b.backgroundColor, ink: b.color,
                   sections: document.querySelectorAll('.privacy section').length, height: document.documentElement.scrollHeight,
                   footerLink: !!document.querySelector('footer a[href="/privacy"]') }; })()`);
        console.log('privacy', w, dark ? 'dark' : 'light', JSON.stringify(r));
        await shot('privacy-' + w + '-' + (dark ? 'dark' : 'light'));
      }
    }
    console.log('third-party hosts requested:', [...third].sort().join(' ') || 'none');
  }
  if (step === 'footer') {
    for (const [w, h, mobile] of [[1280, 900, false], [390, 844, true]].filter(([w]) => !process.env.P_W || +process.env.P_W === w)) {
      await setSize(w, h, mobile); await scheme(false);
      await nav(B + '/?cb=f' + w, 2500);
      const r = await evaluate(`(() => { const a = document.querySelector('footer .disclosure a[href="/privacy"]');
        if (!a) return { link: false };
        a.scrollIntoView(); const rc = a.getBoundingClientRect();
        return { link: true, text: a.textContent, visible: rc.width > 0 && rc.height > 0, x: Math.round(rc.x), w: Math.round(rc.width),
                 line: a.parentElement.textContent.trim().slice(-60), sideways: document.documentElement.scrollWidth - innerWidth }; })()`);
      console.log('footer', w, JSON.stringify(r));
      await sleep(300); await shot('footer-' + w);
    }
  }
  if (step === 'vrbo') {
    await setSize(1280, 900, false); await scheme(false);
    for (const slug of ['philippines', 'sri-lanka']) {
      await nav(B + '/guide/' + slug + '?cb=v', 4000);
      const r = await evaluate(`(() => { const host = document.getElementById('guideStay');
        const btns = host ? [...host.querySelectorAll('a.staybtn')] : [];
        const v = btns.find((b) => /Vrbo/.test(b.textContent)); let q = null;
        if (v) { const u = new URL(v.href); q = { host: u.host, path: u.pathname, aid: u.searchParams.get('aid'), lat: u.searchParams.get('lat'),
                 checkin: u.searchParams.get('checkin'), rel: v.rel, target: v.target }; }
        if (host) host.scrollIntoView({ block: 'center' });
        return { labels: btns.map((b) => b.textContent.replace(/\\s*↗/, '').trim()), vrbo: q, near: host && (host.querySelector('.staynear') || {}).textContent }; })()`);
      console.log('vrbo', slug, JSON.stringify(r));
      await sleep(400); await shot('vrbo-' + slug);
    }
  }
};

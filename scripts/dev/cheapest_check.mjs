// cheapest_check.mjs — /cheapest/<month> and the /cheapest hub in headless Chrome.
// Usage: C_BASE=http://127.0.0.1:8881 C_PATH=/cheapest/november CDP_TIMEOUT=50 node cdp.mjs ./cheapest_check.mjs
// At 1280 and 390, light and dark: no sideways scroll, one h1, the table (1280) or cards (390), the
// rank visible once per row (the # column on a desktop, "1." in the name on a phone), the theme's
// background and text colours, the footer's two new links; screenshots shots/cheapest-<w>-<scheme>.png.
// Navigates with Page.navigate and polls for the h1 (no wait for network quiet).
export default async ({ send, evaluate, setSize, scheme, shot, sleep }) => {
  const B = process.env.C_BASE || 'http://127.0.0.1:8881';
  const P = process.env.C_PATH || '/cheapest/november';
  for (const [w, h, mobile] of [[1280, 900, false], [390, 844, true]]) {
    for (const dark of [false, true]) {
      await setSize(w, h, mobile); await scheme(dark);
      await send('Page.navigate', { url: B + P + '?cb=' + w + dark + Date.now() });
      for (let i = 0; i < 40; i++) {
        const ready = await evaluate(`(() => document.readyState === 'complete' && !!document.querySelector('.listpage h1'))()`);
        if (ready === true) break;
        await sleep(250);
      }
      await sleep(400);
      const r = await evaluate(`(() => {
        const b = getComputedStyle(document.body), row = document.querySelector('.listtable tbody tr');
        const num = row && row.querySelector('td.num'), rk = row && row.querySelector('.rk');
        const pill = row && row.querySelector('.lvl');
        return { theme: document.documentElement.getAttribute('data-theme'),
                 sideways: document.documentElement.scrollWidth - innerWidth,
                 h1s: document.querySelectorAll('h1').length, h1: (document.querySelector('h1') || {}).textContent,
                 rows: document.querySelectorAll('.listtable tbody tr').length,
                 rowDisplay: row && getComputedStyle(row).display,
                 numShown: !!num && getComputedStyle(num).display !== 'none',
                 rkShown: !!rk && getComputedStyle(rk).display !== 'none',
                 pillH: pill && Math.round(pill.getBoundingClientRect().height),
                 boxOverflow: (() => { const x = document.querySelector('.listbox'); return x ? x.scrollWidth - x.clientWidth : null; })(),
                 bg: b.backgroundColor, ink: b.color,
                 footer: ['/cheapest', '/dollar-strength'].every((u) => !!document.querySelector('footer a[href="' + u + '"]')),
                 height: document.documentElement.scrollHeight };
      })()`);
      console.log(P, w, dark ? 'dark' : 'light', JSON.stringify(r));
      await shot('cheapest-' + (P === '/cheapest' ? 'hub-' : '') + w + '-' + (dark ? 'dark' : 'light'));
    }
  }
};

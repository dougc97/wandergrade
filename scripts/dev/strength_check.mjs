// strength_check.mjs — /dollar-strength in headless Chrome.
// Usage: S_BASE=http://127.0.0.1:8882 CDP_TIMEOUT=55 node cdp.mjs ./strength_check.mjs
// At 1280 and 390, light and dark: no sideways scroll, one h1, the theme's colours,
// the index line's box (fixed height, so no layout shift: its height before and after
// load is the same) and stroke colour, the table as a table at 1280 and as cards at 390,
// the layout-shift total from a PerformanceObserver, and screenshots in
// shots/strength-<w>-<scheme>.png.
export default async ({ send, evaluate, setSize, scheme, nav, shot }) => {
  const B = process.env.S_BASE || 'http://127.0.0.1:8882';
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__cls = 0; try { new PerformanceObserver((l) => {
    for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: 'layout-shift', buffered: true }); } catch (e) {}` });
  for (const [w, h, mobile] of [[1280, 900, false], [390, 844, true]]) {
    for (const dark of [false, true]) {
      await setSize(w, h, mobile); await scheme(dark);
      await nav(B + '/dollar-strength?cb=' + w + dark, 1500);
      const r = await evaluate(`(() => {
        const b = getComputedStyle(document.body), h1 = document.querySelector('h1'), svg = document.querySelector('svg.dsline');
        const pl = svg && svg.querySelector('polyline'), tr = document.querySelector('.dstable tbody tr');
        const head = document.querySelector('.dstable thead');
        return { theme: document.documentElement.getAttribute('data-theme'), sideways: document.documentElement.scrollWidth - innerWidth,
          h1s: document.querySelectorAll('h1').length, h1: h1 && h1.textContent, h1weight: h1 && getComputedStyle(h1).fontWeight,
          bg: b.backgroundColor, ink: b.color, svgBox: svg && [Math.round(svg.getBoundingClientRect().width), Math.round(svg.getBoundingClientRect().height)],
          stroke: pl && getComputedStyle(pl).stroke, points: pl && pl.getAttribute('points').split(' ').length,
          rowDisplay: tr && getComputedStyle(tr).display, headShown: head && getComputedStyle(head).display !== 'none',
          rows: document.querySelectorAll('.dstable tbody tr').length, apart: document.querySelectorAll('.dsnone li').length,
          firstRow: tr && tr.innerText.replace(/\\s+/g, ' ').slice(0, 140), cls: +window.__cls.toFixed(4),
          height: document.documentElement.scrollHeight }; })()`);
      console.log(w, dark ? 'dark' : 'light', JSON.stringify(r));
      await shot('strength-' + w + '-' + (dark ? 'dark' : 'light'));
    }
  }
};

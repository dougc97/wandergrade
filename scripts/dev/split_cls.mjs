// split_cls.mjs — a guide's HTML arrives in two parts with a pause between them, cut just before
// M_SPLIT (a literal string of the page), so a frame is sure to paint between the two: the
// timing-dependent shift of a block placed in an earlier grid row than blocks the HTML sends first
// (a slow link shows it only now and then). A proxy on M_PROXY forwards everything else to the
// server on M_UP. Prints layout shifts and, frame by frame, each .guidegrid block's top and visibility.
// Usage: M_PROXY=8964 M_UP=8962 M_SLUG=puerto-rico M_SPLIT='<div class="staycol">' M_W=1280 M_H=900 \
//          CDP_TIMEOUT=28 node scripts/dev/cdp.mjs ./scripts/dev/split_cls.mjs
// Env: M_PAUSE (ms, 1500) M_MOBILE M_RUNS (2) M_WC=0 (no Wikimedia disk cache)
import http from 'node:http';
import { enableWikiCache, stats } from './wikicache.mjs';
const UP = process.env.M_UP, SPLIT = process.env.M_SPLIT, PAUSE = +process.env.M_PAUSE || 1500, PROXY = +process.env.M_PROXY;
const server = http.createServer(async (req, res) => {
  try {
    const r = await fetch(`http://127.0.0.1:${UP}${req.url}`, { headers: { 'Accept-Encoding': 'identity', 'User-Agent': req.headers['user-agent'] || '' } });
    const body = Buffer.from(await r.arrayBuffer());
    const ct = r.headers.get('content-type') || 'application/octet-stream';
    if (req.url.startsWith('/guide/') && ct.startsWith('text/html')) {
      const s = body.toString('utf8'), i = s.indexOf(SPLIT);
      res.writeHead(r.status, { 'Content-Type': ct, 'Cache-Control': 'no-store' });
      if (i < 0) { res.end(s); console.log('  SPLIT NOT FOUND'); return; }
      res.write(s.slice(0, i));
      setTimeout(() => res.end(s.slice(i)), PAUSE);
      return;
    }
    res.writeHead(r.status, { 'Content-Type': ct, 'Cache-Control': 'no-store' });
    res.end(body);
  } catch (e) { res.writeHead(502); res.end(String(e)); }
});
await new Promise((ok) => server.listen(PROXY, '127.0.0.1', ok));
export default async ({ send, on, evaluate, setSize, sleep }) => {
  if (process.env.M_WC !== '0') await enableWikiCache(send, on);
  const w = +process.env.M_W || 1280, h = +process.env.M_H || 900, runs = +process.env.M_RUNS || 2;
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `if (location.port === '${PROXY}') {
    window.__shifts = []; window.__cls = 0; window.__frames = [];
    new PerformanceObserver((l) => { for (const e of l.getEntries()) { if (e.hadRecentInput) continue; window.__cls += e.value;
      window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map((s) => s.node ? (s.node.id ? '#' + s.node.id : s.node.nodeName + '.' + (typeof s.node.className === 'string' ? s.node.className : '')) : '?').slice(0, 4),
        rect: (e.sources || []).slice(0, 2).map((s) => [Math.round(s.previousRect.y), Math.round(s.currentRect.y)]) }); } }).observe({ type: 'layout-shift', buffered: true });
    let last = '';
    const tick = () => { const g = document.querySelector('.guidegrid');
      if (g) { const parts = [...g.children].filter((c) => c.id || c.className).map((c) => (c.id ? '#' + c.id : '.' + c.className.split(' ')[0]) + '@' + Math.round(c.getBoundingClientRect().top + scrollY) + (getComputedStyle(c).visibility === 'hidden' ? '(hidden)' : ''));
        const k = parts.join(' '); if (k !== last) { window.__frames.push(Math.round(performance.now()) + ' ' + k); last = k; } }
      if (performance.now() < 8000) requestAnimationFrame(tick); };
    requestAnimationFrame(tick); }` });
  await setSize(w, h, process.env.M_MOBILE === '1');
  await send('Network.enable'); await send('Network.setCacheDisabled', { cacheDisabled: true });
  const out = [];
  for (let i = 0; i < runs; i++) {
    await send('Page.navigate', { url: `http://127.0.0.1:${PROXY}/guide/${process.env.M_SLUG}` });
    await sleep(PAUSE + 5000);
    out.push(await evaluate(`(function(){ return { cls: +window.__cls.toFixed(4), shifts: window.__shifts, frames: window.__frames }; })()`));
    await send('Page.navigate', { url: 'about:blank' }); await sleep(300);
  }
  console.log(JSON.stringify({ up: UP, slug: process.env.M_SLUG, split: SPLIT, pause: PAUSE, w, h, cls: out.map((o) => o && o.cls) }));
  console.log('  wikicache', JSON.stringify(stats));
  for (const o of out) {
    if (!o || o.EXC) { console.log('  EXC', o && o.EXC); continue; }
    for (const s of o.shifts) console.log('   shift', JSON.stringify(s));
    for (const f of o.frames.slice(0, 6)) console.log('   frame', f);
  }
  server.close();
};

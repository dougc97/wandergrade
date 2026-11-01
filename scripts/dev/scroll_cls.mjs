// scroll_cls.mjs — a reader who scrolls to the bottom of a page before it has finished loading
// (M_AT ms after it first has the newsletter box and can scroll), then stays: layout shifts (sources +
// rects) and every move of #subscribe's on-screen top, frame by frame — a scroll the page causes
// moves the box on screen without any CLS (Chrome takes scrolling out of the score), so both count.
// Usage: M_URL=http://127.0.0.1:8962/guide/ethiopia M_W=390 M_H=844 M_MOBILE=1 M_NET=150,1600 M_CPU=4 \
//          M_RUNS=2 M_SETTLE=7000 CDP_TIMEOUT=55 node scripts/dev/cdp.mjs ./scripts/dev/scroll_cls.mjs
// Env: M_AT (ms, default 200) M_SETTLE (ms after load, default 9000) M_DEBUG=1 (the crawler block's room
// and the activity photos as they change) M_WC=0 (no Wikimedia disk cache, wikicache.mjs)
import { enableWikiCache, stats } from './wikicache.mjs';
export default async ({ send, on, evaluate, setSize, sleep }) => {
  if (process.env.M_WC !== '0') await enableWikiCache(send, on);
  const url = process.env.M_URL, w = +process.env.M_W || 390, h = +process.env.M_H || 844;
  const mobile = process.env.M_MOBILE === '1', cpu = +process.env.M_CPU || 1, runs = +process.env.M_RUNS || 2;
  const at = +(process.env.M_AT || 200), settle = +process.env.M_SETTLE || 9000;
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `if (location.protocol.startsWith('http')) {
    window.__cls = 0; window.__shifts = []; window.__moves = []; window.__scrolled = null;
    new PerformanceObserver((l) => { for (const e of l.getEntries()) { if (e.hadRecentInput) continue; window.__cls += e.value;
      window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4),
        src: (e.sources || []).map((s) => { const n = s.node; if (!n) return '?'; return n.id ? '#' + n.id : (n.nodeName + '.' + (typeof n.className === 'string' ? n.className : '')).slice(0, 40) + (n.textContent ? ' "' + n.textContent.trim().slice(0, 30) + '"' : ''); }).slice(0, 4),
        rect: (e.sources || []).slice(0, 4).map((s) => s.previousRect && s.currentRect ? [Math.round(s.previousRect.y), Math.round(s.currentRect.y), Math.round(s.previousRect.height), Math.round(s.currentRect.height)] : null) }); } })
      .observe({ type: 'layout-shift', buffered: true });
    let last = null;
    const tick = () => { const s = document.getElementById('subscribe');
      if (s) { const top = Math.round(s.getBoundingClientRect().top); const sy = Math.round(scrollY); const dh = document.documentElement.scrollHeight;
        if (last === null || Math.abs(top - last.top) > 1) { window.__moves.push({ t: Math.round(performance.now()), top, sy, dh, ssr: !!document.getElementById('ssrGuide') || !!document.querySelector('.ssrguide') }); }
        last = { top }; }
      requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    // M_AT ms after the page first has the newsletter box and can scroll: the reader goes to the bottom
    const iv = setInterval(() => { const s = document.getElementById('subscribe');
      if (!s || document.documentElement.scrollHeight < innerHeight + 300) return; clearInterval(iv);
      const ready = Math.round(performance.now());
      setTimeout(() => { window.scrollTo(0, 1e9); window.__scrolled = { ready, t: Math.round(performance.now()), sy: Math.round(scrollY), dh: document.documentElement.scrollHeight, rs: document.readyState }; }, ${at}); }, 20);
    window.__dbg = [];
    new MutationObserver((ms) => { for (const m of ms) {
      if (m.type === 'attributes' && m.target.classList && m.target.classList.contains('ssrguide')) window.__dbg.push([Math.round(performance.now()), 'room', m.target.style.height]);
      if (m.type === 'childList') for (const n of m.addedNodes) if (n.nodeType === 1 && n.classList.contains('actthumb')) window.__dbg.push([Math.round(performance.now()), 'thumb', document.getElementById('actDetail').offsetHeight]);
      if (m.type === 'childList') for (const n of m.removedNodes) if (n.nodeType === 1 && n.classList && n.classList.contains('ssrguide')) window.__dbg.push([Math.round(performance.now()), 'room removed']);
    } }).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] });
    addEventListener('scroll', () => { (window.__sc = window.__sc || []).push([Math.round(performance.now()), Math.round(scrollY), document.documentElement.scrollHeight]); }, { passive: true });
  }` });
  await setSize(w, h, mobile);
  if (process.env.M_NET) { const [lat, kbps] = process.env.M_NET.split(',').map(Number);
    await send('Network.enable'); await send('Network.setCacheDisabled', { cacheDisabled: true });
    await send('Network.emulateNetworkConditions', { offline: false, latency: lat, downloadThroughput: kbps * 1000 / 8, uploadThroughput: kbps * 1000 / 8 }); }
  if (cpu > 1) await send('Emulation.setCPUThrottlingRate', { rate: cpu });
  const out = [];
  for (let i = 0; i < runs; i++) {
    await send('Page.navigate', { url });
    const t0 = Date.now();
    // poll for load (fare fetches may never finish: no network-quiet wait)
    while (Date.now() - t0 < 20000) { const rs = await evaluate(`(function(){ return document.readyState; })()`); if (rs === 'complete') break; await sleep(250); }
    await sleep(settle);
    const r = await evaluate(`(function(){ return { cls: +(window.__cls || 0).toFixed(4), shifts: window.__shifts, moves: window.__moves, scrolled: window.__scrolled, endSy: Math.round(scrollY), sc: (window.__sc || []).slice(0, 12), dbg: window.__dbg, endDh: document.documentElement.scrollHeight }; })()`);
    out.push(r);
    await evaluate(`(function(){ try { localStorage.clear(); sessionStorage.clear(); } catch(e){} return 1; })()`);
    await send('Page.navigate', { url: 'about:blank' }); await sleep(300);
  }
  const vals = out.map((o) => (o && o.cls) || 0);
  console.log(JSON.stringify({ url, w, h, mobile, cpu, at, cls: vals }));
  console.log('  wikicache', JSON.stringify(stats));
  for (const o of out) {
    if (!o || o.EXC) { console.log('  EXC', o && o.EXC); continue; }
    console.log('  scrolled', JSON.stringify(o.scrolled), 'end sy', o.endSy, 'dh', o.endDh);
    for (const s of o.shifts) console.log('   shift', JSON.stringify(s));
    console.log('   scroll events', JSON.stringify(o.sc)); console.log('   subscribe moves', JSON.stringify(o.moves.slice(0, 14))); if (process.env.M_DEBUG) console.log('   dbg', JSON.stringify(o.dbg));
  }
};

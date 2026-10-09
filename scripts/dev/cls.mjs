// cls.mjs — in-page layout shift (CLS) for one URL under one viewport, network and CPU profile.
// Usage: M_URL=http://127.0.0.1:8901/?tab=visited M_W=390 M_H=844 M_MOBILE=1 M_NET=150,1600 CDP_TIMEOUT=58 node cdp.mjs ./cls.mjs
//   M_W/M_H/M_MOBILE  viewport (mobile=1 adds touch + a phone UA)     M_RUNS  loads (default 3; the median is printed)
//   M_NET=latencyMs,kbps  emulate a slow link, cache off — on localhost every asset is there before
//                     first paint and nothing shifts, so the production shifts only show with this
//   M_CPU=4           Emulation.setCPUThrottlingRate                   M_SETTLE  ms to wait after load (default 3500)
//   M_SEED='{"fx_visited":["FR"]}'  localStorage before each load (a returning visitor)
//   M_KEEP=1          keep localStorage between runs (default: cleared, a cold visitor every run)
// Prints one JSON line (the per-run CLS values and their median), then each run's shifts: time,
// value, the first three source nodes and the first source's [prevY, newY, prevH, newH].
export default async ({ send, evaluate, setSize, nav, sleep }) => {
  const url = process.env.M_URL, w = +process.env.M_W || 390, h = +process.env.M_H || 844;
  const mobile = process.env.M_MOBILE === '1', cpu = +process.env.M_CPU || 1, runs = +process.env.M_RUNS || 3;
  const settle = +process.env.M_SETTLE || 3500;
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__cls = 0; window.__shifts = []; new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) { window.__cls += e.value; window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map((s) => (s.node && (s.node.id ? '#' + s.node.id : s.node.tagName + '.' + (s.node.className || ''))) || '?').slice(0, 3), rect: (e.sources || []).slice(0,1).map((s) => s.previousRect && s.currentRect ? [s.previousRect.y, s.currentRect.y, s.previousRect.height, s.currentRect.height] : null) }); } }).observe({ type: 'layout-shift', buffered: true });` });
  // M_SEED: JSON object of localStorage items to set before each load (a returning visitor).
  if (process.env.M_SEED) await send('Page.addScriptToEvaluateOnNewDocument', { source: `try { var s = ${process.env.M_SEED}; for (var k in s) localStorage.setItem(k, JSON.stringify(s[k])); } catch(e){}` });
  await setSize(w, h, mobile);
  // M_NET=latencyMs,kbps : emulate a slow link (production assets arrive late; localhost never does).
  if (process.env.M_NET) { const [lat, kbps] = process.env.M_NET.split(',').map(Number);
    await send('Network.enable'); await send('Network.setCacheDisabled', { cacheDisabled: true });
    await send('Network.emulateNetworkConditions', { offline: false, latency: lat, downloadThroughput: kbps * 1000 / 8, uploadThroughput: kbps * 1000 / 8 }); }
  if (cpu > 1) await send('Emulation.setCPUThrottlingRate', { rate: cpu });
  const out = [];
  for (let i = 0; i < runs; i++) {
    await nav(url, settle);
    const r = await evaluate(`(function(){ return { cls: +window.__cls.toFixed(4), shifts: window.__shifts }; })()`);
    out.push(r);
    if (process.env.M_KEEP !== '1') await evaluate(`(function(){ try { localStorage.clear(); sessionStorage.clear(); } catch(e){} return 1; })()`);
    await nav('about:blank', 200);
  }
  const vals = out.map((o) => (o && o.cls) || 0).sort((a, b) => a - b);
  console.log(JSON.stringify({ url, w, h, mobile, cpu, cls: vals, median: vals[Math.floor(vals.length / 2)] }));
  for (const o of out) console.log('  ' + JSON.stringify(o && o.shifts));
};

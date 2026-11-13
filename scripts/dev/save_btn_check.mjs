// save_btn_check.mjs — the Wander List's "👤 Save this map" button in a real browser: where it sits
// (over the map's top-right corner from 561px up, its own line above the map on phones), that it is
// one element, takes no map clicks outside its box, keeps the Tab order and a visible focus ring,
// stays out of full screen and the share image, follows marking/unmarking, and that the first paint
// (app.js blocked) holds exactly the room the button will take (the save line, and a stats floor
// the drawn stats never fall short of). For a new visitor it taps a country on the map for real
// (touch on a phone) and checks the map stays under the finger while the phone's save line opens
// above it, and that a second tap at the same spot unmarks that country.
// Needs a server with accounts ON (the button's rule includes ACCT_ON), e.g. against the mock store:
//   /usr/bin/python3 scripts/mock_upstash.py 8931 &
//   UPSTASH_REDIS_REST_URL=http://127.0.0.1:8931 UPSTASH_REDIS_REST_TOKEN=mock RESEND_API_KEY=mock \
//     /usr/bin/python3 server.py 8950 &
//   S_BASE=http://127.0.0.1:8950 S_W=1280 CDP_TIMEOUT=55 node cdp.mjs ./save_btn_check.mjs
// S_W   viewport width (<=560 runs as a phone: touch, phone UA, 2x)   S_DARK=0  light theme (default dark)
// S_CASE returning (34 marks, signed out; the default) | new (nothing marked) | signed (34 marks and a
//        session: S_SID = a session id in that store, which also sets the head script's wg_acct flag)
//        | shared (nothing marked, opening a shared ?v= map of 5 countries, signed out)
// Prints PASS/FAIL lines and exits the page; the cdp.mjs errors list must be empty too.
const LIST = ["AR","AT","BS","BO","BA","BR","CA","CL","CN","CO","CZ","DO","GB-ENG","FR","DE","GR","GT","HU","IS","IT",
  "JP","MX","MA","PE","PL","PT","PR","SK","ES","SE","CH","TH","US","VN"];
const SHARED = "FR,DE,IT,JP,PE";
export default async ({ send, evaluate, setSize, scheme, nav, sleep }) => {
  const base = process.env.S_BASE || 'http://127.0.0.1:8950', W = +(process.env.S_W || 1280), phone = W <= 560;
  const kase = process.env.S_CASE || 'returning';
  const url = () => base + '/?tab=visited' + (kase === 'shared' ? '&v=' + SHARED : '') + '&cb=' + Date.now();
  const results = [];
  const ok = (c, m) => { results.push(!!c); console.log((c ? '  PASS  ' : '  FAIL  ') + m); };
  await setSize(W, phone ? 844 : 900, phone);
  await scheme(process.env.S_DARK !== '0');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  if (kase === 'signed') await send('Network.setCookie', { name: 'wg_sess', value: process.env.S_SID || '', url: base, path: '/' });
  const seed = kase === 'new' || kase === 'shared' ? '' : `localStorage.setItem("fx_visited", ${JSON.stringify(JSON.stringify(LIST))});`
    + (kase === 'signed' ? `localStorage.setItem("wg_acct", "in:" + (Date.now() + 864e5));` : '');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.clear(); ${seed} } catch (e) {}` });
  const geo = `(function(){ const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
      return { t: +b.top.toFixed(1), b: +b.bottom.toFixed(1), l: +b.left.toFixed(1), r: +b.right.toFixed(1), h: +b.height.toFixed(1), w: +b.width.toFixed(1) }; };
    const sv = document.getElementById('visitedSaveRow'), map = document.getElementById('visitedMap');
    return { acct: window.__WGACCT__, vis: document.documentElement.getAttribute('data-vis'),
      save: r(sv), map: r(map), btn: r(document.getElementById('visitedSave')), tip: r(sv && sv.querySelector('.muted')),
      zoom: r(map && map.querySelector('.mapzoom')), fs: r(map && map.querySelector('.mapzoom [data-z="fs"]')),
      disp: sv && getComputedStyle(sv).display, pos: sv && getComputedStyle(sv).position,
      chips: r(document.getElementById('visitedChips')), stats: r(document.getElementById('visitedStats')),
      tab: r(document.getElementById('tab-visited')),
      n: { btn: document.querySelectorAll('#visitedSave').length, vsave: document.querySelectorAll('.vsave').length,
           inStats: document.querySelectorAll('#visitedStats .vsave, #visitedStats #visitedSave').length },
      words: sv && sv.querySelector('.muted') ? sv.querySelector('.muted').getAttribute('data-tip') : null,
      label: document.getElementById('visitedSave') ? document.getElementById('visitedSave').textContent : null }; })()`;

  // 1. First paint: app.js blocked, so the page stays as served (head scripts and CSS only).
  await send('Network.setBlockedURLs', { urls: ['*/app.js*'] });
  await nav(url(), 800);
  const first = await evaluate(geo);
  await send('Network.setBlockedURLs', { urls: [] });
  // 2. The page once app.js has drawn the tab.
  await nav(url(), 2500);
  const g = await evaluate(geo);
  if (!g || g.EXC) { ok(false, 'page geometry ' + JSON.stringify(g)); return; }
  ok(g.acct === true, 'accounts are on (window.__WGACCT__) — the button needs them');
  const shows = kase === 'returning' || kase === 'shared', count = kase === 'shared' ? 5 : 34;
  const held = shows && phone;     // the phone line, reserved from first paint
  // server.py VISITED_HOLD: v been (the shared map's when there is one), c a UN member among them, s the button.
  const vis = { returning: 'vcs', shared: 'vcs', signed: 'vc', new: null }[kase];
  ok(first && first.vis === vis, `first paint: data-vis ${first && first.vis} (want ${vis})`);
  ok(first && first.disp === (held ? 'flex' : 'none') && Math.abs((first.save ? first.save.h : 0) - (held ? 32 : 0)) < 0.6,
     `first paint: the save line is ${held ? 'held 32px tall' : 'not there'} (display ${first && first.disp}, ${first && first.save && first.save.h}px)`);
  // The tab itself may move on a shared map (the "Viewing a shared map" notice above it), so measure the map within it.
  const rel = (x) => x && x.map && x.tab ? +(x.map.t - x.tab.t).toFixed(1) : null;
  ok(first && first.map && Math.abs(rel(first) - rel(g)) < 0.6 && (kase === 'shared' || Math.abs(first.map.t - g.map.t) < 0.6),
     `the map doesn't move between first paint and app.js (${first && first.map && first.map.t} -> ${g.map.t}; in the tab ${rel(first)} -> ${rel(g)})`);
  // Floors, not estimates: what app.js draws is never shorter than what the first paint held.
  ok(first && first.stats && g.stats.h >= first.stats.h - 0.6,
     `the stats floor is never hollow (held ${first && first.stats && first.stats.h}px, drawn ${g.stats.h}px)`);
  ok(g.n.vsave === 1 && g.n.btn === (shows ? 1 : 0) && g.n.inStats === 0,
     `one .vsave, ${shows ? 'one button' : 'no button'}, nothing in the stats column ${JSON.stringify(g.n)}`);
  if (!shows) {
    ok(g.disp === 'none' && g.save.h === 0, `no button: the row takes no room (display ${g.disp}, ${g.save.h}px)`);
    if (kase === 'new') {
      // A real tap on Brazil (touch on a phone), from the top of the page and from part way down: the
      // map stays under the finger (on a phone the page scrolls by the save line that opens above it),
      // and a second tap at the same spot unmarks Brazil rather than hitting whatever slid under it.
      const tap = async (x, y) => {
        if (phone) { await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
                     await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); }
        else { await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
               await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }); }
        await sleep(600);
      };
      const at = `(function(){ const m = document.getElementById('visitedMap').getBoundingClientRect();
        const p = document.querySelector('#visitedMap path[data-iso="BR"]').getBoundingClientRect();
        return { mapT: +m.top.toFixed(1), y: Math.round(scrollY), br: [Math.round(p.left + p.width / 2), Math.round(p.top + p.height / 2)],
                 marks: JSON.parse(localStorage.getItem('fx_visited') || '[]'), btn: !!document.getElementById('visitedSave') }; })()`;
      for (const start of [0, 200]) {
        await evaluate(`(function(){ window.scrollTo(0, ${start}); return 1; })()`);
        await sleep(200);
        const a = await evaluate(at);
        await tap(...a.br);
        const b = await evaluate(at);
        await tap(...a.br);
        const c = await evaluate(at);
        const line = phone ? 40 : 0;
        ok(Math.abs(b.mapT - a.mapT) < 0.6 && b.y - a.y === line && b.btn && JSON.stringify(b.marks) === '["BR"]'
           && Math.abs(c.mapT - a.mapT) < 0.6 && c.y === a.y && !c.btn && c.marks.length === 0,
           `from scrollY ${start}: the first mark keeps the map put (top ${a.mapT} -> ${b.mapT}, scrollY ${a.y} -> ${b.y}, button ${b.btn}), `
           + `a 2nd tap there unmarks it (marks ${JSON.stringify(c.marks)}, top ${c.mapT}, scrollY ${c.y})`);
      }
    }
  } else {
    ok(g.label === '👤 Save this map' && new RegExp(`^Saved in this browser only\\. Sign in to keep your ${count} been on every device\\.$`).test(g.words || ''),
       `label and ⓘ words as before ("${g.label}", "${g.words}")`);
    // Over the map: a 32px card pill (the zoom buttons' height), the button 3px inside its edge, so the
    // light theme's button green never runs into a marked country's (the same #0a7d28). Phones: 32px button.
    const fr = await evaluate(`(function(){ const s = getComputedStyle(document.getElementById('visitedSaveRow'));
      const z = document.querySelector('#visitedMap .mapzoom button'); return { bg: s.backgroundColor, zbg: z && getComputedStyle(z).backgroundColor,
      btnBg: getComputedStyle(document.getElementById('visitedSave')).backgroundColor }; })()`);
    if (!phone)
      ok(Math.abs(g.save.h - 32) < 0.6 && Math.abs(g.btn.h - 26) < 0.6 && Math.abs(g.btn.t - g.save.t - 3) < 0.6
         && Math.abs(g.save.b - g.btn.b - 3) < 0.6 && Math.abs(g.btn.l - g.save.l - 3) < 0.6 && fr.bg === fr.zbg && fr.bg !== fr.btnBg,
         `a 32px pill like the map buttons, the button framed 3px inside it in the zoom buttons' colour (pill ${g.save.h}, button ${g.btn.h} at +${(g.btn.t - g.save.t).toFixed(1)}/+${(g.btn.l - g.save.l).toFixed(1)}, ${fr.bg} vs zoom ${fr.zbg})`);
    else
      ok(Math.abs(g.btn.h - 32) < 0.6 && Math.abs(g.save.h - 32) < 0.6, `32px tall like the map buttons (button ${g.btn.h}, row ${g.save.h})`);
    if (kase === 'shared') {
      const passed = results.filter(Boolean).length;
      console.log(`${passed}/${results.length} passed (${kase}, ${W}px, ${process.env.S_DARK === '0' ? 'light' : 'dark'})`);
      return;
    }
    if (!phone) {
      ok(g.pos === 'absolute', 'over the map: absolutely positioned (moves nothing)');
      ok(Math.abs(g.save.t - g.map.t - 10) < 0.6 && Math.abs(g.save.t - g.fs.t) < 0.6,
         `top edge 10px into the map, level with the full-screen button (${(g.save.t - g.map.t).toFixed(1)}, fs ${(g.fs.t - g.map.t).toFixed(1)})`);
      ok(Math.abs(g.map.r - g.save.r - 50) < 0.6 && Math.abs(g.zoom.l - g.save.r - 8) < 0.6,
         `right 50px: 8px left of the zoom column (${(g.map.r - g.save.r).toFixed(1)}, gap ${(g.zoom.l - g.save.r).toFixed(1)})`);
      // Map clicks around the box reach the map; inside it, the button or the ⓘ.
      const hits = await evaluate(`(function(){ const s = document.getElementById('visitedSaveRow').getBoundingClientRect();
        const at = (x, y) => { const e = document.elementFromPoint(x, y); return e ? (e.closest('#visitedSave') ? 'btn' : e.closest('#visitedSaveRow .muted') ? 'info' : e.closest('#visitedSaveRow') ? 'pill' : e.closest('.mapzoom') ? 'zoom' : e.closest('#visitedMap') ? 'map' : e.tagName) : null; };
        const my = s.top + s.height / 2, b = document.getElementById('visitedSave').getBoundingClientRect();
        return { left: at(s.left - 2, my), below: at(s.left + s.width / 2, s.bottom + 2), above: at(s.left + s.width / 2, s.top - 2),
                 gap: at(s.right + 4, my), right: at(s.right + 1, my), btn: at(s.left + 10, my), info: at(s.right - 3, my),
                 inTop: at(s.right - 3, s.top + 1), inBottom: at(s.right - 3, s.bottom - 1),
                 // the 3px frame round the button is the button's too
                 frameLeft: at(s.left + 1, my), frameTop: at(s.left + 20, s.top + 1), frameBottom: at(b.right - 2, s.bottom - 1),
                 between: at(b.right + 3, my) }; })()`);
      ok(hits.left === 'map' && hits.below === 'map' && hits.above === 'map' && hits.gap === 'map' && hits.right === 'map'
         && hits.btn === 'btn' && hits.info === 'info' && hits.inTop === 'info' && hits.inBottom === 'info'
         && hits.frameLeft === 'btn' && hits.frameTop === 'btn' && hits.frameBottom === 'btn' && hits.between === 'info',
         'clicks outside its box land on the map, inside it on the button (frame included) or the ⓘ ' + JSON.stringify(hits));
    } else {
      ok(g.pos === 'static', 'phone: in the flow, not over the map');
      ok(Math.abs(g.map.t - g.save.b - 8) < 0.6, `phone: 8px above the map (${(g.map.t - g.save.b).toFixed(1)})`);
      ok(Math.abs(g.save.r - g.map.r) < 0.6 && Math.abs(g.tip.r - g.map.r) < 0.6,
         `phone: right-aligned to the map's edge (row ${g.save.r}, ⓘ ${g.tip.r}, map ${g.map.r})`);
    }
    // Keyboard: Clear all -> Save this map -> ⓘ -> the map's first control, ring visible.
    const tab = async () => { for (const type of ['keyDown', 'keyUp'])
      await send('Input.dispatchKeyEvent', { type, key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 }); };
    await evaluate(`(function(){ document.getElementById('visitedClear').focus(); return 1; })()`);
    const order = [];
    let ring = null;
    for (let i = 0; i < 3; i++) {
      await tab();
      order.push(await evaluate(`(function(){ const a = document.activeElement; return a.id || (a.closest('.mapzoom') ? 'zoom:' + a.dataset.z : a.className); })()`));
      if (i === 0) ring = await evaluate(`(function(){ const s = getComputedStyle(document.activeElement); return s.outlineStyle + ' ' + s.outlineWidth + ' ' + s.outlineColor + ' ' + document.activeElement.matches(':focus-visible'); })()`);
    }
    ok(order[0] === 'visitedSave' && order[1] === 'muted' && order[2] === 'zoom:fs', 'Tab order: Clear all -> Save this map -> ⓘ -> full screen ' + JSON.stringify(order));
    ok(/^solid 2px /.test(ring || '') && / true$/.test(ring || ''), 'focus ring: 2px solid (' + ring + ')');
    // Full screen: only the map moves into the overlay; the button stays behind it.
    const fsr = await evaluate(`(async function(){ document.querySelector('#visitedMap .mapzoom [data-z="fs"]').click();
      await new Promise((r) => setTimeout(r, 400));
      const ov = document.querySelector('.mapfs'); const s = document.getElementById('visitedSaveRow').getBoundingClientRect();
      const e = document.elementFromPoint(s.left + s.width / 2, s.top + s.height / 2);
      const out = { open: !!ov, inOverlay: ov ? ov.querySelectorAll('.vsave, #visitedSave').length : -1, top: e ? !!e.closest('.mapfs') : null };
      document.querySelector('.mapfs-close').click();
      await new Promise((r) => setTimeout(r, 300));
      out.back = document.getElementById('visitedSaveRow').nextElementSibling === document.getElementById('visitedMap')
        && document.getElementById('visitedMap').parentElement.classList.contains('vmapwrap');
      return out; })()`);
    ok(fsr.open && fsr.inOverlay === 0 && fsr.top === true && fsr.back,
       'full screen shows the map without the button, which goes back beside it after ' + JSON.stringify(fsr));
    const share = await evaluate(`(function(){ try { const s = buildVisitedShareSVG('story', SHARE_PINS).svg; return { len: s.length, save: /Save this map|visitedSave/.test(s) }; } catch (e) { return { err: String(e) }; } })()`);
    ok(share && share.len > 1000 && share.save === false, 'the share image has no button in it ' + JSON.stringify(share));
    // Marking and unmarking update it; with nothing marked it goes, and takes no room.
    const life = await evaluate(`(async function(){ const tip = () => { const t = document.querySelector('#visitedSaveRow .muted'); return t ? t.getAttribute('data-tip') : null; };
      const out = {};
      document.querySelector('#visitedMap path[data-iso="AU"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
      out.marked = tip();
      let b, i = 0; while ((b = document.querySelector('#visitedChips .rm')) && i++ < 60) b.click();
      const sv = document.getElementById('visitedSaveRow');
      out.cleared = { html: sv.innerHTML, h: sv.getBoundingClientRect().height, n: document.querySelectorAll('#visitedSave').length };
      document.querySelector('#visitedMap path[data-iso="FR"]').dispatchEvent(new MouseEvent('click', { bubbles: true }));
      out.again = tip();
      return out; })()`);
    ok(/keep your 35 been on/.test(life.marked || '') && life.cleared.html === '' && life.cleared.h === 0 && life.cleared.n === 0
       && /keep your 1 been on/.test(life.again || ''),
       'follows marking (35), clearing (gone, 0px) and the first new mark (1) ' + JSON.stringify(life));
  }
  const passed = results.filter(Boolean).length;
  console.log(`${passed}/${results.length} passed (${kase}, ${W}px, ${process.env.S_DARK === '0' ? 'light' : 'dark'})`);
};

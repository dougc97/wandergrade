// zonemark_kbd_check.mjs — a keyboard user reaching each avoid-zone ⓘ (app.js
// zoneMarkHTML) with Tab gets Canada's words: the tip shows and the ⓘ is
// described by it (aria-describedby="wgtip"), also when Tab has to scroll the
// page to reach it (the scroll handler at the end of app.js's tooltip code).
// Each marker is reached twice: from the focusable before it as the page
// stands, and from the top of the page (always a focus scroll).
//   BASE=http://127.0.0.1:8871 SLUGS="ethiopia,pakistan" node cdp.mjs ./zonemark_kbd_check.mjs
const BASE = process.env.BASE || 'https://wandergrade.com';
const SLUGS = (process.env.SLUGS || 'ethiopia,mauritania').split(',');
export default async ({ send, evaluate, setSize, nav, sleep, errs }) => {
  let good = 0, all = 0;
  const tab = async () => {
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await sleep(400);
  };
  for (const [w, h] of [[1280, 900], [390, 844]]) {
    await setSize(w, h, w < 500);
    for (const slug of SLUGS) {
      await nav(`${BASE}/guide/${slug}?cb=${Date.now()}`, 1500);
      for (let i = 0; i < 40; i++) {
        if (await evaluate(`(() => !!(document.querySelector('#actDetail .actlist') && _watchoutCache[window.__WGGC__]))()`) === true) break;
        await sleep(250);
      }
      await sleep(1500);
      const n = await evaluate(`document.querySelectorAll('#actDetail .zonemark:not(.stale)').length`);
      for (let k = 0; k < n; k++) {
        for (const fromTop of [false, true]) {
          const pre = await evaluate(`(() => {
            const m = document.querySelectorAll('#actDetail .zonemark:not(.stale)')[${k}];
            const els = [...document.querySelectorAll('a[href], button, [tabindex], input, select, summary')]
              .filter((e) => e.tabIndex >= 0 && !e.disabled && e.offsetParent !== null);
            const p = els[els.indexOf(m) - 1];
            if (${fromTop}) scrollTo(0, 0);
            p.focus({ preventScroll: ${fromTop} });
            const r = m.getBoundingClientRect();
            return { inView: r.top >= 0 && r.bottom <= innerHeight };
          })()`);
          await tab();
          const st = await evaluate(`(() => { const a = document.activeElement, t = document.getElementById('wgtip');
            const m = document.querySelectorAll('#actDetail .zonemark:not(.stale)')[${k}];
            return { on: a === m, tip: !t.hidden && t.textContent === m.dataset.tip, described: m.getAttribute('aria-describedby') === 'wgtip' }; })()`);
          const pass = st.on && st.tip && st.described;
          all++; good += pass;
          console.log(pass ? 'PASS' : 'FAIL', w, slug, 'marker', k, fromTop ? 'from the top' : 'from before it',
                      pre.inView ? '(in view)' : '(focus scrolls)', JSON.stringify(st));
        }
      }
    }
  }
  console.log(`${good} of ${all} Tab visits show the marker's words; console errors ${errs.length}`, JSON.stringify(errs.slice(0, 3)));
};

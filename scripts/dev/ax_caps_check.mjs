// ax_caps_check.mjs — no control's accessible name is garbled by CSS capitals. Chrome builds a
// name from the text as drawn, text-transform included, so a control named by a label drawn
// uppercase (th, .picklabel, .gqlabel…) was announced "DESTINATION", "🛡️ SAFETY AT LEAST". For
// each page at 390 and 1280 (every <details> opened; Help me choose opened on /) this reads
// Chrome's accessibility tree (Accessibility.getFullAXTree), reads it again with
// text-transform: none forced on every element, and lists each focusable or control node whose
// name differs between the two. Words written in capitals (YTD, USD) don't differ, so don't show.
// It also checks every sort button on screen is named with the words on screen (WCAG 2.5.3): a
// phone's "VS AVG" header must not be named "vs 1-yr avg".
// Local servers only (no default host on purpose); Wikimedia through wikicache.mjs.
// All 20 page loads take ~3 minutes, past cdp.mjs's default 60 s cap, so give it the time (or one
// width per run with W=390 / W=1280, ~90 s each). A run that ends without the closing OK/FAIL
// line did not finish: it checked nothing past its last "ok" line.
//   CDP_TIMEOUT=300 BASE=http://127.0.0.1:8000 node cdp.mjs ./ax_caps_check.mjs
//   CDP_TIMEOUT=150 W=390 BASE=http://127.0.0.1:8000 node cdp.mjs ./ax_caps_check.mjs
// scripts/test_ax_caps.py holds the fixes in place without a browser.
import { enableWikiCache } from './wikicache.mjs';
const BASE = process.env.BASE;
const OPEN = `(function(){ document.querySelectorAll('details').forEach(function(d){ d.open = true; }); return 1; })()`;
const QUIZ = `(function(){ var b = document.getElementById('guideMeBtn'); if (b) b.click(); return !!document.getElementById('gqMonth'); })()`;
const WIDTHS = (process.env.W || '390,1280').split(',').map(Number);
const PAGES = (process.env.PAGES || '/,/?quiz,/guide/thailand,/cheapest,/?tab=data,/?tab=data&dm=afford,/?tab=data&dm=advisory,/?tab=data&dm=flights,/?tab=trip,/?tab=visited').split(',');
const ROLES = new Set(['button', 'combobox', 'textbox', 'searchbox', 'checkbox', 'radio', 'switch', 'slider', 'spinbutton',
  'listbox', 'menuitem', 'tab', 'link', 'DisclosureTriangle', 'PopUpButton', 'ToggleButton']);
export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  if (!BASE || !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(BASE)) { console.log('Set BASE to a local server, e.g. BASE=http://127.0.0.1:8000'); return; }
  await send('Network.enable');
  await send('Network.setBlockedURLs', { urls: ['*wandergrade.com*', '*onrender.com*', '*cloudflareinsights*', '*prf.hn*', '*hostelworld*'] });
  await enableWikiCache(send, on);
  await send('Accessibility.enable');
  const names = async () => {
    const r = await send('Accessibility.getFullAXTree', {});
    const m = new Map();
    for (const n of (r.result && r.result.nodes) || []) {
      if (n.ignored || !n.backendDOMNodeId) continue;
      const focusable = (n.properties || []).some((p) => p.name === 'focusable' && p.value && p.value.value);
      if (focusable || ROLES.has(n.role && n.role.value)) m.set(n.backendDOMNodeId, { role: n.role.value, name: (n.name && n.name.value) || '' });
    }
    return m;
  };
  // Sort buttons on screen whose name lacks their visible words (as written: text-transform off,
  // emoji and the ⓘ dropped).
  const LABEL_IN_NAME = `(function(){ var out = [];
    document.querySelectorAll('th.sortable .sortbtn').forEach(function (b) {
      if (!b.getClientRects().length) return;
      var norm = function (t) { return (t || '').replace(/[\u24d8\u24be]/g, ' ').replace(/\\p{Extended_Pictographic}|\uFE0F/gu, ' ')
        .replace(/\\s+/g, ' ').trim().toLowerCase(); };
      var seen = norm(b.innerText), name = norm(b.getAttribute('aria-label') || b.innerText);
      if (seen && name.indexOf(seen) < 0) out.push(JSON.stringify(seen) + ' named ' + JSON.stringify(name));
    });
    return out; })()`;
  console.log(`checking ${PAGES.length * WIDTHS.length} page/width runs; the verdict line comes last`);
  let bad = 0, total = 0, lin = 0;
  for (const w of WIDTHS) {
    await setSize(w, w < 700 ? 844 : 900, w < 700);
    for (const page of PAGES) {
      const quiz = page === '/?quiz';
      await nav(BASE + (quiz ? '/' : page), 6000);
      await evaluate(quiz ? QUIZ : OPEN);
      await sleep(1200);
      const a = await names();
      await evaluate(`(function(){ var s = document.createElement('style'); s.id = '__nott'; s.textContent = '*, *::before, *::after { text-transform: none !important }'; document.head.appendChild(s); return 1; })()`);
      await sleep(300);
      const b = await names();
      const lr = await evaluate(LABEL_IN_NAME);
      const miss = Array.isArray(lr) ? lr : ['(the on-screen words check did not run: ' + JSON.stringify(lr) + ')'];
      await evaluate(`(function(){ var s = document.getElementById('__nott'); if (s) s.remove(); return 1; })()`);
      const diff = [...a].filter(([id, x]) => b.has(id) && b.get(id).name !== x.name);
      total += a.size; bad += diff.length; lin += miss.length;
      console.log(`${diff.length || miss.length ? 'FAIL' : 'ok  '} ${w} ${page}: ${a.size} controls`
        + diff.map(([id, x]) => `\n       ${x.role} ${JSON.stringify(x.name)} (written ${JSON.stringify(b.get(id).name)})`).join('')
        + miss.map((m) => `\n       sort button on screen ${m}`).join(''));
    }
  }
  console.log(`${bad || lin ? 'FAIL' : 'OK'}: ${bad} of ${total} control names change with text-transform; `
    + `${lin} sort buttons named without their words on screen; widths ${WIDTHS.join('+')}; page errors ${errs.length}`);
};

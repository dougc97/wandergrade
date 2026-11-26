// ax_caps_check.mjs — no control's accessible name is garbled by CSS capitals. Chrome builds a
// name from the text as drawn, text-transform included, so a control named by a label drawn
// uppercase (th, .picklabel, .gqlabel…) was announced "DESTINATION", "🛡️ SAFETY AT LEAST". For
// each page at 390 and 1280 (every <details> opened; Help me choose opened on /) this reads
// Chrome's accessibility tree (Accessibility.getFullAXTree), reads it again with
// text-transform: none forced on every element, and lists each focusable or control node whose
// name differs between the two. Words written in capitals (YTD, USD) don't differ, so don't show.
// Local servers only (no default host on purpose); Wikimedia through wikicache.mjs.
//   BASE=http://127.0.0.1:8000 node cdp.mjs ./ax_caps_check.mjs
// scripts/test_ax_caps.py holds the fixes in place without a browser.
import { enableWikiCache } from './wikicache.mjs';
const BASE = process.env.BASE;
const OPEN = `(function(){ document.querySelectorAll('details').forEach(function(d){ d.open = true; }); return 1; })()`;
const QUIZ = `(function(){ var b = document.getElementById('guideMeBtn'); if (b) b.click(); return !!document.getElementById('gqMonth'); })()`;
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
  let bad = 0, total = 0;
  for (const w of [390, 1280]) {
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
      await evaluate(`(function(){ var s = document.getElementById('__nott'); if (s) s.remove(); return 1; })()`);
      const diff = [...a].filter(([id, x]) => b.has(id) && b.get(id).name !== x.name);
      total += a.size; bad += diff.length;
      console.log(`${diff.length ? 'FAIL' : 'ok  '} ${w} ${page}: ${a.size} controls` + diff.map(([id, x]) => `\n       ${x.role} ${JSON.stringify(x.name)} (written ${JSON.stringify(b.get(id).name)})`).join(''));
    }
  }
  console.log(`${bad ? 'FAIL' : 'OK'}: ${bad} of ${total} control names change with text-transform; page errors ${errs.length}`);
};

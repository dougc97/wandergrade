// shell_text_switch_check.mjs — with FX_GUIDE_TEXTOUT=0 a guide renders as it
// did before the text-out, not only serves the same bytes.
//
//   cd scripts/dev && BASE=http://127.0.0.1:9085 OFF=http://127.0.0.1:9087 W=1280 \
//     SLUGS="japan wales" CDP_TIMEOUT=300 node cdp.mjs ./shell_text_switch_check.mjs
//
// BASE is a server from before the change, OFF one of this tree run with
// FX_GUIDE_TEXTOUT=0; both must hold the same data (rates, advisories). Each
// guide lands on both, every third-party request refused, storage cleared
// between, and once it has settled (hydrated, Data's risk wait over, the
// page the same on three polls) the whole document, ?v= stamps aside, must be
// the same on both: the hidden Data tab's currency table and "My currency"
// picker drawn (#rows, #dataBase), the guide's country box full (#bestCountry),
// no #shellText, no mark. The counts a crawler running the JS would read are
// printed beside it. Read the SUMMARY line: the exit status is always 0.
const BASE = process.env.BASE, OFF = process.env.OFF;
const SLUGS = (process.env.SLUGS || 'japan wales peru chad western-sahara puerto-rico england afghanistan')
  .split(/[\s,]+/).filter(Boolean);
const W = +process.env.W || 1280, H = W < 768 ? 844 : 900;

const STATE = `(() => {
  const all = [], tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = tw.nextNode());) {
    const q = n.parentElement;
    if (q && (/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(q.tagName) || q.closest('svg'))) continue;
    all.push(n.data);
  }
  const html = document.documentElement.outerHTML.replace(/\\?v=\\d+/g, '?v=X');
  return { shellText: !!document.getElementById('shellText'), marks: html.split('<!--t').length - 1,
    rows: document.querySelectorAll('#rows tr').length,
    dataBase: (document.getElementById('dataBase') || { options: [] }).options.length,
    bestCountry: (document.getElementById('bestCountry') || { options: [] }).options.length,
    links: document.querySelectorAll('a[href]').length,
    words: all.join(' ').split(/\\s+/).filter((w) => /[\\p{L}\\p{N}]/u.test(w)).length,
    dom: html.length, html };
})()`;

export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  await setSize(W, H, W < 768);
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId;
    if (/^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(d.params.request.url)) send('Fetch.continueRequest', { requestId: id });
    else send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' });
  });
  const land = async (url) => {
    await nav('about:blank', 100);
    await nav(url, 300);
    for (let t = 0; t < 20000; t += 250) { if (await evaluate(`!document.getElementById('ssrGuide')`) === true) break; await sleep(250); }
    await sleep(2500);   // renderRates' wait for the advisories is 2 s at most
    let last = null, same = 0, s = null;
    for (let t = 0; t < 15000 && same < 3; t += 400) {
      s = await evaluate(STATE);
      same = last && s.html === last ? same + 1 : 0;
      last = s.html;
      if (same < 3) await sleep(400);
    }
    await evaluate(`(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} return 1; })()`);
    return s;
  };
  const firstDiff = (a, b) => {
    let i = 0;
    while (i < a.length && a[i] === b[i]) i++;
    return i >= a.length && i >= b.length ? null : { at: i, base: a.slice(Math.max(0, i - 80), i + 120), off: b.slice(Math.max(0, i - 80), i + 120) };
  };
  let ok = 0;
  for (const slug of SLUGS) {
    const e0 = errs.length;
    const b = await land(`${BASE}/guide/${slug}`), o = await land(`${OFF}/guide/${slug}`);
    const jsErrs = errs.slice(e0).filter((e) => !/ERR_BLOCKED_BY_CLIENT|favicon/.test(e));
    const counts = (s) => { const { html, ...c } = s; return c; };
    const diff = firstDiff(b.html, o.html);
    const pass = !diff && !o.shellText && !o.marks && o.rows > 1 && o.dataBase > 1 && !jsErrs.length;
    if (pass) ok++;
    console.log(pass ? 'PASS' : 'FAIL', slug, 'base', JSON.stringify(counts(b)), 'off', JSON.stringify(counts(o)));
    if (diff) console.log('  first difference at', diff.at, '\n  base:', JSON.stringify(diff.base), '\n  off: ', JSON.stringify(diff.off));
    if (jsErrs.length) console.log('  js errors', jsErrs.slice(0, 5));
  }
  console.log(`SUMMARY ${ok}/${SLUGS.length} guides render the same with FX_GUIDE_TEXTOUT=0 as before (W=${W})`);
};

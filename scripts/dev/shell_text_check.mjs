// shell_text_check.mjs — a guide page's other tabs, opened from the guide, are
// exactly what they were before their words left the served HTML.
//
//   cd scripts/dev && BASE=http://127.0.0.1:9021 TEST=http://127.0.0.1:9022 W=390 \
//     SLUGS="japan wales" CDP_TIMEOUT=900 node cdp.mjs ./shell_text_check.mjs
//
// On /guide/* the server serves Top Picks', Trip's, Wander List's and Data's
// words as <!--tN--> marks with the strings in #shellText (server.py
// _text_out); app.js puts them back as one of those tabs opens
// (restoreShellText), and draws the hidden Data tab's currency table and "My
// currency" picker only when that tab opens (dataTabDeferred). BASE is a
// server from before the change (a worktree of the commit before it), TEST
// the one to check. Both get the same steps, every third-party request
// refused (photos, Wikipedia, affiliates: identical on both sides, and
// Wikimedia asks for at most 2 requests a second), storage cleared between.
// The two servers must hold the same data (rates, advisories): one whose
// upstream answered minutes later differs in figures, which the summary
// counts apart ("only figures apart") — not this check's business.
// Per guide:
//   landing  the guide hydrates with no JS error; the guide tab, header and
//            newsletter box equal BASE's; on TEST the marks are there, #rows
//            holds only its placeholder row, #dataBase at most 1 option
//   tab      Top Picks, Trip, Wander List and Data, then Data's Cost of
//            living, Safety, Flights and Currency: once each settles, its
//            text, markup (combo list ids and the options' selected
//            attribute aside: the deferred picker is enhanced and written
//            later; each select's value is compared instead) and every box's
//            position and size equal BASE's, and no mark is left; then the
//            table and picker are as full as BASE's
//   back     the guide again: the same h1, text and boxes
//   history  Top Picks, Back to the guide, Forward to Top Picks
//   deep     /guide/<slug>?tab=data&dm=advisory (it opens Data's Safety view)
//   jump     the guide's "switch source → Safety tab" button, where it has one
// Once, on the first guide, BASE and TEST back to back (a currency other than
// the dollar comes from a live feed: both servers fetch it at one moment
// first, and hold that answer 10 minutes): Data's "My currency" set to EUR
// redraws the table; Top Picks' "In" set to EUR, then Data; the header's 👤
// box where accounts are on (nothing is submitted); /?tab=data on the
// homepage, which has no #shellText.
// W sets the viewport (under 768 runs as a phone); OUT names a JSON file for
// every snapshot. Read the SUMMARY line: the exit status is always 0.
import fs from 'node:fs';
const BASE = process.env.BASE, TEST = process.env.TEST;
const SLUGS = (process.env.SLUGS || 'japan wales peru chad western-sahara puerto-rico england afghanistan')
  .split(/[\s,]+/).filter(Boolean);
const W = +process.env.W || 1280, H = W < 768 ? 844 : 900;
const TABS = ['value', 'trip', 'visited', 'data'], DMS = ['afford', 'advisory', 'flights', 'currency'];
const REFUSED = /ERR_BLOCKED_BY_CLIENT/;   // the console line for each refused request

// One element's state: whether it shows, marks left, text, markup, and the box
// (document coordinates, rounded) of everything rendered in it, named.
const SNAP = (sel) => `(() => {
  const s = document.querySelector(${JSON.stringify(sel)});
  if (!s) return null;
  let marks = 0;
  const w = document.createTreeWalker(s, NodeFilter.SHOW_COMMENT);
  for (let n; (n = w.nextNode());) if (/^t\\d+$/.test(n.data)) marks++;
  const boxes = [];
  for (const e of [s, ...s.querySelectorAll('*')]) {
    const r = e.getBoundingClientRect();
    if (r.width || r.height) boxes.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : e.classList.length ? '.' + e.classList[0] : '')
      + ':' + [r.x, r.y + scrollY, r.width, r.height].map(Math.round).join(','));
  }
  // Each select's choice is compared as its value, not as which option carries
  // the selected attribute: that one is the choice when the options were
  // written (a deferred "My currency" picker is written in the currency
  // picked since; drawn at boot, it keeps the dollar's attribute and holds
  // EUR as its value). The guide's country box, hidden behind its combo,
  // holds one option until it is used, so its options are left out too
  // (guide_countries_check.mjs checks them); its value is compared.
  const picks = [...s.querySelectorAll('select')].map((x) => (x.id || x.name) + '=' + x.value).join(' ');
  return { shown: !!s.getClientRects().length, marks, text: s.innerText, boxes: boxes.join(' ') + ' | ' + picks,
           html: s.outerHTML.replace(/\\bcl\\d+/g, 'cl#').replace(/(<option\\b[^>]*?) selected=""/g, '$1')
             .replace(/(<select id="bestCountry"[^>]*>)[\\s\\S]*?(<\\/select>)/, '$1$2') };
})()`;
const STATE = `(() => ({ marks: document.documentElement.outerHTML.split('<!--t').length - 1,
  json: !!document.getElementById('shellText'), rows: document.querySelectorAll('#rows tr').length,
  baseOpts: document.getElementById('dataBase').options.length,
  h1: (document.querySelector('#tab-guide h1') || {}).textContent,
  tab: document.documentElement.getAttribute('data-tab') + ' ' + document.documentElement.getAttribute('data-dm'),
  jump: !!document.querySelector('#guideSafety .advsrcjump') }))()`;

export default async ({ send, on, evaluate, setSize, nav, sleep, errs }) => {
  await setSize(W, H, W < 768);
  // Reduced motion: Top Picks' rows slide in 7px (styles.css rowin), and a
  // headless tab can leave the first one mid-slide, the same server's two
  // runs then 7px apart. Every box compared is the one the motion ends on.
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  let refused = 0;
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  on((d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const id = d.params.requestId;
    if (/^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(d.params.request.url)) send('Fetch.continueRequest', { requestId: id });
    else { refused++; send('Fetch.failRequest', { requestId: id, errorReason: 'BlockedByClient' }); }
  });
  const waitFor = async (expr, ms = 20000) => {
    for (let t = 0; t < ms; t += 250) { if (await evaluate(`(() => !!(${expr}))()`) === true) return true; await sleep(250); }
    return false;
  };
  // Settled: the same state on three polls in a row (up to 15 s).
  const settle = async (sel) => {
    let last = '', same = 0, s = null;
    for (let t = 0; t < 15000 && same < 3; t += 400) {
      s = await evaluate(SNAP(sel));
      const sig = s ? s.text + s.html + s.boxes : '';
      same = sig === last ? same + 1 : 0;
      last = sig;
      if (same < 3) await sleep(400);
    }
    return s;
  };
  const click = (sel) => evaluate(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (b) b.click(); return !!b; })()`);
  const pick = (id, v) => evaluate(`(() => { const s = document.getElementById(${JSON.stringify(id)});
    if (!s || ![...s.options].some((o) => o.value === ${JSON.stringify(v)})) return false;
    s.value = ${JSON.stringify(v)}; s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
  const open = async (url) => { await nav('about:blank', 100); await nav(url, 300); };
  // A guide landing, hydrated (renderGuide removes the served #ssrGuide).
  const land = async (url) => {
    await open(url);
    const ok = await waitFor(`!document.getElementById('ssrGuide')`);
    await settle('#tab-guide');
    return ok;
  };
  const clear = () => evaluate(`(() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} return 1; })()`);
  const errsSince = (e0, r) => {
    const all = errs.slice(e0);
    r.errs = all.filter((e) => !REFUSED.test(e));
    r.refusedLogs = all.length - r.errs.length;
    return r;
  };

  const guide = async (base, slug) => {
    const r = {}, e0 = errs.length;
    r.hydrated = await land(`${base}/guide/${slug}`);
    r['landing:guide'] = await settle('#tab-guide');
    r['landing:header'] = await settle('header');
    r['landing:newsletter'] = await settle('#subscribe');
    r.state = await evaluate(STATE);
    for (const t of TABS) { await click(`#tabs button[data-tab="${t}"]`); r['tab:' + t] = await settle('#tab-' + t); }
    for (const dm of DMS) { await click(`#dataMode button[data-dm="${dm}"]`); r['tab:data/' + dm] = await settle('#tab-data'); }
    r.after = await evaluate(STATE);
    await click('#tabs button[data-tab="guide"]');
    r['back:guide'] = await settle('#tab-guide');
    r.backState = await evaluate(STATE);
    await clear();

    await land(`${base}/guide/${slug}`);
    await click('#tabs button[data-tab="value"]');
    await settle('#tab-value');
    await evaluate('history.back()');
    await waitFor(`document.documentElement.getAttribute('data-tab') === 'guide'`, 5000);
    r['history:back'] = await settle('#tab-guide');
    await evaluate('history.forward()');
    await waitFor(`document.documentElement.getAttribute('data-tab') === 'value'`, 5000);
    r['history:forward'] = await settle('#tab-value');
    await clear();

    await land(`${base}/guide/${slug}?tab=data&dm=advisory`);
    r['deep:data/advisory'] = await settle('#tab-data');
    r.deepState = await evaluate(STATE);
    await clear();

    if (r.state && r.state.jump) {
      await land(`${base}/guide/${slug}`);
      await click('#guideSafety .advsrcjump');
      r['jump:safety'] = await settle('#tab-data');
      await clear();
    }
    return errsSince(e0, r);
  };

  const once = async (base) => {
    const slug = SLUGS[0], r = {}, e0 = errs.length;
    await land(`${base}/guide/${slug}`);
    await click('#tabs button[data-tab="data"]');
    await settle('#tab-data');
    r.pickedEUR = await pick('dataBase', 'EUR');
    r['once:data-mycurrency-eur'] = await settle('#tab-data');
    await clear();

    await land(`${base}/guide/${slug}`);
    await click('#tabs button[data-tab="value"]');
    await settle('#tab-value');
    r.pickedIn = await pick('homeCur', 'EUR');
    await settle('#tab-value');
    await click('#tabs button[data-tab="data"]');
    r['once:picks-in-eur-then-data'] = await settle('#tab-data');
    await clear();

    await land(`${base}/guide/${slug}`);
    if (await click('#acctBtn:not([hidden])')) r['once:account-box'] = await settle('.submodal');
    await clear();

    await open(`${base}/?tab=data`);
    r['once:home-data'] = await settle('#tab-data');
    r.homeJson = await evaluate(`!!document.getElementById('shellText')`);
    await clear();
    return errsSince(e0, r);
  };

  const A = {}, B = {};
  for (const slug of SLUGS) A[slug] = await guide(BASE, slug);
  for (const slug of SLUGS) B[slug] = await guide(TEST, slug);
  await Promise.all([BASE, TEST].map((b) => fetch(b + '/api/rates?base=EUR').then((x) => x.text()).catch(() => '')));
  A.once = await once(BASE);
  B.once = await once(TEST);
  if (process.env.OUT) fs.writeFileSync(process.env.OUT, JSON.stringify({ W, BASE, TEST, A, B }));

  // Where two strings first part, with some context.
  const where = (x, y) => {
    let i = 0;
    while (i < x.length && x[i] === y[i]) i++;
    return `@${i}: ${JSON.stringify(x.slice(Math.max(0, i - 40), i + 60))} vs ${JSON.stringify(y.slice(Math.max(0, i - 40), i + 60))}`;
  };
  let same = 0, figures = 0, all = 0, bad = 0;
  for (const key of [...SLUGS, 'once']) {
    const a = A[key], b = B[key], notes = [];
    for (const k of Object.keys(a).filter((k) => k.includes(':'))) {
      all++;
      const x = a[k], y = b[k];
      if (!x || !y) { notes.push(`${k} missing`); continue; }
      const diff = ['shown', 'text', 'html', 'boxes'].filter((f) => x[f] !== y[f]);
      if (y.marks) diff.push(`${y.marks} marks left`);
      if (!diff.length) { same++; continue; }
      // Only figures apart (text or markup differ, but not with every digit
      // masked, and the same elements are boxed): a feed the two servers
      // fetched at different moments, like the live EUR rates. Counted, and
      // listed, apart.
      const m = (t) => t.replace(/\d/g, '0'), named = (t) => t.replace(/:[^ ]*/g, '');
      if (!y.marks && x.shown === y.shown && (x.text !== y.text || x.html !== y.html)
          && m(x.text) === m(y.text) && m(x.html) === m(y.html) && named(x.boxes) === named(y.boxes)) {
        figures++;
        notes.push(`${k} figures only ${where(x.text === y.text ? x.html : x.text, x.text === y.text ? y.html : y.text)}`);
        continue;
      }
      const f = diff.find((d) => ['text', 'html', 'boxes'].includes(d));
      notes.push(`${k} DIFF ${diff.join('+')} ${f ? where(x[f], y[f]) : ''}`);
    }
    if (a.errs.length || b.errs.length) notes.push(`JS errors base ${a.errs.length} test ${b.errs.length}: ${[...a.errs, ...b.errs].slice(0, 3).join(' | ')}`);
    if (key === 'once') {
      if (b.homeJson || !b.pickedEUR || !b.pickedIn) notes.push(`homepage #shellText ${b.homeJson}, EUR picked ${b.pickedEUR}/${b.pickedIn}`);
    } else {
      const s = (o) => o || {};
      const ok = b.hydrated && s(b.state).json && s(b.state).marks > 0 && s(b.state).rows === 1 && s(b.state).baseOpts <= 1
        && ['h1', 'jump'].every((f) => s(a.state)[f] === s(b.state)[f])
        && ['rows', 'baseOpts', 'tab'].every((f) => s(a.after)[f] === s(b.after)[f])
        && s(a.backState).h1 === s(b.backState).h1 && s(a.deepState).tab === s(b.deepState).tab
        && !s(b.after).marks && !s(b.after).json;
      if (!ok) notes.push(`state ${JSON.stringify({ base: [a.state, a.after], test: [b.state, b.after] })}`);
    }
    if (notes.some((n) => !n.includes(' figures only '))) bad++;
    const st = key === 'once' ? '' : `marks ${b.state.marks}, #rows ${b.state.rows} (base ${a.state.rows}) -> ${b.after.rows}, `
      + `#dataBase ${b.state.baseOpts} (base ${a.state.baseOpts}) -> ${b.after.baseOpts}, `;
    console.log(`${key} ${W}: ${st}JS errors ${a.errs.length}/${b.errs.length}, refused-request lines ${a.refusedLogs}/${b.refusedLogs}`
      + (notes.length ? '\n    ' + notes.join('\n    ') : ' — all equal'));
  }
  console.log(`SUMMARY W=${W}: ${same}/${all} snapshots equal, ${figures} more with only figures apart, `
    + `${SLUGS.length + 1 - bad}/${SLUGS.length + 1} groups clean, `
    + `${refused} third-party requests refused`);
};

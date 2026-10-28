// ig_story.mjs — a 1080x1920 Instagram-story PNG of this month's Top Picks,
// rendered from the live site so the grades, copy and font are the real ones.
//
//   cd scripts/dev && MONTH=11 OUT=/path/to/story.png CDP_TIMEOUT=55 node cdp.mjs ./ig_story.mjs
//
// MONTH defaults to the current month; ORIGIN (ISO, default US) is the
// "From" country the ranking is scored for; SITE overrides the base URL for a
// local server. It refuses while the server sends /cheapest/<month> uncached
// (a feed missing or fares still loading: grades may change); behind an HTTP
// proxy, as in a cloud container, Node's fetch needs NODE_USE_ENV_PROXY=1.
// The page is loaded at /?tab=value&vmn=<month> (analytics
// beacon blocked), the top five rows of the ranked table are read from the
// DOM, and the shared ig_frame.mjs panel is drawn INSIDE the server-rendered
// /cheapest/<month> page (so the site's CSS variables, grade pills and Plus
// Jakarta Sans apply) and screenshotted, with a sidecar .txt beside OUT (posting
// date from POSTED, default today; link-sticker URL; caption). Nothing is posted anywhere.
import { blockBeacon, openCanvas, renderFrame, writeSidecar, brand, band, foot, pill, esc } from './ig_frame.mjs';
const SITE = process.env.SITE || 'https://wandergrade.com';
const MONTH = +(process.env.MONTH || (new Date().getMonth() + 1));
const ORIGIN = (process.env.ORIGIN || 'US').toUpperCase();
const OUT = process.env.OUT || `wandergrade-story-${new Date().toISOString().slice(0, 7)}.png`;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// app.js whyLine added "safest travel rating" for advisory Level 1 until
// 57ae54b (it now quotes the level with its source); kept for an older page. The site
// never makes its own safety claim on a frame: it becomes the State
// Department's level when the row's safety pill says the level is theirs
// ("… — per US State Dept"), and is dropped when it's Canada's or Germany's
// gap-fill ("US State Dept publishes no advisory here; level per …").
export const safetyFact = (fact, advTitle) => (fact !== 'safest travel rating' ? fact
  : /— per US State Dept$/.test(advTitle || '') ? 'US State Dept Level 1' : null);

// No country under advisory Level 3-4 goes on a frame. The row's safety pill
// letter is app.js SAFE_GRADE[level] (A 1, B 2, D 3, F 4; "—" unrated), the
// level the row is ranked on: the State Department's, or Canada's/Germany's
// gap-fill where it publishes none. Keeps the first n rows at A or B, in rank
// order; each keeps its own Top Picks rank, so a skipped place stays visible.
export function pickRows(rows, n = 5) {
  const ok = (r) => r.advLetter === 'A' || r.advLetter === 'B';
  const picked = rows.filter(ok).slice(0, n);
  const last = picked.length ? picked[picked.length - 1].rank : 0;
  return { picked, skipped: rows.filter((r) => !ok(r) && r.rank < last) };
}

// While a feed is missing, or the US fares are still loading after a server
// restart, the server sends /cheapest/<month> uncached (no-store) and the
// homepage's grades shift from minute to minute: a frame then would carry
// numbers that change. Returns why not to render, or null when settled.
// The ?cb= query bypasses Cloudflare, which keeps a settled copy of the plain
// URL for up to 5 minutes (max-age=300) after the server behind it restarts.
// fetchFn is injectable for the tests.
export async function siteUnsettled(month, fetchFn = fetch) {
  const url = `${SITE}/cheapest/${MONTHS[month - 1].toLowerCase()}`;
  let r;
  try { r = await fetchFn(`${url}?cb=${Date.now()}`); } catch (e) { return `GET ${url} failed (${(e.cause && e.cause.code) || e.message})`; }
  if (r.body && r.body.cancel) await r.body.cancel().catch(() => {});
  if (r.status !== 200) return `GET ${url} returned ${r.status}`;
  if (/no-store/i.test(r.headers.get('cache-control') || '')) {
    return `${url} is served uncached: a feed is missing or the US fares are still loading, so grades may still change`;
  }
  return null;
}

// Five cards with two-line why-lines, the link band and the footer have to fit
// between the 250px top and the 280px bottom safe areas: slightly tighter
// cards than the shared frame's (it was 24px padding, 16px apart, 36px under the sub; now 18, 10 and 20).
const TIGHT = `
  #igstory .igh1 { margin: 18px 0 10px; }
  #igstory .igsub { margin-bottom: 20px; }
  #igstory .igc { padding: 18px 30px; margin-bottom: 10px; }
  #igstory .igwhy { font-size: 24px; line-height: 1.25; }`;

export default async (t) => {
  const { send, evaluate, setSize, nav, sleep, errs } = t;
  const before = await siteUnsettled(MONTH);
  if (before) { console.log('REFUSED:', before, '— run again later.'); return; }
  await setSize(1280, 900, false);
  await blockBeacon(send);
  // app.js counts each score up from 0 over 650ms after every re-render
  // (countUp), so a read mid-count got 92 for a 93. With reduced motion asked
  // for, it skips the count and the number shown is the final one.
  const rm = await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  if (rm.error) throw new Error('reduced-motion emulation failed: ' + JSON.stringify(rm.error));
  // No vmn=/vo= in the URL: with both set the page stopped answering CDP in
  // headless Chrome (probe 2026-10-09). The ranking loads for the current
  // month and the locale's origin; a different month is picked through the
  // page's own select below, the way a reader would.
  await nav(`${SITE}/?tab=value&cb=${Date.now()}`, 4000);
  // The ranked rows, top 20 at most, read from the DOM (null until there are 5).
  const READ = `(() => {
      const trs = [...document.querySelectorAll('#topCards table.gradetable:not(.skeleton) tbody tr[data-iso]')];
      if (trs.length < 5) return null;
      return trs.slice(0, 20).map((tr, i) => {
        const link = tr.querySelector('.destlink');
        const flag = (link.querySelector('span') || {}).textContent || '';
        const pill = tr.querySelector('td.overall .gr');
        const adv = tr.querySelector('td[data-go="advisory"] .gr');
        return { rank: i + 1, iso: tr.dataset.iso, flag: flag.trim(), name: link.textContent.replace(flag, '').trim(),
                 grade: pill ? pill.textContent.trim() : '', gradeCls: pill ? pill.className : 'gr',
                 // The pill's title ("Overall value score 93/100") is never animated.
                 score: ((pill && pill.getAttribute('title') || '').match(/value score (\\d+)\\/100/) || [])[1] || '',
                 shown: (tr.querySelector('td.overall .grnum') || {}).textContent || '',
                 why: tr.getAttribute('title') || '', advTitle: adv ? adv.getAttribute('title') || '' : '',
                 advLetter: adv ? adv.textContent.trim() : '' };
      });
    })()`;
  // The ranking fills after the fares and advisories arrive: wait for real rows.
  const waitRows = async () => {
    for (let i = 0; i < 40; i++) { const r = await evaluate(READ); if (r) return r; await sleep(500); }
    return null;
  };
  let rows = await waitRows();
  // The month is picked once the ranking is in: on a slow load the select
  // wasn't ready 4s after navigation, and the change was silently lost.
  const pageMonth = await evaluate(`(() => (document.getElementById('valueMonth') || {}).value || '')()`);
  if (rows && String(pageMonth) !== String(MONTH)) {
    await evaluate(`(() => { const s = document.getElementById('valueMonth'); if (!s) return; s.value = ${JSON.stringify(String(MONTH))}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await sleep(3000);
    rows = await waitRows();
  }
  // Top Picks shows 5 rows by default (app.js pickCount). Once the ranking is
  // in (the picker isn't there before), ask for 20 through the page's own
  // picker, so a row left off for its advisory level (pickRows) has a replacement.
  if (rows && rows.length < 20) {
    const asked = await evaluate(`(() => { const s = document.getElementById('pickCount'); if (!s || s.value === '20') return false; s.value = '20'; s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
    for (let i = 0; i < 20 && asked === true; i++) {
      await sleep(500);
      const more = await evaluate(READ);
      if (more && more.length > rows.length) { rows = more; break; }
    }
    console.log('rows read after asking for the top 20:', rows.length);
  }
  if (!rows) { console.log('no ranked rows after 20s'); return; }
  const { picked, skipped } = pickRows(rows);
  for (const r of skipped) console.log(`skipped #${r.rank} ${r.name}: safety pill "${r.advLetter}" (${r.advTitle}), not Level 1-2`);
  if (!picked.length) { console.log('REFUSED: no Level 1-2 country in the top', rows.length); return; }
  rows = picked;
  // The number on the frame is the pill's; the one on screen must agree.
  const off = rows.filter((r) => !r.score || r.score !== r.shown);
  if (off.length) { console.log('REFUSED: score mismatch', off.map((r) => `${r.name} title ${r.score} vs shown ${r.shown}`).join('; ')); return; }
  const origin = await evaluate(`(() => (document.getElementById('valueOrigin') || {}).value || '')()`);
  const month = await evaluate(`(() => (document.getElementById('valueMonth') || {}).value || '')()`);
  console.log('origin', origin, 'month', month, 'rows', rows.map((r) => `${r.name} ${r.grade} ${r.score}`).join(' | '));
  // Another month's grades under this month's heading would be wrong numbers on a frame.
  if (String(month) !== String(MONTH)) { console.log(`REFUSED: the page ranks month ${month}, not ${MONTH}`); return; }
  if (origin !== ORIGIN) console.log('WARNING: page origin ' + origin + ' differs from ORIGIN ' + ORIGIN + ' (set From in the page or run from that locale)');

  // One line per pick: the row's first two facts; "home" reads oddly on a
  // story with no reader context, so it becomes the origin country's name.
  const homeName = ORIGIN === 'US' ? 'the US' : ORIGIN;
  const why = (r) => r.why.replace(/than home\b/g, 'than ' + homeName).split(/\s*[·;]\s*|,\s(?=[a-z])/)
    .filter(Boolean).map((f) => safetyFact(f, r.advTitle)).filter(Boolean).slice(0, 2).join(' · ');
  const asOf = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  const cards = rows.map((r) => `
    <div class="igc">
      <div class="igrank">#${r.rank}</div>
      <div class="igflag">${esc(r.flag)}</div>
      <div class="igmain"><div class="igname clip">${esc(r.name)}</div><div class="igwhy clamp">${esc(why(r))}</div></div>
      ${pill(r.gradeCls, r.grade, r.score)}
    </div>`).join('');
  // The clear band between the last card and the footer is where the link sticker goes.
  const html = `${brand()}
    <div class="igh1">Where to go in ${esc(MONTHS[MONTH - 1])}</div>
    <div class="igsub">Top value picks for travelers from the US — prices vs home, safety, weather and flights, graded A+ to F.</div>
    ${cards}
    <div class="igspace"></div>${band('link', 130)}
    ${foot(`As of ${asOf}`, 'Tap the link for the full ranking · free, no sign-up')}`;
  // Checked again: the server may have restarted while the rows were read.
  const after = await siteUnsettled(MONTH);
  if (after) { console.log('REFUSED:', after, '— run again later.'); return; }
  await openCanvas(t, `${SITE}/cheapest/${MONTHS[MONTH - 1].toLowerCase()}`);
  await renderFrame(t, { html, out: OUT, allowClip: '.igname.clip, .igwhy.clamp', css: TIGHT });
  const posting = process.env.POSTED || new Date().toISOString().slice(0, 10);
  const link = `${SITE}/?vmn=${MONTH}&vo=${ORIGIN}&utm_source=instagram&utm_medium=story&utm_campaign=toppicks-${posting.slice(0, 7)}`;
  const names = rows.map((r) => r.name);
  const side = writeSidecar(OUT.replace(/\.png$/i, '') + '.txt', {
    series: `Top Picks: where to go in ${MONTHS[MONTH - 1]}, from ${homeName}`, posting, asOf, link,
    frames: [`the top ${rows.length} picks at advisory Level 1-2, link sticker band`],
    caption: `Where to go in ${MONTHS[MONTH - 1]} from ${homeName}: ${names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' : ''}${names[names.length - 1]} `
      + `${skipped.length ? 'lead WanderGrade\'s value ranking among countries at advisory Level 1-2' : 'top WanderGrade\'s value ranking'}. Full ranking at the link.`,
    notes: rows.map((r) => `#${r.rank} ${r.name}: ${r.grade} ${r.score}`)
      .concat(skipped.map((r) => `#${r.rank} ${r.name} left off: its safety pill is "${r.advLetter}" (${r.advTitle}), not Level 1-2.`)),
  });
  console.log('wrote', OUT, 'and', side, '; console errors', errs.length);
};

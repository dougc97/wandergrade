// ig_story.mjs — a 1080x1920 Instagram-story PNG of this month's Top Picks,
// rendered from the live site so the grades, copy and font are the real ones.
//
//   cd scripts/dev && MONTH=11 OUT=/path/to/story.png CDP_TIMEOUT=55 node cdp.mjs ./ig_story.mjs
//
// MONTH defaults to the current month; ORIGIN (ISO, default US) is the
// "From" country the ranking is scored for; SITE overrides the base URL for a
// local server. The page is loaded at /?tab=value&vmn=<month> (analytics
// beacon blocked), the top five rows of the ranked table are read from the
// DOM, and the shared ig_frame.mjs panel is drawn INSIDE the server-rendered
// /cheapest/<month> page (so the site's CSS variables, grade pills and Plus
// Jakarta Sans apply) and screenshotted. Nothing is posted anywhere.
import { blockBeacon, openCanvas, renderFrame, brand, band, foot, pill, esc } from './ig_frame.mjs';
const SITE = process.env.SITE || 'https://wandergrade.com';
const MONTH = +(process.env.MONTH || (new Date().getMonth() + 1));
const ORIGIN = (process.env.ORIGIN || 'US').toUpperCase();
const OUT = process.env.OUT || `wandergrade-story-${new Date().toISOString().slice(0, 7)}.png`;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

// app.js whyLine adds "safest travel rating" for advisory Level 1. The site
// never makes its own safety claim on a frame: it becomes the State
// Department's level when the row's safety pill says the level is theirs
// ("… — per US State Dept"), and is dropped when it's Canada's or Germany's
// gap-fill ("US State Dept publishes no advisory here; level per …").
export const safetyFact = (fact, advTitle) => (fact !== 'safest travel rating' ? fact
  : /— per US State Dept$/.test(advTitle || '') ? 'US State Dept Level 1' : null);

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
  await setSize(1280, 900, false);
  await blockBeacon(send);
  // No vmn=/vo= in the URL: with both set the page stopped answering CDP in
  // headless Chrome (probe 2026-10-09). The ranking loads for the current
  // month and the locale's origin; a different month is picked through the
  // page's own select below, the way a reader would.
  await nav(`${SITE}/?tab=value&cb=${Date.now()}`, 4000);
  const pageMonth = await evaluate(`(() => (document.getElementById('valueMonth') || {}).value || '')()`);
  if (String(pageMonth) !== String(MONTH)) {
    await evaluate(`(() => { const s = document.getElementById('valueMonth'); if (!s) return; s.value = ${JSON.stringify(String(MONTH))}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
    await sleep(3000);
  }
  // The ranking fills after the fares and advisories arrive: wait for real rows.
  let rows = null;
  for (let i = 0; i < 40 && !rows; i++) {
    rows = await evaluate(`(() => {
      const trs = [...document.querySelectorAll('#topCards table.gradetable:not(.skeleton) tbody tr[data-iso]')];
      if (trs.length < 5) return null;
      return trs.slice(0, 5).map((tr) => {
        const link = tr.querySelector('.destlink');
        const flag = (link.querySelector('span') || {}).textContent || '';
        const pill = tr.querySelector('td.overall .gr');
        const adv = tr.querySelector('td[data-go="advisory"] .gr');
        return { iso: tr.dataset.iso, flag: flag.trim(), name: link.textContent.replace(flag, '').trim(),
                 grade: pill ? pill.textContent.trim() : '', gradeCls: pill ? pill.className : 'gr',
                 score: (tr.querySelector('td.overall .grnum') || {}).textContent || '',
                 why: tr.getAttribute('title') || '', advTitle: adv ? adv.getAttribute('title') || '' : '' };
      });
    })()`);
    if (!rows) await sleep(500);
  }
  if (!rows) { console.log('no ranked rows after 20s'); return; }
  const origin = await evaluate(`(() => (document.getElementById('valueOrigin') || {}).value || '')()`);
  const month = await evaluate(`(() => (document.getElementById('valueMonth') || {}).value || '')()`);
  console.log('origin', origin, 'month', month, 'rows', rows.map((r) => `${r.name} ${r.grade} ${r.score}`).join(' | '));
  if (String(month) !== String(MONTH)) console.log('WARNING: page month differs from MONTH');
  if (origin !== ORIGIN) console.log('WARNING: page origin ' + origin + ' differs from ORIGIN ' + ORIGIN + ' (set From in the page or run from that locale)');

  // One line per pick: the row's first two facts; "home" reads oddly on a
  // story with no reader context, so it becomes the origin country's name.
  const homeName = ORIGIN === 'US' ? 'the US' : ORIGIN;
  const why = (r) => r.why.replace(/than home\b/g, 'than ' + homeName).split(/\s*[·;]\s*|,\s(?=[a-z])/)
    .filter(Boolean).map((f) => safetyFact(f, r.advTitle)).filter(Boolean).slice(0, 2).join(' · ');
  const asOf = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  const cards = rows.map((r, i) => `
    <div class="igc">
      <div class="igrank">#${i + 1}</div>
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
  await openCanvas(t, `${SITE}/cheapest/${MONTHS[MONTH - 1].toLowerCase()}`);
  await renderFrame(t, { html, out: OUT, allowClip: '.igname.clip, .igwhy.clamp', css: TIGHT });
  console.log('wrote', OUT, '; console errors', errs.length);
};

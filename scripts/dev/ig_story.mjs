// ig_story.mjs — a 1080x1920 Instagram-story PNG of this month's Top Picks,
// rendered from the live site so the grades, copy and font are the real ones.
//
//   cd scripts/dev && MONTH=11 OUT=/path/to/story.png CDP_TIMEOUT=90 node cdp.mjs ./ig_story.mjs
//
// MONTH defaults to the current month; ORIGIN (ISO, default US) is the
// "From" country the ranking is scored for; SITE overrides the base URL for a
// local server. The page is loaded at /?tab=value&vmn=<month>, the top five
// rows of the ranked table are read from the DOM, and a fixed 1080x1920 panel
// is drawn INSIDE the page (so the site's CSS variables, grade pills and Plus
// Jakarta Sans apply) and screenshotted. Nothing is posted anywhere.
import fs from 'node:fs';
const SITE = process.env.SITE || 'https://wandergrade.com';
const MONTH = +(process.env.MONTH || (new Date().getMonth() + 1));
const ORIGIN = (process.env.ORIGIN || 'US').toUpperCase();
const OUT = process.env.OUT || `wandergrade-story-${new Date().toISOString().slice(0, 7)}.png`;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export default async (t) => {
  const { send, evaluate, setSize, nav, sleep, errs } = t;
  await setSize(1280, 900, false);
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
        return { iso: tr.dataset.iso, flag: flag.trim(), name: link.textContent.replace(flag, '').trim(),
                 grade: pill ? pill.textContent.trim() : '', gradeCls: pill ? pill.className : 'gr',
                 score: (tr.querySelector('td.overall .grnum') || {}).textContent || '',
                 why: tr.getAttribute('title') || '' };
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

  // One line per pick: the row's why-line, trimmed to its first two facts.
  // One line per pick: the row's first two facts; "home" reads oddly on a
  // story with no reader context, so it becomes the origin country's name.
  const homeName = ORIGIN === 'US' ? 'the US' : ORIGIN;
  const why = (s) => s.replace(/than home\b/g, 'than ' + homeName).split(/\s*[·;]\s*|,\s(?=[a-z])/).filter(Boolean).slice(0, 2).join(' · ');
  const asOf = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const cards = rows.map((r, i) => `
    <div class="igc">
      <div class="igrank">#${i + 1}</div>
      <div class="igflag">${esc(r.flag)}</div>
      <div class="igmain"><div class="igname">${esc(r.name)}</div><div class="igwhy">${esc(why(r.why))}</div></div>
      <div class="igpill"><span class="${esc(r.gradeCls)}">${esc(r.grade)}</span><span class="igscore">${esc(r.score)}</span></div>
    </div>`).join('');
  const html = `
    <style>
      #igstory { position: fixed; inset: 0; width: 1080px; height: 1920px; z-index: 99999; box-sizing: border-box;
        padding: 96px 72px 80px; background: var(--bg); color: var(--fg, var(--text, #e8eaed));
        font-family: "Plus Jakarta Sans", system-ui, sans-serif; display: flex; flex-direction: column; }
      #igstory .igbrand { font-weight: 800; font-size: 40px; color: #2bb24c; letter-spacing: -.01em; }
      #igstory .igh1 { font-weight: 800; font-size: 92px; line-height: 1.02; letter-spacing: -.025em; margin: 26px 0 18px; }
      #igstory .igsub { font-size: 32px; line-height: 1.35; opacity: .72; margin-bottom: 54px; max-width: 900px; }
      #igstory .igc { display: flex; align-items: center; gap: 26px; background: var(--card); border: 1px solid var(--line, rgba(255,255,255,.08));
        border-radius: 28px; padding: 30px 34px; margin-bottom: 22px; }
      #igstory .igrank { font-weight: 800; font-size: 34px; opacity: .45; width: 64px; }
      #igstory .igflag { font-size: 64px; line-height: 1; }
      #igstory .igmain { flex: 1; min-width: 0; }
      #igstory .igname { font-weight: 800; font-size: 50px; line-height: 1.1; letter-spacing: -.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      #igstory .igwhy { font-size: 27px; line-height: 1.3; opacity: .72; margin-top: 8px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
      #igstory .igpill { display: flex; align-items: center; gap: 14px; }
      #igstory .igpill .gr { font-size: 44px; min-width: 110px; height: 88px; line-height: 88px; border-radius: 22px; padding: 0 18px; font-weight: 800; }
      #igstory .igscore { font-weight: 800; font-size: 34px; opacity: .6; width: 56px; text-align: right; }
      #igstory .igfoot { margin-top: auto; display: flex; justify-content: space-between; align-items: flex-end; font-size: 28px; opacity: .72; }
      #igstory .igfoot b { font-weight: 800; opacity: 1; color: #2bb24c; font-size: 34px; }
      #igstory .igfoot small { font-size: 24px; }
    </style>
    <div class="igbrand">🌍 WanderGrade</div>
    <div class="igh1">Where to go in ${esc(MONTHS[MONTH - 1])}</div>
    <div class="igsub">Top value picks for travelers from the US — prices vs home, safety, weather and flights, graded A+ to F.</div>
    ${cards}
    <div class="igfoot"><div><b>wandergrade.com</b><br><small>Every country, graded. Free, no sign-up.</small></div><div><small>As of ${esc(asOf)}</small></div></div>`;
  await evaluate(`(() => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const d = document.createElement('div'); d.id = 'igstory'; d.innerHTML = ${JSON.stringify(html)};
    document.body.appendChild(d);
  })()`);
  await setSize(1080, 1920, false);
  await sleep(1200);   // font + pill styles settle
  const fits = await evaluate(`(() => { const s = document.getElementById('igstory'); const f = s.querySelector('.igfoot'); return { h: s.scrollHeight, footBottom: f.getBoundingClientRect().bottom }; })()`);
  console.log('panel', JSON.stringify(fits));
  const shot = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1080, height: 1920, scale: 1 }, captureBeyondViewport: true });
  fs.writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
  console.log('wrote', OUT, fs.statSync(OUT).size, 'bytes; console errors', errs.length);
};

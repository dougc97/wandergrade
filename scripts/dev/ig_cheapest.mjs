// ig_cheapest.mjs — Instagram story frames for next month's cheapest list
// (posted on the 15th), and with FLIP=1 the "month flip" set. Every number
// is read from the live server-rendered /cheapest/<month> page at render time
// (and, for the flip, /api/flight-value and /slugs.json); nothing is posted.
//
//   cd scripts/dev && CDP_TIMEOUT=55 node cdp.mjs ./ig_cheapest.mjs
//   cd scripts/dev && FLIP=1 CDP_TIMEOUT=55 node cdp.mjs ./ig_cheapest.mjs
//
// MONTH (1-12 or an English name) defaults to next month; POSTED (YYYY-MM-DD,
// the day Doug posts, for the sidecar and utm_campaign) to today; TODAY
// injects the date the "as of" check compares with (tests); OUT_DIR sets
// where the PNGs and the sidecar .txt go (default shots/ig/, gitignored);
// SITE overrides the base URL. Refuses to render when the page's "as of" isn't
// today in UTC, when it's degraded (no-store) or when its list isn't
// available. In this cloud container Node's fetch needs NODE_USE_ENV_PROXY=1.
import path from 'node:path';
import * as D from './ig_data.mjs';
import * as F from './ig_frame.mjs';

const { esc } = F;
// The US origin hub is New York (fxtracker/flights.py ORIGIN_HUBS["US"]).
const FARE_LABEL = 'round trip from New York (cached)';

function monthOf(env, today) {
  if (!env.MONTH) return D.nextMonth(+today.slice(5, 7));
  const m = /^\d+$/.test(env.MONTH) ? +env.MONTH : D.MONTHS.findIndex((x) => x.toLowerCase() === env.MONTH.toLowerCase()) + 1;
  if (!(m >= 1 && m <= 12)) throw new Error('MONTH must be 1-12 or a month name, got ' + env.MONTH);
  return m;
}
const link = (site, m, campaign) =>
  `${site}/cheapest/${D.monthSlug(m)}?utm_source=instagram&utm_medium=story&utm_campaign=${campaign}`;
// "US State Dept · Level 1: Exercise normal precautions": the column header,
// then the pill's own words. Never a level outside 1-2 on a frame.
const stateLine = (r) => {
  if (!(r.level === 1 || r.level === 2)) throw new D.Refusal(`${r.name}'s US State Dept pill reads "${r.levelPill}": not Level 1-2, refusing.`);
  return `US State Dept · <b>${esc(r.levelPill)}</b>`;
};
const fareLine = (r) => (r.fare
  ? `<div><b>${esc(r.fare.text)}</b>, ${esc(r.fare.band)} for this route · ${FARE_LABEL}</div>` : '');
const factLines = (r, { fare = true } = {}) => `
  <div>Prices vs US <b>${esc(r.pct)}%${r.dagger ? '†' : ''}</b> · national average</div>
  <div>Weather score <b>${esc(r.wx)}</b>${r.tempC != null ? ` · ${esc(r.tempC)}°C / ${esc(r.tempF)}°F avg` : ''}</div>
  <div>${stateLine(r)}</div>
  ${fare ? fareLine(r) : ''}`;

// ---- the monthly list --------------------------------------------------------------

async function planList({ getter, today, posting, m, site }) {
  const r = await D.getChecked(getter, `/cheapest/${D.monthSlug(m)}`, 'html');
  const p = D.parseCheapest(r.body, r.cacheControl, m);
  D.checkFresh(`/cheapest/${D.monthSlug(m)}`, p.asOf, today);
  const series = `cheapest-${D.monthSlug(m)}`;
  const asOf = `As of ${p.asOfDay}`;
  if (p.rows.length < 2) {
    return { skip: `only ${p.rows.length} countr${p.rows.length === 1 ? 'y qualifies' : 'ies qualify'} for ${p.monthName}: no poll to run`, series, asOf: p.asOf };
  }
  const top = p.rows.slice(0, 3);
  top.forEach(stateLine);   // refuses outright on a Level 3-4 pill
  const nq = `${p.n} ${p.n === 1 ? 'qualifies' : 'qualify'}`;
  const f1 = `${F.brand()}
    <div class="igh1 m">Cheapest countries for ${esc(p.monthName)}, from the US:<br><span class="green">${esc(nq)}</span></div>
    <div class="igsub">The rule, from the page:</div>
    <div class="igchips">${p.chips.map((c) => `<div class="igchip">${esc(c)}</div>`).join('')}</div>
    <div class="igsub" style="margin-top:36px">Ranked by WanderGrade's value grade for a traveller from the US.</div>
    <div class="igspace"></div>${F.foot(asOf, 'Full list at the link · free, no sign-up')}`;
  const cards = top.map((x) => `
    <div class="igc col">
      <div class="igrow"><div class="igrank">#${x.rank}</div><div class="igflag">${esc(x.flag)}</div>
        <div class="igmain"><div class="igname">${esc(D.displayName(x.name))}</div></div>${F.pill(x.gradeCls, x.grade, x.score)}</div>
      <div class="igfacts">${factLines(x)}</div>
    </div>`).join('');
  const dag = top.some((x) => x.dagger) && p.altNote ? `<div class="igquote">${esc(p.altNote)}</div>` : '';
  const f2 = `${F.brand()}
    <div class="igh1 s">${esc(p.monthName)}'s top 3</div>
    ${cards}${dag}
    <div class="igspace"></div>${F.foot(asOf)}`;
  const [a, b] = p.rows;
  const question = `${p.monthName}: ${D.displayName(a.name)} or ${D.displayName(b.name)}?`;
  const f3 = `${F.brand()}
    <div class="igh1 s">Your pick for ${esc(p.monthName)}?</div>
    <div class="iggrid">${[a, b].map((x) => `<div class="igc"><div class="igflag">${esc(x.flag)}</div><div class="igname">${esc(D.displayName(x.name))}</div>${F.pill(x.gradeCls, x.grade, x.score)}</div>`).join('')}</div>
    <div class="igspace"></div>${F.band('poll', 300)}<div style="height:30px"></div>${F.band('link', 130)}<div style="height:24px"></div>
    ${F.foot(`${asOf} · fares are cached New York searches, not live`)}`;
  const url = link(site, m, `cheapest-${posting.slice(0, 7)}`);
  return {
    series, asOf: p.asOf, canvas: `/cheapest/${D.monthSlug(m)}`,
    frames: [{ name: 'f1', html: f1 }, { name: 'f2', html: f2 }, { name: 'f3', html: f3 }],
    sidecar: {
      series: `Cheapest countries for ${p.monthName} ${p.year}, from the US`, posting, asOf: p.asOfDay, link: url,
      frames: [`"${p.monthName}: ${nq}" with the four rule chips`, 'the top 3 as cards', 'poll band, link sticker band, footer'],
      sticker: { kind: 'Poll', frame: 3, question, options: [D.displayName(a.name), D.displayName(b.name)],
                 answer: `none (a poll); the page ranks ${D.displayName(a.name)} #1 (${a.grade} ${a.score}) and ${D.displayName(b.name)} #2 (${b.grade} ${b.score})` },
      caption: `${p.n} ${p.n === 1 ? 'country qualifies' : 'countries qualify'} for ${p.monthName} from the US: ${p.chips.join(', ')}. Full list at the link.`,
      notes: [`Rule, quoted from the page: ${p.rule}`,
        ...top.filter((x) => !x.fare).map((x) => `${x.name} has no cached fare for ${p.monthName} (the page shows "—*"), so its card shows none.`),
        ...(top.some((x) => x.dagger) ? [`† ${p.altNote}`] : [])],
    },
  };
}

// ---- the month flip --------------------------------------------------------------

async function planFlip({ getter, today, posting, m, site }) {
  const m2 = D.nextMonth(m);
  const [r1, r2] = [await D.getChecked(getter, `/cheapest/${D.monthSlug(m)}`, 'html'),
                    await D.getChecked(getter, `/cheapest/${D.monthSlug(m2)}`, 'html')];
  const p1 = D.parseCheapest(r1.body, r1.cacheControl, m), p2 = D.parseCheapest(r2.body, r2.cacheControl, m2);
  D.checkFresh(`/cheapest/${D.monthSlug(m)}`, p1.asOf, today);
  D.checkFresh(`/cheapest/${D.monthSlug(m2)}`, p2.asOf, today);
  const series = `flip-${D.monthSlug(m)}-${D.monthSlug(m2)}`;
  const pick = D.pickFlip(p1, p2);
  if (!pick) return { skip: `no country in ${p1.monthName}'s top 10 drops a full letter or more in ${p2.monthName}`, series, asOf: p1.asOf };
  const { a, b } = pick;
  stateLine(a); stateLine(b);
  const fv = (await D.getChecked(getter, '/api/flight-value', 'json')).json;
  const slugs = (await D.getChecked(getter, '/slugs.json', 'json')).json;
  const iso = slugs[a.slug];
  const c1 = iso && D.fareCity(fv, iso, m), c2 = iso && D.fareCity(fv, iso, m2);
  const fares = !!(c1 && c2 && c1.city === c2.city && a.fare && b.fare);
  const name = D.displayName(a.name);
  const asOf = `As of ${p1.asOfDay}`;
  const question = `${name}: ${p1.monthName} or ${p2.monthName}?`;
  const f1 = `${F.brand()}
    <div class="igkick">Same country, next two months</div>
    <div class="igflag" style="font-size:150px;margin:26px 0 6px">${esc(a.flag)}</div>
    <div class="igh1 m">${esc(question)}</div>
    <div class="igsub">Which month grades better for a traveller from the US? Vote, then tap through.</div>
    <div class="igspace"></div>${F.band('poll', 300)}<div style="height:40px"></div>${F.foot(asOf)}`;
  const monthFrame = (x, p, last) => `${F.brand()}
    <div class="igkick">${esc(name)} in ${esc(p.monthName)}</div>
    <div class="igrow" style="margin:30px 0 30px"><div class="igflag" style="font-size:110px">${esc(x.flag)}</div>${F.pill(x.gradeCls, x.grade, x.score, true)}</div>
    <div class="igc col"><div class="igfacts">${factLines(x, { fare: fares })}</div></div>
    <div class="igsub" style="margin-top:20px">#${x.rank} of ${p.n} on ${esc(p.monthName)}'s cheapest list.</div>
    <div class="igspace"></div>${last ? F.band('link', 130) + '<div style="height:24px"></div>' : ''}
    ${F.foot(fares ? `${asOf} · fares are cached New York searches, not live` : asOf)}`;
  const better = a.score >= b.score ? p1.monthName : p2.monthName;
  return {
    series, asOf: p1.asOf, canvas: `/cheapest/${D.monthSlug(m)}`,
    frames: [{ name: 'f1', html: f1 }, { name: 'f2', html: monthFrame(a, p1, false) }, { name: 'f3', html: monthFrame(b, p2, true) }],
    sidecar: {
      series: `Month flip: ${name}, ${p1.monthName} vs ${p2.monthName}`, posting, asOf: p1.asOfDay,
      link: link(site, m, `flip-${posting.slice(0, 7)}`),
      frames: ['poll', `${p1.monthName}: grade, weather${fares ? ', fare' : ''}`, `${p2.monthName}: grade, weather${fares ? ', fare' : ''}; link sticker band`],
      sticker: { kind: 'Poll', frame: 1, question, options: [p1.monthName, p2.monthName],
                 answer: `${better} grades better: ${a.grade} ${a.score} in ${p1.monthName}, ${b.grade} ${b.score} in ${p2.monthName}` },
      caption: `${name} grades ${a.grade} in ${p1.monthName} and ${b.grade} in ${p2.monthName} for a traveller from the US. ${p1.monthName}'s full cheapest list at the link.`,
      notes: [`Picked as the biggest full-letter drop among ${p1.monthName}'s top 10 (score ${a.score} -> ${b.score}, ${pick.drop} points; ties go to the higher ${p1.monthName} rank).`,
        fares ? `Fares shown: /api/flight-value has the same destination city (${c1.city}) for both months.`
          : `No fares shown: ${!iso ? 'no ISO for ' + a.slug : !c1 || !c2 ? '/api/flight-value has no city for one of the months' : `the cached fares fly to different cities (${c1.city} in ${p1.monthName}, ${c2.city} in ${p2.monthName})`}${(!a.fare || !b.fare) && c1 && c2 && c1.city === c2.city ? ' / the page shows no fare for a month' : ''}.`],
    },
  };
}

export async function plan({ env = process.env, getter = D.liveGetter(), site = D.SITE } = {}) {
  const today = D.todayUTC(env);
  const posting = env.POSTED || today;
  const m = monthOf(env, today);
  return (env.FLIP === '1' ? planFlip : planList)({ getter, today, posting, m, site });
}

export async function run(t, p, dir = F.outDir()) {
  const base = path.join(dir, `${p.series}-${p.asOf}`);
  if (p.skip) {
    F.writeSidecar(base + '.txt', { series: p.series, posting: process.env.POSTED || D.todayUTC(), asOf: p.asOf,
      notes: [`skip this month: ${p.skip}. Nothing rendered.`] });
    console.log('SKIP:', p.skip, '->', base + '.txt');
    return;
  }
  await F.openCanvas(t, D.SITE + p.canvas);
  const flag = await F.flagCheck(t.evaluate, p.frames.length && /<div class="igflag"[^>]*>([^<]+)</.exec(p.frames.map((f) => f.html).join(''))[1]);
  console.log('flag check', JSON.stringify(flag));
  for (const f of p.frames) await F.renderFrame(t, { html: f.html, out: `${base}-${f.name}.png` });
  F.writeSidecar(base + '.txt', p.sidecar);
  console.log('wrote', p.frames.length, 'frames and', base + '.txt');
}

export default async (t) => {
  let p;
  try { p = await plan(); } catch (e) {
    if (e instanceof D.Refusal) { console.log('REFUSED:', e.message); return; }
    throw e;
  }
  await run(t, p);
};

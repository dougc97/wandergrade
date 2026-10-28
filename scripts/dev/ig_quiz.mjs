// ig_quiz.mjs — Instagram quiz-story frames from the live site's own data:
//
//   KIND=dollar  "your dollar after inflation", early each month (/dollar-strength,
//                with /guide-facts.json and /slugs.json for the US State Dept levels)
//   KIND=price   "cheaper than you think", every 2 weeks (/guide-facts.json, /slugs.json);
//                SLIDER=1 for the one-country slider variant
//
//   cd scripts/dev && KIND=dollar CDP_TIMEOUT=55 node cdp.mjs ./ig_quiz.mjs
//   cd scripts/dev && KIND=price CDP_TIMEOUT=55 node cdp.mjs ./ig_quiz.mjs
//   cd scripts/dev && KIND=price SLIDER=1 CDP_TIMEOUT=55 node cdp.mjs ./ig_quiz.mjs
//
// POSTED (YYYY-MM-DD, default today) dates the sidecar, the utm_campaign and
// the price sets' rotation (ISO week); TODAY injects the date the "as of"
// check compares with (tests); OUT_DIR, SITE as in ig_cheapest.mjs. Refuses
// to render unless the data is today's in UTC: for KIND=dollar the exchange-
// rate date on /dollar-strength AND /guide-facts.json's _asof (the levels it
// filters by), for KIND=price the _asof. Frames are drawn on the server-
// rendered /cheapest/<next month> page; nothing is posted anywhere. In this
// cloud container Node's fetch needs NODE_USE_ENV_PROXY=1.
import path from 'node:path';
import * as D from './ig_data.mjs';
import * as F from './ig_frame.mjs';

const { esc } = F;
const utm = (campaign) => `utm_source=instagram&utm_medium=story&utm_campaign=${campaign}`;
const pctAbs = (t) => t.replace(/^[+−-]/, '');   // "−4.2%" -> "4.2%"

// ---- KIND=dollar -------------------------------------------------------------------

async function planDollar({ getter, today, posting, site }) {
  const ds = D.parseDollar((await D.getChecked(getter, '/dollar-strength', 'html')).body);
  D.checkFresh('/dollar-strength (exchange-rate date)', ds.asOf, today);
  const facts = (await D.getChecked(getter, '/guide-facts.json', 'json')).json;
  D.checkFresh('/guide-facts.json (_asof, the US State Dept levels)', facts._asof, today);
  const slugs = (await D.getChecked(getter, '/slugs.json', 'json')).json;
  const series = 'dollar';
  const el = D.dollarEligible(ds, facts, slugs);
  const q = D.pickSignFlip(el);
  const further = D.wentFurther(el);
  const boliviaNote = 'Bolivia (BOB) is left off every frame: its jump comes from an official-rate change a frame can\'t explain, and moving it down would show the list out of order.';
  if (!q) return { skip: 'no allowlisted currency is up before inflation and down after it this month', series, asOf: ds.asOf, notes: [boliviaNote] };
  if (further.length < 4) return { skip: `only ${further.length} US State Dept Level 1-2 rows went further after inflation`, series, asOf: ds.asOf, notes: [boliviaNote] };
  const name = D.displayName(q.place);
  const asOf = `As of ${ds.asOfDay}`;
  const yes = `Yes, ~${pctAbs(q.beforeText)} further`, same = 'About the same', no = `No, ~${pctAbs(q.afterText)} less far`;
  const question = `After inflation, does it go further in ${name}?`;
  const pair = D.inflationPair(q.afterTitle);
  if (!pair) throw new D.Refusal(`/dollar-strength: ${q.code}'s After-inflation figure has no inflation pair in its title ("${q.afterTitle}").`);
  const f1 = `${F.brand()}
    <div class="igkick">Your dollar after inflation</div>
    <div class="igh1 m">$1 buys <span class="green">${esc(pctAbs(q.beforeText))} more</span> ${esc(q.currency)} vs its 1-year average.</div>
    <div class="igrow" style="margin:6px 0 0"><div class="igflag">${esc(q.flag)}</div>
      <div class="igname" style="font-size:44px;flex:1">${esc(question)}</div></div>
    <div class="igspace"></div>${F.band('quiz', 520)}<div style="height:30px"></div>${F.foot(asOf, 'Answer on the next frame')}`;
  const f2 = `${F.brand()}
    <div class="igkick">After inflation, in ${esc(name)}</div>
    <div class="igbig ${q.after < 0 ? 'neg' : 'pos'}">${esc(q.afterText)}</div>
    <div class="igh1 s" style="margin-top:0">$1 goes ~${esc(pctAbs(q.afterText))} ${q.after < 0 ? 'less far' : 'further'} in ${esc(name)}, vs its 1-year average.</div>
    <div class="igc col" style="margin-top:24px"><div class="igfacts">
      <div>Before inflation: $1 buys <b>${esc(pctAbs(q.beforeText))} more</b> ${esc(q.currency)}</div>
      <div>Inflation: <b>${esc(pair)}</b></div>
      <div>US State Dept · <b>Level ${esc(q.level)}</b></div>
    </div></div>
    <div class="igspace"></div>${F.foot(asOf)}`;
  const rowsHtml = further.map((r) => `
    <div class="igc"><div class="igflag">${esc(r.flag)}</div>
      <div class="igmain"><div class="igname" style="font-size:40px">${esc(r.currency)}</div>
        <div class="igwhy">${esc(D.displayName(r.place))} · US State Dept Level ${esc(r.level)}</div></div>
      <div class="igval green">${esc(r.afterText)}</div></div>`).join('');
  const url = `${site}/dollar-strength?${utm(`dollar-${posting.slice(0, 7)}`)}`;
  const f3 = `${F.brand()}
    <div class="igh1 s">Where it did go further, after inflation <span style="opacity:.6">(US State Dept Level 1–2 only)</span></div>
    ${rowsHtml}
    <div class="igspace"></div>${F.band('link', 130)}<div style="height:24px"></div>
    ${F.foot(`each vs its own 1-year average · past moves, not a forecast · as of ${ds.asOfDay}`, 'Every currency at the link')}`;
  return {
    series, asOf: ds.asOf, canvas: `/cheapest/${D.monthSlug(D.nextMonth(+today.slice(5, 7)))}`,
    frames: [{ name: 'f1', html: f1 }, { name: 'f2', html: f2 }, { name: 'f3', html: f3 }],
    sidecar: {
      series: `Your dollar after inflation: ${q.code} ${q.currency}, ${name}`, posting, asOf: ds.asOfDay, link: url,
      frames: ['the question, quiz band', 'the answer: the after-inflation figure and the inflation pair', 'where it did go further (top 4), link sticker band'],
      sticker: { kind: 'Quiz', frame: 1, question, options: [yes, same, no], answer: q.after < 0 ? no : yes },
      caption: `$1 buys ${pctAbs(q.beforeText)} more ${q.currency} than its 1-year average, but after inflation it goes ~${pctAbs(q.afterText)} less far in ${name}. Every currency at the link.`,
      notes: [boliviaNote,
        `Quiz figures from /dollar-strength's ${q.code} row: before inflation ${q.beforeText}, after inflation ${q.afterText} ("${q.afterTitle}").`,
        `Frame 3 rows, in the page's order: ${further.map((r) => `${r.code} (${r.place}) ${r.afterText}`).join(', ')}. Kept: US State Dept Level 1-2 per /guide-facts.json (src "us" only), no † figure, not Bolivia.`],
    },
  };
}

// ---- KIND=price -----------------------------------------------------------------------

async function planPrice({ getter, today, posting, site, slider }) {
  const facts = (await D.getChecked(getter, '/guide-facts.json', 'json')).json;
  D.checkFresh('/guide-facts.json (_asof)', facts._asof, today);
  const slugs = (await D.getChecked(getter, '/slugs.json', 'json')).json;
  const asOfDay = D.isoToDay(facts._asof), asOf = `As of ${asOfDay}`;
  const canvas = `/cheapest/${D.monthSlug(D.nextMonth(+today.slice(5, 7)))}`;
  const guideLink = (iso) => {
    const slug = D.isoToSlug(slugs, iso);
    if (!slug) throw new D.Refusal(`no /guide slug for ${iso} in /slugs.json`);
    return `${site}/guide/${slug}?${utm(`pricequiz-${posting.slice(0, 7)}`)}&utm_content=${iso.toLowerCase()}`;
  };
  const nm = (iso) => D.displayName(D.factName(facts, iso));
  if (slider) {
    const { iso, tried } = D.pickSlider(facts, posting);
    if (!iso) return { skip: 'no slider country passes today: ' + tried.join('; '), series: 'price-slider', asOf: facts._asof };
    const f = facts[iso], N = D.priceCount(facts), more = D.pricierThan(facts, f.pct);
    const question = `${nm(iso)}: everyday prices are what % of the US?`;
    const f1 = `${F.brand()}
      <div class="igkick">Cheaper than you think?</div>
      <div class="igflag" style="font-size:170px;margin:30px 0 10px">${esc(D.flagEmoji(iso))}</div>
      <div class="igh1 m">${esc(nm(iso))}: everyday prices are what % of the US?</div>
      <div class="igsub">The US = 100%. Slide to guess.</div>
      <div class="igspace"></div>${F.band('slider', 260)}<div style="height:40px"></div>${F.foot(asOf, 'Answer on the next frame')}`;
    const f2 = `${F.brand()}
      <div class="igkick">${esc(nm(iso))}</div>
      <div class="igbig pos">${esc(f.pct)}%</div>
      <div class="igh1 s" style="margin-top:0">of US prices, as a national average.</div>
      <div class="igsub">Pricier than ${esc(nm(iso))}: ${esc(more)} of the ${esc(N)} countries WanderGrade has a price figure for.</div>
      <div class="igsub">US State Dept · Level ${esc(f.adv)}</div>
      <div class="igspace"></div>${F.band('link', 130)}<div style="height:24px"></div>${F.foot(`national averages · ${asOf}`)}`;
    return {
      series: 'price-slider', asOf: facts._asof, canvas,
      frames: [{ name: 'f1', html: f1 }, { name: 'f2', html: f2 }],
      sidecar: {
        series: `Price slider: ${nm(iso)}`, posting, asOf: asOfDay, link: guideLink(iso),
        frames: ['the question, slider band', 'the reveal, link sticker band'],
        sticker: { kind: 'Emoji slider', frame: 1, question, options: ['0% (left) to 100% = US prices (right)'], answer: `${f.pct}% of the US` },
        caption: `Everyday prices in ${nm(iso)}: ${f.pct}% of the US, as a national average. The guide's at the link.`,
        notes: [`${N} countries have a price figure on /guide-facts.json (England, Scotland and Wales repeat the UK's figure and count once); ${more} of them have a higher one.`],
      },
    };
  }
  const { set, tried } = D.pickPriceSet(facts, posting);
  if (!set) return { skip: 'no price set passes today: ' + tried.join('; '), series: 'price', asOf: facts._asof };
  const win = set.reduce((a, b) => (facts[b].pct < facts[a].pct ? b : a));
  const question = 'Which is CHEAPEST on the ground for a US traveller?';
  const grid = (reveal) => `<div class="iggrid">${set.map((iso) => `
    <div class="igc${reveal && iso === win ? ' win' : ''}"><div class="igflag">${esc(D.flagEmoji(iso))}</div>
      <div class="igname">${esc(nm(iso))}</div>
      ${reveal ? `<div class="igval${iso === win ? ' green' : ''}">${esc(facts[iso].pct)}%</div><div class="igwhy">of the US</div>` : ''}</div>`).join('')}</div>`;
  const f1 = `${F.brand()}
    <div class="igh1 m">Which is <span class="green">CHEAPEST</span> on the ground for a US traveller?</div>
    ${grid(false)}
    <div class="igspace"></div>${F.band('quiz', 380)}<div style="height:24px"></div>${F.foot(asOf, 'Answer on the next frame')}`;
  const f2 = `${F.brand()}
    <div class="igh1 s">Everyday prices as a share of the US, national averages</div>
    ${grid(true)}
    <div class="igsub" style="margin-top:28px">Cheapest of the four: <b>${esc(nm(win))}</b>.</div>
    <div class="igspace"></div>${F.band('link', 130)}<div style="height:24px"></div>${F.foot(`national averages · ${asOf}`, `${nm(win)}'s guide at the link`)}`;
  const sorted = [...set].sort((a, b) => facts[a].pct - facts[b].pct);
  return {
    series: 'price', asOf: facts._asof, canvas,
    frames: [{ name: 'f1', html: f1 }, { name: 'f2', html: f2 }],
    sidecar: {
      series: `Cheaper than you think: ${set.map(nm).join(', ')}`, posting, asOf: asOfDay, link: guideLink(win),
      frames: ['four flags, no numbers, quiz band', 'the reveal (national averages), link sticker band'],
      sticker: { kind: 'Quiz', frame: 1, question, options: set.map(nm), answer: nm(win) },
      caption: `Everyday prices, national averages vs the US: ${sorted.map((i) => `${nm(i)} ${facts[i].pct}%`).join(', ')}. ${nm(win)}'s guide at the link.`,
      notes: [`Set picked by ISO week ${D.isoWeek(posting)} of ${posting} (week % ${D.PRICE_SETS.length}); each country US State Dept Level 1-2 (src "us") and at least ${D.PRICE_GAP} points apart.`,
        ...tried.map((t) => 'Skipped set ' + t)],
    },
  };
}

export async function plan({ env = process.env, getter = D.liveGetter(), site = D.SITE } = {}) {
  const today = D.todayUTC(env);
  const posting = env.POSTED || today;
  const kind = env.KIND || 'dollar';
  if (kind === 'dollar') return planDollar({ getter, today, posting, site });
  if (kind === 'price') return planPrice({ getter, today, posting, site, slider: env.SLIDER === '1' });
  throw new Error('KIND must be dollar or price, got ' + kind);
}

export async function run(t, p, dir = F.outDir()) {
  const base = path.join(dir, `${p.series}-${p.asOf}`);
  if (p.skip) {
    F.writeSidecar(base + '.txt', { series: p.series, posting: process.env.POSTED || D.todayUTC(), asOf: p.asOf,
      notes: [`skip this month: ${p.skip}. Nothing rendered.`, ...(p.notes || [])] });
    console.log('SKIP:', p.skip, '->', base + '.txt');
    return;
  }
  await F.openCanvas(t, D.SITE + p.canvas);
  const flag = /<div class="igflag"[^>]*>([^<]+)</.exec(p.frames.map((f) => f.html).join(''));
  if (flag) console.log('flag check', JSON.stringify(await F.flagCheck(t.evaluate, flag[1])));
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

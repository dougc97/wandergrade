// test_ig_parsers.mjs — the Instagram story generators' parsers, selection
// rules and stale-date refusal, run on the live site's pages saved under
// fixtures/ig/ (no network, no browser):  cd scripts/dev && node test_ig_parsers.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as D from './ig_data.mjs';
import { sidecarText } from './ig_frame.mjs';
import { plan as cheapestPlan } from './ig_cheapest.mjs';
import { plan as quizPlan } from './ig_quiz.mjs';
import { safetyFact } from './ig_story.mjs';

const FX = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'ig');
const read = (f) => fs.readFileSync(path.join(FX, f), 'utf8');
// The day the fixtures were saved: every "as of" in them is this date.
const DAY = '2026-10-28';
const FILES = {
  '/cheapest/november': ['cheapest-november.html', 'text/html; charset=utf-8'],
  '/cheapest/december': ['cheapest-december.html', 'text/html; charset=utf-8'],
  '/dollar-strength': ['dollar-strength.html', 'text/html; charset=utf-8'],
  '/guide-facts.json': ['guide-facts.json', 'application/json; charset=utf-8'],
  '/api/flight-value': ['flight-value.json', 'application/json; charset=utf-8'],
  '/slugs.json': ['slugs.json', 'application/json; charset=utf-8'],
};
// A getter serving the fixtures; `over` replaces a path's reply (or its body: a function of the saved one).
const getter = (over = {}) => async (p) => {
  const f = FILES[p];
  const base = f ? { url: p, status: 200, contentType: f[1], cacheControl: 'public, max-age=300', body: read(f[0]) }
    : { url: p, status: 404, contentType: 'text/html', cacheControl: '', body: 'not found' };
  const o = over[p];
  if (!o) return base;
  return typeof o === 'function' ? { ...base, body: o(base.body) } : { ...base, ...o };
};
const env = (e = {}) => ({ TODAY: DAY, POSTED: DAY, ...e });
const SITE = 'https://wandergrade.com';
const json = (f) => JSON.parse(read(f));

let pass = 0, fail = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const eq = (a, b, what = '') => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };
const ok = (c, what) => { if (!c) throw new Error(what); };
async function refuses(p, re) {
  try { await p; } catch (e) {
    if (!(e instanceof D.Refusal)) throw new Error('threw a non-refusal: ' + e.message);
    if (re && !re.test(e.message)) throw new Error('refusal message "' + e.message + '" !~ ' + re);
    return e.message;
  }
  throw new Error('did not refuse');
}
const allHtml = (p) => p.frames.map((f) => f.html).join('\n');

// ---- helpers -------------------------------------------------------------------------

test('a true minus (U+2212) parses as negative; parseFloat alone gives NaN', () => {
  ok(Number.isNaN(parseFloat('−4.2')), 'parseFloat("−4.2") should be NaN');
  eq(D.num('−4.2%'), -4.2); eq(D.num('+9.7%'), 9.7); eq(D.num('$1,301'), 1301); eq(D.num('0.0%'), 0);
});
test('dates: "28 Oct 2026" <-> 2026-10-28, ISO week, TODAY injection', () => {
  eq(D.dayToIso('28 Oct 2026'), '2026-10-28'); eq(D.dayToIso('1 Nov 2026'), '2026-11-01'); eq(D.dayToIso('Oct 28 2026'), null);
  eq(D.isoToDay('2026-11-01'), '1 Nov 2026'); eq(D.isoWeek('2026-10-28'), 44); eq(D.isoWeek('2027-01-01'), 53);
  eq(D.todayUTC({ TODAY: '2026-10-27' }), '2026-10-27');
  ok(/^\d{4}-\d{2}-\d{2}$/.test(D.todayUTC({})), 'todayUTC');
});

// ---- /cheapest parser ------------------------------------------------------------------

test('parseCheapest: lede, rule, chips, rows (November)', () => {
  const p = D.parseCheapest(read('cheapest-november.html'), 'public, max-age=300', 11);
  eq(p.n, 40); eq(p.asOf, DAY); eq(p.asOfDay, '28 Oct 2026'); eq(p.rows.length, 40);
  eq(p.rule, 'The rule: US State Department Level 1 or 2, no “do not travel” from the US, Canada or Germany, local prices at or under 50% of the US and a weather score of 70+ in November.');
  eq(p.chips, ['US State Department Level 1 or 2', 'no “do not travel” from the US, Canada or Germany',
    'local prices at or under 50% of the US', 'a weather score of 70+ in November']);
  // The chips rebuild the rule word for word.
  eq(`The rule: ${p.chips[0]}, ${p.chips[1]}, ${p.chips[2]} and ${p.chips[3]}.`, p.rule);
  eq(p.rows[0], { rank: 1, slug: 'thailand', name: 'Thailand', flag: '🇹🇭', gradeCls: 'gr grAp', grade: 'A+', score: 93,
    pct: 29, dagger: false, wx: 74, tempC: 27, tempF: 81, level: 1, levelPill: 'Level 1: Exercise normal precautions',
    fare: { price: 511, text: '$511', band: 'Low' } });
  const cv = p.rows.find((r) => r.slug === 'cape-verde');
  eq(cv.fare, null, 'Cape Verde shows "—*": no fare');
  ok(p.rows.every((r) => r.level === 1 || r.level === 2), 'every row Level 1-2');
  eq(p.heads.slice(-2), ['US State Dept', 'US round trip']);
  ok(p.fareNote.startsWith('* Fares are cached searches'), 'fare note');
});
test('parseCheapest: December, and a "1 country qualifies" page', () => {
  const p = D.parseCheapest(read('cheapest-december.html'), '', 12);
  eq(p.n, 32); eq(p.monthName, 'December');
  const one = read('cheapest-november.html')
    .replace(/<strong>40<\/strong> countries qualify/, '<strong>1</strong> country qualifies')
    .replace(/(<tbody>[\s\S]*?<\/tr>)[\s\S]*?(<\/tbody>)/, '$1$2');
  const q = D.parseCheapest(one, '', 11);
  eq(q.n, 1); eq(q.rows.map((r) => r.name), ['Thailand']);
});
test('parseCheapest refuses: no-store, unavailable list, no table, a different month', async () => {
  const nov = read('cheapest-november.html');
  await refuses((async () => D.parseCheapest(nov, 'no-store', 11))(), /no-store/);
  const unavailable = nov.replace(/<p class="lede">[\s\S]*?<\/p>/, '<p class="lede">The rule: x. The list isn\'t available right now: prices or climate are not loaded (see the note below).</p>')
    .replace(/<div class="listbox">[\s\S]*?<\/table><\/div>/, '');
  await refuses((async () => D.parseCheapest(unavailable, '', 11))(), /isn't available/);
  await refuses((async () => D.parseCheapest(nov.replace(/<table class="listtable">[\s\S]*?<\/table>/, ''), '', 11))(), /no table/);
  await refuses((async () => D.parseCheapest(nov, '', 12))(), /not December/);
});

// ---- /dollar-strength parser ------------------------------------------------------------

test('parseDollar: rows, exchange-rate date (not the ECB index date), † and no-inflation list', () => {
  const ds = D.parseDollar(read('dollar-strength.html'));
  eq(ds.asOf, DAY, 'from p.asof'); eq(ds.rows.length, 132);
  const t = ds.rows.find((r) => r.code === 'TRY');
  eq([t.currency, t.place, t.slug, t.beforeText, t.before, t.afterText, t.after, t.afterDagger],
    ['Turkish Lira', 'Turkey', 'turkey', '+9.7%', 9.7, '−4.2%', -4.2, false]);
  eq(D.inflationPair(t.afterTitle), 'Turkey ~35%/yr vs the US ~3%/yr (World Bank)');
  const eur = ds.rows.find((r) => r.code === 'EUR');
  eq([eur.currency, eur.place, eur.slug], ['Euro', 'Germany', 'germany'], 'the euro is netted against Germany, its first place');
  ok(ds.rows.find((r) => r.code === 'TWD').afterDagger, 'TWD carries a †');
  ok(ds.noInflation.includes('ARS'), 'ARS is in the no-inflation list');
  ok(!ds.rows.some((r) => r.code === 'ARS'), 'ARS has no table row');
});

// ---- selection rules: KIND=dollar ---------------------------------------------------------

test('dollar: Level 3-4, gap-fills, missing entries, † rows and Bolivia are out', () => {
  const ds = D.parseDollar(read('dollar-strength.html')), facts = json('guide-facts.json'), slugs = json('slugs.json');
  const el = D.dollarEligible(ds, facts, slugs);
  const codes = el.map((r) => r.code);
  for (const c of ['UGX', 'IRR', 'IQD']) ok(ds.rows.some((r) => r.code === c) && !codes.includes(c), `${c} (Level 3-4) dropped`);
  ok(el.every((r) => facts[r.iso].src === 'us' && [1, 2].includes(facts[r.iso].adv)), 'all US Level 1-2');
  ok(!codes.includes('TWD'), '† row dropped'); ok(!codes.includes('BOB'), 'Bolivia dropped');
  ok(!codes.includes('TOP'), 'Tonga (no /guide-facts entry) dropped');
  eq(D.usLevel(facts, 'CI'), null, "Côte d'Ivoire's level is Canada's gap-fill"); eq(D.usLevel(facts, 'TO'), null);
  eq(D.wentFurther(el).map((r) => r.place), ['Sri Lanka', 'Morocco', 'Chile', 'Poland']);
  ok(ds.rows[0].code === 'BOB' && D.wentFurther(el)[0].code !== 'BOB', 'Bolivia, #1 on the page, never in the lead slot');
});
test('dollar: the sign flip, and skipping when nothing flips', () => {
  const ds = D.parseDollar(read('dollar-strength.html')), facts = json('guide-facts.json'), slugs = json('slugs.json');
  const el = D.dollarEligible(ds, facts, slugs);
  eq(D.pickSignFlip(el).code, 'TRY');
  eq(D.pickSignFlip(el.filter((r) => r.code !== 'TRY')).code, 'GHS');
  eq(D.pickSignFlip(el.filter((r) => !['TRY', 'GHS'].includes(r.code))), null);
  // A flip under FLIP_MIN isn't a clear quiz.
  eq(D.pickSignFlip([{ ...el.find((r) => r.code === 'TRY'), before: 0.4, after: -0.3 }]), null);
});
test('dollar plan: frames, quiz, link, Turkey (Türkiye), Bolivia note', async () => {
  const p = await quizPlan({ env: env({ KIND: 'dollar' }), getter: getter(), site: SITE });
  ok(!p.skip, 'renders: ' + p.skip);
  eq(p.frames.length, 3);
  const h = allHtml(p);
  ok(h.includes('$1 buys <span class="green">9.7% more</span> Turkish Lira vs its 1-year average.'), 'F1 wording');
  ok(h.includes('Turkey (Türkiye)') && h.includes('Turkey ~35%/yr vs the US ~3%/yr (World Bank)'), 'display name; quoted pair verbatim');
  ok(!/than a year ago/.test(h) && !/expensive/i.test(h), 'no "than a year ago", never "expensive"');
  ok(!/Bolivia|BOB/.test(h), 'Bolivia on no frame');
  ok(h.includes('each vs its own 1-year average · past moves, not a forecast · as of 28 Oct 2026'), 'F3 footer');
  eq(p.sidecar.sticker.options, ['Yes, ~9.7% further', 'About the same', 'No, ~4.2% less far']);
  eq(p.sidecar.sticker.answer, 'No, ~4.2% less far');
  eq(p.sidecar.link, 'https://wandergrade.com/dollar-strength?utm_source=instagram&utm_medium=story&utm_campaign=dollar-2026-10');
  ok(p.sidecar.notes.some((n) => /Bolivia/.test(n)), 'sidecar says why Bolivia is left off');
  ok(sidecarText(p.sidecar).includes('Correct answer: No, ~4.2% less far'), 'sidecar text');
});
test('dollar plan skips when no allowlisted currency flips', async () => {
  const p = await quizPlan({ env: env({ KIND: 'dollar' }), site: SITE,
    getter: getter({ '/dollar-strength': (b) => b.replace(/>−4\.2%</, '>+0.5%<').replace(/>−1\.9%</, '>+0.2%<') }) });
  ok(p.skip && /no allowlisted currency/.test(p.skip), 'skip: ' + p.skip);
});

// ---- selection rules: KIND=price ----------------------------------------------------------

test('price: N counts England/Scotland/Wales once; sets need 2 points and US Level 1-2', () => {
  const facts = json('guide-facts.json');
  eq(D.priceCount(facts), 165);
  eq(D.priceSetProblem(facts, ['JP', 'ES', 'IT', 'FR']), null);
  ok(/under 2 points/.test(D.priceSetProblem(facts, ['GB', 'DE', 'AT', 'DK'])), 'DK 90 vs GB 91');
  ok(/under 2 points/.test(D.priceSetProblem(facts, ['PT', 'CZ', 'JP', 'FR'])), 'PT 59 vs CZ 59');
  ok(/isn't US State Dept Level 1-2/.test(D.priceSetProblem(facts, ['JP', 'CO', 'IT', 'FR'])), 'Colombia is Level 3');
  ok(/isn't US State Dept Level 1-2/.test(D.priceSetProblem(facts, ['JP', 'CI', 'IT', 'FR'])), "a gap-fill isn't the State Department's");
  ok(/no price figure/.test(D.priceSetProblem(facts, ['JP', 'TW', 'IT', 'FR'])), 'Taiwan has no pct');
  for (const s of D.PRICE_SETS) eq(D.priceSetProblem(facts, s), null, s.join('/'));
});
test('price: rotation by ISO week, fall-through, and skip when no set passes', () => {
  const facts = json('guide-facts.json');
  eq(D.pickPriceSet(facts, '2026-10-28').set, D.PRICE_SETS[44 % 8]);
  eq(D.pickPriceSet(facts, '2026-11-04').set, D.PRICE_SETS[45 % 8]);
  const lvl3 = { ...facts, AR: { ...facts.AR, adv: 3 } };   // week 44's set loses Argentina
  const r = D.pickPriceSet(lvl3, '2026-10-28');
  eq(r.set, D.PRICE_SETS[5]); ok(/AR isn't US State Dept/.test(r.tried[0]), 'says why');
  const none = Object.fromEntries(Object.entries(facts).map(([k, v]) => [k, k === '_asof' ? v : { ...v, adv: 3 }]));
  eq(D.pickPriceSet(none, '2026-10-28').set, null);
});
test('price plans: quiz and slider (TODAY = the facts\' _asof)', async () => {
  const facts = json('guide-facts.json');
  const p = await quizPlan({ env: env({ KIND: 'price', TODAY: facts._asof }), getter: getter(), site: SITE });
  ok(!p.skip, 'renders');
  const h = allHtml(p);
  ok(h.includes('Which is <span class="green">CHEAPEST</span> on the ground for a US traveller?'), 'F1 question');
  ok(!/\d+%/.test(p.frames[0].html), 'F1 has no numbers');
  ok(!(/cheaper/i.test(p.frames[1].html) && /% of the US|of the US/.test(p.frames[1].html)), 'never "X% cheaper" beside "X% of the US"');
  ok(/national averages/.test(p.frames[1].html), 'labelled national averages');
  const win = p.sidecar.sticker.answer;
  ok(p.sidecar.link.startsWith(`https://wandergrade.com/guide/`) && /utm_campaign=pricequiz-2026-10&utm_content=[a-z]{2}$/.test(p.sidecar.link), p.sidecar.link);
  ok(p.sidecar.sticker.options.includes(win), 'answer is an option');
  const s = await quizPlan({ env: env({ KIND: 'price', SLIDER: '1', TODAY: facts._asof }), getter: getter(), site: SITE });
  ok(allHtml(s).includes('of the 165 countries WanderGrade has a price figure for'), 'slider N wording');
  ok(!/of every country/.test(allHtml(s)), 'never "of every country"');
});

// ---- selection rules: /cheapest and the flip ------------------------------------------------

test('cheapest plan: chips, top 3, fares only where the page has one, poll, link', async () => {
  const p = await cheapestPlan({ env: env({ MONTH: '11' }), getter: getter(), site: SITE });
  eq(p.frames.length, 3);
  const h = allHtml(p);
  ok(h.includes('<b>$511</b>, Low for this route · round trip from New York (cached)'), 'fare with its band');
  ok(h.includes('US State Dept · <b>Level 1: Exercise normal precautions</b>'), 'level quoted from the pill');
  ok(h.includes('fares are cached New York searches, not live'), 'F3 footer');
  eq(p.sidecar.sticker.question, 'November: Thailand or Egypt?');
  eq(p.sidecar.link, 'https://wandergrade.com/cheapest/november?utm_source=instagram&utm_medium=story&utm_campaign=cheapest-2026-10');
  // MONTH defaults to next month.
  eq((await cheapestPlan({ env: env({}), getter: getter(), site: SITE })).series, 'cheapest-november');
  // A top-3 row with no fare prints none.
  const nofare = await cheapestPlan({ env: env({ MONTH: '11' }), site: SITE,
    getter: getter({ '/cheapest/november': (b) => b.replace('$511 <span class="fvband low" title="Typical for this route: $729–$916 (the middle half of its monthly fares)">Low</span>', '—<sup class="fn">*</sup>') }) });
  ok(!allHtml(nofare).includes('$511'), 'no fare printed for "—*"');
});
test('cheapest plan refuses a Level 3-4 pill and skips an empty list', async () => {
  await refuses(cheapestPlan({ env: env({ MONTH: '11' }), site: SITE,
    getter: getter({ '/cheapest/november': (b) => b.replace('<span class="lvl lvl2" title="U.S. State Department: Exercise Increased Caution, dated 15 Jul 2025">Level 2: Exercise increased caution</span>', '<span class="lvl lvl3" title="x">Level 3: Reconsider travel</span>') }) }), /not Level 1-2/);
  const empty = await cheapestPlan({ env: env({ MONTH: '11' }), site: SITE,
    getter: getter({ '/cheapest/november': (b) => b.replace(/<strong>40<\/strong> countries qualify/, '<strong>0</strong> countries qualify')
      .replace(/<tbody>[\s\S]*?<\/tbody>/, '<tbody><tr><td class="name" data-l="Country">No country meets the rule for this month right now.</td></tr></tbody>') }) });
  ok(empty.skip, 'skip when nothing qualifies');
});
test('flip: full-letter drops, ties to the higher rank, both pages only', () => {
  const p1 = D.parseCheapest(read('cheapest-november.html'), '', 11), p2 = D.parseCheapest(read('cheapest-december.html'), '', 12);
  ok(D.fullLetterDrop('A', 'B+') && D.fullLetterDrop('A', 'B') && D.fullLetterDrop('A+', 'B'), 'full-letter drops');
  ok(!D.fullLetterDrop('A+', 'A') && !D.fullLetterDrop('B+', 'B') && !D.fullLetterDrop('B', 'A'), 'not full-letter drops');
  const za = p1.rows.find((r) => r.slug === 'south-africa'), za2 = p2.rows.find((r) => r.slug === 'south-africa');
  const ma = p1.rows.find((r) => r.slug === 'morocco'), ma2 = p2.rows.find((r) => r.slug === 'morocco');
  eq([za.grade, za.score, za2.grade, za2.score, ma.grade, ma.score, ma2.grade, ma2.score], ['A', 87, 'B', 77, 'A', 90, 'B+', 80]);
  const f = D.pickFlip(p1, p2);
  eq([f.a.name, f.drop], ['Morocco', 10], 'tie at 10 goes to Morocco, #3 vs #5');
  // Without Morocco on December's page it doesn't count (no grade inferred): South Africa.
  eq(D.pickFlip(p1, { ...p2, rows: p2.rows.filter((r) => r.slug !== 'morocco') }).a.name, 'South Africa');
  eq(D.pickFlip(p1, { ...p2, rows: p2.rows.filter((r) => !['morocco', 'south-africa'].includes(r.slug)) }).a.name, 'Egypt', 'A 92 -> B+ 83');
  eq(D.pickFlip(p1, p1), null, 'no drop, no pick');
  eq(D.pickFlip(p1, { ...p2, rows: p2.rows.filter((r) => !p1.rows.slice(0, 10).some((x) => x.slug === r.slug)) }), null, 'none of the top 10 listed next month');
});
test('flip: fares only with the same destination city both months', () => {
  const fv = json('flight-value.json');
  eq(D.fareCity(fv, 'TH', 12), { key: '2026-12', price: 859, city: 'BKK' });
  eq(D.fareCity(fv, 'TH', 5).city, 'HKT');
  eq(D.fareCity(fv, 'TH', 4), null, 'missing month');
  eq(D.fareCity({ ...fv, countries: { XX: { pending: true } } }, 'XX', 11), null, 'pending');
  eq([D.fareCity(fv, 'MA', 11).city, D.fareCity(fv, 'MA', 12).city], ['RAK', 'CMN']);
  eq([D.fareCity(fv, 'ZA', 11).city, D.fareCity(fv, 'ZA', 12).city], ['CPT', 'CPT']);
});
test('flip plan: Morocco, no fares (RAK vs CMN), link, and skip with no drop', async () => {
  const p = await cheapestPlan({ env: env({ FLIP: '1' }), getter: getter(), site: SITE });
  eq(p.sidecar.sticker.question, 'Morocco: November or December?');
  ok(!/\$\d/.test(allHtml(p)), 'no fare on any frame');
  ok(p.sidecar.notes.some((n) => /RAK in November, CMN in December/.test(n)), 'says why');
  eq(p.sidecar.link, 'https://wandergrade.com/cheapest/november?utm_source=instagram&utm_medium=story&utm_campaign=flip-2026-10');
  ok(!/last chance|deadline/i.test(allHtml(p)), 'no deadline wording');
  // With South Africa picked (Morocco gone from December), CPT both months keeps the fares.
  const za = await cheapestPlan({ env: env({ FLIP: '1' }), site: SITE,
    getter: getter({ '/cheapest/december': (b) => b.replace(/<tr><td class="num" data-l="#">\d+<\/td><td class="name" data-l="Country"><span class="rk">\d+\.<\/span> 🇲🇦[\s\S]*?<\/tr>/, '')
      .replace(/<strong>32<\/strong> countries/, '<strong>31</strong> countries') }) });
  eq(za.sidecar.sticker.question, 'South Africa: November or December?');
  ok(allHtml(za).includes('<b>$778</b>, Low for this route'), 'November fare kept: ' + allHtml(za).match(/\$\d[^<]*/g));
  const none = await cheapestPlan({ env: env({ FLIP: '1' }), site: SITE, getter: getter({ '/cheapest/december': () => read('cheapest-november.html').replace(/November/g, 'December').replace('/cheapest/december', '/cheapest/january') }) });
  ok(none.skip && /drops a full letter/.test(none.skip), 'skip this month: ' + none.skip);
});

// ---- the stale-date refusal and blocked GETs ----------------------------------------------------

test('stale-date refusal: every script, with an injected date', async () => {
  await refuses(cheapestPlan({ env: env({ TODAY: '2026-10-29' }), getter: getter(), site: SITE }), /as of 2026-10-28, not today \(2026-10-29 UTC\)/);
  await refuses(cheapestPlan({ env: env({ FLIP: '1', TODAY: '2026-10-29' }), getter: getter(), site: SITE }), /not today/);
  await refuses(quizPlan({ env: env({ KIND: 'dollar', TODAY: '2026-10-29' }), getter: getter(), site: SITE }), /dollar-strength.*not today/);
  await refuses(quizPlan({ env: env({ KIND: 'price', TODAY: '2026-10-29' }), getter: getter(), site: SITE }), /_asof.*not today/);
  // The dollar quiz also needs today's levels.
  await refuses(quizPlan({ env: env({ KIND: 'dollar' }), site: SITE,
    getter: getter({ '/guide-facts.json': (b) => b.replace(/"_asof":"[\d-]+"/, '"_asof":"2026-10-27"') }) }), /guide-facts.*2026-10-27, not today/);
  await refuses((async () => D.checkFresh('x', null, DAY))(), /no "as of"/);
});
test('a blocked or odd GET stops the run', async () => {
  await refuses(cheapestPlan({ env: env({}), site: SITE, getter: getter({ '/cheapest/november': { status: 403, body: '<html>Just a moment...</html>' } }) }), /returned 403/);
  await refuses(quizPlan({ env: env({ KIND: 'price' }), site: SITE, getter: getter({ '/guide-facts.json': { contentType: 'text/html', body: '<html>challenge</html>' } }) }), /not JSON/);
  await refuses(quizPlan({ env: env({ KIND: 'dollar' }), site: SITE, getter: getter({ '/dollar-strength': { body: '<html>Checking your browser</html>' } }) }), /not the site's server-rendered page/);
});

// ---- wording guards ----------------------------------------------------------------------------

test('wording: "safe"/"safest" and Airbnb never pass; ig_story turns the safety phrase into the State Dept level', () => {
  ok(D.wordingProblems('the safest country').length && D.wordingProblems('Safe & cheap').length && D.wordingProblems('book an Airbnb').length, 'caught');
  eq(D.wordingProblems('safety, weather and flights · Level 1: Exercise normal precautions'), []);
  let threw = false; try { sidecarText({ series: 'x', posting: DAY, asOf: DAY, caption: 'The safest pick' }); } catch { threw = true; }
  ok(threw, 'sidecar refuses "safest"');
  eq(safetyFact('safest travel rating', 'Level 1: exercise normal precautions — per US State Dept'), 'US State Dept Level 1');
  eq(safetyFact('safest travel rating', 'Level 1: normal security precautions — US State Dept publishes no advisory here; level per Canada'), null);
  eq(safetyFact('great weather in November', ''), 'great weather in November');
  eq(D.displayName('Turkey'), 'Turkey (Türkiye)'); eq(D.displayName('Japan'), 'Japan');
});

for (const [name, fn] of tests) {
  try { await fn(); pass++; console.log('ok   ', name); } catch (e) { fail++; console.log('FAIL ', name, '\n     ', e.message); }
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

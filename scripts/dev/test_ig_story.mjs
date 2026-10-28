// test_ig_story.mjs — ig_story.mjs's row picking and the frame's wording
// guards (no network, no browser):  cd scripts/dev && node test_ig_story.mjs
import { pickRows, safetyFact, siteUnsettled } from './ig_story.mjs';
import { wordingProblems, sidecarText } from './ig_frame.mjs';

let pass = 0, fail = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const eq = (a, b, what = '') => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };
const ok = (c, what) => { if (!c) throw new Error(what); };

test('only Level 1-2 rows (safety pill A or B), each with its own Top Picks rank', () => {
  const row = (rank, advLetter) => ({ rank, name: 'C' + rank, advLetter });
  const all = [row(1, 'A'), row(2, 'B'), row(3, 'D'), row(4, 'A'), row(5, 'F'), row(6, 'B'), row(7, 'A'), row(8, 'D')];
  const { picked, skipped } = pickRows(all);
  eq(picked.map((r) => r.rank), [1, 2, 4, 6, 7], 'Level 3 (#3) and Level 4 (#5) left off, the next rows taken');
  eq(skipped.map((r) => r.rank), [3, 5], 'only the skips above the last pick are reported');
  eq(pickRows([row(1, 'A'), row(2, 'B'), row(3, 'A'), row(4, 'B'), row(5, 'A'), row(6, 'D')]).skipped, [], 'nothing to report');
  eq(pickRows([row(1, '—'), row(2, 'A')]).picked.map((r) => r.rank), [2], 'unrated is out too');
  eq(pickRows([row(1, 'D'), row(2, 'F')]).picked, [], 'none left: the script refuses');
});

test('the old "safest travel rating" phrase becomes the State Dept level, or is dropped for a gap-fill', () => {
  eq(safetyFact('safest travel rating', 'Level 1: exercise normal precautions — per US State Dept'), 'US State Dept Level 1');
  eq(safetyFact('safest travel rating', 'Level 1: normal security precautions — US State Dept publishes no advisory here; level per Canada'), null);
  eq(safetyFact('great weather in November', ''), 'great weather in November');
});

test('wording: "safe"/"safest", Airbnb and deadline wording never pass, on a frame or in a sidecar', () => {
  ok(wordingProblems('the safest country').length && wordingProblems('Safe & cheap').length, 'safe/safest caught');
  ok(wordingProblems('book an Airbnb').length && wordingProblems('last chance to go').length, 'Airbnb and deadline caught');
  eq(wordingProblems('prices vs home, safety, weather and flights · Level 1: exercise normal precautions per US State Dept'), []);
  let threw = false; try { sidecarText({ series: 'x', posting: '2026-10-28', asOf: 'Oct 28, 2026', caption: 'The safest pick' }); } catch { threw = true; }
  ok(threw, 'sidecar refuses "safest"');
  const s = sidecarText({ series: 'Top Picks', posting: '2026-10-28', asOf: 'Oct 28, 2026', link: 'https://wandergrade.com/?vmn=11', caption: 'c', notes: ['#1 Thailand: A+ 93'] });
  ok(s.includes('Link sticker URL (exact):\n  https://wandergrade.com/?vmn=11') && s.includes('  - #1 Thailand: A+ 93'), 'sidecar layout');
});

test('refuses while the site is unsettled: no-store, a non-200 or a failed GET', async () => {
  const reply = (status, cc) => async () => ({ status, headers: new Headers({ 'cache-control': cc }) });
  eq(await siteUnsettled(11, reply(200, 'public, max-age=300')), null, 'cached page: settled');
  ok(/served uncached/.test(await siteUnsettled(11, reply(200, 'no-store'))), 'no-store: refuse');
  ok(/\/cheapest\/november returned 403/.test(await siteUnsettled(11, reply(403, ''))), 'blocked GET: refuse');
  ok(/failed/.test(await siteUnsettled(12, async () => { throw new Error('ECONNRESET'); })), 'network failure: refuse');
});

for (const [name, fn] of tests) {
  try { await fn(); pass++; console.log('ok   ', name); } catch (e) { fail++; console.log('FAIL ', name, '\n     ', e.message); }
}
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

"""The Trip tab's route (round 16): public/app.js tripLegMatrix /
tripBestOrder / tripTotals / tripFallbackFit / tripLegsURL, run under jsc
(scripts/appjs_harness.js) with public/world.geojson loaded.

    /usr/bin/python3 scripts/test_trip_order.py

What it holds the code to:
  * the leg model (home = index 0): a real leg between trip countries is
    /api/trip-legs' round-trip fare halved with its own flight time; a
    reverse row counts the same; a missing pair is estimated from the
    distance between countryCentroids() with the regional fit, halved, never
    under USD 50 a round trip, minutes = km / 800 * 60 + 120; home legs come
    from the reader's own fares (homeFares); a real fare with no flight time
    keeps the fare and estimates the minutes; no fit at all prices no
    estimated leg (fareOk false);
  * England and the UK (GUIDE_PARENT) on one trip are no flight (0, 0), a
    microstate (Monaco) gets finite legs, every stop once
    (parent_and_tiny_stops);
  * the order: Cheapest and Quickest are the brute-force optimum on 200
    random asymmetric matrices (2-7 stops); Best overall minimises
    fare/bestFare + minutes/bestMinutes; a matrix where Cheapest and Quickest
    disagree gives two orders; one stop is [0], none []; ties keep the input
    order; no fit orders Cheapest by time;
  * big trips (big_trip_fast): 12 stops (nearest neighbour + 2-opt) and 10
    (exact) each order in under 50 ms under jsc in every mode, 40 stops give
    a permutation, and the heuristic stays within 1% of the exact order on
    average on distance-like 12-stop trips;
  * tripTotals sums home -> stops -> home and says when any of it is
    estimated; tripFallbackFit is the reader's long-haul fit (8+ rows);
    tripLegsURL asks for at most 12 countries, the same 12 whatever the order;
  * the Trip UI's pure parts (Task 5): the order modes and where they are
    kept (a shared trip's on screen only), a move by hand, the leg and
    totals wording (≈ once, the home flag, no flight inside one country),
    the switch / handle / leg markup, no reorder under a drag or in Your
    order, and index.html's stand-in and the styles that keep it all from
    shifting the page.
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()

DRIVER = r"""
worldGeo = JSON.parse(read(WORLD_PATH));
const out = {};
const T = (name, f) => { try { out[name] = f(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; } };
let seed = 11;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const perms = (k) => { const res = []; const a = [...Array(k).keys()];
  const go = (i) => { if (i === k) { res.push(a.slice()); return; }
    for (let j = i; j < k; j++) { [a[i], a[j]] = [a[j], a[i]]; go(i + 1); [a[i], a[j]] = [a[j], a[i]]; } };
  go(0); return res; };
const tot = (M, ord) => { let s = M[0][ord[0] + 1]; for (let i = 1; i < ord.length; i++) s += M[ord[i - 1] + 1][ord[i] + 1]; return s + M[ord[ord.length - 1] + 1][0]; };
const isPerm = (o, k) => Array.isArray(o) && o.length === k && new Set(o).size === k && o.every((x) => Number.isInteger(x) && x >= 0 && x < k);
const randM = (k) => { const n = k + 1, F = [], Mi = [], R = [];
  for (let i = 0; i < n; i++) { F.push([]); Mi.push([]); R.push([]);
    for (let j = 0; j < n; j++) { F[i].push(i === j ? 0 : Math.round(20 + rnd() * 600)); Mi[i].push(i === j ? 0 : Math.round(60 + rnd() * 900)); R[i].push(true); } }
  return { n, fare: F, min: Mi, real: R, realMin: R, fareOk: true }; };

T("brute", () => {
  const bad = []; let cases = 0;
  for (let c = 0; c < 200; c++) {
    const k = 2 + (c % 6), m = randM(k), P = perms(k);
    for (const mode of ["cheap", "quick"]) {
      const M = mode === "cheap" ? m.fare : m.min, o = tripBestOrder(m, mode);
      const want = Math.min(...P.map((p) => tot(M, p)));
      cases++;
      if (!isPerm(o, k) || Math.abs(tot(M, o) - want) > 1e-6) bad.push({ k, mode, o, got: isPerm(o, k) ? tot(M, o) : null, want });
    }
    if (c % 4 === 0) {
      const bf = Math.min(...P.map((p) => tot(m.fare, p))), bm = Math.min(...P.map((p) => tot(m.min, p)));
      const sc = (p) => tot(m.fare, p) / bf + tot(m.min, p) / bm;
      const want = Math.min(...P.map(sc)), o = tripBestOrder(m, "best");
      cases++;
      if (!isPerm(o, k) || Math.abs(sc(o) - want) > 1e-9) bad.push({ k, mode: "best", o, got: isPerm(o, k) ? sc(o) : null, want });
    }
  }
  return { cases, bad: bad.slice(0, 3), nbad: bad.length };
});
T("three", () => {
  // home 0; stops 1,2,3. Cheap: 0->3->2->1->0 (a cheap but slow loop); quick: 0->1->2->3->0.
  const F = [[0, 300, 300, 100], [100, 0, 300, 300], [300, 100, 0, 300], [300, 300, 100, 0]];
  const Mi = [[0, 100, 900, 900], [900, 0, 100, 900], [900, 900, 0, 100], [100, 900, 900, 0]];
  const R = F.map((r) => r.map(() => true));
  const m = { n: 4, fare: F, min: Mi, real: R, realMin: R, fareOk: true };
  const P = perms(3);
  const bf = Math.min(...P.map((p) => tot(F, p))), bm = Math.min(...P.map((p) => tot(Mi, p)));
  const sc = (p) => tot(F, p) / bf + tot(Mi, p) / bm;
  const bestWant = P.filter((p) => Math.abs(sc(p) - Math.min(...P.map(sc))) < 1e-9);
  return { cheap: tripBestOrder(m, "cheap"), quick: tripBestOrder(m, "quick"), best: tripBestOrder(m, "best"),
           bestWant, cheapTot: tot(F, tripBestOrder(m, "cheap")), bf, quickTot: tot(Mi, tripBestOrder(m, "quick")), bm };
});
T("small", () => {
  const one = { n: 2, fare: [[0, 5], [5, 0]], min: [[0, 9], [9, 0]], real: [[true, true], [true, true]], realMin: [[true, true], [true, true]], fareOk: true };
  const none = { n: 1, fare: [[0]], min: [[0]], real: [[true]], realMin: [[true]], fareOk: true };
  return { one: ["best", "cheap", "quick"].map((md) => tripBestOrder(one, md)), none: tripBestOrder(none, "best") };
});
T("ties", () => {
  const k = 5, n = k + 1, eq = [...Array(n)].map((_, i) => [...Array(n)].map((_, j) => (i === j ? 0 : 100)));
  const R = eq.map((r) => r.map(() => true));
  const flat = { n, fare: eq, min: eq, real: R, realMin: R, fareOk: true };
  // symmetric: a route and its reverse cost the same; the input order (1,2,3 along a line) is optimal
  const pos = [0, 1, 2, 3];
  const S = pos.map((a) => pos.map((b) => Math.abs(a - b) * 70 + (a === b ? 0 : 10)));
  const R2 = S.map((r) => r.map(() => true));
  const line = { n: 4, fare: S, min: S, real: R2, realMin: R2, fareOk: true };
  // big symmetric (12 stops, heuristic path): a ring already in its best order stays as it is
  const kk = 12, ring = [...Array(kk + 1)].map((_, i) => [Math.cos(i / (kk + 1) * 2 * Math.PI), Math.sin(i / (kk + 1) * 2 * Math.PI)]);
  const D = ring.map((a) => ring.map((b) => Math.round(Math.hypot(a[0] - b[0], a[1] - b[1]) * 1000)));
  const R3 = D.map((r) => r.map(() => true));
  const big = { n: kk + 1, fare: D, min: D, real: R3, realMin: R3, fareOk: true };
  return { flat: ["best", "cheap", "quick"].map((md) => tripBestOrder(flat, md)), line: ["best", "cheap", "quick"].map((md) => tripBestOrder(line, md)),
           big: tripBestOrder(big, "cheap") };
});
const FIT = { a: -10.06, b: 0.1116, n: 40 };
T("matrix", () => {
  const C = countryCentroids();
  const legs = { legs: { TH: { VN: { fare: 120, basis: "month", dur: 95, stops: 0 } }, KH: { TH: { fare: 90, basis: "avg", dur: 70, stops: 0, rev: true } },
                         VN: { KH: { fare: 140, basis: "avg", dur: null, stops: 1 } } }, fit: FIT, pending: [] };
  const hf = { TH: { to: 300, back: 310, basis: "month", dur: 1100 }, VN: { to: 280, back: 280, basis: "avg", dur: null } };
  const m = tripLegMatrix(["TH", "VN", "KH"], "US", legs, hf);
  const km = (a, b) => distKm(C[a], C[b]);
  return { n: m.n, fare: m.fare, min: m.min, real: m.real, realMin: m.realMin, fareOk: m.fareOk,
           kmVNTH: km("VN", "TH"), kmUSKH: km("US", "KH"), kmKHVN: km("KH", "VN") };
});
T("floor", () => {
  const m = tripLegMatrix(["BE", "LU"], "US", { legs: {}, fit: FIT }, {});
  return { fare: m.fare[1][2], km: distKm(countryCentroids().BE, countryCentroids().LU), real: m.real[1][2] };
});
T("nofit", () => {
  const m = tripLegMatrix(["PT", "MA", "ES"], "US", { legs: {}, fit: { a: null, b: null, n: 3 } }, { PT: { to: 250, back: 250, basis: "avg", dur: 420 } });
  const finiteMin = m.min.every((r) => r.every((v) => Number.isFinite(v)));
  return { fareOk: m.fareOk, ptHome: [m.fare[0][1], m.fare[1][0]], est: m.fare[1][2], finiteMin,
           cheap: tripBestOrder(m, "cheap"), quick: tripBestOrder(m, "quick"), best: tripBestOrder(m, "best"),
           totals: tripTotals(m, [0, 1, 2]) };
});
T("badfit", () => {
  // a fit whose slope isn't positive is no fit
  const m = tripLegMatrix(["PT", "MA"], "US", { legs: {}, fit: { a: 300, b: -0.01, n: 50 } }, {});
  return m.fareOk;
});
T("parent_and_tiny_stops", () => {
  const isos = ["GB-ENG", "GB", "MC"];
  const m = tripLegMatrix(isos, "US", { legs: {}, fit: { a: 30, b: 0.09, n: 44 } }, {});
  const finite = [m.fare, m.min].every((M) => M.length === 4 && M.every((r) => r.length === 4 && r.every((v) => Number.isFinite(v))));
  const orders = ["best", "cheap", "quick"].map((md) => tripBestOrder(m, md));
  // the same with the UK as home (a UK reader with England on the trip)
  const m2 = tripLegMatrix(["GB-ENG", "FR"], "GB", { legs: {}, fit: { a: 30, b: 0.09, n: 44 } }, { FR: { to: 60, back: 60, basis: "avg", dur: 75 } });
  return { finite, engGb: [m.fare[1][2], m.min[1][2], m.fare[2][1], m.min[2][1]], mc: [m.fare[0][3], m.min[0][3], m.fare[3][1]],
           orders, perm: orders.every((o) => isPerm(o, 3)), home: [m2.fare[0][1], m2.min[0][1], m2.fare[1][0]],
           totals: tripTotals(m, orders[0]) };
});
T("unknown_place", () => {
  // a code with no shape on the map at all: finite legs all the same, every stop once
  const m = tripLegMatrix(["ZZ", "FR", "IT"], "US", { legs: {}, fit: FIT }, {});
  return { finite: [m.fare, m.min].every((M) => M.every((r) => r.every((v) => Number.isFinite(v)))), order: tripBestOrder(m, "best") };
});
T("big_trip_fast", () => {
  const res = {};
  for (const k of [10, 12]) {
    const m = randM(k), r = {};
    for (const mode of ["best", "cheap", "quick"]) {
      let worst = 0, o = null;
      for (let rep = 0; rep < 3; rep++) { const t0 = Date.now(); o = tripBestOrder(m, mode); worst = Math.max(worst, Date.now() - t0); }
      r[mode] = { ms: worst, perm: isPerm(o, k) };
    }
    res[k] = r;
  }
  const m40 = randM(40), t0 = Date.now(), o40 = tripBestOrder(m40, "best");
  res[40] = { ms: Date.now() - t0, perm: isPerm(o40, 40) };
  // the heuristic is no worse than nearest neighbour alone on the 12-stop trip
  const m12 = randM(12), nn = [];
  { const left = new Set([...Array(12).keys()]); let cur = 0;
    while (left.size) { let bj = -1; for (const j of left) if (bj < 0 || m12.fare[cur][j + 1] < m12.fare[cur][bj + 1]) bj = j; nn.push(bj); left.delete(bj); cur = bj + 1; } }
  res.vsNN = [tot(m12.fare, tripBestOrder(m12, "cheap")), tot(m12.fare, nn)];
  // against the exact optimum (the test's own DP) on 20 distance-like 12-stop trips
  const exact = (M, k) => { const full = (1 << k) - 1, g = new Float64Array((full + 1) * k);
    for (let j = 0; j < k; j++) g[j] = M[j + 1][0];
    for (let mask = 1; mask <= full; mask++) for (let j = 0; j < k; j++) { if (mask & (1 << j)) continue; let v = Infinity;
      for (let i = 0; i < k; i++) if (mask & (1 << i)) v = Math.min(v, M[j + 1][i + 1] + g[(mask ^ (1 << i)) * k + i]); g[mask * k + j] = v; }
    let b = Infinity; for (let j = 0; j < k; j++) b = Math.min(b, M[0][j + 1] + g[(full ^ (1 << j)) * k + j]); return b; };
  let gap = 0, worst = 0;
  for (let c = 0; c < 20; c++) {
    const pts = [...Array(13)].map(() => [rnd() * 3000, rnd() * 3000]);
    const M = pts.map((a, i) => pts.map((b, j) => (i === j ? 0 : Math.hypot(a[0] - b[0], a[1] - b[1]) * 0.06 + 40 + rnd() * 60)));
    const R = M.map((r) => r.map(() => true));
    const g = tot(M, tripBestOrder({ n: 13, fare: M, min: M, real: R, realMin: R, fareOk: true }, "cheap")) / exact(M, 12) - 1;
    gap += g / 20; worst = Math.max(worst, g);
  }
  res.gap = { avg: gap, worst };
  return res;
});
T("totals", () => {
  const F = [[0, 100, 100], [50, 0, 30], [70, 20, 0]], Mi = [[0, 600, 600], [600, 0, 60], [600, 50, 0]];
  const R = [[true, true, true], [true, true, false], [true, true, true]], RM = [[true, true, true], [true, true, true], [true, true, true]];
  const m = { n: 3, fare: F, min: Mi, real: R, realMin: RM, fareOk: true };
  return { a: tripTotals(m, [0, 1]), b: tripTotals(m, [1, 0]) };
});
T("fallback", () => {
  const C = countryCentroids();
  const rows = ["GB", "FR", "DE", "ES", "IT", "JP", "TH", "BR", "MX", "ZA", "AU"].map((iso, i) => ({ iso, avg: Math.round(200 + 0.06 * distKm(C.US, C[iso]) + (i % 3) * 20) }));
  flightsData = { configured: true, origin: "US", countries: rows, by_country: {} };
  const f = tripFallbackFit();
  flightsData = { configured: true, origin: "US", countries: rows.slice(0, 5), by_country: {} };
  const few = tripFallbackFit();
  flightsData = null;
  return { f, few, none: tripFallbackFit() };
});
T("url", () => {
  const twelve = ["TH", "VN", "KH", "LA", "MY", "SG", "ID", "PH", "JP", "KR", "TW", "HK", "CN", "MN"];
  const u1 = tripLegsURL("US", twelve, "2026-12"), u2 = tripLegsURL("US", twelve.slice().reverse(), "2026-12");
  const q = (u) => { const i = u.indexOf("?"); const o = {}; u.slice(i + 1).split("&").forEach((kv) => { const p = kv.split("="); o[p[0]] = decodeURIComponent(p[1]); }); return o; };
  return { u1, same: u1 === u2, isos: q(u1).isos.split(","), month: q(u1).month, path: u1.slice(0, u1.indexOf("?")),
           flex: tripLegsURL("GB", ["GB-ENG", "FR"], null) };
});
// ---- Task 5: the UI's pure parts ----
T("modes", () => {
  localStorage.clear(); _tripSharedSort = null;
  const r = { def: tripSortMode(), last: tripSortLast() };
  setTripSort("cheap"); r.cheap = [tripSortMode(), localStorage.getItem("fx_tripsort"), tripSortLast()];
  setTripSort("mine"); r.mine = [tripSortMode(), tripSortLast()];
  localStorage.setItem("fx_tripsort", "bogus"); r.bogus = tripSortMode();
  // a shared trip: its mode on screen only, until saved
  localStorage.setItem("fx_tripsort", "quick"); localStorage.setItem("fx_trip", '["FR","IT"]'); _trip = new Set(["KH", "TH", "VN"]);
  _tripSharedSort = "mine";
  r.shared = tripSortMode();
  setTripSort("cheap"); r.sharedPick = [tripSortMode(), localStorage.getItem("fx_tripsort"), localStorage.getItem("fx_trip")];
  saveTrip(); r.saved = [_tripSharedSort, tripSortMode(), localStorage.getItem("fx_tripsort"), localStorage.getItem("fx_trip")];
  // a drag makes it the reader's own order, saved
  _tripSharedSort = "mine"; renderTripBook = () => {}; refreshTripPrompt = () => {};
  tripMoveTo("VN", 0);
  r.moved = [[..._trip], localStorage.getItem("fx_trip"), localStorage.getItem("fx_tripsort"), _tripSharedSort, localStorage.getItem("fx_tripsortlast")];
  return r;
});
T("words", () => {
  const F = [[0, 300, 150], [310, 0, 0], [140, 0, 0]], Mi = [[0, 1100, 600], [1100, 0, 0], [600, 0, 0]];
  const R = [[true, true, false], [true, true, true], [false, true, true]], RM = [[true, true, false], [true, true, true], [true, true, true]];
  const m = { n: 3, fare: F, min: Mi, real: R, realMin: RM, fareOk: true };
  const names = [{ iso: "US", name: "the US" }, { iso: "GB-ENG", name: "England" }, { iso: "GB", name: "United Kingdom" }];
  const usd = { cur: "USD", conv: 1 }, eur = { cur: "EUR", conv: 0.9 };
  const m2 = { n: 2, fare: [[0, null], [null, 0]], min: [[0, 95], [95, 0]], real: [[true, false], [false, true]], realMin: [[true, false], [false, true]], fareOk: false };
  return { first: tripLegWords(m, 0, 1, usd, names), last: tripLegWords(m, 1, 0, usd, names), same: tripLegWords(m, 1, 2, usd, names),
           est: tripLegWords(m, 0, 2, usd, names), estEur: tripLegWords(m, 0, 2, eur, names), realEur: tripLegWords(m, 0, 1, eur, names),
           nofare: tripLegWords(m2, 0, 1, usd, [{ iso: "US", name: "the US" }, { iso: "TH", name: "Thailand" }]),
           tot: [tripTotalWords({ fare: 1240.4, minutes: 1265, estimated: true }, usd), tripTotalWords({ fare: 1240, minutes: 60, estimated: false }, usd),
                 tripTotalWords({ fare: 1000, minutes: 125, estimated: true }, eur), tripTotalWords({ fare: null, minutes: 45, estimated: true }, usd)] };
});
T("parts", () => {
  localStorage.clear(); _tripSharedSort = null;
  const host = document.getElementById("tripBook");
  const p3 = tripRouteParts(["TH", "VN", "KH"], host), p1 = tripRouteParts(["TH"], host), p0 = tripRouteParts([], host);
  setTripSort("mine");
  const pm = tripRouteParts(["TH", "VN"], host);
  return { sort3: p3.sort, handle: p3.handle("VN", "Vietnam", 1), leg: p3.leg("", "TH"), total: p3.total,
           sort1: p1.sort, handle1: p1.handle("TH", "Thailand", 0), leg1: p1.leg("TH", ""), leg0: p0.leg("", ""), total0: p0.total, sortMine: pm.sort };
});
T("guards", () => {
  // never reorder under a finger, nor a dragged ("Your order") trip
  localStorage.clear(); _tripSharedSort = null;
  document.documentElement.setAttribute("data-tab", "trip");
  _trip = new Set(["KH", "TH", "VN"]);
  _tripDragging = true;
  const dragging = tripRouteUpdate(true);
  _tripDragging = false;
  setTripSort("mine");
  flightsData = null; valueFlightsSettled = true;
  const url = tripLegsURL(originIso(), ["KH", "TH", "VN"], null);
  _tripLegsReq[url] = { at: Date.now(), state: "done", json: { legs: { TH: { VN: { fare: 20, dur: 600 } }, VN: { KH: { fare: 20, dur: 600 } } }, fit: { a: 40, b: 0.06, n: 35 }, pending: [] } };
  localStorage.setItem("fx_tripmonth", "0");
  const mine = tripRouteUpdate(true);
  return { dragging, mine, order: [..._trip], built: !!(_tripM && _tripM.m && _tripM.m.n === 4), sig: _tripM && _tripM.sig };
});
print(JSON.stringify(out));
"""

with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "run.js")
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("WORLD_PATH", json.dumps(P("public", "world.geojson"))))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-800:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
    sys.exit(1)
errs = {k: v["error"] for k, v in js.items() if isinstance(v, dict) and "error" in v}
results.append(ok(not errs, "every case ran %s" % (json.dumps(errs)[:1200] if errs else "")))
G = lambda k: js.get(k) if not (isinstance(js.get(k), dict) and "error" in js.get(k)) else None
near = lambda a, b, e=1e-6: a is not None and b is not None and abs(a - b) <= e

b = G("brute") or {}
results.append(ok(b.get("cases", 0) >= 450 and b.get("nbad") == 0,
                  "Cheapest, Quickest and Best overall match brute force on 200 random asymmetric trips of 2-7 stops (%s)" % b))
t = G("three") or {}
results.append(ok(t.get("cheap") == [2, 1, 0] and t.get("quick") == [0, 1, 2] and near(t.get("cheapTot"), t.get("bf"))
                  and near(t.get("quickTot"), t.get("bm")),
                  "a trip where they disagree: Cheapest 3-2-1 (%s), Quickest 1-2-3 (%s)" % (t.get("cheap"), t.get("quick"))))
results.append(ok(t.get("best") in (t.get("bestWant") or []),
                  "Best overall is the minimiser of fare/bestFare + minutes/bestMinutes (%s in %s)" % (t.get("best"), t.get("bestWant"))))
s = G("small") or {}
results.append(ok(s.get("one") == [[0], [0], [0]] and s.get("none") == [], "one stop is [0] in every mode, none is [] (%s)" % s))
ti = G("ties") or {}
results.append(ok(ti.get("flat") == [[0, 1, 2, 3, 4]] * 3, "an all-equal trip keeps the input order in every mode (%s)" % ti.get("flat")))
results.append(ok(ti.get("line") == [[0, 1, 2]] * 3, "a route tied with its reverse keeps the input order (%s)" % ti.get("line")))
results.append(ok(ti.get("big") == list(range(12)), "12 stops (heuristic) already in their best order stay in it (%s)" % ti.get("big")))

m = G("matrix") or {}
F, Mi, R, RM = m.get("fare") or [], m.get("min") or [], m.get("real") or [], m.get("realMin") or []
# nodes: 0 US, 1 TH, 2 VN, 3 KH
gx = lambda M, i, j: M[i][j] if len(M) > max(i, j) and len(M[i]) > j else None
results.append(ok(m.get("n") == 4 and gx(F, 1, 2) == 60 and gx(Mi, 1, 2) == 95 and gx(R, 1, 2) is True and gx(RM, 1, 2) is True,
                  "a real leg: TH->VN is half the cached round trip (60) at its own flight time (95 min) (%s, %s)" % (gx(F, 1, 2), gx(Mi, 1, 2))))
results.append(ok(gx(F, 3, 1) == 45 and gx(Mi, 3, 1) == 70 and gx(R, 3, 1) is True, "a reverse row counts the same: KH->TH 45, 70 min (%s)" % gx(F, 3, 1)))
km = m.get("kmVNTH") or 0
want_f, want_m = max(50, -10.06 + 0.1116 * km) / 2, km / 800 * 60 + 120
results.append(ok(near(gx(F, 2, 1), want_f) and near(gx(Mi, 2, 1), want_m) and gx(R, 2, 1) is False and gx(RM, 2, 1) is False,
                  "a missing pair is estimated: VN->TH max(50, a + b*km)/2 = %.2f, km/800*60+120 = %.1f min, marked (%s, %s)"
                  % (want_f, want_m, gx(F, 2, 1), gx(Mi, 2, 1))))
kk = m.get("kmKHVN") or 0
results.append(ok(gx(F, 2, 3) == 70 and gx(R, 2, 3) is True and gx(RM, 2, 3) is False and near(gx(Mi, 2, 3), kk / 800 * 60 + 120),
                  "a real fare with no flight time: the fare stays (70), the minutes are estimated (%s, %s)" % (gx(F, 2, 3), gx(Mi, 2, 3))))
results.append(ok(gx(F, 0, 1) == 300 and gx(F, 1, 0) == 310 and gx(Mi, 0, 1) == 1100 and gx(Mi, 1, 0) == 1100 and gx(R, 0, 1) is True,
                  "home legs from the reader's own fares: US->TH 300, TH->US 310, 1100 min each way (%s)" % [gx(F, 0, 1), gx(F, 1, 0), gx(Mi, 0, 1)]))
results.append(ok(gx(F, 0, 2) == 280 and gx(R, 0, 2) is True and gx(RM, 0, 2) is False,
                  "a home fare with no flight time keeps the fare, estimates the time (%s)" % gx(F, 0, 2)))
ku = m.get("kmUSKH") or 0
results.append(ok(near(gx(F, 0, 3), max(50, -10.06 + 0.1116 * ku) / 2) and gx(R, 0, 3) is False and m.get("fareOk") is True,
                  "a home leg with no fare of its own is estimated like the rest (%s)" % gx(F, 0, 3)))
fl = G("floor") or {}
results.append(ok(fl.get("fare") == 25 and fl.get("real") is False and fl.get("km", 999) < 450,
                  "a short estimated leg never prices under USD 50 a round trip: Belgium->Luxembourg %s one way (%.0f km)" % (fl.get("fare"), fl.get("km") or 0)))
nf = G("nofit") or {}
results.append(ok(nf.get("fareOk") is False and nf.get("ptHome") == [250, 250] and nf.get("est") is None and nf.get("finiteMin") is True,
                  "no fit: estimated legs have no fare (null), real ones keep theirs, every time is finite (%s)" % {k: nf.get(k) for k in ("fareOk", "ptHome", "est")}))
results.append(ok(nf.get("cheap") == nf.get("quick") and nf.get("best") == nf.get("quick"),
                  "no fit: Cheapest and Best overall order by time (%s %s %s)" % (nf.get("cheap"), nf.get("best"), nf.get("quick"))))
nt = nf.get("totals") or {}
results.append(ok(nt.get("fare") is None and (nt.get("minutes") or 0) > 0 and nt.get("estimated") is True,
                  "no fit: the totals have no fare, still a time (%s)" % nt))
results.append(ok(G("badfit") is False, "a fit with a slope that isn't positive counts as none"))
pt = G("parent_and_tiny_stops") or {}
results.append(ok(pt.get("finite") is True and pt.get("perm") is True,
                  "parent_and_tiny_stops: England + the UK + Monaco: every leg finite, each stop once in every mode (%s)" % pt.get("orders")))
results.append(ok(pt.get("engGb") == [0, 0, 0, 0], "England <-> the UK is no flight: 0, 0 both ways (%s)" % pt.get("engGb")))
mc = pt.get("mc") or [0, 0, 0]
results.append(ok(mc[0] > 0 and mc[1] > 0 and mc[2] > 0, "Monaco (a microstate) gets real-looking estimates (%s)" % mc))
results.append(ok(pt.get("home") == [0, 0, 0], "a UK reader with England on the trip: home <-> England is no flight (%s)" % pt.get("home")))
up = G("unknown_place") or {}
results.append(ok(up.get("finite") is True and sorted(up.get("order") or []) == [0, 1, 2],
                  "a place with no shape on the map still gets finite legs and one stop (%s)" % up))
bt = G("big_trip_fast") or {}
fast = all((bt.get(str(k)) or {}).get(md, {}).get("ms", 999) < 50 and (bt.get(str(k)) or {}).get(md, {}).get("perm")
           for k in (10, 12) for md in ("best", "cheap", "quick"))
results.append(ok(fast, "big_trip_fast: 10 stops (exact) and 12 (heuristic) order in under 50 ms in every mode (%s)"
                  % {k: {md: (bt.get(str(k)) or {}).get(md, {}).get("ms") for md in ("best", "cheap", "quick")} for k in (10, 12)}))
b40 = bt.get("40") or {}
results.append(ok(b40.get("perm") is True and b40.get("ms", 9999) < 500, "40 stops: still a permutation, in %s ms" % b40.get("ms")))
vs = bt.get("vsNN") or [1, 0]
results.append(ok(vs[0] <= vs[1] + 1e-9, "the 12-stop heuristic is no worse than nearest neighbour alone (%s)" % vs))
gp = bt.get("gap") or {}
results.append(ok(gp.get("avg", 1) < 0.01 and gp.get("worst", 1) < 0.05,
                  "the 12-stop heuristic on 20 distance-like trips: %.2f%% above the exact order on average, %.2f%% at worst"
                  % (100 * gp.get("avg", 1), 100 * gp.get("worst", 1))))
to = G("totals") or {}
a_, b_ = to.get("a") or {}, to.get("b") or {}
results.append(ok(a_.get("fare") == 100 + 30 + 70 and a_.get("minutes") == 600 + 60 + 600 and a_.get("estimated") is True,
                  "tripTotals: home -> 1 -> 2 -> home = 200, 1260 min, estimated (the 1->2 fare is) (%s)" % a_))
results.append(ok(b_.get("fare") == 100 + 20 + 50 and b_.get("minutes") == 600 + 50 + 600 and b_.get("estimated") is False,
                  "the other way round: 170, 1250 min, all real (%s)" % b_))
fb = G("fallback") or {}
f = fb.get("f") or {}
results.append(ok(isinstance(f.get("a"), (int, float)) and 0.03 < (f.get("b") or 0) < 0.09 and fb.get("few") is None and fb.get("none") is None,
                  "tripFallbackFit: the reader's own fare-by-distance fit from 8+ rows, none from 5 or without fares (%s)" % fb))
u = G("url") or {}
results.append(ok(u.get("path") == "/api/trip-legs" and len(u.get("isos") or []) == 12 and u.get("same") is True and u.get("month") == "2026-12",
                  "tripLegsURL: at most 12 countries, the same 12 whatever the order, with the month (%s)" % u.get("u1")))
results.append(ok(u.get("flex") == "/api/trip-legs?origin=GB&isos=FR,GB-ENG", "no month when flexible (%s)" % u.get("flex")))

# ---- Task 5: the UI's pure parts ----
md = G("modes") or {}
results.append(ok(md.get("def") == "best" and md.get("last") == "best" and md.get("cheap") == ["cheap", "cheap", "cheap"]
                  and md.get("mine") == ["mine", "cheap"] and md.get("bogus") == "best",
                  "modes: Best overall by default; a pick is saved (fx_tripsort) and remembered for ↺ (fx_tripsortlast) (%s)"
                  % {k: md.get(k) for k in ("def", "cheap", "mine", "bogus")}))
results.append(ok(md.get("shared") == "mine" and md.get("sharedPick") == ["cheap", "quick", '["FR","IT"]'],
                  "a shared trip opens as Your order; a mode picked on it touches neither the saved mode nor the saved trip (%s)" % md.get("sharedPick")))
results.append(ok(md.get("saved") == [None, "cheap", "cheap", '["KH","TH","VN"]'],
                  "saving a shared trip makes it the reader's own, with the mode on screen (%s)" % md.get("saved")))
results.append(ok(md.get("moved") == [["VN", "KH", "TH"], '["VN","KH","TH"]', "mine", None, "cheap"],
                  "a move by hand: the row goes there, saved as Your order, ↺ still remembers Cheapest (%s)" % md.get("moved")))
w = G("words") or {}
v = lambda k: (w.get(k) or {}).get("vis")
results.append(ok(v("first") == "🇺🇸 ✈️ USD 300 · 18h 20m" and v("last") == "✈️ USD 310 · 18h 20m 🇺🇸",
                  "home legs carry the home flag, leaving and coming back (%s | %s)" % (v("first"), v("last"))))
results.append(ok(v("same") == "✈️ —" and "same country" in ((w.get("same") or {}).get("sr") or ""),
                  "England -> the UK: no flight (%s)" % w.get("same")))
results.append(ok(v("est") == "🇺🇸 ✈️ ≈USD 150 · ≈10h" and v("estEur") == "🇺🇸 ✈️ ≈EUR 135 · ≈10h" and v("realEur") == "🇺🇸 ✈️ ≈EUR 270 · 18h 20m",
                  "estimates say ≈, once (a converted fare's own ≈ is enough) (%s | %s | %s)" % (v("est"), v("estEur"), v("realEur"))))
results.append(ok(v("nofare") == "🇺🇸 ✈️ ≈1h 35m", "no fare known: the time alone (%s)" % v("nofare")))
sr = (w.get("est") or {}).get("sr") or ""
results.append(ok(sr == "Flight from the US to United Kingdom: about USD 150, 10h (estimated)", "screen readers get the leg in words (%s)" % sr))
results.append(ok(w.get("tot") == ["≈ USD 1,240 · 21h 5m flying", "USD 1,240 · 1h flying", "≈EUR 900 · 2h 5m flying", "≈ 45m flying"],
                  "the totals line (%s)" % w.get("tot")))
pa = G("parts") or {}
s3 = pa.get("sort3") or ""
results.append(ok('data-ts="best" class="active" aria-pressed="true">Best overall' in s3 and 'data-ts="cheap" aria-pressed="false">Cheapest' in s3
                  and 'data-ts="quick" aria-pressed="false">Quickest' in s3 and "tsmine" not in s3 and 'data-tip="' in s3
                  and "≈" in s3 and "visas" in s3, "the switch: Best overall pressed, Cheapest, Quickest, one ⓘ (%s)" % s3[:160]))
sm = pa.get("sortMine") or ""
results.append(ok('class="tsmine">Your order' in sm and 'data-ts="rec">↺ Recommended' in sm and 'aria-pressed="true"' not in sm,
                  "after a drag: Your order and ↺ Recommended, no mode pressed"))
results.append(ok('class="tbdrag" data-iso="VN"' in (pa.get("handle") or "") and "stop 2 of 3" in (pa.get("handle") or "")
                  and "arrow keys" in (pa.get("handle") or ""), "a handle per row names its place and the keys (%s)" % pa.get("handle")))
results.append(ok(pa.get("leg") == '<div class="tbleg" data-from="" data-to="TH"><span aria-hidden="true">✈️ …</span></div>'
                  and pa.get("total") == '<div class="tbtotal"><span aria-hidden="true">…</span></div>',
                  "a leg line and the totals hold their line until the route is in (%s)" % pa.get("leg")))
results.append(ok(pa.get("sort1") == "" and pa.get("handle1") == "" and pa.get("leg1", "").startswith('<div class="tbleg" data-from="TH" data-to=""')
                  and pa.get("leg0") == "" and pa.get("total0") == "", "one country: no switch, no handle, still its legs; none: nothing"))
gd = G("guards") or {}
results.append(ok(gd.get("dragging") is False and gd.get("mine") is False and gd.get("order") == ["KH", "TH", "VN"] and gd.get("built") is True,
                  "never reorders under a drag or in Your order (the legs still build) (%s)" % gd))

# The first-paint stand-in and the styles
HTML = open(P("public", "index.html"), encoding="utf-8").read()
CSS = open(P("public", "styles.css"), encoding="utf-8").read()
i = HTML.find('<div id="tripBar"')
stand = HTML[i:HTML.find("</script>", i)]
results.append(ok(all(x in stand for x in ('class="tripsort"', '<div class="windowtoggle">', ">Best overall<", ">Cheapest<", ">Quickest<",
                                            'class="tsmine">Your order', 'class="tsrec">↺ Recommended', 'class="tbdrag"',
                                            '<div class="tbleg"><span>✈️ …</span></div>', '<div class="tbtotal"><span>…</span></div>',
                                            'localStorage.getItem("fx_tripsort")==="mine"', 'get("tp")', "rows=leg", "rows+=row+leg")),
                  "index.html's Trip stand-in draws the switch (Your order when saved or shared), handles, n+1 legs and the totals"))
import re as _re
rule = lambda sel: (_re.search(r"(?m)^" + _re.escape(sel) + r" \{([^}]*)\}", CSS) or [None, ""])[1]
results.append(ok("height: 24px" in rule(".tbleg") and "height: 31px" in rule(".tbtotal")
                  and "contain: inline-size" in rule(".tbleg, .tbtotal") and "white-space: nowrap" in rule(".tbleg, .tbtotal"),
                  "leg lines and totals are fixed-height single lines that can't widen the grid"))
results.append(ok("touch-action: none" in rule(".tbdrag") and "transform" not in rule(".tbrow.tbdragging"),
                  "only the handle captures a touch drag (the page still scrolls elsewhere)"))
new_classes = set(_re.findall(r"\.(trip[a-z]+|tb[a-z]+|ts[a-z]+)", CSS))
results.append(ok(not [c for c in new_classes if _re.match(r"(ad|adv|sponsor|banner|promo)", c)], "no class name an ad blocker hides"))

print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
sys.exit(0 if all(results) else 1)

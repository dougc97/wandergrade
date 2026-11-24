"""Every guide's served grades line and fares-by-month strip
(fxtracker/guide_lines.py) against what public/app.js renderGuideGrades and
renderGuideFares draw for a first visit (from the US, Any time), with app.js
itself run under jsc (scripts/appjs_harness.js) on one fixture: production's
own /api answers in scripts/parity/fixture_*.json, the country curves taken
from fixture_flight_value.json, public/ppp.json, climate.json and
activities.json.

    /usr/bin/python3 scripts/test_guide_lines.py

What it holds the code to:
  * for all 190 guides: the served grades line is the client's markup with
    the tooltips taken out (title, data-tip, aria-label) — the Overall pill
    and number, the four grades, the 🧳 days, "—" and the reason for an
    ungraded country — and the served strip is the client's, tooltips
    aside but its ⓘ's, which names the search link's commission (or both
    are none: fewer than three months), so the browser's copy replaces them
    without anything moving;
  * redraws: drawn again unchanged (each /api/flight-value poll's answer),
    neither writes anything nor hides the strip; a line waiting for the
    month curves draws its grey boxes after 2.5 s however the guide opened;
  * the page: a guide serves both when the caches hold their inputs and
    neither when they don't; the homepage serves neither; the pre-paint
    script empties them for a reader they aren't for and keeps them for a
    first visit; app.js holds them until its fares are in.
"""
import datetime, json, os, re, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_lines as G, render_guide  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "flights": load("scripts", "parity", "fixture_flights.json"),
       "fv": load("scripts", "parity", "fixture_flight_value.json"),
       "ppp": load("public", "ppp.json"), "climate": load("public", "climate.json"),
       "activities": load("public", "activities.json"), "world": load("public", "world.geojson"),
       "slugs": load("public", "slugs.json")}
GUIDES = [iso for _s, iso in render_guide.all_slugs()]
# The country's one curve (/api/flight-months), as the flight-value build holds it,
# with the origin's hub the search link starts from.
CURVES = {iso: {"origin": "US", "hub": FIX["flights"]["hub"],
                "months": {k: {"price": v[0], "dest": v[1]} for k, v in c["curve"].items()}}
          for iso, c in FIX["fv"]["countries"].items() if isinstance(c, dict) and c.get("curve")}
TODAY = datetime.date.today()

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp;
for (const iso of FIX.guides) _fareMonthsCache["US:" + iso] = Promise.resolve(FIX.curves[iso] || null);
const out = {};
(async () => {
  for (const iso of FIX.guides) {
    ccGuideIso = iso;
    $("guideGrades").innerHTML = ""; $("guideFares").innerHTML = ""; $("guideFares").hidden = true;
    await renderGuideGrades(iso);
    await renderGuideFares(iso);
    out[iso] = { grades: $("guideGrades").innerHTML, fares: $("guideFares").hidden ? "" : $("guideFares").innerHTML };
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""


def bare(h):
    return re.sub(r' (?:title|data-tip|aria-label)="[^"]*"', "", h or "")


with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, guides=GUIDES, curves=CURVES), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=300)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-500:]}
results.append(ok("error" not in js and len(js) == len(GUIDES),
                  "app.js drew the grades and fares of all %d guides under jsc %s" % (len(GUIDES), js.get("error", ""))))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)

inputs = {k: FIX[k] for k in ("rates", "advisories", "flights", "fv", "ppp", "climate", "activities")}
bad_g, bad_f = [], []
tip_bad, ftip_bad = [], []
TIP = re.compile(r'<span class="muted ggmon" data-tip="([^"]*)" title="">(\w+) ⓘ</span>')
FTIP = re.compile(r'<span class="legendinfo" data-tip="([^"]*)" title="">ⓘ</span>')
for iso in GUIDES:
    g = G.grades(iso, inputs, TODAY)
    if bare(g) != bare(js[iso]["grades"]):
        bad_g.append((iso, bare(g), bare(js[iso]["grades"])))
    # The one tooltip the served line keeps: the ⓘ's, after the month.
    if TIP.findall(g) != TIP.findall(js[iso]["grades"]):
        tip_bad.append((iso, TIP.findall(g), TIP.findall(js[iso]["grades"])))
    # The search link where app.js guideNoBookings is false: with this
    # fixture (no do-not-travel marks, every list in) anywhere but Level 4.
    f = G.fares(iso, CURVES.get(iso), FIX["fv"], TODAY, render_guide.name_for_iso,
                G.adv_level(iso, FIX["advisories"]) != 4)
    if bare(f) != bare(js[iso]["fares"]):
        bad_f.append((iso, bare(f), bare(js[iso]["fares"])))
    # The strip's one tooltip kept: its ⓘ's, which names the search link's commission.
    if FTIP.findall(f) != FTIP.findall(js[iso]["fares"]) or (f and len(FTIP.findall(f)) != 1):
        ftip_bad.append((iso, FTIP.findall(f), FTIP.findall(js[iso]["fares"])))
for iso, a, b in (bad_g + bad_f)[:2]:
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    print("        %s first difference at %d:\n        served %r\n        client %r" % (iso, i, a[i - 60:i + 100], b[i - 60:i + 100]))
graded = sum(1 for iso in GUIDES if 'data-gg="ov"' in js[iso]["grades"])
ungraded = [iso for iso in GUIDES if 'data-gg="ov"' not in js[iso]["grades"]]
strips = sum(1 for iso in GUIDES if js[iso]["fares"])
results.append(ok(not bad_g and graded > 120,
                  "every guide's grades line is the client's, tooltips aside (%d graded, %d with a reason: %s) %s"
                  % (graded, len(ungraded), " ".join(ungraded[:8]) + (" …" if len(ungraded) > 8 else ""),
                     [x[0] for x in bad_g][:10] or "")))
gm0 = G.guide_month(TODAY)
th_tip = TIP.findall(G.grades("TH", inputs, TODAY))
results.append(ok(not tip_bad and th_tip == [("Graded for %s from the US, weighted by your Top Picks priorities — the grades "
                                              "the Top Picks table and this page&#39;s 📸 share card show."
                                              % G.MON_FULL[gm0 - 1], G.MON_ABBR[gm0 - 1])],
                  "every graded line ends in the month it is for (\"%s ⓘ\"), and the served one keeps that ⓘ's tip, "
                  "word for word the client's %s" % (G.MON_ABBR[gm0 - 1], tip_bad[:2] or "")))
results.append(ok(not bad_f and strips >= 50,
                  "every guide's fares strip is the client's, tooltips aside, or none in both (%d strips) %s"
                  % (strips, [x[0] for x in bad_f][:10] or "")))
th_ftip = FTIP.findall(js["TH"]["fares"])
results.append(ok(not ftip_bad and len(th_ftip) == 1 and "we may earn a commission" in th_ftip[0]
                  and "the Flights tab&#39;s range" in th_ftip[0],
                  "every served strip keeps its ⓘ's tip, word for word the client's, commission and all %s"
                  % (ftip_bad[:2] or "")))
kinds = set()
for iso in GUIDES:
    h = js[iso]["grades"]
    kinds |= {k for k, pat in (("estimated fare", ">~"), ("no fare", 'data-gg="fly" class="gr grx" data-tip="No fare'),
                               ("days", "ggdays"), ("Level 4", "Level 4, do not travel"),
                               ("unrated", "No advisory from")) if pat in h}
    f = js[iso]["fares"]
    kinds |= {k for k, pat in (("low month", "background:rgb(") , ("no-fare month", "fill na"),
                               ("typical month", "fill typ")) if pat in f}
results.append(ok({"no fare", "days", "Level 4", "low month", "no-fare month", "typical month"} <= kinds,
                  "the guides between them show: %s" % ", ".join(sorted(kinds))))
# The places scoring leaves out on purpose are graded on their guide: the
# parent's advisory (and price level and currency where they have none), their
# own weather, no fare. Scoring itself (picks._score, so Top Picks and the
# newsletter) still never sees them.
BORROW = ["GB-ENG", "GB-SCT", "GB-WLS", "FO", "IM", "GG"]
gm = G.guide_month(TODAY)
gb, sct, fo = G.score("GB", inputs, gm), G.score("GB-SCT", inputs, gm), G.score("FO", inputs, gm)
sct_wx = FIX["climate"]["GB-SCT"]["scores"][gm - 1]
import fxtracker.picks as _P  # noqa: E402
rp = {r["code"]: r["rate_now"] for r in FIX["rates"]["rows"] if "code" in r and "rate_now" in r}
results.append(ok(all('data-gg="ov"' in js[i]["grades"] for i in BORROW)
                  and gb and sct and sct["afford"] == gb["afford"] and sct["safe"] == gb["safe"] and sct["wx"] == sct_wx
                  and sct["fare"] is None and "Flights" in js["GB-SCT"]["grades"] and fo and fo["pl"] != gb["pl"]
                  and all(_P._score(i, gm, FIX["ppp"], FIX["climate"], rp, {}, {"GB": 2, "DK": 1}) is None for i in BORROW),
                  "England, Scotland, Wales, the Faroes, Man and Guernsey graded on their guide (Scotland: the UK's "
                  "affordability %s and safety %s, its own weather %s, no fare; the Faroes their own prices), "
                  "never by scoring itself: %s"
                  % (gb and gb["afford"], gb and gb["safe"], sct_wx,
                     [re.sub(r"<[^>]+>", " ", js[i]["grades"]).split()[:2] for i in BORROW])))
# The search link: under every strip but a Level 4 country's, which keeps its
# line empty (one height for every strip), sponsored, for the travel month or
# else the cheapest, from the hub to that month's city.
links = {iso: re.search(r'<div class="faresearch">(.*?)</div>', js[iso]["fares"]) for iso in GUIDES if js[iso]["fares"]}
lvl4 = {iso for iso in links if G.adv_level(iso, FIX["advisories"]) == 4}
bad_l = [iso for iso, m in links.items() if not m or (iso in lvl4) != (m.group(1) == "")]
m_th = links.get("TH") and links["TH"].group(1)
sel = G.guide_month(TODAY)
th_month = sel if CURVES["TH"]["months"].get("%d-%02d" % (TODAY.year if sel > TODAY.month - 1 else TODAY.year + 1, sel)) \
    else None
results.append(ok(not bad_l and len(links) >= 50 and m_th
                  and 'rel="sponsored nofollow noopener"' in m_th and 'target="_blank"' in m_th
                  and "https://www.aviasales.com/search/NYC" in m_th and "marker=738472" in m_th
                  and (th_month is None or ("Search %s flights from NYC" % G.MON_ABBR[th_month - 1]) in m_th),
                  "every strip ends in its search link line, empty only for Level 4 (%d strips, %d Level 4) %s %s"
                  % (len(links), len(lvl4), bad_l[:6] or "", (m_th or "")[:120])))
d0 = datetime.date(2026, 11, 23)
results.append(ok(G.search_url("NYC", "BKK", "2026-12", d0) == "https://www.aviasales.com/search/NYC1512BKK25121?marker=738472"
                  and G.search_url("NYC", "BKK", "2026-11", d0) == "https://www.aviasales.com/search/NYC2411BKK04121?marker=738472"
                  and G.search_url(None, "BKK", "2026-12", d0) is None and G.search_url("NYC", None, "2026-12", d0) is None,
                  "the search: out on the month's 15th (tomorrow once it has passed), back 10 days later"))

# --- redraws (review #6 follow-up) ----------------------------------------------------------
# Every /api/flight-value answer redraws the line and the strip (askValueFlightValue polls
# while the server fills, for up to 15 minutes after a deploy). Drawn again unchanged, they
# must write nothing: rewritten, the reader's keyboard focus inside fell to <body> and an
# open tip lost its element; the strip, hidden while its curve was fetched, did too.
# And a line waiting for the first month curves draws its grey boxes after 2.5 s however
# the guide was opened (from Top Picks no timer was set: blank until they came), and never
# leaves another country's line standing meanwhile.
REDRAW_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv; valueFlightsSettled = true;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp;
for (const iso of ["TH", "VN"]) _fareMonthsCache["US:" + iso] = Promise.resolve(FIX.curves[iso]);
let timers = [];
setTimeout = function (f, ms) { timers.push({ f: f, ms: ms }); return timers.length; };
// The host as a browser has it: each write puts new nodes under it.
function watch(el) {
  let html = el.innerHTML, hidden = el.hidden;
  const w = { writes: 0, hides: 0 };
  el.childNodes.length = 0; el.childNodes.push({ n: 0 });
  Object.defineProperty(el, "innerHTML", { configurable: true, get: () => html,
    set: (v) => { html = v; w.writes++; el.childNodes.length = 0; if (v) el.childNodes.push({ n: w.writes }); } });
  Object.defineProperty(el, "hidden", { configurable: true, get: () => hidden, set: (v) => { if (v) w.hides++; hidden = v; } });
  return w;
}
const gg = $("guideGrades"), gf = $("guideFares"), o = {};
(async () => {
  ccGuideIso = "TH";
  const wg = watch(gg), wf = watch(gf);
  await renderGuideGrades("TH"); await renderGuideFares("TH");
  const kid = gg.childNodes[0];
  wg.writes = wf.writes = wf.hides = 0;
  await renderGuideGrades("TH"); await renderGuideFares("TH");
  o.same = [wg.writes, wf.writes, wf.hides, gf.hidden, gg.childNodes[0] === kid, gg.innerHTML.indexOf('data-gg="ov"') >= 0];
  flightValue = JSON.parse(JSON.stringify(FIX.fv)); flightValue.countries.TH.lo *= 0.5; flightValue.countries.TH.hi *= 2;
  await renderGuideFares("TH");
  o.moved = [wf.writes, wf.hides];
  gg.innerHTML = "";
  await renderGuideGrades("TH");
  o.emptied = [wg.writes, gg.innerHTML.indexOf('data-gg="ov"') >= 0];
  // The search link known only once the advisory lists land (guideNoBookings null), the
  // strip drawn twice meanwhile (without the range, then with it): the latest draw fills
  // the link in, the strip counts as written with it, and the next redraw writes nothing.
  const realNB = guideNoBookings, realBK = ensureBookingsKnown;
  let known = null, settle = null;
  const bookingsP = new Promise((r) => { settle = r; });
  guideNoBookings = () => known; ensureBookingsKnown = () => bookingsP;
  const slot = { firstChild: null, isConnected: true, html: "",
                 get innerHTML() { return this.html; }, set innerHTML(v) { this.html = v; this.firstChild = v ? {} : null; } };
  gf.querySelector = (q) => (q === ".faresearch" ? slot : null);
  flightValue = null; await renderGuideFares("TH");
  flightValue = FIX.fv; await renderGuideFares("TH");
  known = false; settle(); await bookingsP;
  const w0 = wf.writes;
  await renderGuideFares("TH");
  o.link = [slot.html.indexOf("Search ") >= 0, wf.writes - w0];
  guideNoBookings = realNB; ensureBookingsKnown = realBK;
  // VN opened (from Top Picks: the fares are in) while the first month curves are out.
  flightValue = null; _fvAsk = { origin: "US", done: false }; _guideFareLate = false; timers = [];
  ccGuideIso = "VN";
  await renderGuideGrades("VN");
  const late = timers.filter((t) => t.ms === 2500);
  o.wait = [gg.innerHTML, late.length];
  await renderGuideGrades("VN");
  o.once = timers.filter((t) => t.ms === 2500).length;
  late[0].f();
  await renderGuideGrades("VN");
  o.boxes = [_guideFareLate, (gg.innerHTML.match(/ggpend/g) || []).length];
  flightValue = FIX.fv; _fvAsk.done = true;
  await renderGuideGrades("VN");
  o.landed = [(gg.innerHTML.match(/ggpend/g) || []).length, gg.innerHTML.indexOf('data-gg="ov"') >= 0];
  print(JSON.stringify(o));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, curves={k: CURVES.get(k) for k in ("TH", "VN")}), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + REDRAW_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    rd = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    rd = {"error": (r.stderr or r.stdout)[-300:]}
results.append(ok(rd.get("same") == [0, 0, 0, False, True, True] and rd.get("moved") == [1, 0]
                  and rd.get("emptied") == [2, True] and rd.get("link") == [True, 0],
                  "a redraw that changes nothing writes nothing and never hides the strip (a poll's answer), "
                  "a search link filled in late included; a moved range redraws the strip, an emptied line is "
                  "drawn again %s" % rd))
results.append(ok(rd.get("wait") == ["", 1] and rd.get("once") == 1 and rd.get("boxes") == [True, 3]
                  and rd.get("landed") == [0, True],
                  "a guide opened from Top Picks while the month curves are out: another country's line goes, "
                  "one 2.5 s timer, then the grey boxes, then the grades once they land %s"
                  % {k: rd.get(k) for k in ("wait", "once", "boxes", "landed", "error") if k in rd}))

# --- the page -----------------------------------------------------------------------------
import server  # noqa: E402

server._warm_adv_lists = lambda: None
server._warm_watchouts = lambda iso: None
real_conf = server.flights.is_configured
server.flights.is_configured = lambda: False      # no fares here: the served lines without them
cfg = server.store.load_config()
rkey = (cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD")
try:
    cold = server._render_index("TH").decode("utf-8")
    now = time.time()
    server._adv_cache["us"] = (now, FIX["advisories"])
    server._rates_cache[rkey] = (now, FIX["rates"])
    server._ppp_cache.update(at=now, data=FIX["ppp"])
    warm = {iso: server._render_index(iso).decode("utf-8") for iso in ("TH", "AF", "GB-ENG")}
    home = server._render_index(None).decode("utf-8")
finally:
    server.flights.is_configured = real_conf
utc = datetime.datetime.now(datetime.timezone.utc).date()
nofares = dict(inputs, flights=None, fv=None)
results.append(ok('data-gssr' not in cold and '<div id="guideGrades" class="guidegrades"></div>' in cold
                  and '<div id="guideFares" class="guidefares" hidden></div>' in cold and "{{" not in cold,
                  "caches cold: a guide's grades line is empty and its strip hidden, as before"))
gw = [iso for iso, h in warm.items()
      if ('<div id="guideGrades" class="guidegrades">%s</div>' % G.grades(iso, nofares, utc)) in h
      and ('data-gssr="%d,%d"' % (G.guide_month(utc), utc.month)) in h and server._GUIDE_HOLD in h and "{{" not in h]
results.append(ok(len(gw) == 3 and 'data-gg="ov"' in warm["TH"] and "Level 4, do not travel" in warm["AF"],
                  "caches warm: each guide serves its grades line (graded, Level 4, England's) and the "
                  "pre-paint script: %s" % gw))
results.append(ok("data-gssr" not in home and server._GUIDE_HOLD not in home
                  and '<div id="guideGrades" class="guidegrades"></div>' in home,
                  "the homepage serves no guide line"))

HOLD = re.search(r"<script>(.*)</script>", server._GUIDE_HOLD, re.S).group(1)
PAGE = r"""
function El(id) { this.id = id; this.hidden = false; this.innerHTML = "SERVED"; this.attrs = {}; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
function USP(s) { var o = {}, ks = []; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) { if (!kv) return;
  var i = kv.indexOf("="), k = i < 0 ? kv : kv.slice(0, i); o[k] = i < 0 ? "" : kv.slice(i + 1); ks.push(k); });
  this.forEach = function (f) { ks.forEach(function (k) { f(o[k], k); }); }; }
function run(c) {
  var els = { "tab-guide": new El("tab-guide"), guideGrades: new El("guideGrades"), guideFares: new El("guideFares") };
  els["tab-guide"].attrs["data-gssr"] = c.gssr;
  var document = { getElementById: function (id) { return els[id]; } };
  var location = { search: c.search };
  var store = c.store, localStorage = { getItem: function (k) { return k in store ? store[k] : null; } };
  var RealDate = Date;
  var FakeDate = function (y, m, d) { return arguments.length ? new RealDate(y, m, d) : new RealDate(c.y, c.m - 1, c.d); };
  (function (document, location, localStorage, Date, URLSearchParams) { eval(HOLD_SRC); })(document, location, localStorage, FakeDate, USP);
  return { gssr: els["tab-guide"].getAttribute("data-gssr"), grades: els.guideGrades.innerHTML,
           fares: els.guideFares.innerHTML, hidden: els.guideFares.hidden };
}
var CASES = JSON.parse(CASES_JSON), out = [];
for (var i = 0; i < CASES.length; i++) out.push(run(CASES[i]));
print(JSON.stringify(out));
"""
W = "11,10"
HOLD_CASES = [
    ("a first visit on Oct 28 (graded for November)", "", {}, (2026, 10, 28), True),
    ("utm_ and fbclid", "?utm_medium=email&fbclid=x", {}, (2026, 10, 28), True),
    ("stored US origin, USD fares", "", {"fx_origin": "US", "wg_flightcur": "USD"}, (2026, 10, 28), True),
    ("the newsletter's ?vmn=12", "?vmn=12", {}, (2026, 10, 28), False),
    ("Oct 20: graded for October", "", {}, (2026, 10, 20), False),
    ("Nov 1: the same window, another month on the fare strip", "", {}, (2026, 11, 1), False),
    ("a saved home country", "", {"fx_origin": "DE"}, (2026, 10, 28), False),
    ("a saved currency", "", {"fx_homecur": "GBP"}, (2026, 10, 28), False),
    ("fares shown in euros", "", {"wg_flightcur": "EUR"}, (2026, 10, 28), False),
    ("saved priorities", "", {"fx_priorities2": "{}"}, (2026, 10, 28), False),
    ("Germany's advisories", "", {"wg_advsrc": "de"}, (2026, 10, 28), False),
]
cases = [{"gssr": W, "search": q, "store": st, "y": d[0], "m": d[1], "d": d[2]} for _n, q, st, d, _k in HOLD_CASES]
with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "hold.js")
    open(sp, "w", encoding="utf-8").write(PAGE.replace("HOLD_SRC", json.dumps(HOLD))
                                          .replace("CASES_JSON", json.dumps(json.dumps(cases))))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=60)
try:
    got = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    got = None
bad = []
for (name, _q, _st, _d, keep), g in zip(HOLD_CASES, got or []):
    good = (g == {"gssr": W, "grades": "SERVED", "fares": "SERVED", "hidden": False} if keep
            else g == {"gssr": None, "grades": "", "fares": "", "hidden": True})
    if not good:
        bad.append((name, g))
results.append(ok(got is not None and len(got) == len(HOLD_CASES) and not bad,
                  "the pre-paint script keeps the served line and strip for a first visit and empties them for "
                  "%d other readers %s" % (sum(1 for c in HOLD_CASES if not c[4]),
                                           bad or (r.stderr[-300:] if got is None else ""))))

# app.js: the served line and strip held until rates, advisories and fares are in.
HOLD_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = null; flightValue = null; lastRates = null;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp;
_guideAskedFares = true;   // the fares fetch is the test's to settle
window.__WGGC__ = "TH"; ccGuideIso = "TH"; _fareMonthsCache["US:TH"] = Promise.resolve(FIX.curve);
const gg = $("guideGrades"), gf = $("guideFares");
gg.innerHTML = "SERVED"; gf.innerHTML = "SERVED"; gf.hidden = false;
servedGuide = { iso: "TH", month: travelMonth() }; servedFaresOnScreen = true;
const o = [];
(async () => {
  await renderGuideGrades("TH"); await renderGuideFares("TH"); o.push([gg.innerHTML, gf.innerHTML, gf.hidden, !!servedGuide]);
  lastRates = FIX.rates; valueFlightsSettled = true; flightsData = FIX.flights; flightValue = FIX.fv;
  await renderGuideGrades("TH"); await renderGuideFares("TH"); o.push([gg.innerHTML.slice(0, 30), gf.innerHTML.slice(0, 30), gf.hidden, !!servedGuide]);
  servedGuide = { iso: "TH", month: travelMonth() }; gg.innerHTML = "SERVED"; lastRates = null;
  ccGuideIso = "VN"; await renderGuideGrades("VN"); o.push([gg.innerHTML.slice(0, 5), !!servedGuide]);
  print(JSON.stringify(o));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, curve=CURVES.get("TH")), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + HOLD_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    o = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    o = {"error": (r.stderr or r.stdout)[-300:]}
results.append(ok(isinstance(o, list) and o[0] == ["SERVED", "SERVED", False, True]
                  and o[1][0].startswith("<span data-gg=") and o[1][1].startswith('<span class="fareshead">')
                  and o[1][2] is False and o[1][3] is False and o[2] == ["<span", False],
                  "app.js keeps the served line and strip (on screen, not hidden) while rates and fares are out, "
                  "draws its own once they are in, and lets go for another country %s" % ("" if isinstance(o, list) else o)))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

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
    ungraded country — and the served strip is the client's (or both are
    none: fewer than three months), so the browser's copy replaces them
    without anything moving;
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
# The country's one curve (/api/flight-months), as the flight-value build holds it.
CURVES = {iso: {"origin": "US", "months": {k: {"price": v[0], "dest": v[1]} for k, v in c["curve"].items()}}
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
for iso in GUIDES:
    g = G.grades(iso, inputs, TODAY)
    if g != bare(js[iso]["grades"]):
        bad_g.append((iso, g, bare(js[iso]["grades"])))
    f = G.fares(iso, CURVES.get(iso), FIX["fv"], TODAY, render_guide.name_for_iso)
    if f != bare(js[iso]["fares"]):
        bad_f.append((iso, f, bare(js[iso]["fares"])))
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
results.append(ok(not bad_f and strips >= 50,
                  "every guide's fares strip is the client's, or none in both (%d strips) %s"
                  % (strips, [x[0] for x in bad_f][:10] or "")))
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

"""The homepage's served Top Picks table and note (fxtracker/home_picks.py)
against what public/app.js draws for the same view, with app.js itself run
under jsc (scripts/appjs_harness.js) on one fixture: production's own /api
answers in scripts/parity/fixture_*.json, public/ppp.json, climate.json,
activities.json, and a fixed popular set.

    /usr/bin/python3 scripts/test_home_picks.py

What it holds the code to:
  * flexWindow and bestOfWindow: the Python ports equal app.js's for every
    day of 2026 and 2028 (a leap February) and for value/weather ranking,
    ties, a budget test and a preferred-fare test;
  * the table: renderValue for the default view (US, Any time, Top 5, the
    "b" safety floor, nothing visited, no budget) writes #topCards; the
    served table is the same markup row for row with the tooltips taken out
    (title, data-tip, aria-label) and the header as markSort leaves it — so
    the browser's copy replaces it without anything moving; and the note
    above it (#picksNote) likewise;
  * each piece for every country and month, not only five rows: the Any time
    seasonal tag (seasonalTags), the season strip, the price-data ⚠️
    (pppNotes), the FX mark, the advisory-move mark;
  * the page: index.html keeps its skeleton for the guides and for a reader
    the served view isn't for; the homepage serves the table and note when
    the caches hold their inputs and the skeleton when they don't; the
    pre-paint script's window is flexWindow's; app.js holds the served rows
    until its data is in (holdServedPicks).
"""
import datetime, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import home_picks as H, picks, pricelevel  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
POPULAR = sorted(picks.FALLBACK_POPULAR)
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "flights": load("scripts", "parity", "fixture_flights.json"),
       "fv": load("scripts", "parity", "fixture_flight_value.json"),
       "ppp": load("public", "ppp.json"), "climate": load("public", "climate.json"),
       "activities": load("public", "activities.json"), "world": load("public", "world.geojson"),
       "slugs": load("public", "slugs.json"), "popular": POPULAR}
SLUGS = {iso: s for s, iso in FIX["slugs"].items()}
TODAY = datetime.date.today()        # both sides read the clock, as parity.py's do

DRIVER = r"""
// ---- the test: the default Top Picks view on the fixture -------------------------
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
loaded.value = true;
drawMap = function () {};
$("pickCount").value = "5"; $("safeFloor").value = "b";
const out = { views: [], parts: {}, flex: [], best: [] };
for (const v of FIX.variants) {
  flightsData = v.flights ? FIX.flights : null; flightValue = v.fv ? FIX.fv : null;
  popularSet = new Set(v.popular); popularDataBacked = v.backed;
  renderValue();
  out.views.push({ top: $("topCards").innerHTML, note: $("picksNote").innerHTML });
}
const strip = (h) => String(h);
for (const iso in CUR_BY_ISO) {
  const p = { ppp: !!pppNotes(iso), fx: fxMark(iso), adv: advMovedMark(iso), tag: [], strip: [] };
  for (let m = 1; m <= 12; m++) { p.tag.push(seasonalTags(iso, m, 1, true)); p.strip.push(seasonStrip(iso, m)); }
  out.parts[iso] = p;
}
for (const d of FIX.days) { const [y, mo, da] = d.split("-").map(Number); out.flex.push(flexWindow(new Date(y, mo - 1, da)).join(",")); }
const budgetOk = (s) => s.value < 80, ownFare = (s) => !!s.own;
for (const c of FIX.bestCases) {
  const by = {}; for (const k in c.by) by[+k] = c.by[k];
  const r = bestOfWindow(by, c.win, c.key, c.ok ? budgetOk : undefined, c.own ? ownFare : undefined);
  out.best.push(r ? { month: r.month, moved: !!r.moved, own: !!r.own } : null);
}
print(JSON.stringify(out));
"""

# bestOfWindow cases: ties (the sooner wins), value vs weather ranking, a missing
# month, a budget the best month fails, a preferred month with its own fare.
WIN = [11, 12, 1, 2, 3, 4]
CASES = [
    {"win": WIN, "key": "value", "by": {11: {"value": 80, "wx": 70}, 12: {"value": 85, "wx": 60}, 1: {"value": 85, "wx": 90}}},
    {"win": WIN, "key": "wx", "by": {11: {"value": 80, "wx": 90}, 12: {"value": 85, "wx": 90}, 2: {"value": 70, "wx": 50}}},
    {"win": WIN, "key": "wx", "by": {11: {"value": 80, "wx": None}, 3: {"value": 60, "wx": 10}}},
    {"win": WIN, "key": "value", "ok": True, "by": {11: {"value": 90, "wx": 1}, 12: {"value": 79, "wx": 1}, 4: {"value": 75, "wx": 1}}},
    {"win": WIN, "key": "value", "ok": True, "by": {11: {"value": 95, "wx": 1}, 12: {"value": 96, "wx": 1}}},
    {"win": WIN, "key": "value", "ok": True, "own": True,
     "by": {11: {"value": 78, "wx": 1}, 12: {"value": 70, "wx": 1, "own": True}, 1: {"value": 75, "wx": 1, "own": True}}},
    {"win": WIN, "key": "value", "by": {}},
]
DAYS = [(datetime.date(y, 1, 1) + datetime.timedelta(days=i)).isoformat()
        for y in (2026, 2028) for i in range(366 if y == 2028 else 365)]


# The views compared: the fixture as served, then the branches it doesn't reach —
# no flight values (the distance measure, "~" estimates), no fares at all (no
# Flights measure), no popular set ("Ranked by …"), an off-the-beaten-path one,
# countries with no weather measure.
OFFBEAT = ["AL", "GE", "AM", "UZ", "KG", "MN", "BO", "PY", "MW", "ZM", "LA", "BT", "OM", "TN"]
VARIANTS = [
    {"name": "as served", "flights": True, "fv": True, "popular": POPULAR, "backed": True},
    {"name": "no flight values", "flights": True, "fv": False, "popular": POPULAR, "backed": True},
    {"name": "no fares", "flights": False, "fv": False, "popular": POPULAR, "backed": False},
    {"name": "no popular set", "flights": True, "fv": True, "popular": [], "backed": True},
    {"name": "off the beaten path", "flights": True, "fv": False, "popular": OFFBEAT, "backed": True},
    # No climate.json entry: graded on 3 of 4 measures (the coverage mark), no strip.
    {"name": "no weather data", "flights": True, "fv": True, "popular": ["MO", "KM", "SC", "MT", "AD", "SM", "MH",
                                                                         "FM", "PW", "TC", "VG"], "backed": True},
]


def run_jsc():
    fix = dict(FIX, days=DAYS, bestCases=CASES, variants=VARIANTS)
    with tempfile.TemporaryDirectory() as d:
        fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
        json.dump(fix, open(fp, "w"))
        open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
        try:
            r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout.strip().splitlines()[-1]), r
        except Exception as e:
            return None, e


def bare(h):
    """The markup with the tooltips taken out — all the served copy leaves out."""
    return re.sub(r' (?:title|data-tip|aria-label)="[^"]*"', "", h or "")


def mark_sorted(h):
    """What markSort does to the header after renderGradeTable: each sortable
    th's contents wrapped in a sort button."""
    return re.sub(r'(<th class="[^"]*sortable"[^>]*>)(.*?)(</th>)',
                  lambda m: m.group(1) + '<button type="button" class="sortbtn">' + m.group(2) + "</button>" + m.group(3),
                  h, flags=re.S)


js, err = run_jsc()
results.append(ok(js is not None, "app.js runs under jsc with the harness (%s)" % ("ok" if js else err)))
if js is None:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)

# --- flexWindow / bestOfWindow ---------------------------------------------------------
py_flex = [",".join(map(str, H.flex_window(datetime.date.fromisoformat(d)))) for d in DAYS]
bad = [(d, a, b) for d, a, b in zip(DAYS, js["flex"], py_flex) if a != b]
results.append(ok(not bad and len(DAYS) == 731, "flex_window == flexWindow on all %d days of 2026 and 2028 %s"
                  % (len(DAYS), bad[:3] or "")))
py_best = []
for c in CASES:
    r = H.best_of_window({int(k): v for k, v in c["by"].items()}, c["win"], c["key"],
                         (lambda s: s["value"] < 80) if c.get("ok") else None,
                         (lambda s: bool(s.get("own"))) if c.get("own") else None)
    py_best.append({"month": r["month"], "moved": bool(r.get("moved")), "own": bool(r.get("own"))} if r else None)
results.append(ok(py_best == js["best"], "best_of_window == bestOfWindow on %d cases %s"
                  % (len(CASES), "" if py_best == js["best"] else (py_best, js["best"]))))

# --- the table and the note -----------------------------------------------------------
seen = set()
for v, view in zip(VARIANTS, js["views"]):
    inputs = {k: FIX[k] for k in ("rates", "advisories", "ppp", "climate", "activities")}
    inputs.update(flights=FIX["flights"] if v["flights"] else None, fv=FIX["fv"] if v["fv"] else None,
                  popular=set(v["popular"]) if v["backed"] else None)
    if not v["backed"]:
        # Not data-backed: app.js keeps its own fallback set (== picks.FALLBACK_POPULAR).
        assert set(v["popular"]) == picks.FALLBACK_POPULAR
    served = H.build(inputs, SLUGS, TODAY)
    client = mark_sorted(bare(view["top"]))
    same = served is not None and served["table"] == client
    if not same and served:
        a, b = served["table"], client
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        print("        first difference at %d:\n        served %r\n        client %r" % (i, a[i - 80:i + 120], b[i - 80:i + 120]))
    rows = re.findall(r'<tr data-iso="([A-Z]+)" data-m="(\d+)"', (served or {}).get("table", ""))
    seen |= set(re.findall(r'class="(?:seastag )?(covmark|hzmark|seasfly|seasoff|advmv|fxmark)[ "]|>(~)[A-F]', client))
    results.append(ok(same and len(rows) == 5, "%s: the served table is the client's, row for row, tooltips aside "
                      "(%s)" % (v["name"], " ".join("%s in %s" % (iso, H.MON_ABBR[int(m) - 1]) for iso, m in rows))))
    results.append(ok(served is not None and served["note"] == bare(view["note"]),
                      "%s: the note is the client's: %s" % (v["name"], served and served["note"])))
    if v["name"] == "as served":
        results.append(ok(served["window"] == ",".join(map(str, H.flex_window(TODAY))),
                          "the served window is today's: %s" % served["window"]))
marks = sorted(x for t in seen for x in t if x)
results.append(ok({"covmark", "fxmark", "seasfly", "~"} <= set(marks),
                  "the views between them show a coverage mark, an FX mark, a cheapest-flight chip and an "
                  "estimated fare: %s" % marks))

# --- every piece, every country and month ---------------------------------------------
strength = {r["code"]: r["strength_pct"] for r in FIX["rates"]["rows"] if "code" in r and "strength_pct" in r}
meta = {}
for it in FIX["advisories"]["items"]:
    if it.get("iso"):
        meta[it["iso"]] = it
bad = {"tag": [], "strip": [], "ppp": [], "fx": [], "adv": []}
for iso, p in js["parts"].items():
    for m in range(1, 13):
        if H.seasonal_tag(FIX["activities"], iso, m) != bare(p["tag"][m - 1]):
            bad["tag"].append((iso, m))
        if H.season_strip(FIX["climate"], iso, m) != bare(p["strip"][m - 1]):
            bad["strip"].append((iso, m))
    if H.ppp_note(iso, FIX["ppp"], strength) != p["ppp"]:
        bad["ppp"].append(iso)
    code = picks.CUR_BY_ISO.get(iso)
    nom = strength.get(code) if code and code != "USD" else None
    fx = H.fx_mark({"fx": pricelevel.real_fx_pct(nom, iso, "US", FIX["ppp"]) if nom is not None else None})
    if fx != bare(p["fx"]):
        bad["fx"].append(iso)
    if H.adv_moved(meta.get(iso), TODAY) != bare(p["adv"]):
        bad["adv"].append(iso)
n = len(js["parts"])
tags = sum(1 for p in js["parts"].values() for t in p["tag"] if t)
results.append(ok(not bad["tag"] and tags > 300,
                  "Any time's seasonal tag for %d countries x 12 months (%d tags) %s" % (n, tags, bad["tag"][:5] or "")))
results.append(ok(not bad["strip"], "the season strip for every country and month %s" % (bad["strip"][:5] or "")))
results.append(ok(not bad["ppp"] and any(p["ppp"] for p in js["parts"].values()),
                  "the price-data ⚠️ for every country (%d marked) %s"
                  % (sum(1 for p in js["parts"].values() if p["ppp"]), bad["ppp"] or "")))
results.append(ok(not bad["fx"] and any(p["fx"] for p in js["parts"].values()),
                  "the FX mark for every country (%d marked) %s"
                  % (sum(1 for p in js["parts"].values() if p["fx"]), bad["fx"] or "")))
results.append(ok(not bad["adv"], "the advisory-move mark for every country (%d marked) %s"
                  % (sum(1 for p in js["parts"].values() if p["adv"]), bad["adv"] or "")))

# --- the page -----------------------------------------------------------------------------
import time  # noqa: E402
import server  # noqa: E402

server._warm_adv_lists = lambda: None
server._warm_popularity = lambda: None
real_conf = server.flights.is_configured
server.flights.is_configured = lambda: False      # no fares here: the served view without them
cfg = server.store.load_config()
rkey = (cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD")
cold = server._render_index(None).decode("utf-8")
now = time.time()
server._adv_cache["us"] = (now, FIX["advisories"])
server._rates_cache[rkey] = (now, FIX["rates"])
server._ppp_cache.update(at=now, data=FIX["ppp"])
arrivals = {iso: 1000 - i for i, iso in enumerate(POPULAR)}
arrivals.update({"X%d" % i: 1 for i in range(30)})          # more than 20 figures: data-backed
server._pop_cache.update(at=now, data={"arrivals": arrivals})
try:
    home = server._render_index(None).decode("utf-8")
    guide = server._render_index("JP").decode("utf-8")
finally:
    server.flights.is_configured = real_conf
want = H.build(dict({k: FIX[k] for k in ("rates", "advisories", "ppp", "climate", "activities")},
                    flights=None, fv=None, popular=H.popular_set(arrivals)),
               SLUGS, datetime.datetime.now(datetime.timezone.utc).date())
results.append(ok('data-ssr' not in cold and 'class="gradetable skeleton" aria-hidden="true">' in cold
                  and "{{" not in cold, "caches cold: the homepage serves index.html's skeleton, as before"))
results.append(ok(('data-ssr="%s"' % want["window"]) in home and want["table"] in home
                  and ('</span>%s</p>' % want["note"]) in home and server._TOP_HOLD in home
                  and 'class="gradetable skeleton" aria-hidden="true" hidden>' in home
                  and 'aria-hidden="true" hidden>🌍 Popular destinations, ranked by value' in home and "{{" not in home,
                  "caches warm: the homepage serves the table and note, the skeleton kept hidden beside them"))
results.append(ok("data-ssr" not in guide and want["table"] not in guide and server._TOP_HOLD not in guide
                  and 'class="gradetable skeleton" aria-hidden="true">' in guide,
                  "a guide keeps index.html's skeleton bytes"))

# The pre-paint script under jsc: which readers keep the served rows.
HOLD = re.search(r"<script>(.*)</script>", server._TOP_HOLD, re.S).group(1)
PAGE = r"""
function El(tag, kids) { this.tag = tag; this.hidden = tag === "skel" || tag === "skeltext"; this.childNodes = kids || []; this.attrs = {}; }
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.removeChild = function (c) { var i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); return c; };
Object.defineProperty(El.prototype, "firstChild", { get: function () { return this.childNodes[0]; } });
Object.defineProperty(El.prototype, "lastChild", { get: function () { return this.childNodes[this.childNodes.length - 1]; } });
function USP(s) { var o = {}, ks = []; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) { if (!kv) return;
  var i = kv.indexOf("="), k = i < 0 ? kv : kv.slice(0, i); o[k] = i < 0 ? "" : kv.slice(i + 1); ks.push(k); });
  this.forEach = function (f) { ks.forEach(function (k) { f(o[k], k); }); }; }
function run(c) {
  var skel = new El("skel"), served = new El("served"), top = new El("top", [skel, served]);
  top.attrs["data-ssr"] = c.ssr;
  top.getElementsByTagName = function () { return this.childNodes; };
  var note = new El("note", [new El("skeltext"), new El("t1"), new El("i"), new El("t2")]);
  var document = { getElementById: function (id) { return id === "topCards" ? top : note; } };
  var location = { search: c.search };
  var store = c.store, localStorage = { getItem: function (k) { return k in store ? store[k] : null; } };
  var RealDate = Date;
  var FakeDate = function (y, m, d) { return arguments.length ? new RealDate(y, m, d) : new RealDate(c.y, c.m - 1, c.d); };
  (function (document, location, localStorage, Date, URLSearchParams) { eval(HOLD_SRC); })(document, location, localStorage, FakeDate, USP);
  return { kept: top.childNodes.map(function (x) { return x.tag; }).join(","), ssr: top.getAttribute("data-ssr"),
           skelHidden: skel.hidden, note: note.childNodes.map(function (x) { return x.tag + (x.hidden ? "(hidden)" : ""); }).join(",") };
}
var CASES = JSON.parse(CASES_JSON), out = [];
for (var i = 0; i < CASES.length; i++) out.push(run(CASES[i]));
print(JSON.stringify(out));
"""
W = "11,12,1,2,3,4"
HOLD_CASES = [
    ("a first visit on Oct 28 (Nov–Apr)", "", {}, (2026, 10, 28), True),
    ("utm_ and gclid, tab=value", "?utm_source=x&gclid=1&tab=value", {}, (2026, 10, 28), True),
    ("stored US origin, USD, Top 5", "", {"fx_origin": "US", "fx_homecur": "USD", "fx_pickcount": "5"}, (2026, 10, 28), True),
    ("Oct 20: the window still starts in October", "", {}, (2026, 10, 20), False),
    ("a link with vmn=3", "?vmn=3", {}, (2026, 10, 28), False),
    ("a link with vo=GB", "?vo=GB", {}, (2026, 10, 28), False),
    ("tab=guide", "?tab=guide", {}, (2026, 10, 28), False),
    ("a saved home country", "", {"fx_origin": "GB"}, (2026, 10, 28), False),
    ("a saved currency", "", {"fx_homecur": "EUR"}, (2026, 10, 28), False),
    ("Top 10", "", {"fx_pickcount": "10"}, (2026, 10, 28), False),
    ("any safety level", "", {"fx_safefloor": "any"}, (2026, 10, 28), False),
    ("a budget", "", {"wg_budget": "1500"}, (2026, 10, 28), False),
    ("interests", "", {"wg_interests": '["beach"]'}, (2026, 10, 28), False),
    ("saved priorities", "", {"fx_priorities2": "{}"}, (2026, 10, 28), False),
    ("saved factors", "", {"fx_factors2": "[]"}, (2026, 10, 28), False),
    ("Canada's advisories", "", {"wg_advsrc": "ca"}, (2026, 10, 28), False),
    ("a visited list", "", {"fx_visited": '["FR"]'}, (2026, 10, 28), False),
]
cases = [{"ssr": W, "search": q, "store": st, "y": d[0], "m": d[1], "d": d[2]} for _n, q, st, d, _k in HOLD_CASES]
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
    if keep:
        good = g["kept"] == "served" and g["ssr"] == W and g["note"] == "t1,i,t2"
    else:
        good = g["kept"] == "skel" and g["ssr"] is None and not g["skelHidden"] and g["note"] == "skeltext"
    if not good:
        bad.append((name, g))
results.append(ok(got is not None and len(got) == len(HOLD_CASES) and not bad,
                  "the pre-paint script keeps the served rows for a first visit (tracking queries and stored "
                  "defaults too) and swaps in the skeleton for %d other readers %s"
                  % (sum(1 for c in HOLD_CASES if not c[4]), bad or (r.stderr[-300:] if got is None else ""))))

# app.js: the served rows held until its data is in, then drawn over.
HOLD_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = null; flightValue = null;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
popularSet = new Set(FIX.popular); popularDataBacked = true;
loaded.value = true; drawMap = function () {};
$("pickCount").value = "5"; $("safeFloor").value = "b";
const top = $("topCards"), note = $("picksNote");
top.innerHTML = "SERVED"; note.innerHTML = "SERVED NOTE";
servedPicks = flexWindow().join(","); servedOnScreen = true;
const o = [];
activities = null; renderValue(); o.push([top.innerHTML, note.innerHTML, !!servedPicks]);
activities = FIX.activities; popularitySettled = true; renderValue(); o.push([top.innerHTML, note.innerHTML, !!servedPicks]);
valueFlightsSettled = true; renderValue(); o.push([top.innerHTML.slice(0, 40), note.innerHTML.slice(0, 20), !!servedPicks]);
servedPicks = flexWindow().join(","); servedOnScreen = true; top.innerHTML = "SERVED"; valueFlightsSettled = false;
$("valueMonth").value = "3"; renderValue(); o.push([top.innerHTML.slice(0, 40), !!servedPicks]);
print(JSON.stringify(o));
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + HOLD_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    o = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    o = None
results.append(ok(o is not None and o[0] == ["SERVED", "SERVED NOTE", True] and o[1] == ["SERVED", "SERVED NOTE", True]
                  and o[2][0].startswith("<table") and o[2][2] is False
                  and o[3][0].startswith("<table") and o[3][1] is False,
                  "app.js keeps the served rows and note while its activities, popularity or fares are out, draws "
                  "its own once they are in, and at once for another view (a month picked) %s"
                  % ("" if o else r.stderr[-300:])))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

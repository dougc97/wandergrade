"""An exact tie in a ranking breaks on the country's name the same way on the
site, in the served pages and in the newsletter.

    /usr/bin/python3 scripts/test_tie_order.py

The newsletter's order is the reference: picks.py build_variant sorts on
(-value, -raw, name) with Python's string order (by code point), and so do
the served Top Picks table (home_picks.rank) and /cheapest
(render_cheapest.rank_month). app.js rankValue used to compare the names with
localeCompare, a reader's A-Z that puts "Côte d'Ivoire" before Croatia,
"eSwatini" among the E's and "São Tomé" before Saudi Arabia, and it compared
the map data's names ("Dominican Rep.", "Congo") where Python compares the
site's own (picks.NAME_FIX first). It now uses pyStrCmp and valueScores names
a country as picks._score does.

What it holds the code to:
  * the three Python sorts are the one key (-value, -raw, name);
  * pyStrCmp + rankValue, taken out of app.js and run under node (jsc when
    node is missing), order a constructed exact tie of accented, odd-case and
    hyphenated names (and a character past U+FFFF) exactly as Python's sort
    does, where localeCompare does not;
  * valueScores' name (the tie key) is picks._score's for every country the
    fixture scores, app.js run whole under jsc (scripts/appjs_harness.js);
  * two constructed ties on real countries (every other country scored
    below them): the served homepage table (home_picks.build) is the table
    app.js draws, row for row, tooltips aside; its five countries, in order,
    are the newsletter's five picks (picks.build_variant on the frozen digest
    fixtures, scripts/digest_snapshot.py) and the old comparator's five
    differ; /cheapest's month list (rank_month) keeps the same order.
"""
import datetime, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from fxtracker import home_picks as H, picks, pricelevel, render_cheapest as RC  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
read = lambda *a: open(P(*a), encoding="utf-8").read()
APP = read("public", "app.js")
KEY = lambda s: (-s["value"], -s["raw"], s["name"])          # the newsletter's sort


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def run_js(prog):
    """Run a stand-alone program (print() for output) under node, else jsc."""
    node = shutil.which("node")
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "run.js")
        if node:
            open(sp, "w", encoding="utf-8").write("const print = (s) => console.log(s);\n" + prog)
            cmd = [node, sp]
        else:
            open(sp, "w", encoding="utf-8").write(prog)
            cmd = [JSC, sp]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1]), os.path.basename(cmd[0])
        except Exception:
            return None, "%s: %s" % (os.path.basename(cmd[0]), (r.stderr or r.stdout)[-400:])


# --- 1. the Python sorts are one key --------------------------------------------------
want = 'sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))'
srcs = {"picks.py build_variant": read("fxtracker", "picks.py"),
        "home_picks.py rank": read("fxtracker", "home_picks.py"),
        "render_cheapest.py rank_month": read("fxtracker", "render_cheapest.py")}
results.append(ok(all(want in s for s in srcs.values()),
                  "the newsletter, the served table and /cheapest all sort on %s" % want[5:-1]))

# --- 2. the comparator, node-extracted --------------------------------------------------
NAMES = ["Saudi Arabia", "São Tomé and Príncipe", "Croatia", "Côte d'Ivoire", "Cuba", "Curaçao", "Czechia",
         "eSwatini", "Estonia", "Ethiopia", "DR Congo", "Denmark", "Dominica", "Dominican Republic",
         "Republic of the Congo", "Réunion", "Rwanda", "Türkiye", "Tuvalu", "Åland Islands", "Zimbabwe",
         "Guinea-Bissau", "Guinea", "Guinea Bissau", "Timor-Leste", "Ｚ wide", "\U0001D49C script"]
tie = [{"iso": "X%02d" % i, "name": n, "value": 81, "raw": 81.25} for i, n in enumerate(NAMES)]
# A row above and below the tie, and one a hair under it on the unrounded score.
tie += [{"iso": "TOP", "name": "Zzz", "value": 90, "raw": 90.0}, {"iso": "LOW", "name": "Aaa", "value": 50, "raw": 50.0},
        {"iso": "HAIR", "name": "Aab", "value": 81, "raw": 81.0}]
py = [s["iso"] for s in sorted(tie, key=KEY)]
prog = "%s\n%s\nconst rows = %s;\nprint(JSON.stringify({ site: rows.slice().sort(rankValue).map((s) => s.iso),\n" \
       "  locale: rows.slice().sort((a, b) => (b.value - a.value) || (b.raw - a.raw) || a.name.localeCompare(b.name))" \
       ".map((s) => s.iso), cmp: [pyStrCmp('a', 'a'), pyStrCmp('ab', 'a'), pyStrCmp('a', 'ab'), pyStrCmp('', '')] }));" \
       % (js_fn("pyStrCmp"), js_fn("rankValue"), json.dumps(tie, ensure_ascii=False))
js, eng = run_js(prog)
results.append(ok(bool(js_fn("pyStrCmp")) and "pyStrCmp(a.name, b.name)" in js_fn("rankValue"),
                  "app.js rankValue breaks a tie with pyStrCmp"))
results.append(ok(js is not None and js["site"] == py,
                  "rankValue (%s) orders a %d-name exact tie as Python's sort: %s" % (
                      eng, len(NAMES), " < ".join(next(s["name"] for s in tie if s["iso"] == i) for i in py[1:8]) + " …"
                      if js and js["site"] == py else (js and js["site"], py))))
results.append(ok(js is not None and js["cmp"] == [0, 1, -1, 0], "pyStrCmp: equal 0, a prefix first: %s"
                  % (js and js["cmp"])))
results.append(ok(js is not None and js["locale"] != py,
                  "localeCompare (the old tie-break) orders the same tie differently, so the check bites"))

# --- 3. app.js whole under jsc: names, and the drawn table for two ties ------------------
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "flights": load("scripts", "parity", "fixture_flights.json"),
       "fv": load("scripts", "parity", "fixture_flight_value.json"),
       "ppp": load("public", "ppp.json"), "climate": load("public", "climate.json"),
       "activities": load("public", "activities.json"), "world": load("public", "world.geojson"),
       "slugs": load("public", "slugs.json")}
SLUGS = {iso: s for s, iso in FIX["slugs"].items()}
TODAY = datetime.date.today()
# Real countries at Level 1-2 in both the parity and the frozen digest fixtures,
# no visitor fee. Code point vs locale: Croatia < Curaçao < Czechia < Côte
# d'Ivoire (locale: Côte first); Estonia < Republic of the Congo < … < eSwatini
# (locale, on the map data's "Congo": Congo < Estonia < eSwatini < …).
TIES = [["CI", "HR", "CZ", "CW", "DK", "DO"], ["SZ", "TH", "TL", "TR", "CG", "EE"]]
TIED, LOW = 77, 10

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
loaded.value = true;
drawMap = function () {};
$("pickCount").value = "5"; $("safeFloor").value = "b";
const out = { names: {}, views: [] };
const adv = advisoryByIso();
for (const iso in CUR_BY_ISO) { const s = valueScores(iso, 2, adv, null, 1); if (s) out.names[iso] = s.name; }
// The tie: the tied countries at TIED, every other one at LOW (unrounded alike).
const realScores = valueScores;
let TIE = null;
valueScores = function (iso, month, advMap, fares, anchorPl) {
  const s = realScores(iso, month, advMap, fares, anchorPl);
  if (!s || !TIE) return s;
  s.value = s.raw = TIE.includes(iso) ? FIX.tied : FIX.low;
  return s;
};
for (const t of FIX.ties) {
  TIE = t; popularSet = new Set(t); popularDataBacked = true;
  renderValue();
  out.views.push($("topCards").innerHTML);
}
print(JSON.stringify(out));
"""


def run_app():
    fix = dict(FIX, ties=TIES, tied=TIED, low=LOW)
    with tempfile.TemporaryDirectory() as d:
        fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
        json.dump(fix, open(fp, "w"))
        open(sp, "w", encoding="utf-8").write(read("scripts", "appjs_harness.js") + "\n" + APP + "\n"
                                              + DRIVER.replace("FIX_PATH", json.dumps(fp)))
        try:
            r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout.strip().splitlines()[-1]), None
        except Exception as e:
            return None, e


def _home_picks_helpers():
    """bare() and mark_sorted() taken straight from test_home_picks.py, so the
    two tests can never strip different attributes (main's postcard links added
    aria-expanded there). Only those two functions are compiled: importing the
    module would run its whole suite."""
    import ast
    src = read("scripts", "test_home_picks.py")
    want = {"bare", "mark_sorted"}
    nodes = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in want]
    if {n.name for n in nodes} != want:
        raise SystemExit("test_home_picks.py no longer defines bare() and mark_sorted()")
    ns = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), P("scripts", "test_home_picks.py"), "exec"), ns)
    return ns["bare"], ns["mark_sorted"]


bare, mark_sorted = _home_picks_helpers()


def tied_scorer(real, tie):
    def score(iso, *a, **k):
        s = real(iso, *a, **k)
        if s is None:
            return None
        v = TIED if iso in tie else LOW
        return dict(s, value=v, raw=float(v))
    return score


app, err = run_app()
results.append(ok(app is not None, "app.js runs whole under jsc (%s)" % ("ok" if app else err)))
if app is None:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)

rbc = {r["code"]: r["rate_now"] for r in FIX["rates"]["rows"]}
strength = {r["code"]: r["strength_pct"] for r in FIX["rates"]["rows"]}
fit = pricelevel.plausibility_fit(FIX["ppp"], rbc, picks.CUR_BY_ISO)
adv_py = picks.advisory_levels(FIX["advisories"]["items"])
py_names = {}
for iso in picks.CUR_BY_ISO:
    s = picks._score(iso, 2, FIX["ppp"], FIX["climate"], rbc, strength, adv_py, fit, None, 1)
    if s:
        py_names[iso] = s["name"]
diff = {i: (app["names"].get(i), py_names.get(i)) for i in set(app["names"]) | set(py_names)
        if app["names"].get(i) != py_names.get(i)}
results.append(ok(not diff and len(py_names) > 150,
                  "valueScores names every one of %d scored countries as picks._score does (the tie key), "
                  "e.g. DO %r, CG %r %s" % (len(py_names), app["names"].get("DO"), app["names"].get("CG"), diff or "")))

served_orders = []
real_score = picks._score
for t, view in zip(TIES, app["views"]):
    picks._score = tied_scorer(real_score, set(t))
    try:
        inputs = {k: FIX[k] for k in ("rates", "advisories", "ppp", "climate", "activities")}
        inputs.update(flights=FIX["flights"], fv=FIX["fv"], popular=set(t))
        served = H.build(inputs, SLUGS, TODAY)
    finally:
        picks._score = real_score
    client = mark_sorted(bare(view))
    s_rows = re.findall(r'<tr data-iso="([A-Z]+)"', (served or {}).get("table", ""))
    c_rows = re.findall(r'<tr data-iso="([A-Z]+)"', client)
    names = [py_names[i] for i in t]
    ref = [i for _n, i in sorted(zip(names, t))][:5]                         # Python's order of the tie
    served_orders.append((t, s_rows))
    results.append(ok(served is not None and served["table"] == client and s_rows == c_rows == ref,
                      "tie of %s: the served table is the drawn one, row for row (%s)"
                      % ("/".join(names), " ".join(s_rows) if s_rows == c_rows else (s_rows, c_rows))))

# What the old comparator would have drawn: localeCompare over the map data's names.
prog = "const ties = %s;\nprint(JSON.stringify(ties.map((t) => t.slice().sort((a, b) => a[1].localeCompare(b[1]))" \
       ".slice(0, 5).map((x) => x[0]))));" % json.dumps(
           [[[i, FIX["climate"][i]["name"]] for i in t] for t in TIES], ensure_ascii=False)
old, eng = run_js(prog)
results.append(ok(old is not None and all(o != s for o, (_t, s) in zip(old, served_orders)),
                  "the old tie-break would have drawn other rows: %s, served now %s"
                  % (old, [s for _t, s in served_orders])))

# --- 4. the newsletter: build_variant on the frozen digest fixtures ----------------------
def cheap_scorer(real, tie):
    """tied_scorer, the tied countries also cheap and warm enough for
    /cheapest's rule (prices at most MAX_PCT% of the US, weather MIN_WX+), so
    the whole tie is on the list."""
    tied = tied_scorer(real, tie)

    def score(iso, *a, **k):
        s = tied(iso, *a, **k)
        return dict(s, pl=RC.MAX_PCT / 200, wx=max(s.get("wx") or 0, RC.MIN_WX + 10)) if s and iso in tie else s
    return score


ctx = RC.context(FIX["advisories"], None, None, FIX["rates"], FIX["ppp"], FIX["climate"], {},
                 FIX["flights"], FIX["fv"])
for t, s_rows in served_orders:
    rows = [s["iso"] for s in RC.rank_month(ctx, 2, score=cheap_scorer(real_score, set(t)))]
    ref = [i for _n, i in sorted((py_names[i], i) for i in t)]
    results.append(ok(rows[:len(t)] == ref and rows[:5] == s_rows,
                      "/cheapest (rank_month) lists the whole tie first, the drawn five first: %s" % rows[:len(t)]))

import digest_snapshot as D  # noqa: E402  (replaces the fxtracker modules with a frozen copy)
npicks, _nl, dv = D.install(ROOT)
shared = npicks.gather(3)
real_n = npicks._score
for t, s_rows in served_orders:
    npicks._score = tied_scorer(real_n, set(t))
    try:
        data = npicks.build_variant(dict(shared, popular=set(t)), dv.VARIANTS["USD"])
    finally:
        npicks._score = real_n
    got = [s["iso"] for s in data["picks"]]
    results.append(ok(got == s_rows, "the newsletter's picks for that tie are the served and drawn rows: %s" % got))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

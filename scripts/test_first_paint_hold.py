"""Top Picks' first paint over the skeleton (public/app.js holdFirstPicks),
with app.js itself run under jsc (scripts/appjs_harness.js) on the parity
fixture, as scripts/test_home_picks.py runs it.

    /usr/bin/python3 scripts/test_first_paint_hold.py

A view the served rows aren't for (a story or shared link, a non-US or a
returning visitor) shows index.html's skeleton, and its rows used to be
drawn as soon as the rates were in and then redrawn as popularity, the fares
and the fare curves landed: the top 5 reshuffled under the reader. What it
holds the code to:
  * while the skeleton is on screen, renderValue leaves #topCards and the
    note alone until activities, popularity, the fares and a first answer
    from the fare curves are all in;
  * any answer from the curves counts (a request that failed or is still
    filling), not only a finished fill;
  * no fares on the server: nothing to wait for past the fares request;
  * the wait is capped (FIRST_HOLD_MS from the first try);
  * the visitor's own doing ends it at once (the capture listeners set done);
  * only the first paint: once rows are drawn nothing is held again;
  * served rows on screen: their own hold (holdServedPicks) applies, not this.
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
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

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; worldGeo = FIX.world;
advisories = FIX.advisories;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
loaded.value = true; drawMap = function () {};
$("pickCount").value = "5"; $("safeFloor").value = "b"; $("valueMonth").value = "12";
const top = $("topCards"), note = $("picksNote");
// The skeleton is on screen while #topCards still holds it.
top.querySelector = function (q) { return /skeleton/.test(q) && top.innerHTML === "SKELETON" ? {} : null; };
const out = {};
const fresh = () => {
  top.innerHTML = "SKELETON"; note.innerHTML = "NOTE";
  _firstHold.t0 = 0; _firstHold.done = false; _firstHold.tick = 0;
  servedPicks = null; servedOnScreen = false;
  activities = null; popularitySettled = false; valueFlightsSettled = false;
  flightsData = null; flightValue = null; _fvAsk = null;
};
const drawn = () => top.innerHTML !== "SKELETON";
const snap = () => [drawn(), note.innerHTML === "NOTE"];

// 1. Each piece missing in turn holds; all in draws.
fresh();
const steps = [];
renderValue(); steps.push(snap());                                    // nothing yet
activities = FIX.activities; renderValue(); steps.push(snap());
popularitySettled = true; renderValue(); steps.push(snap());
valueFlightsSettled = true; flightsData = FIX.flights; renderValue(); steps.push(snap());   // curves not answered
flightValue = FIX.fv; renderValue(); steps.push(snap());               // curves in: drawn
out.steps = steps;
// 2. Once drawn, never held again, even with the data flags back off.
popularitySettled = false; flightValue = null;
top.innerHTML = "SKELETON";   // (a skeleton back on screen would not re-arm it)
renderValue(); out.again = drawn();

// 3. Any answer from the curves: the request for this origin done, nothing kept.
fresh(); activities = FIX.activities; popularitySettled = true; valueFlightsSettled = true; flightsData = FIX.flights;
_fvAsk = { origin: "US", done: false }; renderValue(); out.askOpen = drawn();
_fvAsk.done = true; renderValue(); out.askDone = drawn();
// ...for another origin it is no answer.
fresh(); activities = FIX.activities; popularitySettled = true; valueFlightsSettled = true; flightsData = FIX.flights;
_fvAsk = { origin: "DE", done: true }; renderValue(); out.otherOrigin = drawn();

// 4. No fares on the server: the fares request is all there is to wait for.
fresh(); activities = FIX.activities; popularitySettled = true; flightsData = { configured: false };
renderValue(); out.noFaresOpen = drawn();
valueFlightsSettled = true; renderValue(); out.noFares = drawn();

// 5. The cap: past FIRST_HOLD_MS from the first try, drawn with what there is.
fresh(); renderValue(); out.capHeld = drawn();
_firstHold.t0 = Date.now() - FIRST_HOLD_MS - 1; renderValue(); out.capped = drawn();

// 6. The visitor's own doing (the capture listeners set done): drawn at once.
fresh(); renderValue(); _firstHold.done = true; renderValue(); out.visitor = drawn();

// 7. Served rows on screen: not this hold's (holdServedPicks keeps them).
fresh(); top.innerHTML = "SERVED"; servedPicks = flexWindow().join(","); servedOnScreen = true;
$("valueMonth").value = "0";
renderValue(); out.served = [top.innerHTML, _firstHold.done];
activities = FIX.activities; popularitySettled = true; valueFlightsSettled = true;
renderValue(); out.servedDone = [top.innerHTML.slice(0, 6), _firstHold.done];
print(JSON.stringify(out));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    o = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    print(r.stdout[-500:], r.stderr[-1500:])
    o = None

results = []
if o is None:
    results.append(ok(False, "the jsc run printed no result"))
else:
    held = [False, True]
    results.append(ok(o["steps"][:4] == [held] * 4,
                      "the skeleton and the note stay while activities, popularity, the fares or the fare curves "
                      "are out %s" % o["steps"]))
    results.append(ok(o["steps"][4] == [True, False], "drawn (rows and note) once all four are in %s" % o["steps"][4]))
    results.append(ok(o["again"] is True, "only the first paint: nothing is held after rows are drawn"))
    results.append(ok(o["askOpen"] is False and o["askDone"] is True,
                      "any answer from the curves counts: the request done, whatever it brought"))
    results.append(ok(o["otherOrigin"] is False, "an answer for another origin is no answer"))
    results.append(ok(o["noFaresOpen"] is False and o["noFares"] is True,
                      "no fares on the server: waits for the fares request only"))
    results.append(ok(o["capHeld"] is False and o["capped"] is True, "capped at FIRST_HOLD_MS from the first try"))
    results.append(ok(o["visitor"] is True, "the visitor's own doing ends the hold at once"))
    results.append(ok(o["served"] == ["SERVED", False] and o["servedDone"] == ["<table", True],
                      "served rows on screen keep their own hold, and this one stands down when it ends %s %s"
                      % (o["served"], o["servedDone"])))

# The capture listeners that end it on the visitor's doing, trusted events only.
results.append(ok(all(('"%s"' % ev) in APP.split("const FIRST_HOLD_MS", 1)[1].split("function renderValue", 1)[0]
                      for ev in ("click", "input", "change", "keydown"))
                  and "e.isTrusted" in APP.split("const FIRST_HOLD_MS", 1)[1].split("function renderValue", 1)[0],
                  "a trusted click, key or input (capture phase) ends the hold"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

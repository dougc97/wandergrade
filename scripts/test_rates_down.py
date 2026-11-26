"""Top Picks when the live exchange rates fail (public/app.js loadRates,
ratesSettled, renderValue, renderRatesDown, ratesLanded), with app.js itself
run under jsc (scripts/appjs_harness.js) on the parity fixture, as
scripts/test_first_paint_hold.py runs it.

    /usr/bin/python3 scripts/test_rates_down.py

Without the USD rates (lastRates) only the places priced in US dollars could
be graded (rateForCurrency answers 1 for USD alone; PPP_UNIT's PS and LR), and
Top Picks used to show that handful, a dozen countries, as the ranking:
Puerto Rico, Panama and the United States as the Top 5, 13 of 161 countries on
the map. What it holds the code to:
  * a failed USD fetch is tried again quietly, RATES_RETRY_MS apart (2 s, 6 s,
    then 30 s, past the server's 30 s memory of an upstream failure), with no
    error toast and the Data table's Loading row kept until RATES_QUIET retries
    have failed; then the toast once;
  * while those run the first paint stays (the skeleton or the served rows),
    unless the visitor asks for a change; a retry that lands draws the list
    with no notice ever shown;
  * after them Top Picks shows one line where the list goes (Live exchange
    rates didn't load. + Try again + an ⓘ), never a partial list: the gems
    fold and the full ranking say it in one line, the value map isn't drawn
    ("Couldn't load", no key), the weather map (no rates needed) is;
  * the rates landing later (the 30 s try or Try again) draw everything that
    waited, byte-identical to a load whose rates came at once;
  * Try again runs the pending try now: failing, it puts that try back (a
    press can't cancel the 30 s one), says so (the toast, each press) and
    leaves the same line with its button usable again (aria-disabled while
    it runs, never disabled: the keyboard focus stays on it); a press before
    the quiet retries are over says the failure then, once, and lets the
    Data table's Loading row go;
  * the rates landing through any request draw everything that waited: a
    request re-sent for a currency the reader switched to meanwhile, or a
    newer one the switch sent, included;
  * the value map's 📸 keeps its room unseen while that map isn't drawn
    (data-mapout), and is back with the weather map or the rates;
  * served rows in a hidden Top Picks when the retries fail: their hold
    ends (no 250 ms redraw loop), the rows stay until the tab shows;
  * Top Picks hidden when they fail (no height to hold): left as it is,
    drawn when it shows;
  * rates in at once: no retry, nothing re-drawn (the old path exactly);
  * another home currency's own set failing, the USD set in: as before (the
    toast at once, no retry: the list ranks, only the currency marks wait).
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
ppp = FIX.ppp; climate = FIX.climate; worldGeo = FIX.world; advisories = FIX.advisories;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
loaded.value = true;
const maps = []; drawMap = function (id, fn, label) { maps.push(label); };
$("pickCount").value = "5"; $("safeFloor").value = "b"; $("valueMonth").value = "12";
const top = $("topCards"), note = $("picksNote"), tv = $("tab-value");
// The skeleton is on screen while #topCards still holds it; the notice is
// found while its markup is there.
top.querySelector = function (q) {
  if (/skeleton/.test(q)) return top.innerHTML === "SKELETON" ? {} : null;
  if (/ratesdown/.test(q)) return /class="ratesdown"/.test(top.innerHTML) ? { style: { minHeight: "" } } : null;
  return null;
};
// Timers recorded, fired by hand; the rates' retries told from the rest.
const timers = [];
setTimeout = function (f, ms) { timers.push({ f: f, ms: ms, rates: String(f).indexOf('loadRates("auto")') >= 0 }); return timers.length; };
clearTimeout = function (id) { if (id && timers[id - 1]) timers[id - 1].cleared = true; };
const ratesTimers = () => timers.filter((t) => t.rates && !t.cleared && !t.fired);
const fire = () => { const t = ratesTimers()[0]; t.fired = true; t.f(); drainMicrotasks(); return t.ms; };
// Each /api/rates request answers the next of `answers` ("ok" or "fail").
// "hold" keeps the request in flight until release(i, "ok" | "fail").
let answers = [];
const asked = [], heldReq = [];
const ratesFor = (url) => { const base = (url.split("base=")[1] || "USD");
  return JSON.parse(JSON.stringify(base === "USD" ? FIX.rates : Object.assign({}, FIX.rates, { base: base }))); };
getJSON = function (url) {
  asked.push(url);
  const a = answers.shift() || "fail";
  if (a === "hold") return new Promise((res, rej) => heldReq.push({ url: url, res: res, rej: rej }));
  if (a !== "ok") return Promise.reject(new Error("HTTP 500"));
  return Promise.resolve(ratesFor(url));
};
const release = (i, a) => { const h = heldReq[i]; if (a === "ok") h.res(ratesFor(h.url)); else h.rej(new Error("HTTP 500")); drainMicrotasks(); };
const said = [], drops = [];
status = function (m, k) { said.push([m, k || ""]); };
const _drop = dropLoadingRow; dropLoadingRow = function (id) { drops.push(id); };
let landed = 0; const _landed = ratesLanded; ratesLanded = function () { landed++; return _landed(); };
const errs = () => said.filter((s) => /^Could not load rates/.test(s[0])).length;

const fresh = () => {
  lastRates = null; dataRates = null; homeRates = null; homeBase = "USD";
  for (const k in _baseRatesCache) delete _baseRatesCache[k];
  ratesDown = false; _ratesTry = 0; _ratesRetryT = 0; _ratesOwed = false; _ratesSaid = false;
  timers.length = 0; said.length = 0; drops.length = 0; maps.length = 0; asked.length = 0; landed = 0; heldReq.length = 0;
  $("ratesRetry").removeAttribute("aria-disabled"); tv.removeAttribute("data-mapout"); tv.hidden = false;
  $("homeCur").innerHTML = ""; homeManual = false; sharedOriginView = null;
  top.innerHTML = "SKELETON"; note.innerHTML = "NOTE";
  $("valueRows").innerHTML = "LOADING"; $("gemRows").innerHTML = ""; $("valueMap").textContent = "Loading…";
  tv.removeAttribute("data-ratesdown"); $("showMore").hidden = true;
  _firstHold.t0 = 0; _firstHold.done = false; _firstHold.tick = 0;
  servedPicks = null; servedOnScreen = false; lastPicks = []; valueMapMode = "score";
  activities = FIX.activities; popularitySettled = true; valueFlightsSettled = true;
  flightsData = FIX.flights; flightValue = FIX.fv; _fvAsk = null;
  window.event = undefined;
};
// (The value map is drawn by drawMap, stubbed here: whether it was drawn is in maps.)
const view = () => ({ top: top.innerHTML, note: note.innerHTML, full: $("valueRows").innerHTML,
                      gems: $("gemRows").innerHTML, picks: lastPicks.length });
const out = {};

// 0. The reference: the rates in at once, drawn by init's renderValue.
fresh(); answers = ["ok"]; loadRates(); drainMicrotasks();
out.okTimers = ratesTimers().length; out.okLanded = landed; out.okSaid = said.map((s) => s[0]);
renderValue(); out.ref = view(); out.refMaps = maps.slice(); out.refMapout = tv.hasAttribute("data-mapout");

// 1. Down at boot: quiet retries, first paint held, then the notice, then the late list.
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks();
out.boot = { errs: errs(), drops: drops.length, timers: ratesTimers().map((t) => t.ms), down: ratesDown };
renderValue(); out.bootHeld = view(); out.bootMaps = maps.length;
answers = ["fail"]; out.t1 = fire();
out.retry1 = { errs: errs(), drops: drops.length, timers: ratesTimers().map((t) => t.ms), down: ratesDown, top: top.innerHTML };
answers = ["fail"]; out.t2 = fire();
out.retry2 = { errs: errs(), drops: drops.length, timers: ratesTimers().map((t) => t.ms), down: ratesDown,
               attr: tv.hasAttribute("data-ratesdown"), showMore: $("showMore").hidden, maps: maps.slice() };
out.notice = view(); out.noticeMap = $("valueMap").textContent; out.noticeMapout = tv.hasAttribute("data-mapout"); maps.length = 0;
answers = ["ok"]; out.t3 = fire();
out.late = view(); out.lateMaps = maps.slice(); out.lateLanded = landed; out.lateAttr = tv.hasAttribute("data-ratesdown"); out.lateDown = ratesDown;
out.lateTimers = ratesTimers().length; out.lateErrs = errs(); out.lateMapout = tv.hasAttribute("data-mapout");

// 2. Transient: the first retry lands, no notice ever.
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks(); renderValue();
out.trHeld = top.innerHTML;
answers = ["ok"]; fire();
out.tr = view(); out.trErrs = errs(); out.trTimers = ratesTimers().length;

// 3. Served rows during the retries: kept; then the notice in their place.
fresh(); top.innerHTML = "SERVED"; servedPicks = flexWindow().join(","); servedOnScreen = true;
answers = ["fail"]; loadRates(); drainMicrotasks(); renderValue(); out.srvHeld = top.innerHTML;
answers = ["fail"]; fire(); renderValue(); out.srvHeld2 = top.innerHTML;
answers = ["fail"]; fire(); out.srvDown = { top: /class="ratesdown"/.test(top.innerHTML), servedPicks: servedPicks, onScreen: servedOnScreen };

// 4. The visitor's own change during the retries: said at once (it can't be drawn).
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks();
window.event = { isTrusted: true, type: "change", target: { closest: () => null } };
renderValue(); window.event = undefined;
out.visitor = /class="ratesdown"/.test(top.innerHTML) && !/<table/.test(top.innerHTML);
answers = ["ok"]; fire(); out.visitorLate = top.innerHTML === out.ref.top;
// ...but opening the tab (a click outside Top Picks' controls) is no change: held.
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks();
window.event = { isTrusted: true, type: "click", target: { closest: () => null } };
renderValue(); window.event = undefined;
out.tabClick = top.innerHTML;

// 5. Try again: the pending try now; failing, that try put back, said, the
// same line with its button usable again; landing, the list.
fresh(); answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire(); fire();
out.beforeTry = ratesTimers().map((t) => t.ms);
const errsBefore = errs(), noticeBefore = top.innerHTML;
answers = ["hold"]; retryRates();
const askedOnce = asked.length;
out.tryBusy = { aria: $("ratesRetry").getAttribute("aria-disabled"), timers: ratesTimers().length };
retryRates(); out.tryBusy.second = asked.length - askedOnce;   // a press while it runs: ignored
release(0, "fail");
out.tryFail = { timers: ratesTimers().map((t) => t.ms), errs: errs() - errsBefore, same: top.innerHTML === noticeBefore,
                aria: $("ratesRetry").getAttribute("aria-disabled"), down: ratesDown };
answers = ["fail"]; retryRates(); drainMicrotasks(); out.tryFail2 = errs() - errsBefore;
answers = ["ok"]; out.tryLate = fire(); out.tryLateTop = top.innerHTML === out.ref.top && !ratesDown && landed === 1;
fresh(); answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire(); fire();
answers = ["ok"]; retryRates(); drainMicrotasks();
out.tryOk = top.innerHTML === out.ref.top && !ratesDown && ratesTimers().length === 0;

// 5c. Try again before the quiet retries are over (the visitor's own change
// put the notice up at once): failing, the failure is said then, once, the
// Loading row let go, and the quiet tries go on as planned.
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks();
window.event = { isTrusted: true, type: "change", target: { closest: () => null } };
renderValue(); window.event = undefined;
answers = ["fail"]; retryRates(); drainMicrotasks();
out.early = { errs: errs(), drops: drops.length, timers: ratesTimers().map((t) => t.ms), notice: /class="ratesdown"/.test(top.innerHTML),
              aria: $("ratesRetry").getAttribute("aria-disabled") };
answers = ["fail"]; fire(); answers = ["fail"]; fire();
out.early2 = { errs: errs(), drops: drops.length, timers: ratesTimers().map((t) => t.ms), down: ratesDown };
answers = ["ok"]; fire(); out.earlyLate = top.innerHTML === out.ref.top && landed === 1;

// 5d. The currency switched while a request is in flight (the request is
// re-sent for the new one, as itself): the landing still draws everything.
fresh(); answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire(); fire();
answers = ["hold"]; retryRates();
answers = ["ok"]; setHomeCur("EUR", true); drainMicrotasks();
release(0, "ok");
out.switch1 = { notice: /class="ratesdown"/.test(top.innerHTML), table: /^<table/.test(top.innerHTML), picks: lastPicks.length,
                attr: tv.hasAttribute("data-ratesdown"), down: ratesDown, landed: landed, homeCur: /<option/.test($("homeCur").innerHTML),
                timers: ratesTimers().length, base: homeBase, data: dataRates && dataRates.base };
// ...and a quiet retry in flight, the reader doing nothing but the geo seed's switch.
fresh(); answers = ["fail"]; loadRates(); drainMicrotasks(); renderValue();
answers = ["hold"]; fire();
answers = ["ok"]; setHomeCur("EUR", true); drainMicrotasks();
release(0, "ok");
out.switch2 = { table: /^<table/.test(top.innerHTML), landed: landed, homeCur: /<option/.test($("homeCur").innerHTML), timers: ratesTimers().length };
// ...and the switch sending a newer request of its own (the USD set already
// in, the home currency's still on its way): that one draws the landing.
fresh(); homeBase = "EUR"; answers = ["fail"]; loadRates(); drainMicrotasks(); renderValue(); answers = ["fail"]; fire(); answers = ["fail"]; fire();
answers = ["ok", "hold"]; retryRates(); drainMicrotasks();
answers = ["ok"]; setHomeCur("GBP", true); drainMicrotasks();
release(0, "ok");
out.switch3 = { table: /^<table/.test(top.innerHTML), attr: tv.hasAttribute("data-ratesdown"), down: ratesDown, landed: landed,
                homeCur: /<option/.test($("homeCur").innerHTML) };
homeBase = "USD";

// 5b. Top Picks hidden (the reader went to a guide) when the retries fail:
// left as it is, drawn when it shows (activateTab's renderValue).
fresh(); answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire();
tv.hidden = true; fire(); out.hiddenTab = top.innerHTML;
tv.hidden = false; renderValue(); out.shownTab = /class="ratesdown"/.test(top.innerHTML);
// ...served rows there: their hold (and its 250 ms tick) ends; the rows stay till the tab shows.
fresh(); top.innerHTML = "SERVED"; servedPicks = flexWindow().join(","); servedOnScreen = true;
answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire();
tv.hidden = true; fire();
out.hiddenServed = { top: top.innerHTML, servedPicks: servedPicks, onScreen: servedOnScreen };
tv.hidden = false; renderValue(); out.hiddenServedShown = /class="ratesdown"/.test(top.innerHTML);

// 6. The weather map needs no rates: drawn; the value map is not.
fresh(); answers = ["fail", "fail", "fail"]; loadRates(); drainMicrotasks(); renderValue(); fire(); fire();
out.valueMap = { maps: maps.slice(), text: $("valueMap").textContent };
maps.length = 0; valueMapMode = "weather"; renderValue();
out.weatherMap = { maps: maps.slice(), notice: /class="ratesdown"/.test(top.innerHTML), mapout: tv.hasAttribute("data-mapout") };
valueMapMode = "score"; renderValue(); out.scoreAgainMapout = tv.hasAttribute("data-mapout");

// 7. Another home currency (a reader from Germany): its own set fails, the
// USD set lands: as before.
localStorage.setItem("fx_origin", "DE");
fresh(); homeBase = "EUR"; answers = ["ok", "fail"]; loadRates(); drainMicrotasks();
out.eur = { last: !!lastRates, errs: errs(), drops: drops.slice(), timers: ratesTimers().length, landed: landed, asked: asked.slice() };
// ...and both failing: the quiet retries ask for both again.
fresh(); homeBase = "EUR"; answers = ["fail"]; loadRates(); drainMicrotasks();
answers = ["ok", "ok"]; fire();
out.eurLate = { last: !!lastRates, asked: asked.slice(), landed: landed, data: dataRates && dataRates.base };
localStorage.removeItem("fx_origin");
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
NOTICE = "Live exchange rates didn&#39;t load."
if o is None:
    results.append(ok(False, "the jsc run printed no result"))
else:
    ref = o["ref"]
    results.append(ok(ref["top"].startswith("<table") and ref["picks"] == 5 and "Best value destinations" in o["refMaps"]
                      and not o["refMapout"], "reference: the rates in at once draw the Top 5 and the value map (its 📸 shown)"))
    results.append(ok(o["okTimers"] == 0 and o["okLanded"] == 0 and o["okSaid"] == ["Fetching rates…", ""],
                      "rates in at once: no retry, nothing re-drawn, the old status path %s" % o["okSaid"]))

    b = o["boot"]
    results.append(ok(b == {"errs": 0, "drops": 0, "timers": [2000], "down": False},
                      "a failed first fetch: no toast, the Loading row kept, a quiet retry in 2 s %s" % b))
    results.append(ok(o["bootHeld"]["top"] == "SKELETON" and o["bootHeld"]["note"] == "NOTE"
                      and o["bootHeld"]["full"] == "LOADING" and o["bootMaps"] == 0,
                      "during the retries the skeleton, the note and the full ranking stay; no map drawn"))
    r1 = o["retry1"]
    results.append(ok(o["t1"] == 2000 and r1["errs"] == 0 and r1["timers"] == [6000] and not r1["down"]
                      and r1["top"] == "SKELETON", "the first retry fails quietly too: the next in 6 s %s" % r1))
    r2 = o["retry2"]
    results.append(ok(o["t2"] == 6000 and r2["errs"] == 1 and r2["drops"] == 1 and r2["down"] and r2["timers"] == [30000],
                      "the second fails: the toast and the Loading row's end once, one last try in 30 s %s" % r2))
    n = o["notice"]
    results.append(ok(NOTICE in n["top"] and 'id="ratesRetry"' in n["top"] and "Try again" in n["top"]
                      and "data-tip=" in n["top"] and "<table" not in n["top"] and n["picks"] == 0,
                      "then one line where the list goes, with Try again and an ⓘ, and no rows at all"))
    results.append(ok(NOTICE in n["full"] and "<td colspan=\"7\">" in n["full"] and n["full"].count("<tr>") == 1
                      and NOTICE in n["gems"], "the full ranking and the gems fold say it in one line each"))
    results.append(ok(r2["attr"] and r2["showMore"] and "Best value destinations" not in r2["maps"]
                      and o["noticeMap"] == "Couldn't load" and o["noticeMapout"],
                      "the note and share buttons hidden (data-ratesdown, data-mapout), no Show more, the value map not drawn"))
    results.append(ok(o["t3"] == 30000 and o["lateLanded"] == 1 and not o["lateDown"] and not o["lateAttr"]
                      and o["lateTimers"] == 0 and o["lateErrs"] == 1 and "Best value destinations" in o["lateMaps"]
                      and not o["lateMapout"],
                      "the 30 s try lands: drawn once (the value map too), nothing left armed, no second toast"))
    late = o["late"]
    results.append(ok(late == ref, "...byte-identical to a load whose rates came at once%s"
                      % ("" if late == ref else " %s" % {k: (late[k][:80], ref[k][:80]) for k in ref if late[k] != ref[k]})))

    results.append(ok(o["trHeld"] == "SKELETON" and o["tr"] == ref and o["trErrs"] == 0 and o["trTimers"] == 0,
                      "a transient failure: the skeleton held, then the list exactly as with the rates at once, no toast"))
    s = o["srvDown"]
    results.append(ok(o["srvHeld"] == "SERVED" and o["srvHeld2"] == "SERVED" and s["top"]
                      and s["servedPicks"] is None and not s["onScreen"],
                      "served rows stay through the retries, then give way to the notice %s" % s))
    results.append(ok(o["visitor"] and o["visitorLate"],
                      "the visitor's own change during the retries shows the notice at once, the list when they land"))
    results.append(ok(o["tabClick"] == "SKELETON", "a click that changes no ranking (opening the tab) keeps the first paint"))
    tb, tf = o["tryBusy"], o["tryFail"]
    results.append(ok(o["beforeTry"] == [30000] and tb == {"aria": "true", "timers": 0, "second": 0},
                      "Try again runs the pending 30 s try now; aria-disabled while it runs, a second press ignored %s" % tb))
    results.append(ok(tf == {"timers": [30000], "errs": 1, "same": True, "aria": None, "down": True},
                      "Try again failing: the 30 s try put back, the failure said, the same line with its button usable %s" % tf))
    results.append(ok(o["tryFail2"] == 2, "each failed press says so (%s toasts for 2 presses)" % o["tryFail2"]))
    results.append(ok(o["tryLate"] == 30000 and o["tryLateTop"],
                      "the put-back 30 s try lands after a failed press: the list, drawn once"))
    results.append(ok(o["tryOk"], "Try again landing: the list, as with the rates at once, nothing left armed"))
    ea, e2 = o["early"], o["early2"]
    results.append(ok(ea == {"errs": 1, "drops": 1, "timers": [2000], "notice": True, "aria": None},
                      "Try again before the quiet retries are over, failing: said once, the Loading row let go, the 2 s try put back %s" % ea))
    results.append(ok(e2 == {"errs": 1, "drops": 1, "timers": [30000], "down": True} and o["earlyLate"],
                      "...the quiet tries then go on as planned, saying nothing twice, and the last one draws the list %s" % e2))
    w1, w2, w3 = o["switch1"], o["switch2"], o["switch3"]
    results.append(ok(w1 == {"notice": False, "table": True, "picks": 5, "attr": False, "down": False, "landed": 1,
                             "homeCur": True, "timers": 0, "base": "EUR", "data": "EUR"},
                      "the currency switched while Try again runs: the landing draws the list, the In picker, the note %s" % w1))
    results.append(ok(w2 == {"table": True, "landed": 1, "homeCur": True, "timers": 0},
                      "the geo seed's switch while a quiet retry runs: the same %s" % w2))
    results.append(ok(w3 == {"table": True, "attr": False, "down": False, "landed": 1, "homeCur": True},
                      "a newer request the switch sent itself draws the landing %s" % w3))
    results.append(ok(o["hiddenTab"] == "SKELETON" and o["shownTab"],
                      "Top Picks hidden when the retries fail: left alone, the notice drawn when it shows"))
    hs = o["hiddenServed"]
    results.append(ok(hs == {"top": "SERVED", "servedPicks": None, "onScreen": True} and o["hiddenServedShown"],
                      "served rows hidden when the retries fail: their hold ends, the rows stay, the notice when it shows %s" % hs))
    results.append(ok(o["valueMap"]["maps"] == [] and o["valueMap"]["text"] == "Couldn't load",
                      "the value map is not drawn without the rates %s" % o["valueMap"]))
    results.append(ok(o["weatherMap"]["maps"] == ["Weather comfort by month"] and o["weatherMap"]["notice"]
                      and not o["weatherMap"]["mapout"] and o["scoreAgainMapout"],
                      "the weather map (no rates needed) is drawn with its 📸; its tables still say the rates are out"))
    e = o["eur"]
    results.append(ok(e["last"] and e["errs"] == 1 and e["drops"] == ["rows"] and e["timers"] == 0 and e["landed"] == 0
                      and e["asked"] == ["/api/rates", "/api/rates?base=EUR"],
                      "a home currency's own set failing with the USD set in: the toast at once, no retry %s" % e))
    el = o["eurLate"]
    results.append(ok(el["last"] and el["landed"] == 1 and el["data"] == "EUR"
                      and el["asked"] == ["/api/rates", "/api/rates", "/api/rates?base=EUR"],
                      "both failing: the retry asks for both, and lands %s" % el))

# The retry spacing and the notice's words, as the report and the ⓘ state them.
results.append(ok("const RATES_RETRY_MS = [2000, 6000, 30000], RATES_QUIET = 2;" in APP,
                  "retries 2 s, 6 s, 30 s; the notice after the first two"))
results.append(ok('const RATES_DOWN = "Live exchange rates didn\'t load.";' in APP, "the notice's words"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

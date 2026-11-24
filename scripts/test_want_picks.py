"""Top Picks ranking the ★ want-to-go list (Been-to: "★ My want-to-go",
?vb=want), with public/app.js itself run under jsc (scripts/appjs_harness.js)
on the parity fixture, as scripts/test_home_picks.py runs it.

    /usr/bin/python3 scripts/test_want_picks.py

What it holds the code to:
  * the rows are the wishlist's countries, in the ranking's own order, ✓ been
    ones included, with England/Scotland/Wales ranked as the United Kingdom;
  * no popular/hidden-gems split: the gems fold is hidden;
  * the safety floor still applies, and every ★ country that isn't ranked is
    counted in the note, its reason in the tip (Level 4, a filter, no data);
  * an empty ★ list says so; a link's vb=want opens it without saving it,
    and the served rows give way to it;
  * the ★ list isn't in a link, so a share link leaves vb out (the recipient
    would rank their own, mostly empty, list), and the address bar keeps it
    only for a visit a link opened it on (the saved choice needs none);
  * "Somewhere new" and "Include visited" rank as before.
"""
import json, os, re, subprocess, sys, tempfile

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

# AF is Level 4 in the fixture, CO Level 3; FO has no rating of its own;
# GB-SCT ranks as GB.
WISH = ["JP", "GB-SCT", "AF", "FO", "TH", "PT", "MX", "IS", "CO"]

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; worldGeo = FIX.world; activities = FIX.activities;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
popularitySettled = true; valueFlightsSettled = true;
loaded.value = true; drawMap = function () {};
$("pickCount").value = "20"; $("safeFloor").value = "b"; $("valueMonth").value = "12";
const top = $("topCards"), note = $("picksNote");
const rows = () => (top.innerHTML.match(/<tr data-iso="([^"]+)"/g) || []).map((x) => x.slice(14, -1));
document.querySelector("#tabs button.active").dataset.tab = "value";   // currentTab()
const out = {};
localStorage.setItem("fx_wishlist", JSON.stringify(WISH));
localStorage.setItem("fx_visited", JSON.stringify(["TH"]));
wishlist = null; visited = null;
// The ranking itself, unfiltered, for the order.
$("beenFilter").value = "show"; $("safeFloor").value = "any"; renderValue();
out.full = rankedOrder();
function rankedOrder() {
  const advMap = advisoryByIso(), fares = buildFareContext(), A = plAnchor(originIso());
  const sc = [];
  for (const iso in CUR_BY_ISO) { const s = valueScores(iso, 12, advMap, fares, A.pl); if (s) sc.push(s); }
  return sc.sort(rankValue).map((s) => s.iso);
}
$("safeFloor").value = "b";
$("beenFilter").value = "want"; renderValue();
out.want = { rows: rows(), note: note.innerHTML, gemsHidden: $("gemsBox").hidden, url: buildShareURL(false),
             share: buildShareURL(true) };
localStorage.setItem("wg_showvisited", "want");
out.wantSavedUrl = buildShareURL(false);
localStorage.removeItem("wg_showvisited");
$("safeFloor").value = "any"; renderValue();
out.wantAny = { rows: rows(), note: note.innerHTML };
$("safeFloor").value = "b";
$("beenFilter").value = "hide"; renderValue();
out.hide = { rows: rows(), note: note.innerHTML, url: buildShareURL(false) };
$("beenFilter").value = "show"; renderValue();
out.show = { rows: rows() };
localStorage.setItem("fx_wishlist", "[]"); wishlist = null;
$("beenFilter").value = "want"; renderValue();
out.empty = top.innerHTML;
// The served rows are for the default view only.
localStorage.setItem("fx_visited", "[]"); visited = null;
$("pickCount").value = "5"; $("valueMonth").value = "0";
servedPicks = flexWindow().join(","); servedOnScreen = true;
out.servedWant = holdServedPicks(true, flexWindow());
print(JSON.stringify(out));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n"
                                          + DRIVER.replace("FIX_PATH", json.dumps(fp)).replace("WISH", json.dumps(WISH)))
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
    adv = {it["iso"]: it["level"] for it in FIX["advisories"]["items"] if it.get("iso")}
    mine = {"JP", "GB", "TH", "PT", "MX", "IS", "CO"}
    rankable = [i for i in o["full"] if i in mine and adv.get(i, 0) in (1, 2)]
    w = o["want"]
    results.append(ok(w["rows"] == rankable,
                      "the ★ list in the ranking's order, ✓ been included, Scotland as the UK: %s (want %s)"
                      % (w["rows"], rankable)))
    results.append(ok(w["gemsHidden"] is True, "no hidden-gems split on the ★ list"))
    tip = re.search(r'class="muted wantmiss" data-tip="([^"]*)"', w["note"])
    lines = tip.group(1).split("\n") if tip else []
    results.append(ok(w["note"].startswith("★ Your want-to-go list, ranked by value") and tip
                      and ("· %d not ranked ⓘ" % len(lines)) in w["note"]
                      and any(l.startswith("Afghanistan: Level 4") for l in lines)
                      and any(l.startswith("Faroe") for l in lines),
                      "the note names the list and counts what it can't rank, each reason in the tip: %s" % lines))
    results.append(ok(any(l == "Colombia: below your safety filter" for l in lines) and len(lines) == 3
                      and o["wantAny"]["rows"] == [i for i in o["full"] if i in mine and adv.get(i, 0) != 4]
                      and "not ranked" in o["wantAny"]["note"],
                      "the safety floor still applies to the ★ list, and what it drops is counted (Colombia, "
                      "Level 3; ranked at 'Any level')"))
    results.append(ok("vb=want" in w["url"] and "vb=" not in o["hide"]["url"],
                      "the address bar carries vb=want for a visit a link (not the saved choice) opened it on"))
    results.append(ok("vb=" not in w["share"] and "vb=" not in o["wantSavedUrl"],
                      "a share link leaves vb out, and so does the bar when want-to-go is the saved choice: %s / %s"
                      % (w["share"], o["wantSavedUrl"])))
    results.append(ok("hint" in o["empty"] and "Wander List" in o["empty"] and 'id=\'wantGo\'' in o["empty"],
                      "an empty ★ list says where the stars come from"))
    results.append(ok("TH" not in o["hide"]["rows"] and "you've been to hidden" in o["hide"]["note"]
                      and "TH" in o["show"]["rows"],
                      "Somewhere new still hides ✓ been countries and Include visited still shows them"))
    results.append(ok(o["servedWant"] is False, "the served rows give way to the ★ list"))

# A link's vb=want opens the ★ list for the visit only (not saved), and the
# select offers it.
post = APP.split("async function postApplyShared", 1)[1].split("\n}\n", 1)[0]
INDEX = open(P("public", "index.html"), encoding="utf-8").read()
results.append(ok('sharedQ.get("vb") === "want"' in post and "localStorage" not in post.split('sharedQ.get("vb")', 1)[1].split("\n", 1)[0]
                  and '<option value="want">★ My want-to-go</option>' in INDEX,
                  "a link's vb=want opens the ★ list without saving it; the Been-to select offers it"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

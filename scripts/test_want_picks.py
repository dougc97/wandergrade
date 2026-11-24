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
  * "Show top 10" only when there is more: a list of exactly five has none;
  * index.html's stand-in, before first paint: as many skeleton rows as ★
    countries (England/Scotland/Wales as one UK, at most the Top N, at least
    one), renderValue's own hint for an empty list, data-vb (no gems fold),
    which renderValue drops once rows are drawn;
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
$("beenFilter").value = "want"; document.documentElement.setAttribute("data-vb", "want"); renderValue();
out.want = { rows: rows(), note: note.innerHTML, gemsHidden: $("gemsBox").hidden, url: buildShareURL(false),
             share: buildShareURL(true), vbAttr: document.documentElement.getAttribute("data-vb") };
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
// Show more only when there is more: exactly Top 5 ★ countries, then six.
$("pickCount").value = "5";
localStorage.setItem("fx_wishlist", JSON.stringify(["JP", "PT", "MX", "IS", "TH"])); wishlist = null;
$("beenFilter").value = "want"; renderValue();
out.five = { rows: rows().length, more: $("showMore").hidden };
localStorage.setItem("fx_wishlist", JSON.stringify(["JP", "PT", "MX", "IS", "TH", "GB-SCT"])); wishlist = null;
renderValue();
out.six = { rows: rows().length, more: $("showMore").hidden, text: $("showMore").textContent };
$("pickCount").value = "20";
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
    results.append(ok(w["vbAttr"] is None, "renderValue drops the stand-in's data-vb once rows are drawn"))
    results.append(ok(o["five"] == {"rows": 5, "more": True}
                      and o["six"] == {"rows": 5, "more": False, "text": "Show top 10 ↓"},
                      "Show top 10 only when there is more: none for exactly five ★ countries, there for six "
                      "%s %s" % (o["five"], o["six"])))
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

# index.html's stand-in (the script after the skeleton rows) under jsc: a
# tbody of five rows, the head script's data-pc, location and localStorage.
STAND = [x for x in re.findall(r"<script>(\(function\(\)\{var n=\+document.*?)</script>", INDEX, re.S)
         if "#picksNote > .skeltext" in x]
SPAGE = r"""
function run(c) {
  var attrs = c.pc ? { "data-pc": c.pc } : {}, rows = [], ins = [];
  function Row(n) { var cell = { textContent: "#" + n }; return { cell: cell, querySelector: function () { return cell; },
    cloneNode: function () { var r = Row(0); r.cell.textContent = cell.textContent; return r; } }; }
  for (var i = 1; i <= 5; i++) rows.push(Row(i));
  var table = { insertAdjacentHTML: function (w, h) { ins.push(w + ":" + h); } };
  var tbody = { parentNode: table, children: rows, appendChild: function (r) { rows.push(r); },
    removeChild: function (r) { rows.splice(rows.indexOf(r), 1); } };
  Object.defineProperty(tbody, "lastElementChild", { get: function () { return rows[rows.length - 1]; } });
  var document = { documentElement: { getAttribute: function (k) { return k in attrs ? attrs[k] : null; },
      setAttribute: function (k, v) { attrs[k] = String(v); } },
    createTextNode: function (t) { return { text: t }; },
    querySelector: function (q) { return q === "#topCards tbody" ? tbody : null; } };
  var location = { search: c.search }, store = c.store, localStorage = { getItem: function (x) { return x in store ? store[x] : null; } };
  (function (document, location, localStorage, URLSearchParams) { eval(SRC); })(document, location, localStorage, USP);
  return { rows: rows.map(function (r) { return r.cell.textContent; }).join(" "), vb: attrs["data-vb"] || null, ins: ins };
}
function USP(s) { var o = {}; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) { if (!kv) return;
  var i = kv.indexOf("="); o[i < 0 ? kv : kv.slice(0, i)] = i < 0 ? "" : kv.slice(i + 1); });
  this.get = function (x) { return x in o ? o[x] : null; }; }
var CASES = JSON.parse(CASES_JSON), out = [];
for (var i = 0; i < CASES.length; i++) out.push(run(CASES[i]));
print(JSON.stringify(out));
"""
W = lambda *a: json.dumps(list(a))
R = lambda n: " ".join("#%d" % i for i in range(1, n + 1))
STAND_CASES = [  # search, pc, store, rows, data-vb
    ("", None, {}, R(5), None),
    ("", None, {"wg_showvisited": "want", "fx_wishlist": W("JP", "GB-SCT", "GB-ENG", "SY", "FO", "TH", "PT", "MX")}, R(5), "want"),
    ("", None, {"wg_showvisited": "want", "fx_wishlist": W("JP", "PT", "SY")}, R(3), "want"),
    ("?vb=want", None, {"fx_wishlist": W("GB-ENG", "GB-SCT")}, R(1), "want"),
    ("", None, {"wg_showvisited": "want", "fx_wishlist": "[]"}, R(1), "empty"),
    ("?vb=want", None, {}, R(1), "empty"),
    ("", "10", {"wg_showvisited": "want", "fx_wishlist": W(*"JP PT TH MX IS GR VN PE CL AR BR CO".split())}, R(10), "want"),
    ("", "10", {"wg_showvisited": "want", "fx_wishlist": W(*"JP PT TH MX IS GR VN".split())}, R(7), "want"),
    ("", "10", {"wg_showvisited": "1", "fx_wishlist": W("JP")}, R(10), None),
]
got = None
if len(STAND) == 1:
    cases = [{"search": q, "pc": pc, "store": st} for q, pc, st, _r, _v in STAND_CASES]
    with tempfile.TemporaryDirectory() as d:
        sp = os.path.join(d, "stand.js")
        open(sp, "w", encoding="utf-8").write(SPAGE.replace("SRC", json.dumps(STAND[0]))
                                              .replace("CASES_JSON", json.dumps(json.dumps(cases))))
        r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print(r.stdout[-300:], r.stderr[-600:])
        got = None
bad = [(c[0], c[1], c[2].get("fx_wishlist"), g) for c, g in zip(STAND_CASES, got or [])
       if g["rows"] != c[3] or g["vb"] != c[4]]
results.append(ok(got is not None and len(got) == len(STAND_CASES) and not bad,
                  "the stand-in gives the ★ list as many skeleton rows as ★ countries (the UK once, at most the "
                  "Top N, at least one) and sets data-vb %s" % (bad or "")))
HINT = re.search(r"\"(<p class='hint'>Your ★ want-to-go list is empty\..*?</p>)\"", APP)
results.append(ok(got is not None and HINT is not None
                  and [g["ins"] for g in got] == [[] if v != "empty" else ["afterend:" + HINT.group(1)]
                                                  for _q, _p, _s, _r, v in STAND_CASES],
                  "an empty ★ list gets renderValue's own hint, word for word, after the skeleton"))
CSS = open(P("public", "styles.css"), encoding="utf-8").read()
results.append(ok('html[data-vb] #gemsBox, html[data-vb="empty"] #topCards > table.skeleton { display: none; }' in CSS,
                  "data-vb hides the gems fold, and for an empty list the skeleton (styled out: _TOP_HOLD un-hides it)"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

"""Every guide's served grades line, local-prices line and fares-by-month
strip (fxtracker/guide_lines.py) against what public/app.js
renderGuideGrades, renderGuideCost and renderGuideFares draw for a first
visit (from the US, Any time), with app.js
itself run under jsc (scripts/appjs_harness.js) on one fixture: production's
own /api answers in scripts/parity/fixture_*.json, the country curves taken
from fixture_flight_value.json, public/ppp.json, climate.json and
activities.json.

    /usr/bin/python3 scripts/test_guide_lines.py

What it holds the code to:
  * for all 190 guides: the served grades line is the client's markup with
    the tooltips taken out (title, data-tip, aria-label) — the Overall pill
    and number, the four grades, the 🧳 days, "—" and the reason for an
    ungraded country — the served 💰 line is the client's (its band word
    first, none on a Level 4 guide, "UK-wide" for England, Bhutan's visitor
    fee beside it, none on the US's own guide or without a figure), from
    live rates and from the dated snapshot alike, and the served strip is
    the client's, tooltips aside but its ⓘ's, which names the search link's
    commission (or both are none: fewer than three months), so the
    browser's copy replaces them
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
       "slugs": load("public", "slugs.json"), "visa": load("public", "visa.json")}
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
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; visa = FIX.visa; ensureVisa = async () => visa;
for (const iso of FIX.guides) _fareMonthsCache["US:" + iso] = Promise.resolve(FIX.curves[iso] || null);
const out = {};
(async () => {
  for (const iso of FIX.guides) {
    ccGuideIso = iso;
    $("guideGrades").innerHTML = ""; $("guideFares").innerHTML = ""; $("guideFares").hidden = true;
    await renderGuideGrades(iso);
    await renderGuideFares(iso);
    const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
    await renderGuideCost(iso);
    out[iso] = { grades: $("guideGrades").innerHTML, fares: $("guideFares").hidden ? "" : $("guideFares").innerHTML,
                 cost: gc.hidden ? "" : gc.innerHTML };
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
TIP = re.compile(r'<a class="muted ggmon tiplink" href="/how-grades-work" data-tip="([^"]*)" title="">(\w+) '
                 r'<span aria-hidden="true">ⓘ</span>')
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
                                              "the Top Picks table and this page&#39;s 📸 share card show. Click for how every grade is worked out."
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
# The graded line's "Dec ⓘ" is also a link to /how-grades-work that keeps its
# tip (the tip engine's a.tiplink: a tap shows the tip, a second follows the
# link), served too.
LINKED = re.compile(r'<a class="muted ggmon tiplink" href="/how-grades-work" data-tip="Graded for [^"]+'
                    r' Click for how every grade is worked out\." title="">\w+ '
                    r'<span aria-hidden="true">ⓘ</span><span class="vh">, how grades work</span></a>$')
linked = [iso for iso in GUIDES if 'data-gg="ov"' in js[iso]["grades"] and LINKED.search(js[iso]["grades"])
          and LINKED.search(G.grades(iso, inputs, TODAY))]
results.append(ok(len(linked) == graded,
                  "every graded line's month ⓘ links to /how-grades-work with its tip, served too (%d of %d)"
                  % (len(linked), graded)))

# --- the 💰 line (review #11) -------------------------------------------------------------
bad_c = [(iso, G.cost(iso, FIX["rates"], FIX["ppp"], FIX["advisories"]), bare(js[iso]["cost"]))
         for iso in GUIDES if G.cost(iso, FIX["rates"], FIX["ppp"], FIX["advisories"]) != bare(js[iso]["cost"])]
for iso, a, b in bad_c[:2]:
    print("        %s\n        served %r\n        client %r" % (iso, a, b))
leads = {}
for iso in GUIDES:
    m = re.match(r"💰 <b>([A-Z][a-z ]+): local prices ≈ \d+% of the US", js[iso]["cost"])
    leads.setdefault(m.group(1) if m else ("Local" if js[iso]["cost"].startswith("💰 <b>Local prices") else
                                          js[iso]["cost"][:12] or "none"), []).append(iso)
results.append(ok(not bad_c and {"Very cheap", "Cheap", "A bit cheaper", "About the same", "Pricey"} <= set(leads)
                  and "US" in leads.get("none", []) and "AF" in leads.get("Local", [])
                  and "UK-wide figure" in js["GB-SCT"]["cost"] and set(leads) <= {
                      "Very cheap", "Cheap", "A bit cheaper", "About the same", "Pricey", "Local", "none"},
                  "every guide's 💰 line is the client's, tooltip aside, opening with its band word (%s) %s"
                  % (", ".join("%s %d" % (k, len(v)) for k, v in sorted(leads.items())), [x[0] for x in bad_c][:10] or "")))
l4 = [iso for iso in GUIDES if G.adv_level(iso, FIX["advisories"]) == 4]
results.append(ok(l4 and all(iso in leads.get("Local", []) + leads.get("none", []) for iso in l4)
                  and all(G.adv_level(iso, FIX["advisories"]) == 4 for iso in leads.get("Local", [])),
                  "no band word on the %d Level 4 guides, and only there (%s)" % (len(l4), " ".join(l4[:8]))))
# Bhutan's visitor fee (review #10) beside the figure, served and drawn alike
# (the comparison above), and on no other guide.
FEE = ' <span class="guidefee">+ $100/night fee</span><span class="fxinfo"'
results.append(ok(FEE in js["BT"]["cost"] and FEE in G.cost("BT", FIX["rates"], FIX["ppp"], FIX["advisories"])
                  and "Not in the price level." in js["BT"]["cost"]
                  and [i for i in GUIDES if "guidefee" in js[i]["cost"]] == ["BT"],
                  "Bhutan's 💰 line carries its $100/night fee beside the figure, served and drawn, its ⓘ the "
                  "fee in full; no other guide's does"))
results.append(ok("A+ up to about 24% of home prices and F above about 82%" in js["TH"]["cost"]
                  and "about 24%" not in js["AF"]["cost"],
                  "the ⓘ says why a cheap place can grade C or D (not on a Level 4 guide)"))
# The scale those numbers state: afford = (1.3 - pl) / 1.15 x 100, rounded (valueScores).
edge = lambda g: max(p / 1000 for p in range(50, 1500) if (lambda a: a >= g)(
    max(0, min(100, int((1.3 - p / 1000) / 1.15 * 100 + 0.5)))))
results.append(ok(round(edge(93) * 100) == 24 and round(edge(42) * 100) == 82,
                  "A+ ends at %.1f%% and D at %.1f%%: the ⓘ's 24%% and 82%%" % (edge(93) * 100, edge(42) * 100)))

# The dated snapshot's words when live rates didn't load (render_guide._cost_line).
DOC = dict(load("public", "guide-facts.json"), _asof=TODAY.isoformat())
SNAP_ISOS = ["TH", "AF", "GB-SCT", "DE", "CH", "US", "TW", "BT", "CU"]
SNAP_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp; lastRates = null; advisories = FIX.advisories; activities = FIX.activities;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; _guideFacts = FIX.doc;
visa = FIX.visa; ensureVisa = async () => visa;
const out = {};
(async () => {
  for (const iso of FIX.isos) {
    ccGuideIso = iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
    await renderGuideCost(iso);
    out[iso] = gc.hidden ? "" : gc.innerHTML;
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, doc=DOC, isos=SNAP_ISOS), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + SNAP_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    sj = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    sj = {"error": (r.stderr or r.stdout)[-300:]}
snap = {iso: G.cost(iso, None, None, FIX["advisories"],
                    render_guide._cost_line(iso, {k: v for k, v in DOC.get(iso, {}).items()}, TODAY))
        for iso in SNAP_ISOS}
results.append(ok("error" not in sj and all(snap[i] == bare(sj.get(i)) for i in SNAP_ISOS)
                  and "Very cheap: local prices ≈" in snap["TH"] and "(UK-wide figure, " in snap["GB-SCT"]
                  and snap["AF"].startswith("💰 <b>Local prices") and snap["US"] == "" and snap["CU"] == ""
                  and "Very cheap: local prices ≈" in snap["TW"]
                  and ' <span class="guidefee">+ $100/night fee</span>' in snap["BT"],
                  "live rates out: the served line is the snapshot's dated words, as the client's fallback "
                  "draws them %s" % ({i: (snap[i], sj.get(i)) for i in SNAP_ISOS if snap[i] != bare(sj.get(i))}
                                     if "error" not in sj else sj)))

# Advisories out (a failed, slow or blocked /api/advisories): still no band word
# on a Level 4 guide — the page's own mark (#tab-guide data-level) for its own
# guide, else the snapshot's adv, as guide_lines.cost reads snapshot_l4 — and
# the band word everywhere else. It drew "Very cheap" under "Level 4, do not
# travel" on Russia's guide.
L4_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; advisories = null; activities = FIX.activities;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => null; ensurePPP = async () => ppp; _guideFacts = FIX.doc;
visa = FIX.visa; ensureVisa = async () => visa;
const out = {};
(async () => {
  for (const c of FIX.cases) {
    window.__WGGC__ = c.page; const gt = $("tab-guide");
    if (c.level) gt.setAttribute("data-level", c.level); else gt.removeAttribute("data-level");
    ccGuideIso = c.iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
    await renderGuideCost(c.iso);
    out[c.name] = gc.hidden ? "" : gc.innerHTML;
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
L4_DOC = json.loads(json.dumps(DOC))
L4_DOC["PS"].pop("adv", None)            # only the page's own mark says Level 4
L4_CASES = [
    {"name": "Russia's own guide (marked 4, snapshot 4)", "iso": "RU", "page": "RU", "level": "4", "want": "Local"},
    {"name": "Lebanon opened in-app (snapshot 4)", "iso": "LB", "page": "TH", "level": "2", "want": "Local"},
    {"name": "Palestine's own guide (marked 4, no snapshot level)", "iso": "PS", "page": "PS", "level": "4",
     "want": "Local"},
    {"name": "Thailand's own guide (marked 2)", "iso": "TH", "page": "TH", "level": "2", "want": "Very cheap: local"},
    # Nothing says Level 4 (no list, no snapshot level, not the page's guide): the band word.
    {"name": "Palestine opened in-app, no level known", "iso": "PS", "page": "TH", "level": "", "want": "band"},
]
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, doc=L4_DOC, cases=L4_CASES), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + L4_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    l4j = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    l4j = {"error": (r.stderr or r.stdout)[-300:]}


def l4_ok(c, h):
    if not h or not h.startswith("💰 <b>"):
        return False
    lead = h[len("💰 <b>"):]
    if c["want"] == "Local":
        return lead.startswith("Local prices ≈") and "Affordability grade" not in h
    if c["want"] == "band":
        return not lead.startswith("Local prices") and ": local prices ≈" in lead
    return lead.startswith(c["want"] + " prices ≈")


bad_l4 = [(c["name"], l4j.get(c["name"])) for c in L4_CASES if not l4_ok(c, l4j.get(c["name"]))]
results.append(ok("error" not in l4j and not bad_l4,
                  "advisories out: no band word on a Level 4 guide (the page's own data-level, else the snapshot's "
                  "level), the band word elsewhere %s" % (bad_l4 or "" if "error" not in l4j else l4j)))

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
    cold_us = server._render_index("US").decode("utf-8")
    now = time.time()
    # Just after boot: rates in, the World Bank refresh still running (busy,
    # "at" 0), the committed table in hand. The 💰 line is the live one, not
    # the dated snapshot app.js then swapped for it.
    server._rates_cache[rkey] = (now, FIX["rates"])
    server._ppp_cache.update(at=0, data=FIX["ppp"], busy=True)
    try:
        booting = server._render_index("TH").decode("utf-8")
    finally:
        server._ppp_cache["busy"] = False
    server._adv_cache["us"] = (now, FIX["advisories"])
    server._rates_cache[rkey] = (now, FIX["rates"])
    server._ppp_cache.update(at=now, data=FIX["ppp"])
    warm = {iso: server._render_index(iso).decode("utf-8") for iso in ("TH", "AF", "GB-ENG")}
    warm_us = server._render_index("US").decode("utf-8")
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
US_COST = '<div id="guideCost" class="guidecost" hidden data-iso="US" data-pl="US"></div>\n          ' + server._COST_HOLD
cdiv = lambda iso, line: ('<div id="guideCost" class="guidecost" data-iso="%s" data-pl="%s">%s</div>\n          %s'
                          % (iso, G.guide_sizers.GUIDE_PARENT.get(iso, iso), line, server._COST_HOLD))
snap_th = G.cost("TH", None, None, None, render_guide.render("TH")["cost"])
results.append(ok((cdiv("TH", snap_th) in cold if snap_th else '<div id="guideCost" class="guidecost" hidden></div>' in cold)
                  and all(cdiv(i, G.cost(i, FIX["rates"], FIX["ppp"], FIX["advisories"])) in warm[i] for i in warm)
                  and "UK-wide figure" in warm["GB-ENG"] and "💰 <b>Local prices" in warm["AF"]
                  and all(US_COST in h for h in (cold_us, warm_us))
                  and '<div id="guideCost" class="guidecost" hidden></div>' in home and server._COST_HOLD not in home,
                  "the 💰 line is served under the grades: the snapshot's words with the caches cold (%r), live once "
                  "they are warm, with its pre-paint script; on the US's guide empty and hidden, with the script "
                  "(a reader from elsewhere gets its room); none on the homepage" % snap_th[:60]))
boot_th = G.cost("TH", FIX["rates"], FIX["ppp"], None)
results.append(ok(boot_th and cdiv("TH", boot_th) in booting and "(Sep 20" not in boot_th and boot_th != snap_th,
                  "just after boot (rates in, the PPP refresh still running) the 💰 line is the live one from the "
                  "committed table, not the dated snapshot: %r" % (boot_th or "")[:70]))
CSS = open(P("public", "styles.css"), encoding="utf-8").read()
results.append(ok(re.search(r"\.guidecost \{[^}]*line-height: 18px; min-height: 18px;", CSS)
                  and "@media (max-width: 560px) { .guidecost { min-height: 36px; align-content: center; } }" in CSS
                  and ".guidecost.pend:empty" not in CSS,
                  "styles.css: the line's room is the same whoever's words fill it (one 18px line, two on a phone), "
                  "empty and held (the US's guide) too"))
COST_HOLD = re.search(r"<script>(.*)</script>", server._COST_HOLD, re.S).group(1)
COST_PAGE = r"""
function USP(s) { var o = {}; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) { if (!kv) return;
  var i = kv.indexOf("="); o[i < 0 ? kv : kv.slice(0, i)] = i < 0 ? "" : kv.slice(i + 1); });
  this.get = function (k) { return k in o ? o[k] : null; }; }
function run(c) {
  var attrs = { "data-pl": c.pl }, el = { className: "guidecost", hidden: c.pl === "US",
    getAttribute: function (k) { return k in attrs ? attrs[k] : null; } };
  var document = { getElementById: function (id) { return id === "guideCost" ? el : null; } };
  var location = { search: c.search }, store = c.store;
  var localStorage = { getItem: function (k) { return k in store ? store[k] : null; } };
  (function (document, location, localStorage, URLSearchParams) { eval(HOLD_SRC); })(document, location, localStorage, USP);
  return [el.className, el.hidden];
}
var CASES = JSON.parse(CASES_JSON), out = [];
for (var i = 0; i < CASES.length; i++) out.push(run(CASES[i]));
print(JSON.stringify(out));
"""
COST_CASES = [
    ("a first visit", "", {}, "TH", ["guidecost", False]),
    ("a saved US origin and a month link", "?vmn=12", {"fx_origin": "US"}, "TH", ["guidecost", False]),
    ("a saved home country", "", {"fx_origin": "DE"}, "TH", ["guidecost pend", False]),
    ("a shared link's From", "?vo=GB", {}, "TH", ["guidecost pend", False]),
    ("the Flights tab's share link", "?fo=CA", {}, "TH", ["guidecost pend", False]),
    ("a link back to the US over a saved Germany", "?vo=US", {"fx_origin": "DE"}, "TH", ["guidecost", False]),
    ("a German reader on Germany's guide", "", {"fx_origin": "DE"}, "DE", ["guidecost", True]),
    ("a British reader on Scotland's (the UK's figure)", "", {"fx_origin": "GB"}, "GB", ["guidecost", True]),
    # The US's own guide: served empty and hidden (a US reader gets none). A
    # first visit holds its room until /api/geo's guess (wg_geo) says whose.
    ("a first visit on the US's guide", "", {}, "US", ["guidecost pend", False]),
    ("a US guess on the US's guide", "", {"wg_geo": "US"}, "US", ["guidecost", True]),
    ("an unsupported guess (no home saved) on the US's guide", "", {"wg_geo": "BG"}, "US", ["guidecost", True]),
    ("a link back to the US on the US's guide", "?vo=US", {}, "US", ["guidecost", True]),
    ("a saved US origin on the US's guide", "", {"fx_origin": "US"}, "US", ["guidecost", True]),
    ("a saved home country on the US's guide", "", {"fx_origin": "DE"}, "US", ["guidecost pend", False]),
    ("a shared link's From on the US's guide", "?vo=GB", {}, "US", ["guidecost pend", False]),
]
with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "cost.js")
    cc = [{"search": q, "store": st, "pl": pl} for _n, q, st, pl, _w in COST_CASES]
    open(sp, "w", encoding="utf-8").write(COST_PAGE.replace("HOLD_SRC", json.dumps(COST_HOLD))
                                          .replace("CASES_JSON", json.dumps(json.dumps(cc))))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=60)
try:
    cg = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    cg = None
bad = [(c[0], g) for c, g in zip(COST_CASES, cg or []) if g != c[4]]
results.append(ok(cg is not None and len(cg) == len(COST_CASES) and not bad,
                  "the 💰 line's pre-paint script keeps it for a US reader, holds its room unseen for a reader from "
                  "elsewhere (on the US's guide too, served hidden) and hides it on their own country's guide %s" % (bad or (r.stderr[-300:] if cg is None else ""))))

# app.js renderGuideCost after paint: a first visit from abroad (the served
# line drawn for the US until /api/geo seeds a home) keeps the room of a line
# it no longer shows on that reader's own guide; the US's guide fills the room
# the pre-paint script held.
COST_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; visa = FIX.visa; ensureVisa = async () => visa;
const gc = $("guideCost"), o = [];
const snap = () => [gc.hidden, gc.classList.contains("pend"), gc.innerHTML.slice(0, 6)];
(async () => {
  ccGuideIso = "GB"; gc.dataset = { iso: "GB" }; gc.innerHTML = "SERVED"; gc.hidden = false;
  await renderGuideCost("GB"); o.push(snap());
  localStorage.setItem("fx_origin", "GB");
  await renderGuideCost("GB"); o.push(snap());
  ccGuideIso = "DE"; await renderGuideCost("DE"); o.push(snap());
  ccGuideIso = "GB"; await renderGuideCost("GB"); o.push(snap());
  localStorage.setItem("fx_origin", "DE");
  ccGuideIso = "US"; gc.dataset = { iso: "US" }; gc.innerHTML = ""; gc.hidden = false; gc.classList.add("pend");
  await renderGuideCost("US"); o.push(snap());
  localStorage.setItem("fx_origin", "US"); gc.dataset = { iso: "US" }; gc.innerHTML = ""; gc.hidden = true;
  gc.classList.remove("pend");
  await renderGuideCost("US"); o.push(snap());
  // A first visit's held room on the US's guide, the reader still the US
  // (geo not in, or a US guess): kept, unseen, not given back.
  gc.dataset = { iso: "US" }; gc.innerHTML = ""; gc.hidden = false; gc.classList.add("pend");
  await renderGuideCost("US"); o.push(snap());
  print(JSON.stringify(o));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + COST_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    co = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    co = {"error": (r.stderr or r.stdout)[-300:]}
LINE = "💰 <b>"
results.append(ok(co == [[False, False, LINE], [False, True, LINE], [False, False, LINE], [True, False, ""],
                         [False, False, LINE], [True, False, ""], [False, True, ""]],
                  "app.js renderGuideCost: a first visit from the UK keeps the US line's room unseen once /api/geo "
                  "makes the UK's guide its own (it moved the hero 22px), another guide draws, the UK's guide "
                  "entered afresh shows none; on the US's guide a German reader's line fills the held room, a "
                  "US reader gets none, and a first visit's held room stays %s" % ("" if isinstance(co, list) else co)))

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

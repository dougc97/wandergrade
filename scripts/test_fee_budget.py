"""A mandatory visitor fee (visa.json "fee": Bhutan's US$100 a night, Indian
nationals' ₹1,200) where public/app.js meets it outside the live price line:
the guide's dated-snapshot line and the Top Picks budget. app.js itself runs
under jsc (scripts/appjs_harness.js) on scripts/parity/fixture_rates.json and
fixture_advisories.json, public/ppp.json, visa.json and guide-facts.json.

    /usr/bin/python3 scripts/test_fee_budget.py

What it holds the code to:
  * live rates out (renderGuideCost's snapshot fallback, measured against the
    US): an Indian reader's Bhutan line has no band word ("Very cheap" at 22%
    of the US contradicts their live line, "About the same … of India") but
    their ₹1,200/night fee, and its ⓘ gives their rate and says the grade
    counts local prices only; a US reader's Bhutan and Thailand lines are
    the served snapshot's words, unchanged (an Indian reader's Thailand has
    no band word either: the snapshot's is the US's, test_snapshot_band.py);
  * budgetFit takes the fee off what's left, one night per day of the trip,
    in US dollars (the rupee rate by today's rate): ₹150,000 for 10 days and
    a USD 300 fare leave an Indian reader ₹1,200 a day less in Bhutan than
    in Thailand on the same fare; budgetWords and the 💵 line's tip name the
    fee in the budget's money (its own figure beside it when that's another);
    a fare the budget covers but not with the fee is out of reach as a fare
    alone is (impossible on a real fare, estOut on an estimate, impossible
    whatever the fare when the fee alone uses the budget up); a country with
    no fee is untouched; no rupee rate (or no visa.json for the US-dollar
    fee) is no opinion, never a budget that ignores the fee; the guide's AI
    prompt says the fee too;
  * the fee is named only where it is what put the budget over (feeTipped:
    the fare alone fits, the fare and the fee don't): a fare over on its own
    is "the flight alone", fee or not, in the budget note, the ★ list's
    reason (renderValue on the INR edition's fixtures) and the AI prompt; the
    "Any time" chip's tip says which months the fee ruled out and which the
    flight alone did (flexWinScores, flexChips).
"""
import datetime, json, os, re, subprocess, sys, tempfile

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
TODAY = datetime.date.today()
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "ppp": load("public", "ppp.json"), "activities": load("public", "activities.json"),
       "slugs": load("public", "slugs.json"), "visa": load("public", "visa.json"),
       "doc": dict(load("public", "guide-facts.json"), _asof=TODAY.isoformat())}
INR = next(r["rate_now"] for r in FIX["rates"]["rows"] if r["code"] == "INR")
LOCAL = FIX["visa"]["BT"]["fee"]["local"]["IN"]["amount"]      # 1200
USD_FEE = FIX["visa"]["BT"]["fee"]["usd"]                      # 100

SNAP_CASES = [("IN", "BT"), ("US", "BT"), ("IN", "TH"), ("US", "TH")]
# origin, budget money, budget, days, country, fare (USD), estimated, fareMin, pl, rupee rate in, visa.json in
FIT_CASES = {
    "in-bt":      ("IN", "INR", 150000, 10, "BT", 300, False, None, 1.08, True, True),
    "in-th":      ("IN", "INR", 150000, 10, "TH", 300, False, None, 0.62, True, True),
    "in-bt-edge": ("IN", "INR", 150000, 10, "BT", round(150000 / INR - 100, 2), False, None, 1.08, True, True),
    "in-th-edge": ("IN", "INR", 150000, 10, "TH", round(150000 / INR - 100, 2), False, None, 0.62, True, True),
    "in-bt-est":  ("IN", "INR", 150000, 10, "BT", round(150000 / INR - 100, 2), True, None, 1.08, True, True),
    "in-bt-usd":  ("IN", "USD", 2000, 10, "BT", 300, False, None, 1.08, True, True),
    "in-bt-norate": ("IN", "USD", 2000, 10, "BT", 300, False, None, 1.08, False, True),
    "in-th-norate": ("IN", "USD", 2000, 10, "TH", 300, False, None, 0.62, False, True),
    "us-bt":      ("US", "USD", 3000, 10, "BT", 1500, False, None, 0.22, True, True),
    "us-bt-min":  ("US", "USD", 3000, 10, "BT", 2100, False, 1200, 0.22, True, True),
    "us-bt-feeout": ("US", "USD", 900, 10, "BT", 500, True, None, 0.22, True, True),
    "us-bt-novisa": ("US", "USD", 3000, 10, "BT", 1500, False, None, 0.22, True, False),
    "us-th":      ("US", "USD", 3000, 10, "TH", 1500, False, None, 0.30, True, True),
    "in-bt-fareout": ("IN", "INR", 40000, 10, "BT", round(64211 / INR, 4), False, None, 1.08, True, True),
}

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp; advisories = FIX.advisories; activities = FIX.activities;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; _guideFacts = FIX.doc;
ensureVisa = async () => visa;
const out = { snap: {}, fit: {} };
const setOrigin = (o) => { localStorage.removeItem("fx_origin"); if (o) localStorage.setItem("fx_origin", o); };
(async () => {
  // Live rates out: the dated snapshot's line.
  lastRates = null; visa = FIX.visa;
  for (const [o, iso] of FIX.snapCases) {
    setOrigin(o);
    ccGuideIso = iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
    await renderGuideCost(iso);
    out.snap[o + ":" + iso] = gc.hidden ? "" : gc.innerHTML;
  }
  // The budget, on stubbed scores so the guide's AI prompt plans on the case's fare.
  let S = null;
  valueScores = () => S; advisoryByIso = () => ({}); buildFareContext = () => ({ prices: {} });
  for (const k in FIX.fitCases) {
    const [o, cur, budget, days, iso, fare, est, fareMin, pl, rupee, visaIn] = FIX.fitCases[k];
    setOrigin(o);
    localStorage.setItem("wg_budget", String(budget)); localStorage.setItem("wg_budgetdays", String(days));
    localStorage.setItem("wg_budgetcur", cur);
    lastRates = rupee ? FIX.rates : Object.assign({}, FIX.rates, { rows: FIX.rates.rows.filter((r) => r.code !== "INR") });
    visa = visaIn ? FIX.visa : null;
    S = { iso, fare, fareEst: est, fareMin, pl, flyBasis: "month" };
    const bf = budgetFit(S);
    out.fit[k] = { bf: bf && Object.assign({}, bf, { feeInfo: !!bf.feeInfo }), words: bf ? budgetWords(S, bf) : null,
                   line: budLine(S), passes: passesBudget(S), ai: aiGuideBudget(iso, 3), tipped: feeTipped(bf) };
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, snapCases=SNAP_CASES, fitCases=FIT_CASES), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-500:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)


def bare(h):
    return re.sub(r' (?:title|data-tip|aria-label)="[^"]*"', "", h or "")


def tip(h):
    m = re.search(r'data-tip="([^"]*)"', h or "")
    return m.group(1) if m else ""


# --- (a) the snapshot fallback --------------------------------------------------------
snap = js["snap"]
served = {iso: G.cost(iso, None, None, FIX["advisories"], render_guide._cost_line(iso, dict(FIX["doc"].get(iso, {})), TODAY))
          for iso in ("BT", "TH")}
pct = FIX["doc"]["BT"]["pct"]
inbt = snap["IN:BT"]
results.append(ok(re.match(r'💰 <b>Local prices ≈ %d%% of the US \([A-Z][a-z]{2} \d{4}\)</b> '
                           r'<span class="guidefee">\+ ₹1,200/night fee</span><span class="fxinfo"' % pct, inbt)
                  and "cheap" not in bare(inbt).lower(),
                  "live rates out, an Indian reader's Bhutan line has no band word and their own fee: %r"
                  % re.sub(r"<[^>]+>", "", re.sub(r'<span class="fxinfo".*', "", inbt))))
t = tip(inbt)
results.append(ok("Sustainable Development Fee for Indian nationals: ₹1,200 per person per night, on top of what "
                  "you pay to stay. Not in the price level." in t
                  and t.endswith("The 💰 Affordability grade counts local prices only: the fee comes on top.")
                  and "US$" not in t and "grade C or D" not in t and "against the same basket in the US" in t,
                  "… its ⓘ gives their ₹1,200 and says the grade counts local prices only (no US$100, no "
                  "\"cheap place can still grade C or D\" for a band word it no longer has): %r" % t))
results.append(ok(bare(snap["US:BT"]) == served["BT"] and served["BT"].startswith("💰 <b>Local prices ≈ ")
                  and "+ $100/night fee" in served["BT"]
                  and tip(snap["US:BT"]).endswith("counts local prices only: the fee comes on top."),
                  "a US reader's Bhutan fallback is unchanged: the served snapshot's words, no band word, the "
                  "US$100 fee: %r" % served["BT"]))
results.append(ok(bare(snap["US:TH"]) == served["TH"] and "Very cheap: local prices ≈" in served["TH"]
                  and "grade C or D" in tip(snap["US:TH"])
                  and bare(snap["IN:TH"]) == served["TH"].replace("Very cheap: local prices", "Local prices")
                  and "grade C or D" not in tip(snap["IN:TH"]),
                  "a country with no fee (Thailand): a US reader's fallback keeps its band word and grade note, the "
                  "served snapshot's words (%r); an Indian reader's has neither, the band being the US's"
                  % served["TH"]))

# --- (b) the budget -------------------------------------------------------------------
fit = js["fit"]


def want(k):
    o, cur, budget, days, iso, fare, est, fmin, pl, rupee, visa_in = FIT_CASES[k]
    rate = 1 if cur == "USD" else INR
    total = budget / rate
    if iso == "BT":
        if o == "IN":
            night = LOCAL / INR if rupee else None
        else:
            night = USD_FEE if visa_in else None
        if night is None:
            return None
    else:
        night = 0
    fee = night * days
    cheapest = min(fmin, fare) if (not est and fmin) else fare
    f = fare if fare + fee < total else cheapest
    left = total - f - fee
    real = (not est) or (fee > 0 and fee >= total)
    return {"total": total, "fare": f, "fee": fee, "feeNight": night, "left": left, "perDay": left / days,
            "impossible": real and left <= 0, "estOut": (not real) and left <= 0}


def close(a, b):
    return isinstance(b, (int, float)) and abs(a - b) < 1e-6


num_bad = []
for k in FIT_CASES:
    w, g = want(k), fit[k]["bf"]
    if w is None or g is None:
        if (w is None) != (g is None):
            num_bad.append((k, w, g))
        continue
    if not all(close(w[x], g.get(x)) for x in ("total", "fare", "fee", "feeNight", "left", "perDay")) \
            or w["impossible"] != g.get("impossible") or w["estOut"] != g.get("estOut"):
        num_bad.append((k, w, g))
results.append(ok(not num_bad, "budgetFit takes fee × days (₹1,200 at %.4f to the dollar, or US$100) off what the fare "
                  "leaves, for %d cases %s" % (INR, len(FIT_CASES), num_bad)))

a, b = fit["in-bt"], fit["in-th"]
inr = lambda usd: round(usd * INR)
results.append(ok(inr(a["bf"]["perDay"]) == inr(b["bf"]["perDay"]) - LOCAL
                  and a["line"].endswith("💵 INR %s/day left</span>" % format(inr(a["bf"]["perDay"]), ","))
                  and a["words"] == "INR %s flight and the INR 1,200/night visitor fee leave INR %s/day"
                  % (format(inr(300), ","), format(inr(a["bf"]["perDay"]), ","))
                  and ('data-tip="%s"' % a["words"]) in a["line"],
                  "an Indian reader, ₹150,000 for 10 days, USD 300 fare: Bhutan leaves INR %s/day "
                  "(Thailand on the same fare INR %s/day), its 💵 tip %r"
                  % (format(inr(a["bf"]["perDay"]), ","), format(inr(b["bf"]["perDay"]), ","), a["words"])))
results.append(ok(b["bf"].get("fee") == 0 and not b["bf"].get("feeInfo") and " visitor fee" not in b["words"]
                  and re.match(r"INR [\d,]+ flight leaves INR [\d,]+/day — like INR [\d,]+/day at home$", b["words"])
                  and fit["us-th"]["words"] == "USD 1,500 flight leaves USD 150/day — like USD 500/day at home"
                  and not fit["in-th-edge"]["bf"]["impossible"] and fit["in-th-edge"]["passes"],
                  "no fee, no change: Thailand's words are the old ones (%r; %r)" % (b["words"], fit["us-th"]["words"])))
e, x = fit["in-bt-edge"], fit["in-bt-est"]
results.append(ok(e["bf"]["impossible"] and not e["bf"]["estOut"] and not e["passes"] and e["line"] == ""
                  and fit["in-th-edge"]["bf"]["left"] > 0
                  and x["bf"]["estOut"] and not x["bf"]["impossible"] and not x["passes"]
                  and e["ai"].endswith("; the INR %s flight and the INR 1,200/night visitor fee use it up."
                                       % format(inr(e["bf"]["fare"]), ",")),
                  "a fare that leaves USD 100 but not 10 nights' fee: out of reach on a real fare (impossible), "
                  "estOut on an estimate, no 💵 line, and the AI prompt says why: %r" % e["ai"]))
u = fit["in-bt-usd"]
results.append(ok("and the USD %d/night (₹1,200) visitor fee leave " % round(LOCAL / INR) in u["words"],
                  "an Indian reader budgeting in dollars sees the fee in dollars with its rupee figure: %r" % u["words"]))
results.append(ok(fit["in-bt-norate"]["bf"] is None and fit["in-bt-norate"]["passes"] and fit["in-bt-norate"]["line"] == ""
                  and fit["in-th-norate"]["bf"] is not None and fit["us-bt-novisa"]["bf"] is None,
                  "no rupee rate (or no visa.json for the US-dollar fee): no opinion on Bhutan, never a budget that "
                  "ignores the fee; Thailand still judged"))
v = fit["us-bt"]
results.append(ok(v["words"] == "USD 1,500 flight and the USD 100/night visitor fee leave USD 50/day — like USD 227/day at home"
                  and v["ai"].endswith("; " + v["words"] + ".")
                  and fit["us-bt-min"]["bf"]["fareIsMin"] and fit["us-bt-min"]["words"].startswith("USD 1,200 cheapest flight and ")
                  and fit["us-bt-feeout"]["bf"]["impossible"] and not fit["us-bt-feeout"]["bf"]["estOut"]
                  and fit["us-bt-feeout"]["ai"].endswith("; the USD 100/night visitor fee alone uses it up."),
                  "a US reader (where budgetFit still runs for Bhutan: the guide's AI prompt) pays the US$100 a "
                  "night: %r; the cheapest seen fare stands in when the average plus the fee is over; the fee alone "
                  "over budget is out whatever the estimated fare" % v["words"]))

g = fit["in-bt-fareout"]
results.append(ok(g["bf"]["impossible"] and g["bf"]["fare"] >= g["bf"]["total"] and g["tipped"] is False
                  and fit["in-bt-edge"]["tipped"] is True and fit["us-bt-feeout"]["tipped"] is True
                  and fit["in-th-edge"]["tipped"] is False
                  and g["ai"].endswith("; the INR %s flight alone uses it up." % format(inr(g["bf"]["fare"]), ",")),
                  "a fare over the budget on its own (₹40,000, Bhutan's INR 64,211): \"the flight alone\", fee or not; "
                  "the fee is named only where it tipped the budget over: %r" % g["ai"]))

# --- (c) the ★ list and the budget note: renderValue on the INR edition's fixtures ----------------
from fxtracker import picks  # noqa: E402
RV = dict(FIX, climate=load("public", "climate.json"), world=load("public", "world.geojson"),
          popular=sorted(picks.FALLBACK_POPULAR), inrates=load("scripts", "parity", "fixtures", "INR", "rates.json"),
          flights=load("scripts", "parity", "fixtures", "INR", "flights.json"),
          fv=load("scripts", "parity", "fixtures", "INR", "flight_value.json"),
          budgets=[40000, 65000, 150000], want=["BT", "NP", "TH"])
# The "Any time" chip, on per-month rows for Bhutan from India (the INR
# fixtures' route has no month fares yet): ₹72,000 for 10 days; May (80) is
# best and its INR 62,164 flight fits, but not with 10 nights' ₹1,200 fee;
# March and April's INR 70,000 neither; June's INR 75,000 flight alone is
# over; February's INR 52,000 and the fee fit.
FLEX = {"budget": 72000, "win": [2, 3, 4, 5, 6],
        "rows": {"2": [52000, 70], "3": [70000, 72], "4": [70000, 71], "5": [62164, 80], "6": [75000, 60]}}
RV_DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; lastRates = FIX.rates; visa = FIX.visa;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
loaded.value = true; drawMap = function () {};
$("pickCount").value = "5"; $("safeFloor").value = "b";
const out = { views: [], flex: null };
try {
  $("valueOrigin").value = "IN"; localStorage.setItem("fx_origin", "IN");
  homeBase = "INR"; homeRates = FIX.inrates; flightsData = FIX.flights; flightValue = FIX.fv;
  localStorage.setItem("wg_budgetcur", "INR");
  $("valueMonth").value = "3"; $("beenFilter").value = "want";
  wishlist = new Set(FIX.want); popularSet = new Set(FIX.popular); popularDataBacked = true;
  for (const b of FIX.budgets) {
    $("budgetTotal").value = String(b); $("budgetDays").value = "10";
    renderValue();
    out.views.push({ budget: b, note: $("picksNote").innerHTML });
  }
  // The "Any time" chip: real bestOfWindow, flexWinScores and flexChips.
  localStorage.setItem("wg_budget", String(FIX.flex.budget)); localStorage.setItem("wg_budgetdays", "10");
  $("budgetTotal").value = String(FIX.flex.budget);
  const inr = rateForCurrency("INR"), win = FIX.flex.win, byMonth = {};
  for (const m of win) {
    const [fare, value] = FIX.flex.rows[m];
    byMonth[m] = { iso: "BT", name: "Bhutan", fare: fare / inr, fareEst: false, fareMin: null, pl: 1.08,
                   flyBasis: "month", value, wx: 80 };
  }
  const own = (s) => s.flyBasis === "month";
  const b = bestOfWindow(byMonth, win, "value", passesBudget, own);
  const s = b.s; s.month = b.month; s.winScores = flexWinScores(byMonth, win, b, passesBudget, own);
  if (b.moved) s.budgetMoved = true;
  out.flex = { month: b.month, moved: !!b.moved, over: s.winScores.map((x) => [x.m, x.over || null]),
               tip: flexChips(s).match(/data-tip="([^"]*)"/)[1] };
  print(JSON.stringify(out));
} catch (e) { print(JSON.stringify({ error: String(e && e.stack || e) })); }
"""
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(RV, flex=FLEX), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + RV_DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    rv = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    rv = {"error": (r.stderr or r.stdout)[-500:]}
results.append(ok("error" not in rv, "renderValue and the \"Any time\" chip ran under jsc %s" % rv.get("error", "")))
if "error" not in rv:
    import html as H
    V = {v["budget"]: v["note"] for v in rv["views"]}
    miss = lambda n: H.unescape((re.search(r'class="muted wantmiss" data-tip="([^"]*)"', n) or [None, ""])[1])
    plain = lambda n: re.sub(r"<[^>]+>", "", re.sub(r' data-tip="[^"]*"', "", n))
    lo, mid, hi = V[40000], V[65000], V[150000]
    results.append(ok("Bhutan: its flight alone is over your budget" in miss(lo) and "visitor fee" not in miss(lo)
                      and re.search(r"\d+ (?:country is|countries are) out of reach on the flight alone\.", plain(lo))
                      and "visitor fee" not in plain(lo),
                      "₹40,000 for 10 days, Bhutan's fare alone over it: the ★ list says \"its flight alone\", as the "
                      "budget note beside it does (%r; %r)" % (miss(lo), plain(lo).strip()[:140])))
    results.append(ok("Bhutan: its flight and visitor fee are over your budget" in miss(mid)
                      and "1 country is out of reach on the flight and visitor fee." in plain(mid),
                      "₹65,000 for 10 days, the fee tips it over: the ★ list and the note both name the fee (%r; %r)"
                      % (miss(mid), plain(mid).strip()[:140])))
    tipq = H.unescape((re.findall(r'<span class="muted" data-tip="([^"]*)">ⓘ', hi) or [""])[-1])
    results.append(ok("Bhutan" not in miss(hi) and "every pick below is reachable" in plain(hi)
                      and "minus the fare and any visitor fee (a night for each day of the trip), spread over your days" in tipq
                      and "daily visitor fee" not in tipq and "one per day" not in tipq,
                      "₹150,000: Bhutan ranked, and the note's ⓘ says how the fee is counted, once: %r" % tipq[:200]))
    fx = rv["flex"]
    results.append(ok(fx["month"] == 2 and fx["moved"]
                      and fx["over"] == [[2, None], [3, "fee"], [4, "fee"], [5, "fee"], [6, True]]
                      and fx["tip"].endswith(" Jun: out of reach on the flight alone. Mar, Apr, May: out of reach on "
                                             "the flight and visitor fee."),
                      "\"Any time\", ₹72,000 for 10 days: Bhutan moves to February, and its chip says the fee ruled out "
                      "Mar–May (each flight fits alone) and the flight alone June: %r" % fx["tip"]))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

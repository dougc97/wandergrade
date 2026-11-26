"""The guide's 💰 line when live rates or ppp.json don't load: public/app.js
renderGuideCost falls back to the dated snapshot (guide-facts.json: "≈ 30%
of the US (Sep 2026)"), whose band word ("Very cheap", "Pricey") is measured
against the US. app.js itself runs under jsc (scripts/appjs_harness.js) on
scripts/parity/fixture_rates.json and fixture_advisories.json, public/ppp.json,
visa.json and guide-facts.json.

    /usr/bin/python3 scripts/test_snapshot_band.py

What it holds the code to:
  * a reader whose home is the US (stored, or none stored: the default) gets
    the served snapshot's words unchanged, band word first, and the ⓘ's
    grade note ("a cheap place can still grade C or D") that explains it;
  * a reader from anywhere else (India, Germany, Canada, the UK) gets no
    band word there, on a cheap country (Thailand) or a pricey one
    (Switzerland), since their live line is measured against their own home
    and the US's word can contradict it; the ⓘ then has no grade note (it
    only explains a band word) and is otherwise the US reader's;
  * across every guide, a German or Indian reader's fallback line is the US
    reader's with the band word and the grade note taken out, nothing else
    (their own country's guide keeps its home line; Bhutan's fee is the
    reader's own: test_fee_budget.py);
  * the same rule where live rates are out but a country priced in US
    dollars (Ecuador, Panama…) still gets a computed line: for a reader from
    elsewhere the US stands in for their home ("≈ 43% of the US", not "no
    figure for Germany": Germany has one, only today's rate is missing), so
    no band word or grade note there either, and the ⓘ says the basket is
    the US's because live exchange rates didn't load (without "carried to
    today's exchange rate", which read against it); a US reader's line is
    untouched (test_rates_down_home.py has the rest);
  * the same with ppp.json out and live rates in;
  * fee countries are as round 8 left them: Bhutan has no band word for
    anyone, and its ⓘ ends on the fee note;
  * a British reader on Scotland and a German on Germany keep the home
    line, shortened to "Home prices" while live rates are out, its ⓘ
    saying other guides compare with the US for now (the full line says
    they compare with home).
"""
import datetime, html, json, os, re, subprocess, sys, tempfile

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
DOC = FIX["doc"]
ALL = sorted(k for k in DOC if not k.startswith("_"))
ORIGINS = ["", "US", "IN", "DE", "CA", "GB"]
CASES = [(o, iso) for o in ORIGINS for iso in ("TH", "CH", "BT")] + [("GB", "GB-SCT"), ("DE", "DE")]

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
advisories = FIX.advisories; activities = FIX.activities;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; _guideFacts = FIX.doc;
visa = FIX.visa; ensureVisa = async () => visa;
const setOrigin = (o) => { localStorage.removeItem("fx_origin"); if (o) localStorage.setItem("fx_origin", o); };
const draw = async (o, iso) => {
  setOrigin(o);
  ccGuideIso = iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
  await renderGuideCost(iso);
  return gc.hidden ? "" : gc.innerHTML;
};
const out = { cases: {}, all: {}, noppp: {} };
(async () => {
  // Live rates out, ppp.json in.
  ppp = FIX.ppp; lastRates = null;
  for (const [o, iso] of FIX.cases) out.cases[o + ":" + iso] = await draw(o, iso);
  for (const o of ["US", "DE", "IN"]) { out.all[o] = {}; for (const iso of FIX.all) out.all[o][iso] = await draw(o, iso); }
  // ppp.json out, live rates in.
  ppp = null; lastRates = FIX.rates;
  for (const o of ["US", "IN", "DE"]) for (const iso of ["TH", "CH"]) out.noppp[o + ":" + iso] = await draw(o, iso);
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, cases=CASES, all=ALL), open(fp, "w"))
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
    return html.unescape(m.group(1)) if m else ""


def text(h):
    return re.sub(r"<[^>]+>", "", re.sub(r'<span class="fxinfo".*', "", h or ""))


BAND = re.compile(r"<b>(?:Very cheap|Cheap|A bit cheaper|About the same|Pricey): local prices")
GRADE = (" The 💰 Affordability grade puts every country on one scale, A+ up to about 24% of home prices and F "
         "above about 82%, so a cheap place can still grade C or D.")
FEE_NOTE = " The 💰 Affordability grade counts local prices only: the fee comes on top."
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][TODAY.month - 1]
WHEN = "%s %d" % (MON, TODAY.year)
BASE = ("World Bank price level for residents, carried to the %s exchange rate (live rates didn't load) — what a "
        "local basket costs here against the same basket in the US. National averages: tourist areas and foreigner "
        "rent run well above this." % WHEN)


def served(iso, band=True):
    f = dict(DOC.get(iso, {}))
    if not band:
        f["band"] = None
    return G.cost(iso, None, None, FIX["advisories"], render_guide._cost_line(iso, f, TODAY))


c = js["cases"]
# --- US readers: unchanged ------------------------------------------------------------
us_ok = all(bare(c["%s:%s" % (o, iso)]) == served(iso) and tip(c["%s:%s" % (o, iso)]) == BASE + GRADE
            for o in ("", "US") for iso in ("TH", "CH"))
results.append(ok(us_ok and "Very cheap: local prices ≈ %d%% of the US (%s)" % (DOC["TH"]["pct"], WHEN) in served("TH")
                  and "Pricey: local prices ≈ %d%% of the US (%s)" % (DOC["CH"]["pct"], WHEN) in served("CH"),
                  "a US reader (stored, or the default with none stored) keeps the served snapshot's words and the "
                  "grade note: %r, %r" % (text(c["US:TH"]), text(c["US:CH"]))))

# --- every other home: no band word ---------------------------------------------------
bad = {}
for o in ("IN", "DE", "CA", "GB"):
    for iso in ("TH", "CH"):
        h = c["%s:%s" % (o, iso)]
        if not (bare(h) == served(iso, band=False) and tip(h) == BASE and not BAND.search(h)
                and text(h).startswith("💰 Local prices ≈ ")):
            bad[o + ":" + iso] = (text(h), tip(h))
results.append(ok(not bad and text(c["IN:TH"]) == "💰 Local prices ≈ %d%% of the US (%s)" % (DOC["TH"]["pct"], WHEN)
                  and text(c["DE:CH"]) == "💰 Local prices ≈ %d%% of the US (%s)" % (DOC["CH"]["pct"], WHEN),
                  "an Indian, German, Canadian or British reader gets no band word on Thailand or Switzerland, and "
                  "an ⓘ without the grade note (the US reader's otherwise): %r, %r %s"
                  % (text(c["IN:TH"]), text(c["DE:CH"]), bad)))

# --- every guide: only the band word and the grade note differ ---------------------------
A = js["all"]
lead = re.compile(r"<b>(?:Very cheap|Cheap|A bit cheaper|About the same|Pricey): local prices")
# Dollar-priced countries draw a computed line with rates out (rateForCurrency("USD") is 1).
LIVE = [iso for iso in ALL if "carried to today&#39;s exchange rate" in A["US"][iso]]
RATES_OUT = "against the same basket in the US, because live exchange rates didn&#39;t load."
diff = {}
for o, home in (("DE", "DE"), ("IN", "IN")):
    for iso in ALL:
        if iso in (home, "US") or iso == "BT" and o == "IN":
            continue
        want = lead.sub("<b>Local prices", A["US"][iso]).replace(GRADE.replace("&", "&amp;"), "")
        if iso in LIVE:
            want = want.replace(", carried to today&#39;s exchange rate —", " —", 1).replace(
                "against the same basket at home.", RATES_OUT)
        if A[o][iso] != want or BAND.search(A[o][iso]):
            diff[o + ":" + iso] = (A[o][iso][:160], want[:160])
n_band = sum(1 for iso in ALL if BAND.search(A["US"][iso]))
results.append(ok(not diff and n_band > 100 and "Home prices" in A["DE"]["DE"] and "Home prices" in A["IN"]["IN"],
                  "across all %d guides a German or Indian reader's fallback is the US reader's (%d with a band "
                  "word) less the band word and the grade note; their own guide keeps its home line %s"
                  % (len(ALL), n_band, dict(list(diff.items())[:3]))))
ec_us, ec_de = A["US"]["EC"], A["DE"]["EC"]
results.append(ok("EC" in LIVE and 3 <= len(LIVE) <= 30
                  and re.match(r"💰 <b>(?:Very cheap|Cheap): local prices ≈ \d+% of the US</b>", ec_us)
                  and "same basket at home" in tip(ec_us) and tip(ec_us).endswith(GRADE)
                  and re.match(r"💰 <b>Local prices ≈ \d+% of the US</b><span class=\"fxinfo\"", ec_de)
                  and "same basket in the US, because live exchange rates didn't load." in tip(ec_de)
                  and "today's exchange rate" not in tip(ec_de) and "today's exchange rate" in tip(ec_us)
                  and "grade C or D" not in tip(ec_de) and "no figure" not in ec_de
                  and not BAND.search(A["IN"]["EC"])
                  and text(A["DE"]["US"]) == "💰 Local prices ≈ 100% of the US"
                  and "Home prices" in A["US"]["US"],
                  "rates out, a dollar-priced country (%d: %s) still draws a computed line: a US reader's keeps its "
                  "band word (%r); a German's has none and its ⓘ says the basket is the US's (%r), on the US's own "
                  "guide too (%r)" % (len(LIVE), " ".join(LIVE), text(ec_us), text(ec_de), text(A["DE"]["US"]))))

# --- ppp.json out, live rates in: the same rule ------------------------------------------
N = js["noppp"]
results.append(ok(all(BAND.search(N["US:" + i]) and GRADE.replace("&", "&amp;") in N["US:" + i] for i in ("TH", "CH"))
                  and all(not BAND.search(N[o + ":" + i]) and "grade C or D" not in N[o + ":" + i]
                          and text(N[o + ":" + i]).startswith("💰 Local prices ≈ ")
                          for o in ("IN", "DE") for i in ("TH", "CH")),
                  "ppp.json out: the band word for a US reader only (%r; %r)" % (text(N["US:TH"]), text(N["IN:TH"]))))

# --- fee countries and home lines: as round 8 left them -------------------------------------
bt = {o: c[o + ":BT"] for o in ORIGINS}
results.append(ok(all(not BAND.search(h) and tip(h).endswith(FEE_NOTE) and "grade C or D" not in tip(h) for h in bt.values())
                  and bare(bt["US"]) == bare(bt[""]) == bare(bt["DE"]) == bare(bt["CA"]) == bare(bt["GB"]) == served("BT")
                  and tip(bt["DE"]) == tip(bt["US"])
                  and ' <span class="guidefee">+ ₹1,200/night fee</span>' in bt["IN"]
                  and ' <span class="guidefee">+ $100/night fee</span>' in bt["US"],
                  "Bhutan: no band word for anyone, the fee note in the ⓘ, US$100 for all but an Indian reader's "
                  "₹1,200: %r / %r" % (text(bt["US"]), text(bt["IN"]))))
HOME_OUT_TIP = "Other guides compare with the US for now, because live exchange rates didn't load."
results.append(ok(text(c["GB:GB-SCT"]) == text(c["DE:DE"]) == "💰 Home prices"
                  and tip(c["GB:GB-SCT"]) == tip(c["DE:DE"]) == HOME_OUT_TIP,
                  "a British reader on Scotland and a German on Germany keep the home line, just \"Home prices\" "
                  "while live rates are out, its ⓘ saying why: %r / %r" % (text(c["DE:DE"]), tip(c["DE:DE"]))))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

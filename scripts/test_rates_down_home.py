"""Live rates out (/api/rates never answered) for a reader whose home isn't
the US, on a guide for a country priced in US dollars (Ecuador, Panama, El
Salvador, Timor-Leste; Palestine and Liberia through PPP_UNIT). Those still
get a computed price line, since the dollar needs no rate, while the home's
own price level can't be brought to today without one, so the US stands in
(plAnchor). public/app.js runs under jsc (scripts/appjs_harness.js) on
scripts/parity/fixture_rates.json and fixture_advisories.json, public/ppp.json,
visa.json, climate.json and guide-facts.json.

    /usr/bin/python3 scripts/test_rates_down_home.py

What it holds the code to:
  * a German, Indian, British or Taiwanese reader's guide line on Ecuador and
    Panama is the US reader's number with no band word and no "(no figure
    for Germany)": Germany has a figure, only today's rate is missing
    (plRatesOut). Its ⓘ is the US reader's, less the grade note and
    "carried to today's exchange rate" (which read against "rates didn't
    load"), with "in the US, because live exchange rates didn't load" for
    "at home";
  * the AI prompts say the same plainly: aiPriceWords, the guide prompt's
    LOCAL PRICES line and the trip prompt's "prices" bit read "than the US"
    with no "(no figure for …)";
  * "(no figure for …)" stays exactly where it is true: a home with no
    ppp.json row (Cuba, the Isle of Man) with rates out, a home priced in US
    dollars whose factor is broken (Zimbabwe: no rate is missing, so rates
    out or in it is "no figure"), and with live rates in a home with no
    row, an implausible price level (Haiti) or no usable rate (Somalia),
    whose lines are the US reader's with the parenthetical and "in the US"
    (no rates-out clause), band word and grade note kept;
  * the reader's own country's home line: with rates out a German's on
    Germany or a British reader's on Scotland is just "Home prices", its ⓘ
    saying other guides compare with the US for now, because live exchange
    rates didn't load (the full "Home prices: the 100% other guides compare
    to" would say the opposite); a Panamanian's keeps its words (guides
    priced in dollars still compare with Panama) and its ⓘ says the rest
    compare with the US; with rates in, and for a US reader or a home with
    no figure (Cuba, Zimbabwe), the line and ⓘ are as before;
  * with live rates in, plRatesOut is false for every country, so no
    rates-in line changes; a US reader's lines, and an Ecuadorian reader's
    (a dollar home needs no rate), are the same with rates out or in, but
    for the ⓘ on an Ecuadorian's own home line (the Panamanian's, above).

No percentage is typed in: every figure drifts with the calendar day
(pplCarry), so each reader's number is checked against the US reader's
from the same run.
"""
import datetime, html, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
       "climate": load("public", "climate.json"),
       "slugs": load("public", "slugs.json"), "visa": load("public", "visa.json"),
       "doc": dict(load("public", "guide-facts.json"), _asof=TODAY.isoformat())}
DEST = ["EC", "PA", "SV", "TL", "PS", "LR"]
ORIGINS = ["US", "", "DE", "IN", "GB", "TW", "EC", "CU", "IM", "HT", "SO", "ZW"]
HOMES = [["DE", "DE"], ["IN", "IN"], ["GB", "GB"], ["GB", "GB-SCT"], ["US", "US"], ["", "US"], ["CU", "CU"],
         ["PA", "PA"], ["ZW", "ZW"]]

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
advisories = FIX.advisories; activities = FIX.activities; climate = FIX.climate;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp; _guideFacts = FIX.doc;
visa = FIX.visa; ensureVisa = async () => visa;
const setOrigin = (o) => { localStorage.removeItem("fx_origin"); if (o) localStorage.setItem("fx_origin", o); };
const out = { down: {}, ok: {}, trip: {}, ratesOut: {}, home: {} };
(async () => {
  ppp = FIX.ppp;
  for (const mode of ["down", "ok"]) {
    lastRates = mode === "down" ? null : FIX.rates;
    for (const o of FIX.origins) for (const iso of FIX.dest) {
      setOrigin(o);
      const A = plAnchor(originIso());
      const prompt = (buildCountryAIPrompt(iso) || "").split("\n").filter((l) => /^LOCAL PRICES/.test(l))[0] || "";
      ccGuideIso = iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
      await renderGuideCost(iso);
      out[mode][o + ":" + iso] = { lp: localPricesText(iso), ai: aiPriceWords(iso, A.home ? "home" : "the US"),
                                   prompt, guide: gc.hidden ? "" : gc.innerHTML };
    }
    for (const o of ["US", "DE", "IN", "CU"]) {
      setOrigin(o);
      localStorage.setItem("fx_trip", JSON.stringify(["EC", "PA"])); _trip = null;
      out.trip[mode + ":" + o] = (buildTripAIPrompt() || "").split("\n").filter((l) => /^- (Ecuador|Panama):/.test(l));
    }
    for (const [o, iso] of FIX.homes) {
      setOrigin(o);
      ccGuideIso = iso; const gc = $("guideCost"); gc.innerHTML = ""; gc.hidden = true; gc.dataset = {};
      await renderGuideCost(iso);
      out.home[mode + ":" + o + ":" + iso] = gc.hidden ? "" : gc.innerHTML;
    }
    const isos = new Set(Object.keys(CUR_BY_ISO).concat(Object.keys(ppp)));
    out.ratesOut[mode] = [...isos].filter((i) => plRatesOut(i)).sort();
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(dict(FIX, dest=DEST, origins=ORIGINS, homes=HOMES), open(fp, "w"))
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


def tip(h):
    m = re.search(r'data-tip="([^"]*)"', h or "")
    return html.unescape(m.group(1)) if m else ""


def text(h):
    return re.sub(r"<[^>]+>", "", re.sub(r'<span class="fxinfo".*', "", h or ""))


BAND = re.compile(r"<b>(?:Very cheap|Cheap|A bit cheaper|About the same|Pricey): local prices")
GRADE = (" The 💰 Affordability grade puts every country on one scale, A+ up to about 24% of home prices and F "
         "above about 82%, so a cheap place can still grade C or D.")
CLAUSE = ", because live exchange rates didn't load"
TODAY_RATE = ", carried to today's exchange rate"
# A number in plPhrase's words, against the US.
US_WORDS = r"(?:~\d+% (?:cheaper|pricier) than|about the same as) the US"
D, K, T = js["down"], js["ok"], js["trip"]
NAME = {"DE": "Germany", "IN": "India", "GB": "the UK", "TW": "Taiwan", "CU": "Cuba", "IM": "the Isle of Man",
        "HT": "Haiti", "SO": "Somalia", "ZW": "Zimbabwe"}
AI_NAME = dict(NAME, GB="United Kingdom", IM="Isle of Man")

# --- rates out, a home with a figure: no "(no figure for …)" --------------------------------
bad = {}
for o in ("DE", "IN", "GB", "TW"):
    for iso in DEST:
        us, h = D["US:" + iso], D[o + ":" + iso]
        want_line = BAND.sub("<b>Local prices", us["guide"]).split('<span class="fxinfo"')[0]
        want_tip = tip(us["guide"]).replace(TODAY_RATE + " —", " —", 1).replace(
            "against the same basket at home.", "against the same basket in the US" + CLAUSE + ".").replace(GRADE, "")
        if not (h["guide"].split('<span class="fxinfo"')[0] == want_line and tip(h["guide"]) == want_tip
                and h["lp"] == us["lp"] and "no figure" not in json.dumps(h, ensure_ascii=False)
                and not BAND.search(h["guide"]) and tip(h["guide"]).count(CLAUSE) == 1
                and "exchange rate —" not in tip(h["guide"])):
            bad[o + ":" + iso] = (text(h["guide"]), tip(h["guide"])[:200], h["lp"])
results.append(ok(not bad and text(D["DE:EC"]["guide"]) == "💰 Local prices " + D["US:EC"]["lp"]
                  and re.fullmatch(r"≈ \d+% of the US", D["DE:EC"]["lp"])
                  and text(D["GB:PA"]["guide"]) == "💰 Local prices " + D["US:PA"]["lp"]
                  and re.fullmatch(r"💰 Local prices ≈ \d+% of the US", text(D["GB:PA"]["guide"]))
                  and tip(D["DE:EC"]["guide"]).startswith("World Bank price level for residents — what a local basket "
                                                          "costs here against the same basket in the US" + CLAUSE + "."),
                  "rates out: a German, Indian, British or Taiwanese reader's line on Ecuador, Panama, El Salvador, "
                  "Timor-Leste, Palestine and Liberia is the US number with no band word and no \"no figure for\"; "
                  "the ⓘ says it is the US's because live rates didn't load: %r / %r %s"
                  % (text(D["DE:EC"]["guide"]), tip(D["DE:EC"]["guide"])[:150], dict(list(bad.items())[:2]))))

# --- the AI prompts: plainly "than the US" ---------------------------------------------
bad = {}
for o in ("DE", "IN", "GB", "TW"):
    for iso in DEST:
        h, us = D[o + ":" + iso], D["US:" + iso]
        want_ai = us["ai"].replace("than home", "than the US").replace("as home", "as the US")
        if not (h["ai"] == want_ai and h["prompt"] == us["prompt"] and h["prompt"].startswith("LOCAL PRICES: ")
                and "than the US" in h["prompt"]):
            bad[o + ":" + iso] = (h["ai"], h["prompt"], want_ai)
tripbad = {o: T["down:" + o] for o in ("DE", "IN")
           if len(T["down:" + o]) != 2 or any("no figure" in l or "cheaper than the US;" not in l for l in T["down:" + o])}
results.append(ok(not bad and not tripbad and re.fullmatch(US_WORDS, D["DE:EC"]["ai"])
                  and re.match("LOCAL PRICES: " + US_WORDS + r"\. National averages", D["IN:PA"]["prompt"]),
                  "rates out: aiPriceWords, the guide prompt's LOCAL PRICES line and the trip prompt read plainly "
                  "\"than the US\" for a reader from elsewhere: %r; %r %s %s"
                  % (D["DE:EC"]["ai"], [l[l.find("prices"):][:40] for l in T["down:DE"]], dict(list(bad.items())[:2]), tripbad)))

# --- "(no figure for …)" where it is true ------------------------------------------------
def with_nofig(us, o, rates_in):
    """The US reader's line and ⓘ as a no-figure home's: the parenthetical after "% of the US",
    "in the US" for "at home", the band word and grade note kept with live rates in."""
    line = us["guide"].split('<span class="fxinfo"')[0].replace("% of the US", "% of the US (no figure for " + NAME[o] + ")", 1)
    t = tip(us["guide"]).replace("against the same basket at home.", "against the same basket in the US.")
    if not rates_in:
        line, t = BAND.sub("<b>Local prices", line), t.replace(GRADE, "")
    return line, t


bad = {}
for mode, src, homes in (("down", D, ("CU", "IM", "ZW")), ("ok", K, ("CU", "HT", "SO", "ZW"))):
    for o in homes:
        for iso in DEST:
            us, h = src["US:" + iso], src[o + ":" + iso]
            line, t = with_nofig(us, o, mode == "ok")
            if not (h["guide"].split('<span class="fxinfo"')[0] == line and tip(h["guide"]) == t
                    and h["lp"] == us["lp"] + " (no figure for %s)" % NAME[o]
                    and h["ai"] == us["ai"].replace("than home", "than the US").replace("as home", "as the US")
                    + " (no figure for %s)" % AI_NAME[o] and CLAUSE not in tip(h["guide"])):
                bad["%s:%s:%s" % (mode, o, iso)] = (text(h["guide"]), h["ai"], tip(h["guide"])[:160])
results.append(ok(not bad and text(K["HT:EC"]["guide"]) == text(K["US:EC"]["guide"]) + " (no figure for Haiti)"
                  and re.fullmatch(r"💰 (?:Very cheap|Cheap): local prices ≈ \d+% of the US \(no figure for Haiti\)",
                                   text(K["HT:EC"]["guide"]))
                  and re.fullmatch(r"💰 Local prices ≈ \d+% of the US \(no figure for Cuba\)", text(D["CU:PA"]["guide"]))
                  and re.fullmatch(r"💰 Local prices ≈ \d+% of the US \(no figure for Zimbabwe\)", text(D["ZW:EC"]["guide"]))
                  and TODAY_RATE in tip(D["ZW:EC"]["guide"])
                  and re.fullmatch(US_WORDS + r" \(no figure for Somalia\)", K["SO:PA"]["ai"])
                  and D["ZW:PA"]["ai"].endswith(" (no figure for Zimbabwe)")
                  and ("no figure for Cuba" in T["down:CU"][0]) and ("no figure for Cuba" in T["ok:CU"][0]),
                  "\"no figure for\" stays where the home has none: Cuba, the Isle of Man and Zimbabwe (priced in "
                  "dollars, so no rate is missing) with rates out (%r, %r); Cuba, Haiti, Somalia and Zimbabwe with "
                  "rates in, band word and grade note kept (%r) %s"
                  % (text(D["CU:PA"]["guide"]), text(D["ZW:EC"]["guide"]), text(K["HT:EC"]["guide"]),
                     dict(list(bad.items())[:2]))))

# --- the home line: line and ⓘ agree with rates out --------------------------------------
HM = js["home"]
HOME_LINE = "💰 Home prices: the 100% other guides compare to"
HOME_OUT = "💰 Home prices"
OUT_TIP = "Other guides compare with the US for now, because live exchange rates didn't load."
DOLLAR_TIP = ("Guides priced in US dollars compare with prices here; the rest compare with the US for now, because "
              "live exchange rates didn't load.")
HERE_TIP = "Every other guide's percentage is measured against prices here."
UK_TIP = "Every other guide's percentage is measured against UK-wide prices, which apply here too."
OUT = (HOME_OUT, OUT_TIP)
HERE = (HOME_LINE, HERE_TIP)
want = {"down:DE:DE": OUT, "down:IN:IN": OUT, "down:GB:GB": OUT, "down:GB:GB-SCT": OUT,
        "down:PA:PA": (HOME_LINE, DOLLAR_TIP),
        "down:US:US": HERE, "down::US": HERE, "down:CU:CU": HERE, "down:ZW:ZW": HERE,
        "ok:DE:DE": HERE, "ok:IN:IN": HERE, "ok:GB:GB": HERE, "ok:GB:GB-SCT": (HOME_LINE, UK_TIP),
        "ok:US:US": HERE, "ok::US": HERE, "ok:PA:PA": HERE}
bad = {k: (text(HM.get(k)), tip(HM.get(k))) for k in want if (text(HM.get(k)), tip(HM.get(k))) != want[k]}
strip_tip = lambda h: re.sub(r' data-tip="[^"]*"', "", h or "")
results.append(ok(not bad and HM["down:US:US"] == HM["ok:US:US"] == HM["down::US"]
                  and strip_tip(HM["down:DE:DE"]).replace("<b>Home prices</b>", "<b>" + HOME_LINE[2:] + "</b>")
                  == strip_tip(HM["ok:DE:DE"]),
                  "the home line: with rates out a German's, Indian's or British reader's is just \"Home prices\" and "
                  "its ⓘ says other guides compare with the US for now (%r, %r); a Panamanian's keeps its words, its ⓘ "
                  "saying only dollar-priced guides compare with Panama (%r); a US reader's, rates in, and Cuba's or "
                  "Zimbabwe's (no figure) are as before %s"
                  % (text(HM["down:DE:DE"]), tip(HM["down:DE:DE"]), tip(HM["down:PA:PA"]), bad)))

# --- rates in: untouched; US and dollar homes: the same either way --------------------------
# (An Ecuadorian on Ecuador gets the home line, whose ⓘ is a dollar home's with rates out: above.)
same = {k: (D[k]["guide"][:120], K[k]["guide"][:120]) for o in ("US", "", "EC") for k in (o + ":" + i for i in DEST)
        if D[k] != K[k] and k != "EC:EC"}
esc = lambda t: html.escape(t).replace("&#x27;", "&#39;")   # app.js esc()
ec_home = D["EC:EC"]["guide"] == K["EC:EC"]["guide"].replace(esc(HERE_TIP), esc(DOLLAR_TIP)) != K["EC:EC"]["guide"]
results.append(ok(js["ratesOut"]["ok"] == [] and {"DE", "IN", "GB", "TW", "HT", "SO"} <= set(js["ratesOut"]["down"])
                  and not {"US", "EC", "PA", "SV", "TL", "PS", "LR", "ZW", "CU", "IM"} & set(js["ratesOut"]["down"])
                  and ec_home
                  and not any(CLAUSE in json.dumps(v, ensure_ascii=False) for v in K.values())
                  and not same and BAND.search(D["US:EC"]["guide"]) and tip(D["US:EC"]["guide"]).endswith(GRADE)
                  and "same basket at home." in tip(D["US:EC"]["guide"]) and T["down:US"] == T["ok:US"],
                  "with live rates in no country is plRatesOut (%d are with rates out, none of the US, dollar homes "
                  "(Zimbabwe too), Cuba or the Isle of Man); a US or Ecuadorian reader's lines are the same with rates "
                  "out or in %s"
                  % (len(js["ratesOut"]["down"]), dict(list(same.items())[:2]))))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

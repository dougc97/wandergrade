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
    (plRatesOut). Its ⓘ is the US reader's, less the grade note, with "in
    the US, because live exchange rates didn't load" for "at home";
  * the AI prompts say the same plainly: aiPriceWords, the guide prompt's
    LOCAL PRICES line and the trip prompt's "prices" bit read "than the US"
    with no "(no figure for …)";
  * "(no figure for …)" stays exactly where it is true: a home with no
    ppp.json row (Cuba, the Isle of Man) with rates out, and with live rates
    in a home with no row, an implausible price level (Haiti) or no usable
    rate (Somalia), whose lines are the US reader's with the parenthetical
    and "in the US" (no rates-out clause), band word and grade note kept;
  * the reader's own country's home line ("Home prices: the 100% other
    guides compare to") keeps its words with rates out, but a German's on
    Germany or a British reader's on Scotland says in its ⓘ that other
    guides compare with the US for now, because live exchange rates didn't
    load; with rates in, and for a US reader or a home with no figure
    (Cuba), the ⓘ is as before;
  * with live rates in, plRatesOut is false for every country, so no
    rates-in line changes; a US reader's lines, and an Ecuadorian reader's
    (a dollar home needs no rate), are the same with rates out or in.
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
ORIGINS = ["US", "", "DE", "IN", "GB", "TW", "EC", "CU", "IM", "HT", "SO"]
HOMES = [["DE", "DE"], ["IN", "IN"], ["GB", "GB"], ["GB", "GB-SCT"], ["US", "US"], ["", "US"], ["CU", "CU"]]

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
D, K, T = js["down"], js["ok"], js["trip"]
NAME = {"DE": "Germany", "IN": "India", "GB": "the UK", "TW": "Taiwan", "CU": "Cuba", "IM": "the Isle of Man",
        "HT": "Haiti", "SO": "Somalia"}
AI_NAME = dict(NAME, GB="United Kingdom", IM="Isle of Man")

# --- rates out, a home with a figure: no "(no figure for …)" --------------------------------
bad = {}
for o in ("DE", "IN", "GB", "TW"):
    for iso in DEST:
        us, h = D["US:" + iso], D[o + ":" + iso]
        want_line = BAND.sub("<b>Local prices", us["guide"]).split('<span class="fxinfo"')[0]
        want_tip = tip(us["guide"]).replace("against the same basket at home.", "against the same basket in the US"
                                            + CLAUSE + ".").replace(GRADE, "")
        if not (h["guide"].split('<span class="fxinfo"')[0] == want_line and tip(h["guide"]) == want_tip
                and h["lp"] == us["lp"] and "no figure" not in json.dumps(h, ensure_ascii=False)
                and not BAND.search(h["guide"]) and tip(h["guide"]).count(CLAUSE) == 1):
            bad[o + ":" + iso] = (text(h["guide"]), tip(h["guide"])[:200], h["lp"])
results.append(ok(not bad and text(D["DE:EC"]["guide"]) == "💰 Local prices ≈ %s" % D["US:EC"]["lp"][2:]
                  and D["DE:EC"]["lp"] == "≈ 43% of the US" and text(D["GB:PA"]["guide"]) == "💰 Local prices ≈ 48% of the US",
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
results.append(ok(not bad and not tripbad and D["DE:EC"]["ai"] == "~57% cheaper than the US"
                  and D["IN:PA"]["prompt"].startswith("LOCAL PRICES: ~52% cheaper than the US. National averages"),
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
for mode, src, homes in (("down", D, ("CU", "IM")), ("ok", K, ("CU", "HT", "SO"))):
    for o in homes:
        for iso in DEST:
            us, h = src["US:" + iso], src[o + ":" + iso]
            line, t = with_nofig(us, o, mode == "ok")
            if not (h["guide"].split('<span class="fxinfo"')[0] == line and tip(h["guide"]) == t
                    and h["lp"] == us["lp"] + " (no figure for %s)" % NAME[o]
                    and h["ai"] == us["ai"].replace("than home", "than the US").replace("as home", "as the US")
                    + " (no figure for %s)" % AI_NAME[o] and CLAUSE not in tip(h["guide"])):
                bad["%s:%s:%s" % (mode, o, iso)] = (text(h["guide"]), h["ai"], tip(h["guide"])[:160])
results.append(ok(not bad and text(K["HT:EC"]["guide"]) == "💰 Very cheap: local prices ≈ 43% of the US (no figure for Haiti)"
                  and text(D["CU:PA"]["guide"]) == "💰 Local prices ≈ 48% of the US (no figure for Cuba)"
                  and K["SO:PA"]["ai"] == "~52% cheaper than the US (no figure for Somalia)"
                  and ("no figure for Cuba" in T["down:CU"][0]) and ("no figure for Cuba" in T["ok:CU"][0]),
                  "\"no figure for\" stays where the home has none: Cuba and the Isle of Man with rates out (%r); "
                  "Cuba, Haiti and Somalia with rates in, band word and grade note kept (%r) %s"
                  % (text(D["CU:PA"]["guide"]), text(K["HT:EC"]["guide"]), dict(list(bad.items())[:2]))))

# --- the home line: its words kept, its ⓘ true with rates out --------------------------------
HM = js["home"]
HOME_LINE = "💰 Home prices: the 100% other guides compare to"
OUT_TIP = "Other guides compare with the US for now, because live exchange rates didn't load."
HERE_TIP = "Every other guide's percentage is measured against prices here."
UK_TIP = "Every other guide's percentage is measured against UK-wide prices, which apply here too."
want = {"down:DE:DE": OUT_TIP, "down:IN:IN": OUT_TIP, "down:GB:GB": OUT_TIP, "down:GB:GB-SCT": OUT_TIP,
        "down:US:US": HERE_TIP, "down::US": HERE_TIP, "down:CU:CU": HERE_TIP,
        "ok:DE:DE": HERE_TIP, "ok:IN:IN": HERE_TIP, "ok:GB:GB": HERE_TIP, "ok:GB:GB-SCT": UK_TIP,
        "ok:US:US": HERE_TIP, "ok::US": HERE_TIP}
bad = {k: (text(HM.get(k)), tip(HM.get(k))) for k in want if text(HM.get(k)) != HOME_LINE or tip(HM.get(k)) != want[k]}
results.append(ok(not bad and HM["down:US:US"] == HM["ok:US:US"] == HM["down::US"],
                  "the home line keeps its words; with rates out a German's, Indian's or British reader's ⓘ says "
                  "other guides compare with the US for now (%r); a US reader's, rates in, and Cuba's (no figure) "
                  "are as before %s" % (tip(HM["down:DE:DE"]), bad)))

# --- rates in: untouched; US and dollar homes: the same either way --------------------------
same = {k: (D[k]["guide"][:120], K[k]["guide"][:120]) for o in ("US", "", "EC") for k in (o + ":" + i for i in DEST)
        if D[k] != K[k]}
results.append(ok(js["ratesOut"]["ok"] == [] and {"DE", "IN", "GB", "TW", "HT", "SO"} <= set(js["ratesOut"]["down"])
                  and not {"US", "EC", "PA", "CU", "IM"} & set(js["ratesOut"]["down"])
                  and not any(CLAUSE in json.dumps(v, ensure_ascii=False) for v in K.values())
                  and not same and BAND.search(D["US:EC"]["guide"]) and tip(D["US:EC"]["guide"]).endswith(GRADE)
                  and "same basket at home." in tip(D["US:EC"]["guide"]) and T["down:US"] == T["ok:US"],
                  "with live rates in no country is plRatesOut (%d are with rates out, none of the US, dollar homes, "
                  "Cuba or the Isle of Man); a US or Ecuadorian reader's lines are the same with rates out or in %s"
                  % (len(js["ratesOut"]["down"]), dict(list(same.items())[:2]))))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

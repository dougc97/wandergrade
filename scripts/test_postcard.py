"""The Top Picks postcard (a country at a glance): public/app.js
postcardFacts / postcardHTML, run under jsc (scripts/appjs_harness.js) on
scripts/parity/fixture_rates.json and fixture_advisories.json, public/ppp.json,
climate.json, activities.json, visa.json, visa-passport.json and slugs.json.

    /usr/bin/python3 scripts/test_postcard.py

What it holds the code to:
  * three facts in this order: 💰 prices in Top Picks' own words against the
    reader's home (aiPriceWords: plPhrase vs plAnchor(guidePassport())),
    🛂 the VISA_META label for the reader's passport ("your home country" on
    their own), then 📅 the best months (monthSpan of climate.best) or, on a
    row that already names a month, 🧳 "worth N–M days";
  * a non-US reader before /visa-passport.json lands: the visa fact holds its
    place (pending, a non-empty placeholder) and fills with the label after;
  * live rates out (round 10): no "no figure for Germany", the price fact is
    left out where nothing can be priced and a dollar-priced country still
    says "than the US"; no fact is pending once the loads are settled;
  * the markup: "Full guide →" is a real link to /guide/<slug>, the trip
    button reads "🧳 Add to trip" / "✓ On your trip", no photo means the
    flag inside the same .pcphoto box, every interpolated string escaped,
    a map's own fact appended last, and a map card's ✓ Been / ★ Want to go;
  * the photo (postcardPhoto): the guide hero's first (iconicPhotos, stubbed
    here), 330px with a 500px 2x, Wikimedia's thumbnail steps only (an
    unscaled original too), alt naming the place, a credit linking the file
    page; one lookup per country (the same promise), a failed or empty one
    resolves null and is asked again on the next open.
"""
import html, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "ppp": load("public", "ppp.json"), "climate": load("public", "climate.json"),
       "activities": load("public", "activities.json"), "slugs": load("public", "slugs.json"),
       "visa": load("public", "visa.json"), "matrix": load("public", "visa-passport.json")}

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
advisories = FIX.advisories; activities = FIX.activities; climate = FIX.climate; ppp = FIX.ppp;
lastRates = FIX.rates; visa = FIX.visa; visaMatrix = null;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
const setOrigin = (o) => { localStorage.removeItem("fx_origin"); if (o) localStorage.setItem("fx_origin", o); };
const out = {};
const T = (name, f) => { try { out[name] = f(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; } };
const card = (iso, o) => postcardHTML(iso, Object.assign({ rowHasMonth: false, mapFact: null, photo: null,
                                                          inTrip: false, secondary: false }, o || {}));
setOrigin("US");
T("a", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
T("a_want", () => "💰 " + plPhrase(priceLevel("JP") / plAnchor("US").pl, plAnchor("US").name));
T("a_months", () => "📅 " + monthSpan(climate.JP.best));
T("b", () => postcardFacts("JP", { rowHasMonth: true, mapFact: null }));
setOrigin("JP");
T("c", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
setOrigin("DE");
T("d", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
T("d_html", () => card("JP"));
visaMatrix = FIX.matrix;
T("d2", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
T("d2_want", () => "🛂 " + VISA_META[visaInfo("JP", "DE").status].label);
T("de_price", () => postcardFacts("TH", { rowHasMonth: false, mapFact: null }));
setOrigin("US");
T("e0", () => card("JP"));
T("e1", () => card("JP", { inTrip: true }));
T("f", () => card("JP", { photo: { src: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/330px-X.jpg",
  srcset: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/330px-X.jpg 1x", alt: "Fushimi Inari, Japan",
  credit: { text: "📷 Someone · CC BY-SA 4.0", href: "https://commons.wikimedia.org/wiki/File:X.jpg" } } }));
const keep = activities.JP;
activities = Object.assign({}, activities, { JP: Object.assign({}, keep, { summary: '<b>Temples</b> & "food"' }) });
T("g", () => card("JP", { photo: { src: 'https://upload.wikimedia.org/x.jpg"><script>', srcset: "", alt: '<img src=x onerror=alert(1)>',
  credit: { text: '<i>me</i>', href: 'https://commons.wikimedia.org/wiki/File:"x' } }, mapFact: esc("💱 <JPY>") }));
activities = FIX.activities;
const MF = "💱 JPY: your USD +1.2% vs 1-yr avg after inflation";
T("h", () => postcardFacts("JP", { rowHasMonth: false, mapFact: MF }));
T("h_html", () => card("JP", { mapFact: MF, secondary: true }));
// Live rates out (round 10): a German reader can't be priced today, nor can Japan.
lastRates = null; ratesDown = true; setOrigin("DE");
T("r_jp", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
T("r_ec", () => postcardFacts("EC", { rowHasMonth: false, mapFact: null }));
T("r_ec_want", () => aiPriceWords("EC", plAnchor("DE").name));
// Settled with nothing loaded: nothing pending, nothing invented.
lastRates = FIX.rates; ratesDown = false; setOrigin("FR"); visaMatrix = null;
const keepC = climate; climate = null;
T("s_pending", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null }));
T("s_settled", () => postcardFacts("JP", { rowHasMonth: false, mapFact: null, settled: true }));
climate = keepC;
// The photo loader, on a stubbed iconicPhotos (the guide hero's lookup).
// wmThumbAt measures a file name's bytes with TextEncoder, which browsers
// have and jsc doesn't.
if (typeof TextEncoder === "undefined") this.TextEncoder = function () { this.encode = (s) => ({ length: unescape(encodeURIComponent(s)).length }); };
const W = "https://upload.wikimedia.org/wikipedia/commons/";
let calls = 0, mode = "ok";
iconicPhotos = async (iso) => {
  calls++;
  if (mode === "throw") throw new Error("api down");
  if (mode === "empty") return [];
  if (iso === "IS") return [{ thumb: W + "a/ab/Small_falls.jpg", full: W + "a/ab/Small_falls.jpg", w: 900, file: "Small_falls.jpg", place: "Gullfoss" }];
  return [{ thumb: W + "thumb/1/12/Fushimi.jpg/1600px-Fushimi.jpg", full: W + "1/12/Fushimi.jpg", file: "Fushimi.jpg", place: "Fushimi Inari-taisha", ar: 1.5 },
          { thumb: W + "thumb/3/34/Second.jpg/1600px-Second.jpg", full: W + "3/34/Second.jpg", file: "Second.jpg", place: "Kyoto" }];
};
(async () => {
  setOrigin("US");
  const p1 = postcardPhoto("JP"), p2 = postcardPhoto("JP");
  out.ph_same = p1 === p2;
  out.ph = await p1;
  out.ph_calls1 = calls;
  out.ph_again = (await postcardPhoto("JP")) === out.ph;
  out.ph_calls2 = calls;
  out.ph_now = postcardPhotoNow("JP") === out.ph;
  out.ph_orig = await postcardPhoto("IS");
  out.ph_html = postcardHTML("JP", { rowHasMonth: false, mapFact: null, photo: out.ph, inTrip: false, secondary: false });
  mode = "throw"; calls = 0;
  out.ph_throw = await postcardPhoto("TH");
  out.ph_throw_retry = (await postcardPhoto("TH"), calls);
  mode = "empty";
  out.ph_empty = await postcardPhoto("VN");
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-800:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
    sys.exit(1)
errs = {k: v["error"] for k, v in js.items() if isinstance(v, dict) and "error" in v}
results.append(ok(not errs, "every case ran %s" % (json.dumps(errs)[:600] if errs else "")))

ks = lambda facts: [f["k"] for f in facts] if isinstance(facts, list) else facts
fact = lambda facts, k: next((f for f in facts if f["k"] == k), None) if isinstance(facts, list) else None
txt = lambda h: html.unescape(re.sub(r"<[^>]+>", "", h if isinstance(h, str) else ""))
S = lambda k: js.get(k) if isinstance(js.get(k), str) else ""

# (a) the three facts, in order, in Top Picks' words
a = js.get("a")
results.append(ok(ks(a) == ["price", "visa", "months"], "JP for a US reader: price, visa, months (%s)" % ks(a)))
pa = fact(a, "price")
results.append(ok(pa and txt(pa["html"]) == S("a_want") and re.search(r"(cheaper|pricier) than the US|about the same as the US", txt(pa["html"])),
                  "price fact is plPhrase vs plAnchor(guidePassport()) (%r)" % (pa and txt(pa["html"]))))
va = fact(a, "visa")
results.append(ok(va and txt(va["html"]) == "🛂 Visa-free" and not va["pending"], "visa fact is VISA_META's label (%r)" % (va and va["html"])))
ma = fact(a, "months")
results.append(ok(ma and txt(ma["html"]) == S("a_months"), "months fact is monthSpan(climate.best) (%r)" % (ma and ma["html"])))
results.append(ok(isinstance(a, list) and all(not f["pending"] for f in a), "nothing pending with everything loaded"))

# (b) a row that names a month: days instead of months
b = js.get("b")
results.append(ok(ks(b) == ["price", "visa", "days"] and txt((fact(b, "days") or {}).get("html")) == "🧳 worth 10–21 days",
                  "rowHasMonth: third fact is 🧳 worth 10–21 days (%s)" % (b if not isinstance(b, list) else [txt(f["html"]) for f in b])))

# (c) the reader's own country
c = js.get("c")
vc = fact(c, "visa")
results.append(ok(vc and "your home country" in txt(vc["html"]), "own country: 🛂 your home country (%r)" % (vc and vc["html"])))
pc = fact(c, "price")
results.append(ok(not pc or "than Japan" not in txt(pc["html"]), "own country: no 'cheaper than Japan' about Japan (%r)" % (pc and pc["html"])))

# (d) a German reader before the matrix lands, and after
d = js.get("d")
vd = fact(d, "visa")
results.append(ok(vd and vd["pending"] and txt(vd["html"]).strip() not in ("", "🛂"),
                  "DE before visa-passport.json: visa fact pending with a reserved placeholder (%r)" % vd))
results.append(ok(ks(d) == ["price", "visa", "months"], "DE before the matrix: still three facts in order (%s)" % ks(d)))
results.append(ok('class="pcfact pcpend" data-k="visa"' in S("d_html"), "the pending fact is marked in the markup"))
d2 = js.get("d2")
vd2 = fact(d2, "visa")
results.append(ok(vd2 and not vd2["pending"] and txt(vd2["html"]) == S("d2_want"), "DE after the matrix: the label (%r)" % (vd2 and vd2["html"])))
pde = fact(js.get("de_price"), "price")
results.append(ok(pde and "than Germany" in txt(pde["html"]), "DE reader, rates in: prices against Germany (%r)" % (pde and pde["html"])))

# (e) the buttons
e0, e1 = S("e0"), S("e1")
g = re.search(r'<a [^>]*href="([^"]+)"[^>]*>([^<]*)</a>', e0[e0.find("pcguide") - 40:] if "pcguide" in e0 else "")
results.append(ok(g and g.group(1) == "/guide/japan" and g.group(2) == "Full guide →", "Full guide → links /guide/japan (%s)" % str(g and g.groups())))
results.append(ok("🧳 Add to trip" in txt(e0) and "On your trip" not in txt(e0), "not on the trip: 🧳 Add to trip"))
results.append(ok("✓ On your trip" in txt(e1) and "Add to trip" not in txt(e1), "on the trip: ✓ On your trip"))
results.append(ok("✓ Been" not in txt(e0) and "Want to go" not in txt(e0), "a row's postcard has just the two buttons"))

# (f) the photo box
m0 = re.search(r'<div class="pcphoto[^"]*">(.*?)</div>', e0, re.S)
results.append(ok(m0 and "🇯🇵" in m0.group(1) and "<img" not in m0.group(1), "no photo: the flag inside .pcphoto"))
f = S("f")
m1 = re.search(r'<div class="pcphoto[^"]*">(.*?)</div>', f, re.S)
results.append(ok(m1 and '<img class="pcimg"' in m1.group(1) and 'alt="Fushimi Inari, Japan"' in m1.group(1)
                  and "330px-X.jpg" in m1.group(1) and "pccredit" in m1.group(1),
                  "a photo: the img (alt = the place) and its credit ⓘ inside the same box"))

# (g) escaping
gg = S("g")
results.append(ok("&lt;b&gt;Temples&lt;/b&gt; &amp; &quot;food&quot;" in gg and "<b>Temples" not in gg, "summary escaped"))
results.append(ok("<img src=x" not in gg and "<script>" not in gg and "<i>me" not in gg and '"x"' not in gg,
                  "photo alt, src, credit text and href escaped"))
results.append(ok("💱 &lt;JPY&gt;" in gg, "the map fact goes in as given (already escaped by its maker)"))

# (h) a map card
h = js.get("h")
results.append(ok(ks(h) == ["price", "visa", "months", "map"] and (fact(h, "map") or {}).get("html") == "💱 JPY: your USD +1.2% vs 1-yr avg after inflation",
                  "mapFact appended last as k=map (%s)" % ks(h)))
hh = S("h_html")
results.append(ok("✓ Been" in txt(hh) and "★ Want to go" in txt(hh) and "Full guide →" in txt(hh) and "Add to trip" in txt(hh),
                  "secondary: ✓ Been and ★ Want to go beside the two buttons"))
results.append(ok("Japan" in txt(hh), "a map card names its country"))

# Live rates out
rj, rec = js.get("r_jp"), js.get("r_ec")
results.append(ok(isinstance(rj, list) and fact(rj, "price") is None and all("no figure" not in f["html"] for f in rj),
                  "rates out, DE reader, Japan: no price fact, no 'no figure for' (%s)" % rj))
pe = fact(rec, "price")
results.append(ok(pe and txt(pe["html"]) == "💰 " + S("r_ec_want") and "than the US" in pe["html"] and "no figure" not in pe["html"],
                  "rates out, DE reader, Ecuador: '%s'" % (pe and txt(pe["html"]))))
results.append(ok(isinstance(rj, list) and not any(f["pending"] for f in rj), "rates known down: nothing waits for them"))

# Pending vs settled
sp_, ss = js.get("s_pending"), js.get("s_settled")
results.append(ok(isinstance(sp_, list) and (fact(sp_, "months") or {}).get("pending") and (fact(sp_, "visa") or {}).get("pending"),
                  "climate and the matrix still loading: months and visa pending (%s)" % sp_))
results.append(ok(isinstance(ss, list) and not any(f["pending"] for f in ss) and fact(ss, "months") is None and fact(ss, "visa") is None,
                  "settled with neither: both left out, nothing pending (%s)" % ss))

# The photo loader
STEPS = {20, 40, 60, 120, 250, 330, 400, 500, 960, 1280, 1920, 3840}
ph, po = js.get("ph"), js.get("ph_orig")
widths = lambda p: [int(w) for w in re.findall(r"/(\d+)px-", (p or {}).get("src", "") + " " + (p or {}).get("srcset", ""))]
results.append(ok(isinstance(ph, dict) and "/330px-Fushimi.jpg" in ph.get("src", "") and "Second" not in json.dumps(ph),
                  "the hero's first photo, at 330px (%s)" % (ph or {}).get("src")))
results.append(ok(isinstance(ph, dict) and "/500px-Fushimi.jpg 2x" in ph.get("srcset", "") and "/330px-Fushimi.jpg 1x" in ph.get("srcset", ""),
                  "500px on a 2x screen (%s)" % (ph or {}).get("srcset")))
results.append(ok(isinstance(ph, dict) and ph.get("alt") == "Fushimi Inari-taisha, Japan", "alt names the place (%r)" % (ph or {}).get("alt")))
results.append(ok(isinstance(ph, dict) and (ph.get("credit") or {}).get("href", "").endswith("File:Fushimi.jpg")
                  and "Wikimedia Commons" in (ph.get("credit") or {}).get("text", ""),
                  "credit links the file page before its author is known (%s)" % (ph or {}).get("credit")))
results.append(ok(isinstance(po, dict) and "/thumb/a/ab/Small_falls.jpg/330px-Small_falls.jpg" in po.get("src", "")
                  and "/500px-Small_falls.jpg 2x" in po.get("srcset", ""),
                  "an unscaled original gets real thumbnails (%s | %s)" % ((po or {}).get("src"), (po or {}).get("srcset"))))
bad = [w for w in widths(ph) + widths(po) if w not in STEPS]
results.append(ok(widths(ph) and widths(po) and not bad, "only Wikimedia's thumbnail steps (%s)" % (widths(ph) + widths(po))))
results.append(ok(js.get("ph_same") is True and js.get("ph_calls1") == 1 and js.get("ph_again") is True and js.get("ph_calls2") == 1,
                  "one lookup per country: the same promise, iconicPhotos asked once (%s, %s)" % (js.get("ph_calls1"), js.get("ph_calls2"))))
results.append(ok(js.get("ph_now") is True, "postcardPhotoNow hands back the landed photo at once (no flicker on a redraw)"))
pm = re.search(r'<div class="pcphoto[^"]*">(.*?)</div>', S("ph_html"), re.S)
results.append(ok(pm and "330px-Fushimi.jpg" in pm.group(1) and "500px-Fushimi.jpg 2x" in pm.group(1), "the loader's photo drops into the markup"))
results.append(ok(js.get("ph_throw") is None and "ph_throw" in js, "a lookup that throws resolves null"))
results.append(ok(js.get("ph_throw_retry") == 2, "and is asked again on the next open (calls %s)" % js.get("ph_throw_retry")))
results.append(ok(js.get("ph_empty") is None and "ph_empty" in js, "no photo found: null (the flag shows)"))

print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
sys.exit(0 if all(results) else 1)

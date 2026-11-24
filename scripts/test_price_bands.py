"""The price-level band words — "very cheap", "cheap", "a bit cheaper",
"about the same", "pricey" — one way on every surface (review #20, Nov 2026):
"cheap" used to run from 55% to 90% of US prices, so France at 75%, Germany
at 80% and the Bahamas at 90% were all called cheap. No network, no server.

    /usr/bin/python3 scripts/test_price_bands.py

What it holds the code to:
  * guide_facts.band (the server's copy: guide titles and descriptions, the
    list pages' price cells, /dollar-strength) cuts at the printed two
    decimals: under 0.55 very cheap, under 0.75 cheap, to 0.90 a bit
    cheaper, to 1.10 about the same, then pricey — binary edges included
    (0.545 prints 0.55, 0.745 prints 0.74, 0.905 prints 0.91);
  * app.js plWord (map tips, the Cost of living and Currency tables'
    plTag) gives the same word as band for every price level from 0.10 to
    1.50 in steps of 0.0005 and on those edges, run under jsc;
  * the scoring's three-way plBand is unchanged: -1 to 0.90, 0 to 1.10;
  * a guide at 75-90% still asks "Is X Cheap to Visit?" (render_guide.
    _band_q; whether those titles should change waits on Search Console)
    and its description says "(a bit cheaper)".
"""
import datetime, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_facts as GF, render_guide as rg  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


# --- the server's copy ------------------------------------------------------------
EDGES = {0.10: "very cheap", 0.5449: "very cheap", 0.545: "cheap", 0.55: "cheap", 0.7449: "cheap",
         0.745: "cheap", 0.7451: "a bit cheaper", 0.75: "a bit cheaper", 0.80: "a bit cheaper",
         0.90: "a bit cheaper", 0.904: "a bit cheaper", 0.905: "about the same", 1.0: "about the same",
         1.10: "about the same", 1.104: "about the same", 1.105: "about the same", 1.1051: "pricey",
         1.5: "pricey"}
off = [(x, GF.band(x), w) for x, w in EDGES.items() if GF.band(x) != w]
results.append(ok(not off, "guide_facts.band on the printed two decimals: very cheap < 0.55 <= cheap < 0.75 <= "
                  "a bit cheaper <= 0.90 < about the same <= 1.10 < pricey, binary edges included%s"
                  % ("" if not off else " -> %r" % off)))

# --- the browser's copy, under jsc --------------------------------------------------
grid = sorted(set([round(0.10 + i * 0.0005, 4) for i in range(2801)] + list(EDGES)))
pieces = [js_const("PL_SAME"), js_const("plShown"), js_fn("plBand"), js_fn("plWord")]
prog = "\n".join(pieces) + "\nprint(JSON.stringify(%s.map((x) => [plWord(x), plBand(x)])));" % json.dumps(grid)
try:
    js = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception as e:   # no jsc, or it printed nothing: a FAIL below
    js = None
    print("  jsc: %r" % e)
off = [(x, w, GF.band(x)) for x, (w, _b) in zip(grid, js or [])] if js else None
off = [o for o in off if o[1] != o[2]] if off is not None else None
results.append(ok(all(pieces) and js and len(js) == len(grid) and not off,
                  "app.js plWord gives guide_facts.band's word for all %d price levels 0.10-1.50 (step 0.0005) "
                  "and the edges%s" % (len(grid), "" if not off else " -> %r" % off[:5])))
bands = {GF.band(x): b for x, (_w, b) in zip(grid, js or [])}
results.append(ok(js and bands == {"very cheap": -1, "cheap": -1, "a bit cheaper": -1, "about the same": 0, "pricey": 1},
                  "plBand stays three-way: the three cheaper words are all -1 (cheaper), about the same 0, "
                  "pricey 1 %s" % bands))

# --- the title question and the description -----------------------------------------
f = {"pct": 80, "band": GF.band(0.80), "adv": 1, "src": "us"}
m = rg.meta("DE", f, datetime.date(2026, 11, 1))
results.append(ok(f["band"] == "a bit cheaper" and rg._band_q(f) == "Cheap"
                  and m["title"].startswith("Is Germany Cheap to Visit?")
                  and "local prices ≈ 80% of the US (a bit cheaper)." in m["desc"],
                  "a guide at 80%% asks \"Is Germany Cheap to Visit?\" and says \"(a bit cheaper)\": %r / %r"
                  % (m["title"], m["desc"])))
results.append(ok(rg._band_q({"band": "about the same"}) == "Expensive" and rg._band_q({"band": "pricey"}) == "Expensive"
                  and rg._band_q({"band": "very cheap"}) == "Cheap" and rg._band_q({"band": "cheap"}) == "Cheap",
                  "the other bands ask what they asked: very cheap and cheap \"Cheap\", about the same and "
                  "pricey \"Expensive\""))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

"""Top Picks' first paint: the two inline scripts in public/index.html that
write the map heading (h2#valueMapTitle) and the ranked row's label
(.mappicksrow.skel[data-for="valueMap"]) before the page draws, run under jsc
against what app.js writes once it lands — renderValue's title statement and
renderMapPicksOverlay's label, cut out of app.js by name — so the words never
change in front of the reader.

  Any time (no vmn=, vmn=0 or junk, or vmf=1 beside any vmn): "Best value in
  the next 6 months" / "Best value · next 6 months"; Best weather (vmm=weather)
  "Best weather in the next 6 months", and the row is removed;
  a real month (vmn=1-12, no vmf=1): "Best value destinations in March" /
  "Best value in March", "Weather comfort in March" in Best weather.

    /usr/bin/python3 scripts/test_anytime_prepaint.py
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def jsc(prog):
    try:
        return json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
    except Exception:
        return None


MONTHS = re.search(r"^const MONTHS = \[.*?\];$", APP, re.M | re.S).group(0)
title_stmt = re.search(r"if \(vTitle\) vTitle\.textContent = flex\n.*?;\n", APP, re.S)
overlay = js_fn("renderMapPicksOverlay")
SCRIPTS = re.findall(r"<script>(.*?)</script>", HTML, re.S)
pre_h = next((x for x in SCRIPTS if 'getElementById("valueMapTitle")' in x), None)
pre_r = next((x for x in SCRIPTS if 'data-for="valueMap"]' in x), None)
results.append(ok(title_stmt and overlay and pre_h and pre_r,
                  "found renderValue's title statement, renderMapPicksOverlay, and both inline scripts"))

# A page as far as the two scripts see it: location.search, the h2 and the row.
STUBS = r"""
function URLSearchParams(s) { var o = {}; (s || "").replace(/^\?/, "").split("&").forEach(function (kv) {
  if (!kv) return; var i = kv.indexOf("="), k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
  if (!(k in o)) o[k] = i < 0 ? "" : decodeURIComponent(kv.slice(i + 1)); });
  this.get = function (k) { return k in o ? o[k] : null; }; }
var h2 = { textContent: "Best value destinations" };
var row = { removed: false, firstChild: { textContent: "Best value in October" }, remove: function () { this.removed = true; } };
var document = { getElementById: function (id) { return id === "valueMapTitle" ? h2 : null; },
                 querySelector: function (s) { return s === '.mappicksrow.skel[data-for="valueMap"]' ? row : null; } };
"""
# app.js's state for a link, as postApplyShared sets it: vmf=1 wins; else a vmn
# that is one of the select's options ("1".."12") is a real month; else Any time.
CASES = ["", "?vmn=3", "?vmn=12", "?vmn=3&vmf=1", "?vmf=1", "?vmn=0", "?vmn=13", "?vmn=3x", "?vmm=weather",
         "?vmm=weather&vmn=3", "?vmm=weather&vmf=1&vmn=3", "?gc=JP&vmn=7", "?utm_source=x"]
bad = []
for q in CASES:
    p = dict(kv.split("=", 1) for kv in q[1:].split("&") if kv)
    real = p.get("vmf") != "1" and p.get("vmn") in [str(i) for i in range(1, 13)]
    mode = "weather" if p.get("vmm") == "weather" else "score"
    prog = STUBS + "var location = {search: %s};\n" % json.dumps(q) + pre_h + "\n" + pre_r + "\n" + MONTHS + """
var valueMapMode = %s, flex = %s, month = %s, vTitle = { textContent: "" }, label = null;
function $(id) { return null; }
function renderDimPicks(host, t) { label = t; }
%s
%s
renderMapPicksOverlay([], month, "valueMap", flex);
print(JSON.stringify({pre: [h2.textContent, row.removed ? null : row.firstChild.textContent],
                      app: [vTitle.textContent, valueMapMode === "weather" ? null : label]}));
""" % (json.dumps(mode), "false" if real else "true", int(p["vmn"]) if real else 0, title_stmt.group(0), overlay)
    r = jsc(prog)
    if not r or r["pre"] != r["app"]:
        bad.append((q or "(none)", r))
    elif q in ("", "?vmm=weather", "?vmn=3"):
        print("        %-12s %s" % (q or "(none)", r["pre"]))
results.append(ok(r is not None and not bad,
                  "the pre-paint heading and row equal app.js's for %d links (Any time, real months, vmf=1, "
                  "junk vmn, Best weather) %s" % (len(CASES), bad or "")))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

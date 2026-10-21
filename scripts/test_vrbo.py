#!/usr/bin/env python3
"""The guide's Vrbo button (Stay22's /allez/vrbo) and its stand-in, without
the network or a server process.

    /usr/bin/python3 scripts/test_vrbo.py

  * app.js vrboOK (run under jsc with the real regionOf, continentOf and
    region tables) and fxtracker/guide_sizers.vrbo() say the same for every
    guide and every country with stays: the Americas, Europe and Oceania
    less Russia, Papua New Guinea and the Solomon Islands, plus Thailand,
    Indonesia, South Africa and Morocco (Portugal, Mexico, Australia, Puerto
    Rico, England yes; Japan, Kenya, the UAE no);
  * the served stays stand-in has the button exactly where vrbo() says;
  * renderGuideStay under jsc (its page stubbed) draws the same buttons in
    the same order as the stand-in (Booking.com, Vrbo, Hostelworld; no Vrbo
    for Japan or Kenya), and the Vrbo link is
    https://www.stay22.com/allez/vrbo with aid=wandergrade, the chosen
    spot's lat and lng and the stay's checkin and checkout — Booking's own
    query — opened sponsored in a new tab;
  * the Trip tab keeps its single Booking.com Stays link.
"""
import json
import os
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_sizers  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):
    """A top-level const or let: one line, or a block up to its closing line
    ("};" or "})();")."""
    m = re.search(r"^(?:const|let) %s = [^\n]*;$" % re.escape(name), APP, re.M)
    if m and not m.group(0).rstrip(";").endswith(("{", "(() => {")):
        return m.group(0)
    m = re.search(r"^(?:const|let) %s = .*?^\}\)?(?:\(\))?;$" % re.escape(name), APP, re.M | re.S)
    return m.group(0) if m else ""


def load(name):
    with open(os.path.join(ROOT, "public", name), encoding="utf-8") as f:
        return json.load(f)


slugs, coords = load("slugs.json"), load("stay-coords.json")
ISOS = sorted(set(slugs.values()) | set(coords))
REGION_JS = "\n".join([js_const("REGIONS"), js_const("ISO_REGION"), js_const("EXTRA_CONTINENT"),
                       js_const("_SOUTH_AMERICA"), js_const("_MENA_AFRICA"), js_fn("continentOf"), js_fn("regionOf"),
                       js_const("VRBO_REGIONS"), js_const("VRBO_ALSO"), js_const("VRBO_NOT"), js_fn("vrboOK")])


def run(prog):
    try:
        p = subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout) if p.stdout.strip() else {"error": p.stderr[:300]}
    except Exception as e:
        return {"error": str(e)}


# --- which countries ---------------------------------------------------------------
js = run(REGION_JS + "\nconst I = %s, o = {};\nfor (const i of I) o[i] = vrboOK(i);\nprint(JSON.stringify(o));" % json.dumps(ISOS))
py = {iso: guide_sizers.vrbo(iso) for iso in ISOS}
diff = [i for i in ISOS if js.get(i) is not py[i]]
results.append(ok(not diff and len(js) == len(ISOS),
                  "app.js vrboOK and guide_sizers.vrbo agree on all %d guides and stay countries (differ: %s%s)"
                  % (len(ISOS), diff[:8], " " + js["error"] if "error" in js else "")))
yes = ["PT", "MX", "AU", "US", "CA", "GB-ENG", "PR", "CR", "BR", "FJ", "NZ", "TR", "TH", "ID", "ZA", "MA"]
no = ["JP", "KE", "ET", "AE", "EG", "IN", "CN", "VN", "RU", "PG", "SB", "TF", "AQ"]
results.append(ok(all(py[i] for i in yes) and not any(py[i] for i in no),
                  "Vrbo for %s; none for %s (got %s)" % (" ".join(yes), " ".join(no),
                                                         {i: py[i] for i in yes + no if py[i] != (i in yes)})))
guides = sorted(set(slugs.values()))
print("        %d of %d guides get Vrbo" % (sum(py[i] for i in guides), len(guides)))

# --- the stand-in ------------------------------------------------------------------
LABELS = re.compile(r'<a class="staybtn"[^>]*>(.*?) <span class="ext">')
wrong = []
for iso in sorted(coords):
    h = guide_sizers.stay(iso)
    if h and (("🏡 Vrbo" in h) is not py[iso] or LABELS.findall(h)[0] != "🏨 Booking.com"):
        wrong.append(iso)
results.append(ok(not wrong, "the stays stand-in has the Vrbo button exactly where vrbo() says (wrong: %s)" % wrong[:8]))

# --- renderGuideStay under jsc -------------------------------------------------------
PICK = ["PT", "MX", "AU", "TH", "MA", "GB-ENG", "JP", "KE"]
DATES = {"checkin": "2026-11-15", "checkout": "2026-11-18"}
prog = "\n".join([js_const("esc"), REGION_JS, js_const("STAY22_AID"), js_const("HW_COUNTRY"), js_fn("hostelworldURL"),
                  "let _staySpotIdx = 0, _staySpotIso = null, _ssrNoStay = null;", js_fn("renderGuideStay")]) + """
const COORDS = %s, DATES = %s, PICK = %s, out = {};
let host = null, ccGuideIso = null, advisories = null;
const window = {}, $ = (id) => (id === "guideStay" ? host : null), holdSizer = () => {};
const guideNoBookings = () => false, dntSettled = () => true;
const ensureStayCoords = () => Promise.resolve(COORDS), ensureBookingsKnown = () => Promise.resolve(null);
const stayDates = () => DATES;
(async () => {
  for (const iso of PICK) {
    host = { innerHTML: "", hidden: true, style: {}, firstChild: null, querySelectorAll: () => [] };
    ccGuideIso = iso;
    renderGuideStay(iso);
    for (let k = 0; k < 20; k++) await null;
    out[iso] = host.innerHTML;
  }
  print(JSON.stringify(out));
})();""" % (json.dumps({i: coords[i] for i in PICK}), json.dumps(DATES), json.dumps(PICK))
drawn = run(prog)
same, links = {}, {}
for iso in PICK:
    h = drawn.get(iso) or ""
    same[iso] = bool(h) and LABELS.findall(h) == LABELS.findall(guide_sizers.stay(iso))
    a = re.findall(r'<a class="staybtn" target="_blank" rel="([^"]*)" href="([^"]*)">🏡 Vrbo ', h)
    b = re.findall(r'href="(https://www\.stay22\.com/allez/booking\?[^"]*)"', h)
    links[iso] = (a[0] if a else None, b[0] if b else None)
results.append(ok(all(same.values()), "renderGuideStay draws the stand-in's buttons in its order (%s%s)"
                  % (same, " " + drawn["error"] if "error" in drawn else "")))
results.append(ok([LABELS.findall(drawn.get(i) or "") for i in ("PT", "JP")]
                  == [["🏨 Booking.com", "🏡 Vrbo", "🎒 Hostelworld"], ["🏨 Booking.com", "🎒 Hostelworld"]],
                  "Portugal: Booking.com, Vrbo, Hostelworld; Japan: Booking.com, Hostelworld"))
good = []
for iso in PICK:
    (vr, booking) = links[iso]
    if not py[iso]:
        good.append(vr is None)
        continue
    rel, href = vr or ("", "")
    u = urlsplit(href.replace("&amp;", "&"))
    q = parse_qs(u.query)
    ll = coords[iso][0]["ll"]
    good.append(u.scheme == "https" and u.netloc == "www.stay22.com" and u.path == "/allez/vrbo"
                and q == {"aid": ["wandergrade"], "lat": [str(ll[0])], "lng": [str(ll[1])],
                          "checkin": [DATES["checkin"]], "checkout": [DATES["checkout"]]}
                and "sponsored" in rel.split() and booking and booking.split("?")[1] == href.split("?")[1])
results.append(ok(all(good), "the Vrbo link: stay22.com/allez/vrbo?aid=wandergrade&lat&lng&checkin&checkout on the "
                  "chosen spot, Booking's query, rel sponsored; none where vrboOK says no (%s)"
                  % dict(zip(PICK, good))))

# --- the Trip tab is unchanged ---------------------------------------------------------
trip = js_fn("renderTripBook")
results.append(ok("allez/booking" in trip and "allez/vrbo" not in trip and "vrboOK" not in trip,
                  "the Trip tab keeps its one Booking.com Stays link"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

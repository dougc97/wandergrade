#!/usr/bin/env python3
"""The guide's Hostelworld button goes through Partnerize, in the link format
the Partnerize console's link generator writes, without the network or a
server process (nothing here requests prf.hn or hostelworld.com: a request
would count as a click in the owner's stats).

    /usr/bin/python3 scripts/test_hostelworld_link.py

  * app.js HW_CAMREF is Hostelworld's camref, 1101l5NoBM;
  * hostelworldURL (run under jsc with the real HW_COUNTRY) returns exactly
    the console's format,
      https://hostelworld.prf.hn/click/camref:<camref>/pubref:guide-<ISO>/destination:<page, URL-encoded>
    for Vietnam and Japan (typed out in full), Thailand, the UK (England's
    page stands in), England, Guernsey (filed under England) and the
    Falklands (no Hostelworld page: the homepage);
  * for every guide, every country with stays and every HW_COUNTRY entry the
    destination decodes to the plain Hostelworld URL the site linked before
    (the country page, or the homepage), the pubref is "guide-" and the ISO
    in letters, digits and hyphens, and nothing in the link needs escaping
    inside the href attribute renderGuideStay writes it into;
  * renderGuideStay under jsc (its page stubbed, as scripts/test_vrbo.py
    does) draws the Hostelworld button with that href, opened in a new tab
    with rel="sponsored nofollow noopener", like Booking.com and Vrbo;
  * the served stand-in (fxtracker/guide_sizers.stay) keeps its Hostelworld
    button without an href, and no other Hostelworld link is written
    anywhere: app.js outside hostelworldURL, index.html, server.py,
    fxtracker/*.py (the newsletter and llms.txt included).
"""
import glob
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_sizers  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()
CAMREF = "1101l5NoBM"


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


def run(prog):
    try:
        p = subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout) if p.stdout.strip() else {"error": p.stderr[:300]}
    except Exception as e:
        return {"error": str(e)}


def console(iso, page):
    """The console's link: encodeURIComponent's escaping (quote keeps the
    same unreserved set with this `safe`)."""
    return ("https://hostelworld.prf.hn/click/camref:%s/pubref:guide-%s/destination:%s"
            % (CAMREF, iso, quote(page, safe="-_.!~*'()")))


# --- the camref ----------------------------------------------------------------------
results.append(ok(js_const("HW_CAMREF") == 'const HW_CAMREF = "%s";' % CAMREF,
                  "app.js HW_CAMREF is %s (%s)" % (CAMREF, js_const("HW_CAMREF") or "missing")))

# --- hostelworldURL ------------------------------------------------------------------
slugs, coords = load("slugs.json"), load("stay-coords.json")
hw_block = js_const("HW_COUNTRY")
HW_ISOS = set(re.findall(r"\b([A-Z]{2}(?:-[A-Z]{3})?):", hw_block))
ALL = sorted(set(slugs.values()) | set(coords) | HW_ISOS)
# The plain link the site used before Partnerize (main 6dda6fa's hostelworldURL).
OLD = """function oldURL(iso) {
  return HW_COUNTRY[iso] ? "https://www.hostelworld.com/hostels/" + HW_COUNTRY[iso] + "/"
                         : "https://www.hostelworld.com/";
}"""
prog = "\n".join([js_const("HW_CAMREF"), hw_block, js_fn("hostelworldURL"), OLD]) + """
const I = %s, o = {};
for (const i of I) o[i] = { url: hostelworldURL(i), old: oldURL(i) };
const m = (u) => /^https:\\/\\/hostelworld\\.prf\\.hn\\/click\\/camref:([^/]+)\\/pubref:([^/]+)\\/destination:([^/]+)$/.exec(u);
for (const i of I) { const x = m(o[i].url); o[i].dest = x ? decodeURIComponent(x[3]) : null; o[i].pubref = x ? x[2] : null; }
print(JSON.stringify(o));""" % json.dumps(ALL)
got = run(prog)
err = " " + got["error"] if "error" in got else ""

VN = ("https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-VN/destination:"
      "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fasia%2Fvietnam%2F")
JP = ("https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-JP/destination:"
      "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fasia%2Fjapan%2F")
url = lambda iso: (got.get(iso) or {}).get("url")
results.append(ok(url("VN") == VN and url("JP") == JP,
                  "Vietnam and Japan: exactly the console's link (%s, %s%s)" % (url("VN"), url("JP"), err)))
SAMPLE = {"TH": "https://www.hostelworld.com/hostels/asia/thailand/",
          "GB": "https://www.hostelworld.com/hostels/europe/england/",
          "GB-ENG": "https://www.hostelworld.com/hostels/europe/england/",
          "GG": "https://www.hostelworld.com/hostels/europe/england/guernsey/",
          "FK": "https://www.hostelworld.com/"}
wrong = {i: url(i) for i, page in SAMPLE.items() if url(i) != console(i, page)}
results.append(ok(not wrong and "FK" not in HW_ISOS,
                  "Thailand, the UK and England (England's page), Guernsey (under England), the Falklands (no page:"
                  " the homepage): the console's format with pubref guide-<ISO> (wrong: %s%s)" % (wrong, err)))
bad_dest = [i for i in ALL if not got.get(i) or got[i]["dest"] is None or got[i]["dest"] != got[i]["old"]]
results.append(ok(not bad_dest and len(got) == len(ALL),
                  "all %d guides, stay countries and HW_COUNTRY entries: the destination decodes to the old plain"
                  " URL (differ: %s%s)" % (len(ALL), bad_dest[:8], err)))
bad_ref = [i for i in ALL if not got.get(i) or got[i]["pubref"] != "guide-" + i
           or not re.fullmatch(r"[A-Za-z0-9-]+", got[i]["pubref"] or "")]
results.append(ok(not bad_ref, "every pubref is guide-<ISO>, letters, digits and hyphens only (wrong: %s)" % bad_ref[:8]))
unsafe = [i for i in ALL if not got.get(i) or re.search(r"[\"'<>&\s]", got[i]["url"])
          or got[i]["url"].count("/destination:") != 1 or not got[i]["url"].startswith(
              "https://hostelworld.prf.hn/click/camref:%s/pubref:" % CAMREF)]
results.append(ok(not unsafe, "camref, then pubref, then the destination last; nothing an href would need escaped"
                  " (wrong: %s)" % unsafe[:8]))

# --- renderGuideStay -----------------------------------------------------------------
REGION_JS = "\n".join([js_const("REGIONS"), js_const("ISO_REGION"), js_const("EXTRA_CONTINENT"),
                       js_const("_SOUTH_AMERICA"), js_const("_MENA_AFRICA"), js_fn("continentOf"), js_fn("regionOf"),
                       js_const("VRBO_REGIONS"), js_const("VRBO_ALSO"), js_const("VRBO_NOT"), js_fn("vrboOK")])
PICK = ["VN", "JP", "TH", "GB", "GB-ENG", "PT", "FK"]
DATES = {"checkin": "2026-11-15", "checkout": "2026-11-18"}
prog = "\n".join([js_const("esc"), REGION_JS, js_const("STAY22_AID"), js_const("HW_CAMREF"), hw_block,
                  js_fn("hostelworldURL"), "let _staySpotIdx = 0, _staySpotIso = null, _ssrNoStay = null;",
                  js_fn("renderGuideStay")]) + """
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
BTN = re.compile(r'<a class="staybtn" target="_blank" rel="([^"]*)" href="([^"]*)">([^<]*?) <span class="ext">')
rels, hw = {}, {}
for iso in PICK:
    btns = BTN.findall(drawn.get(iso) or "")
    rels[iso] = {label: rel for rel, _, label in btns}
    hw[iso] = next((href for _, href, label in btns if label == "🎒 Hostelworld"), None)
wrong = [i for i in PICK if hw[i] != url(i) or rels[i].get("🎒 Hostelworld") != "sponsored nofollow noopener"]
results.append(ok(not wrong, "renderGuideStay: the Hostelworld button opens hostelworldURL's link, rel=\"sponsored nofollow"
                  " noopener\" (%s; wrong: %s%s)" % (" ".join(PICK), wrong, " " + drawn["error"] if "error" in drawn else "")))
same = [i for i in PICK if len(set(rels[i].values())) != 1 or len(rels[i]) < 2]
results.append(ok(not same, "every stay button there has the same rel as Booking.com's (%s; differ: %s)"
                  % ({i: sorted(rels[i]) for i in ("PT", "JP")}, same)))

# --- the stand-in, and no other Hostelworld link ---------------------------------------
stand = {i: guide_sizers.stay(i) for i in ("VN", "JP", "GB", "FK")}
results.append(ok(all('<a class="staybtn">🎒 Hostelworld <span class="ext">' in h and "href" not in h
                      for h in stand.values()),
                  "the served stand-in keeps a Hostelworld button with no href (Vietnam, Japan, the UK, the Falklands)"))
LINK = re.compile(r"https?://(?:www\.)?hostelworld\.(?:com|prf\.hn)", re.I)
outside = APP.replace(js_fn("hostelworldURL"), "")
outside = "\n".join(l for l in outside.splitlines() if not l.lstrip().startswith("//"))
others = ["public/app.js"] if LINK.search(outside) else []
for path in ["public/index.html", "server.py"] + sorted(glob.glob(os.path.join(ROOT, "fxtracker", "*.py"))):
    path = os.path.relpath(os.path.join(ROOT, path), ROOT)
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        if LINK.search(f.read()):
            others.append(path)
results.append(ok(not others, "no other Hostelworld link anywhere: app.js outside hostelworldURL, index.html, server.py,"
                  " fxtracker/*.py (found in: %s)" % others))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

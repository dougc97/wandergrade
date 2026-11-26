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
  * hostelworldURL(iso, city) with a spot's Hostelworld city page
    (public/hw-cities.json, "asia/japan/kyoto") writes the same link with
    that page as the destination: Japan's Kyoto typed out in full; every
    page in the file decodes to https://www.hostelworld.com/hostels/<page>/
    with the guide's pubref, nothing to escape; anything that isn't a
    "<continent>/<country>/<city>" path falls back to the country page;
  * renderGuideStay under jsc (its page stubbed, as scripts/test_vrbo.py
    does) draws the Hostelworld button with that href, opened in a new tab
    with rel="sponsored nofollow noopener", like Booking.com and Vrbo:
    named for the first spot when it has a city page (Japan's Kyoto,
    Portugal's Lisbon, the UK's London), unnamed on the country page where
    it hasn't but another spot has (Indonesia's Bali, Australia's Great
    Barrier Reef), and the plain button main drew, byte for byte, where no
    spot of the country has one (the Falklands, Kenya, Ethiopia); such a
    country's whole block is the same bytes as with no hw-cities.json;
    before the files land it marks the empty block for its CSS hold:
    data-hw "vrbo" (a spot with a city page, and Vrbo), "solo" (no Vrbo),
    none (no spot with one);
  * app.js HW_ANY, those countries known without the file, is exactly
    hw-cities.json's keys, in build_hw_cities.py's block;
  * hw-cities.json unreadable (a 503, or not an object): ensureHwCities
    fetches it once for the session, however many chips are tapped, and
    every chip of every country draws Hostelworld unnamed on the country
    page, with the class the served stand-in drew (.stayhw where HW_ANY has
    the country, main's plain button elsewhere), so a tap can't change the
    block's height;
  * public/hw-cities.json is scripts/build_hw_cities.py's output, byte for
    byte, from the committed inputs (scripts/hw-city-pages.txt, Hostelworld's
    sitemap read once; stay-coords.json; app.js HW_COUNTRY), with no network;
    its sitemap reader keeps only /hostels/<continent>/<country>/<city>/
    pages (a gzipped sitemap and its index written here: not Hostelworld's
    regions r/, areas a/, a city's filters f/ or districts d/), in the same
    output however often it is read; every page in the file is one of those
    city pages in the guide's own Hostelworld country (the UK's may be
    Scotland's, Wales' or Northern Ireland's); Japan's Kyoto, Tokyo, Osaka
    map by name and Hokkaido, whose Hostelworld page is a region's, does
    not; every curated alias names a real city page;
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

# --- hostelworldURL with a spot's city page -----------------------------------------------
HWC = load("hw-cities.json")
PAIRS = sorted({(iso, page) for iso, m in HWC.items() for page in m.values()})
BAD = ["", "asia/japan", "asia/japan/kyoto/extra", "../../evil", "asia/japan/Kyoto", "asia/japan/kyo to",
       "https://example.com/x/y", "asia/japan/kyoto\"", None]
prog = "\n".join([js_const("HW_CAMREF"), hw_block, js_fn("hostelworldURL")]) + """
const P = %s, B = %s, o = { city: {}, bad: [] };
const m = (u) => /^https:\\/\\/hostelworld\\.prf\\.hn\\/click\\/camref:([^/]+)\\/pubref:([^/]+)\\/destination:([^/]+)$/.exec(u);
for (const [i, p] of P) { const u = hostelworldURL(i, p), x = m(u); o.city[i + " " + p] = { url: u, dest: x ? decodeURIComponent(x[3]) : null, pubref: x ? x[2] : null }; }
for (const b of B) o.bad.push([hostelworldURL("JP", b), hostelworldURL("JP")]);
o.kyoto = hostelworldURL("JP", "asia/japan/kyoto");
print(JSON.stringify(o));""" % (json.dumps(PAIRS), json.dumps(BAD))
cg = run(prog)
cerr = " " + cg["error"] if "error" in cg else ""
KYOTO = ("https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-JP/destination:"
         "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fasia%2Fjapan%2Fkyoto%2F")
results.append(ok(cg.get("kyoto") == KYOTO == console("JP", "https://www.hostelworld.com/hostels/asia/japan/kyoto/"),
                  "Japan's Kyoto: exactly the console's link to the city page (%s%s)" % (cg.get("kyoto"), cerr)))
cbad = [k for k, (i, p) in zip(cg.get("city", {}), PAIRS)
        if (cg["city"].get(i + " " + p) or {}).get("dest") != "https://www.hostelworld.com/hostels/%s/" % p
        or cg["city"][i + " " + p]["pubref"] != "guide-" + i
        or cg["city"][i + " " + p]["url"] != console(i, "https://www.hostelworld.com/hostels/%s/" % p)
        or re.search(r"[\"'<>&\s]", cg["city"][i + " " + p]["url"])]
results.append(ok(len(cg.get("city", {})) == len(PAIRS) > 250 and not cbad,
                  "every city page in hw-cities.json (%d, in %d countries): the console's format, its own pubref, the"
                  " page as the destination, nothing to escape (wrong: %s%s)" % (len(PAIRS), len(HWC), cbad[:5], cerr)))
fallback = [b for b, (got_b, country) in zip(BAD, cg.get("bad", [])) if got_b != country]
results.append(ok(len(cg.get("bad", [])) == len(BAD) and not fallback and url("JP") == JP,
                  "anything but a <continent>/<country>/<city> path of letters, digits and hyphens opens the country"
                  " page instead (wrong: %s)" % fallback))

# --- renderGuideStay -----------------------------------------------------------------
REGION_JS = "\n".join([js_const("REGIONS"), js_const("ISO_REGION"), js_const("EXTRA_CONTINENT"),
                       js_const("_SOUTH_AMERICA"), js_const("_MENA_AFRICA"), js_fn("continentOf"), js_fn("regionOf"),
                       js_const("VRBO_REGIONS"), js_const("VRBO_ALSO"), js_const("VRBO_NOT"), js_fn("vrboOK")])
PICK = ["VN", "JP", "TH", "GB", "GB-ENG", "PT", "FK", "ID", "AU", "KE", "ET"]
# Every country with spots and no city page in hw-cities.json, drawn with the
# file and without it (each chip): the same bytes.
NONE = sorted(i for i in coords if isinstance(coords[i], list) and coords[i] and not HWC.get(i))
DATES = {"checkin": "2026-11-15", "checkout": "2026-11-18"}
STAY_JS = "\n".join([js_const("esc"), REGION_JS, js_const("STAY22_AID"), js_const("HW_CAMREF"), hw_block,
                     js_fn("hostelworldURL"), js_const("HW_ANY"), "let _hwFailed = false;",
                     "let _staySpotIdx = 0, _staySpotIso = null, _ssrNoStay = null;", js_fn("renderGuideStay")])
prog = STAY_JS + """
const COORDS = %s, HWC = %s, DATES = %s, PICK = %s, NONE = %s, out = {}, none = {}, hint = {};
let host = null, ccGuideIso = null, advisories = null, HW = HWC;
const window = {}, $ = (id) => (id === "guideStay" ? host : null), holdSizer = () => {};
const guideNoBookings = () => false, dntSettled = () => true;
const ensureStayCoords = () => Promise.resolve(COORDS), ensureBookingsKnown = () => Promise.resolve(null);
const ensureHwCities = () => Promise.resolve(HW);
const stayDates = () => DATES;
const draw = async (iso, i) => {
  host = { innerHTML: "", hidden: true, style: {}, firstChild: null, dataset: {}, querySelectorAll: () => [] };
  ccGuideIso = iso; _staySpotIso = iso; _staySpotIdx = i;
  renderGuideStay(iso);
  if (!i) hint[iso] = [host.dataset.hw || null, host.innerHTML];   // before the files land
  for (let k = 0; k < 20; k++) await null;
  return host.innerHTML;
};
(async () => {
  for (const iso of PICK) out[iso] = await draw(iso, 0);
  for (const iso of NONE) {
    none[iso] = [];
    for (let i = 0; i < COORDS[iso].length; i++) {
      HW = HWC; const a = await draw(iso, i);
      HW = {}; const b = await draw(iso, i);
      none[iso].push(a === b && a !== "" ? 1 : [a, b]);
    }
  }
  HW = HWC;
  print(JSON.stringify({ out, none, hint }));
})();""" % (json.dumps({i: coords[i] for i in sorted(set(PICK) | set(NONE))}), json.dumps(HWC), json.dumps(DATES),
            json.dumps(PICK), json.dumps(NONE))
both = run(prog)
drawn = both.get("out", both)
# Booking.com and Vrbo name their spot in spans of their own (renderGuideStay),
# and Hostelworld does where the spot has a city page; where another spot of
# the country has one it is the same spans less the place, and elsewhere the
# plain button it always was: its label, then the arrow.
BTN = re.compile(r'<a class="staybtn(?: [^"]*)?" target="_blank" rel="([^"]*)" href="([^"]*)">(.*?)</a>', re.S)
HW_BTN = '<a class="staybtn" target="_blank" rel="sponsored nofollow noopener" href="%s">🎒 Hostelworld <span class="ext">↗</span></a>'
HW_AT = ('<a class="staybtn stayto stayhw" target="_blank" rel="sponsored nofollow noopener" href="%s">'
         '<span><span aria-hidden="true">🎒 </span>Hostelworld<span class="vh"> hostels near </span></span>'
         '<span class="staysep" aria-hidden="true">·</span><span class="stayat" title="%s">%s'
         '<span class="vh"> (opens in a new tab)</span></span><span class="ext" aria-hidden="true">↗</span></a>')
HW_OFF = ('<a class="staybtn stayto stayhw" target="_blank" rel="sponsored nofollow noopener" href="%s">'
          '<span><span aria-hidden="true">🎒 </span>Hostelworld<span class="vh"> (opens in a new tab)</span></span>'
          '<span class="ext" aria-hidden="true">↗</span></a>')


def label(inner):
    vis = re.sub(r'<span class="vh">.*?</span>', "", inner)
    return re.sub(r"<[^>]+>", "", re.split(r' ?<span class="ext"', vis.split('<span class="staysep"')[0])[0]).strip()


def hw_want(iso):
    """The Hostelworld button main's rule plus hw-cities.json draws for the first spot."""
    first = coords[iso][0]["n"]
    page = (HWC.get(iso) or {}).get(first)
    if page:
        return HW_AT % (console(iso, "https://www.hostelworld.com/hostels/%s/" % page), first, first)
    return (HW_OFF if HWC.get(iso) else HW_BTN) % url(iso)


rels, hw, hw_html = {}, {}, {}
for iso in PICK:
    btns = BTN.findall(drawn.get(iso) or "")
    rels[iso] = {label(inner): rel for rel, _, inner in btns}
    hw[iso] = next((href for _, href, inner in btns if label(inner) == "🎒 Hostelworld"), None)
    hw_html[iso] = (drawn.get(iso) or "").endswith(hw_want(iso) + "</div>")
kinds = {i: "named" if (HWC.get(i) or {}).get(coords[i][0]["n"]) else "unnamed" if HWC.get(i) else "plain" for i in PICK}
wrong = [i for i in PICK if rels[i].get("🎒 Hostelworld") != "sponsored nofollow noopener" or not hw_html[i]]
results.append(ok(not wrong and [kinds[i] for i in PICK] == ["named"] * 6 + ["plain", "unnamed", "unnamed", "plain", "plain"],
                  "renderGuideStay: the Hostelworld button is the last, rel=\"sponsored nofollow noopener\", named and"
                  " on the city page for a first spot that has one, the country page otherwise, main's plain button"
                  " where no spot has one (%s; wrong: %s%s)" % (kinds, wrong, " " + drawn["error"] if "error" in drawn else "")))
nb = {i: v for i, v in (both.get("none") or {}).items() if v != [1] * len(v)}
results.append(ok(len(both.get("none") or {}) == len(NONE) > 40 and not nb,
                  "every country with spots and no city page (%d: Ethiopia, Kenya, Guam, the Falklands...) draws the same"
                  " bytes, every chip, as with no hw-cities.json at all (differ: %s)" % (len(NONE), list(nb)[:5])))
same = [i for i in PICK if len(set(rels[i].values())) != 1 or len(rels[i]) < 2]
results.append(ok(not same, "every stay button there has the same rel as Booking.com's (%s; differ: %s)"
                  % ({i: sorted(rels[i]) for i in ("PT", "JP")}, same)))

# The empty block's hold knows, before the files land, whether Hostelworld's
# fixed-width button will add a row (styles.css #guideStay[data-hw]): data-hw
# "vrbo" beside Vrbo, "solo" without, none where no spot has a city page.
hint = both.get("hint") or {}
want_hint = {"VN": "solo", "JP": "solo", "TH": "vrbo", "GB": "vrbo", "GB-ENG": "vrbo", "PT": "vrbo", "FK": None,
             "ID": "vrbo", "AU": "vrbo", "KE": None, "ET": None}
results.append(ok({i: (hint.get(i) or [None])[0] for i in PICK} == want_hint
                  and all((hint.get(i) or [0, 1])[1] == "" for i in PICK),
                  "renderGuideStay marks the empty block before the files land: data-hw \"vrbo\" (Thailand, Portugal,"
                  " the UK), \"solo\" (Vietnam, Japan), none (Kenya, Ethiopia, the Falklands) (%s)"
                  % {i: (hint.get(i) or [None])[0] for i in PICK}))

# app.js HW_ANY is hw-cities.json's countries, in build_hw_cities.py's block.
any_js = set(re.findall(r"[A-Z]{2}(?:-[A-Z]{3})?", js_const("HW_ANY").split("new Set(", 1)[-1]))
with_page = {i for i in coords if isinstance(coords[i], list) and any(x.get("n") in (HWC.get(i) or {}) for x in coords[i])}
results.append(ok(any_js == set(HWC) == with_page and len(any_js) > 100,
                  "app.js HW_ANY is exactly the countries in hw-cities.json, each with a spot of that name (%d; only in"
                  " app.js: %s; missing: %s)" % (len(any_js), sorted(any_js - set(HWC)), sorted(set(HWC) - any_js))))

# hw-cities.json unreadable (a failed fetch, or not an object): ensureHwCities
# says so once for the session, so a chip tap doesn't fetch it again, and the
# button keeps the width the served stand-in drew (unnamed .stayhw where
# HW_ANY says a spot has a page), for every chip of every country.
ALLSP = sorted(i for i in coords if isinstance(coords[i], list) and coords[i])
prog = STAY_JS.replace("let _hwFailed = false;", "") + "\n" + js_const("_hwCities") + "\n" + js_fn("ensureHwCities") + """
const COORDS = %s, DATES = %s, ALL = %s, out = {}, calls = [];
let host = null, ccGuideIso = null, advisories = null, ANSWER = "fail";
const window = {}, $ = (id) => (id === "guideStay" ? host : null), holdSizer = () => {};
const guideNoBookings = () => false, dntSettled = () => true, stayDates = () => DATES;
const ensureStayCoords = () => Promise.resolve(COORDS), ensureBookingsKnown = () => Promise.resolve(null);
// (js_const("esc") brings app.js's own getJSON along: replaced, not redeclared.)
getJSON = (u) => { calls.push(u); return ANSWER === "fail" ? Promise.reject(new Error("HTTP 503")) : Promise.resolve(null); };
const draw = async (iso, i) => {
  host = { innerHTML: "", hidden: true, style: {}, firstChild: null, dataset: {}, querySelectorAll: () => [] };
  ccGuideIso = iso; _staySpotIso = iso; _staySpotIdx = i;
  renderGuideStay(iso);
  for (let k = 0; k < 20; k++) await null;
  return host.innerHTML;
};
(async () => {
  const r = { fail: {}, nul: {} };
  for (const iso of ALL) { out[iso] = []; for (let i = 0; i < COORDS[iso].length; i++) out[iso].push(await draw(iso, i)); }
  r.fail = { calls: calls.length, failed: _hwFailed, cities: JSON.stringify(_hwCities) };
  _hwCities = null; _hwFailed = false; ANSWER = "null"; calls.length = 0;
  const a = await draw("JP", 0), b = await draw("JP", 1);
  r.nul = { calls: calls.length, failed: _hwFailed, jp: [a, b] };
  print(JSON.stringify({ out, r }));
})();""" % (json.dumps({i: coords[i] for i in ALLSP}), json.dumps(DATES), json.dumps(ALLSP))
fl = run(prog)
fr = fl.get("r") or {}
results.append(ok(fr.get("fail") == {"calls": 1, "failed": True, "cities": "{}"}
                  and (fr.get("nul") or {}).get("calls") == 1 and (fr.get("nul") or {}).get("failed") is True,
                  "hw-cities.json unreadable (a 503, or null): fetched once for the session however many chips are"
                  " tapped, and remembered as failed (%s%s)" % (fr, " " + fl["error"] if "error" in fl else "")))
hw_cls = lambda h: (re.findall(r'<a class="staybtn( [^"]*)?"[^>]*>(?:(?!</a>).)*Hostelworld', h, re.S) or ["?"])[-1].strip()
wrongf = []
for iso in ALLSP:
    want = (HW_OFF if iso in any_js else HW_BTN) % url(iso)
    stand = hw_cls(guide_sizers.stay(iso))
    for h in (fl.get("out") or {}).get(iso) or ["?"]:
        if not h.endswith(want + "</div>") or hw_cls(h) != stand:
            wrongf.append(iso)
            break
results.append(ok(len(fl.get("out") or {}) == len(ALLSP) > 180 and not wrongf
                  and all(h.endswith((HW_OFF % url("JP")) + "</div>") for h in (fr.get("nul") or {}).get("jp") or ["?"]),
                  "with hw-cities.json unreadable, every chip of every country (%d) draws Hostelworld unnamed on the"
                  " country page, as wide as the served stand-in's (.stayhw where HW_ANY has the country, main's plain"
                  " button elsewhere) (wrong: %s)" % (len(ALLSP), wrongf[:6])))

# --- the data: scripts/build_hw_cities.py, offline ------------------------------------------
import gzip  # noqa: E402
import importlib.util  # noqa: E402
import tempfile  # noqa: E402

spec = importlib.util.spec_from_file_location("build_hw_cities", os.path.join(ROOT, "scripts", "build_hw_cities.py"))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
import urllib.request as _ur  # noqa: E402
_urlopen, net = _ur.urlopen, []
_ur.urlopen = lambda *a, **k: net.append(a) or (_ for _ in ()).throw(OSError("no network in this test"))
try:
    data, rows = B.build(*B.load_inputs())
    text = B.dump(data)
finally:
    _ur.urlopen = _urlopen
with open(os.path.join(ROOT, "public", "hw-cities.json"), encoding="utf-8") as f:
    committed = f.read()
results.append(ok(B.hw_any_js(data) in APP and B.app_hw_any() == set(data),
                  "app.js HW_ANY is build_hw_cities.py's block for these countries, character for character (--check"
                  " fails and prints it when they differ)"))
results.append(ok(text == committed and not net and json.loads(text) == HWC,
                  "public/hw-cities.json is build_hw_cities.py's output, byte for byte, from the committed inputs, with"
                  " no network (%d spots mapped of %d)" % (sum(len(v) for v in data.values()), len(rows))))
site = B.SITE
SAMPLE_URLS = [site + "/hostels/asia/japan/", site + "/hostels/asia/japan/kyoto/", site + "/hostels/asia/japan/r/hokkaido/",
               site + "/hostels/europe/austria/a/tyrol/", site + "/hostels/asia/japan/kyoto/f/party/",
               site + "/hostels/europe/england/london/d/camden/", site + "/hotels/asia/japan/osaka/",
               site + "/hostels/p/12345/some-hostel/", site + "/hostels/europe/england/guernsey/",
               site + "/hostels/asia/japan/tokyo/"]
with tempfile.TemporaryDirectory() as d:
    xml = lambda tag, inner, locs: ('<?xml version="1.0" encoding="UTF-8"?><%s xmlns="http://www.sitemaps.org/schemas/'
                                    'sitemap/0.9">%s</%s>' % (tag, "".join("<%s><loc>%s</loc></%s>" % (inner, u, inner)
                                                                            for u in locs), tag)).encode()
    with open(os.path.join(d, "sitemap-index.xml"), "wb") as f:
        f.write(xml("sitemapindex", "sitemap", [site + "/sitemap/sitemap-2.xml.gz", site + "/sitemap/sitemap-1.xml.gz"]))
    with open(os.path.join(d, "sitemap-1.xml.gz"), "wb") as f:
        f.write(gzip.compress(xml("urlset", "url", SAMPLE_URLS[:6])))
    with open(os.path.join(d, "sitemap-2.xml.gz"), "wb") as f:
        f.write(gzip.compress(xml("urlset", "url", SAMPLE_URLS[6:])))
    got1, got2 = B.read_pages(d), B.read_pages(d)
results.append(ok(got1 == got2 == ["europe/england/guernsey", "asia/japan/tokyo", "asia/japan/kyoto"],
                  "the sitemap reader keeps only hostel city pages, in the index's order, the same every read (%s)" % got1))
hw_map = B.hw_country()
pages = set(B.read_city_pages())
far = [(i, n, pg) for i, m in data.items() for n, pg in m.items()
       if pg not in pages or pg.rsplit("/", 1)[0] not in [hw_map[i]] + B.EXTRA_COUNTRIES.get(i, [])]
slug_of = dict(re.findall(r"\b([A-Z]{2}(?:-[A-Z]{3})?):([a-z/-]+)", hw_block))
results.append(ok(not far and set(hw_map) == HW_ISOS == set(slug_of)
                  and all(hw_map[i].split("/", 1)[1] == slug_of[i] for i in hw_map),
                  "every mapped page is a Hostelworld city page of the guide's own Hostelworld country (outside: %s)" % far[:4]))
jp = data.get("JP", {})
results.append(ok(jp.get("Kyoto") == "asia/japan/kyoto" and jp.get("Tokyo") == "asia/japan/tokyo"
                  and jp.get("Osaka") == "asia/japan/osaka" and "Hokkaido" not in jp
                  and "asia/japan/hokkaido" not in pages and not any(p.endswith("/r/hokkaido") for p in pages),
                  "Japan: Kyoto, Tokyo and Osaka map to their city pages by name; Hokkaido (Hostelworld's r/hokkaido is a"
                  " region page, not a city's) maps to nothing (%s)" % jp))
bad_alias = [(i, n) for i, m in B.ALIASES.items() for n, (city, why) in m.items()
             if data.get(i, {}).get(n) != (city if "/" in city else hw_map[i] + "/" + city) or not why]
unused = [(i, n) for i, m in B.ALIASES.items() for n in m if n not in [x["n"] for x in coords.get(i, [])]]
results.append(ok(not bad_alias and not unused and "Rila" not in data.get("BG", {}),
                  "every curated alias names a spot in stay-coords.json and a real city page, with its reason; Bulgaria's"
                  " Rila (the mountains) is kept off the town's page (wrong: %s, unused: %s)" % (bad_alias, unused)))

# --- the stand-in, and no other Hostelworld link ---------------------------------------
stand = {i: guide_sizers.stay(i) for i in ("VN", "JP", "GB", "FK", "ID", "KE")}
results.append(ok(all("Hostelworld" in h and "href" not in h for h in stand.values())
                  and '<a class="staybtn stayto stayhw"><span><span aria-hidden="true">🎒 </span>Hostelworld</span>'
                      '<span class="staysep" aria-hidden="true">·</span><span class="stayat">Kyoto</span>' in stand["JP"]
                  and '<a class="staybtn stayto stayhw"><span><span aria-hidden="true">🎒 </span>Hostelworld</span>'
                      '<span class="ext" aria-hidden="true">↗</span></a>' in stand["ID"]
                  and all('<a class="staybtn">🎒 Hostelworld <span class="ext">↗</span></a>' in stand[i] for i in ("FK", "KE")),
                  "the served stand-in keeps a Hostelworld button with no href: named Kyoto on Japan's, unnamed but"
                  " .stayhw on Indonesia's (Bali), main's plain button on the Falklands' and Kenya's"))
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

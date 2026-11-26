#!/usr/bin/env python3
"""The guide's "Where to stay" buttons name the spot they search, without the
network or a server process.

    /usr/bin/python3 scripts/test_stay_place.py

The chips (📍 Kyoto, Tokyo, Osaka…) choose where the Booking.com search (and
Vrbo's, where vrboOK) lands, by lat/lng in the Stay22 link. The only sign of a
tap used to be the heading's small grey "near Osaka", so readers took the
chips for dead buttons. Now Booking.com and Vrbo name the spot
("🏨 Booking.com · Osaka ↗") and the heading is just "🏨 Where to stay".
Hostelworld names it too, and opens its city page, where the spot has one
(public/hw-cities.json: "🎒 Hostelworld · Kyoto ↗"); elsewhere it opens the
country page, unnamed.

  * renderGuideStay under jsc (its page stubbed: chips that can be tapped and
    focused): on Portugal (Vrbo), Japan (no Vrbo) and Ethiopia (one spot, no
    chips) the heading is "🏨 Where to stay" with no place; every chip tap
    names that chip's spot on Booking.com (and Vrbo), marks only that chip
    aria-pressed="true", and points the links at its lat/lng — the hrefs
    exactly main's (aid, lat, lng, checkin, checkout), rel="sponsored
    nofollow noopener", new tab; Hostelworld's button follows the chip too:
    Japan's Kyoto, Tokyo, Osaka and Hakone name the spot and open its city
    page, Hokkaido (a region: no city page) opens the country page unnamed,
    in the same spans less the place (.stayhw, so its row breaks as a named
    one's would); Portugal's Lisbon and Porto (and Pena Palace, Sintra's)
    name theirs, the Algarve doesn't; Ethiopia and Guam (no city page) keep
    main's plain button, byte for byte;
  * a screen reader hears where each link searches: the link's words less
    the aria-hidden parts read "Booking.com hotels near Lisbon (opens in a
    new tab)" / "Vrbo homes near Lisbon (opens in a new tab)" / "Hostelworld
    hostels in Lisbon (opens in a new tab)", the full name whatever the
    ellipsis shows, and the place span's title holds it too; Hostelworld
    unnamed reads "Hostelworld (opens in a new tab)";
  * a chip tapped with the focus on it (keyboard Enter or Space) hands the
    focus to the redrawn chip with the same index (no scroll), so a keyboard
    user isn't dropped to <body>; a tap that didn't focus the chip (Safari's
    mouse click) moves no focus;
  * the served stand-in (guide_sizers.stay) is the drawn block less what
    can't change its size (screen-reader words, title, link targets, chip
    state; a <div> for the h3), for every country with spots: the same
    spans, so it wraps the same, Hostelworld named for the first spot where
    it has a city page, .stayhw where any spot has one, main's plain button
    elsewhere; the longest name (Guam's "War in the Pacific National
    Historical Park", its second chip) in both;
  * styles.css wraps the named buttons on fixed widths, never on the name:
    Booking.com at least 19em, Vrbo 13em, each growing only up to its
    content and shrinking only to the column (min(…, 100%): alone on a row
    narrower than 19em, under ~290px, it isn't 7px wider than the column),
    one line, the place cut with an ellipsis and the containing
    block of its screen-reader words (else a cut name's 1px box sat past the
    page's edge and scrolled a phone sideways); Hostelworld's .stayhw starts
    from a fixed width of its own, named or not; no .staynear left in the
    stylesheet, app.js or the stand-in.
"""
import html
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_sizers  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()
with open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8") as f:
    CSS = f.read()
with open(os.path.join(ROOT, "public", "stay-coords.json"), encoding="utf-8") as f:
    COORDS = json.load(f)
with open(os.path.join(ROOT, "public", "hw-cities.json"), encoding="utf-8") as f:
    HWC = json.load(f)


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):
    m = re.search(r"^(?:const|let) %s = [^\n]*;$" % re.escape(name), APP, re.M)
    if m and not m.group(0).rstrip(";").endswith(("{", "(() => {")):
        return m.group(0)
    m = re.search(r"^(?:const|let) %s = .*?^\}\)?(?:\(\))?;$" % re.escape(name), APP, re.M | re.S)
    return m.group(0) if m else ""


def jsnum(x):
    """String(x) in JS for the coordinates in stay-coords.json."""
    return str(int(x)) if float(x) == int(x) else repr(float(x))


def spots(iso):
    return [s for s in COORDS[iso] if s.get("ll") and s.get("n")]


# --- renderGuideStay under jsc: draw, tap every chip (keyboard, then a mouse) -------------
PICK = ["PT", "JP", "ET", "GU", "ID"]
DATES = {"checkin": "2026-12-15", "checkout": "2026-12-18"}
REGION_JS = "\n".join([js_const("REGIONS"), js_const("ISO_REGION"), js_const("EXTRA_CONTINENT"),
                       js_const("_SOUTH_AMERICA"), js_const("_MENA_AFRICA"), js_fn("continentOf"), js_fn("regionOf"),
                       js_const("VRBO_REGIONS"), js_const("VRBO_ALSO"), js_const("VRBO_NOT"), js_fn("vrboOK")])
prog = "\n".join([js_const("esc"), REGION_JS, js_const("STAY22_AID"), js_const("HW_CAMREF"), js_const("HW_COUNTRY"),
                  js_fn("hostelworldURL"), "let _staySpotIdx = 0, _staySpotIso = null, _ssrNoStay = null;",
                  js_fn("renderGuideStay")]) + """
const COORDS = %s, HWC = %s, DATES = %s, PICK = %s, out = {};
let host = null, ccGuideIso = null, advisories = null, focused = [];
const document = { activeElement: null };
const window = {}, $ = (id) => (id === "guideStay" ? host : null), holdSizer = () => {};
const guideNoBookings = () => false, dntSettled = () => true;
const ensureStayCoords = () => Promise.resolve(COORDS), ensureBookingsKnown = () => Promise.resolve(null);
const ensureHwCities = () => Promise.resolve(HWC);
const stayDates = () => DATES;
function mkHost() {
  // Just enough DOM: the chips app.js wires up, found by their data-si.
  return { _html: "", _chips: null, hidden: true, style: {}, firstChild: null, dataset: {},
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; this._chips = null; this.firstChild = v ? {} : null; },
    chips() {
      if (!this._chips) {
        this._chips = [];
        const re = /data-si="(\\d+)"/g; let m;
        while ((m = re.exec(this._html))) this._chips.push({ dataset: { si: m[1] }, fns: [],
          addEventListener(t, f) { if (t === "click") this.fns.push(f); },
          click() { this.fns.forEach((f) => f()); },
          focus(o) { focused.push({ si: this.dataset.si, preventScroll: !!(o && o.preventScroll) }); } });
      }
      return this._chips;
    },
    querySelectorAll(sel) { return sel === ".staychip" ? this.chips() : []; },
    querySelector(sel) {
      const m = /^\\.staychip\\[data-si="(\\d+)"\\]$/.exec(sel);
      return m ? this.chips().find((c) => c.dataset.si === m[1]) || null : null;
    } };
}
const settle = async () => { for (let k = 0; k < 20; k++) await null; };
(async () => {
  for (const iso of PICK) {
    host = mkHost(); ccGuideIso = iso;
    renderGuideStay(iso); await settle();
    const o = out[iso] = { first: host.innerHTML, kbd: [], mouse: [] };
    const n = host.chips().length, order = [];
    for (let i = 1; i < n; i++) order.push(i);
    if (n) order.push(0);
    for (const mode of ["kbd", "mouse"]) {
      for (const i of order) {
        const c = host.chips()[i];
        document.activeElement = mode === "kbd" ? c : null;   // a mouse click in Safari leaves the focus on <body>
        focused = [];
        c.click(); await settle();
        o[mode].push({ i, html: host.innerHTML, focused });
      }
    }
  }
  print(JSON.stringify(out));
})();""" % (json.dumps({i: COORDS[i] for i in PICK}), json.dumps({i: HWC[i] for i in PICK if i in HWC}),
            json.dumps(DATES), json.dumps(PICK))
try:
    p = subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30)
    drawn = json.loads(p.stdout) if p.stdout.strip() else {"error": p.stderr[:300]}
except Exception as e:  # noqa: BLE001
    drawn = {"error": str(e)}
err = " " + drawn["error"] if "error" in drawn else ""

BTN = re.compile(r'<a class="staybtn(?: ([^"]*))?"( target="_blank" rel="[^"]*" href="[^"]*")?>(.*?)</a>', re.S)


def heard(inner):
    """A link's name as a screen reader computes it from its words: the
    aria-hidden parts left out, the rest (screen-reader words included)."""
    t = re.sub(r'<span aria-hidden="true">.*?</span>', "", inner)
    t = re.sub(r'<span class="(?:staysep|ext)" aria-hidden="true">.*?</span>', "", t)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def buttons(h):
    out = []
    for cls, attrs, inner in BTN.findall(h):
        href = re.search(r'href="([^"]*)"', attrs)
        place = re.search(r'<span class="stayat"( title="[^"]*")?>(.*?)(?:<span class="vh">.*?</span>)?</span>', inner)
        out.append({"cls": cls, "href": html.unescape(href.group(1)) if href else None,
                    "rel": (re.search(r'rel="([^"]*)"', attrs) or [None, None])[1] if attrs else None,
                    "target": "_blank" if 'target="_blank"' in attrs else None,
                    "place": html.unescape(place.group(2)) if place else None,
                    "title": html.unescape(place.group(1)[8:-1]) if place and place.group(1) else None,
                    "heard": heard(inner), "html": '<a class="staybtn%s"%s>%s</a>' % (" " + cls if cls else "", attrs, inner)})
    return out


def pressed(h):
    return re.findall(r'aria-pressed="(true|false)" data-si="(\d+)"', h)


HW = '<a class="staybtn" target="_blank" rel="sponsored nofollow noopener" href="%s">🎒 Hostelworld <span class="ext">↗</span></a>'
HW_OFF = ('<a class="staybtn stayto stayhw" target="_blank" rel="sponsored nofollow noopener" href="%s">'
          '<span><span aria-hidden="true">🎒 </span>Hostelworld<span class="vh"> (opens in a new tab)</span></span>'
          '<span class="ext" aria-hidden="true">↗</span></a>')
HW_URL = {"PT": "https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-PT/destination:"
                "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Feurope%2Fportugal%2F",
          "JP": "https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-JP/destination:"
                "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fasia%2Fjapan%2F",
          "ET": "https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-ET/destination:"
                "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fafrica%2Fethiopia%2F",
          "GU": "https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-GU/destination:"
                "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Foceania%2Fguam%2F",
          "ID": "https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-ID/destination:"
                "https%3A%2F%2Fwww.hostelworld.com%2Fhostels%2Fasia%2Findonesia%2F"}
# Each spot's Hostelworld page, typed out: Japan's cities (Hokkaido, a region,
# has none), Portugal's (the Algarve, a region, has none; Pena Palace is in
# Sintra); Ethiopia and Guam have none.
HW_CITY = {"JP": {"Kyoto": "asia%2Fjapan%2Fkyoto", "Tokyo": "asia%2Fjapan%2Ftokyo", "Osaka": "asia%2Fjapan%2Fosaka",
                  "Hakone": "asia%2Fjapan%2Fhakone"},
           "PT": {"Lisbon": "europe%2Fportugal%2Flisbon", "Porto": "europe%2Fportugal%2Fporto",
                  "Pena Palace": "europe%2Fportugal%2Fsintra"},
           "ID": {"Yogyakarta": "asia%2Findonesia%2Fyogyakarta", "Borobudur": "asia%2Findonesia%2Fborobudur"}}
VRBO = {"PT": True, "JP": False, "ET": False, "GU": True, "ID": True}


def hw_city_url(iso, page):
    return ("https://hostelworld.prf.hn/click/camref:1101l5NoBM/pubref:guide-%s/destination:"
            "https%%3A%%2F%%2Fwww.hostelworld.com%%2Fhostels%%2F%s%%2F" % (iso, page))


def expect(iso, i):
    """What main 1a1d75b links for spot i (its query, byte for byte)."""
    ll = spots(iso)[i]["ll"]
    q = "aid=wandergrade&lat=%s&lng=%s&checkin=%s&checkout=%s" % (jsnum(ll[0]), jsnum(ll[1]), DATES["checkin"], DATES["checkout"])
    return ["https://www.stay22.com/allez/booking?" + q] + (["https://www.stay22.com/allez/vrbo?" + q] if VRBO[iso] else [])


def check_state(iso, h, i):
    """One drawn state for spot i: heading, labels, hrefs, pressed chip, Hostelworld."""
    sp = spots(iso)
    b = buttons(h)
    page = HW_CITY.get(iso, {}).get(sp[i]["n"])
    named = [x for x in b if x["place"] is not None]
    want = ["🏨 Booking.com"] + (["🏡 Vrbo"] if VRBO[iso] else []) + (["🎒 Hostelworld"] if page else [])
    hw_ok = (b[-1]["place"] == sp[i]["n"] and b[-1]["href"] == hw_city_url(iso, page) and b[-1]["cls"] == "stayto stayhw"
             and b[-1]["heard"] == "Hostelworld hostels in %s (opens in a new tab)" % sp[i]["n"]) if page \
        else b[-1]["html"] == (HW_OFF if iso in HW_CITY else HW) % HW_URL[iso]
    return (h.startswith('<h3 class="staytitle">🏨 Where to stay</h3>') and "near" not in h.split("</h3>")[0]
            and [x["href"] for x in named][: len(expect(iso, i))] == expect(iso, i)
            and all(x["place"] == sp[i]["n"] and x["title"] == sp[i]["n"] and x["rel"] == "sponsored nofollow noopener"
                    and x["target"] == "_blank" for x in named)
            and [x["heard"].split(" ")[0] for x in named] == [w.split(" ")[1] for w in want]
            and hw_ok and len(b) == len(want) + (0 if page else 1)
            and (pressed(h) == [("true" if k == i else "false", str(k)) for k in range(len(sp))] if len(sp) > 1
                 else "staychip" not in h))


res = {}
for iso in PICK:
    d = drawn.get(iso) or {}
    states = [(0, d.get("first", ""))] + [(t["i"], t["html"]) for t in d.get("kbd", []) + d.get("mouse", [])]
    res[iso] = bool(d) and all(check_state(iso, h, i) for i, h in states)
results.append(ok(all(res.values()),
                  "heading \"🏨 Where to stay\"; each chip's tap names its spot on Booking.com (and Vrbo), presses only"
                  " that chip and links its lat/lng exactly as main does; Hostelworld names it and opens its city page"
                  " where it has one, else the country page (%s%s)" % (res, err)))
jp = drawn.get("JP") or {}
jp_hw = {spots("JP")[t["i"]]["n"]: buttons(t["html"])[-1] for t in [{"i": 0, "html": jp.get("first", "")}] + jp.get("kbd", [])}
results.append(ok(sorted(jp_hw) == sorted(s["n"] for s in spots("JP"))
                  and all(jp_hw[n]["href"] == hw_city_url("JP", HW_CITY["JP"][n]) and jp_hw[n]["place"] == n
                          for n in ("Kyoto", "Tokyo", "Osaka"))
                  and jp_hw["Hokkaido"]["href"] == HW_URL["JP"] and jp_hw["Hokkaido"]["place"] is None
                  and jp_hw["Hokkaido"]["heard"] == "Hostelworld (opens in a new tab)",
                  "Japan: Kyoto, Tokyo and Osaka open their Hostelworld city pages and name them; Hokkaido opens the"
                  " country page, unnamed (%s)" % {n: (x["place"], (x["href"] or "")[-40:]) for n, x in jp_hw.items()}))

pt = drawn.get("PT") or {}
pt_b = buttons(pt.get("first", ""))
results.append(ok([x["heard"] for x in pt_b] == ["Booking.com hotels near Lisbon (opens in a new tab)",
                                                 "Vrbo homes near Lisbon (opens in a new tab)",
                                                 "Hostelworld hostels in Lisbon (opens in a new tab)"]
                  and buttons((pt.get("kbd") or [{"html": ""}])[0]["html"])[0]["heard"]
                  == "Booking.com hotels near %s (opens in a new tab)" % spots("PT")[1]["n"],
                  "the links' names say where they search, and follow the chip: %s" % [x["heard"] for x in pt_b]))
gu = drawn.get("GU") or {}
gu_b = buttons(((gu.get("kbd") or [{}])[0]).get("html", ""))   # its second chip
LONG = "War in the Pacific National Historical Park"
results.append(ok(spots("GU")[1]["n"] == LONG and gu_b and gu_b[0]["place"] == LONG and gu_b[0]["title"] == LONG
                  and gu_b[0]["heard"] == "Booking.com hotels near %s (opens in a new tab)" % LONG
                  and gu_b[1]["place"] == LONG,
                  "the longest name (Guam's) is whole in the place span, its title and the link's name, whatever the"
                  " ellipsis shows"))
et = drawn.get("ET") or {}
et_b = buttons(et.get("first", ""))
results.append(ok(et and not et["kbd"] and "staychip" not in et.get("first", "")
                  and [x["place"] for x in et_b] == ["Bale Mountains National Park", None]
                  and et_b[-1]["html"] == HW % HW_URL["ET"]
                  and et.get("first", "").startswith('<h3 class="staytitle">🏨 Where to stay</h3><div class="staybtns">'),
                  "one spot (Ethiopia): no chips, the heading alone, Booking.com names Bale Mountains National Park,"
                  " Hostelworld main's plain button (a national park: no city page)"))

foc = {iso: [(t["i"], t["focused"]) for t in (drawn.get(iso) or {}).get("kbd", [])] for iso in ("PT", "JP")}
results.append(ok(all(v and all(f == [{"si": str(i), "preventScroll": True}] for i, f in v) for v in foc.values()),
                  "a chip tapped with the focus on it hands the focus to the redrawn chip of the same index, without"
                  " scrolling (%s)" % {k: v[:2] for k, v in foc.items()}))
results.append(ok(all(not t["focused"] for iso in ("PT", "JP") for t in (drawn.get(iso) or {}).get("mouse", []))
                  and all((drawn.get(iso) or {}).get("mouse") for iso in ("PT", "JP")),
                  "a tap that left the focus elsewhere (Safari's mouse click) moves no focus"))

# --- the stand-in mirrors the drawn block ------------------------------------------------
def as_drawn_layout(h):
    """The client's markup less what doesn't size it: screen-reader words,
    the title, link targets, chip state; its h3 as the stand-in's div."""
    h = re.sub(r'<span class="vh">.*?</span>', "", h)
    h = re.sub(r' title="[^"]*"', "", h)
    h = re.sub(r' target="_blank" rel="[^"]*" href="[^"]*"', "", h)
    h = re.sub(r' aria-pressed="(?:true|false)" data-si="\d+"', "", h)
    return h.replace('<h3 class="staytitle">', '<div class="staytitle">').replace("</h3>", "</div>")


def as_stand_in(h):
    h = re.sub(r'^<div class="gsizer"[^>]*>', "", h)
    return re.sub(r"</div>$", "", h).replace(' tabindex="-1"', "")


same = {iso: bool(drawn.get(iso)) and as_drawn_layout(drawn[iso]["first"]) == as_stand_in(guide_sizers.stay(iso))
        for iso in PICK}
results.append(ok(all(same.values()), "the stand-in is the drawn block's layout, span for span (%s)" % same))
# Every country with spots, its first chip drawn by renderGuideStay under jsc
# against its stand-in: named, unnamed (.stayhw) and plain Hostelworld alike.
ALL = sorted(i for i in COORDS if isinstance(COORDS[i], list) and spots(i))
prog_all = "\n".join([js_const("esc"), REGION_JS, js_const("STAY22_AID"), js_const("HW_CAMREF"), js_const("HW_COUNTRY"),
                      js_fn("hostelworldURL"), "let _staySpotIdx = 0, _staySpotIso = null, _ssrNoStay = null;",
                      js_fn("renderGuideStay")]) + """
const COORDS = %s, HWC = %s, DATES = %s, ALL = %s, out = {};
let host = null, ccGuideIso = null, advisories = null;
const document = { activeElement: null }, window = {}, $ = (id) => (id === "guideStay" ? host : null), holdSizer = () => {};
const guideNoBookings = () => false, dntSettled = () => true, stayDates = () => DATES;
const ensureStayCoords = () => Promise.resolve(COORDS), ensureBookingsKnown = () => Promise.resolve(null);
const ensureHwCities = () => Promise.resolve(HWC);
(async () => {
  for (const iso of ALL) {
    host = { innerHTML: "", hidden: true, style: {}, firstChild: null, dataset: {}, querySelectorAll: () => [], querySelector: () => null };
    ccGuideIso = iso; renderGuideStay(iso);
    for (let k = 0; k < 20; k++) await null;
    out[iso] = host.innerHTML;
  }
  print(JSON.stringify(out));
})();""" % (json.dumps({i: COORDS[i] for i in ALL}), json.dumps(HWC), json.dumps(DATES), json.dumps(ALL))
try:
    p_all = subprocess.run([JSC, "-e", prog_all], capture_output=True, text=True, timeout=30)
    drawn_all = json.loads(p_all.stdout) if p_all.stdout.strip() else {"error": p_all.stderr[:300]}
except Exception as e:  # noqa: BLE001
    drawn_all = {"error": str(e)}
# (Compared as text: app.js esc() writes an apostrophe &#39;, Python's escape &#x27;.)
differ = [i for i in ALL if not drawn_all.get(i)
          or html.unescape(as_drawn_layout(drawn_all[i])) != html.unescape(as_stand_in(guide_sizers.stay(i)))]
kinds = {"named": 0, "unnamed": 0, "plain": 0}
for i in ALL:
    hh = drawn_all.get(i) or ""
    kinds["named" if "stayto stayhw" in hh and "hostels in" in hh else "unnamed" if "stayhw" in hh else "plain"] += 1
results.append(ok(len(drawn_all) == len(ALL) > 180 and not differ and min(kinds.values()) > 10,
                  "every country's stand-in is its drawn first chip's layout, span for span (%d countries: %s; differ: %s%s)"
                  % (len(ALL), kinds, differ[:6], " " + drawn_all["error"] if "error" in drawn_all else "")))
bad = []
for iso in sorted(COORDS):
    h = guide_sizers.stay(iso)
    sp = [s for s in (COORDS[iso] if isinstance(COORDS[iso], list) else []) if s.get("ll") and s.get("n")]
    if not sp:
        continue
    vr = guide_sizers.vrbo(iso)
    b = buttons(h)
    hw_named = sp[0]["n"] in HWC.get(iso, {})
    hw_cls = "stayto stayhw" if any(x["n"] in HWC.get(iso, {}) for x in sp) else ""
    if (not h.startswith('<div class="gsizer"') or '<div class="staytitle">🏨 Where to stay</div>' not in h
            or [x["place"] for x in b] != [sp[0]["n"]] * (2 if vr else 1) + [sp[0]["n"] if hw_named else None]
            or [x["cls"] for x in b] != ["stayto"] + (["stayto stayvr"] if vr else []) + [hw_cls]
            or ("staychip" in h) is not (len(sp) > 1) or "near" in h.split('<div class="staychips">')[0].split("staybtns")[0]):
        bad.append(iso)
results.append(ok(not bad, "every country's stand-in: the heading alone, Booking.com (and Vrbo where vrbo()) naming the first"
                  " spot, Hostelworld naming it where it has a city page, .stayhw where any spot has one, main's plain"
                  " button elsewhere; chips only for two spots or more (wrong: %s)" % bad[:8]))
# Every chip of every country, drawn by the stand-in's rule: a chip tap that
# names Hostelworld, or stops naming it, keeps .stayhw, so the row it starts
# from is the same width (the sweep in the browser measures the heights).
flip = [iso for iso in sorted(HWC) if not all(guide_sizers.stay(iso, [s] + [x for x in spots(iso) if x is not s]).count("stayhw") == 1
                                              for s in spots(iso))]
results.append(ok(not flip, "every country with a city page keeps .stayhw on Hostelworld whichever spot comes first"
                  " (lost on: %s)" % flip[:8]))

# --- the stylesheet ------------------------------------------------------------------------
def rule(sel):
    m = re.search(r"^%s \{([^}]*)\}" % re.escape(sel), CSS, re.M)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


bk, vr, at, hwr = rule(".staybtn.stayto"), rule(".staybtn.stayvr"), rule(".stayto .stayat"), rule(".staybtn.stayhw")
results.append(ok("flex: 1 1 19em" in bk and "min-width: min(19em, 100%)" in bk and "max-width: max-content" in bk
                  and "white-space: nowrap" in bk and "display: inline-flex" in bk
                  and "flex-basis: 13em" in vr and "min-width: min(13em, 100%)" in vr
                  and all(x in at for x in ("min-width: 0", "overflow: hidden", "text-overflow: ellipsis", "position: relative"))
                  and "flex: none" in rule(".stayto > *")
                  and re.search(r"flex-basis: ([\d.]+em); min-width: \1; min-width: min\(\1, 100%\)", hwr),
                  "styles.css: Booking.com at least 19em, Vrbo 13em, growing only to their content and shrinking only"
                  " to the column, one line, the place"
                  " cut with an ellipsis and holding its screen-reader words; Hostelworld's .stayhw a fixed start"
                  " width of its own (%s | %s | %s | %s)" % (bk, vr, at, hwr)))
with open(os.path.join(ROOT, "fxtracker", "guide_sizers.py"), encoding="utf-8") as f:
    SIZERS = f.read()
results.append(ok(not any("staynear" in t for t in (CSS, APP, SIZERS)), "no .staynear left (styles.css, app.js, guide_sizers)"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

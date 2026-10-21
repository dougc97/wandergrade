#!/usr/bin/env python3
"""No stays and no tours where ANY of the three governments says "do not
travel" — from hand-made advisory lists, no network, no server process.

    /usr/bin/python3 scripts/test_any_dnt.py

What it holds the code to:
  * fxtracker/advisories.py own_levels / dnt_for / dnt_sources: a government
    counts for its OWN Level 4 only (a gap it fills in another's list,
    stamped "via", is not read from there: Germany's own list rates Macau 1,
    whatever a stale fill says), a level written "4" is Level 4 and one that
    is no number rates nothing, two rows for one ISO count the most cautious
    (Gaza and the West Bank), a list not in hand is `unknown` and never a
    "no", and a territory a list doesn't rate on its own reads its parent
    there (the Faroes under Denmark, Guernsey and England under the UK)
    while one it does rate keeps its own;
  * server.py: /api/advisories marks every item some government's own list
    rates Level 4 (`dnt`, who says so), whichever list was asked for, names
    the lists not in hand (`dnt_pending`), never touches the cached payload;
    the guide's server render (_render_index) serves no stays stand-in and
    data-nostay for Burkina Faso, Saudi Arabia and Venezuela whichever ONE
    government says Level 4, and for the Faroes when Denmark's is, and
    serves Japan its stays; it writes Canada's and Germany's advisory
    stand-ins beside the US one with each government's level on #tab-guide
    (data-lvca, data-lvde), and the insurance stand-in wherever some
    government's reader gets the line (Burkina Faso: Germany's Level 2; not
    Afghanistan); index.html's first script (under jsc) picks the reader's
    stand-in and level before the first paint; the guide goes out no-store
    while a list is missing (unless one in hand already rules the country
    out); the missing list is fetched in the background, once while in
    flight and once per failure backoff (the real _cached runs, only the
    upstream call is stubbed), its stays stand-in held while in flight and
    dropped (data-nostay, `dnt_failed`) once the fetch has failed;
  * app.js guideNoBookings (run under jsc on the server's own payloads):
    true for every flagged country under every source the reader picks,
    false for Japan, null (no bookings drawn yet) while the advisories load
    or a list is pending and nothing in hand flags the country (dntSettled:
    worth waiting for unless the fetch failed); the stays, the tours button
    and the Trip tab's links read it — renderTripBook, run under jsc, draws
    Stays and Things to do only where it says false and redraws the rows
    once a pending list lands — and the insurance line keeps the reader's
    own level (guideAdvLevel).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories as A  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
PARENTS = server.guide_sizers.ADV_PARENT


def item(iso, level, **kw):
    return dict({"iso": iso, "country": iso, "level": level, "level_text": "", "link": "https://x/" + iso}, **kw)


def payload(src, rows):
    return {"items": rows, "count": len(rows), "source": src, "source_name": src}


# --- fixtures ---------------------------------------------------------------------
# Live on 2026-10-19: Burkina Faso US 4, CA 4, DE 2 (Teilreisewarnung); Saudi
# Arabia DE 4 (since 2026-10-11), US 3, CA 3; Venezuela CA 4, US 3, DE 2; Chad
# US 4, CA 3, DE 2. Japan 1 everywhere. Gaza (4) and the West Bank (3) are both
# PS. The US and Canada rate Denmark 4 here (made up) for the Faroes, which
# only Canada rates on its own (1). Macau: a stale gap-fill in the US list says DE 4, while
# Germany's own list says 1 — the fill is not Germany's word.
def lists(us_only=None):
    """The three lists; us_only=(iso, src) moves a country's only Level 4 to
    `src` (the others at 3, or 2 for Germany, which has no 3)."""
    us = [item("AF", 4), item("BF", 4), item("SA", 3), item("VE", 3), item("TD", 4), item("JP", 1), item("GB", 2),
          item("DK", 4), item("PS", 4), item("PS", 3), item("MO", 4, via="de", via_name="de"),
          item("FO", 1, via="ca", via_name="ca")]
    ca = [item("AF", 4), item("BF", 4), item("SA", 3), item("VE", "4"), item("TD", 3), item("JP", 1), item("GB", 2),
          item("DK", 4), item("FO", 1), item("MO", 2), item("PS", 4, via="us", via_name="us")]
    de = [item("AF", 4), item("BF", 2), item("SA", 4), item("VE", 2), item("TD", 2), item("JP", 1), item("GB", 1),
          item("DK", 1), item("PS", 4), item("MO", 1), item("XX", "n/a")]
    out = {"us": payload("us", us), "ca": payload("ca", ca), "de": payload("de", de)}
    if us_only:
        iso, src = us_only
        for s, p in out.items():
            for it in p["items"]:
                if it["iso"] == iso and not it.get("via"):
                    it["level"] = 4 if s == src else (2 if s == "de" else 3)
    return out


# --- advisories.py -----------------------------------------------------------------
P = lists()
own = {s: A.own_levels(p) for s, p in P.items()}
results.append(ok(own["ca"]["VE"] == 4 and "XX" not in own["de"], "a level written \"4\" is Level 4; one that is no number rates nothing"))
results.append(ok(own["us"]["PS"] == 4, "two rows for one ISO: the most cautious (Gaza 4 over the West Bank 3)"))
results.append(ok("MO" not in own["us"] and "FO" not in own["us"] and "PS" not in own["ca"], "a gap-fill (via) is not the list's own rating"))
flags, unknown = A.dnt_sources(P, PARENTS)
results.append(ok(flags.get("BF") == ["us", "ca"] and flags.get("SA") == ["de"] and flags.get("VE") == ["ca"]
                  and flags.get("TD") == ["us"] and flags.get("PS") == ["us", "de"],
                  "who says Level 4, in US-CA-DE order: %s" % {k: flags.get(k) for k in ("BF", "SA", "VE", "TD", "PS")}))
results.append(ok("JP" not in flags and "MO" not in flags and "GB" not in flags and unknown == [],
                  "Japan, the UK and Macau (a stale fill saying DE 4, Germany's own list 1) are not flagged"))
results.append(ok(A.dnt_for("GG", own, PARENTS) == [] and A.dnt_for("GB-ENG", own, PARENTS) == []
                  and A.dnt_for("FO", own, PARENTS) == ["us"] and flags.get("FO") == ["us"],
                  "a territory reads its parent where a list doesn't rate it (the Faroes: the US list's Denmark), "
                  "keeps its own where it does (Canada's 1, not its Denmark 4) (FO %s)" % A.dnt_for("FO", own, PARENTS)))
P2 = dict(P, us=dict(P["us"], items=[i for i in P["us"]["items"] if i["iso"] != "DK"]))
own2 = {s: A.own_levels(p) for s, p in P2.items()}
results.append(ok(A.dnt_for("FO", own2, PARENTS) == [], "no parent in a list: nothing borrowed from another list"))
miss = dict(P, de=None)
f3, u3 = A.dnt_sources(miss, PARENTS)
results.append(ok(u3 == ["de"] and "SA" not in f3 and f3.get("BF") == ["us", "ca"],
                  "a list not in hand is unknown, not a no: Saudi Arabia unflagged, Burkina Faso still flagged by the two in hand"))
f4, u4 = A.dnt_sources({"us": None, "ca": None, "de": None}, PARENTS)
results.append(ok(f4 == {} and u4 == ["us", "ca", "de"], "no list in hand: no flags, all three unknown"))

# --- server.py: the marks /api/advisories serves -----------------------------------
# The upstream fetch itself is stubbed (advisories.get_advisories), so the
# server's own _advisories_payload, _cached and its failure backoff run.
fetched = []
gate = {"mode": "fail", "event": None}


def fake_fetch(src):
    fetched.append(src)
    if gate["mode"] == "slow":
        gate["event"].wait(10)
        return json.loads(json.dumps(lists()[src]))
    raise RuntimeError("offline")


A.get_advisories = fake_fetch
server._warm_watchouts = lambda iso: None          # Canada's notes: no fetch
server.flights.is_configured = lambda: False      # no fare warm-up to wait for
NOTES = {"iso": "", "source": "Global Affairs Canada", "watchouts": [], "regional": []}
notes_on = [False]
server.watchouts.cached = lambda iso: dict(NOTES, iso=iso) if notes_on[0] else None


def settle():
    """Let the background fetches started so far finish."""
    for _ in range(200):
        if not server._adv_warming:
            return
        time.sleep(0.02)


def load(P):
    settle()
    now = time.time()
    server._adv_cache.clear()
    server._upstream_fail.clear()
    server._adv_failed.clear()
    for s, p in P.items():
        if p is not None:
            server._adv_cache[s] = (now, p)


load(lists())
dnt = server._adv_dnt()
for s in ("us", "ca", "de"):
    served = server._with_dnt(server._adv_cache[s][1], dnt)
    by = {it["iso"]: it.get("dnt") for it in served["items"] if it.get("iso")}
    results.append(ok(by.get("BF") == ["us", "ca"] and by.get("SA") == ["de"] and by.get("VE") == ["ca"]
                      and by.get("JP") is None and "dnt_pending" not in served,
                      "/api/advisories?source=%s marks BF, SA and VE whoever says it, not JP" % s))
results.append(ok(not any("dnt" in it for p in lists().values() for it in p["items"])
                  and not any("dnt" in it for _t, p in server._adv_cache.values() for it in p["items"]),
                  "the cached payloads are left untouched"))
results.append(ok(server._adv_dnt() is dnt, "memoized while the cached lists are the same objects"))


def page(iso):
    return server._render_index(iso).decode("utf-8")


def tab(html_):
    m = re.search(r'<section class="tab" id="tab-guide"[^>]*>', html_)
    return m.group(0) if m else ""


def block(html_, el):
    m = re.search(r'<div id="%s" class="[^"]*">(.*?)</div>\s*<div id=' % el, html_, re.S)
    return m.group(1) if m else None


for iso in ("BF", "SA", "VE"):
    for src in ("us", "ca", "de"):
        load(lists(us_only=(iso, src)))
        h = page(iso)
        stay = block(h, "guideStay")
        results.append(ok('data-nostay="1"' in tab(h) and stay == "",
                          "%s, Level 4 by %s alone: data-nostay, no stays stand-in (%s, %r)" % (iso, src, tab(h), (stay or "")[:40])))
load(lists(us_only=("SA", "de")))
h = page("SA")
results.append(ok('data-for="SA"' in (block(h, "guideInsurance") or ""), "Saudi Arabia keeps the insurance stand-in (the US level, 3)"))
load(lists())
h = page("JP")
results.append(ok("data-nostay" not in tab(h) and 'data-for="JP"' in (block(h, "guideStay") or ""), "Japan: its stays stand-in, no data-nostay"))
h = page("FO")
results.append(ok('data-nostay="1"' in tab(h), "the Faroes: no stays where a list rates Denmark 4 and not the Faroes (the US list here)"))
load(lists(us_only=("TD", "us")))
results.append(ok('data-nostay="1"' in tab(page("TD")), "Chad, US Level 4 only: data-nostay (it has stay spots)"))

# The advisory stand-in and level for the reader's own government.
def sizers(html_, el):
    return re.findall(r'<div class="gsizer"[^>]*data-for="[^"]*"([^>]*)>', block(html_, el) or "")


notes_on[0] = True
load(lists())
h = page("BF")
results.append(ok(sizers(h, "guideSafety") == ["", ' data-src="ca"', ' data-src="de"']
                  and "Level 4 · Do not travel" in h and "Level 4 · Avoid all travel" in h and "Some regions" in h,
                  "Burkina Faso: the US, Canadian and German advisory stand-ins, Canada's and Germany's marked (%s)"
                  % sizers(h, "guideSafety")))
results.append(ok('data-lvca="4"' in tab(h) and 'data-lvde="2"' in tab(h),
                  "and each one's level on #tab-guide (%s)" % tab(h)))
results.append(ok('data-for="BF"' in (block(h, "guideInsurance") or ""),
                  "Burkina Faso keeps an insurance stand-in: a German-source reader (Level 2) gets the line"))
h = page("AF")
results.append(ok('<div id="guideInsurance" class="afflink"></div>' in h and 'data-lvca="4"' in tab(h) and 'data-lvde="4"' in tab(h),
                  "Afghanistan, Level 4 to all three: no insurance stand-in for anyone"))
h = page("JP")
results.append(ok('data-lvca="1"' in tab(h) and 'data-lvde="1"' in tab(h)
                  and 'data-for="JP"' in (block(h, "guideInsurance") or ""), "Japan: Level 1 to Canada and Germany"))
load(dict(lists(), de=None))
h = page("BF")
results.append(ok(sizers(h, "guideSafety") == ["", ' data-src="ca"'] and "data-lvde" not in tab(h),
                  "Germany's list not in hand: no German stand-in or level (the reader keeps the US one)"))
notes_on[0] = False
CSS = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
results.append(ok('#tab-guide[data-gsrc="de"] #guideSafety > .gsizer[data-src="de"]' in CSS
                  and "#tab-guide[data-gsrc] #guideSafety > .gsizer:not([data-src])" in CSS
                  and '#tab-guide[data-level="4"] #guideInsurance:has(> .gsizer)' in CSS,
                  "styles.css shows the reader's stand-in only and drops the insurance one under their Level 4"))
# index.html's first script, under jsc: a German-source reader on Burkina Faso.
IDX = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
m = re.search(r'<script>(\(function\(\)\{try\{var o=localStorage\.getItem\("fx_origin"\).*?)</script>', IDX, re.S)
pre = m.group(1) if m else ""
prog = """
function el(a) { return { a: a, getAttribute: function (k) { return k in this.a ? this.a[k] : null; },
  setAttribute: function (k, v) { this.a[k] = String(v); }, removeAttribute: function (k) { delete this.a[k]; } }; }
const out = {};
for (const [name, src, attrs] of %s) {
  const t = el(attrs);
  var localStorage = { getItem: function (k) { return k === "wg_advsrc" ? src : null; } };
  var document = { getElementById: function () { return t; } };
  %s
  out[name] = t.a;
}
print(JSON.stringify(out));""" % (json.dumps([
    ["bf_de", "de", {"data-level": "4", "data-lvca": "4", "data-lvde": "2"}],
    ["bf_ca", "ca", {"data-level": "4", "data-lvca": "4", "data-lvde": "2"}],
    ["bf_us", "us", {"data-level": "4", "data-lvca": "4", "data-lvde": "2"}],
    ["sa_de", "de", {"data-level": "3", "data-lvca": "3", "data-lvde": "4"}],
    ["xx_de", "de", {"data-level": "2", "data-lvca": "2", "data-lvde": "0"}],
    ["nolist_de", "de", {"data-level": "4", "data-lvca": "4"}],
]), pre)
try:
    pj = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception as e:
    pj = {"error": str(e)}
results.append(ok(bool(pre) and (pj.get("bf_de") or {}).get("data-gsrc") == "de" and pj["bf_de"].get("data-level") == "2"
                  and pj["bf_ca"].get("data-gsrc") == "ca" and pj["bf_ca"].get("data-level") == "4"
                  and "data-gsrc" not in pj["bf_us"] and pj["bf_us"].get("data-level") == "4"
                  and pj["sa_de"].get("data-level") == "4" and "data-level" not in pj["xx_de"]
                  and "data-gsrc" not in pj["nolist_de"] and pj["nolist_de"].get("data-level") == "4",
                  "index.html's first script: the reader's source and its level before the first paint (%s)" % pj))

# Cache-Control while a list is missing, and the background fetch.
load(lists())
results.append(ok(server._guide_cache("JP") == "public, max-age=300", "all three in hand: the guide is cacheable"))
# Germany's list on its way (the fetch in flight): held, not known.
gate.update(mode="slow", event=threading.Event())
load(dict(lists(), de=None))
fetched.clear()
results.append(ok(server._guide_cache("JP") == "no-store" and server._guide_cache("SA") == "no-store",
                  "Germany's list missing: Japan and Saudi Arabia go out no-store"))
results.append(ok(server._guide_cache("BF") == "public, max-age=300", "Burkina Faso is ruled out by the lists in hand: cacheable"))
for _ in range(5):
    server._warm_adv_lists()
time.sleep(0.1)
results.append(ok(fetched == ["de"], "one fetch for the missing list while it is in flight, however many ask (%s)" % fetched))
served = server._with_dnt(server._adv_cache["us"][1], server._adv_dnt())
results.append(ok(served.get("dnt_pending") == ["de"] and "dnt_failed" not in served,
                  "dnt_pending names the list on its way; it hasn't failed (%s)" % {k: served.get(k) for k in ("dnt_pending", "dnt_failed")}))
results.append(ok('data-nostay' not in tab(page("SA")) and 'data-for="SA"' in (block(page("SA"), "guideStay") or ""),
                  "Saudi Arabia before Germany's list: its stays stand-in stays (held, not known)"))
gate["event"].set()
settle()
results.append(ok("de" in server._adv_cache and not server._adv_dnt()["unknown"], "the list lands in the cache"))
results.append(ok('data-nostay="1"' in tab(page("SA")), "and Saudi Arabia's next render knows: data-nostay"))
# Germany's list failing: one fetch per backoff, then no stays drawn at all.
gate["mode"] = "fail"
load(dict(lists(), de=None))
fetched.clear()
server._guide_cache("JP")
settle()
for _ in range(5):
    server._guide_cache("JP")
    server._warm_adv_lists()
settle()
results.append(ok(fetched == ["de"], "a failed fetch is not retried inside its backoff (FAIL_RETRY): %s" % fetched))
served = server._with_dnt(server._adv_cache["us"][1], server._adv_dnt())
results.append(ok(served.get("dnt_pending") == ["de"] and served.get("dnt_failed") == ["de"],
                  "dnt_failed names it (%s)" % {k: served.get(k) for k in ("dnt_pending", "dnt_failed")}))
h = page("JP")
results.append(ok('data-nostay="1"' in tab(h) and (block(h, "guideStay") or "") == ""
                  and server._guide_cache("JP") == "no-store",
                  "while it is failing, a guide holds no stays it can't draw (data-nostay), and goes out no-store"))
gate.update(mode="slow", event=threading.Event())
gate["event"].set()
server._upstream_fail.clear()          # the backoff over
server._warm_adv_lists()
settle()
results.append(ok("de" not in server._adv_failed and not server._adv_dnt()["unknown"]
                  and "data-nostay" not in tab(page("JP")), "back: the list is in and Japan's stays return"))

# --- app.js guideNoBookings under jsc --------------------------------------------------
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M)
    return m.group(0) if m else ""


cases = {}
load(lists())
d = server._adv_dnt()
for s in ("us", "ca", "de"):
    cases[s] = server._with_dnt(server._adv_cache[s][1], d)
load(dict(lists(), de=None))
cases["us_pending"] = server._with_dnt(server._adv_cache["us"][1], server._adv_dnt())
server._adv_failed.add("de")
cases["us_failed"] = server._with_dnt(server._adv_cache["us"][1], server._adv_dnt())
server._adv_failed.clear()
cases["none"] = None
prog = "\n".join([js_const("GUIDE_PARENT"), js_const("ADV_PARENT"), "let advisories = null;",
                  js_fn("advisoryMetaByIso"), js_fn("guideAdvLevel"), js_fn("guideNoBookings"),
                  js_const("dntSettled")]) + """
const C = %s, out = {};
for (const k in C) {
  advisories = C[k];
  out[k] = {};
  for (const iso of ["BF", "SA", "VE", "TD", "PS", "JP", "FO", "GG", "GB-ENG"]) out[k][iso] = guideNoBookings(iso);
  if (advisories) out[k].settled = dntSettled(advisories);
}
print(JSON.stringify(out));""" % json.dumps(cases)
try:
    js = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception as e:
    js = {"error": str(e)}
for s in ("us", "ca", "de"):
    r = js.get(s) or {}
    results.append(ok(all(r.get(i) is True for i in ("BF", "SA", "VE", "TD", "PS", "FO"))
                      and r.get("JP") is False and r.get("GG") is False and r.get("GB-ENG") is False,
                      "guideNoBookings, a %s reader: true for BF, SA, VE, TD, PS, FO; false for JP, GG, England (%s)" % (s, r)))
r = js.get("us_pending") or {}
results.append(ok(r.get("BF") is True and r.get("TD") is True and r.get("SA") is None and r.get("JP") is None
                  and r.get("settled") is False,
                  "a list pending: true where a list in hand says 4, null (nothing drawn yet) elsewhere, worth waiting for (%s)" % r))
r = js.get("us_failed") or {}
results.append(ok(r.get("BF") is True and r.get("SA") is None and r.get("JP") is None and r.get("settled") is True,
                  "a list whose fetch failed: still null, but settled — nothing to wait for (%s)" % r))
results.append(ok((js.get("us") or {}).get("settled") is True, "all three in hand: settled"))
r = js.get("none") or {}
results.append(ok(r and all(v is None for v in r.values()), "advisories still loading: null for every country"))

# Who reads it. The insurance line keeps the reader's own level.
ins = js_fn("renderGuideInsurance")
results.append(ok("guideAdvLevel(iso) === 4" in ins and "guideNoBookings(" not in ins,
                  "renderGuideInsurance: the reader's own level, not the any-government flag"))
results.append(ok("guideNoBookings(iso) !== false" in js_fn("renderGuideStay")
                  and "ensureBookingsKnown()" in js_fn("renderGuideStay"),
                  "renderGuideStay: no stays unless guideNoBookings says false"))
act = js_fn("renderActivity")
results.append(ok("const nb = guideNoBookings(iso);" in act and "guideAdvLevel" not in act,
                  "renderActivity: the tours button reads guideNoBookings"))

# The Trip tab's rows under jsc (renderTripBook with its page around it
# stubbed): Stays and Things to do only where guideNoBookings says false, so
# none while a list is pending, and the rows redrawn once the marks land.
trip_prog = "\n".join([js_const("GUIDE_PARENT"), js_const("ADV_PARENT"), "let advisories = null;",
                       js_fn("advisoryMetaByIso"), js_fn("guideAdvLevel"), js_fn("guideNoBookings"),
                       js_const("dntSettled"), js_fn("renderTripBook")]) + """
const C = %s, out = {};
const host = { innerHTML: "", isConnected: true, querySelectorAll: () => [], querySelector: () => null };
const $ = (id) => (id === "tripBook" ? host : null), esc = (x) => String(x);
const tripMonth = () => ({ flexible: true }), nextMonthKey = () => null, loadWishlist = () => new Set();
let wishlist = new Set(), climate = null, flightsData = null;
const MONTHS = [], originLabel = () => "the US", countryName = (i) => i, flightSearchURL = () => "f";
const viatorURL = (n) => "https://viator.example/" + n, flagEmoji = () => "", guidePath = (i) => "/guide/" + i;
const advLevelText = () => "", advVia = () => "", insuranceHref = () => "ins", bindTripActions = () => {};
const fareStripOpts = () => ({}), ensureFareMonths = async () => null, ensureStayCoords = () => Promise.resolve({});
const trip = ["BF", "SA", "JP"], loadTrip = () => new Set(trip);
const advisoryByIso = () => { const m = {}; for (const it of advisories.items) if (it.iso) m[it.iso] = Number(it.level) || 0; return m; };
let asked = 0, draws = 0;
const ensureBookingsKnown = () => { asked++; advisories = C.us; return Promise.resolve(C.us); };
const links = () => { const o = {}; for (const iso of trip) {
  const at = host.innerHTML.indexOf('<div class="tbrow" data-iso="' + iso + '"');
  const row = at < 0 ? "" : host.innerHTML.slice(at).split('<div class="tbrow')[1];
  o[iso] = (row.match(/Things to do/g) || []).length + (row.match(/class="tbstay"/g) || []).length; } return o; };
advisories = C.us; renderTripBook(trip); out.all = links();
advisories = C.us_failed; asked = 0; renderTripBook(trip); out.failed = links(); out.failed_asked = asked;
advisories = C.us_pending; asked = 0; renderTripBook(trip); out.pending = links(); out.pending_asked = asked;
Promise.resolve().then(() => 0).then(() => { out.landed = links(); print(JSON.stringify(out)); });
""" % json.dumps({k: cases[k] for k in ("us", "us_pending", "us_failed")})
try:
    tj = json.loads(subprocess.run([JSC, "-e", trip_prog], capture_output=True, text=True, timeout=30).stdout)
except Exception as e:
    tj = {"error": str(e)}
results.append(ok(tj.get("all") == {"BF": 0, "SA": 0, "JP": 2},
                  "renderTripBook, all lists in: Stays and Things to do for Japan only, none for BF or SA (%s)" % tj.get("all")))
results.append(ok(tj.get("pending") == {"BF": 0, "SA": 0, "JP": 0} and tj.get("pending_asked") == 1,
                  "a list pending: no links for any row yet, and the marks are asked for (%s, asked %s)"
                  % (tj.get("pending"), tj.get("pending_asked"))))
results.append(ok(tj.get("landed") == {"BF": 0, "SA": 0, "JP": 2},
                  "once they land the rows are redrawn: Japan's links, still none for BF or SA (%s)" % tj.get("landed")))
results.append(ok(tj.get("failed") == {"BF": 0, "SA": 0, "JP": 0} and tj.get("failed_asked") == 0,
                  "a list failed: no links, and nothing waited for (%s, asked %s)" % (tj.get("failed"), tj.get("failed_asked"))))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

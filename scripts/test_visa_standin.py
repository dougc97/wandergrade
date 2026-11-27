"""The guide's visa line for a reader whose passport isn't the US's: the
server's stand-ins for every other From (fxtracker/guide_sizers.visa_passports,
a <template> after #guideVisa), the index.html script that puts the reader's
in place before the first paint, and public/app.js renderGuideVisa holding
that room until its line is drawn. app.js runs under jsc
(scripts/appjs_harness.js) on public/visa-passport.json and visa.json.

    /usr/bin/python3 scripts/test_visa_standin.py

The page is served with the US passport's line (guide_sizers.visa), and a
German passport's is a line longer at 390 (its government's "official
details" link, "(Passport Index)"): drawn when the matrix landed, ~3 s into a
slow load, it took the advisory and everything under it 19px down (CLS 0.003
on Thailand and Morocco for a returning German reader). What it holds the
code to:
  * each stand-in is the line app.js draws for that passport, word for word
    and tag for tag (links without their targets), on every guide and for
    every From the picker offers: home (a German on Germany, a Briton on
    Scotland), the Common Travel Area (a Briton on Guernsey), a matrix with
    no entry (an empty stand-in: app.js hides the line), a German or
    Canadian passport's link from that government's list (a gap-fill's link
    never counts, a territory reads its parent's entry, a link to another
    site is no link);
  * no German or Canadian stand-in when that government's list isn't cached
    (the server can't know the link): those readers keep today's US one;
  * the script picks the saved From's stand-in, a shared link's ?vo= / ?fo=
    over it (?vo=US keeps the US one; a From the picker doesn't offer is
    ignored, as app.js ignores it; a From it offers that has no stand-in,
    a German one before Germany's list is cached, keeps the US one, not the
    saved From's: app.js draws the link's passport), empties and hides the
    block for a passport that gets no line, and does nothing without a saved
    From or when storage throws; every From it follows is one app.js
    follows (CUR_BY_ISO);
  * renderGuideVisa, waiting for the matrix, holds this guide's stand-in for
    the reader's passport (the geo seed sets the From after the first
    paint), and none for another guide;
  * a German or Canadian line drawn while its government's list is still
    loading keeps the held room until the redraw with the link, and lets it
    go if that list fails; a US line holds nothing;
  * the homepage has no stand-ins (its token is empty) and index.html has
    the token right after #guideVisa.
"""
import html, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import flights, guide_sizers  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
SLUGS = load("public", "slugs.json")
GUIDES = sorted(set(SLUGS.values()))
PASSPORTS = sorted(p for p in flights.ORIGIN_HUBS if p != "US")

# The German and Canadian lists, as much of them as the line reads: an entry's
# link, a gap-fill (via) whose link must not count, a link to another site,
# the UK's entry that Guernsey and Scotland read, and countries with none.
DE_ITEMS = [{"iso": "TH", "link": "https://www.auswaertiges-amt.de/de/service/laender/thailand-node/thailandsicherheit-201558"},
            {"iso": "MA", "via": "us", "link": "https://www.auswaertiges-amt.de/de/service/laender/marokko-node"},
            {"iso": "JP", "link": "https://example.org/japan"},
            {"iso": "GB", "link": "https://www.auswaertiges-amt.de/de/service/laender/grossbritannien-node"},
            {"iso": "FR", "link": "https://auswaertiges-amt.de/de/service/laender/frankreich-node"}]
CA_ITEMS = [{"iso": "TH", "link": "https://travel.gc.ca/destinations/thailand"},
            {"iso": "MA", "link": "https://travel.gc.ca/destinations/morocco"},
            {"iso": "MA", "via": "us", "link": "https://travel.gc.ca/destinations/morocco-other"},
            {"iso": "GB", "link": "https://travel.gc.ca/destinations/united-kingdom"},
            {"iso": "DK", "link": "http://travel.gc.ca/destinations/denmark"}]
ADV = {"DE": DE_ITEMS, "CA": CA_ITEMS}


def alts(iso, adv=ADV):
    """{passport: inner markup or "" (empty stand-in)} of the served template."""
    t = guide_sizers.visa_passports(iso, flights.ORIGIN_HUBS, adv)
    m = re.match(r'<template id="guideVisaAlt">(.*)</template><script>', t, re.S)
    out = {}
    for pp, f, inner in re.findall(r'<div class="gsizer" aria-hidden="true" data-nosnippet data-for="([^"]*)" '
                                   r'data-pp="([A-Z]{2})">(.*?)</div>', m.group(1) if m else "", re.S):
        out[f] = (pp, inner)
    return out


SERVED = {iso: alts(iso) for iso in GUIDES}

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
visaMatrix = FIX.matrix; visa = FIX.visa;
_advBySource.de = { items: FIX.de }; _advBySource.ca = { items: FIX.ca };
const host = $("guideVisa");
const out = { lines: {}, wait: {}, link: {}, unfollowed: FIX.hubs.filter((c) => !CUR_BY_ISO[c]) };
for (const iso of FIX.guides) {
  ccGuideIso = iso;
  for (const p of FIX.passports) {
    localStorage.setItem("fx_origin", p);
    host.innerHTML = ""; host.hidden = false; host.style.minHeight = ""; host.dataset = {};
    renderGuideVisa(iso);
    out.lines[iso + ":" + p] = host.hidden ? null : host.innerHTML;
  }
}
// The wait for the matrix: the template's stand-in for this guide and passport.
const tpl = {}; for (const k in FIX.tpl) tpl[k] = FIX.tpl[k];
__els.guideVisaAlt = { content: { querySelector: (q) => {
  const m = /data-pp="([A-Z]{2})"/.exec(q), e = m && tpl[m[1]];
  return e ? { dataset: { for: e.for }, cloneNode: () => ({ standin: e.for + ":" + m[1] }) } : null;
} } };
visaMatrix = null; ensureVisaMatrix = () => new Promise(() => {});
for (const [iso, p] of FIX.waitCases) {
  ccGuideIso = iso; localStorage.setItem("fx_origin", p);
  const got = []; host.appendChild = (c) => { got.push(c.standin || "?"); return c; };
  host.innerHTML = "x"; host.hidden = true;
  renderGuideVisa(iso);
  out.wait[iso + ":" + p] = { appended: got, empty: host.innerHTML === "", shown: !host.hidden };
}
// A German line drawn while its government's list loads.
visaMatrix = FIX.matrix;
let settle = null;
fetchAdv = () => new Promise((res, rej) => { settle = { res, rej }; });
const linkRun = async (p, iso, fail) => {
  ccGuideIso = iso; localStorage.setItem("fx_origin", p);
  delete _advBySource.de; delete _advBySource.ca;
  host.innerHTML = ""; host.hidden = false; host.dataset = { for: iso }; host.style.minHeight = "78px"; settle = null;
  renderGuideVisa(iso);
  const first = { minH: host.style.minHeight, link: /official details/.test(host.innerHTML), asked: !!settle };
  if (settle) {
    if (fail) settle.rej(new Error("down"));
    else { _advBySource[p.toLowerCase()] = { items: p === "DE" ? FIX.de : FIX.ca }; settle.res(); }
    await new Promise((r) => r()); await new Promise((r) => r()); await new Promise((r) => r());
  }
  return { first, after: { minH: host.style.minHeight, link: /official details/.test(host.innerHTML) } };
};
(async () => {
  out.link.de = await linkRun("DE", "TH", false);
  out.link.ca = await linkRun("CA", "MA", false);
  out.link.fail = await linkRun("DE", "TH", true);
  out.link.us = await linkRun("US", "TH", false);
  // Another guide's held room (in-app navigation) is not this one's.
  ccGuideIso = "TH"; localStorage.setItem("fx_origin", "DE"); delete _advBySource.de; fetchAdv = () => new Promise(() => {});
  host.innerHTML = ""; host.dataset = { for: "JP" }; host.style.minHeight = "99px";
  renderGuideVisa("TH");
  out.link.other = host.style.minHeight;
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

WAIT = [("TH", "DE"), ("TH", "GB"), ("MA", "CA"), ("DE", "DE"), ("GG", "AU")]
TPL = {pp: {"for": v[0]} for pp, v in SERVED["TH"].items()}
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump({"matrix": load("public", "visa-passport.json"), "visa": load("public", "visa.json"),
               "de": DE_ITEMS, "ca": CA_ITEMS, "guides": GUIDES, "passports": PASSPORTS,
               "tpl": TPL, "waitCases": WAIT, "hubs": sorted(flights.ORIGIN_HUBS)}, open(fp, "w"))
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


def norm(h):
    """The markup as it lays out: links without their targets, whitespace runs as one space,
    character references as the characters they are (&#x27; and &#39; are both ')."""
    h = re.sub(r"<a [^>]*>", "<a>", h or "")
    return html.unescape(re.sub(r"\s+", " ", h).strip())


# --- every stand-in is the line app.js draws -------------------------------------------
L = js["lines"]
bad, n, empty, home, linked = {}, 0, 0, 0, 0
for iso in GUIDES:
    for p in PASSPORTS:
        drawn = L["%s:%s" % (iso, p)]
        pp = SERVED[iso].get(p)
        if pp is None:
            bad["%s:%s" % (iso, p)] = ("no stand-in", drawn)
            continue
        f, inner = pp
        n += 1
        empty += inner == ""
        home += "Your home country" in inner
        linked += "official details" in inner
        if f != iso or (drawn is None and inner != "") or (drawn is not None and norm(inner) != norm(drawn)):
            bad["%s:%s" % (iso, p)] = (norm(inner), norm(drawn))
results.append(ok(not bad and n == len(GUIDES) * len(PASSPORTS) and empty and home and linked,
                  "every guide has a stand-in for each of the %d other Froms, each the line app.js draws for that "
                  "passport (%d checked: %d home lines, %d with a government's link, %d where the matrix has no "
                  "entry and app.js hides the line) %s"
                  % (len(PASSPORTS), n, home, linked, empty, dict(list(bad.items())[:4]))))
th = {p: norm(SERVED["TH"][p][1]) for p in ("DE", "GB", "CA")}
results.append(ok("<b>Visa · German passport:</b>" in th["DE"] and "<a>official details ↗</a>" in th["DE"]
                  and "(Passport Index); verify before booking" in th["DE"] and "<a>" not in th["GB"]
                  and "<b>Visa · Canadian passport:</b>" in th["CA"] and "<a>official details ↗</a>" in th["CA"],
                  "Thailand: the German and Canadian lines carry their government's link, the British none: %r"
                  % re.sub(r"<[^>]+>", "", html.unescape(th["DE"]))))
sp = {k: norm(SERVED[k[0]][k[1]][1]) for k in [("DE", "DE"), ("GB-SCT", "GB"), ("GG", "GB"), ("MA", "DE"),
                                                ("JP", "DE"), ("GG", "DE"), ("GB-SCT", "CA"), ("FO", "CA")]}
results.append(ok("Your home country" in sp[("DE", "DE")] and "Your home country" in sp[("GB-SCT", "GB")]
                  and "Your home country" not in sp[("GG", "GB")]
                  and "<a>" not in sp[("MA", "DE")] and "<a>" not in sp[("JP", "DE")]
                  and "<a>" in sp[("GG", "DE")] and "<a>" in sp[("GB-SCT", "CA")] and "<a>" not in sp[("FO", "CA")],
                  "home on Germany and Scotland, not Guernsey for a Briton; no link from a gap-fill (Morocco), "
                  "another site (Japan) or http (the Faroes' Denmark); Guernsey and Scotland read the UK's entry"))

# --- no list cached: no German or Canadian stand-in ---------------------------------------
part = alts("TH", {"DE": DE_ITEMS})
none = alts("TH", {})
results.append(ok("CA" not in part and "DE" in part and "DE" not in none and "CA" not in none
                  and "GB" in none and len(none) == len(PASSPORTS) - 2,
                  "a German or Canadian passport gets no stand-in while that government's list isn't cached "
                  "(the link comes from it); the other %d still do" % (len(PASSPORTS) - 2)))

# --- the script that picks before the first paint -------------------------------------------
PICK = re.search(r"<script>(.*)</script>$", guide_sizers.visa_passports("TH", flights.ORIGIN_HUBS, ADV), re.S).group(1)
PICKER = r"""
var CASES = JSON.parse(read(CASES_PATH)), res = {};
CASES.forEach(function (c) {
  var kids = [{ us: 1 }], host = { hidden: false, get firstChild() { return kids[0] || null; },
    removeChild: function (k) { kids.splice(kids.indexOf(k), 1); }, appendChild: function (k) { kids.push(k); } };
  var tpl = { content: { querySelector: function (q) { var m = /data-pp="([A-Z]{2})"/.exec(q);
    if (!m || c.tpl.indexOf(m[1]) < 0) return null;
    return { firstChild: m[1] === "NO" ? null : {}, cloneNode: function () { return { pp: m[1] }; } }; } } };
  var document = { getElementById: function (id) { return id === "guideVisa" ? host : id === "guideVisaAlt" ? tpl : null; } };
  var location = { search: c.q };
  var localStorage = { getItem: function (k) { if (c.boom) throw new Error("blocked"); return k === "fx_origin" ? c.o : null; } };
  var URLSearchParams = function (s) { var o = {}; s.replace(/^\?/, "").split("&").forEach(function (kv) {
    var i = kv.indexOf("="); if (i > 0) o[kv.slice(0, i)] = kv.slice(i + 1); }); this.get = function (k) { return k in o ? o[k] : null; }; };
  (function () { BODY })();
  res[c.name] = { kids: kids.map(function (k) { return k.us ? "US" : k.pp; }), hidden: host.hidden };
});
print(JSON.stringify(res));
"""
TPLS = ["DE", "GB", "CA", "NO"]   # NO: a passport whose stand-in is empty (no line)
CASES = [{"name": "none", "o": None, "q": ""}, {"name": "us", "o": "US", "q": ""},
         {"name": "de", "o": "DE", "q": ""}, {"name": "vo", "o": "DE", "q": "?vo=GB"},
         {"name": "fo", "o": None, "q": "?tab=guide&fo=CA"}, {"name": "vous", "o": "DE", "q": "?vo=US"},
         {"name": "vozz", "o": "DE", "q": "?vo=ZZ"}, {"name": "nolist", "o": "AU", "q": ""},
         {"name": "noline", "o": "NO", "q": ""}, {"name": "boom", "o": "DE", "q": "", "boom": 1},
         # A link's From the picker offers but the page has no stand-in for (Germany's list not
         # cached at render): app.js draws the German line, so the US one stays, not the saved Briton's.
         {"name": "vonone", "o": "GB", "q": "?vo=DE", "tpl": ["GB", "CA", "NO"]},
         {"name": "fonone", "o": "DE", "q": "?tab=guide&fo=AU"},
         {"name": "vobad", "o": "DE", "q": "?vo=DE,GB"}]
for c in CASES:
    c.setdefault("tpl", TPLS)
body = PICK.replace("(function(){", "", 1)
body = body[:body.rindex("})();")]
with tempfile.TemporaryDirectory() as d:
    cp, sp = os.path.join(d, "cases.json"), os.path.join(d, "pick.js")
    json.dump(CASES, open(cp, "w"))
    open(sp, "w", encoding="utf-8").write(PICKER.replace("CASES_PATH", json.dumps(cp)).replace("BODY", body))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=30)
try:
    pk = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    pk = {"error": (r.stderr or r.stdout)[-400:]}
want = {"none": (["US"], False), "us": (["US"], False), "de": (["DE"], False), "vo": (["GB"], False),
        "fo": (["CA"], False), "vous": (["US"], False), "vozz": (["DE"], False), "nolist": (["US"], False),
        "noline": ([], True), "boom": (["US"], False), "vonone": (["US"], False), "fonone": (["US"], False),
        "vobad": (["DE"], False)}
got = {k: (v["kids"], v["hidden"]) for k, v in pk.items()} if "error" not in pk else pk
results.append(ok(got == want,
                  "before the first paint: the saved From's stand-in, a shared ?vo= / ?fo= over it (?vo=US keeps "
                  "the US one, an unknown ?vo= is ignored), the block emptied and hidden for a passport with no "
                  "line, the US one kept with no saved From, a From without a stand-in (saved or a link's), or "
                  "storage blocked %s" % ("" if got == want else got)))
FROMS = re.search(r'"(,[A-Z,]+,)"\.indexOf', PICK)
results.append(ok(FROMS is not None and FROMS.group(1) == "," + ",".join(sorted(flights.ORIGIN_HUBS)) + ","
                  and js["unfollowed"] == [],
                  "the script follows a link's From exactly when the picker offers it (all %d), each one app.js "
                  "follows too (CUR_BY_ISO) %s" % (len(flights.ORIGIN_HUBS), js["unfollowed"])))

# --- renderGuideVisa waiting for the matrix -------------------------------------------------
W = js["wait"]
results.append(ok(W["TH:DE"]["appended"] == ["TH:DE"] and W["TH:GB"]["appended"] == ["TH:GB"]
                  and W["MA:CA"]["appended"] == [] and W["DE:DE"]["appended"] == [] and W["GG:AU"]["appended"] == []
                  and all(v["empty"] and v["shown"] for v in W.values()),
                  "waiting for the matrix, the block holds this guide's stand-in for the reader's passport "
                  "(Thailand's for a German or a Briton), none for another guide's template, and is emptied "
                  "unhidden as before %s" % W))

# --- the link's list still loading ------------------------------------------------------------
K = js["link"]
results.append(ok(K["de"]["first"] == {"minH": "78px", "link": False, "asked": True}
                  and K["de"]["after"] == {"minH": "", "link": True}
                  and K["ca"]["first"]["minH"] == "78px" and K["ca"]["after"] == {"minH": "", "link": True}
                  and K["fail"]["first"]["minH"] == "78px" and K["fail"]["after"] == {"minH": "", "link": False}
                  and K["us"]["first"]["minH"] == "" and not K["us"]["first"]["asked"] and K["other"] == "",
                  "a German or Canadian line drawn while its government's list loads keeps the held 78px until the "
                  "redraw with the link, and lets go if the list fails; a US line holds nothing, nor another "
                  "guide's held room %s" % K))

# --- the homepage and index.html ----------------------------------------------------------------
idx = open(P("public", "index.html"), encoding="utf-8").read()
srv = open(P("server.py"), encoding="utf-8").read()
results.append(ok('<div id="guideVisa" class="guidevisa">{{GUIDE_VISA}}</div>{{GUIDE_VISA_ALT}}' in idx
                  and re.search(r'"GUIDE_VISA_ALT": "",', srv) is not None,
                  "index.html has the token right after #guideVisa, empty by default (the homepage's bytes "
                  "are unchanged)"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

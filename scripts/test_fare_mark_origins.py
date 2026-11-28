"""The guide's fares-by-month strip held for the reader's own From, not only
the default origin's (server.py _fare_strip_known / _fare_strip_others /
_FM_PICK, public/app.js servedFareMark).

    /usr/bin/python3 scripts/test_fare_mark_origins.py

The page holds the strip's room (data-fm, styles.css) where the server's
cached US fares say it will come. A British reader's strip comes from
Britain's fares, and on about a fifth of the guides they disagree with the
US ones: Croatia's strip came 2.9 s into a slow load and the stays and
things to do under it dropped 186px (CLS 0.20 at 390 for a reader scrolled
down), Sweden's held room was given back (0.16). The server now lists the
origins its caches know differ (data-fmy / data-fmn) and a script sets the
reader's before the first paint. What it holds the code to, on the repo's
recorded US fares (scripts/parity/fixture_*.json) and British fares
(scripts/parity/fixtures/GBP), never a fare host:
  * the default origin's mark is what it was, guide for guide;
  * an origin's answer is the one /api/flight-months gives its reader
    (3 of the next 12 months, as renderGuideFares counts), on every guide,
    and "not known" while its fares or a route's curve aren't cached;
  * the list names exactly the origins whose known answer differs, under
    data-fmy where the mark holds nothing and data-fmn where it holds; an
    origin with no cached fares, or a curve not cached, isn't listed;
  * the page carries the list and the script only where there is one (the
    page is otherwise what it was), the script sits right before the fare
    column, and the page memo re-renders when another origin's fares change;
  * the script (run under jsc) sets the room for the saved From, a shared
    ?vo= / ?fo= over it where the picker offers that From, and leaves the
    mark for an origin not listed, no saved From, or storage blocked;
  * app.js servedFareMark (run under jsc) reads the lists the same way, and
    renderGuide asks it for its own guide only, and not as that guide first
    draws: a From the geo seed brings after the first paint keeps the served
    room until the column settles, as before this branch (changed in that
    frame, it merged with the FX line's change into one bigger move).
"""
import datetime, json, os, re, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["TRAVELPAYOUTS_TOKEN"] = "dummy-never-sent"
for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "RENDER"):
    os.environ.pop(k, None)
import socket  # noqa: E402
# Nothing here may leave this machine: any connection but to 127.0.0.1 is
# refused and noted (the last check says none was tried).
OUTSIDE = []
_connect = socket.socket.connect


def _local_only(self, addr):
    if isinstance(addr, tuple) and addr[0] not in ("127.0.0.1", "localhost", "::1"):
        OUTSIDE.append(addr[0])
        raise OSError("test: no outside connections")
    return _connect(self, addr)


socket.socket.connect = _local_only
from fxtracker import flights, flightvalue, watchouts  # noqa: E402
flights.API = "http://127.0.0.1:9"   # refused at once: no fare host is ever reached
flights._cities = {}
watchouts.API = "http://127.0.0.1:9/cta-cap-{iso}.json"   # nor Canada's notes
import server  # noqa: E402
server._warm_watchouts = lambda iso: None   # the renders below would queue them
server._warm_popularity = lambda: None      # and the homepage's, World Bank arrivals

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
jl = lambda *p: json.load(open(os.path.join(ROOT, *p), encoding="utf-8"))
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
SLUGS = jl("public", "slugs.json")
GUIDES = sorted(set(SLUGS.values()))
SEED = {"US": (jl("scripts", "parity", "fixture_flights.json"), jl("scripts", "parity", "fixture_flight_value.json")),
        "GB": (jl("scripts", "parity", "fixtures", "GBP", "flights.json"),
               jl("scripts", "parity", "fixtures", "GBP", "flight_value.json"))}


def seed(origins=("US", "GB")):
    """The origins' fares payloads and their route curves in the server's
    caches, as a warm server holds them (every city of every row cached,
    empty where the recording has no curve)."""
    now = time.time()
    for o in origins:
        fares, fv = SEED[o]
        hub = flights.ORIGIN_HUBS[o][0]
        per_city = {}
        for c in fv["countries"].values():
            for m, (price, city) in (c.get("curve") or {}).items():
                per_city.setdefault(city, {})[m] = {"price": price, "stops": 0, "departure_at": m + "-28T10:00:00Z"}
        for row in fares["countries"]:
            for city in flights.country_cities(row):
                flights._monthly_cache[(hub, city, "usd")] = (now, now, {
                    "configured": True, "origin": o, "hub": hub, "dest": city, "currency": "usd",
                    "months": dict(per_city.get(city, {}))}, False)
        server._flights_cache[o] = (now, json.loads(json.dumps(fares)))


def old_hint(iso):
    """_fare_strip_hint as it was before other origins (r10/ship 39aca9b)."""
    try:
        if not flights.is_configured():
            return False
        hit = server._flights_cache.get(flightvalue.DEFAULT_ORIGIN)
        rows = (hit[1].get("countries") or []) if hit else []
        row = next((r for r in rows if r.get("iso") == iso), None)
        if not row:
            return False
        m = flights.get_country_monthly(flightvalue.DEFAULT_ORIGIN, row, lookup=flights.monthly_cached)
        win = set(flightvalue.window_months())
        return bool(m) and sum(1 for k in (m.get("months") or {}) if k in win) >= 3
    except Exception:
        return False


def reader_sees(o, iso):
    """Whether renderGuideFares draws the strip for a reader from o: what
    /api/flight-months?origin=o&iso= answers (the handler's own path: the
    cached fares' row, the country's curve), counted as the browser counts
    it — the 12 months from this one, at least 3 with a fare."""
    payload = server._fares(o)
    row = next((r for r in payload.get("countries", []) if r.get("iso") == iso), None)
    data = flights.get_country_monthly(o, row) if row else flights.get_monthly(o, "")
    months = data.get("months") or {}
    t = datetime.date.today()
    keys = ["%04d-%02d" % (t.year + (t.month - 1 + i) // 12, (t.month - 1 + i) % 12 + 1) for i in range(12)]
    return sum(1 for k in keys if k in months) >= 3


# --- nothing cached: no mark, no list ---------------------------------------------------------
server._flights_cache.clear()
flights._monthly_cache.clear()
results.append(ok(all(server._fare_strip_known(o, "TH") is None for o in ("US", "GB"))
                  and server._fare_strip_others("TH", False) == "" and not server._fare_strip_hint("TH"),
                  "with no fares cached, no origin is known: no mark, no list"))

# --- the default origin's mark, and each origin's answer ------------------------------------
seed()
same = [g for g in GUIDES if server._fare_strip_hint(g) == old_hint(g)]
results.append(ok(len(same) == len(GUIDES) and sum(old_hint(g) for g in GUIDES) > 40,
                  "the default origin's mark (data-fm) is what it was on all %d guides (%d hold the strip)"
                  % (len(GUIDES), sum(old_hint(g) for g in GUIDES))))
known = {(o, g): server._fare_strip_known(o, g) for o in ("US", "GB") for g in GUIDES}
seen = {(o, g): reader_sees(o, g) for o in ("US", "GB") for g in GUIDES}
bad = [k for k in known if known[k] != seen[k]]
results.append(ok(not bad and None not in known.values(),
                  "each origin's known answer is the strip its reader gets from /api/flight-months, on every guide "
                  "for the US and Britain %s" % bad[:6]))
mark = {g: server._fare_strip_hint(g) for g in GUIDES}
dy = [g for g in GUIDES if not mark[g] and known[("GB", g)]]
dn = [g for g in GUIDES if mark[g] and not known[("GB", g)]]
results.append(ok(len(dy) >= 10 and len(dn) >= 10 and "HR" in dy and "SE" in dn and "GB" in dn,
                  "the recorded British fares disagree with the US mark on %d guides (%d draw it where the mark "
                  "holds nothing, Croatia among them; %d don't where it holds: Sweden, the UK)" % (len(dy) + len(dn), len(dy), len(dn))))

# --- the list -----------------------------------------------------------------------------
attrs = {g: server._fare_strip_others(g, mark[g]) for g in GUIDES}
want = {g: (' data-fmy=",GB,"' if g in dy else ' data-fmn=",GB,"' if g in dn else "") for g in GUIDES}
results.append(ok(attrs == want,
                  "the list names Britain exactly where its answer differs from the mark, under data-fmy or data-fmn "
                  "%s" % [(g, attrs[g], want[g]) for g in GUIDES if attrs[g] != want[g]][:4]))
# An origin cached with no row for the country (its fares have none): no strip, listed where the mark holds.
server._flights_cache["DE"] = (time.time(), {"configured": True, "origin": "DE", "currency": "usd", "countries": [], "by_country": {}})
de = {g: server._fare_strip_others(g, mark[g]) for g in GUIDES}
results.append(ok(all(de[g] == (' data-fmn=",DE,GB,"' if g in dn else ' data-fmn=",DE,"' if mark[g] else want[g]) for g in GUIDES),
                  "an origin whose cached fares have no row for the country is no strip: listed (in order) wherever "
                  "the mark holds %s" % [(g, de[g]) for g in GUIDES if mark[g]][:3]))
del server._flights_cache["DE"]
# A route curve not cached yet: not known, so not listed (the reader keeps the mark).
row = next(r for r in server._flights_cache["GB"][1]["countries"] if r["iso"] == "HR")
gone = {}
for city in flights.country_cities(row):
    k = (flights.ORIGIN_HUBS["GB"][0], city, "usd")
    gone[k] = flights._monthly_cache.pop(k)
results.append(ok(server._fare_strip_known("GB", "HR") is None and server._fare_strip_others("HR", mark["HR"]) == "",
                  "a route curve not cached yet: Britain's answer for Croatia isn't known, and it isn't listed"))
flights._monthly_cache.update(gone)
# Britain's fares not cached (nobody from there lately): not listed anywhere.
gb = server._flights_cache.pop("GB")
results.append(ok(all(server._fare_strip_others(g, mark[g]) == "" for g in GUIDES),
                  "an origin whose fares aren't cached is listed nowhere: its reader keeps the mark"))

# --- the page -----------------------------------------------------------------------------
plain = {g: server._render_index(g).decode("utf-8") for g in ("HR", "SE", "JP")}
server._flights_cache["GB"] = gb
page = {g: server._render_index(g).decode("utf-8") for g in ("HR", "SE", "JP")}
tag = lambda h: re.search(r'<section class="tab" id="tab-guide"[^>]*>', h).group(0)
script = server._fm_pick()
results.append(ok(all("data-fmy" not in h and "data-fmn" not in h and "{{FM_PICK}}" not in h
                      and "data-fmy\")" not in h for h in plain.values()),
                  "with no other origin known the guide carries no list and no script (the page is what it was)"))
results.append(ok('data-fmy=",GB,"' in tag(page["HR"]) and 'data-fm="1"' not in tag(page["HR"])
                  and 'data-fm="1" data-fmn=",GB,"' in tag(page["SE"]) and "data-fmn" not in tag(page["JP"])
                  and "data-fmy" not in tag(page["JP"]),
                  "Croatia's page lists Britain as drawing it, Sweden's as not, Japan's lists nobody: %s / %s / %s"
                  % (tag(page["HR"])[30:], tag(page["SE"])[30:], tag(page["JP"])[30:])))
results.append(ok(page["HR"].count(script) == 1 and (script + '<div class="farecol loading">') in page["HR"]
                  and page["SE"].count(script) == 1 and script not in page["JP"]
                  and page["JP"] == plain["JP"],
                  "the script comes once, right before the fare column, only on a page with a list; Japan's page "
                  "is byte for byte the page with no other origin cached"))
results.append(ok("{{FM_PICK}}<div class=\"farecol loading\">" in HTML and server._HTML_DEFAULTS.get("FM_PICK") == ""
                  and "{{FM_PICK}}" not in server._render_index(None).decode("utf-8"),
                  "index.html has the token right before the fare column; the homepage leaves it empty"))
o1, _v1 = server._page_inputs("HR")
server._flights_cache["GB"] = (gb[0], json.loads(json.dumps(gb[1])))
o2, _v2 = server._page_inputs("HR")
results.append(ok(len(o1) == len(o2) and sum(a is not b for a, b in zip(o1, o2)) == 1,
                  "the page memo re-renders a guide when another origin's fares are replaced (one input changed)"))

# --- the script before the first paint (jsc) ------------------------------------------------
PICK = re.search(r"<script>\(function\(\)\{(.*)\}\)\(\);</script>$", script, re.S).group(1)
PICKER = r"""
var CASES = JSON.parse(read(CASES_PATH)), res = {};
CASES.forEach(function (c) {
  var at = { "data-fmy": c.y, "data-fmn": c.n }; if (c.fm) at["data-fm"] = "1";
  var g = { getAttribute: function (k) { return k in at && at[k] != null ? at[k] : null; },
            setAttribute: function (k, v) { at[k] = String(v); }, removeAttribute: function (k) { delete at[k]; } };
  var document = { getElementById: function (id) { return id === "tab-guide" ? g : null; } };
  var location = { search: c.q };
  var localStorage = { getItem: function (k) { if (c.boom) throw new Error("blocked"); return k === "fx_origin" ? c.o : null; } };
  var URLSearchParams = function (s) { var o = {}; s.replace(/^\?/, "").split("&").forEach(function (kv) {
    var i = kv.indexOf("="); if (i > 0) o[kv.slice(0, i)] = kv.slice(i + 1); }); this.get = function (k) { return k in o ? o[k] : null; }; };
  (function () { BODY })();
  res[c.name] = "data-fm" in at;
});
print(JSON.stringify(res));
"""
CASES = [  # y: data-fmy (the mark holds nothing), n: data-fmn (it holds), fm: the served mark
    {"name": "y-saved", "y": ",GB,IE,", "o": "GB", "q": ""},
    {"name": "y-other", "y": ",GB,IE,", "o": "DE", "q": ""},
    {"name": "y-none", "y": ",GB,", "o": None, "q": ""},
    {"name": "y-us", "y": ",GB,", "o": "US", "q": ""},
    {"name": "n-saved", "n": ",DE,GB,", "fm": 1, "o": "GB", "q": ""},
    {"name": "n-other", "n": ",DE,GB,", "fm": 1, "o": "AU", "q": ""},
    {"name": "n-vo", "n": ",GB,", "fm": 1, "o": "AU", "q": "?vo=GB"},
    {"name": "n-fo", "n": ",GB,", "fm": 1, "o": None, "q": "?tab=guide&fo=GB"},
    {"name": "n-vo-over", "n": ",GB,", "fm": 1, "o": "GB", "q": "?vo=AU"},
    {"name": "n-vozz", "n": ",GB,", "fm": 1, "o": "GB", "q": "?vo=ZZ"},
    {"name": "n-vobad", "n": ",GB,", "fm": 1, "o": "GB", "q": "?vo=GB,DE"},
    {"name": "y-vo", "y": ",GB,", "o": "DE", "q": "?vo=GB"},
    {"name": "n-boom", "n": ",GB,", "fm": 1, "o": "GB", "q": "", "boom": 1},
    {"name": "y-boom", "y": ",GB,", "o": "GB", "q": "", "boom": 1},
    {"name": "y-partial", "y": ",GBX,", "o": "GB", "q": ""},
]
WANT = {"y-saved": True, "y-other": False, "y-none": False, "y-us": False, "n-saved": False, "n-other": True,
        "n-vo": False, "n-fo": False, "n-vo-over": True, "n-vozz": False, "n-vobad": False, "y-vo": True,
        "n-boom": True, "y-boom": False, "y-partial": False}
with tempfile.TemporaryDirectory() as d:
    cp, sp = os.path.join(d, "cases.json"), os.path.join(d, "pick.js")
    json.dump(CASES, open(cp, "w"))
    open(sp, "w", encoding="utf-8").write(PICKER.replace("CASES_PATH", json.dumps(cp)).replace("BODY", PICK))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=30)
try:
    got = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    got = {"error": (r.stderr or r.stdout)[-400:]}
results.append(ok(got == WANT,
                  "before the first paint the room follows the saved From where the page lists it (held for a "
                  "British reader on Croatia, let go on Sweden), a shared ?vo= / ?fo= over it where the picker "
                  "offers it (?vo=ZZ and a malformed one fall back to the saved From), and the mark stays for an "
                  "origin not listed, no saved From, or storage blocked %s"
                  % ("" if got == WANT else {k: v for k, v in got.items() if WANT.get(k) != v} if "error" not in got else got)))
FROMS = re.search(r'"(,[A-Z,]+,)"\.indexOf', PICK)
results.append(ok(FROMS is not None and FROMS.group(1) == "," + ",".join(sorted(flights.ORIGIN_HUBS)) + ",",
                  "the script follows a link's From exactly when the picker offers it (all %d ORIGIN_HUBS), as the "
                  "visa line's does" % len(flights.ORIGIN_HUBS)))

# --- app.js servedFareMark (jsc) and where renderGuide asks it --------------------------------
fn = re.search(r"\nfunction servedFareMark\(gtab, o\) \{.*?\n\}\n", APP, re.S)
JS = (fn.group(0) if fn else "") + r"""
var g = function (a) { return { getAttribute: function (k) { return k in a ? a[k] : null; } }; };
print(JSON.stringify([
  servedFareMark(g({ "data-fmy": ",GB,IE," }), "GB"), servedFareMark(g({ "data-fmy": ",GB,IE," }), "DE"),
  servedFareMark(g({ "data-fmn": ",GB," }), "GB"), servedFareMark(g({ "data-fmn": ",GB," }), "US"),
  servedFareMark(g({ "data-fmn": ",GB," }), "G"), servedFareMark(g({ "data-fm": "1" }), "GB"), servedFareMark(g({}), "GB")]));
"""
with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "m.js")
    open(sp, "w", encoding="utf-8").write(JS)
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=30)
try:
    m = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    m = {"error": (r.stderr or r.stdout)[-300:]}
results.append(ok(m == [True, False, False, True, True, None, None],
                  "servedFareMark: a listed origin draws it under data-fmy and doesn't under data-fmn, any other "
                  "reads the mark's way, and with no list it answers null (the mark stands) %s" % m))
results.append(ok(re.search(r"iso === window\.__WGGC__ \? \(ssr \? null : servedFareMark\(gtab, originIso\(\)\)\) : false;", APP) is not None
                  and APP.count("servedFareMark(") == 2,
                  "renderGuide asks servedFareMark for its own guide only (another guide holds nothing until its "
                  "fares are in), and nowhere else"))

# --- renderGuide's mark, run under jsc: not as the page's guide first draws ---------------------
blk = re.search(r"\n(    const fvC = flightValue .*?\n)(?=    // The FX line likewise)", APP, re.S)
JS2 = (fn.group(0) if fn else "") + r"""
var window = { __WGGC__: "GB" }, flightValue = null, origin = "GB";
var originIso = function () { return origin; };
var mk = function (a) { return { getAttribute: function (k) { return k in a ? a[k] : null; },
  hasAttribute: function (k) { return k in a; }, setAttribute: function (k, v) { a[k] = String(v); },
  removeAttribute: function (k) { delete a[k]; } }; };
var run = function (iso, attrs, opt) {
  opt = opt || {}; var gtab = mk(attrs), ssr = opt.later ? null : {};
  flightValue = opt.fv || null; origin = opt.o || "GB";
  (function () { BLOCK })();
  return gtab.hasAttribute("data-fm");
};
print(JSON.stringify({
  firstLate: run("GB", { "data-fm": "1", "data-fmn": ",GB," }),
  firstSaved: run("GB", { "data-fmn": ",GB," }),
  laterGone: run("GB", { "data-fm": "1", "data-fmn": ",GB," }, { later: 1 }),
  laterCome: run("GB", { "data-fmy": ",GB," }, { later: 1 }),
  laterUS: run("GB", { "data-fm": "1", "data-fmn": ",GB," }, { later: 1, o: "US" }),
  laterNoList: run("GB", { "data-fm": "1" }, { later: 1 }),
  other: run("SE", { "data-fm": "1", "data-fmn": ",GB," }),
  fvIn: run("GB", { "data-fmn": ",GB," }, { fv: { origin: "GB", countries: { GB: { n_curve: 5 } } } })
}));
"""
with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "r.js")
    open(sp, "w", encoding="utf-8").write(JS2.replace("BLOCK", blk.group(1) if blk else "throw new Error('no block')"))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=30)
try:
    rg = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    rg = {"error": (r.stderr or r.stdout)[-300:]}
RG = {"firstLate": True, "firstSaved": False, "laterGone": False, "laterCome": True, "laterUS": True,
      "laterNoList": True, "other": False, "fvIn": True}
results.append(ok(rg == RG,
                  "renderGuide: as the page's guide first draws, a From the geo seed brought after the first paint "
                  "keeps the served room (the column settles it, as before), and a saved From keeps what the "
                  "first-paint script set; drawn again later, the listed origins get theirs (gone for a Briton "
                  "under data-fmn, there under data-fmy), a US reader and a guide with no list keep the mark; "
                  "another guide holds nothing; the Flights data, once in, decides %s" % ("" if rg == RG else rg)))

results.append(ok(not OUTSIDE, "nothing tried to reach another host %s" % sorted(set(OUTSIDE))))

print("%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

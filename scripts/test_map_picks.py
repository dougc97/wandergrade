"""The homepage's served pick lists under the Safety and Flights maps
(fxtracker/map_picks.py) say what public/app.js will write: the list
builders on both sides run on one fixture — app.js's under jsc, its own
functions cut out of the file — and the served rows are compared to the
spans renderDimPicks makes of the client's list. Also: a guide page keeps
index.html's own rows (its HTML is fixed), the homepage serves the fixture's.

    /usr/bin/python3 scripts/test_map_picks.py
"""
import datetime, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import map_picks   # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):   # `const name = …;` up to the statement's line-ending ";"
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def jsc(prog):
    try:
        return json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
    except Exception:
        return None


esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
spans = lambda items: "".join("<span>%d. %s</span>" % (i + 1, t) for i, t in enumerate(items))
TODAY = datetime.date.today()

# --- Flights: "Below typical for <month>" ------------------------------------------
# Eight-plus Low routes with ties, a High, a Typical, a pending country, one
# too few months for a range, one with no fare for the month, an L3 and an L4
# (filtered), a name only Intl.DisplayNames knows (MV), and a nameless ISO.
KEY = map_picks.month_key({"months": []}, TODAY)
NAMES = {"CA": "Canada", "VN": "Vietnam", "EG": "Egypt", "TH": "Thailand", "TR": "Turkey", "MX": "Mexico",
         "KZ": "Kazakhstan", "SA": "Saudi Arabia", "RU": "Russia", "JP": "Japan", "GR": "Greece",
         "PT": "Portugal", "IS": "Iceland", "MA": "Morocco", "UZ": "Uzbekistan", "DO": "Dominican Republic"}
C = lambda price, med, lo, hi: {"curve": {KEY: [price, "XXX"]}, "median": med, "lo": lo, "hi": hi, "n_months": 8}
FV = {"configured": True, "origin": "US", "months": [KEY], "countries": {
    "CA": C(210, 360, 300, 420), "VN": C(620, 1000, 900, 1100), "EG": C(700, 1000, 900, 1100),
    "TH": C(810, 1000, 900, 1100), "SA": C(830, 1000, 900, 1100), "RU": C(880, 1000, 900, 1100),
    "TR": C(895, 1000, 950, 1050), "MV": C(895, 1000, 950, 1050), "MX": C(896, 1000, 950, 1050),
    "KZ": C(896, 1000, 950, 1050), "UZ": C(940, 1000, 950, 1050), "DO": C(945, 1000, 950, 1050),
    "JP": C(1200, 1000, 900, 1100), "GR": C(1000, 1000, 900, 1100), "PT": {"pending": True},
    "IS": {"curve": {KEY: [400, "KEF"]}, "n_months": 3}, "MA": {"curve": {}, "median": 600, "lo": 550, "hi": 650},
    "ZZ": C(100, 1000, 900, 1100)}}
ROWS = [{"iso": i} for i in FV["countries"]]
LEVELS = {"SA": 3, "RU": 4, "CA": 1, "MX": 2, "EG": 2}
prog = ("const NAMES = %s; function countryName(i) { return NAMES[i] || i; }\n"
        "let flightValue = %s; let _fvFailed = false; let showRisky = false; const inRegion = () => true;\n"
        "%s\n%s\n%s\n"
        "print(JSON.stringify(flightLows(%s, %s, %s).slice(0, 8).map((d) => countryName(d.iso) + ' ' + fmtDevPct(d.v.dev))));"
        % (json.dumps(dict(NAMES, MV="Maldives", ZZ="ZZ")), json.dumps(FV), js_fn("fareValue"), js_fn("fmtDevPct"),
           js_fn("flightLows"), json.dumps(ROWS), json.dumps(KEY), json.dumps(LEVELS)))
client = jsc(prog)
server = map_picks.flight_items(FV, LEVELS, NAMES.get, TODAY)
results.append(ok(client and len(client) == 8 and client[0] == "Canada −42%" and "Saudi Arabia −17%" not in client
                  and "Russia −12%" not in client and "Maldives −10%" in client and "ZZ −90%" not in client,
                  "app.js flightLows under jsc: 8 Lows, L3-4 and nameless out, Maldives by its Intl name (%s)" % client))
results.append(ok(client == server, "map_picks.flight_items == app.js flightLows + fmtDevPct, ties in input order\n"
                  "          server %s" % server))
row = map_picks.flights_row(FV, LEVELS, NAMES.get, TODAY)
results.append(ok(row == '<div class="mappicksrow skel" data-for="flightMap" aria-hidden="true"><strong>Below typical for %s</strong>%s</div>'
                  % (map_picks.MON_FULL[int(KEY[5:7]) - 1], spans(client or [])),
                  "the served Flights row is index.html's with renderDimPicks' spans of that list"))
EDGES = [-0.245, 0.245, 0.004, -0.004, -0.005, 0.005, -0.015, 0.015, -0.105, 0, -0.42, 1.5]
js_pct = jsc("%s\nprint(JSON.stringify(%s.map(fmtDevPct)));" % (js_fn("fmtDevPct"), json.dumps(EDGES)))
results.append(ok(js_pct and js_pct == [map_picks.dev_pct(d) for d in EDGES] and "−1%" in js_pct and "0%" in js_pct,
                  "dev_pct == app.js fmtDevPct on the halves (Math.round sends them up), real minus sign (%s)" % js_pct))
d16 = datetime.date(2026, 10, 16)
results.append(ok(map_picks.month_key({"months": ["2026-10", "2026-11"]}, datetime.date(2026, 10, 15)) == "2026-10"
                  and map_picks.month_key({"months": ["2026-10", "2026-11"]}, d16) == "2026-11"
                  and map_picks.month_key({"months": []}, datetime.date(2026, 12, 20)) == "2027-01",
                  "the default departure month: this month to the 15th, then next month (January wraps the year)"))

# --- Safety: "Recently changed" ------------------------------------------------------
D = lambda days: (TODAY - datetime.timedelta(days=days)).isoformat()
ADV = {"source": "us", "items": [
    {"iso": "NC", "country": "New Caledonia", "level": 2, "change": "down", "updated": D(142)},
    {"iso": "MX", "country": "Mexico", "level": 3, "change": "up", "changed": D(3), "updated": D(3)},
    {"iso": "EG", "country": "Egypt", "level": 2, "change": "down", "updated": D(200)},        # outside the window
    {"iso": "DE", "country": "Germany", "level": 2, "change": "up", "changed": D(40), "via": "de"},  # a German gap-fill, its words
    {"iso": "TR", "country": "Turkey", "level": 2, "updated": D(1)},                              # no change
    {"iso": "QQ", "country": "Nowhere", "level": 1, "change": "up", "updated": D(10)},            # the feed's own name
    {"iso": "JP", "country": "Japan", "level": 1, "change": "down", "changed": D(400)},          # too old
]}
ANAMES = {"NC": "New Caledonia", "MX": "Mexico", "EG": "Egypt", "DE": "Germany", "TR": "Turkey", "JP": "Japan"}
m = re.search(r"^  const cutoff = advMoveCutoff\(\);\n.*?^  renderDimPicks\(\"advMap\", \"Recently changed\", changed\.map\(chLine\), changed\.map\(\(it\) => it\.iso\)\);$",
              APP, re.M | re.S)
block = m.group(0) if m else ""
prog = ("const NAMES = %s; function countryName(i) { return NAMES[i] || i; }\n"
        "const advisories = %s; const regionSel = 'all'; const inRegion = () => true;\n"
        "%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n"
        "function renderDimPicks(host, title, items) { print(JSON.stringify(items.map((t) => t.html))); }\n"
        "(function () {\n%s\n})();"
        % (json.dumps(dict(ANAMES, QQ="Nowhere")), json.dumps(ADV), js_const("esc"), js_const("MON_ABBR"),
           js_const("ADV_MOVE_DAYS"), js_const("advMoveCutoff"), js_const("advChangedOn"), js_const("advLvl"),
           js_const("advSrcOf"), js_const("ADV_LVL_WORDS"), js_const("DE_LVL_LABEL"), js_fn("advName"),
           js_fn("advLvlWords") + "\n" + js_fn("fmtDayShort"), block))
client = jsc(prog)
server = map_picks.adv_items(ADV, ANAMES.get, TODAY)
results.append(ok(block and client and len(client) == 4 and client[0].startswith("Mexico <b class=\"chup\"")
                  and "Some regions" in client[2] and client[3].startswith("New Caledonia"),
                  "app.js renderAdvisories' changed list under jsc: 4 moves in 180 days, newest first, Germany's own words (%s)"
                  % [re.sub(r"<[^>]+>", "", c) for c in (client or [])]))
results.append(ok(client == server, "map_picks.adv_items == app.js chLine, markup and all\n          server %s" % server))
results.append(ok(map_picks.advisory_row(ADV, ANAMES.get, TODAY)
                  == '<div class="mappicksrow skel" data-for="advMap" aria-hidden="true"><strong>Recently changed</strong>%s</div>' % spans(client or [])
                  and map_picks.advisory_row({"source": "us", "items": ADV["items"][2:3]}, ANAMES.get, TODAY) == "",
                  "the served Safety row carries those spans; none at all with nothing in the window (the client removes the row)"))

# --- served pages ----------------------------------------------------------------------
import server as srv   # noqa: E402

D = srv._HTML_DEFAULTS
tpl = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
results.append(ok("{{ADV_PICKS}}" in tpl and "{{FLIGHT_PICKS}}" in tpl and 'hidden{{FLIGHTS_OFF}}>' in tpl
                  and D["ADV_PICKS"].startswith('<div class="mappicksrow skel" data-for="advMap"')
                  and D["FLIGHT_PICKS"].count("<span") == 8 and D["FLIGHTS_OFF"] == "",
                  "index.html tokens and their defaults: the rows as blank spans, no data-nofares"))
srv._adv_cache["us"] = (0, ADV)
home = srv._render_index(None).decode("utf-8")
guide = srv._render_index("TH").decode("utf-8")
results.append(ok(map_picks.advisory_row(ADV, srv.render_guide.name_for_iso, TODAY) in home and D["ADV_PICKS"] not in home
                  and D["ADV_PICKS"] in guide and "{{" not in home and "{{" not in guide,
                  "the homepage serves the cached list's row, a guide index.html's own"))
results.append(ok((' data-nofares' in home) == (not srv.flights.is_configured()) and "data-nofares" not in guide,
                  "data-nofares on the homepage exactly when there is no fare token, never on a guide"))
srv._adv_cache.pop("us", None)

n = sum(1 for r in results if r)
# The served words must be the browser's: for every ISO climate.json or ppp.json
# names, map_picks' name is that name (app.js countryName reads them first).
_dn = {}
for _f in ("ppp.json", "climate.json"):
    with open(os.path.join(ROOT, "public", _f), encoding="utf-8") as f:
        for _k, _v in json.load(f).items():
            if isinstance(_v, dict) and _v.get("name"):
                _dn[_k] = _v["name"]
_bad = [i for i in sorted(_dn) if map_picks._name(lambda x: None, i) != _dn[i]]
results.append(ok(not _bad, "served names match climate/ppp names for all %d ISOs (%s)" % (len(_dn), ", ".join(_bad[:5]) or "none differ")))
for _iso, _want in (("AG", "Antigua and Barbuda"), ("KN", "St. Kitts and Nevis"), ("VC", "St. Vincent and the Grenadines")):
    results.append(ok(map_picks._name(lambda x: None, _iso) == _want, "%s is served as %r" % (_iso, _want)))
n = sum(1 for r in results if r)
print("\n%d/%d passed" % (n, len(results)))
sys.exit(0 if n == len(results) else 1)

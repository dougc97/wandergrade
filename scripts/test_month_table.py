"""The guide's month-by-month table (fxtracker/render_guide.month_table,
/guide/<slug>#when-to-go), in-process: no network, no fare token. Fares come
from scripts/parity/fixture_flight_value.json (US origin, months 2026-09 to
2027-08).

    /usr/bin/python3 scripts/test_month_table.py

What it holds the code to:
  * rows: a header and twelve <tr id="january">…<tr id="december">, January
    first; each month's °C/°F, rain (mm and days over 1 mm), weather score
    with ★ on the best months, a ⚠️ cell where a hazard falls (a column only
    where the country has hazards), from climate.json and activities.json;
  * below it: one line per hazard in the chart's words ("⚠️ <b>Nov–Apr:</b>
    …", guide_sizers.chart) and the one "How we grade" line;
  * the caption: "Measured at {at}, Open-Meteo {window}; fares as of {date}",
    and "one representative point in the country" where climate.json names
    no place, never a guessed city;
  * the fare column ("Fare from the US", price and Low/Typical/High): only
    with the country's typical range (median, i.e. MIN_MONTHS months),
    never on the UK-market guides (CV IM GG LT) or where no bookings are
    offered (Level 4), "—" for a month with no cached fare, the January row
    on the next January's fare, each band flightvalue.band's;
  * no table where scores are flat (Antarctica) or a month's temperature or
    rain is missing; only the allowlisted guides (MONTH_TABLE), every
    eligible one with MONTH_TABLE_ALL;
  * the page: the block right after #bestDetail on an allowlisted guide, once,
    with the committed climate.json for all 23; the homepage and every other
    guide without it; app.js hides it when another country is opened in-app;
    /guide/<slug>/<anything> is still a 404, the guide itself a 200.
"""
import copy, datetime, json, os, re, sys, threading, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import flightvalue, guide_sizers, render_guide as rg   # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
FV = json.load(open(os.path.join(ROOT, "scripts", "parity", "fixture_flight_value.json"), encoding="utf-8"))
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
DAY = datetime.date(2026, 10, 28)
D = rg._load()
CLIM, ACTS = D["clim"], D["acts"]
REAL_CLIM = copy.deepcopy(CLIM)

# A fixture country on Australia's code (allowlisted, hazards, a typical range in
# the fixture): fixed numbers, so the test doesn't move with a climate rebuild.
FIX = {"name": "Australia", "at": "Sydney", "curated": True, "best": [3, 4, 9, 10, 11], "window": "2021–2025",
       "scores": [76, 81, 67, 80, 66, 66, 59, 65, 81, 86, 83, 87],
       "temps": [22, 22, 21, 18, 15, 12, 12, 13, 16, 18, 19, 21],
       "rain_mm": [133, 107, 182, 106, 119, 53, 97, 91, 57, 74, 95, 72],
       "rain_days": [15, 15, 16, 12, 12, 7, 9, 9, 7, 12, 13, 1]}
CLIM["AU"] = FIX


def rows_of(t):
    return re.findall(r"<tr(?: id=\"([a-z]+)\")?(?: class=\"best\")?>(.*?)</tr>", t)


def cells(row):
    return [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row)]


t = rg.month_table("AU", FV, DAY)
rs = rows_of(t)
results.append(ok(len(rs) == 13 and rs[0][0] == "" and [r[0] for r in rs[1:]] == rg.MONTH_IDS
                  and t.count('id="when-to-go"') == 1 and t.startswith('<div id="when-to-go"'),
                  "13 rows: a header, then <tr id=\"january\"> … <tr id=\"december\"> in calendar order"))
head = cells(rs[0][1])
results.append(ok(head == ["Month", "Avg temp", "Rain", "Weather score", "⚠️", "Fare from the US"],
                  "columns: Month, Avg temp, Rain, Weather score, ⚠️, Fare from the US (%s)" % head))
jan, apr, jul, dec = (cells(rs[m][1]) for m in (1, 4, 7, 12))
results.append(ok(jan[:4] == ["January", "22°C / 72°F", "133 mm · 15 days", "76"]
                  and jul[:4] == ["July", "12°C / 54°F", "97 mm · 9 days", "59"]
                  and dec[2] == "72 mm · 1 day" and apr[3] == "80 ★",
                  "temperature °C/°F, rain mm · days (1 day), score, ★ on a best month: %s / %s" % (jan[:4], apr[:4])))
best = [rs[m][0] for m in range(1, 13) if 'class="best"' in t.split('<tr id="%s"' % rs[m][0])[1][:20]]
results.append(ok(best == ["march", "april", "september", "october", "november"]
                  and all(cells(rs[m][1])[3].endswith("★") == (m in FIX["best"]) for m in range(1, 13)),
                  "the best months (climate.json best) are starred and marked, the rest not: %s" % best))
hz_months = set(ACTS["AU"]["hazards"][0]["months"])
results.append(ok(all((cells(rs[m][1])[4] == "⚠️") == (m in hz_months) for m in range(1, 13))
                  and 'title="%s"' % ACTS["AU"]["hazards"][0]["note"].replace("(", "(") in t,
                  "a ⚠️ cell in each hazard month (Nov–Apr), the note as its title, empty elsewhere"))
# Below the table: the chart's hazard lines (the stand-in guide_sizers.chart serves).
chart = guide_sizers.chart("AU", "Australia", ACTS["AU"]["hazards"])
lines = re.findall(r'<div class="hazardline">.*?</div>', t)
results.append(ok(lines and all(l in chart for l in lines) and "⚠️ <b>Nov–Apr:</b> Cyclone" in lines[0]
                  and "avoid" not in t.lower(),
                  "one line per hazard below it, worded as the weather chart words it: %s" % lines))
results.append(ok('<p class="wtgnote">How we grade: comfort peaks at 18–26°C, hot months lose points faster than '
                  "cold ones, and rain lowers the score.</p>" in t, "one \"How we grade\" line"))
cap = re.search(r"<caption>(.*?)</caption>", t).group(1)
results.append(ok(cap == "Measured at Sydney, Open-Meteo 2021–2025; fares as of 28 Oct 2026",
                  "caption: %s" % cap))
CLIM["AU"] = dict(FIX); CLIM["AU"].pop("at")
cap2 = re.search(r"<caption>(.*?)</caption>", rg.month_table("AU", None, None)).group(1)
results.append(ok(cap2 == "Measured at one representative point in the country, Open-Meteo 2021–2025",
                  "no place in climate.json: \"one representative point in the country\", no fare date: %s" % cap2))
CLIM["AU"] = FIX

# --- the fare column ------------------------------------------------------------------
fc = FV["countries"]["AU"]
key = {int(k[5:7]): k for k in FV["months"]}
bad = []
for m in range(1, 13):
    c = cells(rs[m][1])[5]
    p = (fc["curve"].get(key[m]) or [None])[0]
    want = "—" if p is None else "$%s %s" % (format(p, ","), flightvalue.band(p, fc).capitalize())
    if c != want:
        bad.append((m, c, want))
results.append(ok(not bad and key[1] == "2027-01" and cells(rs[1][1])[5].startswith("$1,269"),
                  "each month's fare and band from the curve (January = 2027-01, the next January), "
                  "\"—\" with none cached %s" % (bad or "")))
results.append(ok(sum(cells(rs[m][1])[5] == "—" for m in range(1, 13)) == 12 - fc["n_curve"]
                  and {flightvalue.band(p, fc) for p, _c in fc["curve"].values()} >= {"low", "typical", "high"},
                  "a dash for each of the %d uncached months; Low, Typical and High all shown" % (12 - fc["n_curve"])))
no_fare = lambda tt: "Fare from the US" not in tt and "fvband" not in tt and "fares as of" not in tt
results.append(ok(no_fare(rg.month_table("AU", None, DAY)), "no flight-value data: no fare column"))
thin = copy.deepcopy(FV)
thin["countries"]["AU"] = {k: v for k, v in fc.items() if k in ("curve", "n_curve", "n_months")}
thin["countries"]["AU"]["n_months"] = 5
results.append(ok(no_fare(rg.month_table("AU", thin, DAY)),
                  "no typical range (n_months < MIN_MONTHS, no median): no fare column, like the Flights tab"))
results.append(ok(no_fare(rg.month_table("AU", FV, DAY, no_bookings=True)),
                  "a guide with no bookings (a government's Level 4): no fare column"))
uk = copy.deepcopy(FV)
for iso in ("CV", "IM", "GG"):
    uk["countries"][iso] = fc
    CLIM[iso] = dict(FIX, name=iso)
results.append(ok(rg.UK_MARKET == {"CV", "IM", "GG", "LT"}
                  and all(rg.month_table(i, uk, DAY) and no_fare(rg.month_table(i, uk, DAY)) for i in ("CV", "IM", "GG")),
                  "the UK-market guides (CV IM GG; LT not rolled out) never carry it, even with a range"))
for iso in ("CV", "IM", "GG"):
    CLIM[iso] = REAL_CLIM[iso]

# --- when there is no table -------------------------------------------------------------
CLIM["AU"] = dict(FIX, temps=FIX["temps"][:6] + [None] + FIX["temps"][7:])
results.append(ok(rg.month_table("AU", FV, DAY) == "", "a month's temperature missing: no table"))
CLIM["AU"] = dict(FIX, rain_mm=None)
results.append(ok(rg.month_table("AU", FV, DAY) == "", "no rain data: no table"))
CLIM["AU"] = dict(FIX, scores=[0] * 12)
results.append(ok(rg.month_table("AU", FV, DAY) == "", "flat scores (Antarctica's all-zero year): no table"))
CLIM["AU"] = FIX
CLIM["AQ"] = dict(FIX, scores=REAL_CLIM["AQ"]["scores"])
try:
    rg.MONTH_TABLE_ALL = True
    results.append(ok(rg.month_table("AQ", FV, DAY) == "" and "rain_mm" not in CLIM["GB-ENG"]
                      and rg.month_table("GB-ENG", FV, DAY) == "" and rg.month_table_on("JP"),
                      "MONTH_TABLE_ALL: every guide is on; Antarctica (flat) and England (no rain data) still get none"))
    results.append(ok(rg.month_table("JP", FV, DAY).startswith('<div id="when-to-go"'),
                      "MONTH_TABLE_ALL: a guide off the list with the data (Japan) gets it"))
finally:
    rg.MONTH_TABLE_ALL = False
    CLIM["AQ"], CLIM["JP"] = REAL_CLIM["AQ"], REAL_CLIM["JP"]
results.append(ok(rg.month_table("JP", FV, DAY) == "" and not rg.month_table_on("JP")
                  and len(rg.MONTH_TABLE) == 23 and not rg.MONTH_TABLE_ALL,
                  "off by default for a guide off the 23-guide allowlist"))

# --- the real climate.json: all 23 allowlisted guides ---------------------------------
for k in list(CLIM):
    CLIM[k] = REAL_CLIM[k]
miss = [i for i in sorted(rg.MONTH_TABLE) if not rg.month_table(i, FV, DAY)]
results.append(ok(not miss, "every allowlisted guide has its table from the committed climate.json %s" % (miss or "")))
at = {i: re.search(r"<caption>Measured at (.*?), Open-Meteo", rg.month_table(i)).group(1)
      for i in rg.MONTH_TABLE if rg.month_table(i)}
results.append(ok(at.get("AU") == "Sydney" and at.get("CL") == "Santiago" and at.get("GL") == "Nuuk"
                  and all(v == REAL_CLIM[i].get("at", "one representative point in the country") for i, v in at.items()),
                  "each caption names climate.json's place or none: AU %s, CL %s, GL %s, PT %s"
                  % (at.get("AU"), at.get("CL"), at.get("GL"), at.get("PT"))))

# --- the page -----------------------------------------------------------------------------
real_fv = server._guide_fv
server._guide_fv = lambda iso: (FV, DAY) if rg.month_table_on(iso) else (None, None)
try:
    au = server._render_index("AU").decode("utf-8")
    pt = server._render_index("PT").decode("utf-8")
    jp = server._render_index("JP").decode("utf-8")
    home = server._render_index(None).decode("utf-8")
finally:
    server._guide_fv = real_fv
results.append(ok(au.count('id="when-to-go"') == 1
                  and re.search(r'<div id="bestDetail"[^>]*>.*?</div></div></div>\n        <div id="when-to-go"', au, re.S)
                  and au.index('id="when-to-go"') < au.index('class="farecol')
                  and "Fare from the US" in au and "Fare from the US" in pt,
                  "an allowlisted guide: the block once, right after #bestDetail, fares from the default origin"))
results.append(ok("when-to-go" not in jp and "when-to-go" not in home and "{{GUIDE_MONTHS}}" not in jp + home,
                  "the homepage and a guide off the list: no block, no bare token"))
tpl = server._index_template()
results.append(ok(tpl.count("{{GUIDE_MONTHS}}") == 1 and "{{GUIDE_CHART}}</div>{{GUIDE_MONTHS}}\n" in tpl,
                  "index.html's token has no bytes of its own (the other guides stay byte-identical)"))
hide = re.search(r'const wtg = \$\("when-to-go"\);\s*if \(wtg\) wtg\.hidden = iso !== window\.__WGGC__;', APP)
results.append(ok(hide and APP.index(hide.group(0)) > APP.index("function renderGuide(iso)")
                  and APP.index(hide.group(0)) < APP.index("function renderGuideFares("),
                  "app.js renderGuide hides it when the guide on screen isn't the server's own"))

server.Handler.log_message = lambda self, *a: None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def status(path):
    try:
        with urllib.request.build_opener(NoRedirect).open(BASE + path, timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""


codes = {p: status(p) for p in ("/guide/australia", "/guide/australia/when-to-go", "/guide/australia/january",
                                 "/guide/australia/x/y", "/guide/portugal/months")}
httpd.shutdown()
results.append(ok(codes["/guide/australia"][0] == 200 and 'id="when-to-go"' in codes["/guide/australia"][1]
                  and all(v[0] == 404 for p, v in codes.items() if p != "/guide/australia"),
                  "/guide/australia is 200 with the table; every /guide/<slug>/<x> is a 404 (%s)"
                  % {p: v[0] for p, v in codes.items()}))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

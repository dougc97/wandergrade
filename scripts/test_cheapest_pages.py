#!/usr/bin/env python3
"""/cheapest and /cheapest/<month> (fxtracker/render_cheapest.py and the
server's route), from fixtures: no network, no server process beyond a
loopback one for the routes.

    /usr/bin/python3 scripts/test_cheapest_pages.py

What it holds the code to:
  * the year: a month's next occurrence counting the current month, for
    every month seen from every day class in October and in December;
  * the ranking on production data (scripts/fixtures/cheapest_2026-10-23.json,
    GETs of /api/rates, the three /api/advisories, /api/flights?origin=US,
    /api/flight-value?origin=US and /ppp.json): each month's rows are exactly
    picks._score's US-edition output (computed here the way the parity
    harness computes it) filtered by the rule and sorted as build_variant
    sorts, and each row prints that same score's grade, score and price;
  * the rule at its edges with a stand-in scorer: 50% in and 51% out, 70 in
    and 69 out, US Level 2 in and 3 out, a gap-fill never a US rating, any
    government's own Level 4 out (a territory by its parent's), unrated out,
    ties by the unrounded score and then the name;
  * fares: the month's picks.month_fare with its flightvalue.band word, an
    em dash and the one footnote otherwise; dashes and not degraded when no
    fare source is configured;
  * degraded (no-store, said on the page): each advisory list missing, the
    rates or PPP or climate or snapshot missing, fares still loading, a
    failing refresh;
  * titles <= 60 and descriptions <= 157, all 13 unique, no "best time";
    one h1, no ad-blocker class names, real guide links, prev/next/hub and
    /safe-and-cheap links, HTML that parses, no "None";
  * the server: 200 for the 13 paths (cached 5 min, or no-store degraded),
    301 for a trailing slash (query kept), 404 for anything else under
    /cheapest/, HEAD, the memo (one render for repeated requests, a new one
    for a refreshed list), the sitemap's 13 URLs at the data's date, llms.txt;
  * the footer: the homepage's Lists line links both new pages through the
    {{FOOTER_LISTS}} token, the shell pages always, and every guide renders
    byte-identical to the same template with the token taken out.
"""
import copy
import html.parser
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories, flightvalue, geo, guide_sizers, picks, pricelevel  # noqa: E402
from fxtracker import render_cheapest as RC, render_guide as rg, render_lists as RL  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

FIX = json.load(open(os.path.join(ROOT, "scripts", "fixtures", "cheapest_2026-10-23.json"), encoding="utf-8"))
for _it in FIX["adv_us"]["items"]:
    if not _it.get("via"):
        _it["level_text"] = advisories.LEVEL_TEXT[_it["level"]]
CLIM = json.load(open(os.path.join(ROOT, "public", "climate.json"), encoding="utf-8"))
FACTS = json.load(open(os.path.join(ROOT, "public", "guide-facts.json"), encoding="utf-8"))
TODAY = "2026-10-23"
FETCHED = {"us": 1792735200, "ca": 1792735300, "de": 1792735400}   # 2026-10-23 UTC
CENT = geo.country_centroids()
GUIDES = {iso for _s, iso in rg.all_slugs()}


def fx():
    return copy.deepcopy(FIX)


def render(f=None, **kw):
    f = f or FIX
    args = dict(flights=f["flights"], fv=f["fv"], fares_state="warm", fetched=FETCHED, today=TODAY, cent=CENT)
    args.update(kw)
    return RC.pages(f["adv_us"], f["adv_ca"], f["adv_de"], f["rates"], f["ppp"], CLIM, FACTS, **args)


class Check(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1, self.names, self.hrefs, self.text, self.open = 0, [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.h1 += tag == "h1"
        for k in ("class", "id"):
            if a.get(k):
                self.names += a[k].split()
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag not in ("br", "meta", "link", "img", "input"):
            self.open.append(tag)

    def handle_endtag(self, tag):
        if self.open and self.open[-1] == tag:
            self.open.pop()
        else:
            raise ValueError("unbalanced </%s> (open: %s)" % (tag, self.open[-3:]))

    def handle_data(self, data):
        self.text.append(data)


FORBIDDEN = re.compile(r"^(ad|adv|sponsor|banner|promo)|advert", re.I)


def parse(page):
    c = Check()
    c.feed(page["html"])
    c.close()
    return c


# --- the year -------------------------------------------------------------------------
oct_days = ["2026-10-01", "2026-10-15", "2026-10-31"]
dec_days = ["2026-12-01", "2026-12-31"]
yr_oct = all(RC.year_for(m, d) == (2026 if m >= 10 else 2027) for d in oct_days for m in range(1, 13))
yr_dec = all(RC.year_for(m, d) == (2026 if m == 12 else 2027) for d in dec_days for m in range(1, 13))
results.append(ok(yr_oct, "October: October to December are 2026, January to September 2027 (%s)" % ", ".join(oct_days)))
results.append(ok(yr_dec, "December: December is 2026, January to November 2027 (%s)" % ", ".join(dec_days)))
results.append(ok(RC.year_for(1, "2027-01-05") == 2027 and RC.year_for(12, "2027-01-05") == 2027,
                  "January 2027: January is this year, December too"))
results.append(ok(RC.month_order("2026-10-23")[:3] == [10, 11, 12] and RC.month_order("2026-10-23")[-1] == 9,
                  "the hub's rows start at this month"))
results.append(ok([RC.month_of(RC.path_for(m)) for m in range(1, 13)] == list(range(1, 13))
                  and RC.month_of("/cheapest/November") is None and RC.month_of("/cheapest/nov") is None
                  and RC.month_of("/cheapest") is None and len(set(RC.PATHS)) == 13,
                  "13 paths, the months in lowercase English only"))
P = render(today=TODAY)
P_dec = render(today="2026-12-10")
results.append(ok(P["/cheapest/october"]["year"] == 2026 and P["/cheapest/september"]["year"] == 2027
                  and "October 2026" in P["/cheapest/october"]["title"] and "September 2027" in P["/cheapest/september"]["title"]
                  and P_dec["/cheapest/november"]["year"] == 2027 and P_dec["/cheapest/december"]["year"] == 2026,
                  "titles carry the year: October 2026, September 2027; from December, November 2027"))

# --- the ranking on production data -------------------------------------------------------
rate_by = {r["code"]: r["rate_now"] for r in FIX["rates"]["rows"]}
strength = {r["code"]: r["strength_pct"] for r in FIX["rates"]["rows"]}
adv_by = picks.advisory_levels(FIX["adv_us"]["items"])
fit = pricelevel.plausibility_fit(FIX["ppp"], rate_by, picks.CUR_BY_ISO)
anchor = picks._price_level("US", FIX["ppp"], rate_by, fit) or 1
fares = picks.fare_context(FIX["flights"], CENT)
fares["fv"] = FIX["fv"]
own = {s: advisories.own_levels(FIX["adv_" + s]) for s in ("us", "ca", "de")}


def expected(month):
    keep = []
    for iso in picks.CUR_BY_ISO:
        if iso not in GUIDES or "-" in iso:
            continue
        s = picks._score(iso, month, FIX["ppp"], CLIM, rate_by, strength, adv_by, fit, fares, anchor,
                         home_iso="US", home_cur="USD")
        if not s or own["us"].get(iso) not in (1, 2):
            continue
        if advisories.dnt_for(iso, own, guide_sizers.ADV_PARENT):
            continue
        if pricelevel.js_round(100 * s["pl"]) > 50 or s["wx"] is None or s["wx"] < 70:
            continue
        keep.append(s)
    keep.sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))
    return keep


same, row_ok, total = [], [], 0
for m in range(1, 13):
    exp = expected(m)
    page = P[RC.path_for(m)]
    total += len(exp)
    if page["isos"] == [s["iso"] for s in exp]:
        same.append(m)
    trs = re.findall(r"<tr><td class=\"num\".*?</tr>", page["html"], re.S)
    good = len(trs) == len(exp)
    for s, tr in zip(exp, trs):
        g = picks.grade(s["value"])
        good = good and ('>%s</span> %d<' % (g, s["value"]) in tr
                         and '"Prices vs US"><span class="v">%d%%<' % pricelevel.js_round(100 * s["pl"]) in tr
                         and "/guide/" in tr and "<strong>%d</strong>" % s["wx"] in tr)
    row_ok.append(good)
results.append(ok(len(same) == 12 and total > 200,
                  "every month's rows are picks._score's US output, ruled and sorted as build_variant sorts "
                  "(%d rows over 12 months; counts %s)" % (total, [P[RC.path_for(m)]["counts"]["rows"] for m in range(1, 13)])))
results.append(ok(all(row_ok), "each row prints that score's grade, score, price and weather"))
nov = P["/cheapest/november"]
all_rows = [(m, i) for m in range(1, 13) for i in P[RC.path_for(m)]["isos"]]
results.append(ok(all(own["us"].get(i) in (1, 2) and not advisories.dnt_for(i, own, guide_sizers.ADV_PARENT)
                      and i in GUIDES and "-" not in i for _m, i in all_rows),
                  "no row is US Level 3-4, anyone's do not travel, a non-guide or a subdivision"))
via_only = {it["iso"] for it in FIX["adv_us"]["items"] if it.get("via")}
results.append(ok(not ({i for _m, i in all_rows} & via_only),
                  "no country the US list only gap-fills (%d such) is ever a row" % len(via_only)))
# DE or CA Level 4 while the US says 1-2: excluded although cheap with good weather.
de4 = sorted(i for i, l in own["de"].items() if l == 4 and own["us"].get(i) in (1, 2))
ca4 = sorted(i for i, l in own["ca"].items() if l == 4 and own["us"].get(i) in (1, 2))
results.append(ok(not ({i for _m, i in all_rows} & set(de4 + ca4)),
                  "Germany's or Canada's own Level 4 keeps a US Level 1-2 country off (%s)"
                  % ((de4 + ca4) or "none in this data; the mutations below make one")))

# Mutations of the real data: the top November row leaves for each rule.
top = nov["isos"][0]


def without_top(f, label):
    p = render(f)["/cheapest/november"]
    results.append(ok(top not in p["isos"] and p["isos"] == [i for i in nov["isos"] if i != top],
                      "%s: %s leaves November, the rest keep their order" % (label, top)))


f = fx()
next(it for it in f["adv_us"]["items"] if it.get("iso") == top and not it.get("via"))["level"] = 3
without_top(f, "US Level 3")
f = fx()
next(it for it in f["adv_de"]["items"] if it.get("iso") == top)["level"] = 4
without_top(f, "Germany's own Level 4")
f = fx()
next(it for it in f["adv_ca"]["items"] if it.get("iso") == top)["level"] = 4
without_top(f, "Canada's own Level 4")
f = fx()
it = next(it for it in f["adv_us"]["items"] if it.get("iso") == top and not it.get("via"))
it.update(via="ca", via_name="Global Affairs Canada", level=1)
without_top(f, "a Canadian gap-fill in the US list")
f = fx()
f["adv_us"]["items"] = [it for it in f["adv_us"]["items"] if it.get("iso") != top]
f["adv_ca"]["items"] = [it for it in f["adv_ca"]["items"] if it.get("iso") != top]
f["adv_de"]["items"] = [it for it in f["adv_de"]["items"] if it.get("iso") != top]
without_top(f, "rated by nobody")

# Fares: month_fare's price and band; a dash and the footnote otherwise.
fare_rows, dash_rows, fare_good = 0, 0, True
for s in expected(11):
    tr = re.search(r'<tr><td class="num"[^<]*</td><td class="name"[^>]*><span class="rk">\d+\.</span> [^<]*'
                   r'<a href="/guide/[a-z0-9-]+">%s</a>.*?</tr>' % re.escape(rg.name_for_iso(s["iso"])),
                   nov["html"], re.S).group(0)
    mf = picks.month_fare(FIX["fv"], s["iso"], 11)
    if mf:
        fare_rows += 1
        band = flightvalue.band(mf[0], FIX["fv"]["countries"][s["iso"]])
        fare_good = fare_good and ('$%s <span class="fvband %s"' % (format(mf[0], ","), band) in tr
                                   and ">%s</span>" % RC.FV_WORD[band] in tr)
    else:
        dash_rows += 1
        fare_good = fare_good and '"US fare"><span class="v">—<sup class="fn">*</sup>' in tr
results.append(ok(fare_good and fare_rows > 5 and dash_rows > 5,
                  "November fares: month_fare's price with its Low/Typical/High band (%d rows), a dash with the "
                  "footnote mark otherwise (%d rows)" % (fare_rows, dash_rows)))
results.append(ok(nov["html"].count("Fares are cached searches, not live prices, and many months have none") == 1,
                  "one footnote on the fares"))
off = render(flights=None, fv=None, fares_state="off")["/cheapest/november"]
results.append(ok(not off["degraded"] and "fvband" not in off["html"] and off["counts"]["rows"] > 0,
                  "no fare source configured: every fare a dash, the page not degraded for that"))
results.append(ok(not nov["degraded"] and nov["lastmod"] == "2026-10-23" and P["/cheapest"]["lastmod"] == "2026-10-23",
                  "complete inputs: not degraded; lastmod is the rates' own date"))
results.append(ok("Level 1: Exercise normal precautions" in nov["html"]
                  and "Level 2: Exercise increased caution" in nov["html"]
                  and 'title="U.S. State Department: Exercise Normal Precautions, dated' in nov["html"],
                  "the US advisory in the State Department's own words, its date in the tooltip"))
th = next(s for s in expected(11) if s["iso"] == "TH") if "TH" in nov["isos"] else None
results.append(ok(th is None or "measured at Bangkok" in nov["html"],
                  "the weather tooltip names the sample place where climate.json has one"))
results.append(ok(re.search(r"<strong>\d+</strong> · -?\d+°C / -?\d+°F", nov["html"]) is not None
                  and "average daily mean temperature" in nov["html"],
                  "weather: the score, then the average daily mean temperature in C and F"))

# --- the rule at its edges, with a stand-in scorer --------------------------------------
def item(iso, level, **kw):
    return dict({"iso": iso, "level": level, "level_text": advisories.LEVEL_TEXT[level]}, **kw)


US = {"items": [item("VN", 1), item("TH", 1), item("LA", 1), item("KH", 2), item("EG", 3), item("CO", 1),
                item("GG", 1), item("GB", 1), item("MA", 2), item("PE", 1), item("BO", 1),
                item("PR", 1, via="ca"), item("NP", 2)]}
CA = {"items": [item("CO", 4), item("VN", 2)]}
DE = {"items": [item("GB", 4), item("NP", 1)]}
#            pl      wx   value raw    advLvl
FAKE = {"VN": (0.50, 70, 80, 80.2, 1), "TH": (0.505, 90, 95, 95, 1), "LA": (0.30, 69, 95, 95, 1),
        "KH": (0.4049, 75, 80, 80.4, 2), "EG": (0.2, 99, 99, 99, 3), "CO": (0.3, 90, 90, 90, 1),
        "GG": (0.4, 90, 90, 90, 1), "MA": (0.45, 80, 80, 80.2, 2), "PE": (0.45, 80, 70, 70, 1),
        "BO": (0.5049, 71, 60, 60, 1), "PR": (0.3, 90, 90, 90, 1)}


def fake_score(iso, month, *a, **k):
    if iso not in FAKE:
        return None          # NP: unrated / no price for the scorer
    pl, wx, value, raw, adv = FAKE[iso]
    return {"iso": iso, "name": rg.name_for_iso(iso), "pl": pl, "wx": wx, "value": value, "raw": raw,
            "advLvl": adv, "fare": None, "fly_basis": None}


rates_min = {"as_of": "2026-10-20", "rows": [{"code": "EUR", "rate_now": 0.9, "strength_pct": 1.0}]}
E = RC.pages(US, CA, DE, rates_min, {"US": {}}, CLIM, FACTS, score=fake_score, fetched=FETCHED, today=TODAY,
             cent=CENT)["/cheapest/november"]
results.append(ok(E["isos"] == ["KH", "MA", "VN", "PE", "BO"],
                  "edges: 50%% in, 50.5%% (51) out, 50.49 in; weather 70 in, 69 out; US Level 2 in, 3 out; "
                  "Canada's Level 4 out; Germany's Level 4 on the UK takes Guernsey out; a gap-fill out; "
                  "unrated out; ties by the unrounded score, then the name: %s" % E["isos"]))
results.append(ok(E["lastmod"] == "2026-10-20", "lastmod follows the rates' date"))

# --- degraded -------------------------------------------------------------------------------
def deg(label, page, needle, rows=None):
    results.append(ok(page["degraded"] and needle in page["html"]
                      and "This page is served uncached until then." in page["html"]
                      and (rows is None or (page["counts"]["rows"] > 0) == rows),
                      "%s: degraded, says so%s" % (label, "" if rows is None else (", rows kept" if rows else ", no rows"))))


f = FIX
deg("Canada's list missing", RC.pages(f["adv_us"], None, f["adv_de"], f["rates"], f["ppp"], CLIM, FACTS, flights=f["flights"],
                                       fv=f["fv"], fares_state="warm", today=TODAY, cent=CENT)["/cheapest/november"],
    "Global Affairs Canada list is not available right now", True)
deg("both other lists missing", RC.pages(f["adv_us"], None, None, f["rates"], f["ppp"], CLIM, FACTS, today=TODAY,
                                         cent=CENT)["/cheapest/november"],
    "Global Affairs Canada and German Federal Foreign Office (Auswärtiges Amt) lists are not available right now, "
    "so their “do not travel” check could not be applied.", True)
U = RC.pages(None, f["adv_ca"], f["adv_de"], f["rates"], f["ppp"], CLIM, FACTS, today=TODAY, cent=CENT)
deg("US list missing", U["/cheapest/november"], "the US levels are from WanderGrade's daily snapshot of", True)
deg("rates missing", RC.pages(f["adv_us"], f["adv_ca"], f["adv_de"], None, f["ppp"], CLIM, FACTS, today=TODAY,
                              cent=CENT)["/cheapest/november"],
    "Exchange rates or World Bank PPP are not loaded yet", False)
deg("PPP missing", RC.pages(f["adv_us"], f["adv_ca"], f["adv_de"], f["rates"], None, CLIM, FACTS, today=TODAY,
                            cent=CENT)["/cheapest/november"],
    "Exchange rates or World Bank PPP are not loaded yet", False)
deg("climate missing", RC.pages(f["adv_us"], f["adv_ca"], f["adv_de"], f["rates"], f["ppp"], None, FACTS, today=TODAY,
                                cent=CENT)["/cheapest/november"], "Climate data is not loaded", False)
deg("snapshot missing", RC.pages(f["adv_us"], f["adv_ca"], f["adv_de"], f["rates"], f["ppp"], CLIM, None, today=TODAY,
                                 cent=CENT)["/cheapest/november"], "WanderGrade's daily snapshot is not loaded", True)
deg("fares still loading", render(fares_state="cold")["/cheapest/november"],
    "US fares are still loading, so fares and flight grades may change", True)
S = render(stale={"us": 7 * 3600 + 100})["/cheapest/november"]
results.append(ok(S["degraded"] and "refresh failing, showing the copy from 7h ago" in S["html"]
                  and "refresh failing" not in nov["html"],
                  "a failing refresh: noted by the fetch time, degraded"))
results.append(ok(all(p["degraded"] for p in U.values()), "a missing input degrades all 13 pages, the hub too"))

# --- titles, descriptions, hygiene -----------------------------------------------------------
titles = [p["title"] for p in P.values()]
descs = [p["desc"] for p in P.values()]
results.append(ok(all(len(t) <= 60 for t in titles), "titles <= 60 (longest %d)" % max(map(len, titles))))
results.append(ok(all(len(d) <= 157 for d in descs), "descriptions <= 157 (longest %d)" % max(map(len, descs))))
results.append(ok(len(set(titles)) == 13 and len(set(descs)) == 13, "all 13 titles and descriptions unique"))
for variant in (U, P_dec, render(dict(FIX, rates=None))):
    results.append(ok(all(len(p["title"]) <= 60 and len(p["desc"]) <= 157 for p in variant.values())
                      and len({p["desc"] for p in variant.values()}) == 13,
                      "degraded and December variants keep the limits and unique descriptions"))
results.append(ok(not any("best time" in (p["title"] + p["desc"] + p["h1"] + p["html"]).lower() for p in P.values()),
                  "no \"best time\" anywhere"))
results.append(ok(nov["title"] == "Cheapest Countries to Visit in November 2026 (From the US)"
                  and P["/cheapest"]["title"] == "Cheapest Countries to Visit Each Month (From the US)",
                  "the titles: %r, %r" % (nov["title"], P["/cheapest"]["title"])))
results.append(ok(re.match(r"\d+ countries at most half US prices", nov["desc"])
                  and str(nov["counts"]["rows"]) in nov["desc"] and rg.name_for_iso(nov["isos"][0]) in nov["desc"],
                  "the description from the live count and names: %r" % nov["desc"]))
hy = []
for path, p in P.items():
    c = parse(p)
    text = " ".join(c.text)
    guides = [h for h in c.hrefs if h.startswith("/guide/")]
    hy.append(c.h1 == 1 and not [n for n in c.names if FORBIDDEN.search(n)] and not c.open
              and all(rg.iso_for_slug(h[7:]) for h in guides) and "None" not in text
              and "<script" not in p["html"] and "/safe-and-cheap" in c.hrefs
              and "23 Oct 2026" in text)
results.append(ok(all(hy), "all 13: one h1, no ad-blocker names, closed tags, real guide links, no None, no "
                           "script, a /safe-and-cheap link, the snapshot date"))
c = parse(nov)
results.append(ok({"/cheapest/october", "/cheapest/december", "/cheapest", "/safe-and-cheap"} <= set(c.hrefs)
                  and "/?vmn=11&vo=US" in c.hrefs,
                  "November links October, December, the hub, /safe-and-cheap and its Top Picks view"))
jan = parse(P["/cheapest/january"])
results.append(ok({"/cheapest/december", "/cheapest/february"} <= set(jan.hrefs), "January wraps back to December"))
hub = parse(P["/cheapest"])
results.append(ok(all(RC.path_for(m) in hub.hrefs for m in range(1, 13)) and "October 2026" in " ".join(hub.text)
                  and "September 2027" in " ".join(hub.text)
                  and all(str(P[RC.path_for(m)]["counts"]["rows"]) in P["/cheapest"]["html"] for m in range(1, 13)),
                  "the hub: a row per month with its link, year and count"))
results.append(ok(all(rg.name_for_iso(i) in P["/cheapest"]["html"] for i in P["/cheapest/november"]["isos"][:3]),
                  "the hub names each month's top three"))
results.append(ok(all("at or under 50% of the US" in p["html"] and "weather score of 70+" in p["html"]
                      and "US State Department Level 1 or 2" in p["html"] for p in P.values())
                  and all("Left out: US Level 3 and 4" in p["html"] for p in P.values()),
                  "the rule and the exclusions line on every page"))

# --- the server --------------------------------------------------------------------------------
import server  # noqa: E402

server.Handler.log_message = lambda self, *a: None
server._warm_adv_lists = lambda: None          # no fetch from a test
server._warm_watchouts = lambda iso: None
now = time.time()
for s in ("us", "ca", "de"):
    server._adv_cache[s] = (now, FIX["adv_" + s])
cfg = server.store.load_config()
server._rates_cache[(cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD")] = (now, FIX["rates"])
server._ppp_cache.update(at=now, data=FIX["ppp"])
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def get(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


calls = [0]
_real_pages = RC.pages


def counting(*a, **k):
    calls[0] += 1
    return _real_pages(*a, **k)


RC.pages = counting
configured = server.flights.is_configured()
codes = {}
for p in RC.PATHS:
    st, hd, body = get(p)
    codes[p] = (st, hd.get("Cache-Control"), "<h1>" in body)
results.append(ok(all(v[0] == 200 and v[2] for v in codes.values()), "200 with a page for all 13 paths"))
results.append(ok(configured or all(v[1] == "public, max-age=300" for v in codes.values()),
                  "cached 5 minutes when nothing is missing (%s)" % sorted({v[1] for v in codes.values()})))
results.append(ok(calls[0] == 1, "13 requests, one render (memoized): %d" % calls[0]))
st, hd, body = get("/cheapest/november")
results.append(ok(calls[0] == 1 and "Cheapest countries to visit in November 2026" in body
                  and '<link rel="canonical" href="https://wandergrade.com/cheapest/november">' in body,
                  "the November page from the memo, canonical to itself"))
server._adv_cache["us"] = (now, copy.deepcopy(FIX["adv_us"]))     # a refreshed list: a new object
get("/cheapest/september")
results.append(ok(calls[0] == 2, "a refreshed list re-renders"))
del server._adv_cache["ca"]
st, hd, body = get("/cheapest/november")
results.append(ok(st == 200 and hd.get("Cache-Control") == "no-store" and "Global Affairs Canada list is not available" in body,
                  "Canada's list not in hand: served no-store and says so"))
server._adv_cache["ca"] = (now, FIX["adv_ca"])
st, hd, _b = get("/cheapest/")
st2, hd2, _b = get("/cheapest/november/?utm_source=x")
results.append(ok(st == 301 and hd.get("Location") == "/cheapest" and st2 == 301
                  and hd2.get("Location") == "/cheapest/november?utm_source=x",
                  "a trailing slash 301s to the canonical URL, query kept"))
nf = [get(p)[0] for p in ("/cheapest/November", "/cheapest/nov", "/cheapest/november/x", "/cheapest/13", "/cheapest//")]
results.append(ok(nf[:4] == [404] * 4 and nf[4] == 301, "anything else under /cheapest/ is a 404: %s" % nf))
st, hd, body = get("/cheapest", "HEAD")
results.append(ok(st == 200 and body == "", "HEAD answers 200 with no body"))
st, hd, sm = get("/sitemap.xml")
stamp = open(os.path.join(ROOT, "public", "content-stamp.txt")).read().strip()[:10]
lm = re.findall(r"<loc>https://wandergrade\.com(/cheapest[^<]*)</loc><lastmod>([^<]+)</lastmod>", sm)
results.append(ok(sorted(p for p, _ in lm) == sorted(RC.PATHS) and {d for _, d in lm} == {max(stamp, "2026-10-23")},
                  "the sitemap lists the 13 at the rates' date floored at the stamp (%s)" % sorted({d for _, d in lm})))
st, hd, llms = get("/llms.txt")
results.append(ok("https://wandergrade.com/cheapest)" in llms and "https://wandergrade.com/dollar-strength)" in llms,
                  "llms.txt carries the hub and the dollar page"))

# --- the footer: homepage token, shell pages, guides byte-identical ------------------------
LINKS = ('<a href="/cheapest">Cheapest by month</a>', '<a href="/dollar-strength">Dollar strength</a>')
st, hd, home = get("/")
foot = home[home.find("<footer>"):home.find("</footer>")]
results.append(ok(all(l in foot for l in LINKS) and "{{" not in home, "the homepage footer links both new pages"))
shell = server._render_404_page("x").decode("utf-8") + server._shell_page("t", "b").decode("utf-8")
results.append(ok(all(shell.count(l) >= 2 for l in LINKS), "the shell pages' footer links both (404, any shell page)"))
SAMPLE = ["JP", "TH", "PT", "VN", "MX", "FR", "US", "ET", "GG", "GB-ENG", "AQ", "PR", "AR", "EG"]
guides = {iso: server._render_index(iso).decode("utf-8") for iso in SAMPLE}
results.append(ok(all("/cheapest" not in g and "/dollar-strength" not in g and "{{FOOTER_LISTS}}" not in g
                      for g in guides.values()), "no guide carries the links or the bare token"))
tpl_now, gtpl_now = server._index_template(), server._guide_template()
try:
    server._html_tpl = tpl_now.replace("{{FOOTER_LISTS}}", "")
    server._guide_tpl = None
    without = {iso: server._render_index(iso).decode("utf-8") for iso in SAMPLE}
finally:
    server._html_tpl, server._guide_tpl = tpl_now, gtpl_now
same = [iso for iso in SAMPLE if without[iso] == guides[iso]]
results.append(ok(len(same) == len(SAMPLE) and tpl_now.count("{{FOOTER_LISTS}}") == 1
                  and "Safest cheap countries</a>{{FOOTER_LISTS}} &amp; " in tpl_now,
                  "every guide is byte-identical to the token-less template's (%d of %d), the token "
                  "sits in the line with no space of its own" % (len(same), len(SAMPLE))))
safe = RL.safe_and_cheap(FIX["adv_us"], FIX["adv_ca"], FIX["adv_de"], FACTS, CLIM, {}, {})
dnt = RL.do_not_travel(FIX["adv_us"], FIX["adv_ca"], FIX["adv_de"])
results.append(ok(all('href="/cheapest"' in p["html"] and 'href="/dollar-strength"' in p["html"] for p in (safe, dnt)),
                  "/safe-and-cheap and /do-not-travel link both new pages under See also"))

httpd.shutdown()
print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

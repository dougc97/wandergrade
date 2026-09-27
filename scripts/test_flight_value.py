"""The Flights tab's low / typical / high: stats and banding on recorded
production curves, then /api/flight-value end to end — with no real
Travelpayouts key. The token below is a dummy and rates.fetch_json is
replaced by a fake upstream, so nothing leaves this machine.

    /usr/bin/python3 scripts/test_flight_value.py
"""
import datetime, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request

os.environ["TRAVELPAYOUTS_TOKEN"] = "dummy-never-sent"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fxtracker import flights, flightvalue, rates

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

# Recorded 2026-09-26: production /api/flight-months?origin=US&iso=XX.
CURVES = {
    "GR": {"2026-10": 656, "2026-11": 652, "2026-12": 610, "2027-01": 677, "2027-04": 683, "2027-05": 618},
    "MA": {"2026-09": 731, "2026-10": 498, "2026-11": 618, "2026-12": 656, "2027-03": 582, "2027-08": 939},
    "JP": {"2026-09": 1086, "2026-10": 905, "2026-11": 928, "2026-12": 989, "2027-01": 973, "2027-03": 1056,
           "2027-04": 665, "2027-05": 646, "2027-06": 1116, "2027-07": 1165, "2027-09": 1085},
    "TR": {"2026-09": 742, "2026-10": 684, "2026-11": 666, "2026-12": 665, "2027-01": 408, "2027-02": 414,
           "2027-03": 732, "2027-04": 777, "2027-05": 879, "2027-06": 974, "2027-07": 973, "2027-08": 797},
    "IS": {"2026-09": 676, "2026-10": 505, "2026-12": 381, "2027-01": 414},
}
REC_DAY = datetime.date(2026, 9, 26)

# --- percentiles --------------------------------------------------------------
P = flightvalue.percentile
results.append(ok(P([1, 2, 3, 4], 0.25) == 1.75 and P([1, 2, 3, 4], 0.5) == 2.5
                  and P([1, 2, 3, 4], 0.75) == 3.25, "linear-interpolated quartiles of 1..4"))
results.append(ok(P([7], 0.25) == 7 and P([], 0.5) is None, "one value / no values"))
results.append(ok(P([10, 20, 30, 40, 50], 0.5) == 30 and P([10, 20, 30, 40, 50], 0.25) == 20,
                  "odd count lands on real months"))

# --- stats on real curves -----------------------------------------------------
S = flightvalue.curve_stats
ma = S(CURVES["MA"].values())
results.append(ok(ma == {"n_months": 6, "median": 637, "p25": 591, "p75": 712, "lo": 591, "hi": 712},
                  "Morocco: median 637, typical 591-712 (hand-checked) -> %s" % ma))
b = flightvalue.band
results.append(ok(b(498, ma) == "low" and b(582, ma) == "low" and b(618, ma) == "typical"
                  and b(656, ma) == "typical" and b(731, ma) == "high" and b(939, ma) == "high",
                  "Morocco: Oct/Mar low, Nov/Dec typical, Sep/Aug high"))
results.append(ok(round(flightvalue.deviation(498, ma) * 100) == -22, "Morocco October -22% vs median"))

gr = S(CURVES["GR"].values())
results.append(ok(gr["median"] == 654 and gr["p25"] == 626 and gr["p75"] == 672
                  and gr["lo"] == 621 and gr["hi"] == 687,
                  "Greece: +/-5%% floor widens a flat year's range to 621-687 -> %s" % gr))
results.append(ok(677 > flightvalue.percentile(sorted(CURVES["GR"].values()), 0.75)
                  and b(677, gr) == "typical" and b(610, gr) == "low",
                  "Greece January (+3.5%, raw-quartile 'high') reads typical; December (-7%) low"))

tr = S(CURVES["TR"].values())
results.append(ok(tr["n_months"] == 12 and tr["median"] == 737 and b(408, tr) == "low"
                  and b(974, tr) == "high" and b(742, tr) == "typical",
                  "Turkey, a full year: Jan low, Jun high, Sep typical"))

# thresholds are strict on both edges
edge = {"n_months": 6, "median": 100, "lo": 90, "hi": 110}
results.append(ok(b(90, edge) == "typical" and b(89, edge) == "low" and b(110, edge) == "typical"
                  and b(111, edge) == "high", "range edges are typical; one unit past is low/high"))

# too few months: counted, never banded
is_ = S(CURVES["IS"].values())
results.append(ok(is_ == {"n_months": 4} and b(381, is_) is None and flightvalue.deviation(381, is_) is None,
                  "Iceland (4 months) gets no range, no band, no deviation"))
results.append(ok(S([500, 510, 520, 530, 540])["n_months"] == 5 and "median" not in S([500, 510, 520, 530, 540])
                  and "median" in S([500, 510, 520, 530, 540, 550]),
                  "MIN_MONTHS = 6 is the line (5 no, 6 yes)"))
results.append(ok(b(None, ma) is None, "a month with no fare has no band"))

# --- the 12-month window, across a year boundary ------------------------------
W = flightvalue.window_months
results.append(ok(W(REC_DAY) == ["2026-%02d" % m for m in range(9, 13)] + ["2027-%02d" % m for m in range(1, 9)],
                  "window from 2026-09-26 is Sep 2026 .. Aug 2027"))
results.append(ok(W(datetime.date(2026, 12, 31))[:3] == ["2026-12", "2027-01", "2027-02"]
                  and W(datetime.date(2026, 12, 31))[-1] == "2027-11" and len(W(datetime.date(2027, 1, 1))) == 12,
                  "December start wraps into the next year; always 12 months"))

# --- build(): curves from the cache alone ----------------------------------------
def rows_for(curves, extra=None):
    out = []
    for iso in curves:
        r = {"iso": iso, "dest": iso + "X", "cities": [iso + "X", iso + "Y"], "n": 10}
        out.append(r)
    out.append({"iso": "NO", "dest": "OSL", "cities": ["OSL"], "n": 1})
    for r in out:
        r.update((extra or {}).get(r["iso"], {}))
    return out


def fake_lookup(curves, missing=()):
    def look(o, city, cur="usd"):
        if city in missing:
            return None
        iso = city[:2]
        if city.endswith("X") and iso in curves:
            return {"configured": True, "months": {k: {"price": v, "stops": 1} for k, v in curves[iso].items()}}
        return {"configured": True, "months": {}}
    return look


rows = rows_for(CURVES)
p = flightvalue.build("US", {"countries": rows, "origin_name": "United States"}, today=REC_DAY,
                      lookup=fake_lookup(CURVES), needs_fetch=lambda o, c: False)
C = p["countries"]
results.append(ok(p["ready"] == 6 and p["total"] == 6 and p["refresh"] == 0 and p["months"][0] == "2026-09",
                  "every country resolved from cache: ready 6/6, nothing to refresh"))
results.append(ok("2027-09" not in C["JP"]["curve"] and C["JP"]["n_months"] == 10,
                  "Japan's 13th month (Sep 2027) is outside the window and out of the stats"))
results.append(ok(C["MA"]["curve"]["2026-10"] == [498, "MAX"] and "2027-01" not in C["MA"]["curve"]
                  and C["MA"]["lo"] == 591, "Morocco: Oct fare + its city; January simply absent"))
results.append(ok(C["NO"] == {"curve": {}, "n_months": 0}, "no months cached -> empty curve, no stats"))
results.append(ok(C["IS"]["n_months"] == 4 and "median" not in C["IS"], "Iceland: curve kept, no stats"))

# unfetched city -> pending, and counted for the warmer
p2 = flightvalue.build("US", {"countries": rows}, today=REC_DAY, lookup=fake_lookup(CURVES, missing={"GRX"}),
                       needs_fetch=lambda o, c: c == "GRX")
results.append(ok(p2["countries"]["GR"] == {"pending": True} and p2["ready"] == 5 and p2["refresh"] == 1,
                  "a never-fetched city makes its country pending (ready 5/6, refresh 1)"))
# a city skipped by the >=10-month early stop is never needed
p3 = flightvalue.build("US", {"countries": rows}, today=REC_DAY, lookup=fake_lookup(CURVES, missing={"TRY"}),
                       needs_fetch=lambda o, c: c == "TRY")
results.append(ok(p3["countries"]["TR"].get("n_months") == 12 and p3["refresh"] == 0,
                  "Turkey's first city covers the year, so its unfetched second city isn't waited on"))

# latest-prices row months widen the curve; cheapest per month wins
extra = {"IS": {"months": {"2026-11": {"price": 450, "dest": "ISZ"}, "2027-02": {"price": 470, "dest": "ISZ"},
                           "2026-10": {"price": 520, "dest": "ISZ"}}}}
p4 = flightvalue.build("US", {"countries": rows_for(CURVES, extra)}, today=REC_DAY,
                       lookup=fake_lookup(CURVES), needs_fetch=lambda o, c: False)
isc = p4["countries"]["IS"]
results.append(ok(isc["n_months"] == 6 and isc["curve"]["2026-11"] == [450, "ISZ"]
                  and isc["curve"]["2026-10"] == [505, "ISX"] and "median" in isc,
                  "Iceland + row months: 6 months (new Nov/Feb), Oct keeps the cheaper route fare"))

# --- get_flights: the per-country month curve from latest-prices rows ----------
UP = {"monthly": [], "latest": 0, "fail_monthly": False, "fail_latest": False}
TODAY = datetime.date.today()
WIN = flightvalue.window_months()
d = lambda days: (TODAY + datetime.timedelta(days=days)).isoformat()
CITY_META = [{"code": c, "name": c, "country_code": iso} for iso, cs in
             {"MA": ["CMN", "RAK"], "GR": ["ATH"], "TR": ["IST"], "NO": ["OSL"], "US": ["NYC"]}.items() for c in cs]
ROWS = [
    {"destination": "CMN", "value": 700, "depart_date": d(20), "found_at": d(-3) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "RAK", "value": 640, "depart_date": d(21), "found_at": d(-2) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "RAK", "value": 300, "depart_date": d(-5), "found_at": d(-9) + "T10:00:00Z", "number_of_changes": 0},
    {"destination": "CMN", "value": 350, "depart_date": d(60), "found_at": d(-200) + "T10:00:00Z", "number_of_changes": 0},
    {"destination": "ATH", "value": 610, "depart_date": d(70), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "IST", "value": 690, "depart_date": d(40), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "OSL", "value": 437, "depart_date": d(130), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 0},
]
# Upstream monthly curves, shifted onto the live window so this half of the
# test doesn't rot as the calendar moves: CURVES[iso] month i -> WIN[i].
def shifted(iso):
    ks = sorted(CURVES[iso])
    return {WIN[i]: CURVES[iso][k] for i, k in enumerate(ks) if i < 12}


MONTHLY = {"CMN": shifted("MA"), "ATH": shifted("GR"), "IST": shifted("TR"), "OSL": {WIN[4]: 437}, "RAK": {}}


def fake_fetch(url, retries=3):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    if "/data/en/cities.json" in url:
        return CITY_META
    if "get_latest_prices" in url:
        UP["latest"] += 1
        if UP["fail_latest"]:
            raise urllib.error.URLError("fake outage")
        return {"data": ROWS if q.get("page") == "1" else []}
    if "/v1/prices/monthly" in url:
        UP["monthly"].append(q["destination"])
        if UP["fail_monthly"]:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"data": {k + "-11": {"price": v, "transfers": 1}
                         for k, v in MONTHLY.get(q["destination"], {}).items()}}
    raise AssertionError("unexpected upstream call " + url)


rates.fetch_json = fake_fetch
flights._cities = None
fl = flights.get_flights("US")
ma_row = next(r for r in fl["countries"] if r["iso"] == "MA")
exp = {}
for city, price, days in (("CMN", 700, 20), ("RAK", 640, 21)):   # the two live, fresh rows
    k = d(days)[:7]
    if k not in exp or price < exp[k][0]:
        exp[k] = (price, city)
got = {k: (v["price"], v["dest"]) for k, v in ma_row["months"].items()}
results.append(ok(got == exp, "row months: cheapest per departure month + its city -> %s" % got))
results.append(ok(not any(v["price"] in (300, 350) for v in ma_row["months"].values()),
                  "row months skip a departure already flown and a fare older than 90 days"))
results.append(ok(fl["by_country"]["MA"] == 547 and ma_row["min"] == 300,
                  "the average and cheapest (Top Picks inputs) are computed exactly as before"))

# --- HTTP: /api/flight-value and the guide's /api/flight-months ---------------
import server
from http.server import ThreadingHTTPServer
flightvalue.PACE = 0.2
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b"{}")


st, _, bd = get("/api/flight-value?origin=ZZ")
results.append(ok(st == 400 and bd.get("error"), "unsupported origin -> 400"))
st, _, bd = get("/api/flight-value?origin=%3Cscript%3E")
results.append(ok(st == 400, "junk origin -> 400"))

server._flights_cache.clear()
flights._monthly_cache.clear()
UP["monthly"].clear()
st, hd, first = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and first["filling"] and first["ready"] < first["total"]
                  and hd.get("Cache-Control") == "no-store",
                  "cold: answers at once with filling=true, ready %d/%d, no-store"
                  % (first.get("ready", -1), first.get("total", -1))))
results.append(ok(all(v == {"pending": True} for v in first["countries"].values()),
                  "cold: every country pending, nothing invented"))
st, _, again = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and flightvalue.is_warming("US") and len(flightvalue._warming) == 1,
                  "a second request doesn't start a second warmer"))
deadline = time.time() + 15
while flightvalue.is_warming("US") and time.time() < deadline:
    time.sleep(0.05)
st, hd, done = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and not done["filling"] and done["ready"] == done["total"] == 4
                  and hd.get("Cache-Control") == "public, max-age=600",
                  "warm: complete, ready 4/4, cacheable for 10 min"))
results.append(ok(sorted(UP["monthly"]) == sorted(set(UP["monthly"])),
                  "each route fetched once (%d monthly calls: %s)" % (len(UP["monthly"]), ",".join(UP["monthly"]))))
results.append(ok("RAK" in UP["monthly"] and "CMN" in UP["monthly"],
                  "a country's second city is fetched when the first doesn't cover the year"))
mac = done["countries"]["MA"]
results.append(ok(mac.get("n_months", 0) >= 6 and "median" in mac, "Morocco banded after the fill: %s" % mac))

# The guide chart and the tab: same country, same month, same number.
st, _, guide = get("/api/flight-months?origin=US&iso=MA")
same = all(guide["months"][k]["price"] == v[0] for k, v in mac["curve"].items())
results.append(ok(st == 200 and same and set(mac["curve"]) == {k for k in guide["months"] if k in set(WIN)},
                  "guide /api/flight-months?iso=MA and /api/flight-value agree month by month"))
st, _, fl_pub = get("/api/flights?origin=US")
results.append(ok(st == 200 and all("months" not in r for r in fl_pub["countries"]),
                  "/api/flights doesn't ship the server-side month curves"))

# Stale-on-error: fares expired + upstream down -> last good copy, still 200.
ts, payload = server._flights_cache["US"]
server._flights_cache["US"] = (ts - server.FLIGHTS_TTL - 5, payload)
server._upstream_fail.clear()
UP["fail_latest"] = True
st, _, stale = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and stale["ready"] == 4, "fares refresh fails -> served from the stale copy"))
UP["fail_latest"] = False

# Circuit breaker: a failing monthly API ends the pass after MAX_FAILS calls,
# and the cooldown keeps it from restarting on the next request.
flights._monthly_cache.clear()
server._flights_cache.clear()
server._upstream_fail.clear()
flightvalue._warm_done.clear()
UP["monthly"].clear()
UP["fail_monthly"] = True
ROWS.extend({"destination": c, "value": 900 + i, "depart_date": d(30), "found_at": d(-1) + "T10:00:00Z"}
            for i, c in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]))
CITY_META.extend({"code": c, "name": c, "country_code": "Q" + c[0]} for c in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"])
flights._cities = None
st, _, bd = get("/api/flight-value?origin=US")
deadline = time.time() + 15
while flightvalue.is_warming("US") and time.time() < deadline:
    time.sleep(0.05)
results.append(ok(len(UP["monthly"]) == flightvalue.MAX_FAILS,
                  "429s: the pass stops after %d failed calls (made %d)" % (flightvalue.MAX_FAILS, len(UP["monthly"]))))
st, _, bd = get("/api/flight-value?origin=US")
results.append(ok(not bd["filling"] and len(UP["monthly"]) == flightvalue.MAX_FAILS,
                  "within the cooldown a request doesn't restart it (filling=false)"))
UP["fail_monthly"] = False

# No token: a sane empty answer, never an upstream call.
os.environ.pop("TRAVELPAYOUTS_TOKEN")
n_before = len(UP["monthly"]) + UP["latest"]
st, _, bd = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and bd["configured"] is False and bd["countries"] == {} and not bd["filling"]
                  and len(UP["monthly"]) + UP["latest"] == n_before,
                  "no token: configured=false, empty, no upstream call"))
httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

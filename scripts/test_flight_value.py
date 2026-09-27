"""The Flights tab's low / typical / high: stats and banding on recorded
production curves, the monthly-curve cache, /api/flight-value end to end and
the background warmer — with no real Travelpayouts key. The token below is a
dummy and rates.fetch_json is replaced by a fake upstream, so nothing leaves
this machine.

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
REC_DAY = datetime.date(2026, 9, 26)   # 5 days of September left: it may leave the stats
MID_DAY = datetime.date(2026, 9, 10)   # same window, September always counted

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

# --- the current month leaves the stats in its last days ---------------------
PM = flightvalue.partial_month
results.append(ok(PM(REC_DAY) == "2026-09" and PM(datetime.date(2026, 9, 21)) is None
                  and PM(datetime.date(2026, 9, 22)) == "2026-09" and PM(MID_DAY) is None,
                  "partial month: Sep 21 has 10 days left (counted), Sep 22 has 9 (not)"))
results.append(ok(PM(datetime.date(2027, 2, 19)) is None and PM(datetime.date(2027, 2, 20)) == "2027-02"
                  and PM(datetime.date(2026, 12, 31)) == "2026-12",
                  "partial month follows the month's length (Feb 20 of 28; Dec 31)"))
SP = flightvalue.stats_prices
six = {"2026-%02d" % m: 100 + m for m in range(10, 13)}
six.update({"2027-%02d" % m: 200 + m for m in range(1, 4)})
results.append(ok(sorted(SP(dict(six, **{"2026-09": 999}), "2026-09")) == sorted(six.values()),
                  "partial month + 6 others: it leaves the stats (the 6 others stand alone)"))
five = dict(list(six.items())[:5])
results.append(ok(sorted(SP(dict(five, **{"2026-09": 999}), "2026-09")) == sorted(list(five.values()) + [999]),
                  "partial month + only 5 others: it stays in (a range, not 'too few')"))
results.append(ok(sorted(SP(six, "2026-09")) == sorted(six.values()) and sorted(SP(dict(six, **{"2026-09": 999}), None))
                  == sorted(list(six.values()) + [999]),
                  "no fare in the partial month, or no partial month: every month counts"))

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
p = flightvalue.build("US", {"countries": rows, "origin_name": "United States"}, today=MID_DAY,
                      lookup=fake_lookup(CURVES), needs_fetch=lambda o, c: False)
C = p["countries"]
results.append(ok(p["ready"] == 6 and p["total"] == 6 and p["refresh"] == 0 and p["months"][0] == "2026-09"
                  and p["partial"] is None,
                  "every country resolved from cache: ready 6/6, nothing to refresh, no partial month"))
results.append(ok("2027-09" not in C["JP"]["curve"] and C["JP"]["n_months"] == 10,
                  "Japan's 13th month (Sep 2027) is outside the window and out of the stats"))
results.append(ok(C["MA"]["curve"]["2026-10"] == [498, "MAX"] and "2027-01" not in C["MA"]["curve"]
                  and C["MA"]["lo"] == 591, "Morocco: Oct fare + its city; January simply absent"))
results.append(ok(C["NO"] == {"curve": {}, "n_curve": 0, "n_months": 0}, "no months cached -> empty curve, no stats"))
results.append(ok(C["IS"]["n_months"] == C["IS"]["n_curve"] == 4 and "median" not in C["IS"],
                  "Iceland: curve kept, no stats"))

# Sep 26: September stays in every curve (same number as the guide chart);
# where 6+ other months remain it is out of the typical range, and is banded
# against the other months'.
pr = flightvalue.build("US", {"countries": rows}, today=REC_DAY,
                       lookup=fake_lookup(CURVES), needs_fetch=lambda o, c: False)
jp = pr["countries"]["JP"]
jp_rest = [v for k, v in CURVES["JP"].items() if k in set(W(REC_DAY)) and k != "2026-09"]
results.append(ok(pr["partial"] == "2026-09" and jp["curve"]["2026-09"] == [1086, "JPX"]
                  and jp["n_months"] == 9 and jp["n_curve"] == 10 and {k: jp[k] for k in ("median", "lo", "hi")}
                  == {k: S(jp_rest)[k] for k in ("median", "lo", "hi")},
                  "Sep 26: Japan keeps its Sep fare in the curve (n_curve 10); the range is the other 9 months"))
results.append(ok(b(1086, jp) == "high" and C["JP"]["hi"] > jp["hi"],
                  "...and September is banded against them (High; its own fare no longer widens the range)"))
mar = pr["countries"]["MA"]
results.append(ok(mar["curve"]["2026-09"] == [731, "MAX"] and mar["n_months"] == mar["n_curve"] == 6
                  and {k: mar[k] for k in ("median", "lo", "hi")} == {k: ma[k] for k in ("median", "lo", "hi")},
                  "Sep 26: Morocco has only 5 other months, so September stays in and it keeps its range"))
results.append(ok(b(498, mar) == "low" and round(flightvalue.deviation(498, mar) * 100) == -22,
                  "...and October still reads Low, -22%, in September's last days"))

# unfetched city -> pending, and counted for the warmer
p2 = flightvalue.build("US", {"countries": rows}, today=MID_DAY, lookup=fake_lookup(CURVES, missing={"GRX"}),
                       needs_fetch=lambda o, c: c == "GRX")
results.append(ok(p2["countries"]["GR"] == {"pending": True} and p2["ready"] == 5 and p2["refresh"] == 1,
                  "a never-fetched city makes its country pending (ready 5/6, refresh 1)"))
p2b = flightvalue.build("US", {"countries": rows}, today=MID_DAY, lookup=fake_lookup(CURVES, missing={"GRX"}),
                        needs_fetch=lambda o, c: False)
results.append(ok(p2b["countries"]["GR"] == {"pending": True} and p2b["refresh"] == 0,
                  "a failed city inside its retry wait: pending, but no pass started for nothing"))
# a city skipped by the >=10-month early stop is never needed
p3 = flightvalue.build("US", {"countries": rows}, today=MID_DAY, lookup=fake_lookup(CURVES, missing={"TRY"}),
                       needs_fetch=lambda o, c: c == "TRY")
results.append(ok(p3["countries"]["TR"].get("n_months") == 12 and p3["refresh"] == 0,
                  "Turkey's first city covers the year, so its unfetched second city isn't waited on"))

# latest-prices row months FILL the curve's gaps; a route-curve month is never replaced
extra = {"IS": {"months": {"2026-11": {"price": 450, "dest": "ISZ"}, "2027-02": {"price": 470, "dest": "ISZ"},
                           "2026-10": {"price": 520, "dest": "ISZ"}, "2026-12": {"price": 300, "dest": "ISZ"}}}}
p4 = flightvalue.build("US", {"countries": rows_for(CURVES, extra)}, today=MID_DAY,
                       lookup=fake_lookup(CURVES), needs_fetch=lambda o, c: False)
isc = p4["countries"]["IS"]
results.append(ok(isc["n_months"] == 6 and isc["curve"]["2026-11"] == [450, "ISZ"]
                  and isc["curve"]["2027-02"] == [470, "ISZ"] and "median" in isc,
                  "Iceland + row months: the two missing months (Nov, Feb) filled -> 6 months, banded"))
results.append(ok(isc["curve"]["2026-10"] == [505, "ISX"] and isc["curve"]["2026-12"] == [381, "ISX"],
                  "a route-curve month keeps its fare, even against a cheaper row fare (Dec 381, not 300)"))

# --- fake upstream --------------------------------------------------------------
UP = {"monthly": [], "latest": 0, "fail_monthly": False, "fail_latest": False, "fail_dest": set()}
TODAY = datetime.date.today()
WIN = flightvalue.window_months()
d = lambda days: (TODAY + datetime.timedelta(days=days)).isoformat()
CITY_META = [{"code": c, "name": c, "country_code": iso} for iso, cs in
             {"MA": ["CMN", "RAK", "FEZ"], "GR": ["ATH"], "TR": ["IST"], "NO": ["OSL"], "US": ["NYC"],
              "ES": ["AGP", "BCN", "MAD", "VLC"], "PS": ["PST"], "SX": ["STL"],
              "RR": ["RCA", "RCB", "RCC", "RCD"]}.items() for c in cs]
# 20 one-city countries for the warmer's stall test (XA..XT, cities CAZ..CTZ)
STALL = [("X" + chr(65 + i), "C" + chr(65 + i) + "Z") for i in range(20)]
CITY_META += [{"code": c, "name": c, "country_code": iso} for iso, c in STALL]
ROWS = [
    {"destination": "CMN", "value": 700, "depart_date": d(20), "found_at": d(-3) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "RAK", "value": 640, "depart_date": d(21), "found_at": d(-2) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "RAK", "value": 300, "depart_date": d(-5), "found_at": d(-9) + "T10:00:00Z", "number_of_changes": 0},
    {"destination": "CMN", "value": 350, "depart_date": d(60), "found_at": d(-200) + "T10:00:00Z", "number_of_changes": 0},
    {"destination": "ATH", "value": 610, "depart_date": d(70), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "IST", "value": 690, "depart_date": d(40), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 1},
    {"destination": "OSL", "value": 437, "depart_date": d(130), "found_at": d(-1) + "T10:00:00Z", "number_of_changes": 0},
]
# Upstream monthly curves, shifted onto the live window so the test doesn't
# rot as the calendar moves: CURVES[iso] month i -> WIN[i + 1]. The current
# month is left empty, so whether it's in the stats (late in a month or not)
# never changes these assertions.
def shifted(iso):
    ks = sorted(CURVES[iso])
    return {WIN[i + 1]: CURVES[iso][k] for i, k in enumerate(ks) if i < 11}


MONTHLY = {"CMN": shifted("MA"), "ATH": shifted("GR"), "IST": shifted("TR"), "OSL": {WIN[4]: 437}, "RAK": {},
           "FEZ": {WIN[11]: 777}, "STL": {WIN[1]: 500},
           "PST": {WIN[0]: 300, WIN[1]: 410, WIN[2]: 420}}
MONTHLY.update({c: {WIN[i + 1]: 400 + 10 * i for i in range(6)} for _, c in STALL})
DEPART = {("PST", WIN[0]): d(-1) + "T08:00:00+03:00", ("PST", WIN[1]): d(0) + "T23:00:00Z"}


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
        dest = q["destination"]
        UP["monthly"].append(dest)
        if UP["fail_monthly"] or dest in UP["fail_dest"]:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return {"data": {k: {"price": v, "transfers": 1, "departure_at": DEPART.get((dest, k))}
                         for k, v in MONTHLY.get(dest, {}).items()}}
    raise AssertionError("unexpected upstream call " + url)


rates.fetch_json = fake_fetch
flights._cities = None

# --- get_flights: the per-country month curve from latest-prices rows ----------
fl = flights.get_flights("US")
ma_row = next(r for r in fl["countries"] if r["iso"] == "MA")
exp = {}
for city, price, days in (("CMN", 700, 20), ("RAK", 640, 21)):   # the two live, fresh rows
    k = d(days)[:7]
    if k not in exp or price < exp[k][0]:
        exp[k] = (price, city)
got = {k: (v["price"], v["dest"]) for k, v in ma_row["months"].items()}
results.append(ok(got == exp, "row months: cheapest per departure month + its city -> %s" % got))
results.append(ok(all(v["departure_at"] in (d(20), d(21)) for v in ma_row["months"].values()),
                  "row months keep their departure date (dropped on read once it has passed)"))
results.append(ok(not any(v["price"] in (300, 350) for v in ma_row["months"].values()),
                  "row months skip a departure already flown and a fare older than 90 days"))
results.append(ok(fl["by_country"]["MA"] == 547 and ma_row["min"] == 300,
                  "the average and cheapest (Top Picks inputs) are computed exactly as before"))

# A country's top cities: count, then city code — never price order, which
# reshuffled ties on every hourly refresh.
tie = [{"destination": c, "value": v, "depart_date": d(30), "found_at": d(-1) + "T10:00:00Z"}
       for c, v in (("MAD", 500), ("BCN", 480), ("AGP", 470), ("VLC", 300))]
saved_rows = ROWS[:]
ROWS[:] = tie
es1 = next(r for r in flights.get_flights("US")["countries"] if r["iso"] == "ES")["cities"]
ROWS[:] = tie[::-1]
es2 = next(r for r in flights.get_flights("US")["countries"] if r["iso"] == "ES")["cities"]
# Flight time + stops: the most DIRECT cached trip, one way — not the cheapest
# (a cheap 2-stop routing with a two-day layover). "duration" is the whole
# round trip, so it is halved; an impossibly fast row is ignored.
ROWS[:] = [
    {"destination": "MAD", "value": 290, "depart_date": d(30), "return_date": d(37), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 2, "duration": 2850},
    {"destination": "BCN", "value": 610, "depart_date": d(31), "return_date": d(38), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 0, "duration": 900},
    {"destination": "MAD", "value": 650, "depart_date": d(32), "return_date": d(39), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 0, "duration": 860},
    {"destination": "AGP", "value": 700, "depart_date": d(33), "return_date": d(40), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 0, "duration": 120, "distance": 6000},
]
es = next(r for r in flights.get_flights("US")["countries"] if r["iso"] == "ES")
ROWS[:] = saved_rows
results.append(ok(es["stops"] == 0 and es["dur"] == 430 and es["min"] == 290 and es["dest"] == "MAD"
                  and es["dur_city"] == "MAD",
                  "flight time/stops = the most direct trip, one way (not the cheapest's) -> %s/%s to %s"
                  % (es["stops"], es["dur"], es["dur_city"])))
# A row whose time is impossible says nothing about its stops either: it must
# not claim "nonstop" and blank the real 1-stop time.
ROWS[:] = [
    {"destination": "AGP", "value": 700, "depart_date": d(33), "return_date": d(40), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 0, "duration": 120, "distance": 6000},
    {"destination": "BCN", "value": 610, "depart_date": d(31), "return_date": d(38), "found_at": d(-1) + "T10:00:00Z",
     "number_of_changes": 1, "duration": 1400},
]
es = next(r for r in flights.get_flights("US")["countries"] if r["iso"] == "ES")
ROWS[:] = saved_rows
results.append(ok(es["stops"] == 1 and es["dur"] == 700 and es["dur_city"] == "BCN",
                  "an impossibly fast row doesn't set the stops -> %s/%s" % (es["stops"], es["dur"])))
results.append(ok(es1 == es2 == ["VLC", "AGP", "BCN"],
                  "tied cities break on the code, whatever the row order (cheapest city first) -> %s / %s" % (es1, es2)))

# --- the monthly-curve cache ------------------------------------------------------
KEY = lambda c: flights._route_key("US", c)
pst = flights.get_monthly("US", "PST")
results.append(ok(set(pst["months"]) == {WIN[1], WIN[2]} and pst["months"][WIN[1]]["price"] == 410,
                  "a fare departing yesterday is dropped; today's and an undated one stay"))
results.append(ok(flights.get_monthly("US", "PST")["months"] == pst["months"]
                  and flights.monthly_cached("US", "PST")["months"] == pst["months"]
                  and WIN[0] in flights._monthly_cache[KEY("PST")][2]["months"],
                  "...on every read (cache hit, cache-only lookup), from a cache that keeps the raw curve"))
prow = {"iso": "PS", "cities": ["PST"],
        "months": {WIN[1]: {"price": 50, "dest": "PST", "departure_at": d(40)},
                   WIN[3]: {"price": 100, "dest": "PST", "departure_at": d(-2)},
                   WIN[4]: {"price": 200, "dest": "PST", "departure_at": d(100)}}}
pc = flights.get_country_monthly("US", prow)
results.append(ok(pc["months"][WIN[1]]["price"] == 410 and WIN[3] not in pc["months"]
                  and pc["months"][WIN[4]]["price"] == 200,
                  "country curve: row months fill gaps only, and a past row departure doesn't fill"))

# 36h stale cap, on the real fetch time
stl = flights.get_monthly("US", "STL")
k = KEY("STL")
now = time.time()
flights._monthly_cache[k] = (now - 20 * 3600, now - 20 * 3600) + flights._monthly_cache[k][2:]
UP["fail_monthly"] = True
st1 = flights.get_monthly("US", "STL")
results.append(ok(st1.get("stale") and st1["months"] == stl["months"]
                  and abs(flights._monthly_cache[k][1] - (now - 20 * 3600)) < 1,
                  "refresh fails at 20h: the old curve is served stale, its fetch time untouched"))
flights._monthly_cache[k] = (now - 6 * 60, now - 37 * 3600) + flights._monthly_cache[k][2:]
results.append(ok(flights.monthly_cached("US", "STL") is None and flights.monthly_needs_fetch("US", "STL"),
                  "37h after its real fetch the curve is gone, pruned or not"))
st2 = flights.get_monthly("US", "STL")
results.append(ok(st2.get("error") and st2["months"] == {} and not st2.get("stale"),
                  "...and a failing refresh then answers an error, not a 37-hour-old curve"))
UP["fail_monthly"] = False

# A failed lookup is "not fetched" for the Flights tab, never "no fares"
results.append(ok(flights.monthly_cached("US", "STL") is None and not flights.monthly_needs_fetch("US", "STL")
                  and flights.monthly_failed("US", "STL"),
                  "a failed route: no curve (pending), not due a retry for 5 min, marked failed"))
srow = [{"iso": "SX", "cities": ["STL"], "n": 1}]
pf = flightvalue.build("US", {"countries": srow})
results.append(ok(pf["countries"]["SX"] == {"pending": True} and pf["ready"] == 0 and pf["refresh"] == 0,
                  "build(): its country is pending, not {'curve': {}, 'n_months': 0}"))
e = flights._monthly_cache[k]
flights._monthly_cache[k] = (e[0] - flights.MONTHLY_FAIL_TTL - 1,) + e[1:]
results.append(ok(flightvalue.build("US", {"countries": srow})["refresh"] == 1,
                  "...and counts for the warmer once its retry is due"))

# Prune race: two threads pruning the same expired keys used to KeyError on
# the second `del`, losing the fresh curve (or dropping a request).
def race(n_threads, target):
    errs, gate = [], threading.Barrier(n_threads)

    def run(i):
        gate.wait()
        try:
            target(i)
        except Exception as ex:
            errs.append(repr(ex))
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return errs


errs = []
for _ in range(3):
    old = time.time() - 40 * 3600
    flights._monthly_cache.update({("NYC", "Z%06d" % i, "usd"): (old, old, {"months": {}}, False)
                                   for i in range(150000)})
    for c in ("RCA", "RCB", "RCC", "RCD"):
        flights._monthly_cache.pop(KEY(c), None)
    errs += race(4, lambda i: flights.get_monthly("US", "RC" + "ABCD"[i]))
results.append(ok(not errs and all(KEY(c) in flights._monthly_cache for c in ("RCA", "RCB", "RCC", "RCD"))
                  and not any(k[1].startswith("Z") for k in flights._monthly_cache),
                  "concurrent prunes of 150k expired curves: no KeyError, every fresh curve kept %s" % errs[:2]))

import server
cache, errs = {}, []
for _ in range(3):
    old = time.time() - 1000
    cache.update({("z", i): (old, None) for i in range(150000)})
    for i in range(4):
        cache.pop(i, None)
    errs += race(4, lambda i: server._cached("t", cache, i, 10, lambda: i, stale_max=100))
results.append(ok(not errs and all(cache.get(i, (0, None))[1] == i for i in range(4)) and len(cache) == 4,
                  "server._cached: the same concurrent prune, no KeyError %s" % errs[:2]))

# --- HTTP: /api/flight-value and the guide's /api/flight-months ---------------
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


def wait_warm(origin="US", secs=15):
    deadline = time.time() + secs
    while flightvalue.is_warming(origin) and time.time() < deadline:
        time.sleep(0.05)


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
wait_warm()
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
st, _, zz = get("/api/flights?origin=ZZ")
results.append(ok(st == 200 and zz.get("error") and "ZZ" not in server._flights_cache,
                  "/api/flights for an unsupported origin: its error answer, never cached"))

# City churn: the hourly fares refresh brings a new city into Morocco's top
# three after a finished pass. It is fetched on the next request — no cooldown.
UP["monthly"].clear()
for r in server._flights_cache["US"][1]["countries"]:
    if r["iso"] == "MA":
        r["cities"] = r["cities"][:2] + ["FEZ"]
st, hd, ch = get("/api/flight-value?origin=US")
results.append(ok(ch["countries"]["MA"] == {"pending": True} and ch["filling"] and hd.get("Cache-Control") == "no-store",
                  "new city after a finished pass: Morocco pending, filling=true, no-store"))
wait_warm()
st, _, ch2 = get("/api/flight-value?origin=US")
results.append(ok(UP["monthly"] == ["FEZ"] and ch2["ready"] == 4 and ch2["countries"]["MA"]["curve"].get(WIN[11]) == [777, "FEZ"],
                  "...fetched at once (only FEZ called), Morocco back with FEZ's month"))

# Stale-on-error: fares expired + upstream down -> last good copy, still 200,
# for the value endpoint AND the Flights table's own /api/flights.
ts, payload = server._flights_cache["US"]
server._flights_cache["US"] = (ts - server.FLIGHTS_TTL - 5, payload)
server._upstream_fail.clear()
UP["fail_latest"] = True
st, _, stale = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and stale["ready"] == 4, "fares refresh fails -> flight-value served from the stale copy"))
st, _, fstale = get("/api/flights?origin=US")
results.append(ok(st == 200 and fstale.get("stale") and len(fstale["countries"]) == 4
                  and all("months" not in r for r in fstale["countries"]),
                  "fares refresh fails -> /api/flights serves the same stale copy (was a 500)"))
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
wait_warm()
results.append(ok(len(UP["monthly"]) == flightvalue.MAX_FAILS,
                  "429s: the pass stops after %d failed calls (made %d)" % (flightvalue.MAX_FAILS, len(UP["monthly"]))))
st, hd, bd = get("/api/flight-value?origin=US")
results.append(ok(not bd["filling"] and len(UP["monthly"]) == flightvalue.MAX_FAILS,
                  "within the cooldown after an ABORTED pass a request doesn't restart it (filling=false)"))
results.append(ok(bd["ready"] < bd["total"] and hd.get("Cache-Control") == "no-store",
                  "incomplete but not filling (ready %d/%d): still no-store" % (bd["ready"], bd["total"])))
results.append(ok(all(v == {"pending": True} for v in bd["countries"].values()),
                  "failed lookups read pending, not 'no fares cached'"))
UP["fail_monthly"] = False

# --- the warmer: failures in a row can't stall the rest --------------------------
# 20 one-city countries, busiest first; the 6th-10th busiest always fail.
flightvalue.PACE = 0.01
flights._monthly_cache.clear()
flightvalue._warm_done.clear()
UP["monthly"].clear()
UP["fail_dest"] = {c for _, c in STALL[5:10]}
srows = [{"iso": iso, "cities": [c], "n": 100 - i} for i, (iso, c) in enumerate(STALL)]
aborted1 = flightvalue._warm_pass("US", srows)
calls1 = UP["monthly"][:]
for c in UP["fail_dest"]:     # the cooldown has passed; each failure is due a retry
    e = flights._monthly_cache[KEY(c)]
    flights._monthly_cache[KEY(c)] = (e[0] - flights.MONTHLY_FAIL_TTL - 1,) + e[1:]
UP["monthly"].clear()
aborted2 = flightvalue._warm_pass("US", srows)
calls2 = UP["monthly"][:]
sp = flightvalue.build("US", {"countries": srows})["countries"]
results.append(ok(aborted1 and calls1 == [c for _, c in STALL[:10]],
                  "pass 1: 5 good routes, then 5 fresh failures in a row abort it"))
results.append(ok(calls2 == [c for _, c in STALL[10:]] + [c for _, c in STALL[5:10]],
                  "pass 2: the 10 never-reached routes go first, the failing ones last -> %s" % ",".join(calls2[:3])))
results.append(ok(all("median" in sp[iso] for iso, _ in STALL[:5] + STALL[10:])
                  and all(sp[iso] == {"pending": True} for iso, _ in STALL[5:10]),
                  "every country but the 5 failing ones is banded; those 5 read pending"))
results.append(ok(not aborted2, "pass 2 isn't 'aborted': its failures were all on routes already known to fail"))
UP["fail_dest"] = set()

# 6 routes that always fail (one more than MAX_FAILS) behind 6 good ones. Pass
# 1 can't tell them from a storm and aborts; from then on they fail without
# counting, so later passes finish and a city that churns into a country's
# top three is fetched on the next request — no 10-minute cooldown.
flights._monthly_cache.clear()
flightvalue._warm_done.clear()
UP["monthly"].clear()
dead = [c for _, c in STALL[6:12]]
UP["fail_dest"] = set(dead)
drows = [{"iso": iso, "cities": [c], "n": 100 - i} for i, (iso, c) in enumerate(STALL[:12])]


def due_retry(cities):
    for c in cities:
        e = flights._monthly_cache.get(KEY(c))
        if e:
            flights._monthly_cache[KEY(c)] = (e[0] - flights.MONTHLY_FAIL_TTL - 1,) + e[1:]


def warm_now(rows):
    flightvalue._warming["US"] = time.monotonic()
    flightvalue._warm("US", rows)
    return flightvalue._warm_done["US"][1]


ab1 = warm_now(drows)
calls1 = UP["monthly"][:]
due_retry(dead)
UP["monthly"].clear()
ab2 = warm_now(drows)
calls2 = UP["monthly"][:]
results.append(ok(ab1 and calls1 == [c for _, c in STALL[:11]],
                  "6 dead routes, pass 1: 6 good calls, then 5 fresh failures abort it"))
results.append(ok(not ab2 and calls2 == [dead[-1]] + dead[:-1],
                  "pass 2: the never-tried 6th dead route counts (1), the 5 known-dead don't -> finished, not aborted"))
drows[0]["cities"] = [STALL[0][1], "FEZ"]      # a new city joins the busiest country
UP["monthly"].clear()
state = flightvalue.start_warm("US", drows)
wait_warm()
results.append(ok(state == "running" and UP["monthly"] == ["FEZ"],
                  "...so a city that churns in after pass 2 is fetched on the next request -> %s %s"
                  % (state, UP["monthly"])))
# The same dead routes can't hide a real storm: with every route failing,
# fresh routes (tried first) still abort the pass after MAX_FAILS of them.
flightvalue._warm_done.clear()
due_retry(dead)
UP["monthly"].clear()
UP["fail_monthly"] = True
fresh = [{"iso": iso, "cities": [c], "n": 50 - i} for i, (iso, c) in enumerate(STALL[12:20])]
ab3 = warm_now(drows[6:] + fresh)
results.append(ok(ab3 and UP["monthly"] == [c for _, c in STALL[12:17]],
                  "a storm on fresh routes still aborts after %d calls, before the known-dead tail -> %s"
                  % (flightvalue.MAX_FAILS, ",".join(UP["monthly"]))))
# ...and once EVERY route is known-bad (a revoked token, a dead endpoint), the
# known-bad cap still ends each pass: bounded calls, recorded aborted, so the
# cooldown applies instead of full passes against a dead API every few minutes.
flights._monthly_cache.clear()
flightvalue._warm_done.clear()
allrows = [{"iso": iso, "cities": [c], "n": 100 - i} for i, (iso, c) in enumerate(STALL)]
allc = [c for _, c in STALL]
passes = []
for _ in range(8):
    due_retry(allc)
    UP["monthly"].clear()
    passes.append((warm_now(allrows), len(UP["monthly"])))
results.append(ok(all(ab for ab, _ in passes) and max(n for _, n in passes) <= flightvalue.MAX_KNOWN_BAD
                  and passes[-1][1] == flightvalue.MAX_KNOWN_BAD,
                  "every route dead, 8 passes: each aborts, never more than %d calls -> %s"
                  % (flightvalue.MAX_KNOWN_BAD, [n for _, n in passes])))
UP["fail_monthly"] = False
# "In a row": a good answer resets the count, so scattered fresh failures
# (every other route here, MAX_FAILS of them) never end a pass.
flights._monthly_cache.clear()
flightvalue._warm_done.clear()
UP["monthly"].clear()
UP["fail_dest"] = {c for _, c in STALL[1:11:2]}
alt = [{"iso": iso, "cities": [c], "n": 100 - i} for i, (iso, c) in enumerate(STALL[:10])]
ab4 = warm_now(alt)
results.append(ok(not ab4 and UP["monthly"] == [c for _, c in STALL[:10]],
                  "%d fresh failures, each after a good answer: not 'in a row', the pass finishes"
                  % len(UP["fail_dest"])))
UP["fail_dest"] = set()

# --- the warmer: at most 2 origins at once, one slot kept for the default ---------
release = threading.Event()
real_pass = flightvalue._warm_pass
flightvalue._warm_pass = lambda o, rows: release.wait(10) and False
flightvalue._warm_done.clear()
s_de = flightvalue.start_warm("DE", [])
s_fr = flightvalue.start_warm("FR", [])
s_us = flightvalue.start_warm("US", [])
s_gb = flightvalue.start_warm("GB", [])
results.append(ok((s_de, s_fr, s_us, s_gb) == ("running", "queued", "running", "queued")
                  and sorted(flightvalue._warming) == ["DE", "US"],
                  "DE runs, FR queues (slot kept for US), US runs, GB queues -> %s" % [s_de, s_fr, s_us, s_gb]))
st, hd, fr = get("/api/flight-value?origin=FR")
results.append(ok(st == 200 and fr["filling"] and fr["ready"] == 0 and hd.get("Cache-Control") == "no-store"
                  and "FR" not in flightvalue._warming,
                  "a queued origin answers filling=true (its next poll starts it), no-store"))
release.set()
for o in ("DE", "US"):
    wait_warm(o)
results.append(ok(flightvalue.start_warm("FR", []) == "running", "a freed slot goes to the next origin that asks"))
wait_warm("FR")
flightvalue._warm_pass = real_pass

# --- the pacer: the default origin first; monotonic -------------------------------
flightvalue.PACE = 0.3
flightvalue._pace()                      # a slot just went: the next is 0.3s away
order = []
t_other = threading.Thread(target=lambda: (flightvalue._pace(False), order.append(("other", time.monotonic()))))
t_first = threading.Thread(target=lambda: (flightvalue._pace(True), order.append(("default", time.monotonic()))))
t_other.start()
time.sleep(0.05)
t_first.start()
t_other.join(3)
t_first.join(3)
results.append(ok([o for o, _ in order] == ["default", "other"] and order[1][1] - order[0][1] >= 0.25,
                  "the default origin, arriving second, takes the next slot; the other waits one PACE"))
# The same rule without the wake-up race: an open slot is not taken by
# another origin while a default-origin warmer is waiting for it.
with flightvalue._pace_cv:
    flightvalue._pace_next[0] = 0.0
    flightvalue._pace_first[0] += 1          # a default-origin warmer is at the gate
t_other = threading.Thread(target=flightvalue._pace)
t_other.start()
t_other.join(0.4)
held = t_other.is_alive()
with flightvalue._pace_cv:
    flightvalue._pace_first[0] -= 1
    flightvalue._pace_cv.notify_all()
t_other.join(2)
results.append(ok(held and not t_other.is_alive(),
                  "an open slot waits for the default origin's warmer; the other takes it once none waits"))
flightvalue.PACE = 0.05
flightvalue._pace()
real_time = time.time
time.time = lambda: real_time() - 3600  # the wall clock steps back an hour
t = threading.Thread(target=flightvalue._pace)
t.start()
t.join(2)
time.time = real_time
results.append(ok(not t.is_alive(), "pacing is monotonic: a wall clock stepping back doesn't stall the gate"))

# No token: a sane empty answer, never an upstream call.
os.environ.pop("TRAVELPAYOUTS_TOKEN")
server._flights_cache.clear()
n_before = len(UP["monthly"]) + UP["latest"]
st, _, bd = get("/api/flight-value?origin=US")
results.append(ok(st == 200 and bd["configured"] is False and bd["countries"] == {} and not bd["filling"]
                  and len(UP["monthly"]) + UP["latest"] == n_before,
                  "no token: configured=false, empty, no upstream call"))
st, _, bd = get("/api/flights?origin=US")
results.append(ok(st == 200 and bd["configured"] is False and "US" not in server._flights_cache
                  and len(UP["monthly"]) + UP["latest"] == n_before,
                  "no token: /api/flights says not configured, caches nothing"))
httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

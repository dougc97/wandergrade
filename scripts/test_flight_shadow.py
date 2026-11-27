"""The log-only fare-source comparison (fxtracker/flightshadow.py): today's
/v1/prices/monthly curves against Travelpayouts' grouped_prices. Covers the
mapping of grouped_prices answers (recorded on the Oct 26 spike), the
comparison math, the scheduling guards, Upstash writes and expiry through an
in-process mock, /api/flight-shadow's shape, the report script, and that
/api/flight-value and the server's other fare outputs are byte-identical with
the comparison on or off.

No real Travelpayouts key and no network: the token is a dummy, the live
source is a fake rates.fetch_json, grouped_prices is a fake
flightshadow._fetch, and Upstash is scripts/mock_upstash.py on a free port.

    /usr/bin/python3 scripts/test_flight_shadow.py
"""
import contextlib, datetime, gzip, io, json, os, re, shutil, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

TOKEN = "dummyTok0123456789abcdefNEVERSENT"   # never leaves this process
os.environ["TRAVELPAYOUTS_TOKEN"] = TOKEN
for k in ("RENDER", "FLIGHT_SHADOW", "FLIGHT_SHADOW_UNTIL", "FLIGHT_SHADOW_DELAY", "RESEND_API_KEY",
          "BASIC_AUTH_USER", "BASIC_AUTH_PASS"):
    os.environ.pop(k, None)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import mock_upstash  # noqa: E402

mock = HTTPServer(("127.0.0.1", 0), mock_upstash.H)
threading.Thread(target=mock.serve_forever, daemon=True).start()
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % mock.server_address[1]
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock-not-a-secret"

from fxtracker import accounts, flights, flightshadow as fs, flightvalue, rates  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
TODAY = datetime.date.today()
WIN = flightvalue.window_months(TODAY)
DAY = time.strftime("%Y-%m-%d", time.gmtime())


def kv(*cmd):
    return accounts._redis(*cmd)


# --- the recorded spike answers, shifted onto today's window ---------------------
FIX = json.load(open(os.path.join(HERE, "fixtures", "flight_shadow_2026-10-26.json"), encoding="utf-8"))


def shift_key(k):
    i = (int(k[:4]) - 2026) * 12 + int(k[5:7]) - 10     # recorded window starts 2026-10
    return WIN[i] if 0 <= i < 12 else None


def shift_dep(nk, dep):
    if not dep:
        return dep
    if nk == WIN[0]:                       # this month: today, never "already flown"
        return TODAY.isoformat() + dep[10:]
    return "%s-%02d%s" % (nk, min(int(dep[8:10]), 28), dep[10:])


def shifted(rows):
    out = {}
    for k, v in rows.items():
        nk = shift_key(k)
        if nk:
            out[nk] = dict(v, departure_at=shift_dep(nk, v.get("departure_at")))
    return out


ISO = {c: r["iso"] for c, r in FIX["routes"].items()}
MONTHLY = {c: shifted(r["M"]) for c, r in FIX["routes"].items()}       # live v1 answers
GROUPED = {c: dict(r["G"], data=shifted(r["G"]["data"])) for c, r in FIX["routes"].items()}
# Extras: a second Spanish city on both sides (multi-city merge), Norway's
# live lookup failing (live pending), Greece's grouped answer success:false
# (rejected), Iceland's grouped call answering 429 (shadow pending).
ISO.update(BCN="ES", OSL="NO", ATH="GR")
MONTHLY["BCN"] = {WIN[8]: {"price": 610, "transfers": 1}, WIN[9]: {"price": 620, "transfers": 0}}
GROUPED["BCN"] = {"success": True, "data": {
    WIN[8]: {"price": 600, "transfers": 1, "return_transfers": 2, "return_at": "x", "departure_at": None},
    WIN[10]: {"price": 640, "transfers": 0, "return_transfers": 0, "return_at": "x"}}}
MONTHLY["ATH"] = {WIN[3]: {"price": 700, "transfers": 1}, WIN[4]: {"price": 720, "transfers": 1}}
GROUPED["OSL"] = {"success": True, "data": {WIN[2]: {"price": 450, "transfers": 0, "return_at": "x"},
                                            WIN[3]: {"price": 460, "transfers": 0, "return_at": "x"}}}
GROUPED["ATH"] = {"success": False, "data": {}}
GROUPED["REK"] = 429
LIVE_FAIL = {"OSL"}
CITY_META = [{"code": c, "name": c, "country_code": iso} for c, iso in ISO.items()] + \
            [{"code": "NYC", "name": "New York", "country_code": "US"}]
found = (TODAY - datetime.timedelta(days=2)).isoformat() + "T10:00:00Z"


def dep_in(k):
    return TODAY.isoformat() if k == WIN[0] else k + "-28"


def row(city, price, month):
    return {"origin": "NYC", "destination": city, "value": price, "found_at": found, "depart_date": dep_in(month),
            "return_date": dep_in(month), "number_of_changes": 1, "duration": 1000, "distance": 9000}


first = lambda c: sorted(MONTHLY[c])[0]
zrh_fill = next(k for k in reversed(WIN) if k not in MONTHLY["ZRH"] and k not in GROUPED["ZRH"]["data"])
ROWS = ([row("DXB", 500, first("DXB"))] * 3 + [row("LON", 400, first("LON"))] * 4
        + [row("MAD", 300, first("MAD"))] * 3 + [row("BCN", 350, WIN[8])] * 2 + [row("TBS", 600, first("TBS"))]
        + [row("CAI", 700, first("CAI"))] * 2 + [row("PAR", 450, first("PAR"))] * 3
        + [row("BUD", 520, first("BUD")), row("ZRH", 555, zrh_fill), row("REK", 380, first("REK")),
           row("OSL", 437, WIN[2]), row("ATH", 610, WIN[3])])

UP = {"monthly": [], "latest": 0}


def fake_fetch(url, retries=3):
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    if "/data/en/cities.json" in url:
        return CITY_META
    if "get_latest_prices" in url:
        UP["latest"] += 1
        return {"data": ROWS if q.get("page") == "1" else []}
    if "/v1/prices/monthly" in url:
        UP["monthly"].append(q["destination"])
        if q["destination"] in LIVE_FAIL:
            raise urllib.error.HTTPError("x", 429, "Too Many Requests", {}, None)
        return {"success": True, "data": json.loads(json.dumps(MONTHLY.get(q["destination"], {})))}
    raise AssertionError("unexpected upstream call")


CLOCK = [1000.0]
SLEEPS = []
GCALLS = []     # (fake clock, query) per grouped call


def fake_sleep(s):
    SLEEPS.append(s)
    CLOCK[0] += s


def fake_gfetch(url):
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query))
    assert (u.scheme, u.netloc, u.path) == ("https", "api.travelpayouts.com", "/aviasales/v3/grouped_prices"), url
    GCALLS.append((CLOCK[0], q))
    ans = GROUPED.get(q["destination"], {"success": True, "data": {}})
    if isinstance(ans, int):
        return ans, None, 90
    return 200, json.loads(json.dumps(ans)), 150 + 10 * (len(GCALLS) % 7)


REAL_FETCH = fs._fetch
rates.fetch_json = fake_fetch
fs._fetch = fake_gfetch
fs._sleep = fake_sleep
fs._clock = lambda: CLOCK[0]
flights._cities = None
flightvalue.PACE = 0.0

# --- 1. grouped_prices answers ----------------------------------------------------
dxb = FIX["routes"]["DXB"]["G"]
m, ow = fs.months_of(dxb)
results.append(ok(sorted(m) == sorted(k[:7] for k in dxb["data"]) and ow == 0
                  and all(set(v) == {"price", "stops", "departure_at"} for v in m.values()),
                  "a recorded round-trip answer (DXB, 1-60 days): every month kept, keyed YYYY-MM"))
k0 = sorted(dxb["data"])[0]
r0 = dxb["data"][k0]
results.append(ok(m[k0[:7]]["price"] == round(r0["price"])
                  and m[k0[:7]]["stops"] == max(r0["transfers"], r0["return_transfers"]),
                  "price rounded; stops = the larger leg (max(transfers, return_transfers)), as today's source"))
mo, owo = fs.months_of(FIX["oneway_DXB"])
results.append(ok(mo == {} and owo == len(FIX["oneway_DXB"]["data"]) > 0,
                  "an answer with no trip length (one-way rows, no return date): no fares, %d one-way rows counted"
                  % owo))
results.append(ok(fs.months_of({"success": False, "data": {}}) == (None, 0) and fs.months_of(None) == (None, 0)
                  and fs.months_of({"success": True, "data": []}) == (None, 0),
                  "success:false, no body, or data not a month map: not an answer (None)"))
results.append(ok(fs.months_of({"success": True, "data": {"2027-01": {"price": 512.6, "transfers": 1,
                                                                      "return_at": "y"}}})[0]
                  == {"2027-01": {"price": 513, "stops": 1, "departure_at": None}},
                  "no return_transfers: stops = transfers"))
results.append(ok(fs.PARAMS == {"group_by": "month", "currency": "usd", "market": "us",
                                "min_trip_duration": "1", "max_trip_duration": "60"}
                  and FIX["params"] == fs.PARAMS,
                  "asks exactly the settings the spike found comparable (market us, 1-60 day trips)"))

# --- 2. the comparison math on hand-made curves -----------------------------------
L = {"AAA": {WIN[1]: 100, WIN[2]: 200, WIN[3]: 300},
     "BBB": {WIN[i]: p for i, p in zip(range(1, 9), (500, 510, 520, 530, 540, 550, 560, 900))},
     "DDD": {WIN[2]: 300}, "FFA": {WIN[1]: 50, WIN[2]: 60, WIN[3]: 70}, "FFB": {WIN[6]: 90, WIN[7]: 95}}
G = {"AAA": {WIN[1]: 100, WIN[2]: 205, WIN[4]: 400},
     "BBB": {WIN[i]: p for i, p in zip(range(1, 9), (400, 480, 520, 530, 540, 550, 560, 900))},
     "CCC": {WIN[5]: 777}, "FFA": {WIN[1]: 50, WIN[2]: 66, WIN[3]: 70}, "FFB": {WIN[6]: 90}}
asked = []


def mk(src, missing=(), log=None):
    memo = {}

    def look(o, c, cur="usd"):
        if c in memo:
            return memo[c]
        if log is not None:
            log.append(c)
        out = None if c in missing or (c not in src and c in ("CCC", "DDD", "EEE")) else \
            {"configured": True, "months": {k: {"price": p, "stops": 1} for k, p in src.get(c, {}).items()}}
        memo[c] = out
        return out
    return look


mini = {"countries": [
    {"iso": "AA", "dest": "AAA", "cities": ["AAA"], "n": 9, "months": {WIN[5]: {"price": 500, "dest": "AAA"}}},
    {"iso": "BB", "dest": "BBB", "cities": ["BBB"], "n": 8},
    {"iso": "CC", "dest": "CCC", "cities": ["CCC"], "n": 7},   # live: never fetched (pending)
    {"iso": "DD", "dest": "DDD", "cities": ["DDD"], "n": 6},   # grouped: the call failed (pending)
    {"iso": "EE", "dest": "EEE", "cities": ["EEE"], "n": 5},   # both pending
    {"iso": "FF", "dest": "FFA", "cities": ["FFA", "FFB"], "n": 4}]}
c = fs.compare("US", mini, mk(G, missing={"DDD", "EEE"}, log=asked), live=mk(L, missing={"CCC", "EEE"}), today=TODAY)
a = c["agg"]
results.append(ok(a["ready"] == {"countries": 6, "live": 4, "shadow": 4, "both": 3, "pending_grouped": 1,
                                 "pending_live": 1},
                  "ready: 6 countries, live 4 (CC never fetched, EE), grouped 4 (DD failed, EE), both 3 -> %s"
                  % a["ready"]))
results.append(ok(asked == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFA", "FFB"],
                  "grouped asked each city once, the second city only where the first lacks 10 months -> %s" % asked))
aa = c["dest"]["AA"]["m"]
results.append(ok(aa == {WIN[1]: [100, 100, 1.0, "--", "rr"], WIN[2]: [200, 205, 1.025, "--", "rr"],
                         WIN[3]: [300, None, None, "--", "r-"], WIN[4]: [None, 400, None, "--", "-r"],
                         WIN[5]: [500, 500, 1.0, "--", "ff"]} and c["dest"]["AA"]["n"] == [4, 4],
                  "per destination-month: both prices, ratio, bands, and route vs latest-prices fill (AA)"))
rm = a["route_months"]
# routes: AAA BBB FFA FFB (CCC live missing, DDD/EEE grouped None)
exp_rm = dict(both=2 + 8 + 3 + 1, same=1 + 6 + 2 + 1, live_only=1 + 0 + 0 + 1, shadow_only=1)
results.append(ok({k: rm[k] for k in exp_rm} == exp_rm and rm["routes"] == 5 and rm["live_missing"] == 1,
                  "route months (same city, both sources): both 14, same 10, live-only 2, grouped-only 1; "
                  "5 routes, 1 never fetched live -> %s" % {k: rm[k] for k in exp_rm}))
results.append(ok(rm["shadow_cheaper"] == 2 and rm["live_cheaper"] == 2 and rm["within5"] == 1 + 6 + 2 + 1 + 1,
                  "differences: grouped cheaper 2 (BBB x2), dearer 2 (AAA +2.5%, FFA +10%); within 5%: 11"))
off = a["by_offset"]["route"]
results.append(ok(off[1] == [3, 2, 1, 0] and off[2] == [3, 0, 1, 2] and sum(x[0] for x in off) == rm["both"],
                  "by window month: next month 3 shared (2 same, 1 grouped cheaper), month 2: 0 same"))


def bands_of(prices):
    st = flightvalue.curve_stats(flightvalue.stats_prices(prices, flightvalue.partial_month(TODAY)))
    return {k: fs.BANDS[flightvalue.band(p, st)] for k, p in prices.items()}


lbb, sbb = bands_of(L["BBB"]), bands_of(G["BBB"])
bb = c["dest"]["BB"]
results.append(ok(bb["b"] == [1, 1] and all(bb["m"][k][3] == lbb[k] + sbb[k] for k in L["BBB"])
                  and any(lbb[k] != sbb[k] for k in L["BBB"]),
                  "BB (8 months): banded both sides, each month's Low/Typical/High as the Flights tab bands it, "
                  "with at least one disagreement -> %s" % {k[5:]: bb["m"][k][3] for k in sorted(bb["m"])}))
agree = sum(lbb[k] == sbb[k] for k in L["BBB"])
results.append(ok(a["banded"] == {"live": 1, "shadow": 1, "both": 1, "live_only": 0, "shadow_only": 0}
                  and a["bands"]["both"] == 8 and a["bands"]["agree"] == agree
                  and sum(a["bands"]["matrix"].values()) == 8,
                  "bands agree on %d of 8 months; matrix %s" % (agree, a["bands"]["matrix"])))
results.append(ok(c["dest"]["CC"]["n"] == [None, 1] and c["dest"]["DD"]["n"] == [1, None]
                  and c["dest"]["EE"] == {"n": [None, None]},
                  "pending sides read None (CC live, DD grouped, EE both)"))
results.append(ok(c["window"] == [WIN[0], WIN[-1]] and c["tab_month"] == (WIN[1] if TODAY.day > 15 else WIN[0]),
                  "the window and the Flights tab's own month (next month after the 15th)"))
results.append(ok(a["ready"]["pending_grouped"] == 1 and a["ready"]["pending_live"] == 1
                  and a["country_months"]["live_only"] == 1 + 0 + 1 and a["country_months"]["shadow_only"] == 1
                  and "m" not in c["dest"]["CC"] and "m" not in c["dest"]["DD"],
                  "a country with one side pending (CC, DD) is counted as pending, not as months one source lacks "
                  "-> ready %s, country months %s" % (a["ready"], a["country_months"])))
# A banded country whose grouped call failed (HTTP 429, a timeout, success:false):
# a switched server retries it within minutes, so it never reads "would lose its range".
same = {WIN[i]: p for i, p in zip(range(1, 9), (500, 510, 520, 530, 540, 550, 560, 900))}
two = {"countries": [{"iso": "PP", "dest": "PPP", "cities": ["PPP"], "n": 9},
                     {"iso": "QQ", "dest": "QQQ", "cities": ["QQQ"], "n": 8}]}
f1 = fs.compare("US", two, mk({"QQQ": same}, missing={"PPP"}), live=mk({"PPP": same, "QQQ": same}), today=TODAY)["agg"]
f2 = fs.compare("US", two, mk({"PPP": same, "QQQ": same}), live=mk({"QQQ": same}, missing={"PPP"}), today=TODAY)["agg"]
results.append(ok(f1["banded"] == {"live": 1, "shadow": 1, "both": 1, "live_only": 0, "shadow_only": 0}
                  and f1["country_months"]["live_only"] == 0 and f1["ready"]["pending_grouped"] == 1
                  and f1["bands"]["both"] == f1["bands"]["agree"] == 8,
                  "a banded country's grouped call failed: not 'would lose its range' (live_only 0), "
                  "counted as pending -> banded %s, ready %s" % (f1["banded"], f1["ready"])))
results.append(ok(f2["banded"]["shadow_only"] == 0 and f2["country_months"]["shadow_only"] == 0
                  and f2["ready"]["pending_live"] == 1 and f2["banded"]["both"] == 1,
                  "...and a country today's source has not fetched yet is not 'would gain it' -> banded %s"
                  % f2["banded"]))

# --- 3. the live side, filled the real way from the recorded v1 answers -----------
import server  # noqa: E402

server._flights_cache.clear()
flights._monthly_cache.clear()
fares = server._fares("US")
n_m0 = len(UP["monthly"])
flightvalue._warm("US", fares["countries"])
warm_calls = len(UP["monthly"]) - n_m0
ps = flightvalue.pass_stats("US")
results.append(ok(flightvalue.has_warmed("US") and ps["first"] is ps["last"] and ps["first"]["calls"] == warm_calls > 0
                  and set(ps["first"]) == {"secs", "calls", "ms", "aborted"}
                  and set(ps["first"]["ms"]) == {"median", "p95", "max"} and ps["first"]["aborted"] is False,
                  "the live fill records its warm-up as durations alone: %d upstream calls, timings, not aborted"
                  % warm_calls))
flightvalue._warm("US", fares["countries"])
ps2 = flightvalue.pass_stats("US")
results.append(ok(ps2["first"] == ps["first"] and ps2["last"] is not ps["first"] and ps2["last"]["calls"] == 0,
                  "a later pass is 'last' (0 calls: all cached); 'first' stays the warm-up after boot"))

# --- 4. byte-identical with the comparison on vs off ------------------------------
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def raw_get(path, headers=None, method="GET"):
    req = urllib.request.Request(BASE + path, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


isos = sorted(r["iso"] for r in fares["countries"])
PATHS = (["/api/flight-value?origin=US", "/api/flights?origin=US", "/api/flight-months?origin=US&dest=DXB"]
         + ["/api/flight-months?origin=US&iso=" + i for i in isos])


def reader_outputs():
    out = {p: raw_get(p, {"Accept-Encoding": "identity"}) for p in PATHS}
    out = {p: (s, h.get("Cache-Control"), b) for p, (s, h, b) in out.items()}
    f = server._cached_fares("US")
    out["_fv_build"] = json.dumps(server._fv_build(f), sort_keys=True)
    cf = server._cheap_fares()
    out["_cheap_fares"] = json.dumps([cf[1], cf[2]], sort_keys=True)
    out["_guide_fv"] = json.dumps({i: [server._guide_fv(i)[0], str(server._guide_fv(i)[1])] for i in isos},
                                  sort_keys=True)
    out["serve"] = json.dumps(flightvalue.serve("US", f), sort_keys=True)
    return out


before = reader_outputs()
ent_before = flights.monthly_entries()
fc_before = server._flights_cache["US"]
wd_before = dict(flightvalue._warm_done)
live_before = (len(UP["monthly"]), UP["latest"])
results.append(ok(all(v[0] == 200 for k, v in before.items() if k.startswith("/")) and len(before) == len(PATHS) + 4,
                  "baseline (comparison off): %d endpoints + 4 server-side fare outputs captured" % len(PATHS)))

# the scheduling guards, in order
fs._state.update(finished=False, tries={})
fs._days.clear()
results.append(ok(fs.enabled() == (False, "runs on Render only (FLIGHT_SHADOW=1 to test)")
                  and fs.start(server._cached_fares, busy=server._flight_shadow_busy) is False
                  and fs._state["state"] == "off",
                  "off unless on Render or FLIGHT_SHADOW=1: start() starts nothing"))
os.environ["FLIGHT_SHADOW"] = "0"
os.environ["RENDER"] = "1"
results.append(ok(fs.enabled()[0] is False and "FLIGHT_SHADOW=0" in fs.enabled()[1],
                  "FLIGHT_SHADOW=0 switches it off even on Render"))
os.environ.pop("RENDER")
os.environ["FLIGHT_SHADOW"] = "1"
results.append(ok(fs.enabled() == (True, ""), "FLIGHT_SHADOW=1 + token + storage: enabled"))
os.environ["TRAVELPAYOUTS_TOKEN"] = ""
e1 = fs.enabled()
os.environ["TRAVELPAYOUTS_TOKEN"] = TOKEN
u = os.environ.pop("UPSTASH_REDIS_REST_URL")
e2 = fs.enabled()
os.environ["UPSTASH_REDIS_REST_URL"] = u
results.append(ok(e1 == (False, "no Travelpayouts token") and e2 == (False, "no storage (Upstash)"),
                  "no token, or no Upstash: never runs (nowhere to keep two weeks)"))

results.append(ok(server._flight_shadow_busy() is None, "server idle: no reason to wait"))
server._adv_warming.add("ca")
w1 = server._flight_shadow_busy()
server._adv_warming.discard("ca")
server._page_slots = threading.BoundedSemaphore(2)
server._page_slots.acquire()
w2 = server._flight_shadow_busy()
server._page_slots.release()
server._slot_waiting[0] = 1
w3 = server._flight_shadow_busy()
server._slot_waiting[0] = 0
server._busy["at"] = time.time() - 30
w4 = server._flight_shadow_busy()
server._busy["at"] = time.time() - 700
w5 = server._flight_shadow_busy()
server._busy["at"] = 0.0
server._strength_warm["busy"] = True
w6 = server._flight_shadow_busy()
server._strength_warm["busy"] = False
idle_slots = server._flight_shadow_busy()
server._page_slots = None
results.append(ok((w1, w2, w3, w4, w5, w6, idle_slots) == ("advisory refresh", "pages rendering", "pages rendering",
                                                           "pages queued or shed lately", None, "FX history fetch", None),
                  "busy: an advisory refresh, a page holding or waiting for a slot, pages shed in the last "
                  "10 min, the FX history fetch -> %s" % [w1, w2, w3, w4, w5, w6, idle_slots]))

GCALLS.clear()
flightvalue._warm_done.pop("US")
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
flightvalue._warm_done.update(wd_before)
results.append(ok(r == "fares still filling" and not GCALLS, "before the first fare fill has finished: waits"))
flightvalue._warming["DE"] = time.monotonic()
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
flightvalue._warming.pop("DE")
results.append(ok(r == "fares still filling" and not GCALLS, "while any origin's fill runs: waits"))
server._adv_warming.add("de")
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
server._adv_warming.discard("de")
results.append(ok(r == "server busy: advisory refresh" and not GCALLS, "during an advisory refresh: waits"))
r = fs.check(lambda o: None, busy=server._flight_shadow_busy)
results.append(ok(r == "no fares cached" and not GCALLS, "no fares cached: waits (never refreshes them itself)"))
kv("SET", fs.KEY_LOCK, "1", "EX", 60)
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
kv("DEL", fs.KEY_LOCK)
results.append(ok(r == "another process is running it" and not GCALLS,
                  "another process holds the lock (a deploy's overlap): waits"))
os.environ["FLIGHT_SHADOW_UNTIL"] = (TODAY - datetime.timedelta(days=1)).isoformat()
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
os.environ.pop("FLIGHT_SHADOW_UNTIL")
results.append(ok(r.startswith("past ") and fs._state["finished"] and not GCALLS, "past its end date: finished"))
fs._state["finished"] = False

# the run itself
SLEEPS.clear()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
log = buf.getvalue()
s = fs.held_day(DAY) or {}
results.append(ok(r == "ran " + DAY and s.get("aborted") is None and s.get("day") == DAY,
                  "all clear: today's comparison runs -> %r" % r))
after = reader_outputs()
diff = [k for k in before if before[k] != after[k]]
results.append(ok(not diff, "byte-identical after a run: /api/flight-value, /api/flights, every "
                            "/api/flight-months, _fv_build, _cheap_fares, _guide_fv, serve %s" % diff))
results.append(ok(flights.monthly_entries() == ent_before
                  and all(e is dict(ent_before)[k] for k, e in flights.monthly_entries())
                  and server._flights_cache["US"] is fc_before and flightvalue._warm_done == wd_before,
                  "no shared cache touched: every curve entry the same object, the fares entry, the fill record"))
results.append(ok((len(UP["monthly"]), UP["latest"]) == live_before,
                  "no call to today's source (/v1/prices/monthly, get_latest_prices) from the comparison"))

cities_asked = [q["destination"] for _, q in GCALLS]
results.append(ok(sorted(cities_asked) == sorted(set(cities_asked))
                  and set(cities_asked) == {"DXB", "LON", "MAD", "BCN", "TBS", "CAI", "PAR", "BUD", "ZRH", "REK",
                                            "OSL", "ATH"}
                  and all(q["origin"] == "NYC" and q["token"] == TOKEN
                          and {k: q[k] for k in fs.PARAMS} == fs.PARAMS for _, q in GCALLS),
                  "one grouped call per city the live curve uses (Spain's second city too), NYC, the spike's params"))
gaps = [b[0] - a_[0] for a_, b in zip(GCALLS, GCALLS[1:])]
results.append(ok(gaps and min(gaps) >= fs.PACE and s["calls"]["grouped"] == len(GCALLS) == 12
                  and s["calls"]["day_total"] == 12 and s["calls"]["tries"] == 1 and s["calls"]["dropped_runs"] == 0
                  and s["calls"]["pace_s"] == fs.PACE,
                  "serialized, %.1f s apart at least (60/min vs the 600/min limit); 12 calls counted, 12 today in all"
                  % fs.PACE))
results.append(ok(s["calls"]["failed"] == 2 and s["calls"]["rejected"] == 1 and s["calls"]["statuses"] == {"200": 11, "429": 1}
                  and s["calls"]["ms"]["median"] > 0 and s["calls"]["proj_fill_s"] >= 12 * fs.SWITCH_PACE,
                  "failures counted (REK 429, ATH success:false), latency kept, projected fill at the 0.3 s gap"))
dd = s["dest"]
results.append(ok(dd["IS"]["n"][1] is None and dd["NO"]["n"][0] is None and dd["NO"]["n"][1] == 2
                  and dd["GR"]["n"][1] is None and dd["GR"]["n"][0] == 2,
                  "Iceland grouped-pending (429), Norway live-pending (its live lookup failed), Greece rejected"))
results.append(ok(dd["CH"]["m"][zrh_fill][4] == "ff" and dd["CH"]["m"][zrh_fill][0] == dd["CH"]["m"][zrh_fill][1] == 555,
                  "Switzerland: the latest-prices fill month is the same on both sides, marked 'ff'"))
# The recorded agreement, route by route: the spike's own numbers come back.
exp_same = exp_both = 0
for city in ("DXB", "LON", "MAD", "BCN", "TBS", "CAI", "PAR", "BUD", "ZRH"):
    mm = {k: v["price"] for k, v in MONTHLY[city].items()}
    gm = {k: round(v["price"]) for k, v in GROUPED[city]["data"].items() if v.get("return_at")}
    shared = set(mm) & set(gm)
    exp_both += len(shared)
    exp_same += sum(mm[k] == gm[k] for k in shared)
rm = s["agg"]["route_months"]
results.append(ok(rm["both"] == exp_both and rm["same"] == exp_same and rm["live_missing"] == 1,
                  "recorded routes: same price on %d of %d shared months (%.0f%%; the spike said ~92%%)"
                  % (rm["same"], rm["both"], 100.0 * rm["same"] / max(1, rm["both"]))))
results.append(ok(s["live"]["warm"]["first"]["calls"] == warm_calls and s["live"]["age_h"]["max"] < 1
                  and s["live"]["routes_stale"] == 0,
                  "today's source: its warm-up (calls, time) and how old its curves were at the comparison"))

# storage: written with a 30-day expiry, lock released, no token anywhere
stored = kv("GET", fs.KEY_DAY + DAY)
ttl = kv("TTL", fs.KEY_DAY + DAY)
results.append(ok(stored and json.loads(stored) == s and 30 * 86400 - 60 <= ttl <= 30 * 86400
                  and kv("GET", fs.KEY_LOCK) is None and len(stored) <= fs.MAX_BYTES,
                  "stored as fshadow:day:%s, expires in 30 days (TTL %ds), %d bytes, lock released"
                  % (DAY, ttl, len(stored))))
cttl = kv("TTL", fs.KEY_CALLS + DAY)
results.append(ok(int(kv("GET", fs.KEY_CALLS + DAY)) == 12 and 30 * 86400 - 60 <= cttl <= 30 * 86400,
                  "every call counted in Upstash as it is made: fshadow:calls:%s = 12, expires in 30 days" % DAY))
results.append(ok("at" not in s and not re.search(r"\d\d:\d\d", stored)
                  and set(s["live"]["warm"]["first"]) == {"secs", "calls", "ms", "aborted"},
                  "no time of day in the summary (its day and durations only): no restart time to work out"))
results.append(ok(TOKEN not in stored and TOKEN not in log and "[flight-shadow] " + DAY in log,
                  "no token in what is stored or logged; one [flight-shadow] line"))

n_calls = len(GCALLS)
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
results.append(ok(r == "ran today" and len(GCALLS) == n_calls, "at most once a day: a second check calls nothing"))
fs._days.pop(DAY)
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
results.append(ok(r == "ran today (another process)" and fs.held_day(DAY) == s and len(GCALLS) == n_calls,
                  "a day another process stored (Upstash) also counts: read back, nothing called"))

# endpoint
st, hd, raw = raw_get("/api/flight-shadow", {"Accept-Encoding": "identity"})
doc = json.loads(raw)
results.append(ok(st == 200 and hd.get("Content-Type") == "application/json; charset=utf-8"
                  and hd.get("Cache-Control") == "no-store" and hd.get("X-Robots-Tag") == "noindex"
                  and set(doc) == {"v", "status", "days"} and doc["days"] == [fs.held_day(DAY)]
                  and doc["status"]["complete"] == 1 and doc["status"]["wanted"] == 14,
                  "/api/flight-shadow: JSON, no-store, noindex; status + every stored day"))
results.append(ok(set(doc["status"]) == {"state", "why", "finished", "until", "wanted", "complete", "origin",
                                         "params", "pace_s"}
                  and not re.search(rb"\d\d:\d\d", raw)
                  and raw_get("/api/flight-shadow", {"Host": "wandergrade.com", "Accept-Encoding": "identity"})[2] == raw,
                  "no time of day anywhere in it, on the public host too (no check stamp, no run time, no fill "
                  "start): like /healthz's X-Uptime, restart times stay off the public site"))
n_up, n_g = len(UP["monthly"]) + UP["latest"], len(GCALLS)
real_redis, redis_calls = accounts._redis, []
accounts._redis = lambda *cmd: redis_calls.append(cmd) or real_redis(*cmd)
st2, hd2, gz = raw_get("/api/flight-shadow", {"Accept-Encoding": "gzip"})
st3, hd3, head = raw_get("/api/flight-shadow", method="HEAD")
accounts._redis = real_redis
results.append(ok(st2 == 200 and hd2.get("Content-Encoding") == "gzip" and gzip.decompress(gz) == raw
                  and st3 == 200 and head == b"" and hd3.get("Cache-Control") == "no-store",
                  "gzip when asked (the same bytes), HEAD answers headers only"))
results.append(ok(not redis_calls and len(UP["monthly"]) + UP["latest"] == n_up and len(GCALLS) == n_g,
                  "the endpoint reads memory alone: no upstream call, no Upstash call"))
results.append(ok(TOKEN not in raw.decode() and "token" not in raw.decode().lower()
                  and "travelpayouts.com" not in raw.decode(),
                  "nothing secret in it: no token, no upstream URL"))
linked = []
for d_, _, files in os.walk(os.path.join(ROOT, "public")):
    for f in files:
        if "flight-shadow" in open(os.path.join(d_, f), encoding="utf-8", errors="ignore").read():
            linked.append(f)
for f in ("fxtracker/llms_txt.py", "scripts/gen_sitemap.py", "fxtracker/render_guide.py"):
    if "flight-shadow" in open(os.path.join(ROOT, f), encoding="utf-8").read():
        linked.append(f)
results.append(ok(not linked and b"flight-shadow" not in raw_get("/sitemap.xml")[2],
                  "linked from nowhere: no public file, llms.txt builder, sitemap or guide names it %s" % linked))

# the report script
tmp = tempfile.mkdtemp(prefix="fshadow-")
path = os.path.join(tmp, "shadow.json")
open(path, "wb").write(raw)
p = subprocess.run([sys.executable, os.path.join(HERE, "dev", "flight_shadow_report.py"), path],
                   capture_output=True, text=True, timeout=30)
words = p.stdout
results.append(ok(p.returncode == 0 and "Same price on" in words and "Warm-up after a deploy" in words
                  and "What this suggests" in words and "Not yet:" in words and "only 1 of 14 days" in words
                  and "Countries compared, per day:" in words and "Extra calls: about 12 a day" in words
                  and "lowest seen over the past week" in words and "fresh" not in words
                  and TOKEN not in words,
                  "the report turns the JSON into plain words (rc %d, %d lines)" % (p.returncode, words.count("\n"))))
empty = os.path.join(tmp, "empty.json")
open(empty, "w").write(json.dumps({"v": 1, "status": {"state": "waiting", "why": "fares still filling"}, "days": []}))
p2 = subprocess.run([sys.executable, os.path.join(HERE, "dev", "flight_shadow_report.py"), empty],
                    capture_output=True, text=True, timeout=30)
results.append(ok(p2.returncode == 0 and "No results yet" in p2.stdout, "...and says so when there is nothing yet"))
shutil.rmtree(tmp, ignore_errors=True)

# --- 5. dropped runs, aborted runs, caps ----------------------------------------------


def new_day():
    """Today as if nothing had run yet: no day held or stored, no calls counted, no tries."""
    fs._days.pop(DAY, None)
    kv("DEL", fs.KEY_DAY + DAY)
    kv("DEL", fs.KEY_CALLS + DAY)
    fs._state["tries"] = {}
    fs._carry.update(day=None, g=None)


def counted():
    return int(kv("GET", fs.KEY_CALLS + DAY) or 0)


new_day()
fs.BUSY_GIVE_UP, fs.BUSY_WAIT = 10, 5
calls_at = [len(GCALLS)]
real_busy = server._flight_shadow_busy


def busy_after(n):
    """Busy from the n-th grouped call on (a crawl starting mid-run)."""
    return lambda: "pages rendering" if len(GCALLS) - calls_at[0] >= n else real_busy()


r = fs.check(server._cached_fares, busy=busy_after(3))
first_try = [q["destination"] for _, q in GCALLS[calls_at[0]:]]
results.append(ok(r == "dropped: server got busy" and len(first_try) == 3 and DAY not in fs._days
                  and kv("GET", fs.KEY_DAY + DAY) is None and kv("GET", fs.KEY_LOCK) is None
                  and counted() == 3,
                  "busy mid-run past BUSY_GIVE_UP: dropped after 3 calls, nothing stored, lock released, "
                  "the 3 calls counted in Upstash"))
calls_at[0] = len(GCALLS)
flips = iter([None, "pages rendering", "pages rendering"])
r = fs.check(server._cached_fares, busy=lambda: next(flips, None))
retry = [q["destination"] for _, q in GCALLS[calls_at[0]:]]
s2 = fs.held_day(DAY) or {}
c2 = s2.get("calls", {})
results.append(ok(r == "ran " + DAY and c2.get("busy_waits") == 2 + 2,
                  "busy for a moment mid-run: it waits (2 more waits) and carries on"))
results.append(ok(len(retry) == 12 - 3 and not set(retry) & set(first_try)
                  and set(retry) | set(first_try) == set(cities_asked),
                  "the retry carries on: it asks only the 9 cities still missing, none of the first try's 3 again"))
results.append(ok(c2.get("grouped") == 12 and c2.get("day_total") == 12 == counted()
                  and c2.get("tries") == 2 and c2.get("dropped_runs") == 1
                  and sum(c2["statuses"].values()) == 12
                  and s2["agg"] == s["agg"] and s2["dest"] == s["dest"],
                  "the stored day counts every call it made, the dropped try's too (12 in 2 tries, 1 dropped), "
                  "and compares the same as an uninterrupted run -> %s"
                  % {k: c2.get(k) for k in ("grouped", "day_total", "tries", "dropped_runs")}))
# a restart mid-day: the in-memory answers and tries are gone, the Upstash count is not
new_day()
calls_at[0] = len(GCALLS)
r = fs.check(server._cached_fares, busy=busy_after(5))
fs._carry.update(day=None, g=None)        # the process restarts
fs._state["tries"] = {}
r2 = fs.check(server._cached_fares, busy=real_busy)
c3 = (fs.held_day(DAY) or {}).get("calls", {})
results.append(ok(r == "dropped: server got busy" and r2 == "ran " + DAY and c3.get("grouped") == 12
                  and c3.get("day_total") == 5 + 12 == counted() and len(GCALLS) - calls_at[0] == 17,
                  "a restart after a dropped try: the new process asks all 12 again, and the day's total says 17 "
                  "(every process's calls) -> %s" % {k: c3.get(k) for k in ("grouped", "day_total")}))
# the day's limit holds across tries and processes
new_day()
kv("SET", fs.KEY_CALLS + DAY, fs.MAX_CALLS, "EX", 60)
calls_at[0] = len(GCALLS)
r = fs.check(server._cached_fares, busy=real_busy)
results.append(ok(r == "gave up today: %d calls made already" % fs.MAX_CALLS and len(GCALLS) == calls_at[0]
                  and kv("GET", fs.KEY_LOCK) is None,
                  "the day's %d calls already made (any process): no try, no call" % fs.MAX_CALLS))
new_day()
kv("SET", fs.KEY_CALLS + DAY, fs.MAX_CALLS - 4, "EX", 60)
r = fs.check(server._cached_fares, busy=real_busy)
c4 = (fs.held_day(DAY) or {}).get("calls", {})
cap4 = (fs.held_day(DAY) or {}).get("capped")
results.append(ok(r == "ran " + DAY and len(GCALLS) - calls_at[0] == 4 and cap4 is True
                  and c4.get("day_total") == fs.MAX_CALLS == counted(),
                  "4 calls left today: it makes 4, stops there (capped) and the day ends at exactly %d" % fs.MAX_CALLS))
new_day()
# a live fare fill starting mid-run pauses it too (its curves are the yardstick)
calls_at[0] = len(GCALLS)
real_gfetch = fs._fetch


def gfetch_then_fill(url):
    out = real_gfetch(url)
    if len(GCALLS) - calls_at[0] == 2:
        flightvalue._warming["US"] = time.monotonic()
    return out


fs._fetch = gfetch_then_fill
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
fs._fetch = real_gfetch
flightvalue._warming.pop("US", None)
results.append(ok(r == "dropped: server got busy" and len(GCALLS) - calls_at[0] == 2 and DAY not in fs._days,
                  "a live fare fill starting mid-run: it waits, and past BUSY_GIVE_UP drops the run"))
new_day()
# a run that outlasts its lock's TTL: the lock another process took since stays
calls_at[0] = len(GCALLS)
lock_seen = []


def gfetch_lock_taken(url):
    out = real_gfetch(url)
    if len(GCALLS) - calls_at[0] == 1:
        lock_seen.append(kv("GET", fs.KEY_LOCK))
    if len(GCALLS) - calls_at[0] == 2:
        kv("SET", fs.KEY_LOCK, "other-process", "EX", 60)   # ours expired, another took it
    return out


fs._fetch = gfetch_lock_taken
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
fs._fetch = real_gfetch
held = kv("GET", fs.KEY_LOCK)
kv("DEL", fs.KEY_LOCK)
results.append(ok(r.startswith("ran ") and held == "other-process" and lock_seen and lock_seen[0]
                  and lock_seen[0] != "other-process" and TOKEN not in lock_seen[0],
                  "a run that outlasts its lock leaves the lock another process took since (own lock %r)"
                  % (lock_seen[:1],)))
new_day()
fs._state["tries"] = {DAY: fs.TRIES_PER_DAY}
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
results.append(ok(r == "gave up today: busy every try", "at most TRIES_PER_DAY tries a day"))
new_day()

saved = dict(GROUPED)
GROUPED.update({c: 429 for c in GROUPED})
calls_at[0] = len(GCALLS)
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
s3 = fs.held_day(DAY) or {}
GROUPED.clear()
GROUPED.update(saved)
results.append(ok(r.endswith("(aborted)") and len(GCALLS) - calls_at[0] == fs.MAX_FAILS
                  and s3.get("aborted") == "5 failed calls in a row (last HTTP 429)" and "dest" not in s3
                  and s3["calls"]["day_total"] == fs.MAX_FAILS and fs.complete_days() == 0,
                  "grouped failing: stops after %d calls in a row, stored as aborted (not a complete day)"
                  % fs.MAX_FAILS))
fs.MAX_CALLS = 4
summ = fs.run_once(server._cached_fares("US"), today=TODAY)
fs.MAX_CALLS = 400
results.append(ok(summ["capped"] is True and summ["calls"]["grouped"] == 4 == summ["calls"]["day_total"],
                  "hard cap on calls (a run with no day count: its own)"))

# --- 6. Upstash: expiry, trimming, done marker, reload ----------------------------------
big = dict(s, dest={("X%03d" % i): {"n": [12, 12], "b": [1, 1], "m": {k: [999, 1001, 1.002, "TT", "rr"] for k in WIN}}
                    for i in range(300)})
enc = fs.encode(big)
dec = json.loads(enc)
results.append(ok(len(enc) <= fs.MAX_BYTES and dec["trimmed"] and len(dec["dest"]) == 300
                  and any("m" in v for v in dec["dest"].values()) and any("m" not in v for v in dec["dest"].values()),
                  "over %d KB: per-month detail dropped thinnest first, coverage counts kept (%d bytes)"
                  % (fs.MAX_BYTES // 1024, len(enc))))
results.append(ok(json.loads(fs.encode(s)) == s and "trimmed" not in s, "under the cap: stored whole"))
fs.DAY_TTL = 1
fs.store(dict(s, day="2001-01-01"))
fs.DAY_TTL = 30 * 86400
time.sleep(1.2)
results.append(ok(kv("GET", fs.KEY_DAY + "2001-01-01") is None, "a day's key expires on its TTL (1 s here, 30 days live)"))

fs._days.clear()
kv("DEL", fs.KEY_DAY + DAY)
fs._state.update(finished=False, tries={})
fs.WANTED = 2
yday = (datetime.date.fromisoformat(DAY) - datetime.timedelta(days=1)).isoformat()
kv("SET", fs.KEY_DAY + yday, json.dumps(dict(s, day=yday)), "EX", 3600)
results.append(ok(fs.load() and yday in fs._days and fs.complete_days() == 1, "load(): reads the stored days back (MGET)"))
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
results.append(ok(r.startswith("ran ") and kv("GET", fs.KEY_DONE) == DAY and fs._state["finished"],
                  "WANTED complete days: the done marker is set and it stops"))
r = fs.check(server._cached_fares, busy=server._flight_shadow_busy)
results.append(ok(r.startswith("done: 2 complete days"), "finished: says so, runs nothing more"))
fs._days.clear()
fs._state.update(finished=False)
fs.load()
results.append(ok(fs._state["finished"] and len(fs._days) == 2, "after a redeploy: the done marker and both days read back"))
fs.WANTED = 14

# --- 7. the background thread -------------------------------------------------------------
gate, delay_gate, at_delay, redis_log = threading.Event(), threading.Event(), {}, []
real_redis = accounts._redis


def thread_sleep(secs):
    if threading.current_thread().name == "flight-shadow":
        if secs == fs.CHECK_EVERY:
            gate.wait(10)
            return
        if secs == 7.0:          # the boot delay (FLIGHT_SHADOW_DELAY below)
            at_delay["redis"] = [c for t, c in redis_log if t == "flight-shadow"]
            at_delay["doc"] = json.loads(fs.body()[0])
            delay_gate.wait(10)
            return
    fake_sleep(secs)


fs._sleep = thread_sleep
accounts._redis = lambda *cmd: redis_log.append((threading.current_thread().name, cmd[0])) or real_redis(*cmd)
fs._state.update(finished=False)
fs._days.clear()
kv("DEL", fs.KEY_DONE)
os.environ["FLIGHT_SHADOW_DELAY"] = "7"
n_g = len(GCALLS)
started = fs.start(server._cached_fares, busy=server._flight_shadow_busy)
t_end = time.time() + 5
while time.time() < t_end and "doc" not in at_delay:
    time.sleep(0.02)
pub = raw_get("/api/flight-shadow", {"Host": "wandergrade.com", "Accept-Encoding": "identity"})[2]
results.append(ok(started and at_delay.get("redis") == [] and at_delay["doc"]["days"] == []
                  and at_delay["doc"]["status"]["why"] == "starting" and not re.search(rb"\d\d:\d\d", pub),
                  "start(): nothing read from Upstash or parsed during the boot delay; the endpoint says "
                  "'starting' with no time stamp -> %s" % at_delay.get("doc", {}).get("status")))
delay_gate.set()
t_end = time.time() + 5
while time.time() < t_end and fs._state["why"] in ("starting",):
    time.sleep(0.02)
accounts._redis = real_redis
thread_redis = [c for t, c in redis_log if t == "flight-shadow"]
results.append(ok(fs._state["why"] == "ran today" and len(GCALLS) == n_g and thread_redis[:1] == ["MGET"]
                  and DAY in fs._days and isinstance(fs._days[DAY][0], str)
                  and any(t.name == "flight-shadow" for t in threading.enumerate()),
                  "...then it reads the stored days (one MGET, held as their stored text), checks, sees today "
                  "done -> %r" % fs._state["why"]))
fs._state["finished"] = True
gate.set()
t_end = time.time() + 5
while time.time() < t_end and any(t.name == "flight-shadow" for t in threading.enumerate()):
    time.sleep(0.02)
results.append(ok(not any(t.name == "flight-shadow" for t in threading.enumerate()),
                  "...and the thread ends once the test is finished"))
fs._sleep = fake_sleep
os.environ.pop("FLIGHT_SHADOW_DELAY")

# --- 8. the real _fetch: errors carry no URL (and so no token) ------------------------------


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        code = 429 if "rate" in self.path else 200
        body = b'{"success": true, "data": {}}' if code == 200 else b"slow down"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


tiny = HTTPServer(("127.0.0.1", 0), _H)
threading.Thread(target=tiny.serve_forever, daemon=True).start()
tb = "http://127.0.0.1:%d" % tiny.server_address[1]
f1 = REAL_FETCH(tb + "/ok?token=" + TOKEN)
f2 = REAL_FETCH(tb + "/rate?token=" + TOKEN)
f3 = REAL_FETCH("http://127.0.0.1:1/closed?token=" + TOKEN)
results.append(ok(f1[:2] == (200, {"success": True, "data": {}}) and f2[:2] == (429, None) and f3[:2] == (0, None)
                  and all(isinstance(x[2], int) for x in (f1, f2, f3)),
                  "real _fetch: 200 parsed, 429 and a dead port answered as status codes, never raised"))
tiny.shutdown()

httpd.shutdown()
mock.shutdown()
print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

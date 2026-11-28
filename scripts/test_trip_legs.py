"""/api/trip-legs (round 16): fares and flight times between the countries of
a reader's trip, from the hub fares the server already caches
(fxtracker/triplegs.py + server.py's route). No network: the fares source is
stubbed and rates.fetch_json refuses every call, so nothing leaves this
machine.

    /usr/bin/python3 scripts/test_trip_legs.py

What it holds the code to:
  * the request: at most 12 countries (13 is a 400), an origin that is a hub
    (anything else a 400), a month as YYYY-MM or none (junk a 400), codes
    deduplicated in order;
  * at most 4 hub payloads fetched upstream per request, the rest `pending`
    (estimated now, real on a later visit); none at all while the server is
    busy; a cached payload is free and never counts; a stale copy in hand is
    used rather than left pending; a failed fetch is pending, not an error;
    the reader's own (origin) payload is read from the cache only, never
    fetched for the fit;
  * one kind of fare: the trip month's cheapest cached round trip where the
    payload row has that month ("basis": "month"), else the yearly average
    ("avg"); flexible (no month) is "avg" throughout; dur/stops as the row;
  * a country with no hub of its own (Laos) takes the reverse row of a hub
    that has it (Thailand's row for Laos), marked rev; a hub missing the row
    takes the reverse one too; England reads the UK's hub; England and the
    UK on one trip have no leg between them;
  * regional_fit: least squares over rows up to 5,000 km only; under 30 rows
    (or a slope that isn't positive) the fallback; with no fallback, nulls;
  * HTTP: no-store, X-Robots-Tag noindex, no upstream call when everything
    is cached, cache-only while busy, no page slot taken, 400s for the bad
    requests above, and without a fare token an empty answer (never a 500).
"""
import json, os, sys, threading, urllib.error, urllib.request

os.environ["TRAVELPAYOUTS_TOKEN"] = "dummy-never-sent"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fxtracker import flights, geo, rates

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def refuse(*a, **k):
    raise OSError("test: no network (%s)" % (a[:1],))


rates.fetch_json = refuse          # anything that slips through fails loudly instead of leaving the machine

try:
    from fxtracker import triplegs
except Exception as e:   # the module doesn't exist yet: every check fails
    print("  FAIL  import fxtracker.triplegs (%s)" % e)
    print("\n0/1 passed")
    sys.exit(1)

C = geo.site_centroids()


def row(iso, avg, months=None, dur=None, stops=None):
    return {"iso": iso, "avg": avg, "min": avg - 20, "n": 3, "dur": dur, "stops": stops, "dest": "X",
            "dur_city": "X", "seen": None, "cities": ["X"], "months": months or {}}


def payload(origin, rows):
    return {"configured": True, "origin": origin, "hub": flights.ORIGIN_HUBS[origin][0], "currency": "usd",
            "countries": rows, "by_country": {r["iso"]: r["avg"] for r in rows}}


PAY = {
    "US": payload("US", [row("TH", 1100, {"2026-12": {"price": 980}}, 1200, 1), row("VN", 1200, {}, 1300, 1),
                         row("KH", 1300, {}, 1500, 2), row("MX", 400, {}, 300, 0), row("GB", 700, {}, 420, 0),
                         row("CA", 350, {}, 100, 0), row("JP", 1150, {}, 840, 0), row("FR", 720, {}, 460, 0),
                         row("BR", 900, {}, 600, 0), row("CO", 450, {}, 330, 0)]),
    "TH": payload("TH", [row("VN", 160, {"2026-12": {"price": 120, "dest": "SGN"}}, 110, 0),
                         row("KH", 140, {}, 75, 0), row("LA", 150, {"2026-12": {"price": 99}}, 70, 0),
                         row("SG", 180, {}, 140, 0)]),
    "VN": payload("VN", [row("TH", 170, {}, 105, 0), row("KH", 130, {"2026-11": {"price": 90}}, 60, 0)]),
    "KH": payload("KH", [row("TH", 150, {}, 80, 0)]),     # no VN row: VN->KH ... KH->VN takes VN's reverse row
    "GB": payload("GB", [row("FR", 120, {}, 75, 0), row("ES", 140, {}, 140, 0)]),
    "FR": payload("FR", [row("GB", 110, {}, 70, 0), row("ES", 90, {}, 110, 0)]),
    "ES": payload("ES", [row("FR", 95, {}, 105, 0)]),
    "DE": payload("DE", [row("FR", 100, {}, 80, 0)]),
    "IT": payload("IT", [row("FR", 105, {}, 95, 0)]),
    "PT": payload("PT", [row("FR", 115, {}, 135, 0)]),
}


class Src:
    """A fares source: `have` = cached isos; fetch() counts upstream fetches."""
    def __init__(self, have=(), stale=(), fail=()):
        self.have, self.stale, self.fail, self.fetched, self.read = set(have), set(stale), set(fail), [], []

    def cached(self, iso):
        return iso in self.have

    def fares_for(self, iso):
        if iso not in self.have:
            self.fetched.append(iso)
            if iso in self.fail:
                raise RuntimeError("upstream down")
        self.read.append(iso)
        return PAY.get(iso)

    def stale_for(self, iso):
        return PAY.get(iso) if iso in self.stale else None


def run(src, origin, isos, month=None, busy=False, stale=False):
    return triplegs.legs(origin, isos, month, fares_for=src.fares_for, cached=src.cached, busy=busy,
                         stale_for=src.stale_for if stale else None)


# --- the request ----------------------------------------------------------------
H = flights.ORIGIN_HUBS


def parse(*a):
    try:
        return triplegs.parse(*a, hubs=H)
    except ValueError as e:
        return "ValueError: %s" % e


many = ",".join(["TH", "VN", "KH", "LA", "MY", "SG", "ID", "PH", "JP", "KR", "TW", "HK", "CN"])
results.append(ok(str(parse("US", many, "")).startswith("ValueError") and triplegs.MAX_ISOS == 12,
                  "13 countries -> refused (MAX_ISOS 12): %s" % str(parse("US", many, ""))[:60]))
p12 = parse("US", ",".join(many.split(",")[:12]), "")
results.append(ok(isinstance(p12, tuple) and len(p12[1]) == 12, "12 countries are fine"))
results.append(ok(str(parse("ZZ", "TH,VN", "")).startswith("ValueError") and str(parse("", "TH", "")).startswith("ValueError")
                  and str(parse("LA", "TH", "")).startswith("ValueError"),
                  "an origin that isn't a hub (ZZ, blank, Laos) -> refused"))
results.append(ok(str(parse("US", "TH,VN", "2026-13")).startswith("ValueError") and str(parse("US", "TH", "Dec")).startswith("ValueError"),
                  "a month that isn't YYYY-MM -> refused"))
results.append(ok(str(parse("US", "TH,<script>", "")).startswith("ValueError") and str(parse("US", "THA", "")).startswith("ValueError"),
                  "a code that isn't a country code -> refused"))
results.append(ok(parse("us", "th, vn,TH,gb-eng", "2026-12") == ("US", ["TH", "VN", "GB-ENG"], "2026-12"),
                  "codes upper-cased, trimmed and deduplicated in order: %s" % (parse("us", "th, vn,TH,gb-eng", "2026-12"),)))
results.append(ok(parse("US", "", "") == ("US", [], None), "no countries, no month: an empty request, not an error (%s)" % (parse("US", "", ""),)))

# --- fetch caps ----------------------------------------------------------------
six = ["TH", "VN", "KH", "GB", "FR", "ES"]
s = Src(have=["US"])
out = run(s, "US", six)
results.append(ok(s.fetched == ["TH", "VN", "KH", "GB"] and out["pending"] == ["FR", "ES"],
                  "6 uncached hubs: exactly 4 fetched (%s), 2 pending (%s)" % (s.fetched, out["pending"])))
s = Src(have=["US"])
out = run(s, "US", six, busy=True)
results.append(ok(s.fetched == [] and out["pending"] == six, "busy: nothing fetched, every uncached hub pending (%s)" % out["pending"]))
s = Src(have=["US", "TH", "VN", "KH", "GB", "FR", "ES", "DE", "IT", "PT"])
out = run(s, "US", ["TH", "VN", "KH", "GB", "FR", "ES", "DE", "IT", "PT"])
results.append(ok(s.fetched == [] and out["pending"] == [], "9 cached hubs: no fetch, nothing pending"))
s = Src(have=["US", "TH", "VN"])
out = run(s, "US", ["TH", "VN", "KH", "GB", "FR", "ES", "DE"])
results.append(ok(s.fetched == ["KH", "GB", "FR", "ES"] and out["pending"] == ["DE"], "cached ones don't count against the 4 (%s | %s)" % (s.fetched, out["pending"])))
s = Src(have=["US"], stale=["FR", "ES"])
out = run(s, "US", six, busy=True, stale=True)
results.append(ok(s.fetched == [] and out["pending"] == ["TH", "VN", "KH", "GB"] and "ES" in out["legs"].get("FR", {}),
                  "busy, a stale copy in hand: used (FR->ES real), not pending (%s)" % out["pending"]))
s = Src(have=["US"], fail=["VN"])
out = run(s, "US", ["TH", "VN", "KH"])
results.append(ok(out["pending"] == ["VN"] and out["legs"]["TH"]["VN"]["fare"] == 160,
                  "a failed fetch: pending, no error; the other hubs' rows for it still real (%s)" % out["pending"]))
s = Src(have=[])
out = run(s, "US", ["TH", "VN"])
results.append(ok("US" not in s.fetched and "US" not in s.read, "the reader's own payload is never fetched for the fit (fetched %s)" % s.fetched))
s = Src(have=["US"])
out = run(s, "US", ["LA", "MM"])
results.append(ok(s.fetched == [] and out["pending"] == [] and out["legs"] == {},
                  "no hub among the countries: nothing fetched, nothing pending, no legs (%s)" % out))

# --- one kind of fare ---------------------------------------------------------------
s = Src(have=["US", "TH", "VN", "KH"])
out = run(s, "US", ["TH", "VN", "KH"], "2026-12")
L = out["legs"]
results.append(ok(L["TH"]["VN"] == {"fare": 120, "basis": "month", "dur": 110, "stops": 0},
                  "TH->VN in December: the month's cheapest round trip (%s)" % L["TH"].get("VN")))
results.append(ok(L["TH"]["KH"]["fare"] == 140 and L["TH"]["KH"]["basis"] == "avg" and L["TH"]["KH"]["dur"] == 75,
                  "TH->KH, no December fare cached: the yearly average (%s)" % L["TH"].get("KH")))
results.append(ok(L["VN"]["KH"]["basis"] == "avg" and L["VN"]["KH"]["fare"] == 130, "VN->KH: November is not December -> avg (%s)" % L["VN"].get("KH")))
out_f = run(Src(have=["US", "TH", "VN", "KH"]), "US", ["TH", "VN", "KH"], None)
results.append(ok(all(v["basis"] == "avg" for d in out_f["legs"].values() for v in d.values()) and out_f["legs"]["TH"]["VN"]["fare"] == 160,
                  "flexible (no month): avg throughout"))
results.append(ok(out.get("month") == "2026-12" and out.get("origin") == "US" and out_f.get("month") is None,
                  "the answer names its origin and month (a late answer for an old month can be told apart)"))

# --- reverse rows, parents ----------------------------------------------------------
results.append(ok(L["KH"]["VN"] == {"fare": 130, "basis": "avg", "dur": 60, "stops": 0, "rev": True},
                  "KH's payload has no VN row: KH->VN takes VN's row for KH, marked rev (%s)" % L["KH"].get("VN")))
s = Src(have=["US", "TH"])
out = run(s, "US", ["LA", "TH"], "2026-12")
results.append(ok(out["legs"].get("LA", {}).get("TH") == {"fare": 99, "basis": "month", "dur": 70, "stops": 0, "rev": True}
                  and out["legs"]["TH"]["LA"]["fare"] == 99 and "rev" not in out["legs"]["TH"]["LA"],
                  "Laos (no hub) -> Thailand: Thailand's row for Laos, reversed (%s)" % out["legs"].get("LA")))
s = Src(have=["US", "GB", "FR"])
out = run(s, "US", ["GB-ENG", "FR", "GB"])
results.append(ok(out["legs"].get("GB-ENG", {}).get("FR", {}).get("fare") == 120 and out["legs"]["FR"].get("GB-ENG", {}).get("fare") == 110,
                  "England reads the UK's hub both ways (%s)" % {k: out["legs"].get(k) for k in ("GB-ENG", "FR")}))
results.append(ok("GB" not in out["legs"].get("GB-ENG", {}) and "GB-ENG" not in out["legs"].get("GB", {}),
                  "England and the UK on one trip: no leg between them"))

# --- regional fit ------------------------------------------------------------------
near = [(200 + 100 * i, 50 + 0.1 * (200 + 100 * i)) for i in range(40)]          # 200..4100 km, fare = 50 + 0.1 km
far = [(6000 + 100 * i, 2000) for i in range(20)]                                 # long haul, would bend the line
a, b, n = triplegs.regional_fit(near + far, (999, 9))
results.append(ok(abs(a - 50) < 1e-6 and abs(b - 0.1) < 1e-9 and n == 40, "rows over 5,000 km are left out: a=%.3f b=%.4f n=%d" % (a, b, n)))
a, b, n = triplegs.regional_fit(near[:29], (300, 0.05))
results.append(ok((a, b, n) == (300, 0.05, 29), "29 rows: the fallback (%s)" % ((a, b, n),)))
a, b, n = triplegs.regional_fit(near[:29], None)
results.append(ok(a is None and b is None and n == 29, "29 rows, no fallback: nulls (%s)" % ((a, b, n),)))
down = [(200 + 100 * i, 900 - 0.1 * (200 + 100 * i)) for i in range(40)]
a, b, n = triplegs.regional_fit(down, (300, 0.05))
results.append(ok((a, b) == (300, 0.05), "a slope that isn't positive: the fallback (%s)" % ((a, b, n),)))
s = Src(have=["US", "TH", "VN", "KH"])
out = run(s, "US", ["TH", "VN", "KH"])
f = out["fit"]
results.append(ok(set(f) >= {"a", "b", "n"} and isinstance(f["n"], int), "the answer carries the fit {a, b, n} (%s)" % f))
# few regional rows here: the fallback is the reader's own payload fit (all distances, avg fares)
uspts = [(geo.dist_km(C["US"], C[r["iso"]]), r["avg"]) for r in PAY["US"]["countries"] if r["iso"] in C]
mx = sum(p[0] for p in uspts) / len(uspts); my = sum(p[1] for p in uspts) / len(uspts)
bb = sum((x - mx) * (y - my) for x, y in uspts) / sum((x - mx) ** 2 for x, _ in uspts); aa = my - bb * mx
results.append(ok(f["n"] < 30 and f["a"] is not None and abs(f["a"] - aa) < 1e-6 and abs(f["b"] - bb) < 1e-9,
                  "under 30 regional rows: the reader's own fit (a=%s b=%s vs %.2f %.4f)" % (f["a"], f["b"], aa, bb)))
out_n = run(Src(have=[]), "US", ["TH", "VN"], busy=True)
results.append(ok(out_n["fit"]["a"] is None and out_n["fit"]["b"] is None, "nothing in hand at all: a null fit, the browser estimates (%s)" % out_n["fit"]))

# --- HTTP ------------------------------------------------------------------------------
import time
import server
from http.server import ThreadingHTTPServer

UPSTREAM = []
flights.get_flights = lambda o, currency="usd": (UPSTREAM.append(o), PAY.get(o) or payload(o, []))[1]
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b"{}")


now = time.time()
server._flights_cache.clear()
for o in ("US", "TH", "VN", "KH"):
    server._flights_cache[o] = (now, PAY[o])
st, hd, bd = get("/api/trip-legs?origin=US&isos=TH,VN,KH&month=2026-12")
results.append(ok(st == 200 and bd["legs"]["TH"]["VN"]["fare"] == 120 and bd["pending"] == [], "200 with the legs (%s)" % str(bd)[:120]))
results.append(ok(hd.get("Cache-Control") == "no-store" and hd.get("X-Robots-Tag") == "noindex",
                  "no-store, X-Robots-Tag noindex (%s, %s)" % (hd.get("Cache-Control"), hd.get("X-Robots-Tag"))))
results.append(ok(UPSTREAM == [], "everything cached: no upstream call (%s)" % UPSTREAM))
st, hd, bd = get("/api/trip-legs?origin=US&isos=" + many)
results.append(ok(st == 400 and bd.get("error") and hd.get("Cache-Control") == "no-store", "13 countries -> 400 (%s)" % bd))
st, _, bd = get("/api/trip-legs?origin=ZZ&isos=TH")
results.append(ok(st == 400 and bd.get("error"), "unknown origin -> 400 (%s)" % bd))
st, _, bd = get("/api/trip-legs?origin=US&isos=TH&month=junk")
results.append(ok(st == 400, "junk month -> 400"))
st, _, bd = get("/api/trip-legs?origin=US&isos=TH,GB")
results.append(ok(st == 200 and UPSTREAM == ["GB"] and bd["pending"] == [], "an uncached hub is fetched once (%s)" % UPSTREAM))
UPSTREAM.clear()
keep = server._flight_shadow_busy
server._flight_shadow_busy = lambda: "pages rendering"
st, _, bd = get("/api/trip-legs?origin=US&isos=TH,FR")
server._flight_shadow_busy = keep
results.append(ok(st == 200 and UPSTREAM == [] and bd["pending"] == ["FR"], "busy: cache only, FR pending (%s, %s)" % (UPSTREAM, bd.get("pending"))))
results.append(ok(not server._slot_route("/api/trip-legs"), "the endpoint takes no page slot"))
stale_at = now - server.FLIGHTS_TTL - 60
server._flights_cache["ES"] = (stale_at, PAY["ES"])
server._flight_shadow_busy = lambda: "pages rendering"
st, _, bd = get("/api/trip-legs?origin=US&isos=ES,FR")
server._flight_shadow_busy = keep
results.append(ok(st == 200 and UPSTREAM == [] and "FR" in bd["legs"].get("ES", {}) and bd["pending"] == ["FR"],
                  "busy with a stale ES copy: ES's legs real from it, FR pending, no fetch (%s)" % bd.get("pending")))
UPSTREAM.clear()
os.environ.pop("TRAVELPAYOUTS_TOKEN")
st, hd, bd = get("/api/trip-legs?origin=US&isos=TH,VN")
os.environ["TRAVELPAYOUTS_TOKEN"] = "dummy-never-sent"
results.append(ok(st == 200 and bd.get("legs") == {} and bd.get("configured") is False and UPSTREAM == [],
                  "no fare token: an empty answer, never a 500 (%s)" % bd))
httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
sys.exit(0 if all(results) else 1)

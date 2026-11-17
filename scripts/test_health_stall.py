#!/usr/bin/env python3
"""The /healthz stall fixes (Render "health check timed out", 2026-11-10 and
2026-11-16) — offline, no server process, a few seconds.

    /usr/bin/python3 scripts/test_health_stall.py

What it holds the code to:
  * fxtracker/advisories.py FEED_MEMO_TTL: with the memo on, refreshing the
    three lists (get_advisories for us, ca and de, each reading the other two
    as gap-fills) parses each feed exactly once, and concurrent callers wait
    for the one parse in flight, and get its error when it fails (a timing-out
    feed fetched once, not once per caller in turn); the lists come out
    equal to the memo-off ones; every caller gets its own copy (mutating one list leaves the next
    untouched); a parse that raises is not kept; an expired memo parses
    again; at 0 (the default, what the newsletter build gets) every call
    parses, as before.
  * server.py, an advisory list on a request's path: past ADV_TTL the copy in
    hand goes out at once (the same object) while exactly one background
    refresh runs (advhistory stamps only that refreshed list), after which
    the cache holds a new object; while the last refresh failed the copy goes
    out marked stale, with no refresh inside the failure backoff and one
    after it; a list not in hand is computed once however many requests ask
    at once, and they all get it, or all get its error with _adv_failed set;
    a computation stuck past ADV_FLIGHT_WAIT doesn't hold the others; the
    background callers (the refresh thread, the guide-facts refresher) wait
    for a current list; /api/advisories' fallback for a list that can't load
    reads the other lists the same way.
  * server.py main() listens with a backlog of 128 (socketserver's 5 let
    Linux drop the health check's connection) and keeps daemon threads, and
    sets a 0.5 ms GIL switch interval. It works on at most 3 GETs at once
    (/healthz never waits, and a request waiting past PAGE_SLOT_WAIT runs
    anyway).
  * server.py _warm_watchouts: ten guides' Canada notes are all fetched, never
    more than two at once, with no thread per guide; a country already queued
    or in flight is not queued again; a fetch that raises doesn't stop the
    queue.
"""
import copy
import inspect
import json
import os
import re
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories as A  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def item(iso, level, **kw):
    return dict({"iso": iso, "country": iso, "level": level, "level_text": "", "link": "https://x/" + iso}, **kw)


ROWS = {
    "us": [item("BF", 4), item("JP", 1), item("SA", 3, risks=["terrorism"])],
    "ca": [item("BF", 4), item("JP", 1), item("SA", 3), item("VE", 4), item("PS", 4)],
    "de": [item("BF", 2), item("SA", 4), item("VE", 2), item("MO", 1)],
}
calls = {"us": 0, "ca": 0, "de": 0}
gate = {"delay": 0.0, "fail": set(), "delays": {}, "down": set()}
calls_lock = threading.Lock()


def parser(src):
    def run():
        with calls_lock:
            calls[src] += 1
        delay = gate["delays"].get(src, gate["delay"])
        if delay:
            time.sleep(delay)
        if src in gate["down"]:
            raise RuntimeError("feed %s timed out" % src)
        if src in gate["fail"]:
            gate["fail"].discard(src)
            raise RuntimeError("feed %s down" % src)
        rows = copy.deepcopy(ROWS[src])
        return {"items": rows, "count": len(rows), "matched": len(rows), "source": src,
                "source_name": A.SOURCES[src], "source_url": "https://x/" + src}
    return run


A._us_advisories, A._canadian_advisories, A._german_advisories = parser("us"), parser("ca"), parser("de")


def reset(ttl):
    A.FEED_MEMO_TTL = ttl
    A._feed_memo.clear()
    for k in calls:
        calls[k] = 0


def refresh_all():
    return {s: A.get_advisories(s) for s in ("us", "ca", "de")}


# --- advisories.py: one parse per feed, shared -------------------------------------
results.append(ok(A.FEED_MEMO_TTL == 0, "the memo is off by default (the newsletter build never imports server)"))
for f in ("check.py", "send_digest.py", os.path.join("fxtracker", "picks.py")):
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    results.append(ok("import server" not in src and "FEED_MEMO_TTL" not in src,
                      "%s neither imports server nor turns the memo on" % f))

reset(0)
off = refresh_all()
results.append(ok(calls == {"us": 3, "ca": 3, "de": 3},
                  "memo off: a refresh of the three lists parses each feed three times, as before (%s)" % calls))
off2 = refresh_all()
results.append(ok(calls == {"us": 6, "ca": 6, "de": 6}, "memo off: every call parses (%s)" % calls))

reset(120)
on = refresh_all()
results.append(ok(calls == {"us": 1, "ca": 1, "de": 1},
                  "memo on: a refresh of the three lists parses each feed once (%s)" % calls))
results.append(ok(on == off and off == off2 and [on[x]["filled"] for x in ("us", "ca", "de")] == [3, 1, 2],
                  "memo on: the three lists are equal to the memo-off ones"))
on["us"]["items"][0]["level"] = 1
on["us"]["items"].append(item("XX", 4))
on["us"]["items"][-2].setdefault("risks", []).append("mutated")
again = refresh_all()
results.append(ok(again == off and calls == {"us": 1, "ca": 1, "de": 1},
                  "mutating one list leaves the next untouched (still one parse each)"))
a, b = A._from_shared("us"), A._from_shared("us")
results.append(ok(a == b and a is not b and a["items"] is not b["items"] and a["items"][0] is not b["items"][0],
                  "each caller gets its own deep copy"))

reset(120)
gate["fail"] = {"us"}
try:
    A.get_advisories("us")
    raised = False
except RuntimeError:
    raised = True
first = calls["us"]
got = A.get_advisories("us")
results.append(ok(raised and first == 1 and calls["us"] == 2 and got == off["us"],
                  "a parse that raises is not kept: the next caller parses again (%s)" % calls))
reset(120)
gate["fail"] = {"ca"}
us = A.get_advisories("us")
results.append(ok(us["filled"] == 2 and calls["ca"] == 1 and A.get_advisories("ca") == off["ca"] and calls["ca"] == 2,
                  "a gap-fill feed that raises is skipped as before and parsed again next time (%s)" % calls))

reset(120)
A.get_advisories("us")
for s in list(A._feed_memo):
    at, data = A._feed_memo[s]
    A._feed_memo[s] = (at - 121, data)
A.get_advisories("us")
results.append(ok(calls == {"us": 2, "ca": 2, "de": 2}, "an expired memo parses again (%s)" % calls))

reset(120)
gate["delay"] = 0.3
out, ths = [], [threading.Thread(target=lambda: out.append(A.get_advisories("us"))) for _ in range(8)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join(10)
took = time.time() - t0
gate["delay"] = 0.0
results.append(ok(len(out) == 8 and all(o == off["us"] for o in out) and calls == {"us": 1, "ca": 1, "de": 1}
                  and took < 2.0,
                  "8 concurrent callers wait for the one parse in flight: one parse each, same lists (%.2fs, %s)"
                  % (took, calls)))

# The US feed is timing out (each try ~65 s in production; 0.5 s here) while the
# three lists refresh and two more callers ask: the one attempt in flight is
# shared, its error included, so nobody waits behind anyone else's retry.
reset(120)
gate.update(delays={"us": 0.5}, down={"us"})
done, done_lock = {}, threading.Lock()


def ask(i, src):
    t0 = time.time()
    try:
        r = A.get_advisories(src)
    except Exception as e:
        r = e
    with done_lock:
        done[i] = (src, time.time() - t0, r)


ths = [threading.Thread(target=ask, args=(i, s_)) for i, s_ in enumerate(["us", "ca", "de", "ca", "de"])]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join(10)
wall = time.time() - t0
gate.update(delays={}, down=set())
slowest = max(v[1] for v in done.values())
results.append(ok(len(done) == 5 and wall < 0.9 and slowest < 0.9 and calls["us"] == 1,
                  "a failing feed is fetched once and every caller in its flight gets the outcome together "
                  "(wall %.2fs, US fetches %d)" % (wall, calls["us"])))
results.append(ok(isinstance(done[0][2], RuntimeError) and str(done[0][2]) == "feed us timed out"
                  and all(isinstance(done[i][2], dict) and not any(it.get("via") == "us" for it in done[i][2]["items"])
                          for i in (1, 2, 3, 4)),
                  "the US list raises its error; Canada's and Germany's lists load without US gap-fills, not "
                  "queued behind a US retry (%s)" % ", ".join("%s %.2fs" % (v[0], v[1]) for _k, v in sorted(done.items()))))
results.append(ok(not A._feed_flights and "us" not in A._feed_memo,
                  "the failed attempt is not kept once its flight ends"))
A.get_advisories("us")
results.append(ok(calls["us"] == 2, "the next caller after it fetches again (%d)" % calls["us"]))

reset(0)
import server  # noqa: E402
m = re.search(r"advisories\.FEED_MEMO_TTL = (\d+)", inspect.getsource(server.main))
results.append(ok(bool(m) and int(m.group(1)) > 0 and A.FEED_MEMO_TTL == 0,
                  "server.main() turns the memo on (%s s); importing server leaves it off" % (m and m.group(1))))

# --- server.py: serve the copy in hand, one refresh in the background ---------------
WARM_WATCHOUTS = server._warm_watchouts
REAL_GET = A.get_advisories
server._warm_watchouts = lambda iso: None
server.flights.is_configured = lambda: False
fetch = {"n": {}, "delay": 0.0, "fail": False, "hold": None}
stamped = []
_annotate = server.advhistory.record_and_annotate


def fake_get(src):
    fetch["n"][src] = fetch["n"].get(src, 0) + 1
    if fetch["hold"] is not None:
        fetch["hold"].wait(10)
    if fetch["delay"]:
        time.sleep(fetch["delay"])
    if fetch["fail"]:
        raise RuntimeError("%s feed down" % src)
    rows = copy.deepcopy(ROWS[src])
    return {"items": rows, "count": len(rows), "source": src, "source_name": A.SOURCES[src]}


def counted_annotate(src, payload):
    stamped.append(src)
    return _annotate(src, payload)


server.advisories.get_advisories = fake_get
server.advhistory.record_and_annotate = counted_annotate


def settle():
    for _ in range(500):
        with server._adv_warm_lock:
            busy = bool(server._adv_warming)
        with server._adv_flight_lock:
            busy = busy or bool(server._adv_flights)
        if not busy:
            return
        time.sleep(0.01)


def load(age=None, srcs=("us", "ca", "de")):
    """Fresh state; with `age`, each list in hand that many seconds old."""
    settle()
    server._adv_cache.clear()
    server._upstream_fail.clear()
    server._adv_failed.clear()
    fetch.update(n={}, delay=0.0, fail=False, hold=None)
    del stamped[:]
    if age is not None:
        for s_ in srcs:
            rows = copy.deepcopy(ROWS[s_])
            server._adv_cache[s_] = (time.time() - age, {"items": rows, "source": s_, "old": True})


def burst(fn, n=8):
    """n concurrent calls of fn: [(seconds, result or exception)]."""
    out, lock = [], threading.Lock()

    def run():
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            r = e
        with lock:
            out.append((time.time() - t0, r))
    ths = [threading.Thread(target=run) for _ in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(15)
    return out


EXPIRED = server.ADV_TTL + 60
load(EXPIRED)
old = server._adv_cache["us"][1]
fetch["delay"] = 1.0
got = burst(lambda: server._advisories_payload("us"))
slowest = max(t for t, _r in got)
results.append(ok(len(got) == 8 and all(r is old for _t, r in got) and slowest < 0.3,
                  "list past ADV_TTL: 8 concurrent requests get the copy in hand at once, the same object (slowest %.2fs)"
                  % slowest))
time.sleep(0.1)
results.append(ok(fetch["n"] == {"us": 1}, "and exactly one refresh runs (%s)" % fetch["n"]))
settle()
new = server._adv_cache["us"][1]
results.append(ok(new is not old and "old" not in new and server._adv_cache["us"][0] > time.time() - 5
                  and fetch["n"] == {"us": 1} and stamped == ["us"],
                  "afterwards the cache holds a new object, stamped by advhistory once (%s, %s)" % (fetch["n"], stamped)))
results.append(ok(server._advisories_payload("us") is new and fetch["n"] == {"us": 1},
                  "and the next request gets it without a refresh"))

load(EXPIRED)
old_ca = server._adv_cache["ca"][1]
fetch["delay"] = 1.0
t0 = time.time()
payloads, fetched, stale = server._adv_inputs()
took = time.time() - t0
results.append(ok(payloads["ca"] is old_ca and stale == {} and took < 0.3,
                  "/safe-and-cheap's _adv_inputs reads the copies in hand and isn't held by the refreshes (%.2fs)" % took))
settle()
results.append(ok(fetch["n"] == {"us": 1, "ca": 1, "de": 1} and server._adv_cache["ca"][1] is not old_ca,
                  "one refresh per list (%s)" % fetch["n"]))

# A refresh thread that won't start (the process at its thread limit) must not
# fail the request holding a copy, nor leave the list marked as refreshing.
load(EXPIRED)
old = server._adv_cache["us"][1]
real_start = threading.Thread.start


def no_start(self):
    raise RuntimeError("can't start new thread")


threading.Thread.start = no_start
try:
    r = server._advisories_payload("us")
    err = None
except Exception as e:
    r, err = None, e
finally:
    threading.Thread.start = real_start
results.append(ok(err is None and r is old and "us" not in server._adv_warming and "us" not in server._adv_failed,
                  "a refresh thread that can't start: the request still gets the copy, nothing left marked as "
                  "refreshing (%r)" % (err,)))
r = server._advisories_payload("us")
time.sleep(0.1)
settle()
results.append(ok(r is old and fetch["n"] == {"us": 1} and server._adv_cache["us"][1] is not old,
                  "and the next request starts the refresh (%s)" % fetch["n"]))

# The refresh fails: the copy is marked stale, as before.
load(EXPIRED)
old = server._adv_cache["us"][1]
fetch["fail"] = True
first = server._advisories_payload("us")
settle()
fail = server._upstream_fail.get(("advisories", "us"))
results.append(ok(first is old and fail and fail[0] - time.time() > server.STALE_RETRY - 30
                  and "us" not in server._adv_failed and server._adv_cache["us"][1] is old,
                  "a refresh that fails keeps the copy and starts the STALE_RETRY backoff (%s)" % (fail,)))
got = burst(lambda: server._advisories_payload("us"))
time.sleep(0.1)
results.append(ok(all(isinstance(r, dict) and r.get("stale") is True and r.get("stale_age", 0) >= EXPIRED
                      and r["items"] == old["items"] for _t, r in got)
                  and fetch["n"] == {"us": 1} and not server._adv_warming,
                  "inside the backoff: the copy goes out marked stale (stale, stale_age) and no refresh starts (%s)"
                  % fetch["n"]))
payloads, fetched, stale = server._adv_inputs()
results.append(ok(payloads["us"] is old and stale.get("us", 0) >= EXPIRED,
                  "and /safe-and-cheap says the refresh is failing (stale %s), keyed on the cache's own object" % stale))
server._upstream_fail[("advisories", "us")] = (time.time() - 1, "us feed down")
fetch.update(fail=False, delay=0.5)
r = server._advisories_payload("us")
time.sleep(0.1)
results.append(ok(r.get("stale") is True and fetch["n"].get("us") == 2,
                  "the backoff over: still marked stale while one refresh retries (%s)" % fetch["n"]))
settle()
r = server._advisories_payload("us")
results.append(ok("stale" not in r and r is server._adv_cache["us"][1] and r is not old
                  and ("advisories", "us") not in server._upstream_fail,
                  "and once it lands the new list goes out unmarked"))

# Nothing in hand: one computation, everyone waits for it.
load()
fetch["delay"] = 0.5
got = burst(lambda: server._advisories_payload("de"))
objs = {id(r) for _t, r in got}
results.append(ok(len(got) == 8 and len(objs) == 1 and got[0][1] is server._adv_cache["de"][1]
                  and fetch["n"] == {"de": 1} and stamped == ["de"],
                  "nothing in hand: 8 concurrent requests, one computation, all get its list (%s)" % fetch["n"]))
load()
fetch.update(delay=0.5, fail=True)
got = burst(lambda: server._advisories_payload("de"))
fail = server._upstream_fail.get(("advisories", "de"))
results.append(ok(all(isinstance(r, RuntimeError) and str(r) == "de feed down" for _t, r in got)
                  and fetch["n"] == {"de": 1} and "de" in server._adv_failed
                  and fail and fail[0] - time.time() <= server.FAIL_RETRY,
                  "it fails: one computation, all 8 get its error, _adv_failed is set, FAIL_RETRY backoff (%s)"
                  % fetch["n"]))
try:
    server._advisories_payload("de")
    again = None
except RuntimeError as e:
    again = str(e)
results.append(ok(again == "de feed down" and fetch["n"] == {"de": 1},
                  "inside that backoff the next request raises without a computation"))

# A computation stuck on the network doesn't hold the others forever.
load()
saved_wait = server.ADV_FLIGHT_WAIT
server.ADV_FLIGHT_WAIT = 0.3
fetch["hold"] = threading.Event()
lead = threading.Thread(target=lambda: burst(lambda: server._advisories_payload("ca"), 1))
lead.start()
time.sleep(0.1)
t0 = time.time()
fetch_hold = fetch["hold"]
threading.Timer(0.6, fetch_hold.set).start()
r = server._advisories_payload("ca")
took = time.time() - t0
lead.join(5)
server.ADV_FLIGHT_WAIT = saved_wait
results.append(ok(isinstance(r, dict) and fetch["n"] == {"ca": 2} and took >= 0.3,
                  "a computation stuck past ADV_FLIGHT_WAIT: the waiting caller computes itself, as before (%.2fs, %s)"
                  % (took, fetch["n"])))

worst = 3 * (3 * server.rates.TIMEOUT + 1.5 + 3)
results.append(ok(server.ADV_FLIGHT_WAIT > worst,
                  "ADV_FLIGHT_WAIT (%ss) outlasts a computation on timing-out feeds (3 x 64.5 = %.1fs), so "
                  "followers don't give up on a leader that is still fetching" % (server.ADV_FLIGHT_WAIT, worst)))

# Cold start with the US feed timing out (T = 0.6 s here, ~65 s in production):
# the boot warm-up leads all three lists, five /api/advisories?source=us
# requests follow, and even those that give up waiting (ADV_FLIGHT_WAIT below
# T here) join the US fetch in flight instead of queueing up their own.
load()
server.advisories.get_advisories = REAL_GET
saved_from, saved_ttl, saved_wait = A._from, A.FEED_MEMO_TTL, server.ADV_FLIGHT_WAIT
us_fetches = [0]


def slow_from(s_):
    if s_ == "us":
        with calls_lock:
            us_fetches[0] += 1
        time.sleep(0.6)
        raise RuntimeError("us timed out")
    rows = copy.deepcopy(ROWS[s_])
    return {"items": rows, "count": len(rows), "source": s_, "source_name": A.SOURCES[s_]}


A._from, A.FEED_MEMO_TTL, A._feed_memo = slow_from, 120, {}
server.ADV_FLIGHT_WAIT = 0.3
server._warm_adv_lists()
time.sleep(0.02)
got = burst(lambda: server._advisories_payload("us"), 5)
settle()
A._from, A.FEED_MEMO_TTL, server.ADV_FLIGHT_WAIT = saved_from, saved_ttl, saved_wait
server.advisories.get_advisories = fake_get
slowest = max(t for t, _r in got)
results.append(ok(len(got) == 5 and all(isinstance(r, RuntimeError) for _t, r in got) and slowest < 1.0
                  and us_fetches[0] <= 2 and "us" in server._adv_failed
                  and isinstance(server._adv_cache.get("ca", (0, None))[1], dict),
                  "cold, US feed timing out: 5 requests all get its error at about one fetch's time "
                  "(slowest %.2fs, US fetches %d), and Canada's list loads beside it" % (slowest, us_fetches[0])))

# Background callers wait for a current list.
load(EXPIRED)
old = server._adv_cache["us"][1]
fetch["delay"] = 0.3
r = server._advisories_payload("us", background=True)
results.append(ok(r is not old and r is server._adv_cache["us"][1] and fetch["n"] == {"us": 1},
                  "background=True (the refresh thread, guide facts) waits for a current list"))
src = inspect.getsource(server.main)
results.append(ok('get_advisories=lambda: _advisories_payload("us", background=True)' in src,
                  "the guide-facts refresher reads the US list with background=True"))
calls_ = re.findall(r"_advisories_payload\((.*?)\)", open(os.path.join(ROOT, "server.py"), encoding="utf-8").read())
results.append(ok(sorted(calls_) == sorted(['"us", background=True', "source", "src", "src, background=True",
                                            "source, background=False"]),
                  "every caller of _advisories_payload is accounted for (%s)" % calls_))
results.append(ok('_cached("advisories"' not in open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
                  .replace('compute = lambda: _cached("advisories"', ""),
                  "nothing reads _cached(\"advisories\", ...) except _adv_compute_once"))

# /api/advisories: the chosen list can't load, another one stands in, read the same way.
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
load(EXPIRED, srcs=("ca",))
old_ca = server._adv_cache["ca"][1]
server._upstream_fail[("advisories", "de")] = (time.time() + 30, "de feed down")
fetch["delay"] = 1.0
t0 = time.time()
body = json.loads(urllib.request.urlopen(BASE + "/api/advisories?source=de", timeout=10).read())
took = time.time() - t0
results.append(ok(body.get("fallback_for") == "de" and body.get("source") == "ca" and took < 0.5
                  and "de" in server._adv_failed,
                  "/api/advisories?source=de, Germany's list failing: Canada's copy in hand stands in at once (%.2fs)"
                  % took))
time.sleep(0.1)
results.append(ok(fetch["n"].get("ca") == 1, "and Canada's list is refreshed once in the background (%s)" % fetch["n"]))
settle()
httpd.shutdown()

# --- server.py: the listen backlog ------------------------------------------------------
m = re.search(r"httpd = (\w+)\(\(host, port\), Handler\)", inspect.getsource(server.main))
cls = getattr(server, m.group(1), None) if m else None
results.append(ok(cls is not None and issubclass(cls, server.ThreadingHTTPServer) and cls.request_queue_size == 128
                  and cls.daemon_threads is True,
                  "main() serves with %s: request_queue_size %s, daemon threads"
                  % (m and m.group(1), cls and cls.request_queue_size)))
probe = cls(("127.0.0.1", 0), server.Handler) if cls else None
results.append(ok(probe is not None and probe.request_queue_size == 128, "an instance listens with that backlog"))
if probe:
    probe.server_close()

m = re.search(r"sys\.setswitchinterval\(([0-9.]+)\)", inspect.getsource(server.main))
results.append(ok(bool(m) and float(m.group(1)) <= 0.001 and sys.getswitchinterval() >= 0.004,
                  "main() hands the GIL round every %s s (CPython's 0.005 starved the accept loop behind a "
                  "background parse); importing server leaves it alone" % (m and m.group(1))))

# --- server.py: page slots, /healthz exempt ------------------------------------------------
src = inspect.getsource(server.main)
results.append(ok(server._page_slots is None and server.PAGE_SLOTS == 3
                  and "_page_slots = threading.BoundedSemaphore(PAGE_SLOTS)" in src,
                  "main() works on at most %d GETs at once; importing server leaves it unbounded" % server.PAGE_SLOTS))
pg = {"running": 0, "peak": 0, "gate": threading.Event()}
pg_lock = threading.Lock()
real_do_get = server.Handler._do_get


def fake_do_get(self):
    if self.path == "/healthz":
        return real_do_get(self)
    with pg_lock:
        pg["running"] += 1
        pg["peak"] = max(pg["peak"], pg["running"])
    try:
        pg["gate"].wait(10)
        body = b"page"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    finally:
        with pg_lock:
            pg["running"] -= 1


server.Handler._do_get = fake_do_get
server.Handler.log_message = lambda self, *a: None
server._page_slots = threading.BoundedSemaphore(server.PAGE_SLOTS)
httpd = server._Server(("127.0.0.1", 0), server.Handler)   # main()'s backlog: 5 resets a burst on macOS
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
codes, codes_lock = [], threading.Lock()


def get_page(path):
    try:
        c = urllib.request.urlopen(BASE + path, timeout=10).status
    except Exception as e:
        c = repr(e)
    with codes_lock:
        codes.append(c)


ths = [threading.Thread(target=get_page, args=("/guide/x?%d" % i,)) for i in range(8)]
for t in ths:
    t.start()
time.sleep(0.4)
t0 = time.time()
hz = urllib.request.urlopen(BASE + "/healthz", timeout=5).read()
hz_took = time.time() - t0
held = pg["running"]
pg["gate"].set()
for t in ths:
    t.join(10)
results.append(ok(held == 3 and hz == b"ok" and hz_took < 0.5,
                  "8 pages at once: 3 worked on, the rest wait, and /healthz answers past them (%d running, %.2fs)"
                  % (held, hz_took)))
results.append(ok(codes == [200] * 8 and pg["peak"] == 3, "all 8 answered once slots free up (peak %d, %s)" % (pg["peak"], codes)))
pg.update(peak=0, gate=threading.Event())
del codes[:]
saved_wait = server.PAGE_SLOT_WAIT
server.PAGE_SLOT_WAIT = 0.3
ths = [threading.Thread(target=get_page, args=("/guide/y?%d" % i,)) for i in range(4)]
for t in ths:
    t.start()
time.sleep(0.8)
over = pg["running"]
pg["gate"].set()
for t in ths:
    t.join(10)
server.PAGE_SLOT_WAIT = saved_wait
results.append(ok(over == 4 and codes == [200] * 4,
                  "3 slots held by stuck requests: a 4th runs anyway after PAGE_SLOT_WAIT (%d running)" % over))

# Requests waiting on another thread's work (a cold list the boot warm-up is
# computing) give their slots back while they wait.
idle = {"ev": threading.Event(), "waiting": 0, "after": []}


def waiting_do_get(self):
    if not self.path.startswith("/wait"):
        return fake_do_get(self)
    with pg_lock:
        idle["waiting"] += 1
    server._idle_wait(idle["ev"], 5)
    with pg_lock:
        idle["waiting"] -= 1
        idle["after"].append(getattr(server._slot_held, "slots", None) is server._page_slots)
    body = b"waited"
    self.send_response(200)
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)


server.Handler._do_get = waiting_do_get
pg.update(peak=0, gate=threading.Event())
pg["gate"].set()
del codes[:]
server.PAGE_SLOT_WAIT = 5
ths = [threading.Thread(target=get_page, args=("/wait?%d" % i,)) for i in range(3)]
for t in ths:
    t.start()
for _ in range(100):
    if idle["waiting"] == 3:
        break
    time.sleep(0.01)
t0 = time.time()
get_page("/guide/z")
took = time.time() - t0
idle["ev"].set()
for t in ths:
    t.join(10)
server.PAGE_SLOT_WAIT = saved_wait
results.append(ok(took < 0.5 and codes[0] == 200,
                  "3 requests waiting on another thread's computation hold no slot: a page runs at once (%.2fs)" % took))
results.append(ok(sorted(codes) == [200] * 4 and idle["after"] == [True] * 3
                  and server._page_slots._value == server.PAGE_SLOTS,
                  "they take their slots back after the wait, and every slot is free at the end"))
httpd.shutdown()
httpd.server_close()
server.Handler._do_get = real_do_get
server._page_slots = None

# --- server.py: Canada's notes, two fetches at a time ------------------------------------
server._warm_watchouts = WARM_WATCHOUTS
wo = {"running": 0, "peak": 0, "done": [], "gate": threading.Event()}
wo_lock = threading.Lock()


def fake_watchouts(iso):
    with wo_lock:
        wo["running"] += 1
        wo["peak"] = max(wo["peak"], wo["running"])
    try:
        wo["gate"].wait(5)
        time.sleep(0.05)
        if iso == "XB":
            raise RuntimeError("notes down")
        return {"iso": iso}
    finally:
        with wo_lock:
            wo["running"] -= 1
            wo["done"].append(iso)


server.watchouts.get_watchouts = fake_watchouts
ISOS = ["JP", "TH", "VN", "MA", "XB", "CL", "EG", "PE", "MX", "IN"]
threads0 = threading.active_count()
for iso in ISOS:
    server._warm_watchouts(iso)
for iso in ISOS + ["jp", "th", "", None]:
    server._warm_watchouts(iso)
grown = threading.active_count() - threads0
queued = len(server._watchouts_warming)
wo["gate"].set()
for _ in range(300):
    with server._watchouts_lock:
        idle = not server._watchouts_warming and not server._watchouts_workers[0]
    if idle:
        break
    time.sleep(0.02)
results.append(ok(grown <= 2 and queued == 10,
                  "10 guides' notes asked for, twice over: %d threads started, 10 countries queued or in flight (%d)"
                  % (grown, queued)))
results.append(ok(sorted(wo["done"]) == sorted(ISOS) and wo["peak"] <= 2 and wo["peak"] == 2,
                  "all 10 fetched once, a failing one included, never more than 2 at once (peak %d, %d fetches)"
                  % (wo["peak"], len(wo["done"]))))
results.append(ok(idle and not server._watchouts_queue, "the queue drains and the workers exit"))
server._warm_watchouts("JP")
for _ in range(100):
    if wo["done"].count("JP") == 2:
        break
    time.sleep(0.02)
results.append(ok(wo["done"].count("JP") == 2, "once done, a country can be fetched again (the next miss)"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

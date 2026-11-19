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
    a computation stuck past ADV_FLIGHT_WAIT doesn't hold the others (with
    the feed memo on too: a feed parse stuck past FEED_FLIGHT_WAIT is not
    joined, the caller fetches the feed itself); the
    background callers (the refresh thread, the guide-facts refresher) wait
    for a current list; /api/advisories' fallback for a list that can't load
    reads the other lists the same way.
  * server.py main() listens with a backlog of 128 (socketserver's 5 let
    Linux drop the health check's connection) and keeps daemon threads, and
    sets a 0.1 ms GIL switch interval. It renders at most 2 server-side
    pages at once (GET or HEAD); static files, /api/* and /healthz never wait
    for a slot; a page that waits PAGE_SLOT_WAIT for one, or arrives to find
    PAGE_QUEUE_MAX already waiting (at once), is shed: 503, Retry-After,
    no-store, a small page (HEAD: no body), never rendered; and a
    slotted page waiting on the network (another thread's computation, /data's
    dataset rebuild, a cold advisory list) gives its slot back meanwhile and,
    if it can't get one back within PAGE_SLOT_WAIT, finishes without it; a
    list page leading a cold list's computation releases its followers when
    the list (or its error) lands, before it queues for its slot again.
  * server.py _warm_watchouts: ten guides' Canada notes are all fetched, never
    more than two at once, with no thread per guide; a country already queued
    or in flight is not queued again; a fetch that raises doesn't stop the
    queue.
  * scripts/dev/stall_check.py: a burst page times out only when the run
    ends (--page-timeout to set it), so a slow cold page reports its time;
    --rate R sends request i at i/R s (open loop), --gzip asks for gzip, the
    docstring gives the Nov 16 replay, and the FX history's pieces are cut
    from the recorded whole reply.
  * cheaper pages: the country centroids are computed once per process
    (fare_context's own default still computes them, the newsletter's path);
    the default origin's flight-value build is memoized exactly on what it
    reads (fares, every route curve, the day, the next moment a curve goes
    due or stale); text responses gzip at level 6; with the page memo on
    (main()), a public guide or homepage is rendered once and handed out
    again, GET, HEAD and any query string alike, with the very bytes and
    headers as before, until an input is replaced, the day turns, its
    Cache-Control would change or PAGE_MEMO_TTL passes (no-store pages are
    never kept; at most PAGE_MEMO_MAX); an input that raises when read (a
    flight-value build on a bad curve) never costs the page: it is rendered
    as with the memo off and not kept, with one [page-memo] line.
  * fxtracker/rates.py get_history: the first fetch is the whole history,
    in 5-year pieces each of which must reach both its ends; a copy in hand
    is brought up to date from its last 10 days on, falling back to the
    whole history when the reply disagrees with the copy, skips a day of it
    or has a day it lacks; INDEX_MASK, HISTORY_STALE and the failure backoff
    as before (recorded reply, scripts/fixtures/fx_history/).
  * logging: a client hanging up mid-response is one [disconnect] line, any
    other exception keeps its traceback; /healthz carries X-Uptime and writes
    its log line after its answer; [busy] lines (at most one per
    BUSY_LOG_EVERY) count shed, slotless and deep-queued requests; [refresh]
    lines time the advisory, rates and FX history refreshes.
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
    getattr(server, "_adv_refresh_failing", set()).clear()
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

# The refresh fails: the copy is marked stale, as before. (The upstream takes
# 50 ms to fail, as a real one would: failing at once, the refresh thread
# could mark the list failing before this request had read it.)
load(EXPIRED)
old = server._adv_cache["us"][1]
fetch.update(fail=True, delay=0.05)
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

# A refresh failing, its backoff over, and an unrelated cache's failure (rates,
# flights) prunes the expired _upstream_fail record: the next request still
# gets the copy marked stale, as main's inline retry would have returned it.
load(EXPIRED)
old = server._adv_cache["us"][1]
fetch["fail"] = True
server._advisories_payload("us")
settle()
had = ("advisories", "us") in server._upstream_fail
server._upstream_fail[("advisories", "us")] = (time.time() - 1, "us feed down")   # backoff over


def rates_down():
    raise RuntimeError("rates down")


try:
    server._cached("rates", {}, ("prune-test",), 600, rates_down)
except RuntimeError:
    pass
pruned = ("advisories", "us") not in server._upstream_fail
server._upstream_fail.pop(("rates", ("prune-test",)), None)
fetch["hold"] = threading.Event()
r = server._advisories_payload("us")
payloads, fetched, stale = server._adv_inputs()
cpay, cfetched, cstale = server._cheap_adv()
fetch["hold"].set()
settle()
results.append(ok(had and pruned and isinstance(r, dict) and r.get("stale") is True
                  and r.get("stale_age", 0) >= EXPIRED and r["items"] == old["items"]
                  and fetch["n"].get("us") == 2,
                  "refresh failing, backoff over, its record pruned by a rates failure: the copy still goes out "
                  "stale (stale_age %s) while one refresh retries (%s)" % (r.get("stale_age"), fetch["n"])))
results.append(ok(stale.get("us", 0) >= EXPIRED and cstale.get("us", 0) >= EXPIRED,
                  "and /safe-and-cheap and /cheapest still say the refresh is failing (%s, %s)" % (stale, cstale)))
fetch["fail"] = False
server._upstream_fail.pop(("advisories", "us"), None)
server._advisories_payload("us")
settle()
r = server._advisories_payload("us")
results.append(ok("stale" not in r and r is server._adv_cache["us"][1] and r is not old
                  and "us" not in getattr(server, "_adv_refresh_failing", {"us"}),
                  "a refresh that lands clears the failing mark: the new list goes out unmarked"))

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

# The same escape with the feed memo on, through the real get_advisories: a
# leader stuck on its US fetch (a trickling response, a DNS hang) past
# ADV_FLIGHT_WAIT, and the follower that gives up on it opens its own fetch,
# as main's per-request compute did, instead of joining the stuck feed flight.
load()
server.advisories.get_advisories = REAL_GET
saved_from, saved_ttl, saved_wait = A._from, A.FEED_MEMO_TTL, server.ADV_FLIGHT_WAIT
us_fetches = [0]
stuck = threading.Event()


def stuck_from(s_):
    if s_ == "us":
        with calls_lock:
            us_fetches[0] += 1
            first = us_fetches[0] == 1
        if first:
            stuck.wait(3)
    rows = copy.deepcopy(ROWS[s_])
    return {"items": rows, "count": len(rows), "source": s_, "source_name": A.SOURCES[s_]}


saved_fwait = A.FEED_FLIGHT_WAIT
A._from, A.FEED_MEMO_TTL, A._feed_memo, A.FEED_FLIGHT_WAIT = stuck_from, 120, {}, 0.35
server.ADV_FLIGHT_WAIT = 0.3
lead = threading.Thread(target=lambda: server._advisories_payload("us"))
lead.start()
time.sleep(0.1)
t0 = time.time()
try:
    r = server._advisories_payload("us")
except Exception as e:
    r = e
took = time.time() - t0
stuck.set()
lead.join(5)
settle()
A._from, A.FEED_MEMO_TTL, server.ADV_FLIGHT_WAIT, A.FEED_FLIGHT_WAIT = saved_from, saved_ttl, saved_wait, saved_fwait
server.advisories.get_advisories = fake_get
results.append(ok(isinstance(r, dict) and took < 1.0 and us_fetches[0] == 2,
                  "feed memo on, the leader's US fetch stuck past FEED_FLIGHT_WAIT: the follower past "
                  "ADV_FLIGHT_WAIT fetches the feed itself, not behind the stuck one (%.2fs, US fetches %d)"
                  % (took, us_fetches[0])))
results.append(ok(A.FEED_FLIGHT_WAIT > 3 * server.rates.TIMEOUT + 1.5 + 3,
                  "FEED_FLIGHT_WAIT (%ss) outlasts one fetch on a timing-out feed (64.5 s), so a caller still "
                  "joins a fetch that is only slow (the cold-start check above)" % A.FEED_FLIGHT_WAIT))

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
results.append(ok(open(os.path.join(ROOT, "server.py"), encoding="utf-8").read().count('_cached("advisories"') == 1
                  and '_cached("advisories"' in inspect.getsource(server._adv_compute_once),
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

sw = getattr(server, "SWITCH_INTERVAL", None)
results.append(ok("sys.setswitchinterval(SWITCH_INTERVAL)" in inspect.getsource(server.main)
                  and isinstance(sw, float) and 0 < sw <= 0.0001 and sys.getswitchinterval() >= 0.004,
                  "main() hands the GIL round every SWITCH_INTERVAL = %s s (CPython's 0.005 starved the accept "
                  "loop behind a background parse); importing server leaves it alone" % sw))

# --- server.py: page slots, /healthz exempt ------------------------------------------------
src = inspect.getsource(server.main)
results.append(ok(server._page_slots is None and server.PAGE_SLOTS == 2
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
TEST_SLOTS = 3     # the slot tests below run on 3 slots, whatever production uses
server._page_slots = threading.BoundedSemaphore(TEST_SLOTS)
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


def fetch_full(path, method="GET"):
    """(status, headers, body, seconds) for one request, an HTTP error included."""
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(BASE + path, method=method), timeout=10)
        return r.status, r.headers, r.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read(), time.time() - t0


def shed_ok(res, method="GET"):
    st, h, body, _took = res
    return (st == 503 and h.get("Retry-After") == str(server.SHED_RETRY_AFTER)
            and h.get("Cache-Control") == "no-store" and h.get("Content-Type", "").startswith("text/html")
            and int(h.get("Content-Length", -1)) == len(server.Handler._BUSY_PAGE)
            and (body == b"" if method == "HEAD" else body == server.Handler._BUSY_PAGE))


# Three stuck renders hold every slot: a 4th page (GET or HEAD) waits
# PAGE_SLOT_WAIT and is then shed with a 503, never rendered (it used to run
# without a slot, and under a long crawl the slotless renders piled up).
pg.update(peak=0, gate=threading.Event())
del codes[:]
saved_wait = server.PAGE_SLOT_WAIT
server.PAGE_SLOT_WAIT = 0.3
ths = [threading.Thread(target=get_page, args=("/guide/y?%d" % i,)) for i in range(3)]
for t in ths:
    t.start()
for _ in range(150):
    if pg["running"] >= 3:
        break
    time.sleep(0.01)
shed_get = fetch_full("/guide/y?3")
shed_head = fetch_full("/guide/y?4", "HEAD")
over = pg["running"]
pg["gate"].set()
for t in ths:
    t.join(10)
server.PAGE_SLOT_WAIT = saved_wait
results.append(ok(over == 3 and pg["peak"] == 3 and shed_ok(shed_get) and shed_ok(shed_head, "HEAD")
                  and 0.25 < shed_get[3] < 1.5 and codes == [200] * 3,
                  "3 slots held by stuck requests: a 4th page waits PAGE_SLOT_WAIT and gets 503 + Retry-After %s + "
                  "no-store, GET with the busy page, HEAD with none, never rendered (%d running, %.2fs, %s)"
                  % (server.SHED_RETRY_AFTER, over, shed_get[3], shed_get[0])))

# PAGE_QUEUE_MAX already waiting: the next arrival is shed at once, and the
# ones waiting are answered when the slots free up.
pg.update(peak=0, gate=threading.Event())
del codes[:]
saved_q, saved_wait = server.PAGE_QUEUE_MAX, server.PAGE_SLOT_WAIT
server.PAGE_QUEUE_MAX, server.PAGE_SLOT_WAIT = 2, 5
ths = [threading.Thread(target=get_page, args=("/guide/q?%d" % i,)) for i in range(5)]
for t in ths:
    t.start()
for _ in range(200):
    if pg["running"] >= 3 and server._slot_waiting[0] >= 2:
        break
    time.sleep(0.01)
waiting_then = server._slot_waiting[0]
fast = fetch_full("/guide/q?5")
fast_head = fetch_full("/cheapest", "HEAD")
pg["gate"].set()
for t in ths:
    t.join(10)
server.PAGE_QUEUE_MAX, server.PAGE_SLOT_WAIT = saved_q, saved_wait
results.append(ok(waiting_then == 2 and shed_ok(fast) and fast[3] < 0.5 and shed_ok(fast_head, "HEAD")
                  and sorted(codes) == [200] * 5 and server._slot_waiting[0] == 0 and pg["peak"] == 3,
                  "3 slots held and PAGE_QUEUE_MAX (2 here) waiting: the next page is shed at once (%.2fs), the "
                  "waiting ones are answered as slots free (%s), the wait count back to %d"
                  % (fast[3], sorted(set(map(str, codes))), server._slot_waiting[0])))
results.append(ok(server.PAGE_SLOTS == 2 and server.PAGE_QUEUE_MAX == 8 and server.PAGE_SLOT_WAIT == 15
                  and server.SHED_RETRY_AFTER == 30,
                  "production: %d slots, 503 past %d waiting or %d s of waiting, Retry-After %d"
                  % (server.PAGE_SLOTS, server.PAGE_QUEUE_MAX, server.PAGE_SLOT_WAIT, server.SHED_RETRY_AFTER)))

# Only the routes that render server-side take a slot (CPU); static files,
# /api/* (which may sit on an upstream: flights, rates, Upstash) and /healthz
# never wait for one, GET or HEAD alike, even with every slot held.
slot_route = getattr(server, "_slot_route", None)
SLOTTED = ["/", "/guide/japan", "/guide/Japan", "/guide/", "/data", "/safe-and-cheap", "/do-not-travel",
           "/cheapest", "/cheapest/january", "/dollar-strength", "/privacy", "/sitemap.xml", "/llms.txt",
           "/ppp.json", "/pl_history.json"]
FREE = ["/healthz", "/robots.txt", "/app.js", "/styles.css", "/og.png", "/health.json", "/guide-facts.json",
        "/index.html", "/Cheapest", "/data/", "/data/price-levels.json", "/data/price-levels.csv",
        "/auth/verify", "/api/rates", "/api/index", "/api/advisories", "/api/flights", "/api/flight-months",
        "/api/flight-value", "/api/fx-trend", "/api/watchouts", "/api/popularity", "/api/geo",
        "/api/auth/me", "/api/config", "/api/flight-origins"]
wrong = [p for p in SLOTTED if not (slot_route and slot_route(p))] + \
        [p for p in FREE if not slot_route or slot_route(p)]
results.append(ok(slot_route is not None and not wrong,
                  "page slots for server-rendered pages only: %d routes take one, %d never do (wrong: %s)"
                  % (len(SLOTTED), len(FREE), wrong)))


def head_page(path):
    try:
        c = urllib.request.urlopen(urllib.request.Request(BASE + path, method="HEAD"), timeout=10).status
    except Exception as e:
        c = repr(e)
    with codes_lock:
        codes.append(c)


def running_reaches(n, secs=1.5):
    for _ in range(int(secs / 0.01)):
        if pg["running"] >= n:
            return True
        time.sleep(0.01)
    return False


pg.update(peak=0, gate=threading.Event())
del codes[:]
ths = [threading.Thread(target=get_page, args=("/guide/s?%d" % i,)) for i in range(3)]
for t in ths:
    t.start()
running_reaches(3)
FREE_GETS = ["/app.js", "/robots.txt?x=1", "/styles.css?v=9", "/api/rates", "/api/flights?origin=US",
             "/api/watchouts?iso=JP", "/api/auth/me", "/data/price-levels.json"]
FREE_HEADS = ["/og.png", "/api/flight-months?iso=JP"]
more = [threading.Thread(target=get_page, args=(p,)) for p in FREE_GETS] + \
       [threading.Thread(target=head_page, args=(p,)) for p in FREE_HEADS]
for t in more:
    t.start()
free_ran = running_reaches(3 + len(more))
free_running = pg["running"]
pages = [threading.Thread(target=get_page, args=("/safe-and-cheap?q=1",)),
         threading.Thread(target=head_page, args=("/guide/peru",))]
for t in pages:
    t.start()
time.sleep(0.4)
page_running = pg["running"]
t0 = time.time()
hz = urllib.request.urlopen(BASE + "/healthz", timeout=5).read()
hz_took = time.time() - t0
pg["gate"].set()
for t in ths + more + pages:
    t.join(10)
results.append(ok(free_ran and free_running == 3 + len(more),
                  "3 slots held by pages: %d static and /api requests (GET and HEAD) run at once anyway "
                  "(%d running)" % (len(more), free_running)))
results.append(ok(page_running == free_running and hz == b"ok" and hz_took < 0.5,
                  "a page (GET /safe-and-cheap, HEAD /guide/peru) still waits for a slot, and /healthz "
                  "answers past them all (%d running, %.2fs)" % (page_running, hz_took)))
results.append(ok(sorted(codes) == [200] * (5 + len(more)),
                  "and all %d are answered once the slots free up (%s)" % (5 + len(more), sorted(set(map(str, codes))))))

# Requests waiting on another thread's work (a cold list the boot warm-up is
# computing) give their slots back while they wait.
idle = {"ev": threading.Event(), "waiting": 0, "after": []}


def waiting_do_get(self):
    if "wait=" not in self.path:
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
ths = [threading.Thread(target=get_page, args=("/do-not-travel?wait=%d" % i,)) for i in range(3)]
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
for _ in range(100):      # a handler releases its slot just after the client has its response
    if server._page_slots._value == TEST_SLOTS:
        break
    time.sleep(0.01)
results.append(ok(took < 0.5 and codes[0] == 200,
                  "3 requests waiting on another thread's computation hold no slot: a page runs at once (%.2fs)" % took))
results.append(ok(sorted(codes) == [200] * 4 and idle["after"] == [True] * 3
                  and server._page_slots._value == TEST_SLOTS,
                  "they take their slots back after the wait, and every slot is free at the end (%s, %s, %d free)"
                  % (codes, idle["after"], server._page_slots._value)))

# Taking the slot back is not an arrival: with every slot held by stuck renders
# and the queue full, a page whose inline wait has ended still waits its turn
# (no fast 503), and past PAGE_SLOT_WAIT it finishes without a slot rather than
# throwing away the work it has paid for.
idle.update(ev=threading.Event(), waiting=0, after=[])
pg.update(peak=0, gate=threading.Event())
del codes[:]
saved_q = server.PAGE_QUEUE_MAX
server.PAGE_SLOT_WAIT, server.PAGE_QUEUE_MAX = 0.4, 0
waiter = threading.Thread(target=get_page, args=("/do-not-travel?wait=x",))
waiter.start()
for _ in range(100):
    if idle["waiting"] == 1:
        break
    time.sleep(0.01)
holders = [threading.Thread(target=get_page, args=("/guide/h?%d" % i,)) for i in range(3)]
for t in holders:
    t.start()
running_reaches(3)
t0 = time.time()
idle["ev"].set()
waiter.join(10)
back_took = time.time() - t0
pg["gate"].set()
for t in holders:
    t.join(10)
server.PAGE_SLOT_WAIT, server.PAGE_QUEUE_MAX = saved_wait, saved_q
for _ in range(100):
    if server._page_slots._value == TEST_SLOTS:
        break
    time.sleep(0.01)
results.append(ok(codes and codes[0] == 200 and idle["after"] == [False] and 0.35 < back_took < 2
                  and sorted(codes) == [200] * 4 and server._page_slots._value == TEST_SLOTS,
                  "a page back from its inline wait with every slot held and the queue full is not shed: it waits "
                  "PAGE_SLOT_WAIT for its slot, then finishes without one (%.2fs, %s, slot %s)"
                  % (back_took, codes[:1], idle["after"])))
httpd.shutdown()
httpd.server_close()
server.Handler._do_get = real_do_get

# The two inline network waits on a slotted route run without the slot: /data
# rebuilding its dataset (a rates fetch), and a list page computing an
# advisory list not in hand at all. The slot is held again afterwards.
for _ in range(100):
    if server._page_slots._value == TEST_SLOTS:
        break
    time.sleep(0.01)
sem = server._page_slots
seen = {}


def holding(tag):
    seen[tag] = (getattr(server._slot_held, "slots", None) is sem, sem._value)


def fake_build(ppp):
    holding("dataset")
    return {"countries": [], "meta": {}}


saved = (server.build_dataset.build, server.build_dataset.to_csv, dict(server._ppp_cache),
         dict(server._dataset_cache))
server.build_dataset.build, server.build_dataset.to_csv = fake_build, lambda payload: ""
server._ppp_cache.update(at=time.time(), data={"JP": {}})   # no PPP refresh thread
server._dataset_cache.update(at=0, payload=None, csv=None)
sem.acquire()
server._slot_held.slots = sem
try:
    server._dataset()
    holding("dataset_after")
    load()

    def get_watched(src):
        holding("adv")
        return fake_get(src)

    server.advisories.get_advisories = get_watched
    server._advisories_payload("us")
    holding("adv_after")
finally:
    server.advisories.get_advisories = fake_get
    if getattr(server._slot_held, "slots", None) is sem:
        server._slot_held.slots = None
        sem.release()
    server.build_dataset.build, server.build_dataset.to_csv = saved[0], saved[1]
    server._ppp_cache.clear()
    server._ppp_cache.update(saved[2])
    server._dataset_cache.update(saved[3])
results.append(ok(seen.get("dataset") == (False, 3) and seen.get("dataset_after") == (True, 2),
                  "/data's dataset rebuild (a rates fetch) runs without the request's slot, then takes it back (%s, %s)"
                  % (seen.get("dataset"), seen.get("dataset_after"))))
results.append(ok(seen.get("adv") == (False, 3) and seen.get("adv_after") == (True, 2),
                  "so does a list page computing an advisory list not in hand (%s, %s)"
                  % (seen.get("adv"), seen.get("adv_after"))))

# A slotted page leading a cold list's computation hands the outcome to its
# followers before it queues for its slot again: a crawler's guide holding
# the freed slot delays the leader only, not a slotless /api/advisories
# request waiting on the same list (that list already in _adv_cache).


def leader_follower(fail):
    load()
    fetch.update(delay=0.5, fail=fail)
    one = threading.BoundedSemaphore(1)
    saved_slots, saved_wait_ = server._page_slots, server.PAGE_SLOT_WAIT
    server._page_slots, server.PAGE_SLOT_WAIT = one, 5
    out = {}

    def leader():
        one.acquire()
        server._slot_held.slots = one
        try:
            try:
                server._advisories_payload("us")
            except RuntimeError:
                pass
            out["leader_slot"] = getattr(server._slot_held, "slots", None) is one
        finally:
            if getattr(server._slot_held, "slots", None) is one:
                server._slot_held.slots = None
                one.release()

    def hog():                       # a guide render grabbing the slot the leader gave back
        time.sleep(0.05)
        one.acquire()
        time.sleep(2.0)
        one.release()

    def follower():                  # /api/advisories?source=us: no slot
        time.sleep(0.15)
        t = time.time()
        try:
            r = server._advisories_payload("us")
        except RuntimeError as e:
            r = e
        out["follower"] = (time.time() - t, r)

    ths = [threading.Thread(target=f) for f in (leader, hog, follower)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(10)
    server._page_slots, server.PAGE_SLOT_WAIT = saved_slots, saved_wait_
    return out


# A failed dataset rebuild is remembered for a moment: /data reads the
# dataset three times per view (_data_desc, _rates_as_of, _data_page_body),
# and with no copy each read rebuilt (a rates fetch with its retries), giving
# its slot back and queueing for it again each time.
ds = {"n": 0, "fail": True}


def counted_build(ppp):
    ds["n"] += 1
    if ds["fail"]:
        raise RuntimeError("rates down")
    return {"countries": [{}] * 2, "meta": {"rates_as_of": "2026-11-17"}}


saved = (server.build_dataset.build, server.build_dataset.to_csv, dict(server._ppp_cache),
         dict(server._dataset_cache))
server.build_dataset.build, server.build_dataset.to_csv = counted_build, lambda payload: "csv"
server._ppp_cache.update(at=time.time(), data={"JP": {}})
try:
    server._dataset_cache.update(at=0, payload=None, csv=None)
    errs = []
    for _ in range(3):
        try:
            server._dataset()
        except RuntimeError as e:
            errs.append(str(e))
    no_copy = (ds["n"], errs)
    body = server._data_page_body()
    no_copy_page = ds["n"]
    server._dataset_cache["retry_at"] = 0          # the backoff runs out
    ds["fail"] = False
    back = server._dataset()["payload"]["countries"]
    after_back = ds["n"]
    server._dataset_cache["at"] = time.time() - server._DATASET_TTL - 1    # the copy past its hour
    ds["fail"] = True
    stale = [len(server._dataset()["payload"]["countries"]) for _ in range(3)]
    stale_n = ds["n"] - after_back
finally:
    server.build_dataset.build, server.build_dataset.to_csv = saved[0], saved[1]
    server._ppp_cache.clear()
    server._ppp_cache.update(saved[2])
    server._dataset_cache.clear()
    server._dataset_cache.update(saved[3])
results.append(ok(no_copy == (1, ["rates down"] * 3) and no_copy_page == 1 and "__N__" not in body,
                  "a dataset rebuild that fails with no copy is tried once, then each read raises its error inside "
                  "FAIL_RETRY, and /data's page reads it without rebuilding (%s rebuilds)" % no_copy_page))
results.append(ok(len(back) == 2 and after_back == 2 and stale == [2, 2, 2] and stale_n == 1,
                  "past the backoff it rebuilds; with a copy past its hour a failed rebuild is tried once and the "
                  "copy served (%d rebuild, %s)" % (stale_n, stale)))

# A list page with all three lists cold gives its slot back and queues for it
# again once, not once per list: each re-take goes to the back of the slot
# queue, behind a crawler's guides.


class CountSem(threading.BoundedSemaphore):
    def __init__(self, n):
        super().__init__(n)
        self.takes = 0

    def acquire(self, *a, **k):
        self.takes += 1
        return super().acquire(*a, **k)


load()
fetch["delay"] = 0.05
cs = CountSem(3)
cs.acquire()
cs.takes = 0
server._slot_held.slots = cs
try:
    payloads, _f, _s = server._adv_inputs()
    held_after = getattr(server._slot_held, "slots", None) is cs
finally:
    if getattr(server._slot_held, "slots", None) is cs:
        server._slot_held.slots = None
        cs.release()
results.append(ok(cs.takes == 1 and held_after and all(isinstance(payloads[s_], dict) for s_ in ("us", "ca", "de"))
                  and fetch["n"] == {"us": 1, "ca": 1, "de": 1},
                  "/safe-and-cheap with the three lists cold: the slot is given back and taken again once, "
                  "not once per list (%d re-takes)" % cs.takes))
load(EXPIRED)
cs.acquire()
cs.takes = 0
server._slot_held.slots = cs
try:
    server._adv_inputs()
finally:
    server._slot_held.slots = None
    cs.release()
settle()
results.append(ok(cs.takes == 0, "and with the three in hand it keeps its slot throughout (%d re-takes)" % cs.takes))

lf = leader_follower(False)
took, r = lf.get("follower", (99, None))
results.append(ok(took < 1.0 and isinstance(r, dict) and fetch["n"] == {"us": 1} and lf.get("leader_slot"),
                  "a list page leading a cold list's computation releases its followers when the list lands, "
                  "not when its slot frees up (slotless follower %.2fs, compute 0.5s, slot held 2s)" % took))
lf = leader_follower(True)
took, r = lf.get("follower", (99, None))
results.append(ok(took < 1.0 and isinstance(r, RuntimeError) and fetch["n"] == {"us": 1},
                  "and its error likewise (%.2fs, %r)" % (took, r)))
server._page_slots = None

# --- scripts/dev/stall_check.py: a slow burst page reports its time ------------------------
# A fixed 40 s cap cut off the cold start's advisory pages (answered at 51-52 s
# on this branch, never on main) on both trees alike.
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location("stall_check", os.path.join(ROOT, "scripts", "dev", "stall_check.py"))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
pt = getattr(sc, "page_timeout_for", None)
run_src = inspect.getsource(sc.run)
results.append(ok(pt is not None and pt(50, sc.BURST_AT) == 50 - sc.BURST_AT - 2 and pt(70, sc.BURST_AT) > 55
                  and "page_timeout_for(life, burst_at)" in run_src and "--page-timeout" in inspect.getsource(sc.main),
                  "stall_check's burst timeout runs as long as the run allows (%s s at --life 50, %s s at 70), "
                  "and --page-timeout sets it" % (pt and pt(50, sc.BURST_AT), pt and pt(70, sc.BURST_AT))))
# The FX history's pieces are cut from the recorded whole reply, so a replay
# boots with the history as production does.
import tempfile  # noqa: E402
import hashlib as _hl  # noqa: E402
from fxtracker import rates as _R0  # noqa: E402
nc = tempfile.mkdtemp(prefix="stall_nc_")
_whole = _R0._history_url(_R0.HISTORY_START)
_fx_days = {"1999-01-04": {"EUR": 0.85}, "2001-06-01": {"EUR": 1.1}, "2004-03-01": {"EUR": 0.8},
            "2025-02-03": {"EUR": 0.96}, "2026-11-13": {"EUR": 0.9}}
with open(os.path.join(nc, _hl.sha1(_whole.encode()).hexdigest() + ".body"), "w") as f:
    json.dump({"base": "USD", "rates": _fx_days}, f)
with open(os.path.join(nc, _hl.sha1(_whole.encode()).hexdigest() + ".json"), "w") as f:
    json.dump({"status": 200, "headers": {"Content-Type": "application/json"}}, f)
fp = getattr(sc, "frankfurter_pieces", None)
try:
    pcs = fp(nc, ROOT) if fp else {}
finally:
    import shutil  # noqa: E402
    shutil.rmtree(nc, ignore_errors=True)
first_piece = json.loads(pcs[_R0._history_url("1999-01-04", "2003-12-31")][0]) if pcs else {}
last_piece = json.loads(pcs[_R0._history_url("2024-01-01")][0]) if pcs else {}
results.append(ok(len(pcs) == 3 and sorted(first_piece.get("rates", {})) == ["1999-01-04", "2001-06-01"]
                  and sorted(last_piece.get("rates", {})) == ["2025-02-03", "2026-11-13"]
                  and "pieces[url]" in inspect.getsource(sc.serve),
                  "stall_check cuts the FX history's 5-year pieces from the recorded whole reply (%d with days here)"
                  % len(pcs)))
# --rate R: the Nov 16 crawl (2.8 guides a second) as open-loop arrivals on a
# fixed schedule, and --gzip pages that pay their compression as production's do.
ao = getattr(sc, "arrival_offsets", None)
main_src = inspect.getsource(sc.main)
results.append(ok(ao is not None and ao(4, 2.0) == [0.0, 0.5, 1.0, 1.5] and len(ao(130, 2.8)) == 130
                  and abs(ao(130, 2.8)[-1] - 129 / 2.8) < 1e-9
                  and "arrival_offsets(len(work), rate)" in run_src and "--rate" in main_src
                  and "--gzip" in main_src and '"Accept-Encoding": "gzip"' in run_src
                  and "--crawl 130 --rate 2.8 --burst-at 45 --life 110 --on-ms 2" in sc.__doc__,
                  "stall_check --rate R sends request i at i/R s whether or not the others are answered "
                  "(130 at 2.8/s over %.1f s), --gzip asks for gzip, and the docstring gives the Nov 16 replay"
                  % (ao(130, 2.8)[-1] if ao else -1)))

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

# --- fxtracker: the country centroids, once per process ------------------------------
# A guide's grades and the homepage's picks estimate every country's fare by
# distance (picks.fare_context); the centroids behind it were recomputed from
# world.geojson on every render (9.5 ms of a 15.8 ms guide).
import datetime  # noqa: E402
from fxtracker import geo, guide_lines, home_picks, picks, render_cheapest  # noqa: E402
PARITY = os.path.join(ROOT, "scripts", "parity")
jl = lambda *p: json.load(open(os.path.join(ROOT, *p), encoding="utf-8"))
fx_inputs = {"rates": jl("scripts", "parity", "fixture_rates.json"), "ppp": jl("public", "ppp.json"),
             "climate": jl("public", "climate.json"), "activities": jl("public", "activities.json"),
             "advisories": jl("scripts", "parity", "fixture_advisories.json"),
             "flights": jl("scripts", "parity", "fixture_flights.json"),
             "fv": jl("scripts", "parity", "fixture_flight_value.json")}
fresh_c = geo.country_centroids()
cc_calls, fc_seen = [0], []
real_cc, real_fc = geo.country_centroids, picks.fare_context


def counting_cc(world=None):
    cc_calls[0] += 1
    return real_cc(world)


def watching_fc(data, centroids=None):
    fc_seen.append(centroids)
    return real_fc(data, centroids)


site_c = geo.site_centroids()
geo.country_centroids, picks.fare_context = counting_cc, watching_fc
try:
    scores = [guide_lines.score(iso, fx_inputs, 3) for iso in ("JP", "TH", "PE")]
    hp = home_picks.build(dict(fx_inputs, popular=set()), {}, datetime.date(2026, 11, 18))
    cheap_c = render_cheapest.centroids()
finally:
    geo.country_centroids, picks.fare_context = real_cc, real_fc
results.append(ok(site_c == fresh_c and geo.site_centroids() is site_c and cheap_c is site_c and cc_calls[0] == 0
                  and len(fc_seen) == 4 and all(c is site_c for c in fc_seen) and all(scores),
                  "the guide grades (3 renders) and the home picks score with the centroids computed once per "
                  "process, equal to a fresh computation (%d recomputes, %d fare contexts)" % (cc_calls[0], len(fc_seen))))
results.append(ok("geo.country_centroids()" in inspect.getsource(picks.fare_context),
                  "picks.fare_context without centroids still computes them fresh (the newsletter build's path)"))

# --- server.py: the default origin's flight-value build, memoized ----------------------
# Twice per guide and per home render at 1.3 ms a call; the memo must hand back
# exactly what a fresh build would: same fares object, same curves, same day,
# and no curve gone due or stale since.
from fxtracker import flights as FL, flightvalue as FV  # noqa: E402
saved_fl = (FL.is_configured, dict(FL._monthly_cache), FL._cities, FV.build, server._fv_memo[0], server.datetime)
FL.is_configured, FL._cities = (lambda: True), {}
fv_calls = [0]


def counted_fvb(*a, **k):
    fv_calls[0] += 1
    return saved_fl[3](*a, **k)


try:
    FV.build = counted_fvb
    fares_fx = copy.deepcopy(fx_inputs["flights"])
    hub = FL.ORIGIN_HUBS["US"][0]
    per_city = {}
    for _iso, c_ in fx_inputs["fv"]["countries"].items():
        for m_, (price, city) in (c_.get("curve") or {}).items():
            per_city.setdefault(city, {})[m_] = {"price": price, "stops": 0, "departure_at": m_ + "-28T10:00:00Z"}
    FL._monthly_cache.clear()
    now_ = time.time()
    for row in fares_fx["countries"]:
        for city in FL.country_cities(row):
            FL._monthly_cache[(hub, city, "usd")] = (now_, now_, {"configured": True, "origin": "US", "hub": hub,
                                                                  "dest": city, "currency": "usd",
                                                                  "months": dict(per_city.get(city, {}))}, False)
    server._fv_memo[0] = None
    a1, a2 = server._fv_build(fares_fx), server._fv_build(fares_fx)
    fresh_fv = saved_fl[3]("US", fares_fx)
    same = (a1 is a2 and a1 == fresh_fv and fv_calls[0] == 1 and a1["ready"] > 50)
    # one curve rewritten (a refresh landed): rebuilt, and the change shows
    k0 = next(k for k, e in FL._monthly_cache.items() if e[2]["months"])
    e0 = FL._monthly_cache[k0]
    m0 = sorted(e0[2]["months"])[-1]
    FL._monthly_cache[k0] = (e0[0], e0[1], dict(e0[2], months=dict(e0[2]["months"], **{m0: dict(
        e0[2]["months"][m0], price=e0[2]["months"][m0]["price"] + 999)})), False)
    b1 = server._fv_build(fares_fx)
    rewritten = fv_calls[0] == 2 and b1 is not a1 and b1 == saved_fl[3]("US", fares_fx) and b1 != a1
    # a refreshed fares payload with the same content is a new object: rebuilt
    c1 = server._fv_build(copy.deepcopy(fares_fx))
    new_fares = fv_calls[0] == 3 and c1 == b1
    # a curve going due with no write (refresh count 0 -> 1): rebuilt once it has
    e1 = FL._monthly_cache[k0]
    FL._monthly_cache[k0] = (time.time() - FL.MONTHLY_TTL + 0.3,) + e1[1:]
    d1 = server._fv_build(fares_fx)
    d2 = server._fv_build(fares_fx)
    time.sleep(0.4)
    d3 = server._fv_build(fares_fx)
    gone_due = (d1 is d2 and d1["refresh"] == 0 and d3["refresh"] >= 1 and d3 == saved_fl[3]("US", fares_fx)
                and fv_calls[0] == 5)
    d4 = server._fv_build(fares_fx)      # already due: nothing ahead changes it, so it is kept again
    still = d4 is d3 and fv_calls[0] == 5

    class Tomorrow(saved_fl[5]):
        @classmethod
        def now(cls, tz=None):
            return saved_fl[5].fromtimestamp(time.time() + 86400, tz)

    server.datetime = Tomorrow
    server._fv_build(fares_fx)
    new_day = fv_calls[0] == 6
finally:
    FL.is_configured, FL._cities, FV.build, server.datetime = saved_fl[0], saved_fl[2], saved_fl[3], saved_fl[5]
    FL._monthly_cache.clear()
    FL._monthly_cache.update(saved_fl[1])
    server._fv_memo[0] = saved_fl[4]
results.append(ok(same, "the default origin's flight-value build is built once and handed out again while nothing "
                        "it reads has changed, equal to a fresh build (%d builds, %d ready)" % (1, a1["ready"])))
results.append(ok(rewritten and new_fares,
                  "a rewritten route curve, or a new fares payload, rebuilds it, and the rebuild shows the change"))
results.append(ok(gone_due and still, "a curve going due with no write rebuilds it once that moment passes "
                  "(refresh %d -> %d), and a curve already due doesn't stop it being kept" % (d1["refresh"], d3["refresh"])))
results.append(ok(new_day, "so does a new day (the 12-month window, departures already flown)"))
results.append(ok("flightvalue.build(" not in inspect.getsource(server._guide_fv)
                  + inspect.getsource(server._guide_lines) + inspect.getsource(server._home_sizers)
                  + inspect.getsource(server._home_picks) + inspect.getsource(server._cheap_fares),
                  "every page render takes it from the memo (_fv_build)"))

# --- server.py: gzip level 6 -------------------------------------------------------------
import gzip as _gz  # noqa: E402
import socket as _sock  # noqa: E402


class _FakeSrv:
    pass


def handler_get(path, headers=""):
    """(head, body) of one GET through the real Handler on a socketpair."""
    a, b = _sock.socketpair()
    b.sendall(("GET %s HTTP/1.1\r\nHost: wandergrade.com\r\n%s\r\n" % (path, headers)).encode())
    got = []
    rd = threading.Thread(target=lambda: [got.append(x) for x in iter(lambda: b.recv(65536), b"")], daemon=True)
    rd.start()
    server.Handler(a, ("127.0.0.1", 40000), _FakeSrv())
    a.shutdown(_sock.SHUT_WR)
    a.close()
    rd.join(5)
    b.close()
    head, _, body = b"".join(got).partition(b"\r\n\r\n")
    return head.decode("latin-1"), body


raw_geo = open(os.path.join(ROOT, "public", "world.geojson"), "rb").read()
h_gz, b_gz = handler_get("/world.geojson", "Accept-Encoding: gzip\r\n")
h_raw, b_raw = handler_get("/world.geojson")
results.append(ok(server.GZIP_LEVEL == 6 and "Content-Encoding: gzip" in h_gz and _gz.decompress(b_gz) == raw_geo
                  and b_raw == raw_geo and "Content-Encoding" not in h_raw
                  and len(b_gz) <= 1.01 * len(_gz.compress(raw_geo, 9)),
                  "text responses gzip at level %d: world.geojson %d -> %d bytes (level 9: %d), raw without "
                  "Accept-Encoding" % (server.GZIP_LEVEL, len(raw_geo), len(b_gz), len(_gz.compress(raw_geo, 9)))))

# --- server.py: the page memo (rendered guide and home bytes) ---------------------------
import collections  # noqa: E402
renders = []
real_render = server._render_index


def counted_render(iso=None):
    renders.append(iso)
    return real_render(iso)


def page(path, gz=True, method="GET"):
    """(status line + headers without Date, decompressed body) through the real Handler."""
    head, body = handler_get(path, "Accept-Encoding: gzip\r\n" if gz else "") if method == "GET" else \
        handler_head(path, gz)
    if "Content-Encoding: gzip" in head and body:
        body = _gz.decompress(body)
    return re.sub(r"\r\nDate: [^\r]*", "", head), body


def handler_head(path, gz=True):
    a, b = _sock.socketpair()
    b.sendall(("HEAD %s HTTP/1.1\r\nHost: wandergrade.com\r\n%s\r\n"
               % (path, "Accept-Encoding: gzip\r\n" if gz else "")).encode())
    got = []
    rd = threading.Thread(target=lambda: [got.append(x) for x in iter(lambda: b.recv(65536), b"")], daemon=True)
    rd.start()
    server.Handler(a, ("127.0.0.1", 40000), _FakeSrv())
    a.shutdown(_sock.SHUT_WR)
    a.close()
    rd.join(5)
    b.close()
    head, _, body = b"".join(got).partition(b"\r\n\r\n")
    return head.decode("latin-1"), body


saved_pm = (server._page_memo, server.PAGE_MEMO_TTL, server.PAGE_MEMO_MAX, server._render_index,
            server._warm_watchouts, server._warm_popularity, server.datetime)
server._warm_watchouts, server._warm_popularity = (lambda iso: None), (lambda: None)
load(10)                                    # the three lists in hand and current: guides go out public
try:
    server._page_memo = None
    off_plain = page("/guide/japan")
    off_query = page("/guide/japan?utm_source=x&vmn=3&x=1")
    off_raw = page("/guide/japan", gz=False)
    off_head = page("/guide/japan", method="HEAD")
    server._render_index = counted_render
    page("/guide/japan")
    page("/guide/japan")
    memo_off_renders = len(renders)
    server._page_memo = collections.OrderedDict()
    del renders[:]
    on = [page("/guide/japan"), page("/guide/japan?utm_source=x&vmn=3&x=1"), page("/guide/japan", gz=False),
          page("/guide/japan", method="HEAD"), page("/guide/japan")]
    one_render = list(renders)
    entry = server._page_memo.get("JP")
    # an input replaced (Canada's list refreshed, same content): rendered again
    server._adv_cache["ca"] = (time.time(), copy.deepcopy(server._adv_cache["ca"][1]))
    page("/guide/japan")
    page("/guide/japan")
    after_input = len(renders)
    # past PAGE_MEMO_TTL: rendered again
    server.PAGE_MEMO_TTL = 0.3
    time.sleep(0.35)
    page("/guide/japan")
    after_ttl = len(renders)
    server.PAGE_MEMO_TTL = saved_pm[1]

    class Tomorrow(saved_pm[6]):
        @classmethod
        def now(cls, tz=None):
            return saved_pm[6].fromtimestamp(time.time() + 86400, tz)

    server.datetime = Tomorrow
    page("/guide/japan")
    server.datetime = saved_pm[6]
    after_day = len(renders)
    # a list not in hand (its fetch held): the guide goes out no-store, rendered every time, never kept
    fetch["hold"] = threading.Event()
    del server._adv_cache["de"]
    server._page_memo.clear()
    ns1, ns2 = page("/guide/peru"), page("/guide/peru")
    no_store = len(renders) - after_day
    peru_kept = "PE" in server._page_memo
    fetch["hold"].set()
    settle()
    load(10)
    # the homepage: once, then from the memo; a popularity refresh renders it again
    del renders[:]
    h1, h2 = page("/"), page("/")
    home_once = list(renders)
    server._pop_cache["data"] = {"arrivals": {"JP": 1}}
    page("/")
    home_after_pop = len(renders)
    # at most PAGE_MEMO_MAX pages, the least recently used dropped first
    server.PAGE_MEMO_MAX = 2
    server._page_memo.clear()
    for sl in ("chile", "peru", "chile", "kenya"):
        page("/guide/" + sl)
    held = list(server._page_memo)
finally:
    (server._page_memo, server.PAGE_MEMO_TTL, server.PAGE_MEMO_MAX, server._render_index,
     server._warm_watchouts, server._warm_popularity, server.datetime) = saved_pm
    server._pop_cache["data"] = None
    fetch["hold"] = None
results.append(ok(off_plain[1] == off_query[1] == off_raw[1] and "Cache-Control: public, max-age=300" in off_plain[0]
                  and memo_off_renders == 2,
                  "a guide's bytes don't depend on its query string (?utm_source=x&vmn=3&x=1 -> the same %d bytes), "
                  "and with the memo off (tests, tools) every request renders" % len(off_plain[1])))
results.append(ok(one_render == ["JP"] and on[0] == off_plain and on[1] == off_query and on[2] == off_raw
                  and on[3] == off_head and on[4] == off_plain and off_head[1] == b"" and entry is not None
                  and entry[4] is not None,
                  "memo on: GET (gzip and raw), a query string and HEAD of one guide render it once, with the very "
                  "status, headers and bytes the memo-off server sends (%d renders)" % len(one_render)))
results.append(ok(after_input == 2 and after_ttl == 3 and after_day == 4,
                  "an input replaced (a refreshed list, same content), PAGE_MEMO_TTL passing or a new day renders "
                  "it again (renders %d, %d, %d)" % (after_input, after_ttl, after_day)))
results.append(ok(no_store == 2 and not peru_kept and "Cache-Control: no-store" in ns1[0] and ns1 == ns2,
                  "a guide going out no-store (a list not in hand) renders every time and is never kept"))
results.append(ok(home_once == [None] and h1 == h2 and "public, max-age=300" in h1[0] and home_after_pop == 2,
                  "the homepage renders once and is handed out again; new popularity figures render it again"))
results.append(ok(held == ["CL", "KE"], "at most PAGE_MEMO_MAX pages are kept, the least recently used dropped "
                                        "first (%s)" % held))
# Reading a page's inputs raises: the flight-value build on a bad fare curve
# (KeyError), the popularity thread that can't start. The render drops only
# the block it was building, so the page must still go out with the memo on,
# rendered as with it off, not kept, with one [page-memo] line.
import io as io_mod  # noqa: E402
from fxtracker import flightvalue as _fvmod, flights as _flmod  # noqa: E402
saved_fe = (server._page_memo, _fvmod.build, _flmod.is_configured, _fvmod.has_warmed,
            server._flights_cache.get(_fvmod.DEFAULT_ORIGIN), server._warm_popularity, server._warm_watchouts,
            server.PAGE_MEMO_LOG_EVERY, dict(server._page_memo_err))


def bad_build(*a, **k):
    raise KeyError("price")


def no_thread():
    raise RuntimeError("can't start new thread")


load(10)
err_pm, saved_err = io_mod.StringIO(), sys.stderr
try:
    _fvmod.build, _flmod.is_configured, _fvmod.has_warmed = bad_build, (lambda: True), (lambda o: True)
    server._flights_cache[_fvmod.DEFAULT_ORIGIN] = (time.time(), {"configured": True, "countries": []})
    server._warm_watchouts, server._warm_popularity = (lambda iso: None), no_thread
    server._pop_cache["data"] = None
    server.PAGE_MEMO_LOG_EVERY = 60
    server._page_memo_err.update(at=0.0, held=0)
    sys.stderr = err_pm
    server._page_memo = None
    fe_off = [page("/guide/japan"), page("/")]
    server._page_memo = collections.OrderedDict()
    fe_on = [page("/guide/japan"), page("/"), page("/guide/japan", method="HEAD")]
    fe_kept = list(server._page_memo)
finally:
    sys.stderr = saved_err
    (server._page_memo, _fvmod.build, _flmod.is_configured, _fvmod.has_warmed, fl_saved, server._warm_popularity,
     server._warm_watchouts, server.PAGE_MEMO_LOG_EVERY, pm_err) = saved_fe
    server._page_memo_err.clear()
    server._page_memo_err.update(pm_err)
    if fl_saved is None:
        server._flights_cache.pop(_fvmod.DEFAULT_ORIGIN, None)
    else:
        server._flights_cache[_fvmod.DEFAULT_ORIGIN] = fl_saved
pm_lines = [ln for ln in err_pm.getvalue().splitlines() if ln.startswith("[page-memo]")]
results.append(ok(all(p_[0].startswith("HTTP/1.0 200") for p_ in fe_off + fe_on) and fe_on[0] == fe_off[0]
                  and fe_on[1] == fe_off[1] and fe_on[2][1] == b"" and fe_kept == []
                  and len(pm_lines) == 1 and "KeyError" in pm_lines[0] and "rendered without the memo" in pm_lines[0],
                  "a flight-value build that raises (and a popularity thread that won't start) costs the page "
                  "nothing with the memo on: guide and homepage 200 with the memo-off bytes, nothing kept, one "
                  "[page-memo] line per PAGE_MEMO_LOG_EVERY (%s; %r)"
                  % ([p_[0].split("\r\n")[0] for p_ in fe_on], pm_lines[:1])))

src_main = inspect.getsource(server.main)
results.append(ok(server._page_memo is None and "_page_memo = collections.OrderedDict()" in src_main
                  and server.PAGE_MEMO_TTL == 300 and server.PAGE_MEMO_CACHE == "public, max-age=300",
                  "main() turns the page memo on (%d s, public pages only); importing server leaves it off"
                  % server.PAGE_MEMO_TTL))

# --- fxtracker/rates.py: the FX history refresh asks only for the days it lacks ----------
# The whole ECB history since 1999 is a 2.75 MB reply (one json.loads held the
# GIL ~17-22 ms), refetched every HISTORY_TTL on whichever request asked
# first. A copy in hand is now brought up to date from its last days on.
from fxtracker import rates as R  # noqa: E402
FXH = jl("scripts", "fixtures", "fx_history", "frankfurter_2026-11-16.json")
fxh = {"until": "2026-11-13", "urls": [], "bytes": [], "fail": False, "revise": None, "drop": None}


def fake_history_fetch(url, retries=3):
    assert url.startswith(R.HISTORY_API + "/") and "symbols=" + ",".join(sorted(R.MAJORS)) in url, url
    fxh["urls"].append(url)
    if fxh["fail"]:
        raise urllib.error.URLError("frankfurter down")
    start, end = url[len(R.HISTORY_API) + 1:].split("?", 1)[0].split("..", 1)
    rates_ = {k: dict(v) for k, v in FXH["rates"].items()
              if start <= k <= min(fxh["until"], end or "~") and k != fxh["drop"]}
    if fxh["revise"] and fxh["revise"][0] in rates_:
        d_, c_ = fxh["revise"]
        rates_[d_][c_] = round(rates_[d_][c_] * 1.01, 5)
    body = {"amount": 1.0, "base": "USD", "start_date": min(rates_), "end_date": max(rates_), "rates": rates_}
    fxh["bytes"].append(len(json.dumps(body)))
    return json.loads(json.dumps(body))


def fresh_history(until):
    """get_history() from nothing, the fixture served up to `until`."""
    R._history.update(snap=(0.0, [], {}), retry_at=0.0)
    fxh.update(until=until, urls=[], bytes=[], fail=False, revise=None, drop=None)
    return R.get_history()


def age_history(secs):
    at, d_, c_ = R._history["snap"]
    R._history["snap"] = (time.time() - secs, d_, c_)


saved_r = (R.fetch_json, dict(R._history), dict(R.INDEX_MASK), R.HISTORY_CHUNK_YEARS)
R.fetch_json = fake_history_fetch
R.HISTORY_CHUNK_YEARS = 100      # the cut fixture has no 2004-2025: the whole history in one reply here
logs = []
try:
    whole = fresh_history("2026-11-13")
    whole_urls, whole_bytes = list(fxh["urls"]), list(fxh["bytes"])
    # a copy from a week ago, past HISTORY_TTL: one small fetch from its last 10 days on
    fresh_history("2026-11-06")
    held_at, held_dates, held_cols = R._history["snap"]
    age_history(R.HISTORY_TTL + 5)
    fxh.update(until="2026-11-13", urls=[], bytes=[])
    upd = R.get_history()
    upd_urls, upd_bytes = list(fxh["urls"]), list(fxh["bytes"])
    upd_ok = (upd[1] == whole[1] and upd[2] == whole[2] and upd[0] > held_at and len(upd_urls) == 1
              and "/2026-10-27..?" in upd_urls[0] and upd_bytes[0] < whole_bytes[0] / 10
              and held_dates[-1] == "2026-11-06" and R._history["snap"] is upd)
    # nothing new since: the copy's own lists under a new time
    age_history(R.HISTORY_TTL + 5)
    fxh.update(urls=[], bytes=[])
    same = R.get_history()
    nothing_new = same[1] is upd[1] and same[2] is upd[2] and same[0] > upd[0] and len(fxh["urls"]) == 1
    # a revised fixing inside the overlap: fetched whole, and the revision kept
    fresh_history("2026-11-13")
    age_history(R.HISTORY_TTL + 5)
    fxh.update(urls=[], bytes=[], revise=("2026-11-10", "EUR"))
    rev = R.get_history()
    i10 = rev[1].index("2026-11-10")
    revised = (len(fxh["urls"]) == 2 and "/1999-01-04..?" in fxh["urls"][1] and rev[1] == whole[1]
               and abs(rev[2]["EUR"][i10] - whole[2]["EUR"][i10] * 1.01) < 1e-4)
    # an overlap day missing from the reply: fetched whole
    fresh_history("2026-11-13")
    age_history(R.HISTORY_TTL + 5)
    fxh.update(urls=[], bytes=[], drop="2026-11-04")
    R.get_history()
    fxh.update(drop=None)
    gap_full = len(fxh["urls"]) == 2 and "/1999-01-04..?" in fxh["urls"][1]
    # a day inside the overlap that the copy lacks (published late): fetched whole
    R._history.update(snap=(0.0, [], {}), retry_at=0.0)
    fxh.update(until="2026-11-13", drop="2026-11-04", urls=[], revise=None, fail=False)
    R.get_history()                      # the copy, without 2026-11-04
    fxh.update(drop=None, urls=[])
    age_history(R.HISTORY_TTL + 5)
    late = R.get_history()
    late_full = len(fxh["urls"]) == 2 and "/1999-01-04..?" in fxh["urls"][1] and "2026-11-04" in late[1]
    # the update failing: the copy is served, retried after HISTORY_RETRY, no whole fetch tried
    fresh_history("2026-11-06")
    kept = R._history["snap"]
    age_history(R.HISTORY_TTL + 5)
    kept = R._history["snap"]
    fxh.update(urls=[], fail=True)
    served = R.get_history()
    again = R.get_history()
    down_ok = (served is kept and again is kept and len(fxh["urls"]) == 1
               and R._history["retry_at"] > time.time() + R.HISTORY_RETRY - 5)
    # past HISTORY_STALE with the source down: nothing to serve, as before
    R._history["retry_at"] = 0.0
    age_history(R.HISTORY_STALE + 5)
    try:
        R.get_history()
        stale_raises = False
    except Exception:
        stale_raises = True
    # INDEX_MASK holds for the days an update appends
    fresh_history("2026-11-06")
    age_history(R.HISTORY_TTL + 5)
    R.INDEX_MASK["ISK"] = ("2026-11-10", "2026-11-11")
    fxh.update(until="2026-11-13", urls=[], fail=False)
    m = R.get_history()
    masked = [m[2]["ISK"][m[1].index(d_)] for d_ in ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12")]
    mask_ok = masked[0] is not None and masked[1] is None and masked[2] is None and masked[3] is not None \
        and len(fxh["urls"]) == 1
finally:
    R.fetch_json = saved_r[0]
    R._history.clear()
    R._history.update(saved_r[1])
    R.INDEX_MASK.clear()
    R.INDEX_MASK.update(saved_r[2])
    R.HISTORY_CHUNK_YEARS = saved_r[3]
results.append(ok(len(whole_urls) == 1 and "/1999-01-04..?" in whole_urls[0] and len(whole[1]) == len(FXH["rates"])
                  and whole[2]["ISK"][0] is not None,
                  "the first FX history fetch is the whole history since 1999 (%d days, %d bytes here)"
                  % (len(whole[1]), whole_bytes[0])))
results.append(ok(upd_ok, "a copy past HISTORY_TTL is brought up to date by one fetch from 10 days before its last "
                          "date (%s, %d bytes), equal to fetching it whole"
                  % (upd_urls and upd_urls[0].split("/")[-1].split("?")[0], upd_bytes and upd_bytes[0])))
results.append(ok(nothing_new, "with nothing new it keeps the copy's lists under a new fetch time"))
results.append(ok(revised and gap_full and late_full,
                  "a reply that disagrees with the copy (a revised fixing), skips one of its days or has a day it "
                  "lacks (published late) is fetched whole instead, and the revision or late day kept"))
results.append(ok(down_ok and stale_raises, "the update failing serves the copy and backs off HISTORY_RETRY with no "
                                            "whole fetch; past HISTORY_STALE nothing is served, as before"))
results.append(ok(mask_ok, "INDEX_MASK holds for the days an update appends (%s)" % masked))

# The whole history comes in HISTORY_CHUNK_YEARS pieces (each json.loads holds
# the GIL for its piece only), equal to one reply; a piece cut short fails it.
SYN = {}
d_, i_ = datetime.date(1999, 1, 4), 0
while d_ <= datetime.date(2026, 11, 13):
    if d_.weekday() < 5 and (d_.month, d_.day) not in ((1, 1), (12, 25), (12, 26)):
        SYN[d_.isoformat()] = {c: round(1 + (hash(c) % 97) / 10 + i_ * 1e-4, 5) for c in sorted(R.MAJORS)}
        i_ += 1
    d_ += datetime.timedelta(days=1)
syn = {"urls": [], "cut": None}


def fake_syn_fetch(url, retries=3):
    syn["urls"].append(url)
    start, end = url[len(R.HISTORY_API) + 1:].split("?", 1)[0].split("..", 1)
    hi = end or "~"
    if syn["cut"] and syn["cut"][0] == start:
        hi = syn["cut"][1]
    return {"base": "USD", "rates": {k: dict(v) for k, v in SYN.items() if start <= k <= hi}}


saved_c = (R.fetch_json, dict(R._history), R.HISTORY_CHUNK_YEARS)
R.fetch_json = fake_syn_fetch
try:
    spans = R._history_spans(datetime.date(2026, 11, 18))
    jan = R._history_spans(datetime.date(2029, 1, 2))
    R._history.update(snap=(0.0, [], {}), retry_at=0.0)
    chunked = R.get_history()
    chunk_urls = list(syn["urls"])
    R.HISTORY_CHUNK_YEARS = 100
    R._history.update(snap=(0.0, [], {}), retry_at=0.0)
    del syn["urls"][:]
    single = R.get_history()
    single_urls = list(syn["urls"])
    R.HISTORY_CHUNK_YEARS = saved_c[2]
    R._history.update(snap=(0.0, [], {}), retry_at=0.0)
    syn["cut"] = ("2009-01-01", "2011-06-30")       # one piece cut short: a 2.5-year hole
    try:
        R.get_history()
        cut_raised = None
    except ValueError as e:
        cut_raised = str(e)
finally:
    R.fetch_json, R.HISTORY_CHUNK_YEARS = saved_c[0], saved_c[2]
    R._history.clear()
    R._history.update(saved_c[1])
results.append(ok(spans == [("1999-01-04", "2003-12-31"), ("2004-01-01", "2008-12-31"), ("2009-01-01", "2013-12-31"),
                            ("2014-01-01", "2018-12-31"), ("2019-01-01", "2023-12-31"), ("2024-01-01", "")]
                  and jan[-1] == ("2024-01-01", "") and len(chunk_urls) == 6 and len(single_urls) == 1
                  and chunked[1] == single[1] and chunked[2] == single[2] and len(chunked[1]) == len(SYN),
                  "the whole history is fetched in 6 pieces of <= 5 years (the last open-ended, never a bare "
                  "January), equal to one reply (%d days)" % len(chunked[1])))
results.append(ok(cut_raised is not None and "2009-01-01..2013-12-31" in cut_raised,
                  "a piece that comes back short of its end fails the fetch instead of leaving a hole (%s)"
                  % cut_raised))

# --- server.py: a client hanging up is one log line, not a traceback ---------------------
import io  # noqa: E402


def hang_up(path):
    """stderr of one GET whose client closes before reading the response, and
    whether anything raised out of the handler (socketserver's handle_error
    would print its traceback)."""
    a, b = _sock.socketpair()
    a.setsockopt(_sock.SOL_SOCKET, _sock.SO_SNDBUF, 4096)
    b.sendall(("GET %s HTTP/1.1\r\nHost: wandergrade.com\r\n\r\n" % path).encode())
    b.close()
    err, saved_err = io.StringIO(), sys.stderr
    sys.stderr = err
    raised = None
    try:
        server.Handler(a, ("127.0.0.1", 40000), _FakeSrv())
    except Exception as e:
        raised = e
    finally:
        sys.stderr = saved_err
        a.close()
    return err.getvalue(), raised


hu_out, hu_raised = hang_up("/world.geojson?v=1")
hu_tok, _r = hang_up("/auth/verify?t=" + "a" * 40)
other_seen = {}
srv = server._Server(("127.0.0.1", 0), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
real_dg = server.Handler._do_get
server.Handler._do_get = lambda self: (_ for _ in ()).throw(ValueError("boom"))
err2, saved_err = io.StringIO(), sys.stderr
sys.stderr = err2
try:
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/boom" % srv.server_address[1], timeout=5).read()
    except Exception:
        pass
    time.sleep(0.2)
finally:
    sys.stderr = saved_err
    server.Handler._do_get = real_dg
    srv.shutdown()
    srv.server_close()
lines = [ln for ln in hu_out.splitlines() if ln.strip()]
results.append(ok(hu_raised is None and len(lines) == 1 and "Traceback" not in hu_out
                  and re.fullmatch(r"  \[disconnect\] GET /world\.geojson\?v=1 (BrokenPipeError|ConnectionResetError"
                                   r"|ConnectionAbortedError)", lines[0])
                  and "t=[redacted]" in hu_tok and "a" * 40 not in hu_tok,
                  "a client hanging up mid-response is one line (%r), nothing raised out of the handler, a sign-in "
                  "token redacted" % (lines[:1],)))
results.append(ok("Traceback" in err2.getvalue() and "ValueError: boom" in err2.getvalue(),
                  "any other exception still prints its traceback"))

# --- server.py: diagnostics for next time ([busy], [refresh], X-Uptime) ------------------
# X-Uptime on /healthz: whole seconds since the process started.
saved_boot = server._BOOT
server._BOOT = time.monotonic() - 100.4
hz_head, hz_body = handler_get("/healthz")
server._BOOT = saved_boot
up = re.search(r"\r\nX-Uptime: (\d+)\r\n", hz_head)
results.append(ok(hz_body == b"ok" and up and int(up.group(1)) == 100 and hz_head.startswith("HTTP/1.0 200"),
                  "/healthz says X-Uptime: %s (whole seconds since boot), still 200 ok" % (up and up.group(1))))

# [busy]: one line at once, the rest of the window counted and written by a timer.
saved_busy = (server.BUSY_LOG_EVERY, dict(server._busy), server._page_slots, server.PAGE_QUEUE_MAX)
server.BUSY_LOG_EVERY = 0.4
if server._busy.get("timer") is not None:
    server._busy["timer"].cancel()      # the slot tests above queued deep: their timer is pending
server._busy.update(at=0.0, queue=0, wait=0, slotless=0, deep=0, peak=0, timer=None)
server._page_slots = threading.BoundedSemaphore(3)
err3, saved_err = io.StringIO(), sys.stderr
sys.stderr = err3
try:
    for _i in range(3):
        server._page_slots.acquire()
    server.PAGE_QUEUE_MAX = 0
    shed_kinds = [server._take_slot(server._page_slots) for _ in range(3)]
    first_lines = err3.getvalue().splitlines()
    server._busy_note("slotless")
    time.sleep(0.6)
    after_timer = err3.getvalue().splitlines()
    time.sleep(0.6)
    quiet = err3.getvalue().splitlines()
finally:
    sys.stderr = saved_err
    server.BUSY_LOG_EVERY = saved_busy[0]
    if server._busy.get("timer") is not None:
        server._busy["timer"].cancel()
    server._busy.clear()
    server._busy.update(saved_busy[1], timer=None)
    server._page_slots, server.PAGE_QUEUE_MAX = saved_busy[2], saved_busy[3]
results.append(ok(shed_kinds == ["queue"] * 3 and len(first_lines) == 1 and first_lines[0].startswith("[busy] ")
                  and "shed 1 (1 with 0+ waiting" in first_lines[0] and "3/3 slots in use" in first_lines[0]
                  and len(after_timer) == 2 and "shed 2 (2 with" in after_timer[1] and "1 slotless" in after_timer[1]
                  and len(quiet) == 2,
                  "[busy]: the first shed page writes a line at once, the window's other 2 sheds and a slotless "
                  "finish go out in one line BUSY_LOG_EVERY later, then nothing while quiet (%r)" % (after_timer[-1:],)))
results.append(ok("_busy_note(\"slotless\")" in inspect.getsource(server._no_slot)
                  and server.BUSY_LOG_EVERY == 30,
                  "a page finishing without its slot after an inline wait is counted too; production writes at "
                  "most one [busy] line every %d s" % server.BUSY_LOG_EVERY))

# [refresh]: one line when a heavy refresh ends, at most one per name every REFRESH_LOG_EVERY.
saved_rl = (server.REFRESH_LOG_EVERY, dict(server._refresh_logged))
server.REFRESH_LOG_EVERY = 0.3
server._refresh_logged.clear()
out4, saved_out = io.StringIO(), sys.stdout
sys.stdout = out4
try:
    v1 = server._timed_refresh("rates USD", lambda: time.sleep(0.05) or 41)
    v2 = server._timed_refresh("rates USD", lambda: 42)
    time.sleep(0.35)
    try:
        server._timed_refresh("rates USD", lambda: (_ for _ in ()).throw(RuntimeError("fxratesapi down")))
    except RuntimeError:
        pass
    R.fetch_json, R.HISTORY_CHUNK_YEARS = fake_history_fetch, 100
    fresh_history("2026-11-06")
    age_history(R.HISTORY_TTL + 5)
    fxh.update(until="2026-11-13")
    R.get_history()
finally:
    sys.stdout = saved_out
    R.fetch_json, R.HISTORY_CHUNK_YEARS = saved_r[0], saved_r[3]
    R._history.clear()
    R._history.update(saved_r[1])
    server.REFRESH_LOG_EVERY = saved_rl[0]
    server._refresh_logged.clear()
    server._refresh_logged.update(saved_rl[1])
rl = [ln for ln in out4.getvalue().splitlines() if ln.startswith("[refresh]")]
results.append(ok(v1 == 41 and v2 == 42 and len(rl) == 4
                  and re.fullmatch(r"\[refresh\] rates USD done in 0\.\d\ds \(cpu \d+ ms\)", rl[0])
                  and re.fullmatch(r"\[refresh\] rates USD failed: fxratesapi down in \d\.\d\ds \(cpu \d+ ms\), "
                                   r"1 more since", rl[1])
                  and re.fullmatch(r"\[refresh\] fx-history whole, \d+ days in .*", rl[2])
                  and re.fullmatch(r"\[refresh\] fx-history update \+5 days in \d\.\d\ds \(cpu \d+ ms\)", rl[3]),
                  "[refresh]: a refresh's line says what, how long and its CPU; a second inside REFRESH_LOG_EVERY is "
                  "held back and counted; the FX history says whole or update (%r)" % (rl,)))
results.append(ok("_timed_refresh(\"advisories \"" in inspect.getsource(server._advisories_fresh)
                  and "_timed_refresh(\"rates \"" in inspect.getsource(server._rates_payload),
                  "the advisory lists and the rates refresh through it"))

# --- server.py: /healthz writes its log line after its answer ----------------------------
order = []


def log_after(self, code="-", size="-"):
    try:
        order.append(("log", self._probe_peer.recv(65536, _sock.MSG_DONTWAIT)))
    except BlockingIOError:
        order.append(("log", b""))


a_, b_ = _sock.socketpair()
b_.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
saved_lr = server.Handler.log_request
server.Handler.log_request = log_after
server.Handler._probe_peer = b_
try:
    server.Handler(a_, ("127.0.0.1", 40000), _FakeSrv())
finally:
    server.Handler.log_request = saved_lr
    del server.Handler._probe_peer
    a_.close()
    b_.close()
seen_hz = order[0][1] if order else b""
results.append(ok(len(order) == 1 and seen_hz.startswith(b"HTTP/1.0 200 OK\r\nServer: WanderGrade \r\nDate: ")
                  and b"\r\nContent-Type: text/plain\r\nX-Uptime: " in seen_hz and seen_hz.endswith(b"\r\n\r\nok"),
                  "/healthz's request-log line is written after its whole answer is out (status, Server, Date, "
                  "headers and body as before), so the probe never waits on the log pipe"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

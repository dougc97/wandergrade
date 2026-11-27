"""The /data dataset rebuild runs once at a time (server.py _dataset): when the
hourly copy expires, or the server has none yet, requests that arrive while it
is being rebuilt wait for that rebuild and get what it made, instead of each
rebuilding (a rates fetch, three upstream calls with their retries) side by
side. No network, no server process: the real Handler on socketpairs, with
the build replaced by a slow stand-in that stamps each rebuild.

    /usr/bin/python3 scripts/test_dataset_flight.py

What it holds the code to:
  * 8 requests for /data/price-levels.csv and .json arriving together on a
    cold server: one rebuild, every answer 200 and byte-identical to the
    others of its kind, all from that rebuild;
  * the same with the hourly copy expired: one rebuild, and every answer is
    the new copy, not the old one;
  * a rebuild that fails: tried once for the 8; with no copy each answers
    503 with the same error, with a copy each gets that copy (the backoff,
    FAIL_RETRY / STALE_RETRY, as before);
  * a request waiting on another's rebuild holds no page slot (it waits as
    _idle_wait does) and has its slot back after, and the leader publishes
    before it queues for its own slot again;
  * a wait past DATASET_FLIGHT_WAIT (a rebuild stuck on the network) gives
    up on it and rebuilds as every request did before;
  * a warm read takes no lock and starts no rebuild.
"""
import inspect
import json
import os
import socket as _sock
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

server.Handler.log_message = lambda self, *a: None   # no request log lines in the output
ok =lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


class _FakeSrv:
    pass


def handler_get(path):
    """(status line, body) of one GET through the real Handler on a socketpair."""
    a, b = _sock.socketpair()
    b.sendall(("GET %s HTTP/1.1\r\nHost: wandergrade.com\r\n\r\n" % path).encode())
    got = []
    rd = threading.Thread(target=lambda: [got.append(x) for x in iter(lambda: b.recv(65536), b"")], daemon=True)
    rd.start()
    server.Handler(a, ("127.0.0.1", 40000), _FakeSrv())
    a.shutdown(_sock.SHUT_WR)
    a.close()
    rd.join(10)
    b.close()
    head, _, body = b"".join(got).partition(b"\r\n\r\n")
    return head.decode("latin-1").split("\r\n", 1)[0], body


builds = {"n": 0, "delay": 0.4, "fail": False, "mid": []}
builds_lock = threading.Lock()


def fake_build(ppp):
    with builds_lock:
        builds["n"] += 1
        n = builds["n"]
    time.sleep(builds["delay"])
    if builds["fail"]:
        raise RuntimeError("rates down")
    return {"meta": {"rates_as_of": "2026-11-%02d" % n, "build": n},
            "countries": [{"iso": "X%d" % n, "country": "Rebuild %d" % n, "price_level": 0.5}]}


PATHS = ["/data/price-levels.csv", "/data/price-levels.json"] * 4


def burst(paths=PATHS):
    """Every path requested at once (a barrier), each on its own thread."""
    gate = threading.Barrier(len(paths))
    out = [None] * len(paths)

    def one(i, p):
        gate.wait()
        out[i] = handler_get(p)
    ths = [threading.Thread(target=one, args=(i, p)) for i, p in enumerate(paths)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(30)
    return out


def by_kind(out, paths=PATHS):
    kinds = {}
    for p, r in zip(paths, out):
        kinds.setdefault(p, set()).add(r)
    return kinds


saved = (server.build_dataset.build, dict(server._ppp_cache), dict(server._dataset_cache),
         server.STALE_RETRY, server.FAIL_RETRY)
server.build_dataset.build = fake_build
server._ppp_cache.update(at=time.time(), data={"JP": {}})   # no PPP refresh thread
WAIT = getattr(server, "DATASET_FLIGHT_WAIT", None)


def reset(**kw):
    server._dataset_cache.update(dict(at=0, payload=None, csv=None, retry_at=0, error=""), **kw)
    builds.update(n=0, fail=False, delay=0.4)


try:
    # --- cold: nothing in hand -------------------------------------------------------
    reset()
    t = time.time()
    cold = burst()
    cold_s = time.time() - t
    kinds = by_kind(cold)
    csv1 = server.build_dataset.to_csv({"countries": [{"iso": "X1", "country": "Rebuild 1", "price_level": 0.5}]})
    want_json = json.dumps({"meta": {"rates_as_of": "2026-11-01", "build": 1},
                            "countries": [{"iso": "X1", "country": "Rebuild 1", "price_level": 0.5}]})
    cold_ok = (builds["n"] == 1 and all(len(v) == 1 for v in kinds.values())
               and all(r[0].startswith("HTTP/1.0 200") for r in cold)
               and kinds["/data/price-levels.csv"] == {(cold[0][0], csv1.encode("utf-8"))}
               and json.loads(cold[1][1]) == json.loads(want_json))
    results.append(ok(cold_ok, "cold: 8 requests at once (4 CSV, 4 JSON) make 1 rebuild (made %d), every answer 200 "
                      "and the same bytes per kind, from that rebuild (%d distinct CSV, %d distinct JSON, %.2fs)"
                      % (builds["n"], len(kinds["/data/price-levels.csv"]), len(kinds["/data/price-levels.json"]),
                         cold_s)))

    # --- the hourly copy expired -------------------------------------------------------
    reset()
    old = {"meta": {"rates_as_of": "2026-10-31", "build": 0}, "countries": [{"iso": "X0", "country": "Old"}]}
    server._dataset_cache.update(at=time.time() - server._DATASET_TTL - 1, payload=old,
                                 csv=server.build_dataset.to_csv(old))
    exp = burst()
    kinds = by_kind(exp)
    exp_csv = kinds["/data/price-levels.csv"]
    exp_ok = (builds["n"] == 1 and all(len(v) == 1 for v in kinds.values())
              and all(r[0].startswith("HTTP/1.0 200") for r in exp)
              and b"Rebuild 1" in next(iter(exp_csv))[1] and b"Old" not in next(iter(exp_csv))[1]
              and json.loads(exp[1][1])["meta"]["build"] == 1)
    results.append(ok(exp_ok, "the hourly copy expired: 8 requests at once make 1 rebuild (made %d), every answer the "
                      "new copy, none the old (%d distinct CSV)" % (builds["n"], len(exp_csv))))

    # --- a failing rebuild, no copy -------------------------------------------------------
    reset()
    builds["fail"] = True
    fail = burst()
    fail_kinds = by_kind(fail)
    fail_ok = (builds["n"] == 1 and all(r[0].startswith("HTTP/1.0 503") for r in fail)
               and {r[1] for r in fail} == {json.dumps({"error": "dataset unavailable: rates down"}).encode()})
    results.append(ok(fail_ok, "a failing rebuild with no copy: tried once for the 8 (tried %d), each answers 503 with "
                      "its error (%s)" % (builds["n"], sorted({r[0] for r in fail}))))
    # and inside FAIL_RETRY nobody tries again
    again = burst(["/data/price-levels.csv"] * 3)
    results.append(ok(builds["n"] == 1 and all(r[0].startswith("HTTP/1.0 503") for r in again),
                      "...and inside FAIL_RETRY the next ones answer the same error without a rebuild (%d)"
                      % builds["n"]))

    # --- a failing rebuild, a copy in hand -------------------------------------------------
    reset()
    server._dataset_cache.update(at=time.time() - server._DATASET_TTL - 1, payload=old,
                                 csv=server.build_dataset.to_csv(old))
    builds["fail"] = True
    stale = burst()
    stale_ok = (builds["n"] == 1 and all(r[0].startswith("HTTP/1.0 200") for r in stale)
                and {r[1] for p, r in zip(PATHS, stale) if p.endswith(".csv")}
                == {server.build_dataset.to_csv(old).encode("utf-8")})
    results.append(ok(stale_ok, "a failing rebuild with a copy past its hour: tried once for the 8 (tried %d), each "
                      "gets that copy" % builds["n"]))

    # --- page slots: a waiter holds none, and has it back after ------------------------------
    reset()
    builds["delay"] = 0.6
    sem = threading.BoundedSemaphore(2)
    seen = {}

    def slotted(tag, delay):
        time.sleep(delay)
        sem.acquire()
        server._slot_held.slots = sem
        try:
            server._dataset()
            seen[tag] = getattr(server._slot_held, "slots", None) is sem
        finally:
            if getattr(server._slot_held, "slots", None) is sem:
                server._slot_held.slots = None
                sem.release()
    ths = [threading.Thread(target=slotted, args=("lead", 0)), threading.Thread(target=slotted, args=("follow", 0.1))]
    for th in ths:
        th.start()
    time.sleep(0.35)
    free_mid = sem._value
    for th in ths:
        th.join(10)
    results.append(ok(builds["n"] == 1 and free_mid == 2 and seen == {"lead": True, "follow": True},
                      "/data's rebuild with two slotted pages on it: one rebuild (%d), both slots free while it runs "
                      "(%d free), each page has its slot back after (%s)" % (builds["n"], free_mid, seen)))
    # The leader publishes before it queues for its own slot again: a guide
    # holding the only slot delays the leader alone, not a request waiting on it.
    reset()
    builds["delay"] = 0.3
    one = threading.BoundedSemaphore(1)
    saved_wait = server.PAGE_SLOT_WAIT
    server.PAGE_SLOT_WAIT = 5
    took = {}

    def leader():
        one.acquire()
        server._slot_held.slots = one
        try:
            server._dataset()
        finally:
            if getattr(server._slot_held, "slots", None) is one:
                server._slot_held.slots = None
                one.release()

    def hog():                   # a guide render grabbing the slot the leader gave back
        time.sleep(0.05)
        one.acquire()
        time.sleep(1.5)
        one.release()

    def follower():              # /data/price-levels.csv: no slot
        time.sleep(0.1)
        t0 = time.time()
        server._dataset()
        took["follower"] = time.time() - t0
    ths = [threading.Thread(target=f) for f in (leader, hog, follower)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(10)
    server.PAGE_SLOT_WAIT = saved_wait
    results.append(ok(builds["n"] == 1 and took.get("follower", 9) < 0.6,
                      "the leader publishes the rebuild before it queues for its slot again: a slotless request "
                      "waiting on it is answered in %.2fs (rebuild 0.3s, the slot held 1.5s by a guide)"
                      % took.get("follower", -1)))

    # --- a rebuild stuck on the network: the wait gives up -------------------------------
    reset()
    builds["delay"] = 1.0
    if WAIT is not None:
        server.DATASET_FLIGHT_WAIT = 0.2
    stuck_t = {}

    def timed(tag, delay):
        time.sleep(delay)
        t0 = time.time()
        server._dataset()
        stuck_t[tag] = time.time() - t0
    ths = [threading.Thread(target=timed, args=("lead", 0)), threading.Thread(target=timed, args=("follow", 0.05))]
    for th in ths:
        th.start()
    for th in ths:
        th.join(10)
    if WAIT is not None:
        server.DATASET_FLIGHT_WAIT = WAIT
    results.append(ok(WAIT is not None and WAIT >= 200 and builds["n"] == 2,
                      "a wait past DATASET_FLIGHT_WAIT (%s s; above a rebuild's worst case, 3 fetches x 64.5 s) "
                      "gives up on the stuck rebuild and rebuilds as before (%d rebuilds)" % (WAIT, builds["n"])))

    # --- warm: no lock, no rebuild ---------------------------------------------------------
    reset()
    builds["delay"] = 0.0
    server._dataset()
    n_after = builds["n"]
    lock = getattr(server, "_dataset_flight_lock", None)
    held_ok = True
    if lock is not None:
        lock.acquire()               # a warm read must not need it
        try:
            res = []
            th = threading.Thread(target=lambda: res.append(server._dataset()))
            th.start()
            th.join(2)
            held_ok = bool(res) and res[0] is server._dataset_cache
        finally:
            lock.release()
    t0 = time.perf_counter()
    for _ in range(20000):
        server._dataset()
    warm_us = (time.perf_counter() - t0) / 20000 * 1e6
    results.append(ok(lock is not None and held_ok and builds["n"] == n_after == 1,
                      "a warm read takes no lock and starts no rebuild (%.2f us a read)" % warm_us))
finally:
    server.build_dataset.build = saved[0]
    server._ppp_cache.clear()
    server._ppp_cache.update(saved[1])
    server._dataset_cache.clear()
    server._dataset_cache.update(saved[2])
    server.STALE_RETRY, server.FAIL_RETRY = saved[3], saved[4]

results.append(ok("_idle_wait(" in inspect.getsource(server._dataset),
                  "a request waiting on another's rebuild waits through _idle_wait (no page slot held)"))

passed = sum(1 for r in results if r)
print("\n%d/%d passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

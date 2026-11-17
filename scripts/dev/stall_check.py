#!/usr/bin/env python3
"""Does /healthz still answer inside Render's 5 s while the server is busy on
its free tier's 0.1 CPU? (The two "health check timed out" emails,
2026-11-10 and 2026-11-16: the advisory lists expiring every ADV_TTL and
being recomputed by every request at once.)

    /usr/bin/python3 scripts/dev/stall_check.py [--tree DIR] [--scenario adv_expired|cold|fresh]
                                                [--crawl N] [--on-ms 5] [--life 50]
                                                [--label NAME] [-v]

It boots the real server from DIR (--tree, else $STALL_TREE, else the repo
this file sits in) by calling its own server.main(), so a tree is exercised
as main() configures it: the fixed tree with its feed memo and 128 backlog,
an older tree as it was. The child is throttled to --on-ms of every 100 ms
(SIGSTOP/SIGCONT; 5 on a Mac stands in for Render's 0.1 CPU), /healthz is
probed once a second on its own connection (20 s timeout), and at t=4.5 s
four page requests arrive together (40 s timeout): /api/advisories?source=us,
/safe-and-cheap, /safe-and-cheap?x=1 and /do-not-travel. --crawl N adds N
distinct guide pages to that burst (/guide/<slug>?x=<i>, slugs spread over
public/slugs.json), the shape of a crawler arriving. Prints one JSON line:
probes, errors, over5s, max (worst probe, failures included), max_ok, the
page results as [t, seconds, status, path] with pages_ok and pages_max, and
the config the child saw (backlog, feed memo TTL, switch interval, replay
mode).

Scenarios:
  adv_expired  the three lists are filled unthrottled before boot and then
               aged past ADV_TTL (the 6-hourly expiry, copies in hand); at
               t=4 s _warm_adv_lists runs, as a request would start it.
  cold         empty caches: main()'s own boot warm-ups plus the burst.
  fresh        the three lists filled and current (no refresh runs): what
               the burst alone costs, e.g. what a deeper backlog lets in.

Backlog overflow differs by OS: macOS answers a connection past a full
listen queue with an instant reset (ConnectionResetError at ~0 s here),
Linux (Render) drops the SYN and the client retries it after 1, 3, 7 s...
So an old tree's errors on this Mac are resets, where on Render they are
slow connects, and a deeper backlog's trade (more connections let in, each
then queued behind the others) can only be judged roughly here.

Network: none. Every urlopen is answered from recorded responses in
$STALL_NETCACHE (files <sha1 of the URL>.body + .json {"status", "headers"};
never committed), and any other URL fails as offline. Without that
directory the three advisory parsers are replaced by synthetic stand-ins
that burn about what the real ones do (US 0.4 s, Canada 0.12 s, Germany
0.08 s of CPU on a Mac) and return small lists, so it still runs.

Runs ~life + 5 s; split runs to keep each command under a minute. Starts
one child process and kills only it.
"""
import argparse
import hashlib
import http.client
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
NETCACHE = os.environ.get("STALL_NETCACHE") or (
    "/private/tmp/claude-501/-Users-doug-Desktop-Claude-Workspace/"
    "5f5f209c-3c7f-483b-8747-bd588d9b4133/scratchpad/health/bg/netcache")
BURST = ["/api/advisories?source=us", "/safe-and-cheap", "/safe-and-cheap?x=1", "/do-not-travel"]
BURST_AT = 4.5
PAGE_TIMEOUT = 40   # the burst's own timeout, so a slow cold page reports its time (probes: 20 s)
SCENARIOS = ("adv_expired", "cold", "fresh")


# ---- the child: the real server on replayed responses ------------------------------
def serve(port, scen, life, tree):
    import urllib.error
    import urllib.request
    import socketserver

    sys.path.insert(0, tree)
    os.chdir(tree)
    t0 = time.time()
    say = lambda msg: print("[srv %5.1fs] %s" % (time.time() - t0, msg), flush=True)
    config = {"replay": "netcache" if os.path.isdir(NETCACHE) else "synthetic"}
    blocked = []

    class Resp(io.BytesIO):
        status = 200

        def __init__(self, body, headers):
            super().__init__(body)
            self.headers = headers

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    def fake_urlopen(req, *a, **kw):
        url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
        h = hashlib.sha1(url.encode()).hexdigest()
        body = os.path.join(NETCACHE, h + ".body")
        if config["replay"] == "netcache" and os.path.exists(body):
            with open(os.path.join(NETCACHE, h + ".json"), encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("status", 200) == 200:
                with open(body, "rb") as f:
                    return Resp(f.read(), meta.get("headers", {}))
        blocked.append(url)
        raise urllib.error.URLError("offline in stall_check: " + url)

    urllib.request.urlopen = fake_urlopen

    activate = socketserver.TCPServer.server_activate

    def server_activate(self):
        config["backlog"] = self.request_queue_size
        config["server_class"] = type(self).__name__
        activate(self)

    socketserver.TCPServer.server_activate = server_activate

    import server
    from fxtracker import advisories

    if config["replay"] == "synthetic":
        synthetic(advisories)

    if scen in ("adv_expired", "fresh"):
        for s in server._ADV_SRCS:
            server._advisories_payload(s)
    if scen == "fresh":
        say("lists filled, current: %s"
            % {s: len(server._adv_cache[s][1].get("items") or []) for s in server._adv_cache})
    if scen == "adv_expired":
        for s in list(server._adv_cache):
            at, data = server._adv_cache[s]
            server._adv_cache[s] = (at - server.ADV_TTL - 1, data)
        memo = getattr(advisories, "_feed_memo", None)
        if memo is not None:
            memo.clear()   # a 6 h-old parse would be long expired
        say("lists filled and aged past ADV_TTL: %s"
            % {s: len(server._adv_cache[s][1].get("items") or []) for s in server._adv_cache})

    def work():
        time.sleep(1)
        config["feed_memo_ttl"] = getattr(advisories, "FEED_MEMO_TTL", None)
        config["switch_interval"] = sys.getswitchinterval()
        say("config " + json.dumps(config, sort_keys=True))
        if scen == "adv_expired":
            time.sleep(3)
            server._warm_adv_lists()
            say("_warm_adv_lists started")

    def killer():
        time.sleep(life)
        say("exit, process CPU %.2fs, %d blocked URLs (%s)"
            % (time.process_time(), len(blocked), ", ".join(sorted(set(blocked)))[:300]))
        sys.stdout.flush()
        os._exit(0)

    threading.Thread(target=work, daemon=True).start()
    threading.Thread(target=killer, daemon=True).start()
    sys.argv = ["server.py", str(port)]
    server.main()


def synthetic(advisories):
    """CPU-bound stand-ins for the three feed parsers."""
    import re
    try:
        with open(os.path.join(advisories.ROOT, "public", "ppp.json"), encoding="utf-8") as f:
            isos = sorted(k for k in json.load(f) if len(k) == 2 and k.isupper())
    except Exception:
        isos = ["JP", "TH", "VN", "MA", "CL", "EG", "PE", "MX", "IN", "BF", "SA", "VE"]
    text = "<item><title>Somewhere - Level 2: Exercise Increased Caution</title></item>" * 400

    def make(src, cost, salt):
        def parse():
            c0 = time.thread_time()
            while time.thread_time() - c0 < cost:
                re.findall(r"<title>(.*?)</title>", text)
            items = [{"iso": i, "country": i, "level": 1 + (sum(map(ord, i)) + salt) % 4,
                      "level_text": "", "link": "https://example.invalid/" + i} for i in isos]
            items.sort(key=lambda r: (-r["level"], r["country"]))
            return {"items": items, "count": len(items), "matched": len(items), "source": src,
                    "source_name": advisories.SOURCES[src], "source_url": "https://example.invalid/"}
        return parse

    advisories._us_advisories = make("us", 0.4, 0)
    advisories._canadian_advisories = make("ca", 0.12, 1)
    advisories._german_advisories = make("de", 0.08, 2)


# ---- the orchestrator ------------------------------------------------------------------
def crawl_paths(tree, n):
    """n distinct guide pages, slugs spread evenly over the tree's slugs.json."""
    if n <= 0:
        return []
    with open(os.path.join(tree, "public", "slugs.json"), encoding="utf-8") as f:
        slugs = sorted(json.load(f))
    step = max(1, len(slugs) // n)
    return ["/guide/%s?x=%d" % (slug, i) for i, slug in enumerate(slugs[::step][:n])]


def run(tree, scen, on_ms, life, label, verbose, crawl=0):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    log = tempfile.NamedTemporaryFile("w+", prefix="stall_check_", suffix=".log", delete=False)
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE") or k.startswith("LC_")}
    env["STALL_NETCACHE"] = NETCACHE
    srv = subprocess.Popen([sys.executable, "-I", "-B", os.path.abspath(__file__), "--serve",
                            str(port), scen, str(life), tree],
                           stdout=log, stderr=subprocess.STDOUT if verbose else subprocess.DEVNULL, env=env)
    stop = [False]

    def cleanup():
        stop[0] = True
        try:
            os.kill(srv.pid, signal.SIGCONT)
        except OSError:
            pass
        if srv.poll() is None:
            srv.kill()
        srv.wait(timeout=10)

    try:
        t0 = time.time()
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
                if srv.poll() is not None or time.time() - t0 > 60:
                    log.seek(0)
                    sys.stderr.write(log.read())
                    raise SystemExit("server did not start")
        boot = time.time() - t0
        t0 = time.time()
        probes, pages, lock = [], [], threading.Lock()

        def get(path, store, timeout=20):
            st = time.time()
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
                c.request("GET", path)
                r = c.getresponse()
                r.read()
                code = r.status
                c.close()
            except socket.timeout:
                code = "timeout"
            except Exception as e:
                code = type(e).__name__
            with lock:
                store.append([round(st - t0, 2), round(time.time() - st, 3), code, path])

        def throttle():
            if on_ms <= 0:
                return
            while not stop[0] and srv.poll() is None:
                os.kill(srv.pid, signal.SIGCONT)
                time.sleep(on_ms / 1000.0)
                if stop[0]:
                    break
                os.kill(srv.pid, signal.SIGSTOP)
                time.sleep((100 - on_ms) / 1000.0)
            try:
                os.kill(srv.pid, signal.SIGCONT)
            except OSError:
                pass

        def burst():
            time.sleep(BURST_AT)
            for p in BURST + crawl_paths(tree, crawl):
                threading.Thread(target=get, args=(p, pages, PAGE_TIMEOUT), daemon=True).start()

        threading.Thread(target=throttle, daemon=True).start()
        threading.Thread(target=burst, daemon=True).start()
        while time.time() - t0 < life - 3:
            threading.Thread(target=get, args=("/healthz", probes), daemon=True).start()
            time.sleep(1.0)
        time.sleep(2.5)
        stop[0] = True
        time.sleep(0.3)
        try:
            os.kill(srv.pid, signal.SIGCONT)
        except OSError:
            pass
        srv.wait(timeout=30)
    finally:
        cleanup()
    log.seek(0)
    lines = log.read().splitlines()
    log.close()
    os.unlink(log.name)
    config = {}
    for ln in lines:
        if "] config {" in ln:
            config = json.loads(ln.split("] config ", 1)[1])
    with lock:
        probes = sorted(probes)
        pages = sorted(pages)
    lat_ok = sorted(p[1] for p in probes if p[2] == 200)
    errs = [p for p in probes if p[2] != 200]
    res = {"label": label, "tree": tree, "scenario": scen, "on_ms": on_ms, "crawl": crawl,
           "boot_s": round(boot, 2),
           "probes": len(probes), "ok": len(lat_ok), "errors": len(errs),
           "over1s": sum(1 for p in probes if p[2] != 200 or p[1] > 1),
           "over5s": sum(1 for p in probes if p[2] != 200 or p[1] > 5),
           "max": max((p[1] for p in probes), default=None),
           "max_ok": lat_ok[-1] if lat_ok else None,
           "p50_ok": lat_ok[len(lat_ok) // 2] if lat_ok else None,
           "pages_ok": sum(1 for p in pages if p[2] == 200),
           "pages_max": max((p[1] for p in pages), default=None),
           "pages": pages, "config": config,
           "slow_probes": [p[:3] for p in probes if p[2] != 200 or p[1] > 1][:30]}
    print(json.dumps(res))
    if verbose:
        sys.stderr.write("\n".join(lines[-80:]) + "\n")
    return res


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        port, scen, life, tree = sys.argv[2:6]
        serve(int(port), scen, float(life), tree)
        return
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tree", default=os.environ.get("STALL_TREE") or REPO)
    ap.add_argument("--scenario", choices=SCENARIOS, default="adv_expired")
    ap.add_argument("--crawl", type=int, default=0, metavar="N",
                    help="add N distinct guide pages to the burst")
    ap.add_argument("--on-ms", type=float, default=5.0)
    ap.add_argument("--life", type=float, default=50.0)
    ap.add_argument("--label", default="")
    ap.add_argument("-v", "--verbose", action="store_true", help="the child's log (and request log) on stderr")
    a = ap.parse_args()
    tree = os.path.abspath(a.tree)
    if not os.path.exists(os.path.join(tree, "server.py")):
        raise SystemExit("no server.py in %s" % tree)
    run(tree, a.scenario, a.on_ms, a.life, a.label or os.path.basename(tree), a.verbose, a.crawl)


if __name__ == "__main__":
    main()

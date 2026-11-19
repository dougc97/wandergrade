#!/usr/bin/env python3
"""Does /healthz still answer inside Render's 5 s while the server is busy on
its free tier's 0.1 CPU? (The two "health check timed out" emails,
2026-11-10 and 2026-11-16: the advisory lists expiring every ADV_TTL and
being recomputed by every request at once.)

    /usr/bin/python3 scripts/dev/stall_check.py [--tree DIR] [--scenario adv_expired|cold|fresh|...]
                                                [--crawl N] [--on-ms 5] [--life 50]
                                                [--block SUBSTR [--block-code N]]
                                                [--burst PATH,PATH] [--burst-at S] [--rate R]
                                                [--gzip] [--exact] [--page-timeout S] [--label NAME] [-v]

It boots the real server from DIR (--tree, else $STALL_TREE, else the repo
this file sits in) by calling its own server.main(), so a tree is exercised
as main() configures it: the fixed tree with its feed memo and 128 backlog,
an older tree as it was. The child is throttled to --on-ms of every 100 ms
(SIGSTOP/SIGCONT; 5 on a Mac stands in for Render's 0.1 CPU), /healthz is
probed once a second on its own connection (20 s timeout), and at t=4.5 s
four page requests arrive together: /api/advisories?source=us,
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
  slowapi      as fresh, but the burst is three /api/watchouts requests whose
               upstream (Canada's per-country notes) answers --slow-s (8) s
               late, and half a second later a visitor asks for /, a guide,
               app.js and the cached /api/advisories?source=us: "visitors"
               gives each one's seconds, "visitors_max" the worst. Requests
               idle on an upstream must not hold the visitor up.
  nov18_crawl  as fresh, then the crawl behind Render's alert of 2026-11-18
               14:30:00-14:31:58 ET (a64aea2), paced open-loop for 120 s.
  nov18_scrape as fresh, then the 99 requests of the scrape of 2026-11-18
               21:35:16 ET that reached production (0c811b5, which rode it
               out), within 3.2 s.
  nov18_scrape_all  the same scraper read as asking for every guide: 194
               pages in 5 s, twice what reached the origin. A stress test.
               All three are described under "The Nov 18 replays" below.

--block SUBSTR fails every fetch whose URL contains it (a feed that is down:
--block travel.state.gov), as offline (URLError: 3 tries, 4.5 s of backoff),
or with --block-code N as HTTP N at once (a 4xx is not retried). --burst
replaces the burst's paths and --burst-at its time, e.g. a cold start with
the US feed down and one request for each list right after boot:
  --scenario cold --block travel.state.gov --burst-at 1 --burst \
  '/api/advisories?source=us,/api/advisories?source=ca,/api/advisories?source=de,/do-not-travel'

--rate R sends the burst open-loop instead of all at once: request i goes at
burst_at + i/R s on its own connection, whether or not the earlier ones have
been answered, the way a crawler paces itself (Render's log of 2026-11-16:
~130 /guide/<slug> GETs in 47 s, 2.8 a second). --gzip makes the burst's
requests ask for gzip as Cloudflare and Googlebot do (the probes don't), so
each page pays its compression; without it every page goes out raw, about a
third of a production page's CPU short. "pages_shed" counts burst pages
answered 503 (load shed), "duty_pct" is the throttle's measured share of
on-time (it oversleeps), and "probe_list" is every probe as [t, s, status].

The Nov 16 replay (a sustained crawl that starts after the boot warm-ups):
  --scenario fresh --burst '' --crawl 130 --rate 2.8 --burst-at 45 --life 110 --on-ms 2 [--gzip]
Calibration, 2026-11-18 on an M5: --on-ms 2 is the setting at which the tree
from before the fix (a7cdbd2) fails this replay as Render did on Nov 16 (33
probe errors, 45 over 5 s); at --on-ms 5 both it and a64aea2 pass, so 5 is
too gentle to judge a crawl by (at 3, 2026-11-19, a7cdbd2 still failed, 17
probe errors, all listen-queue resets, and a64aea2 passed; the Nov 18
calibration below). It is not a capacity model: the throttle
gives 2.4-3.0 ms per 100 (duty_pct 2.4-2.8), and the Mac's speed under it
moves run to run (the same 130 gzip pages cost 3.4-4.9 s of CPU at on-ms 2,
1.06 s at 5), so shed counts carry about +-30 of noise between runs. Read
collapse against no collapse (probes over 5 s, the worst probe) and repeat
a run before believing a difference. Requests still in flight when the
child exits at --life show as RemoteDisconnected or ConnectionResetError.

The Nov 18 replays, from Render's application log (read 2026-11-19; its
lines give the second an answer went out, to the microsecond, and come in
100 ms clusters: the container's CPU quota period). All start after the
boot warm-ups (--burst-at defaults to 45 for them), always ask for gzip
(every real request came through Cloudflare) and follow a 301 the way a
crawler does: GET the Location 1-3 s after the answer (fixed per URL and
visit; the log's uncongested follows were answered 1.6-2.5 s after their
301, the render included). --burst, --crawl and --clients don't apply.
  nov18_crawl   2026-11-18 14:30:00 ET on a64aea2: idle before, then one
                crawler until Render restarted the container at 14:31:58. In
                the first 46 s a64aea2 answered 157 requests, 3.4 a second:
                58 query-form /?tab=guide&gc=XX (301 to /guide/<slug>), 89
                /guide/<slug> (the follows and ~20% more), 6 /cheapest/<month>,
                /data twice, /privacy and gc=SC (no guide: a homepage render)
                once. Probes were answered on schedule until 14:30:46.9, one
                more at 14:31:00.8 (4-9 s late), then none: a64aea2 failed
                ~47-52 s into the crawl. Past 14:30:46 it still answered
                301s, 1-2 a second, and a guide only now and then.
                Here: 37% query form (the log's codes in its order,
                NOV18_CODES, 138 of them, 89 distinct: the crawler came back
                to a code 20-60 s later), as many follows, 20% other
                /guide/<slug>, 4% /cheapest/<month> (the log's months in
                turn), /data twice, /privacy and /safe-and-cheap once, on a
                fixed schedule over 120 s, 3.5 a second with their follows if
                every redirect is answered (--rate R sets that total). Its
                User-Agent names it a crawler. --life defaults to burst_at +
                135.
  nov18_scrape  2026-11-19 02:35:16 UTC on 0c811b5, no alert: a scraper with
                a browser's User-Agent. 99 requests reached the origin within
                3.2 s: /privacy, /guide/vietnam, /, /guide/thailand, then
                mexico, egypt and tunisia, then the guides from afghanistan
                to kosovo in alphabetical order (but belarus and greenland).
                Production answered 32 (the four and 28 guides, the last 4.6 s
                after the first request) and shed 67, every one with 8
                already waiting. [busy] at +0.3 s: "1 queued deep, queue peak
                4, now 4 waiting, 2/2 slots in use"; for the window: "shed 67
                (67 with 8+ waiting, 0 after 15s; 0 to crawler UAs), 0
                slotless, 15 queued deep, queue peak 8". Every probe on
                schedule (the one due 0.94 s in answered 14 ms late). Here the
                four at their log spacing (0, 0.115, 0.133, 0.289 s), the 95
                guides evenly from 0.30 to 3.25 s. --life defaults to
                burst_at + 65.
  nov18_scrape_all  the scrape as first read from the log: the four 50 ms
                apart, then all 190 guides evenly over the rest of 5 s. 194
                requests where 99 reached the origin, so ~2.7x production's
                sheds, each paying its accept, thread and 503: a stress test,
                not a replay. --life defaults to burst_at + 65.
  /usr/bin/python3 scripts/dev/stall_check.py --tree DIR --scenario nov18_crawl --on-ms 2
  /usr/bin/python3 scripts/dev/stall_check.py --tree DIR --scenario nov18_scrape --on-ms 2
Calibration against that log (2026-11-19 on an M5, each run alone): the
throttle gives far less than Render did, and only that makes the old trees
fail here.
  nov18_scrape on 0c811b5, pages answered of 99 and the worst probe:
  --on-ms 2: 5, 6.96 s (3 over 5 s); 3: 11, 3.35 s; 4: 11, 1.22 s; 5: 12,
  0.56 s, the last page 6.9 s in. Production: 32, the last 4.6 s in, every
  probe on time. Render worked through the queue ~2.5x as fast as --on-ms 5
  and ~8x as fast as 3.
  nov18_crawl on a64aea2, pages and 301s answered in the first 46 s, and
  the first probe over 5 s: --on-ms 2: 14 + 28, 9.4 s in; 3: 24 + 36, 31.6
  s in; 4: 46 + 39, none; 5: 91 + 53, none. Production: 99 + 58 (it kept up
  with the crawler), then failed 47-52 s in. At the pace Render showed, the
  replay doesn't fail a64aea2: what tipped production over isn't in it (a
  background refresh is the first suspect; a64aea2 predates the [refresh]
  lines that would say).
So --on-ms 2 is a margin gate, harsher than production on both trees (it
fails 0c811b5 on the scrape production rode out), and 3 is where a64aea2
falls over about when production did (31-49 s into the crawl over these
runs and the earlier mix) while 0c811b5 rides the scrape out; from 4 up
a64aea2 passes the crawl, too gentle to judge one by. Neither is a capacity
model: compare trees side by side at one setting.
Their JSON adds "planned" (the requests on the schedule, follows not
counted), "offered" (planned + follows_sent: what the tree was asked, which
depends on how many 301s it answered, so compare trees by "by_kind"), "codes"
(every page's status, a request that got none by its error's name),
"pages_301", "dropped" (pages that got no status),
"by_kind" (the codes per kind: query, follow, guide, cheapest, other),
"query_sent"/"query_301"/"query_503" (the query-form URLs and how many were
answered 301 and how many shed 503 instead), "follows_sent" and
"follows_unsent" (a follow due after the run's end), "first_bad_probe"
(seconds after the burst began that the first probe failed or took over
5 s) and "busy" (the child's [busy] lines; -v only, as the server writes
them to stderr). Each page row carries its kind as a fifth field.

--switch S sets the child's server.SWITCH_INTERVAL (main()'s GIL switch
interval) for a sweep, and --clients N fetches the burst through N clients,
one request after another. "cpu_s" is the child's process CPU from t=1 s to
its exit, "burst_wall_s" (with --clients) the burst's wall time; the
overhead workload, unthrottled, is 60 guides by 8 clients while the lists
refresh in the background:
  --scenario adv_expired --on-ms 0 --burst '' --burst-at 4 --crawl 60 --clients 8 --life 20

Backlog overflow differs by OS: macOS answers a connection past a full
listen queue with an instant reset (ConnectionResetError at ~0 s here),
Linux (Render) drops the SYN and the client retries it after 1, 3, 7 s...
So an old tree's errors on this Mac are resets, where on Render they are
slow connects, and a deeper backlog's trade (more connections let in, each
then queued behind the others) can only be judged roughly here.

Network: none. Every urlopen is answered from recorded responses in
$STALL_NETCACHE (files <sha1 of the URL>.body + .json {"url", "status",
"headers"}; never committed), and any other URL fails as offline, except
that a URL carrying today's date on api.fxratesapi.com or api.worldbank.org
(the rates' one-year timeseries, the World Bank's year range) gets the
recording's reply for the same URL with its dates blanked ("dated_replays"
lists them; --exact turns it off: before 2026-11-19 those fetches failed
as offline on every tree, so the replay rendered its pages without rates). The FX history's
pieces (rates._history_spans: get_history fetches 1999-today in 5-year
replies) are cut from the recorded whole reply before the server starts. Without that
directory the three advisory parsers are replaced by synthetic stand-ins
that burn about what the real ones do (US 0.4 s, Canada 0.12 s, Germany
0.08 s of CPU on a Mac) and return small lists, so it still runs.

A burst request times out after --page-timeout S, by default as long as the
run lets it (life - burst_at - 2: the child exits at life), so a slow page
reports its time instead of a cap. A cold start computes the three lists on
the 0.1 CPU in ~50 s, so comparing the cold burst's advisory pages between
trees needs --life 70 or more: at the default 50 every tree's cold
advisory pages time out alike and can't be told apart (the branch answers
them at 51-52 s; main, measured with 140 s, not at all). That is at
--on-ms 5; at --on-ms 2 the cold start's work (~4.3 s of CPU at a ~2.4%
duty) outlasts even --life 150 (2026-11-19: all four cold pages timed out
at 143.5 s on the branch and on a64aea2 alike), so compare cold pages at
--on-ms 5 and read only the probes of a cold run at 2.

Runs ~life + 5 s; split runs to keep each command under a minute (run a
longer one in the background, at most two at once: they share the CPU).
Starts one child process and kills only it.
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
SCENARIOS = ("adv_expired", "cold", "fresh", "slowapi", "nov18_crawl", "nov18_scrape", "nov18_scrape_all")
# --scenario slowapi: three /api requests whose upstream answers SLOW_S late
# (Canada's per-country notes, each its own fetch), and half a second later a
# visitor's set: the app shell, a guide, a static file, a cached /api route.
SLOW_API = ["/api/watchouts?iso=fr", "/api/watchouts?iso=it", "/api/watchouts?iso=es"]
SLOW_URL = "/travel-voyage/cta-cap-"
SLOW_S = 8.0
VISITORS = ["/", "/guide/japan", "/app.js", "/api/advisories?source=us"]
# --scenario nov18_crawl / nov18_scrape(_all): Render's log of 2026-11-18 (docstring).
NOV18 = ("nov18_crawl", "nov18_scrape", "nov18_scrape_all")
NOV18_BURST_AT = 45.0
NOV18_CRAWL_S = 120.0
NOV18_RATE = 3.5                     # the crawler's requests a second, its follows included
# Shares of all the crawler's requests, its follows included (as many as "query"):
# 30:00-30:46 of the log, before a64aea2 fell behind, 157 answers: 58 query
# form, 89 /guide/ (the follows and ~20% more), 6 /cheapest/, 4 other.
NOV18_SHARES = (("query", 0.37), ("guide", 0.20), ("cheapest", 0.04))
# The query-form codes in the log's order (14:30:00-14:31:59, 138 answered, 89
# distinct: the crawler came back to a code 20-60 s later), cycled. SC has no
# guide: that one is a homepage render.
NOV18_CODES = tuple("""HT UY EG UY RO GH CA HK ID GM SR DK TW JO SA GT LA EG UG JO IL CL UY AU SO MU DE MW BZ CR
    IS ER KP IN FJ ER TJ CR SC LR KE CD GB NA BB PY BT NO RU KW CL GY TM SO MU AU DE SB PG MA IR BD MW IQ IS YE
    JM NG PH AE LK IN BY GE KR PL SD LY SL SR CZ KZ BN AW BR UG TJ PY VU AZ LR DZ RW KE MZ BT NO BB LB AL CL TH SB
    MX NA MU MD CR KW CD IR MA SO LS IS BR IQ ER SE KP IN MW AU BD KG AE GE AO DO KR SD LY UA SL HU CZ MN
    AF""".split())
NOV18_MONTHS = ("july", "april", "october", "may", "february", "march", "october", "september", "march",
                "february")   # /cheapest/<month> in the log's order
NOV18_MISC = ((0.15, "/data"), (0.30, "/privacy"), (0.42, "/safe-and-cheap"), (0.65, "/data"))  # (share of the way in, path)
# nov18_scrape: the 99 requests that reached the origin (2026-11-19 02:35:16-02:35:21 UTC).
NOV18_SCRAPE_HEAD = ("/privacy", "/guide/vietnam", "/", "/guide/thailand")
NOV18_SCRAPE_HEAD_AT = (0.0, 0.115, 0.133, 0.289)   # their answers' spacing in the log
NOV18_SCRAPE_FIRST = ("mexico", "egypt", "tunisia")  # guides outside the alphabetical run (mexico, egypt answered first)
NOV18_SCRAPE_LAST = "kosovo"                         # the run stopped here: afghanistan..kosovo
NOV18_SCRAPE_SKIP = ("belarus", "greenland")         # in that run, not in the log
NOV18_SCRAPE_SPAN = (0.30, 3.25)                     # the guides, evenly (16.97-19.86 s in the log)
NOV18_SCRAPE_S = 5.0                                 # nov18_scrape_all: every guide inside 5 s
UA_CRAWLER = "Mozilla/5.0 (compatible; ReplayBot/1.0; +https://example.invalid/bot)"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


# ---- the child: the real server on replayed responses ------------------------------
def serve(port, scen, life, tree, opts):
    import urllib.error
    import urllib.request
    import socketserver

    sys.path.insert(0, tree)
    os.chdir(tree)
    t0 = time.time()
    say = lambda msg: print("[srv %5.1fs] %s" % (time.time() - t0, msg), flush=True)
    config = {"replay": "netcache" if os.path.isdir(NETCACHE) else "synthetic"}
    if opts.get("block"):
        config["block"] = opts["block"]
        config["block_code"] = opts.get("block_code")
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
        for sub, secs in (opts.get("delay") or {}).items():
            if sub in url:
                time.sleep(secs)   # a slow upstream: the answer (or the failure) comes late
        if any(b in url for b in opts.get("block") or ()):
            blocked.append(url)
            if opts.get("block_code"):   # an HTTP error at once (4xx: no retries)
                raise urllib.error.HTTPError(url, opts["block_code"], "blocked in stall_check", {}, None)
            raise urllib.error.URLError("blocked in stall_check: " + url)
        if url in pieces:
            return Resp(pieces[url][0], pieces[url][1])
        h = hashlib.sha1(url.encode()).hexdigest()
        body = os.path.join(NETCACHE, h + ".body")
        if config["replay"] == "netcache" and not os.path.exists(body) and dated.get(dated_key(url)):
            h = dated[dated_key(url)]        # today's date in the URL: the recording's own day
            body = os.path.join(NETCACHE, h + ".body")
            dated_used.append(url)
        if config["replay"] == "netcache" and os.path.exists(body):
            with open(os.path.join(NETCACHE, h + ".json"), encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("status", 200) == 200:
                with open(body, "rb") as f:
                    return Resp(f.read(), meta.get("headers", {}))
        blocked.append(url)
        raise urllib.error.URLError("offline in stall_check: " + url)

    urllib.request.urlopen = fake_urlopen
    pieces = frankfurter_pieces(NETCACHE, tree) if config["replay"] == "netcache" else {}
    dated = dated_index(NETCACHE) if config["replay"] == "netcache" and not opts.get("exact") else {}
    dated_used = []
    if pieces:
        config["fx_history_pieces"] = len(pieces)

    activate = socketserver.TCPServer.server_activate

    def server_activate(self):
        config["backlog"] = self.request_queue_size
        config["server_class"] = type(self).__name__
        activate(self)

    socketserver.TCPServer.server_activate = server_activate

    import server
    from fxtracker import advisories

    if opts.get("switch") and hasattr(server, "SWITCH_INTERVAL"):
        server.SWITCH_INTERVAL = opts["switch"]   # main() hands the GIL round at this

    if config["replay"] == "synthetic":
        synthetic(advisories)

    if scen in ("adv_expired", "fresh", "slowapi") + NOV18:
        for s in server._ADV_SRCS:
            server._advisories_payload(s)
    if scen in ("fresh", "slowapi") + NOV18:
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
        cpu0[0] = time.process_time()
        say("config " + json.dumps(config, sort_keys=True))
        if scen == "adv_expired":
            time.sleep(3)
            server._warm_adv_lists()
            say("_warm_adv_lists started")

    cpu0 = [0.0]

    def killer():
        time.sleep(life)
        cpu = time.process_time()
        say("cpu " + json.dumps({"total": round(cpu, 3), "since_config": round(cpu - cpu0[0], 3)}))
        say("dated " + json.dumps(sorted(set(dated_used))))
        say("exit, process CPU %.2fs, %d blocked URLs (%s)"
            % (cpu, len(blocked), ", ".join(sorted(set(blocked)))[:300]))
        sys.stdout.flush()
        os._exit(0)

    threading.Thread(target=work, daemon=True).start()
    threading.Thread(target=killer, daemon=True).start()
    sys.argv = ["server.py", str(port)]
    server.main()


# Hosts whose URLs carry today's date (the rates' one-year timeseries, the
# World Bank's year range): a run on a later day than the recording asks for
# URLs it doesn't hold, and those fetches failed as offline in every run, so
# pages rendered without rates. They are answered with the recording's reply
# for the same URL with its dates blanked (dated_key), listed in the output
# as "dated_replays"; --exact turns this off. Frankfurter is not one: its
# history pieces are cut above, and a tail request must not get the whole.
DATED_HOSTS = ("api.fxratesapi.com", "api.worldbank.org")


def dated_key(url):
    """`url` with its dates blanked, for a host in DATED_HOSTS, else None."""
    if not any("//%s/" % h in url for h in DATED_HOSTS):
        return None
    import re
    return re.sub(r"date=\d{4}:\d{4}", "date=Y:Y", re.sub(r"\d{4}-\d{2}-\d{2}", "D", url))


def dated_index(netcache):
    """{dated_key(url): sha1 name} over the recording's 200 replies."""
    out = {}
    try:
        names = sorted(os.listdir(netcache))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(netcache, name), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        k = dated_key(meta.get("url") or "")
        if k and meta.get("status", 200) == 200:
            out.setdefault(k, name[:-5])
    return out


def frankfurter_pieces(netcache, tree):
    """{url: (body, headers)} for the pieces the tree's rates.get_history asks
    Frankfurter for (rates._history_spans), cut from the recorded whole
    history (1999-01-04..), which is all the recording holds. Cut here, before
    the server starts and unthrottled, so the server pays only for reading
    them, as from the network. {} for a tree that asks in one piece."""
    try:
        sys.path.insert(0, tree)
        from fxtracker import rates
        spans = rates._history_spans()
        url_of = rates._history_url
    except Exception:
        return {}
    whole = url_of(rates.HISTORY_START)
    h = hashlib.sha1(whole.encode()).hexdigest()
    try:
        with open(os.path.join(netcache, h + ".body"), "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        with open(os.path.join(netcache, h + ".json"), encoding="utf-8") as f:
            headers = json.load(f).get("headers", {})
    except (OSError, ValueError):
        return {}
    out = {}
    for start, end in spans:
        part = {k: v for k, v in (data.get("rates") or {}).items() if start <= k <= (end or "~")}
        if part:
            out[url_of(start, end)] = (json.dumps(dict(data, start_date=min(part), end_date=max(part), rates=part),
                                                  separators=(",", ":")).encode("utf-8"), headers)
    return out


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


def arrival_offsets(n, rate):
    """--rate: request i's start, in seconds after the burst begins (i / rate),
    on a fixed schedule so a slow server can't slow the arrivals down."""
    return [i / float(rate) for i in range(n)]


def page_timeout_for(life, burst_at):
    """The burst's default timeout: as long as the run lets a request take
    (the child exits at `life`), so a slow page reports its own time."""
    return max(5.0, life - burst_at - 2)


def guide_slugs(tree):
    """{slug: iso} of the tree's guides (public/slugs.json)."""
    with open(os.path.join(tree, "public", "slugs.json"), encoding="utf-8") as f:
        return dict(json.load(f))


def nov18_crawl_plan(slug_iso, seconds=NOV18_CRAWL_S, rate=NOV18_RATE, seed=20261118):
    """--scenario nov18_crawl: the crawler's own requests as [(offset s, path,
    kind)] on a fixed schedule over `seconds`, kind "query" (/?tab=guide&gc=XX,
    NOV18_CODES in turn: a 301 to /guide/<slug>, whose follow the run adds, or
    for SC the homepage), "guide", "cheapest" or "other". So many that with one
    follow per "query" they come to `rate` a second. The same plan every time
    (`seed`)."""
    import random
    rng = random.Random(seed)
    total = int(round(seconds * rate))
    kinds = []
    for kind, share in NOV18_SHARES:
        kinds += [kind] * int(round(share * total))
    rng.shuffle(kinds)
    slots = [(k, None) for k in kinds]
    for frac, path in NOV18_MISC:
        slots.insert(int(frac * (len(slots) + 1)), ("other", path))
    iso_slug = {iso: slug for slug, iso in slug_iso.items()}
    codes = sorted(iso_slug)
    rng.shuffle(codes)
    plan, nq, ng, nc = [], 0, 0, 0
    step = seconds / float(len(slots))
    for i, (kind, path) in enumerate(slots):
        if kind == "query":
            path, nq = "/?tab=guide&gc=" + NOV18_CODES[nq % len(NOV18_CODES)], nq + 1
        elif kind == "guide":
            path, ng = "/guide/" + iso_slug[codes[ng % len(codes)]], ng + 1
        elif kind == "cheapest":
            path, nc = "/cheapest/" + NOV18_MONTHS[nc % len(NOV18_MONTHS)], nc + 1
        plan.append((round(i * step, 3), path, kind))
    return plan


def nov18_scrape_plan(slug_iso):
    """--scenario nov18_scrape: [(offset s, path, kind)], the 99 requests of
    the log that reached the origin: the four first pages at their spacing,
    then NOV18_SCRAPE_FIRST and the alphabetical run afghanistan..kosovo
    (less NOV18_SCRAPE_SKIP), evenly over NOV18_SCRAPE_SPAN."""
    head = [(at, p, "guide" if p.startswith("/guide/") else "other")
            for at, p in zip(NOV18_SCRAPE_HEAD_AT, NOV18_SCRAPE_HEAD)]
    taken = set(NOV18_SCRAPE_FIRST) | set(NOV18_SCRAPE_SKIP)
    slugs = [s for s in NOV18_SCRAPE_FIRST if s in slug_iso] + sorted(
        s for s in slug_iso if s <= NOV18_SCRAPE_LAST and s not in taken)
    a, b = NOV18_SCRAPE_SPAN
    step = (b - a) / float(max(1, len(slugs) - 1))
    return head + [(round(a + i * step, 3), "/guide/" + s, "guide") for i, s in enumerate(slugs)]


def nov18_scrape_all_plan(slug_iso, seconds=NOV18_SCRAPE_S):
    """--scenario nov18_scrape_all: [(offset s, path, kind)], the four first
    pages 50 ms apart, then every guide alphabetically, evenly over the rest."""
    head = [(round(i * 0.05, 3), p, "guide" if p.startswith("/guide/") else "other")
            for i, p in enumerate(NOV18_SCRAPE_HEAD)]
    start = 0.05 * len(head)
    slugs = sorted(slug_iso)
    step = (seconds - start) / float(len(slugs))
    return head + [(round(start + i * step, 3), "/guide/" + s, "guide") for i, s in enumerate(slugs)]


def follow_delay(path, nth=0):
    """Seconds a crawler waits after a 301 before it GETs the Location: 1-3,
    fixed per URL and visit (the log's uncongested follows were answered
    1.6-2.5 s after their 301, the render included)."""
    key = path if not nth else "%s#%d" % (path, nth)
    return 1.0 + 2.0 * int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) / float(0xffffffff)


def nov18_summary(pages, probes, plan, burst_at, follows_sent, lines):
    """The Nov 18 replays' extra keys (docstring) from the page rows
    [t, s, status, path, kind], the probe rows and the child's log lines."""
    codes, by_kind = {}, {}
    for p in pages:
        codes[str(p[2])] = codes.get(str(p[2]), 0) + 1
        k = by_kind.setdefault(p[4], {})
        k[str(p[2])] = k.get(str(p[2]), 0) + 1
    query = [p for p in pages if p[4] == "query"]
    n301 = sum(1 for p in pages if p[2] in (301, 302, 307, 308))
    bad = [p[0] - burst_at for p in probes if p[0] >= burst_at and (p[2] != 200 or p[1] > 5)]
    return {"planned": len(plan), "offered": len(plan) + follows_sent, "codes": codes, "pages_301": n301,
            "dropped": sum(1 for p in pages if not isinstance(p[2], int)),
            "by_kind": by_kind, "query_sent": len(query),
            "query_301": sum(1 for p in query if p[2] == 301),
            "query_503": sum(1 for p in query if p[2] == 503),
            "follows_sent": follows_sent, "follows_unsent": n301 - follows_sent,
            "first_bad_probe": round(min(bad), 2) if bad else None,
            "busy": [ln.strip() for ln in lines if "[busy]" in ln]}


def run(tree, scen, on_ms, life, label, verbose, crawl=0, block=(), burst_paths=None, burst_at=BURST_AT,
        block_code=None, slow_s=SLOW_S, switch=None, clients=0, page_timeout=None, rate=0.0,
        gzip_pages=False, exact=False):
    page_timeout = page_timeout or page_timeout_for(life, burst_at)
    plan = []
    if scen == "nov18_crawl":
        rate = rate or NOV18_RATE
        plan = nov18_crawl_plan(guide_slugs(tree), rate=rate)
    elif scen == "nov18_scrape":
        plan = nov18_scrape_plan(guide_slugs(tree))
    elif scen == "nov18_scrape_all":
        plan = nov18_scrape_all_plan(guide_slugs(tree))
    if plan:
        gzip_pages = True   # every real request came through Cloudflare, which asks for gzip
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    log = tempfile.NamedTemporaryFile("w+", prefix="stall_check_", suffix=".log", delete=False)
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE") or k.startswith("LC_")}
    env["STALL_NETCACHE"] = NETCACHE
    opts = {"block": list(block), "block_code": block_code, "switch": switch, "exact": exact}
    if scen == "slowapi":
        opts["delay"] = {SLOW_URL: slow_s}
        if burst_paths is None:
            burst_paths = SLOW_API
    srv = subprocess.Popen([sys.executable, "-I", "-B", os.path.abspath(__file__), "--serve",
                            str(port), scen, str(life), tree, json.dumps(opts)],
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
        duty = [0.0, 0.0]   # the throttle's on-time, its whole time

        def get(path, store, timeout=20):
            st = time.time()
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
                c.request("GET", path, headers={"Accept-Encoding": "gzip"}
                          if gzip_pages and store is pages else {})
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
                a = time.perf_counter()
                os.kill(srv.pid, signal.SIGCONT)
                time.sleep(on_ms / 1000.0)
                if stop[0]:
                    break
                os.kill(srv.pid, signal.SIGSTOP)
                duty[0] += time.perf_counter() - a
                time.sleep((100 - on_ms) / 1000.0)
                duty[1] += time.perf_counter() - a
            try:
                os.kill(srv.pid, signal.SIGCONT)
            except OSError:
                pass

        work = (BURST if burst_paths is None else burst_paths) + crawl_paths(tree, crawl)
        done = []
        ua = UA_CRAWLER if scen == "nov18_crawl" else UA_BROWSER
        inflight, follows = [0], {"sent": 0, "seen": {}}

        def fetch(path, kind):
            """A Nov 18 page: gzip and the replay's User-Agent; a 301 is
            followed after follow_delay, as the crawler did."""
            if kind == "follow":
                with lock:
                    if stop[0]:
                        return
                    follows["sent"] += 1
            with lock:
                inflight[0] += 1
            st, loc = time.time(), None
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=page_timeout)
                c.request("GET", path, headers={"Accept-Encoding": "gzip", "User-Agent": ua})
                r = c.getresponse()
                r.read()
                code, loc = r.status, r.getheader("Location")
                c.close()
            except socket.timeout:
                code = "timeout"
            except Exception as e:
                code = type(e).__name__
            with lock:
                pages.append([round(st - t0, 2), round(time.time() - st, 3), code, path, kind])
                inflight[0] -= 1
            if code in (301, 302, 307, 308) and loc:
                import urllib.parse
                u = urllib.parse.urlsplit(loc)
                target = u.path + ("?" + u.query if u.query else "")
                with lock:
                    nth = follows["seen"].get(path, 0)
                    follows["seen"][path] = nth + 1
                tm = threading.Timer(follow_delay(path, nth), fetch, args=(target, "follow"))
                tm.daemon = True
                tm.start()

        def burst():
            time.sleep(burst_at)
            if plan:   # open-loop on the plan's schedule, answered or not
                start = time.time()
                for at, p, kind in plan:
                    time.sleep(max(0.0, start + at - time.time()))
                    threading.Thread(target=fetch, args=(p, kind), daemon=True).start()
                return
            if rate > 0:   # open-loop: each on its own schedule, answered or not
                start = time.time()
                for p, at in zip(work, arrival_offsets(len(work), rate)):
                    time.sleep(max(0.0, start + at - time.time()))
                    threading.Thread(target=get, args=(p, pages, page_timeout), daemon=True).start()
                return
            if not clients:
                for p in work:
                    threading.Thread(target=get, args=(p, pages, page_timeout), daemon=True).start()
                return
            todo, tl = list(work), threading.Lock()

            def client():
                while True:
                    with tl:
                        if not todo:
                            return
                        p = todo.pop(0)
                    get(p, pages, page_timeout)
            ths = [threading.Thread(target=client, daemon=True) for _ in range(clients)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            done.append(round(time.time() - t0 - burst_at, 3))

        def visitors():
            time.sleep(burst_at + 0.5)
            for p in VISITORS:
                threading.Thread(target=get, args=(p, pages, page_timeout), daemon=True).start()

        threading.Thread(target=throttle, daemon=True).start()
        threading.Thread(target=burst, daemon=True).start()
        if scen == "slowapi":
            threading.Thread(target=visitors, daemon=True).start()
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
        for _ in range(30):   # the Nov 18 pages still reading when the child exited
            with lock:
                if not inflight[0]:
                    break
            time.sleep(0.1)
    finally:
        cleanup()
    log.seek(0)
    lines = log.read().splitlines()
    log.close()
    os.unlink(log.name)
    config, cpu, dated = {}, {}, []
    for ln in lines:
        if "] config {" in ln:
            config = json.loads(ln.split("] config ", 1)[1])
        if "] cpu {" in ln:
            cpu = json.loads(ln.split("] cpu ", 1)[1])
        if "] dated [" in ln:
            dated = json.loads(ln.split("] dated ", 1)[1])
    with lock:
        probes = sorted(probes)
        pages = sorted(pages)
    lat_ok = sorted(p[1] for p in probes if p[2] == 200)
    errs = [p for p in probes if p[2] != 200]
    res = {"label": label, "tree": tree, "scenario": scen, "on_ms": on_ms, "crawl": crawl,
           "block": list(block), "burst_at": burst_at, "clients": clients, "page_timeout": page_timeout,
           "rate": rate, "gzip": gzip_pages, "life": life,
           "duty_pct": round(100 * duty[0] / duty[1], 2) if duty[1] else None,
           "cpu_s": cpu.get("since_config"), "cpu_total_s": cpu.get("total"),
           "burst_wall_s": done[0] if done else None,
           "boot_s": round(boot, 2),
           "probes": len(probes), "ok": len(lat_ok), "errors": len(errs),
           "over1s": sum(1 for p in probes if p[2] != 200 or p[1] > 1),
           "over5s": sum(1 for p in probes if p[2] != 200 or p[1] > 5),
           "max": max((p[1] for p in probes), default=None),
           "max_ok": lat_ok[-1] if lat_ok else None,
           "p50_ok": lat_ok[len(lat_ok) // 2] if lat_ok else None,
           "pages_ok": sum(1 for p in pages if p[2] == 200),
           "pages_shed": sum(1 for p in pages if p[2] == 503),
           "pages_max": max((p[1] for p in pages), default=None),
           "pages": pages, "config": config, "dated_replays": dated,
           "visitors": {p[3]: p[1] if p[2] == 200 else p[2] for p in pages if scen == "slowapi" and p[3] in VISITORS},
           "visitors_max": max((p[1] for p in pages if scen == "slowapi" and p[3] in VISITORS), default=None),
           "slow_probes": [p[:3] for p in probes if p[2] != 200 or p[1] > 1][:30],
           "probe_list": [p[:3] for p in probes]}
    if plan:
        res.update(nov18_summary(pages, probes, plan, burst_at, follows["sent"], lines))
    print(json.dumps(res))
    if verbose:
        sys.stderr.write("\n".join(lines[-80:]) + "\n")
    return res


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        port, scen, life, tree = sys.argv[2:6]
        serve(int(port), scen, float(life), tree, json.loads(sys.argv[6]) if len(sys.argv) > 6 else {})
        return
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tree", default=os.environ.get("STALL_TREE") or REPO)
    ap.add_argument("--scenario", choices=SCENARIOS, default="adv_expired")
    ap.add_argument("--crawl", type=int, default=0, metavar="N",
                    help="add N distinct guide pages to the burst")
    ap.add_argument("--block", action="append", default=[], metavar="SUBSTR",
                    help="fail every fetch whose URL contains SUBSTR, as offline (repeatable), "
                         "e.g. travel.state.gov for a US feed that is down")
    ap.add_argument("--block-code", type=int, metavar="N",
                    help="a blocked fetch answers HTTP N at once (4xx: no retries) instead of "
                         "failing as offline (3 tries, 4.5 s of backoff)")
    ap.add_argument("--burst", metavar="PATH,PATH", help="the burst's paths instead of the default four")
    ap.add_argument("--burst-at", type=float, metavar="S",
                    help="when the burst starts (default %s s; %s for the nov18 scenarios)" % (BURST_AT, NOV18_BURST_AT))
    ap.add_argument("--slow-s", type=float, default=SLOW_S, metavar="S",
                    help="slowapi: how late the slow upstream answers")
    ap.add_argument("--clients", type=int, default=0, metavar="N",
                    help="fetch the burst through N clients one request after another "
                         "(default: every request at once)")
    ap.add_argument("--rate", type=float, default=0.0, metavar="R",
                    help="send the burst open-loop at R requests a second (default: all at once)")
    ap.add_argument("--exact", action="store_true",
                    help="no date-blanked replays: a URL with today's date that the recording lacks fails "
                         "as offline (how runs before 2026-11-19 replayed)")
    ap.add_argument("--gzip", action="store_true",
                    help="burst requests ask for gzip, as Cloudflare and Googlebot do")
    ap.add_argument("--switch", type=float, metavar="S",
                    help="the child's GIL switch interval (server.SWITCH_INTERVAL) for a sweep")
    ap.add_argument("--on-ms", type=float, default=5.0)
    ap.add_argument("--life", type=float,
                    help="the child exits at S (default 50; nov18_crawl burst_at + 135, nov18_scrape(_all) "
                         "burst_at + 65)")
    ap.add_argument("--page-timeout", type=float, metavar="S",
                    help="the burst's timeout (default life - burst_at - 2, as long as the run allows)")
    ap.add_argument("--label", default="")
    ap.add_argument("-v", "--verbose", action="store_true", help="the child's log (and request log) on stderr")
    a = ap.parse_args()
    tree = os.path.abspath(a.tree)
    if not os.path.exists(os.path.join(tree, "server.py")):
        raise SystemExit("no server.py in %s" % tree)
    burst_at = a.burst_at if a.burst_at is not None else NOV18_BURST_AT if a.scenario in NOV18 else BURST_AT
    life = a.life if a.life is not None else (
        burst_at + NOV18_CRAWL_S + 15 if a.scenario == "nov18_crawl" else
        burst_at + 65 if a.scenario in ("nov18_scrape", "nov18_scrape_all") else 50.0)
    run(tree, a.scenario, a.on_ms, life, a.label or os.path.basename(tree), a.verbose, a.crawl,
        a.block, [p for p in a.burst.split(",") if p] if a.burst is not None else None, burst_at,
        a.block_code, a.slow_s, a.switch, a.clients, a.page_timeout, a.rate, a.gzip, a.exact)


if __name__ == "__main__":
    main()

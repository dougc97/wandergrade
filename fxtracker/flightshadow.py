"""Fare sources side by side: today's /v1/prices/monthly curves against
aviasales/v3/grouped_prices. LOG ONLY: nothing a reader sees reads this
module, and it writes nothing the site reads (no fare cache, no curve cache,
no fares refresh). Doug's call, 2026-11-26: two weeks of a free comparison,
then decide whether to switch. A switch could cut the fare warm-up after a
deploy from ~9 minutes to ~1 (600 calls/min against 20/min), and the
6-month band bar stays either way.

What it compares (the Oct 26 spike, memory flight-value-feature): with no
trip length grouped_prices answers ONE-WAY fares (~0.52x), so it asks
market=us + min_trip_duration=1 + max_trip_duration=60, the documented
settings that matched today's source on 92% of months; rows without a
return date (one way) and answers with success:false are not fares. Stops
are the larger leg's (max(transfers, return_transfers)), as today's source
counts them. Its known risk, measured here: it keeps the cheapest fare seen
over about a week, so this month and next may read cheaper ("Low") than
today's source says.

Once a day, off the request path, for the default origin only (US, the
origin a switch would start with): for every destination country in the
cached fares payload, the same cities the live curve uses (its top three,
stopping once ten months are covered, flights.get_monthly_multi), fetched
from grouped_prices one call at a time, PACE seconds apart (60/min, a tenth
of the documented limit), and laid beside the live curves read from the
cache alone (flights.monthly_cached), each built into the country curve the
site shows (flights.get_country_monthly, the same latest-prices fill on both
sides) and banded the Flights tab's way (flightvalue.curve_stats / band).

When: never in the first FIRST_DELAY after boot (the boot warm-ups), never
before the default origin's first fare fill has finished or while any fill
runs, never while the server says it is busy (an advisory refresh, the
health or guide-facts rebuild, the FX history fetch, page slots in use or
pages queued or shed in the last 10 minutes: server._flight_shadow_busy), which is
asked again before every call: busy past BUSY_GIVE_UP and the run is dropped
(nothing stored) and tried again at a later check, at most TRIES_PER_DAY a
day. It stops by itself after WANTED complete daily runs, or after UNTIL.

Storage, in Upstash (the accounts client, accounts._redis), so the record
survives deploys; nothing runs without it:
  fshadow:day:<YYYY-MM-DD>  one day's summary (JSON, at most MAX_BYTES), TTL 30 days
  fshadow:lock              a run in progress (SET NX, TTL 15 min): one process at a time
  fshadow:done              set once WANTED complete days are stored, TTL 60 days
Read once at start and after each run, never on a request: /api/flight-shadow
answers from memory (body()), and scripts/dev/flight_shadow_report.py turns
that JSON into plain words.

Env: RENDER (runs there), FLIGHT_SHADOW=1 (runs anyway, local testing),
FLIGHT_SHADOW=0 (never), FLIGHT_SHADOW_DELAY (seconds before the first check,
default FIRST_DELAY), FLIGHT_SHADOW_UNTIL (YYYY-MM-DD, default UNTIL).
"""

import datetime
import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import accounts, flights, flightvalue, rates

V = 1
ORIGIN = flightvalue.DEFAULT_ORIGIN
PATH = "/aviasales/v3/grouped_prices"
# The settings the Oct 26 spike found comparable (round 2, R1_60). Never the
# token: it is added per call and never stored, logged or served.
PARAMS = {"group_by": "month", "currency": "usd", "market": "us",
          "min_trip_duration": "1", "max_trip_duration": "60"}
PACE = 1.0           # seconds between grouped calls: 60/min against a documented 600/min
MAX_CALLS = 400      # per run (~117 countries x at most 3 cities = 351)
MAX_FAILS = 5        # failed calls in a row end the run (stored as aborted)
SWITCH_PACE = 0.3    # the gap a switched warmer would leave between calls (200/min)
NEAR = 2             # window months 0 and 1 (this month and next): the near-term check
SAME_WITHIN = 0.05   # "within 5%"
DAY_TTL = 30 * 86400
LOCK_TTL = 15 * 60
DONE_TTL = 60 * 86400
KEY_DAY = "fshadow:day:"
KEY_LOCK = "fshadow:lock"
KEY_DONE = "fshadow:done"
KEEP_DAYS = 30
WANTED = 14          # complete daily runs, then it stops
UNTIL = "2026-12-31"
MAX_BYTES = 64 * 1024
FIRST_DELAY = 30 * 60
CHECK_EVERY = 15 * 60
BUSY_WAIT = 5
BUSY_GIVE_UP = 120
TRIES_PER_DAY = 8
UA = "fx-tracker/1.0"
BANDS = {"low": "L", "typical": "T", "high": "H", None: "-"}

_lock = threading.Lock()
_days = {}           # "YYYY-MM-DD" -> summary, the last KEEP_DAYS
_state = {"state": "off", "why": "not started", "checked": None, "finished": False,
          "tries": {}, "ver": 0}
_body = {"ver": -1, "raw": b"", "gz": None}
_sleep = time.sleep  # tests replace it
_clock = time.monotonic


class _Abandon(Exception):
    """The server got busy and stayed busy: drop the run, store nothing."""


class _Abort(Exception):
    """Upstream keeps failing: end the run, store what it says."""


def _utc_day(now=None):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _utc_stamp(now=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def until():
    v = (os.environ.get("FLIGHT_SHADOW_UNTIL") or "").strip()
    try:
        return datetime.date.fromisoformat(v).isoformat()
    except ValueError:
        return UNTIL


def _set_state(state, why, **kw):
    with _lock:
        _state.update(state=state, why=why, checked=_utc_stamp(), **kw)
        _state["ver"] += 1


# ---- upstream ----------------------------------------------------------------

def _fetch(url):
    """One GET: (HTTP status or 0, parsed JSON or None, milliseconds). Never
    raises and never retries (every call is counted), and nothing it logs or
    returns carries the URL, which holds the token."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=rates.TIMEOUT, context=rates._SSL) as r:
            status, raw = r.status, r.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = None
    except urllib.error.HTTPError as e:
        status, body = e.code, None
    except Exception:
        status, body = 0, None
    return status, body, round((time.monotonic() - t0) * 1000)


def months_of(body):
    """grouped_prices' answer as {YYYY-MM: {price, stops, departure_at}}
    plus how many rows were one-way (no return date, not a fare here); None
    when it is not an answer (success false, no data)."""
    if not isinstance(body, dict) or body.get("success") is False or not isinstance(body.get("data"), dict):
        return None, 0
    out, oneway = {}, 0
    for k, v in body["data"].items():
        if not isinstance(v, dict) or v.get("price") is None:
            continue
        if not v.get("return_at"):
            oneway += 1
            continue
        try:
            price = round(float(v["price"]))
        except (TypeError, ValueError):
            continue
        stops = v.get("transfers")
        if v.get("return_transfers") is not None:
            stops = max(stops or 0, v.get("return_transfers") or 0)
        out[str(k)[:7]] = {"price": price, "stops": stops, "departure_at": v.get("departure_at")}
    return out, oneway


class _Grouped:
    """The paced grouped_prices lookup for one run, shaped like
    flights.monthly_cached (None = no curve: the call failed), memoized per
    city so a country asked twice costs one call."""

    def __init__(self, origin, busy=None):
        self.origin, self.hub = origin, flights.ORIGIN_HUBS[origin][0]
        self.busy = busy
        self.memo = {}
        self.ms, self.statuses = [], {}
        self.calls = self.failed = self.rejected = self.oneway = 0
        self.fails = 0
        self.capped = False
        self.busy_waits = 0
        self.next_at = 0.0

    def _quiet(self):
        """Wait while the server is busy or a live fare fill runs (its curves
        are what this compares against); _Abandon after BUSY_GIVE_UP."""
        waited = 0.0
        while True:
            why = (self.busy() if self.busy else None) or \
                ("fares filling" if flightvalue.warming_any() else None)
            if not why:
                return
            if waited >= BUSY_GIVE_UP:
                raise _Abandon(why)
            self.busy_waits += 1
            _sleep(BUSY_WAIT)
            waited += BUSY_WAIT

    def __call__(self, origin, city, cur="usd"):
        if city in self.memo:
            return self.memo[city]
        if self.calls >= MAX_CALLS:
            self.capped = True
            return None
        self._quiet()
        wait = self.next_at - _clock()
        if wait > 0:
            _sleep(wait)
        self.next_at = _clock() + PACE
        q = dict(PARAMS, origin=self.hub, destination=city, token=flights.token())
        status, body, ms = _fetch("%s%s?%s" % (flights.API, PATH, urllib.parse.urlencode(q)))
        self.calls += 1
        self.ms.append(ms)
        self.statuses[str(status)] = self.statuses.get(str(status), 0) + 1
        months, oneway = months_of(body) if status == 200 else (None, 0)
        self.oneway += oneway
        if months is None:
            self.failed += 1
            if status == 200:
                self.rejected += 1
            self.fails += 1
            if self.fails >= MAX_FAILS:
                raise _Abort("%d failed calls in a row (last HTTP %s)" % (self.fails, status or "none"))
            self.memo[city] = None
            return None
        self.fails = 0
        out = {"configured": True, "origin": origin, "hub": self.hub, "dest": city,
               "currency": cur, "months": flights._upcoming(months)}
        self.memo[city] = out
        return out


# ---- comparison ---------------------------------------------------------------

def _q(vals, q):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else None


def _close(a, b):
    return abs(b / a - 1) <= SAME_WITHIN if a else a == b


def _window_curve(route, full, inwin):
    """{month: (price, kind)} of a country curve in the window: kind "r" for
    a route-curve month, "f" for a latest-prices fill month. None when the
    curve is missing (pending)."""
    if full is None:
        return None
    rm = (route or {}).get("months") or {}
    return {k: (v["price"], "r" if k in rm else "f")
            for k, v in sorted((full.get("months") or {}).items()) if k in inwin}


def _bands(curve, partial):
    prices = {k: p for k, (p, _) in curve.items()}
    stats = flightvalue.curve_stats(flightvalue.stats_prices(prices, partial))
    return stats, {k: flightvalue.band(p, stats) for k, p in prices.items()}


def compare(origin, fares, grouped, live=None, today=None, now=None):
    """The day's comparison, pure: `grouped` and `live` are lookups shaped
    like flights.monthly_cached (live's default: that, the cache alone;
    grouped is asked each city at most once per country and should memoize,
    as _Grouped does). Returns {"window", "partial", "tab_month", "agg",
    "live", "dest"}."""
    live = live or flights.monthly_cached
    now = time.time() if now is None else now
    today = today or datetime.date.today()
    window = flightvalue.window_months(today)
    pos = {k: i for i, k in enumerate(window)}
    inwin = set(window)
    partial = flightvalue.partial_month(today)
    # The Flights tab's default month: next month after the 15th (app.js).
    tab_month = window[1] if today.day > 15 else window[0]
    rows = [r for r in (fares or {}).get("countries") or [] if r.get("iso")]
    rows.sort(key=lambda r: (-(r.get("n") or 0), r["iso"]))

    cm = dict(both=0, same=0, within5=0, live_only=0, shadow_only=0)
    rm = dict(both=0, same=0, within5=0, live_only=0, shadow_only=0, shadow_cheaper=0,
              live_cheaper=0, stops_same=0, dep_same=0, routes=0, live_missing=0)
    banded = dict(live=0, shadow=0, both=0, live_only=0, shadow_only=0)
    ready = dict(countries=len(rows), live=0, shadow=0, both=0)
    bands = {"both": 0, "agree": 0, "matrix": {}}
    by_route = [[0, 0, 0, 0] for _ in window]          # both, same, shadow cheaper, live cheaper
    by_band = [[0, 0, 0, 0, 0, 0] for _ in window]     # both banded, agree, low L/S, high L/S
    ratios, near_ratios = [], []
    ages, stale = [], 0
    entries = dict(flights.monthly_entries()) if live is flights.monthly_cached else {}
    dest = {}

    hub = flights.ORIGIN_HUBS[origin][0]
    for row in rows:
        iso = row["iso"]
        cities = flights.country_cities(row)
        asked = []

        def peek(o, c, cur="usd"):
            asked.append(c)
            return grouped(o, c, cur)

        lr = flights.get_monthly_multi(origin, cities, lookup=live)
        lf = flights.get_country_monthly(origin, row, lookup=live)
        sr = flights.get_monthly_multi(origin, cities, lookup=peek)
        sf = flights.get_country_monthly(origin, row, lookup=grouped)
        lc, sc = _window_curve(lr, lf, inwin), _window_curve(sr, sf, inwin)
        ready["live"] += lc is not None
        ready["shadow"] += sc is not None
        ready["both"] += lc is not None and sc is not None

        # Route level: the two sources on the same city, before any merge —
        # every city the grouped side was asked for (an empty answer
        # included: its months are the live side's alone).
        for city in dict.fromkeys(asked):
            g = grouped(origin, city)      # memoized: no second call
            if g is None:
                continue
            m = live(origin, city)
            rm["routes"] += 1
            if m is None:
                rm["live_missing"] += 1
                continue
            ent = entries.get((hub, city, "usd"))
            if ent is not None:
                ages.append((now - ent[1]) / 3600)
            stale += bool(m.get("stale"))
            gm = {k: v for k, v in (g.get("months") or {}).items() if k in inwin}
            mm = {k: v for k, v in (m.get("months") or {}).items() if k in inwin}
            for k in sorted(set(gm) | set(mm)):
                if k not in gm:
                    rm["live_only"] += 1
                    continue
                if k not in mm:
                    rm["shadow_only"] += 1
                    continue
                lp, sp = mm[k]["price"], gm[k]["price"]
                i = pos[k]
                rm["both"] += 1
                by_route[i][0] += 1
                if lp == sp:
                    rm["same"] += 1
                    by_route[i][1] += 1
                elif sp < lp:
                    rm["shadow_cheaper"] += 1
                    by_route[i][2] += 1
                else:
                    rm["live_cheaper"] += 1
                    by_route[i][3] += 1
                rm["within5"] += _close(lp, sp)
                if lp:
                    (near_ratios if i < NEAR else ratios).append(sp / lp)
                rm["stops_same"] += mm[k].get("stops") == gm[k].get("stops")
                ld, sd = str(mm[k].get("departure_at") or "")[:10], str(gm[k].get("departure_at") or "")[:10]
                rm["dep_same"] += bool(ld) and ld == sd

        # Country level: the curve the site would show, and its bands.
        if lc is None and sc is None:
            dest[iso] = {"n": [None, None]}
            continue
        ls, lb = _bands(lc, partial) if lc is not None else ({}, {})
        ss, sb = _bands(sc, partial) if sc is not None else ({}, {})
        lband, sband = "lo" in ls, "lo" in ss
        banded["live"] += lband
        banded["shadow"] += sband
        banded["both"] += lband and sband
        banded["live_only"] += lband and not sband
        banded["shadow_only"] += sband and not lband
        months = {}
        for k in sorted(set(lc or {}) | set(sc or {})):
            lp, lk = (lc or {}).get(k, (None, "-"))
            sp, sk = (sc or {}).get(k, (None, "-"))
            if lp is not None and sp is not None:
                cm["both"] += 1
                cm["same"] += lp == sp
                cm["within5"] += _close(lp, sp)
            elif lp is not None:
                cm["live_only"] += 1
            else:
                cm["shadow_only"] += 1
            b1, b2 = lb.get(k), sb.get(k)
            i = pos[k]
            if b1 and b2:
                bands["both"] += 1
                bands["agree"] += b1 == b2
                key = BANDS[b1] + BANDS[b2]
                bands["matrix"][key] = bands["matrix"].get(key, 0) + 1
                by_band[i][0] += 1
                by_band[i][1] += b1 == b2
            by_band[i][2] += b1 == "low"
            by_band[i][3] += b2 == "low"
            by_band[i][4] += b1 == "high"
            by_band[i][5] += b2 == "high"
            ratio = round(sp / lp, 3) if lp and sp is not None else None
            months[k] = [lp, sp, ratio, BANDS[b1] + BANDS[b2], lk + sk]
        dest[iso] = {"n": [None if lc is None else len(lc), None if sc is None else len(sc)],
                     "b": [int(lband), int(sband)], "m": months}

    def dist(vals):
        return {"p10": round(_q(vals, 0.1), 3), "median": round(_q(vals, 0.5), 3),
                "p90": round(_q(vals, 0.9), 3)} if vals else {}

    rm["ratio"] = dist(ratios + near_ratios)
    rm["ratio_near"] = dist(near_ratios)
    rm["ratio_later"] = dist(ratios)
    return {
        "window": [window[0], window[-1]],
        "partial": partial,
        "tab_month": tab_month,
        "agg": {"ready": ready, "banded": banded, "country_months": cm, "route_months": rm,
                "bands": bands, "by_offset": {"route": by_route, "bands": by_band}},
        "live": {"routes_stale": stale,
                 "age_h": {"median": round(_q(ages, 0.5), 1), "max": round(max(ages), 1)} if ages else {}},
        "dest": dest,
    }


# ---- one run -----------------------------------------------------------------

def run_once(fares, busy=None, today=None, origin=ORIGIN, live=None):
    """Fetch and compare once: the summary, or None when the run was dropped
    because the server stayed busy (nothing to store)."""
    g = _Grouped(origin, busy)
    t0 = time.monotonic()
    started = time.time()
    out = {"v": V, "day": _utc_day(started), "at": _utc_stamp(started), "origin": origin,
           "hub": g.hub, "params": dict(PARAMS), "aborted": None}
    try:
        out.update(compare(origin, fares, g, live=live, today=today, now=started))
    except _Abandon as e:
        print("[flight-shadow] dropped: server busy (%s) for %ds" % (e, BUSY_GIVE_UP), flush=True)
        return None
    except _Abort as e:
        out["aborted"] = str(e)
    out["capped"] = g.capped
    ms = sorted(g.ms)
    out["calls"] = {"grouped": g.calls, "failed": g.failed, "rejected": g.rejected,
                    "oneway_rows": g.oneway, "statuses": g.statuses, "busy_waits": g.busy_waits,
                    "secs": round(time.monotonic() - t0, 1),
                    "ms": {"median": _q(ms, 0.5), "p95": _q(ms, 0.95), "max": ms[-1]} if ms else {},
                    # What a switched warmer would take for these calls at its own gap.
                    "proj_fill_s": round(sum(max(SWITCH_PACE, m / 1000) for m in ms), 1),
                    "pace_s": PACE}
    out.setdefault("live", {})["warm"] = flightvalue.pass_stats(origin)
    return out


def encode(summary, limit=None):
    """The summary as compact JSON of at most `limit` bytes: past it, the
    per-month detail goes, the thinnest destinations' first ("trimmed")."""
    limit = limit or MAX_BYTES
    raw = json.dumps(summary, separators=(",", ":"))
    if len(raw) <= limit:
        return raw
    s = dict(summary, dest={k: dict(v) for k, v in (summary.get("dest") or {}).items()})
    order = sorted((k for k, v in s["dest"].items() if "m" in v),
                   key=lambda k: (len(s["dest"][k]["m"]), k))
    trimmed = 0
    for k in order:
        s["dest"][k].pop("m", None)
        trimmed += 1
        s["trimmed"] = trimmed
        if trimmed % 8 == 0 or trimmed == len(order):
            raw = json.dumps(s, separators=(",", ":"))
            if len(raw) <= limit:
                return raw
    s.pop("dest", None)
    s["trimmed"] = "all"
    return json.dumps(s, separators=(",", ":"))


# ---- storage -----------------------------------------------------------------

def _keep(day):
    """Only the last KEEP_DAYS days stay in memory (Upstash expires them too)."""
    cut = (datetime.date.fromisoformat(day) - datetime.timedelta(days=KEEP_DAYS - 1)).isoformat()
    for d in [d for d in _days if d < cut]:
        _days.pop(d, None)


def load(today=None):
    """Read every stored day of the last KEEP_DAYS and the done marker (one
    MGET, one GET). Background thread only."""
    today = today or _utc_day()
    base = datetime.date.fromisoformat(today)
    days = [(base - datetime.timedelta(days=i)).isoformat() for i in range(KEEP_DAYS)]
    try:
        vals = accounts._redis("MGET", *[KEY_DAY + d for d in days]) or []
        done = accounts._redis("GET", KEY_DONE)
    except Exception as e:
        print("[flight-shadow] stored days unreadable: %s" % type(e).__name__, flush=True)
        return False
    with _lock:
        for d, raw in zip(days, vals):
            if raw:
                try:
                    _days[d] = json.loads(raw)
                except ValueError:
                    pass
        _keep(today)
        if done:
            _state["finished"] = True
        _state["ver"] += 1
    return True


def complete_days():
    with _lock:
        return sum(1 for s in _days.values() if not s.get("aborted"))


def store(summary):
    """Write the day's summary (TTL 30 days) and, once WANTED complete days
    are held, the done marker. True when written."""
    day = summary["day"]
    raw = encode(summary)
    try:
        accounts._redis("SET", KEY_DAY + day, raw, "EX", DAY_TTL)
    except Exception as e:
        print("[flight-shadow] not stored (%s); kept in memory" % type(e).__name__, flush=True)
        ok = False
    else:
        ok = True
    with _lock:
        _days[day] = json.loads(raw)
        _keep(day)
        _state["ver"] += 1
    if ok and complete_days() >= WANTED:
        try:
            accounts._redis("SET", KEY_DONE, day, "EX", DONE_TTL)
        except Exception:
            pass
        with _lock:
            _state["finished"] = True
    return ok


# ---- scheduling --------------------------------------------------------------

def enabled():
    """(True, "") when the job may run in this process, else (False, why)."""
    flag = (os.environ.get("FLIGHT_SHADOW") or "").strip()
    if flag == "0":
        return False, "switched off (FLIGHT_SHADOW=0)"
    if not (os.environ.get("RENDER") or flag == "1"):
        return False, "runs on Render only (FLIGHT_SHADOW=1 to test)"
    if not flights.is_configured():
        return False, "no Travelpayouts token"
    if ORIGIN not in flights.ORIGIN_HUBS:
        return False, "no hub for " + ORIGIN
    if not accounts.storage_configured():
        return False, "no storage (Upstash)"
    return True, ""


def check(fares_for, busy=None, today=None, now=None):
    """One scheduled check: run today's comparison when everything allows,
    else say why not. Returns what happened, in words (also the status)."""
    now = time.time() if now is None else now
    day = _utc_day(now)
    with _lock:
        finished = _state["finished"]
        have = day in _days
        tries = _state["tries"].get(day, 0)
    if finished or day > until():
        _set_state("finished", "done: %d complete days stored" % complete_days() if finished
                   else "past %s" % until(), finished=True)
        return _state["why"]
    if have:
        _set_state("waiting", "ran today")
        return _state["why"]
    if tries >= TRIES_PER_DAY:
        _set_state("waiting", "gave up today: busy every try")
        return _state["why"]
    if not flightvalue.has_warmed(ORIGIN) or flightvalue.warming_any():
        _set_state("waiting", "fares still filling")
        return _state["why"]
    why = busy() if busy else None
    if why:
        _set_state("waiting", "server busy: " + why)
        return _state["why"]
    fares = fares_for(ORIGIN)
    if not (fares or {}).get("countries"):
        _set_state("waiting", "no fares cached")
        return _state["why"]
    try:
        stored = accounts._redis("GET", KEY_DAY + day)
        if stored:
            with _lock:
                _days[day] = json.loads(stored)
                _state["ver"] += 1
            _set_state("waiting", "ran today (another process)")
            return _state["why"]
        if not accounts._redis("SET", KEY_LOCK, int(now), "EX", LOCK_TTL, "NX"):
            _set_state("waiting", "another process is running it")
            return _state["why"]
    except Exception as e:
        _set_state("waiting", "storage unreachable (%s)" % type(e).__name__)
        return _state["why"]
    with _lock:
        _state["tries"] = {day: tries + 1}
    _set_state("running", "comparing")
    try:
        summary = run_once(fares, busy=busy, today=today)
        if summary is None:
            _set_state("waiting", "dropped: server got busy")
            return _state["why"]
        store(summary)
        c = summary["calls"]
        print("[flight-shadow] %s: %d grouped calls in %.0fs (%d failed)%s; %s" % (
            summary["day"], c["grouped"], c["secs"], c["failed"],
            "; aborted: " + summary["aborted"] if summary["aborted"] else "",
            _one_line(summary)), flush=True)
        _set_state("ran", "ran " + summary["at"] + (" (aborted)" if summary["aborted"] else ""))
        return _state["why"]
    finally:
        try:
            accounts._redis("DEL", KEY_LOCK)
        except Exception:
            pass


def _one_line(s):
    a = s.get("agg") or {}
    r, b = a.get("route_months") or {}, a.get("bands") or {}
    return "route months both %d, same %d, bands agree %d/%d, banded live %d / grouped %d" % (
        r.get("both", 0), r.get("same", 0), b.get("agree", 0), b.get("both", 0),
        (a.get("banded") or {}).get("live", 0), (a.get("banded") or {}).get("shadow", 0))


def start(fares_for, busy=None):
    """Start the daily job on a background thread when enabled(); True when
    started. `fares_for(origin)`: the cached fares payload, read without a
    refresh (None when there is none); `busy()`: why the server is busy, or
    None."""
    ok, why = enabled()
    if not ok:
        _set_state("off", why)
        return False
    try:
        delay = float(os.environ.get("FLIGHT_SHADOW_DELAY") or FIRST_DELAY)
        if not 0 <= delay < 10 ** 7:
            raise ValueError
    except ValueError:
        delay = FIRST_DELAY
    _set_state("waiting", "starting")

    def loop():
        loaded = load()            # a redeploy picks up the days already stored
        _sleep(delay)              # after the boot warm-ups
        while True:
            try:
                if not loaded:     # storage was unreachable at boot: the done marker and
                    loaded = load()  # earlier days decide whether to run at all
                check(fares_for, busy)
            except Exception as e:     # the thread must outlive any one bad check
                print("[flight-shadow] check failed: %s" % type(e).__name__, flush=True)
            with _lock:
                if _state["finished"]:
                    return
            _sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True, name="flight-shadow").start()
    print("[flight-shadow] started (first check in %ds, until %s)" % (delay, until()), flush=True)
    return True


# ---- endpoint ------------------------------------------------------------------

def body(want_gz=False):
    """(raw, gzipped or None) of /api/flight-shadow's JSON, from memory: the
    status and every day held, oldest first. Rebuilt only when either moved."""
    with _lock:
        ver = _state["ver"]
        if _body["ver"] != ver:
            status = {k: _state[k] for k in ("state", "why", "checked", "finished")}
            status.update(until=until(), wanted=WANTED,
                          complete=sum(1 for s in _days.values() if not s.get("aborted")),
                          origin=ORIGIN, params=dict(PARAMS), pace_s=PACE)
            doc = {"v": V, "status": status, "days": [_days[d] for d in sorted(_days)]}
            _body.update(ver=ver, raw=json.dumps(doc, separators=(",", ":")).encode("utf-8"), gz=None)
        if want_gz and _body["gz"] is None:
            _body["gz"] = gzip.compress(_body["raw"], 6)
        return _body["raw"], _body["gz"] if want_gz else None

"""Is this month's fare low, typical or high FOR THIS ROUTE? The Flights tab's
answer, in the spirit of Google Flights' price insight — built from cached
fares, so it compares months, not booking dates.

A destination country's curve is flights.get_country_monthly(): the cheapest
cached round-trip per departure month, the same curve the guide's fare chart
draws, so a country's number for a month is the same on both. Over the 12
departure months the chart shows (this month first):

  typical range = the middle half of those monthly fares (25th-75th
                  percentile), widened to at least +/-5% of the median
  deviation     = fare / median - 1
  band          = "low" below the range, "high" above it, else "typical"

Why the +/-5% floor: on a flat route (US->Greece: every month within 6% of
the median) raw quartiles still label a quarter of the year "high" — +3.5%,
$23, inside the noise of a cached fare. Google's range is wide enough not to
cry wolf there; so is this one.

Why MIN_MONTHS = 6: the Top Picks fare strips already demand half a year of
real months, and below that the "range" is two or three points — with four,
linear quartiles always call exactly one month low and one high, whatever
the prices. Same threshold both places, so a country either has a season
story everywhere or nowhere.

Why the current month leaves the range in its last days: what is left of
it is last-minute fares (22 recorded US curves on Sep 26: 5 of the 10
banded countries with a September fare read High, none Low). It stays in
the curve — the guide chart's number — and is banded against the other
months' range, but stops moving that range once fewer than PARTIAL_DAYS
of it remain.

Filling ~110 countries x up to 3 cities cold is ~175 upstream calls from the
US. /v1/prices/monthly allows 60 requests/minute per token (Travelpayouts,
"API rate limits", limits from 14.06.2024), and visitors' guide pages share
that budget — so ONE background warmer per origin, at most MAX_WARMERS at
once, all behind one pacer at 1 call / PACE seconds (20/min), while the
endpoint answers from the cache alone and says how far the fill has got.
(Faster, untested without a token: /aviasales/v3/grouped_prices, grouped by
departure month at 600/min, could fill a country in one call.)
"""

import calendar
import datetime
import threading
import time

from . import flights

MIN_MONTHS = 6
TYPICAL_MIN_HALF = 0.05
WINDOW = 12
PARTIAL_DAYS = 10   # the current month leaves the stats with fewer days than this left
PACE = 3.0          # seconds between the warmers' upstream calls (20/min)
MAX_FAILS = 5       # consecutive failures that end a warm pass (429 storm, bad token)
WARM_COOLDOWN = 10 * 60   # an ABORTED pass isn't re-run sooner than this
MAX_WARMERS = 2     # origins filling at once; one slot is always kept for DEFAULT_ORIGIN
DEFAULT_ORIGIN = "US"     # the site's default origin: boot-warmed, first at the pacer


# ---- stats ------------------------------------------------------------------

def window_months(today=None):
    """The 12 departure months the guide chart shows: this month first."""
    today = today or datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(WINDOW):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def partial_month(today=None):
    """The current month's key once fewer than PARTIAL_DAYS of it remain
    (today counted), else None: shown and banded, but not in the stats."""
    today = today or datetime.date.today()
    left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    return "%04d-%02d" % (today.year, today.month) if left < PARTIAL_DAYS else None


def percentile(sorted_vals, q):
    """Linear interpolation between closest ranks (Excel PERCENTILE.INC,
    numpy's default), so it is reproducible by hand from the guide chart."""
    if not sorted_vals:
        return None
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def curve_stats(prices):
    """{n_months} always; median/p25/p75 and the typical range lo..hi only
    when there are MIN_MONTHS months to stand on. Rounded to whole units —
    the client bands with these exact numbers, so both sides agree."""
    vals = sorted(p for p in prices if p is not None)
    out = {"n_months": len(vals)}
    if len(vals) < MIN_MONTHS:
        return out
    med = percentile(vals, 0.5)
    p25, p75 = percentile(vals, 0.25), percentile(vals, 0.75)
    out.update(median=round(med), p25=round(p25), p75=round(p75),
               lo=round(min(p25, med * (1 - TYPICAL_MIN_HALF))),
               hi=round(max(p75, med * (1 + TYPICAL_MIN_HALF))))
    return out


def band(price, stats):
    """"low" / "typical" / "high", or None without a price or a range."""
    if price is None or "lo" not in stats:
        return None
    if price < stats["lo"]:
        return "low"
    if price > stats["hi"]:
        return "high"
    return "typical"


def deviation(price, stats):
    """Signed fraction vs the median (-0.24 = 24% under), or None."""
    if price is None or not stats.get("median"):
        return None
    return price / stats["median"] - 1


# ---- payload ----------------------------------------------------------------

def build(origin_iso, fares, today=None, lookup=None, needs_fetch=None):
    """Every destination country's curve + stats, from the cache alone (never
    an upstream call). A country with no curve yet (unfetched, or its lookup
    failed) is {"pending": true}. `refresh` counts countries with a city
    get_monthly would call for right now (unfetched, expired, or a failure
    due a retry), which is what decides whether to warm."""
    lookup = lookup or flights.monthly_cached
    needs_fetch = needs_fetch or flights.monthly_needs_fetch
    months = window_months(today)
    inwin = set(months)
    partial = partial_month(today)
    rows = (fares or {}).get("countries") or []
    out, ready, refresh = {}, 0, 0
    for row in rows:
        iso = row.get("iso")
        if not iso:
            continue
        seen = []

        def peek(o, c, cur="usd"):
            seen.append(c)
            return lookup(o, c, cur)

        m = flights.get_country_monthly(origin_iso, row, lookup=peek)
        # Not `m is None`: a failure inside its 5-minute retry wait has
        # nothing to fetch yet, and a pass started for it would do nothing.
        if any(needs_fetch(origin_iso, c) for c in seen):
            refresh += 1
        if m is None:
            out[iso] = {"pending": True}
            continue
        ready += 1
        # [price, city] per month: the city is where that month's fare is, so
        # the tab's fare link searches the route that has the price.
        curve = {k: [v["price"], v.get("dest") or row.get("dest")]
                 for k, v in sorted((m.get("months") or {}).items()) if k in inwin}
        out[iso] = dict(curve=curve, **curve_stats([p for k, (p, _) in curve.items()
                                                    if k != partial]))
    return {
        "configured": True,
        "origin": origin_iso,
        "origin_name": (fares or {}).get("origin_name"),
        "currency": (fares or {}).get("currency", "usd"),
        "months": months,
        "partial": partial,
        "min_months": MIN_MONTHS,
        "countries": out,
        "ready": ready,
        "total": len(out),
        "refresh": refresh,
    }


def serve(origin_iso, fares):
    """build() plus the warm-up: start (or keep) the background fill when
    anything is due a fetch. `filling` promises that waiting will bring more
    countries — a refresh of already-shown curves doesn't count; a fill
    queued behind other origins does (the client's next poll starts it)."""
    payload = build(origin_iso, fares)
    if payload.pop("refresh"):
        state = start_warm(origin_iso, (fares or {}).get("countries") or [])
    else:
        state = "running" if is_warming(origin_iso) else None
    payload["filling"] = bool(state) and payload["ready"] < payload["total"]
    return payload


# ---- background warmer ------------------------------------------------------

_warm_lock = threading.Lock()
_warming = {}     # origin -> monotonic start, while a pass runs (keys: ORIGIN_HUBS only)
_warm_done = {}   # origin -> (monotonic end, aborted) of its last pass
_pace_cv = threading.Condition()
_pace_next = [0.0]    # monotonic time the next warmer call may go
_pace_first = [0]     # default-origin warmers waiting at the gate


def _pace(first=False):
    """Wait for this warmer's next upstream slot. One gate for every warmer,
    so two origins at once still make 20/min; a waiting default-origin warmer
    (`first`) takes the next slot ahead of the other. Monotonic, so a wall
    clock stepping back can't stall every warmer behind the gate."""
    with _pace_cv:
        if first:
            _pace_first[0] += 1
        try:
            while True:
                wait = _pace_next[0] - time.monotonic()
                if wait <= 0 and (first or not _pace_first[0]):
                    _pace_next[0] = time.monotonic() + PACE
                    return
                _pace_cv.wait(wait if wait > 0 else PACE)
        finally:
            if first:
                _pace_first[0] -= 1
            _pace_cv.notify_all()


def is_warming(origin_iso):
    with _warm_lock:
        return origin_iso in _warming


class _Abort(Exception):
    pass


def _warm_pass(origin_iso, rows):
    """One pass over every destination; True when it gave up after MAX_FAILS
    upstream failures in a row."""
    fails = [0]
    first = origin_iso == DEFAULT_ORIGIN

    def paced(o, c, cur="usd"):
        if not flights.monthly_needs_fetch(o, c, cur):
            return flights.get_monthly(o, c, cur)       # cache hit, no call
        _pace(first)
        m = flights.get_monthly(o, c, cur)
        fails[0] = fails[0] + 1 if (m.get("error") or m.get("stale")) else 0
        if fails[0] >= MAX_FAILS:
            raise _Abort()
        return m

    def failed_before(row):
        return any(flights.monthly_failed(origin_iso, c) for c in flights.country_cities(row)[:3])

    # Busiest routes first (the likeliest to have a year of months), but
    # routes whose last lookup failed go last: in a fixed order, MAX_FAILS of
    # them in a row aborted every later pass at the same spot, and each
    # country behind them stayed pending until a restart.
    try:
        for row in sorted(rows, key=lambda r: (failed_before(r), -(r.get("n") or 0))):
            try:
                flights.get_country_monthly(origin_iso, row, lookup=paced)
            except _Abort:
                raise
            except Exception:
                pass
    except _Abort:
        print("[flight-value] %s: %d upstream failures in a row; pausing the fill"
              % (origin_iso, MAX_FAILS), flush=True)
        return True
    return False


def _warm(origin_iso, rows):
    aborted = False
    try:
        aborted = _warm_pass(origin_iso, rows)
    finally:
        with _warm_lock:
            _warming.pop(origin_iso, None)
            _warm_done[origin_iso] = (time.monotonic(), aborted)


def start_warm(origin_iso, rows):
    """Start the fill for an origin. "running" when a pass runs after the
    call, "queued" when the warmer slots are taken (a later request starts
    it), None when there's nothing to start: no token, or the cooldown after
    an aborted pass."""
    if origin_iso not in flights.ORIGIN_HUBS or not flights.is_configured():
        return None
    with _warm_lock:
        if origin_iso in _warming:
            return "running"
        # Only an ABORTED pass (429 storm, bad token) waits out the cooldown.
        # A finished one may rerun at once — monthly_needs_fetch keeps it from
        # re-calling anything fresh — so a city that churned into a country's
        # top three on the hourly fares refresh is fetched on the next request
        # instead of leaving that country pending for 10 minutes.
        last = _warm_done.get(origin_iso)
        if last and last[1] and time.monotonic() - last[0] < WARM_COOLDOWN:
            return None
        # Every origin shares the pacer, so more passes at once add latency,
        # not speed. One slot stays free for the default origin, so visitors
        # (or a crawler) trying other origins can't lock its refresh out.
        taken = len(_warming) + (0 if DEFAULT_ORIGIN in (origin_iso, *_warming) else 1)
        if taken >= MAX_WARMERS:
            return "queued"
        _warming[origin_iso] = time.monotonic()
    threading.Thread(target=_warm, args=(origin_iso, list(rows)), daemon=True).start()
    return "running"

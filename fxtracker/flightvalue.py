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

Filling ~110 countries x up to 3 cities cold is ~175 upstream calls from the
US. /v1/prices/monthly allows 60 requests/minute per token (Travelpayouts,
"API rate limits", limits from 14.06.2024), and visitors' guide pages share
that budget — so ONE background warmer per origin, all warmers behind one
pacer at 1 call / PACE seconds (20/min), while the endpoint answers from the
cache alone and says how far the fill has got.
"""

import datetime
import threading
import time

from . import flights

MIN_MONTHS = 6
TYPICAL_MIN_HALF = 0.05
WINDOW = 12
PACE = 3.0          # seconds between the warmers' upstream calls (20/min)
MAX_FAILS = 5       # consecutive failures that end a warm pass (429 storm, bad token)
WARM_COOLDOWN = 10 * 60   # a finished pass isn't re-run sooner than this


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
    an upstream call). A country whose cities aren't fetched yet is
    {"pending": true}. `refresh` counts countries needing a fetch or a
    refetch (expired), which is what decides whether to warm."""
    lookup = lookup or flights.monthly_cached
    needs_fetch = needs_fetch or flights.monthly_needs_fetch
    months = window_months(today)
    inwin = set(months)
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
        if m is None or any(needs_fetch(origin_iso, c) for c in seen):
            refresh += 1
        if m is None:
            out[iso] = {"pending": True}
            continue
        ready += 1
        # [price, city] per month: the city is where that month's fare is, so
        # the tab's fare link searches the route that has the price.
        curve = {k: [v["price"], v.get("dest") or row.get("dest")]
                 for k, v in sorted((m.get("months") or {}).items()) if k in inwin}
        out[iso] = dict(curve=curve, **curve_stats([p for p, _ in curve.values()]))
    return {
        "configured": True,
        "origin": origin_iso,
        "origin_name": (fares or {}).get("origin_name"),
        "currency": (fares or {}).get("currency", "usd"),
        "months": months,
        "min_months": MIN_MONTHS,
        "countries": out,
        "ready": ready,
        "total": len(out),
        "refresh": refresh,
    }


def serve(origin_iso, fares):
    """build() plus the warm-up: start (or keep) the background fill when
    anything is unfetched or expired. `filling` promises that waiting will
    bring more countries — a refresh of already-shown curves doesn't count."""
    payload = build(origin_iso, fares)
    if payload.pop("refresh"):
        start_warm(origin_iso, (fares or {}).get("countries") or [])
    payload["filling"] = is_warming(origin_iso) and payload["ready"] < payload["total"]
    return payload


# ---- background warmer ------------------------------------------------------

_warm_lock = threading.Lock()
_warming = {}     # origin -> started_at, while a pass runs (keys: ORIGIN_HUBS only)
_warm_done = {}   # origin -> finished_at of its last pass
_pace_lock = threading.Lock()
_last_call = [0.0]


def _pace():
    # One gate for every warmer: two origins filling at once still make 20/min.
    with _pace_lock:
        wait = _last_call[0] + PACE - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def is_warming(origin_iso):
    with _warm_lock:
        return origin_iso in _warming


class _Abort(Exception):
    pass


def _warm(origin_iso, rows):
    fails = [0]

    def paced(o, c, cur="usd"):
        if not flights.monthly_needs_fetch(o, c, cur):
            return flights.get_monthly(o, c, cur)       # cache hit, no call
        _pace()
        m = flights.get_monthly(o, c, cur)
        fails[0] = fails[0] + 1 if (m.get("error") or m.get("stale")) else 0
        if fails[0] >= MAX_FAILS:
            raise _Abort()
        return m

    try:
        # Busiest routes first: they're the likeliest to have a year of months.
        for row in sorted(rows, key=lambda r: -(r.get("n") or 0)):
            try:
                flights.get_country_monthly(origin_iso, row, lookup=paced)
            except _Abort:
                raise
            except Exception:
                pass
    except _Abort:
        print("[flight-value] %s: %d upstream failures in a row; pausing the fill"
              % (origin_iso, MAX_FAILS), flush=True)
    finally:
        with _warm_lock:
            _warming.pop(origin_iso, None)
            _warm_done[origin_iso] = time.time()


def start_warm(origin_iso, rows):
    """Start the fill for an origin unless one is running or just finished.
    True when a pass is running after the call."""
    if origin_iso not in flights.ORIGIN_HUBS or not flights.is_configured():
        return False
    with _warm_lock:
        if origin_iso in _warming:
            return True
        done = _warm_done.get(origin_iso)
        if done and time.time() - done < WARM_COOLDOWN:
            return False
        _warming[origin_iso] = time.time()
    threading.Thread(target=_warm, args=(origin_iso, list(rows)), daemon=True).start()
    return True

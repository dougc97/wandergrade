"""/api/trip-legs (round 16): fares and flight times between the countries of
a reader's trip, for the Trip tab's recommended order and its route globe.

Nothing new upstream: the answer is read from the hub fares payloads the
server already caches for /api/flights (flights.get_flights, one per
ORIGIN_HUBS country). For each trip country that is a hub, its payload's
rows for the other trip countries are the real legs; a country with no hub
of its own (or a hub missing the row) takes the reverse row of a hub that
has it. Pairs with neither stay out: the browser estimates them from
distance with the regional fit returned beside them, and marks them ≈.

One kind of fare everywhere (the Trip rows' own): the trip month's cheapest
cached ROUND TRIP where the row has that month ("basis": "month"), else the
row's yearly average ("avg"). `fare` is that round-trip USD figure as
cached; the browser halves it for one way, as it halves the fit's estimate.
`dur` is the row's one-way flight time in minutes (its most direct cached
trip), `stops` its stop count; either may be None.

The cost is capped, because a trip is up to 12 countries and an uncached
hub payload is 1-3 Travelpayouts calls: at most MAX_FETCH uncached payloads
per request (the rest come back in `pending`: estimated now, real on a later
visit, once a reader's request has cached them), and none at all while the
server says it is busy (server._flight_shadow_busy: a page rendering, a
background refresh, a crawl in the last 10 minutes). A copy in hand past its
hour (stale_for) is used rather than left pending. The reader's own payload
(origin) is read for the fallback fit only when it is in hand, never
fetched.
"""
import re

from . import flights, geo

MAX_ISOS = 12          # a request with more is refused (400)
MAX_FETCH = 4          # uncached hub payloads fetched per request; the rest pending
FIT_MAX_KM = 5000      # the regional fit's rows: short and medium haul only
FIT_MIN_ROWS = 30      # under this many, the reader's own payload fit instead
ORIGIN_FIT_MIN = 8     # app.js buildFareContext's minimum for its fit

# app.js GUIDE_PARENT: England, Scotland and Wales fly as the UK.
GUIDE_PARENT = {"GB-ENG": "GB", "GB-SCT": "GB", "GB-WLS": "GB"}
_ISO_RE = re.compile(r"[A-Z]{2}(-[A-Z]{3})?")
_MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def parse(origin, isos_raw, month_raw, hubs=None):
    """(origin, [iso...], month|None) from the query's raw strings, or
    ValueError: an origin that isn't a hub, a code that isn't a country
    code, more than MAX_ISOS countries, a month that isn't YYYY-MM. Codes
    are upper-cased, trimmed and deduplicated in order; none is fine."""
    hubs = flights.ORIGIN_HUBS if hubs is None else hubs
    origin = (origin or "").strip().upper()
    if origin not in hubs:
        raise ValueError("origin must be a supported hub country")
    isos = []
    for part in (isos_raw or "").split(","):
        iso = part.strip().upper()
        if not iso:
            continue
        if not _ISO_RE.fullmatch(iso):
            raise ValueError("not a country code: %s" % iso[:12])
        if iso not in isos:
            isos.append(iso)
    if len(isos) > MAX_ISOS:
        raise ValueError("at most %d countries" % MAX_ISOS)
    month = (month_raw or "").strip()
    if month and not _MONTH_RE.fullmatch(month):
        raise ValueError("month must be YYYY-MM")
    return origin, isos, month or None


def fare_of(row, month):
    """(fare, basis) for a payload row: the month's cheapest cached round
    trip, else the yearly average; (None, None) with neither."""
    m = (row.get("months") or {}).get(month) if month else None
    if m and m.get("price"):
        return m["price"], "month"
    if row.get("avg"):
        return row["avg"], "avg"
    return None, None


def _lsq(pts):
    """Least squares fare = a + b * km over (km, fare) points: (a, b), or
    (None, None) with no spread in km."""
    n = len(pts)
    if not n:
        return None, None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if not den:
        return None, None
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / den
    return my - b * mx, b


def regional_fit(rows, fallback):
    """(a, b, n): fare = a + b * km over the (km, fare) rows up to
    FIT_MAX_KM (n of them). Under FIT_MIN_ROWS rows, or a slope that isn't
    positive (fares falling with distance would price far legs below near
    ones), the fallback (a, b) with the same n; (None, None, n) without
    one."""
    pts = [(km, fare) for km, fare in rows if km is not None and fare is not None and 0 < km <= FIT_MAX_KM]
    n = len(pts)
    fb = (fallback[0], fallback[1], n) if fallback else (None, None, n)
    if n < FIT_MIN_ROWS:
        return fb
    a, b = _lsq(pts)
    if b is None or b <= 0:
        return fb
    return a, b, n


def _origin_fit(payload, centroids):
    """The reader's own payload fit, as app.js buildFareContext makes it:
    every row, yearly averages, at least ORIGIN_FIT_MIN points; or None."""
    o = centroids.get(payload.get("origin")) if payload else None
    if not o:
        return None
    pts = [(geo.dist_km(o, centroids[r["iso"]]), r["avg"]) for r in payload.get("countries") or []
           if r.get("iso") in centroids and r.get("avg")]
    if len(pts) < ORIGIN_FIT_MIN:
        return None
    a, b = _lsq(pts)
    return (a, b) if b is not None else None


def legs(origin, isos, month, fares_for, cached, busy, stale_for=None, centroids=None, hubs=None):
    """The answer for one request (parse() has checked the arguments):
    {"configured", "origin", "month", "legs": {from: {to: {"fare", "basis",
    "dur", "stops"[, "rev": True]}}}, "fit": {"a", "b", "n"}, "pending":
    [iso]}. fares_for(iso): the hub payload (may fetch upstream unless
    cached(iso)); stale_for(iso): an older copy in hand or None, never a
    fetch; busy: fetch nothing."""
    hubs = flights.ORIGIN_HUBS if hubs is None else hubs
    centroids = geo.site_centroids() if centroids is None else centroids
    payloads, waiting, fetched = {}, set(), 0
    for hub in dict.fromkeys(GUIDE_PARENT.get(i, i) for i in isos):
        if hub not in hubs:
            continue
        data = None
        try:
            if cached(hub):
                data = fares_for(hub)
            else:
                data = stale_for(hub) if stale_for else None
                if data is None and not busy and fetched < MAX_FETCH:
                    fetched += 1
                    data = fares_for(hub)
        except Exception:
            data = None
        if data and data.get("countries") is not None:
            payloads[hub] = data
        else:
            waiting.add(hub)
    rows = {hub: {r.get("iso"): r for r in p.get("countries") or []} for hub, p in payloads.items()}

    def leg(row, rev):
        fare, basis = fare_of(row, month)
        if fare is None:
            return None
        out = {"fare": fare, "basis": basis, "dur": row.get("dur"), "stops": row.get("stops")}
        if rev:
            out["rev"] = True
        return out

    out_legs = {}
    for a in isos:
        pa = GUIDE_PARENT.get(a, a)
        for b in isos:
            pb = GUIDE_PARENT.get(b, b)
            if pa == pb:
                continue          # the same country (England and the UK): no flight between them
            fwd = rows.get(pa, {}).get(pb)
            rev = None if fwd else rows.get(pb, {}).get(pa)
            got = leg(fwd, False) if fwd else leg(rev, True) if rev else None
            if got:
                out_legs.setdefault(a, {})[b] = got

    # The regional fit: every row in hand, from its hub's centroid.
    origin_payload = None
    try:
        if cached(origin):
            origin_payload = fares_for(origin)
        elif stale_for:
            origin_payload = stale_for(origin)
    except Exception:
        origin_payload = None
    fit_rows = []
    for hub, p in list(payloads.items()) + ([(origin, origin_payload)] if origin_payload and origin not in payloads else []):
        h = centroids.get(hub)
        if not h:
            continue
        for r in p.get("countries") or []:
            c = centroids.get(r.get("iso"))
            if c:
                fit_rows.append((geo.dist_km(h, c), fare_of(r, month)[0]))
    a, b, n = regional_fit(fit_rows, _origin_fit(origin_payload, centroids))
    return {"configured": True, "origin": origin, "month": month, "legs": out_legs,
            "fit": {"a": a, "b": b, "n": n},
            "pending": [i for i in isos if GUIDE_PARENT.get(i, i) in waiting]}

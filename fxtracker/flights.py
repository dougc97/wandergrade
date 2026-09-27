"""Country-level flight prices via the Travelpayouts (Aviasales) API.

The user picks an ORIGIN COUNTRY; we query cached cheapest fares from that
country's main air hub, drop domestic routes and fares older than
MAX_FARE_AGE_DAYS, and aggregate the rest by DESTINATION COUNTRY (average +
cheapest fare). Free, but requires a token from a Travelpayouts account —
read from the TRAVELPAYOUTS_TOKEN env var.
"""

import datetime
import os
import re
import time
import urllib.parse

from . import rates  # reuse fetch_json (verifying SSL + retries)

API = "https://api.travelpayouts.com"
# Cached fares can be months old; only fares Aviasales observed within this
# window feed the displayed averages, so we never show stale prices as current.
MAX_FARE_AGE_DAYS = 90
_cities = None  # city code -> {"name", "country"} (lazy, cached)


def _fresh_enough(found_at, cutoff):
    """True if this fare was observed on/after `cutoff` (a date). Day precision
    is plenty for a 90-day window and dodges tz/format quirks. Fares with no
    found_at are kept (the field is normally present; don't over-prune)."""
    if not found_at:
        return True
    try:
        return datetime.date.fromisoformat(str(found_at)[:10]) >= cutoff
    except ValueError:
        return True

# Origin country -> its main international hub (Travelpayouts city codes; the
# multi-airport codes like NYC/LON/TYO aggregate all airports in that city).
ORIGIN_HUBS = {
    "US": ("NYC", "United States"), "CA": ("YTO", "Canada"), "MX": ("MEX", "Mexico"),
    "BR": ("SAO", "Brazil"), "AR": ("BUE", "Argentina"), "CL": ("SCL", "Chile"),
    "CO": ("BOG", "Colombia"), "PE": ("LIM", "Peru"), "PA": ("PTY", "Panama"),
    "CR": ("SJO", "Costa Rica"), "DO": ("SDQ", "Dominican Republic"),
    "GB": ("LON", "United Kingdom"), "IE": ("DUB", "Ireland"), "FR": ("PAR", "France"),
    "DE": ("FRA", "Germany"), "NL": ("AMS", "Netherlands"), "BE": ("BRU", "Belgium"),
    "ES": ("MAD", "Spain"), "PT": ("LIS", "Portugal"), "IT": ("ROM", "Italy"),
    "CH": ("ZRH", "Switzerland"), "AT": ("VIE", "Austria"), "PL": ("WAW", "Poland"),
    "CZ": ("PRG", "Czechia"), "HU": ("BUD", "Hungary"), "GR": ("ATH", "Greece"),
    "RO": ("BUH", "Romania"), "SE": ("STO", "Sweden"), "NO": ("OSL", "Norway"),
    "DK": ("CPH", "Denmark"), "FI": ("HEL", "Finland"), "IS": ("REK", "Iceland"),
    "TR": ("IST", "Turkey"), "IL": ("TLV", "Israel"), "AE": ("DXB", "UAE"),
    "QA": ("DOH", "Qatar"), "SA": ("RUH", "Saudi Arabia"), "EG": ("CAI", "Egypt"),
    "MA": ("CAS", "Morocco"), "ZA": ("JNB", "South Africa"), "KE": ("NBO", "Kenya"),
    "NG": ("LOS", "Nigeria"), "GH": ("ACC", "Ghana"), "IN": ("DEL", "India"),
    "LK": ("CMB", "Sri Lanka"), "TH": ("BKK", "Thailand"), "VN": ("SGN", "Vietnam"),
    "KH": ("PNH", "Cambodia"), "MY": ("KUL", "Malaysia"), "SG": ("SIN", "Singapore"),
    "ID": ("JKT", "Indonesia"), "PH": ("MNL", "Philippines"), "HK": ("HKG", "Hong Kong"),
    "TW": ("TPE", "Taiwan"), "CN": ("BJS", "China"), "JP": ("TYO", "Japan"),
    "KR": ("SEL", "South Korea"), "AU": ("SYD", "Australia"), "NZ": ("AKL", "New Zealand"),
}


def token():
    return os.environ.get("TRAVELPAYOUTS_TOKEN", "")


def is_configured():
    return bool(token())


def origins():
    """Supported origin countries for the dropdowns, alphabetical by name."""
    return sorted(
        ({"iso": iso, "name": name} for iso, (_, name) in ORIGIN_HUBS.items()),
        key=lambda o: o["name"])


def _load_cities():
    global _cities
    if _cities is not None:
        return _cities
    out = {}
    try:
        for c in rates.fetch_json(API + "/data/en/cities.json"):
            code = c.get("code")
            if code:
                out[code] = {"name": c.get("name", code), "country": c.get("country_code", "")}
    except Exception:
        pass
    _cities = out
    return out


def get_flights(origin_iso, currency="usd"):
    """Aggregate cached cheapest fares from `origin_iso`'s hub by destination
    country: average fare, cheapest fare, and how many routes were sampled.
    Domestic destinations are excluded."""
    origin_iso = (origin_iso or "US").strip().upper()[:2]
    if not is_configured():
        return {"configured": False, "countries": [], "by_country": {}}
    if origin_iso not in ORIGIN_HUBS:
        return {"configured": True, "error": "unsupported origin country " + origin_iso,
                "countries": [], "by_country": {}}
    hub, origin_name = ORIGIN_HUBS[origin_iso]

    cities = _load_cities()
    # Cached fares cluster on popular routes, so pull several pages to reach
    # more destination countries; stop early once a page comes back short.
    rows = []
    for page in (1, 2, 3):
        qs = urllib.parse.urlencode({
            "origin": hub, "currency": currency, "period_type": "year",
            "one_way": "false", "page": page, "limit": 1000, "sorting": "price",
            "token": token(),
        })
        data = rates.fetch_json("{0}/aviasales/v3/get_latest_prices?{1}".format(API, qs))
        batch = data.get("data", []) if isinstance(data, dict) else []
        rows.extend(batch)
        if len(batch) < 1000:
            break

    cutoff = datetime.date.today() - datetime.timedelta(days=MAX_FARE_AGE_DAYS)
    today_iso = datetime.date.today().isoformat()
    agg = {}  # dest country iso -> {"sum", "n", "min", "dur", "stops"}
    for r in rows:
        meta = cities.get(r.get("destination"), {})
        dest_iso = meta.get("country", "")
        price = r.get("value") or r.get("price")
        if price is None or not dest_iso or dest_iso == origin_iso:
            continue
        if not _fresh_enough(r.get("found_at"), cutoff):
            continue   # skip stale fares — don't average months-old prices in
        a = agg.setdefault(dest_iso, {"sum": 0.0, "n": 0, "min": price,
                                      "dur": None, "stops": None,
                                      "dest": r.get("destination"), "seen": None,
                                      "cities": {}, "months": {}})
        a["sum"] += price
        a["n"] += 1
        # Cheapest fare per DEPARTURE month, across every city of the country.
        # These rows are already paid for, and they reach cities the per-route
        # monthly curve never asks about — they widen that curve for free (see
        # get_country_monthly). A departure already in the past is not a fare.
        dep = str(r.get("depart_date") or "")[:10]
        if len(dep) == 10 and dep >= today_iso:
            mk, cur = dep[:7], a["months"].get(dep[:7])
            if cur is None or price < cur["price"]:
                stops = r.get("number_of_changes")
                a["months"][mk] = {"price": round(price), "dest": r.get("destination"),
                                   "stops": r.get("transfers") if stops is None else stops,
                                   "departure_at": dep}
        # Every destination city with cached fares, by how often it appears.
        # The monthly curve merges across the top few — one secondary city
        # rarely has a full year of cached months, but two or three do.
        a["cities"][r.get("destination")] = a["cities"].get(r.get("destination"), 0) + 1
        if price <= a["min"]:
            # Travel time + layovers belong to the cheapest itinerary — the one
            # someone would actually book. The v3 latest-prices feed names the
            # layover count "number_of_changes" (not "transfers"); duration is
            # in minutes. We also keep that itinerary's destination city code so
            # the frontend can deep-link an Aviasales search to the exact city.
            a["min"] = price
            a["dur"] = r.get("duration_to") or r.get("duration")
            a["dest"] = r.get("destination")
            stops = r.get("number_of_changes")
            if stops is None:
                stops = r.get("transfers")
            a["stops"] = stops
            # When Aviasales last observed this cheapest fare (freshness signal;
            # found_at is the observation time, distinct from the travel date).
            a["seen"] = r.get("found_at")

    def _top_cities(a):
        # Ties break on the code, not on price order: this list is re-derived
        # every hour, and a city swapping in on a tie made its country pending
        # on the Flights tab until the new city was fetched.
        top = sorted(a["cities"], key=lambda c: (-a["cities"][c], c))[:3]
        if a["dest"] and a["dest"] not in top:
            top = [a["dest"]] + top[:2]
        return top

    countries = [{"iso": iso, "avg": round(a["sum"] / a["n"]), "min": round(a["min"]),
                  "n": a["n"], "dur": a["dur"], "stops": a["stops"], "dest": a["dest"],
                  "seen": a["seen"], "cities": _top_cities(a), "months": a["months"]}
                 for iso, a in agg.items()]
    countries.sort(key=lambda c: c["avg"])

    return {
        "configured": True,
        "origin": origin_iso,
        "origin_name": origin_name,
        "hub": hub,
        "currency": currency,
        "countries": countries,
        "by_country": {c["iso"]: c["avg"] for c in countries},
    }


# ---- monthly fare curve for one route --------------------------------------
# /v1/prices/monthly returns the cheapest CACHED fare per month, up to a year
# forward — forward-looking booking data, which is exactly the "when should I
# fly" question. Same cached-search caveat as everything else here: months
# nobody searched simply don't appear, and that absence must render as absence.
_monthly_cache = {}   # route key -> (checked_at, fetched_at, data, failed)
MONTHLY_TTL = 12 * 3600
# A failed upstream call is not "no fares": it is remembered only this long
# (so a burst of visitors doesn't hammer a struggling API), and an older good
# curve for the route is served instead when there is one.
MONTHLY_FAIL_TTL = 5 * 60
# An expired curve stays the stale-on-error fallback this long after its last
# REAL fetch — a failed refresh used to reset the age, so a dead route served
# its old curve forever. Also the prune age: pruning at the TTL itself meant
# the Flights tab's background refresh deleted every other expired route the
# moment it wrote its first fresh one.
MONTHLY_STALE_MAX = 36 * 3600


def _departed(v, today_iso):
    dep = str(v.get("departure_at") or "")[:10]
    return len(dep) == 10 and dep < today_iso


def _upcoming(months, today=None):
    """Months whose fare departs today or later. A cached curve can hold a
    fare for a date already flown (it is up to 12h old, and the current
    month's cheapest is often in its first days) — nobody can book that.
    A month without a departure date is kept (don't over-prune)."""
    today_iso = (today or datetime.date.today()).isoformat()
    return {k: v for k, v in (months or {}).items() if not _departed(v, today_iso)}


def _entry(key, now):
    """The route's cache entry, or None once its last real fetch is
    MONTHLY_STALE_MAX old — gone whether or not the prune has reached it."""
    hit = _monthly_cache.get(key)
    return None if hit is None or now - hit[1] >= MONTHLY_STALE_MAX else hit


def _due(hit, now):
    return now - hit[0] >= (MONTHLY_FAIL_TTL if hit[3] else MONTHLY_TTL)


def _served(hit):
    """A cache entry as get_monthly answers it: departures already flown
    dropped, and a curve whose last refresh failed marked stale."""
    data = hit[2]
    months = _upcoming(data.get("months"))
    stale = hit[3] and not data.get("error")
    if not stale and len(months) == len(data.get("months") or {}):
        return data
    out = dict(data, months=months)
    if stale:
        out["stale"] = True
    return out


def _route_key(origin_iso, dest_city, currency="usd"):
    """Cache key for a route worth a token-authenticated call, else None."""
    origin_iso = (origin_iso or "US").strip().upper()[:2]
    dest_city = (dest_city or "").strip().upper()[:3]
    if not is_configured() or origin_iso not in ORIGIN_HUBS \
            or not re.fullmatch(r"[A-Z]{3}", dest_city):
        return None
    # Only real Travelpayouts city codes get a token-authenticated call —
    # otherwise any client-supplied 3-char string spends one upstream call
    # and a permanent cache entry.
    cities = _load_cities()
    if cities and dest_city not in cities:
        return None
    return (ORIGIN_HUBS[origin_iso][0], dest_city, currency)


def monthly_cached(origin_iso, dest_city, currency="usd"):
    """get_monthly from the cache alone — never an upstream call. None means
    this route has no curve yet: never fetched, or its lookup failed (so the
    Flights tab shows that country pending and the warmer retries it, rather
    than a failure reading "no fares cached"). An invalid route answers
    empty, the same as get_monthly, so it can't sit pending forever."""
    key = _route_key(origin_iso, dest_city, currency)
    if key is None:
        return {"configured": is_configured(), "months": {}}
    hit = _entry(key, time.time())
    if hit is None or hit[2].get("error"):
        return None
    return _served(hit)


def monthly_needs_fetch(origin_iso, dest_city, currency="usd"):
    """True when get_monthly would call upstream for this route right now."""
    key = _route_key(origin_iso, dest_city, currency)
    if key is None:
        return False
    now = time.time()
    hit = _entry(key, now)
    return hit is None or _due(hit, now)


def monthly_failed(origin_iso, dest_city, currency="usd"):
    """True when this route's last upstream lookup failed."""
    key = _route_key(origin_iso, dest_city, currency)
    hit = _monthly_cache.get(key) if key else None
    return bool(hit and hit[3])


def get_monthly(origin_iso, dest_city, currency="usd"):
    key = _route_key(origin_iso, dest_city, currency)
    if key is None:
        return {"configured": is_configured(), "months": {}}
    hub, dest_city, _cur = key
    origin_iso = (origin_iso or "US").strip().upper()[:2]
    now = time.time()
    hit = _entry(key, now)
    if hit and not _due(hit, now):
        return _served(hit)
    out = {"configured": True, "origin": origin_iso, "hub": hub,
           "dest": dest_city, "currency": currency, "months": {}}
    failed = False
    try:
        qs = urllib.parse.urlencode({"origin": hub, "destination": dest_city,
                                     "currency": currency, "token": token()})
        data = rates.fetch_json("{0}/v1/prices/monthly?{1}".format(API, qs))
        for k, v in ((data or {}).get("data") or {}).items():
            if isinstance(v, dict) and v.get("price") is not None:
                # departure_at is kept so a fare for a date already flown can
                # be dropped on every read (_upcoming), not only at fetch time.
                out["months"][k[:7]] = {"price": round(v["price"]),
                                        "stops": v.get("transfers"),
                                        "departure_at": v.get("departure_at")}
    except Exception:
        # Not cached as an authoritative empty curve for 12h (one 429 used to
        # hide that route's fare strip and chart for everyone). The "error"
        # flag lets the client tell a failure from genuine absence.
        if hit and not hit[2].get("error"):
            # Keep serving the last good curve — never past MONTHLY_STALE_MAX
            # from its real fetch (_entry) — and retry upstream in 5 minutes.
            entry = (now, hit[1], hit[2], True)
            _monthly_cache[key] = entry
            return _served(entry)
        out["error"] = "fare lookup failed"
        failed = True
    # Prune on write so the cache can't grow for the life of the process (one
    # entry per route ever asked about) — at the stale limit, not the TTL.
    # The warmer thread writes too: snapshot, and pop what another thread may
    # already have pruned (a second `del` raised KeyError and lost this curve).
    for k, e in list(_monthly_cache.items()):
        if now - e[1] >= MONTHLY_STALE_MAX:
            _monthly_cache.pop(k, None)
    entry = (now, now, out, failed)
    _monthly_cache[key] = entry
    return _served(entry)


def get_monthly_multi(origin_iso, dest_cities, currency="usd", lookup=None):
    """Monthly curve for a COUNTRY: cheapest cached fare per month across its
    top cached destination cities. One secondary city rarely carries a full
    year of cached months (US->Bucharest: 2), but the country's two or three
    busiest cached cities together usually do. Cheapest per month wins, which
    matches what the number means everywhere else on the site. Stops after the
    first city if it already covers the year, so hub routes cost one call.

    `lookup` replaces get_monthly (the Flights tab reads the cache alone with
    monthly_cached); a lookup answering None means "not fetched yet", and the
    whole country answers None rather than a curve missing a city."""
    lookup = lookup or get_monthly
    merged = None
    for city in (dest_cities or [])[:3]:
        m = lookup(origin_iso, city, currency)
        if m is None:
            return None
        if not m.get("months"):
            continue
        # Each month remembers which city its fare is for, so a fare link can
        # search the route that actually has that price.
        tagged = {k: dict(v, dest=city) for k, v in m["months"].items()}
        if merged is None:
            merged = dict(m)
            merged["months"] = tagged
            merged["dests"] = [city]
        else:
            merged["dests"].append(city)
            for k, v in tagged.items():
                cur = merged["months"].get(k)
                if cur is None or v["price"] < cur["price"]:
                    merged["months"][k] = v
        if len(merged["months"]) >= 10:
            break
    if merged is not None:
        return merged
    first = (dest_cities or [""])[0]
    return lookup(origin_iso, first, currency)


def country_cities(row):
    """The destination cities a country's curve is built from (get_flights row)."""
    return row.get("cities") or ([row["dest"]] if row.get("dest") else [])


def get_country_monthly(origin_iso, row, currency="usd", lookup=None):
    """The ONE monthly curve for a destination country — the guide's fare
    chart, the Top Picks strips and the Flights tab's low/typical/high all
    read this, so the same country and month is always the same number.
    Per-route curves for its top cities, with the months they lack filled
    from the latest-prices rows get_flights already fetched (row "months").
    None while a city is unfetched (cache-only lookup)."""
    m = get_monthly_multi(origin_iso, country_cities(row), currency, lookup=lookup)
    if m is None:
        return None
    extra = _upcoming(row.get("months"))
    if not extra:
        return m
    out = dict(m)
    out["months"] = dict(m.get("months") or {})
    # Fill only, never replace: rows are any city and the last 90 days, the
    # route curves the top cities at any age, so a cheaper row fare swapped
    # into a curve month could move it across a band edge. Until that is
    # measured with a real token, rows only widen the curve.
    for k, v in extra.items():
        out["months"].setdefault(k, v)
    return out

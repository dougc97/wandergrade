#!/usr/bin/env python3
"""Precompute monthly climate-comfort scores per country -> public/climate.json.

"Best time to travel" has no API, so we derive a weather-comfort proxy: for one
point per country (see sample_point) we pull five years of daily temperature +
rainfall from Open-Meteo (free, no key), aggregate to months, and score each
month 0-100. Top destinations get curated best-month overrides on top (the
"hybrid" approach).

Run once (re-run to refresh): python3 -m fxtracker.build_climate
Only some countries:          python3 -m fxtracker.build_climate FR NO CL
It writes a static file the website reads, so there are no live weather calls.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict

from . import geo
from . import rates  # reuse the verifying SSL context + fetch_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
OUT = os.path.join(ROOT, "public", "climate.json")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
# A five-year window over the last COMPLETE calendar years, derived from the
# clock. Was hardcoded to 2024 alone, which had two problems: it could never
# refresh, and one year is a thin basis for "typical" weather — a single wet or
# freak-hot year permanently skewed a country's best months. Five years averages
# anomalies out while staying recent enough to reflect current climate. The end
# year is the last complete one, since a partial year would bias whichever
# months have already happened.
_LAST_COMPLETE = time.gmtime().tm_year - 1
WINDOW_YEARS = 5
YEAR = ("%d-01-01" % (_LAST_COMPLETE - WINDOW_YEARS + 1), "%d-12-31" % _LAST_COMPLETE)

# Curated best-months for major destinations (1=Jan). Overlaid on weather scores
# so the "best months" reflect travel knowledge (shoulder seasons, dry seasons,
# festivals) for the places people most often ask about.
CURATED = {
    "JP": [3, 4, 10, 11], "FR": [5, 6, 9, 10], "IT": [4, 5, 9, 10],
    "ES": [4, 5, 9, 10], "GB": [5, 6, 7, 9], "GR": [5, 6, 9, 10],
    "PT": [5, 6, 9, 10], "HR": [5, 6, 9], "DE": [5, 6, 9],
    "TH": [11, 12, 1, 2], "VN": [2, 3, 4, 11], "ID": [5, 6, 7, 8, 9],
    "IN": [10, 11, 2, 3], "MY": [1, 2, 6, 7], "PH": [12, 1, 2, 3],
    "KR": [4, 5, 10, 11], "TR": [4, 5, 9, 10], "AE": [11, 12, 1, 2, 3],
    "MX": [11, 12, 3, 4], "BR": [4, 5, 9, 10], "AR": [3, 4, 10, 11],
    "PE": [5, 6, 7, 8], "CL": [3, 4, 11, 12], "CO": [12, 1, 2, 7],
    "CR": [12, 1, 2, 3, 4], "US": [5, 6, 9, 10], "CA": [6, 7, 8, 9],
    "ZA": [9, 10, 4, 5], "EG": [10, 11, 3, 4], "MA": [3, 4, 5, 10],
    "KE": [1, 2, 6, 7, 8, 9, 10], "TZ": [6, 7, 8, 9], "AU": [3, 4, 9, 10, 11],
    "NZ": [11, 12, 1, 2, 3], "FJ": [5, 6, 7, 8, 9, 10],
}


# Where to sample, as (lat, lon), for countries one geometric point can't stand
# for. A vertex average over every part put France's sample in the Atlantic west
# of Morocco (dragged by French Guiana) and Fiji's in the Indian Ocean; the big
# ones' interior points were nowhere anyone goes (the US at Mt Hood, Canada in
# Nunavut, Chile in the high Andes, China on the Gansu plateau). So: the capital
# for multi-part countries, for the named big ones, and wherever the old point
# fell at sea or in a neighbour — or the main city visitors go to where the
# capital is atypical of it (Sydney, Istanbul). Tel Aviv, not Jerusalem, for
# Israel: the simplified map puts East Jerusalem in the Palestine polygon.
SAMPLE_POINTS = {
    "FR": (48.857, 2.352),     # Paris
    "NO": (59.913, 10.752),    # Oslo
    "CL": (-33.449, -70.669),  # Santiago
    "CA": (45.421, -75.697),   # Ottawa
    "US": (38.907, -77.037),   # Washington, D.C.
    "FJ": (-18.141, 178.442),  # Suva
    "MY": (3.139, 101.687),    # Kuala Lumpur
    "NZ": (-41.286, 174.776),  # Wellington
    "GR": (37.984, 23.728),    # Athens
    "JP": (35.676, 139.650),   # Tokyo
    "GB": (51.507, -0.128),    # London
    "HR": (45.815, 15.982),    # Zagreb
    "TH": (13.756, 100.502),   # Bangkok
    "VN": (21.028, 105.854),   # Hanoi
    "SB": (-9.433, 159.950),   # Honiara
    "CV": (14.933, -23.513),   # Praia
    "FO": (62.011, -6.776),    # Tórshavn
    "IL": (32.085, 34.782),    # Tel Aviv
    "HT": (18.594, -72.307),   # Port-au-Prince
    "PG": (-9.443, 147.180),   # Port Moresby
    "ID": (-6.209, 106.846),   # Jakarta
    "PH": (14.600, 120.984),   # Manila
    "AR": (-34.604, -58.382),  # Buenos Aires
    "RU": (55.756, 37.617),    # Moscow
    "CN": (39.904, 116.407),   # Beijing
    "IT": (41.903, 12.496),    # Rome
    "OM": (23.588, 58.383),    # Muscat
    "TR": (41.008, 28.978),    # Istanbul
    "AU": (-33.869, 151.209),  # Sydney
}
# An override must sit on (or just off the simplified coastline of) its own
# country — a typo'd coordinate should fail the build, not sample the sea.
MAX_OFFSHORE_KM = 40


def centroid(geometry):
    """The old sample point: mean of every vertex of every part. Kept only so
    the rebuild can tell which countries' points moved."""
    polys = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polys = [polys]
    sx = sy = n = 0
    for poly in polys:
        for ring in poly:
            for lon, lat in ring:
                sx += lon
                sy += lat
                n += 1
    return (sx / n, sy / n) if n else (None, None)


def _km_to_geometry(pt, geometry):
    """Rough distance (km) from pt to the nearest vertex of the geometry."""
    return min(geo.dist_km(pt, v) for poly in geo.polygons(geometry)
               for ring in poly for v in ring)


def sample_point(iso, geometry):
    """(lon, lat) guaranteed on the country's own land, or None.

    1. SAMPLE_POINTS override.
    2. The vertex average of the main territory (largest ring), when that lands
       on it. Single-part countries keep exactly the point their data was built
       on, and it leans toward the (usually more visited) coast.
    3. Otherwise the largest ring's area centroid, nudged inside when a concave
       shape puts it outside (geo.ring_centroid, as app.js does for map pins).
    """
    if iso in SAMPLE_POINTS:
        lat, lon = SAMPLE_POINTS[iso]
        pt = (lon, lat)
        if geo.in_geometry(pt, geometry) or _km_to_geometry(pt, geometry) <= MAX_OFFSHORE_KM:
            return pt
        print("  {0}: override {1} is not on its own land — ignored".format(iso, pt))
    ring = geo.largest_ring(geometry)
    if not ring:
        return None
    mean = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    if geo.in_ring(mean, ring):
        return mean
    c = geo.ring_centroid(ring)
    if c and geo.in_ring(c, ring):
        return (c[0], c[1])
    return None


def comfort(temp, rain):
    """0-100 monthly comfort from avg temp (C) and total rain (mm). Sweet spot
    ~18-26C; hot months penalized harder (humidity); rain reduces the score."""
    if temp is None:
        return None
    if temp > 26:
        t_pen = (temp - 26) * 6
    elif temp < 18:
        t_pen = (18 - temp) * 4
    else:
        t_pen = 0
    r_pen = min(60, (rain or 0) * 0.18)
    return max(0, min(100, round(100 - t_pen - r_pen)))


def monthly_scores(lat, lon):
    url = ("{0}?latitude={1:.3f}&longitude={2:.3f}&start_date={3}&end_date={4}"
           "&daily=temperature_2m_mean,precipitation_sum&timezone=auto").format(
        ARCHIVE, lat, lon, YEAR[0], YEAR[1])
    data = rates.fetch_json(url, retries=4)
    daily = data.get("daily", {})
    times = daily.get("time", [])
    temps = daily.get("temperature_2m_mean", [])
    rains = daily.get("precipitation_sum", [])
    # Temperature averages over every matching day, but rain must be totalled
    # PER (year, month) and then averaged across years — comfort() expects one
    # month's rainfall in mm. Summing every matching day across a 5-year window
    # would report five Januaries of rain as one, quintupling the penalty and
    # driving nearly every score to the floor.
    mt = defaultdict(list)                          # month -> daily temps
    mr = defaultdict(lambda: defaultdict(float))    # month -> year -> total mm
    for t, tp, rn in zip(times, temps, rains):
        y, m = int(t[0:4]), int(t[5:7])
        if tp is not None:
            mt[m].append(tp)
        if rn is not None:
            mr[m][y] += rn
    scores, temps = [], []
    for m in range(1, 13):
        at = sum(mt[m]) / len(mt[m]) if mt[m] else None
        tr = (sum(mr[m].values()) / len(mr[m])) if mr[m] else 0
        scores.append(comfort(at, tr))
        temps.append(round(at) if at is not None else None)  # avg °C, shown in the guide
    return scores, temps


def season_order(months):
    """Months in the order a season reads. A season that runs across New Year
    starts after its largest gap: [1, 2, 12] -> [12, 1, 2], so it reads
    "December, January and February", not "January, February and December".
    Anything else stays in calendar order ([3, 4, 10] -> "March, April and
    October")."""
    b = sorted(set(months))
    n = len(b)
    if n < 2 or b[0] + 12 - b[-1] > 2:
        return b
    _gap, i = max(((b[(i + 1) % n] - b[i]) % 12, i) for i in range(n))
    start = (i + 1) % n
    return b[start:] + b[:start]


def best_months(scores, iso):
    if iso in CURATED:
        return CURATED[iso]
    ranked = sorted(range(12), key=lambda i: (scores[i] if scores[i] is not None else -1),
                    reverse=True)
    return season_order(m + 1 for m in ranked[:3])


def main(only=None):
    """Rebuild every country, or only the ISO codes in `only`."""
    with open(GEOJSON, encoding="utf-8") as f:
        geo_data = json.load(f)

    out = {}
    feats = [f for f in geo_data["features"]
             if f["properties"].get("iso") and f["properties"]["iso"] != "-99"
             # Northern Ireland carries iso "GB"; the UK is its own feature.
             and not (f["properties"].get("sub") and f["properties"]["sub"] == f["properties"]["iso"])
             and (not only or f["properties"]["iso"] in only)]
    print("computing climate for {0} countries...".format(len(feats)))
    for i, f in enumerate(feats):
        iso = f["properties"]["iso"]
        name = f["properties"].get("name", iso)
        if iso in out:
            continue
        pt = sample_point(iso, f["geometry"])
        if pt is None:
            print("  [{0}/{1}] {2} {3} SKIPPED: no sample point on land".format(i + 1, len(feats), iso, name))
            continue
        lon, lat = pt
        try:
            scores, temps = monthly_scores(lat, lon)
            out[iso] = {
                "name": name,
                "scores": scores,
                "temps": temps,
                "best": best_months(scores, iso),
                "curated": iso in CURATED,
            }
            print("  [{0}/{1}] {2} {3} ok".format(i + 1, len(feats), iso, name))
        except (urllib.error.HTTPError, urllib.error.URLError, Exception) as e:
            print("  [{0}/{1}] {2} {3} FAILED: {4}".format(i + 1, len(feats), iso, name, e))
        # 0.4s was fine for one-year requests; five-year ones are ~5x the payload
        # and Open-Meteo started returning 429 about 190 countries in.
        time.sleep(0.9)

    # MERGE onto whatever is already committed rather than replacing it. A run
    # that gets rate-limited half way through used to write only the countries
    # it managed to fetch, silently deleting the rest — the 2026-07 rebuild lost
    # 39 (Singapore, the Maldives, most of the Caribbean) before this existed.
    # Stale data for a country beats no data for it. A refreshed country keeps
    # any fields this script doesn't produce.
    previous = {}
    try:
        with open(OUT, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        pass
    kept = [k for k in previous if k not in out]
    merged = dict(previous)
    for iso, row in out.items():
        merged[iso] = dict(previous.get(iso) or {}, **row)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1} ({2} fresh, {3} kept from the previous file)"
          .format(len(merged), OUT, len(out), len(kept)))
    if kept and not only:
        print("  kept: {0}".format(", ".join(sorted(kept)[:20])))


if __name__ == "__main__":
    main(set(a.upper() for a in sys.argv[1:]) or None)

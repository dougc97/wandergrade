#!/usr/bin/env python3
"""Precompute monthly climate-comfort scores per country -> public/climate.json.

"Best time to travel" has no API, so we derive a weather-comfort proxy: for each
country's centroid we pull a year of daily temperature + rainfall from Open-Meteo
(free, no key), aggregate to months, and score each month 0-100. Top destinations
get curated best-month overrides on top (the "hybrid" approach).

Run once (re-run to refresh): python3 -m fxtracker.build_climate
It writes a static file the website reads, so there are no live weather calls.
"""

import json
import os
import time
import urllib.request
import urllib.error
from collections import defaultdict

from . import rates  # reuse the verifying SSL context + fetch_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
OUT = os.path.join(ROOT, "public", "climate.json")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
YEAR = ("2024-01-01", "2024-12-31")

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


def centroid(geometry):
    """Rough centroid: mean of all coordinate pairs. Good enough for one climate
    sample per country (big/multi-part countries are approximate)."""
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
    mt, mr = defaultdict(list), defaultdict(list)
    for t, tp, rn in zip(times, temps, rains):
        m = int(t[5:7])
        if tp is not None:
            mt[m].append(tp)
        if rn is not None:
            mr[m].append(rn)
    scores, temps = [], []
    for m in range(1, 13):
        at = sum(mt[m]) / len(mt[m]) if mt[m] else None
        tr = sum(mr[m]) if mr[m] else 0
        scores.append(comfort(at, tr))
        temps.append(round(at) if at is not None else None)  # avg °C, shown in the guide
    return scores, temps


def best_months(scores, iso):
    if iso in CURATED:
        return CURATED[iso]
    ranked = sorted(range(12), key=lambda i: (scores[i] if scores[i] is not None else -1),
                    reverse=True)
    return sorted(m + 1 for m in ranked[:3])


def main():
    with open(GEOJSON, encoding="utf-8") as f:
        geo = json.load(f)

    out = {}
    feats = [f for f in geo["features"]
             if f["properties"].get("iso") and f["properties"]["iso"] != "-99"]
    print("computing climate for {0} countries...".format(len(feats)))
    for i, f in enumerate(feats):
        iso = f["properties"]["iso"]
        name = f["properties"].get("name", iso)
        if iso in out:
            continue
        lon, lat = centroid(f["geometry"])
        if lat is None:
            continue
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
        time.sleep(0.4)  # be gentle with the free API

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1}".format(len(out), OUT))


if __name__ == "__main__":
    main()

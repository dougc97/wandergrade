#!/usr/bin/env python3
"""Precompute PPP conversion factors per country -> public/ppp.json (World Bank,
free, no key). One call covers all countries.

The website combines this annual figure with the live exchange rate to derive a
"price level vs the US" (affordability): price_level = ppp_factor / market_rate.
Below ~1 means the country is cheaper than the US for a dollar holder.

Run: python3 -m fxtracker.build_ppp
"""

import json
import os
import urllib.request

from . import rates  # reuse the verifying SSL context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "ppp.json")
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
# PA.NUS.PPP = PPP conversion factor, GDP (local currency units per international $)
URL = ("https://api.worldbank.org/v2/country/all/indicator/PA.NUS.PPP"
       "?format=json&date=2017:2025&per_page=20000")


def _fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "fx-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=40, context=rates._SSL) as resp:
        raw = resp.read().decode("utf-8-sig")
    return json.loads(raw)[1] or []


def main():
    # Only keep real countries that exist on our map.
    with open(GEOJSON, encoding="utf-8") as f:
        valid = {feat["properties"]["iso"] for feat in json.load(f)["features"]
                 if feat["properties"].get("iso") and feat["properties"]["iso"] != "-99"}

    latest = {}  # iso -> (year, value, name)
    for r in _fetch():
        iso = r["country"]["id"]
        val = r["value"]
        if val is None or len(iso) != 2 or not iso.isalpha() or iso not in valid:
            continue
        year = int(r["date"])
        if iso not in latest or year > latest[iso][0]:
            latest[iso] = (year, val, r["country"]["value"])

    out = {iso: {"ppp": round(v, 6), "year": y, "name": nm}
           for iso, (y, v, nm) in latest.items()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1}".format(len(out), OUT))


if __name__ == "__main__":
    main()

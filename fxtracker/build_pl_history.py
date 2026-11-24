#!/usr/bin/env python3
"""Price level vs the US, per country per year since 1990 -> public/pl_history.json
(World Bank, free, no key). Feeds the Cost of living tab's "over time" chart.

A year's price level is the PPP factor (the one ppp.json and the map use:
household consumption, PA.NUS.PRVT.PP, or the GDP-wide PA.NUS.PPP where
build_ppp.pick_basis falls back to it) over the exchange rate the World
Bank's own US$ GDP implies (NY.GDP.MKTP.CN / NY.GDP.MKTP.CD).

Each country's series is on ONE basis, its map figure's, so the chart never
joins two kinds of figure. A country on the GDP-wide fallback is GDP-wide
throughout. A household-basis country's years without a household figure
(the UAE before 2007, the 1990s for most post-Soviet states, the last year
for Qatar) follow the GDP-wide figure's year-to-year move, linked at the
nearest year with both: spliced raw, the two differ by up to 2.5x (Gambia,
1990) and would draw jumps nobody measured — the fault of the GDP-in-US$ /
GDP-at-PPP route below. "gdp" lists, per country, the year ranges that
follow the GDP-wide figure (review 2026-11-23 item 15).

Two routes that look equivalent are not:
 * PPP factor / official rate (PA.NUS.FCRF) mixes units — the factor is in
   euros for every year while the rate is in francs or marks before a country
   joined (France read 0.20 in 1995), and redenominations did the same to
   Venezuela and Zimbabwe (0.00).
 * GDP in US$ / GDP at PPP (NY.GDP.MKTP.PP.CD) carries national-accounts
   rebasings as fake jumps: ~40 countries' older years sit on the pre-rebasing
   GDP level (Guyana 0.16 -> 0.43 in one year, Ghana "92% pricier than 1990"
   when it is 12% cheaper).
The World Bank's ready-made ratio (PA.NUS.PPPC.RF) has been archived.

"alt" lists countries whose US$ GDP is converted at a rate more than 10% off
the official one (Burundi, Angola): their yearly figures are consistent with
each other but not with the map's today figure, which uses the official rate,
so the chart doesn't join the two.

Run: python3 -m fxtracker.build_pl_history   (server.py also refreshes it monthly)
"""

import json
import os
import time

from .build_ppp import _fetch, GEOJSON, ROOT, pick_basis

OUT = os.path.join(ROOT, "public", "pl_history.json")
FIRST_YEAR = 1990
_THIS_YEAR = time.gmtime().tm_year
_URL = ("https://api.worldbank.org/v2/country/all/indicator/{0}"
        "?format=json&date=%d:%d&per_page=20000" % (FIRST_YEAR, _THIS_YEAR + 1))
HH_URL = _URL.format("PA.NUS.PRVT.PP")      # LCU per international $, household consumption
PPP_URL = _URL.format("PA.NUS.PPP")          # LCU per international $, all of GDP
USD_URL = _URL.format("NY.GDP.MKTP.CD")       # GDP, current US$
LCU_URL = _URL.format("NY.GDP.MKTP.CN")       # GDP, current local currency
FX_URL = _URL.format("PA.NUS.FCRF")           # official rate, LCU per US$
# A year counts only if about as many countries have it as the year before:
# the World Bank publishes a new year gradually (ppp.json was once built when
# 2025 existed for 42 countries), and a "typical country" from a few would
# not be one.
MIN_YEAR_COVER = 0.8
ALT_RATE = 1.10
# A ratio of exactly a euro conversion rate is a change of unit, not another
# exchange rate: Bulgaria's GDP is already in euros while its official rate is
# still quoted in lev (x1.95583).
EURO_CONVERSION = (1.95583, 7.5345, 0.585274, 15.6466, 0.702804, 3.4528, 0.4293,
                   30.126, 239.64, 340.75)
# Outside this a ratio is a data error, not a price level (the map's own
# plausibility band, tablePriceLevel in app.js, is 0.08-6).
LO, HI = 0.05, 6.0
# A single year this far off BOTH neighbours is a broken observation (post-
# Soviet 1992 Azerbaijan read 0.01 between 0.14 and 0.06); a real devaluation
# moves the level and it stays moved (Argentina 2002, Nigeria 2024).
SPIKE = 2.5


def _by_iso(rows, valid):
    out = {}
    for r in rows:
        iso, val = r["country"]["id"], r["value"]
        if val is None or iso not in valid:
            continue
        out.setdefault(iso, {})[int(r["date"])] = val
    return out


def _despike(vals):
    out = list(vals)
    for i in range(1, len(vals) - 1):
        a, b, c = vals[i - 1], vals[i], vals[i + 1]
        if a and b and c and (min(b / a, b / c) > SPIKE or max(b / a, b / c) < 1 / SPIKE):
            out[i] = None
    return out


def _newest(series):
    """{iso: (year, value, None)} — the newest figure per country, in the
    shape build_ppp.pick_basis takes."""
    return {iso: (max(s), s[max(s)], None) for iso, s in series.items() if s}


def factors(hh, gdp):
    """({iso: {year: factor}}, {iso: [[from, to], ...]}): each country's PPP
    factor per year on its map figure's basis, and the year ranges that
    follow the GDP-wide figure (the whole series on the fallback; linked
    years for a household-basis country)."""
    out, flagged = {}, {}
    for iso, (_y, _v, _n, basis) in pick_basis(_newest(hh), _newest(gdp)).items():
        h, g = hh.get(iso, {}), gdp.get(iso, {})
        if basis == "gdp":
            out[iso], linked = dict(g), sorted(g)
        else:
            both = sorted(y for y in h if y in g)
            f, linked = dict(h), []
            for y in sorted(g):
                if y in h or not both:
                    continue
                at = min(both, key=lambda b: (abs(b - y), b))
                f[y] = g[y] * h[at] / g[at]
                linked.append(y)
            out[iso] = f
        ranges = []
        for y in linked:
            if ranges and ranges[-1][1] == y - 1:
                ranges[-1][1] = y
            else:
                ranges.append([y, y])
        if ranges:
            flagged[iso] = ranges
    return out, flagged


def build():
    """{"years", "pl": {iso: [level or None per year]}, "alt": [iso], "gdp":
    {iso: [[from, to], ...]}, "source"}; raises on a failed fetch (the
    caller keeps what it has)."""
    with open(GEOJSON, encoding="utf-8") as f:
        valid = {feat["properties"]["iso"] for feat in json.load(f)["features"]
                 if feat["properties"].get("iso")}
    ppp, gdp_years = factors(_by_iso(_fetch(HH_URL), valid), _by_iso(_fetch(PPP_URL), valid))
    usd = _by_iso(_fetch(USD_URL), valid)
    lcu = _by_iso(_fetch(LCU_URL), valid)
    try:
        fx = _by_iso(_fetch(FX_URL), valid)
    except Exception:
        fx = {}          # only the "alt" check needs it
    years = sorted({y for s in ppp.values() for y in s})
    out, alt = {}, []
    for iso, p in ppp.items():
        u, c = usd.get(iso, {}), lcu.get(iso, {})
        vals = []
        for y in years:
            v = p[y] * u[y] / c[y] if p.get(y) and u.get(y) and c.get(y) else None
            vals.append(v if v is not None and LO <= v <= HI else None)
        vals = _despike(vals)
        if sum(v is not None for v in vals) < 2:
            continue
        out[iso] = [round(v, 4) if v is not None else None for v in vals]
        both = [y for y in years if u.get(y) and c.get(y) and fx.get(iso, {}).get(y)]
        if both:
            y = both[-1]
            ratio = (c[y] / u[y]) / fx[iso][y]
            unit = any(abs(ratio / k - 1) < 0.01 or abs(ratio * k - 1) < 0.01
                       for k in EURO_CONVERSION)
            if max(ratio, 1 / ratio) > ALT_RATE and not unit:
                alt.append(iso)
    if not out:
        raise ValueError("no World Bank price levels")
    # Trailing years nobody (or too few) has reached yet.
    def cover(i):
        return sum(v[i] is not None for v in out.values())
    while len(years) > 1 and cover(len(years) - 1) < MIN_YEAR_COVER * cover(len(years) - 2):
        years.pop()
        for iso in out:
            out[iso].pop()
    out = {iso: v for iso, v in out.items() if sum(x is not None for x in v) >= 2}
    # Only the flagged years the series still shows (inside the published
    # window, with a figure).
    gdp = {}
    for iso, ranges in gdp_years.items():
        if iso not in out:
            continue
        shown = [y for a, b in ranges for y in range(a, b + 1)
                 if y in years and out[iso][years.index(y)] is not None]
        r = []
        for y in shown:
            if r and r[-1][1] == y - 1:
                r[-1][1] = y
            else:
                r.append([y, y])
        if r:
            gdp[iso] = r
    return {"years": years, "pl": out, "alt": sorted(a for a in alt if a in out), "gdp": gdp,
            "source": "World Bank: PA.NUS.PRVT.PP (PA.NUS.PPP in the years \"gdp\" lists) "
                      "x NY.GDP.MKTP.CD / NY.GDP.MKTP.CN"}


def committed():
    with open(OUT, encoding="utf-8") as f:
        return json.load(f)


def main():
    out = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print("wrote %s: %d countries, %d-%d" % (OUT, len(out["pl"]), out["years"][0], out["years"][-1]))


if __name__ == "__main__":
    main()

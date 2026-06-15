"""Country popularity = international tourism receipts in US$ (UN Tourism via the
World Bank indicator ST.INT.RCPT.CD — same provider as the PPP data).

Receipts (money spent by inbound visitors) is a better "famous leisure
destination" signal than raw arrivals: arrivals over-counts border crossings and
regional day-trips (which floated Kazakhstan/Kyrgyzstan/Tunisia near the top),
while receipts tracks real tourism spend (US, France, Thailand, Japan, Italy…).

We take the MAX per country over a recent multi-year window rather than the
latest value: that ignores the COVID-2020/21 trough (which otherwise sinks big
destinations to the bottom) and auto-updates as new normal-year data lands. The
frontend turns this into the "popular vs hidden-gem" split.
"""

import datetime

from . import rates  # reuse fetch_json (SSL verify + retries)

API = "https://api.worldbank.org/v2/country/all/indicator/ST.INT.RCPT.CD"


def get_arrivals():
    """Return {ISO2: max_annual_tourism_receipts_usd} for the last ~10 years.
    Aggregates (World, EU, …) are left in; the frontend keeps only real
    countries. (Name kept as get_arrivals for the stable API surface.)"""
    year = datetime.date.today().year
    url = "{0}?format=json&per_page=8000&date=2015:{1}".format(API, year)
    data = rates.fetch_json(url)
    rows = data[1] if isinstance(data, list) and len(data) > 1 else []
    best = {}
    for r in rows or []:
        v = r.get("value")
        c = r.get("country") or {}
        iso2 = c.get("id")
        iso3 = r.get("countryiso3code")
        if not v or not iso2 or not iso3 or len(iso3) != 3:
            continue
        if v > best.get(iso2, 0):
            best[iso2] = v
    return best

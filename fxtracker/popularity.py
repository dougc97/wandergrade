"""Country popularity = international tourist arrivals (UN Tourism via the World
Bank indicator ST.INT.ARVL — same provider as the PPP data).

We take the MAX arrivals per country over a recent multi-year window rather than
the latest value: that ignores the COVID-2020/21 trough (which otherwise sinks
big destinations to the bottom) and auto-updates as new normal-year data lands.
The frontend turns this into the "popular vs hidden-gem" split.
"""

import datetime

from . import rates  # reuse fetch_json (SSL verify + retries)

API = "https://api.worldbank.org/v2/country/all/indicator/ST.INT.ARVL"


def get_arrivals():
    """Return {ISO2: max_annual_arrivals} for the last ~10 years. Aggregates
    (World, EU, …) are left in; the frontend keeps only real countries."""
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

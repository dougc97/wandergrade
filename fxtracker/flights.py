"""Cheapest flight prices from an origin via the Travelpayouts (Aviasales) API.

Free, but requires a token from a Travelpayouts account — read from the
TRAVELPAYOUTS_TOKEN env var. City/airport reference data is open (no token) and
is used to map destination codes to country + name for the map and table.
"""

import os
import urllib.parse

from . import rates  # reuse fetch_json (verifying SSL + retries)

API = "https://api.travelpayouts.com"
_cities = None  # code -> {"name", "country"} (lazy-loaded, cached)


def token():
    return os.environ.get("TRAVELPAYOUTS_TOKEN", "")


def is_configured():
    return bool(token())


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


def get_flights(origin, currency="usd", limit=200):
    """Cheapest recent fares from `origin` (IATA). Returns enriched items plus the
    cheapest price per country (for the map)."""
    origin = (origin or "").strip().upper()[:3]
    if not is_configured():
        return {"configured": False, "items": [], "by_country": {}}
    if not origin:
        return {"configured": True, "error": "missing origin", "items": [], "by_country": {}}

    cities = _load_cities()
    qs = urllib.parse.urlencode({
        "origin": origin, "currency": currency, "period_type": "year",
        "one_way": "false", "page": 1, "limit": limit, "sorting": "price",
        "token": token(),
    })
    data = rates.fetch_json("{0}/aviasales/v3/get_latest_prices?{1}".format(API, qs))
    rows = data.get("data", []) if isinstance(data, dict) else []

    items, by_country = [], {}
    for r in rows:
        dest = r.get("destination")
        meta = cities.get(dest, {})
        country = meta.get("country", "")
        price = r.get("value") or r.get("price")
        if price is None:
            continue
        items.append({
            "dest": dest,
            "city": meta.get("name", dest),
            "country": country,
            "price": price,
            "depart": (r.get("depart_date") or r.get("departure_at") or "")[:10],
            "return": (r.get("return_date") or r.get("return_at") or "")[:10],
            "transfers": r.get("number_of_changes", r.get("transfers", 0)),
        })
        if country and (country not in by_country or price < by_country[country]):
            by_country[country] = price

    items.sort(key=lambda x: x["price"])
    return {
        "configured": True,
        "origin": origin,
        "currency": currency,
        "items": items,
        "by_country": by_country,
    }

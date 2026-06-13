"""Country-level flight prices via the Travelpayouts (Aviasales) API.

The user picks an ORIGIN COUNTRY; we query cached cheapest fares from that
country's main air hub, drop domestic routes, and aggregate the results by
DESTINATION COUNTRY (average + cheapest fare). Free, but requires a token from
a Travelpayouts account — read from the TRAVELPAYOUTS_TOKEN env var.
"""

import os
import urllib.parse

from . import rates  # reuse fetch_json (verifying SSL + retries)

API = "https://api.travelpayouts.com"
_cities = None  # city code -> {"name", "country"} (lazy, cached)

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

    agg = {}  # dest country iso -> {"sum", "n", "min", "dur", "stops"}
    for r in rows:
        meta = cities.get(r.get("destination"), {})
        dest_iso = meta.get("country", "")
        price = r.get("value") or r.get("price")
        if price is None or not dest_iso or dest_iso == origin_iso:
            continue
        a = agg.setdefault(dest_iso, {"sum": 0.0, "n": 0, "min": price,
                                      "dur": None, "stops": None})
        a["sum"] += price
        a["n"] += 1
        if price <= a["min"]:
            # Travel time + layovers belong to the cheapest itinerary — the one
            # someone would actually book. duration_to is the outbound leg in
            # minutes; transfers is the number of stops on that leg.
            a["min"] = price
            a["dur"] = r.get("duration_to") or r.get("duration")
            a["stops"] = r.get("transfers")

    countries = [{"iso": iso, "avg": round(a["sum"] / a["n"]), "min": round(a["min"]),
                  "n": a["n"], "dur": a["dur"], "stops": a["stops"]}
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

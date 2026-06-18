"""Server-side port of the site's Top Picks scoring (app.js `valueScores`).

Generates the monthly newsletter's graded destination picks using the same
data and formulas the website uses, so the email matches what users see:

  Affordability = cheapness (PPP price level vs home) nudged by FX timing
  Safety        = US State Dept advisory level (1-4)
  Weather       = Open-Meteo climate comfort score for the chosen month
  Overall value = weighted mean (Affordability x3, Safety x2, Weather x2)

Flights (the 4th on-site factor) are NOT scored here: the site's flight grade
needs live Travelpayouts fares fitted against a distance baseline, which isn't
reproducible in a batch job. The composite above is exactly the site's formula
for any destination lacking a cached fare (~half the world), so the ranking is
faithful; the email points readers to the site for live flight deals.

Assumes a US traveler (home = USD, anchor price level = 1), matching the site's
default before any personalization.
"""

import datetime
import json
import os
import urllib.parse
import urllib.request

from . import advisories, popularity, rates

# Wikimedia blocks the default urllib UA; identify ourselves.
_UA = "Wandergrade/1.0 (https://wandergrade.com; hello@newsletter.wandergrade.com)"

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")

# Currency by country ISO-2 — transcribed from app.js CUR_BY_ISO so price levels
# line up with the site exactly.
_CUR = {
    # Americas
    "CA": "CAD", "MX": "MXN", "GT": "GTQ", "BZ": "BZD", "HN": "HNL", "NI": "NIO",
    "CR": "CRC", "CU": "CUP", "DO": "DOP", "HT": "HTG", "JM": "JMD", "TT": "TTD",
    "BS": "BSD", "BB": "BBD", "CO": "COP", "VE": "VES", "GY": "GYD", "SR": "SRD",
    "PE": "PEN", "BR": "BRL", "BO": "BOB", "PY": "PYG", "CL": "CLP", "AR": "ARS",
    "UY": "UYU",
    # Europe (non-euro)
    "GB": "GBP", "IM": "GBP", "JE": "GBP", "GG": "GBP", "CH": "CHF", "LI": "CHF",
    "NO": "NOK", "SJ": "NOK", "SE": "SEK", "DK": "DKK", "GL": "DKK", "FO": "DKK",
    "IS": "ISK", "CZ": "CZK", "PL": "PLN", "HU": "HUF", "RO": "RON", "BG": "BGN",
    "RS": "RSD", "BA": "BAM", "MK": "MKD", "AL": "ALL", "MD": "MDL", "UA": "UAH",
    "BY": "BYN", "RU": "RUB", "TR": "TRY",
    # Middle East
    "IL": "ILS", "PS": "ILS", "SA": "SAR", "AE": "AED", "QA": "QAR", "KW": "KWD",
    "BH": "BHD", "OM": "OMR", "JO": "JOD", "LB": "LBP", "SY": "SYP", "IQ": "IQD",
    "IR": "IRR", "YE": "YER",
    # Asia
    "CN": "CNY", "JP": "JPY", "KR": "KRW", "IN": "INR", "PK": "PKR", "BD": "BDT",
    "LK": "LKR", "NP": "NPR", "AF": "AFN", "MM": "MMK", "TH": "THB", "VN": "VND",
    "KH": "KHR", "LA": "LAK", "MY": "MYR", "SG": "SGD", "ID": "IDR", "PH": "PHP",
    "BN": "BND", "HK": "HKD", "MO": "MOP", "TW": "TWD", "MN": "MNT", "KZ": "KZT",
    "UZ": "UZS", "TM": "TMT", "KG": "KGS", "TJ": "TJS", "AZ": "AZN", "AM": "AMD",
    "GE": "GEL", "BT": "BTN", "KP": "KPW",
    # Oceania
    "AU": "AUD", "NZ": "NZD", "FJ": "FJD", "PG": "PGK", "SB": "SBD", "VU": "VUV",
    # Africa
    "EG": "EGP", "MA": "MAD", "DZ": "DZD", "TN": "TND", "LY": "LYD", "ZA": "ZAR",
    "NG": "NGN", "KE": "KES", "GH": "GHS", "ET": "ETB", "TZ": "TZS", "UG": "UGX",
    "RW": "RWF", "BI": "BIF", "SD": "SDG", "SO": "SOS", "DJ": "DJF", "AO": "AOA",
    "MZ": "MZN", "ZM": "ZMW", "BW": "BWP", "NA": "NAD", "SZ": "SZL", "LS": "LSL",
    "MW": "MWK", "MG": "MGA", "MU": "MUR", "GM": "GMD", "GN": "GNF", "LR": "LRD",
    "CD": "CDF", "CV": "CVE", "KM": "KMF", "MR": "MRU", "SC": "SCR", "ER": "ERN",
    # CFA franc zones
    "SN": "XOF", "CI": "XOF", "ML": "XOF", "BF": "XOF", "NE": "XOF", "BJ": "XOF",
    "TG": "XOF", "GW": "XOF", "CM": "XAF", "TD": "XAF", "CF": "XAF", "CG": "XAF",
    "GA": "XAF", "GQ": "XAF",
}
_EUROZONE = ["AT", "BE", "CY", "EE", "FI", "FR", "DE", "GR", "IE", "IT", "LV",
             "LT", "LU", "MT", "NL", "PT", "SK", "SI", "ES", "HR", "AD", "MC",
             "SM", "VA", "ME", "XK"]
_USD_USING = ["US", "EC", "SV", "PA", "TL", "ZW", "MH", "FM", "PW", "TC", "VG", "BQ"]
for _iso in _EUROZONE:
    _CUR[_iso] = "EUR"
for _iso in _USD_USING:
    _CUR[_iso] = "USD"

CUR_BY_ISO = _CUR

# Used only if the World Bank popularity feed is unavailable (mirrors app.js).
FALLBACK_POPULAR = set((
    "FR ES IT GB DE GR PT NL AT CH IE HR CZ IS NO SE DK PL HU BE TR "
    "US MX CA BR AR PE CO CR CU DO JM CL "
    "JP TH CN IN VN ID PH KR SG MY KH LK NP AE IL JO TW "
    "EG MA ZA KE TZ AU NZ").split())

POPULAR_N = 60
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def clamp100(x):
    return max(0, min(100, x))


def grade(score):
    if score is None:
        return "—"
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


# Safety grade comes straight from the advisory tier (app.js SAFE_GRADE), so the
# letter matches the State Dept level exactly. No advisory => treated as Level 2.
SAFE_GRADE = {1: "A", 2: "B", 3: "D"}


def _load(name):
    with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
        return json.load(f)


def flag(iso):
    """Regional-indicator flag emoji from an ISO-2 code (e.g. 'TR' -> 🇹🇷)."""
    if not iso or len(iso) != 2 or not iso.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso.upper())


def cover_photo(query, width=1024, height=420):
    """Resolve a landmark query (from activities.json `photo`) to an email-ready
    cover image URL. Returns None on any failure so a missing photo never breaks
    the email.

    We look up the Wikipedia article's image via the REST summary, then serve it
    through the free images.weserv.nl proxy (resized to a banner crop). Two
    reasons we can't hotlink Wikimedia directly in email:
      * Wikimedia now rejects arbitrary thumbnail widths ("use thumbnail sizes
        list" — 400), and the valid sizes differ per image.
      * Gmail's image proxy can't fetch raw upload.wikimedia.org URLs (403/400),
        so the photos silently fail to load.
    weserv sidesteps both: it fetches the original, resizes to any width, and
    serves a cache-friendly JPEG that Gmail's proxy loads fine.
    """
    if not query:
        return None
    url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
           + urllib.parse.quote(query.replace(" ", "_")))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15, context=rates._SSL) as r:
            d = json.load(r)
        orig = (d.get("originalimage") or {}).get("source")
        if orig and "//" in orig:
            bare = orig.split("//", 1)[1]   # strip scheme; weserv wants ssl:host/path
            return ("https://images.weserv.nl/?url="
                    + urllib.parse.quote("ssl:" + bare, safe="")
                    + "&w={0}&h={1}&fit=cover&a=attention&output=jpg&q=80".format(width, height))
        # Fall back to the ready-made (small but valid) thumbnail if no original.
        return (d.get("thumbnail") or {}).get("source")
    except Exception:
        return None


def _price_level(iso, ppp, rate_by_code):
    p = ppp.get(iso)
    cur = CUR_BY_ISO.get(iso)
    if not p or not cur:
        return None
    rate = 1.0 if cur == "USD" else rate_by_code.get(cur)
    if not rate:
        return None
    pl = p["ppp"] / rate
    if pl < 0.08 or pl > 6:          # guard against broken World Bank values
        return None
    return pl


def _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso):
    """One destination's scores for `month` (1-12). Returns None if unscorable
    or excluded (Level 4 / Do Not Travel). Mirrors app.js valueScores."""
    pl = _price_level(iso, ppp, rate_by_code)
    if pl is None:
        return None
    adv = adv_by_iso.get(iso)
    if adv == 4:
        return None                  # Do Not Travel: excluded outright
    cur = CUR_BY_ISO.get(iso)
    cl = climate.get(iso)

    aff = clamp100(((1.3 - pl) / 0.95) * 100)
    strength = strength_by_code.get(cur)
    fx = clamp100(50 + strength * 6.25) if strength is not None else 50
    afford = clamp100(aff * 0.7 + fx * 0.3)
    safe = {1: 100, 2: 70, 3: 35}.get(adv, 70)
    wx = cl["scores"][month - 1] if cl and cl["scores"][month - 1] is not None else 50

    # Weighted mean (Affordability 3, Safety 2, Weather 2) — the site's default
    # weights with Flights omitted (see module docstring).
    value = clamp100((3 * afford + 2 * safe + 2 * wx) / 7.0)
    name = (cl and cl.get("name")) or (ppp.get(iso) and ppp[iso].get("name")) or iso
    return {
        "iso": iso, "name": name, "afford": round(afford), "safe": round(safe),
        "wx": round(wx), "value": round(value), "advLvl": adv, "pl": pl,
        "fx": round(strength, 1) if strength is not None else None,
    }


def _popular_set():
    """Top-N countries by international tourism receipts, real countries only
    (drops World Bank aggregates by intersecting with CUR_BY_ISO)."""
    try:
        receipts = popularity.get_arrivals()
        ranked = sorted((iso for iso in receipts if iso in CUR_BY_ISO),
                        key=lambda i: receipts[i], reverse=True)
        if len(ranked) >= 20:
            return set(ranked[:POPULAR_N])
    except Exception:
        pass
    return set(FALLBACK_POPULAR)


def _enrich(s, acts, with_photo):
    """Attach flag, things-to-do, and (optionally) a resolved cover photo."""
    a = acts.get(s["iso"], {})
    s["flag"] = flag(s["iso"])
    s["activities"] = a.get("activities", [])[:2]
    s["photo"] = cover_photo(a.get("photo")) if with_photo else None
    return s


def build(month=None, n_picks=5, n_gems=3):
    """Fetch live data, score every destination, return the digest payload:
    {month, month_name, year, as_of, picks: [...], gems: [...]}.

    `picks` are the most-popular destinations (by tourism receipts) ranked by
    value; `gems` are off-the-beaten-path high-value ones. Both exclude Level 3
    (Reconsider Travel) and Level 4, matching the site's default "safe" floor.
    Picks are enriched with a cover photo + things-to-do; gems stay compact.
    """
    today = datetime.date.today()
    if month is None:
        # Feature ~2 months out so readers have booking lead time.
        month = (today.month - 1 + 2) % 12 + 1
    year = today.year + (1 if today.month + 2 > 12 else 0)

    ppp = _load("ppp.json")
    climate = _load("climate.json")
    acts = _load("activities.json")

    fav = rates.compute_favorability()
    rate_by_code = {r["code"]: r["rate_now"] for r in fav["rows"]}
    strength_by_code = {r["code"]: r["strength_pct"] for r in fav["rows"]}
    adv_by_iso = {it["iso"]: it["level"] for it in advisories.get_advisories()["items"] if it.get("iso")}
    popular = _popular_set()

    scored = []
    for iso in CUR_BY_ISO:
        s = _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso)
        if s and s["advLvl"] != 3:   # default "safe" floor: drop Level 3 (4 already gone)
            scored.append(s)

    scored.sort(key=lambda s: s["value"], reverse=True)
    picks = [s for s in scored if s["iso"] in popular][:n_picks]
    gems = [s for s in scored if s["iso"] not in popular][:n_gems]

    picks = [_enrich(s, acts, with_photo=True) for s in picks]
    gems = [_enrich(s, acts, with_photo=False) for s in gems]

    return {
        "month": month, "month_name": MONTHS[month - 1], "year": year,
        "as_of": fav["as_of"], "picks": picks, "gems": gems,
    }

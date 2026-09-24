"""Server-side port of the site's Top Picks scoring (app.js `valueScores`).

Generates the monthly newsletter's graded destination picks using the same
data and formulas the website uses, so the email matches what users see:

  Affordability = cheapness (PPP price level, carried forward for inflation)
                  nudged by the REAL FX move vs the 1-yr average
  Safety        = advisory level (1-3); unrated countries are not graded
  Weather       = Open-Meteo climate comfort score for the chosen month
  Flights       = the US fare vs the typical fare for that distance
  Overall value = weighted mean (Affordability x3, Safety x2, Weather x2,
                  Flights x2) — the site's default priorities

Flights come from the same cached-fare data the site uses (Travelpayouts
directly when a token is configured, otherwise the live site's /api/flights),
fitted against distance exactly as app.js buildFareContext() does; countries
with no cached fare get the site's distance estimate. If no fare data can be
had at all, Flights drops out — which is also what the site does then.

Every sub-score is rounded at the same steps as app.js (its clamp100 rounds),
so the letters in the email are the letters on the page it links to.

Assumes a US traveler (home = USD, anchor price level = the US's), matching the
site's default before any personalization.
"""

import datetime
import json
import math
import os
import urllib.parse
import urllib.request

from . import advisories, geo, popularity, pricelevel, rates

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
    "IS": "ISK", "CZ": "CZK", "PL": "PLN", "HU": "HUF", "RO": "RON",
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
             "SM", "VA", "ME", "XK", "BG"]   # Bulgaria: euro since 2026-01-01
_USD_USING = ["US", "EC", "SV", "PA", "TL", "ZW", "MH", "FM", "PW", "TC", "VG", "BQ",
              "PR"]
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


def js_round(x):
    """JavaScript Math.round: halves round up (Python's round() goes to even)."""
    return int(math.floor(x + 0.5))


def clamp100(x):
    """app.js clamp100 — which ROUNDS. Grading the same rounded sub-scores the
    site grades is what keeps a 92.5 from reading A+ here and A there."""
    return max(0, min(100, js_round(x)))


def grade(score):
    if score is None:
        return "—"
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


# Safety grade comes straight from the advisory tier (app.js SAFE_GRADE), so the
# letter matches the advisory level exactly. No advisory => not graded at all.
SAFE_GRADE = {1: "A", 2: "B", 3: "D"}

# The site's default priorities (app.js WEIGHT_DEFS/PRI_W: high 3, med 2).
WEIGHTS = {"afford": 3, "safe": 2, "wx": 2, "fly": 2}
HOME_ISO = "US"
SITE = "https://wandergrade.com"


def _load(name):
    with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
        return json.load(f)


def flag(iso):
    """Regional-indicator flag emoji from an ISO-2 code (e.g. 'TR' -> 🇹🇷)."""
    if not iso or len(iso) != 2 or not iso.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso.upper())


def cover_photo(query, width=1024, height=420):
    """URL only; see cover() for the credit that must travel with it."""
    return (cover(query, width, height) or {}).get("url")


def _strip_html(v):
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", "", v or "")).strip()


def photo_credit(orig_url):
    """Author + licence for a Wikimedia Commons file, from its extmetadata.

    Most Commons photos are CC BY or CC BY-SA, which require naming the author
    and the licence wherever the image appears — a footer "Photos via Wikimedia
    Commons" doesn't satisfy that. Returns None when it can't be resolved.
    """
    try:
        path = urllib.parse.urlsplit(orig_url).path
        if "/wikipedia/commons/" not in path:
            return None
        parts = path.split("/")
        name = parts[-2] if "/thumb/" in path else parts[-1]
        name = urllib.parse.unquote(name)
        url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
               "&prop=imageinfo&iiprop=extmetadata&titles="
               + urllib.parse.quote("File:" + name))
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15, context=rates._SSL) as r:
            pages = (json.load(r).get("query") or {}).get("pages") or {}
        for pg in pages.values():
            md = ((pg.get("imageinfo") or [{}])[0].get("extmetadata")) or {}
            val = lambda k: _strip_html((md.get(k) or {}).get("value"))
            return {"artist": val("Artist")[:80] or "Unknown author",
                    "license": val("LicenseShortName") or "see file page",
                    "license_url": (md.get("LicenseUrl") or {}).get("value") or "",
                    "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
                        "File:" + name.replace(" ", "_"))}
    except Exception:
        return None
    return None


def cover(query, width=1024, height=420):
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
        # Only freely licensed Commons files: an en.wikipedia-hosted image is
        # usually fair-use, which doesn't extend to a newsletter.
        credit = photo_credit(orig) if orig else None
        if not credit:
            return None
        # strip scheme (weserv wants ssl:host/path) and Wikipedia's utm_* query
        bare = orig.split("//", 1)[1].split("?", 1)[0]
        return {"url": ("https://images.weserv.nl/?url="
                        + urllib.parse.quote("ssl:" + bare, safe="")
                        + "&w={0}&h={1}&fit=cover&a=attention&output=jpg&q=80".format(width, height)),
                "credit": credit}
    except Exception:
        return None


def _price_level(iso, ppp, rate_by_code, fit=None):
    """Delegates to the canonical implementation — see fxtracker/pricelevel.py.

    This used to be its own copy of the arithmetic, which is how it silently
    fell behind when the income plausibility guard was added to the browser
    only. build() always passes `fit`, so the guard applies here too.
    """
    return pricelevel.price_level(iso, ppp, rate_by_code, CUR_BY_ISO, fit)


def _us_fares():
    """US-origin fare data, exactly what the site's Top Picks load. The digest
    job has no Travelpayouts token, so it reads the live site's cached copy."""
    try:
        from . import flights
        if flights.is_configured():
            return flights.get_flights(HOME_ISO)
    except Exception:
        pass
    try:
        return rates.fetch_json(SITE + "/api/flights?origin=" + HOME_ISO)
    except Exception as e:
        print("WARNING: no fare data ({0}); Flights left out of the grade.".format(e))
        return None


def fare_context(data, centroids=None):
    """Port of app.js buildFareContext(): known fares shrunk toward a fare ~
    distance fit, plus distance estimates for every mappable country. None when
    there is no fare data (the site then grades without Flights)."""
    if not (data and data.get("configured") and data.get("by_country")):
        return None
    c = centroids if centroids is not None else geo.country_centroids()
    prices = dict(data["by_country"])
    est = set()
    expected = None
    origin = data.get("origin")
    o = c.get(origin)
    pts = [(geo.dist_km(o, c[iso]), p) for iso, p in prices.items() if o and iso in c]
    if o and len(pts) >= 8:
        n = len(pts)
        mx = sum(x for x, _ in pts) / n
        my = sum(y for _, y in pts) / n
        num = sum((x - mx) * (y - my) for x, y in pts)
        den = sum((x - mx) ** 2 for x, _ in pts)
        b = num / den if den else 0
        a = my - b * mx

        def expected(iso):
            return max(50, a + b * geo.dist_km(o, c[iso])) if iso in c else None

        known = list(prices.values())
        lo, hi = min(known), max(known) * 1.4
        n_by = {r.get("iso"): r.get("n") for r in data.get("countries") or []}
        for iso in list(prices):
            if iso not in c:
                continue
            e = a + b * geo.dist_km(o, c[iso])
            w = (n_by.get(iso) or 1) / ((n_by.get(iso) or 1) + 3)
            prices[iso] = js_round(w * prices[iso] + (1 - w) * max(50, e))
        for iso in CUR_BY_ISO:
            if prices.get(iso) is not None or iso not in c or iso == origin:
                continue
            e = a + b * geo.dist_km(o, c[iso])
            prices[iso] = js_round(max(lo, min(hi, e)))
            est.add(iso)
    vals = list(prices.values())
    if not vals:
        return None
    return {"prices": prices, "est": est, "min": min(vals), "max": max(vals),
            "expected": expected}


def _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
           fit=None, fares=None, anchor_pl=1.0):
    """One destination's scores for `month` (1-12). Returns None if unscorable,
    unrated, or excluded (Level 4 / Do Not Travel). Mirrors app.js valueScores."""
    pl_us = _price_level(iso, ppp, rate_by_code, fit)
    if pl_us is None:
        return None
    pl = pl_us / (anchor_pl or 1)
    adv = adv_by_iso.get(iso)
    if adv == 4:
        return None                  # Do Not Travel: excluded outright
    # Unrated means unrated: the site declines to recommend a place no
    # government rates rather than invent a level (it used to read as Level 2).
    if not adv:
        return None
    cur = CUR_BY_ISO.get(iso)
    cl = climate.get(iso)

    aff = clamp100(((1.3 - pl) / 0.95) * 100)
    # The dollar's move vs its 1-yr average, net of the inflation gap: a steadily
    # depreciating high-inflation currency always sits above its own average.
    nominal = strength_by_code.get(cur) if cur and cur != "USD" else None
    real = pricelevel.real_fx_pct(nominal, iso, HOME_ISO, ppp)
    fx = clamp100(50 + real * 6.25) if real is not None else 50
    comps = {
        "afford": clamp100(aff * 0.7 + fx * 0.3),
        "safe": {1: 100, 2: 70, 3: 35}.get(adv, 70),
        "wx": cl["scores"][month - 1] if cl and cl["scores"][month - 1] is not None else 50,
    }
    fare = None
    if fares and fares["prices"].get(iso) is not None:
        fare = fares["prices"][iso]
        base = fares["expected"](iso) if fares["expected"] else None
        comps["fly"] = (clamp100(70 + (1 - fare / base) * 100) if base
                        else clamp100((fares["max"] - fare) / (fares["max"] - fares["min"]) * 100)
                        if fares["max"] > fares["min"] else 50)
    num = sum(WEIGHTS[k] * v for k, v in comps.items())
    den = sum(WEIGHTS[k] for k in comps)
    value = clamp100(num / den) if den else 0
    name = (cl and cl.get("name")) or (ppp.get(iso) and ppp[iso].get("name")) or iso
    return {
        "iso": iso, "name": name, "afford": comps["afford"], "safe": comps["safe"],
        "wx": comps["wx"], "fly": comps.get("fly"), "value": value, "advLvl": adv,
        "pl": pl, "fare": fare, "fareEst": bool(fares and iso in fares["est"]),
        # REAL move, which is what "your dollar goes further" claims are about.
        "fx": round(real, 1) if real is not None else None,
        "fx_nominal": nominal,
    }


def _advisory_items():
    """US advisories for the digest. The feed fetch retries, but one bad morning
    at travel.state.gov used to abort the whole month's issue, so fall back to
    the live site's cached copy (which is also exactly what readers will see),
    then to Canada's feed, before giving up."""
    try:
        return advisories.get_advisories()["items"]
    except Exception as e:
        print("WARNING: US advisory feed failed ({0}); using the site's copy.".format(e))
    try:
        return rates.fetch_json(SITE + "/api/advisories")["items"]
    except Exception as e:
        print("WARNING: site advisories unavailable ({0}); using Canada's.".format(e))
    return advisories.get_advisories("ca")["items"]


def advisory_levels(items):
    """{iso: level}, keeping the MOST cautious row when a country appears twice
    (e.g. the US feed's separate Gaza and West Bank rows)."""
    out = {}
    for it in items:
        iso, lvl = it.get("iso"), it.get("level")
        if iso and lvl and lvl > out.get(iso, 0):
            out[iso] = lvl
    return out


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
    c = cover(a.get("photo")) if with_photo else None
    s["photo"] = c and c["url"]
    s["photo_credit"] = c and c["credit"]
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
    adv_by_iso = advisory_levels(_advisory_items())
    popular = _popular_set()
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, CUR_BY_ISO)
    anchor = _price_level(HOME_ISO, ppp, rate_by_code, fit) or 1
    fares = fare_context(_us_fares())

    scored = []
    for iso in CUR_BY_ISO:
        s = _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
                   fit, fares, anchor)
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

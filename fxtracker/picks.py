"""Server-side port of the site's Top Picks scoring (app.js `valueScores`).

Generates the monthly newsletter's graded destination picks using the same
data and formulas the website uses, so the email matches what users see:

  Affordability = cheapness (PPP price level, carried forward for inflation)
                  nudged by the REAL FX move vs the 1-yr average
  Safety        = advisory level (1-3); unrated countries are not graded
  Weather       = Open-Meteo climate comfort score for the chosen month
                  (left out of the mean where a country has no climate data)
  Flights       = the home country's fare vs the typical fare for that
                  distance (or the route's own typical for the month)
  Overall value = the plain mean of the grades a place has: every factor
                  counts the same (WEIGHTS, the site's default priorities
                  since 2026-10-14; Affordability counted x3 before)

Flights come from the same cached-fare data the site uses (Travelpayouts
directly when a token is configured, otherwise the live site's /api/flights),
fitted against distance exactly as app.js buildFareContext() does; countries
with no cached fare get the site's distance estimate. If no fare data can be
had at all, Flights drops out — which is also what the site does then.

Every sub-score is rounded at the same steps as app.js (its clamp100 rounds),
so the letters in the email are the letters on the page it links to.

build() assumes a US traveler (home = USD, anchor price level = the US's),
matching the site's default before any personalization. build_variant() scores
the same data for another home currency (fxtracker/digest_variants.py): fares
from that country, prices vs its price level, the currency's strength measured
in it — what the site shows a visitor whose From and currency are set there.
gather() fetches what every edition shares once, so a run building ten
editions doesn't fetch the shared inputs ten times.
"""

import copy
import datetime
import json
import os
import re
import urllib.parse
import urllib.request

from . import advisories, geo, popularity, pricelevel, rates
from .digest_variants import VARIANTS

# Wikimedia blocks the default urllib UA; identify ourselves.
_UA = "Wandergrade/1.0 (https://wandergrade.com; hello@newsletter.wandergrade.com)"

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")

# Currency by country ISO-2 — transcribed from app.js CUR_BY_ISO so price levels
# line up with the site exactly.
_CUR = {
    # Americas
    "CA": "CAD", "MX": "MXN", "GT": "GTQ", "BZ": "BZD", "HN": "HNL", "NI": "NIO",
    "CR": "CRC", "CU": "CUP", "DO": "DOP", "HT": "HTG", "JM": "JMD", "TT": "TTD",
    "BS": "BSD", "BB": "BBD",
    # Curaçao's XCG replaced the ANG 1:1 on the same USD peg; the feed quotes ANG.
    "AW": "AWG", "CW": "ANG",
    "CO": "COP", "VE": "VES", "GY": "GYD", "SR": "SRD",
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
    # The feed only quotes the old leone; the price level reads SLE via
    # pricelevel.PPP_UNIT, FX moves keep SLL (as app.js does).
    "SL": "SLL",
    # CFA franc zones
    "SN": "XOF", "CI": "XOF", "ML": "XOF", "BF": "XOF", "NE": "XOF", "BJ": "XOF",
    "TG": "XOF", "GW": "XOF", "CM": "XAF", "TD": "XAF", "CF": "XAF", "CG": "XAF",
    "GA": "XAF", "GQ": "XAF",
}
_EUROZONE = ["AT", "BE", "CY", "EE", "FI", "FR", "DE", "GR", "IE", "IT", "LV",
             "LT", "LU", "MT", "NL", "PT", "SK", "SI", "ES", "HR", "AD", "MC",
             "SM", "VA", "ME", "XK", "BG"]   # Bulgaria: euro since 2026-01-01
_USD_USING = ["US", "EC", "SV", "PA", "TL", "ZW", "MH", "FM", "PW", "TC", "VG", "BQ",
              "PR", "GU"]
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


js_round = pricelevel.js_round   # JavaScript Math.round (halves toward +inf)


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

# The site's default priorities (app.js WEIGHT_DEFS/PRI_W: high 3, med 2):
# every factor Med since 2026-10-14 (affordability was High, a leftover of
# the FX-tracker days; flights are a cost too, so cost is still half).
WEIGHTS = {"afford": 2, "safe": 2, "wx": 2, "fly": 2}
HOME_ISO = "US"
SITE = "https://wandergrade.com"


# app.js NAME_FIX: Natural Earth's abbreviations ("Dominican Rep.", "S. Sudan")
# and long forms read as the site names them, so a pick is called in the email
# what Top Picks and its guide call it.
NAME_FIX = {"US": "United States", "BA": "Bosnia and Herzegovina", "CD": "DR Congo",
            "CG": "Republic of the Congo", "CF": "Central African Republic",
            "DO": "Dominican Republic", "GQ": "Equatorial Guinea", "SS": "South Sudan",
            "SB": "Solomon Islands", "EH": "Western Sahara", "TF": "French Southern Territories"}


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
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", v or "")).strip()


# ---- the cover photo ---------------------------------------------------------
# A featured country's cover is the first candidate the site's own photo
# checks pass (cover_for): its activities.json `photo` where it has one (an
# optional override, for a gallery whose lead is weak at email size), then
# the guide gallery's first six entries in order, the photos the guide hero
# is drawn from. That is not always the hero's first photo: the hero leaves
# out a photo the activity rows below it show as a thumbnail, while two or
# more remain (app.js loadHeroPhotos), and the cover doesn't, so on
# 2026-10-30 eleven of the 57 countries that can be featured with a cover
# (CN HR HU IE LK MX NO PE TW VN ZA) lead with a photo their guide shows as
# an activity thumbnail, not as its hero (Vietnam's cover is Ho Chi Minh City
# Hall, its hero opens on Ban Gioc Falls); an override (MY) or a lead the
# email refuses (CZ's FAL licence) moves two more. The checks are app.js
# wikiIconic's and commonsPhoto's, plus two of the email's own: the licence
# list on every cover (LICENCE_OK) and the 800px floor (COVER_MIN_W).
# All of them ask about the photo, none whether the image service serves the
# address the email uses: October 2026's Vietnam cover passed every one and
# was a 404 there. A send adds that last look (cover_check.py, through
# cover_for's `loads`); nothing else asks the image service anything.

# Mirrors PHOTO_BAD in app.js (scripts/photo_sweep.py has the same copy): no
# map, flag, seal, logo, collage... matched on the file name.
PHOTO_BAD = re.compile(
    r"map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram"
    r"|\.svg|location|adm[_ ]|administrative|emblem|wikidata|collage|montage", re.I)
# Mirrors PHOTO_LICENCE_OK in app.js (scripts/gallery_entry.py LICENCE_OK):
# CC BY and CC BY-SA in any version or port, CC0 and public domain, matched
# against extmetadata's short name and its code. The site asks it of a pinned
# file; the email asks it of every cover, as the credit under it is all the
# licence gets.
LICENCE_OK = re.compile(
    r"^(?:cc[- ]by(?:-sa)?(?:[- ]\d(?:\.\d)?(?:[- ](?:[a-z]{2}|igo))?)?|cc0(?:[- ]1\.0)?"
    r"|pd(?:[- ][a-z0-9.-]+)?|public domain(?: mark(?: 1\.0)?)?)$", re.I)
# The original must be at least this wide (the guide hero's own bar), so
# _thumb always hands weserv a thumbnail at one of Wikimedia's steps, never
# an upload.wikimedia.org original, which Wikimedia answers with 429 when
# weserv asks (Venezuela's and Vanuatu's small files showed broken).
COVER_MIN_W = 800
# The guide hero shows a gallery's first six entries (app.js photoSubjects):
# with the override, at most seven lookups for a country, each once a run.
GALLERY_SHOWN = 6

_SKIP = None


def _skip_files():
    """public/photo-skip.json, the lead images the October 2026 photo sweep
    rejected, which the guide hero leaves out too; read once. An unreadable
    list skips nothing, as on the site."""
    global _SKIP
    if _SKIP is None:
        try:
            _SKIP = frozenset(_load("photo-skip.json").get("files") or [])
        except Exception:
            _SKIP = frozenset()
    return _SKIP


def _file_key(name):
    """A Commons file name as page.pageimage and photo-skip.json spell it: no
    File: prefix, underscores, first letter capitalised."""
    n = re.sub(r"^file:", "", (name or "").strip(), flags=re.I).replace(" ", "_")
    return n[:1].upper() + n[1:]


def _commons_file(name):
    """One Commons imageinfo request for File:<name>: the original's URL and
    width, its licence (short name and code) and the credit the email prints.
    CC BY / BY-SA ask for the author and the licence wherever the photo
    appears; a footer "Photos via Wikimedia Commons" doesn't do it. None when
    Commons has no such file."""
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&prop=imageinfo&iiprop=url|size|extmetadata"
           "&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|License&titles="
           + urllib.parse.quote("File:" + name))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15, context=rates._SSL) as r:
        pages = (json.load(r).get("query") or {}).get("pages") or {}
    for pg in pages.values():
        ii = (pg.get("imageinfo") or [None])[0]
        if not ii or not pg.get("title"):
            return None
        md = ii.get("extmetadata") or {}
        val = lambda k: _strip_html((md.get(k) or {}).get("value"))
        file = _file_key(pg["title"])
        return {"file": file, "url": ii.get("url") or "", "width": ii.get("width"),
                "licence": val("LicenseShortName"), "code": val("License"),
                "credit": {"artist": val("Artist")[:80] or "Unknown author",
                           "license": val("LicenseShortName") or "see file page",
                           "license_url": (md.get("LicenseUrl") or {}).get("value") or "",
                           "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
                               "File:" + file)}}
    return None


def _cover_of(name, width, height):
    """Commons file `name` as a cover, or None where the checks leave it out:
    PHOTO_BAD on its name, photo-skip.json, a licence LICENCE_OK refuses, an
    original under COVER_MIN_W wide, or one _thumb can't make a thumbnail of
    (a .tif: weserv would fetch the original). The name's checks cost no
    request; the rest is one imageinfo request."""
    name = (name or "").strip()
    if not name or PHOTO_BAD.search(name) or _file_key(name) in _skip_files():
        return None
    info = _commons_file(name)
    # Commons' canonical spelling of the name is the skip list's too.
    if not info or not info["url"] or info["file"] in _skip_files():
        return None
    if not (LICENCE_OK.match(info["licence"]) or LICENCE_OK.match(info["code"])):
        return None
    w = info["width"]
    if not isinstance(w, int) or w < COVER_MIN_W:
        return None
    # strip scheme (weserv wants ssl:host/path) and any utm_* query
    bare = _thumb(info["url"].split("//", 1)[1].split("?", 1)[0], w)
    if not bare.startswith("thumb.wikimedia.org/"):
        return None
    return _banner(bare, info["credit"], width, height)


# A compact card shows its photo at 110x84 (newsletter._compact_card); it is
# asked for at twice that, for sharp screens.
THUMB_W, THUMB_H = 220, 168


def _banner(bare, credit, width, height):
    """The email's banner for `bare`, a thumb.wikimedia.org host/path, served
    through the free images.weserv.nl proxy (resized to a banner crop). Two
    reasons we can't hotlink Wikimedia directly in email:
      * Wikimedia rejects arbitrary thumbnail widths ("use thumbnail sizes
        list" — 400), and the valid sizes differ per image.
      * Gmail's image proxy can't fetch raw upload.wikimedia.org URLs (403/400),
        so the photos silently fail to load.
    weserv sidesteps both: it fetches the thumbnail, resizes to any width, and
    serves a cache-friendly JPEG that Gmail's proxy loads fine. It is handed a
    thumbnail, never an original (_thumb): since Oct 2026 Wikimedia answers
    weserv's fetches of originals with 429, which weserv passes on as a 404,
    so Vietnam's Ha Long Bay showed as a broken image while every thumbnail
    loaded."""
    src = urllib.parse.quote("ssl:" + bare, safe="")
    size = "&w={0}&h={1}&fit=cover&a=attention&output=jpg&q=80"
    return {"url": ("https://images.weserv.nl/?url=" + src + size.format(width, height)),
            # The same photo for a compact card: the same service and the same
            # crop rule, at twice the size the card shows it (THUMB_W x THUMB_H).
            # The cards used to load the whole 1024x420 banner into a 110x84 box.
            "thumb": "https://images.weserv.nl/?url=" + src + size.format(THUMB_W, THUMB_H),
            "credit": credit}


def cover(query, width=1024, height=420):
    """A Wikipedia page title (a gallery entry, or activities.json `photo`) as
    an email-ready cover, {url, credit}: the page's lead image, asked for as
    app.js wikiIconic asks (prop=pageimages, which only names a free image),
    through _cover_of's checks. The REST summary can lead with a non-free
    one: France's Eiffel Tower page led there with the tower's logo, hosted
    on en.wikipedia, while pageimages and the guide hero give the Commons
    photo. The file is page.pageimage, the name the hero tests against
    photo-skip.json; two requests in all, with _cover_of's imageinfo. None
    on any failure, so a missing photo never breaks the email; cover_for
    then tries the next candidate."""
    if not query:
        return None
    url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages"
           "&piprop=original|name&redirects=1&titles=" + urllib.parse.quote(query, safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15, context=rates._SSL) as r:
            pages = (json.load(r).get("query") or {}).get("pages") or {}
        page = next(iter(pages.values()), None) or {}
        path = urllib.parse.urlsplit((page.get("original") or {}).get("source") or "").path
        # Only Commons files: one hosted on en.wikipedia instead is a file
        # Commons can't take (fair use, or a modern building where there is
        # no freedom of panorama: the UAE's, Kuwait's and Oman's leads), which
        # doesn't extend to a newsletter.
        if not page.get("pageimage") or "/wikipedia/commons/" not in path:
            return None
        return _cover_of(page["pageimage"], width, height)
    except Exception:
        return None


def cover_file(name, width=1024, height=420):
    """A gallery's pinned Commons file ({file, label}: one photo pinned by
    name where no page leads with a good one) as a cover, through the same
    checks as a page's lead image; one imageinfo request, app.js
    commonsPhoto's. None on any failure."""
    try:
        return _cover_of(name, width, height)
    except Exception:
        return None


def cover_candidates(a):
    """What a country's cover is chosen from, in order (`a` its
    activities.json entry): `photo` where it has one, then the gallery
    entries the guide hero shows, each once."""
    out = [a["photo"]] if a.get("photo") else []
    for g in (a.get("gallery") or [])[:GALLERY_SHOWN]:
        if g not in out:
            out.append(g)
    return out


def cover_for(a, memo=None, loads=None):
    """A featured country's cover, {url, thumb, credit}: the first of its
    cover_candidates that passes the site's own photo checks (cover() for a
    title, cover_file() for a pinned file), or None when none does.

    `loads` is a send's load check and nobody else's (cover_check.py, which
    send_digest.py asks for): it is asked about each cover that passes,
    `loads(candidate, cover)`, and one it says False to is passed over for
    the next. Without it nothing here asks the image service anything."""
    for entry in cover_candidates(a):
        c = _cover_memo(entry, memo)
        if c and (loads is None or loads(entry, c)):
            return c
    return None


# Wikimedia's standard thumbnail widths (scripts/dev/thumb_check.mjs has the
# full list), widest first; the banner is 1024 wide, so 1280 is plenty.
_THUMB_STEPS = (1280, 960, 500)
_THUMB_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _thumb(bare, width):
    """`bare` (host/path) of a Commons original as the thumb.wikimedia.org
    thumbnail at the widest step its `width` allows; anything else (already a
    thumbnail, a format whose thumbnail is renamed, a width unknown or under
    500) comes back unchanged."""
    host, _, path = bare.partition("/")
    parts = path.split("/")
    # wikipedia/commons/<a>/<ab>/<File.jpg>
    if (host != "upload.wikimedia.org" or len(parts) != 5 or parts[:2] != ["wikipedia", "commons"]
            or not parts[4].lower().endswith(_THUMB_EXT) or not isinstance(width, int)):
        return bare
    step = next((s for s in _THUMB_STEPS if width >= s), None)
    if step is None:
        return bare
    name = parts[4]
    return "thumb.wikimedia.org/wikipedia/commons/thumb/%s/%s/%s/%dpx-%s" % (
        parts[2], parts[3], name, step, name)


def _price_level(iso, ppp, rate_by_code, fit=None):
    """Delegates to the canonical implementation — see fxtracker/pricelevel.py.

    This used to be its own copy of the arithmetic, which is how it silently
    fell behind when the income plausibility guard was added to the browser
    only. build() always passes `fit`, so the guard applies here too.
    """
    return pricelevel.price_level(iso, ppp, rate_by_code, CUR_BY_ISO, fit)


def _fares_raw(origin=HOME_ISO):
    """Fare data from `origin` (ISO-2), exactly what the site's Top Picks load
    for a visitor travelling from there. The digest job has no Travelpayouts
    token, so it reads the live site's cached copy."""
    try:
        from . import flights
        if flights.is_configured():
            return flights.get_flights(origin)
    except Exception:
        pass
    try:
        return rates.fetch_json(SITE + "/api/flights?origin=" + origin)
    except Exception as e:
        print("WARNING: no fare data ({0}); Flights left out of the grade.".format(e))
        return None


def _flight_value(origin, fares):
    """The Flights tab's per-route month curves and typical ranges for the
    same origin — flightvalue.serve() with a token (the site's own cache),
    else the live site's copy. None when unavailable: the grade then falls
    back to the distance measure for every country, as it did before."""
    try:
        from . import flights, flightvalue
        if flights.is_configured():
            return flightvalue.serve(origin, fares)
    except Exception:
        pass
    try:
        return rates.fetch_json(SITE + "/api/flight-value?origin=" + origin)
    except Exception:
        return None


def month_fare(fv, iso, month, today=None):
    """(price, deviation vs the route's median) for `month` from the flight-
    value payload, or None when the route has no range or no fare that month.
    The month key is its next occurrence, the guide chart's rule — mirrors
    app.js flightMonthKey + fareValue."""
    c = (fv or {}).get("countries", {}).get(iso) if fv else None
    if not c or c.get("pending") or c.get("median") is None:
        return None
    today = today or datetime.date.today()
    mm = "%02d" % month
    key = next((k for k in fv.get("months") or [] if k[5:] == mm), None)
    if key is None:
        key = "%04d-%s" % (today.year if month > today.month else today.year + 1, mm)
    rec = (c.get("curve") or {}).get(key)
    if not rec:
        return None
    price = rec[0]
    return price, price / c["median"] - 1


def fare_context(data, centroids=None):
    """Port of app.js buildFareContext(): `prices` is the fare a traveller pays
    (cached average, or a distance estimate for every mappable country); `deal`
    is the same shrunk toward a fare ~ distance fit, which only the Flights
    grade reads. None when there is no fare data (the site then grades without
    Flights)."""
    if not (data and data.get("configured") and data.get("by_country")):
        return None
    c = centroids if centroids is not None else geo.country_centroids()
    prices = dict(data["by_country"])
    deal = dict(prices)
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
        for iso in list(deal):
            if iso not in c:
                continue
            e = a + b * geo.dist_km(o, c[iso])
            w = (n_by.get(iso) or 1) / ((n_by.get(iso) or 1) + 3)
            deal[iso] = js_round(w * deal[iso] + (1 - w) * max(50, e))
        for iso in CUR_BY_ISO:
            if prices.get(iso) is not None or iso not in c or iso == origin:
                continue
            e = a + b * geo.dist_km(o, c[iso])
            prices[iso] = deal[iso] = js_round(max(lo, min(hi, e)))
            est.add(iso)
    vals = list(deal.values())
    if not vals:
        return None
    return {"prices": prices, "deal": deal, "est": est, "min": min(vals), "max": max(vals),
            "expected": expected}


def _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
           fit=None, fares=None, anchor_pl=1.0, home_iso=HOME_ISO, home_cur="USD"):
    """One destination's scores for `month` (1-12). Returns None if unscorable,
    unrated, or excluded (Level 4 / Do Not Travel). Mirrors app.js valueScores.

    `strength_by_code` is each currency's move measured in `home_cur` (the
    site's homeRates rows); `rate_by_code` stays USD-based, because price
    levels are vs the US and `anchor_pl` (the home's own) rebases them."""
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
    nominal = strength_by_code.get(cur) if cur and cur != home_cur else None
    real = pricelevel.real_fx_pct(nominal, iso, home_iso, ppp)
    fx = clamp100(50 + real * 6.25) if real is not None else 50
    comps = {
        "afford": clamp100(aff * 0.7 + fx * 0.3),
        "safe": {1: 100, 2: 70, 3: 35}.get(adv, 70),
    }
    # No climate entry = no weather measure, averaged over the rest (app.js
    # wxKnown). A stand-in 50 put a D in the email that the site never shows.
    scores = (cl or {}).get("scores") or []
    if len(scores) >= month and scores[month - 1] is not None:
        comps["wx"] = scores[month - 1]
    fare = None
    fly_basis = None
    # Flights, month first: the chosen month's fare against the route's own
    # typical range (the Flights tab's Low/Typical/High), where a route has
    # one — at the median 70 (B), 30% under 100, 30% over 40, the same slope
    # the distance measure uses. Poland read an "A" beside a strip showing
    # September its priciest month, because the grade was the all-months
    # average against a distance-typical fare. That measure stays the
    # fallback for routes with too few cached months (and says so).
    mf = month_fare(fares.get("fv"), iso, month) if fares else None
    if mf:
        fare, dev = mf
        comps["fly"] = clamp100(70 - dev * 100)
        fly_basis = "month"
    elif fares and fares["prices"].get(iso) is not None:
        fare = fares["prices"][iso]
        deal = fares.get("deal", fares["prices"]).get(iso, fare)
        base = fares["expected"](iso) if fares["expected"] else None
        # An estimated fare IS the distance baseline, so it grades the neutral
        # 70 — what the site's "~" mark has always said ("flights count as a
        # typical fare for the distance"). Grading it against the baseline
        # read the 1.4x-max-known cap as a bargain: from Beijing (10 cached
        # fares) Argentina, Chile and El Salvador got Flights A+ and filled the
        # CNY picks. Mirrors app.js valueScores; US-origin estimates already
        # sat at 70, so the USD digest is unchanged.
        comps["fly"] = (70 if iso in fares["est"]
                        else clamp100(70 + (1 - deal / base) * 100) if base
                        else clamp100((fares["max"] - deal) / (fares["max"] - fares["min"]) * 100)
                        if fares["max"] > fares["min"] else 50)
        fly_basis = "distance"
    num = sum(WEIGHTS[k] * v for k, v in comps.items())
    den = sum(WEIGHTS[k] for k in comps)
    value = clamp100(num / den) if den else 0
    name = NAME_FIX.get(iso) or (cl and cl.get("name")) or (ppp.get(iso) and ppp[iso].get("name")) or iso
    return {
        "iso": iso, "name": name, "afford": comps["afford"], "safe": comps["safe"],
        "wx": comps.get("wx"), "fly": comps.get("fly"), "value": value, "advLvl": adv,
        # Before rounding, for ties only (build's sort; app.js rankValue).
        "raw": num / den if den else 0,
        "pl": pl, "fare": fare, "fareEst": bool(fares and iso in fares["est"] and fly_basis != "month"),
        "fly_basis": fly_basis,
        # REAL move, which is what "your dollar goes further" claims are about
        # (2 decimals, the same figure as the site's s.fx).
        "fx": real,
        "fx_nominal": nominal,
    }


def _advisory_items(source="us"):
    """US advisories for the digest. The feed fetch retries, but one bad morning
    at travel.state.gov used to abort the whole month's issue, so fall back to
    the live site's cached copy (which is also exactly what readers will see),
    then to Canada's feed, before giving up.

    Another `source` ("ca", "de": an edition graded on its home government's
    advisories) reads that feed, else the site's copy of it. Every edition
    uses "us" today (digest_variants.adv_source)."""
    if source != "us":
        try:
            return advisories.get_advisories(source)["items"]
        except Exception as e:
            print("WARNING: {0} advisory feed failed ({1}); using the site's copy.".format(
                source, e))
        return rates.fetch_json(SITE + "/api/advisories?source=" + source)["items"]
    try:
        return advisories.get_advisories()["items"]
    except Exception as e:
        print("WARNING: US advisory feed failed ({0}); using the site's copy.".format(e))
    try:
        return rates.fetch_json(SITE + "/api/advisories")["items"]
    except Exception as e:
        print("WARNING: site advisories unavailable ({0}); using Canada's.".format(e))
    # Canada's own levels standing in for the whole US list: each says so.
    return [dict(it, via=it.get("via") or "ca") for it in advisories.get_advisories("ca")["items"]]


def advisory_levels(items):
    """{iso: level}, keeping the MOST cautious row when a country appears twice
    (e.g. the US feed's separate Gaza and West Bank rows)."""
    out = {}
    for it in items:
        iso, lvl = it.get("iso"), it.get("level")
        if iso and lvl and lvl > out.get(iso, 0):
            out[iso] = lvl
    return out


# Whose level a grade is, in app.js ADV_SRC_SHORT's words ("per US State
# Dept" on the site's pills).
ADV_SRC_SHORT = {"us": "US State Dept", "ca": "Global Affairs Canada", "de": "German Foreign Office"}


def advisory_sources(items, source="us"):
    """{iso: short name of the government whose level advisory_levels kept}:
    the list's own (`source`), or the one that filled its gap (`via`: Côte
    d'Ivoire's Canada level on the US list)."""
    best = {}
    for it in items:
        iso, lvl = it.get("iso"), it.get("level")
        if iso and lvl and lvl > best.get(iso, (0, None))[0]:
            best[iso] = (lvl, it.get("via") or source)
    return {iso: ADV_SRC_SHORT.get(by, by) for iso, (_l, by) in best.items()}


def _popular_set():
    """Top-N countries by international tourism receipts, real countries only
    (drops World Bank aggregates by intersecting with CUR_BY_ISO)."""
    try:
        receipts = popularity.get_arrivals()
        ranked = sorted((iso for iso in receipts if iso in CUR_BY_ISO),
                        key=lambda i: receipts[i], reverse=True)
        if len(ranked) >= 20:
            # A curated country the feed has no figure for stays popular: the
            # World Bank's 2026-10-08 update blanked receipts for Spain, the UK,
            # Canada, China and 37 others, which made them "hidden gems".
            return set(ranked[:POPULAR_N]) | {i for i in FALLBACK_POPULAR if receipts.get(i) is None}
    except Exception:
        pass
    return set(FALLBACK_POPULAR)


def _enrich(s, acts, with_photo, memo=None, check=None, top=False):
    """Attach flag, things-to-do, and (optionally) the cover photo cover_for
    picks. `memo` caches cover lookups across editions (a candidate is one
    lookup a run, not ten). `check` is a send's cover_check.CoverCheck, None
    for every other caller: it passes over a photo that does not load at the
    address this card will use, the banner when `top`, else the small copy."""
    a = acts.get(s["iso"], {})
    s["flag"] = flag(s["iso"])
    s["activities"] = a.get("activities", [])[:2]
    c = None
    if with_photo:
        c = (check.choose(s.get("name") or s["iso"], top, lambda loads: cover_for(a, memo, loads))
             if check else cover_for(a, memo))
    s["photo"] = c and c["url"]
    # The compact cards' small copy of the same photo (_banner). .get: a
    # cover that carries none leaves the card on the banner.
    s["photo_thumb"] = c and c.get("thumb")
    s["photo_credit"] = c and c["credit"]
    return s


def _cover_memo(entry, memo):
    """One cover candidate, looked up once a run when `memo` is given. It
    calls the module-level cover() / cover_file() at call time (the digest
    tests swap fakes in)."""
    pinned = isinstance(entry, dict)
    key = ("file", entry.get("file")) if pinned else ("title", entry)
    if memo is not None and key in memo:
        return memo[key]
    c = cover_file(entry.get("file")) if pinned else cover(entry)
    if memo is not None:
        memo[key] = c
    return c


def gather(month=None):
    """Fetch what every edition of the digest shares, once: the month, the
    static data, the USD rates, the US advisories and the popular set. Fares,
    flight values, other bases' rates and other advisory sources are fetched
    lazily by build_variant() and memoized here, so a USD-only run makes
    exactly the outside calls build() always made, in the same order."""
    today = datetime.date.today()
    if month is None:
        # Feature ~2 months out so readers have booking lead time.
        month = (today.month - 1 + 2) % 12 + 1
    # The featured month's next occurrence, this month counted, as the
    # /cheapest/<month> page the issue links names it (render_cheapest.year_for):
    # an explicit --month 1 in October is January next year. This used to be
    # the default month's year, so --month 1 in October printed "January 2026".
    from .render_cheapest import year_for
    year = year_for(month, today)

    ppp = _load("ppp.json")
    climate = _load("climate.json")
    acts = _load("activities.json")

    fav = rates.compute_favorability()
    rate_by_code = {r["code"]: r["rate_now"] for r in fav["rows"]}
    us_items = _advisory_items()
    adv = {"us": advisory_levels(us_items)}
    adv_by = {"us": advisory_sources(us_items, "us")}
    popular = _popular_set()
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, CUR_BY_ISO)
    return {
        "month": month, "year": year, "ppp": ppp, "climate": climate, "acts": acts,
        "rate_by_code": rate_by_code, "fit": fit, "popular": popular,
        "adv": adv, "adv_by": adv_by, "fav_by_base": {"USD": fav}, "fares_by_origin": {}, "cover_memo": {},
    }


def _fav_for(shared, code):
    """compute_favorability() in `code`, memoized (USD is gather()'s).

    Every base re-fetches the same USD-based currency list, latest rates and
    year of history from the provider and rebases them locally, so nine
    editions would be 27 identical requests to a keyless API that answers a
    burst with 429. The provider fetches are shared across the non-USD bases
    of one run instead (deep copies, as compute_favorability may rebase in
    place); gather()'s USD call is left exactly as it always was."""
    memo = shared["fav_by_base"]
    if code not in memo:
        up = shared.setdefault("upstream", {})
        saved = rates.get_currencies, rates.get_latest, rates.get_timeseries

        def once(name, fn):
            def wrapped(*args):
                if (name,) + args not in up:
                    up[(name,) + args] = fn(*args)
                return copy.deepcopy(up[(name,) + args])
            return wrapped
        rates.get_currencies, rates.get_latest, rates.get_timeseries = (
            once("currencies", saved[0]), once("latest", saved[1]), once("timeseries", saved[2]))
        try:
            memo[code] = rates.compute_favorability(base=code)
        finally:
            rates.get_currencies, rates.get_latest, rates.get_timeseries = saved
    return memo[code]


def fares_for(shared, origin):
    """fare_context() for `origin` with its flight values attached, memoized.
    None when there is no fare data (Flights then drops out, as on the site)."""
    memo = shared["fares_by_origin"]
    if origin not in memo:
        raw = _fares_raw(origin)
        fares = fare_context(raw)
        if fares:
            fares["fv"] = _flight_value(origin, raw)
        memo[origin] = fares
    return memo[origin]


def _adv_for(shared, source):
    memo = shared["adv"]
    if source not in memo:
        items = _advisory_items(source)
        memo[source] = advisory_levels(items)
        shared.setdefault("adv_by", {})[source] = advisory_sources(items, source)
    return memo[source]


def build_variant(shared, v, n_picks=5, n_gems=3, cover_check=None):
    """Score every destination for edition `v` (a digest_variants.Variant)
    from gather()'s shared data and return the digest payload:
    {month, month_name, year, as_of, picks: [...], gems: [...], variant, home_iso}.

    `picks` are the most-popular destinations (by tourism receipts) ranked by
    value; `gems` are off-the-beaten-path high-value ones. Both exclude Level 3
    (Reconsider Travel) and Level 4, matching the site's default "safe" floor.
    Picks are enriched with a cover photo + things-to-do; gems stay compact.
    A non-USD edition leaves its own home country out (v.exclude_home).

    `cover_check` (a cover_check.CoverCheck, one for the whole run) is what
    send_digest.py passes so no issue goes out with a photo that does not
    load. Left out, as by every other caller, the payload is what it always
    was and the image service is never asked.
    """
    month = shared["month"]
    ppp, climate, acts = shared["ppp"], shared["climate"], shared["acts"]
    rate_by_code, fit = shared["rate_by_code"], shared["fit"]
    fav = _fav_for(shared, v.code)
    strength_by_code = {r["code"]: r["strength_pct"] for r in fav["rows"]}
    adv_by_iso = _adv_for(shared, v.adv_source)
    popular = shared["popular"]
    anchor = _price_level(v.home_iso, ppp, rate_by_code, fit) or 1
    fares = fares_for(shared, v.home_iso)

    scored = []
    for iso in CUR_BY_ISO:
        if v.exclude_home and iso == v.home_iso:
            continue
        s = _score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
                   fit, fares, anchor, home_iso=v.home_iso, home_cur=v.code)
        if s and s["advLvl"] != 3:   # default "safe" floor: drop Level 3 (4 already gone)
            scored.append(s)

    # Ties on the shown score break on the unrounded one, then the name, as
    # app.js rankValue does: list order used to decide them.
    scored.sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))
    picks = [s for s in scored if s["iso"] in popular][:n_picks]
    gems = [s for s in scored if s["iso"] not in popular][:n_gems]

    memo = shared["cover_memo"]
    # The first pick is the email's top card (newsletter.render_digest), the
    # one card that shows the banner; the load check asks for that address.
    picks = [_enrich(s, acts, with_photo=True, memo=memo, check=cover_check, top=(i == 0))
             for i, s in enumerate(picks)]
    gems = [_enrich(s, acts, with_photo=False, memo=memo) for s in gems]
    # Whose level each 🛡️ grade is: the email names it as the site does.
    by = (shared.get("adv_by") or {}).get(v.adv_source) or {}
    for s in picks + gems:
        s["advBy"] = by.get(s["iso"])

    return {
        "month": month, "month_name": MONTHS[month - 1], "year": shared["year"],
        "as_of": fav["as_of"], "picks": picks, "gems": gems,
        "variant": v.code, "home_iso": v.home_iso,
    }


def build(month=None, n_picks=5, n_gems=3, cover_check=None):
    """The USD edition: build_variant(gather(month), VARIANTS["USD"]) — the
    digest exactly as it was before editions existed. `cover_check`: see
    build_variant; only send_digest.py passes one."""
    return build_variant(gather(month), VARIANTS["USD"], n_picks, n_gems, cover_check)

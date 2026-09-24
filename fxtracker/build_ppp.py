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
import time
import urllib.request

from . import rates  # reuse the verifying SSL context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "ppp.json")
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
# PA.NUS.PPP = PPP conversion factor, GDP (local currency units per international $)
# The end year was hardcoded to 2025, which would have silently ignored 2026
# data the moment the World Bank published it. Ask for next year too — absent
# years simply come back null and are skipped.
_THIS_YEAR = time.gmtime().tm_year
URL = ("https://api.worldbank.org/v2/country/all/indicator/PA.NUS.PPP"
       "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# GDP per capita in current US$. Not used for the grade — only to sanity-check the
# price level. Price level tracks income log-linearly (the Penn effect), so a
# country whose price level is wildly out of line with its income is almost always
# a broken exchange rate rather than a genuinely expensive place. Sudan is the
# live example: the official rate is pegged near 602 SDG/USD while the currency
# really trades far weaker, which made the site rank Sudan the most expensive
# country on earth, ahead of Iceland and Switzerland.
GDP_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD"
           "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# Consumer-price inflation, annual %. The PPP factor is a year-old snapshot of
# local prices; dividing it by TODAY's rate with no inflation carry-forward read
# Turkey (CPI ~35%) as far cheaper than it is. pricelevel.py and app.js carry the
# factor forward with this, and use it to turn nominal FX moves into real ones.
# World Bank only: IMF DataMapper is bot-walled.
CPI_URL = ("https://api.worldbank.org/v2/country/all/indicator/FP.CPI.TOTL.ZG"
           "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# GDP in local currency and in US$. Where the two are identical the World Bank's
# "local currency" is the US dollar, so the PPP factor is USD per international
# $ (West Bank & Gaza, Liberia) — build-time check only, see _warn_usd_units().
GDP_LCU_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CN"
               "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
GDP_USD_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD"
               "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fx-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=40, context=rates._SSL) as resp:
        raw = resp.read().decode("utf-8-sig")
    return json.loads(raw)[1] or []


def _latest_by_iso(rows, valid):
    """Newest non-null value per country. The World Bank publishes with a lag and
    not every country lands in the same year, so we keep the latest PER COUNTRY."""
    latest = {}  # iso -> (year, value, name)
    for r in rows:
        iso = r["country"]["id"]
        val = r["value"]
        if val is None or len(iso) != 2 or not iso.isalpha() or iso not in valid:
            continue
        year = int(r["date"])
        if iso not in latest or year > latest[iso][0]:
            latest[iso] = (year, val, r["country"]["value"])
    return latest


def build():
    """Fetch and shape the PPP table: {iso: {ppp, year, name, gdppc, gdppc_year,
    infl, infl_year}} (the last four only when the World Bank has them).

    Shared by main() (writes the committed file) and the server's live refresh,
    so both paths can never disagree about how the data is derived. Keeps the
    latest available year PER COUNTRY — the World Bank publishes with a lag and
    not every country lands in the same year.
    """
    # Only keep real countries that exist on our map.
    with open(GEOJSON, encoding="utf-8") as f:
        valid = {feat["properties"]["iso"] for feat in json.load(f)["features"]
                 if feat["properties"].get("iso") and feat["properties"]["iso"] != "-99"}

    latest = _latest_by_iso(_fetch(URL), valid)
    out = {iso: {"ppp": round(v, 6), "year": y, "name": nm}
           for iso, (y, v, nm) in latest.items()}

    # Income is a cross-check, not an input to the grade, so it must never be able
    # to fail the PPP build. If it's unavailable the entries simply carry no
    # gdppc and the client falls back to its absolute plausibility bounds.
    try:
        for iso, (y, v, _nm) in _latest_by_iso(_fetch(GDP_URL), valid).items():
            if iso in out:
                out[iso]["gdppc"] = round(v, 2)
                out[iso]["gdppc_year"] = y
    except Exception as e:
        print("WARNING: GDP per capita fetch failed ({0}). "
              "Price-level plausibility check will fall back to absolute bounds.".format(e))

    # Same rule for inflation: without it the price level simply isn't carried
    # forward (factor 1), which is what the site did before this existed.
    try:
        for iso, (y, v, _nm) in _latest_by_iso(_fetch(CPI_URL), valid).items():
            if iso in out:
                out[iso]["infl"] = round(v, 2)
                out[iso]["infl_year"] = y
    except Exception as e:
        print("WARNING: inflation fetch failed ({0}). "
              "Price levels will not be carried forward for inflation.".format(e))

    return out


def _warn_usd_units(out):
    """Flag countries whose World Bank local currency is the US dollar but which
    pricelevel.PPP_UNIT doesn't know about — their PPP factor would otherwise be
    divided by a local rate it isn't quoted in (Palestine published 3x too cheap,
    Liberia dropped). Warn only: it runs at commit time, never in the live refresh."""
    from .pricelevel import PPP_UNIT
    from .picks import CUR_BY_ISO
    def same_year(rows):   # the value for the PPP factor's own data year
        return {r["country"]["id"]: r["value"] for r in rows if r["value"] is not None
                and r["date"] == str(out.get(r["country"]["id"], {}).get("year"))}
    try:
        lcu, usd = same_year(_fetch(GDP_LCU_URL)), same_year(_fetch(GDP_USD_URL))
    except Exception as e:
        print("WARNING: PPP unit check skipped ({0}).".format(e))
        return
    for iso in sorted(out):
        a, b = lcu.get(iso), usd.get(iso)
        if not a or not b or abs(a / b - 1) > 1e-6:
            continue
        unit = PPP_UNIT.get(iso) or CUR_BY_ISO.get(iso)
        # Ungraded (no currency mapping) or pegged 1:1 to the dollar: harmless.
        if unit in (None, "USD", "BSD", "BMD", "PAB"):
            continue
        print("WARNING: {0}'s PPP factor is quoted in US dollars (GDP in local currency == "
                  "GDP in US$) but it is divided by {1}; add it to pricelevel.PPP_UNIT and "
                  "app.js PPP_UNIT.".format(iso, unit))


def committed():
    """The ppp.json checked into the repo — the fallback when the API is down."""
    with open(OUT, encoding="utf-8") as f:
        return json.load(f)


def main():
    out = build()
    _warn_usd_units(out)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1}".format(len(out), OUT))


if __name__ == "__main__":
    main()

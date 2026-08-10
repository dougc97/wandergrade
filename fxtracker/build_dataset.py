#!/usr/bin/env python3
"""The public dataset: what US$100 buys in every country, as CSV and JSON.

Why this exists as a file at all: the site already published ppp.json, but that
is only the World Bank's own inputs re-hosted — the figure that is actually ours
(PPP divided by *today's* market rate, rather than a year-old snapshot) existed
solely as a computation in the reader's browser. Nobody could download the one
number that makes this site different from a World Bank mirror.

Run: python3 -m fxtracker.build_dataset
"""

import csv
import datetime
import io
import json

from . import rates
from .picks import CUR_BY_ISO
from . import pricelevel

FIELDS = [
    "iso", "country", "currency", "price_level", "usd100_buys",
    "ppp_factor", "ppp_year", "gdp_per_capita_usd", "gdp_per_capita_year",
]

NOTES = (
    "price_level is the World Bank PPP conversion factor divided by the market "
    "exchange rate at rates_as_of: 1.00 means prices match the US, 0.50 means "
    "half. usd100_buys is 100 / price_level, i.e. the local purchasing power of "
    "US$100 in US dollars. These are national averages for residents; tourist "
    "areas and rent paid by foreigners run well above them. Countries whose "
    "exchange rate is a managed peg, or otherwise so far out of line with income "
    "that the result would be fictional, are omitted rather than guessed."
)


def build(ppp):
    """Rows for every country we can state a price level for, cheapest first."""
    fav = rates.compute_favorability()
    rate_by_code = {r["code"]: r["rate_now"] for r in fav["rows"]}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, CUR_BY_ISO)

    rows = []
    for iso in sorted(CUR_BY_ISO):
        pl = pricelevel.price_level(iso, ppp, rate_by_code, CUR_BY_ISO, fit)
        if pl is None:
            continue
        p = ppp[iso]
        rows.append({
            "iso": iso,
            "country": p.get("name") or iso,
            "currency": pricelevel.PPP_CUR.get(iso) or CUR_BY_ISO[iso],
            "price_level": round(pl, 4),
            "usd100_buys": round(100.0 / pl, 2),
            "ppp_factor": p.get("ppp"),
            "ppp_year": p.get("year"),
            "gdp_per_capita_usd": p.get("gdppc"),
            "gdp_per_capita_year": p.get("gdppc_year"),
        })
    rows.sort(key=lambda r: r["price_level"])
    return {
        "meta": {
            "source": "https://wandergrade.com/",
            "rates_as_of": fav.get("as_of"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc)
                            .replace(microsecond=0).isoformat(),
            "countries": len(rows),
            "ppp_source": "World Bank PA.NUS.PPP (PPP conversion factor, GDP)",
            "income_source": "World Bank NY.GDP.PCAP.CD (GDP per capita, current US$)",
            "licence": "World Bank data under CC BY 4.0; derived figures free to reuse with attribution.",
            "notes": NOTES,
        },
        "countries": rows,
    }


def to_csv(payload):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for r in payload["countries"]:
        w.writerow(r)
    return buf.getvalue()


def main():
    from .picks import _load
    payload = build(_load("ppp.json"))
    print(json.dumps(payload["meta"], indent=2))
    print(to_csv(payload)[:400])
    print("... %d countries" % len(payload["countries"]))


if __name__ == "__main__":
    main()

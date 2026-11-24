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

# New columns go on the END so existing CSV consumers keep their positions.
FIELDS = [
    "iso", "country", "currency", "price_level", "usd100_buys",
    "ppp_factor", "ppp_year", "gdp_per_capita_usd", "gdp_per_capita_year",
    "ppp_unit", "inflation_pct", "inflation_year", "inflation_factor",
    "ppp_basis", "ppp_source",
]

NOTES = (
    "price_level is the PPP conversion factor for household consumption "
    "(ppp_basis household; ppp_basis gdp where the World Bank has no usable recent "
    "household figure: its last one carried forward along the GDP-wide factor; "
    "ppp_source names whose figure it is: the World Bank, or for Taiwan, which it "
    "doesn't cover, the IMF's GDP-wide factor adjusted to household spending with "
    "Taiwan's household/GDP price ratio from the Penn World Table), carried forward from "
    "mid-ppp_year to rates_as_of by the gap between local and US inflation "
    "(inflation_factor, from World Bank consumer-price inflation; 1 when no "
    "current figure exists), divided by the market exchange rate at rates_as_of: "
    "1.00 means prices match the US, 0.50 means half. ppp_unit is the currency "
    "the PPP factor is quoted in when it differs from the one in circulation "
    "(e.g. US dollars for West Bank & Gaza and Liberia). usd100_buys is "
    "100 / price_level, i.e. the local purchasing power of "
    "US$100 in US dollars. These are national averages for residents; tourist "
    "areas and rent paid by foreigners run well above them. Countries whose "
    "exchange rate is a managed peg, or otherwise so far out of line with income "
    "that the result would be fictional, are omitted rather than guessed."
)


def _taiwan_src(ppp):
    """How Taiwan's hand-entered factor was made (build_ppp.MANUAL), with the
    Penn World Table release and years its row carries."""
    e = (ppp or {}).get("TW") or {}
    imf = "IMF %s (PPPEX, GDP-wide)" % (e.get("src_note") or "World Economic Outlook")
    if not e.get("hh_ratio"):
        return imf + ", entered by hand"
    yrs = e.get("hh_years") or []
    return ("%s times Taiwan's household/GDP price ratio, %s, from the %s%s (pl_c / pl_gdpo against the "
            "US's own%s), entered by hand" % (
                imf, e["hh_ratio"], e.get("hh_src") or "Penn World Table",
                " " + e["hh_version"] if e.get("hh_version") else "",
                ", %d-%d average" % (min(yrs), max(yrs)) if yrs else ""))


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
            "currency": CUR_BY_ISO[iso],
            "price_level": round(pl, 4),
            "usd100_buys": round(100.0 / pl, 2),
            "ppp_factor": p.get("ppp"),
            "ppp_year": p.get("year"),
            "gdp_per_capita_usd": p.get("gdppc"),
            "gdp_per_capita_year": p.get("gdppc_year"),
            "ppp_unit": pricelevel.PPP_UNIT.get(iso) or CUR_BY_ISO[iso],
            "inflation_pct": p.get("infl"),
            "inflation_year": p.get("infl_year"),
            "inflation_factor": round(pricelevel.carry_factor(iso, ppp), 4),
            "ppp_basis": p.get("basis") or "household",
            "ppp_source": ("IMF + Penn World Table" if p.get("hh_ratio") else "IMF") if p.get("src") == "imf"
                          else "World Bank",
        })
    rows.sort(key=lambda r: r["price_level"])
    return {
        "meta": {
            "source": "https://wandergrade.com/",
            "rates_as_of": fav.get("as_of"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc)
                            .replace(microsecond=0).isoformat(),
            "countries": len(rows),
            "ppp_source": ("World Bank PA.NUS.PRVT.PP (PPP conversion factor, private consumption); "
                           "carried forward along PA.NUS.PPP (GDP) where ppp_basis is gdp; "
                           "Taiwan: " + _taiwan_src(ppp)),
            "income_source": "World Bank NY.GDP.PCAP.CD (GDP per capita, current US$)",
            "inflation_source": ("World Bank FP.CPI.TOTL.ZG (inflation, consumer prices, annual %); "
                                 "Taiwan: IMF World Economic Outlook (PCPIPCH)"),
            "licence": ("World Bank data under CC BY 4.0; Taiwan's figures from the IMF World Economic Outlook "
                        "(imf.org/external/terms.htm) and the Penn World Table (CC BY 4.0); derived figures free "
                        "to reuse with attribution."),
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

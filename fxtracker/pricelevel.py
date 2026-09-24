#!/usr/bin/env python3
"""The derived price level: World Bank PPP, carried forward for inflation since
its data year, divided by the live market rate — plus the real (inflation-
adjusted) FX move built on the same inflation figures.

This is the one number the whole site turns on, and it existed in two places —
app.js for the browser, picks.py for the newsletter. They drifted the moment the
income plausibility guard landed in the browser copy only, which is exactly the
kind of split that publishes one figure and grades on another. Both callers, and
the public dataset export, come through here now.

Kept deliberately free of I/O so the caller decides where ppp/rates come from.
"""

import datetime
import math

# Countries whose World Bank PPP factor is quoted in a unit other than the
# currency they trade in day to day. Mirrors PPP_UNIT in app.js, and is used ONLY
# for the price level — FX moves, the dataset's currency column and the guide keep
# the circulating currency (ILS, LRD, SLL).
#   BG: the 2025 factor was restated in euros (Bulgaria joined on 2026-01-01).
#   PS, LR: the World Bank's "local currency" for West Bank & Gaza and Liberia is
#     the US dollar (their GDP in LCU equals GDP in US$), so dividing by ILS/LRD
#     published Palestine ~3x too cheap and pushed Liberia below PL_MIN.
#   SL: quoted in new leones (SLE, 2022 redenomination); the rates provider only
#     carries the old SLL, so SLE is derived below.
PPP_UNIT = {"BG": "EUR", "PS": "USD", "LR": "USD", "SL": "SLE"}
# Kept for older callers; the circulating-currency override it once held (BG)
# now lives in CUR_BY_ISO via the eurozone list.
PPP_CUR = {}

# Currencies the provider doesn't quote, as (quoted code, quoted units per 1).
DERIVED_RATE = {"SLE": ("SLL", 1000.0)}

# Real price levels sit roughly in [0.1, 4]; outside this band means a broken
# World Bank value or a redenominated currency, not a genuinely extreme country.
PL_MIN, PL_MAX = 0.08, 6.0

# Price level tracks income log-linearly (the Penn effect). Anything this far off
# that line is almost always a broken exchange rate — a managed peg, or a
# currency that has collapsed — rather than a real outlier.
PLAUSIBLE_SD = 3.0
MIN_POINTS = 40

# ---- inflation (shared spec with app.js; the two must match) -----------------
# The PPP factor is a snapshot of local prices in its data year. Dividing it by
# TODAY's rate with no carry-forward read high-inflation countries as far cheaper
# than they are (Turkey 0.33 vs ~0.46), and a steadily depreciating currency
# always sits above its own 1-yr average, so nominal "+9%" FX was an artifact.
US_INFL_FALLBACK = 0.03
MAX_CARRY_YEARS = 3


def now_year(today=None):
    """Fractional current year: 2026-09-24 -> ~2026.73."""
    d = today or datetime.date.today()
    return d.year + (d.timetuple().tm_yday - 1) / 365.25


def infl_rate(iso, ppp, ppp_year=None):
    """Annual inflation as a fraction, or None when there is no usable reading.
    A high-inflation figure older than the PPP year (Argentina's 2024 = 220%)
    would badly overcorrect, so it counts as unknown."""
    e = ppp.get(iso)
    if not e or e.get("infl") is None:
        return None
    if ppp_year is None:
        ppp_year = e.get("year")
    iy = e.get("infl_year")
    if iy is not None and ppp_year is not None and iy < ppp_year and e["infl"] >= 10:
        return None
    return min(3.0, max(-0.05, e["infl"] / 100.0))


def high_infl_unknown(iso, ppp):
    """High inflation we can't date to the PPP year: FX direction is unknowable."""
    e = ppp.get(iso) or {}
    return infl_rate(iso, ppp) is None and (e.get("infl") or 0) >= 10


def us_infl(ppp):
    r = infl_rate("US", ppp)
    return US_INFL_FALLBACK if r is None else r


def carry_factor(iso, ppp, now_y=None):
    """How much local prices have outrun US prices since mid-PPP-year."""
    e = ppp.get(iso) or {}
    r_l = infl_rate(iso, ppp)
    if r_l is None or e.get("year") is None:
        return 1.0
    ny = now_year() if now_y is None else now_y
    t = min(MAX_CARRY_YEARS, max(0.0, ny - (e["year"] + 0.5)))
    return ((1 + r_l) / (1 + us_infl(ppp))) ** t


def real_fx_pct(nominal_pct, iso, home_iso, ppp):
    """Nominal "vs the 1-yr average" move -> real (inflation-adjusted) move, in %.
    None when the destination's high inflation isn't current (no honest answer).
    0.5 is the mean age in years of the samples in a 364-day average."""
    if nominal_pct is None:
        return None
    r_b = infl_rate(home_iso, ppp)
    if r_b is None:
        r_b = us_infl(ppp)
    r_l = infl_rate(iso, ppp)
    if r_l is None:
        if (ppp.get(iso) or {}).get("infl") is not None and ppp[iso]["infl"] >= 10:
            return None
        r_l = r_b
    return ((1 + nominal_pct / 100.0) * ((1 + r_b) / (1 + r_l)) ** 0.5 - 1) * 100.0


def rate_for(code, rate_by_code):
    """Units of `code` per US dollar, deriving the few the provider lacks."""
    if code == "USD":
        return 1.0
    if code in DERIVED_RATE:
        base, per = DERIVED_RATE[code]
        r = rate_by_code.get(base)
        return r / per if r else None
    return rate_by_code.get(code)


def raw_price_level(iso, ppp, rate_by_code, cur_by_iso, now_y=None):
    """PPP (carried forward for inflation) / market rate, with only the crude
    absolute bounds applied."""
    p = ppp.get(iso)
    cur = PPP_UNIT.get(iso) or cur_by_iso.get(iso)
    if not p or not cur or not p.get("ppp"):
        return None
    rate = rate_for(cur, rate_by_code)
    if not rate:
        return None
    pl = p["ppp"] * carry_factor(iso, ppp, now_y) / rate
    if pl < PL_MIN or pl > PL_MAX:
        return None
    return pl


def _fit(points):
    """Least-squares fit of ln(price level) on ln(income). None if too few."""
    n = len(points)
    if n < MIN_POINTS:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if not sxx:
        return None
    b = sum((x - mx) * (y - my) for x, y in points) / sxx
    a = my - b * mx
    sd = (sum((y - (a + b * x)) ** 2 for x, y in points) / n) ** 0.5
    return (a, b, sd) if sd > 0 else None


def plausibility_fit(ppp, rate_by_code, cur_by_iso, now_y=None):
    """Fit the income/price-level relationship across every country we can.

    Refits once without its own extremes, so a single broken country cannot
    widen the band enough to hide inside it.
    """
    pts = []
    for iso in ppp:
        g = (ppp[iso] or {}).get("gdppc")
        pl = raw_price_level(iso, ppp, rate_by_code, cur_by_iso, now_y)
        if g and g > 0 and pl:
            pts.append((math.log(g), math.log(pl)))
    first = _fit(pts)
    if not first:
        return None
    a, b, sd = first
    trimmed = [(x, y) for x, y in pts if abs(y - (a + b * x)) <= 3 * sd]
    return _fit(trimmed) or first


def implausible(iso, ppp, pl, fit):
    if not fit or pl is None:
        return False
    g = (ppp.get(iso) or {}).get("gdppc")
    if not g or g <= 0:
        return False
    a, b, sd = fit
    return abs(math.log(pl) - (a + b * math.log(g))) > PLAUSIBLE_SD * sd


def price_level(iso, ppp, rate_by_code, cur_by_iso, fit=None, now_y=None):
    """Price level vs the US, or None when we cannot state one honestly.

    Pass `fit` (from plausibility_fit) to apply the income cross-check; without
    it only the absolute bounds apply, which is what the old callers did.
    """
    pl = raw_price_level(iso, ppp, rate_by_code, cur_by_iso, now_y)
    if pl is None or implausible(iso, ppp, pl, fit):
        return None
    return pl

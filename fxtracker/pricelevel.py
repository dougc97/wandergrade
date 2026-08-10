#!/usr/bin/env python3
"""The derived price level: World Bank PPP divided by the live market rate.

This is the one number the whole site turns on, and it existed in two places —
app.js for the browser, picks.py for the newsletter. They drifted the moment the
income plausibility guard landed in the browser copy only, which is exactly the
kind of split that publishes one figure and grades on another. Both callers, and
the public dataset export, come through here now.

Kept deliberately free of I/O so the caller decides where ppp/rates come from.
"""

import math

# Countries whose PPP factor is quoted in a currency other than the one they
# trade in day to day. Mirrors PPP_CUR in app.js.
PPP_CUR = {"BG": "EUR"}

# Real price levels sit roughly in [0.1, 4]; outside this band means a broken
# World Bank value or a redenominated currency, not a genuinely extreme country.
PL_MIN, PL_MAX = 0.08, 6.0

# Price level tracks income log-linearly (the Penn effect). Anything this far off
# that line is almost always a broken exchange rate — a managed peg, or a
# currency that has collapsed — rather than a real outlier.
PLAUSIBLE_SD = 3.0
MIN_POINTS = 40


def raw_price_level(iso, ppp, rate_by_code, cur_by_iso):
    """PPP / market rate, with only the crude absolute bounds applied."""
    p = ppp.get(iso)
    cur = PPP_CUR.get(iso) or cur_by_iso.get(iso)
    if not p or not cur or not p.get("ppp"):
        return None
    rate = 1.0 if cur == "USD" else rate_by_code.get(cur)
    if not rate:
        return None
    pl = p["ppp"] / rate
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


def plausibility_fit(ppp, rate_by_code, cur_by_iso):
    """Fit the income/price-level relationship across every country we can.

    Refits once without its own extremes, so a single broken country cannot
    widen the band enough to hide inside it.
    """
    pts = []
    for iso in ppp:
        g = (ppp[iso] or {}).get("gdppc")
        pl = raw_price_level(iso, ppp, rate_by_code, cur_by_iso)
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


def price_level(iso, ppp, rate_by_code, cur_by_iso, fit=None):
    """Price level vs the US, or None when we cannot state one honestly.

    Pass `fit` (from plausibility_fit) to apply the income cross-check; without
    it only the absolute bounds apply, which is what the old callers did.
    """
    pl = raw_price_level(iso, ppp, rate_by_code, cur_by_iso)
    if pl is None or implausible(iso, ppp, pl, fit):
        return None
    return pl

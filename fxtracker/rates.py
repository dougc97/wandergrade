"""Fetch FX rates from fxratesapi.com (no API key, ~180 currencies) and score
USD favorability.

All rates are expressed as "units of foreign currency per 1 USD", so a HIGHER
number means the dollar is STRONGER -> better for a US traveler.

The only network surface is `fetch_json` + the three get_* helpers; swap those to
change provider. History is limited to ~366 days on this free tier, so windows
are capped at MAX_HISTORY_DAYS.
"""

import datetime
import json
import os
import ssl
import time
import urllib.request
import urllib.error

API = "https://api.fxratesapi.com"
BASE = "USD"
TIMEOUT = 20
MAX_HISTORY_DAYS = 364  # free-tier timeseries reaches ~366 days back

# The provider mixes non-fiat tickers into its rate list. Exclude crypto, precious
# metals, the IMF SDR / index units, and defunct or redenominated duplicates so
# the travel table and alerts only show real, current national currencies.
NON_FIAT = {
    # cryptocurrencies / stablecoins
    "ADA", "ARB", "BNB", "BTC", "DAI", "DOT", "ETH", "LTC", "OP", "SOL", "XRP",
    # precious metals, IMF SDR, Chilean UF index unit
    "XAU", "XAG", "XPT", "XPD", "XDR", "CLF",
    # defunct / redenominated / duplicate codes
    "BYR", "LTL", "LVL", "HRK", "ZMK", "MRO", "STD", "VEF", "SVC", "ZWL",
}

# Stable, liquid basket for the headline "overall USD strength" index. Using all
# ~180 currencies would let hyperinflation outliers (ARS, VES, etc.) distort it,
# so the index stays on these majors while the map/table use full coverage.
MAJORS = {
    "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD",
    "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK",
    "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "ZAR",
}


def _ssl_context():
    """Build a verifying SSL context that works even when python.org's Python
    ships without CA certs installed (a common macOS gotcha). Tries, in order:
    SSL_CERT_FILE env var, the `certifi` package, then the system bundle.
    Verification stays ON in every case."""
    env_file = os.environ.get("SSL_CERT_FILE")
    if env_file and os.path.exists(env_file):
        return ssl.create_default_context(cafile=env_file)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for path in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


_SSL = _ssl_context()


def fetch_json(url, retries=3):
    """GET + parse JSON, retrying transient errors (the provider sits behind
    Cloudflare and occasionally returns 5xx blips)."""
    req = urllib.request.Request(url, headers={"User-Agent": "fx-tracker/1.0"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last = e
            # Don't retry genuine client errors (e.g. bad currency code).
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500:
                raise
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def _day(date_str):
    """Normalize an ISO timestamp like '2026-05-01T23:59:00.000Z' to '2026-05-01'."""
    return date_str[:10]


def get_currencies():
    """Return {code: full_name} for every currency the provider supports."""
    data = fetch_json(API + "/currencies")
    return {code: meta.get("name", code) for code, meta in data.items()}


def get_latest():
    """Latest USD-based rates: returns (date_str, {code: rate})."""
    data = fetch_json("{0}/latest?base={1}".format(API, BASE))
    return _day(data["date"]), data["rates"]


def get_timeseries(start, end):
    """Daily USD-based rates between two dates (inclusive).
    Returns {date_str: {code: rate}} with date keys normalized to YYYY-MM-DD."""
    url = "{0}/timeseries?start_date={1}&end_date={2}&base={3}".format(
        API, start, end, BASE)
    rates = fetch_json(url)["rates"]
    return {_day(k): v for k, v in rates.items()}


def _series_by_currency(timeseries):
    """Pivot {date: {code: rate}} into {code: [rate, rate, ...]} (chronological)."""
    out = {}
    for day in sorted(timeseries.keys()):
        for code, rate in timeseries[day].items():
            out.setdefault(code, []).append(rate)
    return out


def _usd_index(timeseries, basket=MAJORS):
    """Build an equal-weighted USD strength index from a {date: {code: rate}} map.

    Raw rates can't be averaged (JPY~150 vs EUR~0.85), so each currency is
    normalized to 100 at its first day in the window; the index for a date is the
    mean of the basket currencies' normalized values that day. Index > 100 means
    the dollar is stronger overall than it was at the window start. Restricting to
    `basket` (the majors) keeps hyperinflation outliers from distorting it.

    Returns (points, change_pct) where points = [{date, value}, ...] chronological.
    """
    dates = sorted(timeseries.keys())
    if not dates:
        return [], 0.0

    # First observed rate per basket currency = its own baseline (=100).
    first = {}
    for d in dates:
        for code, rate in timeseries[d].items():
            if code in basket and code not in first and rate:
                first[code] = rate

    points = []
    for d in dates:
        normed = [
            (rate / first[code]) * 100.0
            for code, rate in timeseries[d].items()
            if code in first
        ]
        if normed:
            points.append({"date": d, "value": round(sum(normed) / len(normed), 2)})

    change_pct = round(points[-1]["value"] - 100.0, 2) if points else 0.0
    return points, change_pct


def _rate_label(strength_pct, percentile):
    """Human-friendly verdict combining how far above baseline and how high in range."""
    if strength_pct >= 5 and percentile >= 85:
        return "great"
    if strength_pct >= 2:
        return "good"
    if strength_pct >= -2:
        return "average"
    return "weak"


def compute_index(days=365):
    """Just the overall USD strength index over an arbitrary window. Used by the
    chart's window toggle, independent of the saved favorability settings."""
    days = min(days, MAX_HISTORY_DAYS)
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=days)).isoformat()
    end = today.isoformat()
    timeseries = get_timeseries(start, end)
    points, change = _usd_index(timeseries)
    basket = set()
    for day in timeseries.values():
        basket.update(c for c in day if c in MAJORS)
    return {
        "days": days,
        "index": points,
        "index_change_pct": change,
        "index_count": len(basket),
        "as_of": points[-1]["date"] if points else end,
    }


def compute_favorability(baseline_days=365, threshold_pct=2.0, watch=None):
    """Score every currency. Returns a dict with metadata and a sorted list of rows.

    Each row: code, name, rate_now, baseline_avg, low, high, strength_pct,
    percentile, favorable, label.
    """
    names = get_currencies()
    latest_date, latest = get_latest()

    baseline_days = min(baseline_days, MAX_HISTORY_DAYS)
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=baseline_days)).isoformat()
    end = today.isoformat()
    timeseries = get_timeseries(start, end)
    series = _series_by_currency(timeseries)
    index_points, index_change = _usd_index(timeseries)

    watch_set = set(c.upper() for c in (watch or []))

    rows = []
    for code, rate_now in latest.items():
        if code in NON_FIAT:
            continue
        hist = series.get(code)
        if not hist:
            continue
        avg = sum(hist) / len(hist)
        low, high = min(hist), max(hist)
        strength_pct = (rate_now / avg - 1.0) * 100.0 if avg else 0.0
        # Percentile rank of today's rate within the historical window (0-100).
        # High percentile = dollar near the strong end of its recent range.
        below = sum(1 for v in hist if v <= rate_now)
        percentile = below / len(hist) * 100.0
        favorable = strength_pct >= threshold_pct

        rows.append({
            "code": code,
            "name": names.get(code, code),
            "rate_now": round(rate_now, 4),
            "baseline_avg": round(avg, 4),
            "low": round(low, 4),
            "high": round(high, 4),
            "strength_pct": round(strength_pct, 2),
            "percentile": round(percentile, 1),
            "favorable": favorable,
            "watched": (not watch_set) or (code in watch_set),
            "label": _rate_label(strength_pct, percentile),
        })

    # Strongest dollar first.
    rows.sort(key=lambda r: r["strength_pct"], reverse=True)

    return {
        "as_of": latest_date,
        "baseline_days": baseline_days,
        "threshold_pct": threshold_pct,
        "rows": rows,
        # Overall USD strength vs rest-of-world, equal-weighted, base 100 at
        # window start. index_change = current value minus 100 (percent).
        "index": index_points,
        "index_change_pct": index_change,
        "index_count": len(rows),
    }

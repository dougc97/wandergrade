#!/usr/bin/env python3
"""Spike for the flight-coverage plan: would an origin-wide month matrix lift
the Flights tab's banded count? Read-only; prints counts, never the token.

    TRAVELPAYOUTS_TOKEN=... /usr/bin/python3 scripts/dev/tp_probe.py [--quick]

About 75 Travelpayouts calls paced at 3 s (the 20/min gate the server uses),
so roughly four minutes; --quick skips the per-route comparison (40 calls).

What it measures, in order:
  1. The year feed the server reads today (get_latest_prices, period_type=year,
     sorting=price): rows per page 1-6. A full page 3 (1000 rows) means the
     feed is truncated and cheap routes crowd out the rest.
  2. Proposal A, the month matrix: 12 get_latest_prices calls, one per window
     month, group_by=directions (one row per destination). Per call: rows,
     destinations, countries. Merged: countries with >= 6 months on their own,
     and merged fill-only into the live site's curves (/api/flight-value) -> the
     banded count the Flights tab would show.
  3. Fallback B2: the same 12 months through prices_for_dates?unique=true.
  4. market=us on the year feed and three month calls: does the cache change?
  5. (unless --quick) 20 routes: /v1/prices/monthly (what the server uses,
     undocumented now) vs aviasales/v3/grouped_prices group_by=month: months
     returned and price agreement, to judge the later migration.
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.travelpayouts.com"
SITE = "https://wandergrade.com"
HUB = "NYC"
ORIGIN = "US"
MIN_MONTHS = 6
PACE = 3.0
TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
QUICK = "--quick" in sys.argv
if not TOKEN or "paste" in TOKEN.lower() or "your" in TOKEN.lower():
    print("TRAVELPAYOUTS_TOKEN is not set to the real token (Render -> the service -> Environment); nothing to probe.")
    sys.exit(2)
# wandergrade.com's Cloudflare answers 403 to Python's default User-Agent.
UA = {"User-Agent": "wandergrade-probe/1.0 (+https://wandergrade.com)"}


def get_public(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))

_calls = 0


def get(url, params=None, token=True):
    """One GET, paced. Prints the path and the row count, never the token."""
    global _calls
    p = dict(params or {})
    if token:
        p["token"] = TOKEN
    full = url + ("?" + urllib.parse.urlencode(p) if p else "")
    if _calls:
        time.sleep(PACE)
    _calls += 1
    req = urllib.request.Request(full, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = json.loads(r.read().decode("utf-8"))
            left = r.headers.get("X-Rate-Limit-Remaining")
    except urllib.error.HTTPError as e:
        print("   HTTP %s on %s" % (e.code, url.split("?")[0].replace(API, "")))
        return None, None
    shown = {k: v for k, v in p.items() if k != "token"}
    return body, left


def rows_of(body):
    d = (body or {}).get("data")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):   # grouped responses: {key: row}
        return [dict(v, _key=k) for k, v in d.items() if isinstance(v, dict)]
    return []


def window_months(today=None):
    today = today or datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(12):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


print("loading city -> country map (public, no token)...")
cities = {}
for c in rows_of({"data": get_public(API + "/data/en/cities.json")}):
    if c.get("code"):
        cities[c["code"]] = c.get("country_code", "")
print("  %d cities" % len(cities))

print("loading the live site's current curves...")
live = get_public(SITE + "/api/flight-value?origin=US")
# {"countries": {iso: {"curve": {"YYYY-MM": price}, "n_months": n}}, "months": [...]}
WINDOW = set(live.get("months") or [])
cur_curve = {iso: set((e.get("curve") or {}).keys()) for iso, e in (live.get("countries") or {}).items()}
cur_months = {iso: (e.get("n_months") or 0) for iso, e in (live.get("countries") or {}).items()}
banded_now = sum(1 for n in cur_months.values() if n >= MIN_MONTHS)
print("  %d destinations, %d banded today (>= %d months)" % (len(cur_months), banded_now, MIN_MONTHS))

today = datetime.date.today()
cutoff = (today - datetime.timedelta(days=90)).isoformat()
months = window_months(today)


def by_country_month(rows):
    """{iso: {YYYY-MM: cheapest price}} for upcoming, fresh, foreign rows."""
    out = {}
    for r in rows:
        iso = cities.get(r.get("destination") or r.get("destination_airport") or "", "")
        price = r.get("value") or r.get("price")
        dep = (r.get("depart_date") or r.get("departure_at") or r.get("_key") or "")[:10]
        if not iso or iso == ORIGIN or price is None or not dep:
            continue
        if dep < today.isoformat() and len(dep) == 10:
            continue
        if (r.get("found_at") or "")[:10] and (r.get("found_at") or "")[:10] < cutoff:
            continue
        if r.get("actual") is False:
            continue
        m = dep[:7]
        d = out.setdefault(iso, {})
        if m not in d or price < d[m]:
            d[m] = price
    return out


def merged_banded(extra):
    """Fill-only merge of `extra` months into the live curves (union of month
    keys inside the window); the banded count the Flights tab would show, and
    how many destinations it would list at all."""
    n = 0
    listed = set(cur_curve) | set(extra)
    for iso in listed:
        months_now = cur_curve.get(iso, set()) | {m for m in extra.get(iso, {}) if not WINDOW or m in WINDOW}
        if len(months_now) >= MIN_MONTHS:
            n += 1
    return n


# 1. year feed truncation
print("\n1. year feed (what the server reads today)")
year_rows = []
for page in range(1, 7):
    body, left = get(API + "/aviasales/v3/get_latest_prices",
                     {"origin": HUB, "currency": "usd", "period_type": "year", "one_way": "false",
                      "page": page, "limit": 1000, "sorting": "price"})
    rows = rows_of(body)
    year_rows += rows
    print("  page %d: %d rows (rate-limit remaining %s)" % (page, len(rows), left))
    if len(rows) < 1000:
        break
ym = by_country_month(year_rows)
print("  feed alone: %d countries, %d with >= %d months" % (len(ym), sum(1 for v in ym.values() if len(v) >= MIN_MONTHS), MIN_MONTHS))

# 2. month matrix
print("\n2. month matrix: 12 x get_latest_prices period_type=month group_by=directions")
matrix_rows = []
for m in months:
    body, left = get(API + "/aviasales/v3/get_latest_prices",
                     {"origin": HUB, "currency": "usd", "period_type": "month", "beginning_of_period": m + "-01",
                      "group_by": "directions", "one_way": "false", "limit": 1000, "page": 1, "sorting": "price"})
    rows = rows_of(body)
    dests = {r.get("destination") for r in rows}
    isos = {cities.get(d, "") for d in dests} - {"", ORIGIN}
    found = sorted({(r.get("found_at") or "")[:10] for r in rows if r.get("found_at")})
    print("  %s: %4d rows, %3d destinations, %3d countries, found_at %s..%s" % (m, len(rows), len(dests), len(isos), found[:1], found[-1:]))
    for r in rows:
        r.setdefault("depart_date", m + "-15")
    matrix_rows += rows
mm = by_country_month(matrix_rows)
print("  matrix alone: %d countries, %d with >= %d months; merged fill-only with the live curves: %d banded (today %d)"
      % (len(mm), sum(1 for v in mm.values() if len(v) >= MIN_MONTHS), MIN_MONTHS, merged_banded(mm), banded_now))

# 3. fallback prices_for_dates
print("\n3. fallback: 12 x prices_for_dates unique=true")
pfd_rows = []
for m in months:
    body, left = get(API + "/aviasales/v3/prices_for_dates",
                     {"origin": HUB, "currency": "usd", "departure_at": m, "unique": "true",
                      "one_way": "false", "limit": 1000, "page": 1, "sorting": "price"})
    rows = rows_of(body)
    for r in rows:
        r.setdefault("depart_date", (r.get("departure_at") or m + "-15")[:10])
    print("  %s: %4d rows" % (m, len(rows)))
    pfd_rows += rows
pm = by_country_month(pfd_rows)
print("  prices_for_dates alone: %d countries, %d with >= %d months; merged fill-only: %d banded"
      % (len(pm), sum(1 for v in pm.values() if len(v) >= MIN_MONTHS), MIN_MONTHS, merged_banded(pm)))

# 4. market=us
print("\n4. market=us")
body, _ = get(API + "/aviasales/v3/get_latest_prices",
              {"origin": HUB, "currency": "usd", "period_type": "year", "one_way": "false", "page": 1,
               "limit": 1000, "sorting": "price", "market": "us"})
rows = rows_of(body)
top = {}
for r in rows:
    iso = cities.get(r.get("destination"), "")
    if iso:
        top[iso] = top.get(iso, 0) + 1
print("  year page 1 with market=us: %d rows, %d countries; top: %s"
      % (len(rows), len(top), ", ".join("%s %d" % kv for kv in sorted(top.items(), key=lambda kv: -kv[1])[:6])))
for m in months[:3]:
    body, _ = get(API + "/aviasales/v3/get_latest_prices",
                  {"origin": HUB, "currency": "usd", "period_type": "month", "beginning_of_period": m + "-01",
                   "group_by": "directions", "one_way": "false", "limit": 1000, "page": 1, "sorting": "price", "market": "us"})
    print("  month %s with market=us: %d rows" % (m, len(rows_of(body))))

# 5. per-route comparison
if not QUICK:
    print("\n5. 20 routes: /v1/prices/monthly vs grouped_prices group_by=month")
    dests = []
    for r in year_rows:
        d = r.get("destination")
        if d and cities.get(d, "") not in ("", ORIGIN) and d not in dests:
            dests.append(d)
        if len(dests) >= 20:
            break
    agree = total = 0
    for d in dests:
        a, _ = get(API + "/v1/prices/monthly", {"origin": HUB, "destination": d, "currency": "usd"})
        b, _ = get(API + "/aviasales/v3/grouped_prices", {"origin": HUB, "destination": d, "group_by": "month", "currency": "usd"})
        am = {k[:7]: v.get("price") for k, v in ((a or {}).get("data") or {}).items() if isinstance(v, dict)}
        bm = {k[:7]: v.get("price") for k, v in ((b or {}).get("data") or {}).items() if isinstance(v, dict)}
        same = sum(1 for k in am if k in bm and am[k] == bm[k])
        agree += same
        total += len(am)
        print("  %s: monthly %2d months, grouped %2d months, same price on %d" % (d, len(am), len(bm), same))
    print("  price agreement on shared months: %d/%d" % (agree, total))

print("\ndone: %d calls" % _calls)

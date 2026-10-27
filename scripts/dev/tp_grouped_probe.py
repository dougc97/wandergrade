#!/usr/bin/env python3
"""Spike: can aviasales/v3/grouped_prices (documented, 600 calls/min) replace
/v1/prices/monthly (listed as outdated, 60/min) as the per-route month curve
behind the guide's fare chart, the Top Picks strips and the Flights tab's
Low / Typical / High? Read-only. Never prints or saves the token.

    read -s TP; TRAVELPAYOUTS_TOKEN="$TP" /usr/bin/python3 scripts/dev/tp_grouped_probe.py OUT.json; unset TP

Travelpayouts' docs (Aviasales Data API, 2026-10-25): grouped_prices returns
"the cheapest tickets grouped by the specific attribute found by Aviasales
users in the last 48 hours"; to replace /v1/prices/monthly "pass month in
group_by, do not specify departure_at and return_at"; its market defaults to
ru (or the origin's), and it takes min_trip_duration / max_trip_duration in
days. October's 20-route check found different prices on all 96 shared
months without saying why; this run keeps every field so the reason can be
found offline (one-way vs round trip, trip length, stops, market, age).

Part A, paired and fresh: about 60 US routes (the first city of countries
with 6+, 3-5 and 1-2 months on the live Flights tab), each asked back to back:
  M   /v1/prices/monthly  origin=NYC destination=X currency=usd   (exactly the server's call)
  G   grouped_prices      origin=NYC destination=X group_by=month currency=usd
  GU  G + market=us
  GT  GU + min_trip_duration=3 + max_trip_duration=21
Part B, breadth: GU for every city the server's curves can use (each
country's up to 3 cities in the live /api/flights?origin=US), to count how
many countries a grouped curve would band (6+ months).

Pacing: M every 4 s (the server's own warmer uses the same token on this
endpoint at up to 20/min; 15 + 20 stays under the 60 limit), grouped every
0.25 s; a part stops after 3 consecutive 429s, and X-Rate-Limit-Remaining
under 5 waits out X-Rate-Limit-Reset. About 7 minutes, ~480 calls.

OUT.json: the live payloads read, then per route and variant the HTTP status,
milliseconds, rate-limit headers and the response's data. Prints counts only.
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.travelpayouts.com"
SITE = "https://wandergrade.com"
HUB = "NYC"
ORIGIN = "US"
M_PACE, G_PACE = 4.0, 0.25
PER_BUCKET = 20
# wandergrade.com's Cloudflare answers 403 to Python's default User-Agent.
UA = {"User-Agent": "wandergrade-probe/1.0 (+https://wandergrade.com)", "Accept-Encoding": "identity"}

TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip()
VARIANTS = {
    "G": {"group_by": "month", "currency": "usd"},
    "GU": {"group_by": "month", "currency": "usd", "market": "us"},
    "GT": {"group_by": "month", "currency": "usd", "market": "us",
           "min_trip_duration": "3", "max_trip_duration": "21"},
}
B_VARIANTS = ("GU",)
# --round2 (2026-10-26): run 1 showed grouped_prices without a trip length
# answers ONE-WAY fares (no return_at on all 137 shared months, about half
# the price), and with 3-21 days round trips equal to /v1/prices/monthly on
# 81% of months but fewer months. Round 2 looks for the settings that keep
# those months: wider trip windows and the undocumented one_way=false, each
# for Part A (paired with M again) and for every city in Part B.
if "--round2" in sys.argv:
    _RT = {"group_by": "month", "currency": "usd", "market": "us"}
    VARIANTS = {
        "R3_21": dict(_RT, min_trip_duration="3", max_trip_duration="21"),
        "R1_30": dict(_RT, min_trip_duration="1", max_trip_duration="30"),
        "R1_60": dict(_RT, min_trip_duration="1", max_trip_duration="60"),
        "RF": dict(_RT, one_way="false"),
    }
    B_VARIANTS = tuple(VARIANTS)


def public(path):
    req = urllib.request.Request(SITE + path, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=60))


class Pacer:
    def __init__(self, gap):
        self.gap, self.next = gap, 0.0

    def wait(self):
        now = time.monotonic()
        if now < self.next:
            time.sleep(self.next - now)
        self.next = time.monotonic() + self.gap


def call(path, params, pacer):
    """One token GET. Returns {status, ms, rate, data|error}; the URL (which
    carries the token) is never kept."""
    pacer.wait()
    q = dict(params, token=TOKEN)
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(q), headers=UA)
    t0 = time.monotonic()
    out = {}
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
            out["status"] = r.status
            hdr = r.headers
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        hdr = e.headers
        try:
            body = {"error": e.read(500).decode("utf-8", "replace")}
        except Exception:
            body = {"error": str(e.reason)}
    except Exception as e:   # network trouble: recorded, never fatal
        out["status"] = 0
        hdr = {}
        body = {"error": type(e).__name__ + ": " + str(e)[:200]}
    out["ms"] = round((time.monotonic() - t0) * 1000)
    out["rate"] = {k: hdr.get(k) for k in ("X-Rate-Limit", "X-Rate-Limit-Remaining", "X-Rate-Limit-Reset")
                   if hdr and hdr.get(k) is not None}
    if isinstance(body, dict):
        for k in ("success", "error", "currency", "data"):
            if k in body:
                out[k] = body[k]
    else:
        out["data"] = body
    # Out of budget for this minute: wait for the reset before the next call.
    try:
        if int(out["rate"].get("X-Rate-Limit-Remaining", 99)) < 5:
            time.sleep(min(60, int(out["rate"].get("X-Rate-Limit-Reset", 60))) + 1)
    except (TypeError, ValueError):
        pass
    if TOKEN and TOKEN in json.dumps(out):   # never write the token, even if echoed
        out = {"status": out.get("status"), "ms": out["ms"], "error": "response echoed the token; dropped"}
    return out


def months_of(res):
    d = res.get("data")
    return len(d) if isinstance(d, dict) else 0


def pick_sample(fv, fl):
    """The first city of up to PER_BUCKET countries per bucket of live
    months (6+, 3-5, 1-2, then 0/pending to fill), by ISO for repeatability."""
    rows = {r["iso"]: r for r in fl.get("countries") or [] if r.get("iso") and r.get("dest")}
    n = {iso: (c.get("n_curve") or 0) for iso, c in (fv.get("countries") or {}).items()}
    buckets = {"6+": [], "3-5": [], "1-2": [], "0": []}
    for iso in sorted(rows):
        k = n.get(iso, 0)
        buckets["6+" if k >= 6 else "3-5" if k >= 3 else "1-2" if k >= 1 else "0"].append(iso)
    chosen = []
    for b in ("6+", "3-5", "1-2"):
        chosen += [(iso, b) for iso in buckets[b][:PER_BUCKET]]
    short = 3 * PER_BUCKET - len(chosen)
    chosen += [(iso, "0") for iso in buckets["0"][:max(0, short)]]
    return [(iso, rows[iso]["dest"], b, n.get(iso, 0)) for iso, b in chosen]


def main(argv):
    if len(argv) < 2:
        print(__doc__.split("\n\n")[1])
        return 2
    argv = [a for a in argv if a != "--round2"]
    out_path = argv[1]
    if not TOKEN or "paste" in TOKEN.lower() or "your" in TOKEN.lower():
        print("TRAVELPAYOUTS_TOKEN is not set to the real token (Render -> the service -> Environment); nothing to probe.")
        return 2
    # What was pasted, described without showing it: a Travelpayouts API token
    # is 32 letters and digits. Then one call to see the API accepts it.
    shape = "%d characters%s" % (len(TOKEN), "" if TOKEN.isalnum() else ", including spaces or symbols")
    print("token: %s%s" % (shape, "" if len(TOKEN) == 32 and TOKEN.isalnum()
                           else " (a Travelpayouts token is 32 letters and digits)"))
    first = call("/aviasales/v3/grouped_prices", dict(next(iter(VARIANTS.values())), origin=HUB, destination="LON"), Pacer(0))
    if first["status"] in (401, 403):
        print("Travelpayouts rejected the token (HTTP %d). Copy TRAVELPAYOUTS_TOKEN's value again "
              "(Render -> Environment, or Travelpayouts -> Profile -> API token) and re-run." % first["status"])
        return 3
    print("token accepted (HTTP %s)" % first["status"])
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    print("reading the live site (no token)...")
    fl = public("/api/flights?origin=" + ORIGIN)
    fv = public("/api/flight-value?origin=" + ORIGIN)
    print("  %d countries in /api/flights, %d in /api/flight-value" % (len(fl.get("countries") or []),
                                                                       len(fv.get("countries") or {})))
    doc = {"meta": {"started": started, "hub": HUB, "origin": ORIGIN, "variants": VARIANTS,
                    "b_variants": list(B_VARIANTS),
                    "m_pace": M_PACE, "g_pace": G_PACE},
           "live_flights": fl, "live_fv": fv, "A": [], "B": []}
    pm, pg = Pacer(M_PACE), Pacer(G_PACE)

    def save():
        tmp = out_path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        os.replace(tmp, out_path)

    sample = pick_sample(fv, fl)
    print("\nPart A: %d routes, M + %s each (~%d min)" % (len(sample), " + ".join(VARIANTS),
                                                       round(len(sample) * M_PACE / 60) + 1))
    m429 = g429 = 0
    for i, (iso, city, bucket, n_live) in enumerate(sample, 1):
        rec = {"iso": iso, "city": city, "bucket": bucket, "n_curve_live": n_live}
        if m429 < 3:
            rec["M"] = call("/v1/prices/monthly", {"origin": HUB, "destination": city, "currency": "usd"}, pm)
            m429 = m429 + 1 if rec["M"]["status"] == 429 else 0
        if g429 < 3:
            for v, params in VARIANTS.items():
                rec[v] = call("/aviasales/v3/grouped_prices", dict(params, origin=HUB, destination=city), pg)
                g429 = g429 + 1 if rec[v]["status"] == 429 else 0
        doc["A"].append(rec)
        print("  %2d/%d %s %s [%s, live %d]: " % (i, len(sample), iso, city, bucket, n_live) + "  ".join(
            "%s %s/%d" % ((v,) + ((rec[v]["status"], months_of(rec[v])) if v in rec else ("-", 0)))
            for v in ("M",) + tuple(VARIANTS)))
        if i % 10 == 0:
            save()
    save()
    if m429 >= 3:
        print("  /v1/prices/monthly answered 429 three times running; its part stopped.")

    routes = []
    for r in fl.get("countries") or []:
        for c in (r.get("cities") or ([r["dest"]] if r.get("dest") else []))[:3]:
            routes.append((r["iso"], c))
    print("\nPart B: %s for all %d cities of %d countries (~%d min)" % (
        " + ".join(B_VARIANTS), len(routes), len(fl.get("countries") or []),
        round(len(routes) * len(B_VARIANTS) * G_PACE / 60) + 1))
    g429 = 0
    for i, (iso, city) in enumerate(routes, 1):
        if g429 >= 3:
            print("  grouped_prices answered 429 three times running; Part B stopped at %d." % i)
            break
        rec = {"iso": iso, "city": city}
        for v in B_VARIANTS:
            rec[v] = call("/aviasales/v3/grouped_prices", dict(VARIANTS[v], origin=HUB, destination=city), pg)
            g429 = g429 + 1 if rec[v]["status"] == 429 else 0
        doc["B"].append(rec)
        if i % 50 == 0:
            print("  %d/%d" % (i, len(routes)))
            save()
    doc["meta"]["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    save()
    ok = sum(1 for r in doc["B"] if all(r[v]["status"] == 200 for v in B_VARIANTS))
    print("  %d/%d answered 200" % (ok, len(doc["B"])))
    print("\ndone. Wrote %s (no token in it). Tell Claude it finished." % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

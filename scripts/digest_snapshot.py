#!/usr/bin/env python3
"""Render the monthly digest for every month from FROZEN inputs, offline, so
two code trees can be compared byte for byte.

    /usr/bin/python3 scripts/digest_snapshot.py --root <tree> --out <file.json>
        [--variants USD|all|EUR,GBP] [--html-dir DIR] [--month N]

<tree> is any checkout of the repo (this one, or `git archive <rev> fxtracker
public | tar -x -C <dir>`): its fxtracker package and public/ data are what
get imported and read. Everything that would touch the network or the clock
is replaced through seams that exist in the old and new code alike:

  dates               picks.datetime / pricelevel.datetime: today 2026-10-03,
                      now 12:00 UTC
  rates.compute_favorability(base=...)   scripts/digest_golden/fixtures/rates_<CUR>.json
  advisories.get_advisories              .../advisories_us.json
  popularity.get_arrivals                raises: the fixed fallback popular set
  rates.fetch_json                       .../flights_<ISO>.json and flight_value_<ISO>.json
                                         by origin; any other URL raises
  flights.is_configured                  False
  picks.cover                            a deterministic fake (None for some)
  urllib.request.urlopen                 raises: a live call fails the run

The fixtures are copies, frozen on purpose: refreshing scripts/parity's own
fixtures must not move the golden output.

Writes {"USD": {"1": [subject, body], ...}, ...}. Without build_variant (an
old tree) only USD can be rendered, through picks.build().
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import types
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "digest_golden", "fixtures")
TODAY = datetime.date(2026, 10, 3)


class _Date(datetime.date):
    @classmethod
    def today(cls):
        return cls(TODAY.year, TODAY.month, TODAY.day)


class _DateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(TODAY.year, TODAY.month, TODAY.day, 12, 0, tzinfo=tz)


DATETIME_SHIM = types.SimpleNamespace(date=_Date, datetime=_DateTime,
                                      timezone=datetime.timezone, timedelta=datetime.timedelta)


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def fake_cover(query, width=1024, height=420):
    """Deterministic stand-in for the Wikipedia/Commons lookup: about one
    query in four has no usable photo, as in real life."""
    if not query:
        return None
    h = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if int(h[:2], 16) < 64:
        return None
    slug = "".join(ch if ch.isalnum() else "_" for ch in query)[:40]
    return {"url": "https://images.example/%s_%dx%d.jpg?h=%s" % (slug, width, height, h[:8]),
            "credit": {"artist": "Artist %s" % h[2:6], "license": "CC BY-SA 4.0",
                       "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
                       "page": "https://commons.wikimedia.org/wiki/File:%s.jpg" % slug}}


def _no_network(*a, **k):
    raise RuntimeError("digest_snapshot: live network call attempted: %r" % (a[:1],))


def install(root):
    """Import `root`'s fxtracker with every outside seam frozen; returns
    (picks, newsletter, variants-module-or-None)."""
    sys.path.insert(0, root)
    for m in [m for m in sys.modules if m == "fxtracker" or m.startswith("fxtracker.")]:
        del sys.modules[m]
    from fxtracker import advisories, flights, newsletter, picks, popularity, pricelevel, rates
    try:
        from fxtracker import digest_variants
    except ImportError:
        digest_variants = None
    assert os.path.realpath(picks.__file__).startswith(os.path.realpath(root)), picks.__file__

    urllib.request.urlopen = _no_network
    picks.datetime = DATETIME_SHIM
    pricelevel.datetime = DATETIME_SHIM

    def compute_favorability(baseline_days=365, threshold_pct=2.0, watch=None, base="USD"):
        return _fixture("rates_%s.json" % base)

    def get_advisories(source="us"):
        return _fixture("advisories_%s.json" % source)

    def get_arrivals():
        raise RuntimeError("popularity frozen: fallback set")

    def fetch_json(url, retries=3):
        for kind in ("flight-value", "flights"):
            pre = "/api/%s?origin=" % kind
            if pre in url:
                iso = url.split(pre, 1)[1][:2]
                return _fixture("%s_%s.json" % (kind.replace("-", "_"), iso))
        raise RuntimeError("fetch_json frozen: no fixture for %s" % url)

    rates.compute_favorability = compute_favorability
    advisories.get_advisories = get_advisories
    popularity.get_arrivals = get_arrivals
    rates.fetch_json = fetch_json
    flights.is_configured = lambda: False
    picks.cover = fake_cover
    return picks, newsletter, digest_variants


def snapshot(root, codes=("USD",), months=range(1, 13), keep_data=False):
    picks, newsletter, dv = install(root)
    out = {}
    datas = {}
    for m in months:
        if codes == ("USD",):
            # The legacy entry point, exactly as a USD-only send_digest run
            # calls it (and the only one an old tree has).
            data = picks.build(month=m)
            out.setdefault("USD", {})[str(m)] = list(newsletter.render_digest(data))
            datas.setdefault("USD", {})[m] = data
            continue
        shared = picks.gather(m)
        for c in codes:
            data = picks.build_variant(shared, dv.VARIANTS[c])
            out.setdefault(c, {})[str(m)] = list(newsletter.render_digest(data))
            datas.setdefault(c, {})[m] = data
    return (out, datas) if keep_data else out


def page(subject, body):
    """A viewable HTML page around an email body."""
    import html
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title></head><body style=\"margin:0;background:#f4f5f6\">\n%s\n</body></html>\n"
            % (html.escape(subject), body))


def digest_hashes(snap):
    return {c: {m: hashlib.sha256((sb[0] + "\n" + sb[1]).encode("utf-8")).hexdigest()
                for m, sb in sorted(per.items(), key=lambda kv: int(kv[0]))}
            for c, per in snap.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--out", required=True)
    ap.add_argument("--variants", default="USD", help="USD, all, or a comma list")
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--html-dir", default=None, help="also write <CODE>-<month>.html pages")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.variants == "all":
        sys.path.insert(0, root)
        from fxtracker.digest_variants import PICKER_ORDER
        codes = tuple(PICKER_ORDER)
    else:
        codes = tuple(c.strip().upper() for c in a.variants.split(",") if c.strip())
    months = [a.month] if a.month else range(1, 13)
    snap = snapshot(root, codes, months)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=0, sort_keys=True)
    if a.html_dir:
        os.makedirs(a.html_dir, exist_ok=True)
        for c, per in snap.items():
            for m, (subj, body) in per.items():
                with open(os.path.join(a.html_dir, "%s-%s.html" % (c, m)), "w", encoding="utf-8") as f:
                    f.write(page(subj, body))
    print("wrote %s: %s" % (a.out, ", ".join("%s x%d" % (c, len(p)) for c, p in snap.items())))


if __name__ == "__main__":
    main()

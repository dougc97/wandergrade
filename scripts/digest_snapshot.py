#!/usr/bin/env python3
"""Render the monthly digest for every month from FROZEN inputs, offline, so
a render can be pinned (the golden hashes), read back and checked against
its payload (digest_check.py), and compared with another code tree's.

    /usr/bin/python3 scripts/digest_snapshot.py --root <tree> --out <file.json>
        [--variants USD|all|EUR,GBP] [--html-dir DIR] [--month N] [--data-out <file.json>]

<tree> is any checkout of the repo (this one, or extract_code's copy of an
older commit's code): its fxtracker package and public/ data are what get
imported and read. Everything that would touch the network or the clock is
replaced through seams that exist in the old and new code alike:

  dates               picks.datetime / pricelevel.datetime: today 2026-10-03,
                      now 12:00 UTC
  rates.compute_favorability(base=...)   scripts/digest_golden/fixtures/rates_<CUR>.json
  advisories.get_advisories              .../advisories_us.json
  popularity.get_arrivals                raises: the fixed fallback popular set
  rates.fetch_json                       .../flights_<ISO>.json and flight_value_<ISO>.json
                                         by origin; any other URL raises
  flights.is_configured                  False
  picks.cover / picks.cover_file        deterministic fakes keyed on the title or
                                         the pinned file's name (None for some);
                                         cover_file only where the tree has it;
                                         snapshot(offline_covers=True) keeps the
                                         tree's own, every lookup failing on the
                                         frozen urlopen (no pick gets a cover)
  urllib.request.urlopen                 raises: a live call fails the run

The fixtures are copies, frozen on purpose: refreshing scripts/parity's own
fixtures must not move the golden output.

Writes {"USD": {"1": [subject, body], ...}, ...}. --data-out also writes the
payloads the bodies were rendered from ({"USD": {"1": {...}, ...}, ...}:
picks.build's for a USD-only run, picks.build_variant's otherwise), which is
how one tree's picks, grades, links and numbers are compared with another's
whatever either email looks like.

BASE is the commit the Dec 2026 redesign started from. The tests compare this
tree with it in two ways that don't read the body: the payloads must be equal
(test_digest_variants 1), and every Buttondown call and printed line must be
equal once each body is swapped for a token (test_send_digest 1). Until then
the tests compared bodies with commit 4788fd2's, less a list of stripped
pieces; that machinery went with the redesign (REVIEW3, COVERS, CHEAP_LINK,
the cost-line and weights grafts, the subject mapping), since a body nearly
every piece of which changed can't be compared that way. What the body says
is now checked against its own payload (digest_check.py).
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import types
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "digest_golden", "fixtures")
TODAY = datetime.date(2026, 10, 3)
# main before the Dec 2026 redesign (the tree dec/newsletter-polish was cut from).
BASE = "7a1491f"
# Fields this tree adds to a pick or gem that BASE's payload doesn't have, each
# with its reason. The payload comparison (test_digest_variants 1) sets these
# aside and nothing else, so name every one.
ADDED_FIELDS = (
    # A pick's cover at 220x168, for the compact cards (picks._banner's
    # "thumb"): the same photo as "photo" from the same image service, where
    # the cards used to load the 1024x420 banner into a 110x84 box. None on
    # a pick with no cover and on every gem, as "photo" is.
    "photo_thumb",
)


def extract_code(root, rev, dest):
    """Commit `rev`'s code (fxtracker/ and send_digest.py, from `root`'s
    repository) into the empty directory `dest`, on `root`'s data: dest/public
    is a link to root/public. The data is input, not code, so a comparison
    with `rev` shows what the code changed and nothing a data refresh did
    (as the 4788fd2 comparisons took this tree's climate.json). Raises
    RuntimeError with git's message when `rev` can't be read."""
    q = lambda x: "'" + x.replace("'", "'\\''") + "'"
    p = subprocess.run("git -C %s archive %s fxtracker send_digest.py | tar -x -C %s"
                       % (q(root), q(rev), q(dest)), shell=True, capture_output=True, text=True, timeout=50)
    if p.returncode != 0 or not os.path.isdir(os.path.join(dest, "fxtracker")):
        raise RuntimeError("git archive %s failed: %s" % (rev, (p.stderr or p.stdout).strip()))
    os.symlink(os.path.join(root, "public"), os.path.join(dest, "public"))


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
    """Deterministic stand-in for the Wikipedia/Commons lookup of a title
    (picks.cover): about one query in four has no usable photo, as in real
    life (the site's checks refuse it, or the page has none)."""
    if not query:
        return None
    h = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if int(h[:2], 16) < 64:
        return None
    slug = "".join(ch if ch.isalnum() else "_" for ch in query)[:40]
    return {"url": "https://images.example/%s_%dx%d.jpg?h=%s" % (slug, width, height, h[:8]),
            # The compact cards' small copy (picks._banner's "thumb"); BASE's
            # code doesn't read it, so its payload is the same as before.
            "thumb": "https://images.example/%s_220x168.jpg?h=%s" % (slug, h[:8]),
            "credit": {"artist": "Artist %s" % h[2:6], "license": "CC BY-SA 4.0",
                       "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
                       "page": "https://commons.wikimedia.org/wiki/File:%s.jpg" % slug}}


def fake_cover_file(name, width=1024, height=420):
    """The same for a gallery's pinned Commons file (picks.cover_file),
    keyed on "File:<name>", so a file never shares a title's answer."""
    if not name:
        return None
    return fake_cover("File:" + name, width, height)


def fake_rule_cover(a):
    """The cover the rule must pick for activities.json entry `a` under the
    fakes, worked out here rather than by the code under test: `photo` where
    there is one, then the first six gallery entries, each once; the first
    the fakes answer wins (fake_cover for a title, fake_cover_file for a
    pinned {file, label}). None when none answers."""
    seen = []
    for e in ([a["photo"]] if a.get("photo") else []) + list(a.get("gallery") or [])[:6]:
        if e in seen:
            continue
        seen.append(e)
        c = fake_cover_file(e["file"]) if isinstance(e, dict) else fake_cover(e)
        if c:
            return c
    return None


def _no_network(*a, **k):
    raise RuntimeError("digest_snapshot: live network call attempted: %r" % (a[:1],))


# The tree's own cover lookups, as install() found them before the fakes
# went in (snapshot(offline_covers=True) puts them back).
REAL_COVERS = {}


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
    REAL_COVERS.clear()
    REAL_COVERS.update(cover=picks.cover, cover_file=getattr(picks, "cover_file", None))
    picks.cover = fake_cover
    if hasattr(picks, "cover_file"):        # the cover rule's file lookup (old trees lack it)
        picks.cover_file = fake_cover_file
    return picks, newsletter, digest_variants


def snapshot(root, codes=("USD",), months=range(1, 13), keep_data=False, offline_covers=False):
    picks, newsletter, dv = install(root)
    if offline_covers:
        # The tree's own lookups on the frozen urlopen: each fails, as with
        # Wikipedia or Commons down, and no pick gets a cover.
        picks.cover = REAL_COVERS["cover"]
        if REAL_COVERS["cover_file"]:
            picks.cover_file = REAL_COVERS["cover_file"]
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
    ap.add_argument("--data-out", default=None, metavar="FILE",
                    help="also write the payloads the bodies were rendered from")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.variants == "all":
        sys.path.insert(0, root)
        from fxtracker.digest_variants import PICKER_ORDER
        codes = tuple(PICKER_ORDER)
    else:
        codes = tuple(c.strip().upper() for c in a.variants.split(",") if c.strip())
    months = [a.month] if a.month else range(1, 13)
    snap, datas = snapshot(root, codes, months, keep_data=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=0, sort_keys=True)
    if a.data_out:
        with open(a.data_out, "w", encoding="utf-8") as f:
            json.dump(datas, f, ensure_ascii=False, indent=0, sort_keys=True)
    if a.html_dir:
        os.makedirs(a.html_dir, exist_ok=True)
        for c, per in snap.items():
            for m, (subj, body) in per.items():
                with open(os.path.join(a.html_dir, "%s-%s.html" % (c, m)), "w", encoding="utf-8") as f:
                    f.write(page(subj, body))
    print("wrote %s: %s" % (a.out, ", ".join("%s x%d" % (c, len(p)) for c, p in snap.items())))


if __name__ == "__main__":
    main()

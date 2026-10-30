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
  picks.cover / picks.cover_file        deterministic fakes keyed on the title or
                                         the pinned file's name (None for some);
                                         cover_file only where the tree has it;
                                         snapshot(offline_covers=True) keeps the
                                         tree's own, every lookup failing on the
                                         frozen urlopen (no pick gets a cover)
  urllib.request.urlopen                 raises: a live call fails the run

The fixtures are copies, frozen on purpose: refreshing scripts/parity's own
fixtures must not move the golden output.

Writes {"USD": {"1": [subject, body], ...}, ...}. Without build_variant (an
old tree) only USD can be rendered, through picks.build().

--graft-cost-line <newtree> swaps <newtree>'s cost line (newsletter._cost_line
and the helpers it calls, GRAFT below) into <tree> before rendering. The
2026-10 cost-band change (the site's ±10% "about the same" band on the two
printed decimals) is the one deliberate change to the USD text; an old tree
with only that function grafted in must render byte for byte what the new
tree renders, which proves nothing else in USD moved.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
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


# newsletter.py names the cost line is built from, taken from the new tree.
GRAFT = ("PL_SAME", "_pl_shown", "_pl_band", "_cost_line")

# The USD issue's other deliberate change since 4788fd2 (2026-10-24): the line
# after the hidden gems linking the issue month's /cheapest page.
CHEAP_LINK = re.compile(
    r"<p style='font-size:14px;margin:18px 0 0;color:#111'>\U0001f4b0 <b>On a budget\?</b> "
    r"<a href='https://wandergrade\.com/cheapest/[a-z]+' style='[^']*'>The cheapest countries "
    r"to visit in [A-Za-z]+ →</a></p>")


# Review 3's USD changes (2026-10-28), one alternation per changed piece, so
# a comparison with 4788fd2 strips exactly these from both texts (as
# CHEAP_LINK is) and still proves nothing else moved:
#  src    each 🛡️ grade names whose level it is ("per US State Dept", or the
#         government that filled the gap), as the site's pills do;
#  ai     the AI callout drops the July "New:" and names the four AIs the
#         guide's button offers (either wording is stripped);
#  apos   "route’s" takes the typographic apostrophe (either is stripped);
#  year   the issue's year: an explicit --month N prints N's next occurrence
#         (render_cheapest.year_for) where 4788fd2 printed the default
#         month's, in the intro and in send_digest's "Digest for" line;
#  quote  the closing quote, which newsletter._quote_for picks by that year.
# And one change since (2026-10-29), stripped the same way:
#  btn/btnend  the two green buttons' labels sit in two spans, since
#         Buttondown's CSS turned their white text blue (newsletter.GREEN's
#         note); the spans go, the label stays.
REVIEW3 = re.compile(
    r"(?P<src> <span style='color:#888'>per (?:US State Dept|Global Affairs Canada|German Foreign Office)</span>)"
    r"|(?P<ai><div style='background:#eef7f0;border:1px solid #cfe8d6;border-radius:10px;padding:12px 14px;"
    r"margin:2px 0 18px;font-size:14px;color:#1a5e33'>✨ (?:[^<]|<b>[^<]*</b>)*</div>)"
    r"|(?P<apos>(?<=this month vs the )route['’]s(?= usual))"
    r"|(?P<year> 20\d\d(?=</b>\? WanderGrade grades| \(rates as of ))"
    r"|(?P<quote><p style=\"font-size:13px;line-height:1\.6;color:#666;font-style:italic;[^\"]*\">“[^”]*”<br>"
    r"<span style=\"font-style:normal;color:#888\">— [^<]*<i>[^<]*</i></span></p>)"
    r"|(?P<btn><span><span style=\"color:#ffffff\">)|(?P<btnend></span></span>(?=</a>))")


def without_review3(text):
    """`text` with REVIEW3's pieces taken out, and {piece: how many were}."""
    found = {}
    def cut(m):
        found[m.lastgroup] = found.get(m.lastgroup, 0) + 1
        return ""
    return REVIEW3.sub(cut, text), found


# The cover rule (2026-10-30): a pick's cover is the first photo of its guide
# gallery the site's own checks pass (picks.cover_for; activities.json `photo`
# only an optional override), where 4788fd2 looked up `photo` alone. A
# comparison with an older tree takes out of both texts each card's cover
# image (the hero's <a><img>, a compact card's thumbnail cell) and its
# "Photo:" credit line, and checks every piece taken out of this tree's (the
# link, image, alt text, file page, artist, licence and its link) against
# expected_covers.
COVERS = re.compile(
    r"(?P<hero><a href='(?P<hero_href>[^']*)'><img src='(?P<hero_src>[^']*)' width='560' "
    r"alt='(?P<hero_alt>[^']*)' "
    r"style='width:100%;max-width:560px;height:220px;object-fit:cover;display:block'></a>)"
    r"|(?P<thumb><td width='110' valign='top'><a href='(?P<thumb_href>[^']*)'><img src='(?P<thumb_src>[^']*)' "
    r"width='110' alt='(?P<thumb_alt>[^']*)' "
    r"style='width:110px;height:84px;object-fit:cover;border-radius:8px;display:block'></a></td>)"
    r"|(?P<credit><div style='font-size:11px;color:#888;margin:4px 0 0'>Photo: <a href='(?P<page>[^']*)' "
    r"style='color:#888'>(?P<artist>[^<]*)</a> &middot; "
    r"(?:<a href='(?P<lic_url>[^']*)' style='color:#888'>(?P<lic_a>[^<]*)</a>|(?P<lic_t>[^<]*))</div>)")


def without_covers(text):
    """`text` with every cover image and "Photo:" credit taken out, and the
    covers in order, one tuple a card, as the markup has them: (kind, link,
    image URL, alt, credit page, artist, licence URL or None, licence), kind
    "hero" or "thumb"; a card's credit follows its image, and a missing
    half reads None."""
    found = []
    def cut(m):
        kind = "hero" if m.group("hero") else "thumb" if m.group("thumb") else None
        if kind:
            found.append([kind, m.group(kind + "_href"), m.group(kind + "_src"), m.group(kind + "_alt")]
                         + [None] * 4)
        else:
            credit = [m.group("page"), m.group("artist"), m.group("lic_url"),
                      m.group("lic_a") if m.group("lic_url") is not None else m.group("lic_t")]
            if found and found[-1][4] is None:
                found[-1][4:] = credit
            else:
                found.append([None] * 4 + credit)
        return ""
    return COVERS.sub(cut, text), [tuple(f) for f in found]


def expected_covers(root, picks_, link):
    """The covers the rule must give `picks_` (build data's picks, in order,
    the first on the hero card) under the fakes, from `root`'s
    activities.json, as without_covers reads them: the card's guide link
    (link(iso), the URL its name links to), the image, the country's name
    as alt text and the whole credit, each as newsletter prints it (the
    link and image as they are, the rest escaped). Picks the fakes give no
    photo print none."""
    import html
    with open(os.path.join(root, "public", "activities.json"), encoding="utf-8") as f:
        acts = json.load(f)
    out = []
    for i, s_ in enumerate(picks_):
        c = fake_rule_cover(acts.get(s_["iso"], {}))
        if c:
            cr = c["credit"]
            out.append(("hero" if i == 0 else "thumb", link(s_["iso"]), c["url"], html.escape(s_["name"]),
                        html.escape(cr["page"]), html.escape(cr["artist"]),
                        html.escape(cr["license_url"]) if cr.get("license_url") else None,
                        html.escape(cr["license"])))
    return out


def without_cheap_link(per_month):
    """{month: [subject, body]} with that line taken out of each body, and
    True when every body carried it exactly once."""
    out, once = {}, True
    for m, (subj, body) in per_month.items():
        body, n = CHEAP_LINK.subn("", body)
        once = once and n == 1
        out[m] = [subj, body]
    return out, once


def graft_cost_line(newsletter, new_root):
    """Replace `newsletter`'s _cost_line (an old tree's module) with
    new_root's, plus the helpers and constant it uses, and its picks.WEIGHTS
    with new_root's (the default priorities). The new function's
    default edition is USD from new_root's digest_variants (stdlib only), and
    `decimal` is imported into the old module's namespace for it."""
    import ast
    import importlib.util
    src_path = os.path.join(new_root, "fxtracker", "newsletter.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    keep = []
    for node in tree.body:
        names = ([node.name] if isinstance(node, ast.FunctionDef)
                 else [t.id for t in node.targets if isinstance(t, ast.Name)]
                 if isinstance(node, ast.Assign) else [])
        if any(n in GRAFT for n in names):
            keep.append(node)
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in keep}
    assert found == set(GRAFT), "graft: %s lacks %s" % (src_path, set(GRAFT) - found)
    spec = importlib.util.spec_from_file_location(
        "_graft_dv", os.path.join(new_root, "fxtracker", "digest_variants.py"))
    dv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dv)
    ns = newsletter.__dict__
    import decimal
    ns.setdefault("decimal", decimal)
    ns["USD"] = dv.VARIANTS["USD"]      # the new code's default edition (old trees have none)
    mod = ast.Module(body=keep, type_ignores=[])
    exec(compile(mod, src_path, "exec"), ns)
    graft_weights(newsletter, new_root)


def graft_weights(newsletter, new_root):
    """The deliberate scoring changes since 4788fd2, both 2026-10-14: the
    default priorities (every factor Med; affordability was High) and the
    tie rule (a tie on the shown score breaks on the unrounded one, then the
    name, where list order used to decide). The old tree scores with
    new_root's picks.WEIGHTS and ranks with that tie rule — its picks.py
    re-run with the two lines swapped — so a comparison against it still
    isolates everything else (alone: --graft-weights, the raw-text check)."""
    import ast
    old_picks = sys.modules.get((newsletter.__package__ or "fxtracker") + ".picks")
    if old_picks is not None and '"raw": num / den' not in open(old_picks.__file__, encoding="utf-8").read():
        # Only the two functions are redefined, in the old module's own
        # namespace: re-running the whole file undid install()'s frozen seams.
        with open(old_picks.__file__, encoding="utf-8") as f:
            src = f.read()
        swaps = (('"value": value, "advLvl": adv,', '"value": value, "advLvl": adv, "raw": num / den if den else 0,'),
                 ('scored.sort(key=lambda s: s["value"], reverse=True)',
                  'scored.sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))'))
        tree = ast.parse(src)
        for a, b in swaps:
            fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and a in (ast.get_source_segment(src, n) or "")]
            assert len(fns) == 1, "graft: %s lacks %r" % (old_picks.__file__, a)
            fn_src = ast.get_source_segment(src, fns[0]).replace(a, b)
            exec(compile("\n" * (fns[0].lineno - 1) + fn_src, old_picks.__file__, "exec"), old_picks.__dict__)
    with open(os.path.join(new_root, "fxtracker", "picks.py"), encoding="utf-8") as f:
        ptree = ast.parse(f.read())
    weights = next(ast.literal_eval(n.value) for n in ptree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "WEIGHTS" for t in n.targets))
    old_picks = sys.modules.get((newsletter.__package__ or "fxtracker") + ".picks")
    if old_picks is not None:
        old_picks.WEIGHTS = dict(weights)


def snapshot(root, codes=("USD",), months=range(1, 13), keep_data=False, graft=None, weights=None,
             offline_covers=False):
    picks, newsletter, dv = install(root)
    if offline_covers:
        # The tree's own lookups on the frozen urlopen: each fails, as with
        # Wikipedia or Commons down, and no pick gets a cover.
        picks.cover = REAL_COVERS["cover"]
        if REAL_COVERS["cover_file"]:
            picks.cover_file = REAL_COVERS["cover_file"]
    if graft:
        graft_cost_line(newsletter, graft)
    elif weights:
        graft_weights(newsletter, weights)
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
    ap.add_argument("--graft-cost-line", default=None, metavar="NEWTREE",
                    help="render with NEWTREE's newsletter._cost_line and picks.WEIGHTS (see the docstring)")
    ap.add_argument("--graft-weights", default=None, metavar="NEWTREE",
                    help="render with only NEWTREE's picks.WEIGHTS (the default priorities)")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.variants == "all":
        sys.path.insert(0, root)
        from fxtracker.digest_variants import PICKER_ORDER
        codes = tuple(PICKER_ORDER)
    else:
        codes = tuple(c.strip().upper() for c in a.variants.split(",") if c.strip())
    months = [a.month] if a.month else range(1, 13)
    snap = snapshot(root, codes, months,
                    graft=os.path.abspath(a.graft_cost_line) if a.graft_cost_line else None,
                    weights=os.path.abspath(a.graft_weights) if a.graft_weights else None)
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

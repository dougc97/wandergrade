"""The two cross-country list pages, /safe-and-cheap and /do-not-travel, as
pure functions: the cached documents in, a whole page body plus its <title>,
description and sitemap lastmod out. Nothing here reads the network or the
server's caches, so scripts/test_list_pages.py renders them from hand-made
fixtures.

Both pages are server-rendered text only (no app.js), because their whole
point is to be crawlable: the site's moat words — three governments side by
side, each in its own words, a numeric rule, a dated snapshot — had no
crawlable home until now (the Safety table is built client-side).

Every number on a page is computed here from the documents handed in, never
typed into the copy: the counts in the intro, the rows, the as-of dates.
When a document is missing (an advisory feed down with nothing cached), the
page still renders, says so, and reports `degraded` so the server sends it
with no-store rather than letting Cloudflare keep a thinner copy for 5 min.

Class names: nothing beginning ad/adv/sponsor/banner/promo or containing
"advert" — EasyList once hid the site's advisory text on those. The level
pills reuse styles.css's .lvl/.lvlN; everything else is .listpage-*.
"""

import datetime
import html
import json
import os
import re

from . import advhistory, pricelevel
from . import render_guide as rg
from .advisories import SOURCES
from .picks import CUR_BY_ISO

SITE = rg.SITE
PUBLIC = rg.PUBLIC

# The rules, stated once so the page copy and the membership can't disagree.
SAFE_PCT = 60          # local prices at or under this % of the US
SAFE_US_LEVEL = 1      # and the US State Department's lowest level
NEAR_PCT = 50          # "Nearly made it": US Level 2 and prices under this
# Level changes older than this are history, not news (advhistory's own window).
RECENT_DAYS = advhistory.WINDOW_DAYS

# Each government in the order the site's footer credits them (not US first:
# the safety source follows the traveller's home country).
GOVS = ("us", "ca", "de")
GOV_SHORT = rg.ADV_SRC_SHORT
# The cell label on a phone, where the row is a card (the table header, shown
# from 900px, carries the full name): "Canada: Avoid all travel".
GOV_LABEL = {"us": "US", "ca": "Canada", "de": "Germany"}
GOV_FLAG = {"us": "🇺🇸", "ca": "🇨🇦", "de": "🇩🇪"}
# Germany's feed is binary (Reisewarnung / Teilreisewarnung / nothing), so its
# "avoid non-essential travel" rung doesn't exist: the Level 3 table shows its
# word for the country anyway, which is the point of the comparison.
LOWEST = {"us": 1, "ca": 1, "de": 1}

TITLE_MAX = 60
DESC_MAX = 157

_clim = None


def climate():
    """public/climate.json, read once: best months per ISO (and whether they
    are hand-curated or the best-weather months). The file only changes on
    deploy, so one read per process is right."""
    global _clim
    if _clim is None:
        with open(os.path.join(PUBLIC, "climate.json"), encoding="utf-8") as f:
            _clim = json.load(f)
    return _clim


def own_by_iso(payload):
    """{ISO: item} for a government's OWN ratings — a gap-fill from another
    government ("via") is that government's call and is read from its own
    list. Two rows for one ISO (Gaza and the West Bank are both PS): the most
    cautious wins, as everywhere else on the site."""
    out = {}
    for it in ((payload or {}).get("items") or []):
        iso = it.get("iso")
        if not iso or it.get("via") or not isinstance(it.get("level"), int):
            continue
        if iso not in out or it["level"] > out[iso]["level"]:
            out[iso] = it
    return out


def _day(d):
    """'2026-09-28' -> '28 Sep 2026': day-month-year, for a page read from
    anywhere. Empty on anything that isn't a date."""
    try:
        x = datetime.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return ""
    return "%d %s %d" % (x.day, rg.MON[x.month - 1], x.year)


def _fetched(fetched, src):
    """'6 Oct 2026 14:02 UTC' for a cache timestamp (epoch seconds), or ''."""
    ts = (fetched or {}).get(src)
    if not ts:
        return ""
    try:
        t = datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return ""
    return "%d %s %d %02d:%02d UTC" % (t.day, rg.MON[t.month - 1], t.year, t.hour, t.minute)


def _year(today):
    return str(today or datetime.date.today().isoformat())[:4]


_slug_of = None


def _slug(iso):
    global _slug_of
    if _slug_of is None:
        _slug_of = {iso: slug for slug, iso in rg.all_slugs()}
    return _slug_of.get(iso)


def _name(iso, *items):
    """The country's name as the guides spell it, else the first feed's own
    name (the German feed's is German, so it comes last in the call)."""
    nm = rg.name_for_iso(iso)
    if nm:
        return nm
    for it in items:
        if it and it.get("country"):
            return it["country"]
    return iso


def _country(iso, name):
    """Flag and name, linked to its guide where one exists."""
    nm = html.escape(name)
    link = ('<a href="/guide/%s">%s</a>' % (_slug(iso), nm)) if _slug(iso) else nm
    return "%s %s" % (rg.flag_emoji(iso), link)


def _country_cell(iso, name, extra=""):
    return '<td class="name" data-l="Country">%s%s</td>' % (_country(iso, name), extra)


def _cell(label, inner, attrs=""):
    """A labelled cell: on a phone the label is drawn from data-l and the
    value sits beside it as ONE flex item (.v), so a pill, its date and a
    row of chips wrap inside the value instead of each becoming a column."""
    return '<td data-l="%s"%s><span class="v">%s</span></td>' % (html.escape(label, quote=True), attrs, inner)


def _pill(src, it, missing="no rating"):
    """A government's level in its own words, as the site's level pill, with
    the feed's full phrase in the tooltip. `it` None: the government publishes
    no rating for the country (not the same as its feed being down)."""
    if not it:
        return '<span class="lvl none">%s</span>' % html.escape(missing)
    lvl = it["level"]
    return '<span class="lvl lvl%d" title="%s">%s</span>' % (
        lvl, html.escape(it.get("level_text") or "", quote=True), html.escape(rg.lvl_words(src, lvl)))


def _when(it):
    """The dated part of a government's cell: the feed's own date, and the
    date WanderGrade's record saw the level arrive (advhistory's `changed`)
    with the direction. Canada's feed carries no date in the payload, so its
    cell shows only a recorded change."""
    if not it:
        return ""
    bits = []
    if it.get("updated"):
        bits.append(html.escape(_day(it["updated"])))
    if it.get("changed"):
        arrow = {"up": "↑ ", "down": "↓ "}.get(it.get("change") or "", "")
        bits.append("%ssince %s" % (arrow, html.escape(_day(it["changed"]))))
    elif it.get("change") and it.get("updated"):
        # The US feed's own words ("The advisory level was increased to 3"),
        # dated by its publish date — the only change a feed reports itself.
        bits.append({"up": "raised", "down": "lowered"}[it["change"]])
    return ('<span class="when">%s</span>' % " · ".join(bits)) if bits else ""


def _gov_cell(src, it, missing="no rating"):
    return _cell(GOV_LABEL[src], _pill(src, it, missing) + _when(it))


def _chips(words, cls="risk", title=None):
    """Short labels in a row; `title` (the sentence they were read from) on
    the row, once, not on every chip."""
    if not words:
        return ""
    t = (' title="%s"' % html.escape(title, quote=True)) if title else ""
    return '<span class="chips"%s>%s</span>' % (t, "".join(
        '<span class="%s">%s</span>' % (cls, html.escape(w)) for w in words))


def _months(c):
    """The country's best months as the guide claims them: "best months to
    visit" only where they are hand-curated, otherwise the best-weather months
    — SSR must never assert more than the guide does."""
    best = [m for m in (c or {}).get("best") or [] if 1 <= m <= 12]
    if not best:
        return ""
    txt = rg._months_ranges(best)
    return txt if c.get("curated") else "weather: " + txt


def _fit(variants, limit):
    """The first variant that fits, else the last one clipped at a word."""
    for v in variants:
        if len(v) <= limit:
            return v
    return rg._clip(variants[-1], limit)


def _page(h1, lede, body, notes, sources):
    """One page body: a single h1, the rule or counts as the lede, the
    sections, footnotes, then the dated sources. Minimal copy by design — the
    tables do the talking, the rest is in tooltips (title attributes: these
    pages carry no JavaScript)."""
    return ('<div class="listpage"><h1>%s</h1><p class="lede">%s</p>%s%s'
            '<p class="asof">%s</p></div>'
            % (h1, lede, body,
               "".join('<p class="note">%s</p>' % n for n in notes if n),
               sources))


def _missing_note(missing):
    if not missing:
        return ""
    return ("%s %s not available right now, so its column reads “not loaded”: "
            "this page is served uncached until it is back."
            % (" and ".join(html.escape(SOURCES[s]) for s in missing),
               "feed is" if len(missing) == 1 else "feeds are"))


def _sources_line(fetched, own, facts_asof=None, health_built=None):
    parts = []
    if facts_asof:
        parts.append("Prices: WanderGrade's daily snapshot as of %s (World Bank PPP carried "
                     "forward for inflation, at that day's exchange rates)" % html.escape(_day(facts_asof)))
    for src in GOVS:
        items = own.get(src)
        if items is None:
            parts.append("%s: not loaded" % html.escape(SOURCES[src]))
            continue
        newest = max((it.get("updated") or "" for it in items.values()), default="")
        bits = [html.escape(SOURCES[src])]
        f = _fetched(fetched, src)
        if f:
            bits.append("fetched " + html.escape(f))
        if newest:
            bits.append("newest advisory dated " + html.escape(_day(newest)))
        parts.append(": ".join(bits[:1] + [", ".join(bits[1:])]) if len(bits) > 1 else bits[0])
    if health_built:
        parts.append("Health notes: Government of Canada (Public Health Agency of Canada), "
                     "as of %s" % html.escape(_day(health_built)))
    return " · ".join(parts) + "."


def lastmod_of(*dates):
    """The newest well-formed date among `dates`, or ''."""
    ok = [str(d)[:10] for d in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d or "")[:10])]
    return max(ok) if ok else ""


def newest_change(payloads):
    """The newest level-change date the payloads ({source: payload or None})
    carry, or '': the /do-not-travel sitemap lastmod, never "today"."""
    own = {s: own_by_iso(p) for s, p in payloads.items() if p is not None}
    return lastmod_of(*[c[0] for c in recent_changes(own)])


# ---- /safe-and-cheap -------------------------------------------------------------

def real_fx(iso, fx, ppp):
    """The dollar's inflation-adjusted move against the country's currency vs
    its one-year average, in % (pricelevel.real_fx_pct, the figure the
    Currency tab shows), or None when the rates aren't cached, the currency
    is unknown, or inflation makes the real figure dishonest."""
    if not fx or not ppp:
        return None
    cur = CUR_BY_ISO.get(iso)
    nominal = fx.get(cur) if cur else None
    if nominal is None:
        return None
    try:
        return pricelevel.real_fx_pct(float(nominal), iso, "US", ppp)
    except (TypeError, ValueError, KeyError):
        return None


def _fx_cell(real):
    if real is None:
        return "—"
    return "%+.1f%%" % real


def safe_rows(us, facts):
    """[(pct, iso)] for the rule: the US's own Level 1 and pct <= SAFE_PCT, by
    price. Only guides (the facts document's entries), never a subdivision
    (England, Scotland and Wales carry the UK's figures and aren't countries)."""
    rows = []
    for iso, f in (facts or {}).items():
        if iso.startswith("_") or "-" in iso or not isinstance(f, dict):
            continue
        pct = f.get("pct")
        it = us.get(iso)
        if pct is None or not it or it["level"] != SAFE_US_LEVEL or pct > SAFE_PCT:
            continue
        rows.append((pct, iso))
    return sorted(rows, key=lambda r: (r[0], _name(r[1])))


def near_rows(us, facts):
    """[(pct, iso)]: US Level 2 and prices under NEAR_PCT — the cheap places
    one government's "increased caution" keeps off the list above."""
    rows = []
    for iso, f in (facts or {}).items():
        if iso.startswith("_") or "-" in iso or not isinstance(f, dict):
            continue
        pct = f.get("pct")
        it = us.get(iso)
        if pct is None or not it or it["level"] != 2 or pct >= NEAR_PCT:
            continue
        rows.append((pct, iso))
    return sorted(rows, key=lambda r: (r[0], _name(r[1])))


def safe_and_cheap(us, ca, de, facts, clim, health, pl_history, fetched=None, fx=None, ppp=None,
                   today=None):
    """The /safe-and-cheap page. `us`/`ca`/`de` are /api/advisories payloads
    (None when that feed is unavailable); `facts` the guide-facts document;
    `clim` climate.json; `health` the health document; `pl_history` the
    price-level history (its "alt" list is the alternative-rate footnote);
    `fetched` {source: epoch} cache times; `fx` {currency: strength_pct} from
    the cached /api/rates rows and `ppp` the PPP table, both optional (the
    column is left out without them, never shown as a row of dashes).

    Without the US feed there is no rule to apply: the US level in the facts
    document (the daily snapshot, src "us") stands in, dated as such."""
    today = today or datetime.date.today().isoformat()
    facts = facts or {}
    year = _year(today)
    notes, missing = [], [s for s, p in (("us", us), ("ca", ca), ("de", de)) if p is None]
    own = {s: (own_by_iso(p) if p is not None else None) for s, p in (("us", us), ("ca", ca), ("de", de))}
    us_own = own["us"]
    if us_own is None:
        # The snapshot's US levels: same source, up to a day older.
        us_own = {iso: {"level": f["adv"], "level_text": ""} for iso, f in facts.items()
                  if isinstance(f, dict) and f.get("src") == "us" and isinstance(f.get("adv"), int)}
        notes.append("The US State Department feed is not available right now: the US levels are "
                     "from WanderGrade's daily snapshot of %s. This page is served uncached until "
                     "the feed is back." % html.escape(_day(facts.get("_asof"))))
    ca_own, de_own = own["ca"] or {}, own["de"] or {}
    alt = set((pl_history or {}).get("alt") or [])
    hc = (health or {}).get("c") or {}

    rows = safe_rows(us_own, facts)
    agree = [iso for _p, iso in rows
             if (ca_own.get(iso) or {}).get("level") == LOWEST["ca"]
             and (de_own.get(iso) or {}).get("level") == LOWEST["de"]]
    near = near_rows(us_own, facts)
    show_fx = bool(fx and ppp)
    alt_used = False

    def row(n, pct, iso, nearly=False):
        nonlocal alt_used
        f = facts.get(iso) or {}
        mark = ""
        if iso in agree:
            mark = (' <span class="agree" title="Canada and Germany are also at their lowest level">'
                    "✓ all three agree</span>")
        pct_txt = "%d%%" % pct
        if iso in alt:
            alt_used = True
            pct_txt += '<sup class="fn">†</sup>'
        cells = [_country_cell(iso, _name(iso), mark),
                 _cell("Prices vs US", pct_txt,
                       ' title="%s"' % html.escape((f.get("band") or "").capitalize(), quote=True))]
        if nearly:
            it = us_own.get(iso) or {}
            cells.append(_cell("US", _pill("us", it) + _chips(it.get("risks") or [], title=it.get("summary") or None)))
        else:
            cells.append(_gov_cell("us", us_own.get(iso)))
        cells.append(_gov_cell("ca", ca_own.get(iso), "not loaded" if "ca" in missing else "no rating"))
        cells.append(_gov_cell("de", de_own.get(iso), "not loaded" if "de" in missing else "no rating"))
        if show_fx and not nearly:
            cells.append(_cell("Dollar vs 1-yr avg", _fx_cell(real_fx(iso, fx, ppp))))
        cells.append(_cell("Best months", html.escape(_months((clim or {}).get(iso))) or "—"))
        if not nearly:
            h = hc.get(iso)
            if h is None:
                cells.append(_cell("Health notes", "—"))
            elif not h.get("h"):
                cells.append(_cell("Health notes", "only the usual"))
            else:
                areas = set(h.get("a") or [])
                cells.append(_cell("Health notes", '<span class="chips">%s</span>' % "".join(
                    '<span class="hnote"%s>%s%s</span>'
                    % (' title="in certain areas"' if w in areas else "", html.escape(w), "*" if w in areas else "")
                    for w in h["h"])))
        return '<tr><td class="num" data-l="#">%d</td>%s</tr>' % (n, "".join(cells))

    head = ["#", "Country", "Prices vs US", "US State Dept", "Global Affairs Canada", "German Foreign Office"]
    if show_fx:
        head.append("Dollar vs 1-yr avg")
    head += ["Best months", "Health notes"]
    table = ('<div class="listbox"><table class="listtable"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
             % ("".join("<th>%s</th>" % html.escape(h) for h in head),
                "".join(row(i + 1, p, iso) for i, (p, iso) in enumerate(rows))
                or '<tr><td class="name" data-l="Country">No country meets the rule today.</td></tr>'))
    near_head = ["#", "Country", "Prices vs US", "US State Dept", "Global Affairs Canada",
                 "German Foreign Office", "Best months"]
    near_table = ('<div class="listbox"><table class="listtable"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                  % ("".join("<th>%s</th>" % html.escape(h) for h in near_head),
                     "".join(row(i + 1, p, iso, nearly=True) for i, (p, iso) in enumerate(near))
                     or '<tr><td class="name" data-l="Country">None today.</td></tr>'))

    lede = ("The rule: <strong>US State Department Level %d</strong> (“exercise normal precautions”) "
            "and <strong>local prices at or under %d%% of the US</strong>. <strong>%d</strong> countries "
            "qualify today, cheapest first; <strong>%d</strong> of them are also at the lowest level for "
            "Canada and Germany." % (SAFE_US_LEVEL, SAFE_PCT, len(rows), len(agree)))
    body = table
    body += ('<h2>Nearly made it: cheap, but US Level 2</h2>'
             '<p class="sub"><strong>%d</strong> countries under %d%% of US prices where the State Department '
             "says “exercise increased caution”, with its reasons.</p>%s" % (len(near), NEAR_PCT, near_table))
    if alt_used:
        notes.append("† priced on the alternative rate basis: the market exchange rate, not the official one.")
    notes.append("Prices are national averages vs the US (100%%), from World Bank PPP at the snapshot's "
                 "exchange rates. Best months: the guide's hand-picked months, or the best-weather months "
                 "where it has none. Health notes are Canada's risk-to-travellers list (* in certain areas).%s"
                 % (" Dollar vs 1-yr avg: how much further a US dollar goes there than its one-year average, "
                    "after local and US inflation." if show_fx else ""))
    notes.append(_missing_note(missing))
    body += ('<p class="xlink">See also: <a href="/do-not-travel">the Do Not Travel list, US, Canada and '
             'Germany compared</a> · <a href="/data">the price-level dataset</a>.</p>')
    sources = _sources_line(fetched, own, facts.get("_asof"), (health or {}).get("built"))
    h1 = "Safest cheap countries to visit in %s" % year
    title = _fit(["Safest Cheap Countries to Visit in %s (Data, Not Opinion)" % year,
                  "Safest Cheap Countries to Visit in %s (Data)" % year], TITLE_MAX)
    desc = _fit(["%d countries at US State Dept Level 1 with prices at or under %d%% of the US, cheapest "
                 "first, with Canada's and Germany's levels, best months and health notes. As of %s."
                 % (len(rows), SAFE_PCT, _day(facts.get("_asof")) or _day(today)),
                 "%d countries at US Level 1 with prices at or under %d%% of the US, with Canada's and "
                 "Germany's levels, best months and health notes. As of %s."
                 % (len(rows), SAFE_PCT, _day(facts.get("_asof")) or _day(today))], DESC_MAX)
    return {
        "path": "/safe-and-cheap",
        "title": title, "desc": desc, "h1": h1,
        "html": _page(html.escape(h1), lede, body, notes, sources),
        # The day the page's data last changed: the snapshot's own date.
        "lastmod": lastmod_of(facts.get("_asof")),
        "degraded": bool(missing),
        "counts": {"safe": len(rows), "agree": len(agree), "near": len(near)},
        "isos": {"safe": [i for _p, i in rows], "agree": agree, "near": [i for _p, i in near]},
    }


# ---- /do-not-travel --------------------------------------------------------------

def recent_changes(own, today=None):
    """[(date, iso, src, direction, level)] newest first, within RECENT_DAYS of
    today: the level changes WanderGrade's own record saw (advhistory's
    `changed`), plus the ones the US feed reports in words with its publish
    date (the only feed that says so itself)."""
    out = []
    for src in GOVS:
        for iso, it in (own.get(src) or {}).items():
            if it.get("changed"):
                out.append((str(it["changed"])[:10], iso, src, it.get("change") or "", it["level"]))
            elif src == "us" and it.get("change") and it.get("updated"):
                out.append((str(it["updated"])[:10], iso, src, it["change"], it["level"]))
    if today:
        try:
            floor = (datetime.date.fromisoformat(str(today)[:10])
                     - datetime.timedelta(days=RECENT_DAYS)).isoformat()
            out = [c for c in out if c[0] >= floor]
        except ValueError:
            pass
    return sorted(out, key=lambda c: (c[0], _name(c[1])), reverse=True)


def level4_sets(own):
    """(all three, one or two, level 3) as sorted ISO lists.
    all three: each government's own rating is its top level;
    one or two: top level for at least one, not all three;
    level 3: Reconsider travel (US) or Avoid non-essential travel (Canada),
             and no government at its top level (Germany has no Level 3)."""
    us, ca, de = (own.get(s) or {} for s in GOVS)
    four = {iso for d in (us, ca, de) for iso, it in d.items() if it["level"] == 4}
    all3 = sorted(iso for iso in four if all((d.get(iso) or {}).get("level") == 4 for d in (us, ca, de)))
    some = sorted(iso for iso in four if iso not in all3)
    three = sorted(iso for d in (us, ca) for iso, it in d.items() if it["level"] == 3 and iso not in four)
    return all3, some, sorted(set(three))


def do_not_travel(us, ca, de, fetched=None, today=None):
    """The /do-not-travel page from the three /api/advisories payloads (None
    for a feed that is unavailable: its column reads "not loaded", the page
    says so and reports `degraded`)."""
    today = today or datetime.date.today().isoformat()
    year = _year(today)
    missing = [s for s, p in (("us", us), ("ca", ca), ("de", de)) if p is None]
    own = {s: (own_by_iso(p) if p is not None else None) for s, p in (("us", us), ("ca", ca), ("de", de))}
    all3, some, three = level4_sets(own)
    changes = recent_changes(own, today)

    def nm(iso):
        return _name(iso, (own["us"] or {}).get(iso), (own["ca"] or {}).get(iso), (own["de"] or {}).get(iso))

    def row(iso):
        us_it = (own["us"] or {}).get(iso)
        cells = [_country_cell(iso, nm(iso))]
        for src in GOVS:
            cells.append(_gov_cell(src, (own[src] or {}).get(iso), "not loaded" if src in missing else "no rating"))
        risks = (us_it or {}).get("risks") or []
        cells.append(_cell("US reasons", _chips(risks, title=(us_it or {}).get("summary") or None) or "—"))
        return "<tr>%s</tr>" % "".join(cells)

    def table(isos, empty):
        head = ["Country", "US State Dept", "Global Affairs Canada", "German Foreign Office", "US reasons"]
        return ('<div class="listbox"><table class="listtable"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                % ("".join("<th>%s</th>" % h for h in head),
                   "".join(row(i) for i in sorted(isos, key=nm))
                   or '<tr><td class="name" data-l="Country">%s</td></tr>' % empty))

    if changes:
        items = []
        for date, iso, src, direction, level in changes:
            it = (own[src] or {}).get(iso) or {}
            verb = {"up": "raised to", "down": "lowered to"}.get(direction, "now")
            items.append('<li><span class="when">%s</span> <span class="name">%s</span> %s: %s %s</li>' % (
                html.escape(_day(date)), _country(iso, nm(iso)),
                html.escape(GOV_SHORT[src]), html.escape(verb), _pill(src, it)))
        recent = '<ul class="changes">%s</ul>' % "".join(items)
    else:
        recent = ('<p class="sub">No level changes in the last %d days in the three feeds, by WanderGrade\'s '
                  'own record.</p>' % RECENT_DAYS)

    n_any = len(all3) + len(some)
    lede = ("<strong>%d</strong> countries are “do not travel” for at least one of the three governments "
            "WanderGrade follows: <strong>%d</strong> for all three, <strong>%d</strong> for one or two. "
            "A further <strong>%d</strong> are “reconsider travel” for the US or “avoid non-essential "
            "travel” for Canada. Each in the government's own words, with its date and reasons."
            % (n_any, len(all3), len(some), len(three)))
    body = ("<h2>Recent changes</h2>%s"
            "<h2>Do not travel: all three governments agree (%d)</h2>%s"
            "<h2>Do not travel for one or two governments (%d)</h2>"
            '<p class="sub">Where the governments disagree — the comparison no single list shows.</p>%s'
            "<h2>Reconsider travel / avoid non-essential travel (%d)</h2>"
            '<p class="sub">Germany publishes no middle level: it either warns or doesn\'t.</p>%s'
            % (recent, len(all3), table(all3, "None today."), len(some),
               table(some, "None today."), len(three), table(three, "None today.")))
    body += ('<p class="xlink">See also: <a href="/safe-and-cheap">the safest cheap countries, by the same '
             'three governments</a>.</p>')
    notes = ["Levels are each government's own; the pill's tooltip quotes its phrase. Dates: the feed's own "
             "date where it publishes one, and “since” when WanderGrade's record saw the level change "
             "(↑ raised, ↓ lowered). US reasons are the State Department's “due to” clause.",
             _missing_note(missing)]
    sources = _sources_line(fetched, own)
    h1 = "Do not travel list %s: US, Canada and Germany compared" % year
    title = _fit(["Do Not Travel List %s: US, Canada & Germany Compared" % year], TITLE_MAX)
    desc = _fit(["%d countries rated do not travel by the US, Canada or Germany, %d by all three, each in "
                 "the government's own words with dates and reasons, plus the Level 3 list. %s."
                 % (n_any, len(all3), _day(today)),
                 "%d countries rated do not travel by the US, Canada or Germany (%d by all three), in each "
                 "government's own words, with dates and reasons." % (n_any, len(all3))], DESC_MAX)
    return {
        "path": "/do-not-travel",
        "title": title, "desc": desc, "h1": h1,
        "html": _page(html.escape(h1), lede, body, notes, sources),
        # The newest change the payloads carry (never today): a feed-reported
        # or recorded level change. The server floors it at the content stamp.
        "lastmod": lastmod_of(*[c[0] for c in recent_changes(own)]),
        "degraded": bool(missing),
        "counts": {"any4": n_any, "all3": len(all3), "some4": len(some), "l3": len(three),
                   "changes": len(changes)},
        "isos": {"all3": all3, "some4": some, "l3": three},
    }

"""/cheapest/<month> (12 pages, january ... december) and the /cheapest hub:
the cheapest countries to visit in each month for a traveller from the US,
as pure functions — the cached documents in, the 13 pages out — in the
shell and look of the list pages (fxtracker/render_lists.py, whose helpers
this reuses). Nothing here reads the network or the server's caches, so
scripts/test_cheapest_pages.py renders them from fixtures.

One computation decides everything on a row: picks._score, the port of
app.js valueScores that the newsletter and the parity harness hold to the
site, run exactly as picks.build_variant runs the US edition (US origin, the
cached USD /api/rates rows for prices and the dollar's move, the US list's
levels with its gap-fills, fare_context plus the flight-value curves). The
grade, the score, the price figure and the rule's 50% all come from that one
result, ranked as build_variant ranks (score, then the unrounded score, then
the name), so a month's page agrees with Top Picks for that month with From
set to the US.

The rule, stated once here and printed on every page from these constants:
  * the US State Department's own rating is Level 1 or 2 (a gap-fill from
    Canada or Germany is their call, not the State Department's);
  * no government of the three rates the country Level 4 in its own list
    (advisories.dnt_for with guide_sizers.ADV_PARENT: the guides' stays
    rule, whoever the reader follows);
  * local prices at or under MAX_PCT % of the US, the whole-percent figure
    the page prints;
  * a weather score of MIN_WX or more that month (public/climate.json);
  * a country with a guide, never a subdivision; unrated is out (_score).

A page whose inputs are incomplete still renders, says what is missing and
reports `degraded`, so the server sends it with no-store.
"""

import datetime
import html

from . import advisories, flightvalue, geo, picks, pricelevel
from . import render_guide as rg
from . import render_lists as RL
from .advisories import SOURCES
from .guide_sizers import ADV_PARENT

SLUGS = ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december")
HUB = "/cheapest"
PATHS = (HUB,) + tuple("%s/%s" % (HUB, s) for s in SLUGS)

# The rule (see the module docstring).
US_LEVELS = (1, 2)
MAX_PCT = 50
MIN_WX = 70
HOME_ISO = "US"
HOME_CUR = "USD"
# The State Department's own words for the two levels the rule admits.
US_WORDS = {1: "Exercise normal precautions", 2: "Exercise increased caution"}
HUB_TOP = 3

TITLE_MAX = RL.TITLE_MAX
DESC_MAX = RL.DESC_MAX
FV_WORD = {"low": "Low", "typical": "Typical", "high": "High"}   # app.js FV_WORD


def path_for(month):
    return "%s/%s" % (HUB, SLUGS[month - 1])


def month_of(path):
    """1-12 for a month page's exact path, else None (the hub, a 404)."""
    for i, s in enumerate(SLUGS):
        if path == "%s/%s" % (HUB, s):
            return i + 1
    return None


def _date(today):
    if isinstance(today, datetime.date):
        return today
    try:
        return datetime.date.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return datetime.datetime.now(datetime.timezone.utc).date()


def year_for(month, today):
    """The month's next occurrence, this month counted: in October 2026,
    October and November are 2026 and September is 2027 — the same rule as
    the flight curves' months (flightvalue.window_months, picks.month_fare)."""
    t = _date(today)
    return t.year if month >= t.month else t.year + 1


def month_order(today):
    """1-12 starting at this month: the hub's rows, soonest first."""
    m = _date(today).month
    return [(m - 1 + i) % 12 + 1 for i in range(12)]


_cent = None


def centroids():
    """app.js countryCentroids, from the committed world.geojson, once."""
    global _cent
    if _cent is None:
        _cent = geo.country_centroids()
    return _cent


def _f(c):
    return pricelevel.js_round(c * 9 / 5 + 32)   # app.js fmtTemp


def _money(p):
    return "$" + format(int(p), ",")


# ---- the computation ---------------------------------------------------------

def context(us, ca, de, rates, ppp, clim, facts, flights=None, fv=None, cent=None):
    """What every month shares: the scorer's inputs as build_variant builds
    them for the US edition, the three governments' own levels, and what is
    missing. `us`/`ca`/`de` are /api/advisories payloads (None: not in hand);
    `rates` the cached USD /api/rates payload; `ppp` the PPP table; `clim`
    climate.json; `facts` the guide-facts document (the US levels' stand-in
    while the US list is missing); `flights` the cached /api/flights?origin=US
    payload and `fv` its flight-value build (None without fares)."""
    facts = facts or {}
    ctx = {"missing": [s for s, p in (("us", us), ("ca", ca), ("de", de)) if p is None],
           "own": {s: advisories.own_levels(p) for s, p in (("us", us), ("ca", ca), ("de", de))
                   if p is not None},
           "items": {s: (RL.own_by_iso(p) if p is not None else None)
                     for s, p in (("us", us), ("ca", ca), ("de", de))},
           "clim": clim or {}, "ppp": ppp, "rates": rates,
           "guides": {iso for _slug, iso in rg.all_slugs() if "-" not in iso},
           "ok": bool(rates and rates.get("rows") and ppp and clim)}
    if us is not None:
        ctx["adv"] = picks.advisory_levels(us.get("items") or [])
    else:
        # WanderGrade's daily snapshot of the same list, gap-fills and all
        # (src says whose), up to a day older: the US column's stand-in.
        snap = {iso: f for iso, f in facts.items()
                if isinstance(f, dict) and isinstance(f.get("adv"), int)}
        ctx["adv"] = {iso: f["adv"] for iso, f in snap.items()}
        ctx["own"]["us"] = {iso: f["adv"] for iso, f in snap.items() if f.get("src") == "us"}
    if not ctx["ok"]:
        return ctx
    rows = rates["rows"]
    ctx["rate_by_code"] = {r["code"]: r["rate_now"] for r in rows if "code" in r and "rate_now" in r}
    ctx["strength_by_code"] = {r["code"]: r["strength_pct"] for r in rows if "code" in r and "strength_pct" in r}
    ctx["fit"] = pricelevel.plausibility_fit(ppp, ctx["rate_by_code"], picks.CUR_BY_ISO)
    ctx["anchor"] = picks._price_level(HOME_ISO, ppp, ctx["rate_by_code"], ctx["fit"]) or 1
    fares = picks.fare_context(flights, cent if cent is not None else centroids()) if flights else None
    if fares:
        fares["fv"] = fv
    ctx["fares"] = fares
    ctx["fv"] = fv
    return ctx


def score_all(ctx, month, score=None):
    """{ISO: picks._score(...)} for every guide country the US edition
    scores (build_variant's loop over CUR_BY_ISO), month `month`."""
    score = score or picks._score
    out = {}
    if not ctx["ok"]:
        return out
    for iso in picks.CUR_BY_ISO:
        if iso not in ctx["guides"]:
            continue
        s = score(iso, month, ctx["ppp"], ctx["clim"], ctx["rate_by_code"], ctx["strength_by_code"],
                  ctx["adv"], ctx["fit"], ctx["fares"], ctx["anchor"], home_iso=HOME_ISO, home_cur=HOME_CUR)
        if s:
            out[iso] = s
    return out


def pct_of(s):
    """The price figure the page prints and the rule reads: whole percent of
    the US, from the score's own price level (guide_facts' rounding)."""
    return pricelevel.js_round(100 * s["pl"])


def why_out(iso, s, ctx):
    """None when the country meets the rule, else the first rule it fails."""
    if s is None:
        return "unscored"            # no price level, unrated, or Level 4 for the US list
    lvl = ctx["own"].get("us", {}).get(iso)
    if lvl not in US_LEVELS or s.get("advLvl") != lvl:
        return "us level"
    return _rest_out(iso, s, ctx)


def _rest_out(iso, s, ctx):
    """The rule past the US level: anyone's do not travel, price, weather."""
    if advisories.dnt_for(iso, ctx["own"], ADV_PARENT):
        return "do not travel"
    if pct_of(s) > MAX_PCT:
        return "price"
    if s.get("wx") is None or s["wx"] < MIN_WX:
        return "weather"
    return None


def feed_gaps(ctx, month, scored=None):
    """Guide countries the State Department's feed has no entry for (the
    served US list carries them only as a Canadian or German gap-fill) that
    would otherwise meet the month's rule — named on the page, so the line
    saying why they are left out stays true. ISO codes, by name."""
    scored = score_all(ctx, month) if scored is None else scored
    us = ctx["own"].get("us") or {}
    out = [iso for iso, s in scored.items()
           if iso not in us and s.get("advLvl") in US_LEVELS and _rest_out(iso, s, ctx) is None]
    return sorted(out, key=RL._name)


def available(ctx):
    """Whether a list can be drawn at all: prices, climate and some US levels
    in hand. Without them the page says the list isn't available — never
    that no country qualifies."""
    return bool(ctx["ok"] and ctx["own"].get("us"))


def rank_month(ctx, month, score=None, scored=None):
    """The month's rows, best first: every scored guide country that meets
    the rule, in build_variant's order."""
    scored = score_all(ctx, month, score) if scored is None else scored
    keep = [s for iso, s in scored.items() if why_out(iso, s, ctx) is None]
    keep.sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))
    return keep


def fare_of(ctx, iso, month, today):
    """(price, band) for the month's US fare where the route has a range and a
    fare that month (picks.month_fare, banded as the Flights tab bands it:
    flightvalue.band against the route's own year), else None."""
    fv = ctx.get("fv")
    mf = picks.month_fare(fv, iso, month, _date(today)) if fv else None
    if not mf:
        return None
    c = (fv.get("countries") or {}).get(iso) or {}
    band = flightvalue.band(mf[0], c)
    return (mf[0], band, c) if band else None


# ---- the pages -------------------------------------------------------------------

def _rule_html(month_name=None):
    return ("<strong>US State Department Level %d or %d</strong>, no “do not travel” from the US, Canada "
            "or Germany, <strong>local prices at or under %d%% of the US</strong> and a <strong>weather "
            "score of %d+</strong>%s"
            % (US_LEVELS[0], US_LEVELS[1], MAX_PCT, MIN_WX, (" in %s" % month_name) if month_name else " that month"))


_plural = RL._plural


def _and(names):
    return ("%s and %s" % (", ".join(names[:-1]), names[-1])) if len(names) > 1 else "".join(names)


def _excluded(gaps=(), when="this month"):
    """The one line on what the rule leaves out. `gaps`: the guide countries
    missing from the State Department's feed that would otherwise qualify
    (feed_gaps), named so the reason given is theirs."""
    line = ("Left out: US Level 3 and 4, any country the US, Canada or Germany says not to travel to, "
            "and countries missing from the State Department's feed")
    if gaps:
        one = len(gaps) == 1
        tip = ("Not in the State Department's feed, so there is no US level to go by. Canada or Germany "
               "rates %s, and %s otherwise %s the rule." % (_plural(len(gaps), "it", "them"),
                                                            _plural(len(gaps), "it", "they"),
                                                            "meets" if one else "meet"))
        names = [('<a href="/guide/%s">%s</a>' % (RL._slug(i), html.escape(RL._name(i))))
                 if RL._slug(i) else html.escape(RL._name(i)) for i in gaps]
        line += ' (<span title="%s">%s: %s</span>)' % (html.escape(tip, quote=True), when, _and(names))
    return line + "."


def _us_pill(it, lvl, today=None):
    words = US_WORDS.get(lvl, rg.lvl_words("us", lvl))
    tip = "U.S. State Department: %s" % ((it or {}).get("level_text") or words)
    upd = str((it or {}).get("updated") or "")[:10]
    if upd and (not today or upd <= str(today)[:10]):
        tip += ", dated %s" % RL._day(upd)
    return '<span class="lvl lvl%d" title="%s">Level %d: %s</span>' % (
        lvl, html.escape(tip, quote=True), lvl, html.escape(words))


def _grade_pill(s, month_name):
    g = picks.grade(s["value"])
    cls = "gr gr" + g.replace("+", "p")
    return ('<span class="%s" title="WanderGrade value from the US in %s: prices, safety, weather and '
            'flights">%s</span> %d' % (cls, html.escape(month_name), g, s["value"]))


def _weather(s, c, month):
    temps = (c or {}).get("temps") or []
    t = temps[month - 1] if len(temps) >= month else None
    tip = "Weather score 0–100 for %s" % rg.MON_FULL[month - 1]
    if t is None:
        return '<span title="%s">%d</span>' % (html.escape(tip, quote=True), s["wx"])
    tip += "; average daily mean temperature, five-year average (Open-Meteo)"
    if c.get("at"):
        tip += ", measured at %s" % c["at"]
    return ('<span title="%s"><strong>%d</strong> · %d°C / %d°F</span>'
            % (html.escape(tip, quote=True), s["wx"], t, _f(t)))


def _fare_cell(f):
    if not f:
        return "—<sup class=\"fn\">*</sup>"
    price, band, c = f
    tip = "Typical for this route: %s–%s (the middle half of its monthly fares)" % (_money(c["lo"]), _money(c["hi"]))
    return ('%s <span class="fvband %s" title="%s">%s</span>'
            % (_money(price), band, html.escape(tip, quote=True), FV_WORD[band]))


def _wrap(h1, lede, body, notes, sources):
    """render_lists._page with the page's own class beside .listpage."""
    return RL._page(h1, lede, body, notes, sources).replace('<div class="listpage">',
                                                             '<div class="listpage cheap">', 1)


def _problems(ctx, facts, fares_state):
    """[(note, ...)] for each missing input, worded for the page, and whether
    the page is degraded (any note) — served uncached until they are back."""
    notes = []
    if "us" in ctx["missing"]:
        if facts and facts.get("_asof"):
            notes.append("The US State Department feed is not available right now: the US levels are from "
                         "WanderGrade's daily snapshot of %s." % html.escape(RL._day(facts["_asof"])))
        else:
            notes.append("The US State Department feed is not available right now.")
    others = [s for s in ("ca", "de") if s in ctx["missing"]]
    if others:
        notes.append("%s %s not available right now, so %s “do not travel” check could not be applied."
                     % (" and ".join(html.escape(SOURCES[s]) for s in others),
                        "list is" if len(others) == 1 else "lists are",
                        "its" if len(others) == 1 else "their"))
    if not (ctx["rates"] and ctx["rates"].get("rows")) or not ctx["ppp"]:
        notes.append("Exchange rates or World Bank PPP are not loaded yet, so no country can be priced.")
    if not ctx["clim"]:
        notes.append("Climate data is not loaded, so no month can be scored.")
    if not facts:
        notes.append("WanderGrade's daily snapshot is not loaded.")
    if fares_state == "cold":
        notes.append("US fares are still loading, so fares and flight grades may change.")
    if notes:
        notes.append("This page is served uncached until then.")
    return notes


def _sources(ctx, fetched, stale, rates_asof, today=None):
    parts = []
    if rates_asof:
        parts.append("Prices and grades: WanderGrade's snapshot of %s (exchange rates from fxratesapi.com, "
                     "World Bank PPP carried forward for inflation)" % html.escape(RL._day(rates_asof)))
    adv = RL._sources_line(fetched, ctx["items"], stale={s: a for s, a in (stale or {}).items()
                                                         if a and s not in ctx["missing"]}, today=today)
    return " · ".join(parts + [adv[:-1]]) + "."


def pages(us, ca, de, rates, ppp, clim, facts, flights=None, fv=None, fares_state="off",
          fetched=None, stale=None, today=None, cent=None, score=None, pl_alt=None):
    """{path: page} for the hub and the 12 months. fares_state: "off" (no
    fare source configured: the fare column is dashes, not a degradation),
    "cold" (configured, but the US flight-value pass hasn't run or the fares
    aren't cached: degraded) or "warm". `pl_alt`: the price-level history's
    "alt" list (a † on those prices, as /safe-and-cheap marks them)."""
    today_d = _date(today)
    ctx = context(us, ca, de, rates, ppp, clim, facts, flights, fv, cent)
    notes = _problems(ctx, facts, fares_state)
    stale = {s: a for s, a in (stale or {}).items() if a and s not in ctx["missing"]}
    degraded = bool(notes or stale)
    rates_asof = (rates or {}).get("as_of")
    sources = _sources(ctx, fetched, stale, rates_asof, today_d.isoformat())
    lastmod = lastmod_of(rates, facts)
    snap = RL._day(rates_asof) or RL._day((facts or {}).get("_asof")) or RL._day(today_d.isoformat())
    have = available(ctx)
    scored = {m: score_all(ctx, m, score) for m in range(1, 13)}
    ranked = {m: rank_month(ctx, m, scored=scored[m]) for m in range(1, 13)}
    gaps = {m: (feed_gaps(ctx, m, scored[m]) if have else []) for m in range(1, 13)}
    alt = RL.alt_marked(pl_alt)
    us_items = ctx["items"].get("us") or {}
    fare_note = ("* Fares are cached searches, not live prices, and many months have none. Where a month "
                 "has one: the cheapest round trip from the US, marked Low, Typical or High against the "
                 "route's own year.")
    unavailable = ("The list isn't available right now: %s not loaded (see the note below)."
                   % ("prices or climate are" if not ctx["ok"] else "the US levels are"))
    out = {}

    for m in range(1, 13):
        name, year = rg.MON_FULL[m - 1], year_for(m, today_d)
        rows = ranked[m]
        n = len(rows)
        trs, alt_used = [], False
        for i, s in enumerate(rows):
            iso = s["iso"]
            lvl = ctx["own"]["us"][iso]
            f = fare_of(ctx, iso, m, today_d)
            pct = "%d%%" % pct_of(s)
            if iso in alt:
                alt_used = True
                pct += '<sup class="fn">†</sup>'
            cells = [
                '<td class="num" data-l="#">%d</td>' % (i + 1),
                '<td class="name" data-l="Country"><span class="rk">%d.</span> %s</td>'
                % (i + 1, RL._country(iso, RL._name(iso))),
                RL._cell("Grade", _grade_pill(s, name)),
                RL._cell("Prices vs US", pct),
                RL._cell("Weather score", _weather(s, ctx["clim"].get(iso), m)),
                RL._cell("US State Dept", _us_pill(us_items.get(iso), lvl, today_d.isoformat())),
                RL._cell("US round trip", _fare_cell(f)),
            ]
            trs.append("<tr>%s</tr>" % "".join(cells))
        head = ["#", "Country", "Grade", "Prices vs US", "Weather (score · avg daily mean)",
                "US State Dept", "US round trip"]
        table = ('<div class="listbox"><table class="listtable"><thead><tr>%s</tr></thead><tbody>%s</tbody>'
                 '</table></div>'
                 % ("".join("<th>%s</th>" % html.escape(h) for h in head),
                    "".join(trs) or '<tr><td class="name" data-l="Country">No country meets the rule '
                    'for this month right now.</td></tr>')) if have else ""
        prev_m, next_m = (m - 2) % 12 + 1, m % 12 + 1
        nav = ('<p class="monthnav"><a href="%s">← %s</a> · <a href="%s">All months</a> · '
               '<a href="%s">%s →</a></p>'
               % (path_for(prev_m), rg.MON_FULL[prev_m - 1], HUB, path_for(next_m), rg.MON_FULL[next_m - 1]))
        if have:
            lede = ("The rule: %s. <strong>%d</strong> %s, ranked by WanderGrade's value grade for a "
                    "traveller from the US, as of %s." % (_rule_html(name), n,
                                                         _plural(n, "country qualifies", "countries qualify"),
                                                         html.escape(snap)))
        else:
            lede = "The rule: %s. %s" % (_rule_html(name), unavailable)
        body = nav + table
        body += ('<p class="xlink">See also: <a href="/safe-and-cheap">the safest cheap countries, any '
                 'month</a> · <a href="/?vmn=%d&amp;vo=US">%s in Top Picks</a> · '
                 '<a href="/do-not-travel">the Do Not Travel list</a>.</p>' % (m, name))
        page_notes = [_excluded(gaps[m]),
                      "Grade: WanderGrade's overall value from the US in %s (prices, safety, weather and "
                      "flights), as Top Picks shows it. Prices: national averages vs the US (100%%)." % name,
                      fare_note] + ([RL.ALT_NOTE] if alt_used else []) + notes
        h1 = "Cheapest countries to visit in %s %d, from the US" % (name, year)
        title = RL._fit(["Cheapest Countries to Visit in %s %d (From the US)" % (name, year),
                         "Cheapest Countries to Visit in %s %d (US)" % (name, year),
                         "Cheapest Countries in %s %d (From the US)" % (name, year)], TITLE_MAX)
        top = [RL._name(s["iso"]) for s in rows[:3]]
        lead = ("%d %s at most half US prices with good weather (70+) and US Level 1–2 in %s %d, "
                "graded from the US" % (n, _plural(n, "country", "countries"), name, year))
        if not have:
            desc = RL._fit(["The cheapest countries to visit in %s %d from the US: US Level 1–2, at most half "
                            "US prices, weather 70+, graded A+ to F." % (name, year),
                            "Cheapest countries to visit in %s %d from the US: Level 1–2, half US prices, "
                            "weather 70+." % (name, year)], DESC_MAX)
        elif rows:
            desc = RL._fit(["%s: %s %s." % (lead, _and(top), _plural(len(top), "leads", "lead")),
                            "%s: %s first." % (lead, top[0]),
                            "%s." % lead], DESC_MAX)
        else:
            desc = RL._fit(["No country meets the rule for %s %d right now: US Level 1–2, at most half US "
                            "prices, weather 70+, graded from the US." % (name, year)], DESC_MAX)
        out[path_for(m)] = {
            "path": path_for(m), "month": m, "year": year,
            "title": title, "desc": desc, "h1": h1,
            "html": _wrap(html.escape(h1), lede, body, page_notes, sources),
            "lastmod": lastmod, "degraded": degraded,
            "counts": {"rows": len(rows)}, "isos": [s["iso"] for s in rows], "gaps": gaps[m],
            "available": have,
        }

    # The hub: one row per month, soonest first.
    trs = []
    for m in month_order(today_d):
        p = out[path_for(m)]
        names = ", ".join(html.escape(RL._name(i)) for i in p["isos"][:HUB_TOP]) or "—"
        trs.append('<tr><td class="name" data-l="Month"><a href="%s">%s %d</a></td>%s%s</tr>'
                   % (p["path"], rg.MON_FULL[m - 1], p["year"],
                      RL._cell("Countries", str(p["counts"]["rows"]) if have else "—"),
                      RL._cell("Top three", names)))
    table = ('<div class="listbox"><table class="listtable hub"><thead><tr><th>Month</th><th>Countries</th>'
             '<th>Top three</th></tr></thead><tbody>%s</tbody></table></div>' % "".join(trs))
    lede = ("One list per month. The rule: %s. Each list is ranked by WanderGrade's value grade for a "
            "traveller from the US, as of %s.%s" % (_rule_html(), html.escape(snap),
                                                    "" if have else " " + unavailable))
    body = table + ('<p class="xlink">See also: <a href="/safe-and-cheap">the safest cheap countries, any '
                    'month</a> · <a href="/do-not-travel">the Do Not Travel list</a>.</p>')
    nxt = out[path_for(today_d.month % 12 + 1)]
    h1 = "Cheapest countries to visit each month, from the US"
    hub_lead = ("Each month's cheapest countries from the US: at most half US prices, weather 70+ and US "
                "Level 1–2, graded A+ to F")
    nxt_name = "%s %d" % (rg.MON_FULL[nxt["month"] - 1], nxt["year"])
    k = nxt["counts"]["rows"]
    if have and nxt["isos"]:
        hub_desc = RL._fit(["%s. %s: %d %s, led by %s." % (hub_lead, nxt_name, k, _plural(k, "country", "countries"),
                                                          RL._name(nxt["isos"][0])),
                            "%s. %s: %d %s." % (hub_lead, nxt_name, k, _plural(k, "country", "countries")),
                            "%s." % hub_lead], DESC_MAX)
    else:
        hub_desc = RL._fit(["%s." % hub_lead], DESC_MAX)
    # A country missing from the State Department's feed that would qualify in
    # any month: named once on the hub, as each month names its own.
    hub_gaps = sorted({i for g in gaps.values() for i in g}, key=RL._name)
    out[HUB] = {
        "path": HUB, "month": None, "year": None,
        "title": RL._fit(["Cheapest Countries to Visit Each Month (From the US)"], TITLE_MAX),
        "desc": hub_desc, "h1": h1,
        "html": _wrap(html.escape(h1), lede, body, [_excluded(hub_gaps, "in some months")] + notes, sources),
        "lastmod": lastmod, "degraded": degraded,
        "counts": {m: out[path_for(m)]["counts"]["rows"] for m in range(1, 13)},
        "isos": [], "gaps": hub_gaps, "available": have,
    }
    return out


def lastmod_of(rates, facts):
    """The day the pages' data last changed: the exchange rates' own date
    (every row's price and grade moves with them), else the daily snapshot's,
    else '' — never today."""
    return RL.lastmod_of((rates or {}).get("as_of")) or RL.lastmod_of((facts or {}).get("_asof"))

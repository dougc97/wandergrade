"""/how-grades-work as a pure function: the page body, its <title>,
description and "last updated" date, in the shell the list pages use
(server.py _shell_page), built like /privacy.

Every number on it is read from the code that grades, never typed here:

  * the letter bands:      picks.GRADE_BANDS (picks.grade)
  * the Overall weights:   picks.WEIGHTS
  * Affordability:         picks.AFF_PL_ZERO / AFF_PL_SPAN and picks.afford_score,
                           which picks._score grades with (the examples and the
                           A+ and F points are its output)
  * the price words:       guide_facts.band, probed at every whole percent
  * Safety:                picks.SAFE_GRADE / SAFE_SCORE
  * Weather:               build_climate.COMFORT_* / *_PTS_* and comfort()
                           (the example is its output), WINDOW_YEARS, CURATED,
                           and the count of STATION_RAIN places in Sources
  * Flights:               picks.FLY_TYPICAL / FLY_SLOPE
  * refresh intervals:     passed in by server.py (its CACHE_TTL, ADV_TTL,
                           FLIGHTS_TTL, PPP_TTL), so a changed TTL changes the page

So a change to the scoring changes this page with it. What a change must
also move is UPDATED: scripts/test_how_grades_work.py pins a digest of the
page's text and fails until UPDATED and the pin are moved together (the
sitemap dates the page by UPDATED, and a page whose words change under an
old date is the fabricated freshness the sitemap avoids, the other way round).
"""

import html

from . import build_climate, guide_facts, picks
from .home_picks import grade_cls

PATH = "/how-grades-work"
UPDATED = "2026-11-24"
CONTACT = "hello@wandergrade.com"
TITLE = "How Grades Work | WanderGrade"
DESC = ("How WanderGrade grades every country A+ to F: the formulas, weights, data sources and "
        "known limits behind Affordability, Safety, Weather and Flights.")

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
FACTOR = {"afford": "💰 Affordability", "safe": "🛡️ Safety", "wx": "🌤️ Weather", "fly": "✈️ Flights"}
# Refresh intervals in seconds, as server.py holds them (it passes its own).
DEFAULT_TTLS = {"rates": 600, "ppp": 30 * 24 * 3600, "adv": 6 * 3600, "flights": 3600}


def updated_text(day=UPDATED):
    """'23 November 2026': day-month-year, as /privacy prints its date."""
    y, m, d = day.split("-")
    return "%d %s %s" % (int(d), _MONTHS[int(m) - 1], y)


def _n(x):
    """A number as the page prints it: 6.25, 0.18, 35, never 35.0."""
    return ("%.2f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def _word(k):
    """3 -> 'three': small counts read as words."""
    return ("zero one two three four five six seven eight nine ten".split()[k]
            if isinstance(k, int) and 0 <= k <= 10 else str(k))


def _pct(x):
    """0.35 -> '35%'."""
    return "%s%%" % _n(round(x * 100, 2))


def _pill(letter):
    return '<span class="gr %s">%s</span>' % (grade_cls(letter), html.escape(letter))


def _sec(sid, title, *parts):
    return '<section id="%s"><h2>%s</h2>%s</section>' % (sid, title, "".join(parts))


def _mail():
    """The contact link inside Cloudflare's email_off markers, as /privacy has it."""
    return '<!--email_off--><a href="mailto:%s">%s</a><!--/email_off-->' % (CONTACT, CONTACT)


def _every(seconds):
    """3600 -> 'every hour', 600 -> 'every 10 minutes', 2592000 -> 'every month'."""
    for unit, size in (("month", 30 * 86400), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size and seconds % size == 0:
            k = seconds // size
            return "every %s" % unit if k == 1 else "every %d %ss" % (k, unit)
    return "every %d seconds" % seconds


def letter_bands():
    """[(letter, low, high)], A+ first, from picks.GRADE_BANDS; F runs from 0."""
    out, top = [], 100
    for lo, g in picks.GRADE_BANDS:
        out.append((g, lo, top))
        top = lo - 1
    out.append(("F", 0, top))
    return out


def price_words():
    """[(word, low %, high %)] in order, from guide_facts.band probed at every
    whole percent from 0 to 300 (high None: open-ended)."""
    runs = []
    for i in range(0, 301):
        w = guide_facts.band(round(i / 100, 2))
        if runs and runs[-1][0] == w:
            runs[-1][2] = i
        else:
            runs.append([w, i, i])
    if runs:
        runs[-1][2] = None
    return [tuple(r) for r in runs]


def _price_words_text():
    words = price_words()
    parts = []
    for k, (w, lo, hi) in enumerate(words):
        if k == 0:
            parts.append("under %d%% %s" % (words[1][1] if len(words) > 1 else hi + 1, w))
        elif hi is None:
            parts.append("over %d%% %s" % (words[k - 1][2], w))
        else:
            parts.append("%d–%d%% %s" % (lo, hi, w))
    return ", ".join(parts)


def _pl_at(score):
    """The price level where afford_score's unrounded line reaches `score`."""
    return picks.AFF_PL_ZERO - picks.AFF_PL_SPAN * score / 100


def afford_numbers():
    """The figures the Affordability section quotes, from picks' constants:
    100 at or under `full`, 0 at or over `zero`, and roughly where the line
    leaves A+ and enters F (`a_plus`, `f`, whole percent of home prices). A
    score rounds half up (clamp100), so A+ (picks.GRADE_BANDS) starts half a
    point under its lowest score, and F half a point under D's. The guide's
    price ⓘ (app.js COST_GRADE_TIP) and llms.txt quote the same two points."""
    lo = dict((g, s) for s, g in picks.GRADE_BANDS)
    return {"full": _pl_at(100), "zero": picks.AFF_PL_ZERO,
            "a_plus": round(100 * _pl_at(lo["A+"] - 0.5)), "f": round(100 * _pl_at(lo["D"] - 0.5))}


AFFORD_EXAMPLES = (0.2, 0.5, 0.7, 1.0)   # price levels the examples line scores


def afford_examples():
    """[(price level, Affordability, letter)] by picks.afford_score: what a
    country at that level grades."""
    return [(pl, picks.afford_score(pl), picks.grade(picks.afford_score(pl))) for pl in AFFORD_EXAMPLES]


WX_EXAMPLE = (30, 150)   # °C, mm: the worked example's month


def weather_example():
    """(temp, rain, hot penalty, rain penalty, score) for WX_EXAMPLE, the score
    from build_climate.comfort itself."""
    t, r = WX_EXAMPLE
    b = build_climate
    hot = max(0, t - b.COMFORT_HI) * b.HOT_PTS_PER_C
    rain = min(b.RAIN_PTS_MAX, r * b.RAIN_PTS_PER_MM)
    return t, r, hot, rain, b.comfort(t, r)


def _f(c):
    return round(c * 9 / 5 + 32)


def page(ttls=None):
    """{"title", "desc", "h1", "html", "updated"} for /how-grades-work."""
    ttl = dict(DEFAULT_TTLS, **(ttls or {}))
    w = picks.WEIGHTS
    tot = sum(w.values()) or 1
    equal = len(set(w.values())) == 1
    a = afford_numbers()
    b = build_climate
    t, r, hot, rain, wx = weather_example()
    fly_full = (100 - picks.FLY_TYPICAL) / (picks.FLY_SLOPE / 100)    # % under typical for 100
    per_pct = picks.FLY_SLOPE / 100

    bands = "".join('<span class="lband">%s %d–%d</span>' % (_pill(g), lo, hi)
                    for g, lo, hi in letter_bands())
    weights = (" each count the same (%s)." % _pct(1 / len(w)) if equal else
               ": " + ", ".join("%s %s" % (FACTOR[k], _pct(v / tot)) for k, v in w.items()) + ".")
    safe = " · ".join("Level %d = %s (%d)" % (lvl, _pill(picks.SAFE_GRADE[lvl]), picks.SAFE_SCORE[lvl])
                      for lvl in sorted(picks.SAFE_SCORE))
    examples = " · ".join("%s → %d %s" % (_pct(pl), sc, _pill(g)) for pl, sc, g in afford_examples())

    body = "".join([
        '<div class="listpage privacy method"><h1>How grades work</h1>',
        '<p class="lede">Every country gets four grades and an Overall grade, A+ to F, worked out from '
        "public data by the same code that draws the site. These are the real numbers.</p>",
        '<p class="asof">Last updated %s</p>' % updated_text(),

        _sec("overall", "Overall",
             "<p>Each grade starts as a score from 0 to 100. By default the four scores%s Change "
             'that with the priorities on <a href="/">Top Picks</a>. A score a country lacks is left '
             "out and the rest are averaged.</p>" % weights,
             '<p class="bands">%s</p>' % bands),

        _sec("afford", FACTOR["afford"],
             "<p>Local prices against your home country, and nothing else: %s of home prices or less "
             "scores 100, %s or more scores 0, a straight line between. That puts A+ up to about %d%% "
             "of home prices and F above about %d%%.</p>" % (_pct(a["full"]), _pct(a["zero"]), a["a_plus"], a["f"]),
             '<p class="ex">%s</p>' % examples,
             "<p>How strong your currency is against its average over the past year, after inflation, "
             "is shown beside the grades, on Top Picks and the guides, but it doesn't change them.</p>",
             '<p>Price words on guides and lists: %s. The price levels are a <a href="/data">free '
             "download</a>.</p>" % html.escape(_price_words_text())),

        _sec("safety", FACTOR["safe"],
             "<p>The travel advisory level from the government you pick: the US State Department (the "
             "default), Global Affairs Canada or Germany's Foreign Office. Where it rates nothing, the "
             "strictest level of the other two fills in.</p>",
             '<p class="ex">%s</p>' % safe,
             '<p>Level 4, “do not travel”: left out of every ranking (see the <a href="/do-not-travel">'
             "list</a>). A country no government rates isn't graded.</p>"),

        _sec("weather", FACTOR["wx"],
             "<p>A comfort score for your travel month, from %s years of daily temperature and rain at "
             "one point in each country.</p>" % _word(b.WINDOW_YEARS),
             "<ul>"
             "<li>A month averaging %d–%d °C (%d–%d °F) starts at 100.</li>"
             "<li>Each °C above %d takes off %s, each °C below %d takes off %s.</li>"
             "<li>Each mm of the month's rain takes off %s, at most %s.</li>"
             "</ul>" % (b.COMFORT_LO, b.COMFORT_HI, _f(b.COMFORT_LO), _f(b.COMFORT_HI),
                        b.COMFORT_HI, _n(b.HOT_PTS_PER_C), b.COMFORT_LO, _n(b.COLD_PTS_PER_C),
                        _n(b.RAIN_PTS_PER_MM), _n(b.RAIN_PTS_MAX)),
             '<p class="ex">%d °C and %d mm of rain: 100 − %s − %s = %d %s</p>'
             % (t, r, _n(hot), _n(rain), wx, _pill(picks.grade(wx))),
             "<p>Best months are the three best-scoring months, or a hand-picked list for %d popular "
             "destinations.</p>" % len(b.CURATED)),

        _sec("flights", FACTOR["fly"],
             "<p>The round-trip fare from your home for your month, against that route's typical "
             "fare.</p>",
             "<ul>"
             "<li>A typical fare scores %d %s. Each 1%% cheaper adds %s (100 at %s%% under), each 1%% "
             "dearer takes %s off.</li>"
             "<li>A route with too few months of fares is compared with the typical fare for its "
             "distance.</li>"
             "<li>No cached fare: counted as typical, and the letter shows ~.</li>"
             "</ul>" % (picks.FLY_TYPICAL, _pill(picks.grade(picks.FLY_TYPICAL)),
                        "a point" if per_pct == 1 else _n(per_pct) + " points", _n(fly_full),
                        "one" if per_pct == 1 else _n(per_pct)),
             "<p>Fares are what Aviasales searches found in roughly the last 90 days, not live prices. "
             "With no fare data, Flights is left out.</p>"),

        _sec("sources", "Sources",
             "<ul>"
             "<li>Exchange rates, today and over the past year: fxratesapi.com, checked %s.</li>"
             "<li>Price levels and inflation: World Bank, yearly figures (prices for household spending; "
             "Taiwan's from the IMF, adjusted to household spending with the Penn World Table), checked %s.</li>"
             "<li>Advisories: US State Department, Global Affairs Canada, German Foreign Office, "
             "checked %s.</li>"
             "<li>Weather: Open-Meteo's historical archive, rebuilt by hand, not live. For %d places where "
             "its rain is far off, the nearest weather station's long-run averages.</li>"
             "<li>Fares: Aviasales through Travelpayouts, refreshed %s.</li>"
             "</ul>" % (_every(ttl["rates"]), _every(ttl["ppp"]), _every(ttl["adv"]), len(b.STATION_RAIN),
                        _every(ttl["flights"]))),

        _sec("limits", "Known limits",
             "<ul>"
             "<li>Prices are national averages. Tourist areas and rents for foreigners run higher.</li>"
             "<li>Weather is one point per country. Big countries vary by region.</li>"
             "<li>Fares are past searches, not quotes.</li>"
             "<li>Advisories can change without notice. Read the government's own page before you go.</li>"
             "<li>Where the World Bank has no recent household-spending figure, the price is its last one "
             "carried forward along the GDP-wide figure, or the GDP-wide figure itself.</li>"
             "<li>A country with no price figure (no World Bank data, or an exchange rate too far out of "
             "line to trust) isn't ranked.</li>"
             "</ul>"),

        _sec("about", "Who makes this",
             "<p>Grades never depend on affiliate links. Some links pay a commission; none changes a "
             "grade or a ranking.</p>"
             "<p>Built by one person. Questions or corrections: %s</p>" % _mail()),
        "</div>",
    ])
    return {"title": TITLE, "desc": DESC, "h1": "How grades work", "html": body, "updated": UPDATED}

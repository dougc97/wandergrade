#!/usr/bin/env python3
"""/how-grades-work (fxtracker/render_methodology.py), in-process: no network,
no server of its own beyond a loopback one for the route.

    /usr/bin/python3 scripts/test_how_grades_work.py

What it holds the code to:
  * the route: GET is 200 text/html, cached like /privacy, sets no cookie;
    HEAD answers the same with no body; /how-grades-work/ and
    /How-Grades-Work 301 to it, query kept; the sitemap lists it dated by
    its own UPDATED, and llms.txt links it (and /data) once;
  * the page: one h1, title and description in the list pages' limits,
    canonical, HTML that html.parser accepts, every section, no class an ad
    blocker would hide, the contact address inside email_off markers, "Grades
    never depend on affiliate links" and "Built by one person";
  * every number on it is the one the grading code uses, checked against the
    code's behaviour, not against literals typed here: the letter bands
    against picks.grade, the Affordability end points and its A+ and F
    points against picks.afford_score (and the guide's price ⓘ and llms.txt
    quote the same A+ and F points), the Safety scores and the Flights slope against
    picks._score itself (its price, fare and level inputs stubbed), the
    weather rule against build_climate.comfort, the price words against
    guide_facts.band, and the refresh intervals against server.py's TTLs;
  * the page follows the code: with a scoring constant or the band rule
    changed (and put back), the page says the new numbers;
  * the date can't go stale: a digest of the page is pinned here, and any
    change to its words fails until render_methodology.UPDATED and PIN move
    together (the sitemap dates the page by UPDATED);
  * the footer: the homepage, the guides, the shell pages (/data, the lists,
    /privacy, 404) and this page link it exactly once, with the link text
    "How grades work".
"""
import hashlib
import html.parser
import os
import re
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import build_climate, guide_facts, llms_txt, picks, render_guide as rg  # noqa: E402
from fxtracker import render_methodology as RM  # noqa: E402
import server  # noqa: E402

# sha1 of render_methodology.page(server's TTLs)["html"]. A change to the
# page's words (a scoring constant, a TTL, the copy) changes it: then set
# render_methodology.UPDATED to the day it ships and this to the new digest.
PIN = "0d90b11a8e1d8fa2b44f8e06438a4bc0eefce7f3"

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
TTLS = {"rates": server.CACHE_TTL, "ppp": server.PPP_TTL, "adv": server.ADV_TTL, "flights": server.FLIGHTS_TTL}
page = RM.page(TTLS)
body = page["html"]
served = server._render_methodology_page().decode("utf-8")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
norm = lambda t: re.sub(r"\s+", " ", t)

# --- the route ------------------------------------------------------------------------
server.Handler.log_message = lambda self, *a: None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def get(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


st, hd, raw = get("/how-grades-work")
results.append(ok(st == 200 and hd.get("Content-Type") == "text/html; charset=utf-8"
                  and hd.get("Cache-Control") == "public, max-age=300" and "Set-Cookie" not in hd
                  and raw.decode("utf-8") == served,
                  "GET /how-grades-work: 200 text/html, public max-age=300, no cookie (%s %s)"
                  % (st, hd.get("Cache-Control"))))
st2, hd2, raw2 = get("/how-grades-work", "HEAD")
results.append(ok(st2 == 200 and raw2 == b"" and hd2.get("Content-Type") == hd.get("Content-Type"),
                  "HEAD /how-grades-work: the same status and type, no body"))
st3, hd3, _ = get("/how-grades-work/?utm_source=x")
results.append(ok(st3 == 301 and hd3.get("Location") == "/how-grades-work?utm_source=x",
                  "/how-grades-work/ 301s to /how-grades-work, query kept (%s %s)" % (st3, hd3.get("Location"))))
st4, hd4, _ = get("/How-Grades-Work")
results.append(ok(st4 == 301 and hd4.get("Location") == "/how-grades-work",
                  "/How-Grades-Work 301s to the lowercase URL (%s %s)" % (st4, hd4.get("Location"))))
st5, _, home_raw = get("/")
home = home_raw.decode("utf-8")
httpd.shutdown()
results.append(ok(server._slot_route("/how-grades-work"), "it takes a page slot, as /privacy does"))

sm = server._sitemap().decode("utf-8")
results.append(ok("<loc>https://wandergrade.com/how-grades-work</loc><lastmod>%s</lastmod>" % RM.UPDATED in sm,
                  "the sitemap lists /how-grades-work at its own date %s" % RM.UPDATED))
txt = llms_txt.build(rg.all_slugs(), rg.name_for_iso)
results.append(ok(txt.count("](https://wandergrade.com/how-grades-work)") == 1
                  and txt.count("](https://wandergrade.com/data)") == 1,
                  "llms.txt links /how-grades-work and /data once each"))

# --- the page ---------------------------------------------------------------------------
class Check(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.classes = []

    def handle_starttag(self, tag, attrs):
        self.h1 += tag == "h1"
        for k, v in attrs:
            if k in ("class", "id") and v:
                self.classes += v.split()


c = Check()
try:
    c.feed(served)
    parsed = True
except Exception:
    parsed = False
results.append(ok(parsed and c.h1 == 1, "html.parser accepts the served page; exactly one h1 (%d)" % c.h1))
results.append(ok(len(page["title"]) <= 60 and len(page["desc"]) <= 155
                  and "<title>How Grades Work | WanderGrade</title>" in served
                  and '<link rel="canonical" href="https://wandergrade.com/how-grades-work">' in served
                  and '<meta name="robots"' not in served,
                  "title (%d) and description (%d) in the list pages' limits; canonical; indexable"
                  % (len(page["title"]), len(page["desc"]))))
bad = [k for k in c.classes if re.match(r"(ad|adv|sponsor|banner|promo)", k) or "advert" in k]
results.append(ok(not bad, "no class or id an ad blocker would hide (%s)" % bad))
SECTIONS = ["overall", "afford", "safety", "weather", "flights", "sources", "limits", "about"]
missing = [s for s in SECTIONS if '<section id="%s">' % s not in body]
results.append(ok(not missing, "every section is there (missing: %s)" % missing))
results.append(ok("Last updated %s" % RM.updated_text() in text, "the last-updated line reads %s" % RM.updated_text()))
results.append(ok(body.count("mailto:") == 1 and
                  '<!--email_off--><a href="mailto:hello@wandergrade.com">hello@wandergrade.com</a><!--/email_off-->' in body,
                  "hello@wandergrade.com as a mailto link inside Cloudflare's email_off markers"))
for words in ["Grades never depend on affiliate links", "Built by one person", "national averages",
              "not live prices", "one point in each country", "Level 4"]:
    results.append(ok(words in text, "says “%s”" % words))
results.append(ok("airbnb" not in served.lower(), "no Airbnb anywhere on the page"))

# --- the numbers are the code's --------------------------------------------------------
# Letter bands: each range's ends grade to its letter, the next score up doesn't.
bands = RM.letter_bands()
bad = [(g, lo, hi) for g, lo, hi in bands
       if picks.grade(lo) != g or picks.grade(hi) != g or (hi < 100 and picks.grade(hi + 1) == g)
       or "%s %d–%d" % (g, lo, hi) not in text]
results.append(ok(len(bands) == 7 and bands[-1][1] == 0 and not bad,
                  "the letter bands are picks.grade's, every range printed (%s; bad %s)"
                  % (" ".join("%s %d" % (g, lo) for g, lo, _ in bands), bad)))

# Overall weights.
w = picks.WEIGHTS
if len(set(w.values())) == 1:
    results.append(ok("each count the same (%d%%)" % round(100 / len(w)) in text,
                      "the equal weights are picks.WEIGHTS' (%d%% each)" % round(100 / len(w))))
else:
    results.append(ok(False, "picks.WEIGHTS aren't equal: check the page's weights line"))

# Affordability (review #21: the price level alone): the end points the page
# quotes are where afford_score reaches 100 and 0, and its A+ and F points are
# where the letter changes; the guide's price ⓘ and llms.txt say the same.
a = RM.afford_numbers()
af = picks.afford_score
results.append(ok(af(a["full"]) == 100 and af(a["full"] + 0.011) < 100
                  and af(a["zero"]) == 0 and af(a["zero"] - 0.011) > 0,
                  "Affordability: 100 at %.2f and below, 0 at %.2f and above (afford_score)" % (a["full"], a["zero"])))
results.append(ok(picks.grade(af((a["a_plus"] - 1) / 100)) == "A+" and picks.grade(af((a["a_plus"] + 1) / 100)) != "A+"
                  and picks.grade(af((a["f"] + 1) / 100)) == "F" and picks.grade(af((a["f"] - 1) / 100)) != "F",
                  "A+ runs to about %d%% of home prices and F starts about %d%% (afford_score, picks.grade)"
                  % (a["a_plus"], a["f"])))
results.append(ok(all(s in text for s in ["15% of home prices or less scores 100", "130% or more scores 0",
                                          "A+ up to about %d%% of home prices and F above about %d%%"
                                          % (a["a_plus"], a["f"]),
                                          "is shown beside the grades, on Top Picks and the guides, but it "
                                          "doesn't change them"])
                  and "70% local prices" not in text and "Currency flat" not in text,
                  "the Affordability numbers are printed as computed, and no currency part is described"))
ex_ok = all("%d%% → %d %s" % (round(pl * 100), sc, g) in text and sc == af(pl) for pl, sc, g in RM.afford_examples())
results.append(ok(ex_ok, "each example is afford_score's grade (%s)" % RM.afford_examples()))
src = open(os.path.join(ROOT, "fxtracker", "picks.py"), encoding="utf-8").read()
score_src = re.search(r"^def _score\(.*?^def ", src, re.M | re.S).group(0)
results.append(ok('"afford": afford_score(pl),' in score_src, "_score grades Affordability with afford_score"))
app_src = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
results.append(ok("afford: clamp100(((%s - pl) / %s) * 100)," % (RM._n(picks.AFF_PL_ZERO), RM._n(picks.AFF_PL_SPAN)) in app_src,
                  "app.js valueScores grades Affordability on the same line"))
tip = re.search(r'const COST_GRADE_TIP = ([^;]+);', app_src)
tip = re.sub(r'"\s*\+\s*"', "", tip.group(1)) if tip else ""
claim = "A+ up to about %d%% of home prices, F above about %d%%" % (a["a_plus"], a["f"])
results.append(ok("A+ up to about %d%%" % a["a_plus"] in tip and "F above about %d%%" % a["f"] in tip
                  and claim in llms_txt.build(rg.all_slugs(), rg.name_for_iso),
                  "the guide's price ⓘ (COST_GRADE_TIP) and llms.txt quote the same A+ and F points (%s)" % claim))

# Safety and Flights through _score itself, its inputs stubbed: the scores
# the page prints are the ones a country gets.
real_pl, real_mf = picks._price_level, picks.month_fare
try:
    picks._price_level = lambda iso, ppp, rates, fit=None: 0.5
    clim = {"TH": {"scores": [80] * 12}}
    run = lambda lvl, fares=None: picks._score("TH", 1, {}, clim, {}, {}, {"TH": lvl}, fares=fares)
    safe = {lvl: (run(lvl) or {}).get("safe") for lvl in (1, 2, 3)}
    results.append(ok(safe == picks.SAFE_SCORE and run(4) is None and run(None) is None,
                      "Safety: _score gives %s, drops Level 4 and the unrated" % safe))
    results.append(ok(all("Level %d = %s (%d)" % (l, picks.SAFE_GRADE[l], s) in text for l, s in safe.items()),
                      "the Safety levels, letters and scores are printed"))
    fly = {}
    for dev in (-0.3, -0.01, 0, 0.01):
        picks.month_fare = lambda fv, iso, month, today=None, d=dev: (100.0, d)
        fly[dev] = run(1, {"fv": {}, "prices": {}, "est": set()})["fly"]
    results.append(ok(fly == {-0.3: 100, -0.01: picks.FLY_TYPICAL + 1, 0: picks.FLY_TYPICAL, 0.01: picks.FLY_TYPICAL - 1}
                      and "A typical fare scores %d" % picks.FLY_TYPICAL in text
                      and "Each 1% cheaper adds a point (100 at 30% under)" in text,
                      "Flights: _score gives %s at 30%% under / 1%% under / typical / 1%% over, as printed" % fly))
    results.append(ok(run(1)["afford"] == af(0.5) and run(1)["wx"] == 80,
                      "_score's Affordability and Weather are afford_score's and the month's climate score"))
finally:
    picks._price_level, picks.month_fare = real_pl, real_mf

# Weather: the rule against comfort().
cf = build_climate.comfort
results.append(ok(cf(18, 0) == 100 and cf(26, 0) == 100 and cf(27, 0) == 94 and cf(17, 0) == 96
                  and cf(22, 100) == 82 and cf(22, 1000) == 40,
                  "comfort(): 100 across 18-26 °C, -6 per °C above, -4 per °C below, -0.18/mm, at most -60"))
results.append(ok(all(s in text for s in ["18–26 °C (64–79 °F)", "Each °C above 26 takes off 6",
                                          "each °C below 18 takes off 4", "takes off 0.18, at most 60"]),
                  "the weather rule is printed with comfort()'s numbers"))
t, r, hot, rain, wx = RM.weather_example()
results.append(ok(wx == cf(t, r) == 100 - hot - rain and "%d °C and %d mm of rain: 100 − %d − %d = %d" % (t, r, hot, rain, wx) in text,
                  "the worked example is comfort(%d, %d) = %d" % (t, r, wx)))
results.append(ok("hand-picked list for %d popular destinations" % len(build_climate.CURATED) in text
                  and "from five years" in text and build_climate.WINDOW_YEARS == 5,
                  "the curated count (%d) and the window are build_climate's" % len(build_climate.CURATED)))

# Price words: each boundary printed is where guide_facts.band changes.
words = RM.price_words()
bad = [x for x in words[1:] if guide_facts.band(x[1] / 100) == guide_facts.band((x[1] - 1) / 100)]
results.append(ok(len(words) >= 3 and not bad
                  and "under 55% very cheap, 55–74% cheap, 75–90% a bit cheaper, 91–110% about the same" in text,
                  "the price words follow guide_facts.band (%s)" % RM._price_words_text()))

# Refresh intervals: server.py's.
results.append(ok(all(s in text for s in ["checked every 10 minutes", "checked every month",
                                          "checked every 6 hours", "refreshed every hour"])
                  and TTLS == {"rates": 600, "ppp": 30 * 86400, "adv": 6 * 3600, "flights": 3600},
                  "the refresh intervals are server.py's TTLs (%s)" % TTLS))

# --- the page follows the code ----------------------------------------------------------
saved = (picks.AFF_PL_SPAN, picks.GRADE_BANDS, build_climate.HOT_PTS_PER_C, guide_facts.band)
try:
    picks.AFF_PL_SPAN = 1.1
    picks.GRADE_BANDS = ((90, "A+"),) + saved[1][1:]
    build_climate.HOT_PTS_PER_C = 5
    guide_facts.band = lambda pl: "cheap" if pl < 0.75 else "a bit cheaper" if pl <= 0.9 else "pricey"
    moved = norm(re.sub(r"<[^>]+>", " ", RM.page(TTLS)["html"]))
finally:
    picks.AFF_PL_SPAN, picks.GRADE_BANDS, build_climate.HOT_PTS_PER_C, guide_facts.band = saved
results.append(ok(all(s in moved for s in ["20% of home prices or less scores 100", "A+ 90–100", "takes off 5,",
                                           "75–90% a bit cheaper", "over 90% pricey"]),
                  "with a scoring constant, a band or a word rule changed, the page says the new numbers"))
results.append(ok(RM.page(TTLS)["html"] == body, "and back once they're put back"))

# --- the date can't go stale -----------------------------------------------------------
digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
results.append(ok(digest == PIN, "the page's words are the pinned ones (digest %s): if you changed them on "
                  "purpose, set render_methodology.UPDATED to the ship day and PIN to %s" % (digest[:12], digest)))

# --- the footer --------------------------------------------------------------------------
LINK = '<a href="/how-grades-work">How grades work</a>'
footer = lambda doc: doc[doc.find("<footer>"):doc.find("</footer>")]
guides = {iso: server._render_index(iso).decode("utf-8") for iso in ["JP", "GB-SCT", "AF"]}
# /data and the list pages are _shell_page documents ("a shell page"): rendered
# themselves they would fetch their data.
docs = dict({"/": home, "/how-grades-work": served, "/privacy": server._render_privacy_page().decode("utf-8"),
             "a shell page": server._shell_page("t", "<p>x</p>").decode("utf-8"),
             "404": server._render_404_page("x").decode("utf-8")}, **guides)
# Besides the footer's, the only links to it are the grades' ⓘ (a.muted.tiplink:
# the Full ranking's in the homepage shell, a graded guide's "Dec ⓘ", which is
# also a.ggmon).
TIP = '<a class="muted tiplink" href="/how-grades-work"'
TIPS = re.compile(r'<a class="muted (?:ggmon )?tiplink" href="/how-grades-work"')
bad = [k for k, doc in docs.items() if footer(doc).count(LINK) != 1
       or doc.count('href="/how-grades-work"') - len(TIPS.findall(doc)) != 1]
results.append(ok(st5 == 200 and not bad,
                  "the footer links /how-grades-work exactly once: the homepage, the guides, /privacy, "
                  "the shell pages (/data, the lists), 404 and the page itself (%s)" % (", ".join(bad) or "all")))

# --- the grades' ⓘ -----------------------------------------------------------------------
# The Full ranking's ⓘ is a tip and a link (app.js tip engine: a tap shows the
# tip, a second or a click follows); the guide's grade row is test_guide_lines'.
rk = re.search(r'<p class="tablekey rankkey">.*?</p>', home, re.S)
rk = rk.group(0) if rk else ""
results.append(ok(re.search(TIP + r' data-tip="[^"]*Click for how every grade is worked out\." title="">'
                            r' <span aria-hidden="true">ⓘ</span><span class="vh">How grades work</span></a>', rk)
                  and home.count(TIP) == 1,
                  "the Full ranking's ⓘ links /how-grades-work, its tip kept and its name said"))
app = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
results.append(ok('closest("a.tiplink[data-tip]")' in app and "_tipAtDown !== tl" in app
                  and 'if (el.matches("a[href]")) continue;' in app,
                  "app.js: a tap on a tiplink shows its tip first, a click follows it, and it is no role=button"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)

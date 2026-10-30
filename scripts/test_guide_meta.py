"""Guide titles, descriptions, headings and their client/server lockstep, over
every guide — no network, no server process.

    /usr/bin/python3 scripts/test_guide_meta.py

What it holds the code to:
  * every <title> <= 60 characters, every description <= 155; none repeated;
  * public/guide-facts.json's t/d/dn are exactly render_guide.meta() (the one
    implementation) — a stale or hand-edited file fails here;
  * Oman's summary and number-free description carry Doug's 2026-11-01
    wording, with no "fjord" or "Musandam" (a merge that brings back the old
    one-line activities.json fails here, and scripts/dev/om_summary_reapply.py
    re-applies it);
  * app.js names every guide as country-names.json does (EXTRA_PLACES ->
    NAME_FIX -> climate.json's Natural Earth name), so client headings match
    the server's title, h1 and description;
  * the h1 is the same string on both sides, the raw page has exactly one h1
    and it is visible, and the /guide/ template carries no shell h2/h3;
  * the four other tabs' words are out of every served guide (server.py
    _text_out): each <!--tN--> mark is used once and puts back exactly the
    text FX_GUIDE_TEXTOUT=0 serves, no letter or digit is left in those
    tabs but scripts and .picklabel, no {{TOKEN}} is lost, and the rest of
    the page — #tab-guide included — and the homepage are byte for byte
    what the switch off serves;
  * weather-only countries never claim "best months to visit";
  * names that take "the" have it inside every sentence, on both sides;
  * Level 3/4 titles ask "safe?", Level 4 never "cheap?" or "(very cheap)";
  * a title with a price figure says "Costs vs US" wherever its rung fits in
    TITLE_MAX, on the best-time fallback too (only the Dominican Republic's
    ": Weather & Costs vs US" rung, 64, is too long);
  * descriptions never end mid-phrase;
  * Turkey's description names it "Turkey (Türkiye)" once on every rung that
    fits (render_guide.ALSO_NAMED), the served page nowhere else, and no other
    guide, title or h1 says Türkiye;
  * the title fallback (render_guide.TITLE_BEST_TIME) is on for exactly the
    Dominican Republic, Morocco and the Isle of Man (Doug, 2026-11-05): "Best
    Time to Visit X" leads their stored and served titles, which are exactly
    the three committed that day; every other guide keeps the title it has
    with the switch off and a Level 4 one its safety question; switched off,
    scripts/retitle_guide_facts.py re-words exactly those three back, and on
    for every guide "Best Time to Visit X" leads every title but a Level 4 one
    within TITLE_MAX and the script re-words exactly those;
  * no guide carries FAQPage JSON-LD (its questions were never visible on the
    page, which Google requires; FAQ rich results are gov/health-only since
    2023) and the homepage keeps its WebSite block; the staleness guard drops
    every figure and advisory clause;
  * the COMMITTED snapshot is younger than STALE_DAYS - 15. It is only the
    fallback now — the server recomputes the document daily
    (fxtracker/guide_facts.py) — but it is what a fresh deploy serves until
    its first check and what a server whose inputs are down keeps serving, so
    it must not be close to dropping every figure itself. Past 45 days the
    test says so without failing;
  * every guide's sitemap <lastmod> is its own snapshot date; "/" and "/data"
    keep content-stamp.txt;
  * the Wander List's served empty-state line (server.py VISITED_STATS, the
    homepage's first paint) is byte-for-byte what app.js renderVisitedStats
    writes for MILESTONE_TIERS[0], run under jsc — the two are kept by hand,
    and a drift would move the tab when app.js lands (CLS 0.095 at 390
    before the line was served); a guide serves no such line.
"""
import datetime
import html
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_facts as GF, render_guide as rg  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
P = lambda n: json.load(open(os.path.join(ROOT, "public", n), encoding="utf-8"))
names, clim, facts = P("country-names.json"), P("climate.json"), P("guide-facts.json")
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
guides = [iso for _s, iso in rg.all_slugs()]
asof = datetime.date.fromisoformat(facts["_asof"])

# --- lengths and uniqueness -------------------------------------------------------
R = {iso: rg.render(iso) for iso in guides}
long_t = [(i, len(R[i]["title"])) for i in guides if len(R[i]["title"]) > rg.TITLE_MAX]
long_d = [(i, len(R[i]["desc"])) for i in guides if len(R[i]["desc"]) > rg.DESC_MAX]
results.append(ok(not long_t, "%d titles, none over 60 characters %s" % (len(guides), long_t or "")))
results.append(ok(not long_d, "%d descriptions, none over 155 characters %s" % (len(guides), long_d or "")))
results.append(ok(len({R[i]["title"] for i in guides}) == len(guides), "no two guides share a title"))
results.append(ok(len({R[i]["desc"] for i in guides}) == len(guides), "no two guides share a description"))
results.append(ok(all(R[i]["og_title"] == R[i]["title"] for i in guides), "og:title is the title"))
results.append(ok(not any(re.search(r"\d", R[i]["title"]) for i in guides),
                  "titles state no number or level (they ask a question)"))
results.append(ok(not any("Cheap" in R[i]["title"] for i in guides if (facts[i].get("adv") == 4)),
                  "no Level 4 country is asked \"cheap?\""))
# The question-title checks skip a guide on the best-time fallback (below): it
# has its own ladder. A Level 4 guide is never on it. The price wording does not
# skip it: with a price figure it says "Costs vs US" whenever its shortest such
# rung fits (Morocco's is 49 characters); only the Dominican Republic's, 64,
# goes without. The rung is spelled out here, not read from the ladder, so a
# ladder that drops "vs US" fails.
unsafe = [i for i in guides if facts[i].get("adv") in (3, 4) and not rg.best_time_title_on(i, facts[i])
          and not R[i]["title"].startswith("Is %s Safe" % rg.name_in_text(i))]
l3_cheap = [i for i in guides if facts[i].get("adv") == 3 and facts[i].get("band") in ("cheap", "very cheap")
            and not rg.best_time_title_on(i, facts[i]) and "Safe & Cheap to Visit?" not in R[i]["title"]]
results.append(ok(not unsafe and not l3_cheap and sum(1 for i in guides if facts[i].get("adv") in (3, 4)) >= 40,
                  "every Level 3/4 question title asks \"Is X Safe…\"; Level 3 cheap ones \"Safe & Cheap\" %s"
                  % ((unsafe + l3_cheap) or "")))
l4_band = [i for i in guides if facts[i].get("adv") == 4
           and re.search(r"\((very cheap|cheap|about the same|pricey)", R[i]["desc"] + R[i]["body"])]
results.append(ok(not l4_band, "no Level 4 description or fact line gives a bargain band %s" % (l4_band or "")))
def cost_vs_us_fits(i):
    nt = rg.name_in_text(i)
    if rg.best_time_title_on(i, facts[i]):
        return len("Best Time to Visit %s: Weather & Costs vs US" % nt) <= rg.TITLE_MAX
    return (facts[i].get("adv") in (None, 1, 2)
            and len("Is %s %s to Visit? Costs vs US" % (nt, rg._band_q(facts[i]))) <= rg.TITLE_MAX)
no_cost_t = [i for i in guides if "pct" in facts[i] and "Costs vs US" not in R[i]["title"] and cost_vs_us_fits(i)]
fb_cost = sorted(i for i in guides if "pct" in facts[i] and rg.best_time_title_on(i, facts[i]))
results.append(ok(not no_cost_t, "price titles say \"Costs vs US\" wherever it fits, on the best-time fallback too "
                  "(fallback with a price: %s; no room: %s) %s"
                  % (fb_cost, [i for i in fb_cost if not cost_vs_us_fits(i)], no_cost_t or "")))

# --- the snapshot file is meta()'s own output --------------------------------------
bad = []
for iso in guides:
    f = {k: v for k, v in facts[iso].items() if k not in ("t", "d", "dn", "m")}
    m = rg.meta(iso, f, asof)
    dn = rg.meta_numberfree(iso)
    if (facts[iso]["t"], facts[iso]["d"], facts[iso].get("dn", facts[iso]["d"])) != (m["title"], m["desc"], dn):
        bad.append(iso)
results.append(ok(not bad, "guide-facts.json t/d/dn == render_guide.meta() for all %d %s"
                  % (len(guides), bad[:5] or "")))
fresh = rg.snapshot_fresh()
results.append(ok(not fresh or all(R[i]["title"] == facts[i]["t"] and R[i]["desc"] == facts[i]["d"] for i in guides),
                  "render() serves the file's strings while the snapshot is fresh"))
results.append(ok(set(guides) <= set(facts), "every guide has a snapshot entry"))
# Oman's opening line and number-free description sold "a dramatic fjord-like
# coast", which is Musandam, a province the US advisory (reissued 2026-10-23)
# now says not to visit. Doug's wording of 2026-11-01 replaces it. Both files
# hold it: a merge that takes another branch's one-line activities.json (or
# guide-facts.json) brings the old line back, and this fails until the new one
# is re-applied with scripts/dev/om_summary_reapply.py.
OM_SUMMARY = "Wadis, dunes, desert forts and turtle beaches."
om_summ = " ".join(((rg._load()["acts"].get("OM") or {}).get("summary") or "").split())
om_blob = " ".join([om_summ, facts["OM"]["d"], facts["OM"].get("dn", ""), R["OM"]["desc"]])
om_ok = (om_summ == OM_SUMMARY and facts["OM"].get("dn", "").endswith(" " + OM_SUMMARY)
         and not re.search(r"fjord|musandam", om_blob, re.I))
results.append(ok(om_ok, "Oman: summary and dn are %r, with no fjord or Musandam (summary %r, dn %r)%s"
                  % (OM_SUMMARY, om_summ, facts["OM"].get("dn"), "" if om_ok else
                     "\n        a merge brought back the old line: re-set OM summary to the new sentence"
                     " (and dn to match) with /usr/bin/python3 scripts/dev/om_summary_reapply.py")))
results.append(ok(all("pct" not in facts[i] for i in ("US",) if i in facts), "no price figure for the US itself"))

# --- client names: EXTRA_PLACES -> NAME_FIX -> climate name ------------------------
def js_obj(name):
    m = re.search(r"^const %s = \{(.*?)\};" % name, APP, re.M | re.S)
    return dict(re.findall(r'"?([A-Z]{2}(?:-[A-Z]{3})?)"?\s*:\s*"([^"]*)"', m.group(1))) if m else {}
EXTRA, FIX = js_obj("EXTRA_PLACES"), js_obj("NAME_FIX")
client = {iso: EXTRA.get(iso) or FIX.get(iso) or (clim.get(iso) or {}).get("name") for iso in guides}
drift = [(i, client[i], names.get(i)) for i in guides if client[i] != names.get(i)]
results.append(ok(EXTRA and FIX and not drift, "app.js countryName() == country-names.json for every guide %s"
                  % (drift or "")))
m = re.search(r"^const NAME_THE = new Set\(\[(.*?)\]\);", APP, re.M)
js_the = set(re.findall(r'"([A-Z]{2})"', m.group(1))) if m else set()
results.append(ok(js_the == rg.THE, "app.js NAME_THE == render_guide.THE %s" % (js_the ^ rg.THE or "")))
results.append(ok("nameT = countryNameInText(iso)" in APP.split("function renderActivity", 1)[1][:400]
                  and "Things to do in ${esc(nameT)}" in APP
                  and "const cname = countryNameInText(iso);" in APP and "Best time to visit ${esc(cname)}" in APP,
                  "renderActivity and renderCountryClimate name the country via countryNameInText()"))
bare = []
for iso in rg.THE:
    if iso not in R:
        continue
    n = names[iso]
    blob = " ".join([R[iso]["title"], R[iso]["desc"], R[iso]["body"], facts[iso].get("dn", "")])
    if re.search(r"\b(Is|is|in|to|visit|for|rates) %s\b" % re.escape(n), blob):
        bare.append(iso)
results.append(ok(not bare, "\"the\" names never sit bare in a sentence (Is/in/visit/for X) %s" % (bare or "")))
cut = []
for iso in guides:
    dsc = R[iso]["desc"]
    summ = " ".join(((rg._load()["acts"].get(iso) or {}).get("summary") or "").split())
    if dsc.endswith("…"):
        head = dsc[:-1].rsplit(". ", 1)[-1]
        if not (summ.startswith(head) and summ[len(head):].lstrip(".").startswith((", ", " — "))):
            cut.append(iso)
    elif not dsc.endswith((".", "!", "?", ")")):
        cut.append(iso)
results.append(ok(not cut, "no description ends mid-phrase %s" % (cut or "")))

# --- h1: one, visible, identical on both sides -------------------------------------
h1_bad = []
for iso in guides:
    txt = re.sub(r"<[^>]+>", "", html.unescape(rg.h1_html(iso)))
    if txt != rg.flag_emoji(iso) + " " + names[iso] + " travel: " + rg.h1_topics(iso):
        h1_bad.append(iso)
results.append(ok(not h1_bad, "h1 text = flag + name + ' travel: ' + its topics %s" % (h1_bad or "")))
no_cost = [i for i in guides if "pct" not in facts[i]]
results.append(ok(all("cost" not in rg.h1_topics(i) for i in no_cost)
                  and all("safety" not in rg.h1_topics(i) for i in guides if not facts[i].get("adv"))
                  and rg.h1_topics("CO") == "cost, safety & when to go" and rg.h1_topics("TF") == "when to go",
                  "the h1 names only topics the guide has data for (%d without a price figure)" % len(no_cost)))
tpl = server._guide_template()
results.append(ok(not re.search(r"<h[23][\s>]", tpl), "the /guide/ template has no static h2/h3"))
results.append(ok(tpl.count('data-h="2"') == 13 and tpl.count('data-h="3"') == 0,
                  "13 shell h2s demoted to <div data-h>, no h3 left (%d, %d)"
                  % (tpl.count('data-h="2"'), tpl.count('data-h="3"'))))
results.append(ok(all('id="%s" data-nosnippet' % t in tpl for t in server._SHELL_TABS),
                  "the four non-guide tabs are data-nosnippet"))
home = server._render_index(None).decode("utf-8")
results.append(ok(home.count("<h2") >= 13 and "data-h=" not in home and "data-nosnippet" not in home
                  and '<h1 class="cardtitle" id="guideH1" hidden>Travel Guide</h1>' in home,
                  "the homepage keeps its real headings and the hidden guide h1"))

# --- the four tabs' words, out of the served guide (server.py _text_out) -----------
# Compared as a browser parses them (entities decoded, comments apart), against
# the same server with the switch off: what FX_GUIDE_TEXTOUT=0 serves.
class _Events(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ev, self.stack, self.wordy = [], [], []

    def handle_starttag(self, tag, attrs):
        self.ev.append(("<", tag, tuple(attrs)))
        if tag not in ("br", "img", "input", "hr", "wbr", "meta", "link", "source"):
            self.stack.append((tag, "picklabel" in (dict(attrs).get("class") or "").split()))

    def handle_endtag(self, tag):
        self.ev.append((">", tag))
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, d):
        self.ev.append(("", d))
        if re.search(r"[^\W_]", d) and not (self.stack and self.stack[-1][0] in ("script", "style")) \
                and not any(k for _t, k in self.stack):
            self.wordy.append(d.strip()[:40])

    def handle_comment(self, d):
        self.ev.append(("!", d))


def parsed(src, words=None):
    """src's parse events, each <!--tN--> swapped for words[N] when given."""
    p = _Events()
    p.feed(src)
    p.close()
    out = []
    for e in p.ev:
        if words is not None and e[0] == "!" and re.fullmatch(r"t\d+", e[1]):
            e = ("", words[int(e[1][1:])])
        if e[0] == "" and out and out[-1][0] == "":
            out[-1] = ("", out[-1][1] + e[1])
        else:
            out.append(e)
    return out, p.wordy


def tab_spans(page):
    return [(a, server._section_end(page, a))
            for a in (page.index('<section class="tab" id="%s"' % t) for t in server._SHELL_TABS)]


def served(textout):
    was = server.GUIDE_TEXTOUT
    server.GUIDE_TEXTOUT, server._guide_tpl = textout, None
    try:
        return (server._guide_template(), server._render_index(None),
                {i: server._render_index(i).decode("utf-8") for i in guides})
    finally:
        server.GUIDE_TEXTOUT, server._guide_tpl = was, None


def outside(page):
    """The page with the four tab sections cut out, as the list of pieces around them."""
    sp = tab_spans(page)
    return [page[b:c] for b, c in zip([0] + [e for _a, e in sp], [a for a, _e in sp] + [len(page)])]


def guide_tab(page):
    a = page.index('<section class="tab" id="tab-guide"')
    return page[a:server._section_end(page, a)]


TOK = lambda s: sorted(re.findall(r"\{\{[A-Z_]+\}\}", s))
SHELL = re.compile(r'<script type="application/json" id="shellText">(.*?)</script>\n  ', re.S)
tpl_on, home_on, on = served(True)
tpl_off, home_off, off = served(False)
bad_rest, bad_marks, bad_text, bad_words, words_n = [], [], [], [], set()
for iso in guides:
    page, ref = on[iso], off[iso]
    js = SHELL.findall(page)
    try:
        words = json.loads(js[0]) if len(js) == 1 else None
    except ValueError:
        words = None
    marks = sorted(int(n) for n in re.findall(r"<!--t(\d+)-->", page))
    if words is None or marks != list(range(len(words))) or '</script>\n  <script src="/app.js' not in page:
        bad_marks.append(iso)
        continue
    words_n.add(len(words))
    # Everything but the four tabs and the JSON block: the switch-off bytes.
    sp, rp = tab_spans(page), tab_spans(ref)
    if outside(SHELL.sub("", page)) != outside(ref):
        bad_rest.append(iso)
    # Parsed on 8 (the four tabs are the template's on every guide, and the
    # byte check above holds the rest of each page).
    if iso in ("CO", "GB-ENG", "GB-WLS", "JP", "EH", "AF", "PR", "TD"):
        for t, (a, b), (c, d) in zip(server._SHELL_TABS, sp, rp):
            got, left = parsed(page[a:b], words)
            if got != parsed(ref[c:d])[0]:
                bad_text.append(iso + " " + t)
            if left:
                bad_words.append((iso, t, left[:3]))
results.append(ok(not bad_marks and len(words_n) == 1,
                  "every guide: one #shellText (before app.js) that parses, and marks t0..t%d each used once %s"
                  % (max(words_n or {0}) - 1, bad_marks[:5] or "")))
results.append(ok(not bad_text, "8 guides: putting each mark back gives exactly the four tabs FX_GUIDE_TEXTOUT=0 "
                  "serves, tags, attributes and decoded text %s" % (bad_text or "")))
results.append(ok(not bad_words, "no letter or digit left in those tabs but scripts and .picklabel %s" % (bad_words or "")))
results.append(ok(not bad_rest, "every guide outside the four tabs and #shellText is the switch-off page byte for "
                  "byte %s" % (bad_rest[:5] or "")))
results.append(ok(all(guide_tab(on[i]) == guide_tab(off[i]) for i in guides),
                  "#tab-guide is byte-identical with the switch on and off"))
results.append(ok(home_on == home_off and not re.search(rb"<!--t\d|shellText", home_on),
                  "the homepage is identical either way and holds no marks"))
results.append(ok(TOK(tpl_off) == TOK(server._index_template())
                  and TOK(tpl_on) == [t for t in TOK(tpl_off) if t[2:-2] not in server._TEXTOUT_FILLED]
                  and all(server._HTML_DEFAULTS[k] in off["CO"] for k in server._TEXTOUT_FILLED),
                  "no {{TOKEN}} lost: the template keeps all but %s, filled with the guide's own (constant) value"
                  % ", ".join(server._TEXTOUT_FILLED)))
results.append(ok(all(not re.search(r"<!--t\d|shellText", off[i]) for i in guides),
                  "switch off: no marks and no #shellText (the guide as before)"))
LD = lambda page: re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
home_ld = [json.loads(b) for b in LD(home)]
results.append(ok([d.get("@type") for d in home_ld] == ["WebSite"]
                  and home_ld[0].get("url") == "https://wandergrade.com/",
                  "the homepage keeps its one WebSite JSON-LD block"))
one_h1, ld_bad = [], []
for iso in guides:
    page = server._render_index(iso).decode("utf-8")
    h1s = re.findall(r"<h1\b[^>]*>", page)
    if len(h1s) != 1 or "hidden" in h1s[0] or 'id="guideH1"' not in h1s[0] or rg.h1_html(iso) not in page:
        one_h1.append(iso)
    # None at all: the WebSite block is the homepage's, and FAQPage is gone.
    if LD(page) or "FAQPage" in page or "jsonld" in rg.render(iso):
        ld_bad.append(iso)
results.append(ok(not one_h1, "every raw guide page: exactly one h1, visible, = render_guide.h1_html %s"
                  % (one_h1[:5] or "")))
results.append(ok(not ld_bad, "no guide page carries JSON-LD (no FAQPage of invisible questions) %s" % (ld_bad[:5] or "")))

# --- curated vs weather wording ----------------------------------------------------
claim = []
for iso in guides:
    if (clim.get(iso) or {}).get("curated"):
        continue
    blob = " ".join([R[iso]["title"], R[iso]["desc"], R[iso]["body"],
                     facts[iso]["t"], facts[iso]["d"], facts[iso].get("dn", "")]).lower()
    if "best months to visit" in blob:
        claim.append(iso)
results.append(ok(not claim, "weather-only countries never say \"best months to visit\" %s" % (claim or "")))

# --- attribution ---------------------------------------------------------------------
ca_us = [i for i in guides if facts[i].get("src") == "ca" and "US State" in R[i]["desc"] + R[i]["body"]]
results.append(ok(not ca_us, "Canada-rated guides (PR, US, GU, FK…) are never called a US advisory %s" % (ca_us or "")))
co = R["CO"]
results.append(ok("💰 Local prices ≈ %d%% of the US (%s %d)" % (facts["CO"]["pct"], rg.MON[asof.month - 1], asof.year)
                  in co["body"] and "Safety · per US State Dept" in co["body"],
                  "Colombia: dated cost line, attributed safety line"))

# --- the client h1, run under jsc against the same snapshot --------------------------
def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""
def js_fn_const(name):   # `const name = (...) => ...;` — the statement, up to its line-ending ";"
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
prog = ("const _guideFacts = %s; const NAMES = %s; function countryName(i) { return NAMES[i]; }\n%s\n"
        "const out = {}; for (const i of Object.keys(NAMES)) out[i] = guideH1Text(i); print(JSON.stringify(out));"
        % (json.dumps(facts), json.dumps({i: names[i] for i in guides}), js_fn("guideH1Text")))
try:
    js_h1 = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception:
    js_h1 = {}
h1_drift = [i for i in guides if js_h1.get(i) != names[i] + " travel: " + rg.h1_topics(i)]
results.append(ok(js_h1 and not h1_drift and 'class="gname"' in js_fn("guideH1Html")
                  and 'class="gname"' in rg.h1_html("CO"),
                  "app.js guideH1Text() == render_guide's h1 for all %d guides %s" % (len(guides), h1_drift[:5] or "")))

gd = rg.generic_desc("BS")
results.append(ok(gd.startswith("What to do in the Bahamas, ")
                  and ('"What to do in " + countryNameInText(iso)\n    + "%s"' % gd[len("What to do in the Bahamas"):]) in APP,
                  "app.js guideMeta()'s fallback description is render_guide.generic_desc()"))

# --- _DEFAULT_META lockstep ----------------------------------------------------------
m = re.search(r"^const _DEFAULT_META = (\{.*?\});", APP, re.M | re.S)
try:
    out = subprocess.run([JSC, "-e", "print(JSON.stringify(%s))" % m.group(1)],
                         capture_output=True, text=True, timeout=30).stdout
    dm = json.loads(out)
except Exception:
    dm = {}
D = server._HTML_DEFAULTS
results.append(ok(dm == {"title": D["TITLE"], "desc": D["DESC"], "og": D["OGTITLE"]},
                  "app.js _DEFAULT_META == server _HTML_DEFAULTS TITLE/DESC/OGTITLE"))
# The Wander List's empty-state line: served in #visitedStats (VISITED_STATS)
# so the tab's first paint holds the 29px renderVisitedStats then writes.
# The real function runs under jsc with empty lists; the served copy differs
# by the "vstand" class only (styles.css stands it down for a returning
# visitor's floor), and a guide page serves none (its HTML is fixed).
tiers = re.search(r"^const MILESTONE_TIERS = \[.*?\];", APP, re.M | re.S)
try:
    out = subprocess.run([JSC, "-e", "const host = {}; const $ = () => host; const visited = new Set(), wishlist = new Set();\n"
                          "%s\n%s\n%s\nrenderVisitedStats(); print(host.innerHTML);"
                          % (js_fn_const("esc"), tiers.group(0) if tiers else "", js_fn("renderVisitedStats"))],
                         capture_output=True, text=True, timeout=30).stdout.strip()
except Exception:
    out = ""
served = D["VISITED_STATS"]
results.append(ok(out and 'class="vstats-line vstand"' in served and served.replace(' vstand"', '"') == out,
                  "server VISITED_STATS == app.js renderVisitedStats() for an empty list (%s)"
                  % (re.sub(r"<[^>]+>", " ", out).split() and " ".join(re.sub(r"<[^>]+>", " ", out).split()) or "jsc gave nothing")))
results.append(ok(b"vstand" in server._render_index(None) and b"vstand" not in server._render_index("TH"),
                  "the served line is on the homepage and not in a guide"))

# --- staleness guard -----------------------------------------------------------------
# render_guide reads the document through guide_facts.get_doc() on every call,
# so swapping that function in is how a test serves it a different document.
real_get_doc = GF.get_doc


def serve(doc):
    GF.get_doc = lambda: doc


try:
    old_asof = datetime.date.today() - datetime.timedelta(days=rg.STALE_DAYS + 1)
    serve(dict(facts, _asof=old_asof.isoformat()))
    rg._stale_warned = old_asof                   # keep the test output quiet
    stale = {iso: rg.render(iso) for iso in ("CO", "PR", "GB-ENG", "SO")}
    leaks = [i for i, r in stale.items()
             if re.search(r"\d+%|Level \d|As of", r["desc"] + r["body"]) or "💰" in r["body"]
             or "🛡️ Level" in r["body"]]
    results.append(ok(not leaks and stale["CO"]["desc"] == rg.meta_numberfree("CO")
                      and stale["CO"]["title"] == facts["CO"]["t"],
                      "past 90 days: no figure, level or date anywhere; the title keeps its question %s"
                      % (leaks or "")))
finally:
    GF.get_doc = real_get_doc

# --- snapshot age and per-guide lastmod ---------------------------------------------
# The committed file is the fallback (see the docstring): a healthy server
# serves its own daily recompute, so only an old fallback fails here.
age = (datetime.date.today() - asof).days
FALLBACK_MAX = rg.STALE_DAYS - 15
results.append(ok(age <= FALLBACK_MAX,
                  "the committed guide-facts.json (the fallback a deploy serves until its first daily "
                  "recompute) is %d days old, at most %d (figures drop out at day %d; to rebuild: "
                  "parity.py --refresh, then build_guide_facts.py)" % (age, FALLBACK_MAX, rg.STALE_DAYS)))
if 45 < age <= FALLBACK_MAX:
    print("  NOTE  the committed fallback is %d days old: rebuild it with the next deploy "
          "(fails from day %d)" % (age, FALLBACK_MAX + 1))
results.append(ok(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", facts[i].get("m", "")) for i in guides),
                  "every guide's snapshot entry carries its change date m"))
sm = server._sitemap().decode("utf-8")
lm = dict(re.findall(r"<loc>https://wandergrade\.com(/[^<]*)</loc><lastmod>([^<]+)</lastmod>", sm))
stamp = open(os.path.join(ROOT, "public", "content-stamp.txt"), encoding="utf-8").read().strip()[:10]
slug_of = {iso: s for s, iso in rg.all_slugs()}
results.append(ok(lm.get("/") == stamp and lm.get("/data") == stamp
                  and all(lm.get("/guide/" + slug_of[i]) == max(stamp, facts[i]["m"]) for i in guides),
                  "sitemap: \"/\" and \"/data\" at content-stamp %s, each guide at max(stamp, its m)" % stamp))
try:
    old = datetime.date.today() - datetime.timedelta(days=rg.STALE_DAYS + 5)
    serve(dict(facts, _asof=old.isoformat(), CO=dict(facts["CO"], m=old.isoformat())))
    rg._stale_warned = old
    exp = rg.snapshot_expired_on()
    sm2 = server._sitemap().decode("utf-8")
    results.append(ok(exp == old + datetime.timedelta(days=rg.STALE_DAYS + 1)
                      and ("/guide/%s</loc><lastmod>%s<" % (slug_of["CO"], max(stamp, exp.isoformat()))) in sm2,
                      "past 90 days a guide's lastmod moves to the day its figures dropped out"))
finally:
    GF.get_doc = real_get_doc

# --- Turkey (Türkiye): the second name, once, in the description only ----------------
# render_guide.ALSO_NAMED. Every rung of the ladder (Levels 1-3, fresh and
# number-free) names the country exactly once, as "Turkey (Türkiye)", within DESC_MAX;
# the served /guide/turkey has it in its description and nowhere else; no other guide
# says Türkiye in its title, description or h1; the name itself stays Turkey.
AKA = "Turkey (T\u00fcrkiye)"
rungs = [rg._desc("TR", dict(facts["TR"], adv=lv), asof) for lv in (None, 1, 2, 3)] + \
        [rg._desc("TR", {}, None), rg.meta("TR")["desc"], facts["TR"]["d"], facts["TR"]["dn"]]
# A rung that can't fit it (a Level 4 Turkey: 159) drops the second name, not the limit.
lv4 = rg._desc("TR", dict(facts["TR"], adv=4), asof)
results.append(ok(len(lv4) <= rg.DESC_MAX and lv4.count("Turkey") == 1 and "Do not travel" in lv4,
                  "a Level 4 Turkey drops the second name to fit: %s" % lv4))
results.append(ok(all(r.count(AKA) == 1 and r.count("Turkey") == 1 and len(r) <= rg.DESC_MAX for r in rungs),
                  "every TR description rung names it once as %r, within %d: %s" % (AKA, rg.DESC_MAX, rungs[6])))
tr_page = server._render_index("TR").decode("utf-8")
tr_desc = re.search(r'<meta name="description" content="([^"]*)"', tr_page).group(1)
results.append(ok(AKA in html.unescape(tr_desc)
                  and tr_page.count("T\u00fcrkiye") == len(re.findall(r'<meta (?:name|property)="(?:og:|twitter:)?description"', tr_page)),
                  "/guide/turkey: Türkiye only in its description (and that description's og/twitter copies)"))
results.append(ok(R["TR"]["title"] == facts["TR"]["t"] and "T\u00fcrkiye" not in R["TR"]["title"] + rg.h1_html("TR")
                  and names.get("TR") == "Turkey" and rg.name_in_text("TR") == "Turkey"
                  and not [i for i in guides if i != "TR" and "T\u00fcrkiye" in R[i]["title"] + R[i]["desc"] + rg.h1_html(i)],
                  "the title, h1 and country name stay Turkey; no other guide says Türkiye"))

# --- the title fallback (render_guide.TITLE_BEST_TIME): on for DO, MA and IM ---------
# Doug's call of 2026-11-05, after the Search Console read: "Best Time to Visit X"
# leads exactly the Dominican Republic's, Morocco's and the Isle of Man's titles,
# stored and served, within TITLE_MAX and unique, and each is word for word the
# title committed that day (BEST_TIME_TITLES: a ladder change that re-words one
# fails here, even with the stored copy re-worded to match); every other guide's
# is the title it has with the switch off (meta() switched off here), and a
# Level 4 guide keeps its safety question. Both modes are still exercised by
# switching it here, not by the default: off, scripts/retitle_guide_facts.py
# re-words exactly those three stored t's back; on for every guide, "Best Time
# to Visit X" leads every title but a Level 4 one and the script re-words
# exactly those stored t's, touching nothing else; TITLE_BEST_TIME_ONLY limits it.
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import retitle_guide_facts as RT  # noqa: E402
raw_facts = open(os.path.join(ROOT, "public", "guide-facts.json"), encoding="utf-8").read()
BEST_TIME_TITLES = {
    "DO": "Best Time to Visit the Dominican Republic: Weather & Costs",
    "IM": "Best Time to Visit the Isle of Man: Weather & Things to Do",
    "MA": "Best Time to Visit Morocco: Weather, Costs vs US & Safety",
}
BEST_TIME_ONLY = sorted(BEST_TIME_TITLES)
default = (rg.TITLE_BEST_TIME, rg.TITLE_BEST_TIME_ONLY)
figs = lambda i: {k: v for k, v in facts[i].items() if k not in ("t", "d", "dn", "m")}
same_but_t = lambda new: (all(dict(new[i], t=None) == dict(facts[i], t=None) for i in guides)
                          and {k: v for k, v in new.items() if k not in guides}
                          == {k: v for k, v in facts.items() if k not in guides})
lv4 = [i for i in guides if facts[i].get("adv") == 4]
try:
    rg.TITLE_BEST_TIME, rg.TITLE_BEST_TIME_ONLY = False, None
    off = {i: rg.meta(i, figs(i), asof)["title"] for i in guides}
    off_raw, off_changed = RT.retitle(raw_facts)
finally:
    rg.TITLE_BEST_TIME, rg.TITLE_BEST_TIME_ONLY = default
led = [i for i in guides if R[i]["title"].startswith("Best Time to Visit ")]
led_t = [i for i in guides if facts[i]["t"].startswith("Best Time to Visit ")]
results.append(ok(rg.TITLE_BEST_TIME is True and set(rg.TITLE_BEST_TIME_ONLY or ()) == set(BEST_TIME_ONLY)
                  and sorted(led) == sorted(led_t) == BEST_TIME_ONLY
                  and all(R[i]["title"] == facts[i]["t"] != off[i] and len(R[i]["title"]) <= rg.TITLE_MAX
                          and R[i]["title"].startswith("Best Time to Visit %s" % rg.name_in_text(i)) for i in BEST_TIME_ONLY)
                  and len({R[i]["title"] for i in BEST_TIME_ONLY}) == len(BEST_TIME_ONLY)
                  and all(R[i]["title"] == BEST_TIME_TITLES[i] for i in BEST_TIME_ONLY),
                  "on by default for exactly %s (stored %s, served %s): \"Best Time to Visit X\" leads, <= %d, "
                  "unique and word for word the 2026-11-05 titles: %s"
                  % (BEST_TIME_ONLY, sorted(led_t), sorted(led), rg.TITLE_MAX,
                     "; ".join("%s (%d)" % (R[i]["title"], len(R[i]["title"])) for i in BEST_TIME_ONLY))))
others = [i for i in guides if i not in BEST_TIME_ONLY and not (facts[i]["t"] == R[i]["title"] == off[i])]
results.append(ok(not others, "every other guide's stored and served title (%d) is the one it has with the switch off %s"
                  % (len(guides) - len(BEST_TIME_ONLY), others[:5] or "")))
results.append(ok(lv4 and all(R[i]["title"].startswith("Is %s Safe to Visit?" % rg.name_in_text(i)) for i in lv4),
                  "the %d Level 4 guides keep their safety question" % len(lv4)))
off_new = json.loads(off_raw)
results.append(ok(sorted(i for i, _old, _new in off_changed) == BEST_TIME_ONLY
                  and all(off_new[i]["t"] == off[i] for i in guides) and same_but_t(off_new)
                  and len(off_raw.splitlines()) == len(raw_facts.splitlines()),
                  "switched off, retitle_guide_facts re-words exactly %s back, nothing else"
                  % sorted(i for i, _old, _new in off_changed)))
try:
    rg.TITLE_BEST_TIME, rg.TITLE_BEST_TIME_ONLY = True, None
    on = {i: rg.meta(i, figs(i), asof)["title"] for i in guides}
    out, changed = RT.retitle(off_raw)
    new = json.loads(out)
    results.append(ok(all(len(t) <= rg.TITLE_MAX for t in on.values()) and len(set(on.values())) == len(guides)
                      and all(on[i].startswith("Best Time to Visit " + rg.name_in_text(i)) for i in guides if i not in lv4)
                      and all(on[i] == off[i] for i in lv4) and all(on[i] == facts[i]["t"] for i in BEST_TIME_ONLY),
                      "on for every guide: \"Best Time to Visit X\" leads %d titles, <= %d and unique; the %d Level 4 "
                      "guides keep their safety question (%s)" % (len(guides) - len(lv4), rg.TITLE_MAX, len(lv4), on.get("PT"))))
    results.append(ok(len(changed) == len(guides) - len(lv4)
                      and all(new[i]["t"] == on[i] for i in guides) and same_but_t(new)
                      and len(out.splitlines()) == len(raw_facts.splitlines()),
                      "on for every guide, retitle_guide_facts re-words exactly the switched-off file's t's (%d) to "
                      "meta(), nothing else" % len(changed)))
    rg.TITLE_BEST_TIME_ONLY = {"PT", "AU", "AF"}
    only = [i for i in guides if rg.meta(i, figs(i), asof)["title"] != off[i]]
    results.append(ok(sorted(only) == ["AU", "PT"],
                      "TITLE_BEST_TIME_ONLY limits it to its guides (Level 4 Afghanistan still keeps its own): %s" % only))
finally:
    rg.TITLE_BEST_TIME, rg.TITLE_BEST_TIME_ONLY = default

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

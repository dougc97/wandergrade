"""Guide titles, descriptions, headings and their client/server lockstep, over
every guide — no network, no server process.

    /usr/bin/python3 scripts/test_guide_meta.py

What it holds the code to:
  * every <title> <= 60 characters, every description <= 155; none repeated;
  * public/guide-facts.json's t/d/dn are exactly render_guide.meta() (the one
    implementation) — a stale or hand-edited file fails here;
  * app.js names every guide as country-names.json does (EXTRA_PLACES ->
    NAME_FIX -> climate.json's Natural Earth name), so client headings match
    the server's title, h1 and description;
  * the h1 is the same string on both sides, the raw page has exactly one h1
    and it is visible, and the /guide/ template carries no shell h2/h3;
  * weather-only countries never claim "best months to visit";
  * JSON-LD parses and has the expected types; the staleness guard drops every
    figure and advisory clause.
"""
import datetime
import html
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import render_guide as rg  # noqa: E402
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

# --- the snapshot file is meta()'s own output --------------------------------------
bad = []
for iso in guides:
    f = {k: v for k, v in facts[iso].items() if k not in ("t", "d", "dn")}
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
results.append(ok("const name = countryName(iso);" in APP.split("function renderActivity", 1)[1][:400]
                  and "Best time to visit ${esc(cname)}" in APP,
                  "renderActivity and renderCountryClimate name the country via countryName()"))

# --- h1: one, visible, identical on both sides -------------------------------------
results.append(ok('countryName(iso) + " travel: cost, safety & when to go"' in APP
                  and "guideH1Html(iso)" in APP, "app.js guideH1Text is the server's h1 string"))
h1_bad = []
for iso in guides:
    txt = re.sub(r"<[^>]+>", "", html.unescape(rg.h1_html(iso)))
    if txt != rg.flag_emoji(iso) + " " + names[iso] + " travel: cost, safety & when to go":
        h1_bad.append(iso)
results.append(ok(not h1_bad, "h1 text = flag + name + ' travel: cost, safety & when to go' %s" % (h1_bad or "")))
tpl = server._guide_template()
results.append(ok(not re.search(r"<h[23][\s>]", tpl), "the /guide/ template has no static h2/h3"))
results.append(ok(tpl.count('data-h="2"') == 14 and tpl.count('data-h="3"') == 2,
                  "14 shell h2s and 2 h3s demoted to <div data-h> (%d, %d)"
                  % (tpl.count('data-h="2"'), tpl.count('data-h="3"'))))
results.append(ok(all('id="%s" data-nosnippet' % t in tpl for t in server._SHELL_TABS),
                  "the four non-guide tabs are data-nosnippet"))
home = server._render_index(None).decode("utf-8")
results.append(ok(home.count("<h2") >= 14 and "data-h=" not in home and "data-nosnippet" not in home
                  and '<h1 class="cardtitle" id="guideH1" hidden>Travel Guide</h1>' in home,
                  "the homepage keeps its real headings and the hidden guide h1"))
one_h1, ld_bad = [], []
for iso in guides:
    page = server._render_index(iso).decode("utf-8")
    h1s = re.findall(r"<h1\b[^>]*>", page)
    if len(h1s) != 1 or "hidden" in h1s[0] or 'id="guideH1"' not in h1s[0] or rg.h1_html(iso) not in page:
        one_h1.append(iso)
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
            if d.get("@type") != "FAQPage" or not all(q.get("@type") == "Question"
                                                      and q["acceptedAnswer"].get("@type") == "Answer"
                                                      for q in d["mainEntity"]):
                ld_bad.append(iso)
        except ValueError:
            ld_bad.append(iso)
results.append(ok(not one_h1, "every raw guide page: exactly one h1, visible, = render_guide.h1_html %s"
                  % (one_h1[:5] or "")))
results.append(ok(not ld_bad, "every guide's JSON-LD parses as a FAQPage of Questions/Answers %s" % (ld_bad[:5] or "")))

# --- curated vs weather wording ----------------------------------------------------
claim = []
for iso in guides:
    if (clim.get(iso) or {}).get("curated"):
        continue
    blob = " ".join([R[iso]["title"], R[iso]["desc"], R[iso]["body"], R[iso]["jsonld"],
                     facts[iso]["t"], facts[iso]["d"], facts[iso].get("dn", "")]).lower()
    if "best months to visit" in blob:
        claim.append(iso)
results.append(ok(not claim, "weather-only countries never say \"best months to visit\" %s" % (claim or "")))

# --- attribution ---------------------------------------------------------------------
ca_us = [i for i in guides if facts[i].get("src") == "ca" and "US State" in R[i]["desc"] + R[i]["body"]]
results.append(ok(not ca_us, "Canada-rated guides (PR, US, GU, FK…) are never called a US advisory %s" % (ca_us or "")))
co = R["CO"]
results.append(ok("💰 Local prices ≈ %d%% of the US (%s %d)" % (facts["CO"]["pct"], rg.MON[asof.month - 1], asof.year)
                  in co["body"] and "Safety · per US State Dept" in co["body"]
                  and "Is Colombia safe to visit?" in co["jsonld"],
                  "Colombia: dated cost line, attributed safety line, safety FAQ"))

# --- _DEFAULT_META lockstep ----------------------------------------------------------
m = re.search(r"^const _DEFAULT_META = (\{.*?\});", APP, re.M | re.S)
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
try:
    out = subprocess.run([JSC, "-e", "print(JSON.stringify(%s))" % m.group(1)],
                         capture_output=True, text=True, timeout=30).stdout
    dm = json.loads(out)
except Exception:
    dm = {}
D = server._HTML_DEFAULTS
results.append(ok(dm == {"title": D["TITLE"], "desc": D["DESC"], "og": D["OGTITLE"]},
                  "app.js _DEFAULT_META == server _HTML_DEFAULTS TITLE/DESC/OGTITLE"))

# --- staleness guard -----------------------------------------------------------------
data = rg._load()
saved = data["facts"].get("_asof")
try:
    data["facts"]["_asof"] = (datetime.date.today() - datetime.timedelta(days=rg.STALE_DAYS + 1)).isoformat()
    rg._stale_warned = True                       # keep the test output quiet
    stale = {iso: rg.render(iso) for iso in ("CO", "PR", "GB-ENG", "SO")}
    leaks = [i for i, r in stale.items()
             if re.search(r"\d+%|Level \d|As of", r["desc"] + r["body"] + r["jsonld"]) or "💰" in r["body"]
             or "🛡️ Level" in r["body"]]
    results.append(ok(not leaks and stale["CO"]["desc"] == rg.meta_numberfree("CO")
                      and stale["CO"]["title"] == facts["CO"]["t"],
                      "past 90 days: no figure, level or date anywhere; the title keeps its question %s"
                      % (leaks or "")))
finally:
    data["facts"]["_asof"] = saved

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

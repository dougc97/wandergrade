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
  * names that take "the" have it inside every sentence, on both sides;
  * Level 3/4 titles ask "safe?", Level 4 never "cheap?" or "(very cheap)";
  * descriptions never end mid-phrase;
  * JSON-LD parses and has the expected types; the staleness guard drops every
    figure and advisory clause;
  * the COMMITTED snapshot is younger than STALE_DAYS - 15. It is only the
    fallback now — the server recomputes the document daily
    (fxtracker/guide_facts.py) — but it is what a fresh deploy serves until
    its first check and what a server whose inputs are down keeps serving, so
    it must not be close to dropping every figure itself. Past 45 days the
    test says so without failing;
  * every guide's sitemap <lastmod> is its own snapshot date; "/" and "/data"
    keep content-stamp.txt.
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
unsafe = [i for i in guides if facts[i].get("adv") in (3, 4)
          and not R[i]["title"].startswith("Is %s Safe" % rg.name_in_text(i))]
l3_cheap = [i for i in guides if facts[i].get("adv") == 3 and facts[i].get("band") in ("cheap", "very cheap")
            and "Safe & Cheap to Visit?" not in R[i]["title"]]
results.append(ok(not unsafe and not l3_cheap and sum(1 for i in guides if facts[i].get("adv") in (3, 4)) >= 40,
                  "every Level 3/4 title asks \"Is X Safe…\"; Level 3 cheap ones \"Safe & Cheap\" %s"
                  % ((unsafe + l3_cheap) or "")))
l4_band = [i for i in guides if facts[i].get("adv") == 4
           and re.search(r"\((very cheap|cheap|about the same|pricey)", R[i]["desc"] + R[i]["jsonld"])]
results.append(ok(not l4_band, "no Level 4 description or FAQ gives a bargain band %s" % (l4_band or "")))
no_cost_t = [i for i in guides if "pct" in facts[i] and facts[i].get("adv") in (None, 1, 2)
             and "Costs vs US" not in R[i]["title"]
             and len("Is %s %s to Visit? Costs vs US" % (rg.name_in_text(i), rg._band_q(facts[i]))) <= rg.TITLE_MAX]
results.append(ok(not no_cost_t, "price titles say \"Costs vs US\" wherever it fits %s" % (no_cost_t or "")))

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
    blob = " ".join([R[iso]["title"], R[iso]["desc"], R[iso]["body"], R[iso]["jsonld"], facts[iso].get("dn", "")])
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

# --- the client h1, run under jsc against the same snapshot --------------------------
def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
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
             if re.search(r"\d+%|Level \d|As of", r["desc"] + r["body"] + r["jsonld"]) or "💰" in r["body"]
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

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

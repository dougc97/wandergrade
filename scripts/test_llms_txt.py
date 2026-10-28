"""/llms.txt says only true things about the site: every guide in the
sitemap's slug list is linked once with its display name, every link is on the
canonical origin, and every link parameter and value it documents is one
public/app.js actually reads (so a renamed parameter fails here, not silently
in an assistant's answer).

    /usr/bin/python3 scripts/test_llms_txt.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import llms_txt, render_guide   # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
SERVER = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()

slugs = render_guide.all_slugs()
txt = llms_txt.build(slugs, render_guide.name_for_iso)
lines = txt.splitlines()

results.append(ok(lines[0] == "# WanderGrade", "starts with the H1 the llmstxt.org format asks for"))
results.append(ok(any(l.startswith("> ") for l in lines[1:4]), "a one-paragraph > summary follows the H1"))

guide_links = re.findall(r"^- \[([^\]]+)\]\((https://wandergrade\.com/guide/([a-z0-9-]+))\)$", txt, re.M)
linked = [g[2] for g in guide_links]
results.append(ok(sorted(linked) == sorted(s for s, _ in slugs),
                  "the guide index links every slug exactly once (%d of %d)" % (len(set(linked)), len(slugs))))
results.append(ok(all(n == (render_guide.name_for_iso(i) or n) for (n, _, s), (_, i) in
                      zip(sorted(guide_links, key=lambda g: g[2]), sorted(slugs))),
                  "each guide link reads the country's display name"))
results.append(ok(("%d in all" % len(slugs)) in txt, "the guide count in the text is the real one (%d)" % len(slugs)))

urls = re.findall(r"https?://[^\s)`]+", txt)
results.append(ok(all(u.startswith("https://wandergrade.com") for u in urls), "every URL is on https://wandergrade.com (%d)" % len(urls)))

# Documented link parameters: each must be read by app.js.
for param in ["vmn", "vmf", "vo", "hc", "vr", "pc", "sf", "vmm", "tab"]:
    results.append(ok(("?" + param + "=") in txt or ("&" + param + "=") in txt, "documents ?%s=" % param))
    results.append(ok(re.search(r'get\("%s"\)' % param, APP) is not None, "app.js reads ?%s=" % param))
regions = re.search(r"^const REGIONS = \{(.*?)\};", APP, re.M | re.S).group(1)
for code in ["AMER", "EUR", "MENA", "ASIA", "AFRICA", "OCEANIA"]:
    results.append(ok(code in txt and re.search(r"\b%s:" % code, regions) is not None, "region code %s is app.js's" % code))
for tab in ["guide", "trip", "visited", "data"]:
    results.append(ok('data-tab="%s"' % tab in open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read(),
                      "tab=%s is a real tab" % tab))
results.append(ok('vmm") === "weather"' in APP, "vmm=weather is the value app.js checks"))
results.append(ok('["a", "b", "any"].includes(sharedQ.get("sf"))' in APP, "sf takes a, b or any"))

# The cross-country pages, each linked once: the month lists by their hub
# (the twelve months named by their URL pattern, not twelve more links) and
# the dollar page.
for path in ("/safe-and-cheap", "/do-not-travel", "/cheapest", "/dollar-strength", "/privacy"):
    results.append(ok(txt.count("](https://wandergrade.com%s)" % path) == 1, "links %s once" % path))
results.append(ok("https://wandergrade.com/cheapest/january to https://wandergrade.com/cheapest/december" in txt
                  and "50% of US prices" in txt and "weather score of 70" in txt,
                  "the month lists' entry names the month URLs and the rule's numbers"))
from fxtracker import render_cheapest  # noqa: E402
results.append(ok(render_cheapest.MAX_PCT == 50 and render_cheapest.MIN_WX == 70
                  and render_cheapest.US_LEVELS == (1, 2) and "U.S. Level 1 or 2" in txt,
                  "the entry's numbers are render_cheapest's rule"))
results.append(ok("render_cheapest.HUB" in SERVER and "render_cheapest.PATHS" in SERVER,
                  "server.py routes the month lists"))
results.append(ok("inflation" in txt.split("/dollar-strength)", 1)[1].split("\n", 1)[0]
                  and "before inflation" in txt.split("/dollar-strength)", 1)[1].split("\n", 1)[0],
                  "the dollar page's entry says after inflation, and the index before it"))

# What renders without JavaScript: the homepage's one served view and the guides'
# grades, as fxtracker/home_picks.py and guide_lines.py build them.
from fxtracker import home_picks, guide_lines  # noqa: E402
results.append(ok(home_picks.PICK_COUNT == 5 and home_picks.FLEX_MONTHS == 6 and "_home_picks()" in SERVER
                  and "the five best-value popular destinations for a traveller from the US" in txt
                  and "best month of the next six" in txt and "the top five" in txt,
                  "the homepage entry says what home_picks serves: the US's top five over the next six months"))
results.append(ok("_guide_lines(" in SERVER and hasattr(guide_lines, "grades") and hasattr(guide_lines, "fares")
                  and "first month of the next six" in txt and "round-trip fare for each departure month" in txt,
                  "the guides' entry says what guide_lines serves: the grades and the fares by month"))
results.append(ok("table is empty" not in txt and "for several minutes after the site restarts" in txt,
                  "no longer says the homepage table is empty; says when the served parts can be missing"))

results.append(ok('path == "/llms.txt"' in SERVER and "llms_txt.build(render_guide.all_slugs()" in SERVER,
                  "server.py serves it from the sitemap's slug list"))

n_fail = results.count(False)
print("%d/%d passed" % (len(results) - n_fail, len(results)))
sys.exit(1 if n_fail else 0)

#!/usr/bin/env python3
"""The two list pages (fxtracker/render_lists.py), rendered from hand-made
fixtures — no network, no server process.

    /usr/bin/python3 scripts/test_list_pages.py

What it holds the code to:
  * /safe-and-cheap membership is the rule (US Level 1 and pct <= 60), sorted
    by price; the "all three agree" mark lands exactly where Canada and
    Germany are at their lowest level; a gap-fill ("via") never counts as a
    US rating; subdivisions (GB-ENG) never appear;
  * "Nearly made it" is US Level 2 and pct < 50, with the US risk chips;
  * an ISO on pl_history's "alt" list is footnoted, not dropped; the price
    band is visible text on the row, not a tooltip;
  * /do-not-travel sorts the three groups right (all three / one or two /
    Level 3), counts them in the intro, dates the recent changes from the
    advhistory stamps and the US feed's own words, and prints each feed's
    date;
  * a missing feed still renders, says so (grammar right for two), and
    reports `degraded`; a feed whose refresh is failing (`stale`) is noted by
    its fetch time, to the hour, and degrades the page too; the US feed
    down with the snapshot's US levels standing in is a full list, still
    available; only no US levels at all, or no prices, is unavailable (the
    server's 503) and says "isn't available right now", never a count of 0;
  * titles <= 60 characters, descriptions <= 157, exactly one h1, no class
    or id an ad blocker would hide, every /guide/ link a real slug, HTML
    that html.parser accepts, no "None" in the text, the as-of dates on the
    page, and the sitemap lastmods are the data's dates (never today).
"""
import html.parser
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import render_guide as rg, render_lists as RL  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def item(iso, level, src, **kw):
    words = {"us": ["Exercise Normal Precautions", "Exercise Increased Caution", "Reconsider Travel", "Do Not Travel"],
             "ca": ["Take normal security precautions", "Exercise a high degree of caution",
                    "Avoid non-essential travel", "Avoid all travel"],
             "de": {1: "Keine Warnung (no warning)", 2: "Teilreisewarnung (warning for some regions)",
                    4: "Reisewarnung (avoid travel)"}}
    text = words[src][level] if src == "de" else words[src][level - 1]
    return dict({"iso": iso, "country": iso, "level": level, "level_text": text, "link": "https://x/" + iso}, **kw)


def payload(src, rows):
    return {"items": rows, "count": len(rows), "source": src, "source_name": src}


# --- fixtures ---------------------------------------------------------------------
# Vietnam L1/27%: on the list, Canada says caution (no agree mark). Laos
# L1/21%: all three lowest (mark). Turkmenistan L1/45% on the alt list, and
# Canada's caution keeps it off the agree mark too.
# Portugal L1/60%: the boundary, in. Poland L1/61%: just out. Puerto Rico:
# Canada's L1 fills the US gap ("via") — never a US rating. Albania L2/40%:
# nearly made it, with reasons. Egypt L2/55%: too pricey for "nearly".
# Afghanistan L4 x3; Chad L4 US only; Venezuela L4 Canada only; Colombia L3
# US and CA; Palestine L4 US+DE, no Canada row.
US = payload("us", [
    item("VN", 1, "us", updated="2026-06-24", risks=[], summary="Exercise normal precautions in Vietnam."),
    item("LA", 1, "us", updated="2026-09-04", risks=[]),
    item("TM", 1, "us", updated="2026-03-01", risks=[]),
    item("PT", 1, "us", updated="2026-01-10", risks=[]),
    item("PL", 1, "us", updated="2026-01-10", risks=[]),
    item("AL", 2, "us", updated="2026-05-05", risks=["Crime", "Unrest"], summary="Exercise increased caution in Albania due to crime and unrest."),
    item("EG", 2, "us", updated="2026-05-05", risks=["Terrorism"]),
    item("AF", 4, "us", updated="2026-02-20", risks=["Terrorism", "Kidnapping"], summary="Do not travel to Afghanistan due to terrorism and kidnapping."),
    item("TD", 4, "us", updated="2026-04-28", risks=["Crime", "Terrorism"]),
    item("VE", 3, "us", updated="2026-06-27", risks=["Crime"]),
    item("CO", 3, "us", updated="2026-07-01", risks=["Crime", "Terrorism", "Kidnapping"]),
    item("PS", 4, "us", updated="2026-08-26", risks=["Terrorism", "Unrest"]),
    # The feed's own words: lowered to Level 2, dated by its publish date.
    item("NC", 2, "us", updated="2026-09-21", change="down", risks=["Crime"]),
    item("PR", 1, "ca", via="ca", via_name="Global Affairs Canada"),
])
CA = payload("ca", [
    item("VN", 2, "ca"), item("LA", 1, "ca"), item("TM", 2, "ca"), item("PT", 1, "ca"), item("PL", 1, "ca"),
    item("AL", 2, "ca"), item("EG", 2, "ca"), item("AF", 4, "ca"),
    # WanderGrade's record saw Chad move 3 -> 4 and back: today it is 3, raised on 2026-09-30.
    item("TD", 3, "ca", changed="2026-09-30", change="up"),
    item("VE", 4, "ca", changed="2026-08-15", change="up"), item("CO", 3, "ca"), item("NC", 1, "ca"),
    item("PR", 1, "ca"),
])
DE = payload("de", [
    item("VN", 1, "de", updated="2026-02-02"), item("LA", 1, "de", updated="2026-02-02"),
    item("TM", 1, "de", updated="2026-02-02"), item("PT", 1, "de", updated="2026-02-02"),
    item("PL", 1, "de", updated="2026-02-02"), item("AL", 1, "de", updated="2026-02-02"),
    item("EG", 2, "de", updated="2026-02-02"), item("AF", 4, "de", updated="2026-08-19"),
    item("TD", 2, "de", updated="2026-08-31"), item("VE", 2, "de", updated="2026-08-31"),
    item("CO", 1, "de", updated="2026-08-31"), item("PS", 4, "de", updated="2026-09-01"),
    item("NC", 1, "de", updated="2026-08-31"),
])
FACTS = {"_asof": "2026-09-28",
         "VN": {"pct": 27, "band": "very cheap", "adv": 1, "src": "us"},
         "LA": {"pct": 21, "band": "very cheap", "adv": 1, "src": "us"},
         "TM": {"pct": 45, "band": "very cheap", "adv": 1, "src": "us"},
         "PT": {"pct": 60, "band": "cheap", "adv": 1, "src": "us"},
         "PL": {"pct": 61, "band": "cheap", "adv": 1, "src": "us"},
         "AL": {"pct": 40, "band": "very cheap", "adv": 2, "src": "us"},
         "EG": {"pct": 55, "band": "cheap", "adv": 2, "src": "us"},
         "AF": {"pct": 17, "band": "very cheap", "adv": 4, "src": "us"},
         "PR": {"pct": 30, "band": "very cheap", "adv": 1, "src": "ca"},
         # A subdivision carries the UK's figures and is never a row.
         "GB-ENG": {"pct": 20, "band": "very cheap", "adv": 1, "src": "us", "plof": "GB", "advof": "GB"}}
CLIM = {"VN": {"best": [2, 3, 4, 11], "curated": True}, "LA": {"best": [10, 11, 3, 4], "curated": False},
        "TM": {"best": [4, 5, 9]}, "PT": {"best": [5, 6, 9, 10], "curated": True}}
HEALTH = {"built": "2026-09-30", "c": {"VN": {"h": ["Dengue", "Malaria"], "a": ["Malaria"]},
                                       "LA": {"h": []}, "PT": {"h": []}}}
PLH = {"alt": ["TM", "VE"], "years": [], "pl": {}}
FETCHED = {"us": 1791300000, "ca": 1791300100, "de": 1791300200}   # 2026-10-06 UTC
TODAY = "2026-10-06"


class Check(html.parser.HTMLParser):
    """Counts h1s, collects class/id names, hrefs and text; raises on a
    parse error so a stray '<' in a name can't pass."""
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.names = []
        self.hrefs = []
        self.text = []
        self.open = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h1":
            self.h1 += 1
        for k in ("class", "id"):
            if a.get(k):
                self.names += a[k].split()
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag not in ("br", "meta", "link", "img", "input"):
            self.open.append(tag)

    def handle_endtag(self, tag):
        if self.open and self.open[-1] == tag:
            self.open.pop()
        else:
            raise ValueError("unbalanced </%s> (open: %s)" % (tag, self.open[-3:]))

    def handle_data(self, data):
        self.text.append(data)

    def error(self, message):
        raise ValueError(message)


FORBIDDEN = re.compile(r"^(ad|adv|sponsor|banner|promo)|advert", re.I)


def hygiene(page, label):
    """The checks every page passes: lengths, one h1, names, links, parse, text."""
    c = Check()
    c.feed(page["html"])
    c.close()
    results.append(ok(len(page["title"]) <= RL.TITLE_MAX, "%s: title %d chars <= %d: %r" % (label, len(page["title"]), RL.TITLE_MAX, page["title"])))
    results.append(ok(len(page["desc"]) <= RL.DESC_MAX, "%s: description %d chars <= %d: %r" % (label, len(page["desc"]), RL.DESC_MAX, page["desc"])))
    results.append(ok(c.h1 == 1, "%s: exactly one h1 (%d)" % (label, c.h1)))
    bad = sorted({n for n in c.names if FORBIDDEN.search(n)})
    results.append(ok(not bad, "%s: no class or id an ad blocker hides %s" % (label, bad or "")))
    guides = [h for h in c.hrefs if h.startswith("/guide/")]
    dead = [h for h in guides if not rg.iso_for_slug(h[len("/guide/"):])]
    results.append(ok(guides and not dead, "%s: %d /guide/ links, every one a real slug %s" % (label, len(guides), dead or "")))
    results.append(ok(not c.open, "%s: html.parser accepts it, every tag closed %s" % (label, c.open or "")))
    text = " ".join(c.text)
    results.append(ok("None" not in text and "None" not in page["title"] + page["desc"],
                      "%s: no \"None\" in the text" % label))
    results.append(ok(page["html"].count("<script") == 0, "%s: no JavaScript in the body" % label))
    results.append(ok("6 Oct 2026" in text, "%s: the feeds' fetch times are printed" % label))
    return c, text


# --- /safe-and-cheap ----------------------------------------------------------------
fx = {"VND": 4.0, "LAK": -2.0, "EUR": 1.5}
ppp = {"VN": {"infl": 3.5, "infl_year": 2025}, "LA": {"infl": 4.0, "infl_year": 2025}, "PT": {"infl": 2.0, "infl_year": 2025},
       "US": {"infl": 3.0, "infl_year": 2025}}
S = RL.safe_and_cheap(US, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, fx=fx, ppp=ppp, today=TODAY)
c, text = hygiene(S, "/safe-and-cheap")
results.append(ok(S["isos"]["safe"] == ["LA", "VN", "TM", "PT"],
                  "rule: US Level 1 and pct <= 60, by price (Poland at 61 out, Portugal at 60 in, Puerto "
                  "Rico's Canadian fill out, GB-ENG out): %s" % S["isos"]["safe"]))
results.append(ok(S["counts"] == {"safe": 4, "agree": 2, "near": 1}, "counts %s" % S["counts"]))
results.append(ok(S["isos"]["agree"] == ["LA", "PT"] and S["html"].count("all three agree") == 2,
                  "the agree mark where Canada and Germany are at their lowest level (Laos, Portugal), "
                  "not Vietnam or Turkmenistan (Canada: high degree of caution)"))
results.append(ok(re.search(r"<strong>4</strong> countries qualify", S["html"]) and "<strong>2</strong> of them" in S["html"],
                  "the intro's counts are the rows'"))
results.append(ok(S["isos"]["near"] == ["AL"] and "Nearly made it" in S["html"]
                  and re.search(r'/guide/albania.*?<span class="risk">Crime</span><span class="risk">Unrest</span>', S["html"], re.S),
                  "Nearly made it: US Level 2 under 50% (Albania, not Egypt at 55), with the US risk chips"))
tm = re.search(r'<tr>.*?/guide/turkmenistan.*?</tr>', S["html"], re.S).group(0)
results.append(ok('45%<sup class="fn">†</sup>' in tm and RL.ALT_NOTE in S["html"]
                  and RL.ALT_NOTE.startswith("† at the official exchange rate") and "market exchange rate" not in text,
                  "Turkmenistan: on the list, its † saying the price is at the official rate (TMT 3.5, what the "
                  "figure divides by), not the market one"))
# Liberia sits on the alt list only because the World Bank's unit for it is the dollar
# (pricelevel.PPP_UNIT): its price divides by no exchange rate, so no † and no note.
US_LR = payload("us", US["items"] + [item("LR", 1, "us", updated="2026-03-01", risks=[])])
SL = RL.safe_and_cheap(US_LR, CA, DE, dict(FACTS, LR={"pct": 49, "band": "very cheap", "adv": 1, "src": "us"}),
                       CLIM, HEALTH, {"alt": ["LR"], "years": [], "pl": {}}, fetched=FETCHED, today=TODAY)
lr = re.search(r'<tr>.*?/guide/liberia.*?</tr>', SL["html"], re.S)
results.append(ok(lr and "49%" in lr.group(0) and '<sup class="fn">†</sup>' not in SL["html"]
                  and RL.ALT_NOTE not in SL["html"],
                  "Liberia (priced in the World Bank's dollar unit, no exchange rate): listed with no † and no note"))
bt = re.search(r'<tr>.*?/guide/laos.*?</tr>', S["html"], re.S).group(0)
results.append(ok('21% <span class="band">very cheap</span>' in bt and 'title="Very cheap"' not in S["html"]
                  and '60% <span class="band">cheap</span>' in re.search(r'<tr>.*?/guide/portugal.*?</tr>', S["html"], re.S).group(0),
                  "the price band is visible text beside the number, not a tooltip"))
vn = re.search(r'<tr>.*?/guide/vietnam.*?</tr>', S["html"], re.S).group(0)
results.append(ok("Normal precautions" in vn and "High degree of caution" in vn and "No warning" in vn,
                  "each government's level in its own words on the row"))
results.append(ok("February–April and November" in vn and "weather: March, April, October and November" in
                  re.search(r'<tr>.*?/guide/laos.*?</tr>', S["html"], re.S).group(0),
                  "best months: curated as such, else the best-weather months, as the guide claims them"))
results.append(ok('<span class="hnote">Dengue</span><span class="hnote" title="in certain areas">Malaria*</span>' in vn
                  and "only the usual" in re.search(r'<tr>.*?/guide/laos.*?</tr>', S["html"], re.S).group(0),
                  "Canada's health notes where the document has them, areas marked"))
results.append(ok("Dollar vs 1-yr avg" in S["html"] and re.search(r'data-l="Dollar vs 1-yr avg"><span class="v">[+-]\d+\.\d%<', vn),
                  "the inflation-adjusted dollar column from the cached rates"))
# The dollar column as app.js signedPct prints it (a true minus, "0.0%" unsigned), and a
# country with no inflation figure (Turkmenistan: TMT pegged, no "infl") ‡-marked with the
# /dollar-strength note's words: its figure is the exchange-rate move alone.
SX = RL.safe_and_cheap(US, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED,
                       fx=dict(fx, TMT=0.0), ppp=ppp, today=TODAY)
cell = lambda page, slug: re.search(r'<tr>.*?/guide/%s.*?data-l="Dollar vs 1-yr avg"><span class="v">(.*?)</span></td>'
                                    % slug, page["html"], re.S).group(1)
results.append(ok(cell(SX, "laos") == "\u22122.5%" and cell(SX, "vietnam").startswith("+")
                  and "%+." not in SX["html"] and not re.search(r'data-l="Dollar vs 1-yr avg"><span class="v">-', SX["html"]),
                  "the dollar column's minus is U+2212: Laos %r" % cell(SX, "laos")))
results.append(ok(cell(SX, "turkmenistan").endswith('>0.0%</span><sup class="fn">‡</sup>')
                  and "No inflation figure for Turkmenistan" in cell(SX, "turkmenistan")
                  and RL.NO_INFL_NOTE in SX["html"] and RL.NO_INFL_NOTE not in S["html"]
                  and "‡" not in cell(SX, "vietnam") and SX["html"].count("‡") == 2,
                  "Turkmenistan (no inflation figure): \"0.0%‡\", never \"+0.0%\" as if after inflation, and the "
                  "‡ note; no mark or note where every figure is adjusted"))
# The rank rides in the name on a phone card, where # is hidden (as /cheapest's .rk).
results.append(ok(re.search(r'<td class="name" data-l="Country"><span class="rk">1\.</span> \S+ <a href="/guide/laos"', S["html"])
                  and re.search(r'<span class="rk">4\.</span> \S+ <a href="/guide/portugal"', S["html"])
                  and re.search(r'<span class="rk">1\.</span> \S+ <a href="/guide/albania"', S["html"]),
                  "each row's rank rides in its name cell, both tables"))
css = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
wide = css[css.index("  .listtable thead { display: table-header-group; }"):]
results.append(ok(".listtable .rk { color: var(--gray)" in css
                  and "  .listtable .rk { display: none; }" in wide[:wide.index("\n}\n")],
                  "CSS: the card rank shows on every list table below 1024px and hides where # shows"))
S2 = RL.safe_and_cheap(US, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok("Dollar vs 1-yr avg" not in S2["html"] and S2["counts"] == S["counts"],
                  "without cached rates the dollar column is left out, nothing else changes"))
results.append(ok("Prices: WanderGrade's daily snapshot as of 28 Sep 2026" in text and "as of 30 Sep 2026" in text
                  and "newest advisory dated 21 Sep 2026" in text and "newest advisory dated 1 Sep 2026" in text,
                  "as-of dates: the snapshot, the health document, each feed's newest advisory"))
results.append(ok(S["lastmod"] == "2026-09-28" and not S["degraded"], "lastmod is the snapshot date; not degraded"))
results.append(ok(S["title"] == "Safest Cheap Countries to Visit in 2026 (Data, Not Opinion)", "the title: %r" % S["title"]))

# A feed down: the page still renders, says so, is degraded.
S3 = RL.safe_and_cheap(US, None, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok(S3["degraded"] and "Global Affairs Canada feed is not available" in S3["html"]
                  and S3["html"].count("not loaded") >= 4 and S3["counts"]["safe"] == 4 and S3["counts"]["agree"] == 0,
                  "Canada down: renders, says so, degraded, column reads \"not loaded\", no agree marks"))
S4 = RL.safe_and_cheap(None, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok(S4["degraded"] and S4["isos"]["safe"] == ["LA", "VN", "TM", "PT"]
                  and "daily snapshot of 28 Sep 2026" in S4["html"],
                  "US down: the snapshot's US levels stand in, dated, and the page is degraded"))
results.append(ok(S4["available"] is True and S3["available"] is True and S["available"] is True,
                  "US down with the snapshot standing in: a full list, available (200 no-store, as /cheapest), "
                  "never a 503"))
# No list to draw: no US levels from the feed or the snapshot, or no prices.
# Only then is the page unavailable (the server's 503, review #4), and it says
# so: never a count of 0 or "No country meets the rule", in the page or the
# description.
no_us = {k: dict(v, src="ca") if isinstance(v, dict) and v.get("src") == "us" else v for k, v in FACTS.items()}
S8 = RL.safe_and_cheap(None, CA, DE, no_us, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
S9 = RL.safe_and_cheap(US, CA, DE, {}, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
S10 = RL.safe_and_cheap(None, CA, DE, None, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
blank = lambda pg: ("No country meets" not in pg["html"] and "None today" not in pg["html"]
                    and "<strong>0</strong>" not in pg["html"] and not re.match(r"0 ", pg["desc"])
                    and "Nearly made it" not in pg["html"] and pg["degraded"] and pg["available"] is False)
results.append(ok(blank(S8) and "isn't available right now: the US levels are not loaded" in S8["html"]
                  and "daily snapshot of" not in S8["html"],
                  "no US feed and no snapshot US levels: unavailable, \"the US levels are not loaded\", no rows"))
results.append(ok(blank(S9) and "isn't available right now: prices are not loaded" in S9["html"]
                  and "daily price snapshot is not available" in S9["html"],
                  "the US feed but no price snapshot: unavailable, \"prices are not loaded\", no rows"))
results.append(ok(blank(S10) and len(S10["desc"]) <= RL.DESC_MAX and "<h1>" in S10["html"],
                  "no feed and no snapshot at all: unavailable, the page still renders with its h1 (%r)" % S10["desc"]))
S5 = RL.safe_and_cheap(US, None, None, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok("Global Affairs Canada and German Federal Foreign Office (Auswärtiges Amt) feeds are not available right now, "
                  "so their columns read “not loaded”: this page is served uncached until they are back." in S5["html"]
                  and "feed is not available right now, so its column reads" in S3["html"],
                  "the missing-feed note reads right for one feed and for two"))
# A feed whose refresh is failing: the last good copy is served, the page
# says so by the fetch time (to the hour) and counts as degraded; a stale
# age for a feed that is missing altogether is ignored (nothing is served).
S6 = RL.safe_and_cheap(US, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, fx=fx, ppp=ppp,
                       stale={"us": 7 * 3600 + 100}, today=TODAY)
results.append(ok(S6["degraded"] and S6["counts"] == S["counts"]
                  and "U.S. State Department: fetched 6 Oct 2026 15:20 UTC, refresh failing, showing the copy from "
                      "7h ago, newest advisory dated 21 Sep 2026" in S6["html"]
                  and "refresh failing" not in S["html"],
                  "a failing refresh is noted next to the fetched time and degrades the page; absent otherwise"))
S7 = RL.safe_and_cheap(US, None, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, stale={"ca": 99999}, today=TODAY)
results.append(ok("refresh failing" not in S7["html"] and "Global Affairs Canada feed is not available" in S7["html"],
                  "a stale age for a feed that is missing is ignored: the missing note stands alone"))
results.append(ok([RL._age(a) for a in (6 * 3600, 7 * 3600 + 3599, 47 * 3600, 2 * 86400, 3 * 86400 + 5, "x")]
                  == ["6h", "7h", "47h", "2d", "3d", ""],
                  "_age: hours under two days, then days, '' for junk"))

# --- /do-not-travel -----------------------------------------------------------------
D = RL.do_not_travel(US, CA, DE, fetched=FETCHED, today=TODAY)
c, text = hygiene(D, "/do-not-travel")
results.append(ok(D["isos"] == {"all3": ["AF"], "some4": ["PS", "TD", "VE"], "l3": ["CO"]},
                  "groups: all three / one or two (Chad US-only, Venezuela Canada-only, Palestine US+DE) / "
                  "Level 3 (Colombia; never a Level 4 country): %s" % D["isos"]))
results.append(ok(D["counts"] == {"any4": 4, "all3": 1, "some4": 3, "l3": 1, "changes": 3}, "counts %s" % D["counts"]))
results.append(ok("<strong>4</strong> countries are" in D["html"] and "<strong>1</strong> for all three" in D["html"]
                  and "<strong>3</strong> for one or two" in D["html"] and "A further <strong>1</strong>" in D["html"],
                  "the intro's counts are the groups'"))
chg = re.search(r'<ul class="changes">(.*?)</ul>', D["html"], re.S).group(1)
dates = re.findall(r'<span class="when">([^<]+)</span>', chg)
results.append(ok(dates == ["30 Sep 2026", "21 Sep 2026", "15 Aug 2026"],
                  "recent changes newest first, from the advhistory stamps and the US feed's words: %s" % dates))
results.append(ok("raised to" in chg and "lowered to" in chg and "/guide/chad" in chg and "New Caledonia" in chg,
                  "each change names the country, the government and the direction"))
td = re.search(r'<tr>.*?/guide/chad.*?</tr>', D["html"], re.S).group(0)
results.append(ok("Do not travel" in td and "Avoid non-essential travel" in td and "Some regions" in td
                  and "28 Apr 2026" in td and "↑ since 30 Sep 2026" in td and "31 Aug 2026" in td
                  and '<span class="risk">Crime</span><span class="risk">Terrorism</span>' in td,
                  "Chad's row: three governments in their words, each feed's date, the recorded change, US risk chips"))
ps = re.search(r'<tr>.*?Palestin.*?</tr>', D["html"], re.S)
results.append(ok(ps and "no rating" in ps.group(0), "Palestine: Canada publishes no rating, and the row says so"))
results.append(ok(D["lastmod"] == "2026-09-30" and not D["degraded"], "lastmod is the newest change the payloads carry"))
results.append(ok(D["title"] == "Do Not Travel List 2026: US, Canada & Germany Compared", "the title: %r" % D["title"]))
D2 = RL.do_not_travel(US, CA, None, fetched=FETCHED, today=TODAY)
results.append(ok(D2["degraded"] and "German Federal Foreign Office" in D2["html"] and "not loaded" in D2["html"]
                  and D2["isos"]["all3"] == [] and "AF" in D2["isos"]["some4"],
                  "Germany down: renders, degraded, nothing can be \"all three\""))
D4 = RL.do_not_travel(US, CA, DE, fetched=FETCHED, stale={"de": 6 * 3600 + 1}, today=TODAY)
results.append(ok(D4["degraded"] and D4["counts"] == D["counts"]
                  and "German Federal Foreign Office (Auswärtiges Amt): fetched 6 Oct 2026 15:23 UTC, refresh failing, showing the "
                      "copy from 6h ago" in D4["html"] and "refresh failing" not in D["html"],
                  "/do-not-travel: a failing refresh is noted and degrades the page too"))
D3 = RL.do_not_travel(US, CA, DE, fetched=FETCHED, today="2027-06-01")
results.append(ok(D3["counts"]["changes"] == 0 and "No level changes in the last 180 days" in D3["html"]
                  and D3["title"].startswith("Do Not Travel List 2027"),
                  "the window closes on old changes; the year follows today"))
results.append(ok(RL.newest_change({"us": US, "ca": CA, "de": DE}) == "2026-09-30"
                  and RL.newest_change({"us": None, "ca": None, "de": None}) == "",
                  "newest_change: the sitemap's date, '' with nothing cached"))

# A feed item dated after today (the US list's French Polynesia read 2 Dec 2026 on 23 Oct) is
# never the "newest advisory": both pages print the newest on or before today.
US_FUT = payload("us", US["items"] + [item("PF", 1, "us", updated="2026-12-02")])
newest_ok = RL._newest(RL.own_by_iso(US_FUT), TODAY) == RL._newest(RL.own_by_iso(US), TODAY) <= TODAY
DF = RL.do_not_travel(US_FUT, CA, DE, fetched=FETCHED, today=TODAY)
SF = RL.safe_and_cheap(US_FUT, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok(newest_ok and RL._newest(RL.own_by_iso(US_FUT)) == "2026-12-02"
                  and all("2 Dec 2026" not in p["html"] and "newest advisory dated" in p["html"] for p in (DF, SF)),
                  "a future-dated feed item is not the newest advisory on either page (today caps it; no today: no cap)"))

# --- a mandatory daily visitor fee (review #10) -----------------------------------------
# Bhutan (visa.json's "fee": US$100 a night) at US Level 1 and 22%: off the
# list by the rule, named under it with its price and fee; the rule says so.
FEE = rg.visitor_fee("BT")
SB = RL.safe_and_cheap(payload("us", US["items"] + [item("BT", 1, "us", updated="2026-09-04", risks=[])]), CA, DE,
                       dict(FACTS, BT={"pct": 22, "band": "very cheap", "adv": 1, "src": "us"}),
                       CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
hygiene(SB, "/safe-and-cheap with a fee country")
feeline = re.search(r'<p class="sub feeout">(.*?)</p>', SB["html"])
results.append(ok(FEE and FEE["usd"] == 100 and FEE["per"] == "night" and FEE["name"] == "Sustainable Development Fee"
                  and "BT" not in SB["isos"]["safe"] and SB["isos"]["fee"] == ["BT"]
                  and SB["isos"]["safe"] == S["isos"]["safe"],
                  "Bhutan's US$100-a-night fee keeps it off /safe-and-cheap; the rest of the list is unchanged"))
results.append(ok(feeline and '<a href="/guide/bhutan">Bhutan</a> (22% <span class="fee" title="Sustainable Development Fee: '
                  'US$100 per person per night' in feeline.group(1) and "+ $100/night fee</span>)" in feeline.group(1)
                  and "no mandatory daily visitor fee" in SB["html"] and "no mandatory daily visitor fee" in S["html"]
                  and "feeout" not in S["html"],
                  "the rule names the fee; the left-out line gives Bhutan's price and fee (tooltip in full), only "
                  "where a fee country would otherwise qualify"))
results.append(ok(RL.fee_mark("BT").startswith(' <span class="fee" title="') and RL.fee_mark("VN") == ""
                  and "Not in the price level." in RL.fee_mark("BT") and "(set until 31 Dec 2029)" in RL.fee_mark("BT")
                  and "Indian nationals pay ₹1,200 a night." in RL.fee_mark("BT"),
                  "fee_mark: the fee beside a price, the tooltip with its end date (31 Dec 2029) and the Indian "
                  "nationals' rate; nothing for a country without one"))
SBn = RL.safe_and_cheap(payload("us", US["items"] + [item("BT", 2, "us", risks=["Crime"])]), CA, DE,
                        dict(FACTS, BT={"pct": 22, "band": "very cheap", "adv": 2, "src": "us"}),
                        CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
results.append(ok("BT" not in SBn["isos"]["near"] and SBn["isos"]["near"] == S["isos"]["near"],
                  "a fee country is never \"Nearly made it\" either"))
_css = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
results.append(ok(".listpage .fee {" in _css and ".guidecost .guidefee {" in _css,
                  "CSS: the fee's own style on the list rows and the guide line"))
_g = rg.render("BT")["body"]
results.append(ok(re.search(r"<p>💰 (?:[A-Z][a-z ]+: local|Local) prices ≈ \d+% of the US \([^)]*\) \+ \$100/night fee</p>", _g)
                  is not None
                  and "+ $100/night fee" not in rg.render("NP")["body"],
                  "the Bhutan guide's served price line carries the fee beside the figure (no other guide)"))
_app = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
results.append(ok("function visitorFee(iso)" in _app and "${feeHtml}" in _app and _app.count("${feeHtml}") == 2
                  and "ensureVisa().catch(() => {})]);" in _app,
                  "app.js renderGuideCost draws the fee beside both of its lines (live and snapshot), from visa.json"))

# --- the newsletter box on the list pages (review #9) ------------------------------------
# The guides' USD form as server HTML: the same pitch, Buttondown endpoint and
# embed=1, a plain post into a new tab (no script), the US-dollars line; on
# /safe-and-cheap, every /cheapest page and /dollar-strength, not
# /do-not-travel. The account is app.js's own.
_app = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
_bd = re.search(r'const BUTTONDOWN_USER = "([^"]+)";', _app).group(1)
_box = RL.subscribe_html()
from fxtracker import render_strength as RS2, render_cheapest as RC2  # noqa: E402
_pages = {"/safe-and-cheap": S["html"],
          "/dollar-strength": RS2.dollar_strength({"as_of": "2026-10-06", "threshold_pct": 2.0, "rows": [
              {"code": "VND", "strength_pct": 4.0, "favorable": True, "rate_now": 26000.0}]}, ppp, today=TODAY)["html"],
          "/cheapest/november": RC2._wrap("h", "l", "", ["n"], "s"), "/do-not-travel": D["html"]}
results.append(ok(RL.BUTTONDOWN_USER == _bd
                  and '<form action="https://buttondown.com/api/emails/embed-subscribe/%s" method="post" '
                      'target="_blank" class="subform">' % _bd in _box
                  and '<input type="hidden" name="embed" value="1">' in _box
                  and '<input type="email" name="email" placeholder="you@email.com" aria-label="Email address" required>' in _box
                  and "📬 Once a month: the best-value places to travel, straight to your inbox." in _box
                  and "Written in US dollars, from a US traveler's point of view." in _box
                  and "onsubmit" not in _box and "window.open" not in _box and "<script" not in _box
                  and "next month" not in _box.lower(),
                  "the box: app.js's account (%s), its pitch and US-dollars line, embed=1, a plain post into a new "
                  "tab, no popup script, no promise of the list by email" % _bd))
results.append(ok(all(_box in h for p, h in _pages.items() if p != "/do-not-travel") and _box not in D["html"]
                  and all(h.count("<form") == 1 for p, h in _pages.items() if p != "/do-not-travel")
                  and S["html"].index(_box) > S["html"].index('<p class="asof">'),
                  "on /safe-and-cheap, /cheapest/<month> and /dollar-strength, after the notes and sources; not on "
                  "/do-not-travel"))
_c = Check()
_c.feed('<div class="listpage">%s</div>' % _box)
_c.close()
results.append(ok(not _c.open and not [n for n in _c.names if FORBIDDEN.search(n)],
                  "the box parses and its class names pass the ad-blocker rule: %s" % sorted(set(_c.names))))
import server  # noqa: E402
_csp = server.SECURITY_HEADERS["Content-Security-Policy"]
results.append(ok("form-action" not in _csp or "https://buttondown.com" in _csp.split("form-action", 1)[1].split(";")[0],
                  "CSP lets the form post to Buttondown (no form-action, or one naming it)"))

# --- phone cards (review #28) -------------------------------------------------------------
# Two columns below 1024px at every width, labels above values, a dash-only
# cell left out of the card, /dollar-strength's "Before inflation" out below
# 520px; short labels on the rows.
_cssall = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
_lb = _cssall[_cssall.index(".listbox {"):_cssall.index("/* /dollar-strength (fxtracker/render_strength.py)")]
_phone = re.search(r"@media \(max-width: 519px\) \{(.*?)\n\}", _lb, re.S)
results.append(ok(".listtable tbody tr { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);" in _lb
                  and "@media (min-width: 520px) and (max-width: 1023px)" not in _lb
                  and re.search(r"@media \(max-width: 1023px\) \{\s*\.listtable td\.nil \{ display: none; \}", _lb)
                  and _phone and ".listtable td { display: block;" in _phone.group(1)
                  and ".listtable td::before { display: block;" in _phone.group(1)
                  and ".listtable td.wide { grid-column: 1 / -1; }" in _phone.group(1)
                  and ".listtable td.dsbefore { display: none; }" in _phone.group(1),
                  "CSS: two-column cards below 1024px at every width (label beside from 520px, above below it), "
                  "dash-only cells out; below 520px a lone row of chips full width and Before inflation out"))
_chip = RL._cell("Health notes", '<span class="chips"><span class="hnote">Dengue</span></span>')
_odd = RL._card([RL._cell("A", "1"), RL._cell("B", "2"), _chip])
_even = RL._card([RL._cell("A", "1"), _chip])
_nil = RL._card([RL._cell("A", "1"), RL._cell("B", "—"), _chip])
results.append(ok('<td data-l="Health notes" class="wide">' in _odd and 'class="wide"' not in _even
                  and 'class="wide"' not in _nil
                  and '<td data-l="Health notes" class="wide">' in re.search(r'<tr>.*?/guide/vietnam.*?</tr>', S["html"], re.S).group(0)
                  and 'class="wide"' not in D["html"],
                  "_card: a row of chips that would start the card's last pair alone is wide (a nil cell not "
                  "counted); beside a neighbour it isn't (/do-not-travel's US reasons sit by Germany)"))
results.append(ok('data-l="Prices"><span class="v">' in S["html"] and 'data-l="Prices vs US"' not in S["html"]
                  and "<th>Prices vs US</th>" in S["html"]
                  and re.search(r'<td data-l="Best months" class="nil"><span class="v">—</span></td>', S["html"])
                  and RL._cell("X", "—<sup class=\"fn\">*</sup>").startswith('<td data-l="X" class="nil">')
                  and RL._cell("X", '<span title="t">—</span>', cls="k").startswith('<td data-l="X" class="k nil">')
                  and RL._cell("X", "only the usual") == '<td data-l="X"><span class="v">only the usual</span></td>',
                  "rows: the short \"Prices\" label (the header keeps \"Prices vs US\"); a dash, footnote mark or "
                  "tooltip and all, is class nil; anything else is not"))

# --- one of a kind: the counts read in the singular ------------------------------------
S1 = RL.safe_and_cheap(US, CA, DE, {"_asof": FACTS["_asof"], "LA": FACTS["LA"], "AL": FACTS["AL"]},
                       CLIM, HEALTH, PLH, fetched=FETCHED, today=TODAY)
D1 = RL.do_not_travel(payload("us", [item("AF", 4, "us"), item("CO", 3, "us")]),
                      payload("ca", [item("AF", 4, "ca"), item("CO", 2, "ca")]),
                      payload("de", [item("AF", 4, "de")]), fetched=FETCHED, today=TODAY)
results.append(ok("<strong>1</strong> country qualifies today, cheapest first; it is also at the lowest level for "
                  "Canada and Germany." in S1["html"]
                  and "<strong>1</strong> country under 50% of US prices" in S1["html"]
                  and S1["desc"].startswith("1 country at US")
                  and "<strong>1</strong> country is “do not travel”" in D1["html"]
                  and "A further <strong>1</strong> is “reconsider travel”" in D1["html"]
                  and D1["desc"].startswith("1 country rated")
                  and "<strong>4</strong> countries qualify today" in S["html"]
                  and "<strong>2</strong> of them are also" in S["html"]
                  and "<strong>4</strong> countries are “do not travel”" in D["html"],
                  "one country is \"1 country qualifies\" / \"1 country is\" / \"A further 1 is\", never \"1 countries\""))
from fxtracker import render_strength as RS  # noqa: E402
P1 = RS.dollar_strength({"as_of": "2026-10-06", "threshold_pct": 2.0,
                         "rows": [{"code": "VND", "strength_pct": 4.0, "favorable": True, "rate_now": 26000.0}]},
                        ppp, today=TODAY)
results.append(ok("<strong>1</strong> currency, the strongest dollar after inflation first: <strong>1</strong> is "
                  "stronger than usual" in P1["html"] and P1["desc"].startswith("1 currency ranked"),
                  "/dollar-strength: \"1 currency … 1 is stronger than usual\": %r"
                  % re.search(r'<p class="sub">.*?</p>', P1["html"]).group(0)[:140]))

# --- no "None", no forbidden names, on both pages' full output --------------------------
results.append(ok(all(" None" not in p["html"] and ">None<" not in p["html"] for p in (S, S3, S4, S5, S6, S7, D, D2, D3, D4)),
                  "no None leaks on any degraded variant either"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

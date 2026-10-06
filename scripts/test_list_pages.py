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
    its fetch time, to the hour, and degrades the page too;
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
# Vietnam L1/27%: on the list, Canada says caution (no agree mark). Bhutan
# L1/21%: all three lowest (mark). Turkmenistan L1/45% on the alt list, and
# Canada's caution keeps it off the agree mark too.
# Portugal L1/60%: the boundary, in. Poland L1/61%: just out. Puerto Rico:
# Canada's L1 fills the US gap ("via") — never a US rating. Albania L2/40%:
# nearly made it, with reasons. Egypt L2/55%: too pricey for "nearly".
# Afghanistan L4 x3; Chad L4 US only; Venezuela L4 Canada only; Colombia L3
# US and CA; Palestine L4 US+DE, no Canada row.
US = payload("us", [
    item("VN", 1, "us", updated="2026-06-24", risks=[], summary="Exercise normal precautions in Vietnam."),
    item("BT", 1, "us", updated="2026-09-04", risks=[]),
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
    item("VN", 2, "ca"), item("BT", 1, "ca"), item("TM", 2, "ca"), item("PT", 1, "ca"), item("PL", 1, "ca"),
    item("AL", 2, "ca"), item("EG", 2, "ca"), item("AF", 4, "ca"),
    # WanderGrade's record saw Chad move 3 -> 4 and back: today it is 3, raised on 2026-09-30.
    item("TD", 3, "ca", changed="2026-09-30", change="up"),
    item("VE", 4, "ca", changed="2026-08-15", change="up"), item("CO", 3, "ca"), item("NC", 1, "ca"),
    item("PR", 1, "ca"),
])
DE = payload("de", [
    item("VN", 1, "de", updated="2026-02-02"), item("BT", 1, "de", updated="2026-02-02"),
    item("TM", 1, "de", updated="2026-02-02"), item("PT", 1, "de", updated="2026-02-02"),
    item("PL", 1, "de", updated="2026-02-02"), item("AL", 1, "de", updated="2026-02-02"),
    item("EG", 2, "de", updated="2026-02-02"), item("AF", 4, "de", updated="2026-08-19"),
    item("TD", 2, "de", updated="2026-08-31"), item("VE", 2, "de", updated="2026-08-31"),
    item("CO", 1, "de", updated="2026-08-31"), item("PS", 4, "de", updated="2026-09-01"),
    item("NC", 1, "de", updated="2026-08-31"),
])
FACTS = {"_asof": "2026-09-28",
         "VN": {"pct": 27, "band": "very cheap", "adv": 1, "src": "us"},
         "BT": {"pct": 21, "band": "very cheap", "adv": 1, "src": "us"},
         "TM": {"pct": 45, "band": "very cheap", "adv": 1, "src": "us"},
         "PT": {"pct": 60, "band": "cheap", "adv": 1, "src": "us"},
         "PL": {"pct": 61, "band": "cheap", "adv": 1, "src": "us"},
         "AL": {"pct": 40, "band": "very cheap", "adv": 2, "src": "us"},
         "EG": {"pct": 55, "band": "cheap", "adv": 2, "src": "us"},
         "AF": {"pct": 17, "band": "very cheap", "adv": 4, "src": "us"},
         "PR": {"pct": 30, "band": "very cheap", "adv": 1, "src": "ca"},
         # A subdivision carries the UK's figures and is never a row.
         "GB-ENG": {"pct": 20, "band": "very cheap", "adv": 1, "src": "us", "plof": "GB", "advof": "GB"}}
CLIM = {"VN": {"best": [2, 3, 4, 11], "curated": True}, "BT": {"best": [10, 11, 3, 4], "curated": False},
        "TM": {"best": [4, 5, 9]}, "PT": {"best": [5, 6, 9, 10], "curated": True}}
HEALTH = {"built": "2026-09-30", "c": {"VN": {"h": ["Dengue", "Malaria"], "a": ["Malaria"]},
                                       "BT": {"h": []}, "PT": {"h": []}}}
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
fx = {"VND": 4.0, "BTN": -2.0, "EUR": 1.5}
ppp = {"VN": {"infl": 3.5, "infl_year": 2025}, "BT": {"infl": 4.0, "infl_year": 2025}, "PT": {"infl": 2.0, "infl_year": 2025},
       "US": {"infl": 3.0, "infl_year": 2025}}
S = RL.safe_and_cheap(US, CA, DE, FACTS, CLIM, HEALTH, PLH, fetched=FETCHED, fx=fx, ppp=ppp, today=TODAY)
c, text = hygiene(S, "/safe-and-cheap")
results.append(ok(S["isos"]["safe"] == ["BT", "VN", "TM", "PT"],
                  "rule: US Level 1 and pct <= 60, by price (Poland at 61 out, Portugal at 60 in, Puerto "
                  "Rico's Canadian fill out, GB-ENG out): %s" % S["isos"]["safe"]))
results.append(ok(S["counts"] == {"safe": 4, "agree": 2, "near": 1}, "counts %s" % S["counts"]))
results.append(ok(S["isos"]["agree"] == ["BT", "PT"] and S["html"].count("all three agree") == 2,
                  "the agree mark where Canada and Germany are at their lowest level (Bhutan, Portugal), "
                  "not Vietnam or Turkmenistan (Canada: high degree of caution)"))
results.append(ok(re.search(r"<strong>4</strong> countries qualify", S["html"]) and "<strong>2</strong> of them" in S["html"],
                  "the intro's counts are the rows'"))
results.append(ok(S["isos"]["near"] == ["AL"] and "Nearly made it" in S["html"]
                  and re.search(r'/guide/albania.*?<span class="risk">Crime</span><span class="risk">Unrest</span>', S["html"], re.S),
                  "Nearly made it: US Level 2 under 50% (Albania, not Egypt at 55), with the US risk chips"))
tm = re.search(r'<tr>.*?/guide/turkmenistan.*?</tr>', S["html"], re.S).group(0)
results.append(ok('45%<sup class="fn">†</sup>' in tm and "† priced on the alternative rate basis" in text,
                  "Turkmenistan: on the list, footnoted as priced on the alternative rate basis"))
bt = re.search(r'<tr>.*?/guide/bhutan.*?</tr>', S["html"], re.S).group(0)
results.append(ok('21% <span class="band">very cheap</span>' in bt and 'title="Very cheap"' not in S["html"]
                  and '60% <span class="band">cheap</span>' in re.search(r'<tr>.*?/guide/portugal.*?</tr>', S["html"], re.S).group(0),
                  "the price band is visible text beside the number, not a tooltip"))
vn = re.search(r'<tr>.*?/guide/vietnam.*?</tr>', S["html"], re.S).group(0)
results.append(ok("Normal precautions" in vn and "High degree of caution" in vn and "No warning" in vn,
                  "each government's level in its own words on the row"))
results.append(ok("February–April and November" in vn and "weather: March, April, October and November" in
                  re.search(r'<tr>.*?/guide/bhutan.*?</tr>', S["html"], re.S).group(0),
                  "best months: curated as such, else the best-weather months, as the guide claims them"))
results.append(ok('<span class="hnote">Dengue</span><span class="hnote" title="in certain areas">Malaria*</span>' in vn
                  and "only the usual" in re.search(r'<tr>.*?/guide/bhutan.*?</tr>', S["html"], re.S).group(0),
                  "Canada's health notes where the document has them, areas marked"))
results.append(ok("Dollar vs 1-yr avg" in S["html"] and re.search(r'data-l="Dollar vs 1-yr avg"><span class="v">[+-]\d+\.\d%<', vn),
                  "the inflation-adjusted dollar column from the cached rates"))
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
results.append(ok(S4["degraded"] and S4["isos"]["safe"] == ["BT", "VN", "TM", "PT"]
                  and "daily snapshot of 28 Sep 2026" in S4["html"],
                  "US down: the snapshot's US levels stand in, dated, and the page is degraded"))
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

# --- no "None", no forbidden names, on both pages' full output --------------------------
results.append(ok(all(" None" not in p["html"] and ">None<" not in p["html"] for p in (S, S3, S4, S5, S6, S7, D, D2, D3, D4)),
                  "no None leaks on any degraded variant either"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

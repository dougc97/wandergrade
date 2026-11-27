"""A US advisory above Level 1 whose lead gives no "due to" takes its risks
from its section titles; nothing else's risks move.

    /usr/bin/python3 scripts/test_risks_headings.py

No network. Mali (Level 4) showed "—" for its US reasons on /do-not-travel
and in the Safety tab's Risks column: its lead is "Do not travel to Mali for
any reason." (no "due to"), and the sentences read in that case
(advisories._risks's fallback) name nothing — but its sections are titled
Crime, Terrorism, Kidnapping, Unrest, Armed Conflict and Health. Liberia
(Level 2), whose lead is a bare "Exercise increased caution", showed only
Crime though its sections are Crime, Unrest and Health. The titles are the
ones advisories._sentences already drops (round 9's heading reader), handed
back by advisories._titles. Four parts:
  * _titles on the markup shapes: the titles in the advisory's order, and
    _sentences unchanged by collecting them;
  * _title_risks / _item_risks on small descriptions: Level 1 never reads
    titles (they are general tips there), a "due to" lead keeps its own
    reasons whatever the titles say, a placeless "due to" lead (Afghanistan)
    still comes before the titles, a title the vocabulary has no word for
    ("Air Travel") adds nothing and never "Other", and the titles add to
    what the opening sentences name, never drop it;
  * the recorded feed (scripts/advisories_sample.us-2026-11-25.xml, all 218
    items) through _us_advisories: Mali and Liberia read their titles and
    alone say so (risks_from), Level 1 countries with titles (Canada
    "Crime", Cyprus "Armed Conflict", the Kyrgyz Republic "Unrest",
    Montserrat's volcano) stay empty, Level 3 countries with a "due to" lead
    (Israel, Honduras) keep it though their titles name more, no row above
    Level 1 is left without a reason, and every other row equals the reader
    before the change, field for field;
  * render_lists._us_reasons: Mali's chips are titled with the headings, a
    "due to" row's with its summary.
"""
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from fxtracker import advisories as A  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

# ---- the titles, in order --------------------------------------------------
# A title closed by a line break inside a paragraph ("<p><b>Health</b><br />",
# Mali, Liberia) is cut by an earlier pass than a heading tag's ("<h5>"), so
# the order collected is not the advisory's; the advisory's order is kept.
MIXED = ("Do not travel<p>to <b>Testland</b> for any reason.</p>\n<h5><b>Crime</b></h5>\n<p>Crime is common.</p>\n"
         "<p><b>Health</b><br />\nMedical services are limited.</p>\n<h5>Armed Conflict</h5>\n<p>Fighting occurs.</p>\n"
         "<p><b>Unrest</b></p>\n<p>Demonstrations occur.</p>")
results.append(ok(A._titles(MIXED) == ["Crime", "Health", "Armed Conflict", "Unrest"],
                  "titles in the advisory's order across markup shapes: %r" % A._titles(MIXED)))
results.append(ok(A._sentences(MIXED) == ["Do not travel to Testland for any reason.", "Crime is common.",
                                          "Medical services are limited.", "Fighting occurs.", "Demonstrations occur."],
                  "...and the sentences read without them: %r" % A._sentences(MIXED)))
results.append(ok(A._titles("<p>Exercise normal precautions in Testland.</p>") == [] and A._titles("") == [],
                  "no titles, none handed back"))
# A sentence or a lead set as a heading is no title (round 9's kind()).
results.append(ok(A._titles("<h5><b>There is a high risk of wrongful detention in Testland.</b></h5>"
                            "<p><b>Do not travel to Testland due to crime.</b></p>") == [],
                  "a whole sentence or a lead set in a heading is not a title"))

# ---- risks from titles -----------------------------------------------------
NAME_ISO = A._name_to_iso()


def risks(desc, level, iso):
    return A._item_risks(desc, level, iso, NAME_ISO)[0]


def titled(desc, level, iso):
    # True where every reason is a section title: the row says so
    # (risks_from), and its tip names the headings, not the summary.
    return A._item_risks(desc, level, iso, NAME_ISO)[1]


results.append(ok(risks(MIXED.replace("Testland", "Mali"), 4, "ML") == ["Crime", "Health", "Armed conflict", "Unrest"]
                  and titled(MIXED.replace("Testland", "Mali"), 4, "ML"),
                  "Level 4 with no \"due to\": the titles, as the vocabulary's labels, in order: %r"
                  % risks(MIXED.replace("Testland", "Mali"), 4, "ML")))
L1 = ("Exercise normal precautions<p>in <b>Canada</b>.</p>\n<h5>Crime</h5>\n<p>Petty crime occurs.</p>\n"
      "<h5>Armed Conflict</h5>\n<p>None.</p>")
results.append(ok(A._title_risks(L1, 1) == [] and risks(L1, 1, "CA") == [],
                  "Level 1 with titles stays empty by design: %r" % risks(L1, 1, "CA")))
L3 = ("Reconsider travel<p>to <b>Israel</b> due to <b>terrorism</b> and <b>unrest</b>.</p>\n"
      "<h5>Armed conflict</h5>\n<p>Rockets are fired.</p>\n<h5>Terrorism</h5>\n<p>Attacks occur.</p>")
results.append(ok(risks(L3, 3, "IL") == ["Terrorism", "Unrest"] and not titled(L3, 3, "IL"),
                  "Level 3 with \"due to\" keeps its own reasons, not its titles': %r" % risks(L3, 3, "IL")))
AF = ("Do not travel<p>to <b>Afghanistan</b> for any reason.</p>\n<p>Do not travel due to civil unrest, crime, and "
      "terrorism.</p>\n<h5>Kidnapping</h5>\n<p>Kidnapping occurs.</p>")
results.append(ok(risks(AF, 4, "AF") == ["Unrest", "Crime", "Terrorism"],
                  "a placeless \"due to\" lead still comes before the titles (Afghanistan): %r" % risks(AF, 4, "AF")))
NONE = ("Do not travel<p>to <b>Mali</b> for any reason.</p>\n<h5>Air Travel</h5>\n<p>The FAA has issued a "
        "notice.</p>\n<h4>U.S. government employee travel restrictions</h4>\n<p>Employees stay in Bamako.</p>")
results.append(ok(A._title_risks(NONE, 4) == [] and risks(NONE, 4, "ML") == [],
                  "titles the vocabulary has no word for add nothing, and no \"Other\": %r" % risks(NONE, 4, "ML")))
BARE = ("Exercise increased caution<p><b>Crime</b></p>\n<p>Violent crime is common in urban areas.</p>\n"
        "<p><b>Unrest</b></p>\n<p>Demonstrations occur regularly.</p>\n<p><b>Health</b></p>\n<p>Care is limited.</p>")
results.append(ok(risks(BARE, 2, "LR") == ["Crime", "Unrest", "Health"] and titled(BARE, 2, "LR"),
                  "titles come before the sentences read for a bare lead (Liberia; was [\"Crime\"]): %r"
                  % risks(BARE, 2, "LR")))
NOTITLE = "Exercise increased caution<p>in <b>Uganda</b>.</p>\n<p>Violent crime is a real danger in Uganda.</p>"
results.append(ok(risks(NOTITLE, 2, "UG") == ["Crime"] and not titled(NOTITLE, 2, "UG"),
                  "no titles: the sentences are still read, as before: %r" % risks(NOTITLE, 2, "UG")))
# The titles add to what those sentences name, never replace it: a section
# list that misses a risk the opening names can't drop it.
SHORT = NOTITLE + "\n<h5>Health</h5>\n<p>Care is limited.</p>"
results.append(ok(risks(SHORT, 2, "UG") == ["Health", "Crime"] and not titled(SHORT, 2, "UG"),
                  "a title list missing a risk the opening names keeps it (Crime), after the titles: %r"
                  % risks(SHORT, 2, "UG")))

# ---- the recorded feed -----------------------------------------------------
with open(os.path.join(HERE, "advisories_sample.us-2026-11-25.xml"), encoding="utf-8") as f:
    FEED = f.read()
A._fetch_text = lambda url, retries=3: FEED
items = A._us_advisories()["items"]
got = {i["iso"]: i for i in items if i.get("iso")}


def old_item_risks(desc, level, iso, name_iso):
    # The reader before titles were read (main 1a1d75b / r10/ship 39aca9b).
    return (A._risks(A._summary(desc, level, iso, name_iso, full=True, any_level=True), level)
            or A._risks(A._summary(desc, level, "", name_iso, full=True), level)), False


new_item_risks = A._item_risks
A._item_risks = old_item_risks
try:
    old_items = {(i.get("iso"), i["country"]): i for i in A._us_advisories()["items"]}
finally:
    A._item_risks = new_item_risks
before = {k: i["risks"] for k, i in old_items.items()}
after = {(i.get("iso"), i["country"]): i["risks"] for i in items}

WANT = {
    "ML": ["Crime", "Terrorism", "Kidnapping", "Unrest", "Armed conflict", "Health"],
    "LR": ["Crime", "Unrest", "Health"],
}
for iso, want in WANT.items():
    it = got.get(iso, {})
    results.append(ok(it.get("risks") == want, "%s (Level %s) reads its titles: %r (was %r)"
                      % (iso, it.get("level"), it.get("risks"), before.get((iso, it.get("country"))))))
for iso, title in (("CA", "Crime"), ("CY", "Armed Conflict"), ("KG", "Unrest"), ("MS", "Soufrière Hills volcano")):
    it = got.get(iso, {})
    results.append(ok(it.get("level") == 1 and it.get("risks") == [],
                      "%s (Level 1, titled %r) stays empty: %r" % (iso, title, it.get("risks"))))
for iso, want in (("IL", ["Terrorism", "Unrest"]), ("HN", ["Crime", "Terrorism"])):
    it = got.get(iso, {})
    results.append(ok(it.get("level") == 3 and it.get("risks") == want and "due to" in (it.get("summary") or ""),
                      "%s (Level 3, \"due to\") keeps its own reasons: %r" % (iso, it.get("risks"))))
blank = [i["country"] for i in items if i["level"] >= 2 and not i.get("risks")]
results.append(ok(not blank, "no row above Level 1 is left without a reason%s" % ("" if not blank else ": %r" % blank)))
moved = sorted(k[0] or k[1] for k in after if after[k] != before.get(k))
results.append(ok(len(items) == len(before) == 214 and moved == ["LR", "ML"],
                  "every other row's risks are unchanged (moved: %r of %d)" % (moved, len(items))))
diff = sorted(k[0] or k[1] for k, i in ((((i.get("iso"), i["country"]), i)) for i in items)
              if i != old_items.get(k))
results.append(ok(diff == ["LR", "ML"], "...and every other field of every other row too: %r" % diff))
marked = sorted(i.get("iso") for i in items if "risks_from" in i)
results.append(ok(marked == ["LR", "ML"] and all(got[c]["risks_from"] == "headings" for c in marked),
                  "only Mali and Liberia say their reasons are section headings: %r" % marked))
same = all(A._sentences(d) == A._sentences(d, titles=[])
           for d in (A._tag(b, "description") for b in re.findall(r"<item>(.*?)</item>", FEED, re.S)))
results.append(ok(same, "collecting the titles leaves every item's sentences as they were"))
ml_block = next(b for b in re.findall(r"<item>(.*?)</item>", FEED, re.S)
                if html.unescape(A._tag(b, "title")).startswith("Mali "))
results.append(ok(A._titles(A._tag(ml_block, "description"))[:2] == ["Crime", "Terrorism"]
                  and "Armed Conflict" in A._titles(A._tag(ml_block, "description")),
                  "Mali's titles as the feed gives them: %r" % A._titles(A._tag(ml_block, "description"))))

# ---- where the pages say the reasons come from ------------------------------
# /do-not-travel and /safe-and-cheap title a row's chips with the sentence
# they were read from; for Mali, whose summary names none of them, with the
# headings (the Safety tab's tip says the same, in app.js).
from fxtracker import render_lists as RL  # noqa: E402
ml_html, il_html = RL._us_reasons(got["ML"]), RL._us_reasons(got["IL"])
results.append(ok('title="From the section headings of the U.S. State Department&#x27;s advisory"' in ml_html
                  and ml_html.count('class="risk"') == 6,
                  "Mali's chips are titled with the headings, not its summary: %r" % ml_html[:120]))
results.append(ok(('title="%s"' % html.escape(got["IL"]["summary"], quote=True)) in il_html,
                  "a \"due to\" row's chips still carry its summary (Israel)"))
results.append(ok(RL._us_reasons(None) == "" and RL._us_reasons(got["CA"]) == "",
                  "no row or no reasons: no chips (the cell shows its dash)"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

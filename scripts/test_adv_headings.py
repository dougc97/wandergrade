"""A section title in a US advisory is never glued onto, or quoted as, a sentence.

    /usr/bin/python3 scripts/test_adv_headings.py

No network. The State Department's descriptions are HTML with section titles
("<h5>Crime</h5>", "<h5><b>U.S. embassy operations</b></h5>", bold or styled
paragraphs); once the tags went, a title ran into the sentence after it, and
the guides, the Safety tips and the lists quoted "…due to crime, terrorism,
and unrest. Crime Petty crime is common…" (Belgium) and "…war. U.S. embassy
operations The Embassy is open…" (Ukraine). Two parts:
  * the markup shapes seen in the feed, each through advisories._sentences
    (the description as the sentences _summary picks from);
  * the recorded feed (scripts/advisories_sample.us-2026-11-25.xml, all 218
    items) through _us_advisories: the nine summaries that had a title in
    them read without it, and no sentence of any item, quoted or not, starts
    with a title or is one. The titles are read off each item's own markup
    here, independently of the code under test.
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

# ---- the shapes ------------------------------------------------------------
# (what it is, description HTML, the sentences it must give). "was" is what
# the main branch gave on 2026-11-25.
SHAPES = [
    ("a bare <h5> title (Belgium; was \"Crime Petty crime is common…\")",
     "Exercise increased caution<p>in <b>Belgium </b>due to <b>crime</b>.</p>\n<h5>Crime</h5>\n<ul>\n"
     "<li>Petty crime is common, especially in popular tourist locations. Stay aware of your surroundings.</li>\n</ul>",
     ["Exercise increased caution in Belgium due to crime .",
      "Petty crime is common, especially in popular tourist locations.", "Stay aware of your surroundings."]),
    ("a bold <h5> title (Morocco; was \"Terrorism There is risk…\")",
     "Exercise increased caution<p>in <b>Morocco </b>due to risk of <b>terrorism</b>.</p>\n<h5><b>Terrorism</b></h5>\n"
     "<p>There is risk of terrorist violence in Morocco.  </p>",
     ["Exercise increased caution in Morocco due to risk of terrorism .",
      "There is risk of terrorist violence in Morocco."]),
    ("a title that is the next sentence's first word (Lesotho; was \"Crime Crime is common…\")",
     "Exercise increased caution<p>in <b>Lesotho</b> due to <b>crime</b>.</p>\n<h5>Crime</h5>\n"
     "<p>Crime is common in Lesotho.</p>",
     ["Exercise increased caution in Lesotho due to crime .", "Crime is common in Lesotho."]),
    ("a bold title with a space after it (Solomon Islands)",
     "<h5><b>Mosquito-borne diseases</b> </h5>\n<p>Mosquito-borne diseases such as malaria are widespread.</p>",
     ["Mosquito-borne diseases such as malaria are widespread."]),
    ("a title over a list (Ukraine; was \"U.S. embassy operations The Embassy…\")",
     "<ul><li>U.S. citizens should email KyivACS.</li>\n</ul>\n<h5><b>U.S. embassy operations</b></h5>\n<ul>\n"
     "<li>The Embassy is open and operating in Kyiv.</li></ul>",
     ["U.S. citizens should email KyivACS.", "The Embassy is open and operating in Kyiv."]),
    ("a styled title with a full stop (Ecuador; was quoted as \"Crime and kidnapping.\")",
     "<h5><span class='header-paragraph'>Crime and kidnapping.</span></h5>\n<p>Crime is a widespread problem in Ecuador.</p>",
     ["Crime is a widespread problem in Ecuador."]),
    ("a title with an aside and a colon (Mexico; was glued onto the list's first item)",
     "<h4>U.S. government employee travel restrictions (U.S. citizens are strongly advised to follow):</h4>\n<ul>\n"
     "<li>May not travel between cities after dark.</li>\n</ul>",
     ["May not travel between cities after dark."]),
    ("a whole sentence set as a heading stays (Afghanistan)",
     "<h5><b>There is a high risk of wrongful detention of U.S. nationals in Afghanistan.&nbsp;</b></h5>\n<ul>\n"
     "<li>All U.S. citizens are targeted for detention.</li></ul>",
     ["There is a high risk of wrongful detention of U.S. nationals in Afghanistan.",
      "All U.S. citizens are targeted for detention."]),
    ("a styled title nested in an <h3> (Chad)",
     "<h3><span class='body-regular'><span class='header-paragraph'>Crime</span></span></h3>\n"
     "<p><span class='body-regular'>Both violent and petty crime are a real danger in Chad.</span></p>",
     ["Both violent and petty crime are a real danger in Chad."]),
    ("a title and its text in one <h4> (Mauritius): the text stays, and ends there",
     "<h4><span class='header-paragraph'>Crime<br>\n</span><b><span class='body-regular'>Most crimes against "
     "foreigners are crimes of opportunity. This includes pickpocketing</span></b></h4>\n<p>Next.</p>",
     ["Most crimes against foreigners are crimes of opportunity.", "This includes pickpocketing.", "Next."]),
    ("bold inside a styled title (Somalia; was quoted as \"Aviation safety.\")",
     "<p><span class='body-regular'><span class='header-paragraph'><b>Aviation safety</b></span></span></p>\n"
     "<p><span class='body-regular'>The FAA has issued a Notice to Airmen.</span></p>",
     ["The FAA has issued a Notice to Airmen."]),
    ("a styled line break after the title (Belarus; was \"Ordered departure On February 28…\")",
     "<p><span class='body-regular'><span class='header-paragraph'><b>Ordered departure</b>"
     "<span class='header-callout'><br />\n </span></span>On February 28, 2022, the U.S. Department of State "
     "ordered the departure of U.S. government employees.</span></p>",
     ["On February 28, 2022, the U.S. Department of State ordered the departure of U.S. government employees."]),
    ("a long bold title (China; was quoted as \"Dual nationals and U.S. citizens of Chinese heritage.\")",
     "<p>Text before.</p>\n<p><b>Dual nationals and U.S. citizens of Chinese heritage</b></p>\n"
     "<p>China does not recognize dual nationality.</p>",
     ["Text before.", "China does not recognize dual nationality."]),
    ("a bold instruction opening a list runs on into it (Egypt; was \"Americans should reconsider travel to.\")",
     "<p><b>Americans should reconsider travel to:</b></p>\n<ul>\n<li>Western and Libyan Deserts due to terrorism.</li>\n</ul>",
     ["Americans should reconsider travel to: Western and Libyan Deserts due to terrorism."]),
    ("a bold instruction stays, as its own sentence (Russia)",
     "<b>U.S. citizens in Russia should leave immediately<br></b>The embassy has limited ability to help.",
     ["U.S. citizens in Russia should leave immediately.", "The embassy has limited ability to help."]),
    ("a lead in a heading still runs on into its list",
     "<h5>Do not travel to:</h5><ul><li>Gaza due to terrorism.</li></ul>",
     ["Do not travel to: Gaza due to terrorism."]),
    ("the old template's \"Country Summary:\" (Morocco, 2025)",
     "<p>Exercise increased caution in Morocco due to terrorism.</p>\n<p><b><i>Country Summary</i></b>: "
     "Terrorist groups continue plotting possible attacks in Morocco.</p>",
     ["Exercise increased caution in Morocco due to terrorism.",
      "Terrorist groups continue plotting possible attacks in Morocco."]),
    ("a list's lead-in on its own (Tonga; was \"If you decide to travel to Tonga: Be aware…\")",
     "<p>Exercise normal precautions in Tonga.</p>\n<p>If you decide to travel to Tonga:</p>\n<ul>\n"
     "<li>Be aware of your surroundings.</li>\n</ul>",
     ["Exercise normal precautions in Tonga.", "Be aware of your surroundings."]),
    ("\"Please read the entire Travel Advisory.\" leaves nothing (Belize; was a stray \"Please\")",
     "Exercise increased caution<p>in <b>Belize </b>due to <b>crime</b>. Some areas have increased risk. Please read "
     "the entire Travel Advisory.</p>\n<h5><b>Crime</b></h5>\n<p>Isolated incidents of violent crime can happen.</p>",
     ["Exercise increased caution in Belize due to crime .", "Some areas have increased risk.",
      "Isolated incidents of violent crime can happen."]),
    ("a <div> ends its sentence like a paragraph",
     "<div><span class='body-regular'>Greece is a generally safe destination</span></div><p>Petty crime is common.</p>",
     ["Greece is a generally safe destination.", "Petty crime is common."]),
]
for what, desc, want in SHAPES:
    got = A._sentences(desc)
    results.append(ok(got == want, what + ("" if got == want else ": %r" % got)))

# ---- the recorded feed -----------------------------------------------------
with open(os.path.join(HERE, "advisories_sample.us-2026-11-25.xml"), encoding="utf-8") as f:
    FEED = f.read()
A._fetch_text = lambda url, retries=3: FEED
got = {i["iso"]: i for i in A._us_advisories()["items"] if i.get("iso")}

# The nine items that quoted a title on 2026-11-25 (main 3d50457 read e.g.
# "…unrest. Crime Petty crime is common…"), with their risk chips, which
# never depended on it.
NINE = {
    "BE": ("Exercise increased caution in Belgium due to crime, terrorism, and unrest. Petty crime is common,"
           " especially in popular tourist locations.", ["Crime", "Terrorism", "Unrest"]),
    "BW": ("Exercise increased caution in Botswana due to crime. Petty crime and crimes of opportunity, primarily"
           " the theft of money and personal property, are common in Botswana.", ["Crime"]),
    "CL": ("Exercise increased caution in Chile due to crime, unrest, and health. Petty crime is common in Chile.",
           ["Crime", "Unrest", "Health"]),
    "SZ": ("Exercise increased caution in Eswatini due to crime and unrest. Crime is common in Eswatini.",
           ["Crime", "Unrest"]),
    "XK": ("Exercise increased caution in Kosovo due to unrest and terrorism. Demonstrations related to the local"
           " political situation may occur with little notice.", ["Unrest", "Terrorism"]),
    "LS": ("Exercise increased caution in Lesotho due to crime and health. Crime is common in Lesotho.",
           ["Crime", "Health"]),
    "MA": ("Exercise increased caution in Morocco due to risk of terrorism. There is risk of terrorist violence,"
           " including terrorist attacks and other activity in Morocco.", ["Terrorism"]),
    "SB": ("Exercise increased caution to Solomon Islands due to risks to health, unexploded ordinance, crime and"
           " civil unrest. Mosquito-borne diseases such as malaria and dengue fever are widespread.",
           ["Health", "Explosives", "Crime", "Unrest"]),
    "UA": ("Do not travel to Ukraine for any reason due to the Russia-Ukraine war. The Embassy is open and operating"
           " in Kyiv; however, Embassy personnel are subject to movement, curfew, and activity restrictions, which"
           " may cause delays in provision of consular assistance to U.S. citizens…", ["Armed conflict"]),
}
for iso, (summary, risks) in NINE.items():
    it = got.get(iso, {})
    results.append(ok(it.get("summary") == summary and it.get("risks") == risks,
                      "%s quotes no title: %r %r" % (iso, it.get("summary"), it.get("risks"))))

SAYS = r"\b(should|must|leave|depart|avoid|do not|don't|are|is|will|cannot)\b"


def plain(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def titles(desc):
    """The section titles in an item's markup: heading tags, styled
    header-paragraph spans and bold-only paragraphs that hold a noun phrase,
    not a lead, an instruction or a whole sentence."""
    out = set()
    for pat in (r"<(h[1-6])\b[^>]*>(.*?)</\1\s*>",
                r"<span class=['\"]header-paragraph['\"]>()(.*?)</span>",
                r"<p>\s*(?:<span[^>]*>\s*)?<b>()([^<]{1,80})</b>(?:\s|&nbsp;)*(?:</span>\s*)?</p>"):
        for m in re.finditer(pat, desc, re.I | re.S):
            if "header-paragraph" in m.group(2):
                continue        # a heading holding its title span and text: the span is read on its own
            t = plain(m.group(2)).rstrip(" :")
            if not t or re.match(r"(exercise|reconsider|do not travel)\b", t, re.I):
                continue
            if re.search(SAYS, re.sub(r"\([^)]*\)", " ", t), re.I):
                continue
            if t.endswith((".", "!", "?")) and len(t.split()) > 6:
                continue
            out.add(t.rstrip("."))
    return out


def glued(sentences, ts):
    return [(t, s) for s in sentences for t in ts
            if re.match(re.escape(t) + r"\.?\s+[A-Z“\"(]", s) or s.rstrip(".: ") == t]


items = re.findall(r"<item>(.*?)</item>", FEED, re.S)
with_titles = 0
bad_sentences, bad_summaries = [], []
by_name = {}
for block in items:
    desc = A._tag(block, "description")
    ts = titles(desc)
    with_titles += bool(ts)
    bad_sentences += [(A._tag(block, "title"), t, s) for t, s in glued(A._sentences(desc), ts)]
    by_name.setdefault(A._norm(re.split(r"\s*[-–]\s*Level", html.unescape(A._tag(block, "title")))[0]), ts)
for it in A._us_advisories()["items"]:
    ts = by_name.get(A._norm(it["country"]), set())
    sents = re.split(r"(?<=[.!?…])\s+", it.get("summary") or "")
    bad_summaries += [(it.get("iso") or it["country"], t, s) for t, s in glued(sents, ts)]
results.append(ok(len(items) == 218 and with_titles >= 60,
                  "the recording has its 218 items, %d of them with section titles" % with_titles))
results.append(ok(not bad_sentences,
                  "no sentence of any item starts with a section title or is one%s"
                  % ("" if not bad_sentences else ": %r" % bad_sentences[:5])))
results.append(ok(not bad_summaries,
                  "no quoted summary does either%s" % ("" if not bad_summaries else ": %r" % bad_summaries[:5])))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)

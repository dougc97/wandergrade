#!/usr/bin/env python3
"""What a rendered digest must say, worked out from its payload alone, and the
checks that hold a render to it. Offline; imported by test_digest_variants.py.

Until the Dec 2026 redesign the digest tests proved "the USD email is commit
4788fd2's text, less a list of stripped pieces" (digest_snapshot's REVIEW3,
COVERS, CHEAP_LINK and the cost-line graft). The redesign changes nearly
every piece of the body, so a strip-and-compare of the body has nothing left
to hold on to. Three proofs replace it:

  the payload   which countries, grades, links and numbers go in the email
                (picks.build_variant's output) is compared with the
                pre-redesign code's, field for field, every edition and
                month (test_digest_variants 1, digest_snapshot.BASE);
  check()       the email is read back (Email, a small HTML reader) and
                every visible line, link, image, Overall badge and photo
                credit in it must be the one expected() works out from the
                payload: the email says what the payload says, and nothing
                else; each compact card is laid out as THUMB_CELL ...
                WORDS_VALIGN spell out (compact_cards);
  proofing()    the markup rules that stop Buttondown, the sender,
                restyling it in either of the two templates the account has
                used (the note above newsletter._link).

A line's text is compared with its non-breaking spaces kept (NB below): they
are what holds a flag's gap, an icon to its letter and an arrow to its last
word, so expected() spells each one out and a plain space in its place is a
difference.

expected() is the email's spec, in plain text. When the email changes on
purpose, change expected() and RULES to say the new thing. Don't loosen
check() or proofing().

`nl` and `pk` below are a tree's newsletter and picks modules, as
digest_snapshot.install returns them. expected() takes only facts from them
(the site address, the price band, the grade bands and the advisory sources'
names, each with its own test), never the functions that write the email's
HTML. The Overall badge's colours are read from the site's own stylesheet
(site_grade_colours), and the highlights the guides mark as inside an
avoid-all zone from the site's own list (avoid_marked). The closing quotes
and Buttondown's unsubscribe token are spelled out here (QUOTES, UNSUB), not
read from `nl`: read from the code under test, a changed citation or a
mistyped token passed check() in every edition, and only the USD golden
hashes noticed.
"""
import html.parser
import io
import json
import os
import re

VOID = frozenset(("img", "br", "hr", "meta", "link", "input"))
BLOCK = frozenset(("div", "p", "table", "tbody", "thead", "tr", "td", "th", "ul", "ol", "li",
                   "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"))

GREEN = "#0a7d28"
SMALL = "#666"            # small print
CREDIT = "#6f6f6f"        # the photo credits
WHITE = "#ffffff"         # a green button's label
MIN_PX = 12               # nothing a reader sees is smaller
CREDITS_LEAD = "Photos (cropped) via Wikimedia Commons."
# The hidden preheader ends in ten of these (&#847; in the HTML): they stop a mail
# app filling the inbox preview with the text that follows.
PAD = "\u034f"
# U+FE0F follows each of these in the email (the emoji form), spelled out
# so an editor can't drop it.
SHIELD, SUN, PLANE = "\U0001f6e1\ufe0f", "\U0001f324\ufe0f", "\u2708\ufe0f"
MONEY = "\U0001f4b0"
NB = "\xa0"               # a non-breaking space (&nbsp; in the HTML)
SEP = NB + "\u00b7 "      # between two grades: a row may break only after the dot
BRAND_TOP = "\U0001f30d WanderGrade"   # the brand line that opens the email
# Buttondown swaps this for the reader's own unsubscribe link when it sends.
# Anything else in its place goes out as a dead link.
UNSUB = "{{ unsubscribe_url }}"
# The closing quotes, word for word: (quote, author, the work it is from). An
# issue's is QUOTES[(year * 12 + month) % 5], so each of the five is in some
# frozen month. Every one is cited to the work it is really from
# (newsletter.QUOTES has the rule); a citation changed there must be changed
# here on purpose.
QUOTES = (
    ("Travel is fatal to prejudice, bigotry, and narrow-mindedness.",
     "Mark Twain", "The Innocents Abroad, 1869"),
    ("I travel not to go anywhere, but to go. I travel for travel\u2019s sake.",
     "Robert Louis Stevenson", "Travels with a Donkey in the C\u00e9vennes, 1879"),
    ("Though we travel the world over to find the beautiful, we must carry it with us, or we find it not.",
     "Ralph Waldo Emerson", "Essays: First Series, 1841"),
    ("I am tormented with an everlasting itch for things remote.",
     "Herman Melville", "Moby-Dick, 1851"),
    ("The mountains are calling and I must go.",
     "John Muir", "letter to his sister Sarah, 1873"),
)


# ---- reading an email back ---------------------------------------------------

class Node(object):
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    @property
    def style(self):
        out = {}
        for part in (self.attrs.get("style") or "").split(";"):
            if ":" in part:
                k, val = part.split(":", 1)
                out[k.strip().lower()] = val.strip()
        return out

    def walk(self):
        """Every element under this one, in document order."""
        for k in self.kids:
            if isinstance(k, Node):
                yield k
                for x in k.walk():
                    yield x

    def text(self):
        return "".join(k if isinstance(k, str) else " " if k.tag == "br" else k.text() for k in self.kids)

    def own_text(self, links=True):
        """The text this block shows itself: its inline content, with nested
        blocks left out (each is a line of its own). links=False also leaves
        out what sits inside a link."""
        return "".join(k if isinstance(k, str) else " " if k.tag == "br"
                       else "" if k.tag in BLOCK or (k.tag == "a" and not links)
                       else k.own_text(links) for k in self.kids)

    def elements(self):
        return [k for k in self.kids if isinstance(k, Node)]

    def next_element(self):
        sibs = self.parent.elements() if self.parent else []
        i = next((j for j, s in enumerate(sibs) if s is self), None)
        return sibs[i + 1] if i is not None and i + 1 < len(sibs) else None


def norm(s):
    """White space evened out; a non-breaking space is kept as it is (NB)."""
    return re.sub(r"[ \t\r\n\f\v]+", " ", s).strip(" \t\r\n\f\v")


class _Reader(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.at = self.root
        self.problems = []

    def handle_starttag(self, tag, attrs):
        if len(set(k for k, _v in attrs)) != len(attrs):
            self.problems.append("<%s> repeats an attribute: %r" % (tag, attrs))
        n = Node(tag, dict((k, v or "") for k, v in attrs), self.at)
        self.at.kids.append(n)
        if tag not in VOID:
            self.at = n

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.at = self.at.parent

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.at.tag != tag:
            self.problems.append("</%s> closes <%s>" % (tag, self.at.tag))
            up = self.at
            while up is not None and up.tag != tag:
                up = up.parent
            if up is None:
                return
            self.at = up
        self.at = self.at.parent

    def handle_data(self, data):
        self.at.kids.append(data)


class Email(object):
    """A body read back: .lines [(text, node)], .links, .images, .badges,
    .credits, and .problems (markup that doesn't nest)."""

    def __init__(self, body):
        r = _Reader()
        r.feed(body)
        r.close()
        self.root, self.problems = r.root, list(r.problems)
        if r.at is not r.root:
            self.problems.append("<%s> is never closed" % r.at.tag)
        if norm("".join(k for k in r.root.kids if isinstance(k, str))):
            self.problems.append("text outside any block")
        self.lines = [(t, n) for t, n in ((norm(n.own_text()), n) for n in r.root.walk()
                                          if n.tag in BLOCK) if t]
        self.links = [_link(a) for a in r.root.walk() if a.tag == "a"]
        self.images = [_image(i) for i in r.root.walk() if i.tag == "img"]
        # An Overall badge: a <span> with a fill of its own.
        self.badges = [n for n in r.root.walk() if n.tag == "span" and "background" in n.style]
        self.credits_node = next((n for t, n in self.lines if t.startswith("Photos ")), None)
        # .credit_links: each entry's (photographer's <a>, licence's <a> or None).
        self.credit_links = []
        self.credits = (_credits(self.credits_node, self.credit_links)
                        if self.credits_node is not None else None)


def _solid(kids):
    return [k for k in kids if not (isinstance(k, str) and not k.strip())]


def _link(a):
    """One <a>: kind "image" (a picture, no words), "button" (a background of
    its own) or "text"; for the last two the colour and underline its words
    carry, read off the inner of two nested spans (None where the words
    aren't in two spans, which proofing() reports)."""
    st = a.style
    text = norm(a.text())
    kind = ("image" if not text and any(x.tag == "img" for x in a.walk())
            else "button" if any(k.startswith("background") for k in st) else "text")
    inner = None
    kids = _solid(a.kids)
    if kind != "image" and len(kids) == 1 and isinstance(kids[0], Node) and kids[0].tag == "span":
        k2 = _solid(kids[0].kids)
        if len(k2) == 1 and isinstance(k2[0], Node) and k2[0].tag == "span":
            inner = k2[0]
    ist = inner.style if inner is not None else {}
    return {"kind": kind, "href": a.attrs.get("href"), "text": text, "color": ist.get("color"),
            "underline": ist.get("text-decoration") == "underline",
            "plain": st.get("text-decoration") == "none", "node": a}


# A compact card's photo (Doug, 2026-11-12, "A": the photo grows with the
# card). Its cell takes 35% of the card but never less than 110px; the image
# fills the cell at its own shape, with the size it has at a 600px email in
# its width and height attributes (Outlook on the desktop ignores a
# percentage width on an image); the card's words sit in the middle of the
# photo's height. The photo is asked for at 440x336, the approved 220:168
# shape at about 2.3 times the 194px it is shown at. Spelled out here, not
# read from the code under test.
THUMB_CELL = {"width": "35%", "valign": "top"}
THUMB_CELL_STYLE = {"width": "35%", "min-width": "110px"}
THUMB_IMG = {"width": "194", "height": "148"}
THUMB_IMG_STYLE = {"display": "block", "width": "100%", "height": "auto", "border-radius": "8px"}
THUMB_ASKED = (440, 336)
WORDS_VALIGN = "middle"


def _image(img):
    a = img.parent
    while a is not None and a.tag != "a":
        a = a.parent
    src, w = img.attrs.get("src") or "", img.attrs.get("width")
    kind = ("flag" if src.startswith("https://flagcdn.com/") else "hero" if w == "560"
            else "thumb" if w == THUMB_IMG["width"] else "?")
    return {"kind": kind, "src": src, "alt": img.attrs.get("alt"), "href": a.attrs.get("href") if a else None,
            "node": img}


def asked_size(src):
    """(width, height) an image address asks for: the image service's
    &w=..&h=.., or the size in a frozen fixture's stand-in name
    (digest_snapshot.fake_cover, "..._440x336.jpg"). None when it names
    none."""
    m = re.search(r"[?&]w=(\d+)&h=(\d+)(?:&|$)", src) or re.search(r"_(\d+)x(\d+)\.jpg(?:\?|$)", src)
    return (int(m.group(1)), int(m.group(2))) if m else None


def compact_cards(e, picks):
    """Problems (strings) in the compact cards of Email `e`, whose payload
    picks are `picks`: each is a table of one row, the photo's cell (where
    the pick shows a photo) and the words' cell, laid out as THUMB_CELL ...
    WORDS_VALIGN say, and a photo that is the pick's small copy is asked
    for at THUMB_ASKED. [] when all are."""
    bad = []
    tables = [n for n in e.root.walk() if n.tag == "table" and n.attrs.get("role") == "presentation"]
    cards = picks[1:]
    if len(tables) != len(cards):
        return ["%d compact card tables for %d compact cards" % (len(tables), len(cards))]
    for t, s in zip(tables, cards):
        rows = [n for n in t.walk() if n.tag == "tr"]
        tds = rows[0].elements() if len(rows) == 1 else []
        if not tds or any(x.tag != "td" for x in tds) or len(tds) != (2 if s.get("photo") else 1):
            bad.append("%s's card is not one row of %s" % (s["name"], "photo, words" if s.get("photo") else "words"))
            continue
        words = tds[-1]
        if words.attrs.get("valign") != WORDS_VALIGN:
            bad.append("%s's words are valign=%r, want %r (beside the photo's middle)"
                       % (s["name"], words.attrs.get("valign"), WORDS_VALIGN))
        if not s.get("photo"):
            continue
        cell = tds[0]
        imgs = [n for n in cell.walk() if n.tag == "img"]
        if any(cell.attrs.get(k) != val for k, val in THUMB_CELL.items()) or cell.style != THUMB_CELL_STYLE:
            bad.append("%s's photo cell is %r style %r, want %r style %r"
                       % (s["name"], dict((k, cell.attrs.get(k)) for k in THUMB_CELL), cell.style,
                          THUMB_CELL, THUMB_CELL_STYLE))
        if len(imgs) != 1:
            bad.append("%s's photo cell holds %d images" % (s["name"], len(imgs)))
            continue
        img = imgs[0]
        if any(img.attrs.get(k) != val for k, val in THUMB_IMG.items()) or img.style != THUMB_IMG_STYLE:
            bad.append("%s's photo is width=%r height=%r style %r, want %r style %r"
                       % (s["name"], img.attrs.get("width"), img.attrs.get("height"), img.style,
                          THUMB_IMG, THUMB_IMG_STYLE))
        if s.get("photo_thumb") and img.attrs.get("src") == s["photo_thumb"] and asked_size(s["photo_thumb"]) != THUMB_ASKED:
            bad.append("%s's small photo asks for %r, want %r" % (s["name"], asked_size(s["photo_thumb"]), THUMB_ASKED))
    return bad


def _credits(node, nodes=None):
    """The credits block's entries as the reader gets them: [(country,
    photographer, the link on the photographer's name, licence, the link on
    the licence or None)], or a string saying what doesn't parse. Two
    entries are parted by a non-breaking space, a dot and a space (SEP), as
    two grades are. `nodes` (a list) is given each entry's two <a>s."""
    links, flat = [], []
    for k in node.kids:
        if isinstance(k, str):
            flat.append(k)
        elif k.tag == "a":
            flat.append("\x01%d\x02" % len(links))
            links.append(k)
        else:
            return "unexpected <%s> in the credits block" % k.tag
    flat = norm("".join(flat))
    if not flat.startswith(CREDITS_LEAD + " "):
        return "the credits block doesn't open %r: %r" % (CREDITS_LEAD, flat[:60])
    out = []
    for part in flat[len(CREDITS_LEAD) + 1:].split(SEP):
        m = re.match(r"^([^\x01\x02]+): \x01(\d+)\x02, (?:\x01(\d+)\x02|([^\x01\x02]+))$", part)
        if not m:
            return "a credit that isn't 'Country: photographer, licence': %r" % part
        who = links[int(m.group(2))]
        lic = links[int(m.group(3))] if m.group(3) else None
        out.append((m.group(1), norm(who.text()), who.attrs.get("href"),
                    norm(lic.text()) if lic is not None else m.group(4),
                    lic.attrs.get("href") if lic is not None else None))
        if nodes is not None:
            nodes.append((who, lic))
    return out


# ---- what the payload says the email must be -----------------------------------

def _labels(s):
    labels = [a if isinstance(a, str) else a.get("t", "") for a in (s.get("activities") or [])]
    return [x for x in labels if x][:2]


_MARKED = {}


def avoid_marked(public):
    """{ISO: frozenset of highlight labels} the site's guides mark as inside
    one of Global Affairs Canada's avoid-all zones: public/avoid-marks.json's
    "activity" entries, read here on their own (not through the code under
    test). The email never recommends one (Doug, 2026-11-12: the top card's
    "Don't miss" skips them, as the stay chips skip avoid-zone places).
    Raises when the file can't be read: a check must not pass on no list."""
    path = os.path.join(public, "avoid-marks.json")
    if path not in _MARKED:
        with io.open(path, encoding="utf-8") as f:
            countries = json.load(f)["countries"]
        _MARKED[path] = dict((iso, frozenset(e["i"] for e in es if e["s"] == "activity"))
                             for iso, es in countries.items())
    return _MARKED[path]


def _strong(s):
    """The reader's money goes further than usual here: the dollar line."""
    return s.get("fx") is not None and s["fx"] >= 3


def _cost(nl, pk, s, v):
    """The price line, in the site's three bands (the band and its rounding
    are checked against JavaScript in test_digest_variants 2c). None without
    a price level."""
    pl = s.get("pl")
    if not pl:
        return None
    band = nl._pl_band(pl)
    if band < 0:
        return "Prices ~%d%% below %s%slevels" % (pk.js_round((1 - pl) * 100), v.levels_adj, NB)
    if band > 0:
        return "Pricier than %s" % v.vs_place
    return "Prices about on par with %s" % v.vs_place


_HEX = r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b"
_SITE_COLOURS = {}


def _hex6(c):
    c = c.lower()
    return c if len(c) == 7 else "#" + "".join(ch * 2 for ch in c[1:])


def site_grade_colours(css_path):
    """{letter: (fill, letter colour)} as the site paints its grade pills,
    read from its stylesheet (public/styles.css): each .grAp ... .grF rule's
    background, and for the letter .gr's own colour unless a later rule
    names the letter's class and sets another (".grA, .grBp, .grB, .grC,
    .grD { color: #000; }"). Colours come back as six lower-case digits.
    Raises ValueError when the stylesheet no longer says it this way."""
    if css_path not in _SITE_COLOURS:
        with io.open(css_path, encoding="utf-8") as f:
            css = f.read()
        letter = lambda cls: cls.replace("p", "+")
        fills = dict((letter(c), _hex6(h)) for c, h in re.findall(
            r"^\.gr(Ap|A|Bp|B|C|D|F)\s*\{\s*background:\s*(%s);\s*\}" % _HEX, css, re.M))
        base = re.search(r"^\.gr\s*\{[^}]*?(?<![-\w])color:\s*(%s)" % _HEX, css, re.M)
        over = re.findall(r"^((?:\.gr(?:Ap|A|Bp|B|C|D|F)\s*,?\s*)+)\{\s*color:\s*(%s);\s*\}" % _HEX, css, re.M)
        if sorted(fills) != sorted(["A+", "A", "B+", "B", "C", "D", "F"]) or not base or len(over) != 1:
            raise ValueError("%s: the grade pill rules aren't where site_grade_colours looks for them"
                             % css_path)
        ink = dict((g, _hex6(base.group(1))) for g in fills)
        for cls in re.findall(r"\.gr(Ap|A|Bp|B|C|D|F)\b", over[0][0]):
            ink[letter(cls)] = _hex6(over[0][1])
        _SITE_COLOURS[css_path] = dict((g, (fills[g], ink[g])) for g in fills)
    return _SITE_COLOURS[css_path]


def expected(nl, pk, v, d):
    """{subject, lines, links, images, badges, credits} for edition `v`'s
    payload `d`.

    lines    [(key, text)]: every line a reader sees, top to bottom. A line
             is one block's own text; the key names the piece (RULES).
    links    [(kind, address, words, colour, underlined)] in order.
    images   [(kind, address, alt text, the address it links to)] in order.
    badges   [(letter, fill, letter colour)]: the Overall badge of each card
             and gem in order, in the site's colours for that letter.
    credits  [(country, photographer, file page, licence, licence link)]:
             one for each card that shows a photo, in card order.
    held     [(line key, words)]: words that must sit in a span that can't
             wrap, or the small print breaks them at a hyphen.
    grouped  [True or False] for each gem in order: its four grades are one
             group that moves to the next line together. False where the
             row names another government: that row is too long for a
             phone's line and flows freely."""
    usd = v.code == "USD"
    m, mn, yr = d["month"], d["month_name"], d["year"]
    picks, gems = d["picks"], d["gems"]
    site = nl.SITE
    vo = "" if usd else "&vo=" + v.home_iso
    grade, safe = pk.grade, lambda s: pk.SAFE_GRADE.get(s["advLvl"], "B")
    # The edition's main advisory source: the grade key names it once, and a
    # compact card or gem names its own only where it is another government's.
    main = pk.ADV_SRC_SHORT.get(v.adv_source, v.adv_source)
    by = lambda s: " per %s" % s["advBy"] if s.get("advBy") and s["advBy"] != main else ""
    guide = lambda s: "%s/?tab=guide&gc=%s&vmn=%d%s" % (site, s["iso"], m, vo)
    flag = lambda s: ("flag", "https://flagcdn.com/32x24/%s.png" % s["iso"].lower(), s["iso"], None)
    colours = site_grade_colours(os.path.join(pk.PUBLIC, "styles.css"))
    marked = avoid_marked(pk.PUBLIC)
    lines, links, images, badges, credits, held, grouped = [], [], [], [], [], [], []
    line = lambda key, text: lines.append((key, text))
    # A name row: the flag, its gap (a non-breaking space), the name, the badge.
    name = lambda s: NB + "%s %s" % (s["name"], grade(s["value"]))
    badge = lambda s: badges.append((grade(s["value"]),) + colours[grade(s["value"])])

    # A fare grade is marked "~" when it is an estimate (no cached fare yet:
    # picks counts the route as typical for its distance), as on the site.
    fly = lambda s: ("~" if s.get("fareEst") else "") + grade(s["fly"])

    def letters(s):
        """A compact card's or a gem's four grades: each icon held to its letter."""
        units = [MONEY + NB + grade(s["afford"]), SHIELD + NB + safe(s) + by(s), SUN + NB + grade(s["wx"])]
        if s.get("fly") is not None:
            units.append(PLANE + NB + fly(s))
        return SEP.join(units)

    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)
    pre = ("Plan ahead: after inflation, your %s goes further than usual in %d of %s’s picks."
           % (v.noun, nstrong, mn) if nstrong else
           "Plan ahead: %d destinations graded A+ to F on value, safety, weather and flights for %s."
           % (len(picks), mn))
    line("pre", pre + PAD * 10)
    line("brand_top", BRAND_TOP)
    # The count is the number of picks ("1 top pick", "5 top picks"); the
    # banknote sentence is there only when a pick has the dollar line, its
    # banknote held to "marks"; flights is named only when a card or gem has
    # a fare grade (with no fare data at all no row shows one).
    flights = any(s.get("fly") is not None for s in picks + gems)
    line("intro", "%d top pick%s for %s, graded A+ to F on %s.%s "
                  "Going another month? Pick your travel month%s→"
         % (len(picks), "" if len(picks) == 1 else "s", mn,
            "money, safety, weather and flights" if flights else "money, safety and weather",
            " %s%smarks where your %s goes further than usual right now." % (v.fx_emoji, NB, v.noun)
            if nstrong else "",
            NB))
    links.append(("text", site if usd else "%s/?vo=%s" % (site, v.home_iso),
                  "Pick your travel month%s→" % NB, GREEN, False))

    for i, s in enumerate(picks):
        g, top = guide(s), i == 0
        if s.get("photo"):
            # The top card shows the banner; a compact card the small copy,
            # or the banner when the payload has none.
            images.append(("hero", s["photo"], s["name"], g) if top else
                          ("thumb", s.get("photo_thumb") or s["photo"], s["name"], g))
            links.append(("image", g, "", None, False))
            c = s.get("photo_credit")
            if c:
                credits.append((s["name"], c["artist"], c["page"], c["license"], c.get("license_url") or None))
        images.append(flag(s))
        links.append(("text", g, s["name"], GREEN, False))
        line("name", name(s))
        badge(s)
        if top:
            units = [MONEY + NB + "Affordability" + NB + grade(s["afford"]), SHIELD + NB + "Safety" + NB + safe(s),
                     SUN + NB + "Weather" + NB + grade(s["wx"])]
            if s.get("fly") is not None:
                units.append(PLANE + NB + "Flights" + NB + fly(s) + " (%s)" % (
                    "estimated, no fare yet" if s.get("fareEst")
                    else "%s vs the route’s usual" % mn if s.get("fly_basis") == "month"
                    else "year-round, for the distance"))
            line("grades", SEP.join(units))
            if s.get("advBy"):
                line("source", "Safety grade from %s advisories" % s["advBy"])
        else:
            line("grades", letters(s))
        # The same two money lines on every card, price first; the dollar
        # line only from 3%.
        cost = _cost(nl, pk, s, v)
        if cost:
            line("cost", cost)
        if _strong(s):
            line("fx", "%s %s goes ~%d%% further than%susual"
                 % (v.fx_emoji, v.noun_cap, pk.js_round(s["fx"]), NB))
        if top:
            # Never a highlight the guide marks as inside an avoid-all zone:
            # one in the payload is left out here, so an email that shows it
            # says something its payload's rule does not.
            dont = [x for x in _labels(s) if x not in marked.get(s["iso"], ())]
            if dont:
                line("dont_miss", "Don’t miss: %s" % ", ".join(dont))
            line("guide_button", "See %s’s guide%s→" % (s["name"], NB))
            links.append(("button", g, "See %s’s guide%s→" % (s["name"], NB), WHITE, False))
        else:
            line("guide_link", "See the guide%s→" % NB)
            links.append(("text", g, "See the guide%s→" % NB, GREEN, False))

    line("ai", "✨ Open any country’s guide and tap Plan with AI for a tailored, month-aware "
               "itinerary — ChatGPT, Claude, Grok or Perplexity, your call.")
    if gems:
        line("gems", "\U0001f48e Hidden gems")
        line("gems_sub", "Under-the-radar, high-value spots the crowds miss:")
    for s in gems:
        images.append(flag(s))
        links.append(("text", guide(s), s["name"], GREEN, False))
        # (the gap after the badge: a non-breaking space and an ordinary one)
        line("gem", name(s) + NB + " " + letters(s))
        grouped.append(not by(s))
        badge(s)
    if usd:
        # The month's /cheapest page is graded from the US: the USD edition only.
        cheap = "The cheapest countries to visit in %s%s→" % (mn, NB)
        # (no 💰 here: in this email it marks the Affordability grade only)
        line("budget", "On a budget? " + cheap)
        links.append(("text", "%s/cheapest/%s" % (site, mn.lower()), cheap, GREEN, False))
    line("all_button", "See every country’s grades%s→" % NB)
    links.append(("button", "%s/?vmn=%d%s" % (site, m, vo), "See every country’s grades%s→" % NB, WHITE, False))
    line("reply", "\U0001f4ac Tell me where you’re headed — just hit reply, or write to "
                  "hello@wandergrade.com. I read every message.")
    links.append(("text", "mailto:hello@wandergrade.com", "hello@wandergrade.com", "#444", True))
    q, who, src = QUOTES[(yr * 12 + m) % len(QUOTES)]
    line("quote", "“%s”" % q)
    line("byline", "— %s, %s" % (who, src))
    if credits:
        line("credits", CREDITS_LEAD + " " + SEP.join("%s: %s, %s" % (c[0], c[1], c[3]) for c in credits))
        for c in credits:
            links.append(("text", c[2], c[1], CREDIT, False))
            if c[4]:
                links.append(("text", c[4], c[3], CREDIT, False))
    # The grade key opens the footer: the edition's home, its money and its
    # main advisory source, and the month. (newsletter._grade_key ties each
    # clause to the scoring code; test_digest_variants 8 holds the facts.)
    # The flights sentence, with what "~" means, is there when a card or gem
    # has a fare grade.
    line("key", ("Reading the grades: the badge is the Overall grade, an equal mix of the others. "
                 "{money}{nb}is mostly local prices against {home}, partly whether your {noun} goes further than "
                 "usual (against its 1-year average, after inflation). "
                 "{shield}{nb}is the {main} advisory level (Level{nb}1{nb}={nb}A, Level{nb}2{nb}={nb}B) "
                 "unless another government is named. "
                 "{sun}{nb}is {month}’s usual weather."
                 + (" {plane}{nb}is the fare against the usual for that route or distance "
                    "(~{nb}={nb}estimated)." if flights else ""))
         .format(money=MONEY, shield=SHIELD, sun=SUN, plane=PLANE, nb=NB, home=v.vs_place, noun=v.noun,
                 main=main, month=mn))
    held.append(("key", "1-year"))
    switch = "" if usd else (" Want another currency’s edition? Reply and say which, or change it in your "
                             "account on wandergrade.com (sign in with this address).")
    # The date's hyphens are U+2011 (non-breaking, same look), so a mail app
    # doesn't turn it into a blue calendar link (newsletter._date).
    as_of = d["as_of"].replace("-", "‑")
    line("footer", "Grades are for %s planning %s travel; set your home country on the site to re-grade "
                   "for you.%s Currency data as of %s." % (v.traveler, mn, switch, as_of))
    held += [("footer", "re-grade"), ("footer", as_of)]
    # (parted like two grades: a line of the brand line can't start with a dot)
    line("brand", SEP.join(("WanderGrade grades every country A+ to F", "once a month, no spam",
                            "wandergrade.com", "unsubscribe")))
    links.append(("text", site, "wandergrade.com", SMALL, True))
    links.append(("text", UNSUB, "unsubscribe", SMALL, True))
    return {"subject": "\U0001f9ed %s trips: where your %s goes furthest" % (mn, v.noun),
            "lines": lines, "links": links, "images": images, "badges": badges, "credits": credits,
            "held": held, "grouped": grouped}


# The block a line sits in: its tag, and the style it must carry (None: any
# value, but its own). Every block of words is a <div> with its own size and
# line height, or Buttondown resizes it; the intro is the one <p>, at the
# 16px/24px it is delivered at, and it and the one heading have their own
# margin.
_SMALL = {"font-size": "12px", "line-height": "18px", "margin": None}
_ROW = {"font-size": None, "line-height": None}
RULES = {
    # The brand line: the name alone, 800, about 20px, centred, a small gap under it.
    "brand_top": ("div", {"font-size": "20px", "line-height": None, "margin": None, "color": "#111",
                          "font-weight": "800", "text-align": "center"}),
    "intro": ("p", {"font-size": "16px", "line-height": "24px", "margin": None, "color": "#111"}),
    "name": ("div", dict(_ROW, color="#111")),
    "grades": ("div", dict(_ROW, color=None, margin=None)),
    # Whose advisories the top card's safety grade is: small print, like the footer.
    "source": ("div", dict(_SMALL, color=SMALL)),
    "cost": ("div", dict(_ROW, color=None, margin=None)),
    "fx": ("div", dict(_ROW, color=GREEN, margin=None)),
    "dont_miss": ("div", dict(_ROW, color=None, margin=None)),
    "guide_button": ("div", dict(_ROW, margin=None)),
    "guide_link": ("div", dict(_ROW, margin=None)),
    "ai": ("div", dict(_ROW, color=None, margin=None)),
    "gems": ("h2", {"font-size": "18px", "line-height": None, "margin": None, "color": "#111"}),
    "gems_sub": ("div", {"font-size": "13px", "line-height": "19px", "margin": None, "color": "#555"}),
    "gem": ("div", dict(_ROW, color=None, margin=None)),
    "budget": ("div", {"font-size": "14px", "line-height": "21px", "margin": None, "color": "#111"}),
    "all_button": ("div", dict(_ROW, margin=None)),
    "reply": ("div", {"font-size": "14px", "line-height": "21px", "margin": None, "color": "#444"}),
    # The quote as readers have always seen it (Buttondown delivered the old 13px <p> at 16px/24px).
    "quote": ("div", {"font-size": "16px", "line-height": "24px", "margin": None, "color": "#666",
                      "font-style": "italic", "text-align": "center"}),
    # The byline and the credits under it are the same size (newsletter._credits' note).
    "byline": ("div", dict(_SMALL, color=SMALL, **{"font-style": "normal"})),
    "credits": ("div", dict(_SMALL, color=CREDIT, **{"text-align": "center"})),
    # The grade key opens the footer (its top border); two more lines of small print follow.
    "key": ("div", dict(_SMALL, color=SMALL, **{"border-top": "1px solid #e0e0e0"})),
    "footer": ("div", dict(_SMALL, color=SMALL)),
    "brand": ("div", dict(_SMALL, color=SMALL)),
}


def _first_diff(got, want):
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else None
        w = want[i] if i < len(want) else None
        if g != w:
            return "#%d: got %r, want %r" % (i, g, w)
    return ""


def _px(node, prop="font-size"):
    m = re.match(r"^(\d+(?:\.\d+)?)px$", node.style.get(prop) or "")
    return float(m.group(1)) if m else None


def _colour(node, prop):
    """A style's colour as six lower-case digits, None when it isn't a plain hex colour."""
    val = node.style.get(prop) or ""
    return _hex6(val) if re.match("^%s$" % _HEX, val) else None


def check(nl, pk, v, d, subject, body):
    """Problems (strings) where `body` doesn't say what payload `d` says for
    edition `v`. [] when it does."""
    want, got = expected(nl, pk, v, d), Email(body)
    bad = list(got.problems)
    if subject != want["subject"]:
        bad.append("subject %r, want %r" % (subject, want["subject"]))
    lines = [t for t, _n in got.lines]
    if lines != [t for _k, t in want["lines"]]:
        return bad + ["lines " + _first_diff(lines, [t for _k, t in want["lines"]])]
    links = [(x["kind"], x["href"], x["text"], x["color"], x["underline"]) for x in got.links]
    if links != want["links"]:
        bad.append("links " + _first_diff(links, want["links"]))
    images = [(x["kind"], x["src"], x["alt"], x["href"]) for x in got.images]
    if images != want["images"]:
        bad.append("images " + _first_diff(images, want["images"]))
    # Each compact card: the photo's cell and image as THUMB_CELL ...
    # WORDS_VALIGN spell them out, and the small photo asked for at 440x336.
    bad += compact_cards(got, d["picks"])
    if (got.credits or []) != want["credits"]:
        bad.append("credits: got %r, want %r" % (got.credits, want["credits"]))
    # A linked licence's name stays on one line ("CC BY-SA 4.0" broke after
    # "CC" and at its hyphen); a photographer's name is free to wrap.
    for who, lic in got.credit_links:
        if lic is not None and lic.style.get("white-space") != "nowrap":
            bad.append("the licence %r in the credits can split across lines" % norm(lic.text()))
        if "white-space" in who.style:
            bad.append("the photographer %r in the credits can't wrap" % norm(who.text())[:30])
    node, rows = {}, []
    for (key, _t), (_t2, n) in zip(want["lines"], got.lines):
        node.setdefault(key, n)
        if key in ("name", "gem"):
            rows.append((key, n))
        tag, style = RULES.get(key, (None, {}))
        if tag and n.tag != tag:
            bad.append("%s is a <%s>, want <%s>" % (key, n.tag, tag))
        st = n.style
        for prop, val in style.items():
            if prop not in st or (val is not None and st[prop] != val):
                bad.append("%s: %s is %r, want %s" % (key, prop, st.get(prop), val or "its own"))
    # The Overall badge: one on each card and gem, the letter the payload
    # grades, in the site's colours for that letter. It comes right after the
    # name's link and is no part of it, its letter can't wrap, and the top
    # card's is the biggest.
    badges = [(norm(b.text()), _colour(b, "background"), _colour(b, "color")) for b in got.badges]
    if badges != want["badges"]:
        bad.append("badges " + _first_diff(badges, want["badges"]))
    groups = list(want["grouped"])
    for key, n in rows:
        kids = n.elements()
        b = kids[2] if len(kids) > 2 else None
        one_group = groups.pop(0) if key == "gem" and groups else False
        # (a card's row ends with its badge; a gem's four grades follow it on
        # the same row)
        if not ((len(kids) == 3 if key == "name" else len(kids) > 3) and kids[0].tag == "img"
                and kids[1].tag == "a" and any(b is x for x in got.badges)):
            bad.append("%s row %r is not flag, name link, badge%s"
                       % (key, norm(n.own_text())[:30], "" if key == "name" else ", grades"))
            continue
        if b.style.get("white-space") != "nowrap" or b.style.get("display") != "inline-block":
            bad.append("the badge after %r can wrap" % norm(kids[1].text()))
        if key == "gem":
            # The four grades are one inline-block that may wrap inside: too
            # wide for the name's line, they move to the next one together.
            # A row that names another government has no group at all.
            grp, row = kids[3], norm(n.own_text())
            boxes = [x for x in kids[3:] if "display" in x.style]
            if one_group:
                if (len(kids) != 4 or grp.tag != "span" or grp.style.get("display") != "inline-block"
                        or "white-space" in grp.style or (NB + " ") not in row
                        or norm(grp.text()) != row.split(NB + " ", 1)[1]):
                    bad.append("the grades after %r are not one group that moves to the next line together"
                               % norm(kids[1].text()))
            elif boxes:
                bad.append("the grades after %r name another government and must flow freely, not as one group"
                           % norm(kids[1].text()))
    if len(got.badges) != len(rows) or any(_px(b) is None or _px(b, "line-height") is None for b in got.badges):
        bad.append("%d badges for %d name rows, each with its own size" % (len(got.badges), len(rows)))
    elif len(rows) > 1 and rows[0][0] == "name" and not all(_px(got.badges[0]) > _px(b) for b in got.badges[1:]):
        bad.append("the top card's badge is not the biggest")
    # Words the small print must not break at a hyphen ("1-year", "re-grade",
    # the date) sit in a span that can't wrap.
    for key, words in want["held"]:
        if not any(x.tag == "span" and x.style.get("white-space") == "nowrap" and norm(x.text()) == words
                   for x in node[key].walk()):
            bad.append("%r in the %s line can break across lines" % (words, key))
    # The byline belongs to the quote; the credits come right under the quote
    # and before the footer, whose top border (on the grade key, its first
    # line) closes them off. The footer is the key, the line saying whose
    # grades these are, and the brand line, and nothing after.
    if node["byline"].parent is not node["quote"]:
        bad.append("the byline is not inside the quote block")
    after = node["quote"].next_element()
    if want["credits"]:
        if after is not node.get("credits") or "border-top" in node["credits"].style:
            bad.append("the credits block is not right under the quote")
        after = node["credits"].next_element()
    if after is not node["key"]:
        bad.append("the grade key does not follow the %s" % ("credits" if want["credits"] else "quote"))
    if (node["key"].next_element() is not node["footer"] or node["footer"].next_element() is not node["brand"]
            or node["brand"].next_element() is not None
            or "border-top" in node["footer"].style or "border-top" in node["brand"].style):
        bad.append("the footer is not the grade key, the grades-for line and the brand line, in that order")
    return bad


_HEADINGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))


def proofing(body):
    """Problems (strings) in `body` that Buttondown's stylesheets would act
    on, or that a reader couldn't read. [] when there are none. The rules
    are for both templates the account has used, Modern and Classic (the
    note above newsletter._link says what each does)."""
    e = Email(body)
    bad = list(e.problems)
    # Modern: p, ul and li arrive at 16px/24px with a 16px margin whatever we wrote.
    ps = [n for n in e.root.walk() if n.tag == "p"]
    if len(ps) != 1:
        bad.append("%d <p> (the intro is the only one allowed): %r"
                   % (len(ps), [norm(n.text())[:30] for n in ps][:4]))
    lists = sorted(set(n.tag for n in e.root.walk() if n.tag in ("ul", "ol", "li")))
    if lists:
        bad.append("list markup Buttondown resizes: %s" % ", ".join(lists))
    # Classic has no margin rule for <p> or a heading (the mail app's default
    # applies), Modern forces its own: each carries its own margin.
    for n in e.root.walk():
        if (n.tag == "p" or n.tag in _HEADINGS) and "margin" not in n.style:
            bad.append("<%s> %r has no margin of its own" % (n.tag, norm(n.text())[:30]))
    # Every link with words arrives blue unless the words sit in two spans
    # with the colour on the inner one; our text-decoration:none survives.
    for x in e.links:
        if x["kind"] != "image" and not (x["color"] and x["plain"]):
            bad.append("link %r: its words need two spans with a colour on the inner one, and "
                       "text-decoration:none on the <a>" % x["text"][:40])
    # Classic throws away an image's left and right margin
    # (img{margin-left:0!important;margin-right:0!important}): no image has
    # one, so a gap beside an image (a flag's) is the same in both templates.
    for x in e.images:
        if any(k in x["node"].style for k in ("margin", "margin-left", "margin-right")) or any(
                k in x["node"].attrs for k in ("hspace", "align")):
            bad.append("<img alt=%r> has a side margin, which Classic throws away" % x["alt"])
    # Nothing a reader sees is under 12px; the hidden preheader is the one exception.
    tops = e.root.elements()
    hidden = [n for n in e.root.walk() if n.style.get("display") == "none"]
    if len(hidden) != 1 or not tops or hidden[0] is not tops[0]:
        bad.append("the hidden preheader must be the first block, and the only hidden one")
    skip = set(id(n) for h in hidden for n in [h] + list(h.walk()))
    for n in e.root.walk():
        size = n.style.get("font-size")
        if size is None or id(n) in skip:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)px$", size)
        if not m or float(m.group(1)) < MIN_PX:
            bad.append("font-size %s on <%s> %r" % (size, n.tag, norm(n.text())[:30]))
    if "#888" in body.lower():
        bad.append("#888 is still in the body (too pale; small print is #666)")
    # Modern paints a block with no colour of its own black (div,table,td,p{color:#000}),
    # so a block that shows words outside a link sets its own.
    for n in e.root.walk():
        if n.tag in BLOCK and id(n) not in skip and norm(n.own_text(links=False)) and "color" not in n.style:
            bad.append("<%s> %r has no colour of its own" % (n.tag, norm(n.own_text())[:30]))
    # Classic gives every <div> and <p> 16px and a 1.4em line height
    # (p,div{font-size:16px;line-height:1.4em}), whatever its parent says, and
    # Modern gives neither. So every block that directly holds words (a
    # link's or a button's too: its line is the block's) sets both itself,
    # and a link that sets its own size sets its own line height.
    for n in e.root.walk():
        if n.tag in BLOCK and id(n) not in skip and norm(n.own_text()):
            for prop in ("font-size", "line-height"):
                if prop not in n.style:
                    bad.append("<%s> %r has no %s of its own" % (n.tag, norm(n.own_text())[:30], prop))
    for x in e.links:
        if x["text"] and "font-size" in x["node"].style and "line-height" not in x["node"].style:
            bad.append("link %r sets a font-size but no line-height" % x["text"][:40])
    # The brand line: once, and the first thing in the panel (the block after
    # the hidden preheader).
    panel = tops[1].elements() if len(tops) > 1 else []
    brand = [n for t, n in e.lines if t == BRAND_TOP]
    if len(brand) != 1 or not panel or brand[0] is not panel[0]:
        bad.append("the brand line %r must be there once, first in the panel (found %d)" % (BRAND_TOP, len(brand)))
    return bad


# ---- a render with its covers taken out -----------------------------------------

def _canon(node, drop):
    out = []
    for k in node.kids:
        if isinstance(k, str):
            out.append(k)
        elif id(k) not in drop:
            out.append("<%s %s>%s</%s>" % (k.tag, " ".join("%s=%r" % kv for kv in sorted(k.attrs.items())),
                                           _canon(k, drop), k.tag))
    return "".join(out)


def canon(body, covers=True):
    """`body`'s markup and text in one spelling (attribute order and white
    space evened out). covers=False leaves out every cover and its credit:
    each link that holds only a cover photo, the table cell that held
    nothing else, and the credits block. A render whose cover lookups all
    failed must equal that exactly: nothing is left in a cover's place."""
    e = Email(body)
    drop = set()
    if not covers:
        for x in e.images:
            if x["kind"] == "flag":
                continue
            a = x["node"].parent
            if a.tag == "a" and _solid(a.kids) == [x["node"]]:
                drop.add(id(a))
                if a.parent.tag == "td" and _solid(a.parent.kids) == [a]:
                    drop.add(id(a.parent))
        if e.credits_node is not None:
            drop.add(id(e.credits_node))
    return re.sub(r"\s+", " ", _canon(e.root, drop))

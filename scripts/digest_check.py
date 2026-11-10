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
                every visible line, link, image and photo credit in it must
                be the one expected() works out from the payload: the email
                says what the payload says, and nothing else;
  proofing()    the markup rules that stop Buttondown, the sender,
                restyling it in either of the two templates the account has
                used (the note above newsletter._link).

expected() is the email's spec, in plain text. When the email changes on
purpose, change expected() and RULES to say the new thing. Don't loosen
check() or proofing().

`nl` and `pk` below are a tree's newsletter and picks modules, as
digest_snapshot.install returns them. expected() takes only facts from them
(the site address, the quote list, the price band and the grade bands, each
with its own test), never the functions that write the email's HTML.
"""
import html.parser
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
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


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
    """A body read back: .lines [(text, node)], .links, .images, .credits,
    and .problems (markup that doesn't nest)."""

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
        self.credits_node = next((n for t, n in self.lines if t.startswith("Photos ")), None)
        self.credits = _credits(self.credits_node) if self.credits_node is not None else None


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


def _image(img):
    a = img.parent
    while a is not None and a.tag != "a":
        a = a.parent
    src, w = img.attrs.get("src") or "", img.attrs.get("width")
    kind = ("flag" if src.startswith("https://flagcdn.com/") else "hero" if w == "560"
            else "thumb" if w == "110" else "?")
    return {"kind": kind, "src": src, "alt": img.attrs.get("alt"), "href": a.attrs.get("href") if a else None,
            "node": img}


def _credits(node):
    """The credits block's entries as the reader gets them: [(country,
    photographer, the link on the photographer's name, licence, the link on
    the licence or None)], or a string saying what doesn't parse."""
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
    for part in flat[len(CREDITS_LEAD) + 1:].split(" · "):
        m = re.match(r"^([^\x01\x02]+): \x01(\d+)\x02, (?:\x01(\d+)\x02|([^\x01\x02]+))$", part)
        if not m:
            return "a credit that isn't 'Country: photographer, licence': %r" % part
        who = links[int(m.group(2))]
        lic = links[int(m.group(3))] if m.group(3) else None
        out.append((m.group(1), norm(who.text()), who.attrs.get("href"),
                    norm(lic.text()) if lic is not None else m.group(4),
                    lic.attrs.get("href") if lic is not None else None))
    return out


# ---- what the payload says the email must be -----------------------------------

def _labels(s):
    labels = [a if isinstance(a, str) else a.get("t", "") for a in (s.get("activities") or [])]
    return [x for x in labels if x][:2]


def _strong(s):
    """The reader's money goes further than usual here: the dollar line."""
    return s.get("fx") is not None and s["fx"] >= 3


def _cost(nl, pk, s, v):
    """The price fact, in the site's three bands (the band and its rounding
    are checked against JavaScript in test_digest_variants 2c)."""
    pl = s.get("pl")
    if not pl:
        return None
    band = nl._pl_band(pl)
    if band < 0:
        return "prices run about %d%% below %s levels" % (pk.js_round((1 - pl) * 100), v.levels_adj)
    if band > 0:
        worth = v.code == "USD" or (s.get("value") or 0) >= 68
        return "pricier than %s%s" % (v.vs_place, ", but graded worth it" if worth else "")
    return "prices about on par with %s" % v.vs_place


def expected(nl, pk, v, d):
    """{subject, lines, links, images, credits} for edition `v`'s payload `d`.

    lines    [(key, text)]: every line a reader sees, top to bottom. A line
             is one block's own text; the key names the piece (RULES).
    links    [(kind, address, words, colour, underlined)] in order.
    images   [(kind, address, alt text, the address it links to)] in order.
    credits  [(country, photographer, file page, licence, licence link)]:
             one for each card that shows a photo, in card order."""
    usd = v.code == "USD"
    m, mn, yr = d["month"], d["month_name"], d["year"]
    picks, gems = d["picks"], d["gems"]
    site = nl.SITE
    vo = "" if usd else "&vo=" + v.home_iso
    grade, safe = pk.grade, lambda s: pk.SAFE_GRADE.get(s["advLvl"], "B")
    by = lambda s: " per %s" % s["advBy"] if s.get("advBy") else ""
    guide = lambda s: "%s/?tab=guide&gc=%s&vmn=%d%s" % (site, s["iso"], m, vo)
    flag = lambda s: ("flag", "https://flagcdn.com/32x24/%s.png" % s["iso"].lower(), s["iso"], None)
    lines, links, images, credits = [], [], [], []
    line = lambda key, text: lines.append((key, text))

    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)
    pre = ("Plan ahead: after inflation, your %s goes further than usual in %d of %s’s picks."
           % (v.noun, nstrong, mn) if nstrong else
           "Plan ahead: %d destinations graded A+ to F on value, safety, weather and flights for %s."
           % (len(picks), mn))
    line("pre", pre + PAD * 10)
    line("masthead", "\U0001f30d WanderGrade")
    line("tagline", "Where Should I Travel Next?")
    line("intro", "Where’s worth it in %s %d? WanderGrade grades every country A+ to F on what your "
                  "trip actually hinges on — how far your money goes, safety, weather and flights. "
                  "The twist: we flag where your %s is unusually strong right now. %s’s standouts "
                  "\U0001f447" % (mn, yr, v.noun, mn))
    line("calendar", "\U0001f4c5 %s picks, sent two months ahead so there’s time to plan and book. "
                     "Going a different time? Pick your travel month →" % mn)
    links.append(("text", site if usd else "%s/?vo=%s" % (site, v.home_iso),
                  "Pick your travel month →", GREEN, False))
    line("top_picks", "\U0001f31f Top picks")

    for i, s in enumerate(picks):
        g, top = guide(s), i == 0
        if s.get("photo"):
            images.append(("hero" if top else "thumb", s["photo"], s["name"], g))
            links.append(("image", g, "", None, False))
            c = s.get("photo_credit")
            if c:
                credits.append((s["name"], c["artist"], c["page"], c["license"], c.get("license_url") or None))
        images.append(flag(s))
        links.append(("text", g, s["name"], GREEN, False))
        fly = s.get("fly") is not None
        if top:
            line("name", "%s — Overall %s" % (s["name"], grade(s["value"])))
            basis = ("%s vs the route’s usual" % mn if s.get("fly_basis") == "month"
                     else "year-round, for the distance")
            line("grades", "\U0001f4b0 Affordability %s · %s Safety %s%s · %s Weather %s%s"
                 % (grade(s["afford"]), SHIELD, safe(s), by(s), SUN, grade(s["wx"]),
                    " · %s Flights %s (%s)" % (PLANE, grade(s["fly"]), basis) if fly else ""))
            if _strong(s):
                line("fx", "%s After inflation, your %s goes about %d%% further here than its 1-year average."
                     % (v.fx_emoji, v.noun, pk.js_round(s["fx"])))
            cost = _cost(nl, pk, s, v)
            if cost:
                line("cost", "\U0001f4b0 Everyday %s." % cost)
            if _labels(s):
                line("dont_miss", "Don’t miss: %s" % ", ".join(_labels(s)))
            line("guide_button", "See %s’s guide →" % s["name"])
            links.append(("button", g, "See %s’s guide →" % s["name"], WHITE, False))
        else:
            line("name", "%s — %s" % (s["name"], grade(s["value"])))
            line("grades", "\U0001f4b0 %s · %s %s%s · %s %s%s"
                 % (grade(s["afford"]), SHIELD, safe(s), by(s), SUN, grade(s["wx"]),
                    " · %s %s" % (PLANE, grade(s["fly"])) if fly else ""))
            # One money line on a small card: the dollar line where it has one, else the price.
            cost = _cost(nl, pk, s, v)
            if _strong(s):
                line("fx", "%s %s goes ~%d%% further than its 1-yr average here, after inflation"
                     % (v.fx_emoji, v.noun_cap, pk.js_round(s["fx"])))
            elif cost:
                line("cost", "\U0001f4b0 %s" % (cost[0].upper() + cost[1:]))
            line("guide_link", "See the guide →")
            links.append(("text", g, "See the guide →", GREEN, False))

    line("ai", "✨ Open any country’s guide and tap Plan with AI for a tailored, month-aware "
               "itinerary — ChatGPT, Claude, Grok or Perplexity, your call.")
    if gems:
        line("gems", "\U0001f48e Hidden gems")
        line("gems_sub", "Under-the-radar, high-value spots the crowds miss:")
    for s in gems:
        images.append(flag(s))
        links.append(("text", guide(s), s["name"], GREEN, False))
        line("gem", "%s — %s · \U0001f4b0 %s · %s %s%s · %s %s%s"
             % (s["name"], grade(s["value"]), grade(s["afford"]), SHIELD, safe(s), by(s), SUN, grade(s["wx"]),
                " · %s %s" % (PLANE, grade(s["fly"])) if s.get("fly") is not None else ""))
    if usd:
        # The month's /cheapest page is graded from the US: the USD edition only.
        cheap = "The cheapest countries to visit in %s →" % mn
        line("budget", "\U0001f4b0 On a budget? " + cheap)
        links.append(("text", "%s/cheapest/%s" % (site, mn.lower()), cheap, GREEN, False))
    line("all_button", "See every country’s grades →")
    links.append(("button", "%s/?vmn=%d%s" % (site, m, vo), "See every country’s grades →", WHITE, False))
    line("reply", "\U0001f4ac Tell me where you’re headed — just hit reply, or write to "
                  "hello@wandergrade.com. I read every message.")
    links.append(("text", "mailto:hello@wandergrade.com", "hello@wandergrade.com", "#444", True))
    q, who, src = nl.QUOTES[(yr * 12 + m) % len(nl.QUOTES)]
    line("quote", "“%s”" % q)
    line("byline", "— %s, %s" % (who, src))
    if credits:
        line("credits", CREDITS_LEAD + " " + " · ".join("%s: %s, %s" % (c[0], c[1], c[3]) for c in credits))
        for c in credits:
            links.append(("text", c[2], c[1], CREDIT, False))
            if c[4]:
                links.append(("text", c[4], c[3], CREDIT, False))
    switch = "" if usd else (" Want another currency’s edition? Reply and say which, or change it in your "
                             "account on wandergrade.com (sign in with this address).")
    line("footer", "Grades are for %s planning %s travel; set your home country on the site to re-grade "
                   "for you.%s Currency data as of %s." % (v.traveler, mn, switch, d["as_of"]))
    line("brand", "WanderGrade · once a month, no spam · wandergrade.com · unsubscribe")
    links.append(("text", site, "wandergrade.com", SMALL, True))
    links.append(("text", nl.UNSUB, "unsubscribe", SMALL, True))
    return {"subject": "\U0001f9ed %s trips: where your %s goes furthest" % (mn, v.noun),
            "lines": lines, "links": links, "images": images, "credits": credits}


# The block a line sits in: its tag, and the style it must carry (None: any
# value, but its own). Small print is a <div> with its own size, line height
# and margin, or Buttondown resizes it; the intro is the one <p>.
_SMALL = {"font-size": "12px", "line-height": "18px", "margin": None}
RULES = {
    "intro": ("p", {}),
    "calendar": ("div", {"font-size": "13px", "line-height": "19px", "margin": None, "color": "#555"}),
    "gems_sub": ("div", {"font-size": "13px", "line-height": "19px", "margin": None, "color": "#555"}),
    "budget": ("div", {"font-size": "14px", "line-height": "21px", "margin": None, "color": "#111"}),
    "reply": ("div", {"font-size": "14px", "line-height": "21px", "margin": None, "color": "#444"}),
    # The quote as readers have always seen it (Buttondown delivered the old 13px <p> at 16px/24px).
    "quote": ("div", {"font-size": "16px", "line-height": "24px", "margin": None, "color": "#666",
                      "font-style": "italic", "text-align": "center"}),
    # The byline and the credits under it are the same size (newsletter._credits' note).
    "byline": ("div", dict(_SMALL, color=SMALL, **{"font-style": "normal"})),
    "credits": ("div", dict(_SMALL, color=CREDIT, **{"text-align": "center"})),
    "footer": ("div", dict(_SMALL, color=SMALL, **{"border-top": "1px solid #e0e0e0"})),
    "brand": ("div", dict(_SMALL, color=SMALL)),
}


def _first_diff(got, want):
    for i in range(max(len(got), len(want))):
        g = got[i] if i < len(got) else None
        w = want[i] if i < len(want) else None
        if g != w:
            return "#%d: got %r, want %r" % (i, g, w)
    return ""


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
    if (got.credits or []) != want["credits"]:
        bad.append("credits: got %r, want %r" % (got.credits, want["credits"]))
    node = {}
    for (key, _t), (_t2, n) in zip(want["lines"], got.lines):
        node.setdefault(key, n)
        tag, style = RULES.get(key, (None, {}))
        if tag and n.tag != tag:
            bad.append("%s is a <%s>, want <%s>" % (key, n.tag, tag))
        st = n.style
        for prop, val in style.items():
            if prop not in st or (val is not None and st[prop] != val):
                bad.append("%s: %s is %r, want %s" % (key, prop, st.get(prop), val or "its own"))
    # The byline belongs to the quote; the credits come right under the quote
    # and before the footer, whose top border closes them off.
    if node["byline"].parent is not node["quote"]:
        bad.append("the byline is not inside the quote block")
    after = node["quote"].next_element()
    if want["credits"]:
        if after is not node.get("credits") or "border-top" in node["credits"].style:
            bad.append("the credits block is not right under the quote")
        after = node["credits"].next_element()
    if after is not node["footer"]:
        bad.append("the footer does not follow the %s" % ("credits" if want["credits"] else "quote"))
    return bad


def _block_of(n):
    n = n.parent
    while n is not None and n.tag not in BLOCK:
        n = n.parent
    return n


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
    # Every link with words arrives blue unless the words sit in two spans
    # with the colour on the inner one; our text-decoration:none survives.
    for x in e.links:
        if x["kind"] != "image" and not (x["color"] and x["plain"]):
            bad.append("link %r: its words need two spans with a colour on the inner one, and "
                       "text-decoration:none on the <a>" % x["text"][:40])
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
    # Classic makes a <div> or <p> with no font-size of its own 16px, whatever
    # its parent says (p,div{font-size:16px}), so one that shows words sets
    # its own; a link's words may take the link's size instead (the buttons).
    for n in e.root.walk():
        if n.tag not in ("div", "p") or id(n) in skip or "font-size" in n.style:
            continue
        loose = [x["text"] for x in e.links if x["text"] and "font-size" not in x["node"].style
                 and _block_of(x["node"]) is n]
        if norm(n.own_text(links=False)) or loose:
            bad.append("<%s> %r has no font-size of its own" % (n.tag, norm(n.own_text())[:30]))
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

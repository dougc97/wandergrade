"""Per-country safety watchouts, distilled from Global Affairs Canada's
structured advisory pages (data.international.gc.ca, the same source the
Canadian advisory levels come from).

The rule everywhere on this site is that we do not AUTHOR safety claims —
so this module never summarizes in its own words. Canada's pages are built
from consistent h3 sections ("Crime", "Swimming", "Road safety"...) with a
lead paragraph each; we lift the section title and its first sentence
verbatim. Regional advisories ("Chihuahua - Avoid non-essential travel")
arrive as their own headed blocks and pass through the same way. The full
page is always linked.

Canada is used for ALL travelers' watchouts (clearly attributed) because
theirs is the only feed that ships the structured text as data; the LEVEL
shown beside it still follows the traveler's own government.
"""

import html as _html
import re
import sys
import time
from html.parser import HTMLParser

from . import rates

API = "https://data.international.gc.ca/travel-voyage/cta-cap-{iso}.json"
TTL = 6 * 3600
FAIL_TTL = 10 * 60   # a network blip is retried soon, not trusted for 6h
_cache = {}   # iso -> (fetched_at, payload)

# Section titles that describe the page, not the country.
_SKIP = re.compile(r"risk level|why do we|about (the|this)|more information", re.I)


def _txt(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment or "")
    s = _html.unescape(re.sub(r"\s+", " ", s)).strip()
    return re.sub(r"\s+([.,;:])", r"\1", s)


def _first_sentence(html_block):
    p = re.search(r"<p[^>]*>(.*?)</p>", html_block or "", re.S)
    if not p:
        return ""
    lead = _txt(p.group(1))
    return re.split(r"(?<=[.!?])\s+", lead)[0][:220] if lead else ""


def _sections(html_str):
    """[{t: heading, d: first sentence}] for each h3-headed block."""
    out = []
    parts = re.split(r"<h3[^>]*>", html_str or "")
    for chunk in parts[1:]:
        m = re.match(r"(.*?)</h3>(.*)", chunk, re.S)
        if not m:
            continue
        title = _txt(m.group(1))
        if not title or _SKIP.search(title):
            continue
        out.append({"t": title[:90], "d": _first_sentence(m.group(2))})
    return out


def _top_level_items(fragment):
    """Region names from the FIRST-level <ul> of a regional-advisory block.
    The source nests each region's exclusion list inside its <li> — or, when
    the HTML is malformed (Sinaloa on the Mexico page), as a sibling <ul>
    right after it — so a depth counter, not a tree, finds the regions."""
    out, cur, depth, pos = [], None, 0, 0
    for m in re.finditer(r"<(/?)(ul|li)[^>]*>", fragment, re.I):
        if cur is not None and depth == 1:
            cur.append(fragment[pos:m.start()])
        pos = m.end()
        closing, tag = m.group(1) == "/", m.group(2).lower()
        if tag == "ul":
            depth += (-1 if closing else 1)
            if depth != 1 and cur is not None:
                out.append("".join(cur)); cur = None
            if depth == 0:
                break                      # first top-level list only
        elif tag == "li" and depth == 1:
            if cur is not None:
                out.append("".join(cur))
            cur = [] if not closing else None
    if cur:
        out.append("".join(cur))
    regions = []
    for raw in out:
        t = _txt(raw)
        if not t:
            continue
        # "Chihuahua, excluding Chihuahua City" -> "Chihuahua*" — the star says
        # exceptions exist; the linked page has them.
        base = re.split(r",?\s+(?:excluding|except|within|in all areas|only if)\b", t, flags=re.I)[0].strip(" ,:;")
        if base and base.lower() not in (r.rstrip("*").lower() for r in regions):
            regions.append(base + ("*" if base != t.strip(" ,:;") else ""))
    return regions[:14]



# ---------------------------------------------------------------------------
#  Regional advisories, read as Canada wrote them
# ---------------------------------------------------------------------------
# Each regional block is an h3 ("Border with Somalia - Avoid all travel")
# over paragraphs and lists. What a block MEANS is spread across all of it:
# the area is in the first sentence ("Avoid all travel to Mandera, Wajir,
# Garissa and Lamu counties bordering Somalia, due to …"), the exceptions in
# a later one ("This advisory excludes Lamu Island and Manda Island …"), a
# list can be the area itself (Western Mindanao's provinces), a band's states
# (India), the exceptions (Karachi), what the area takes in (northern Sinai's
# governorates), or a tree (a state, then the cities excluded from it). The
# first cut kept one sentence cut at 200 characters, the first list and its
# top level, and four blocks; it showed Israel's guide the two roads Canada
# EXCEPTS from Palestine, dropped Kenya's Lamu Island exception and Israel's
# Lebanon and Gaza lines, and read Mexico's "Jalisco, within 50 km of the
# border with Michoacán" as all of Jalisco. So the block is read whole here
# (_Body), and its one-line forms (line; full, the line uncut; brief) are
# written here once, from Canada's own words — selected and shortened, never
# restated — for the guide, the Safety table, the server's stand-in and the
# AI prompts alike. Short of room, a line names every place before any
# detail (_fill, _least: "parts of Cortés", "Colón (parts excepted)",
# "parts of Amazonas"), flags every excepted place or none (_line), its
# "and N more" counts places (_count), several exceptions come under words
# that say they are exceptions, each of Canada's sentences its own
# (_compose), and an exception is never said wider than Canada wrote it
# (_shorten); full, the guide's AI prompt, is never shortened at all.
# Canada's sentence on its exceptions (Colombia's "If you intend to travel
# to any of the above excluded areas, do so by air") follows every form that
# names them, and none that only flags them (_conds). A
# notice with no call and no area is no advisory and is left out (_notice).
# Canada's "we advise" is said "Canada advises" (_third): beside the
# traveller's own government's level, "we" read as that government's.

REGIONAL_CAP = 12   # Israel and Palestine has 6, the most on 2026-10-14
LINE_CAP = 260      # the guide's 📍 line, after the call: lists are cut to it
LINE_MAX = 359      # …and nothing goes past this: only to name every place
                    # (Benin's four bands and Canada's sentence for its parks,
                    # 359; Pakistan's seven, 352; Mauritania's regions, 347;
                    # Tunisia's four, 335) or where nothing can be cut
                    # (northern Sinai's area and exception)
BRIEF_CAP = 120     # the trip prompt's line per area, when it is whole or a heading
BRIEF_ITEMS = 10    # …and the places it names of a long list (as many as before the line),
BRIEF_NAMES = 500   # in about as many characters as they took then — every place where
                    # they all fit in that at their shortest (_names); a heading with
                    # what its block includes too (northern Sinai's governorates)
TEXT_CAP = 2000     # the tip: Canada's full text, cut at a line or sentence

# Canada's calls, mildest first: an exception "where you should exercise a
# high degree of caution" is milder than an avoid-all block and can go when
# a line is short of room; one "where you should avoid all travel" (Tanzania's
# 10 km band inside its avoid-non-essential area) is stricter and never goes.
_CALLS = ["take normal security precautions", "exercise a high degree of caution",
          "avoid non-essential travel", "avoid all travel"]
# A call however the feed spells it: "non‑essential" with a non-breaking
# hyphen, "non essential", a no-break space between words (_norm).
_NE = r"non[\s\u2010-\u2015\u2212-]*essential"
_CALL_RX = (r"(?:avoid\s+all\s+travel|avoid\s+" + _NE + r"\s+travel|exercise\s+a\s+high\s+degree\s+of\s+caution|"
            r"take\s+normal\s+security\s+precautions)")
_LEAD_CALL = re.compile(r"^(" + _CALL_RX + r")\b[\s:]*(?:(?:to|in|on)\b\s*)*", re.I)   # "to to" (Mozambique), "on the east coast" (Sabah)
# "where you should exercise a high degree of caution", "on which you
# should …", "to which you should …", Ecuador's "where we advise against
# all travel" (said "where Canada advises …" on the site, _third).
_WHERE = re.compile(r",?\s+(?:where|on which|to which|in which)\s+(?:you should|we advise|Canada advises)\s+"
                    r"(avoid\s+all\s+travel|(?:advise\s+)?against\s+all\s+travel|avoid\s+" + _NE + r"\s+travel|"
                    r"exercise\s+a\s+high\s+degree\s+of\s+caution|take\s+normal\s+security\s+precautions)\b", re.I)


_WE = re.compile(r"\bwe\s+((?:strongly|also|still)\s+)?(advise|recommend|urge|encourage|ask)\b", re.I)


def _third(s):
    """Canada's first person said as Canada: Ecuador's "except within 20 km
    of the border with Colombia where we advise against all travel" read, on
    a site that gives the traveller's own government's level beside it, as
    WanderGrade's advice — or that government's. "where Canada advises
    against all travel". The line, the brief and the guide's AI prompt say
    it so (that prompt credits Global Affairs Canada in a heading, in a
    prompt the traveller speaks in the first person: "we" there is theirs);
    the ⓘ quotes Canada's text as Canada's and keeps "we"."""
    return _WE.sub(lambda m: "Canada " + (m.group(1) or "").lower() + m.group(2).lower() + "s", s or "")


def _norm(s):
    """A call as _CALLS spells it, whatever hyphen or space the feed used."""
    s = re.sub(r"\s+", " ", s or "").strip()
    return re.sub(_NE, "non-essential", s, flags=re.I)


def _canon(call):
    """The call _CALLS has for these words, capitalized, or None."""
    c = _norm(call).lower()
    return c.capitalize() if c in _CALLS else None
# Headings that name no place ("Regional advisory - Avoid all travel"):
# they never stand for their list — Cauca and Buenaventura aren't "Border
# areas" to a reader or an AI.
_GENERIC = re.compile(r"^(?:regional (?:advisory|advisories|risk level)|border (?:areas?|regions?))$", re.I)
# An item's own exception: "Caquetá, excluding the city of Florencia",
# "Meta, excluding:" (a list follows), "Carchi (except for the Panamerican
# Highway …)". "within", "in all areas south of" and "only if" are not
# exceptions: "Amazonas, within 20 km of the border with Peru" is a strip of
# Amazonas, not Amazonas with parts excepted.
_EXC_PAREN = re.compile(r"\s*\((?:excluding|except(?: for)?|with the exception of)\s+((?:[^()]|\([^()]*\))*)\)", re.I)
_EXC_INLINE = re.compile(r"(?:,\s*|\s+)(?:excluding|except(?: for)?|with the exception of)(?=[\s:]|$)\s*:?\s*(.*)$", re.I | re.S)
# group 1: Canada's own opening ("This advisory also excludes"), which a line
# quoting the sentence keeps; group 2: what it excludes or includes.
_ADVISORY = r"^(this (?:advisory|warning) (?:also )?"
_EXCLUDES = re.compile(_ADVISORY + r"(?:excludes|does not (?:include|apply to)))\s*:?\s*(.*?)[.:]?$", re.I | re.S)
_INCLUDES = re.compile(_ADVISORY + r"includes)\s*:?\s*(.*?)[.:]?$", re.I | re.S)
# A later sentence that refers back to the block's exceptions: Colombia's "If
# you intend to travel to any of the above excluded areas, do so by air."
# Every other sentence _analyze leaves out (2026-10-15: Armenia's and India's
# closed crossings, the consular-reach and recognition sentences, Ethiopia's
# "could spread to major cities", Jammu and Kashmir's threats) is background
# and conditions neither a place nor an exception.
_EXC_KIND = r"(?:areas?|places?|cities|city|towns?|locations?|roads?|zones?|regions?|sites?)"
_COND = re.compile(r"\b(?:the|these|those|such|said)\s+(?:above\s+|listed\s+)?(?:excluded|excepted|exempted)\s+" + _EXC_KIND + r"\b"
                   r"|\b(?:the|these|those)\s+(?:above\s+)?(?:exclusions|exceptions)\b|\b" + _EXC_KIND + r"\s+(?:excluded|excepted)\s+above\b",
                   re.I)
# A form that names an exception: "(except …", "— except …", ". Except …",
# Canada's "This advisory excludes …"; never "(parts excepted)" or a star.
_SAYS_EXC = re.compile(r"\bexcept\b|\bexcludes\b|\bdoes not (?:include|apply to)\b", re.I)
# Words that take the list after them as their object ("…, especially:",
# "the municipalities of:"): the list follows them directly.
_OBJECT_END = re.compile(r"\b(?:of|in|especially|including|particularly|notably|namely)$", re.I)


# A non-restrictive aside closing an area: "the area within 1 km of the
# border with Armenia, which is closed". Nothing is attached straight after
# one — ", except …" and " (parts excepted)" read as excepting from the
# aside ("closed, except Nakhchivan": an open crossing).
_ASIDE = re.compile(r",\s+(?:which|where)\b[^,;:()]*$", re.I)


def _unaside(s):
    """An area without its closing aside, before a tag a brief or a line
    attaches to it: "the area within 1 km of the border with Armenia (parts
    excepted)", never "…, which is closed (parts excepted)"."""
    return _ASIDE.sub("", s or "")


def _clean(s):
    s = re.sub(r"\s+", " ", s or "").strip()      # \s takes the feed's &nbsp; too
    s = re.sub(r"\s+([.,;:)])", r"\1", s)
    return re.sub(r"\(\s+", "(", s)


def _unshout(s):
    """Israel's headings come in capitals ("PALESTINE - AVOID ALL TRAVEL")."""
    if re.search(r"[a-z]", s) or not re.search(r"[A-Z]{2}", s):
        return s
    s = re.sub(r"(^|[\s(-])(\w)", lambda m: m.group(1) + m.group(2).upper(), s.lower())
    return re.sub(r" (And|Of|The|With|In) ", lambda m: m.group(0).lower(), s)


def _rank(call):
    c = _norm(call).lower()
    if "all travel" in c:
        return 3
    return _CALLS.index(c) if c in _CALLS else -1


_ABBR = {"st", "ste", "mt", "mts", "ft", "pt", "rd", "no", "nos", "hwy", "ave", "approx", "etc", "vs", "dr", "gen"}


def _sentences(t):
    """Sentences of one paragraph. Canada writes "north of St. Catherine –
    Nuweiba – El Tor Road" (the old cut ended Egypt's sentence there): a stop
    after a known abbreviation or an initial ("U.S.") doesn't end one."""
    out, start = [], 0
    for m in re.finditer(r"[.!?](?=\s+[\"“(A-Z0-9])", t):
        w = re.search(r"(\S+)$", t[start:m.start()])
        w = w.group(1) if w else ""
        if w.lower() in _ABBR or re.fullmatch(r"(?:.*\.)?[A-Z]", w):
            continue
        out.append(t[start:m.end()].strip())
        start = m.end()
    if t[start:].strip():
        out.append(t[start:].strip())
    return out


class _Body(HTMLParser):
    """One block's body as a sequence of ("p", text) and ("ul", [item]),
    item = {"t": its own text, "items": [sub-items]}. The feed's HTML is
    loose — paragraphs left open around lists, items left unclosed, and a
    state's exclusion list as a sibling <ul> after its <li> rather than
    inside it (Jalisco and Chocó) — so a list opened between items belongs
    to the item before it."""

    _BREAK = {"p", "div", "br", "h4", "h5", "h6", "section", "table", "tr"}
    # A paragraph opened between items, not inside one, ends the lists: a
    # list left unclosed (or bare <li>s with no <ul>) would otherwise take
    # the "This advisory excludes …" after it as one more listed place.
    _ENDS_LIST = {"p", "div", "h4", "h5", "h6", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self._buf, self._open = [], [], []

    def _para(self):
        t = _clean("".join(self._buf))
        self._buf = []
        if t:
            self.nodes.append(("p", t))

    def _data(self, s):
        if not self._open:
            self._buf.append(s)
            return
        top = self._open[-1]
        if top["cur"] is None:
            if not s.strip():
                return
            top["cur"] = {"t": "", "items": []}      # text between items
            top["items"].append(top["cur"])
        top["cur"]["t"] += s

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            if not self._open:
                self._para()
                items = []
                self.nodes.append(("ul", items))
            else:
                top = self._open[-1]
                host = top["cur"] or (top["items"][-1] if top["items"] else None)
                items = host["items"] if host is not None else top["items"]
            self._open.append({"items": items, "cur": None})
        elif tag == "li":
            if not self._open:
                self.handle_starttag("ul", [])
            top = self._open[-1]
            top["cur"] = {"t": "", "items": []}
            top["items"].append(top["cur"])
        elif tag in self._ENDS_LIST and self._open and self._open[-1]["cur"] is None:
            self._open = []
            self._para()
        elif tag in self._BREAK:
            self._data(" ") if self._open else self._para()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            if self._open:
                self._open.pop()
        elif tag == "li":
            if self._open:
                self._open[-1]["cur"] = None
        elif tag in self._BREAK:
            self._data(" ") if self._open else self._para()

    def handle_data(self, data):
        self._data(data)

    def close(self):
        super().close()
        self._open = []
        self._para()


def _tidy(items):
    out = []
    for it in items:
        t, kids = _clean(it["t"]), _tidy(it["items"])
        if t or kids:
            out.append({"t": t, "items": kids})
    return out


def _body(fragment):
    # A "Useful links" list (Uganda's Ebola notice) is navigation, not advice,
    # and a paragraph that is only a link to another section of the page
    # ("Natural disasters and climate") says nothing here.
    fragment = re.split(r"<h4[^>]*>\s*(?:useful|related) links", fragment or "", flags=re.I)[0]
    fragment = re.sub(r'<p[^>]*>\s*<a[^>]*href="#(?!levels)[^"]*"[^>]*>[^<]*</a>\s*</p>', "", fragment)
    p = _Body()
    p.feed(fragment)
    p.close()
    return [(k, v if k == "p" else _tidy(v)) for k, v in p.nodes if k == "p" or _tidy(v)]


def _export(items):
    """The tree as the API serves it: {t} with {items} only where it has some."""
    return [dict({"t": it["t"]}, **({"items": _export(it["items"])} if it["items"] else {})) for it in items]


def _plain_text(nodes):
    """The tip: every paragraph and list item in order, a bullet per item
    (◦ under it, ▪ under that — the tip keeps line breaks, not indents),
    cut at a line or a sentence near TEXT_CAP."""
    lines = []

    def walk(items, depth):
        for it in items:
            if it["t"]:
                lines.append(("•", "◦", "▪")[min(depth, 2)] + " " + it["t"])
            walk(it["items"], depth + 1)

    for kind, v in nodes:
        if kind == "p":
            lines.append(v)
        else:
            walk(v, 0)
    out = ""
    for ln in lines:
        nxt = (out + "\n" if out else "") + ln
        if len(nxt) <= TEXT_CAP:
            out = nxt
            continue
        room = TEXT_CAP - len(out) - 2
        part = ""
        for s in _sentences(ln):
            if len(part) + len(s) + 1 > room:
                break
            part = (part + " " + s).strip()
        out = (out + "\n" if out else "") + (part + " …" if part else "…")
        break
    return out


def _unstop(s):
    """An item without its closing full stop, which in a line of items
    joined by "; " stopped it mid-list (Mauritania's "…-Sélibali line.");
    an abbreviation's or an initial's stays ("St.", "U.S.")."""
    m = re.search(r"(\S+)\.$", s or "")
    if m and m.group(1).lower() not in _ABBR and not re.fullmatch(r"(?:.*\.)?[A-Z]", m.group(1)):
        return s[:-1]
    return s


def _split_exc(text):
    """(base, exception or None): "Caquetá, excluding the city of Florencia"
    -> ("Caquetá", "the city of Florencia"); "Meta, excluding:" -> ("Meta", "")."""
    m = _EXC_PAREN.search(text)
    if m:
        return _unstop(_clean(text[:m.start()] + text[m.end():]).rstrip(" ,:")), _clean(m.group(1))
    m = _EXC_INLINE.search(text)
    if m and m.start() > 0:
        return text[:m.start()].rstrip(" ,:"), _unstop(_clean(m.group(1)).rstrip(" :"))
    return text, None


def _shorten(s, cx, intro=False):
    """An exception, said shorter when a line is short of room: its "where
    you should <call>" goes when that call is milder than the block's AND no
    stricter than the country's own level (cx["floor"]), which is what a
    reader assumes for an excepted place — Pakistan's Haripur "where you
    should exercise a high degree of caution" is the country's level and
    can go, its Chitral "where you should avoid non-essential travel" is
    stricter than that and stays, as does Tanzania's 10 km band "where you
    should avoid all travel". So do the exception's asides — "(and highway
    186 leading there)", "(which is currently closed)" — and a bare "the
    following areas" before its list, unless `intro`: there it is what says
    the list after it is all exceptions (Karachi's "except the following
    areas: …"; see _compose). Each only narrows what reads as excepted: the
    safe way to be short. Not "the city of" before a name: "Colón (except
    Trujillo)" excepted what reads as all of Trujillo (a municipality too),
    where Canada excepts the city — wider than Canada, the one thing an
    exception must never be. Not "(formerly Karachi South)": without it
    Karachi's line read "the city of Karachi, except District of Karachi".
    Nor an acronym's "(DHA)", which the same item goes on to use
    ("northeast of DHA Phase 1"). cx["keep_calls"]: a list where one
    exception keeps its call keeps every one's (_fill), so a bare one never
    follows "…, where you should avoid all travel" as if under it."""
    if not cx.get("keep_calls"):
        s = _WHERE.sub(lambda m: "" if _droppable(m.group(1), cx) else m.group(0), s)
    s = _clean(re.sub(r"\s*\((?:and|which)\b[^()]*\)", "", s))
    return s if intro else re.sub(r"^the following (?:areas?|locations?)$", "", s, flags=re.I)


def _droppable(call, cx):
    """Whether an exception's "where you should <call>" can go (_shorten):
    milder than the block's and no stricter than the country's level."""
    floor = cx.get("floor")
    floor = 0 if floor is None or floor < 0 else floor
    r = _rank(call)
    return 0 <= r < cx["rank"] and r <= floor


def _keeps_call(text, cx):
    """Whether an exception's text carries a call _shorten keeps."""
    return any(not _droppable(m.group(1), cx) for m in _WHERE.finditer(text or ""))


def _sep(parts):
    """The joint for a list: a comma while every part is a bare name, a
    semicolon once any carries a comma, a colon or a bracket ("Cesar, in the
    municipalities of González and Río de Oro"; "southern Songkhla province
    (Hat Yai city; …)"), its own call ("Chitral district where you should
    avoid non-essential travel" would take Haripur with it after a comma),
    or is a phrase rather than a name: Morocco's "within 30 km west of the
    militarized zone of the Berm, between the Berm and neighbouring
    countries …" read as one area described twice, where Canada lists two."""
    return "; " if any(re.search(r"[,;:(]|\b(?:where|which) (?:you should|we advise|Canada advises)\b|^(?:[a-z]|\d+\s*(?:km|kilometres)\b)", x)
                       for x in parts) else ", "


def _join(parts):
    return _sep(parts).join(parts)


def _more(n):
    return "and %d more" % n


_BAND = re.compile(r"^(within \d+ (?:km|kilometres) of the border with )(.+)$", re.I)


def _bands(parts):
    """Brazil's eight "within 20 km of the border with X" said once each
    distance: "within 20 km of the border with Bolivia (except Pantanal
    National Park), Colombia, French Guiana, …". Only Canada's words, less
    their repeats, and only for places named bare (a comma in one, even in
    its exceptions, would blur where the next begins; "(parts excepted)"
    has none: Honduras's "within 20 km of the border with Guatemala (parts
    excepted), El Salvador (parts excepted)"); used wherever a list is said
    with nothing hidden (_fill), as Benin's two 50 km bands are."""
    out = []      # [band words or None, [places]]
    for p in parts:
        m = _BAND.match(p)
        band = m.group(1) if m and not re.search(r"[,;]", m.group(2)) else None
        if band and out and out[-1][0] and out[-1][0].lower() == band.lower():
            out[-1][1].append(m.group(2))
        else:
            out.append([band, [m.group(2) if band else p]])
    return [(b + ", ".join(ps)) if b else ps[0] for b, ps in out]


# Words that put their list in brackets after them: "District of Karachi
# (formerly Karachi South), including:" reads "… (including Clifton area;
# …)" — "including (Clifton area; …)" was the line's roughest edge.
_INCL_END = re.compile(r",?\s*\b(including|especially|particularly|notably|namely|in particular)$", re.I)


def _has_exclusion(items):
    return any(_split_exc(it["t"])[1] is not None for it in _walk(items))


def _cuttable(kids, depth, boundary):
    """Whether a sub-list may be cut to "and N more". depth is the kids'
    own: 0 places, odd inside an exception, even past 0 an exclusion from
    one (back under the block's call). Cutting places hides some, which the
    count says; cutting exceptions makes the line stricter than Canada,
    never looser. So: places, yes; whole exceptions under the word that
    excepts them, yes (an exception's own exclusions go with it); the parts
    of one exception only while none carries an exclusion of its own —
    Karachi's District of Karachi "including" the DHA phases "excluding"
    their northwest: cut, the phases' exclusion would go and the district
    would stand, excepting more than Canada does; and nothing in an
    exclusion, which cut would widen the exception around it."""
    if depth == 0:
        return True
    if depth % 2 == 0:
        return False
    return boundary or not _has_exclusion(kids)


_OF_END = re.compile(r"\b(?:of|in)$", re.I)
# "all of the following regions:" — each one whole, a place in its own right.
_ALL_OF = re.compile(r"\ball of\b", re.I)
_EMPH = re.compile(r",?\s*\b(?:especially|particularly|notably|namely|in particular)\b.*$", re.I | re.S)
_TAKES = re.compile(r",?\s*\bincluding\b.*$", re.I | re.S)


def _heading(text):
    """An item's words as they head its list: "the following" and the colon go."""
    return _unstop(re.sub(r"^the following\s+", "", text, flags=re.I).rstrip(" :"))


def _place(text):
    """The place a heading names, without the words that bring on its list:
    "Cortés:" -> "Cortés"; "District of Karachi (formerly Karachi South),
    including:" -> "District of Karachi (formerly Karachi South)"."""
    return _TAKES.sub("", _EMPH.sub("", _heading(text))).rstrip(" ,:")


def _parts_of(text):
    """ "parts of <the place>", or None where no place can take it: "in
    Escuintla Department" is "parts of Escuintla Department"; "The oases
    of" or "within 50 km of …" name none."""
    p = re.sub(r"^in\s+", "", _place(text), flags=re.I)
    return None if _OF_END.search(p) or re.match(r"(?:within|on|along)\b", p, re.I) else "parts of " + p


# A place named, then the part of it Canada means: "Amazonas, within 20 km
# of the border with Peru, west of Puerto Narino", "Cesar, in the
# municipalities of González and Río de Oro", "Antioquia, the area along the
# border with Choco department …" — "parts of Amazonas" at its shortest.
_QUAL = re.compile(r"^([^,;:()]+?),\s+(?:within|in(?!\s+particular\b)|the\s+areas?|all\s+areas|along|north|south|"
                   r"east|west|near|between)\b", re.I)
# A heading over parts of a place that says so: "the following areas of
# northern Guayaquil:" is "areas of northern Guayaquil" at its shortest.
_AREAS = re.compile(r"^(?:specific\s+)?(?:areas|parts|neighbourhoods|sections)\s+(?:of|in)\s+\S", re.I)


def _qualified(text):
    """The place a qualified item is a part of ("Amazonas"), or None: a
    name, capitalized and short, never a phrase ("within 50 km of the
    border with Nigeria, north of …"), and never where the item takes in
    more ("…, including the oasis of Dakhla")."""
    m = _QUAL.match(text or "")
    if not m or re.search(r"\bincluding\b", text, re.I):
        return None
    p = m.group(1).strip()
    if not p[:1].isupper() or len(p) > 40 or re.match(r"(?:the|within|along|on|in|areas?|all|north|south|east|west)\b", p, re.I):
        return None
    return p


def _kind(item, under_of=False):
    """What a listed item is, which decides its shortest honest form
    (_least) and what "and N more" counts for it (_count):
      leaf   a place with nothing under it
      exc    a place with its own exceptions ("Colón, excluding the city of
             Trujillo"; "Meta, excluding:" over a list)
      of     words its list completes ("in the departments of:"): each item
             under it is a place in its own right — Honduras's departments,
             Mauritania's "all of the following regions:"
      part   one of those whose own list names only parts of it (Honduras's
             "Cortés:", three neighbourhoods and two cities)
      emph   a place whose list singles out parts of it ("District of San
             Miguelito, especially the following areas:")
      whole  one whose list singles out whole regions ("northern and eastern
             Mauritania, especially: all of the following regions:"): they
             are places to name where the line has room past its cap (_line)
      takes  a place whose list it takes in ("the governorate of Kasserine,
             including … the following mountains:" — Mghila reaches into
             Sidi Bouzid, so its list can go past the place)
      group  a heading over places ("in Escuintla Department:", "CA-02:"):
             its places count, not itself"""
    if _split_exc(item["t"])[1] is not None:
        return "exc"
    if not item["items"]:
        return "leaf"
    h = _heading(item["t"])
    if _OF_END.search(h) or _ALL_OF.match(h):
        return "of"
    em = _EMPH.search(h)
    if em:
        return "whole" if _ALL_OF.search(em.group(0)) or all(_ALL_OF.match(_heading(k["t"])) for k in item["items"]) else "emph"
    if _TAKES.search(h):
        return "takes"
    # "in Escuintla Department:" says where its places are, under an "of"
    # heading too: never "parts of in Escuintla Department".
    return "part" if under_of and not re.match(r"(?:in|within|on|along)\b", h, re.I) else "group"


def _count(item, under_of=False):
    """How many places an item is to "and N more": a heading over places
    counts its places — Guatemala's "Municipalities: in Guatemala Department
    (San Pedro Ayampuc, and 1 more); and 1 more" hid the three of Escuintla
    Department as one, its border crossings' "and 7 more" nine crossings."""
    k = _kind(item, under_of)
    if k in ("of", "group"):
        return sum(_count(x, k == "of") for x in item["items"])
    return 1


def _lets_off(item, cx):
    """Whether every exception an item states lets its part off (_relief):
    then "(parts excepted)" says them all."""
    exc = _split_exc(item["t"])[1]
    return all(_relief(cx, x) for x in ([exc] if exc else []) + [k["t"] for k in item["items"]])


def _frame(item, mode, cx, depth, under_of=False, last=False):
    """(head, close, the kids' depth, whether they are an exception's, of):
    the words before and after an item's sub-list. An "of" heading over
    several, said last in its list, takes its list after a colon, as Canada
    writes it — "in the departments of: Choluteca: …; Colón …" — where
    brackets read "in the departments of (Choluteca: …)"; anywhere else the
    brackets say where its list ends."""
    text, kids = item["t"], item["items"]
    base, exc = _split_exc(text)
    if exc is not None:
        if mode == "compact":
            if depth % 2 == 0:
                exc = _shorten(exc, cx)
            else:
                base = _shorten(base, cx)
        head = base.rstrip(" ,:") + " (except "
        if exc and kids:
            head += exc + (" " if _OBJECT_END.search(exc) else ": ")
        elif exc:
            head += exc
        return head, ")", depth + 1, True, False
    head = _heading(text)
    if depth % 2 == 1 and mode == "compact":
        head = _shorten(head, cx)
    if not kids:
        return head, "", depth, False, False
    of = _kind(item, under_of) == "of"
    im = _INCL_END.search(head)
    if im and len(kids) > 1:
        return head[:im.start()].rstrip(" ,") + " (" + im.group(1) + " ", ")", depth, False, of
    if len(kids) == 1 and _OBJECT_END.search(head):
        return head + " ", "", depth, False, of        # "…, especially all of the following regions (…)"
    if of and last:
        return head + ": ", "", depth, False, of
    return head + " (", ")", depth, False, of


# The kinds whose lists are places a line's breadth pass may name more of
# (grow False): an "of" heading's, a group's, a whole's regions.
_PLACES = ("of", "group", "whole")


def _render(item, mode, cx, depth=0, room=None, under_of=False, hide=True, last=False, grow=True):
    """One list item as the line says it: its own words, its sub-items in
    brackets after it, its exceptions named — "Chocó (except the towns of
    Bahía Solano, Capurganá, Nuquí)", "southern Songkhla province (Hat Yai
    city; east of Highways 408 and 4113, including Sakom)". depth as in
    _cuttable: compact mode shortens only what is an exception at an odd
    depth (narrowing it), never an exclusion from one (that would widen the
    exception: "the coastal road" back under the block's call would read
    as excepted). With room, the fullest form that fits, never shorter than
    _least: a sub-list _cuttable allows cut to "and N more" (grow False: only
    an "of" heading's, a group's or a whole's places, more of them named,
    never detail — not even a full form that would fit).
    hide False: an "of" heading's places all named (see _fill)."""
    head, close, kd, boundary, of = _frame(item, mode, cx, depth, under_of, last)
    kids = item["items"]
    if not kids:
        return head + close
    kh, kl = (hide if of or _kind(item, under_of) == "whole" else True), (True if close else last)
    full = head + _fill(kids, mode, cx, kd, None, of, kh, kl)[0] + close
    if room is None or (grow and len(full) <= room):
        return full
    least = _least(item, mode, cx, depth, under_of, hide, last)
    if not grow and _kind(item, under_of) not in _PLACES:
        return least          # the breadth pass names places, never detail
    if _cuttable(kids, kd, boundary):
        cut = head + _fill(kids, mode, cx, kd, max(room - len(head) - len(close), 0), of, kh, kl, grow)[0] + close
        if len(least) < len(cut) <= room:
            return cut
    return least


def _least(item, mode, cx, depth=0, under_of=False, hide=True, last=False):
    """An item at its shortest honest form, which a line short of room says
    for it so as to name every place before any detail (_fill):
      a place with exceptions   "Colón (parts excepted)"; one in cx["bare"]
                                just "Colón" (its exceptions cut: stricter
                                than Canada, never looser, _line); one with
                                a stricter exception keeps it named (_relief)
      a part of a place         "parts of Amazonas" for "Amazonas, within
                                20 km of the border with Peru, …" (_qualified),
                                its exceptions too where they all let off
      an exception with an exclusion of its own, or over a list holding one
                                "parts of District of Karachi (formerly
                                Karachi South)": never wider than Canada's
      part                      "parts of Cortés", never "Cortés" bare
      emph                      the place alone: the parts it singles out
                                are in it ("District of San Miguelito")
      whole                     the place alone too; with hide False (and
                                cx["wholes"]) its regions all named at their
                                shortest: "northern and eastern Mauritania,
                                especially all of the following regions
                                (Tiris Zemmour, Hodh El Gharbi, Hodh Ech
                                Chargui)" — without them the area can't be
                                placed (Hodh El Gharbi is in no other item)
      of                        its places each at their shortest — with
                                hide, its first and "and N more"
      group                     its first place and "and N more"; "in X" over
                                several, "parts of X" where that is shorter
                                (Peru's "parts of the Department of Junin");
                                "areas of northern Guayaquil" its own words
      takes                     its first place and "and N more"
    Its full form wherever that is no longer. Only places, never exceptions:
    "parts of" an exception reads as more of it excepted than Canada lists."""
    full = _render(item, mode, cx, depth, None, under_of, hide, last)
    kind, kids = _kind(item, under_of), item["items"]
    odd = depth % 2 == 1
    q = None if odd else _qualified(_split_exc(item["t"])[0])
    if kind == "leaf":
        return "parts of " + q if q and len(q) + 9 < len(full) else full

    def first(kh=None):
        head, close, kd, boundary, of = _frame(item, mode, cx, depth, under_of, last)
        if not kids or not _cuttable(kids, kd, boundary):
            return full
        kh = (hide if of else True) if kh is None else kh
        return head + _fill(kids, mode, cx, kd, 0, of, kh, True if close else last)[0] + close
    if kind == "exc":
        base = _split_exc(item["t"])[0]
        place = _heading(base).rstrip(" ,")       # its own words: "including …" may reach past it
        if odd:
            s = _parts_of(_shorten(base, cx) if mode == "compact" else base) or full
        elif not _lets_off(item, cx):
            s = first()          # a stricter exception never goes (_relief)
        elif q:
            s = "parts of " + q
        elif id(item) in cx.get("bare", ()):
            s = place
        else:
            s = _unaside(place) + " (parts excepted)"
    elif kind == "part" or (odd and _has_exclusion(kids)):
        s = _parts_of(item["t"]) or first()
    elif kind == "emph" and not odd:
        s = _place(item["t"])
    elif kind == "whole" and not odd:
        s = _place(item["t"]) if hide or not cx.get("wholes", True) else first(False)
    elif kind == "group" and not odd and _AREAS.match(_heading(item["t"])):
        s = _heading(item["t"])
    elif kind == "group" and not odd and _count(item, under_of) > 1 and re.match(r"in\s", _heading(item["t"]), re.I):
        s = min(first(), _parts_of(item["t"]) or full, key=len)
    else:
        s = first()
    return s if len(s) < len(full) else full


def _fill(items, mode, cx, depth, room, under_of=False, hide=True, last=True, grow=True):
    """(text, shown): the items in Canada's order within room, then "and N
    more" for the places left out (_count).
    Breadth first: every item at its shortest honest form (_least) if they
    all fit, else as many as fit — and only then is the room left spent,
    in Canada's order, first on naming more places (an "of" heading's or a
    group's list of them: only those grow in that pass), then on detail.
    The line once spent its room on detail: Honduras named its Guatemala
    border's exceptions and hid six departments behind "and 6 more";
    Mexico said Chihuahua's and Colima's exceptions and hid nine of its 14
    states; Karachi said its first exception's own list and hid the other
    three (now three of its four are named; the fourth, Jinnah
    International Airport, is 115 characters on its own). A place said
    bare (cx["bare"]) gets no detail back, nor a heading over one: the
    line flags every excepted place or none. hide False: no item hidden,
    however long (the line past its cap, _line). last: the list ends its
    line or brackets, so an "of" heading said last can take its own list
    after a colon. The first item always stays. grow False: no detail."""
    n = len(items)
    counts = [_count(i, under_of) for i in items]
    if mode == "compact" and depth % 2 == 1 and n > 1 and any(_keeps_call(it["t"], cx) for it in items):
        cx = dict(cx, keep_calls=True)      # exceptions: every call kept where one is (_shorten)

    def rend(i, rm=None, lst=False, g=True):
        return _render(items[i], mode, cx, depth, rm, under_of, hide, lst, g)

    def say(parts):
        if len(parts) == n:
            return _join(_bands(parts))
        return sep.join(parts) + sep + _more(sum(counts[len(parts):]))
    full = [rend(i, None, last and i == n - 1) for i in range(n)]
    sep = _sep(full)
    if room is None or (grow and len(say(full)) <= room):
        return say(full), n
    least = [_least(it, mode, cx, depth, under_of, hide) for it in items]
    k = n
    if hide and len(say(least)) > room:
        k = next((j for j in range(n - 1, 0, -1) if len(say(least[:j])) <= room), 1)
    out, how = least[:k], [None] * k
    bare = cx.get("bare", ())
    for g in ((False, True) if grow else (False,)):
        for i in range(k):
            slack = room - len(say(out))
            if slack <= 0:
                break
            if not g and _kind(items[i], under_of) not in _PLACES:
                continue         # names more places: a heading's list of them
            if g and bare and any(id(x) in bare for x in _walk([items[i]])):
                continue         # a place said bare gets no exceptions back, nor its heading's
            cands = ([(full[i], "full")] if g else []) + [(rend(i, len(out[i]) + slack, False, g), (len(out[i]) + slack, g))]
            for c, h in cands:
                if len(c) > len(out[i]) and len(say(out[:i] + [c] + out[i + 1:])) <= room:
                    out[i], how[i] = c, h
                    break
    if k == n and last:
        h = how[-1]
        c = (_least(items[-1], mode, cx, depth, under_of, hide, True) if h is None
             else rend(n - 1, None, True) if h == "full" else rend(n - 1, h[0], True, h[1]))
        if len(c) <= len(out[-1]) or len(say(out[:-1] + [c])) <= room:
            out[-1] = c
    return say(out), k


def _lead_parts(lead):
    """The first sentence, read: {call, area, exc, exc_list, intro, colon}.
    "Avoid all travel to <area> due to …": the area ends at "due to", an
    exception or the list's colon. Jordan's exception sits inside it
    ("…Iraq and Syria, with the exception of the tourist site Umm Qais, due
    to …"); Karachi's says its list is the exceptions ("with the exception
    of the following areas where …:"); Kosovo's list is introduced past the
    reason ("…, particularly in the municipalities of:"). None: not a call."""
    m = _LEAD_CALL.match(lead or "")
    if not m:
        return None
    rest = re.sub(r"\.$", "", lead[m.end():].strip()).strip()
    colon = rest.endswith(":")
    body = rest[:-1].rstrip() if colon else rest
    out = {"call": m.group(1), "area": "", "exc": "", "exc_list": "", "intro": "", "colon": colon}
    pm = _EXC_PAREN.search(body)          # Ecuador: "the following areas (except within 20 km …)"
    if pm:
        out["exc"] = _clean(pm.group(1))
        body = _clean(body[:pm.start()] + body[pm.end():])
    end = len(body)
    for rx in (r",?\s+due to\b", r",?\s+with exclusions\b"):
        dm = re.search(rx, body, re.I)
        if dm:
            end = min(end, dm.start())
    em = re.search(r",?\s+(?:with the exception of|except(?: for)?|excluding)\s+(.*?)(?=,\s*due to\b|\s+due to\b|$)", body, re.I)
    if em:
        x = _clean(em.group(1)).rstrip(" ,")
        if re.match(r"the following\b", x, re.I):
            out["exc_list"] = x
        elif not out["exc"]:
            out["exc"] = x
        end = min(end, em.start())
    out["area"] = body[:end].strip(" ,")
    if colon and not out["exc_list"]:
        im = re.search(r",\s*((?:particularly|especially|notably|in particular|including)\b[^,]*)$", body, re.I)
        if im and im.start() >= end:
            out["intro"] = im.group(1)
    return out


def _notice(head_call, L, nodes):
    """Whether a block is a notice, not an advisory: no call in its heading
    or its first sentence, nor anywhere in its text, so no area to call one
    for. Canada's "Canadian border measures related to Ebola for travellers
    from Uganda" (the Congo's and South Sudan's too, 2026-10) are its
    re-entry rules for Canadians — quarantine for 21 days — and read as
    "📍 Canadian border measures…: Until November 27, 2026, …", a place line
    with no place. They are left out (regional_blocks); the outbreak itself
    is in the site's health data (health.json: the Congo's Ebola notice, its
    and Uganda's country-wide calls naming Ebola). A block whose text does
    name a call somewhere is kept whatever its heading says, and so is one
    whose heading ends in " - <something>" at all: a call spelled in a way
    _CALL_RX doesn't know is still an advisory, never a notice to drop."""
    if head_call or L:
        return False
    words = [v for k, v in nodes if k == "p"] + [it["t"] for k, v in nodes if k == "ul" for it in _walk(v)]
    return not any(re.search(_CALL_RX, w, re.I) for w in words)


def _analyze(t, fragment, floor=None):
    """A block's parts: its call, its area, its lists grouped under the
    sentences that introduce them, and the exceptions and inclusions Canada
    states, in its order (src: "sentence" for one Canada wrote as "This
    advisory excludes/includes …", which the line can then quote, word: its
    opening as Canada wrote it, "This advisory also excludes"). conds:
    Canada's sentences on the exceptions (_COND), whole — Colombia's "If you
    intend to travel to any of the above excluded areas, do so by air" was
    left out with the background, and the guide's AI could route a bus
    through Valle del Cauca to Cali. floor: the country's own level (_rank),
    which _shorten needs."""
    nodes = _body(fragment)
    paras = [v for k, v in nodes if k == "p"]
    lead = (_sentences(paras[0]) or [""])[0] if paras else ""

    def third(items):
        return [{"t": _third(it["t"]), "items": third(it["items"])} for it in items]
    # The line's, the brief's and full's words say Canada's "we" as Canada
    # (_third); the tip (text, from nodes) and lead quote it as written.
    said = [(k, _third(v) if k == "p" else third(v)) for k, v in nodes]
    parts = [p.strip() for p in t.split(" - ")]
    if not (len(parts) > 1 and _canon(parts[-1])):
        loose = [p.strip() for p in re.split(r"\s+[\u2010-\u2015-]\s+", t)]
        parts = loose if len(loose) > 1 and _canon(loose[-1]) else parts     # "Northern region – Avoid all travel"
    head_call = parts[-1] if len(parts) > 1 else ""
    head = _unshout(" - ".join(parts[:-1]) if len(parts) > 1 else t)
    L = _lead_parts(_third(_norm(lead)))
    if _canon(head_call):
        call = _canon(head_call)
    elif L:
        call = _canon(L["call"]) or L["call"].capitalize()
    else:
        call = _unshout(head_call) or head    # no call: see _notice
    groups, extras, conds, pending, last, first = [], [], [], None, None, True
    for kind, v in said:
        if kind == "p":
            ss = _sentences(v)
            if first:
                ss, first = ss[1:], False
            for s in ss:
                last = None
                for k, rx in (("except", _EXCLUDES), ("include", _INCLUDES)):
                    m = rx.match(s)
                    if m:
                        x, word = _clean(m.group(2)), _clean(m.group(1))
                        word = word[:1].upper() + word[1:]
                        if s.rstrip().endswith(":"):
                            pending = (k, x, word)
                        else:
                            extras.append({"k": k, "t": x, "items": [], "src": "sentence", "word": word})
                        break
                else:
                    pending = ("group", s.rstrip(" :"), "") if s.rstrip().endswith(":") else None
                    if not pending and _COND.search(s):
                        conds.append(_unstop(_clean(s)))
            continue
        if pending:
            k, x, word = pending
            if k == "group":
                # "This area consists of:" (Peru's VRAEM) only says the list
                # is the area; Guatemala's "Within Guatemala City:" says where.
                x = "" if re.search(r"\bconsists of$", x, re.I) else re.sub(r"^the following\s+", "", x, flags=re.I)
                groups.append({"intro": x, "items": list(v)})
                last = groups[-1]
            else:
                extras.append({"k": k, "t": x, "items": list(v), "src": "sentence", "word": word})
                last = extras[-1]
            pending = None
        elif last is not None:
            last["items"].extend(v)        # one list the HTML split in two (Tunisia, Mauritania)
        elif L and L["exc_list"] and not groups and not extras:
            extras.append({"k": "except", "t": L["exc_list"], "items": list(v), "src": "lead"})
            last = extras[-1]
        else:
            groups.append({"intro": L["intro"] if L and not groups else "", "items": list(v)})
            last = groups[-1]
    if L and L["exc"]:
        extras.insert(0, {"k": "except", "t": L["exc"], "items": [], "src": "lead"})

    named = bool(head) and head != call and not _GENERIC.match(head)
    items = [it for g in groups for it in g["items"]]
    optional = False      # a heading standing in for "the following areas": the first thing to go
    if L:
        area = L["area"]
        pm = re.match(r"^the following\s+(.+)$", area, re.I)
        if items and pm and not re.search(r"\b(?:within|km|except)\b", area, re.I):
            # "the following provinces of Mindanao island" says what the list
            # is ("provinces of Mindanao island: …"); "the following areas"
            # says nothing and gives way to a short named heading.
            area = pm.group(1) if re.search(r"\s(?:of|in)\s", pm.group(1)) else (head if named and len(head) <= 50 else "")
            if area == head and any(head.lower() in it["t"].lower() for it in items):
                area = ""      # its first place in its own words: "Northern and eastern Mauritania: northern and eastern Mauritania, …"
            optional = area == head
        if items and area and all(_split_exc(it["t"])[0].rstrip(" :").lower() in area.lower() for it in items):
            area = ""      # a heading that names every place adds nothing to them
        if not area and not items and named:
            area = head
    else:
        # No call in the heading or the first sentence, but one further on
        # (none on 2026-10-15): the first sentence says what it is, the tip
        # the rest.
        area = re.sub(r"\.$", "", lead) or (head if named else "")
    return {"t": t, "call": call, "rank": _rank(call), "head": head, "named": named, "lead": lead, "L": L,
            "notice": _notice(head_call, L, nodes),
            "area": area, "optional": optional and bool(area), "groups": groups, "extras": extras, "conds": conds,
            "nodes": nodes, "cx": {"rank": _rank(call), "floor": floor}}


def _compose(B, mode, room=None, hide=True, bare=None, grow=True, wholes=True):
    """The block in one line: the area, its places (each list under the words
    that introduce it), then what Canada excepts and includes. With room,
    the places first — cutting an exception only makes the line stricter
    than Canada, cutting a place hides one — so the places take the room
    less the exceptions at their shortest, and the exceptions what is left.
    hide False: no place hidden however long the line (_line's ceiling);
    bare: the places (ids) said without their exceptions (_least); grow
    False: the room goes only to naming more places, the exceptions stay at
    their shortest (_line past its cap); wholes False: a whole's regions
    are not among the places hide False names (_least).
    Canada's sentences on the exceptions (B["conds"]) follow, whole, last,
    wherever the line names an exception (_conds)."""
    s = _composed(B, mode, room, hide, bare, grow, wholes)
    tail = _conds(B, s)
    if not tail or room is None or len(s) + len(tail) <= room:
        return s + tail
    s = _composed(B, mode, max(room - len(tail), 0), hide, bare, grow, wholes)
    return s + _conds(B, s)


def _conds(B, s):
    """What follows a form that names any of the block's exceptions: Canada's
    sentences on them (Colombia's "If you intend to travel to any of the
    above excluded areas, do so by air"), each whole and its own. A form
    that only flags them "(parts excepted)" or "*" gets none: the sentence
    reads on places to avoid. Put last: each refers back ("the above")."""
    conds = B.get("conds") or []
    return "".join(". " + c for c in conds) if conds and _SAYS_EXC.search(s or "") else ""


def _composed(B, mode, room=None, hide=True, bare=None, grow=True, wholes=True):
    """_compose without Canada's sentences on the exceptions."""
    cx = dict(B["cx"], bare=bare or frozenset(), wholes=wholes)
    prefix, groups, extras = B["area"], B["groups"], B["extras"]
    multi = len(groups) > 1
    # Several exceptions after "except" read as more places: Egypt's "…,
    # including the oasis of Dakhla — except Marsa Matruh via the Marsa
    # Matruh Road only; The White and Black deserts via the Oasis Road only;
    # and 1 more" made the deserts one more place to avoid. They need words
    # that say the rest of the line is exceptions: Canada's own sentence
    # where it wrote one (". This advisory excludes …", own), else Canada's
    # "the following areas:" before them (Karachi's lead: _shorten intro).
    excs = [e for e in extras if e["k"] == "except"]
    several = len(excs) > 1 or any(len(e["items"]) > 1 for e in excs)
    own = several and any(e.get("src") == "sentence" for e in excs)
    # What a block includes, after a list, is Canada's own sentence: Benin's
    # "…; within 50 km of the border with Nigeria, north of the town of Nikki
    # in Borgou Department — including the W National Park and the Pendjari
    # National Park" put the parks on the Nigeria band, where neither is.
    own = own or bool(groups) and any(e["k"] == "include" and e.get("src") == "sentence" for e in extras)
    # So is all of it after an area that ends in an aside (_ASIDE):
    # Azerbaijan's "…the border with Armenia, which is closed, except the
    # border between Armenia and the Azerbaijani Autonomous Republic of
    # Nakhchivan, where you should exercise a high degree of caution" read
    # as a closed border but for an open crossing to Nakhchivan.
    tail = groups[-1]["items"][-1]["t"] if groups and groups[-1]["items"] else prefix
    own = own or bool(extras) and bool(_ASIDE.search(tail or ""))

    def lab(g):
        intro = g["intro"]
        if multi and intro:
            intro = intro[:1].upper() + intro[1:]
        return (intro + (" " if _OBJECT_END.search(intro) else ": ")) if intro else ""

    def one(g, limit=None, h=None):
        lim = None if limit is None else max(limit - len(lab(g)), 0)
        return lab(g) + _fill(g["items"], mode, cx, 0, lim, hide=hide if h is None else h, grow=grow)[0]

    def grp(limit=None):
        # Several lists (Guatemala's city zones, municipalities and border
        # crossings) each keep their own words and at least their first
        # place, so each "and N more" counts its own list: the crossings
        # once read as eight more municipalities — and every place of each
        # where they all fit, before any list's detail. Canada's order
        # decides who gets the room beyond that.
        whole = [one(g) for g in groups]
        if limit is None or (grow and len(". ".join(whole)) <= limit):
            return ". ".join(whole)
        mins = [len(one(g, 0, False)) for g in groups]
        if hide and sum(mins) + 2 * (len(groups) - 1) > limit:
            mins = [len(one(g, 0)) for g in groups]
        out = []
        for i, g in enumerate(groups):
            used = len(". ".join(out)) + (2 if out else 0)
            avail = limit - used - sum(mins[i + 1:]) - 2 * (len(groups) - i - 1)
            out.append(whole[i] if grow and len(whole[i]) <= avail else one(g, avail))
        return ". ".join(out)

    def ex(limit=None, sentence=False):
        # Each kind under its word — " — except A". After a list cut to "and
        # N more" they are a sentence of their own, in Canada's words where
        # Canada wrote one (". This advisory includes …"): Benin's "…; and 2
        # more — including the W National Park and the Pendjari National
        # Park" read as if the parks were the two left out. Each of Canada's
        # sentences stays one, its own words opening it: Tanzania's
        # "…, where you should avoid all travel; Mtwara City" put the city
        # Canada lets off to a high degree of caution in the avoid-all band's
        # list. Where several are joined by "; " and one keeps its call,
        # they all keep theirs (_shorten).
        own_s = lambda e: sentence and e.get("src") == "sentence"
        joined = [e for e in excs if not own_s(e)]
        kx = dict(cx, keep_calls=True) if len(joined) > 1 and any(_keeps_call(e["t"], cx) for e in joined) else cx
        out, prev = "", None
        for e in extras:
            exc = e["k"] == "except"
            x = _shorten(e["t"], kx if e in joined else cx, several and not sentence) if mode == "compact" and exc else e["t"]
            if own_s(e):
                lead_in = (". " if out else "") + e.get("word", "This advisory " + ("excludes" if exc else "includes")) + " "
            else:
                word = ("except " if exc else "including ") if not sentence else ("Except " if exc else "Including ")
                lead_in = "; " if prev == e["k"] else (((". " if sentence else ", ") if out else "") + word)
            body = x
            if e["items"]:
                pre = (x + (" " if _OBJECT_END.search(x) else ": ")) if x else ""
                d = 1 if exc else 0
                left = None if limit is None else max(limit - len(out) - len(lead_in) - len(pre), 0)
                body = pre + _fill(e["items"], mode, cx, d, left, hide=hide or exc, last=e is extras[-1])[0]
            out += lead_in + body
            prev = None if own_s(e) else e["k"]
        return out

    def put(g, e, sentence=False):
        s = prefix
        if g:
            s = (s + (", " if re.match(r"(?:particularly|especially|notably|including)\b", g) else ": ") if s else "") + g
        if e:
            s = (s + (". " if sentence else " — " if g else ", ") if s else "") + e
        return s

    s = put(grp(), ex(sentence=own), own)
    if room is None or (grow and len(s) <= room):
        return s
    if not groups:
        return put("", ex(max(room - len(prefix) - 2, 0) if grow else 0, own), own)
    pre = len(prefix) + (2 if prefix else 0)
    cut = lambda g: bool(re.search(r"\band \d+ more$", g))
    e_min = ex(0, own) if extras else ""
    g = grp(room - pre - (len(e_min) + (2 if own else 3) if e_min else 0))
    if extras and not own and cut(g):
        g = grp(room - pre - len(ex(0, True)) - 2)
    sentence = own or (bool(extras) and cut(g))
    e = ex(max(room - pre - len(g) - (2 if sentence else 3), 0) if grow else 0, sentence) if extras else ""
    return put(g, e, sentence)


def _marked(B):
    """The places a line can say "(parts excepted)" of, in Canada's order:
    each list's items and the places under an "of" heading (Honduras's
    Colón), a group or a whole, which a line past its cap may name too
    (Ethiopia's West Shewa, under "the following zones in the Oromia
    region:") — only those whose exceptions all let them off (_lets_off):
    one with a stricter exception keeps it named, bare or not."""
    def walk(items, under_of=False):
        for it in items:
            k = _kind(it, under_of)
            if k == "exc" and _lets_off(it, B["cx"]):
                yield it
            elif k in _PLACES:
                yield from walk(it["items"], k == "of")
    return [it for g in B["groups"] for it in walk(g["items"])]


# "the province of Balochistan; the province of Khyber Pakhtunkhwa", "in the
# province of El Oro: …; in the province of Guayas: …": a division's name
# said once a list has said what its places are.
_REPEAT = re.compile(r"^(in\s+)?(the\s+(?:province|department|state|region|governorate|district|county|prefecture)\s+of\s+)", re.I)


def _derepeat(B):
    """B with a list's repeated "the province of" said only the first time
    (_line, short of room): "the province of Esmeraldas; in El Oro (Machala,
    Huaquillas); in Guayas (…)". Only where the words are the same, before
    a name (capitalized), and only for places: an exception is never said
    any other way than Canada wrote it. B itself where nothing repeats."""
    changed = []

    def walk(items, depth):
        seen, out = set(), []
        for it in items:
            t = it["t"]
            m = _REPEAT.match(t) if depth % 2 == 0 else None
            if m and t[m.end():][:1].isupper():
                key = " ".join(m.group(2).lower().split())
                if key in seen:
                    t = (m.group(1) or "") + t[m.end():]
                    changed.append(key)
                seen.add(key)
            kd = depth + (1 if _split_exc(it["t"])[1] is not None else 0)
            out.append({"t": t, "items": walk(it["items"], kd)})
        return out
    groups = [dict(g, items=walk(g["items"], 0)) for g in B["groups"]]
    return dict(B, groups=groups) if changed else B


def _lets_off_extra(B, e):
    """An exception Canada states in a sentence of its own that lets its part
    off (_relief): the one kind of words after the lists a line can cut."""
    return e["k"] == "except" and _relief(B, e["t"]) and all(_relief(B, k["t"]) for k in e["items"])


def _line(B, cap, ceiling=None):
    """The block's line within cap: whole if it fits, else with its milder
    exceptions said shorter, then without a heading standing in for "the
    following areas", then with a list's repeated "the province of" said
    once (_derepeat), then every place at its shortest (_least) and the
    room left first to naming more places, then to detail, then cut to
    "and N more".
    Past cap, up to `ceiling`, only to name every place of its lists, at
    their shortest, where cap can't: Pakistan's line hid the 10 km China,
    India and Iran strips, the Line of Control and the Karakoram Highway
    from Mansehra to Chilas behind "and 3 more", Honduras's six of its
    seven departments, Colombia's 14 of its 16 places — and the whole
    regions an "especially … all of" list names (Mauritania's Tiris
    Zemmour, Hodh El Gharbi and Hodh Ech Chargui, which its line said only
    as "northern and eastern Mauritania"), where they fit. If that is still
    too long, every place's "(parts excepted)" goes — all of them or none
    (Colombia's border areas, three flagged and three bare, read as if
    Canada excepted nothing from Cúcuta or Ipiales; cut, an exception makes
    the line stricter, never looser; the tip has it) — and then the
    exceptions Canada states in a sentence of their own that let parts
    off. Never what a block includes, a place to avoid (Benin's four bands
    and Canada's sentence for its parks are 359 characters, the ceiling),
    nor a stricter exception. Only past that are places hidden, within cap.
    Or past cap where nothing can be cut: an area and its exception in one
    long sentence each (northern Sinai).
    A line past cap then names the places inside its groups while they fit
    the ceiling, before any other detail (grow False): Colombia's "towns in
    Chocó (Bahía Solano, and 2 more)" hid Capurganá and Nuquí, the towns
    Canada lets off Chocó's avoid-all line, with room for both."""
    for mode in ("full", "compact"):
        s = _compose(B, mode)
        if len(s) <= cap:
            return s
    if B["optional"]:
        B = dict(B, area="", optional=False)
        s = _compose(B, "compact")
        if len(s) <= cap:
            return s
    if not B["L"]:
        # No call in its first sentence (_analyze): that sentence says what
        # it is, and its lists live in the tip.
        B = dict(B, groups=[])
    B = _derepeat(B)

    def fit(B, hide=True, bare=frozenset(), wholes=True):
        room = cap
        s = _compose(B, "compact", room, hide, bare, wholes=wholes)
        while len(s) > cap and room > 80:
            room -= len(s) - cap
            s = _compose(B, "compact", room, hide, bare, wholes=wholes)
        return s
    s = fit(B)
    if ceiling:
        if len(s) > cap and len(_compose(B, "compact")) <= ceiling:
            # Over cap however it is cut: then nothing is cut. Northern Sinai's
            # line hid Ismailia and Suez to save 15 of the 26 characters over.
            return _compose(B, "compact")
        if B["groups"] and len(fit(B, False)) > cap:
            # Every place named: with each one's "(parts excepted)", else
            # with none — a line that flags some places and says others bare
            # reads as if Canada excepted nothing from those (Colombia's
            # Cúcuta and Ipiales) — then without the exceptions Canada says
            # in a sentence of their own that let parts off. Never without
            # what a block includes (Benin's parks: places to avoid) or a
            # stricter exception. A whole's regions are places, so they come
            # before any of that; without them only where they can't fit.
            relief = frozenset(id(it) for it in _marked(B))
            keep = [e for e in B["extras"] if not _lets_off_extra(B, e)]
            ways = [(B, frozenset())] + ([(B, relief)] if relief else []) + (
                [(dict(B, extras=keep), relief)] if len(keep) < len(B["extras"]) else [])
            whole = any(_kind(it) == "whole" for it in _walk([it for g in B["groups"] for it in g["items"]]))
            for wholes in ((True, False) if whole else (True,)):
                for Bw, bare in ways:
                    t = fit(Bw, False, bare, wholes)
                    if len(t) <= cap and not wholes:
                        return s           # its other places fit within cap: the line at cap names them
                    if len(t) <= ceiling:
                        w = _compose(Bw, "compact", ceiling, False, bare, False, wholes)
                        return w if len(t) < len(w) <= ceiling else t
    if len(s) > (ceiling or cap):
        # One place or exception longer than the line (none on 2026-10-15):
        # the area, flagged when Canada excepts parts of it, and the tip.
        s = B["area"] or B["head"]
        s = _unaside(s) + " (parts excepted)" if _excepted(B) else s
        s = s if len(s) <= cap else s[:cap - 3].rsplit(" ", 1)[0] + "..."
    return s


def _relief(B, exc):
    """Whether an exception lets its part off: not when it carries a call
    stricter than the block's own — Tanzania's 10 km band "where you should
    avoid all travel", Tunisia's and Ecuador's border strips. Each of those
    has its own stricter block; starred or "(parts excepted)", it read as a
    part let off."""
    m = _WHERE.search(exc or "")
    return not m or _rank(m.group(1)) < B["rank"]


def _excepted(B):
    flat = [it for g in B["groups"] for it in g["items"]]
    return any(e["k"] == "except" and _relief(B, e["t"]) for e in B["extras"]) or any(
        _split_exc(it["t"])[1] is not None and _relief(B, _split_exc(it["t"])[1]) for it in _walk(flat))


def _cut_words(s, cap):
    return s if len(s) <= cap else s[:cap - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _included(e, cx):
    """What a block includes (a "This advisory includes …" sentence) at its
    shortest honest form, for a brief: its own words with the list it
    introduces said in place of a bare "the following <kind>" ("parts of
    the following governorates:" is "parts of Port Said, …"), and after
    them where they say more. Egypt's "all of the Governorate of North
    Sinai and parts of the following governorates east of the Suez Canal:
    Port Said, Ismailia, Suez" stays whole: "parts of Port Said, Ismailia,
    Suez" read as the three canal cities, which lie west of the canal.
    Every place it names stays: these are places to avoid."""
    t, its = e["t"], [_least(it, "compact", cx) for it in e["items"]]
    if not its:
        return t
    m = re.search(r"\bthe following\s+\w+$", t, re.I)
    if m:
        return t[:m.start()] + _join(its)
    return t + (" " if _OBJECT_END.search(t) else ": ") + _join(its)


def _names(B, most, cap):
    """The trip prompt's form of a long list, as it always had it under a
    generic heading and now under a named one too: up to `most` places (and
    about `cap` characters) in their own words without their exceptions,
    starred where Canada lets parts off (the prompt says what * means); a
    list of places under one (Guatemala's municipalities by department,
    Honduras's departments) named one level down, a whole's regions all
    (Mauritania's Tiris Zemmour, Hodh El Gharbi, Hodh Ech Chargui); several
    lists each under their own words with their own "and N more" —
    Guatemala's brief once ended its city zones with "and 10 more", the
    municipalities and border crossings. Every place where they all fit in
    `cap` at their shortest ("parts of Amazonas" for "Amazonas, within
    20 km of the border with Peru, …"), however many: Mexico's brief hid
    Sinaloa, Sonora, Tamaulipas and Zacatecas behind "and 4 more" with room
    for them; then the places of a list two levels down named at its first
    ("areas of northern Guayaquil (Bastión Popular, and 10 more)") all
    named, in Canada's order, while they fit: Ecuador's brief hid 12 of its
    14 Guayaquil neighbourhoods with room for every one; then each place in
    its own words again, in Canada's order, while they fit. A heading
    standing in for "the following areas" leads them where it costs no
    place ("Western Sahara border regions: within 30 km west of the
    militarized zone of the Berm; …"), and carries the star for what Canada
    excepts from the whole block: "…, including the oasis of Dakhla*" read
    as Dakhla let off, where Canada lets off Marsa Matruh and the White and
    Black deserts. What the block includes follows in Canada's sentence
    where it fits (Benin's parks: _included); then a stricter exception of
    the block's in Canada's words, as the line says it (Ecuador's "— except
    within 20 km of the border with Colombia where Canada advises against
    all travel"), where it fits; then, once every place is named, each
    place's own exceptions as the line says them in place of its star, in
    Canada's order, where they fit: Georgia's "…with the occupied regions of
    Abkhazia and South Ossetia*" read as South Ossetia let off, and said
    nothing of Highway E60 (the Tbilisi–Gori–Kutaisi road runs in the band);
    it reads "… (except Highway E60)". The star stays where they don't fit.
    Canada's sentences on the exceptions follow wherever one is named
    (_conds)."""
    cx = B["cx"]
    # What name() says a list two levels down whole ("open") and which
    # places it says with their exceptions ("said"); "seen": where it could
    # do either, in Canada's order.
    cur = {"open": frozenset(), "said": frozenset(), "seen": []}

    def star(it):
        return any(_split_exc(k["t"])[1] is not None and _relief(B, _split_exc(k["t"])[1]) for k in _walk([it]))

    def name(it, deep=True, under_of=False, last=False, short=False):
        base, exc = _split_exc(it["t"])
        q = _qualified(base) if short else None
        if q and (exc is None or _lets_off(it, cx)):
            return "parts of " + q
        if exc is not None and id(it) in cur["said"]:
            return _render(it, "compact", cx, 0, None, under_of, True, last)      # the line's own words
        base = _heading(base).rstrip(" ,")
        kind = _kind(it, under_of)
        if exc is None and it["items"]:
            of = kind == "of"
            if deep or id(it) in cur["open"]:
                kids = [name(k, kind == "whole", of, short=short) for k in it["items"]]
                if len(kids) == 1 and _OBJECT_END.search(base):
                    return base + " " + kids[0]
                return base + (": " + _join(kids) if of and last else " (" + _join(kids) + ")")
            # A list two levels down is never dropped to leave its heading
            # bare: Honduras's brief said "Cortés", all of it, where Canada
            # lists three neighbourhoods and two cities of it.
            if kind == "part":
                return "parts of " + _place(it["t"]) + ("*" if star(it) else "")
            if kind == "emph":
                return _place(it["t"]) + ("*" if star(it) else "")
            cur["seen"].append(("open", id(it)))
            more = sum(_count(k, of) for k in it["items"][1:])
            return base + " (" + name(it["items"][0], False, of) + (", " + _more(more) if more else "") + ")"
        if not star(it):
            return base
        if exc is not None:
            cur["seen"].append(("said", id(it)))
        return base + "*"
    gs = [g for g in B["groups"] if g["items"]]
    multi = len(gs) > 1
    names = [[name(it) for it in g["items"]] for g in gs]
    counts = [[_count(it) for it in g["items"]] for g in gs]
    sizes = [len(g["items"]) for g in gs]
    labs = []
    for g in gs:
        intro = g["intro"][:1].upper() + g["intro"][1:] if multi else g["intro"]
        labs.append((intro + (" " if _OBJECT_END.search(intro) else ": ")) if intro else "")
    starred = any(e["k"] == "except" and _relief(B, e["t"]) for e in B["extras"])

    def render(pre, cfg):
        # cfg: each list's (how many named, [each one in its own words?]);
        # the joint is the list's own (_sep), "; " once a form needs it.
        cur["seen"] = []
        out = []
        for i, g in enumerate(gs):
            k, own = cfg[i]
            xs = [name(g["items"][j], last=j == sizes[i] - 1, short=not own[j]) for j in range(k)]
            sep = _sep(names[i] + xs)
            out.append(labs[i] + sep.join(xs) + ("" if k == sizes[i] else sep + _more(sum(counts[i][k:]))))
        return pre + ". ".join(out)

    def opening(pre, cfg):
        # Every list two levels down named at its first place named whole,
        # in Canada's order, while it fits: places, before any detail.
        opened, tried = set(), set()
        while True:
            cur["open"] = frozenset(opened)
            render(pre, cfg)
            nxt = next((x for k, x in cur["seen"] if k == "open" and x not in tried), None)
            if nxt is None:
                return frozenset(opened)
            tried.add(nxt)
            opened.add(nxt)
            cur["open"] = frozenset(opened)
            if len(render(pre, cfg)) > cap:
                opened.discard(nxt)

    def listed(pre):
        # Every list its first place, then more in Canada's order while they fit.
        cur["open"] = frozenset()
        take = [1] * len(gs)
        whole = lambda: [(take[i], [True] * take[i]) for i in range(len(gs))]
        for i in range(len(gs)):
            while take[i] < sizes[i] and sum(take) < most:
                take[i] += 1
                if len(render(pre, whole())) > cap:
                    take[i] -= 1
                    break
        if take == sizes:
            cfg = whole()
            return cfg, opening(pre, cfg)
        cfg = [(n, [False] * n) for n in sizes]
        if len(render(pre, cfg)) > cap:
            return whole(), frozenset()
        opened = opening(pre, cfg)
        cur["open"] = opened
        for i in range(len(gs)):
            for j in range(sizes[i]):
                cfg[i][1][j] = True
                if len(render(pre, cfg)) > cap:
                    cfg[i][1][j] = False
        return cfg, opened
    head = B["area"] + ("*" if starred else "")
    pre = head + ": " if B["area"] and not B["optional"] else ""
    cfg, opened = listed(pre)
    if B["area"] and B["optional"]:
        cur["open"] = opened
        s = render(pre, cfg)
        cfg_h, opened_h = listed(head + ": ")
        cur["open"] = opened_h
        t = render(head + ": ", cfg_h)
        if t == head + ": " + s and len(t) <= cap:
            pre, cfg, opened = head + ": ", cfg_h, opened_h
    cur["open"] = opened
    every = [k for k, _ in cfg] == sizes
    strict = [e for e in B["extras"] if e["k"] == "except" and not _relief(B, e["t"])]
    incs, strict_on = set(), False

    def final(said):
        cur["said"] = frozenset(said)
        s = render(pre, cfg)
        if starred and not s.endswith("*") and not s.startswith(head + ": "):
            s += "*"
        # Straight after the list, an exception as the line says one ("—
        # except …", Tunisia's and Ecuador's); past a sentence, a sentence
        # of its own, in Canada's words where Canada wrote one.
        lone = False
        for e in B["extras"]:
            if e["k"] == "include" and id(e) in incs:
                s += ". " + e.get("word", "This advisory includes") + " " + _included(e, cx)
            elif strict_on and e in strict:
                x = _shorten(e["t"], cx, bool(e["items"]))
                if e["items"]:
                    x = (x + (" " if _OBJECT_END.search(x) else ": ") if x else "") + _fill(e["items"], "compact", cx, 1, None)[0]
                s += (" — except " if not lone else ". " + e["word"] + " " if e.get("src") == "sentence" else ". Except ") + x
            else:
                continue
            lone = True
        return s + _conds(B, s)
    for e in B["extras"]:
        if e["k"] == "include":
            incs.add(id(e))
            if len(final(())) > cap:
                incs.discard(id(e))
    strict_on = bool(strict)
    if strict_on and len(final(())) > cap:
        strict_on = False
    said = []
    if every:
        cur["said"] = frozenset()
        render(pre, cfg)
        for x in [x for k, x in cur["seen"] if k == "said"]:
            said.append(x)
            if len(final(said)) > cap:
                said.pop()
    return final(said)


def _regional(t, fragment, floor=None):
    """One regional block as /api/watchouts serves it. line: the 📍 line after
    its call, Canada's words selected and shortened (the guide, the Safety
    table, the server's stand-in); full: the same uncut, for the guide's AI
    prompt, which has no ⓘ to hold what "and N more" leaves out; brief: the
    trip prompt's line, shorter still; text: the whole block for the tip.
    None for a notice (_notice), which is no advisory."""
    B = _analyze(t, fragment, floor)
    if B["notice"]:
        return None
    flat = [it for g in B["groups"] for it in g["items"]]
    line = _line(B, LINE_CAP, LINE_MAX)
    compact = _compose(B, "compact")
    # The guide's AI prompt has no ⓘ: every place, every exception with its
    # call and asides as Canada wrote them ("Wagah (which is currently
    # closed)") and Canada's sentence on them (_conds), nothing shortened.
    full = _compose(B, "full") if B["L"] else line
    excepted = _excepted(B)
    if len(compact) <= BRIEF_CAP:
        brief = compact
    elif not B["L"]:
        brief = _cut_words(B["head"], BRIEF_CAP)    # no call in its first sentence: its heading
    elif flat:
        # A list names its places, under a named heading too: Peru's VRAEM
        # brief said only its heading, never that the area takes in the
        # Provinces of Abancay and Andahuaylas (Abancay is on the Cusco–
        # Abancay–Nazca road and holds the Choquequirao trailhead), and
        # Benin's "Border areas with Burkina Faso, Niger, Nigeria and Togo"
        # read as the whole Nigeria and Togo borders, where Canada's bands
        # are north of Nikki and west of the Boukoumbé–Tanguiéta axis.
        brief = _names(_derepeat(B), BRIEF_ITEMS, BRIEF_NAMES)
    elif B["named"]:
        # The heading, or Canada's own words for the area where they say it
        # and more: Peru's "Upper Huallaga River Valley" is "the Upper
        # Huallaga River Valley and surroundings" — Tingo María and Aguaytía
        # are in the provinces around it. Then what it includes, at its
        # shortest (_included), past BRIEF_CAP up to BRIEF_NAMES if need be:
        # these are places to avoid — "Northern Sinai (parts excepted)" left
        # out the parts of Port Said, Ismailia and Suez east of the canal,
        # Togo's "within 30 km of the border with Burkina Faso" Dapaong and
        # the N28 and N16. The tag is the block's, so it goes on the heading:
        # after the last place, "…, Ismailia, Suez (parts excepted)" read as
        # Suez let off. Nothing straight after an aside (_unaside).
        tag = " (parts excepted)" if excepted else ""
        area = B["L"]["area"]
        h = area if (B["head"].lower() in area.lower() and len(B["head"]) < len(area) <= BRIEF_CAP - len(tag)
                     and not re.search(r"\bthe following\b", area, re.I)) else B["head"]      # not a list's "the following areas"
        inc = "".join(", including " + _included(e, B["cx"]) for e in B["extras"] if e["k"] == "include")
        tagged = lambda x: (_unaside(x) if inc or tag else x) + tag + inc
        cap = BRIEF_NAMES if inc else BRIEF_CAP
        brief = next((tagged(x) for x in (h, B["head"]) if len(tagged(x)) <= cap), None)
        if brief is None and inc:
            brief = _cut_words(tagged(B["head"]), cap)      # cut, and says so ("…")
        elif brief is None:
            brief = _cut_words(_unaside(h) if tag else h, BRIEF_CAP - len(tag)) + tag
    else:
        brief = _line(B, BRIEF_CAP)

    def said(e, exc):
        its = [_render(i, "full", B["cx"], 1 if exc else 0) for i in e["items"]]
        if not its:
            return e["t"]
        return (e["t"] + (" " if _OBJECT_END.search(e["t"]) else ": ") if e["t"] else "") + _join(its)

    excepts = [said(e, True) for e in B["extras"] if e["k"] == "except"]
    for it in _walk(flat):
        x = _split_exc(it["t"])[1]
        if x is not None:
            excepts.append(said({"t": x, "items": it["items"]}, True))
    return {
        "t": t[:120], "call": B["call"], "lead": B["lead"], "line": line, "full": full, "brief": brief,
        "text": _plain_text(B["nodes"]), "items": _export(flat), "excepts": excepts,
        "includes": [said(e, False) for e in B["extras"] if e["k"] == "include"],
        "regions": _top_level_items(fragment),
    }


def _walk(items):
    for it in items:
        yield it
        yield from _walk(it["items"])


def _country_wide(area, name):
    """The block for the whole country repeats its name — "The Bahamas" on
    "Bahamas", "Côte d’Ivoire" on "Côte d'Ivoire (Ivory Coast)", "DEMOCRATIC
    REPUBLIC OF THE CONGO" on "Democratic Republic of Congo (Kinshasa)" —
    while "Thailand-Cambodia border" and "Indonesian Papua" only start with
    it (a prefix test hid both)."""
    def words(s):
        s = re.sub(r"\([^)]*\)", " ", s.lower().replace("’", "'"))
        return [w for w in re.sub(r"[^a-z0-9' ]+", " ", s).split() if w != "the"]
    return bool(name) and words(area) == words(name)


def regional_blocks(adv_html, name="", floor=None):
    """Every regional block of a country's `advisories` HTML (the
    country-wide one, notices (_notice) and GAC's [placeholder] records
    left out). The country-wide one's call is the level a reader assumes
    for an excepted place (_shorten); floor stands in where there is none
    (Israel and Palestine's page has only regional blocks)."""
    out, blocks = [], []
    for chunk in re.split(r"<h3[^>]*>", adv_html or "")[1:]:
        hm = re.match(r"(.*?)</h3>(.*)", chunk, re.S)
        if not hm:
            continue
        t = _txt(hm.group(1))
        if not t:
            continue
        if _country_wide(t.split(" - ")[0], name):
            r = _rank(t.split(" - ")[-1].strip())
            floor = r if r >= 0 else floor
            continue
        blocks.append((t, hm.group(2)))
    for t, body in blocks:
        lead = _first_sentence(body)
        # GAC ships template/test records for placeholder countries —
        # "[info alert heading]" / "[description of event]" — which must
        # never be served as if they were real advice.
        if re.fullmatch(r"\[.*\]", t) or re.fullmatch(r"\[.*\]", lead or ""):
            continue
        entry = _regional(t, body, floor)
        if entry is None:
            continue
        if not any(e["t"] == entry["t"] and e["text"] == entry["text"] for e in out):
            out.append(entry)
    return out


def cached(iso):
    """What get_watchouts last answered for this country, or None — the
    cache alone, never an upstream call (the guide page sizes its advisory
    block from it while the browser fetches the real answer)."""
    hit = _cache.get((iso or "").strip().lower()[:2])
    return None if not hit or hit[1].get("_failed") else {k: v for k, v in hit[1].items() if k != "_failed"}


def from_feed(iso, raw):
    """The /api/watchouts answer for one country from Canada's per-country
    JSON as fetched (the tests and scripts/dev/avoid_lines_dump.py read it
    the same way)."""
    out = {"iso": iso.upper(), "source": "Global Affairs Canada",
           "link": "", "watchouts": [], "regional": []}
    d = (raw or {}).get("data") or {}
    eng = d.get("eng") or {}
    if eng.get("url-slug"):
        out["link"] = "https://travel.gc.ca/destinations/" + eng["url-slug"]
    # Regional advisories live in the `advisories` block as their own headed
    # sections (regional_blocks above); the country-wide one is left out —
    # the level beside the notes already says it.
    state = d.get("advisory-state")       # 0-3, normal to avoid all: the level where no block says it
    regional = regional_blocks(eng.get("advisories", "") or "", (eng.get("name") or "").strip(),
                               state if isinstance(state, int) and 0 <= state <= 3 else None)
    if len(regional) > REGIONAL_CAP:
        print("[watchouts] %s: %d regional blocks, the first %d kept" % (iso.upper(), len(regional), REGIONAL_CAP),
              file=sys.stderr, flush=True)
    out["regional"] = regional[:REGIONAL_CAP]
    secs = _sections(eng.get("security", "")) + _sections(eng.get("disasters-climate", ""))
    secs = [s for s in secs if not re.fullmatch(r"\[.*\]", s.get("t", ""))
            and not re.fullmatch(r"\[.*\]", s.get("d", "") or "")]
    out["watchouts"] = secs[:8]
    return out


def get_watchouts(iso):
    iso = (iso or "").strip().lower()[:2]
    if not re.fullmatch(r"[a-z]{2}", iso):
        return {"iso": iso.upper(), "watchouts": [], "regional": []}
    now = time.time()
    hit = _cache.get(iso)
    if hit and now - hit[0] < (FAIL_TTL if hit[1].get("_failed") else TTL):
        return {k: v for k, v in hit[1].items() if k != "_failed"}
    out = {"iso": iso.upper(), "source": "Global Affairs Canada",
           "link": "", "watchouts": [], "regional": []}
    try:
        out = from_feed(iso, rates.fetch_json(API.format(iso=iso)))
    except Exception as e:
        # A country the feed lacks (404/410 — what the feed answers for a
        # missing file) simply shows no watchouts, for the full TTL. Anything
        # else is a failure, not an answer: keep the last good copy, or
        # remember the empty one only briefly — caching it for 6h hid a
        # country's safety notes from everyone after one timeout. That covers
        # 429/408 too: fetch_json re-raises every 4xx without retrying, and a
        # rate limit says nothing about whether the country has notes.
        if (getattr(e, "code", None) or 0) not in (404, 410):
            if hit and not hit[1].get("_failed"):
                _cache[iso] = (now - TTL + FAIL_TTL, hit[1])
                return hit[1]
            _cache[iso] = (now, dict(out, _failed=True))
            return out
    _cache[iso] = (now, out)
    return out

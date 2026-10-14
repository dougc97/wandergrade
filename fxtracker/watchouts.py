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
# (_Body), and its one-line form (line, brief) is written here once, from
# Canada's own words — selected and shortened, never restated — for the
# guide, the Safety table, the server's stand-in and the AI prompts alike.

REGIONAL_CAP = 12   # Israel and Palestine has 6, the most on 2026-10-14
LINE_CAP = 260      # the guide's 📍 line, after the call: lists are cut to it
LINE_MAX = 300      # …and nothing goes past this (an area and its exception
                    # in one long sentence each: northern Sinai, 286)
BRIEF_CAP = 120     # the trip prompt's line per area
TEXT_CAP = 2000     # the tip: Canada's full text, cut at a line or sentence

# Canada's calls, mildest first: an exception "where you should exercise a
# high degree of caution" is milder than an avoid-all block and can go when
# a line is short of room; one "where you should avoid all travel" (Tanzania's
# 10 km band inside its avoid-non-essential area) is stricter and never goes.
_CALLS = ["take normal security precautions", "exercise a high degree of caution",
          "avoid non-essential travel", "avoid all travel"]
_CALL_RX = r"(?:avoid all travel|avoid non-essential travel|exercise a high degree of caution|take normal security precautions)"
_LEAD_CALL = re.compile(r"^(" + _CALL_RX + r")\b[\s:]*(?:(?:to|in|on)\b\s*)*", re.I)   # "to to" (Mozambique), "on the east coast" (Sabah)
# "where you should exercise a high degree of caution", "on which you
# should …", "to which you should …", Ecuador's "where we advise against
# all travel".
_WHERE = re.compile(r",?\s+(?:where|on which|to which|in which)\s+(?:you should|we advise)\s+"
                    r"(avoid all travel|(?:advise )?against all travel|avoid non-essential travel|"
                    r"exercise a high degree of caution|take normal security precautions)\b", re.I)
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
_ADVISORY = r"^this (?:advisory|warning) (?:also )?"
_EXCLUDES = re.compile(_ADVISORY + r"(?:excludes|does not (?:include|apply to))\s*:?\s*(.*?)[.:]?$", re.I | re.S)
_INCLUDES = re.compile(_ADVISORY + r"includes\s*:?\s*(.*?)[.:]?$", re.I | re.S)
# Words that take the list after them as their object ("…, especially:",
# "the municipalities of:"): the list follows them directly.
_OBJECT_END = re.compile(r"\b(?:of|in|especially|including|particularly|notably|namely)$", re.I)


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
    c = (call or "").lower()
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


def _split_exc(text):
    """(base, exception or None): "Caquetá, excluding the city of Florencia"
    -> ("Caquetá", "the city of Florencia"); "Meta, excluding:" -> ("Meta", "")."""
    m = _EXC_PAREN.search(text)
    if m:
        return _clean(text[:m.start()] + text[m.end():]).rstrip(" ,:"), _clean(m.group(1))
    m = _EXC_INLINE.search(text)
    if m and m.start() > 0:
        return text[:m.start()].rstrip(" ,:"), _clean(m.group(1)).rstrip(" :")
    return text, None


def _shorten(s, rank):
    """An exception, said shorter when a line is short of room: its "where
    you should <call>" goes when that call is milder than the block's (never
    a stricter one: Tanzania's 10 km band "where you should avoid all
    travel" stays), and so do its asides — "(and highway 186 leading
    there)", "(which is currently closed)", "(formerly Karachi South)", an
    acronym's "(DHA)" — "the city of" before a name, and Karachi's bare
    "the following areas". Each only narrows what reads as excepted: the
    safe way to be short."""
    s = _WHERE.sub(lambda m: "" if 0 <= _rank(m.group(1)) < rank else m.group(0), s)
    s = re.sub(r"\s*\((?:and|which|formerly)\b[^()]*\)|\s*\([A-Z]{2,6}\)", "", s)
    s = re.sub(r"^(?:the )?(?:city and ruins|cities|city|towns?|municipalit(?:y|ies)) of\s+", "", _clean(s), flags=re.I)
    return re.sub(r"^the following (?:areas?|locations?)$", "", s, flags=re.I)


def _sep(parts):
    """The joint for a list: a comma while every part is a bare name, a
    semicolon once any carries a comma or a bracket ("Cesar, in the
    municipalities of González and Río de Oro"; "southern Songkhla province
    (Hat Yai city; …)")."""
    return "; " if any(re.search(r"[,;(]", x) for x in parts) else ", "


def _join(parts):
    return _sep(parts).join(parts)


def _more(n):
    return "and %d more" % n


_BAND = re.compile(r"^(within \d+ (?:km|kilometres) of the border with )(.+)$", re.I)


def _bands(parts):
    """Brazil's eight "within 20 km of the border with X" said once each
    distance: "within 20 km of the border with Bolivia (except Pantanal
    National Park), Colombia, French Guiana, …". Only Canada's words, less
    their repeats, and only for places named bare (a comma in one would blur
    where the next begins); used where the whole list then fits (a cut list
    keeps one place per part, so "and N more" counts places)."""
    out = []      # [band words or None, [places]]
    for p in parts:
        m = _BAND.match(p)
        band = m.group(1) if m and "," not in re.sub(r"\([^()]*\)", "", m.group(2)) else None
        if band and out and out[-1][0] and out[-1][0].lower() == band.lower():
            out[-1][1].append(m.group(2))
        else:
            out.append([band, [m.group(2) if band else p]])
    return [(b + ", ".join(ps)) if b else ps[0] for b, ps in out]


def _render(item, mode, rank, exc_ctx=False, room=None):
    """One list item as the line says it: its own words, its sub-items in
    brackets after it, its exceptions named — "Chocó (except the towns of
    Bahía Solano, Capurganá, Nuquí)", "southern Songkhla province (Hat Yai
    city; east of Highways 408 and 4113, including Sakom)". With room, a
    long sub-list is cut to "and N more" (the tip has it whole): a place's
    sub-places or its exceptions (fewer exceptions only make the line
    stricter), never anything inside an exception — Karachi's excepted
    District of Karachi has its own exclusions, and cut, the line would
    except more than Canada does."""
    text, kids = item["t"], item["items"]
    base, exc = _split_exc(text)
    if exc is not None:
        if mode == "compact":
            exc = _shorten(exc, rank)
            base = _shorten(base, rank) if exc_ctx else base
        head = base.rstrip(" ,:") + " (except "
        if exc and kids:
            head += exc + (" " if _OBJECT_END.search(exc) else ": ")
        elif exc:
            head += exc
        close, kid_exc = ")", True
    else:
        head = re.sub(r"^the following\s+", "", text, flags=re.I).rstrip(" :")
        if exc_ctx and mode == "compact":
            head = _shorten(head, rank)
        if not kids:
            return head
        if len(kids) == 1 and _OBJECT_END.search(head):
            head, close = head + " ", ""     # "…, especially all of the following regions (…)"
        else:
            head, close = head + " (", ")"
        kid_exc = exc_ctx
    if not kids:
        return head + close
    if room is None or exc_ctx:
        return head + _join([_render(k, mode, rank, kid_exc) for k in kids]) + close
    return head + _fill(kids, mode, rank, kid_exc, max(room - len(head) - len(close), 24))[0] + close


def _fill(items, mode, rank, exc_ctx, room, later=0):
    """(text, shown): the items in Canada's order while they fit in room, an
    item too long for what is left cut inside its own sub-list, then "and N
    more" — N counts the items left out and `later` more after these. The
    first item always stays."""
    full = [_render(i, mode, rank, exc_ctx) for i in items]
    sep = _sep(full)
    if not later and len(sep.join(full)) <= room:
        return sep.join(full), len(full)
    out = []
    for i, (f, it) in enumerate(zip(full, items)):
        rest = len(items) - i - 1 + later
        left = room - len(sep.join(out + [""])) - (len(sep + _more(rest)) if rest else 0)
        if len(f) <= left:
            out.append(f)
            continue
        cut = _render(it, mode, rank, exc_ctx, left) if it["items"] else f
        if len(cut) <= left or not out:
            out.append(cut)
            if len(cut) <= left:
                continue
        break
    n = len(items) - len(out) + later
    return sep.join(out) + (sep + _more(n) if n else ""), len(out)


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


def _analyze(t, fragment):
    """A block's parts: its call, its area, its lists grouped under the
    sentences that introduce them, and the exceptions and inclusions Canada
    states, in its order."""
    nodes = _body(fragment)
    paras = [v for k, v in nodes if k == "p"]
    lead = (_sentences(paras[0]) or [""])[0] if paras else ""
    parts = [p.strip() for p in t.split(" - ")]
    head_call = parts[-1] if len(parts) > 1 else ""
    head = _unshout(" - ".join(parts[:-1]) if len(parts) > 1 else t)
    L = _lead_parts(lead)
    if head_call and head_call.lower() in _CALLS:
        call = head_call.capitalize()
    elif L:
        call = L["call"].capitalize()
    else:
        call = _unshout(head_call) or head    # Canada's Ebola border notice has no call
    groups, extras, pending, last, first = [], [], None, None, True
    for kind, v in nodes:
        if kind == "p":
            ss = _sentences(v)
            if first:
                ss, first = ss[1:], False
            for s in ss:
                last = None
                for k, rx in (("except", _EXCLUDES), ("include", _INCLUDES)):
                    m = rx.match(s)
                    if m:
                        x = _clean(m.group(1))
                        if s.rstrip().endswith(":"):
                            pending = (k, x)
                        else:
                            extras.append({"k": k, "t": x, "items": []})
                        break
                else:
                    pending = ("group", s.rstrip(" :")) if s.rstrip().endswith(":") else None
            continue
        if pending:
            k, x = pending
            if k == "group":
                # "This area consists of:" (Peru's VRAEM) only says the list
                # is the area; Guatemala's "Within Guatemala City:" says where.
                x = "" if re.search(r"\bconsists of$", x, re.I) else re.sub(r"^the following\s+", "", x, flags=re.I)
                groups.append({"intro": x, "items": list(v)})
                last = groups[-1]
            else:
                extras.append({"k": k, "t": x, "items": list(v)})
                last = extras[-1]
            pending = None
        elif last is not None:
            last["items"].extend(v)        # one list the HTML split in two (Tunisia, Mauritania)
        elif L and L["exc_list"] and not groups and not extras:
            extras.append({"k": "except", "t": L["exc_list"], "items": list(v)})
            last = extras[-1]
        else:
            groups.append({"intro": L["intro"] if L and not groups else "", "items": list(v)})
            last = groups[-1]
    if L and L["exc"]:
        extras.insert(0, {"k": "except", "t": L["exc"], "items": []})

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
            optional = area == head
        if items and area and all(_split_exc(it["t"])[0].rstrip(" :").lower() in area.lower() for it in items):
            area = ""      # a heading that names every place adds nothing to them
        if not area and not items and named:
            area = head
    else:
        area = re.sub(r"\.$", "", lead) if lead else (head if named else "")
    return {"t": t, "call": call, "rank": _rank(call), "head": head, "named": named, "lead": lead, "L": L,
            "area": area, "optional": optional and bool(area), "groups": groups, "extras": extras, "nodes": nodes}


def _compose(B, mode, room=None):
    """The block in one line: the area, its places (each list under the words
    that introduce it), then what Canada excepts and includes. With room,
    the places are cut to "and N more" and a long list of exceptions keeps
    at least a third of it."""
    rank, prefix, groups, extras = B["rank"], B["area"], B["groups"], B["extras"]

    def ex(limit=None):
        out, prev = "", None
        for e in extras:
            x = _shorten(e["t"], rank) if mode == "compact" and e["k"] == "except" else e["t"]
            body = x
            if e["items"]:
                pre = (x + (" " if _OBJECT_END.search(x) else ": ")) if x else ""
                exc = e["k"] == "except"
                if limit is None:
                    body = pre + _join([_render(i, mode, rank, exc) for i in e["items"]])
                else:
                    body = pre + _fill(e["items"], mode, rank, exc, max(limit - len(out) - len(pre) - 10, 30))[0]
            word = "except " if e["k"] == "except" else "including "
            out += ("; " + body) if prev == e["k"] else ((", " if out else "") + word + body)
            prev = e["k"]
        return out

    def grp(limit=None):
        multi = len(groups) > 1
        total = sum(len(g["items"]) for g in groups)
        out, shown = "", 0
        for g in groups:
            intro = g["intro"]
            if multi and intro:
                intro = intro[:1].upper() + intro[1:]
            lab = (intro + (" " if _OBJECT_END.search(intro) else ": ")) if intro else ""
            pre = (". " if out else "") + lab
            if limit is None:
                out += pre + _join(_bands([_render(i, mode, rank) for i in g["items"]]))
                continue
            left = limit - len(out) - len(pre)
            later = total - shown - len(g["items"])
            if out and left < 30:
                break
            txt, n = _fill(g["items"], mode, rank, False, left - (16 if later else 0))
            if n == len(g["items"]) and not txt.endswith(" more"):
                out, shown = out + pre + txt, shown + n
                continue
            return out + pre + _fill(g["items"], mode, rank, False, left, later)[0]
        if limit is not None and shown < total:
            out += "; " + _more(total - shown)
        return out

    def put(g, e):
        s = prefix
        if g:
            s = (s + (", " if re.match(r"(?:particularly|especially|notably|including)\b", g) else ": ") if s else "") + g
        if e:
            s = (s + (" — " if g else ", ") if s else "") + e
        return s

    if room is None:
        return put(grp(), ex())
    if not groups:
        return put("", ex(max(room - len(prefix) - 2, 40)))
    # The places first: cutting an exception only makes the line stricter
    # than Canada, cutting a place hides one. The exceptions keep a third.
    e, g = ex(), grp()
    if len(prefix) + len(g) + len(e) + 5 > room:
        e_room = max(room - len(prefix) - len(g) - 5, room // 3)
        if len(e) > e_room:
            e = ex(e_room)
    return put(grp(max(room - len(prefix) - len(e) - 5, 40)), e)


def _line(B, cap, ceiling=None):
    """The block's line within cap: whole if it fits, else with its milder
    exceptions said shorter, then without a heading standing in for "the
    following areas", then cut to "and N more". Past `ceiling` only when
    nothing can be cut (one sentence each for an area and its exception)."""
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
        # Not a call (the Ebola border notice): its first sentence says what
        # it is, and its list of rules lives in the tip.
        B = dict(B, groups=[])
    room = cap
    s = _compose(B, "compact", room)
    while len(s) > cap and room > 80:
        room -= len(s) - cap
        s = _compose(B, "compact", room)
    if len(s) > (ceiling or cap):
        # One place or exception longer than the line (none on 2026-10-14):
        # the area, flagged when Canada excepts parts of it, and the tip.
        s = (B["area"] or B["head"]) + (" (parts excepted)" if _excepted(B) else "")
        s = s if len(s) <= cap else s[:cap - 3].rsplit(" ", 1)[0] + "..."
    return s


def _excepted(B):
    flat = [it for g in B["groups"] for it in g["items"]]
    return any(e["k"] == "except" for e in B["extras"]) or any(_split_exc(it["t"])[1] is not None for it in _walk(flat))


def _names(B, cap):
    """The trip prompt's form of a long list under a generic heading: each
    place in its own words without its exceptions, starred where it has
    some (the prompt says what * means), cut to "and N more"."""
    def name(it):
        base, exc = _split_exc(it["t"])
        base = re.sub(r"^the following\s+", "", base, flags=re.I).rstrip(" ,:")
        if exc is None and it["items"] and _OBJECT_END.search(base):
            return base + " " + _join([name(k) for k in it["items"]])   # "in the departments of …"
        return base + ("*" if exc is not None or any(_split_exc(k["t"])[1] is not None for k in _walk(it["items"])) else "")
    flat = [it for g in B["groups"] for it in g["items"]]
    names = [name(it) for it in flat]
    pre = B["area"] + ": " if B["area"] and not B["optional"] else ""
    sep = _sep(names)
    out = []
    for i, n in enumerate(names):
        rest = len(names) - i - 1
        if out and len(pre + sep.join(out + [n]) + (sep + _more(rest) if rest else "")) > cap:
            break
        out.append(n)
    left = len(names) - len(out)
    s = pre + sep.join(out) + (sep + _more(left) if left else "")
    return s + ("*" if any(e["k"] == "except" for e in B["extras"]) and not s.endswith("*") else "")


def _regional(t, fragment):
    """One regional block as /api/watchouts serves it. line: the 📍 line after
    its call, Canada's words selected and shortened (the guide, the Safety
    table, the server's stand-in); brief: the trip prompt's line, shorter
    still; text: the whole block for the tip."""
    B = _analyze(t, fragment)
    rank = B["rank"]
    flat = [it for g in B["groups"] for it in g["items"]]
    line = _line(B, LINE_CAP, LINE_MAX)
    compact = _compose(B, "compact")
    excepted = _excepted(B)
    if len(compact) <= BRIEF_CAP:
        brief = compact
    elif not B["L"]:
        brief = _line(dict(B, area=B["head"]), BRIEF_CAP)    # a notice, not a call: its heading
    elif B["named"]:
        brief = B["head"] + (" (parts excepted)" if excepted else "")
    else:
        # Guatemala's lists each sit under their own words ("Within
        # Guatemala City:"), which the names alone would lose.
        brief = _line(B, BRIEF_CAP) if len(B["groups"]) > 1 or not flat else ""
        if not brief or len(brief) > BRIEF_CAP or brief == (B["area"] or B["head"]):
            brief = _names(B, BRIEF_CAP) if flat else brief

    def said(e, exc):
        its = [_render(i, "full", rank, exc) for i in e["items"]]
        if not its:
            return e["t"]
        return (e["t"] + (" " if _OBJECT_END.search(e["t"]) else ": ") if e["t"] else "") + _join(its)

    excepts = [said(e, True) for e in B["extras"] if e["k"] == "except"]
    for it in _walk(flat):
        x = _split_exc(it["t"])[1]
        if x is not None:
            excepts.append(said({"t": x, "items": it["items"]}, True))
    return {
        "t": t[:120], "call": B["call"], "lead": B["lead"], "line": line, "brief": brief,
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


def regional_blocks(adv_html, name=""):
    """Every regional block of a country's `advisories` HTML (the
    country-wide one and GAC's [placeholder] records left out)."""
    out = []
    for chunk in re.split(r"<h3[^>]*>", adv_html or "")[1:]:
        hm = re.match(r"(.*?)</h3>(.*)", chunk, re.S)
        if not hm:
            continue
        t = _txt(hm.group(1))
        if not t or _country_wide(t.split(" - ")[0], name):
            continue
        body = hm.group(2)
        lead = _first_sentence(body)
        # GAC ships template/test records for placeholder countries —
        # "[info alert heading]" / "[description of event]" — which must
        # never be served as if they were real advice.
        if re.fullmatch(r"\[.*\]", t) or re.fullmatch(r"\[.*\]", lead or ""):
            continue
        entry = _regional(t, body)
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
    regional = regional_blocks(eng.get("advisories", "") or "", (eng.get("name") or "").strip())
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

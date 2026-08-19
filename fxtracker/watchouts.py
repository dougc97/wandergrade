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
import time

from . import rates

API = "https://data.international.gc.ca/travel-voyage/cta-cap-{iso}.json"
TTL = 6 * 3600
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


def get_watchouts(iso):
    iso = (iso or "").strip().lower()[:2]
    if not re.fullmatch(r"[a-z]{2}", iso):
        return {"iso": iso.upper(), "watchouts": [], "regional": []}
    now = time.time()
    hit = _cache.get(iso)
    if hit and now - hit[0] < TTL:
        return hit[1]
    out = {"iso": iso.upper(), "source": "Global Affairs Canada",
           "link": "", "watchouts": [], "regional": []}
    try:
        raw = rates.fetch_json(API.format(iso=iso))
        d = (raw or {}).get("data") or {}
        eng = d.get("eng") or {}
        if eng.get("url-slug"):
            out["link"] = "https://travel.gc.ca/destinations/" + eng["url-slug"]
        name = (eng.get("name") or "").strip().lower()
        # Regional advisories live in the `advisories` block as their own headed
        # sections. The country-wide heading repeats the country name and is
        # skipped; the rest carry the state/city-level nuance a flat 1-4 level
        # hides — heading, the "due to" clause, and the named regions (starred
        # when the source lists exceptions for them).
        adv_html = eng.get("advisories", "") or ""
        parts = re.split(r"<h3[^>]*>", adv_html)
        for chunk in parts[1:]:
            hm = re.match(r"(.*?)</h3>(.*)", chunk, re.S)
            if not hm:
                continue
            t = _txt(hm.group(1))
            if not t or t.lower().startswith(name):
                continue
            body = hm.group(2)
            lead = _first_sentence(body)
            # GAC ships template/test records for placeholder countries —
            # "[info alert heading]" / "[description of event]" — which must
            # never be served as if they were real advice.
            if re.fullmatch(r"\[.*\]", t) or re.fullmatch(r"\[.*\]", lead or ""):
                continue
            entry = {"t": t[:120], "lead": lead[:200],
                     "regions": _top_level_items(body)}
            if entry not in out["regional"]:
                out["regional"].append(entry)
        out["regional"] = out["regional"][:4]
        secs = _sections(eng.get("security", "")) + _sections(eng.get("disasters-climate", ""))
        secs = [s for s in secs if not re.fullmatch(r"\[.*\]", s.get("t", ""))
                and not re.fullmatch(r"\[.*\]", s.get("d", "") or "")]
        out["watchouts"] = secs[:8]
    except Exception:
        pass   # a country the feed lacks simply shows no watchouts
    _cache[iso] = (now, out)
    return out

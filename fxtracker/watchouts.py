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
        # Regional advisories live in the `advisories` block as their own
        # "<Region> - Avoid ..." headings; the country-wide heading repeats the
        # country name, so it is filtered rather than shown twice.
        for m in re.finditer(r"<h3[^>]*>(.*?)</h3>", eng.get("advisories", "") or "", re.S):
            t = _txt(m.group(1))
            if t and " - " in t and not t.lower().startswith(name):
                if t not in out["regional"]:
                    out["regional"].append(t[:120])
        out["regional"] = out["regional"][:6]
        secs = _sections(eng.get("security", "")) + _sections(eng.get("disasters-climate", ""))
        out["watchouts"] = secs[:8]
    except Exception:
        pass   # a country the feed lacks simply shows no watchouts
    _cache[iso] = (now, out)
    return out

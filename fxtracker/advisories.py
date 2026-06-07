"""US State Dept travel advisories: fetch the RSS feed, parse level (1-4) per
country, and map names to ISO codes so the map can color them. No key."""

import os
import re
import json
import html

from . import rates  # reuse fetch_json's verifying SSL + retries

FEED = "https://travel.state.gov/_res/rss/TAsTWs.xml"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOJSON = os.path.join(ROOT, "public", "world.geojson")

LEVEL_TEXT = {
    1: "Exercise Normal Precautions",
    2: "Exercise Increased Caution",
    3: "Reconsider Travel",
    4: "Do Not Travel",
}

# State Dept names that don't match the map's country names.
ALIASES = {
    "burma": "MM", "myanmar": "MM",
    "democratic republic of the congo": "CD", "dr congo": "CD",
    "republic of the congo": "CG", "congo": "CG",
    "cote d ivoire": "CI", "ivory coast": "CI",
    "south korea": "KR", "korea": "KR", "north korea": "KP",
    "russia": "RU", "russian federation": "RU",
    "czech republic": "CZ", "czechia": "CZ",
    "the gambia": "GM", "gambia": "GM",
    "eswatini": "SZ", "swaziland": "SZ",
    "timor leste": "TL", "east timor": "TL",
    "cabo verde": "CV", "cape verde": "CV",
    "north macedonia": "MK", "macedonia": "MK",
    "bosnia and herzegovina": "BA",
    "central african republic": "CF",
    "dominican republic": "DO",
    "south sudan": "SS", "sudan": "SD",
    "equatorial guinea": "GQ", "guinea bissau": "GW",
    "united kingdom": "GB", "great britain": "GB",
    "united states": "US", "united states of america": "US",
    "laos": "LA", "syria": "SY", "vietnam": "VN", "brunei": "BN",
    "moldova": "MD", "tanzania": "TZ", "venezuela": "VE", "bolivia": "BO",
    "iran": "IR", "palestinian territories": "PS", "west bank": "PS",
    "micronesia": "FM", "trinidad and tobago": "TT", "saint lucia": "LC",
    "bahrain": "BH", "comoros": "KM", "solomon islands": "SB", "hong kong": "HK",
    "macau": "MO", "sao tome and principe": "ST", "maldives": "MV",
    "mauritius": "MU", "kingdom of denmark": "DK",
}


def _norm(name):
    name = html.unescape(name).lower()
    name = re.sub(r"\btravel advisory\b", "", name)
    name = re.sub(r"[^a-z ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name.startswith("the "):
        name = name[4:]
    return name


def _name_to_iso():
    """Map normalized country name -> ISO from the geojson, plus aliases."""
    out = {}
    try:
        with open(GEOJSON, encoding="utf-8") as f:
            geo = json.load(f)
        for feat in geo["features"]:
            iso = feat["properties"].get("iso")
            nm = feat["properties"].get("name")
            if iso and iso != "-99" and nm:
                out[_norm(nm)] = iso
    except Exception:
        pass
    out.update(ALIASES)
    return out


def get_advisories():
    """Return {as_of, items: [{iso, country, level, level_text, link}]}."""
    raw = _fetch_text(FEED)
    name_iso = _name_to_iso()

    items = []
    seen = set()
    for block in re.findall(r"<item>(.*?)</item>", raw, re.S):
        title = _tag(block, "title")
        link = _tag(block, "link")
        if not title:
            continue
        m = re.match(r"(.+?)\s*[-–]\s*Level\s*(\d)", html.unescape(title))
        if not m:
            continue
        country = re.sub(r"\s*travel advisory\s*$", "", m.group(1).strip(), flags=re.I)
        key = _norm(country)
        # Skip composite/placeholder rows and duplicate countries (the feed repeats some).
        if not key or "see summaries" in key or key in seen:
            continue
        seen.add(key)
        level = int(m.group(2))
        iso = name_iso.get(key)
        items.append({
            "iso": iso,
            "country": country,
            "level": level,
            "level_text": LEVEL_TEXT.get(level, ""),
            "link": link,
        })

    items.sort(key=lambda r: (-r["level"], r["country"]))
    return {"items": items, "count": len(items),
            "matched": sum(1 for i in items if i["iso"])}


def _tag(block, tag):
    m = re.search(r"<{0}>(.*?)</{0}>".format(tag), block, re.S)
    if not m:
        return ""
    val = m.group(1)
    cdata = re.match(r"\s*<!\[CDATA\[(.*?)\]\]>\s*$", val, re.S)
    return (cdata.group(1) if cdata else val).strip()


def _fetch_text(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 fx-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=rates.TIMEOUT, context=rates._SSL) as resp:
        return resp.read().decode("utf-8", "replace")

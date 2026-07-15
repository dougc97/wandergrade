"""Travel advisories from multiple governments, normalized to a 1-4 level per
country so the map can color them and the score can use them. Which source is
used follows the traveler's home country (US State Dept by default; German
Federal Foreign Office for German travelers) — government advisories reflect
each country's own foreign policy, so a single source can feel skewed. No key."""

import os
import re
import json
import html

from . import rates  # reuse fetch_json's verifying SSL + retries

FEED = "https://travel.state.gov/_res/rss/TAsTWs.xml"
US_URL = "https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories.html"

# German Federal Foreign Office (Auswärtiges Amt) open data — per-country travel
# warnings with ISO-2 country codes and warning/partialWarning flags.
AA_FEED = "https://www.auswaertiges-amt.de/opendata/travelwarning"
AA_URL = "https://www.auswaertiges-amt.de/de/ReiseUndSicherheit/reise-und-sicherheitshinweise"

SOURCES = {
    "us": "U.S. State Department",
    "de": "German Federal Foreign Office (Auswärtiges Amt)",
}
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
    # Names the feed publishes that the map spells differently. Without these the
    # country silently has no advisory and safetyPill() reads it as Level 2 — so
    # Kyrgyzstan (actually Level 1) was being marked down, not up.
    "kyrgyz republic": "KG", "kyrgyzstan": "KG",
    "federated states of micronesia": "FM",
    "turks and caicos islands": "TC", "montserrat": "MS",
    "saint kitts and nevis": "KN", "saint vincent and the grenadines": "VC",
    "french guiana": "GF",
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


def _from(source):
    return _german_advisories() if source == "de" else _us_advisories()


def get_advisories(source="us"):
    """Advisories from the given government source, normalized to a common shape:
    {items: [{iso, country, level, level_text, link, via?, via_name?}], source, ...}.

    Where the home government publishes nothing, the other government fills in and
    the item is stamped with `via` so the UI can say whose call it is. This is not
    tidiness: the US feed silently omits Israel, the West Bank and Gaza, and Brazil
    (verified — 219 entries, A-Z, no Israel between Ireland and Italy), and an
    unrated country used to be read as Level 2, so Palestine came out graded B and
    recommendable. Germany rates it Level 4.

    Nothing is invented. A country neither government rates stays unrated, and
    valueScores() drops it from the picks rather than guess a level for it.

    Caveat worth knowing: the German feed is binary (warning / partial warning), so
    it can never express Level 3 — a partial warning arrives here as Level 2. That
    makes it a lossy filler. A source with a native 1-4 scale (Canada, Australia)
    would fill these gaps more faithfully.
    """
    primary = _from(source)
    other_key = "us" if source == "de" else "de"
    try:
        other = _from(other_key)
    except Exception:
        return primary          # a filler that won't load must never break the page
    have = {i["iso"] for i in primary["items"] if i.get("iso")}
    for it in other["items"]:
        iso = it.get("iso")
        if not iso or iso in have:
            continue
        fill = dict(it, via=other_key, via_name=SOURCES[other_key])
        primary["items"].append(fill)
        have.add(iso)
    primary["items"].sort(key=lambda r: (-r["level"], r["country"]))
    primary["count"] = len(primary["items"])
    primary["matched"] = sum(1 for i in primary["items"] if i["iso"])
    primary["filled"] = sum(1 for i in primary["items"] if i.get("via"))
    return primary


def _german_advisories():
    """German Foreign Office warnings -> 1-4 levels. Germany only issues warnings
    for genuinely risky places, so most countries read as Level 1 (normal) — a
    deliberately less-alarmist, non-US view."""
    raw = rates.fetch_json(AA_FEED)
    resp = (raw or {}).get("response", {}) if isinstance(raw, dict) else {}
    items = []
    for v in resp.values():
        if not isinstance(v, dict):
            continue
        iso = (v.get("countryCode") or "").strip().upper()
        if len(iso) != 2:
            continue
        if v.get("warning"):
            level, txt = 4, "Reisewarnung (avoid travel)"
        elif v.get("partialWarning"):
            # A Teilreisewarnung covers specific regions, not the whole country
            # (e.g. Japan's is just the Fukushima exclusion zone) — country-wide
            # that reads as "increased caution", not "reconsider travel".
            level, txt = 2, "Teilreisewarnung (warning for some regions)"
        else:
            level, txt = 1, "Keine Warnung (no warning)"
        items.append({"iso": iso, "country": v.get("countryName", ""),
                      "level": level, "level_text": txt, "link": AA_URL})
    items.sort(key=lambda r: (-r["level"], r["country"]))
    return {"items": items, "count": len(items),
            "matched": sum(1 for i in items if i["iso"]),
            "source": "de", "source_name": SOURCES["de"], "source_url": AA_URL}


def _us_advisories():
    """Return {items: [{iso, country, level, level_text, link}], source...}."""
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
            "matched": sum(1 for i in items if i["iso"]),
            "source": "us", "source_name": SOURCES["us"], "source_url": US_URL}


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

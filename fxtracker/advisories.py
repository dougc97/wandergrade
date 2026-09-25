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

# Global Affairs Canada open data: one JSON, ISO-2 codes already in it, and a
# native four-level scale that lands 1:1 on ours. The best-shaped feed of the
# three, which is why it fills gaps before the others do.
CA_FEED = "https://data.international.gc.ca/travel-voyage/index-alpha-eng.json"
CA_URL = "https://travel.gc.ca/travelling/advisories"

SOURCES = {
    "us": "U.S. State Department",
    "de": "German Federal Foreign Office (Auswärtiges Amt)",
    "ca": "Global Affairs Canada",
}

# Who fills a gap first. Ordered by how well the source's own scale maps to ours:
# Canada and the US publish four levels; Germany publishes a binary warning and
# cannot express Level 3, so it goes last and only covers what the others miss.
FALLBACK_ORDER = ("ca", "us", "de")
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
    # The feed publishes Gaza (Level 4) as its own row; unmatched, Palestine was
    # left on the West Bank's Level 3 and ranked when the floor was "Any".
    "gaza": "PS", "gaza strip": "PS",
    # "Mainland China, Hong Kong & Macau - See Summaries" rows are matched by the
    # slug of their link (china-travel-advisory.html) — see _us_advisories.
    "mainland china": "CN",
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


def _canadian_advisories():
    """Global Affairs Canada -> 1-4. advisory-state is 0-3 on a scale that matches
    ours rung for rung (normal precautions / high degree of caution / avoid
    non-essential travel / avoid all travel), so the mapping is +1 and no
    interpretation is needed. Countries arrive with ISO-2 attached, so unlike the
    US feed there is no name matching to get wrong."""
    raw = rates.fetch_json(CA_FEED)
    data = (raw or {}).get("data") or {}
    items = []
    for v in (data.values() if isinstance(data, dict) else data):
        if not isinstance(v, dict):
            continue
        iso = (v.get("country-iso") or "").strip().upper()
        state = v.get("advisory-state")
        if len(iso) != 2 or state is None:
            continue
        eng = v.get("eng") or {}
        slug = eng.get("url-slug")
        items.append({
            "iso": iso,
            "country": eng.get("name") or v.get("country-eng") or iso,
            "level": int(state) + 1,
            "level_text": eng.get("advisory-text") or LEVEL_TEXT.get(int(state) + 1, ""),
            "link": ("https://travel.gc.ca/destinations/" + slug) if slug else CA_URL,
        })
    items.sort(key=lambda r: (-r["level"], r["country"]))
    return {"items": items, "count": len(items),
            "matched": sum(1 for i in items if i["iso"]),
            "source": "ca", "source_name": SOURCES["ca"], "source_url": CA_URL}


def _from(source):
    if source == "de":
        return _german_advisories()
    if source == "ca":
        return _canadian_advisories()
    return _us_advisories()


def get_advisories(source="us"):
    """Advisories from the given government source, normalized to a common shape:
    {items: [{iso, country, level, level_text, link, via?, via_name?}], source, ...}.

    Where the home government publishes nothing, the other government fills in and
    the item is stamped with `via` so the UI can say whose call it is. This is not
    tidiness: the US feed is unstable (it has dropped Israel, the West Bank, Gaza
    and Brazil between fetches, and 213/209 items on consecutive days), and an
    unrated country used to be read as Level 2, so Palestine came out graded B and
    recommendable. Germany rates it Level 4. When the feed does publish Gaza
    (Level 4) and the West Bank (Level 3) as separate rows, both map to PS and
    the most cautious one is kept.

    Nothing is invented. A country neither government rates stays unrated, and
    valueScores() drops it from the picks rather than guess a level for it.

    Gap-fills are MOST-CAUTIOUS-WINS: when more than one other government rates
    a country the home source is silent on, the sternest published level fills
    the gap (ties go to the earlier source in FALLBACK_ORDER, which is ordered
    by scale fidelity). The home government stays authoritative whenever it
    speaks — this only governs substitutes. Rationale: the German feed is
    binary (warning / partial warning), so it can never express Level 3 and a
    partial warning arrives here as a flat Level 2. Under first-source-wins,
    Canada's feed dropping a country it rates L3 would have silently handed the
    fill to that lossy L2 — the country would look SAFER because a cautious
    voice vanished. A substitute judgment must never be softer than any
    government's published view.
    """
    primary = _from(source)
    have = {i["iso"] for i in primary["items"] if i.get("iso")}
    fills = {}   # iso -> (item, source_key) with the highest level seen
    for key in FALLBACK_ORDER:
        if key == source:
            continue
        try:
            other = _from(key)
        except Exception:
            continue            # a filler that won't load must never break the page
        for it in other["items"]:
            iso = it.get("iso")
            if not iso or iso in have:
                continue
            best = fills.get(iso)
            if best is None or it["level"] > best[0]["level"]:
                fills[iso] = (it, key)
    for it, key in fills.values():
        primary["items"].append(dict(it, via=key, via_name=SOURCES[key]))
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

    rows = []
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
        if not key:
            continue
        # Composite rows ("Mainland China, Hong Kong & Macau - See Summaries -
        # Level 2") are the ONLY China advisory the feed carries, so skipping them
        # credited China's level to Canada. Their link slug says which place each
        # one is (china-travel-advisory.html); they only fill places no
        # single-country row covers.
        composite = "see summaries" in _norm(title)
        if composite:
            slug = re.search(r"/([a-z-]+?)(?:-travel-advisory)?\d*\.html?$", link or "", re.I)
            key = _norm(slug.group(1).replace("-", " ")) if slug else ""
            if not key:
                continue
            country = key.title()
        rows.append((composite, key, country, int(m.group(2)), link, block))

    items = []
    seen = set()
    by_iso = {}
    # Single-country rows first, so a composite never shadows one.
    for composite, key, country, level, link, block in sorted(rows, key=lambda r: r[0]):
        if key in seen:              # the feed repeats some countries
            continue
        seen.add(key)
        iso = name_iso.get(key)
        desc = _tag(block, "description")
        item = {
            "iso": iso,
            "country": country,
            "level": level,
            "level_text": LEVEL_TEXT.get(level, ""),
            "link": link,
            # The government's own words on WHY, not just the level number.
            # 1-4 is black and white; "conditions vary widely from state to
            # state" is the nuance a traveler actually needs, and quoting the
            # feed keeps us out of the business of authoring safety claims.
            "summary": _summary(desc, level, iso, name_iso),
            # The bookkeeping sentences _summary discards ("The advisory level
            # was decreased to 1") are exactly the change signal — captured
            # here with the item's publish date so the UI can show what moved.
            "change": _change(desc),
            "updated": _pubdate(_tag(block, "pubDate")),
        }
        if not iso:
            items.append(item)
            continue
        # One row per country, most cautious wins (Gaza L4 over West Bank L3).
        # Clients keep the last row per ISO, so a duplicate would silently let
        # whichever sorted later decide.
        if iso not in by_iso or level > by_iso[iso]["level"]:
            by_iso[iso] = item
    items.extend(by_iso.values())

    items.sort(key=lambda r: (-r["level"], r["country"]))
    return {"items": items, "count": len(items),
            "matched": sum(1 for i in items if i["iso"]),
            "source": "us", "source_name": SOURCES["us"], "source_url": US_URL}


# The lead phrase each level opens with. A summary whose lead doesn't match the
# row's own level is quoting a different advisory: Macau's item (Level 3) opens
# with the shared China/Hong Kong text, so its tooltip read "Exercise increased
# caution in Hong Kong..." — a lower level for a different place.
LEVEL_LEAD = {1: r"exercise normal precaution", 2: r"exercise (increased|a high degree of) caution",
              3: r"reconsider travel", 4: r"do not travel"}


def _fold(text):
    """Lower-case ASCII for loose name matching (Côte -> cote)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", " ", t.lower()).strip()


def _names(sentence, iso, name_iso):
    """(names this row's place, names some OTHER mapped place) for the "where"
    part of a lead sentence — the words before "due to"."""
    where = " " + _fold(re.split(r"\bdue to\b", sentence, 1, flags=re.I)[0]) + " "
    hits = [(nm, i) for nm, i in name_iso.items() if len(nm) >= 4 and " " + nm + " " in where]
    # "guinea" inside "papua new guinea" is not a second place.
    hits = [(nm, i) for nm, i in hits if not any(nm != o and nm in o for o, _ in hits)]
    return any(i == iso for _, i in hits), any(i != iso for _, i in hits)


def _summary(desc, level=None, iso=None, name_iso=None):
    """First two meaningful sentences of the advisory description, plain text.
    The description opens by restating the level ("Exercise increased caution
    in Mexico due to...") — that first sentence carries the WHY (due to
    terrorism, crime, and kidnapping), the next carries the flavor. Capped so
    a chatty advisory can't flood a guide page; the full text is one click
    away on the linked page.

    With `level`/`iso`/`name_iso`, the lead must be this row's own: in order of
    preference, this level's phrase naming this place; this level's phrase
    naming no other place; any level's phrase naming only this place. Failing
    all three, lead sentences are dropped and the plain sentences quoted, so a
    summary never opens with another place's (or another level's) advisory."""
    if not desc:
        return ""
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", desc)
    # Markup boundaries that are sentence breaks (\x01), handled before tags go:
    #  * the bold-italic change note ("...Advisory summary was updated</i>") has
    #    no full stop, so it ran into the next sentence and the bookkeeping
    #    filter dropped both. Its text stays (Vietnam's lead is inside it);
    #  * headings, as their own bold paragraph ("<p><b>Crime</b></p>", possibly
    #    in a <span>) or run into the text ("<b>Crime<br></b>Violent crime..."),
    #    read as "Crime Violent crime..." once tags were stripped. Dropped.
    text = re.sub(r"<p>\s*<b>\s*<i>(.*?)</i>\s*</b>\s*</p>", " \\1 \x01 ", text, flags=re.I | re.S)
    # (A bold "Do not travel to Belarus due to:" is the lead, not a heading.)
    heading = (lambda m: m.group(0) if re.search(r"[.!?]\s*$", m.group(1)) or re.match(
        r"\s*(exercise|reconsider|do not travel)\b", m.group(1), re.I) else " \x01 ")
    text = re.sub(r"<p>\s*(?:<span[^>]*>\s*)?<b>([^<]{1,80})</b>(?:\s|&nbsp;)*(?:</span>\s*)?</p>",
                  heading, text, flags=re.I)
    text = re.sub(r"<b>\s*([^<]{1,60}?)<br\s*/?>\s*</b>", heading, text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    # "Read the entire Travel Advisory." is boilerplate in most items;
    # "Advisory summary:" is a section heading that survives tag-stripping (its
    # colon used to survive too: "...due to terrorism. : Terrorist groups...");
    # "Summary not available" is the feed's placeholder, glued onto the lead
    # ("Exercise normal precautionSummary not available").
    text = re.sub(r"\s*Read the entire Travel Advisory\.?", "", text, flags=re.I)
    text = re.sub(r"\bAdvisory summary\b\s*:?", "", text, flags=re.I)
    text = re.sub(r"\s*Summary not available\.?", " \x01 ", text, flags=re.I)
    # Shield abbreviations the sentence splitter would break on ("...travel to
    # Japan, U.S. government employees...").
    text = text.replace("U.S.", "U\x00S\x00")
    parts = [re.sub(r"^[\s:;,.]+", "", p.replace("U\x00S\x00", "U.S."))
             for p in re.split(r"(?<=[.!?])\s+|\s*\x01\s*", text)]
    # Drop the bookkeeping sentences ("Reissued after periodic review...",
    # "An area of increased risk was added.") — they describe the document,
    # not the country — and the read-more boilerplate.
    BOILER = re.compile(r"reissued|periodic review|advisory level was|no changes to the risk"
                        r"|risk indicators|updated? to reflect|was (added|updated|removed)"
                        r"|country information page|travel guidance for"
                        r"|always exercise caution when traveling"
                        r"|smart traveler enrollment|general tips to stay safe", re.I)
    keep = [p.strip() for p in parts if p.strip() and not BOILER.search(p)]
    LEAD = re.compile(r"^(exercise|reconsider|do not travel)", re.I)
    # Headings glued onto the sentence that repeats them: "Level 3: Reconsider
    # Travel to Macau SAR Reconsider travel to Macau SAR due to..." / "Summary: ..."
    for i, p in enumerate(keep):
        p = re.sub(r"^(level \d:\s*|(advisory )?su+m+ary:?\s*)", "", p, flags=re.I)
        hits = list(re.finditer(r"\b(exercise|reconsider|do not travel)\b", p, re.I))
        if len(hits) >= 2 and hits[0].start() == 0 and "due to" not in p[:hits[1].start()].lower():
            p = p[hits[1].start():]
        keep[i] = p
    if level in LEVEL_LEAD and name_iso is not None:
        own_lvl = re.compile("^" + LEVEL_LEAD[level], re.I)
        tags = [(bool(LEAD.match(p)), bool(own_lvl.match(p))) + _names(p, iso, name_iso)
                for p in keep]
        pick = next((i for i, t in enumerate(tags) if t[1] and t[2] and not t[3]), None)
        if pick is None:
            pick = next((i for i, t in enumerate(tags) if t[1] and not t[3]), None)
        if pick is None:
            pick = next((i for i, t in enumerate(tags) if t[0] and t[2] and not t[3]), None)
        if pick is not None:
            keep = keep[pick:]
        else:
            keep = [p for p, t in zip(keep, tags) if not t[0]]
    else:
        # Anchor on the canonical lead ("Exercise increased caution in X due
        # to...", "Reconsider travel to X...") — everything before it is noise.
        for i, p in enumerate(keep):
            if LEAD.match(p):
                keep = keep[i:]
                break
    # Some items open with the bare level phrase as a heading fragment
    # ("Exercise increased caution") glued to the real sentence that repeats
    # it — drop the fragment when the next sentence starts the same way.
    if len(keep) >= 2 and LEAD.match(keep[1]) and len(keep[0]) < 40:
        keep = keep[1:]
    # A "normal precautions" advisory has said everything in sentence one —
    # every sentence after it is program plugs and generic tips, and padding a
    # Level 1 country's summary with them made safe places read scary.
    take = keep[:1] if keep and re.match(r"exercise normal precautions", keep[0], re.I) else keep[:2]
    out = re.sub(r"\s+", " ", " ".join(take)).strip()
    out = re.sub(r"\s+([.,;])", r"\1", out)   # feed HTML leaves "Thailand ." artifacts
    if out and not LEAD.match(out) and len(out) < 40:
        return ""          # nothing informative survived; better silent than junk
    if re.fullmatch(r"(exercise normal precautions?|exercise increased caution|reconsider travel"
                    r"|do not travel)\.?", out, re.I):
        return ""          # a bare level phrase says no more than the level itself
    return (out[:277] + "...") if len(out) > 280 else out


def _change(desc):
    """'up' if the advisory level was raised (riskier), 'down' if lowered."""
    if not desc:
        return None
    text = re.sub(r"<[^>]+>", " ", desc)
    m = re.search(r"\b(increased|raised|decreased|lowered)\b[^.]{0,40}\bLevel\b"
                  r"|advisory level was (increased|raised|decreased|lowered)", text, re.I)
    if not m:
        return None
    word = (m.group(1) or m.group(2) or "").lower()
    return "up" if word in ("increased", "raised") else "down"


def _pubdate(raw):
    """'Fri, 10 Jul 2026' -> '2026-07-10' (empty on anything unparseable)."""
    m = re.search(r"\d{1,2} \w{3} \d{4}", raw or "")
    if not m:
        return ""
    try:
        import datetime
        return datetime.datetime.strptime(m.group(0), "%d %b %Y").date().isoformat()
    except ValueError:
        return ""


def _tag(block, tag):
    m = re.search(r"<{0}>(.*?)</{0}>".format(tag), block, re.S)
    if not m:
        return ""
    val = m.group(1)
    cdata = re.match(r"\s*<!\[CDATA\[(.*?)\]\]>\s*$", val, re.S)
    return (cdata.group(1) if cdata else val).strip()


def _fetch_text(url, retries=3):
    """GET text with the same retry/backoff as rates.fetch_json. This was the one
    unretried fetch in the monthly digest, so a single travel.state.gov blip
    lost the month's issue."""
    import time
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 fx-tracker/1.0"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=rates.TIMEOUT, context=rates._SSL) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last = e
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500:
                raise
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last

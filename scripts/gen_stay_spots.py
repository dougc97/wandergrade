#!/usr/bin/env python3
"""Build public/stay-coords.json: ISO -> up to 5 stay-search anchor spots
(name + lat/lng) for the Travel Guide's "Where to stay" chips.

Spots mirror the page's own recommendations: the places named in "top things
to do" come first (all comma-separated places in a label's parenthetical,
e.g. "Tea country & trains (Ella, Kandy)" -> Ella AND Kandy), then curated
gallery places fill any remaining room. Coordinates via Wikipedia, with the
same disambiguation fallbacks the photo pipeline uses ("Ella, Sri Lanka" /
"Ella (Sri Lanka)").

Every coordinate must land in the country itself (see in_country): nothing
checked that, so "Granada" resolved to Spain and Nicaragua's default
Booking.com link searched hotels in Andalusia. A coordinate given only to
whole degrees is a region's rough centre, and near a border it can be across
it: Wikipedia's Fann Mountains (39, 68) is in Uzbekistan.

Every spot is its own point (see placeholder): Wikipedia's "Maracas Bay"
carries the coordinates of the whole island of Trinidad, so its chip searched
the same hotels as the "Trinidad" chip beside it.

Distinct destinations first (see pick): a place within DUP_KM of a chip is
that chip's neighbourhood (Nyhavn by Copenhagen, Gamla stan by Stockholm) and
keeps a slot only while nothing distinct can have it, and a landmark across
town (within FAR_KM) comes after both. Dropping every neighbourhood outright
left Singapore with Marina Bay and Sentosa alone and swapped Budapest's
Parliament for Heroes' Square, another Budapest landmark 3.2 km off; filling
slots in plain guide order spent North Korea's last one on Pyongyang's Arch
of Triumph while Mount Kumgang waited further down the gallery.

Every guide place that finds no point is printed with its country (a
rebuild said nothing when Sweden's Visby fell off the coarse map): give a
real place one in stay-aliases.json, and leave a phrase that names none
("Desert safari").

No spot inside a zone Canada says to avoid all travel to, nor inside a place
or distance the US State Department names under "Do not travel" (see SKIP_PATH): Benin's
chips offered Pendjari National Park, which Canada's advisory names. A
skipped place is kept out under its other names and on its ground (a label
within SKIP_KM of its point), and a US advisory that keeps its list off the
feed (Mexico's states) is reviewed by hand and re-flagged when reissued.

Run from the repo root with /usr/bin/python3; re-run when activities or
galleries change:
  /usr/bin/python3 scripts/gen_stay_spots.py            # every country (rewrites the file)
  /usr/bin/python3 scripts/gen_stay_spots.py NI SL      # just these; merged into the file
  /usr/bin/python3 scripts/gen_stay_spots.py --prune    # drop skip-listed spots, fetch nothing
  /usr/bin/python3 scripts/gen_stay_spots.py --check    # validate the file (its neighbourhood chips against
                                                        # a rebuild) + Canada's and the US's live words
  /usr/bin/python3 scripts/gen_stay_spots.py --check --dir <feed copy> --us <rss copy>   # from local copies
"""

import contextlib
import hashlib
import html
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
MAX_SPOTS = 5
sys.path.insert(0, ROOT)
from fxtracker import geo  # noqa: E402
import gallery_entry  # noqa: E402

# The world map is coarse (Natural Earth 110m): Iguazú, Everest and Victoria
# Falls all fall a few km inside the neighbour. Within NEAR_KM of the country's
# own outline counts as in it; beyond that, inside another country is a
# namesake abroad; and a spot at sea may sit up to MAX_OFFSHORE_KM out
# (nearshore islands and reefs the map leaves out).
NEAR_KM = 25
MAX_OFFSHORE_KM = 80
# Parts the simplified map leaves out or draws far from the mainland, as
# (min_lat, min_lon, max_lat, max_lon).
EXTRA_AREAS = {
    "BS": [(20.9, -80.5, 27.3, -72.7)],                                # the whole archipelago
    "CL": [(-27.25, -109.5, -27.0, -109.2)],                           # Easter Island
    "EC": [(-1.5, -92.1, 0.7, -89.2)],                                 # Galápagos
    "EH": [(20.7, -17.2, 27.7, -8.6)],                                 # Western Sahara coast
    "ES": [(38.6, 1.1, 40.1, 4.4), (27.6, -18.2, 29.5, -13.3)],       # Balearics, Canaries
    "GQ": [(3.1, 8.3, 3.9, 9.0)],                                      # Bioko (Malabo)
    "GR": [(34.8, 23.0, 38.0, 28.3)],                                  # Cyclades, Dodecanese
    "NC": [(-23.0, 163.5, -19.5, 169.0)],                              # Loyalty Is., Isle of Pines
    "SB": [(-12.5, 155.3, -6.5, 170.3)],
    "SE": [(56.85, 17.9, 58.45, 19.4)],                                # Gotland (Visby, 100 km out)
    "SO": [(8.0, 42.6, 11.5, 49.1)],                                   # Somaliland (its own map feature)
    "TF": [(-46.6, 50.0, -46.0, 52.5), (-39.0, 77.3, -37.6, 77.8)],   # Crozet, Amsterdam/St-Paul
    "VE": [(11.7, -67.0, 12.0, -66.5)],                                # Los Roques
    "VU": [(-20.3, 166.4, -13.0, 170.3)],
    "YE": [(12.0, 52.0, 12.8, 54.6)],                                  # Socotra
}

# Two spots closer than DUP_KM search the same hotels (San Blas / Guna Yala,
# Nyhavn by Copenhagen); a spot within CENTROID_KM of the map's centre of its
# country is the country, not a place in it.
DUP_KM = 3
CENTROID_KM = 0.5
# A spot at least FAR_KM from every chip is a destination of its own; nearer,
# it is the same city's spread. The guides' places across town sit 3-8 km
# from their city's chip (the Heydar Aliyev Center 3.7 km from Baku's,
# Sentosa 5 km from Marina Bay, Hongdae 5.9 km from Seoul, Katara 8.2 km
# from Doha): 10 km clears the widest of them, while a beach strip 11 km out
# (Burj Al Arab's Jumeirah from Downtown Dubai) or a day trip 19-38 km away
# (Barzan Towers from Doha, Frederiksborg, the Stockholm Archipelago) has a
# Booking search of other hotels.
FAR_KM = 10
# Gallery places only top up thin lists (to 4), never crowd the itinerary.
GALLERY_SPOTS = 4

_GEOMS = None
_CENTROIDS = None


def _geoms():
    global _GEOMS
    if _GEOMS is None:
        _GEOMS = {}
        for f in geo.load_world()["features"]:
            iso = f["properties"].get("iso")
            if iso and iso != "-99":
                _GEOMS.setdefault(iso, []).append(f["geometry"])
    return _GEOMS


def _centroids():
    """{iso: [lon, lat]}: the centre app.js puts each country's map pin on."""
    global _CENTROIDS
    if _CENTROIDS is None:
        _CENTROIDS = geo.country_centroids()
    return _CENTROIDS


def _decimals(x):
    s = repr(round(float(x), 6))
    s = s.rstrip("0").rstrip(".") if "." in s else s
    return len(s.split(".")[1]) if "." in s else 0


def _km_to(pt, geometry):
    """Distance (km) from pt (lon, lat) to the nearest edge of a geometry."""
    k = math.cos(math.radians(pt[1]))
    best = float("inf")
    for poly in geo.polygons(geometry):
        for ring in poly:
            for a, b in zip(ring, ring[1:]):
                ax, ay = (a[0] - pt[0]) * k, a[1] - pt[1]
                bx, by = (b[0] - pt[0]) * k, b[1] - pt[1]
                dx, dy = bx - ax, by - ay
                ln = dx * dx + dy * dy
                t = 0 if not ln else max(0.0, min(1.0, -(ax * dx + ay * dy) / ln))
                best = min(best, math.hypot(ax + t * dx, ay + t * dy) * 111.2)
    return best


def rough(ll):
    """True when [lat, lng] is given to whole degrees: Wikipedia's rough
    centre of a range or a region, good only to ~55 km."""
    return min(_decimals(x) for x in ll) == 0


def near_neighbour(ll, iso):
    """The other country within NEAR_KM of a rough [lat, lng], or None. The
    coarse map can't tell sides that close to a border, and a whole-degree
    point doesn't say which side its place is on: the Fann Mountains' (39, 68)
    is 4 km inside Tajikistan on the map and in Uzbekistan on the ground."""
    if not rough(ll):
        return None
    pt = (ll[1], ll[0])
    for other, geoms in sorted(_geoms().items()):
        if other != iso and min(_km_to(pt, x) for x in geoms) < NEAR_KM:
            return other
    return None


def in_country(ll, iso, curated=False):
    """True when [lat, lng] is plausibly in `iso` (see NEAR_KM above). A
    curated point (stay-aliases.json "ll") is trusted however round it is."""
    if any(a <= ll[0] <= c and b <= ll[1] <= d for a, b, c, d in EXTRA_AREAS.get(iso, [])):
        return True
    g = _geoms()
    own = g.get(iso)
    if not own:
        return True                  # no geometry to judge by (tiny territories)
    if not curated and near_neighbour(ll, iso):
        return False
    pt = (ll[1], ll[0])
    if any(geo.in_geometry(pt, x) for x in own):
        return True
    km = min(_km_to(pt, x) for x in own)
    if km <= NEAR_KM:
        return True
    if any(other != iso and any(geo.in_geometry(pt, x) for x in geoms)
           for other, geoms in g.items()):
        return False
    return km <= MAX_OFFSHORE_KM


class LookupFailed(Exception):
    """Wikipedia didn't answer (rate limit, network) — not the same as "no
    coordinates", and must not silently drop a country's spots."""


# Every title asked this run, with its point or None: a country's places are
# asked together, up to WIKI_BATCH titles a request (prefetch), as every
# place is now looked at, not just the first five. Wikipedia answers HTTP 429
# to a few hundred single-title requests a minute.
_COORDS = {}
WIKI_BATCH = 50


def _wiki(titles):
    """{title: [lat, lng] or None} for up to WIKI_BATCH titles, one request.
    A title is followed through Wikipedia's normalisation and redirects to
    its page ("Paektu Mountain" is Mount Paektu's)."""
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
           "&prop=coordinates&colimit=max&redirects=1&titles=" + urllib.parse.quote("|".join(titles)))
    req = urllib.request.Request(
        api, headers={"User-Agent": "wandergrade-spots/1.0 (+https://wandergrade.com)"})
    for attempt in range(4):
        try:
            j = json.load(urllib.request.urlopen(req, timeout=20))
            break
        except Exception as e:
            if attempt == 3:
                raise LookupFailed(titles[0] if len(titles) == 1 else "%d titles from %s" % (len(titles), titles[0]))
            wait = 2 * (attempt + 1)
            if getattr(e, "code", None) == 429:          # rate limited: its own pause, not ours
                try:
                    wait = max(wait, min(60, int(e.headers.get("Retry-After") or 0)), 15 * (attempt + 1))
                except (TypeError, ValueError):
                    wait = 15 * (attempt + 1)
            time.sleep(wait)
    q = j.get("query", {})
    hop = {n["from"]: n["to"] for n in q.get("normalized", []) + q.get("redirects", [])}
    pages = {p.get("title"): p for p in q.get("pages", {}).values()}
    out = {}
    for t in titles:
        x = t
        for _ in range(4):
            if x not in hop:
                break
            x = hop[x]
        c = (pages.get(x) or {}).get("coordinates")
        out[t] = [round(c[0]["lat"], 5), round(c[0]["lon"], 5)] if c else None
    return out


def prefetch(titles):
    """Ask Wikipedia for every title not asked yet, WIKI_BATCH at a time."""
    todo = list(dict.fromkeys(t for t in titles if t and t not in _COORDS and "|" not in t))
    for i in range(0, len(todo), WIKI_BATCH):
        _COORDS.update(_wiki(todo[i:i + WIKI_BATCH]))


def coords(subject):
    if subject not in _COORDS:
        _COORDS.update(_wiki([subject]))
    return _COORDS[subject]


def coords_with_fallback(subject, country, iso):
    """First title whose coordinates are in the country. The bare title stays
    first (a qualified one can land on a region article: "Sylhet, Bangladesh"
    is the division, not the city), but a better-known namesake abroad
    (Granada, Antigua, Casco Viejo) now fails in_country and falls through."""
    for title in variants(subject, country):
        ll = coords(title)
        if ll and in_country(ll, iso):
            return ll
    return None


def variants(subject, country):
    """The titles coords_with_fallback tries, in its order."""
    return (subject, "%s, %s" % (subject, country), "%s (%s)" % (subject, country))


def why_unresolved(subject, country, iso):
    """Why coords_with_fallback found no point for `subject`, from what this
    run already asked (it asks nothing itself)."""
    for title in variants(subject, country):
        ll = _COORDS.get(title)
        if ll:
            other = near_neighbour(ll, iso)
            return ("Wikipedia's %s is a whole-degree point within %d km of %s" % (ll, NEAR_KM, other) if other
                    else "Wikipedia's %s is outside %s on the map" % (ll, country))
    return "no coordinates on Wikipedia"


def expand(s):
    """Wikipedia titles spell these out ('Iona NP' -> 'Iona National Park')."""
    return re.sub(r"\bNP\b", "National Park", re.sub(r"\bMt\b", "Mount", s))


def act_places(x):
    """Every place an activity names: all parenthetical entries, else the
    photo-subject override, else the cleaned label."""
    label = x if isinstance(x, str) else x.get("t", "")
    m = re.search(r"\(([^)]*)\)", label)
    if m:
        return [expand(s.strip()) for s in m.group(1).split(",") if s.strip()]
    if isinstance(x, dict) and x.get("p"):
        return [x["p"]]
    clean = re.sub(r"\s*\([^)]*\)", "", label).strip()
    return [expand(clean)] if clean else []


def label(subject):
    return re.sub(r"\s*\(.*\)", "", subject.split(",")[0]).strip()


import difflib


def same_place(a, b):
    """'Kalandula'/'Kalandula Falls' (containment) and 'Masai Mara'/
    'Maasai Mara' (spelling variants) are the same stay anchor."""
    a, b = a.lower(), b.lower()
    return a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.92


try:
    ALIASES = json.load(open(os.path.join(ROOT, "scripts", "stay-aliases.json"), encoding="utf-8"))
except OSError:
    ALIASES = {}

# Canada's regional "Avoid all travel" blocks the spots were reviewed against,
# per country by heading: a fingerprint of Canada's words, and under "skip" the
# places inside that zone (with where they fall and the words that cover them).
# A skipped place never becomes a stay anchor: no booking link into a zone
# Canada says to stay out of, the rule app.js applies to a whole country at
# "do not travel". The page says nothing of its own about it; the guide's 📍
# line already quotes Canada. --check flags a block that is new, gone or
# reworded since the review; the review itself is by hand (a zone is words —
# a region, a border band, a park — not a shape).
# Under "us", the same for the State Department's regional "Do not travel"
# areas, where it names them (a region, a county, a 10 km band; "specific
# areas within" one names nothing): per country a fingerprint of the feed's
# "Do Not Travel to" words and the places inside an area they name. Tiya,
# clear of Canada's Ethiopian zones, is in the US's Oromia. A line that names
# no place or distance a point can be checked against is reviewed by hand and
# its "note" records the call, not a skip (Doug, 2026-10-19): Brazil's
# "International land borders" keeps Iguazú Falls, Benin's "border region in
# northern ... Benin" keeps Tanougou Falls. A whole country
# at the US's level 4 is app.js's rule (no stays for that source), not this.
# Where the feed says "some areas have increased risk" and names none
# (Mexico's states, India's Kashmir are only on travel.state.gov), the entry
# fingerprints the whole row and its "note" records the review by hand.
# A skipped place is matched by its name, its other names ("aka": Gonder for
# Gondar) and its point ("ll", where it has one): any candidate within
# SKIP_KM of that point is the same ground under another label (a gallery's
# "Gisenyi" is the skipped Lake Kivu chip).
SKIP_PATH = os.path.join(ROOT, "scripts", "stay-skip.json")
SKIP_KM = 5
try:
    SKIP = json.load(open(SKIP_PATH, encoding="utf-8"))
except OSError:
    SKIP = {}


def _fold(s):
    """'Limbé' and 'Limbe' are one place."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).casefold()


def _skip_lists(iso, skip=None):
    """Every "skip" dict for `iso`: one per Canada block, then the US's."""
    skip = skip or SKIP
    for block in ((skip.get("countries") or {}).get(iso) or {}).values():
        yield block.get("skip") or {}
    yield ((((skip.get("us") or {}).get("countries") or {}).get(iso) or {}).get("skip")) or {}


def skipped(iso, *names, skip=None):
    """The skip-listed place any of `names` is (same_place, with its "aka"
    names), or None."""
    for places in _skip_lists(iso, skip):
        for s, v in places.items():
            for alt in [s] + list((v or {}).get("aka") or []):
                if any(n and same_place(_fold(n), _fold(alt)) for n in names):
                    return s
    return None


def skipped_near(iso, ll, skip=None):
    """The skip-listed place whose point is within SKIP_KM of `ll`, or None:
    the same ground under a name the list doesn't hold (Gisenyi, the Lake
    Kivu chip's town)."""
    if not ll:
        return None
    pt = (ll[1], ll[0])
    for places in _skip_lists(iso, skip):
        for s, v in places.items():
            p = (v or {}).get("ll")
            if p and geo.dist_km(pt, (p[1], p[0])) < SKIP_KM:
                return s
    return None


def skip_hit(iso, spot, skip=None):
    """The skip-listed place a stay spot ({"n", "ll"}) is, by name or by
    point, or None."""
    return skipped(iso, spot["n"], skip=skip) or skipped_near(iso, spot.get("ll"), skip=skip)


def fingerprint(text):
    """Canada's words without their layout: the parser's bullets, spacing and
    punctuation can change while Canada's advice doesn't."""
    return hashlib.sha1(re.sub(r"[\W_]+", "", _fold(text)).encode("utf-8")).hexdigest()[:12]


def review_problems(iso, blocks, skip=None):
    """What changed in one country's avoid-all zones since the review.
    `blocks` are watchouts.from_feed's regional blocks for it."""
    have = {b.get("t"): fingerprint(b.get("text") or "") for b in blocks
            if b.get("call") == "Avoid all travel"}
    seen = ((skip or SKIP).get("countries") or {}).get(iso) or {}
    out = []
    for t, fp in have.items():
        if t not in seen:
            out.append("%s new avoid-all block, not reviewed: %s" % (iso, t))
        elif seen[t].get("fp") != fp:
            out.append("%s avoid-all block reworded since the review: %s" % (iso, t))
    for t, b in seen.items():
        if t not in have:
            out.append("%s avoid-all block gone from Canada's page%s: %s" % (
                iso, " (its skipped places may be fine now)" if b.get("skip") else "", t))
    return out


# The US feed (advisories.FEED, RSS) gives each country's advisory as one
# description. Its regional list opens "Do Not Travel to:" and runs to the
# next tier ("Reconsider travel to", "Exercise increased caution in") or to
# the staff rules and summary that follow it.
US_LEAD = re.compile(r"\bdo not travel (?:to|within|in)\b", re.I)
US_STOP = re.compile(r"\b(?:reconsider travel|exercise (?:increased|normal) caution|advisory summary"
                     r"|u\.s\. government employee|read the (?:entire|full))", re.I)


def us_text(desc):
    """An RSS description as plain text."""
    t = re.sub(r"<!\[CDATA\[|\]\]>", "", desc or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(t)))
    return re.sub(r"\s+", " ", t).strip()


def us_passage(text):
    """A US advisory's regional "Do not travel" words, or ""."""
    m = US_LEAD.search(text or "")
    if not m:
        return ""
    rest = text[m.start():]
    stop = US_STOP.search(rest, 1)
    return (rest[:stop.start()] if stop else rest).strip()


# A row that says "some areas have increased risk" may name them in the feed
# (Brazil's "Do Not Travel to : International land borders", Tanzania's
# "Reconsider travel to the border ... in the Mtwara Region") or not at all:
# Mexico's row ends "Check the maps of restricted areas" and India's names no
# area, while both advisories list "Do not travel" states on travel.state.gov.
# Such a row is reviewed by hand there (the site refuses scripted reads); its
# words are US_UNLISTED + the whole row, so any reissue asks for it again.
US_SOME = re.compile(r"\bsome areas have increased risks?\b", re.I)
US_TIER = re.compile(r"\b(?:do not travel|reconsider travel|exercise (?:increased caution|normal precaution))", re.I)
US_UNLISTED = "No list in the feed (review on travel.state.gov): "
# Feed titles the site's name map misses (advisories._norm drops the curly
# apostrophe of "Côte d’Ivoire", so it is straightened first).
US_NAMES = {"republic of congo": "CG"}


def us_unlisted(text):
    """True when a US row says some areas have increased risk but names none
    at any tier: its only tier words are its own lead sentence's."""
    return bool(US_SOME.search(text or "")) and not us_passage(text) and len(US_TIER.findall(text)) <= 1


def us_words(text):
    """What --check reviews in one US row: its regional "Do not travel"
    words; for a row that names its risky areas only on travel.state.gov,
    US_UNLISTED + the row; else ""."""
    return us_passage(text) or (US_UNLISTED + text if us_unlisted(text) else "")


def us_items(raw):
    """(title's country, iso or None, level, plain text) for every row of
    the US feed's XML."""
    from fxtracker import advisories
    name_iso = advisories._name_to_iso()
    out = []
    for block in re.findall(r"<item>(.*?)</item>", raw or "", re.S):
        m = re.match(r"(.+?)\s*[-–]\s*Level\s*(\d)", html.unescape(advisories._tag(block, "title")))
        if not m:
            continue
        key = advisories._norm(re.sub(r"[\u2018\u2019]", "'", m.group(1)))
        out.append((m.group(1), name_iso.get(key) or US_NAMES.get(key), int(m.group(2)),
                    us_text(advisories._tag(block, "description"))))
    return out


def us_passages(raw):
    """{iso: what --check reviews (us_words)} from the US feed's XML, for
    countries below level 4 (at 4 the whole country is "do not travel", which
    app.js already answers with no stays). A country the feed lists twice
    gets both rows' words, in a fixed order."""
    found = {}
    for name, iso, level, text in us_items(raw):
        words = us_words(text)
        if iso and level < 4 and words:
            found.setdefault(iso, set()).add(words)
    return {iso: " | ".join(sorted(w)) for iso, w in found.items()}


def us_unmapped(raw):
    """Feed rows below level 4 with words to review but no ISO for their
    title: reported, never silently dropped."""
    return sorted(name for name, iso, level, text in us_items(raw) if not iso and level < 4 and us_words(text))


def us_review_problems(iso, words, skip=None):
    """What changed in one country's US "Do not travel" words since the
    review: `words` as us_passages gives them ("" for none)."""
    seen = (((skip or SKIP).get("us") or {}).get("countries") or {}).get(iso)
    unlisted = words.startswith(US_UNLISTED)
    if words and not seen:
        if unlisted:
            return ["%s US advisory says some areas have increased risk but the feed names none, not reviewed:"
                    " read its \"Do not travel\" areas on travel.state.gov" % iso]
        return ["%s new US \"Do not travel\" areas, not reviewed: %s" % (iso, words[:160])]
    if words and seen.get("fp") != fingerprint(words):
        if unlisted:
            return ["%s US advisory reissued or reworded since the review (its areas are only on"
                    " travel.state.gov): read them again" % iso]
        return ["%s US \"Do not travel\" areas reworded since the review: %s" % (iso, words[:160])]
    if not words and seen:
        return ["%s US \"Do not travel\" areas gone from the feed, or the country is now level 4%s"
                % (iso, " (its skipped places may be fine now)" if seen.get("skip") else "")]
    return []


def build_country(args):
    """(iso, spots), or (iso, None) when Wikipedia couldn't be reached. The
    country's titles are asked in batches first (prefetch_country)."""
    try:
        prefetch_country(*args)
        return _build_country(args)
    except LookupFailed as e:
        print("\n%s: lookup failed at %r — keeping its previous spots" % (args[0], str(e)))
        return args[0], None


def _subjects(iso, act):
    """(subject, cap, alias, chip name) for every place the guide names, in
    its order: "top things to do" first (up to MAX_SPOTS), then the gallery
    (topping up to GALLERY_SPOTS). A pinned Commons file's place is its
    label; a label that isn't a Wikipedia title finds no coordinates."""
    aliases = ALIASES.get(iso, {})
    subjects = [(p, MAX_SPOTS) for x in (act.get("activities") or []) for p in act_places(x)]
    subjects += [(gallery_entry.label(e), GALLERY_SPOTS) for e in act.get("gallery") or []]
    for subject, cap in subjects:
        # curated alias: phrase -> real Wikipedia title (+ optional chip label,
        # + optional fixed "ll" for places Wikipedia has no coordinates for)
        al = aliases.get(subject) or aliases.get(label(subject)) or {}
        yield subject, cap, al, al.get("label") or label(al.get("title") or subject)


def prefetch_country(iso, act, names):
    """Ask Wikipedia for a country's titles together: every bare title, then
    "X, Country" for those without a point in the country, then "X (Country)"."""
    country = names.get(iso, iso)
    titles = [al.get("title") or s for s, cap, al, name in _subjects(iso, act) if name and not al.get("ll")]
    for k in range(3):
        need = [t for t in titles if not any(_COORDS.get(v) and in_country(_COORDS[v], iso)
                                             for v in variants(t, country)[:k])]
        prefetch([variants(t, country)[k] for t in need])


# Every guide place a build found no point for, per country: [(place, why)].
UNRESOLVED = {}


def candidates(iso, act, names):
    """The guide's places as stay candidates, in its order: [{"n", "ll",
    "cap"}], each a point in the country and clear of the skip list. A place
    with no point goes to UNRESOLVED[iso], printed by main()."""
    country = names.get(iso, iso)
    out, unresolved = [], []
    for subject, cap, al, name in _subjects(iso, act):
        if not name or skipped(iso, name, subject, al.get("title")):
            continue
        title = al.get("title") or subject
        ll = al.get("ll") or coords_with_fallback(title, country, iso)
        if not ll:
            if subject not in [u for u, why in unresolved]:
                unresolved.append((subject, why_unresolved(title, country, iso)))
            continue
        near = skipped_near(iso, ll)
        if near:
            print("\n%s: %s %s left out — within %d km of skip-listed %s" % (iso, name, ll, SKIP_KM, near), end="")
            continue
        out.append({"n": name, "ll": ll, "cap": cap, "cur": bool(al.get("ll"))})
    UNRESOLVED[iso] = unresolved
    return out


def _build_country(args):
    iso, act, names = args
    return iso, pick(iso, candidates(iso, act, names))


def _tier(ll, spots):
    """0 for a destination of its own (FAR_KM or more from every spot), 1 for
    a spot's neighbourhood (within DUP_KM of one), 2 for a place across town
    (between the two)."""
    pt = (ll[1], ll[0])
    d = min((geo.dist_km(pt, (s["ll"][1], s["ll"][0])) for s in spots), default=float("inf"))
    return 0 if d >= FAR_KM else 1 if d < DUP_KM else 2


def pick(iso, cands):
    """The chips from `cands` (candidates' order and caps), in the guide's
    order. Slots go to destinations of their own first, in the guide's order;
    then to neighbourhoods; then to places across town.

    A neighbourhood (within DUP_KM of a chip) loses its slot only to a
    distinct destination: Sweden's Gamla stan and Vasa Museum give theirs to
    the Stockholm Archipelago and Visby; Singapore's Clarke Quay and Gardens
    by the Bay keep theirs, as nothing there is FAR_KM from Marina Bay (an
    empty slot helps no one). A place across town never takes a neighbourhood's
    slot: Budapest's Parliament stays and Heroes' Square, gallery place #1 but
    3.2 km off, doesn't swap in; Baku keeps Flame Towers over the Heydar
    Aliyev Center. It fills a slot nothing else wants (Sentosa, 5 km from
    Marina Bay, takes Singapore's last). The same point, the same place by
    name or the country's centre (see placeholder) is never a chip."""
    chosen, out = {}, set()
    for tier in (0, 1, 2):
        for i, c in enumerate(cands):
            if i in chosen or i in out or len(chosen) >= c["cap"]:
                continue
            spots = list(chosen.values())
            why = placeholder(iso, c["n"], c["ll"], spots, near=False, curated=c.get("cur", False))
            if why:
                # Two names for one place (San Blas / Guna Yala) are one chip.
                # The very same point is that, or a borrowed one (Maracas
                # Bay's was Trinidad's): said, so a place that lost its chip
                # can get its own point in stay-aliases.json. A name the
                # guide repeats ("Dubai" three times) goes quietly; one
                # inside another FAR_KM off (Dubai Marina, 19 km from Dubai's
                # chip) is said, as it may be a place of its own.
                out.add(i)
                twin = next((s for s in spots if same_place(c["n"], s["n"])), None)
                km = twin and geo.dist_km((c["ll"][1], c["ll"][0]), (twin["ll"][1], twin["ll"][0]))
                if twin is None:
                    print("\n%s: %s %s left out — %s" % (iso, c["n"], c["ll"], why), end="")
                elif km >= FAR_KM:
                    print("\n%s: %s %s left out — the same place as %s by name, %.0f km off (if it's a place"
                          " of its own, give it a point in stay-aliases.json)" % (iso, c["n"], c["ll"], twin["n"], km), end="")
                continue
            if _tier(c["ll"], spots) <= tier:
                chosen[i] = {"n": c["n"], "ll": c["ll"]}
    return [chosen[i] for i in sorted(chosen)]


def placeholder(iso, name, ll, spots, near=True, curated=False):
    """Why `ll` isn't a point of its own beside `spots` (the country's spots
    so far), or None: the same point as one of them (Maracas Bay borrowing
    Trinidad's), the same place by name, the centre of the country itself,
    or (with `near`) within DUP_KM of one, a neighbourhood that pick keeps
    only while nothing distinct can have its slot.

    A name inside another (Kalandula / Kalandula Falls) is one place, unless
    the point is `curated` (set by hand in stay-aliases.json) and FAR_KM from
    the other's: the Stockholm Archipelago's, 38 km out, isn't Stockholm's,
    and the name rule alone kept Sweden's from ever being a chip."""
    pt = (ll[1], ll[0])
    for s in spots:
        if [round(x, 4) for x in s["ll"]] == [round(x, 4) for x in ll]:
            return "same point as %s" % s["n"]
    for s in spots:
        if same_place(name, s["n"]) and not (curated and geo.dist_km(pt, (s["ll"][1], s["ll"][0])) >= FAR_KM):
            return "same place as %s" % s["n"]
    c = _centroids().get(iso)
    if c and geo.dist_km(pt, tuple(c)) < CENTROID_KM:
        return "the centre of the country, not a place in it"
    for s in spots if near else []:
        if geo.dist_km(pt, (s["ll"][1], s["ll"][0])) < DUP_KM:
            return "within %d km of %s" % (DUP_KM, s["n"])
    return None


def _curated(iso, ll):
    """True when `ll` is a stay-aliases.json point for `iso` (set by hand)."""
    return any(a.get("ll") and [round(x, 5) for x in a["ll"]] == [round(x, 5) for x in ll]
               for a in (ALIASES.get(iso) or {}).values())


def check(data):
    """Every anchor that isn't a sound point of its own country, as
    (iso, name, ll, why): outside it (or a rough centre near a border), or a
    placeholder beside an earlier spot (see placeholder)."""
    out = []
    for iso, spots in sorted(data.items()):
        for i, s in enumerate(spots):
            cur = _curated(iso, s["ll"])
            if not in_country(s["ll"], iso, curated=cur):
                other = None if cur else near_neighbour(s["ll"], iso)
                out.append((iso, s["n"], s["ll"], "a whole-degree point within %d km of %s" % (NEAR_KM, other)
                            if other else "outside its country"))
                continue
            why = placeholder(iso, s["n"], s["ll"], spots[:i], curated=cur)
            if why:
                out.append((iso, s["n"], s["ll"], why))
    return out


def fresh_build(iso):
    """`iso`'s spots as a rebuild would pick them now (Wikipedia asked; None
    when it can't be reached), without touching the file."""
    acts = _json_once("activities.json")
    if iso not in acts:
        return []
    with contextlib.redirect_stdout(io.StringIO()):       # its "left out" lines are a build's, not --check's
        return build_country((iso, acts[iso], _json_once("country-names.json")))[1]


_LOADED = {}


def _json_once(name):
    if name not in _LOADED:
        with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
            _LOADED[name] = json.load(f)
    return _LOADED[name]


def near_notes(rows, build=fresh_build):
    """The rows of check() within DUP_KM of an earlier anchor that a rebuild
    of their country would drop, as (iso, name, ll, why). One the rule keeps
    (a neighbourhood with nothing distinct to take its slot: Singapore's
    Clarke Quay) is no note. `build(iso)` gives the spots a rebuild would
    pick, or None when it can't tell."""
    near = [r for r in rows if r[3].startswith("within")]
    out = []
    for iso in sorted({r[0] for r in near}):
        fresh = build(iso)
        names = None if fresh is None else {s["n"] for s in fresh}
        for r in near:
            if r[0] != iso:
                continue
            if names is None:
                out.append(r[:3] + (r[3] + " (not judged: Wikipedia unreachable)",))
            elif r[1] not in names:
                out.append(r[:3] + (r[3] + "; a rebuild drops it",))
    return out


def skipped_present(data, skip=None):
    """Every anchor that is a skip-listed place, by name or by point:
    (iso, spot, skip-list name)."""
    return [(iso, s["n"], hit) for iso, spots in sorted(data.items()) for s in spots
            for hit in [skip_hit(iso, s, skip=skip)] if hit]


def prune(data, skip=None):
    """`data` without its skip-listed anchors; a country left with none drops
    out, as main() leaves out one that found none (the stays block hides)."""
    out = {}
    for iso, spots in data.items():
        keep = [s for s in spots if not skip_hit(iso, s, skip=skip)]
        if keep:
            out[iso] = keep
    return out


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def canada_review(data, mirror=None):
    """review_problems for every country with spots, from Canada's live feed
    or a local copy of it (<mirror>/<iso>.json, as fetched)."""
    from fxtracker import rates, watchouts

    def one(iso):
        if mirror:
            p = os.path.join(mirror, iso.lower() + ".json")
            if not os.path.exists(p):
                return review_problems(iso, [])
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        else:
            try:
                raw = rates.fetch_json(watchouts.API.format(iso=iso.lower()))
            except Exception as e:
                if getattr(e, "code", None) in (404, 410):    # no Canada page
                    return review_problems(iso, [])
                return ["%s Canada's page unreadable (%s): nothing checked" % (iso, e)]
        return review_problems(iso, watchouts.from_feed(iso, raw)["regional"])

    isos = sorted(k for k in data if re.fullmatch(r"[A-Z]{2}", k))
    with ThreadPoolExecutor(max_workers=8) as ex:
        return [line for lines in ex.map(one, isos) for line in lines]


def us_review(data, rss=None):
    """us_review_problems for every country with spots or a reviewed entry,
    from the US feed or a local copy of it (the RSS XML, as fetched)."""
    from fxtracker import advisories
    try:
        if rss:
            with open(rss, encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = advisories._fetch_text(advisories.FEED)
    except Exception as e:
        return ["US feed unreadable (%s): nothing checked" % e]
    words = us_passages(raw)
    if not words:
        return ["US feed has no \"Do not travel\" areas at all (format changed?): nothing checked"]
    seen = ((SKIP.get("us") or {}).get("countries") or {})
    isos = sorted(set(k for k in data if re.fullmatch(r"[A-Z]{2}", k)) | set(seen))
    return (["US feed row with areas to review matches no country (add it to US_NAMES): %s" % n
             for n in us_unmapped(raw)]
            + [line for iso in isos for line in us_review_problems(iso, words.get(iso, ""))])


def main(only=None):
    acts = json.load(open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(PUBLIC, "country-names.json"), encoding="utf-8"))
    path = os.path.join(PUBLIC, "stay-coords.json")
    out = {}
    if only:
        missing = sorted(set(only) - set(acts))
        if missing:
            sys.exit("not in activities.json: " + " ".join(missing))
    try:
        previous = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if only:
        out = {k: v for k, v in previous.items() if k not in only}
    jobs = [(iso, acts[iso], names) for iso in sorted(acts) if not only or iso in only]
    rebuilt = set()
    with ThreadPoolExecutor(max_workers=2 if only else 8) as ex:
        for iso, spots in ex.map(build_country, jobs):
            if spots is None:
                spots = previous.get(iso) or []
            else:
                rebuilt.add(iso)
            if spots:
                out[iso] = spots
            print("%s:%d" % (iso, len(spots)), end=" ", flush=True)
    # A country kept from before (not rebuilt, or Wikipedia down) may still
    # hold a place skip-listed since.
    out = prune(out)
    save(path, out)
    counts = [len(v) for v in out.values()]
    print("\n%d/%d countries; avg %.1f spots; thin(<2): %s"
          % (len(out), len(acts), sum(counts) / len(counts),
             [k for k in acts if len(out.get(k, [])) < 2]))
    unresolved = [(iso, UNRESOLVED[iso]) for iso in sorted(UNRESOLVED) if iso in rebuilt and UNRESOLVED[iso]]
    if unresolved:
        print("GUIDE PLACES WITH NO POINT, NO CHIP (give a real place one in stay-aliases.json):")
        for iso, places in unresolved:
            print("  %s: %s" % (iso, "; ".join("%s (%s)" % p for p in places)))
    # A rebuilt country's neighbourhood chips are the rule's (pick); another
    # country's are judged by --check.
    rows = check(out)
    bad = [r for r in rows if not r[3].startswith("within")]
    if bad:
        print("NOT A SOUND POINT OF THEIR OWN (fix with stay-aliases.json, or rebuild the country):")
        for row in bad:
            print("  %s %s %s: %s" % row)
    for row in rows:
        if row not in bad and row[0] not in rebuilt:
            print("  (note) %s %s %s: %s (not rebuilt in this run; --check judges it)" % row)


if __name__ == "__main__":
    argv = sys.argv[1:]
    path = os.path.join(PUBLIC, "stay-coords.json")
    if argv == ["--prune"]:
        data = json.load(open(path, encoding="utf-8"))
        gone = skipped_present(data)
        save(path, prune(data))
        for row in gone:
            print("dropped %s %s (stay-skip.json: %s)" % row)
        print("%d anchor(s) dropped" % len(gone))
        sys.exit(0)
    if argv[:1] == ["--check"]:
        mirror = argv[argv.index("--dir") + 1] if "--dir" in argv[:-1] else None
        rss = argv[argv.index("--us") + 1] if "--us" in argv[:-1] else None
        data = json.load(open(path, encoding="utf-8"))
        rows = check(data)
        # An anchor within DUP_KM of an earlier one (Nyhavn by Copenhagen)
        # searches the same hotels. A rebuild keeps it while nothing distinct
        # can have its slot (pick): then it's a neighbourhood chip, no note.
        # One a rebuild would drop is listed, not failed: it's no wrong point.
        near = [r for r in rows if r[3].startswith("within")]
        bad = [r for r in rows if r not in near]
        for row in bad:
            print("%s %s %s: %s" % row)
        print("%d anchor(s) not a sound point of their own country" % len(bad))
        notes = near_notes(near)
        for row in notes:
            print("  (note) %s %s %s: %s" % row)
        print("%d anchor(s) within %d km of an earlier one that a rebuild drops (%d more kept by the rule:"
              " neighbourhoods with nothing distinct to take their slot)" % (len(notes), DUP_KM, len(near) - len(notes)))
        left = skipped_present(data)
        for row in left:
            print("%s %s is skip-listed as %s: run --prune" % row)
        print("%d skip-listed anchor(s) in the file" % len(left))
        stale = canada_review(data, mirror)
        for line in stale:
            print(line)
        print("%d Canada avoid-all block(s) to review against the spots (%s), then update %s"
              % (len(stale), mirror or "live feed", os.path.relpath(SKIP_PATH, ROOT)))
        us = us_review(data, rss)
        for line in us:
            print(line)
        print("%d US \"Do not travel\" list(s) to review against the spots (%s), then update %s"
              % (len(us), rss or "live feed", os.path.relpath(SKIP_PATH, ROOT)))
        sys.exit(1 if bad or left or stale or us else 0)
    main({a.upper() for a in argv} or None)

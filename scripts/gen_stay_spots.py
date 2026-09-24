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
Booking.com link searched hotels in Andalusia.

Run from the repo root with /usr/bin/python3; re-run when activities or
galleries change:
  /usr/bin/python3 scripts/gen_stay_spots.py            # every country (rewrites the file)
  /usr/bin/python3 scripts/gen_stay_spots.py NI SL      # just these; merged into the file
  /usr/bin/python3 scripts/gen_stay_spots.py --check    # validate the file, fetch nothing
"""

import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
MAX_SPOTS = 5
sys.path.insert(0, ROOT)
from fxtracker import geo  # noqa: E402

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
    "SO": [(8.0, 42.6, 11.5, 49.1)],                                   # Somaliland (its own map feature)
    "TF": [(-46.6, 50.0, -46.0, 52.5), (-39.0, 77.3, -37.6, 77.8)],   # Crozet, Amsterdam/St-Paul
    "VE": [(11.7, -67.0, 12.0, -66.5)],                                # Los Roques
    "VU": [(-20.3, 166.4, -13.0, 170.3)],
    "YE": [(12.0, 52.0, 12.8, 54.6)],                                  # Socotra
}

_GEOMS = None


def _geoms():
    global _GEOMS
    if _GEOMS is None:
        _GEOMS = {}
        for f in geo.load_world()["features"]:
            iso = f["properties"].get("iso")
            if iso and iso != "-99":
                _GEOMS.setdefault(iso, []).append(f["geometry"])
    return _GEOMS


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


def in_country(ll, iso):
    """True when [lat, lng] is plausibly in `iso` (see NEAR_KM above)."""
    if any(a <= ll[0] <= c and b <= ll[1] <= d for a, b, c, d in EXTRA_AREAS.get(iso, [])):
        return True
    g = _geoms()
    own = g.get(iso)
    if not own:
        return True                  # no geometry to judge by (tiny territories)
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


def coords(subject):
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
           "&prop=coordinates&redirects=1&titles=" + urllib.parse.quote(subject))
    req = urllib.request.Request(
        api, headers={"User-Agent": "wandergrade-spots/1.0 (+https://wandergrade.com)"})
    for attempt in range(4):
        try:
            j = json.load(urllib.request.urlopen(req, timeout=20))
            break
        except Exception:
            if attempt == 3:
                raise LookupFailed(subject)
            time.sleep(2 * (attempt + 1))
    page = next(iter(j.get("query", {}).get("pages", {}).values()), {})
    c = page.get("coordinates")
    if c:
        return [round(c[0]["lat"], 5), round(c[0]["lon"], 5)]
    return None


def coords_with_fallback(subject, country, iso):
    """First title whose coordinates are in the country. The bare title stays
    first (a qualified one can land on a region article: "Sylhet, Bangladesh"
    is the division, not the city), but a better-known namesake abroad
    (Granada, Antigua, Casco Viejo) now fails in_country and falls through."""
    for title in (subject, "%s, %s" % (subject, country), "%s (%s)" % (subject, country)):
        ll = coords(title)
        if ll and in_country(ll, iso):
            return ll
    return None


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


def build_country(args):
    """(iso, spots), or (iso, None) when Wikipedia couldn't be reached."""
    try:
        return _build_country(args)
    except LookupFailed as e:
        print("\n%s: lookup failed at %r — keeping its previous spots" % (args[0], str(e)))
        return args[0], None


def _build_country(args):
    iso, act, names = args
    country = names.get(iso, iso)
    aliases = ALIASES.get(iso, {})
    act_cands = [p for x in (act.get("activities") or []) for p in act_places(x)]
    gal_cands = act.get("gallery") or []
    spots = []

    def add(subject, cap):
        if len(spots) >= cap:
            return
        # curated alias: phrase -> real Wikipedia title (+ optional chip label,
        # + optional fixed "ll" for places Wikipedia has no coordinates for)
        al = aliases.get(subject) or aliases.get(label(subject))
        name = (al or {}).get("label") or label((al or {}).get("title") or subject)
        if not name or any(same_place(name, s["n"]) for s in spots):
            return
        ll = (al or {}).get("ll") or coords_with_fallback((al or {}).get("title") or subject,
                                                          country, iso)
        # Two names for one place (San Blas / Guna Yala) make two identical chips.
        if ll and not any(geo.dist_km((ll[1], ll[0]), (s["ll"][1], s["ll"][0])) < 3 for s in spots):
            spots.append({"n": name, "ll": ll})

    # Activity places first (up to 5) — these mirror "top things to do".
    for s in act_cands:
        add(s, MAX_SPOTS)
    # Gallery places only top up thin lists (to 4), never crowd the itinerary.
    for s in gal_cands:
        add(s, 4)
    return iso, spots


def check(data):
    """Every anchor that isn't plausibly in its own country."""
    return [(iso, s["n"], s["ll"]) for iso, spots in sorted(data.items())
            for s in spots if not in_country(s["ll"], iso)]


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
    with ThreadPoolExecutor(max_workers=2 if only else 8) as ex:
        for iso, spots in ex.map(build_country, jobs):
            if spots is None:
                spots = previous.get(iso) or []
            if spots:
                out[iso] = spots
            print("%s:%d" % (iso, len(spots)), end=" ", flush=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    counts = [len(v) for v in out.values()]
    print("\n%d/%d countries; avg %.1f spots; thin(<2): %s"
          % (len(out), len(acts), sum(counts) / len(counts),
             [k for k in acts if len(out.get(k, [])) < 2]))
    bad = check(out)
    if bad:
        print("OUTSIDE THEIR COUNTRY (fix with stay-aliases.json):")
        for row in bad:
            print("  %s %s %s" % row)


if __name__ == "__main__":
    args = [a.upper() for a in sys.argv[1:]]
    if args == ["--CHECK"]:
        bad = check(json.load(open(os.path.join(PUBLIC, "stay-coords.json"), encoding="utf-8")))
        for row in bad:
            print("%s %s %s" % row)
        print("%d anchor(s) outside their country" % len(bad))
        sys.exit(1 if bad else 0)
    main(set(args) or None)

#!/usr/bin/env python3
"""Audit of the guide's "Top things to do" thumbnails (2026-10-31): which
Wikipedia page and image each activity row shows, and whether that page is
the intended place, in the right country.

The row's photo is client-side (public/app.js activitySubject -> actPhoto ->
wikiIconic): subject = the row's "p", else the first parenthesised name in
its title (text before a comma), else the title without brackets, NP ->
National Park, Mt -> Mount; then wikiIconic(subject, 700, 500), then
"subject, Country", then "subject (Country)". wikiIconic reads en.wikipedia
pageimages (redirects=1, 1600px thumb), refuses PHOTO_BAD thumbs and files on
public/photo-skip.json, and applies the size gate. This script mirrors that
in Python, batching 50 titles a request, and adds what the site does not ask
for: the page's coordinates (prop=coordinates), short description,
disambiguation flag and Wikidata item, then the item's P17 (country), P31
(instance of) and P625 (coordinates) via wbgetentities, and a point-in-
polygon test against public/world.geojson. Every response is cached on disk
(--cache DIR, default /tmp/activity-thumb-audit, which a reboot clears), so
a rerun asks nothing twice and a long run can be resumed in <60 s slices.

A "p" may also pin a Commons file ("File:Name.jpg", as Iceland's northern
lights did first): pageimages answers a File: page with the file itself, so
the same chain shows it, and gen_stay_spots.py leaves such a pin out of the
stay places. A pin carries no coordinates or Wikidata item: vet it with
`filemeta` (licence, camera/object coordinates, categories, description).
A row with no parenthetical may carry "sp", its stay place (2026-11-01):
gen_stay_spots then reads "sp", not "p", so its photo can change without
moving a chip (`stays` proves it); app.js never reads "sp".

    /usr/bin/python3 scripts/dev/activity_thumb_audit.py resolve  [--cache DIR] [--acts FILE]
        rows.json: one record per activity row (subject, attempts, title,
        file, thumb, coords, description, QID) + gallery.json (each
        country's gallery[:6] resolved as iconicPhotos does: file keys)
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py wikidata [--cache DIR]
        adds P17/P31/P625 for every resolved page's item (and the ISO-2 ->
        QID map via one SPARQL query on P297)
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py flag     [--cache DIR]
        flags.json + a printed table: page outside the country's polygon
        (with distance), P17 not the country, disambiguation, person/taxon/
        generic items, no photo, a row's file shown by an earlier row, a file
        the country's hero gallery shows
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py thumbs   [--cache DIR] [--only ISO:i,...]
        downloads the 330px thumb every row shows (the size loadActivityThumbs
        hotlinks), sequentially, cached
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py sheet OUT.jpg ISO:i [ISO:i ...]
        a labelled PIL contact sheet of those rows' 330px thumbs
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py try "ISO:i|Title" [...] [--file LIST]
        a candidate "p" for row i of ISO (or lines of LIST) through the same
        actPhoto chain: the page and file it would show, coords and the
        site-map check, P17, and whether the file is one the country's hero
        gallery or another of its rows already shows (hero_clash/row_clash)
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py stays [--ref 85b827d] [--ref-tree DIR] [--all] [--acts FILE]
        "p" is also a "Where to stay" place for a row whose title has no
        parenthetical and no "sp" (scripts/gen_stay_spots.py act_places):
        rebuild the stay chips of every country whose activities differ from
        REF (--all: every country), from REF's file and from this tree's,
        with this script's cached Wikipedia coordinates, and print SAME/DIFF
        (DIFF = the next gen_stay_spots run would change that country's
        chips); --ref-tree DIR builds REF's side with an export of REF's
        tree, so its gen_stay_spots.py, and the fxtracker/geo.py and
        scripts/gallery_entry.py it imports, are compared as well (the
        files each side loaded are printed first)
    /usr/bin/python3 scripts/dev/activity_thumb_audit.py filemeta "File:Name.jpg" [...]
        Commons metadata of candidate pinned files: size, licence, author,
        date, coordinates (camera/object, with the site-map check when
        --iso XX is given), categories, description

User-Agent "WanderGrade-dev/1.0 (hello@wandergrade.com)"; requests are
sequential, 0.3 s apart. No Nominatim.
"""
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC = os.path.join(ROOT, "public")
UA = "WanderGrade-dev/1.0 (hello@wandergrade.com)"
PAUSE = 0.3
DEFAULT_CACHE = "/tmp/activity-thumb-audit"


def _opt(argv, flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


ARGV = sys.argv[1:]
CACHE = _opt(ARGV, "--cache", DEFAULT_CACHE)
ACTS_FILE = _opt(ARGV, "--acts", os.path.join(PUBLIC, "activities.json"))
HTTP_DIR = os.path.join(CACHE, "http")
THUMB_DIR = os.path.join(CACHE, "thumbs330")

with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
    APP = f.read()
# The site's own filter, read from app.js so the audit cannot drift from it.
PHOTO_BAD = re.compile(re.search(r"^const PHOTO_BAD = /(.*)/i;$", APP, re.M).group(1), re.I)
with open(os.path.join(PUBLIC, "photo-skip.json"), encoding="utf-8") as f:
    SKIP = set(json.load(f).get("files") or [])
with open(os.path.join(PUBLIC, "country-names.json"), encoding="utf-8") as f:
    NAMES = json.load(f)        # == app.js countryName() for all 190 guides (checked 2026-10-31)


def acts():
    with open(ACTS_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---- app.js mirrors -----------------------------------------------------------
def act_label(x):
    return (x if isinstance(x, str) else (x or {}).get("t")) or ""


def activity_subject(x):
    """app.js activitySubject(); \\b is ASCII in a JS regex without /u."""
    label = act_label(x)
    if isinstance(x, dict) and x.get("p"):
        return x["p"]
    m = re.search(r"\(([^),]+)", label)
    subj = (m.group(1) if m else re.sub(r"\s*\([^)]*\)", "", label)).strip()
    subj = re.sub(r"\bNP\b", "National Park", subj, count=1, flags=re.A)
    return re.sub(r"\bMt\b", "Mount", subj, count=1, flags=re.A)


def file_key(u):
    """app.js fileKey()."""
    m = re.search(r"/wikipedia/[^/]+/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?]+)", u or "")
    return urllib.parse.unquote(m.group(1)) if m else u


def wm_thumb_at(url, w, orig_w):
    """app.js wmThumbAt() (the 330px thumb loadActivityThumbs hotlinks)."""
    t = re.match(r"^(.*/thumb/.+/)(\d+)(px-[^/?]+(?:\?.*)?)$", url or "")
    if t:
        return t.group(1) + str(w) + t.group(3) if w < int(t.group(2)) else url
    o = re.match(r"^(https://(?:upload|thumb)\.wikimedia\.org/wikipedia/[^/]+/)([0-9a-f]/[0-9a-f]{2}/)"
                 r"([^/?]+\.(?:jpe?g|png|gif|webp))(\?.*)?$", url or "", re.I)
    if not o or not (w > 0 and (orig_w or 0) > w):
        return url
    if len(urllib.parse.unquote(o.group(3)).encode("utf-8")) > 160:
        return url
    return o.group(1) + "thumb/" + o.group(2) + o.group(3) + "/" + str(w) + "px-" + o.group(3) + (o.group(4) or "")


def gate(page, min_w, min_h):
    """wikiIconic()'s verdict on a pageimages record: the photo or None."""
    t = (page or {}).get("thumbnail") or {}
    thumb = t.get("source")
    if not thumb or PHOTO_BAD.search(thumb):
        return None
    if page.get("pageimage") and page["pageimage"] in SKIP:
        return None
    if (t.get("width") or 0) < min_w and (t.get("height") or 0) < min_h:
        return None
    orig = (page.get("original") or {}).get("source")
    p = {"thumb": thumb, "full": orig if (orig and not PHOTO_BAD.search(orig)) else thumb,
         "file": page.get("pageimage") or ""}
    if "/thumb/" not in thumb:
        p["w"] = (page.get("original") or {}).get("width") or t.get("width") or 0
    return p


def refusal(page):
    """Why wikiIconic(…, 700, 500) refuses a page, in its order."""
    t = (page or {}).get("thumbnail") or {}
    if (page or {}).get("missing"):
        return "missing"
    if not t.get("source"):
        return "no-image"
    if PHOTO_BAD.search(t["source"]):
        return "PHOTO_BAD"
    if page.get("pageimage") in SKIP:
        return "skip-list"
    if (t.get("width") or 0) < 700 and (t.get("height") or 0) < 500:
        return "too-small"
    return None


# ---- HTTP, cached -----------------------------------------------------------------
_last = [0.0]


def get(url, binary=False, timeout=30):
    os.makedirs(HTTP_DIR, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    path = os.path.join(HTTP_DIR, key + (".bin" if binary else ".json"))
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return data if binary else json.loads(data)
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=timeout).read()
    _last[0] = time.time()
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    return data if binary else json.loads(data)


WP_API = "https://en.wikipedia.org/w/api.php?"


PAGES_FILE = os.path.join(CACHE, "pages.json")
_PAGES = None


def _pages_store():
    global _PAGES
    if _PAGES is None:
        try:
            with open(PAGES_FILE, encoding="utf-8") as f:
                _PAGES = json.load(f)
        except (OSError, ValueError):
            _PAGES = {}
    return _PAGES


def wp_pages(titles):
    """title -> the page record app.js would read for it (pageimages as the
    site asks, plus coordinates, description, pageprops). 50 a request,
    continuation merged, normalized/redirects followed; every title's record
    is kept in pages.json so no title is asked twice."""
    store = _pages_store()
    titles = list(dict.fromkeys(t for t in titles if t))
    out = {t: store[t] for t in titles if t in store}
    titles = [t for t in titles if t not in store]
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        base = {"action": "query", "format": "json", "redirects": "1",
                "prop": "pageimages|coordinates|description|pageprops",
                "piprop": "thumbnail|original|name", "pithumbsize": "1600", "pilimit": "50",
                "colimit": "max", "ppprop": "disambiguation|wikibase_item",
                "titles": "|".join(chunk)}
        pages, norm, redir, cont = {}, {}, {}, {}
        while True:
            j = get(WP_API + urllib.parse.urlencode({**base, **cont}))
            q = j.get("query") or {}
            for n in q.get("normalized") or []:
                norm[n["from"]] = n["to"]
            for r in q.get("redirects") or []:
                redir[r["from"]] = r["to"]
            for pg in (q.get("pages") or {}).values():
                cur = pages.setdefault(pg["title"], {})
                for k, v in pg.items():
                    if k == "coordinates":
                        cur.setdefault("coordinates", []).extend(v)
                    else:
                        cur[k] = v
            if "continue" not in j:
                break
            cont = j["continue"]
        for t in chunk:
            u = norm.get(t, t)
            seen = set()
            while u in redir and u not in seen:
                seen.add(u)
                u = redir[u]
            pg = pages.get(u)
            out[t] = store[t] = pg if pg is not None else {"title": u, "missing": True}
        with open(PAGES_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False)
        os.replace(PAGES_FILE + ".tmp", PAGES_FILE)
    return out


def act_photo(subject, country, cache):
    """actPhoto(): (photo, page, the title that served it, attempts)."""
    tries = [subject] + ([subject + ", " + country, subject + " (" + country + ")"] if country else [])
    attempts = []
    for t in tries:
        if t not in cache:
            cache.update(wp_pages([t]))
        pg = cache[t]
        p = gate(pg, 700, 500)
        attempts.append({"ask": t, "title": pg.get("title"), "file": pg.get("pageimage"),
                         "ok": bool(p), "why": None if p else refusal(pg)})
        if p:
            return p, pg, t, attempts
    return None, None, None, attempts


def commons_photo(name, min_w, min_h):
    """commonsPhoto() minus the licence (gallery file entries only)."""
    name = (name or "").strip()
    if not name or PHOTO_BAD.search(name):
        return None
    j = get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size",
        "iiurlwidth": "1600", "titles": "File:" + name}))
    page = next(iter(((j.get("query") or {}).get("pages") or {}).values()), None)
    ii = ((page or {}).get("imageinfo") or [None])[0]
    if not ii or not ii.get("thumburl"):
        return None
    f = page["title"].replace("File:", "", 1).replace(" ", "_")
    if f in SKIP:
        return None
    tw, th = min(ii.get("thumbwidth") or 0, ii.get("width") or 0), min(ii.get("thumbheight") or 0, ii.get("height") or 0)
    if tw < min_w and th < min_h:
        return None
    return {"thumb": ii["thumburl"], "full": ii.get("url") or ii["thumburl"], "file": f}


def gallery_keys(a, iso, cache):
    """iconicPhotos(iso): file keys of the gallery[:6] photos (800/1000 gate)."""
    keys, titles = [], []
    for e in (a[iso].get("gallery") or [])[:6]:
        if isinstance(e, dict):
            p = commons_photo(e.get("file"), 800, 1000)
            keys.append([e.get("label"), file_key(p["full"]) if p else None])
        else:
            titles.append(e)
    missing = [t for t in titles if t not in cache]
    if missing:
        cache.update(wp_pages(missing))
    for e in (a[iso].get("gallery") or [])[:6]:
        if isinstance(e, str):
            p = gate(cache[e], 800, 1000)
            keys.append([e, file_key(p["full"]) if p else None])
    return keys


# ---- geometry -------------------------------------------------------------------
def _load_geo():
    with open(os.path.join(PUBLIC, "world.geojson"), encoding="utf-8") as f:
        g = json.load(f)
    polys = {}
    for ft in g["features"]:
        geom = ft["geometry"]
        rings = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        polys.setdefault(ft["properties"]["iso"], []).extend(rings)
    return polys


GEO = None


def _in_ring(lon, lat, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _seg_km(lon, lat, a, b):
    kx = 111.32 * math.cos(math.radians(lat))
    ky = 110.57
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy)


def geo_check(iso, lat, lon):
    """(inside?, km to the country's outline) on the site's coarse map; the
    UK home nations use GB."""
    global GEO
    if GEO is None:
        GEO = _load_geo()
    polys = GEO.get("GB" if iso.startswith("GB-") else iso)
    if not polys:
        return None, None
    inside = False
    best = 1e9
    for poly in polys:
        outer, holes = poly[0], poly[1:]
        if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
            inside = True
        for ring in poly:
            for k in range(len(ring) - 1):
                best = min(best, _seg_km(lon, lat, ring[k], ring[k + 1]))
    return inside, round(best, 1)


# ---- commands --------------------------------------------------------------------
def page_coords(pg):
    for c in (pg or {}).get("coordinates") or []:
        if c.get("globe", "earth") == "earth":
            return [c["lat"], c["lon"]]
    return None


def cmd_resolve():
    a = acts()
    t0 = time.time()
    cache = {}
    # Every row's first ask in batches of 50, then the fallbacks.
    subs = [(activity_subject(x), NAMES[iso]) for iso in a for x in a[iso]["activities"]]
    cache.update(wp_pages([s for s, _ in subs]))
    for fmt in ("%s, %s", "%s (%s)"):
        left = [(s, c) for s, c in subs
                if not any(gate(cache.get(t), 700, 500) for t in (s, s + ", " + c) if t in cache)]
        cache.update(wp_pages([fmt % (s, c) for s, c in left]))
    rows = []
    for iso in a:
        country = NAMES[iso]
        for i, x in enumerate(a[iso]["activities"]):
            subj = activity_subject(x)
            p, pg, served, attempts = act_photo(subj, country, cache)
            rec = {"iso": iso, "i": i, "t": x.get("t"), "d": x.get("d"), "p": x.get("p"), "subject": subj,
                   "attempts": attempts, "served": served}
            if p:
                rec.update({"title": pg.get("title"), "file": p["file"], "key": file_key(p["full"]),
                            "thumb": p["thumb"], "w": p.get("w"),
                            "thumb330": wm_thumb_at(p["thumb"], 330, p.get("w")),
                            "coords": page_coords(pg), "desc": pg.get("description"),
                            "disambig": "disambiguation" in (pg.get("pageprops") or {}),
                            "qid": (pg.get("pageprops") or {}).get("wikibase_item")})
            rows.append(rec)
        if time.time() - t0 > 45:
            print("time budget: stopped after", iso, "- rerun to continue (cached)")
            return
    cache.update(wp_pages([e for iso in a for e in (a[iso].get("gallery") or [])[:6] if isinstance(e, str)]))
    gal = {iso: gallery_keys(a, iso, cache) for iso in a}
    # First shown wins (loadActivityThumbs' `used`; it is the first to RESOLVE,
    # which is document order when nothing is cached).
    for iso in a:
        seen = {}
        gk = {k for _, k in gal[iso] if k}
        for r in rows:
            if r["iso"] != iso or not r.get("key"):
                continue
            if r["key"] in seen:
                r["dup_of"] = seen[r["key"]]
            else:
                seen[r["key"]] = r["i"]
            r["in_gallery"] = r["key"] in gk
    json.dump(rows, open(os.path.join(CACHE, "rows.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(gal, open(os.path.join(CACHE, "gallery.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    shown = sum(1 for r in rows if r.get("key") and "dup_of" not in r)
    print("rows", len(rows), "with photo", sum(1 for r in rows if r.get("key")), "shown", shown,
          "no photo", sum(1 for r in rows if not r.get("key")), "%.1fs" % (time.time() - t0))


def wd_entities(qids, props="claims|labels|descriptions"):
    out = {}
    qids = sorted(set(q for q in qids if q))
    for i in range(0, len(qids), 50):
        j = get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "format": "json", "ids": "|".join(qids[i:i + 50]),
            "props": props, "languages": "en"}), timeout=50)
        for q, e in (j.get("entities") or {}).items():
            cl = e.get("claims") or {}

            def vals(pid):
                r = []
                for c in cl.get(pid) or []:
                    dv = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                    if isinstance(dv, dict) and "id" in dv:
                        r.append(dv["id"])
                    elif isinstance(dv, dict) and "latitude" in dv:
                        r.append([dv["latitude"], dv["longitude"]])
                    elif dv is not None:
                        r.append(dv)
                return r
            out[q] = {"label": ((e.get("labels") or {}).get("en") or {}).get("value"),
                      "desc": ((e.get("descriptions") or {}).get("en") or {}).get("value"),
                      "P17": vals("P17"), "P31": vals("P31"), "P625": vals("P625"), "P297": vals("P297")}
    return out


def cmd_wikidata():
    rows = json.load(open(os.path.join(CACHE, "rows.json"), encoding="utf-8"))
    ents = wd_entities([r.get("qid") for r in rows])
    # ISO alpha-2 -> country items, one SPARQL query (cached).
    sp = get("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({
        "format": "json", "query": "SELECT ?c ?iso WHERE { ?c wdt:P297 ?iso }"}), timeout=50)
    iso2q = {}
    for b in sp["results"]["bindings"]:
        iso2q.setdefault(b["iso"]["value"], []).append(b["c"]["value"].rsplit("/", 1)[1])
    p17 = sorted({q for e in ents.values() for q in e["P17"]})
    labels = wd_entities(p17, props="labels")
    json.dump({"ents": ents, "iso2q": iso2q, "p17labels": {q: v["label"] for q, v in labels.items()}},
              open(os.path.join(CACHE, "wikidata.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("items", len(ents), "countries in P297", len(iso2q), "distinct P17", len(p17))


# Sovereign items a dependent territory's places carry in P17 (Wikidata), and
# ISO codes the P297 map lacks.
EXTRA_Q = {
    "GB-ENG": ["Q145"], "GB-SCT": ["Q145"], "GB-WLS": ["Q145"], "FK": ["Q145"], "GS": ["Q145"],
    "GG": ["Q145", "Q25230"], "JE": ["Q145", "Q785"], "IM": ["Q145", "Q9676"], "BM": ["Q145"], "KY": ["Q145"],
    "GU": ["Q30"], "PR": ["Q30"], "VI": ["Q30"],
    "AW": ["Q29999", "Q55"], "CW": ["Q29999", "Q55"], "SX": ["Q29999", "Q55"],
    "NC": ["Q142"], "PF": ["Q142"], "TF": ["Q142"],
    "FO": ["Q756617", "Q35"], "GL": ["Q756617", "Q35"],
    "HK": ["Q148"], "MO": ["Q148"], "PS": ["Q219060", "Q801"], "EH": ["Q1028", "Q40362"],
    "XK": ["Q1246", "Q403"], "TW": ["Q865"], "CK": ["Q664"], "AQ": [], "NL": ["Q55"],
}
HUMAN, TAXON, DISAMBIG = "Q5", "Q16521", "Q4167410"


def cmd_flag():
    rows = json.load(open(os.path.join(CACHE, "rows.json"), encoding="utf-8"))
    wd = json.load(open(os.path.join(CACHE, "wikidata.json"), encoding="utf-8"))
    ents, iso2q, lab = wd["ents"], wd["iso2q"], wd["p17labels"]
    flags = []
    for r in rows:
        f = []
        if not r.get("key"):
            f.append("no-photo")
        else:
            e = ents.get(r.get("qid") or "", {})
            want = set(iso2q.get(r["iso"], [])) | set(EXTRA_Q.get(r["iso"], []))
            if r.get("disambig") or DISAMBIG in e.get("P31", []):
                f.append("disambiguation")
            if HUMAN in e.get("P31", []):
                f.append("person")
            if TAXON in e.get("P31", []):
                f.append("taxon")
            if e.get("P17") and not (set(e["P17"]) & want):
                f.append("P17=" + "/".join(lab.get(q) or q for q in e["P17"]))
            c = r.get("coords") or (e.get("P625") or [None])[0]
            if c:
                inside, km = geo_check(r["iso"], c[0], c[1])
                r["geo"] = [inside, km]
                if inside is False:
                    f.append("outside %skm" % km)
            else:
                f.append("no-coords")
            if not e.get("P17"):
                f.append("no-P17")
            if r.get("dup_of") is not None:
                f.append("dup-of-row%d" % r["dup_of"])
            if r.get("in_gallery"):
                f.append("hero-file")
            if re.search(r"\.(png|gif|tiff?)$", r.get("file") or "", re.I):
                f.append("non-jpeg")
            r["wd"] = {"label": e.get("label"), "desc": e.get("desc"),
                       "P17": [lab.get(q) or q for q in e.get("P17", [])]}
        r["flags"] = f
        flags.append(r)
    json.dump(flags, open(os.path.join(CACHE, "flags.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    strong = ("P17=", "outside", "disambiguation", "person", "taxon")
    n = 0
    for r in flags:
        if any(x.startswith(strong) for x in r["flags"]):
            n += 1
            print("%s:%d %-40s -> %-40s %s | %s" % (r["iso"], r["i"], r["t"][:40], (r.get("title") or "")[:40],
                                                   ",".join(r["flags"]), (r.get("desc") or "")[:60]))
    print("strong flags:", n, "of", len(flags))


def cmd_thumbs():
    rows = json.load(open(os.path.join(CACHE, "rows.json"), encoding="utf-8"))
    only = _opt(ARGV, "--only", None)
    want = set(only.split(",")) if only else None
    t0 = time.time()
    n = 0
    for r in rows:
        if not r.get("thumb330") or (want and "%s:%d" % (r["iso"], r["i"]) not in want):
            continue
        os.makedirs(THUMB_DIR, exist_ok=True)
        path = os.path.join(THUMB_DIR, hashlib.sha1(r["thumb330"].encode()).hexdigest() + ".jpg")
        if os.path.exists(path):
            continue
        try:
            data = get(r["thumb330"], binary=True)
            with open(path, "wb") as f:
                f.write(data)
            n += 1
        except Exception as e:
            print("fail", r["iso"], r["i"], r["thumb330"][:100], e)
        if time.time() - t0 > 45:
            print("time budget: rerun to continue")
            break
    print("downloaded", n)


def thumb_image(url):
    from PIL import Image
    os.makedirs(THUMB_DIR, exist_ok=True)
    path = os.path.join(THUMB_DIR, hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if not os.path.exists(path):
        data = get(url, binary=True)
        with open(path, "wb") as f:
            f.write(data)
    return Image.open(path).convert("RGB")


def contact_sheet(out, items, cols=6, tile=330):
    """items: [(label lines, thumb url or None)]."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
    except Exception:
        font = ImageFont.load_default()
    th = 250
    cap = 58
    rows_n = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tile + 8) + 8, rows_n * (th + cap + 8) + 8), "white")
    d = ImageDraw.Draw(sheet)
    for k, (lines, url) in enumerate(items):
        x = 8 + (k % cols) * (tile + 8)
        y = 8 + (k // cols) * (th + cap + 8)
        if url:
            try:
                im = thumb_image(url)
                im.thumbnail((tile, th))
                sheet.paste(im, (x + (tile - im.width) // 2, y))
            except Exception as e:
                d.text((x + 4, y + 4), "fetch failed: %s" % e, fill="red", font=font)
        else:
            d.rectangle((x, y, x + tile, y + th), outline="red")
            d.text((x + 8, y + th // 2), "no thumbnail", fill="red", font=font)
        for li, line in enumerate(lines[:3]):
            d.text((x, y + th + 2 + li * 18), line[:44], fill="black", font=font)
    sheet.save(out, "JPEG", quality=85)
    return out


def cmd_sheet():
    rows = json.load(open(os.path.join(CACHE, "rows.json"), encoding="utf-8"))
    by = {"%s:%d" % (r["iso"], r["i"]): r for r in rows}
    out = ARGV[1]
    items = []
    for k in [a for a in ARGV[2:] if not a.startswith("--") and a != CACHE]:
        r = by[k]
        items.append(([k + " " + (r["t"] or ""), "-> " + (r.get("title") or "(none)"), r.get("file") or ""],
                      r.get("thumb330")))
    print(contact_sheet(out, items))


def cmd_try():
    """Candidates as ISO|Title arguments (or lines of --file F): each through
    actPhoto with the country's fallbacks, then its coords, P17, and whether
    its file is one the country's hero gallery or another row already shows."""
    args = [a for a in ARGV[1:] if not a.startswith("--") and a not in (CACHE, _opt(ARGV, "--file", None))]
    if _opt(ARGV, "--file", None):
        with open(_opt(ARGV, "--file", None), encoding="utf-8") as f:
            args += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    pairs = [a.split("|", 1) for a in args]
    a = acts()
    cache = wp_pages([t for _, t in pairs] + [t + ", " + NAMES[i.split(":")[0]] for i, t in pairs]
                     + [t + " (" + NAMES[i.split(":")[0]] + ")" for i, t in pairs])
    rows = json.load(open(os.path.join(CACHE, "rows.json"), encoding="utf-8"))
    res = []
    for key, t in pairs:
        iso = key.split(":")[0]
        p, pg, served, attempts = act_photo(t, NAMES[iso], cache)
        res.append((key, t, p, pg or cache[t], served, attempts))
    ents = wd_entities([(r[3].get("pageprops") or {}).get("wikibase_item") for r in res])
    wd = json.load(open(os.path.join(CACHE, "wikidata.json"), encoding="utf-8"))
    lab = dict(wd["p17labels"])
    gcache = {}
    for key, t, p, pg, served, attempts in res:
        iso = key.split(":")[0]
        if iso not in gcache:
            gcache[iso] = {k: g for g, k in gallery_keys(a, iso, cache) if k}
        others = {r["key"]: "%s:%d" % (r["iso"], r["i"]) for r in rows
                  if r["iso"] == iso and r.get("key") and "%s:%d" % (r["iso"], r["i"]) != key}
        e = ents.get((pg.get("pageprops") or {}).get("wikibase_item") or "", {})
        c = page_coords(pg) or (e.get("P625") or [None])[0]
        geo = geo_check(iso, c[0], c[1]) if c else None
        fk = file_key(p["full"]) if p else None
        print(json.dumps({"row": key, "ask": t, "served": served, "title": pg.get("title"), "ok": bool(p),
                          "why": None if p else [x["why"] for x in attempts],
                          "file": fk or pg.get("pageimage"),
                          "thumb330": wm_thumb_at(p["thumb"], 330, p.get("w")) if p else None,
                          "coords": c, "geo": geo, "desc": pg.get("description"),
                          "P17": [lab.get(q, q) for q in e.get("P17", [])],
                          "hero_clash": gcache[iso].get(fk) if fk else None,
                          "row_clash": others.get(fk) if fk else None}, ensure_ascii=False))


def cmd_filemeta():
    """Commons metadata for candidate pinned files ("File:Name.jpg" or a
    bare name), 50 a request: what a pin must be vetted on, since it has no
    article coordinates or Wikidata item (licence, where it was taken, the
    categories it is filed under)."""
    iso = _opt(ARGV, "--iso", None)
    skip = {CACHE, iso}
    names = [a for a in ARGV[1:] if not a.startswith("--") and a not in skip]
    names = [re.sub(r"^File:", "", n).replace("_", " ") for n in names]
    for i in range(0, len(names), 50):
        j = get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "coordinates|imageinfo|categories",
            # colimit: prop=coordinates answers 10 pages a request by default,
            # so files past the tenth of a batch came back with no coordinates
            "iiprop": "extmetadata|size", "coprop": "type", "coprimary": "all", "colimit": "max", "cllimit": "max",
            "clshow": "!hidden", "iiextmetadatafilter":
            "ImageDescription|LicenseShortName|Artist|DateTimeOriginal",
            "titles": "|".join("File:" + n for n in names[i:i + 50])}))
        for pg in ((j.get("query") or {}).get("pages") or {}).values():
            ii = (pg.get("imageinfo") or [{}])[0]
            md = ii.get("extmetadata") or {}

            def v(k):
                return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", (md.get(k) or {}).get("value", ""))).strip()
            coords = [[c.get("type") or "object", c["lat"], c["lon"]] for c in pg.get("coordinates") or []]
            print(json.dumps({
                "file": pg["title"], "missing": "missing" in pg, "size": [ii.get("width"), ii.get("height")],
                "licence": v("LicenseShortName"), "artist": v("Artist")[:80], "date": v("DateTimeOriginal")[:25],
                "coords": coords,
                "geo": [geo_check(iso, c[1], c[2]) for c in coords] if iso else None,
                "categories": [c["title"].split(":", 1)[1] for c in pg.get("categories") or []],
                "desc": v("ImageDescription")[:300]}, ensure_ascii=False))


def cmd_stays():
    import contextlib
    import importlib.util
    import io
    import subprocess
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import gen_stay_spots as g

    def wiki(titles):                    # gen_stay_spots._wiki's answer, from this script's cache
        pages = wp_pages(titles)
        out = {}
        for t in titles:
            c = [x for x in (pages[t].get("coordinates") or []) if x.get("globe", "earth") == "earth"]
            out[t] = [round(c[0]["lat"], 5), round(c[0]["lon"], 5)] if c else None
        return out
    g._wiki = wiki
    ref = _opt(ARGV, "--ref", "85b827d")
    # --ref-tree DIR: an export of REF (git archive REF | tar -x -C DIR) whose
    # own gen_stay_spots.py (and the stay-aliases/stay-skip files beside it)
    # builds REF's side, so a change to the code is compared too, not only
    # one to activities.json. --all compares every country, not only those
    # whose activities differ (to check a code change on unchanged data, run
    # it with --acts DIR/public/activities.json).
    g_old = g
    if _opt(ARGV, "--ref-tree", None):
        ref_tree = os.path.abspath(_opt(ARGV, "--ref-tree", None))
        # REF's helpers as well: gen_stay_spots imports fxtracker.geo and
        # gallery_entry, which this tree's import above already put in
        # sys.modules (with this tree's scripts/ first on sys.path), so REF's
        # module would reuse them. They are set aside while REF's module
        # loads from REF's paths and put back after; REF's module keeps the
        # ones it imported (stays reaches no other fxtracker module).
        mine = lambda k: k in ("gallery_entry", "fxtracker") or k.startswith("fxtracker.")
        ours = {k: sys.modules.pop(k) for k in list(sys.modules) if mine(k)}
        path0 = list(sys.path)
        sys.path[:0] = [os.path.join(ref_tree, "scripts"), ref_tree]
        try:
            spec = importlib.util.spec_from_file_location(
                "gen_stay_spots_ref", os.path.join(ref_tree, "scripts", "gen_stay_spots.py"))
            g_old = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(g_old)
        finally:
            for k in [k for k in sys.modules if mine(k)]:
                del sys.modules[k]
            sys.modules.update(ours)
            sys.path[:] = path0
        g_old._wiki = wiki
        loaded = [m.__file__ for m in (g_old, g_old.geo, g_old.gallery_entry)]
        print("REF side:", *(os.path.relpath(f, ref_tree) if f.startswith(ref_tree + os.sep)
                             else "NOT REF'S " + f for f in loaded))
        print("this side:", *(os.path.relpath(m.__file__, ROOT) for m in (g, g.geo, g.gallery_entry)))
        if not all(f.startswith(ref_tree + os.sep) for f in loaded):
            sys.exit("stays: REF's side did not load REF's own files, so it would not compare them")
    old = json.loads(subprocess.run(["git", "-C", ROOT, "show", ref + ":public/activities.json"],
                                    capture_output=True, text=True, check=True).stdout)
    new = acts()
    with open(os.path.join(PUBLIC, "stay-coords.json"), encoding="utf-8") as f:
        stays = json.load(f)
    diff = 0
    for iso in sorted(i for i in new if "--all" in ARGV or new[i] != old.get(i)):
        with contextlib.redirect_stdout(io.StringIO()):
            g_old.prefetch_country(iso, old[iso], NAMES)     # 50 titles a request, not one by one
            g.prefetch_country(iso, new[iso], NAMES)
            b_old = g_old._build_country((iso, old[iso], NAMES, stays.get(iso)))[1]
            b_new = g._build_country((iso, new[iso], NAMES, stays.get(iso)))[1]
        same = [(x["n"], x["ll"]) for x in b_old] == [(x["n"], x["ll"]) for x in b_new]
        diff += not same
        print(iso, "SAME" if same else "DIFF", "" if same else "%s -> %s" % ([x["n"] for x in b_old], [x["n"] for x in b_new]))
    print("countries whose stay chips a rebuild would change:", diff)


if __name__ == "__main__":
    cmd = ARGV[0] if ARGV else ""
    {"resolve": cmd_resolve, "wikidata": cmd_wikidata, "flag": cmd_flag, "thumbs": cmd_thumbs,
     "sheet": cmd_sheet, "try": cmd_try, "stays": cmd_stays,
     "filemeta": cmd_filemeta}.get(cmd, lambda: print(__doc__))()

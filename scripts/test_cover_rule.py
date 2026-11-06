#!/usr/bin/env python3
"""The newsletter's cover rule (fxtracker/picks.py cover_for), offline: a
featured country's cover is the first candidate that passes the site's own
photo checks, the candidates being activities.json `photo` (an optional
override) and then the gallery entries the guide hero shows.

    /usr/bin/python3 scripts/test_cover_rule.py

  * the checks are the site's: PHOTO_BAD and PHOTO_LICENCE_OK equal app.js's,
    the skip list is public/photo-skip.json, and six gallery entries is
    app.js photoSubjects' slice;
  * the selection order, with the two lookups (cover() for a title,
    cover_file() for a pinned {file, label}) stubbed: `photo` first, then the
    gallery in order, each entry once (an override the gallery repeats too,
    with nothing passing), stopping at the first that passes, never past the
    sixth gallery entry, never more than seven lookups;
  * the memo: a candidate is looked up once a run, across countries and
    editions, and a title never shares a pinned file's answer;
  * each rejection, with Wikipedia and Commons answered from a fixture
    (urlopen stubbed; a title's lead image is its pageimages answer, as app.js
    wikiIconic asks, which names only a free image where the REST summary can
    lead with a non-free one): PHOTO_BAD (no Commons request), the skip list
    (by the name, and by Commons' canonical spelling where the two differ),
    a licence outside the site's (either half of the check, the short name
    or the code, can pass it), an en.wikipedia-hosted image, no lead image, a
    missing file, an original under 800px wide, one with no thumbnail at a
    step (.tif), a failed request; and what passes: the weserv banner of a
    thumb.wikimedia.org thumbnail at the widest step under the original (500
    from 800, 960, 1280) and the credit the email prints; a page whose free
    lead differs from its any-licence one gives the free one; a pinned file
    asks Commons once;
  * the data: `photo` is left only on the twelve override countries, each a
    photo of its own gallery (Doug's 2026-10-30 picks among them: Batu Caves,
    Tower Bridge, Bran Castle, Pena Palace; Congo's gallery lead won over
    Lefini), and app.js reads `photo` only for a country without a gallery,
    which none is.
"""
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import picks  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()
with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
    ACTS = json.load(f)
with open(os.path.join(ROOT, "public", "photo-skip.json"), encoding="utf-8") as f:
    SKIP = set(json.load(f)["files"])

print("1. the site's checks")
js_bad = re.search(r"^const PHOTO_BAD = /(.*)/i;$", APP, re.M).group(1)
js_lic = re.search(r"^const PHOTO_LICENCE_OK = /(.*)/i;$", APP, re.M).group(1)
results.append(ok(picks.PHOTO_BAD.pattern == js_bad and picks.PHOTO_BAD.flags & re.I,
                  "picks.PHOTO_BAD is app.js PHOTO_BAD"))
results.append(ok(picks.LICENCE_OK.pattern == js_lic and picks.LICENCE_OK.flags & re.I,
                  "picks.LICENCE_OK is app.js PHOTO_LICENCE_OK"))
results.append(ok(picks._skip_files() == SKIP and len(SKIP) > 100,
                  "the skip list is public/photo-skip.json (%d files)" % len(SKIP)))
results.append(ok("a.gallery.slice(0, %d)" % picks.GALLERY_SHOWN in APP and picks.COVER_MIN_W == 800,
                  "candidates stop at the %d gallery entries the guide hero shows; originals from %dpx wide"
                  % (picks.GALLERY_SHOWN, picks.COVER_MIN_W)))

print("2. selection order, the override, pinned files, the memo")
saved = picks.cover, picks.cover_file
asked = []
PASS = set()


def stub_cover(q, width=1024, height=420):
    asked.append(("title", q))
    return {"url": "T:" + q, "credit": {"page": q}} if q in PASS else None


def stub_file(name, width=1024, height=420):
    asked.append(("file", name))
    return {"url": "F:" + name, "credit": {"page": name}} if ("File:" + name) in PASS else None


picks.cover, picks.cover_file = stub_cover, stub_file
try:
    def run(a, memo=None):
        del asked[:]
        c = picks.cover_for(a, memo)
        return c and c["url"], list(asked)

    g = ["G1", "G2", {"file": "P3.jpg", "label": "Place 3"}, "G4", "G5", "G6", "G7"]
    PASS.clear(); PASS.update({"G1", "G2"})
    results.append(ok(run({"gallery": g}) == ("T:G1", [("title", "G1")]),
                      "no override: the gallery's first entry, one lookup"))
    PASS.clear(); PASS.update({"G4"})
    results.append(ok(run({"gallery": g}) == ("T:G4", [("title", "G1"), ("title", "G2"), ("file", "P3.jpg"),
                                                       ("title", "G4")]),
                      "refused entries fall through in gallery order; a pinned entry goes to cover_file"))
    PASS.clear(); PASS.update({"File:P3.jpg"})
    results.append(ok(run({"gallery": g})[0] == "F:P3.jpg", "a pinned file that passes is the cover"))
    PASS.clear(); PASS.update({"G7"})
    c, seen = run({"photo": "OV", "gallery": g})
    results.append(ok(c is None and seen == [("title", "OV")] + [("title", "G1"), ("title", "G2"),
                                                                 ("file", "P3.jpg"), ("title", "G4"),
                                                                 ("title", "G5"), ("title", "G6")],
                      "never past the sixth gallery entry: %d lookups at most, None when all are refused"
                      % len(seen)))
    PASS.clear(); PASS.update({"OV", "G1"})
    results.append(ok(run({"photo": "OV", "gallery": g}) == ("T:OV", [("title", "OV")]),
                      "the override comes first, even with a gallery lead that passes"))
    PASS.clear(); PASS.update({"G1"})
    results.append(ok(run({"photo": "OV", "gallery": g}) == ("T:G1", [("title", "OV"), ("title", "G1")]),
                      "a refused override falls back to the gallery"))
    PASS.clear(); PASS.update({"G2"})
    results.append(ok(run({"photo": "G2", "gallery": g}) == ("T:G2", [("title", "G2")])
                      and run({"photo": "G4", "gallery": g})[1].count(("title", "G4")) == 1,
                      "an override that is also a gallery entry is looked up once"))
    PASS.clear()
    results.append(ok(run({"photo": "G4", "gallery": g}) == (None, [("title", "G4"), ("title", "G1"), ("title", "G2"),
                                                                ("file", "P3.jpg"), ("title", "G5"),
                                                                ("title", "G6")]),
                      "with nothing passing, an override the gallery repeats is still looked up once, first"))
    results.append(ok(run({}) == (None, []) and run({"photo": "", "gallery": []}) == (None, []),
                      "no photo and no gallery: no cover, no lookup"))

    # The memo: once a run, across countries and editions.
    PASS.clear(); PASS.update({"G2", "File:G1"})
    memo = {}
    first = run({"gallery": ["G1", "G2"]}, memo)
    again = run({"gallery": ["G1", "G2"]}, memo)
    other = run({"photo": "G1", "gallery": [{"file": "G1", "label": "x"}, "G2"]}, memo)
    results.append(ok(first == ("T:G2", [("title", "G1"), ("title", "G2")]) and again == ("T:G2", [])
                      and other == ("F:G1", [("file", "G1")]),
                      "the memo answers a candidate seen before (refused or not) with no lookup, and keys a "
                      "title apart from a pinned file of the same name"))
    results.append(ok(run({"gallery": ["G1", "G2"]})[1] == [("title", "G1"), ("title", "G2")],
                      "without a memo every call looks up again"))

    # build_variant's shared memo: ten editions featuring the same five
    # countries look each candidate up once.
    shared_memo = {}
    acts = {"AA": {"gallery": ["A1", "A2"]}, "BB": {"photo": "B0", "gallery": ["B1"]}}
    PASS.clear(); PASS.update({"A2", "B1"})
    del asked[:]
    for _edition in range(10):
        for iso in ("AA", "BB"):
            picks._enrich({"iso": iso}, acts, with_photo=True, memo=shared_memo)
    gem = picks._enrich({"iso": "AA"}, acts, with_photo=False, memo=shared_memo)
    results.append(ok(sorted(asked) == [("title", "A1"), ("title", "A2"), ("title", "B0"), ("title", "B1")]
                      and gem["photo"] is None,
                      "_enrich over ten editions: %d lookups for two countries' four candidates; a gem gets "
                      "no cover" % len(asked)))
finally:
    picks.cover, picks.cover_file = saved

print("3. each check, against a Wikipedia/Commons fixture")


def canon(name):
    """A title as MediaWiki normalises it: runs of spaces and underscores to
    one space, trimmed, first letter capitalised."""
    name = re.sub(r"[ _]+", " ", name).strip()
    return name[:1].upper() + name[1:]


class Wiki:
    """en.wikipedia pageimages (and REST summaries) by title, Commons imageinfo
    by file name."""

    def __init__(self):
        self.calls = []
        # title -> its free lead image URL (None: the page has none), what
        # pageimages names by default (pilicense=free)
        self.lead = {}
        # title -> a non-free lead image, which the REST summary and
        # pageimages with pilicense=any lead with instead
        self.nonfree = {}
        # canonical name (spaces) -> imageinfo
        self.files = {}

    def file(self, name, width=4000, short="CC BY-SA 4.0", code="cc-by-sa-4.0", artist="<a href='//x'>Jane Doe</a>"):
        self.files[canon(name)] = {"width": width, "short": short, "code": code, "artist": artist}

    def __call__(self, req, timeout=None, context=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.calls.append(url)
        u = urllib.parse.urlsplit(url)
        if u.netloc == "en.wikipedia.org" and u.path == "/w/api.php":
            q = urllib.parse.parse_qs(u.query)
            assert q["action"] == ["query"] and q["prop"] == ["pageimages"] and q["redirects"] == ["1"] \
                and {"original", "name"} <= set(q["piprop"][0].split("|")), url
            title = canon(q["titles"][0])
            if title == "Boom":
                raise urllib.error.HTTPError(url, 503, "down", {}, None)
            if title not in self.lead:
                return io.BytesIO(json.dumps({"query": {"pages": {"-1": {"ns": 0, "title": title,
                                                                         "missing": ""}}}}).encode())
            src = (self.nonfree.get(title) or self.lead[title]) if q.get("pilicense") == ["any"] else self.lead[title]
            page = {"pageid": 7, "ns": 0, "title": title}
            if src:
                path = urllib.parse.urlsplit(src).path.split("/")
                page["original"] = {"source": src + "?utm_source=en.wikipedia.org&utm_campaign=api"
                                    "&utm_content=original", "width": 4000, "height": 3000}
                page["pageimage"] = urllib.parse.unquote(path[-2] if "/thumb/" in src else path[-1])
            return io.BytesIO(json.dumps({"batchcomplete": "", "query": {"pages": {"7": page}}}).encode())
        if u.netloc == "en.wikipedia.org" and u.path.startswith("/api/rest_v1/page/summary/"):
            # Not what cover() asks since 2026-10-30; answered (with the
            # non-free lead where a page has one) so going back to it fails
            # the free-lead check rather than the fixture.
            title = canon(urllib.parse.unquote(u.path.rsplit("/", 1)[1]))
            if title not in self.lead:
                raise urllib.error.HTTPError(url, 404, "no page", {}, None)
            src = self.nonfree.get(title) or self.lead[title]
            body = {"type": "standard", "title": title}
            if src:
                body["originalimage"] = {"source": src, "width": 4000, "height": 3000}
            return io.BytesIO(json.dumps(body).encode())
        if u.netloc == "commons.wikimedia.org" and u.path == "/w/api.php":
            q = urllib.parse.parse_qs(u.query)
            assert q["prop"] == ["imageinfo"] and "url" in q["iiprop"][0] and "size" in q["iiprop"][0], url
            name = canon(q["titles"][0][len("File:"):])
            info = self.files.get(name)
            if not info:
                return io.BytesIO(json.dumps({"query": {"pages": {"-1": {"title": "File:" + name,
                                                                          "missing": ""}}}}).encode())
            enc = urllib.parse.quote(name.replace(" ", "_"))
            md = {"Artist": {"value": info["artist"]}, "LicenseShortName": {"value": info["short"]},
                  "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                  "License": {"value": info["code"]}}
            return io.BytesIO(json.dumps({"query": {"pages": {"7": {"title": "File:" + name, "imageinfo": [
                {"url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/" + enc, "width": info["width"],
                 "height": 600, "extmetadata": md}]}}}}).encode())
        raise AssertionError("unexpected request " + url)


def up(name):
    return "https://upload.wikimedia.org/wikipedia/commons/a/ab/" + urllib.parse.quote(name)


W = Wiki()
# A rejected file only the skip list refuses (a capitalised name PHOTO_BAD passes).
skipped = next(f for f in sorted(SKIP) if f[:1].isupper() and not picks.PHOTO_BAD.search(f))
W.lead.update({
    "Good": up("Good_view.jpg"),
    "Logo": up("Petronas_Towers_logo.jpg"),
    "Map": up("Malaysia_location_map.png"),
    "Svg": up("Taipei_101.svg"),
    "Skipped": up(skipped),
    "NC": up("Nc_photo.jpg"),
    "Gfdl": up("Gfdl_photo.jpg"),
    "CodeOnly": up("Code_only.jpg"),
    "Fair": "https://upload.wikimedia.org/wikipedia/en/a/ab/Poster_photo.jpg",
    "Bare": None,
    "Gone": up("Deleted_photo.jpg"),
    "Narrow": up("Narrow_photo.jpg"),
    "Edge": up("Edge_photo.jpg"),
    "Mid": up("Mid_photo.jpg"),
    "Big": up("Big_photo.jpg"),
    "Tiff": up("Scan_photo.tif"),
    "Thumbed": "https://thumb.wikimedia.org/wikipedia/commons/thumb/c/cd/Large_photo.jpg/3840px-Large_photo.jpg",
    "Igo": up("Igo_photo.jpg"),
    "Tower": up("Tower_photo.jpg"),
})
# France's Eiffel Tower on 2026-10-30: the REST summary led with the tower's
# logo, an en.wikipedia upload; pageimages names the Commons photo.
W.nonfree["Tower"] = "https://upload.wikimedia.org/wikipedia/en/b/ba/Tower_logo.svg"
W.file("Good_view.jpg", 3000)
W.file(skipped, 3000)
W.file("Nc_photo.jpg", short="CC BY-NC-SA 4.0", code="cc-by-nc-sa-4.0")
W.file("Gfdl_photo.jpg", short="GFDL", code="gfdl")
W.file("Code_only.jpg", short="Attribution-ShareAlike", code="cc-by-sa-3.0")
W.file("Narrow_photo.jpg", 799)
W.file("Edge_photo.jpg", 800)
W.file("Mid_photo.jpg", 1100)
W.file("Big_photo.jpg", 5000)
W.file("Scan_photo.tif", 6000)
W.file("Large_photo.jpg", 9000)
W.file("Plage de Roume.jpg", 2048, artist="<a href='https://commons.wikimedia.org/wiki/User:Someone'>Some One</a>")
W.file("Under par.jpg", 640)
W.file("Odd licence.jpg", short="FAL", code="fal")
# Virunga National Park-107997.jpg's licence: a short name the list takes, no code.
W.file("Igo_photo.jpg", short="CC BY-SA 3.0 igo", code="")
W.file("Tower_photo.jpg", 2900)

real_urlopen = urllib.request.urlopen
urllib.request.urlopen = W
try:
    def look(title):
        n = len(W.calls)
        c = picks.cover(title)
        return c, [u.split("/")[2] for u in W.calls[n:]]

    def lookf(name):
        n = len(W.calls)
        c = picks.cover_file(name)
        return c, [u.split("/")[2] for u in W.calls[n:]]

    c, hosts = look("Good")
    thumb = "thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Good_view.jpg/1280px-Good_view.jpg"
    want_url = ("https://images.weserv.nl/?url=" + urllib.parse.quote("ssl:" + thumb, safe="")
                + "&w=1024&h=420&fit=cover&a=attention&output=jpg&q=80")
    results.append(ok(c == {"url": want_url, "credit": {
        "artist": "Jane Doe", "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
        "page": "https://commons.wikimedia.org/wiki/File%3AGood_view.jpg"}}
        and hosts == ["en.wikipedia.org", "commons.wikimedia.org"],
        "a title that passes: two requests, a weserv banner of the 1280px thumbnail, the credit"))
    refused = {}
    for t in ("Logo", "Map", "Svg", "Skipped", "Fair", "Bare", "Missing page", "Boom"):
        refused[t] = look(t)
    results.append(ok(all(refused[t] == (None, ["en.wikipedia.org"]) for t in refused),
                      "refused on the page's lead image alone, Commons never asked: PHOTO_BAD (a logo, a locator map, "
                      "an .svg), the skip list, an en.wikipedia-hosted image, no lead image, no page, a failed "
                      "request -> %s" % {t: v[0] for t, v in refused.items() if v != (None, ["en.wikipedia.org"])}))
    results.append(ok(look("NC")[0] is None and look("Gfdl")[0] is None and lookf("Odd licence.jpg")[0] is None,
                      "a licence outside the site's: NC, GFDL-only, FAL"))
    results.append(ok(look("CodeOnly")[0] is not None,
                      "a short name the regex misses passes on its code (cc-by-sa-3.0), as on the site"))
    results.append(ok(look("Igo")[0] is not None,
                      "a short name the list takes passes with no code ('CC BY-SA 3.0 igo', as Virunga's)"))
    c, hosts = look("Tower")
    results.append(ok(c and "Tower_photo.jpg%2F1280px-Tower_photo.jpg" in c["url"]
                      and hosts == ["en.wikipedia.org", "commons.wikimedia.org"]
                      and "pilicense" not in W.calls[-2] and "/w/api.php" in W.calls[-2],
                      "a page whose any-licence lead is an en.wikipedia logo gives its free Commons lead, as the "
                      "guide hero does (France's Eiffel Tower): pageimages, no pilicense"))
    results.append(ok(look("Gone")[0] is None, "a lead image Commons has no record of"))
    edge, mid, big = look("Edge")[0], look("Mid")[0], look("Big")[0]
    results.append(ok(look("Narrow")[0] is None and lookf("Under par.jpg")[0] is None
                      and "%2F500px-Edge_photo.jpg" in edge["url"] and "%2F960px-Mid_photo.jpg" in mid["url"]
                      and "%2F1280px-Big_photo.jpg" in big["url"],
                      "the 800px floor: 799 refused, 800 gets the 500px thumbnail, 1100 the 960px, 5000 the 1280px"))
    results.append(ok(look("Tiff")[0] is None,
                      "a .tif original passes every other check but has no same-name thumbnail: refused, so "
                      "weserv is never handed an original"))
    th = look("Thumbed")[0]
    results.append(ok(th and "%2F1280px-Large_photo.jpg" in th["url"] and "3840px" not in th["url"],
                      "a lead image given as a thumbnail resolves to its original's file (pageimage)"))
    c, hosts = lookf("Plage de Roume.jpg")
    results.append(ok(c and hosts == ["commons.wikimedia.org"]
                      and c["credit"]["page"] == "https://commons.wikimedia.org/wiki/File%3APlage_de_Roume.jpg"
                      and c["credit"]["artist"] == "Some One"
                      and "Plage_de_Roume.jpg%2F1280px-Plage_de_Roume.jpg" in c["url"],
                      "a pinned file: one Commons request, the same checks, credited under its canonical name"))
    lower = skipped[:1].lower() + skipped[1:].replace("_", " ")
    results.append(ok(lookf(lower) == (None, [])
                      and lookf("Sierra Leone location map.jpg") == (None, []) and lookf("") == (None, []),
                      "a pinned name the skip list holds (as written: %r) or PHOTO_BAD refuses costs no request"
                      % lower))
    # MediaWiki collapses a run of spaces or underscores: a name written with
    # two is a different key until Commons spells it.
    doubled = skipped.replace("_", "__", 1)
    results.append(ok(picks._file_key(doubled) not in SKIP and lookf(doubled) == (None, ["commons.wikimedia.org"]),
                      "a pinned name the skip list holds only in Commons' spelling (%r) is refused after its one "
                      "request" % doubled))
finally:
    urllib.request.urlopen = real_urlopen

print("4. the data")
OVERRIDES = {"DJ", "FK", "GL", "GQ", "MW", "PY", "TG", "UG", "MY", "GB", "RO", "PT"}
with_photo = {iso for iso, a in ACTS.items() if "photo" in a}
results.append(ok(with_photo == OVERRIDES,
                  "`photo` is left on exactly the %d override countries%s"
                  % (len(OVERRIDES), "" if with_photo == OVERRIDES else " (got %s)" % sorted(with_photo ^ OVERRIDES))))
odd = [iso for iso in with_photo if ACTS[iso]["photo"] not in (ACTS[iso].get("gallery") or [])[:picks.GALLERY_SHOWN]]
DOUG = {"MY": "Batu Caves", "GB": "Tower Bridge", "RO": "Bran Castle", "PT": "Pena Palace"}
results.append(ok(not odd and all(ACTS[iso]["photo"] == t for iso, t in DOUG.items()),
                  "each override is a photo of its own guide gallery (Doug's picks: Malaysia's Batu Caves, the UK's "
                  "Tower Bridge, Romania's Bran Castle, Portugal's Pena Palace)%s"
                  % (" -> %s" % odd if odd else "")))
fn = APP[APP.index("function photoSubjects(iso)"):]
fn = fn[:fn.index("\n}\n")]
reads = re.findall(r"\ba\.photo\b", APP)
results.append(ok(all(isinstance(a.get("gallery"), list) and a["gallery"] for a in ACTS.values())
                  and "if (a && Array.isArray(a.gallery) && a.gallery.length) return a.gallery.slice(0, 6);" in fn
                  and fn.index("a.gallery.slice(0, 6)") < fn.index("a.photo") and len(reads) == 2,
                  "app.js reads `photo` only for a country with no gallery (photoSubjects), and all %d have one"
                  % len(ACTS)))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)

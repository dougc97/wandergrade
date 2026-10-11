#!/usr/bin/env python3
"""Build public/og-images.json: ISO -> a 1200px-wide hero photo URL for each
country's social-share preview (og:image on /guide/<slug> pages).

Uses the first curated gallery subject that resolves to a real photo via the
Wikipedia pageimages API (same source + PHOTO_BAD filter as the site's hero
carousel); a gallery's pinned Commons file ({"file", "label"},
scripts/gallery_entry.py) resolves through Commons imageinfo, under the
site's licence rule too. Run from the repo root with /usr/bin/python3;
re-run whenever galleries change. Network: ~190 requests, a minute or two.

--missing keeps every existing entry and fetches only countries absent from
og-images.json (e.g. newly added guides) — a few requests instead of ~190.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import gallery_entry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
PHOTO_BAD = re.compile(
    r"map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram"
    r"|\.svg|location|adm[_ ]|administrative|emblem|wikidata|collage|montage", re.I)


def _skip():
    """Lead images the 2026-10 photo sweep rejected (public/photo-skip.json);
    the hero carousel skips them too (app.js photoSkip)."""
    try:
        with open(os.path.join(PUBLIC, "photo-skip.json"), encoding="utf-8") as f:
            return set(json.load(f).get("files") or [])
    except (OSError, ValueError):
        return set()


SKIP = _skip()
UA = "wandergrade-og/1.0 (+https://wandergrade.com)"


def file_thumb(entry):
    """A pinned Commons file's 1200px thumb, on app.js commonsPhoto()'s terms."""
    name = entry.get("file") or ""
    if PHOTO_BAD.search(name):
        return None
    try:
        info = gallery_entry.commons_file(name, 1200, UA)
    except Exception:
        return None
    if (not info["thumb"] or info["file"] in SKIP or PHOTO_BAD.search(info["thumb"])
            or not gallery_entry.licence_ok(info["lic"], info["code"])):
        return None
    return info["thumb"] if (info["tw"] >= 700 or info["th"] >= 500) else None


def thumb(subject):
    if gallery_entry.is_file(subject):
        return file_thumb(subject)
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
           "&prop=pageimages&piprop=thumbnail|name&pithumbsize=1200&redirects=1"
           "&titles=" + urllib.parse.quote(subject))
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        j = json.load(urllib.request.urlopen(req, timeout=20))
        page = next(iter(j.get("query", {}).get("pages", {}).values()))
        if page.get("pageimage") in SKIP:
            return None
        th = page.get("thumbnail", {})
        # The API now tacks utm_* tracking params onto thumb URLs; store it clean.
        t = (th.get("source") or "").split("?")[0] or None
        # size gate: a small delivered thumb means a tiny source file
        if t and not PHOTO_BAD.search(t) and (th.get("width", 0) >= 700 or th.get("height", 0) >= 500):
            return t
    except Exception:
        return None
    return None


def main():
    acts = json.load(open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8"))
    out, misses = {}, []
    if "--missing" in sys.argv[1:]:
        try:
            with open(os.path.join(PUBLIC, "og-images.json"), encoding="utf-8") as f:
                out = json.load(f)
        except OSError:
            out = {}
    for iso in sorted(acts):
        if iso in out:
            continue
        url = None
        for subject in (acts[iso].get("gallery") or [])[:3]:
            url = thumb(subject)
            if url is None:
                time.sleep(1)
                url = thumb(subject)   # one retry for transient errors
            if url:
                break
        if url:
            out[iso] = url
        else:
            misses.append(iso)
        sys.stdout.write(".")
        sys.stdout.flush()
    with open(os.path.join(PUBLIC, "og-images.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    print("\nwrote %d/%d og images; misses: %s" % (len(out), len(acts), misses))


if __name__ == "__main__":
    main()
